# -*- coding: utf-8 -*-
"""
用 Gemini API 對已分類段落生成合成 QA 對，作為 fine-tuning 的訓練資料來源。

動機：這次 fine-tuning 的目的不是複製 classify_chain.py／classify_agent.py 的分類任務，
而是希望微調後的模型能直接回答「信義鄉相關知識」的問題（例如某個歷史事件、地名、族群文化），
不需要在推論時額外檢索——知識要內化進模型權重本身。labeled_corpus.jsonl 的段落是敘述性
文字，不是現成的問答對，所以先用 LLM 把每個段落轉成 0~2 組合成 QA 對，再拿去微調。

模型選擇：實際用 5 個代表性段落比較過 Claude Haiku 4.5／Gemini 3.1 Flash-Lite／
Groq（Llama 3.3 70B Versatile）三家（GPT-5 Mini 因帳號未設定計費未能測試），選定
**Gemini 3.1 Flash-Lite**：品質與 Claude 相當（包括正確對「無法判斷」類段落回傳空陣列），
但實測全量成本只要 Claude 的約 1/8（約 $3.4 vs $28.3 USD）；Groq 雖然也便宜，但測試中
發現它會編造段落沒提到的資訊（例如把信義鄉布農族的祭儀誤植為「泰雅族」），對訓練資料
的正確性風險較高，故未採用。

會呼叫付費 Gemini API，跟 notion_classify.py 一樣採**逐筆落地快取＋可斷點續傳**設計：
每處理完一個段落就寫入 data/qa_pairs.jsonl 一行，重新執行只會處理尚未生成過的段落，
不會重複呼叫 API 或重複計費（呼應這個專案一貫的成本意識與容錯慣例）。

這是新增的平行實驗模組，不修改 notion_classify.py／classify_chain.py／classify_agent.py，
不寫入 Notion。

前置作業：`.env` 需要有 `GOOGLE_API_KEY`（見 https://aistudio.google.com/apikey）。

CLI 使用方式：
    python -m src.finetune.generate_qa --sample 20   # 先小量測試，控制花費
    python -m src.finetune.generate_qa --all         # 處理全部尚未生成過的段落
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI, HarmBlockThreshold, HarmCategory
from pydantic import BaseModel, Field

from src.langchain_pipeline.classify_chain import _load_corpus

load_dotenv()

QA_GEN_MODEL = "gemini-3.1-flash-lite"

DATA_DIR = Path(__file__).resolve().parent / "data"
QA_CACHE_PATH = DATA_DIR / "qa_pairs.jsonl"

QA_GEN_SYSTEM_PROMPT = """你是《南投縣信義鄉志》的資料標註助理。任務是讀一段論文段落，
產生 0~2 組「問答對」，之後要拿來微調另一個語言模型，讓它學會直接回答關於**南投縣信義鄉**的
知識性問題（回答時不需要引用來源，把知識當作自己已經知道的事實來回答）。

背景與重要限制：段落內容環繞信義鄉在地知識，包括原住民族群、地理、歷史、產業等。信義鄉以
布農族為主，但也有其他族群，段落若沒有明確指出是哪個族群、地名、人名、年代等專有名詞，
絕對不要自行推測或杜撰（包括不要預設一定是布農族）——寧可用段落中出現的原始說法
（例如「部落」「族人」「原住民」），也不要臆測成特定名稱。

規則：
1. 問題要像真實使用者會自然提出的問題（例如某個地名、歷史事件、族群文化、產業、人物等），
   不要出現「這段話」「本段」「上文」等指涉段落本身的詞語——使用者不會看到原始段落。
2. 答案要完整、正確，只根據段落內容作答，不要加入段落沒有提到的資訊（包含不要杜撰段落
   沒明說的族群、人名、地名、年代等專有名詞）；不要保留學術引用格式（如作者、年份、頁碼）；
   用 80~200 字的完整繁體中文句子回答，不要條列。
3. 若段落內容瑣碎、不具知識性（例如純統計數字、目錄、參考文獻、個人心路歷程與感想等
   無法轉換成客觀知識問答的內容），回傳空陣列，不要硬湊問題。

範例（僅供參考格式，不是段落原文）：
段落：「射耳祭於每年四、五月間舉行，是重要的祭典之一，主要目的是訓練男子的狩獵技能與
膽識，並祈求獵獲豐收。」（段落沒有明講是哪個族群）
問答對：
- Q: 射耳祭有什麼意義？
  A: 射耳祭是每年四、五月間舉行的重要祭典，主要目的是訓練男子的狩獵技能與膽識，同時
     祈求獵獲豐收，是傳統文化中相當重要的活動之一。

段落：「（以下為個人論文誌謝與心得感想，略）」
問答對：（空陣列，因為是個人心路歷程，不具客觀知識性）"""


class QAPair(BaseModel):
    question: str = Field(..., description="像真實使用者會問的自然語言問題，不指涉段落本身")
    answer: str = Field(..., description="80~200 字的完整中文答案，只根據段落內容作答")


class QAPairsResult(BaseModel):
    pairs: list[QAPair] = Field(default_factory=list, max_length=2)


# 段落是學術論文的民族誌／史料內容（非公開對外服務），偶爾會提到懲罰、傷痛等描述，
# 曾實際觸發 Gemini 預設的安全過濾（PROHIBITED_CONTENT）擋掉合法的學術內容，
# 故對這個內部資料生成任務放寬全部類別的安全門檻。
_SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

_llm = ChatGoogleGenerativeAI(model=QA_GEN_MODEL, max_output_tokens=600, safety_settings=_SAFETY_SETTINGS)
# include_raw=True：解析失敗時回傳 parsing_error 而不是直接丟例外，讓失敗的段落單純不寫入
# 快取、留給下一次重新執行自然重試（呼應 notion_classify.py 的斷點續傳設計，不需要額外的
# retry 包裝）；同時也才拿得到 raw.usage_metadata 供量測真實花費。
_structured_llm = _llm.with_structured_output(QAPairsResult, include_raw=True)


def _load_cached_ids() -> set[str]:
    if not QA_CACHE_PATH.exists():
        return set()
    ids = set()
    with QA_CACHE_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.add(json.loads(line)["id"])
    return ids


def generate_for_entry(entry: dict) -> tuple[QAPairsResult | None, dict]:
    """回傳 (QAPairsResult 或 None（解析失敗）, usage_metadata dict)。"""
    messages = [
        SystemMessage(content=QA_GEN_SYSTEM_PROMPT),
        HumanMessage(content=f"<段落>\n{entry['paragraph']}\n</段落>\n\n請根據這段內容產生問答對。"),
    ]
    output = _structured_llm.invoke(messages)
    usage = getattr(output["raw"], "usage_metadata", None) or {}
    if output["parsing_error"] is not None:
        return None, usage
    return output["parsed"], usage


def main() -> None:
    parser = argparse.ArgumentParser(description="用 Gemini API 對段落生成合成 QA 對（供 fine-tuning 使用）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sample", type=int, metavar="N", help="只處理 N 筆尚未生成過的段落（測試用，控制花費）")
    group.add_argument("--all", action="store_true", help="處理全部尚未生成過的段落")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entries = _load_corpus()
    done_ids = _load_cached_ids()
    todo = [e for e in entries if e["id"] not in done_ids]
    if args.sample:
        todo = todo[: args.sample]

    print(f"語料總筆數：{len(entries)}｜已生成過：{len(done_ids)}｜本次要處理：{len(todo)}")

    total_input = 0
    total_output = 0
    total_pairs = 0
    skipped = 0
    with QA_CACHE_PATH.open("a", encoding="utf-8") as f:
        for i, entry in enumerate(todo, 1):
            try:
                result, usage = generate_for_entry(entry)
            except Exception as e:
                skipped += 1
                print(f"x [{i}/{len(todo)}] {entry['id']}（呼叫失敗，跳過，下次重跑會自動補）：{e}")
                continue

            total_input += usage.get("input_tokens", 0)
            total_output += usage.get("output_tokens", 0)

            if result is None:
                skipped += 1
                print(f"x [{i}/{len(todo)}] {entry['id']}（結構化解析失敗，跳過，下次重跑會自動補）")
                continue

            record = {"id": entry["id"], "pairs": [p.model_dump() for p in result.pairs]}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

            total_pairs += len(result.pairs)
            mark = "✓" if result.pairs else "-"
            print(f"{mark} [{i}/{len(todo)}] {entry['id']}（{len(result.pairs)} 組 QA）")

    processed = len(todo) - skipped
    print(f"\n完成：新增 {processed} 筆段落的生成結果（共 {total_pairs} 組 QA 對），跳過 {skipped} 筆")
    if total_input or total_output:
        print(f"本次實際 token 用量：input={total_input}, output={total_output}")
        if processed:
            print(f"平均每筆：input={total_input / len(todo):.0f}, output={total_output / len(todo):.0f}")


if __name__ == "__main__":
    main()
