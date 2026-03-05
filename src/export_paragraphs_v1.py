# -*- coding: utf-8 -*-
"""摘要與內文的語意段落匯出工具（v1：原工作流，狀態機＋切句→章節切分→合併短段→過長切分）。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover
    fitz = None

from . import config

Section = Literal["摘要", "內文"]


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

_SECTION_BREAK_RE = re.compile(
    "|".join(f"({p})" for p in config.SECTION_BREAK_PATTERNS)
)

_HEADER_PREFIX_RE = re.compile(
    r"^第[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾\d]+[章節]"
)
# 避免 [\u4e00-\u9fff]{0,10} 造成災難性回溯，改為單字元匹配
_HEADER_ONLY_RE = re.compile(
    r"^第[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾\d]+[章節]"
    r"(?:[一二三四五六七八九十壹貳參肆伍陸柒捌玖拾\d、．.（）()\u4e00-\u9fff])*$"
)

_SENTENCE_END_RE = re.compile(r"(。|\.|．)")


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
    stripped = text.strip()
    if not stripped or len(stripped) < 5:
        return False
    if "。" in stripped:
        return False
    digit_space_count = sum(1 for c in stripped if c.isdigit() or c == " " or c == "\u3000")
    if digit_space_count / len(stripped) > 0.50 and len(stripped) > 20:
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
    m = re.match(r"^(\d{1,3})\s+([\u4e00-\u9fff].*)$", text.strip())
    if not m:
        return text
    body = m.group(2)
    if body and body[0] in "年月日個位次名歲天":
        return text
    return body


def _norm_to_text_positions(text: str) -> list[int]:
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


def _is_header_only_paragraph(text: str, norm: str | None = None) -> bool:
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
    min_len = min_len if min_len is not None else config.MIN_PARAGRAPH_LENGTH
    result: list[dict[str, Any]] = []
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        text = (p.get("段落") or "").strip()
        norm = _normalize(text)
        section = p.get("區段", "")
        should_merge = len(norm) < min_len or _is_header_only_paragraph(text, norm)
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


def _split_long_paragraph_by_sentence(
    text: str, max_len: int | None = None
) -> list[str]:
    max_len = max_len if max_len is not None else config.MAX_PARAGRAPH_LENGTH
    text = (text or "").strip()
    if not text or len(text) <= max_len:
        return [text] if text else []

    def _split_long_sentence(long_s: str) -> list[str]:
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
    if not text or not text.strip():
        return [text] if text else []
    norm = _normalize(text)
    matches = list(_SECTION_BREAK_RE.finditer(norm))
    if not matches:
        return [text]
    positions = _norm_to_text_positions(text)

    def norm_pos_to_text(norm_pos: int) -> int:
        return positions[norm_pos] if norm_pos < len(positions) else len(text)

    chunks: list[str] = []
    for i, m in enumerate(matches):
        start = norm_pos_to_text(m.start())
        end = norm_pos_to_text(matches[i + 1].start()) if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
    first_end = norm_pos_to_text(matches[0].start())
    if first_end > 0:
        first_chunk = text[:first_end].strip()
        if first_chunk:
            chunks.insert(0, first_chunk)
    return chunks if chunks else [text]


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


def _split_by_period(lines_with_pages: list[tuple[str, int]]) -> list[tuple[str, int, int]]:
    """合併所有行成連續文字，以。切分，回傳 (句子, 起始頁, 結束頁)。"""
    if not lines_with_pages:
        return []

    merged_text = ""
    page_boundaries: list[tuple[int, int]] = []

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

    sentences: list[tuple[str, int, int]] = []
    parts = re.split(r"(。|\.|．)", merged_text)

    current_sentence = ""
    sentence_start_pos = 0
    pos = 0

    for part in parts:
        if part in ("。", ".", "．"):
            current_sentence += part
            s = current_sentence.strip()
            if s:
                start_pg = _page_at_pos(sentence_start_pos)
                end_pg = _page_at_pos(pos + len(part) - 1)
                sentences.append((s, start_pg, end_pg))
            pos += len(part)
            current_sentence = ""
            sentence_start_pos = pos
        else:
            current_sentence += part
            pos += len(part)

    leftover = current_sentence.strip()
    if leftover:
        start_pg = _page_at_pos(sentence_start_pos)
        end_pg = _page_at_pos(max(0, pos - 1))
        sentences.append((leftover, start_pg, end_pg))

    return sentences


def extract_paragraphs_from_pdf(pdf_path: Path, show_progress: bool = False) -> list[dict[str, Any]]:
    """
    從單一 PDF 擷取「摘要＋內文」的語意段落。

    策略（原工作流）：
    1. 擷取所有行 → 過濾雜訊 → 狀態機收集摘要/內文行
    2. 切句（依句號）
    3. 摘要：依 _is_abstract_heading 分段；內文：每句章節切分，迴圈內合併成段落
    4. 合併短段
    5. 過長段落再切分
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

    # --- Step 1: 狀態機收集摘要/內文的「乾淨行」 ---
    state = "before_abstract"
    section_lines: list[tuple[Section, str, int]] = []

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

        if state == "in_body" and _is_body_end(norm):
            state = "after_body"
            continue

        if state == "before_abstract" and _is_abstract_start(norm):
            state = "in_abstract"
        elif state == "in_abstract" and _is_abstract_end(norm):
            state = "after_abstract_before_body"
            continue
        elif state in ("before_abstract", "after_abstract_before_body") and _is_body_start(norm):
            state = "in_body"

        if state == "in_abstract":
            section_lines.append(("摘要", text, page))
        elif state == "in_body":
            section_lines.append(("內文", text, page))

    if not section_lines:
        return []

    # --- Step 2 & 3: 切句 → 依標題合併成段落 ---
    abstract_lines = [(t, p) for sec, t, p in section_lines if sec == "摘要"]
    body_lines = [(t, p) for sec, t, p in section_lines if sec == "內文"]

    paragraphs: list[dict[str, Any]] = []

    for section_name, lines_with_pages in [("摘要", abstract_lines), ("內文", body_lines)]:
        sentences = _split_by_period(lines_with_pages)
        if not sentences:
            continue

        is_abstract = section_name == "摘要"
        cur_texts: list[str] = []
        cur_start: int | None = None
        cur_end: int | None = None

        def flush_paragraph() -> None:
            nonlocal cur_texts, cur_start, cur_end
            if cur_texts and cur_start is not None and cur_end is not None:
                combined = "".join(cur_texts).strip()
                if combined:
                    paragraphs.append({
                        "區段": section_name,
                        "段落": combined,
                        "起始頁": cur_start,
                        "結束頁": cur_end,
                    })
            cur_texts = []
            cur_start = None
            cur_end = None

        for sent_text, s_page, e_page in sentences:
            if is_abstract:
                is_heading = _is_abstract_heading(sent_text)
                if is_heading:
                    flush_paragraph()
                    cur_texts = [sent_text]
                    cur_start = s_page
                    cur_end = e_page
                else:
                    if cur_texts:
                        cur_texts.append(sent_text)
                        cur_end = e_page
                    else:
                        cur_texts = [sent_text]
                        cur_start = s_page
                        cur_end = e_page
            else:
                sub_chunks = _split_by_section_patterns(sent_text)
                for chunk in sub_chunks:
                    chunk_heading = _is_section_heading(chunk)
                    if chunk_heading:
                        flush_paragraph()
                        cur_texts = [chunk]
                        cur_start = s_page
                        cur_end = e_page
                    else:
                        if cur_texts:
                            cur_texts.append(chunk)
                            cur_end = e_page
                        else:
                            cur_texts = [chunk]
                            cur_start = s_page
                            cur_end = e_page

        flush_paragraph()

    # --- Step 4: 合併短段（先於過長切分） ---
    paragraphs = _merge_short_and_header_paragraphs(
        paragraphs, min_len=config.MIN_PARAGRAPH_LENGTH
    )

    # --- Step 5: 過長段落依句號再切分 ---
    expanded: list[dict[str, Any]] = []
    for p in paragraphs:
        para = p.get("段落", "")
        chunks = _split_long_paragraph_by_sentence(
            para, max_len=config.MAX_PARAGRAPH_LENGTH
        )
        for chunk in chunks:
            expanded.append({**p, "段落": chunk})

    if show_progress:
        print(f"    完成，共 {len(expanded)} 段", flush=True)
    return expanded
