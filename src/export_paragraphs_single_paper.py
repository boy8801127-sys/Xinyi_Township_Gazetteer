# -*- coding: utf-8 -*-
"""單篇學位論文（來源代碼 98）段落擷取匯出——只做「擷取＋分段」，產出**獨立**的
output/paragraphs_paper_98-{序號}_review.csv 供人工複核（Excel 合併儲存格），
不會寫進既有的 output/paragraphs_all.csv／paragraphs_all_merged.csv，也不觸碰
Notion／labeled_corpus.jsonl／向量庫。

為什麼另外開一支，而不是重跑 export_paragraphs.py：
- `run_on_paper_dir_for_paragraphs()` 是對整個 paper/碩博士論文/ 目錄跑、再一次性
  輸出 paragraphs_all.csv（覆寫），只為了新增一篇論文重跑會把已經人工複核過的
  60 篇結果一起蓋掉。這支腳本只吃單一 PDF、只寫自己的輸出檔。
- 段落切分邏輯完全沿用 export_paragraphs_v1.extract_paragraphs_from_pdf()（學位
  論文既有呼叫路徑，不傳期刊專用參數），所以切出來的結果跟前 60 篇同一套規則。

id 規則沿用 `{來源代碼}-{論文序號}-{段落序號}`（見 src/data/source_codes.py），論文
序號取自 PDF 檔名的數字前綴（例：`81-孫海與振昌木業….pdf` → `98-81-1`、`98-81-2`…）。

後續步驟（人工複核完才做，不在這支腳本範圍）：
1. 本檔輸出的 CSV 另存成 xlsx，人工把該合併的段落列用 A 欄（ID）合併儲存格
2. python -m src.split_and_merge_paragraphs_xlsx <複核後的 xlsx>
3. 匯入 Notion → notion_classify.py → build_labeled_corpus.py

CLI:
  python -m src.export_paragraphs_single_paper "paper/碩博士論文/81-孫海與振昌木業-….pdf"
  python -m src.export_paragraphs_single_paper --paper-index 81
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from . import config
from .export_paragraphs import _make_page_str, _remove_paragraph_spaces
from .export_paragraphs_v1 import extract_paragraphs_from_pdf
from .extract_pdf import _decode_filename, list_papers

SOURCE_CODE = "98"
FIELDNAMES = ["ID", "段落", "來源文章", "頁數"]

# 既有的學位論文總表：只拿來做「這篇是不是已經處理過」的防呆檢查，不會被寫入
EXISTING_MERGED_CSV = config.OUTPUT_DIR / "paragraphs_all_merged.csv"

_FILENAME_INDEX_RE = re.compile(r"^0*(\d+)")


def paper_index_from_filename(pdf_path: Path) -> int:
    """從 PDF 檔名的數字前綴取論文序號（`81-xxx.pdf` → 81）。"""
    m = _FILENAME_INDEX_RE.match(_decode_filename(pdf_path))
    if not m:
        raise SystemExit(
            f"檔名「{pdf_path.name}」沒有數字前綴，無法決定論文序號。\n"
            "請把 PDF 改名成 `{序號}-{標題}.pdf`（例：81-孫海與振昌木業….pdf），"
            "或用 --paper-index 明確指定。"
        )
    return int(m.group(1))


def find_pdf_by_index(paper_index: int, paper_dir: Path | None = None) -> Path:
    """依論文序號在 paper/碩博士論文/ 底下找出對應 PDF。"""
    d = paper_dir or config.PAPER_DIR
    matches = [
        p for p in list_papers(d)
        if _FILENAME_INDEX_RE.match(_decode_filename(p))
        and int(_FILENAME_INDEX_RE.match(_decode_filename(p)).group(1)) == paper_index
    ]
    if not matches:
        raise SystemExit(f"{d} 底下找不到序號 {paper_index} 的 PDF")
    if len(matches) > 1:
        names = "\n".join(f"  - {p.name}" for p in matches)
        raise SystemExit(f"序號 {paper_index} 對到多個 PDF，請確認檔名：\n{names}")
    return matches[0]


def _warn_if_already_exported(paper_index: int) -> None:
    """若該序號已經在既有總表裡，出聲提醒（不阻擋）——避免重複匯入同一篇。"""
    if not EXISTING_MERGED_CSV.exists():
        return
    prefix = f"{SOURCE_CODE}-{paper_index}-"
    with open(EXISTING_MERGED_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        hit = sum(1 for row in reader if (row.get("ID") or "").startswith(prefix))
    if hit:
        print(
            f"⚠️ 注意：{EXISTING_MERGED_CSV.name} 裡已經有 {hit} 筆 {prefix}* 的段落，"
            "這篇論文可能先前就處理過了。\n"
            "   本腳本仍會輸出到獨立檔案、不會動到那份總表，但請先確認是不是重複作業。",
            flush=True,
        )


def run(
    pdf_path: Path,
    paper_index: int | None = None,
    output_path: Path | None = None,
    glyph_fix: str | None = None,
) -> Path:
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise SystemExit(f"找不到 PDF：{pdf_path}")

    idx = paper_index if paper_index is not None else paper_index_from_filename(pdf_path)
    source = _decode_filename(pdf_path)
    _warn_if_already_exported(idx)

    out_path = output_path or (
        config.OUTPUT_DIR / f"paragraphs_paper_{SOURCE_CODE}-{idx}_review.csv"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"論文序號 {idx}：{source}", flush=True)
    if glyph_fix:
        # 這份 PDF 的內嵌字型 ToUnicode 表有錯，先依 glyph id 還原字元再切段落，
        # 詳見 src/glyph_fix.py 的說明。
        from .glyph_fix import build_fixed_page_lines, count_fixes, load_fix_map

        fix_map = load_fix_map(glyph_fix)
        fixed = sum(count_fixes(pdf_path, fix_map).values())
        print(f"    套用字形對照表 {glyph_fix}：{len(fix_map)} 條、修正 {fixed} 字", flush=True)
        lines = build_fixed_page_lines(pdf_path, fix_map, show_progress=True)
        paragraphs = extract_paragraphs_from_pdf(pdf_path, precomputed_lines=lines)
    else:
        paragraphs = extract_paragraphs_from_pdf(pdf_path, show_progress=True)
    if not paragraphs:
        raise SystemExit(
            "⚠️ 沒有擷取到任何段落。可能是 PDF 缺少文字層（純掃描檔，需要 OCR，"
            "作法可參考 export_paragraphs_journal.py 的 _ocr_pdf_lines()），"
            "或摘要／緒論起始關鍵字跟 config 的設定對不上。"
        )

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for para_idx, para in enumerate(paragraphs, start=1):
            writer.writerow({
                "ID": f"{SOURCE_CODE}-{idx}-{para_idx}",
                "段落": _remove_paragraph_spaces(para.get("段落", "")),
                "來源文章": source,
                "頁數": _make_page_str(para.get("起始頁"), para.get("結束頁")),
            })

    print(f"\n擷取到 {len(paragraphs)} 段", flush=True)
    print(f"輸出：{out_path}", flush=True)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="單篇學位論文段落擷取（獨立輸出，不併入既有 CSV）"
    )
    parser.add_argument("pdf", nargs="?", help="PDF 路徑；省略時用 --paper-index 尋找")
    parser.add_argument(
        "--paper-index", type=int, default=None,
        help="論文序號（id 的中段）。省略時取 PDF 檔名的數字前綴",
    )
    parser.add_argument("--out", default=None, help="輸出 CSV 路徑（預設放 output/）")
    parser.add_argument(
        "--glyph-fix", default=None,
        help="套用 src/data/glyph_fix/{名稱}.json 字形對照表，修正 PDF 文字層錯字（例：98-81）",
    )
    args = parser.parse_args()

    if args.pdf:
        pdf_path = Path(args.pdf)
    elif args.paper_index is not None:
        pdf_path = find_pdf_by_index(args.paper_index)
    else:
        parser.error("請指定 PDF 路徑，或用 --paper-index 指定論文序號")

    run(
        pdf_path,
        paper_index=args.paper_index,
        output_path=Path(args.out) if args.out else None,
        glyph_fix=args.glyph_fix,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
