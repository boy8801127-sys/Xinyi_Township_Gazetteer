# -*- coding: utf-8 -*-
"""摘要與內文的語意段落匯出工具（v2：句號切分＋標題合併策略）。"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Literal

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover
    fitz = None

from . import config
from .extract_pdf import _decode_filename, list_papers


Section = Literal["摘要", "內文"]

# ---------------------------------------------------------------------------
# 工具函式
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return text.replace(" ", "").replace("\u3000", "")


def _matches_any(text: str, keywords: tuple[str, ...]) -> bool:
    norm = _normalize(text)
    return any(k in norm for k in keywords)


def _is_abstract_start(text: str) -> bool:
    return _matches_any(text, config.ABSTRACT_START_KEYWORDS)


def _is_abstract_end(text: str) -> bool:
    return _matches_any(text, config.ABSTRACT_END_KEYWORDS)


def _is_body_start(text: str) -> bool:
    return _matches_any(text, config.BODY_START_KEYWORDS)


def _is_body_end(text: str) -> bool:
    return _matches_any(text, config.BODY_END_KEYWORDS)


_ROMAN_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)
_TOC_DOTS_RE = re.compile(r"\.{5,}")
_FIGURE_TITLE_RE = re.compile(r"^(圖|表)\s*\d+([－\-]\d+)?")
_STANDALONE_NUM_RE = re.compile(r"^\d{1,3}$")

_SECTION_HEADING_RE = re.compile(
    r"^("
    r"第[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾\d]+[章節]"
    r"|[壹貳參肆伍陸柒捌玖拾]+[、．.]"
    r"|[一二三四五六七八九十]+[、．.]"
    r"|（[一二三四五六七八九十\d]+）"
    r"|\([一二三四五六七八九十\d]+\)"
    r")"
)

_ABSTRACT_HEADING_RE = re.compile(
    rf"^({'|'.join(map(re.escape, config.PARAGRAPH_HEADING_KEYWORDS))})[：:]"
)

# 章節截斷 regex：模組層級編譯一次，避免每句重複編譯
_SECTION_BREAK_RE = re.compile(
    "|".join(f"({p})" for p in config.SECTION_BREAK_PATTERNS)
)


def _is_noise_line(text: str) -> bool:
    norm = _normalize(text)
    if not norm:
        return True
    if _STANDALONE_NUM_RE.match(norm):
        return True
    if len(norm) <= 3 and _ROMAN_RE.match(norm):
        return True
    return False


def _looks_like_toc_line(text: str) -> bool:
    if _TOC_DOTS_RE.search(text):
        return True
    if "……" in text or "..." in text:
        return True
    return False


def _is_figure_or_table_title(text: str) -> bool:
    norm = text.strip()
    if not norm:
        return False
    return bool(_FIGURE_TITLE_RE.match(norm))


def _is_table_data_line(text: str) -> bool:
    """偵測表格資料行：數字與空白佔比高、缺少完整句子標誌。"""
    stripped = text.strip()
    if not stripped or len(stripped) < 5:
        return False
    if "。" in stripped:
        return False
    digit_space_count = sum(1 for c in stripped if c.isdigit() or c == " " or c == "\u3000")
    ratio = digit_space_count / len(stripped)
    if ratio > 0.50 and len(stripped) > 20:
        return True
    return False


def _should_skip_line(text: str) -> bool:
    return (
        _is_noise_line(text)
        or _looks_like_toc_line(text)
        or _is_figure_or_table_title(text)
        or _is_table_data_line(text)
    )


def _is_section_heading(text: str) -> bool:
    norm = _normalize(text)
    return bool(_SECTION_HEADING_RE.match(norm))


def _is_abstract_heading(text: str) -> bool:
    norm = _normalize(text)
    return bool(_ABSTRACT_HEADING_RE.match(norm))


def _strip_leading_page_number(text: str) -> str:
    """移除行首的頁碼數字（1~3 位數字＋空白＋後面有中文）。"""
    m = re.match(r"^(\d{1,3})\s+([\u4e00-\u9fff].*)$", text.strip())
    if not m:
        return text
    body = m.group(2)
    if body and body[0] in "年月日個位次名歲天":
        return text
    return body


def _norm_to_text_positions(text: str) -> list[int]:
    """norm 每個字元對應的 text 起始位置（norm 為移除空格後的 text）。"""
    norm = _normalize(text)
    positions: list[int] = []
    j = 0
    for _ in range(len(norm)):
        while j < len(text) and text[j] in " \u3000":
            j += 1
        if j < len(text):
            positions.append(j)
            j += 1
    positions.append(len(text))
    return positions


_HEADER_PREFIX_RE = re.compile(
    r"^第[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾\d]+[章節]"
)
# 避免 [\u4e00-\u9fff]{0,10} 造成災難性回溯，改為單字元匹配
_HEADER_ONLY_RE = re.compile(
    r"^第[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾\d]+[章節]"
    r"(?:[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾\d、．.（）()\u4e00-\u9fff])*$"
)


def _is_header_only_paragraph(text: str, norm: str | None = None) -> bool:
    """段落是否僅含第、章、節結構（章節標題），無實質正文，應與下段合併。"""
    if norm is None:
        norm = _normalize(text)
    if len(norm) < 2:
        return False
    if not _HEADER_PREFIX_RE.match(norm):
        return False
    return bool(_HEADER_ONLY_RE.match(norm))


def _merge_short_and_header_paragraphs(
    paragraphs: list[dict[str, Any]], min_len: int | None = None
) -> list[dict[str, Any]]:
    """過短或純章節標題段落與下一段合併（同區段內）。"""
    min_len = min_len if min_len is not None else config.MIN_PARAGRAPH_LENGTH
    result: list[dict[str, Any]] = []
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        text = (p.get("段落") or "").strip()
        norm = _normalize(text)
        section = p.get("區段", "")
        should_merge = (
            len(norm) < min_len or _is_header_only_paragraph(text, norm)
        )
        if should_merge and i + 1 < len(paragraphs):
            next_p = paragraphs[i + 1]
            if next_p.get("區段") != section:
                result.append(p)
                i += 1
                continue
            merged_text = text + "。" + (next_p.get("段落") or "").strip()
            result.append({
                **p,
                "段落": merged_text,
                "結束頁": next_p.get("結束頁", p.get("結束頁")),
            })
            i += 2
        else:
            result.append(p)
            i += 1
    return result


_SENTENCE_END_RE = re.compile(r"(。|\.|．)")


def _split_long_paragraph_by_sentence(
    text: str, max_len: int | None = None
) -> list[str]:
    """
    若段落超過 max_len 字，依句號（。、.、．）切分為多段，每段 ≤ max_len。
    """
    max_len = max_len if max_len is not None else config.MAX_PARAGRAPH_LENGTH
    text = (text or "").strip()
    if not text or len(text) <= max_len:
        return [text] if text else []

    def _split_long_sentence(long_s: str) -> list[str]:
        """單句超過 max_len 時，依 ，； 再切為小段。"""
        sub_parts = re.split(r"([，；])", long_s)
        subs: list[str] = []
        i = 0
        while i < len(sub_parts):
            s = sub_parts[i]
            if i + 1 < len(sub_parts) and sub_parts[i + 1] in ("，", "；"):
                s += sub_parts[i + 1]
                i += 2
            else:
                i += 1
            if s.strip():
                subs.append(s)
        return subs

    parts = _SENTENCE_END_RE.split(text)
    sentences: list[str] = []
    i = 0
    while i < len(parts):
        s = parts[i]
        if i + 1 < len(parts) and parts[i + 1] in ("。", ".", "．"):
            s += parts[i + 1]
            i += 2
        else:
            i += 1
        if s.strip():
            if len(s) > max_len:
                sentences.extend(_split_long_sentence(s))
            else:
                sentences.append(s)

    chunks: list[str] = []
    current = ""
    for s in sentences:
        if current and len(current) + len(s) > max_len:
            chunks.append(current)
            current = s
        else:
            current = (current + s) if current else s
    if current:
        chunks.append(current)

    final: list[str] = []
    for c in chunks:
        while len(c) > max_len:
            final.append(c[:max_len])
            c = c[max_len:]
        if c:
            final.append(c)
    return final


def _split_by_section_patterns(text: str) -> list[str]:
    """依章節標題 pattern 將文字切成多個子段。回傳區段字串列表。"""
    return [c for c, _, _ in _split_by_section_patterns_with_positions(text)]


def _split_by_section_patterns_with_positions(text: str) -> list[tuple[str, int, int]]:
    """
    依章節標題 pattern 將文字切成多個子段。
    回傳 [(chunk, start_pos, end_pos), ...]，start/end 為在 text 中的字元位置。
    """
    if not text or not text.strip():
        return [(text, 0, len(text))] if text else []
    norm = _normalize(text)
    matches = list(_SECTION_BREAK_RE.finditer(norm))
    if not matches:
        return [(text, 0, len(text))]
    positions = _norm_to_text_positions(text)

    def norm_pos_to_text(norm_pos: int) -> int:
        return positions[norm_pos] if norm_pos < len(positions) else len(text)

    result: list[tuple[str, int, int]] = []
    first_end = norm_pos_to_text(matches[0].start())
    if first_end > 0:
        first_chunk = text[:first_end].strip()
        if first_chunk:
            result.append((first_chunk, 0, first_end))
    for i, m in enumerate(matches):
        start = norm_pos_to_text(m.start())
        end = norm_pos_to_text(matches[i + 1].start()) if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            result.append((chunk, start, end))
    return result if result else [(text, 0, len(text))]


# ---------------------------------------------------------------------------
# PDF 行擷取
# ---------------------------------------------------------------------------

def _iter_page_lines(doc: "fitz.Document", show_progress: bool = False) -> list[dict[str, Any]]:
    if fitz is None:
        raise RuntimeError("請安裝 PyMuPDF：pip install PyMuPDF")
    lines: list[dict[str, Any]] = []
    total_pages = len(doc)
    for page_index in range(total_pages):
        if show_progress and total_pages > 10:
            if page_index % 10 == 0 or page_index == total_pages - 1:
                print(f"    頁 {page_index + 1}/{total_pages}", flush=True)
        page = doc.load_page(page_index)
        try:
            blocks = page.get_text("dict")["blocks"]
        except Exception:
            text = page.get_text().strip()
            if text:
                for raw_line in text.splitlines():
                    t = raw_line.strip()
                    if t:
                        lines.append({"page": page_index + 1, "text": t})
            continue

        page_lines: list[dict[str, Any]] = []
        for block in blocks:
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                texts = []
                for span in spans:
                    t = span.get("text", "")
                    if t:
                        texts.append(t)
                line_text = "".join(texts).strip()
                if line_text:
                    page_lines.append({"page": page_index + 1, "text": line_text})
        lines.extend(page_lines)
    return lines


# ---------------------------------------------------------------------------
# 核心：三步驟段落擷取
# ---------------------------------------------------------------------------

def extract_paragraphs_from_pdf(pdf_path: Path, show_progress: bool = False) -> list[dict[str, Any]]:
    """
    從單一 PDF 擷取語意段落。

    策略（無狀態機）：
    1. 擷取所有行 → 過濾雜訊 → 遇參考文獻停止
    2. 章節切分（先於切句）
    3. 切句（依句號）
    4. 過長段落再切分
    5. 合併短段（最後）
    """
    if fitz is None:
        raise RuntimeError("請安裝 PyMuPDF：pip install PyMuPDF")

    doc = fitz.open(pdf_path)
    try:
        if show_progress:
            print(f"    擷取文字…", flush=True)
        all_lines = _iter_page_lines(doc, show_progress)
    finally:
        doc.close()

    if not all_lines:
        return []

    if show_progress:
        print(f"    分析段落…", flush=True)

    # --- Step 1: 收集乾淨行（無狀態機，遇參考文獻停止；遇摘要/緒論開始收集） ---
    lines_with_pages: list[tuple[str, int]] = []
    collecting = False
    for line_info in all_lines:
        page = line_info["page"]
        text = line_info["text"].strip()
        if not text:
            continue
        if _should_skip_line(text):
            continue
        text = _strip_leading_page_number(text)
        if not text.strip():
            continue
        text = text.strip()
        norm = _normalize(text)
        if _is_body_end(norm):
            break
        if not collecting and (_is_abstract_start(norm) or _is_body_start(norm)):
            collecting = True
        if collecting:
            lines_with_pages.append((text, page))

    if not lines_with_pages:
        return []

    # --- Step 2: 合併成連續文字，建立頁邊界 ---
    merged_text = ""
    page_boundaries: list[tuple[int, int]] = []  # (char_start, page)
    for text, pg in lines_with_pages:
        start_pos = len(merged_text)
        if merged_text and not merged_text.endswith(" "):
            merged_text += " "
            start_pos = len(merged_text)
        merged_text += text
        page_boundaries.append((start_pos, pg))

    def _page_at_pos(pos: int) -> int:
        result_page = page_boundaries[0][1]
        for bp_start, bp_page in page_boundaries:
            if bp_start <= pos:
                result_page = bp_page
            else:
                break
        return result_page

    # --- Step 3: 章節切分（早於切句） ---
    section_chunks = _split_by_section_patterns_with_positions(merged_text)

    # --- Step 4: 切句（依句號），並合併成段落 ---
    paragraphs: list[dict[str, Any]] = []
    for chunk, chunk_start, chunk_end in section_chunks:
        if not chunk.strip():
            continue
        start_page = _page_at_pos(chunk_start)
        end_page = _page_at_pos(max(chunk_start, chunk_end - 1))
        parts = re.split(r"(。|\.|．)", chunk)
        current = ""
        sent_start = chunk_start
        for i, part in enumerate(parts):
            if part in ("。", ".", "．"):
                current += part
                s = current.strip()
                if s:
                    sp = _page_at_pos(sent_start)
                    ep = _page_at_pos(sent_start + len(s) - 1)
                    paragraphs.append({
                        "區段": "內文",
                        "段落": s,
                        "起始頁": sp,
                        "結束頁": ep,
                    })
                sent_start = chunk_start + sum(len(p) for p in parts[: i + 1])
                current = ""
            else:
                current += part
        leftover = current.strip()
        if leftover:
            sp = _page_at_pos(sent_start)
            ep = _page_at_pos(min(chunk_end, sent_start + len(leftover) - 1))
            paragraphs.append({
                "區段": "內文",
                "段落": leftover,
                "起始頁": sp,
                "結束頁": ep,
            })

    # --- Step 5: 過長段落依句號再切分 ---
    expanded: list[dict[str, Any]] = []
    for p in paragraphs:
        para = p.get("段落", "")
        chunks = _split_long_paragraph_by_sentence(
            para, max_len=config.MAX_PARAGRAPH_LENGTH
        )
        for chunk in chunks:
            expanded.append({**p, "段落": chunk})

    # --- Step 6: 合併短段（最後） ---
    expanded = _merge_short_and_header_paragraphs(
        expanded, min_len=config.MIN_PARAGRAPH_LENGTH
    )

    if show_progress:
        print(f"    完成，共 {len(expanded)} 段", flush=True)
    return expanded


# ---------------------------------------------------------------------------
# 對整個 paper 目錄執行
# ---------------------------------------------------------------------------

def run_on_paper_dir_for_paragraphs(
    paper_dir: Path | None = None,
    max_pdfs: int | None = None,
) -> list[dict[str, Any]]:
    from .export_paragraphs_v1 import extract_paragraphs_from_pdf as extract_v1

    d = paper_dir or config.PAPER_DIR
    pdfs = list_papers(d)
    if max_pdfs is not None:
        pdfs = pdfs[:max_pdfs]
    all_rows: list[dict[str, Any]] = []
    total = len(pdfs)
    for i, pdf_path in enumerate(pdfs):
        if total > 1:
            print(f"  處理中 {i + 1}/{total}: {pdf_path.name}", flush=True)
        source = _decode_filename(pdf_path)
        show_progress = total > 1
        for para in extract_v1(pdf_path, show_progress=show_progress):
            row = dict(para)
            row["來源文章"] = source
            all_rows.append(row)
    return all_rows


# ---------------------------------------------------------------------------
# CSV 匯出
# ---------------------------------------------------------------------------

_PAPER_INDEX_RE = re.compile(r"^0*(\d+)")


def _get_paper_index_from_source_name(name: str, fallback_index: int) -> int:
    m = _PAPER_INDEX_RE.match(name)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return fallback_index
    return fallback_index


def _sanitize_filename(name: str) -> str:
    for c in '\\/:*?"<>|':
        name = name.replace(c, "_")
    name = name.strip() or "未命名"
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    if not name.lower().endswith(".csv"):
        name = name + ".csv"
    return name


def _make_page_str(start_page: Any, end_page: Any) -> str:
    if start_page and end_page and start_page != end_page:
        return f"{start_page}–{end_page}"
    return str(start_page or "")


def _remove_paragraph_spaces(text: str) -> str:
    """移除段落內 PDF 產生的多餘空格：全形空格、中文間空格、連續空格。保留英文片語內空格。"""
    if not text:
        return ""
    # 全形空格一律移除
    text = text.replace("\u3000", "")
    # 移除兩個中文字之間的空格（PDF 常見斷行產物）
    text = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", text)
    # 移除中文與標點之間的多餘空格
    text = re.sub(r"([\u4e00-\u9fff、，。；：])\s+", r"\1", text)
    text = re.sub(r"\s+([\u4e00-\u9fff、，。；：])", r"\1", text)
    # 將連續多個半形空格壓成一個（保留英文片語內單一空格）
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def export_paragraphs_all(rows: list[dict[str, Any]], output_dir: Path | None = None) -> Path:
    base_dir = output_dir or config.OUTPUT_DIR
    base_dir.mkdir(parents=True, exist_ok=True)
    out_path = base_dir / "paragraphs_all.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["ID", "段落", "來源文章", "頁數"],
            extrasaction="ignore",
        )
        writer.writeheader()

        by_source: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for r in rows:
            src = (r.get("來源文章") or "").strip() or "未命名"
            if src not in by_source:
                by_source[src] = []
                order.append(src)
            by_source[src].append(r)

        fallback_counter = 1
        for src in order:
            paper_index = _get_paper_index_from_source_name(src, fallback_counter)
            if not _PAPER_INDEX_RE.match(src):
                fallback_counter += 1
            para_idx = 1
            for r in by_source[src]:
                pid = f"P{paper_index}-{para_idx}"
                para_idx += 1
                writer.writerow({
                    "ID": pid,
                    "段落": _remove_paragraph_spaces(r.get("段落", "")),
                    "來源文章": src,
                    "頁數": _make_page_str(r.get("起始頁"), r.get("結束頁")),
                })
    return out_path


def export_paragraphs_by_paper(rows: list[dict[str, Any]], output_dir: Path | None = None) -> list[Path]:
    base_dir = output_dir or config.OUTPUT_DIR
    target_dir = base_dir / "paragraphs_by_paper"
    target_dir.mkdir(parents=True, exist_ok=True)

    by_source: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        src = (r.get("來源文章") or "").strip() or "未命名"
        by_source.setdefault(src, []).append(r)

    paths: list[Path] = []
    for src, sub in by_source.items():
        fname = _sanitize_filename(src)
        out_path = target_dir / fname
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["ID", "段落", "來源文章", "頁數"],
                extrasaction="ignore",
            )
            writer.writeheader()

            paper_index = _get_paper_index_from_source_name(src, 1)
            para_idx = 1
            for r in sub:
                pid = f"P{paper_index}-{para_idx}"
                para_idx += 1
                writer.writerow({
                    "ID": pid,
                    "段落": _remove_paragraph_spaces(r.get("段落", "")),
                    "來源文章": src,
                    "頁數": _make_page_str(r.get("起始頁"), r.get("結束頁")),
                })
        paths.append(out_path)
    return paths


if __name__ == "__main__":
    import sys

    try:
        rows = run_on_paper_dir_for_paragraphs(max_pdfs=1)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    if not rows:
        print("無段落可匯出（paper/ 可能沒有 PDF）", file=sys.stderr)
        sys.exit(1)
    all_path = export_paragraphs_all(rows, config.OUTPUT_DIR)
    by_paths = export_paragraphs_by_paper(rows, config.OUTPUT_DIR)
    print(f"已匯出全部段落：{all_path}")
    for p in by_paths:
        print(f"已匯出論文段落檔：{p}")
