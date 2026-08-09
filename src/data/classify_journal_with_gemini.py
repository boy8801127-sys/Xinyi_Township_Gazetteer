# -*- coding: utf-8 -*-
"""
用 Gemini（gemini-3.1-flash-lite）對期刊論文段落（來源代碼 97）做分類與關鍵字擷取，
寫回 Notion 並存本地 results/*.json 快取。

流程比照 notion_classify.py（既有論文／縣志分類腳本），差異只在呼叫的 LLM 換成
Gemini（成本考量，見 --estimate-cost）；CATEGORIES／SYSTEM_PROMPT／Notion 讀寫
輔助函式全部直接從 notion_classify import 沿用，不複製貼上、不改動該檔案本身
（平行實驗模組慣例）。

這次期刊資料是匯進「單一資料庫」（不是像既有兩個母頁面底下掛多個 child_database），
所以直接吃 database_id，不用 list_child_databases()。

用法：
    python -m src.data.classify_journal_with_gemini --estimate-cost <database_id>
    python -m src.data.classify_journal_with_gemini --run --dry-run <database_id>
    python -m src.data.classify_journal_with_gemini --run <database_id>
"""
from __future__ import annotations

import argparse
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

import notion_classify as nc

load_dotenv()

# 比照 src/rag/query_engine.py 的選型（2026-07 實測：3.5-flash-lite 品質明顯優於
# 3.1-flash-lite，定價只小幅上漲），用官方別名自動跟最新一代同步，不寫死版本號。
GEMINI_MODEL = "gemini-flash-lite-latest"

# 定價（USD / 1M tokens，2026-07 查證 Google 官方定價頁，見 query_engine.py 同一段
# 註解）與平均每筆 token 數（來源是 notion_classify.py 對 10,099 筆既有資料實際
# 分類時統計出的平均用量，同一個分類任務、同一份 SYSTEM_PROMPT，只是這裡換 Gemini
# 模型，沿用合理，不用另外呼叫 API 才能估價）。
GEMINI_INPUT_RATE = 0.30
GEMINI_OUTPUT_RATE = 2.50
AVG_INPUT_TOKENS_PER_ITEM = 38_066_941 / 10_099
AVG_OUTPUT_TOKENS_PER_ITEM = 1_817_689 / 10_099

RESULTS_TITLE = "期刊論文_97"


class ClassifyResult(BaseModel):
    categories: list[str] = Field(..., description="1~2 個分類名稱")
    reason: str = Field(..., description="20~50 字的分類原因")
    keywords: list[str] = Field(default_factory=list, description="3~5 個關鍵字")


_llm = ChatGoogleGenerativeAI(model=GEMINI_MODEL, max_output_tokens=400)
_structured_llm = _llm.with_structured_output(ClassifyResult, include_raw=True)


def classify_paragraph_gemini(paragraph: str) -> dict:
    messages = [
        SystemMessage(content=nc.SYSTEM_PROMPT),
        HumanMessage(content=nc.build_user_prompt(paragraph)),
    ]
    output = _structured_llm.invoke(messages)
    if output["parsing_error"] is not None:
        raise ValueError(f"Gemini 回傳解析失敗：{output['parsing_error']}")
    parsed: ClassifyResult = output["parsed"]
    cats = [nc._normalize_category(c) for c in parsed.categories[:2]]
    return {
        "categories": cats or ["無法判斷"],
        "reason": parsed.reason.strip()[:200],
        "keywords": (parsed.keywords[:5] if len(parsed.keywords) > 5 else parsed.keywords),
    }


def _unclassified_pages(ds_id: str) -> list[dict]:
    raw_pages = nc.get_unclassified_pages(ds_id)
    pages = [nc.parse_page(p) for p in raw_pages]
    return [p for p in pages if p["paragraph"].strip()]


def estimate_cost(database_id: str) -> None:
    ds_id = nc.get_data_source_id(database_id)
    pages = _unclassified_pages(ds_id)
    n = len(pages)
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
        f"（同一套 SYSTEM_PROMPT／分類任務）——input≈{AVG_INPUT_TOKENS_PER_ITEM:.0f} "
        f"tokens/筆、output≈{AVG_OUTPUT_TOKENS_PER_ITEM:.0f} tokens/筆，"
        f"套用 {GEMINI_MODEL} 定價 ${GEMINI_INPUT_RATE}/1M input、"
        f"${GEMINI_OUTPUT_RATE}/1M output 換算，本次沒有呼叫任何付費 API。"
    )


def run(database_id: str, dry_run: bool) -> None:
    ds_id = nc.get_data_source_id(database_id)
    print(f"ds_id: {ds_id}")
    nc.ensure_data_source_properties(ds_id)

    pages = _unclassified_pages(ds_id)
    print(f"待處理：{len(pages)} 筆")
    if not pages:
        return

    result_data = nc.load_result_file(RESULTS_TITLE, database_id)
    existing_ids = {r["page_id"] for r in result_data["records"]}
    for p in pages:
        if p["page_id"] not in existing_ids:
            result_data["records"].append(nc._make_record(p))
    nc.save_result_file(result_data, RESULTS_TITLE, database_id)

    records_by_id = {r["page_id"]: r for r in result_data["records"]}
    todo = [r for r in result_data["records"] if not r["categories"] and not r["error"]]
    print(f"呼叫 Gemini 分類：{len(todo)} 筆")

    for i, rec in enumerate(todo, 1):
        try:
            parsed = classify_paragraph_gemini(rec["paragraph"])
            rec["categories"] = parsed["categories"]
            rec["reason"] = parsed["reason"]
            rec["keywords"] = parsed["keywords"]
        except Exception as e:  # noqa: BLE001 - 單筆失敗要能繼續跑下一筆，不整批中斷
            rec["error"] = f"分類失敗：{e}"
        if i % 20 == 0 or i == len(todo):
            print(f"  {i}/{len(todo)}")
            nc.save_result_file(result_data, RESULTS_TITLE, database_id)

    nc.save_result_file(result_data, RESULTS_TITLE, database_id)

    success, errors = nc.write_all_records(result_data, dry_run)
    print(f"\n寫入 Notion：成功 {success} 筆，失敗 {errors} 筆。")
    if dry_run:
        print("（Dry-run 模式，結果已存本地 results/ 但未寫入 Notion）")


def main() -> None:
    parser = argparse.ArgumentParser(description="用 Gemini 對期刊論文段落（代碼 97）分類")
    parser.add_argument("database_id", help="Notion 資料庫 ID（網址裡的那串，不是 data_source id）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--estimate-cost", action="store_true", help="只估價，不呼叫任何付費 API")
    group.add_argument("--run", action="store_true", help="實際執行分類")
    parser.add_argument("--dry-run", action="store_true", help="配合 --run：只印出結果，不寫回 Notion")
    args = parser.parse_args()

    if args.estimate_cost:
        estimate_cost(args.database_id)
    else:
        run(args.database_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
