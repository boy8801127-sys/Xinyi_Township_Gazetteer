# -*- coding: utf-8 -*-
"""修正 PDF 內嵌字型 ToUnicode 對照表錯誤造成的錯字。

## 問題

有些 PDF 的內嵌字型子集，ToUnicode CMap 有一部分 glyph 被填成錯誤的碼位
（在 `81-孫海與振昌木業…` 這篇實測到的模式是：填成「該字後面那個字」的碼位），
於是 PyMuPDF／pdftotext 等所有依賴文字層的工具都會讀到錯字。麻煩的是錯字本身
是合法中文字（「昂貴」→「昂人」、「巒大山」→「巒大中」、「認為」→「識為」），
不會變成亂碼，任何編碼偵測都抓不出來，只有跟原始頁面對照才看得見。

## 修法

PDF 內部的 glyph id 是正確的——同一個字形永遠對到同一個 glyph id，錯的只是
glyph id → Unicode 那層對照。所以只要建立一份「glyph id → 正確的字」對照表就能
還原。對照表怎麼來：把每個 glyph 在原始頁面上的位置裁切、放大成字形圖，人工看圖
判定，再用該 glyph 出現處的上下文交叉驗證（見 `docs/glyph_fix_98-81.md` 的建立過程）。

改用 OCR 重抽全篇不是好選擇：實測 OCR 會引入自己的辨識錯誤（「奮」→「蕉」、
「巒」→「蠻」），且丟失版面結構；文字層除了這批系統性錯字之外品質是好的。

## 用法

    from .glyph_fix import build_fixed_page_lines, load_fix_map
    lines = build_fixed_page_lines(pdf_path, load_fix_map("98-81"))
    paragraphs = extract_paragraphs_from_pdf(pdf_path, precomputed_lines=lines)

`build_fixed_page_lines()` 產出的行結構刻意比照
`export_paragraphs_v1._iter_page_lines()`，所以套上去之後段落切分規則跟其他論文
完全一樣，差別只在字元內容被修正過。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover
    fitz = None

FIX_MAP_DIR = Path(__file__).resolve().parent / "data" / "glyph_fix"


def load_fix_map(name: str) -> dict[int, str]:
    """讀取 `src/data/glyph_fix/{name}.json`，回傳 {glyph_id: 正確的字}。

    JSON 的 key 是字串形式的 glyph id，value 是正確的字；value 為 null 代表
    「這個 glyph 的標注本來就是對的」，載入時會濾掉，只留真正要換的。
    """
    path = FIX_MAP_DIR / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"找不到字形對照表：{path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        int(k): v
        for k, v in raw.items()
        if not k.startswith("_") and v
    }


def _glyph_table(page: "fitz.Page") -> dict[tuple[float, float], int]:
    """以字元 bbox 左上角為 key 的 glyph id 查表。

    key 用 bbox 而不是「第幾個字元」，是因為 `get_texttrace()` 會多抓到重複繪製
    的標題文字（PDF 用兩次繪製做粗體效果），跟 `get_text("rawdict")` 的字元序列
    對不齊；改用座標配對就不受影響。實測這份 PDF 的 86,450 個漢字 100% 配對成功
    （漢字在兩邊的 bbox 完全相同，只有數字／西文因為字型不同會有小數差異，
    而那些字不在對照表裡、本來就不用修）。
    """
    table: dict[tuple[float, float], int] = {}
    for span in page.get_texttrace():
        for ch in span["chars"]:
            bbox = ch[3]
            table[(round(bbox[0], 1), round(bbox[1], 1))] = ch[1]
    return table


def build_fixed_page_lines(
    pdf_path: Path,
    fix_map: dict[int, str],
    show_progress: bool = False,
) -> list[dict[str, Any]]:
    """逐頁擷取行文字並依 glyph id 修正錯字。

    回傳 `[{"page": int, "text": str}, ...]`，形狀跟
    `export_paragraphs_v1._iter_page_lines()` 相同，可直接傳給
    `extract_paragraphs_from_pdf()` 的 `precomputed_lines` 參數。
    """
    if fitz is None:
        raise RuntimeError("請安裝 PyMuPDF：pip install PyMuPDF")

    doc = fitz.open(pdf_path)
    try:
        lines: list[dict[str, Any]] = []
        total = doc.page_count
        for page_index in range(total):
            if show_progress and total > 10 and (page_index % 20 == 0 or page_index == total - 1):
                print(f"    頁 {page_index + 1}/{total}", flush=True)
            page = doc.load_page(page_index)
            # get_texttrace()（_glyph_table 用來取得 glyph id）內部一律以 rotation=0
            # 量測座標，但 get_text("rawdict") 預設用頁面實際 rotation 換算座標——
            # 旋轉頁上兩邊座標系會對不上，導致 bbox 全部配對失敗、整頁字形悄悄修正
            # 失效且不報錯。強制兩邊都在 rotation=0 下抓取，確保座標系一致（不影響
            # 抓出來的文字內容，只影響座標換算；抓完就地還原，不寫回檔案不受影響）。
            original_rotation = page.rotation
            if original_rotation:
                page.set_rotation(0)
            try:
                gtbl = _glyph_table(page)
                raw_dict = page.get_text("rawdict")
            finally:
                if original_rotation:
                    page.set_rotation(original_rotation)
            for block in raw_dict["blocks"]:
                for line in block.get("lines", []):
                    buf: list[str] = []
                    for span in line.get("spans", []):
                        for ch in span.get("chars", []):
                            c = ch["c"]
                            bbox = ch["bbox"]
                            gid = gtbl.get((round(bbox[0], 1), round(bbox[1], 1)))
                            if gid is not None:
                                c = fix_map.get(gid, c)
                            buf.append(c)
                    text = "".join(buf).strip()
                    if text:
                        lines.append({"page": page_index + 1, "text": text})
    finally:
        doc.close()
    return lines


def count_fixes(pdf_path: Path, fix_map: dict[int, str]) -> dict[str, int]:
    """統計這份對照表在該 PDF 實際會修掉幾個字（依「錯字→正字」分組）。"""
    if fitz is None:
        raise RuntimeError("請安裝 PyMuPDF：pip install PyMuPDF")
    stats: dict[str, int] = {}
    doc = fitz.open(pdf_path)
    try:
        for page_index in range(doc.page_count):
            for span in doc.load_page(page_index).get_texttrace():
                for ch in span["chars"]:
                    fixed = fix_map.get(ch[1])
                    if fixed:
                        key = f"{chr(ch[0])}→{fixed}"
                        stats[key] = stats.get(key, 0) + 1
    finally:
        doc.close()
    return dict(sorted(stats.items(), key=lambda x: -x[1]))
