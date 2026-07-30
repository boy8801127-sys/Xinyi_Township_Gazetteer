# -*- coding: utf-8 -*-
"""
讀 paper_bibliography.json（由 build_paper_bibliography.py 一次性產生），
組出論文段落的腳註引用格式：

    作者，〈篇名〉（學校地：系所，畢業年），頁{起訖頁碼}。

「起訖頁碼」不是整篇論文的頁碼，是呼叫端傳入的、該段落自己的 page 欄位值。

新增論文（不在 paper_bibliography.json 裡的論文序號）時，直接照同樣 schema
在 paper_bibliography.json 手動補一筆即可，不需要重跑 build_paper_bibliography.py：
    {"<論文序號>": {"author": ..., "title": ..., "school": ..., "department": ...,
                    "degree": "碩士"|"博士", "year_ad": <西元年 int>, "city": ...}}
"""
from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache

_BIBLIOGRAPHY_PATH = Path(__file__).resolve().parent / "paper_bibliography.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    if not _BIBLIOGRAPHY_PATH.exists():
        return {}
    return json.loads(_BIBLIOGRAPHY_PATH.read_text(encoding="utf-8"))


def get_paper_bibliography(paper_index: str) -> dict | None:
    return _load().get(str(paper_index))


def format_paper_citation(paper_index: str, page: str) -> str:
    """組出論文段落的 source 欄位腳註格式；查無書目資料時退回空字串（呼叫端應自行處理 fallback）。"""
    info = get_paper_bibliography(paper_index)
    if info is None:
        return ""

    page_clause = ""
    if page:
        normalized_page = page.replace("–", "-").replace("—", "-")
        page_clause = f"，頁 {normalized_page}"

    return (
        f"{info['author']}，〈{info['title']}〉"
        f"（{info['city']}：{info['school']}{info['department']}{info['degree']}論文，{info['year_ad']} 年）"
        f"{page_clause}。"
    )
