# -*- coding: utf-8 -*-
"""
動態 few-shot 分類 chain（LangChain LCEL + 既有 RAG 檢索）

用 src/rag/query_engine.py 的 search_similar() 檢索與待分類段落語意最相近的
「已分類」段落，動態組成 few-shot 範例，取代 notion_classify.py 中寫死在
SYSTEM_PROMPT 裡的固定範例。搭配 LangChain 的 with_structured_output() 以
Pydantic schema 強制輸出格式（categories 限制為合法分類名稱），取代
notion_classify.py 手寫的 JSON 解析與分類名稱修正邏輯。

這是平行的實驗／展示模組，不會修改、也不會呼叫 notion_classify.py 既有的
穩定分類流程，不會寫入 Notion。

前置作業（沿用 RAG 模組）：
    python -m src.data.build_labeled_corpus
    python -m src.rag.build_index

CLI 使用方式：
    python -m src.langchain_pipeline.classify_chain --text "段落文字…"
    python -m src.langchain_pipeline.classify_chain --paper-id P11-199
    python -m src.langchain_pipeline.classify_chain --compare --sample 10
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Literal

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from pydantic import BaseModel, Field, ValidationError

from src.rag.query_engine import SimilarParagraph, search_similar

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent.parent
CATEGORIES_FILE = ROOT / "This_plan" / "類別.txt"
ARCH_FILE = ROOT / "This_plan" / "信義鄉志架構分類.txt"
CORPUS_PATH = ROOT / "src" / "data" / "labeled_corpus.jsonl"

DEFAULT_LLM_MODEL = "claude-haiku-4-5"

# ---------------------------------------------------------------------------
# 分類清單與系統提示詞（不含固定 few-shot，範例改為動態注入）
# ---------------------------------------------------------------------------

CATEGORIES: list[str] = [
    line.strip()
    for line in CATEGORIES_FILE.read_text(encoding="utf-8").splitlines()
    if line.strip()
] + ["無法判斷"]

_ARCH_TEXT = ARCH_FILE.read_text(encoding="utf-8")

SYSTEM_PROMPT = f"""你是《南投縣信義鄉志》的編纂助理，負責對論文段落進行分類並擷取關鍵字。

【分類清單】（共 {len(CATEGORIES)} 類）：
{chr(10).join(f"- {c}" for c in CATEGORIES)}

【各篇章內容範圍參考】：
{_ARCH_TEXT[:3000]}

【任務說明】：
1. 從上方清單中選出 1～2 個最符合的分類（必須完全符合名稱）。
   - 若段落明顯跨兩個領域，可選 2 個；若只符合一個，就選 1 個。
   - 若段落完全無法判斷所屬領域（例如純統計數字、亂碼、無意義文字），選「無法判斷」。
2. 用一句話說明為什麼選這些分類（20～50 字，中文）。
3. 從段落擷取 3～5 個關鍵字（優先選：地名、人名、族群、事件、制度等專有名詞）。

接下來會提供幾個跟待分類段落語意相近、已完成分類的真實範例，請參考範例的分類風格與細緻度作答。"""


def _user_prompt(paragraph: str) -> str:
    return f"<段落>\n{paragraph}\n</段落>\n\n請分類並說明原因、擷取關鍵字。"


# ---------------------------------------------------------------------------
# 結構化輸出 schema
# ---------------------------------------------------------------------------

CategoryName = Literal[tuple(CATEGORIES)]  # type: ignore[valid-type]


class ClassificationResult(BaseModel):
    categories: list[CategoryName] = Field(
        ..., min_length=1, max_length=2, description="1~2 個最符合的分類，必須是分類清單中的名稱"
    )
    reason: str = Field(..., description="20~50 字的中文分類原因")
    keywords: list[str] = Field(..., min_length=3, max_length=5, description="3~5 個關鍵字")


# ---------------------------------------------------------------------------
# LCEL chain：檢索動態 few-shot → 組 prompt → 結構化輸出
# ---------------------------------------------------------------------------

_llm = ChatAnthropic(model=DEFAULT_LLM_MODEL, max_tokens=400)
_structured_llm = _llm.with_structured_output(ClassificationResult)


def _retrieve_examples(inputs: dict) -> dict:
    """呼叫既有 RAG 檢索，過濾掉「無法判斷」與待分類段落自己。"""
    paragraph = inputs["paragraph"]
    k = inputs.get("k", 3)
    exclude_id = inputs.get("exclude_id")

    raw = search_similar(paragraph, k=k + 2)
    examples = [
        r
        for r in raw
        if r.paragraph.strip() != paragraph.strip()
        and r.id != exclude_id
        and r.categories != ["無法判斷"]
    ][:k]
    return {**inputs, "examples": examples}


def _build_prompt(inputs: dict) -> list:
    paragraph = inputs["paragraph"]
    examples: list[SimilarParagraph] = inputs["examples"]

    messages: list = [SystemMessage(content=SYSTEM_PROMPT)]
    for ex in examples:
        messages.append(HumanMessage(content=_user_prompt(ex.paragraph)))
        messages.append(
            AIMessage(
                content=json.dumps(
                    {"categories": ex.categories, "reason": ex.reason, "keywords": ex.keywords},
                    ensure_ascii=False,
                )
            )
        )
    messages.append(HumanMessage(content=_user_prompt(paragraph)))
    return messages


# 分類步驟本身（組 prompt → 結構化輸出）單獨包一層 retry：schema 驗證失敗時重試一次。
_classify_step = (RunnableLambda(_build_prompt) | _structured_llm).with_retry(
    retry_if_exception_type=(ValidationError,),
    wait_exponential_jitter=False,
    stop_after_attempt=2,
)

# 完整 chain：檢索 → （組 prompt → 結構化輸出），並用 RunnablePassthrough.assign()
# 把分類結果掛回原本的 state，讓 examples 能跟 result 一起傳出去給呼叫端使用。
classify_chain = RunnableLambda(_retrieve_examples) | RunnablePassthrough.assign(result=_classify_step)


def classify_with_dynamic_fewshot(
    paragraph: str,
    k: int = 3,
    exclude_id: str | None = None,
) -> tuple[ClassificationResult, list[SimilarParagraph]]:
    """執行動態 few-shot 分類，回傳結構化結果與實際用到的範例（供印出檢視）。"""
    output = classify_chain.invoke({"paragraph": paragraph, "k": k, "exclude_id": exclude_id})
    return output["result"], output["examples"]


# ---------------------------------------------------------------------------
# --compare：跟既有語料的靜態分類（notion_classify.py 產出）比較
# ---------------------------------------------------------------------------

def _load_corpus() -> list[dict]:
    if not CORPUS_PATH.exists():
        raise FileNotFoundError(
            f"找不到 {CORPUS_PATH}，請先執行：python -m src.data.build_labeled_corpus"
        )
    entries = []
    with CORPUS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _find_entry_by_id(entries: list[dict], paper_id: str) -> dict | None:
    return next((e for e in entries if e["id"] == paper_id), None)


def compare_sample(n: int, seed: int | None, k: int) -> None:
    entries = [e for e in _load_corpus() if e["categories"] != ["無法判斷"]]
    rng = random.Random(seed)
    sample = rng.sample(entries, min(n, len(entries)))

    full_match = 0
    any_overlap = 0
    errors = 0
    for entry in sample:
        static_cats = entry["categories"]
        try:
            result, _ = classify_with_dynamic_fewshot(entry["paragraph"], k=k, exclude_id=entry["id"])
        except Exception as e:
            errors += 1
            print(f"x {entry['id']}（分類失敗，跳過）：{e}")
            continue

        dynamic_cats = list(result.categories)

        is_full_match = set(static_cats) == set(dynamic_cats)
        is_overlap = bool(set(static_cats) & set(dynamic_cats))
        full_match += is_full_match
        any_overlap += is_overlap

        mark = "✓" if is_full_match else ("~" if is_overlap else "✗")
        print(f"{mark} {entry['id']}")
        print(f"    靜態基準（既有語料）：{' / '.join(static_cats)}")
        print(f"    動態 chain：        {' / '.join(dynamic_cats)}")
        if not is_full_match:
            print(f"    動態原因：{result.reason}")

    total = len(sample)
    compared = total - errors
    if compared == 0:
        print("\n沒有可比較的樣本（全部分類失敗）。" if total else "沒有可比較的樣本。")
        return
    print(f"\n完全一致：{full_match}/{compared}（{full_match / compared:.0%}）")
    print(f"至少部分重疊：{any_overlap}/{compared}（{any_overlap / compared:.0%}）")
    if errors:
        print(f"分類失敗（已跳過）：{errors}/{total}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_examples(examples: list[SimilarParagraph]) -> None:
    print(f"動態檢索到 {len(examples)} 筆 few-shot 範例：")
    for i, ex in enumerate(examples, 1):
        preview = ex.paragraph[:40].replace("\n", " ")
        print(f"  [{i}] {ex.id}（score={ex.score:.3f}）| {' / '.join(ex.categories)} | {preview}...")
    print()


def _print_result(result: ClassificationResult) -> None:
    print(f"分類：{' / '.join(result.categories)}")
    print(f"原因：{result.reason}")
    print(f"關鍵字：{', '.join(result.keywords)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="動態 few-shot 分類 chain（LangChain LCEL + RAG 檢索）")
    parser.add_argument("--text", metavar="TEXT", help="直接輸入段落文字進行分類")
    parser.add_argument("--paper-id", metavar="ID", help="從 labeled_corpus.jsonl 撈一筆段落測試，並印出原本分類對照")
    parser.add_argument("--compare", action="store_true", help="從語料抽樣，比較動態 chain 與既有靜態分類")
    parser.add_argument("--sample", type=int, default=10, help="--compare 抽樣筆數（預設 10）")
    parser.add_argument("--seed", type=int, default=None, help="--compare 抽樣亂數種子")
    parser.add_argument("--k", type=int, default=3, help="動態 few-shot 檢索筆數（預設 3）")
    args = parser.parse_args()

    if args.compare:
        compare_sample(n=args.sample, seed=args.seed, k=args.k)
        return

    if args.paper_id:
        entry = _find_entry_by_id(_load_corpus(), args.paper_id)
        if entry is None:
            print(f"找不到 ID：{args.paper_id}")
            return
        result, examples = classify_with_dynamic_fewshot(entry["paragraph"], k=args.k, exclude_id=entry["id"])
        _print_examples(examples)
        _print_result(result)
        print(f"\n原本分類（語料現有標註）：{' / '.join(entry['categories'])}")
        return

    if args.text:
        result, examples = classify_with_dynamic_fewshot(args.text, k=args.k)
        _print_examples(examples)
        _print_result(result)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
