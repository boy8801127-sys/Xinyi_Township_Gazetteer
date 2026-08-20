# -*- coding: utf-8 -*-
"""把已經分類好的本機 CSV（理蕃之友／理蕃誌稿，來源代碼 93）匯入 Notion，建成一個
child database 供人工複核。

跟 import_paragraphs_to_notion.py（學位論文專用）不同：
    1. CSV 欄位不一樣：id／paragraph(內文)／source(資料來源)／page(頁數)／
       categories／reason／keywords／images／備註，是 classify_csv_with_gemini.py
       填好分類結果的成果，不是論文的 ID／段落／頁數／來源文章。
    2. 分類結果已經在本機 CSV 裡填好了，建立頁面時直接一次連分類（分類／分類原因／
       關鍵字）一起寫入，不像論文流程要先建空白頁面、之後再另外跑
       classify_*_with_gemini.py 補分類。
    3. 沒有「論文序號 41 以後放第 2 個母頁面」這種規則（那是論文流程專屬的既有
       慣例），母頁面預設用 NOTION_DATABASE_ID_1，可用 --parent 覆蓋。

寫回 Notion 用的分類屬性名稱（分類／分類原因／關鍵字）、multi_select 選項清理規則
直接沿用 notion_classify.py 的 PROP_CATEGORY／PROP_REASON／PROP_KEYWORDS／
_sanitize_option，rich_text 分段規則沿用 import_paragraphs_to_notion.py 的
_rich_text，都不重寫（平行實驗模組慣例），確保之後能被同一套 parse_page() 讀回。

比照 import_paragraphs_to_notion.py 已經修過的坑：中途失敗不會留孤兒 database，
可以用 --database-id 續傳（自動跳過已匯入的列，不會重建重複的 database）。

用法：
    python -m src.data.import_csv_to_notion <csv_path> [<csv_path> ...] --dry-run
    python -m src.data.import_csv_to_notion <csv_path> [<csv_path> ...] --run
    python -m src.data.import_csv_to_notion <csv_path> [<csv_path> ...] --database-id <db_id> --run
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import notion_classify as nc

from .import_paragraphs_to_notion import _rich_text

SLEEP_BETWEEN_PAGES = 0.35

HEADER = [
    "來源代碼", "id", "paragraph(內文)", "source(資料來源)", "page(頁數)",
    "categories", "reason", "keywords", "images", "備註",
]
_COL = {name: i for i, name in enumerate(HEADER)}
LIST_SPLIT = "、"


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    data_rows = [r for r in rows[2:] if any(c.strip() for c in r)]
    data_rows = [r + [""] * (len(HEADER) - len(r)) if len(r) < len(HEADER) else r for r in data_rows]
    out = [dict(zip(HEADER, r)) for r in data_rows]
    missing_id = [r for r in out if not r["id"].strip()]
    if missing_id:
        raise SystemExit(
            f"{csv_path} 有 {len(missing_id)} 筆 id 欄位是空的，先跑完 id 編號才能匯入 Notion。"
        )
    return out


def make_db_title(csv_path: Path) -> str:
    return f"S93_{csv_path.stem}_{datetime.now():%Y_%m_%d}"


def create_database(parent_page_id: str, title: str) -> tuple[str, str]:
    db = nc.notion.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": title}}],
        initial_data_source={
            "properties": {
                "ID": {"title": {}},
                "段落": {"rich_text": {}},
                "頁數": {"rich_text": {}},
                nc.PROP_CATEGORY: {"multi_select": {}},
                nc.PROP_REASON: {"rich_text": {}},
                nc.PROP_KEYWORDS: {"multi_select": {}},
            }
        },
    )
    return db["id"], db["data_sources"][0]["id"]


def _existing_ids(ds_id: str) -> set[str]:
    ids: set[str] = set()
    cursor = None
    while True:
        kwargs: dict = {"page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = nc.notion.data_sources.query(ds_id, **kwargs)
        for page in resp.get("results", []):
            ids.add(nc.parse_page(page)["notion_id"])
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return ids


def create_pages(ds_id: str, rows: list[dict[str, str]]) -> int:
    created = 0
    for i, row in enumerate(rows, 1):
        cats = [nc._sanitize_option(c) for c in row["categories"].split(LIST_SPLIT) if c.strip()]
        kws = [nc._sanitize_option(k) for k in row["keywords"].split(LIST_SPLIT) if k.strip()]
        nc.notion.pages.create(
            parent={"type": "data_source_id", "data_source_id": ds_id},
            properties={
                "ID": {"title": [{"type": "text", "text": {"content": row["id"].strip()}}]},
                "段落": {"rich_text": _rich_text(row["paragraph(內文)"])},
                "頁數": {"rich_text": _rich_text(row["page(頁數)"])},
                nc.PROP_CATEGORY: {"multi_select": [{"name": c} for c in cats]},
                nc.PROP_REASON: {"rich_text": _rich_text(row["reason"])},
                nc.PROP_KEYWORDS: {"multi_select": [{"name": k} for k in kws]},
            },
        )
        created += 1
        time.sleep(SLEEP_BETWEEN_PAGES)
        if i % 20 == 0 or i == len(rows):
            print(f"  已建立 {i}/{len(rows)} 筆", flush=True)
    return created


def run(csv_path: Path, database_id: str | None, parent_page_id: str | None, dry_run: bool) -> None:
    rows = load_rows(csv_path)
    title = make_db_title(csv_path)

    print(f"來源 CSV：{csv_path}")
    print(f"段落筆數：{len(rows)}（ID {rows[0]['id']} ~ {rows[-1]['id']}）")
    if database_id:
        print(f"續傳模式，接續匯入到既有 database：{database_id}")
    else:
        resolved_parent = parent_page_id or os.environ.get("NOTION_DATABASE_ID_1") or os.environ.get("NOTION_DATABASE_ID", "")
        print(f"目標母頁面：{resolved_parent or '（未設定，執行時會報錯）'}")
        print(f"將建立 database：{title}")

    if dry_run:
        print("\n[dry-run] 未實際寫入 Notion。前 3 筆預覽：")
        for r in rows[:3]:
            print(f"  {r['id']} | 頁 {r['page(頁數)']} | {r['categories']} | {r['paragraph(內文)'][:50]}…")
        return

    if database_id:
        db_id = database_id
        ds_id = nc.get_data_source_id(db_id)
        existing_ids = _existing_ids(ds_id)
    else:
        parent = parent_page_id or os.environ.get("NOTION_DATABASE_ID_1") or os.environ.get("NOTION_DATABASE_ID", "")
        if not parent:
            raise SystemExit("找不到母頁面 ID，請用 --parent 指定或在 .env 設定 NOTION_DATABASE_ID_1")
        db_id, ds_id = create_database(parent, title)
        print(f"\n已建立 database：{db_id}")
        print(f"data_source_id：{ds_id}")
        existing_ids = set()

    todo_rows = [r for r in rows if r["id"].strip() not in existing_ids]
    if existing_ids:
        print(f"（續傳模式：{len(rows) - len(todo_rows)} 筆先前已匯入，自動略過）")
    if not todo_rows:
        print("\n沒有需要新增的頁面（全部已匯入過）。")
        return

    try:
        created = create_pages(ds_id, todo_rows)
    except Exception:
        print(
            f"\n⚠️ 匯入中途失敗，database_id={db_id} 已保留，"
            f"可加 --database-id {db_id} 重跑續傳（已匯入的列會自動略過，不會重複建立、不會產生新 database）。"
        )
        raise

    print(f"\n完成，共建立 {created} 筆頁面。")


def main() -> int:
    parser = argparse.ArgumentParser(description="把已分類好的 CSV（來源代碼 93）匯入 Notion 建成 child database")
    parser.add_argument("csv_paths", nargs="+", help="一或多個已填好 id／分類的卷別 CSV")
    parser.add_argument(
        "--parent", default=None,
        help="母頁面 ID；預設用 .env 的 NOTION_DATABASE_ID_1（沒有論文序號規則，跟論文流程不同）",
    )
    parser.add_argument(
        "--database-id", default=None,
        help="續傳模式：只能搭配單一個 csv_path 使用，中途失敗後重跑，接續匯入到既有的 database",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只檢查與預覽，不寫入 Notion")
    group.add_argument("--run", action="store_true", help="實際寫入 Notion")
    args = parser.parse_args()

    paths = [Path(p) for p in args.csv_paths]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"找不到檔案：{', '.join(str(p) for p in missing)}")
    if args.database_id and len(paths) > 1:
        raise SystemExit("--database-id 續傳模式一次只能指定一個 csv_path")

    for p in paths:
        run(p, args.database_id, args.parent, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
