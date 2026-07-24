# -*- coding: utf-8 -*-
"""
Agentic RAG 問答（v.s. query_engine.py::answer_question() 的單次、固定 k 檢索）

answer_question() 每次固定檢索 k 筆就直接生成答案：如果問題是廣泛性的歷史提問
（例如「發生過哪些重要事件」），檢索一次很容易只看到某一個面向，答案的全面性
會不如直接問一般 LLM（一般 LLM 靠通用預訓練知識東拼西湊，看起來面向較廣，但
沒有真實引用來源佐證）。

這支改用 langchain.agents.create_agent，讓 Gemini 自己決定：要不要呼叫檢索工具、
呼叫幾次（最多 6 次，用 ToolCallLimitMiddleware 針對這個工具硬性把關；
recursion_limit 是另一層、對整個 agent 推理迴圈的步數上限，避免失控燒錢）、
用什麼查詢字句——鼓勵它針對廣泛性問題主動換不同角度分次檢索，藉此提升回答的
全面性，同時系統提示明確禁止用檢索不到的通用知識填補答案，保留 RAG「每個論點
都有真實引用來源」的核心優勢。

這是平行的實驗／展示模組，比照 classify_agent.py 的編排方式，不會修改、也不會
呼叫 query_engine.py／classify_chain.py／classify_agent.py 既有流程。

CLI 使用方式：
    python -m src.langchain_pipeline.answer_agent --ask "南投縣信義鄉在日治時期發生過哪些重要的事情？"
    python -m src.langchain_pipeline.answer_agent --compare --ask "..."
"""
from __future__ import annotations

import argparse
import json
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware
from langchain.tools import tool
from langchain_core.messages import AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field

from src.rag.query_engine import (
    SCOPE_NANTOU,
    SCOPE_XINYI,
    Citation,
    DEFAULT_LLM_MODEL,
    SimilarParagraph,
    answer_question,
    search_images,
    search_similar,
)

load_dotenv()

SEARCH_TOOL_NAME = "search_gazetteer_paragraphs"
MAX_TOOL_CALLS_HINT = 6
# LangGraph 的 recursion_limit 算的是「圖的步數」，不是「呼叫檢索工具的次數」：
# 每一輪「模型決定呼叫工具」→「工具執行」通常就吃掉 2 步，6 次檢索光是這樣就
# ≈12~14 步，加上最後整理成 AgentAnswer、以及 ToolCallLimitMiddleware 擋下超額
# 呼叫時模型可能還要再摸索一兩輪才會收手，原本的 20 步對「真的用滿 6 次檢索」的
# 廣泛性問題幾乎注定不夠、很容易觸發 GraphRecursionError。40 給足夠餘裕，且
# ToolCallLimitMiddleware 本身已經把實際檢索次數硬性鎖在 MAX_TOOL_CALLS_HINT，
# 調高這個值不會讓 agent 多檢索、也不會因此變貴，只是不要提前打斷它收尾。
AGENT_RECURSION_LIMIT = 40


def _scope_clause(scope: str | None) -> str:
    if scope == SCOPE_XINYI:
        return (
            "\n\n【地理範圍限定】：這次只回答明確跟信義鄉相關的內容。如果檢索到"
            "的段落談的是南投縣其他鄉鎮或整個南投縣、沒有明確關聯到信義鄉，不要"
            "拿來回答（除非問題本身就是問信義鄉以外的範圍）。"
        )
    return ""


def _build_system_prompt(scope: str | None = None) -> str:
    return f"""你是《南投縣信義鄉志》的問答助理，服務對象是教授與相關領域的專業研究者，
負責回答關於信義鄉的知識性問題。

【核心規則，絕對不能違反】：
你只能根據 {SEARCH_TOOL_NAME} 工具實際檢索到的段落內容作答。如果某個面向沒有被
檢索到，代表資料庫裡沒有（或你還沒找到），絕對不可以用你自己本來就知道的通用
歷史/知識去填補、去杜撰。寧可答案涵蓋的面向少一點，也不能講出查無來源的內容。

【回答對象與詳細程度】：
使用者具備學術或專業背景，不需要簡化用詞或省略細節。回答時盡量把檢索到的段落
裡出現的具體事實都寫進去（例如確切年代、人名、地名、統計數據、制度或機構
名稱），不要只挑重點簡短帶過或用籠統字眼概括；如果不同段落的說法有出入、或
資料只涵蓋問題的部分面向，要如實指出這些落差與限制，不要為了讓答案看起來完整
而抹平細節。

【追求全面性】：
如果問題是廣泛性的提問（例如「發生過哪些重要事件」「有哪些影響」），只查一次
很可能只看到單一面向。你應該主動用不同的關鍵字、不同的切入角度分次檢索（例如
政治／軍事、社會制度、教育、交通建設、經濟產業、宗教信仰等不同面向各查一次），
盡量讓答案涵蓋多個不同面向，而不是查到看起來像有答案就停手。最多可呼叫檢索工具
{MAX_TOOL_CALLS_HINT} 次；如果問題本身很具體、單次檢索就已經找齊需要的資訊，
不需要硬湊次數。**一旦已經呼叫了 {MAX_TOOL_CALLS_HINT} 次（或你評估已經涵蓋
足夠面向），就不要再嘗試呼叫檢索工具**，直接根據目前查到的內容整理成最終答案；
超過上限後再呼叫工具會被系統擋下來、徒然浪費你可用的推理回合數，反而讓你更難
順利整理出結論。

【回答格式，準確標註來源是重點】：
- answer：完整、分點列出的回答，繁體中文。每次引用某個檢索到的段落時，緊接在
  對應句子後面用中括號標註該段落的 id（例如「信義鄉在日治時期設有蕃童教育所
  [B17-021]」），id 必須跟 {SEARCH_TOOL_NAME} 回傳結果裡的 "id" 欄位完全一致，
  一字不差——這個標記會被轉成可點擊的連結，id 錯誤會導致連結失效。沒有實際引用
  依據的句子不要加標記。**一句話同時引用多個段落時，每個 id 要各自用一對中括號
  分開寫**，例如「原住民以布農族為主 [P55-185][P11-80]」，不要寫成
  「[P55-185, P11-80]」（逗號寫在同一個中括號裡無法個別轉成連結）。
- cited_ids：實際引用來當作答案依據的段落 id 清單，必須跟 answer 裡標註的 id
  完全一致（同一組 id、不多不少），只列真的用到的，不要照抄全部檢索結果{_scope_clause(scope)}"""


class AgentAnswer(BaseModel):
    answer: str = Field(description="完整、分點列出的回答，繁體中文")
    cited_ids: list[str] = Field(description="實際引用的段落 id 清單")


def _make_search_tool(citation_pool: dict[str, Citation], source_type: str | None = None):
    @tool(SEARCH_TOOL_NAME)
    def search_gazetteer_paragraphs(query: str, k: int = 5) -> str:
        """檢索跟信義鄉志相關、語意最相近的段落，回傳 JSON 陣列（含 id/paragraph/source/page）。
        query 可以自行改寫成更精準的關鍵字，不必用原問題全文；可重複呼叫、每次換個
        切入角度來擴大涵蓋面。"""
        results = search_similar(query, k=k, source_type=source_type)
        for r in results:
            citation_pool[r.id] = Citation(
                id=r.id, source=r.source, page=r.page, paragraph=r.paragraph, score=r.score,
                images=r.images,
            )
        return json.dumps(
            [
                {"id": r.id, "paragraph": r.paragraph[:300], "source": r.source, "page": r.page}
                for r in results
            ],
            ensure_ascii=False,
        )

    return search_gazetteer_paragraphs


def _count_search_calls(messages: list) -> tuple[int, list[str]]:
    """數出 agent 實際呼叫檢索工具的次數與查詢字句（排除結構化輸出用的 submit 工具呼叫）。"""
    queries = []
    for m in messages:
        if isinstance(m, AIMessage):
            for call in getattr(m, "tool_calls", None) or []:
                if call.get("name") == SEARCH_TOOL_NAME:
                    queries.append(call.get("args", {}).get("query", ""))
    return len(queries), queries


def answer_with_agent(
    question: str, source_type: str | None = None, scope: str | None = None
) -> tuple[AgentAnswer, list[Citation], int, list[str], list[SimilarParagraph]]:
    """執行 agent 編排問答，回傳結構化答案、引用來源、實際呼叫檢索工具次數、查詢字句、
    以及獨立檢索到的相關圖片（見 query_engine.search_images()——跟 agent 自己動態呼叫
    的文字檢索完全分開，用原始問題單獨查一次，不佔用、也不受 agent 檢索次數影響）。
    source_type：限定這次對話全程只從「論文」或「書籍」來源檢索，None 表示不限——
    這是整次對話固定的搜尋範圍（由呼叫端／UI 決定），不是讓 agent 自己每次呼叫時判斷。
    scope：SCOPE_XINYI 限定只用明確跟信義鄉相關的段落作答，None／SCOPE_NANTOU 不限。

    可能拋出 langgraph.errors.GraphRecursionError（agent 在 recursion_limit 步數內
    沒能收斂出結構化回答時）——呼叫端（CLI）負責接住並印出友善訊息。"""
    citation_pool: dict[str, Citation] = {}
    llm = ChatGoogleGenerativeAI(model=DEFAULT_LLM_MODEL)
    agent = create_agent(
        model=llm,
        tools=[_make_search_tool(citation_pool, source_type=source_type)],
        system_prompt=_build_system_prompt(scope),
        response_format=AgentAnswer,
        middleware=[
            # 真正對 search_gazetteer_paragraphs 這個工具本身設次數上限（跟系統提示
            # 講的「最多 6 次」一致）；recursion_limit 只是另一層總步數上限，兩者算的
            # 單位不同，不能只靠 recursion_limit 去對應「6 次」這個數字。
            ToolCallLimitMiddleware(tool_name=SEARCH_TOOL_NAME, run_limit=MAX_TOOL_CALLS_HINT, exit_behavior="continue"),
        ],
    )
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config={"recursion_limit": AGENT_RECURSION_LIMIT},
        )
    except GraphRecursionError:
        fallback = AgentAnswer(
            answer=(
                "agent 在允許的推理步數內沒能整理出最終答案（問題可能太廣泛，"
                "觸發了太多輪推理／檢索）。請把問題拆得更具體一點再試一次。"
            ),
            cited_ids=[],
        )
        return fallback, [], 0, [], []

    call_count, queries = _count_search_calls(result["messages"])

    structured: AgentAnswer = result["structured_response"]
    # cited_ids 是模型輸出，沒有唯一性保證——同一段落若在不同句子各被引用一次，
    # 可能重複列出；去重保留首次出現順序，避免下游（app.py 的引用編號／錨點 id）
    # 因為重複段落出現兩次而錯亂。
    unique_ids = list(dict.fromkeys(structured.cited_ids))
    citations = [citation_pool[cid] for cid in unique_ids if cid in citation_pool]
    images = search_images(question, source_type=source_type)
    return structured, citations, call_count, queries, images


def _print_answer(answer: str, citations: list[Citation], images: list[SimilarParagraph] | None = None) -> None:
    print(answer)
    print("\n引用來源：")
    for c in citations:
        print(f"  - {c.id}｜{c.source} 第 {c.page} 頁（相關度 {c.score:.0%}）")
        preview = c.paragraph[:200].replace("\n", " ")
        print(f"    {preview}{'...' if len(c.paragraph) > 200 else ''}")
    if images:
        print("\n相關圖片：")
        for r in images:
            print(f"  - {r.id}｜{r.source} 第 {r.page} 頁 → {', '.join(r.images)}")


def compare_with_single_shot(question: str, source_type: str | None = None, scope: str | None = None) -> None:
    print("=" * 20, "單次版 answer_question()（query_engine.py）", "=" * 20)
    single = answer_question(question, source_type=source_type, scope=scope)
    _print_answer(single.answer, single.citations, single.images)
    print(f"\n引用段落數：{len(single.citations)}")

    print("\n" + "=" * 20, "Agentic 版 answer_with_agent()", "=" * 20)
    structured, citations, call_count, queries, images = answer_with_agent(question, source_type=source_type, scope=scope)
    print(f"呼叫檢索工具 {call_count} 次：{queries}")
    _print_answer(structured.answer, citations, images)
    print(f"\n引用段落數：{len(citations)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic RAG 問答（讓模型自主決定要不要／如何多次檢索）")
    parser.add_argument("--ask", metavar="QUESTION", help="向鄉志問答助手提問")
    parser.add_argument("--compare", action="store_true", help="同一題並列比較單次版與 agent 版")
    parser.add_argument(
        "--source-type", default=None, choices=["論文", "書籍"],
        help="限定資料來源（論文／書籍），預設不限",
    )
    parser.add_argument(
        "--scope", default=None, choices=[SCOPE_XINYI, SCOPE_NANTOU],
        help="地理範圍，預設不限",
    )
    args = parser.parse_args()

    if not args.ask:
        parser.print_help()
        return

    if args.compare:
        compare_with_single_shot(args.ask, source_type=args.source_type, scope=args.scope)
        return

    structured, citations, call_count, queries, images = answer_with_agent(
        args.ask, source_type=args.source_type, scope=args.scope
    )
    print(f"呼叫檢索工具 {call_count} 次：{queries}\n")
    _print_answer(structured.answer, citations, images)


if __name__ == "__main__":
    main()
