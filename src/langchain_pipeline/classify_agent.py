# -*- coding: utf-8 -*-
"""
LangChain Agent 編排（v.s. classify_chain.py 的固定 chain）

classify_chain.py 用 LCEL 把「檢索 → 組 prompt → 結構化輸出」寫死成固定流程：
不論段落內容為何，永遠檢索固定 k 筆範例、永遠用完整段落文字當查詢字句、永遠只呼叫一次 Claude。

這支改用 langchain.agents.create_agent，讓 Claude 自己決定：要不要呼叫檢索工具、
呼叫幾次（最多 3 次，recursion_limit 硬性把關）、用什麼查詢字句、要不要限定分類篩選。
流程順序由模型自主決定，而不是寫死在程式碼裡——這是 chain 與 agent 編排哲學上的核心差異。

這是平行的實驗／展示模組，不會修改、也不會呼叫 notion_classify.py 或 classify_chain.py
既有流程（只從 classify_chain.py import 共用的分類清單／schema），不會寫入 Notion。

CLI 使用方式：
    python -m src.langchain_pipeline.classify_agent --text "段落文字…"
    python -m src.langchain_pipeline.classify_agent --paper-id P13-1126
    python -m src.langchain_pipeline.classify_agent --compare --sample 5 --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage

from src.langchain_pipeline.classify_chain import (
    CATEGORIES,
    DEFAULT_LLM_MODEL,
    ClassificationResult,
    _find_entry_by_id,
    _load_corpus,
    _user_prompt,
)
from src.rag.query_engine import search_similar

load_dotenv()

SEARCH_TOOL_NAME = "search_similar_paragraphs"

AGENT_SYSTEM_PROMPT = f"""你是《南投縣信義鄉志》的編纂助理，負責對論文段落進行分類並擷取關鍵字。

【分類清單】（共 {len(CATEGORIES)} 類）：
{chr(10).join(f"- {c}" for c in CATEGORIES)}

【任務說明】：
1. 從上方清單中選出 1～2 個最符合的分類（必須完全符合名稱）；若完全無法判斷，選「無法判斷」。
2. 用一句話說明為什麼選這些分類（20～50 字，中文）。
3. 從段落擷取 3～5 個關鍵字。

【工具使用說明】：
你有一個 {SEARCH_TOOL_NAME} 工具，可以查詢跟待分類段落語意相近、已完成分類的真實範例，
參考它們的分類風格與細緻度作答。你可以自行改寫查詢字句（不一定要用完整段落原文）、
決定要查幾筆、要不要限定分類。如果段落內容清楚、你已經有把握，可以完全不呼叫這個工具直接作答；
如果不確定，最多呼叫 3 次。"""


def _make_search_tool(exclude_id: str | None):
    @tool(SEARCH_TOOL_NAME)
    def search_similar_paragraphs(query: str, k: int = 3, category: str | None = None) -> str:
        """搜尋語意最相近、已完成分類的段落，回傳 JSON 陣列（含 categories/reason/keywords）。
        query 可以是原段落全文，也可以自行改寫成更精準的查詢字句；
        category 可選填正確分類名稱以縮小範圍。"""
        raw = search_similar(query, k=k + 2, category=category)
        filtered = [
            r for r in raw if r.id != exclude_id and r.categories != ["無法判斷"]
        ][:k]
        return json.dumps(
            [
                {
                    "categories": r.categories,
                    "reason": r.reason,
                    "keywords": r.keywords,
                    "paragraph": r.paragraph[:200],
                }
                for r in filtered
            ],
            ensure_ascii=False,
        )

    return search_similar_paragraphs


# 比 classify_chain.py 的 400 更高：多輪工具呼叫（推理＋工具參數＋最終結構化輸出）需要更多輸出預算。
_llm = ChatAnthropic(model=DEFAULT_LLM_MODEL, max_tokens=800)


def _count_search_calls(messages: list) -> tuple[int, list[str]]:
    """數出 agent 實際呼叫檢索工具的次數與查詢字句。
    排除 create_agent 內部用來強制結構化輸出的「submit schema」工具呼叫。"""
    queries = []
    for m in messages:
        if isinstance(m, AIMessage):
            for call in getattr(m, "tool_calls", None) or []:
                if call.get("name") == SEARCH_TOOL_NAME:
                    queries.append(call.get("args", {}).get("query", ""))
    return len(queries), queries


def classify_with_agent(
    paragraph: str, exclude_id: str | None = None
) -> tuple[ClassificationResult, int, list[str]]:
    """執行 agent 編排分類，回傳結構化結果、實際呼叫檢索工具次數、每次的查詢字句。"""
    agent = create_agent(
        model=_llm,
        tools=[_make_search_tool(exclude_id)],
        system_prompt=AGENT_SYSTEM_PROMPT,
        response_format=ClassificationResult,
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": _user_prompt(paragraph)}]},
        config={"recursion_limit": 10},  # 硬性上限，避免工具呼叫迴圈失控燒錢
    )
    call_count, queries = _count_search_calls(result["messages"])
    return result["structured_response"], call_count, queries


# ---------------------------------------------------------------------------
# --compare：跟既有語料的靜態分類比較，並統計工具呼叫次數
# ---------------------------------------------------------------------------

def compare_sample(n: int, seed: int | None) -> None:
    entries = [e for e in _load_corpus() if e["categories"] != ["無法判斷"]]
    rng = random.Random(seed)
    sample = rng.sample(entries, min(n, len(entries)))

    full_match = 0
    any_overlap = 0
    errors = 0
    total_calls = 0
    zero_call_count = 0
    for entry in sample:
        static_cats = entry["categories"]
        try:
            result, call_count, _ = classify_with_agent(entry["paragraph"], exclude_id=entry["id"])
        except Exception as e:
            errors += 1
            print(f"x {entry['id']}（分類失敗，跳過）：{e}")
            continue

        dynamic_cats = list(result.categories)
        total_calls += call_count
        zero_call_count += call_count == 0

        is_full_match = set(static_cats) == set(dynamic_cats)
        is_overlap = bool(set(static_cats) & set(dynamic_cats))
        full_match += is_full_match
        any_overlap += is_overlap

        mark = "✓" if is_full_match else ("~" if is_overlap else "✗")
        print(f"{mark} {entry['id']}（呼叫工具 {call_count} 次）")
        print(f"    靜態基準（既有語料）：{' / '.join(static_cats)}")
        print(f"    Agent 分類：        {' / '.join(dynamic_cats)}")
        if not is_full_match:
            print(f"    Agent 原因：{result.reason}")

    total = len(sample)
    compared = total - errors
    if compared == 0:
        print("\n沒有可比較的樣本（全部分類失敗）。" if total else "沒有可比較的樣本。")
        return
    print(f"\n完全一致：{full_match}/{compared}（{full_match / compared:.0%}）")
    print(f"至少部分重疊：{any_overlap}/{compared}（{any_overlap / compared:.0%}）")
    print(f"平均呼叫工具次數：{total_calls / compared:.1f}")
    print(f"0 次呼叫（有把握不查）：{zero_call_count}/{compared}（{zero_call_count / compared:.0%}）")
    if errors:
        print(f"分類失敗（已跳過）：{errors}/{total}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_result(result: ClassificationResult, call_count: int, queries: list[str]) -> None:
    if queries:
        print(f"呼叫檢索工具 {call_count} 次：{queries}")
    else:
        print("呼叫檢索工具 0 次（有把握，直接作答）")
    print(f"分類：{' / '.join(result.categories)}")
    print(f"原因：{result.reason}")
    print(f"關鍵字：{', '.join(result.keywords)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LangChain Agent 編排分類（讓模型自主決定是否／如何檢索）")
    parser.add_argument("--text", metavar="TEXT", help="直接輸入段落文字進行分類")
    parser.add_argument("--paper-id", metavar="ID", help="從 labeled_corpus.jsonl 撈一筆段落測試，並印出原本分類對照")
    parser.add_argument("--compare", action="store_true", help="從語料抽樣，比較 agent 與既有靜態分類")
    parser.add_argument("--sample", type=int, default=10, help="--compare 抽樣筆數（預設 10）")
    parser.add_argument("--seed", type=int, default=None, help="--compare 抽樣亂數種子")
    args = parser.parse_args()

    if args.compare:
        compare_sample(n=args.sample, seed=args.seed)
        return

    if args.paper_id:
        entry = _find_entry_by_id(_load_corpus(), args.paper_id)
        if entry is None:
            print(f"找不到 ID：{args.paper_id}")
            return
        result, call_count, queries = classify_with_agent(entry["paragraph"], exclude_id=entry["id"])
        _print_result(result, call_count, queries)
        print(f"\n原本分類（語料現有標註）：{' / '.join(entry['categories'])}")
        return

    if args.text:
        result, call_count, queries = classify_with_agent(args.text)
        _print_result(result, call_count, queries)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
