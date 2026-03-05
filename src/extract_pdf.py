# -*- coding: utf-8 -*-
"""步驟 1：從 PDF 擷取文字，分離正文與註腳。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from . import config

# 註腳內容規則：行首數字+點/空格/頓號（註腳編號）
_FOOTNOTE_NUMBER_RE = re.compile(r"^\d+[\.\s、．]")


def _is_likely_footnote(text: str) -> bool:
    """
    依內容判斷是否像註腳：含《、〈，或行首為註腳編號（數字+點/空格/頓號）。
    """
    if not text or not text.strip():
        return False
    stripped = text.strip()
    if "《" in stripped or "〈" in stripped:
        return True
    if _FOOTNOTE_NUMBER_RE.match(stripped):
        return True
    return False


def _decode_filename(path: Path) -> str:
    """嘗試將可能為 Big5 的檔名解為可讀字串。"""
    name = path.name
    try:
        # 若已是合法 UTF-8 且含中文，直接回傳
        name.encode("utf-8").decode("utf-8")
        if any("\u4e00" <= c <= "\u9fff" for c in name):
            return name
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    try:
        return name.encode("latin1").decode("big5")
    except (UnicodeDecodeError, UnicodeEncodeError, LookupError):
        return name


def extract_page(page: "fitz.Page", footnote_y_ratio: float = config.FOOTNOTE_Y_RATIO) -> tuple[str, str, list[str], list[str]]:
    """
    擷取單頁正文與註腳文字。

    回傳 (body, footnote, body_blocks, footnote_blocks)：
    - body: 將同一頁所有正文區塊以換行連接的文字
    - footnote: 將同一頁所有註腳區塊以換行連接的文字
    - body_blocks: 每一個正文區塊（已移除段內硬換行）的文字列表
    - footnote_blocks: 每一個註腳區塊的文字列表

    頁面 y 大於 footnote_y_ratio * 頁高 的區塊，加上內容規則，視為註腳。
    """
    if fitz is None:
        raise RuntimeError("請安裝 PyMuPDF: pip install PyMuPDF")
    page_height = page.rect.height
    y_threshold = page_height * footnote_y_ratio
    body_parts: list[str] = []
    footnote_parts: list[str] = []
    body_blocks: list[str] = []
    footnote_blocks: list[str] = []
    try:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    except Exception:
        # fallback: 整頁當正文
        text = page.get_text()
        body = text.strip()
        return body, "", [body] if body else [], []
    for block in blocks:
        if "bbox" not in block:
            continue
        x0, y0, x1, y1 = block["bbox"]
        block_text_parts: list[str] = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span.get("text", "").strip()
                if t:
                    block_text_parts.append(t)
        # 同一個 block 視為「同一自然段」，段內換行以空白串接
        text = " ".join(block_text_parts)
        if not text:
            continue
        is_footnote_by_position = y0 >= y_threshold
        is_footnote_by_content = config.USE_FOOTNOTE_CONTENT_RULES and _is_likely_footnote(text)
        if is_footnote_by_position or is_footnote_by_content:
            footnote_parts.append(text)
            footnote_blocks.append(text)
        else:
            body_parts.append(text)
            body_blocks.append(text)
    body = "\n".join(body_parts).strip()
    footnote = "\n".join(footnote_parts).strip()
    return body, footnote, body_blocks, footnote_blocks


def extract_pdf(pdf_path: Path, footnote_y_ratio: float | None = None) -> list[dict]:
    """
    擷取 PDF 每頁正文與註腳。
    回傳 [{"page": 1, "body": "...", "footnote": "...", "body_blocks": [...], "footnote_blocks": [...]}, ...]，
    page 為 1-based。
    """
    if fitz is None:
        raise RuntimeError("請安裝 PyMuPDF: pip install PyMuPDF")
    ratio = footnote_y_ratio if footnote_y_ratio is not None else config.FOOTNOTE_Y_RATIO
    out: list[dict] = []
    doc = fitz.open(pdf_path)
    try:
        for i in range(len(doc)):
            page = doc.load_page(i)
            body, footnote, body_blocks, footnote_blocks = extract_page(page, ratio)
            out.append(
                {
                    "page": i + 1,
                    "body": body,
                    "footnote": footnote,
                    "body_blocks": body_blocks,
                    "footnote_blocks": footnote_blocks,
                }
            )
    finally:
        doc.close()
    return out


def iter_pdf_pages(pdf_path: Path, footnote_y_ratio: float | None = None) -> Iterator[dict]:
    """逐頁 yield，節省記憶體。"""
    for item in extract_pdf(pdf_path, footnote_y_ratio):
        yield item


def list_papers(paper_dir: Path | None = None) -> list[Path]:
    """列出 paper 目錄下所有 PDF 路徑。"""
    d = paper_dir or config.PAPER_DIR
    if not d.is_dir():
        return []
    return sorted(d.glob("*.pdf"), key=lambda p: p.name)


if __name__ == "__main__":
    import json
    import sys
    paper_dir = config.PAPER_DIR
    pdfs = list_papers(paper_dir)
    if not pdfs:
        print("未找到 PDF，請將檔案放入 paper/", file=sys.stderr)
        sys.exit(1)
    # 測試第一本
    first = pdfs[0]
    display_name = _decode_filename(first)
    print(f"測試擷取: {display_name}", file=sys.stderr)
    pages = extract_pdf(first)
    print(json.dumps({"source": display_name, "pages": pages[:2]}, ensure_ascii=False, indent=2))
