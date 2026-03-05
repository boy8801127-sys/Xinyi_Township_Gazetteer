# -*- coding: utf-8 -*-
"""步驟 2：以句號切分段落並標註來源文章、頁數、註腳。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import config
from .extract_pdf import extract_pdf, _decode_filename


def _split_sentences(text: str) -> list[str]:
    """
    以中文句號 。 與句尾英文 . 切分句子。
    英文句尾：. 後為空白或結尾，且不將「1.」「2.」等序號切開（前一字非數字時才切）。
    """
    if not text or not text.strip():
        return []
    # 先以中文句號切
    by_cn = re.split(r"(?<=。)", text)
    sentences: list[str] = []
    for block in by_cn:
        block = block.strip()
        if not block:
            continue
        # 再以英文句尾 . 切：. 後為空白或結尾，且 . 前不是數字（避免 1. 2. 序號斷開）
        parts = re.split(r"(?<!\d)\.(?=\s+|$)", block)
        for p in parts:
            p = p.strip()
            if p:
                sentences.append(p)
    return [s for s in sentences if s]


def segment_and_annotate(pages: list[dict], source_name: str) -> list[dict[str, Any]]:
    """
    將每頁 body 以句號切段，每段標註來源文章、頁數、該頁註腳。
    pages: [{"page": 1, "body": "...", "footnote": "..."}, ...]
    回傳 [{"段落": "...", "來源文章": "...", "頁數": 1, "註腳": "..."}, ...]
    """
    rows: list[dict[str, Any]] = []
    for p in pages:
        page_no = p["page"]
        body = p.get("body", "") or ""
        footnote = p.get("footnote", "") or ""
        for sent in _split_sentences(body):
            sent = sent.strip()
            if not sent:
                continue
            rows.append({
                "段落": sent,
                "來源文章": source_name,
                "頁數": page_no,
                "註腳": footnote,
            })
    return rows


def run_on_pdf(pdf_path: Path, footnote_y_ratio: float | None = None) -> list[dict[str, Any]]:
    """對單一 PDF 執行擷取＋切分＋標註。"""
    pages = extract_pdf(pdf_path, footnote_y_ratio)
    source_name = _decode_filename(pdf_path)
    return segment_and_annotate(pages, source_name)


def run_on_paper_dir(paper_dir: Path | None = None, max_pdfs: int | None = None) -> list[dict[str, Any]]:
    """對 paper 目錄下所有 PDF 執行，回傳合併的段落列表。"""
    from .extract_pdf import list_papers
    pdfs = list_papers(paper_dir)
    if max_pdfs is not None:
        pdfs = pdfs[: max_pdfs]
    all_rows: list[dict[str, Any]] = []
    total = len(pdfs)
    for i, pdf_path in enumerate(pdfs):
        if total > 1:
            print(f"  處理中 {i + 1}/{total}: {pdf_path.name}", flush=True)
        all_rows.extend(run_on_pdf(pdf_path))
    return all_rows


if __name__ == "__main__":
    import json
    import sys
    from .extract_pdf import list_papers
    pdfs = list_papers(config.PAPER_DIR)
    if not pdfs:
        print("無 PDF 可處理", file=sys.stderr)
        sys.exit(1)
    rows = run_on_pdf(pdfs[0])
    print(json.dumps(rows[:3], ensure_ascii=False, indent=2))
