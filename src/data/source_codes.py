# -*- coding: utf-8 -*-
"""
語料庫 id／source 欄位的來源代碼表：id 格式為 `{來源代碼}-{原序號}-{段落序號}`
（例：論文段落 `98-11-200`、縣志段落 `92-01-079`），代碼對應下表。

之後新增其他來源類型的資料時，先在 SOURCE_CODES 確認代碼／名稱，若該來源要在
UI／CLI 上有自己的粗分類（而不是併入既有的「論文」「書籍」「其他」），
再到 SOURCE_TYPE_DISPLAY 補一行對照。
"""
from __future__ import annotations

SOURCE_CODES: dict[str, str] = {
    "91": "信義鄉公所檔案",
    "92": "南投縣志稿＆南投縣志＆續修南投縣志",
    "93": "理蕃之友＆理蕃誌稿",
    "94": "政府公報",
    "95": "臺灣總督府公文類纂",
    "96": "國資圖數位典藏資料庫",
    "97": "華藝",
    "98": "信義鄉布農族博碩士論文",
    "99": "其他",
    "100": "國史館檔案史料文物",
    "101": "文獻資料",
    "102": "信義鄉歷年預算決算",
    "103": "信義鄉歷年施政計畫",
    "104": "南投歷史老照片",
}

# 目前站上 UI／CLI 的來源類型篩選只有「論文」「書籍」二分類，其餘代碼的資料
# 上線前，先決定它該併入既有分類還是新增分類，再在這裡補上對照，否則一律落入「其他」。
SOURCE_TYPE_DISPLAY: dict[str, str] = {
    "98": "論文",
    "97": "論文",  # 期刊論文，性質上跟學位論文一樣是學術論文，併入同一粗分類
    "92": "書籍",
}

_DEFAULT_SOURCE_TYPE = "其他"

# 哪些來源代碼的 source 欄位本身已經內含頁碼（例如論文的腳註格式「...，頁 12。」，
# 見 src/data/paper_bibliography.py::format_paper_citation()）。顯示引用時如果
# 還另外加印「第 X 頁」會造成頁碼重複，這裡集中管理，之後新增的來源類型如果
# 也採用內含頁碼的格式，記得加進這個集合。
_SOURCE_INCLUDES_PAGE = {"98", "97"}


def code_of(entry_id: str) -> str:
    """從 `{代碼}-{原序號}-{段落序號}` 格式的 id 取出來源代碼。"""
    return entry_id.split("-", 1)[0]


def source_type_for_id(entry_id: str) -> str:
    """回傳給 UI／CLI 篩選用的粗分類名稱，未對照到的代碼一律回傳「其他」。"""
    return SOURCE_TYPE_DISPLAY.get(code_of(entry_id), _DEFAULT_SOURCE_TYPE)


def citation_includes_page(entry_id: str) -> bool:
    """source 欄位本身是否已經內含頁碼，顯示引用時要不要再另外加印「第 X 頁」看這裡。"""
    return code_of(entry_id) in _SOURCE_INCLUDES_PAGE
