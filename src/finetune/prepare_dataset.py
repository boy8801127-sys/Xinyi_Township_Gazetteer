# -*- coding: utf-8 -*-
"""
Fine-tuning 用資料集切分：把 generate_qa.py 產出的合成 QA 對切成 held-out 評估集與
訓練集，並轉成 chat 格式（system + user + assistant）供 train.ipynb 讀取。

held-out 評估集在「段落」層級切分（同一段落生成的所有 QA 對只會全部進 train 或全部進
eval，不會拆開，避免同段落的相似問題同時出現在兩邊造成洩漏），並依段落既有分類做
分層抽樣，讓各篇章主題在評估集裡都有涵蓋。訓練階段完全看不到這批段落——這比 chain/agent
的 --compare 隨機抽樣更嚴謹，因為 fine-tuning（把資料權重直接寫進模型）有真正的
記憶／過擬合風險，不像 chain/agent 只是在推論時檢索既有語料。

前置作業：
    python -m src.finetune.generate_qa --all   # 先用 Gemini API 生成合成 QA 對

這是新增的平行實驗模組，不修改 notion_classify.py／classify_chain.py／classify_agent.py，
不寫入 Notion。

CLI 使用方式：
    python -m src.finetune.prepare_dataset
    python -m src.finetune.prepare_dataset --eval-size 100 --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from src.langchain_pipeline.classify_chain import _find_entry_by_id, _load_corpus

DATA_DIR = Path(__file__).resolve().parent / "data"
QA_CACHE_PATH = DATA_DIR / "qa_pairs.jsonl"
EVAL_IDS_PATH = DATA_DIR / "eval_ids.json"
TRAIN_PATH = DATA_DIR / "train.jsonl"
ADAPTERS_DIR = Path(__file__).resolve().parent / "adapters"

# Twinkle AI 基底模型，train.ipynb／evaluate.py 共用同一份，避免各處各寫一份不同步。
# 原本也試過 twinkle-ai/Llama-3.2-3B-F1-Instruct，但該模型用 Hermes 格式訓練，
# chat template 跟標準格式不同、風險高，已改成只用 Gemma（官方標準 chat template）。
MODEL_NAME = "twinkle-ai/gemma-3-4B-T1-it"

# 微調的目的是讓模型直接回答信義鄉相關知識問題、不需要在推論時額外檢索——
# 跟 classify_chain/agent 需要把完整分類清單塞進 prompt 不同，這裡的系統提示很單純，
# 因為知識本身要內化進權重，不是靠 prompt 裡列出來的規則現查現用。
FT_SYSTEM_PROMPT = (
    "你是熟悉《南投縣信義鄉志》相關知識的在地知識助理，請根據你所學到的信義鄉歷史、地理、"
    "社會、文化、產業等知識，用完整、正確的中文直接回答使用者的問題。"
)


def _load_qa_records() -> list[dict]:
    if not QA_CACHE_PATH.exists():
        raise FileNotFoundError(
            f"找不到 {QA_CACHE_PATH}，請先執行：python -m src.finetune.generate_qa --all"
        )
    records = []
    with QA_CACHE_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _stratified_eval_ids(
    paragraph_ids: list[str], corpus: list[dict], eval_size: int, seed: int
) -> set[str]:
    """依段落既有分類（categories[0]）分層抽樣出 held-out 評估集，讓各篇章主題都有涵蓋。"""
    rng = random.Random(seed)
    by_primary: dict[str, list[str]] = defaultdict(list)
    for pid in paragraph_ids:
        entry = _find_entry_by_id(corpus, pid)
        primary = entry["categories"][0] if entry else "未知"
        by_primary[primary].append(pid)
    for group in by_primary.values():
        rng.shuffle(group)

    total = len(paragraph_ids)
    picked: list[str] = []
    for group in by_primary.values():
        share = max(1, round(len(group) / total * eval_size))
        picked.extend(group[:share])

    rng.shuffle(picked)
    return set(picked[:eval_size])


def _to_chat_examples(paragraph_id: str, pairs: list[dict]) -> list[dict]:
    return [
        {
            "id": paragraph_id,
            "messages": [
                {"role": "system", "content": FT_SYSTEM_PROMPT},
                {"role": "user", "content": pair["question"]},
                {"role": "assistant", "content": pair["answer"]},
            ],
        }
        for pair in pairs
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="切分 fine-tuning 訓練／held-out 評估資料集（QA 格式）")
    parser.add_argument("--eval-size", type=int, default=100, help="held-out 評估集段落筆數（預設 100）")
    parser.add_argument("--seed", type=int, default=42, help="分層抽樣用的固定亂數種子（預設 42）")
    args = parser.parse_args()

    records = [r for r in _load_qa_records() if r["pairs"]]
    corpus = _load_corpus()
    paragraph_ids = [r["id"] for r in records]

    eval_ids = _stratified_eval_ids(paragraph_ids, corpus, args.eval_size, args.seed)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_IDS_PATH.write_text(
        json.dumps(sorted(eval_ids), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    train_pair_count = 0
    with TRAIN_PATH.open("w", encoding="utf-8") as f:
        for record in records:
            if record["id"] in eval_ids:
                continue
            for example in _to_chat_examples(record["id"], record["pairs"]):
                f.write(json.dumps(example, ensure_ascii=False) + "\n")
                train_pair_count += 1

    eval_pair_count = sum(len(r["pairs"]) for r in records if r["id"] in eval_ids)

    print(f"已生成 QA 的段落數：{len(records)}（已排除生成後 0 組 QA 的段落）")
    print(f"訓練集：{len(paragraph_ids) - len(eval_ids)} 段落，共 {train_pair_count} 組 QA → {TRAIN_PATH}")
    print(f"評估集：{len(eval_ids)} 段落，共 {eval_pair_count} 組 QA（id 清單）→ {EVAL_IDS_PATH}")


if __name__ == "__main__":
    main()
