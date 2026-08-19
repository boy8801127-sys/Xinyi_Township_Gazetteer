# -*- coding: utf-8 -*-
"""用 Gemini 對「單篇學位論文」（來源代碼 98）的 Notion 段落做分類與關鍵字擷取。

跟 `classify_journal_with_gemini.py`（期刊論文／代碼 97）是同一套做法，差別只有兩點：

1. results 檔名不寫死。期刊那批是一次匯進「單一資料庫」，所以那支把
   `RESULTS_TITLE` 寫成常數 `"期刊論文_97"`；學位論文是「每篇一個 child database」
   （既有 54 篇都是 `results/P{序號}_{檔名}_{日期}.json`），所以這裡改成從 Notion
   讀該 database 的實際標題當檔名，自動跟既有慣例對齊。
2. 分類邏輯／SYSTEM_PROMPT／定價估算全部直接 import 沿用，不複製也不改動那兩支
   （平行實驗模組慣例）。

為什麼學位論文這次不用原本的 `notion_classify.py`（Claude）：既有 60 篇當初是用
Claude 分類的，但 2026-07 起期刊那批改用 Gemini flash-lite 實測品質相當、成本約
1/8，這篇沿用同樣的選型。

用法：
    python -m src.data.classify_paper_with_gemini <database_id> --estimate-cost
    python -m src.data.classify_paper_with_gemini <database_id> --run --dry-run
    python -m src.data.classify_paper_with_gemini <database_id> --run
"""
from __future__ import annotations

import argparse
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import notion_classify as nc

from .classify_journal_with_gemini import (
    AVG_INPUT_TOKENS_PER_ITEM,
    AVG_OUTPUT_TOKENS_PER_ITEM,
    GEMINI_INPUT_RATE,
    GEMINI_MODEL,
    GEMINI_OUTPUT_RATE,
    _unclassified_pages,
    classify_paragraph_gemini,
)

SAVE_EVERY = 20


def get_database_title(database_id: str) -> str:
    """取 Notion database 的標題，拿來當 results/*.json 的檔名（比照既有 54 篇）。"""
    db = nc.notion.databases.retrieve(database_id=database_id)
    return "".join(t.get("plain_text", "") for t in db.get("title", [])) or database_id


def estimate_cost(database_id: str) -> None:
    ds_id = nc.get_data_source_id(database_id)
    pages = _unclassified_pages(ds_id)
    n = len(pages)
    print(f"資料庫：{get_database_title(database_id)}")
    print(f"待分類段落數：{n}")
    if n == 0:
        print("沒有待分類的段落（可能都已分類過，或還沒匯入 Notion）。")
        return

    input_cost = n * AVG_INPUT_TOKENS_PER_ITEM / 1e6 * GEMINI_INPUT_RATE
    output_cost = n * AVG_OUTPUT_TOKENS_PER_ITEM / 1e6 * GEMINI_OUTPUT_RATE
    total = input_cost + output_cost
    print(f"模型：{GEMINI_MODEL}")
    print(f"預估費用：約 ${total:.2f} USD（約 NT${total * 32:.0f}）")
    print(
        "估算依據：沿用 notion_classify.py 對 10,099 筆既有資料的真實平均 token 用量"
        f"（同一套 SYSTEM_PROMPT／分類任務），本次沒有呼叫任何付費 API。"
    )


def run(database_id: str, dry_run: bool) -> None:
    results_title = get_database_title(database_id)
    ds_id = nc.get_data_source_id(database_id)
    print(f"資料庫：{results_title}")
    print(f"ds_id: {ds_id}")
    nc.ensure_data_source_properties(ds_id)

    pages = _unclassified_pages(ds_id)
    print(f"待處理：{len(pages)} 筆")
    if not pages:
        return

    result_data = nc.load_result_file(results_title, database_id)
    existing_ids = {r["page_id"] for r in result_data["records"]}
    for p in pages:
        if p["page_id"] not in existing_ids:
            result_data["records"].append(nc._make_record(p))
    nc.save_result_file(result_data, results_title, database_id)

    # 沒有 categories 的一律重試（含上次失敗過的），不因為單次暫時性錯誤
    # （API 逾時、JSON 解析失敗等）就把段落永久卡住、需要手動改 JSON 才能救回。
    todo = [r for r in result_data["records"] if not r["categories"]]
    print(f"呼叫 Gemini 分類：{len(todo)} 筆")

    for i, rec in enumerate(todo, 1):
        try:
            parsed = classify_paragraph_gemini(rec["paragraph"])
            rec["categories"] = parsed["categories"]
            rec["reason"] = parsed["reason"]
            rec["keywords"] = parsed["keywords"]
            rec["error"] = None
        except Exception as e:  # noqa: BLE001 - 單筆失敗要能繼續跑，不整批中斷
            rec["error"] = f"分類失敗：{e}"
        if i % SAVE_EVERY == 0 or i == len(todo):
            print(f"  {i}/{len(todo)}", flush=True)
            nc.save_result_file(result_data, results_title, database_id)

    nc.save_result_file(result_data, results_title, database_id)

    failed = [r for r in result_data["records"] if r.get("error")]
    if failed:
        print(f"⚠️ 有 {len(failed)} 筆分類失敗（已記在 results/，可重跑本指令續傳）")

    success, errors = nc.write_all_records(result_data, dry_run)
    print(f"\n寫入 Notion：成功 {success} 筆，失敗 {errors} 筆。")
    if dry_run:
        print("（Dry-run 模式，結果已存本地 results/ 但未寫入 Notion）")


def main() -> None:
    parser = argparse.ArgumentParser(description="用 Gemini 對單篇學位論文段落（代碼 98）分類")
    parser.add_argument("database_id", help="Notion 資料庫 ID（網址裡那串，不是 data_source id）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--estimate-cost", action="store_true", help="只估價，不呼叫任何付費 API")
    group.add_argument("--run", action="store_true", help="實際執行分類")
    parser.add_argument("--dry-run", action="store_true", help="配合 --run：只存本地，不寫回 Notion")
    args = parser.parse_args()

    if args.estimate_cost:
        estimate_cost(args.database_id)
    else:
        run(args.database_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
