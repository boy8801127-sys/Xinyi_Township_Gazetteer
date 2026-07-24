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

第三列（圖片）：這裡先把每個表格第三列裡的內嵌圖片（如果有）一併存到
images/books/，並產出 output/images_review.csv 供人工審閱——縣志掃描頁的
「圖片」有不少其實是原本文字內容的掃描圖（跟內文重複，沒有額外資訊），
只有「真的圖片（照片/插圖）」跟「表格」才值得放進問答系統，這裡不做自動
判斷，只負責抽出來讓人工在 CSV 裡標記。真正決定哪些圖片會進入正式語料的是
promote_reviewed_images.py（讀人工標記結果，寫回 results/books_南投縣志.json）。

使用方式：
    python -m src.data.extract_books
    python -m src.data.extract_books --docx "books/02-南投縣志(2010出版)/卷一 自然志 博物篇/xxx.docx"  # 人工抽測單一 docx
"""
from __future__ import annotations

import argparse
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
IMAGES_REVIEW_CSV_PATH = ROOT / "output" / "images_review.csv"
RESULTS_PATH = ROOT / "results" / "books_南投縣志.json"
IMAGES_DIR = ROOT / "images" / "books"
CSV_FIELDNAMES = ["ID", "段落", "來源文章", "頁數"]

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R_EMBED_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
_RELS_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

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


def _load_rels(z: zipfile.ZipFile) -> dict[str, str]:
    """讀 word/_rels/document.xml.rels，回傳 relationship id -> 該 docx zip 內的
    實際路徑（Target 通常是相對 word/ 的相對路徑，例如 media/image12.png）。
    沒有這個檔案（極少數 docx 可能沒有內嵌任何物件）就回傳空 dict。"""
    try:
        with z.open("word/_rels/document.xml.rels") as f:
            tree = ET.parse(f)
    except KeyError:
        return {}
    rels = {}
    for rel in tree.getroot().findall("r:Relationship", _RELS_NS):
        rid, target = rel.get("Id"), rel.get("Target")
        if rid and target:
            rels[rid] = "word/" + target.lstrip("/")
    return rels


def _image_from_cell(cell: ET.Element, rels: dict[str, str], z: zipfile.ZipFile) -> tuple[bytes, str] | None:
    """從表格第三列（圖片欄）的儲存格找內嵌圖片（w:drawing//a:blip），透過
    r:embed 關聯 ID 查 rels 找到 word/media/ 底下的實際檔案並讀出 bytes。
    沒有圖片、或關聯 ID 查無對應檔案，就回傳 None（純文字儲存格的正常情況）。"""
    blip = cell.find(".//" + _A + "blip")
    if blip is None:
        return None
    rid = blip.get(_R_EMBED_ATTR)
    if not rid or rid not in rels:
        return None
    target = rels[rid]
    try:
        data = z.read(target)
    except KeyError:
        return None
    ext = Path(target).suffix or ".png"
    return data, ext


def _iter_docx_tables(docx_path: Path):
    """逐一 yield 單一 docx 內每個表格的 (檔名, 內文, 圖片 bytes 或 None, 副檔名)。
    圖片解析（_load_rels／_image_from_cell）跟內文一樣是同一次表格遍歷裡順便做，
    不是另外開一次 zip 重新掃描。"""
    with zipfile.ZipFile(docx_path) as z:
        with z.open("word/document.xml") as f:
            tree = ET.parse(f)
        rels = _load_rels(z)
        body = tree.getroot().find("w:body", _NS)
        for tbl in body.findall("w:tbl", _NS):
            cells_by_row = [r.findall("w:tc", _NS) for r in tbl.findall("w:tr", _NS)]
            if len(cells_by_row) < 2:
                continue
            filename = _text_of(cells_by_row[0][1]) if len(cells_by_row[0]) > 1 else ""
            body_text = _text_of(cells_by_row[1][1]) if len(cells_by_row[1]) > 1 else ""
            image_bytes, image_ext = None, ""
            if len(cells_by_row) > 2 and len(cells_by_row[2]) > 1:
                found = _image_from_cell(cells_by_row[2][1], rels, z)
                if found:
                    image_bytes, image_ext = found
            yield filename, body_text, image_bytes, image_ext


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


def extract_all(only_docx: Path | None = None) -> list[dict]:
    """回傳所有段落記錄：
    {id, paragraph, source, book, volume, zhi, pian, title, page, categories,
     has_image, image_filename}。
    only_docx 給定時只處理該單一 docx（人工抽測用），vol_idx 仍照全部 docx 清單
    排序後的位置決定，維持跟全量執行時同一套 id 編號規則，方便單獨抽測某一卷
    時 id 還是跟正式跑出來的一致。"""
    docx_paths = sorted(BOOKS_DIR.glob("*/*.docx"))
    if not docx_paths:
        raise FileNotFoundError(f"找不到 docx，請確認 {BOOKS_DIR} 是否存在")

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    image_count = 0
    for vol_idx, docx_path in enumerate(docx_paths, start=1):
        if only_docx is not None and docx_path.resolve() != only_docx.resolve():
            continue

        folder_name = docx_path.parent.name
        category = FOLDER_CATEGORY.get(folder_name)
        if category is None:
            print(f"  [警告] 資料夾「{folder_name}」沒有對應分類，整卷跳過")
            continue

        volume, zhi, pian = _split_folder_name(folder_name)

        table_idx = 0
        for filename, body_text, image_bytes, image_ext in _iter_docx_tables(docx_path):
            # 一般情況維持原本「內文太短就跳過」的門檻；但如果這格有真的圖片，
            # 就算內文（圖說）很短甚至沒有，也不能整格丟掉——縣志裡不少頁是
            # 大版面圖片配極短圖說，內文長度不能拿來判斷圖片本身有沒有價值。
            if len(body_text) < config.MIN_PARAGRAPH_LENGTH and not image_bytes:
                continue
            page = _page_from_filename(filename)
            title = _PAGE_SUFFIX_RE.sub("", filename).strip()
            source = f"{BOOK_NAME}｜{folder_name}｜{title}" if title else f"{BOOK_NAME}｜{folder_name}"
            entry_id = f"B{vol_idx:02d}-{table_idx:03d}"

            image_filename = ""
            if image_bytes:
                image_filename = f"{entry_id}{image_ext}"
                (IMAGES_DIR / image_filename).write_bytes(image_bytes)
                image_count += 1

            # 純圖片頁（表格/大版面照片）常常內文是空的，圖說全靠檔名本身
            # （title，例如「表7 南投縣主要礦場」「圖一 南投縣主要礦場分布圖」）。
            # paragraph 若整段是空的就退回用 title 頂替，title 也是空的（極少數
            # 檔名格式異常）再退回 source——不然這筆 entry 完全沒有可檢索的
            # 文字，語意搜尋永遠比對不到，圖片核准了也等於進不了系統。有實質
            # 內文就照樣用內文，不覆蓋。
            paragraph_text = body_text.strip() or title or source

            entries.append({
                "id": entry_id,
                "paragraph": paragraph_text,
                "source": source,
                "book": BOOK_NAME,
                "volume": volume,
                "zhi": zhi,
                "pian": pian,
                "title": title,
                "page": page,
                "categories": [category],
                "has_image": bool(image_filename),
                "image_filename": image_filename,
            })
            table_idx += 1

        print(f"  [{vol_idx:02d}] {folder_name}：{table_idx} 段（分類：{category}）")

    print(f"\n共抽出 {image_count} 張圖片，存於：{IMAGES_DIR}（尚未篩選，全部先存檔，"
          f"篩選交給人工，見 output/images_review.csv）")
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


_PHOTO_TITLE_KEYWORDS = ("圖", "照片")
_TABLE_TITLE_KEYWORDS = ("表",)


def _guess_image_type(title: str) -> tuple[str, str]:
    """依「標題」欄文字（通常就是原書圖說/表格自己的標題，例如「表3-2-1」
    「圖3-5」）粗略猜 photo／table 兩欄要不要預先勾——只是給人工審閱一個起點，
    最終還是要人工核對；沒中任何關鍵字就兩欄都留空，交給人工自己判斷。"""
    is_photo = any(kw in title for kw in _PHOTO_TITLE_KEYWORDS)
    is_table = any(kw in title for kw in _TABLE_TITLE_KEYWORDS)
    return ("V" if is_photo else ""), ("V" if is_table else "")


def _load_existing_review(path: Path) -> dict[str, tuple[str, str]]:
    """讀舊版 images_review.csv 的 photo／table 欄位（如果存在），供重跑
    extract_books.py 時保留人工審閱結果用。檔案不存在（第一次跑）就回傳空
    dict，沒有任何特殊處理。"""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {
            row["ID"]: (row.get("photo", ""), row.get("table", ""))
            for row in csv.DictReader(f)
            if row.get("ID")
        }


def _write_images_review_csv(entries: list[dict]) -> None:
    """圖片人工審閱用 CSV：對照 images/books/ 資料夾（用檔案總管切成縮圖檢視
    最快），在 photo／table 兩欄核對——依標題關鍵字預先勾好初步猜測（見
    _guess_image_type），人工看過縮圖後修正：猜錯的清空，漏勾的補上 V；
    兩欄都空白（不管是本來就沒猜中、還是人工看過確認不是）就代表這張圖不放
    進系統。這裡只負責產出清單＋初步猜測，不做最終篩選——真正決定哪些圖片
    進入正式語料的是 promote_reviewed_images.py，讀這份 CSV 的最終標記結果。
    ID 照抽取順序（跟 images/books/ 資料夾內檔名排序一致）方便對照。

    **重跑安全**：extract_books.py 本來就設計成可以重跑（例如新增了 docx 卷、
    或後續要幫論文 PDF 也加圖片支援），但這支函式以前是每次都整份重寫、無條件
    蓋掉這個 CSV——結果實際發生過一次事故：為了把新抽出的縣志段落 append
    進論文段落 CSV 而重跑一次 extract_books.py，連帶把已經人工審閱完的
    photo／table 標記整個蓋回沒有人工核對過的初步猜測，等於白費了一輪人工
    審閱。現在改成：舊檔案裡任何 ID 只要已經有人工標記過（不論是空白或
    有勾），一律原封不動保留；只有全新出現、舊檔案裡完全沒有這個 ID 的列，
    才套用 _guess_image_type() 的初步猜測。"""
    rows = [e for e in entries if e["has_image"]]
    IMAGES_REVIEW_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing_review = _load_existing_review(IMAGES_REVIEW_CSV_PATH)
    fieldnames = ["ID", "頁數", "書目名稱", "卷期", "志名", "篇名", "標題", "圖片檔名", "photo", "table"]
    guessed_photo = guessed_table = 0
    kept_from_existing = 0
    with IMAGES_REVIEW_CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in rows:
            if e["id"] in existing_review:
                photo_mark, table_mark = existing_review[e["id"]]
                kept_from_existing += 1
            else:
                photo_mark, table_mark = _guess_image_type(e["title"])
                guessed_photo += bool(photo_mark)
                guessed_table += bool(table_mark)
            writer.writerow({
                "ID": e["id"],
                "頁數": e["page"],
                "書目名稱": e["book"],
                "卷期": e["volume"],
                "志名": e["zhi"],
                "篇名": e["pian"],
                "標題": e["title"],
                "圖片檔名": e["image_filename"],
                "photo": photo_mark,
                "table": table_mark,
            })
    print(f"\n圖片審閱用 CSV：{IMAGES_REVIEW_CSV_PATH}（{len(rows)} 張圖片）")
    if kept_from_existing:
        print(f"  沿用既有人工審閱結果：{kept_from_existing} 列（不會被這次重跑覆蓋）")
    print(
        f"  新出現、套用標題關鍵字初步猜測：photo {guessed_photo} 張、"
        f"table {guessed_table} 張，僅供起點，仍需人工核對\n"
        f"  請對照 {IMAGES_DIR} 資料夾（檔案總管切成「特大圖示」縮圖檢視），"
        f"核對／修正 photo／table 兩欄（填 V 代表勾選，清空代表不勾——兩欄都"
        f"空白就是這張圖不放進系統），填完存檔後執行："
        f"python -m src.data.promote_reviewed_images"
    )


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
    parser = argparse.ArgumentParser(description="抽取《南投縣志》docx 段落與圖片")
    parser.add_argument(
        "--docx", type=Path, default=None,
        help="只處理單一 docx（人工抽測用，例：books/02-南投縣志(2010出版)/卷一 自然志 博物篇/xxx.docx），"
             "預設處理 books/02-南投縣志(2010出版)/ 底下全部 docx",
    )
    args = parser.parse_args()

    print(f"掃描：{BOOKS_DIR}")
    entries = extract_all(only_docx=args.docx)
    print(f"\n共抽出 {len(entries)} 段（有內文或圖片的表格）")
    _append_to_csv(entries)
    _write_review_csv(entries)
    _write_images_review_csv(entries)
    _write_results_json(entries)


if __name__ == "__main__":
    main()
