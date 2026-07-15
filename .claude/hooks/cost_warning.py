#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PreToolUse hook（Bash / PowerShell）。

執行前偵測指令是否會呼叫付費 API（Anthropic Claude 或 Voyage AI），
若是，強制轉為「ask」並在權限提示裡附上呼叫原因與預估花費，
讓使用者在授權前就能看到花費資訊。不符合已知付費模式的指令一律放行，不列印任何內容。

預估數字來源：
- notion_classify.py 的每筆單價，是從 batch_states/ 內 57 個 batch 的真實用量
  （38,066,941 input tokens、1,817,689 output tokens ÷ 10,099 筆）換算而來，非猜測。
- classify_chain.py 的單次呼叫成本，是從一次真實呼叫的 usage_metadata
  （3,537 input / 109 output tokens）換算而來。
- classify_agent.py 的成本區間，是從 3 次真實呼叫的 usage_metadata 換算而來：
  未呼叫檢索工具時 2 次平均約 2,405 input / 128 output tokens，
  呼叫 1 次檢索工具時 1 次約 5,480 input / 300 output tokens。
  agent 會自行決定要不要檢索、檢索幾次（最多 3 次，見 recursion_limit），
  故單次成本本來就有波動，不是固定值。
- 定價比照 calc_cost.py 的註解（claude-haiku-4-5：Input $1.00/1M、Output $5.00/1M，
  Batch 皆 5 折）。calc_cost.py 頂層會建立 Anthropic client（需要 ANTHROPIC_API_KEY）
  而無法直接 import，故常數在此重新宣告——日後若調價，兩處都要同步更新。
- build_index.py（Voyage embedding）本專案未實測過真實花費，僅為粗估，會明確標註。
- generate_qa.py 改用 Gemini API（gemini-3.1-flash-lite，即時模式 $0.25/1M input、
  $1.50/1M output，2026-07 查證）。單價是從全量 --all 實跑（10,099 筆）的真實
  usage_metadata 換算而來（合計 input 8,106,964 / output 1,608,083 tokens，
  平均每筆 input≈803 / output≈159 tokens），實際總花費約 $4.44 USD。
  選型依據：實測比較過 Claude Haiku 4.5／Gemini 3.1 Flash-Lite／Groq Llama 3.3 70B，
  Gemini 品質與 Claude 相當、成本只要 Claude 的約 1/8，且未觀察到 Groq 出現的編造資訊問題。
"""
import json
import re
import sys

if sys.stdin.encoding and sys.stdin.encoding.lower() != "utf-8":
    sys.stdin.reconfigure(encoding="utf-8")

# claude-haiku-4-5 定價（USD / 1M tokens），比照 calc_cost.py
INPUT_RATE_REALTIME = 1.00
OUTPUT_RATE_REALTIME = 5.00
INPUT_RATE_BATCH = 0.50
OUTPUT_RATE_BATCH = 2.50

# gemini-3.1-flash-lite 定價（USD / 1M tokens，即時模式，2026-07 查證）
GEMINI_FLASH_LITE_INPUT_RATE = 0.25
GEMINI_FLASH_LITE_OUTPUT_RATE = 1.50

# 實測 token 數（見上方 docstring 來源說明）
NOTION_INPUT_TOKENS_PER_ITEM = 38_066_941 / 10_099
NOTION_OUTPUT_TOKENS_PER_ITEM = 1_817_689 / 10_099
CLASSIFY_CHAIN_INPUT_TOKENS = 3_537
CLASSIFY_CHAIN_OUTPUT_TOKENS = 109
AGENT_INPUT_TOKENS_NO_RETRIEVAL = 2_405
AGENT_OUTPUT_TOKENS_NO_RETRIEVAL = 128
AGENT_INPUT_TOKENS_WITH_RETRIEVAL = 5_480
AGENT_OUTPUT_TOKENS_WITH_RETRIEVAL = 300
# generate_qa.py：全量 --all 實跑（10,099 筆）的真實平均值（見上方 docstring 來源說明）
QA_GEN_INPUT_TOKENS = 803
QA_GEN_OUTPUT_TOKENS = 159


def _token_cost(input_tokens: float, output_tokens: float, input_rate: float, output_rate: float) -> float:
    return input_tokens / 1_000_000 * input_rate + output_tokens / 1_000_000 * output_rate


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    if not cmd:
        return

    reason = None
    estimate = None

    if "classify_chain" in cmd:
        reason = "會呼叫 Claude API（claude-haiku-4-5，即時模式）做動態 few-shot 分類，並呼叫 Voyage API 做語意檢索。"
        if "--compare" in cmd:
            m = re.search(r"--sample[=\s]+(\d+)", cmd)
            n = int(m.group(1)) if m else 10  # --compare 的 argparse 預設值
        else:
            n = 1  # --text / --paper-id 都只分類一筆
        per_call = _token_cost(
            CLASSIFY_CHAIN_INPUT_TOKENS, CLASSIFY_CHAIN_OUTPUT_TOKENS,
            INPUT_RATE_REALTIME, OUTPUT_RATE_REALTIME,
        )
        low, high = per_call * n * 0.9, per_call * n * 1.5
        estimate = (
            f"單次呼叫實測約 ${per_call:.4f} USD；本次預估跑 {n} 筆，"
            f"約 ${low:.4f}~${high:.4f} USD（約 NT${low * 32:.2f}~{high * 32:.2f}）。"
        )

    elif "classify_agent" in cmd:
        reason = (
            "會呼叫 Claude API（claude-haiku-4-5）做 agent 編排分類，模型自行決定要不要"
            "呼叫檢索工具、呼叫幾次（最多 3 次），並呼叫 Voyage API 做語意檢索。"
        )
        if "--compare" in cmd:
            m = re.search(r"--sample[=\s]+(\d+)", cmd)
            n = int(m.group(1)) if m else 10  # --compare 的 argparse 預設值
        else:
            n = 1  # --text / --paper-id 都只分類一筆
        low = _token_cost(
            AGENT_INPUT_TOKENS_NO_RETRIEVAL, AGENT_OUTPUT_TOKENS_NO_RETRIEVAL,
            INPUT_RATE_REALTIME, OUTPUT_RATE_REALTIME,
        ) * n
        high = _token_cost(
            AGENT_INPUT_TOKENS_WITH_RETRIEVAL, AGENT_OUTPUT_TOKENS_WITH_RETRIEVAL,
            INPUT_RATE_REALTIME, OUTPUT_RATE_REALTIME,
        ) * n * 1.3  # 多留一點餘裕：實測樣本裡最多只呼叫過 1 次，但系統提示允許到 3 次
        estimate = (
            f"實測：不檢索時約 ${low / n:.4f} USD／筆，檢索 1 次約 ${high / n / 1.3:.4f} USD／筆"
            f"（agent 自行決定要不要檢索，非固定）；本次預估跑 {n} 筆，"
            f"約 ${low:.4f}~${high:.4f} USD（約 NT${low * 32:.2f}~{high * 32:.2f}）。"
        )

    elif "generate_qa" in cmd:
        reason = "會呼叫 Gemini API（gemini-3.1-flash-lite）對段落生成合成 QA 對，供後續 fine-tuning 使用。"
        m = re.search(r"--sample[=\s]+(\d+)", cmd)
        if m:
            n = int(m.group(1))
        elif "--all" in cmd:
            n = 10_099  # 語料總筆數，實際依尚未生成過的段落數而定，可能更少
        else:
            n = 0
        per_item = _token_cost(
            QA_GEN_INPUT_TOKENS, QA_GEN_OUTPUT_TOKENS,
            GEMINI_FLASH_LITE_INPUT_RATE, GEMINI_FLASH_LITE_OUTPUT_RATE,
        )
        estimate = (
            f"實測平均每筆約 ${per_item:.4f} USD；本次預估最多處理 {n} 筆，"
            f"約 ${per_item * n:.2f} USD（約 NT${per_item * n * 32:.2f}）。"
        )

    elif "notion_classify.py" in cmd:
        reason = "會呼叫 Claude API 對 Notion 段落做分類與關鍵字擷取。"
        if "--dry-run" in cmd:
            reason += "（--dry-run 只跳過寫回 Notion，仍會實際呼叫 API 產生費用）"
        else:
            reason += "並寫回 Notion。"
        is_batch = "--batch" in cmd
        input_rate = INPUT_RATE_BATCH if is_batch else INPUT_RATE_REALTIME
        output_rate = OUTPUT_RATE_BATCH if is_batch else OUTPUT_RATE_REALTIME
        per_item = _token_cost(NOTION_INPUT_TOKENS_PER_ITEM, NOTION_OUTPUT_TOKENS_PER_ITEM, input_rate, output_rate)
        mode = "Batch 模式（5 折）" if is_batch else "即時模式"
        estimate = (
            f"{mode}，依 57 個 batch 的真實歷史數據（10,099 筆均攤）每筆約 ${per_item:.5f} USD，"
            f"實際花費依待分類筆數而定。例如 100 筆約 ${per_item * 100:.2f} USD、"
            f"1000 筆約 ${per_item * 1000:.2f} USD。"
        )

    elif "build_index" in cmd:
        reason = "會呼叫 Voyage AI 對全部段落做 embedding，建立／覆寫向量索引。"
        estimate = (
            "⚠️ 本專案沒有實測過 Voyage 的真實花費，以下為粗估：Voyage 定價通常在每百萬 token "
            "數分錢等級，10,099 筆量級預期在 $1 USD 以下，但未經驗證，且 Voyage 帳單不會出現在 "
            "Anthropic Console，需另外查 Voyage AI 自己的 dashboard。"
        )

    elif "query_engine" in cmd:
        reason = "會呼叫 Voyage API 做語意檢索"
        reason += "，並呼叫 Claude API 生成含引用來源的回答。" if "--ask" in cmd else "（--search 純檢索，也會呼叫付費 embedding API）。"
        estimate = "單次呼叫量級與 classify_chain 類似，約 $0.001~0.01 USD。"

    elif "fix_errors.py" in cmd:
        reason = "會重新呼叫 Claude API，對指定的失敗記錄重新分類。"
        estimate = "通常只處理個位數筆數，預期總花費在 $0.01 USD 以下。"

    if reason is None:
        return

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": (
                f"⚠️ 此指令會呼叫付費 API\n"
                f"呼叫原因：{reason}\n"
                f"預估花費：{estimate}"
            ),
        }
    }
    print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()
