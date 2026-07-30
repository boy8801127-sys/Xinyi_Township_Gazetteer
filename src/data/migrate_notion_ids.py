# -*- coding: utf-8 -*-
"""
一次性腳本：把 Notion 資料庫裡論文段落頁面的 "ID" 欄位（title 型別）從舊格式
（P11-200）批次更新成新格式（98-11-200），沿用 notion_classify.py 既有的
notion_client.Client 與寫入節流（0.35 秒／次，比照 Notion API 速率限制）。

縣志段落從未寫入過 Notion（extract_books.py 這條線不經過 Notion 人工整理），
不在這支腳本的處理範圍——只處理 output/id_migration_map.csv 裡 is_notion_uuid
為 True 的列（共 12,667 筆論文段落）。

12,667 次 API 呼叫在 0.35 秒節流下約需 70~80 分鐘，設計成可斷點續傳：
已成功的 page_id 會記進 output/notion_id_migration_progress.jsonl，
中斷後重跑會自動跳過已完成的部分。

使用方式：
    python -m src.data.migrate_notion_ids
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from notion_client import Client

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "output" / "id_migration_map.csv"
PROGRESS_PATH = ROOT / "output" / "notion_id_migration_progress.jsonl"
SLEEP_SECONDS = 0.35

notion = Client(auth=os.environ["NOTION_API_KEY"])


def _load_rows() -> list[dict]:
    if not MAP_PATH.exists():
        raise FileNotFoundError(f"找不到 {MAP_PATH}，請先執行：python -m src.data.migrate_ids")
    rows = []
    with MAP_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["is_notion_uuid"] == "True":
                rows.append(row)
    return rows


def _load_done_page_ids() -> set[str]:
    if not PROGRESS_PATH.exists():
        return set()
    done = set()
    with PROGRESS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("status") == "ok":
                done.add(rec["page_id"])
    return done


def _append_progress(page_id: str, new_id: str, status: str, error: str = "") -> None:
    with PROGRESS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"page_id": page_id, "new_id": new_id, "status": status, "error": error},
                            ensure_ascii=False) + "\n")


def migrate() -> None:
    rows = _load_rows()
    done = _load_done_page_ids()
    todo = [r for r in rows if r["page_id"] not in done]

    print(f"需更新的論文段落頁面共 {len(rows)} 筆，已完成 {len(done)} 筆，本次待處理 {len(todo)} 筆")
    if not todo:
        print("沒有需要處理的頁面，結束。")
        return

    ok = fail = 0
    for i, row in enumerate(todo, 1):
        page_id, new_id = row["page_id"], row["new_id"]
        try:
            notion.pages.update(
                page_id=page_id,
                properties={"ID": {"title": [{"type": "text", "text": {"content": new_id}}]}},
            )
            _append_progress(page_id, new_id, "ok")
            ok += 1
        except Exception as e:  # noqa: BLE001 - 單筆失敗要能繼續跑完剩下的，不中止整批
            _append_progress(page_id, new_id, "error", str(e))
            fail += 1
            print(f"失敗：{page_id} -> {new_id}：{e}")
        if i % 200 == 0:
            print(f"進度：{i}/{len(todo)}（成功 {ok}，失敗 {fail}）")
        time.sleep(SLEEP_SECONDS)

    print(f"\n完成。本次成功 {ok} 筆，失敗 {fail} 筆。"
          f"{'失敗的頁面重跑本腳本即可再試一次。' if fail else ''}")


if __name__ == "__main__":
    migrate()
