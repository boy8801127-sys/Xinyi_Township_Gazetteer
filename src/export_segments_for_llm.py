# -*- coding: utf-8 -*-
"""僅供本地 LLM 判讀用的段落匯出：不分類，只輸出段落與來源資訊。"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from . import config
from .extract_pdf import _decode_filename, extract_pdf, list_papers


def run_on_pdf_for_llm(pdf_path: Path, footnote_y_ratio: float | None = None) -> list[dict[str, Any]]:
    """
    對單一 PDF 執行擷取與「自然段」切分，產出 rows：
    - 段落：每個 body block（一個自然段），已移除段內硬換行
    - 來源文章：檔名或可讀題名
    - 頁數：該段所在頁碼
    - 註腳：該頁所有註腳合併文字
    """
    pages = extract_pdf(pdf_path, footnote_y_ratio)
    source_name = _decode_filename(pdf_path)
    rows: list[dict[str, Any]] = []
    for p in pages:
        page_no = p.get("page")
        footnote = p.get("footnote", "") or ""
        blocks = p.get("body_blocks") or []
        # 若沒有 body_blocks，就退而以整頁 body 切分
        if not blocks:
            body = (p.get("body") or "").strip()
            if body:
                blocks = [body]
        for block in blocks:
            text = (block or "").strip()
            if not text:
                continue
            rows.append(
                {
                    "段落": text,
                    "來源文章": source_name,
                    "頁數": page_no,
                    "註腳": footnote,
                }
            )
    return rows


def run_on_paper_dir_for_llm(
    paper_dir: Path | None = None,
    max_pdfs: int | None = None,
    footnote_y_ratio: float | None = None,
) -> list[dict[str, Any]]:
    """對 paper 目錄下所有 PDF 執行，回傳合併的段落列表（供 LLM 使用）。"""
    d = paper_dir or config.PAPER_DIR
    pdfs = list_papers(d)
    if max_pdfs is not None:
        pdfs = pdfs[: max_pdfs]
    all_rows: list[dict[str, Any]] = []
    for pdf_path in pdfs:
        all_rows.extend(run_on_pdf_for_llm(pdf_path, footnote_y_ratio))
    return all_rows


_PAPER_INDEX_RE = re.compile(r"^0*(\d+)")


def _get_paper_index_from_source_name(name: str, fallback_index: int) -> int:
    """
    從來源文章名稱推論論文編號：取開頭連續數字；若無則使用備援編號。
    """
    m = _PAPER_INDEX_RE.match(name)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return fallback_index


def export_segments_for_llm(rows: list[dict[str, Any]], out_dir: Path | None = None) -> Path:
    """
    將 rows 匯出為 output/llm/llm_segments.csv：
    - ID：論文編號-段落編號（例如 1-2 表示第 1 篇論文第 2 段）
    - 段落、來源文章、頁數、註腳
    """
    base_dir = out_dir or config.OUTPUT_DIR
    target_dir = base_dir / "llm"
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / "llm_segments.csv"

    # 依來源文章分組，同時保留首次出現順序
    by_source: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for r in rows:
        src = (r.get("來源文章") or "").strip() or "未命名"
        if src not in by_source:
            by_source[src] = []
            order.append(src)
        by_source[src].append(r)

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["ID", "段落", "來源文章", "頁數", "註腳"],
            extrasaction="ignore",
        )
        writer.writeheader()

        fallback_counter = 1
        for src in order:
            paper_index = _get_paper_index_from_source_name(src, fallback_counter)
            if not _PAPER_INDEX_RE.match(src):
                fallback_counter += 1
            paragraph_idx = 1
            for r in by_source[src]:
                pid = f"{paper_index}-{paragraph_idx}"
                paragraph_idx += 1
                writer.writerow(
                    {
                        "ID": pid,
                        "段落": r.get("段落", ""),
                        "來源文章": src,
                        "頁數": r.get("頁數", ""),
                        "註腳": r.get("註腳", ""),
                    }
                )

    return out_path


if __name__ == "__main__":
    import sys

    rows = run_on_paper_dir_for_llm(max_pdfs=1)
    if not rows:
        print("無段落可匯出（paper/ 可能沒有 PDF）", file=sys.stderr)
        sys.exit(1)
    out = export_segments_for_llm(rows, config.OUTPUT_DIR)
    print(f"已匯出 LLM 段落檔：{out}")

