# -*- coding: utf-8 -*-
"""
《南投縣志》(2010出版) docx 抽取工具。

books/02-南投縣志(2010出版)/ 底下每個「卷/篇」資料夾各有 1 個 docx，內容全部
裝在 Word 表格裡（每個表格固定 3 列：檔名／內文／圖片，對應原書一個掃描頁）。
把「內文」抽出來，轉成跟論文段落完全相同的兩種既有格式，讓下游
`build_labeled_corpus.py`／`build_index.py` 不用改一行就能吃到：
    1. 追加到 output/paragraphs_all_merged.csv（ID／段落／來源文章／頁數）
    2. 寫入 results/books_南投縣志.json（比照 notion_classify.py 的 results/*.json schema）

分類不呼叫 API：縣志本身的卷/篇結構已經是明確的分類依據，直接用資料夾名稱
對照 This_plan/類別.txt 既有的 12 類（見 FOLDER_CATEGORY），不逐段送語意判斷。

使用方式：
    python -m src.data.extract_books
"""
from __future__ import annotations

import csv
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from .. import config

ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_DIR = ROOT / "books" / "02-南投縣志(2010出版)"
CSV_PATH = ROOT / "output" / "paragraphs_all_merged.csv"
REVIEW_CSV_PATH = ROOT / "output" / "paragraphs_books_review.csv"
RESULTS_PATH = ROOT / "results" / "books_南投縣志.json"
CSV_FIELDNAMES = ["ID", "段落", "來源文章", "頁數"]

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

# 資料夾（卷/篇）-> This_plan/類別.txt 既有分類。key 需與磁碟上資料夾名稱完全一致
# （原書資料夾命名本身「志」／「誌」／「篇」用字不一致，照抄勿修正）。
FOLDER_CATEGORY: dict[str, str] = {
    "卷一 自然志 博物篇": "自然與生態篇",
    "卷一 自然志 氣候篇": "自然與生態篇",
    "卷二 住民志 人口篇、氏族篇": "社會篇",
    "卷二 住民志 原住民篇": "社會篇",
    "卷二 住民志 宗教篇、風俗篇": "宗教禮俗篇",
    "卷二 住民志 語言篇": "教育與語言篇",
    "卷三 政事志 司法篇、警政篇": "政事篇",
    "卷三 政事志 建設篇": "交通與建設篇",
    "卷三 政事志 戶政篇、役政篇": "政事篇",
    "卷三 政事志 行政篇、自治篇": "政事篇",
    "卷三 政事志 選舉篇": "政事篇",
    "卷三 政事篇 財政篇、地政篇": "政事篇",
    "卷三 政事誌 人民團體篇、社會福利篇、衛生篇": "社會篇",
    "卷四 經濟志 商業篇、金融篇": "經濟篇",
    "卷四 經濟志 工業篇、公用事業篇": "經濟篇",
    "卷四 經濟志 水產篇、林業篇、畜產篇": "經濟篇",
    "卷四 經濟志 農業篇、水利篇": "經濟篇",
    "卷五 教育誌 學校教育篇、社會教育篇": "教育與語言篇",
    "卷五 教育誌 學校篇": "教育與語言篇",
    "卷六 文化志 文獻篇、勝蹟篇": "文化篇",
    "卷七 人物誌 人物傳篇、職官表篇": "人物篇",
}

# 檔名結尾的頁碼標記，原始資料裡半形/全形底線混用，兩種都要吃
_PAGE_SUFFIX_RE = re.compile(r"[_＿]p(\d+)\s*$")


def _text_of(el: ET.Element) -> str:
    """取儲存格純文字。儲存格內常有多個 <w:p> 段落（如編號列表逐項），
    逐段落分別取文字後用換行接起來，避免不同段落的文字被直接黏在一起；
    原始文字裡偶爾夾雜的 \\ufeff（BOM）雜訊字元一併清掉。"""
    paras = el.findall(".//" + _W + "p")
    if not paras:
        paras = [el]
    lines = []
    for p in paras:
        line = "".join(t.text or "" for t in p.iter(_W + "t")).replace("﻿", "").strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _iter_docx_tables(docx_path: Path):
    """逐一 yield 單一 docx 內每個表格的 (檔名, 內文) 純文字。"""
    with zipfile.ZipFile(docx_path) as z:
        with z.open("word/document.xml") as f:
            tree = ET.parse(f)
    body = tree.getroot().find("w:body", _NS)
    for tbl in body.findall("w:tbl", _NS):
        cells_by_row = [r.findall("w:tc", _NS) for r in tbl.findall("w:tr", _NS)]
        if len(cells_by_row) < 2:
            continue
        filename = _text_of(cells_by_row[0][1]) if len(cells_by_row[0]) > 1 else ""
        body_text = _text_of(cells_by_row[1][1]) if len(cells_by_row[1]) > 1 else ""
        yield filename, body_text


def _page_from_filename(filename: str) -> str:
    m = _PAGE_SUFFIX_RE.search(filename)
    return m.group(1) if m else ""


def _split_folder_name(folder_name: str) -> tuple[str, str, str]:
    """把「卷X X志 X篇」資料夾名稱拆成 (卷期, 志名, 篇名) 三段（單一空白分隔，
    21 個資料夾全部驗證過都是這個格式，含「政事篇」而非「政事志」的命名異常也照拆）。"""
    parts = folder_name.split(" ", 2)
    if len(parts) != 3:
        return folder_name, "", ""
    return parts[0], parts[1], parts[2]


BOOK_NAME = "南投縣志"


def extract_all() -> list[dict]:
    """回傳所有段落記錄：{id, paragraph, source, book, volume, zhi, pian, title, page, categories}。"""
    docx_paths = sorted(BOOKS_DIR.glob("*/*.docx"))
    if not docx_paths:
        raise FileNotFoundError(f"找不到 docx，請確認 {BOOKS_DIR} 是否存在")

    entries: list[dict] = []
    for vol_idx, docx_path in enumerate(docx_paths, start=1):
        folder_name = docx_path.parent.name
        category = FOLDER_CATEGORY.get(folder_name)
        if category is None:
            print(f"  [警告] 資料夾「{folder_name}」沒有對應分類，整卷跳過")
            continue

        volume, zhi, pian = _split_folder_name(folder_name)

        table_idx = 0
        for filename, body_text in _iter_docx_tables(docx_path):
            if len(body_text) < config.MIN_PARAGRAPH_LENGTH:
                continue
            page = _page_from_filename(filename)
            title = _PAGE_SUFFIX_RE.sub("", filename).strip()
            source = f"{BOOK_NAME}｜{folder_name}｜{title}" if title else f"{BOOK_NAME}｜{folder_name}"

            entries.append({
                "id": f"B{vol_idx:02d}-{table_idx:03d}",
                "paragraph": body_text,
                "source": source,
                "book": BOOK_NAME,
                "volume": volume,
                "zhi": zhi,
                "pian": pian,
                "title": title,
                "page": page,
                "categories": [category],
            })
            table_idx += 1

        print(f"  [{vol_idx:02d}] {folder_name}：{table_idx} 段（分類：{category}）")

    return entries


def _append_to_csv(entries: list[dict]) -> None:
    existing_ids: set[str] = set()
    file_exists = CSV_PATH.exists()
    if file_exists:
        with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("ID"):
                    existing_ids.add(row["ID"])

    new_rows = [e for e in entries if e["id"] not in existing_ids]
    skipped = len(entries) - len(new_rows)

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 附加寫入既有檔案時不能用 utf-8-sig（會在檔案中段插入多一個 BOM），
    # 只有從零建立新檔時才需要 BOM 讓 Excel 正確辨識編碼。
    mode = "a" if file_exists else "w"
    encoding = "utf-8" if file_exists else "utf-8-sig"
    with CSV_PATH.open(mode, newline="", encoding=encoding) as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for e in new_rows:
            writer.writerow({
                "ID": e["id"],
                "段落": e["paragraph"],
                "來源文章": e["source"],
                "頁數": e["page"],
            })

    print(f"\nCSV：{CSV_PATH}")
    print(f"  新增 {len(new_rows)} 列" + (f"（略過已存在 {skipped} 列）" if skipped else ""))


def _write_review_csv(entries: list[dict]) -> None:
    """獨立輸出一份只含縣志段落的 CSV，方便人工檢查彙整內容
    （paragraphs_all_merged.csv 混了 18000+ 筆論文段落，不好直接檢視）。"""
    REVIEW_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["ID", "分類", "頁數", "書目名稱", "卷期", "志名", "篇名", "標題", "內文"]
    with REVIEW_CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in entries:
            writer.writerow({
                "ID": e["id"],
                "分類": "、".join(e["categories"]),
                "頁數": e["page"],
                "書目名稱": e["book"],
                "卷期": e["volume"],
                "志名": e["zhi"],
                "篇名": e["pian"],
                "標題": e["title"],
                "內文": e["paragraph"],
            })
    print(f"\n審閱用 CSV：{REVIEW_CSV_PATH}（{len(entries)} 筆，可直接用 Excel 開啟檢查）")


def _write_results_json(entries: list[dict]) -> None:
    records = [
        {
            "page_id": e["id"],
            "notion_id": e["id"],
            "paragraph": e["paragraph"],
            "categories": e["categories"],
            "reason": "依《南投縣志》原書篇章分類",
            "keywords": [],
            "written_to_notion": False,
            "written_at": None,
            "error": None,
        }
        for e in entries
    ]
    data = {
        "db_id": "books_南投縣志",
        "db_title": "南投縣志(2010出版)",
        "batch_id": None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "records": records,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresults JSON：{RESULTS_PATH}（{len(records)} 筆）")


def main() -> None:
    print(f"掃描：{BOOKS_DIR}")
    entries = extract_all()
    print(f"\n共抽出 {len(entries)} 段（有內文的表格）")
    _append_to_csv(entries)
    _write_review_csv(entries)
    _write_results_json(entries)


if __name__ == "__main__":
    main()
