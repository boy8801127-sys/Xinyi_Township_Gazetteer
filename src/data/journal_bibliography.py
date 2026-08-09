# -*- coding: utf-8 -*-
"""
讀 paper/期刊論文/書目資料清單.csv，組出期刊論文段落的引用格式：

    作者，〈篇名〉，《期刊名稱》，第X卷第X期（YYYY年M月）或第X期（YYYY年M月），頁起-訖。

跟論文（paper_bibliography.py）的差異：期刊書目資料本身就是使用者直接填寫的結構化
CSV，不需要像論文那樣先跑一次性腳本從 docx/xls 解析，所以這裡直接讀 CSV，不另外
產生一份 JSON 中介檔。新增期刊論文時，直接在
paper/期刊論文/書目資料清單.csv 補一列即可。
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

_BIBLIOGRAPHY_PATH = (
    Path(__file__).resolve().parent.parent.parent / "paper" / "期刊論文" / "書目資料清單.csv"
)


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    if not _BIBLIOGRAPHY_PATH.exists():
        return {}
    with open(_BIBLIOGRAPHY_PATH, encoding="utf-8-sig") as f:
        return {row["序號"]: row for row in csv.DictReader(f)}


def get_journal_bibliography(paper_index: str) -> dict | None:
    return _load().get(str(paper_index))


def _issue_clause(volume: str, issue: str) -> str:
    if not issue:
        return f"第 {volume} 卷" if volume else ""
    if issue.isdigit():
        return f"第 {volume} 卷第 {issue} 期" if volume else f"第 {issue} 期"
    # 期別非數字（例如「創刊號」），不套「第…期」樣板，直接沿用原文字
    return f"第 {volume} 卷 {issue}" if volume else issue


def format_journal_citation(paper_index: str, page: str) -> str:
    """組出期刊論文段落的 source 欄位引用格式；查無書目資料、或資料缺了作者／篇名／
    期刊名稱任一必要欄位時，都退回空字串（呼叫端應自行處理 fallback，比照
    paper_bibliography.py::format_paper_citation() 的慣例）。"""
    info = get_journal_bibliography(paper_index)
    if info is None:
        return ""

    author = (info.get("作者") or "").strip()
    title = (info.get("篇名") or "").strip()
    journal_name = (info.get("期刊名稱") or "").strip()
    if not (author and title and journal_name):
        return ""

    volume = (info.get("卷") or "").strip()
    issue = (info.get("期") or "").strip()
    year = (info.get("年") or "").strip()
    month = (info.get("月") or "").strip()

    issue_clause = _issue_clause(volume, issue)
    date_clause = f"{year} 年 {month} 月" if month else f"{year} 年"

    page_clause = ""
    if page:
        normalized_page = page.replace("–", "-").replace("—", "-")
        page_clause = f"，頁 {normalized_page}"

    return (
        f"{author}，〈{title}〉，《{journal_name}》，"
        f"{issue_clause}（{date_clause}）"
        f"{page_clause}。"
    )
