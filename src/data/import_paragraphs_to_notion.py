# -*- coding: utf-8 -*-
"""把單篇論文的最終段落 CSV 匯入 Notion，建成一個 child database 供後續分類使用。

補的是既有流程裡唯一沒有腳本的那一步：`output/*_final.csv` →（人工在 Notion 匯入）→
`notion_classify.py`／`classify_*_with_gemini.py` 分類。既有 54 篇學位論文與期刊論文
當初都是手動匯入的，段落數少時還好，這支讓它可以直接跑。

建出來的 database 結構完全比照既有那 54 個（欄位名稱、型別、命名慣例都一樣），
所以 `notion_classify.list_child_databases()` 跟分類腳本可以無縫接上：

    ID（title）／段落（rich_text）／頁數（rich_text）
    分類（multi_select）／分類原因（rich_text）／關鍵字（multi_select）

命名慣例：`P{論文序號}_{PDF檔名}_{YYYY_MM_DD}`，掛在 `.env` 的 NOTION_DATABASE_ID_1／
NOTION_DATABASE_ID_2 兩個母頁面之一（既有慣例：序號 41 以後放第 2 個）——這支預設會
依 CSV 裡的論文序號自動選對應的母頁面，不用每次手動帶 `--parent`。

中途失敗（Notion API 逾時／速率限制）不會留下孤兒 database：`create_pages()` 的例外
會被 `run()` 接住，印出目前的 database_id，並提示改用 `--database-id` 續傳——續傳時
會先查詢該 database 底下已存在的頁面 ID，自動跳過已匯入的列，不會重跑 `create_database()`
產生第二個重複的 database。

用法：
    python -m src.data.import_paragraphs_to_notion output/paragraphs_paper_98-81_final.csv --dry-run
    python -m src.data.import_paragraphs_to_notion output/paragraphs_paper_98-81_final.csv --run
    # 中途失敗後續傳（db_id 用失敗訊息印出的那個）：
    python -m src.data.import_paragraphs_to_notion output/paragraphs_paper_98-81_final.csv --database-id <db_id> --run
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

from dotenv import load_dotenv

import notion_classify as nc

load_dotenv()

# Notion 單一 rich_text block 的字數上限，超過要拆成多個 block（同一個欄位可以放
# 多個 block，讀出來會自動接回一整段，見 notion_classify._extract_text()）。
RICH_TEXT_LIMIT = 2000

# 建完 database 之後每筆頁面之間的間隔，避免撞 Notion API 速率限制（比照
# notion_classify.write_record_to_notion() 的 0.35 秒）。
SLEEP_BETWEEN_PAGES = 0.35


def _rich_text(text: str) -> list[dict]:
    text = text or ""
    if not text:
        return []
    return [
        {"type": "text", "text": {"content": text[i : i + RICH_TEXT_LIMIT]}}
        for i in range(0, len(text), RICH_TEXT_LIMIT)
    ]


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("ID") or "").strip()]
    if not rows:
        raise SystemExit(f"{csv_path} 沒有任何有 ID 的資料列")
    return rows


def _paper_index_str(rows: list[dict[str, str]]) -> str:
    """從第一列的 ID（{來源代碼}-{論文序號}-{段落序號}）取出論文序號，維持原始
    字串（含可能的前導零），供組標題用；比較大小的地方另外轉 int（見
    `_default_parent_for_index()`）。只看第一列——若同一份 CSV 混了不同論文的
    列，這裡不會發現，仍會用第一列的序號當整份的標題／母頁面依據。"""
    return rows[0]["ID"].strip().split("-")[1]


def make_db_title(rows: list[dict[str, str]]) -> str:
    """比照既有慣例組出 database 標題：P{論文序號}_{PDF檔名}_{YYYY_MM_DD}。"""
    paper_index = _paper_index_str(rows)
    source = (rows[0].get("來源文章") or "").strip()
    return f"P{paper_index}_{source}_{datetime.now():%Y_%m_%d}"


def _default_parent_for_index(paper_index: str) -> str:
    """既有慣例：論文序號 41 以後放第 2 個母頁面。env var 命名比照
    `notion_classify.py::_get_all_page_ids()` 的 fallback 順序（NOTION_DATABASE_ID_1
    沒設定就退回舊的 NOTION_DATABASE_ID）。"""
    if int(paper_index) >= 41:
        return os.environ.get("NOTION_DATABASE_ID_2", "")
    return os.environ.get("NOTION_DATABASE_ID_1") or os.environ.get("NOTION_DATABASE_ID", "")


def _existing_ids(ds_id: str) -> set[str]:
    """續傳模式用：查詢這個 data source 底下已經存在的頁面 ID，匯入時用來跳過
    已經匯入過的列，避免重複建立。沿用 notion_classify.py 的 parse_page()，不
    自己重新解析 title property。"""
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


def create_database(parent_page_id: str, title: str) -> tuple[str, str]:
    """在母頁面底下建立 child database，回傳 (database_id, data_source_id)。"""
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


def create_pages(ds_id: str, rows: list[dict[str, str]]) -> int:
    created = 0
    for i, row in enumerate(rows, 1):
        nc.notion.pages.create(
            parent={"type": "data_source_id", "data_source_id": ds_id},
            properties={
                "ID": {"title": [{"type": "text", "text": {"content": row["ID"].strip()}}]},
                "段落": {"rich_text": _rich_text(row.get("段落", ""))},
                "頁數": {"rich_text": _rich_text(str(row.get("頁數", "") or ""))},
            },
        )
        created += 1
        time.sleep(SLEEP_BETWEEN_PAGES)
        if i % 20 == 0 or i == len(rows):
            print(f"  已建立 {i}/{len(rows)} 筆", flush=True)
    return created


def run(csv_path: Path, database_id: str | None, parent_page_id: str | None, dry_run: bool) -> None:
    rows = load_rows(csv_path)
    paper_index = _paper_index_str(rows)
    title = make_db_title(rows)
    over_limit = [r["ID"] for r in rows if len(r.get("段落", "")) > RICH_TEXT_LIMIT]

    print(f"來源 CSV：{csv_path}")
    print(f"段落筆數：{len(rows)}（ID {rows[0]['ID']} ~ {rows[-1]['ID']}）")
    if database_id:
        print(f"續傳模式，接續匯入到既有 database：{database_id}")
    else:
        resolved_parent = parent_page_id or _default_parent_for_index(paper_index)
        print(f"目標母頁面：{resolved_parent or '（未設定，執行時會報錯）'}")
        print(f"將建立 database：{title}")
    if over_limit:
        print(f"（{len(over_limit)} 筆段落超過 {RICH_TEXT_LIMIT} 字，會自動拆成多個 rich_text block）")

    if dry_run:
        print("\n[dry-run] 未實際寫入 Notion。前 3 筆預覽：")
        for r in rows[:3]:
            print(f"  {r['ID']} | 頁 {r.get('頁數','')} | {r.get('段落','')[:60]}…")
        return

    if database_id:
        db_id = database_id
        ds_id = nc.get_data_source_id(db_id)
        existing_ids = _existing_ids(ds_id)
    else:
        parent = parent_page_id or _default_parent_for_index(paper_index)
        if not parent:
            env_name = "NOTION_DATABASE_ID_2" if int(paper_index) >= 41 else "NOTION_DATABASE_ID_1"
            raise SystemExit(
                f"找不到母頁面 ID：論文序號 {paper_index} 依慣例應該用 {env_name}，"
                "請在 .env 設定或用 --parent 指定"
            )
        db_id, ds_id = create_database(parent, title)
        print(f"\n已建立 database：{db_id}")
        print(f"data_source_id：{ds_id}")
        existing_ids = set()

    todo_rows = [r for r in rows if r["ID"].strip() not in existing_ids]
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
    print(f"接著執行分類：python -m src.data.classify_paper_with_gemini {db_id} --estimate-cost")


def main() -> int:
    parser = argparse.ArgumentParser(description="把最終段落 CSV 匯入 Notion 建成 child database")
    parser.add_argument("csv_path", help="最終段落 CSV（例：output/paragraphs_paper_98-81_final.csv）")
    parser.add_argument(
        "--parent", default=None,
        help="母頁面 ID；預設依 CSV 裡的論文序號自動選 .env 的 NOTION_DATABASE_ID_1／_2"
             "（既有慣例：序號 41 以後放第 2 個），這個參數可以覆蓋自動判斷",
    )
    parser.add_argument(
        "--database-id", default=None,
        help="續傳模式：中途失敗後重跑，接續匯入到既有的 database（已匯入的列自動略過），"
             "不會再建立新的 database；跟 --parent 互斥（有 --database-id 就不需要 --parent）",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只檢查與預覽，不寫入 Notion")
    group.add_argument("--run", action="store_true", help="實際寫入 Notion")
    args = parser.parse_args()

    run(Path(args.csv_path), args.database_id, args.parent, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
