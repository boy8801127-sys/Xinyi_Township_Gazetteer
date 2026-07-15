# -*- coding: utf-8 -*-
"""
評估 fine-tuned adapter：對 held-out QA 對做並列比對

載入 train.ipynb 訓練出的 LoRA adapter，對 prepare_dataset.py 切出的 held-out
評估集（訓練時完全沒看過的段落所生成的 QA 對）做推論，把模型答案跟合成參考答案並列印出。

刻意不做自動判定「答對/答錯」：這裡的參考答案是 Gemini 生成的合成資料，不是人工驗證過的
ground truth，開放式問答的正確性也沒有一個簡單的字串比對可以衡量（跟 chain/agent 的分類
任務不同，分類有離散類別可以算一致率）。所以評估方式是**並列呈現，讓人親自判讀**，
只統計客觀、不需要判斷對錯的指標（有沒有答、答案長度）——沿用這個專案一貫「不虛構
正確率／一致率」的誠實標註原則。

這是新增的平行實驗模組，不修改 notion_classify.py／classify_chain.py／classify_agent.py，
不寫入 Notion。

CLI 使用方式：
    python -m src.finetune.evaluate
    python -m src.finetune.evaluate --limit 20
    python -m src.finetune.evaluate --text "信義鄉在日治時期發生過哪些重要史事？"
"""
from __future__ import annotations

import argparse
import json
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from src.finetune.prepare_dataset import ADAPTERS_DIR, DATA_DIR, EVAL_IDS_PATH, FT_SYSTEM_PROMPT

QA_CACHE_PATH = DATA_DIR / "qa_pairs.jsonl"
ADAPTER_DIR = ADAPTERS_DIR / "gemma"
MAX_SEQ_LENGTH = 1536
MAX_NEW_TOKENS = 300


def _load_finetuned():
    """載入 base model + LoRA adapter，回傳 (model, tokenizer)。延遲 import：這幾個套件很重，
    不裝 requirements-finetune.txt 的人 import 這個模組其他部分（例如常數）不該連帶失敗。"""
    from unsloth import FastLanguageModel

    if not ADAPTER_DIR.exists():
        raise FileNotFoundError(f"找不到 adapter：{ADAPTER_DIR}，請先在 train.ipynb 完成訓練並存檔。")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(ADAPTER_DIR),
        max_seq_length=MAX_SEQ_LENGTH,
        load_in_4bit=True,
    )
    FastLanguageModel.for_inference(model)
    return model, tokenizer


def answer_with_finetuned(question: str, model, tokenizer) -> str:
    """對單一問題做推論，回傳模型的原始文字答案。"""
    messages = [
        {"role": "system", "content": FT_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    output_ids = model.generate(
        **inputs, max_new_tokens=MAX_NEW_TOKENS, temperature=0.1, do_sample=False
    )
    generated = tokenizer.decode(
        output_ids[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True
    )
    return generated.strip()


def _load_eval_qa_pairs(limit: int | None) -> list[tuple[str, dict]]:
    if not EVAL_IDS_PATH.exists():
        raise FileNotFoundError(f"找不到 {EVAL_IDS_PATH}，請先執行：python -m src.finetune.prepare_dataset")
    if not QA_CACHE_PATH.exists():
        raise FileNotFoundError(f"找不到 {QA_CACHE_PATH}，請先執行：python -m src.finetune.generate_qa --all")

    eval_ids = set(json.loads(EVAL_IDS_PATH.read_text(encoding="utf-8")))
    pairs: list[tuple[str, dict]] = []
    with QA_CACHE_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record["id"] not in eval_ids:
                continue
            for pair in record["pairs"]:
                pairs.append((record["id"], pair))

    return pairs[:limit] if limit else pairs


def evaluate(limit: int | None) -> None:
    qa_pairs = _load_eval_qa_pairs(limit)
    if not qa_pairs:
        print("沒有可評估的 held-out QA 對，請確認 prepare_dataset.py／generate_qa.py 是否已執行。")
        return

    model, tokenizer = _load_finetuned()

    answered = 0
    empty = 0
    total_model_len = 0
    total_ref_len = 0
    for eid, pair in qa_pairs:
        answer = answer_with_finetuned(pair["question"], model, tokenizer)
        print(f"=== {eid} ===")
        print(f"問題：{pair['question']}")
        print(f"模型答案：{answer if answer else '（空白）'}")
        print(f"參考答案：{pair['answer']}")
        print()

        if answer:
            answered += 1
            total_model_len += len(answer)
        else:
            empty += 1
        total_ref_len += len(pair["answer"])

    total = len(qa_pairs)
    print(f"共評估 {total} 組 QA")
    print(f"有產生答案：{answered}/{total}（{answered / total:.0%}）｜空白／拒答：{empty}/{total}")
    if answered:
        print(f"模型答案平均長度：{total_model_len / answered:.0f} 字｜參考答案平均長度：{total_ref_len / total:.0f} 字")
    print(
        "\n⚠️ 以上不包含自動判定的正確率：參考答案是 Gemini 生成的合成資料，不是人工驗證過的"
        "\nground truth，開放式問答也沒有簡單的字串比對可以衡量對錯，請直接肉眼比對模型答案"
        "\n跟參考答案的品質。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="評估 fine-tuned adapter（held-out QA 並列比對）")
    parser.add_argument("--limit", type=int, default=None, help="限制評估的 QA 對數量（預設跑滿全部）")
    parser.add_argument("--text", metavar="TEXT", help="直接輸入問題，跟模型互動測試（不比對參考答案）")
    args = parser.parse_args()

    if args.text:
        model, tokenizer = _load_finetuned()
        answer = answer_with_finetuned(args.text, model, tokenizer)
        print(f"問題：{args.text}")
        print(f"模型答案：{answer if answer else '（空白）'}")
        return

    evaluate(args.limit)


if __name__ == "__main__":
    main()
