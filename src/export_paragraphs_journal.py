# -*- coding: utf-8 -*-
"""期刊論文（來源代碼 97／華藝）段落擷取匯出——任務一：只做擷取＋分段，
產出 output/paragraphs_journal_review.csv 供人工檢視，不寫進既有
paragraphs_all_merged.csv、不觸碰 Notion／labeled_corpus.jsonl／向量庫。

跟既有學位論文流程（代碼 98）的差異：
- 章節編號習慣不同（常用「一、」而非「壹、」），且標題常因 PDF 排版被拆成多行，
  所以呼叫 extract_paragraphs_from_pdf() 時額外傳入 config.JOURNAL_BODY_START_KEYWORDS
  等專用設定（見 export_paragraphs_v1.py 的選用參數）。
- 華藝下載的 PDF 不是每篇都有封面頁（13 篇裡只有部分帶 DOI／airiti 字樣），逐頁
  偵測而非寫死跳過第 1 頁。
- id 前綴改用 97，序號依檔名排序重新編號（1~N），不會跟既有 98/92 開頭的 id 衝突。
- `OCR_FALLBACK_FILENAMES` 裡列的幾篇原始 PDF 沒有可用的內嵌文字層（實測是純掃描
  圖片）或內嵌文字層品質太差（OCR 亂碼），改用 Tesseract（繁體中文語言包）逐頁把
  圖片重新辨識成文字，再餵回 extract_paragraphs_from_pdf() 的 precomputed_lines
  參數沿用同一套段落切分邏輯，見 `_ocr_pdf_lines()`。

CLI: python -m src.export_paragraphs_journal
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import fitz  # PyMuPDF

from . import config
from .export_paragraphs import _make_page_str, _remove_paragraph_spaces
from .export_paragraphs_v1 import extract_paragraphs_from_pdf
from .extract_pdf import _decode_filename

JOURNAL_DIR = config.ROOT / "paper" / "期刊論文"
OUTPUT_CSV = config.OUTPUT_DIR / "paragraphs_journal_review.csv"
SOURCE_CODE = "97"

_COVER_PAGE_MARKERS = ("airiti", "doi.airiti.com", "digital object identifier")

# 沒有可用文字層（純掃描圖片）或文字層品質太差（OCR 亂碼）的期刊論文，改走
# _ocr_pdf_lines() 重新 OCR。之後若發現其他篇也有同樣問題，直接把檔名加進這個集合。
OCR_FALLBACK_FILENAMES = {
    "布農族主題繪本研究－以《布農族．法莉絲Bunun．Valis》為例.pdf",
    "布農族竹編器的文化意義研究.pdf",
    "南投縣信義鄉布農族傳統植物食茱萸分布地區土壤性質與養分濃度之調查.pdf",
}

# Tesseract 引擎（winget install --id UB-Mannheim.TesseractOCR）與繁體中文語言包
# （tessdata/chi_tra.traineddata，見 .gitignore 說明；系統帳號沒有權限寫進
# Tesseract 自己的 tessdata 目錄，改用 TESSDATA_PREFIX 指到專案內這份）。
# 優先用 PATH 上找得到的 tesseract（shutil.which，跨機器可攜），找不到才退回
# winget 預設安裝路徑（這台機器目前的實際狀況）；兩個都沒有就等真的要跑 OCR
# 時讓 pytesseract 自己丟出清楚的 TesseractNotFoundError，不在 import 這裡就擋掉。
_TESSERACT_WINGET_DEFAULT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_TESSERACT_CMD = shutil.which("tesseract") or _TESSERACT_WINGET_DEFAULT
_TESSDATA_DIR = config.ROOT / "tessdata"
_OCR_DPI = 300


def _ocr_pdf_lines(pdf_path: Path, skip_pages: set[int]) -> list[dict[str, Any]]:
    """逐頁把 PDF 頁面渲染成圖片，用 Tesseract（繁中）重新 OCR，回傳跟
    export_paragraphs_v1._iter_page_lines() 相同形狀的 [{"page": int, "text": str}, ...]，
    可以直接餵給 extract_paragraphs_from_pdf() 的 precomputed_lines 參數。"""
    import pytesseract
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD
    os.environ["TESSDATA_PREFIX"] = str(_TESSDATA_DIR)

    lines: list[dict[str, Any]] = []
    doc = fitz.open(pdf_path)
    try:
        for page_index in range(doc.page_count):
            page_no = page_index + 1
            if page_no in skip_pages:
                continue
            print(f"    OCR 頁 {page_no}/{doc.page_count}…", flush=True)
            pix = doc.load_page(page_index).get_pixmap(dpi=_OCR_DPI)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text = pytesseract.image_to_string(img, lang="chi_tra")
            for raw_line in text.splitlines():
                t = raw_line.strip()
                if t:
                    lines.append({"page": page_no, "text": t})
    finally:
        doc.close()
    return lines


def _detect_cover_pages(pdf_path: Path) -> set[int]:
    """逐頁偵測華藝自動產生的封面／書目資訊頁（不是每篇都有），回傳要跳過的頁碼
    （1-indexed，對應 export_paragraphs_v1._iter_page_lines 的頁碼慣例）。

    讀的是 PDF 內嵌的原生文字層，對 OCR_FALLBACK_FILENAMES 裡那幾篇（文字層本來
    就缺失／品質太差才需要 OCR）完全偵測不到東西——那幾篇改用
    `_detect_cover_pages_from_lines()` 對 OCR 結果做偵測，見 run()。"""
    skip: set[int] = set()
    doc = fitz.open(pdf_path)
    try:
        for page_index in range(doc.page_count):
            text = doc.load_page(page_index).get_text().lower()
            if any(marker in text for marker in _COVER_PAGE_MARKERS):
                skip.add(page_index + 1)
    finally:
        doc.close()
    return skip


def _detect_cover_pages_from_lines(lines: list[dict[str, Any]]) -> set[int]:
    """跟 _detect_cover_pages() 同一套標記比對，但吃已經 OCR 好的逐行文字——給
    OCR_FALLBACK_FILENAMES 那幾篇用，因為它們的原生文字層本來就讀不到東西。"""
    skip: set[int] = set()
    by_page: dict[int, list[str]] = {}
    for line in lines:
        by_page.setdefault(line["page"], []).append(line["text"])
    for page_no, texts in by_page.items():
        page_text = "".join(texts).lower()
        if any(marker in page_text for marker in _COVER_PAGE_MARKERS):
            skip.add(page_no)
    return skip


def list_journal_pdfs() -> list[Path]:
    return sorted(JOURNAL_DIR.glob("*.pdf"), key=lambda p: p.name)


def _validate_paper_order(pdfs: list[Path]) -> None:
    """驗證 PDF 依檔名字母排序後的序號，跟 書目資料清單.csv「序號→檔名」對應是否
    一致——兩者一旦對不上，format_journal_citation() 會把 A 篇論文的作者／期刊／
    頁碼接到 B 篇論文的段落上，且不會有任何錯誤或警告（新增／刪除／改名 PDF 時
    最容易踩到）。"""
    from .data.journal_bibliography import get_journal_bibliography

    mismatches = []
    for paper_index, pdf_path in enumerate(pdfs, start=1):
        info = get_journal_bibliography(paper_index)
        expected_name = (info or {}).get("檔名", "").strip()
        if expected_name and expected_name != pdf_path.name:
            mismatches.append((paper_index, pdf_path.name, expected_name))
    if mismatches:
        detail = "\n".join(
            f"  序號 {idx}：實際 PDF 是「{actual}」，書目資料清單.csv 卻寫「{expected}」"
            for idx, actual, expected in mismatches
        )
        raise SystemExit(
            "⚠️ PDF 依檔名排序後的序號跟 書目資料清單.csv 的「序號→檔名」對不上，"
            f"繼續跑會把錯的作者／期刊／頁碼接到段落上：\n{detail}\n"
            "請檢查是否新增／刪除／改名了 paper/期刊論文/ 底下的 PDF，"
            "或需要同步調整 書目資料清單.csv 的序號。"
        )


def run() -> Path:
    pdfs = list_journal_pdfs()
    if not pdfs:
        raise SystemExit(f"{JOURNAL_DIR} 底下找不到任何 PDF")
    _validate_paper_order(pdfs)

    import csv

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    empty_papers: list[str] = []

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["ID", "段落", "來源文章", "頁數"], extrasaction="ignore")
        writer.writeheader()

        for paper_index, pdf_path in enumerate(pdfs, start=1):
            source = _decode_filename(pdf_path)
            print(f"[{paper_index}/{len(pdfs)}] {source}", flush=True)

            if source in OCR_FALLBACK_FILENAMES:
                # 這幾篇原生文字層缺失／品質太差，_detect_cover_pages() 讀原生文字層
                # 偵測不到封面頁——改成先整篇 OCR，再對 OCR 出來的文字做封面頁偵測。
                print(f"    原始文字層缺失／品質不佳，改用 Tesseract 重新 OCR（可能要幾分鐘）…")
                ocr_lines = _ocr_pdf_lines(pdf_path, skip_pages=set())
                skip_pages = _detect_cover_pages_from_lines(ocr_lines)
                if skip_pages:
                    print(f"    偵測到 {len(skip_pages)} 頁封面／書目頁，已跳過：{sorted(skip_pages)}")
                    ocr_lines = [line for line in ocr_lines if line["page"] not in skip_pages]
                paragraphs: list[dict[str, Any]] = extract_paragraphs_from_pdf(
                    pdf_path,
                    body_start_keywords=config.JOURNAL_BODY_START_KEYWORDS,
                    body_end_keywords=config.JOURNAL_BODY_END_KEYWORDS,
                    extra_body_start_re=config.JOURNAL_SECTION_HEADING_RE,
                    extra_section_heading_re=config.JOURNAL_SECTION_HEADING_RE,
                    precomputed_lines=ocr_lines,
                )
            else:
                skip_pages = _detect_cover_pages(pdf_path)
                if skip_pages:
                    print(f"    偵測到 {len(skip_pages)} 頁封面／書目頁，已跳過：{sorted(skip_pages)}")
                paragraphs = extract_paragraphs_from_pdf(
                    pdf_path,
                    show_progress=True,
                    body_start_keywords=config.JOURNAL_BODY_START_KEYWORDS,
                    body_end_keywords=config.JOURNAL_BODY_END_KEYWORDS,
                    extra_body_start_re=config.JOURNAL_SECTION_HEADING_RE,
                    extra_section_heading_re=config.JOURNAL_SECTION_HEADING_RE,
                    skip_pages=skip_pages or None,
                )

            if not paragraphs:
                empty_papers.append(source)
                print(f"    ⚠️ 沒有擷取到任何段落，需要人工檢視！")
                continue

            for para_idx, para in enumerate(paragraphs, start=1):
                pid = f"{SOURCE_CODE}-{paper_index}-{para_idx}"
                writer.writerow({
                    "ID": pid,
                    "段落": _remove_paragraph_spaces(para.get("段落", "")),
                    "來源文章": source,
                    "頁數": _make_page_str(para.get("起始頁"), para.get("結束頁")),
                })
            print(f"    擷取到 {len(paragraphs)} 段")

    print(f"\n輸出：{OUTPUT_CSV}")
    if empty_papers:
        print(f"\n⚠️ 以下 {len(empty_papers)} 篇沒有擷取到任何段落，人工檢視時請特別留意：")
        for name in empty_papers:
            print(f"  - {name}")
    return OUTPUT_CSV


if __name__ == "__main__":
    run()
