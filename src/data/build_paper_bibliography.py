# -*- coding: utf-8 -*-
"""
一次性腳本：解析 `paper/信義鄉布農族博碩士論文.docx`（論文書目清單，88 筆純文字段落）
與 `paper/台灣大專院校地址名冊.xls`（教育部大專校院名錄，含縣市欄位），組出
`src/data/paper_bibliography.json`（論文序號 -> 作者／篇名／學校／系所／學位／
西元畢業年／城市），供 paper_bibliography.py 的 format_paper_citation() 使用。

只需在 88 筆論文清單或名冊有更新時重新執行一次：
    python -m src.data.build_paper_bibliography

之後新增的論文（不在這份 88 筆 docx 清單裡）不需要重跑本腳本，直接手動在
paper_bibliography.json 補一筆同樣 schema 的資料即可。
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
DOCX_PATH = ROOT / "paper" / "信義鄉布農族博碩士論文.docx"
ROSTER_XLS_PATH = ROOT / "paper" / "台灣大專院校地址名冊.xls"
PAPER_DIR = ROOT / "paper"
OUTPUT_PATH = ROOT / "src" / "data" / "paper_bibliography.json"

_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_SEQ_RE = re.compile(r"^\d+\.$")
_SCHOOL_LINE_RE = re.compile(r"／")
_ADVISOR_STUDENT_RE = re.compile(r"^研究生[:：]\s*(.+)$")
_PDF_PREFIX_RE = re.compile(r"^0*(\d+)-")
_PAREN_SUFFIX_RE = re.compile(r"\([^)]*\)\s*$")

# 名冊裡查無（已改制／合併，不在最新學年度名錄裡）的學校，人工補上所在縣市。
SCHOOL_CITY_OVERRIDES = {
    "台灣神學研究學院": "臺北市",
    "國立交通大學": "新竹市",
    "國立新竹教育大學": "新竹市",
    "國立臺灣體育大學(桃園)": "桃園市",
    "臺中師範學院": "臺中市",
}


def _docx_paragraph_texts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    texts = []
    for p in root.findall(".//w:body/w:p", _NS):
        runs = p.findall(".//w:t", _NS)
        texts.append("".join(r.text or "" for r in runs))
    return texts


def _parse_papers(texts: list[str]) -> dict[str, dict]:
    """回傳 {論文序號(docx 原始序號 "1".."88"): {title, school, department, degree, year_ad, author}}"""
    papers: dict[str, dict] = {}
    i = 0
    n = len(texts)
    while i < n:
        t = texts[i].strip()
        if not _SEQ_RE.match(t):
            i += 1
            continue
        seq = t.rstrip(".")

        title = None
        school = department = degree = year_ad = None
        author = None

        j = i + 1
        window_end = min(n, i + 8)
        while j < window_end:
            line = texts[j].strip()
            if not line:
                j += 1
                continue
            if title is None:
                title = line
            elif _SCHOOL_LINE_RE.search(line) and ("碩士" in line or "博士" in line):
                parts = line.split("／")
                if len(parts) >= 4:
                    school, department, year_roc, degree = parts[0], parts[1], parts[2], parts[3]
                    year_ad = int(year_roc) + 1911
            elif _ADVISOR_STUDENT_RE.match(line):
                author = _ADVISOR_STUDENT_RE.match(line).group(1).strip()
            if school is not None and author is not None:
                break
            if _SEQ_RE.match(line):
                break
            j += 1

        if title and school and author and year_ad:
            papers[seq] = {
                "title": title,
                "school": school,
                "department": department,
                "degree": degree,
                "year_ad": year_ad,
                "author": author,
            }
        i = j
    return papers


def _load_school_city_table() -> dict[str, str]:
    import pandas as pd

    df = pd.read_excel(ROSTER_XLS_PATH, sheet_name="大專校院名錄", engine="xlrd", header=None, skiprows=2)
    df.columns = ["代碼", "學校名稱", "公私立", "縣市代碼", "縣市名稱", "地址", "電話", "網址", "體系別"]
    table = dict(zip(df["學校名稱"], df["縣市名稱"]))
    table.update(SCHOOL_CITY_OVERRIDES)
    return table


def _imported_paper_indices() -> set[str]:
    indices = set()
    for f in PAPER_DIR.glob("*.pdf"):
        m = _PDF_PREFIX_RE.match(f.name)
        if m:
            indices.add(m.group(1))
    return indices


def _short_city(city: str) -> str:
    return city.rstrip("市縣")


def build() -> None:
    texts = _docx_paragraph_texts(DOCX_PATH)
    papers = _parse_papers(texts)
    city_table = _load_school_city_table()
    imported = _imported_paper_indices()

    result: dict[str, dict] = {}
    missing_city = []
    for seq, info in papers.items():
        if seq not in imported:
            continue
        school_key = info["school"]
        city = city_table.get(school_key)
        if city is None:
            # 去掉尾端括號註記後再試一次（如「國立臺灣體育大學(桃園)」已在 override 裡處理，
            # 這裡是保險，避免未來新論文的學校名帶類似註記卻沒被 override 收錄）。
            stripped = _PAREN_SUFFIX_RE.sub("", school_key).strip()
            city = city_table.get(stripped)
        if city is None:
            missing_city.append((seq, school_key))
            continue

        result[seq] = {
            "author": info["author"],
            "title": info["title"],
            "school": _PAREN_SUFFIX_RE.sub("", info["school"]).strip(),
            "department": info["department"],
            "degree": info["degree"],
            "year_ad": info["year_ad"],
            "city": _short_city(city),
        }

    OUTPUT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"論文清單解析出：{len(papers)} 筆")
    print(f"實際有匯入 PDF：{len(imported)} 筆")
    print(f"成功寫入書目資料：{len(result)} 筆 -> {OUTPUT_PATH}")
    if missing_city:
        print(f"缺城市對照（未寫入，需人工補 SCHOOL_CITY_OVERRIDES）：{missing_city}")
    skipped = imported - set(result.keys())
    if skipped:
        print(f"有 PDF 但書目資料不完整而跳過：{sorted(skipped, key=int)}")


if __name__ == "__main__":
    build()
