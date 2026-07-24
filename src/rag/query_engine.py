# -*- coding: utf-8 -*-
"""
查詢已建好的向量索引，提供兩種用途：
    1. search_similar()：純語意檢索，供分類流程做動態 few-shot（見 src/langchain_pipeline/classify_chain.py）
    2. answer_question()：檢索 + Gemini 生成含引用來源的回答（鄉志編纂問答助手）

前置作業：
    python -m src.data.build_labeled_corpus
    python -m src.rag.build_index

CLI 使用方式：
    python -m src.rag.query_engine --ask "日治時期信義鄉發生哪些重要史事？"
    python -m src.rag.query_engine --search "布農族祭典" --k 5
    python -m src.rag.query_engine --search "部落產業" --category 經濟篇
    python -m src.rag.query_engine --ask "信義鄉的氣候概況" --source-type 書籍
    python -m src.rag.query_engine --ask "南投縣的氣候概況" --scope 整個南投縣

answer_question() 用 LlamaIndex 的 CitationQueryEngine（而非普通 as_query_engine()）：
它會把檢索到的段落再切成帶編號的「Source N」小塊塞進 prompt，要求 Gemini 在答案裡
用 [N] 標註引用哪一塊，UI 端可以把 [N] 轉成超連結、點擊跳到對應的引用來源——這是
準確、逐句可追溯來源的關鍵，跟純 as_query_engine() 「答案文字完全不含引用位置資訊」
不同。citation_chunk_size 設 1024（預設 512）是因為語料庫段落平均長度落在
300~800 字之間，太小的預設值會把一段話硬切成兩三個引用編號，1024 讓大多數段落
維持成單一引用。
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from dotenv import load_dotenv
from llama_index.core import PromptTemplate, Settings, VectorStoreIndex
from llama_index.core.query_engine import CitationQueryEngine
from llama_index.core.schema import NodeWithScore
from llama_index.core.vector_stores import (
    ExactMatchFilter,
    MetadataFilters,
)
from llama_index.embeddings.voyageai import VoyageEmbedding
from llama_index.llms.google_genai import GoogleGenAI
from llama_index.vector_stores.chroma import ChromaVectorStore

load_dotenv()

# 地理範圍篩選的兩個合法值（UI 的 Radio 選項、answer_agent.py 都共用這組字面值，
# 避免各處各寫一份字串、日後改字容易漏改）。
SCOPE_XINYI = "僅信義鄉"
SCOPE_NANTOU = "整個南投縣"

ROOT = Path(__file__).resolve().parent.parent.parent
CHROMA_DIR = ROOT / "vectorstore" / "chroma"
COLLECTION_NAME = "xinyi_paragraphs"

EMBED_MODEL_NAME = "voyage-3"
# "gemini-flash-lite-latest" 是 Google 官方提供、永遠指向當前最新一代 flash-lite
# 模型的別名（實測用 client.models.list() 確認存在且可正常呼叫），刻意不寫死版本號
# ——這一階的模型選型本來就會隨 Google 換代持續重新比較，用別名讓它自動跟最新版
# 同步，不用每次都改程式碼。
#
# 選型依據（2026-07 實測，4 題涵蓋具體事實／比較／已知檢索缺口／綜合性問題，各
# 用 gemini-3.1-flash-lite／gemini-3.5-flash-lite／gemini-3.5-flash 各答一次）：
# 3.5-flash-lite 的回答明顯更完整（例如「原住民族群分布與遷徙歷史」一題，3.1 版
# 只有 496 字，3.5-flash-lite 給了 1155 字，多補了鄉治沿革與跨年份人口統計交叉
# 比對），延遲持平或更快；定價只小幅上漲（input $0.25→$0.30、output $1.50→$2.50，
# 每百萬 token，2026-07 查證 Google 官方定價頁）。3.5-flash（非 lite）則不採用：
# 定價貴 6 倍，且 4 題裡有 2 題直接因為 MAX_TOKENS 被截斷失敗，得再拉高
# DEFAULT_MAX_TOKENS 才能用，划不來。
DEFAULT_LLM_MODEL = "gemini-flash-lite-latest"
# 明確指定，不吃 GoogleGenAI 的預設值（None＝跟模型上限走、max_retries=3）——
# prompt 改成要求盡量寫進具體細節（面向教授／專業受眾）後，回答篇幅會比原本的
# 簡短摘要長不少，1024 容易被截斷，拉高到 2048 給足夠空間；retries 拉高到 5
# 降低單次 API 抖動就整段失敗的機率。
DEFAULT_MAX_TOKENS = 2048
DEFAULT_MAX_RETRIES = 5


@dataclass
class SimilarParagraph:
    id: str
    paragraph: str
    source: str
    page: str
    categories: list[str]
    keywords: list[str]
    reason: str
    score: float
    images: list[str] = field(default_factory=list)


@dataclass
class Citation:
    id: str
    source: str
    page: str
    paragraph: str
    score: float = 0.0
    images: list[str] = field(default_factory=list)


@dataclass
class AnswerWithCitations:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    # 跟 citations 分開的獨立圖片清單（來自 search_images()，不佔用 citations 的
    # 檢索名額），供 UI 做成一直顯示、不用點開來源才看得到的圖片區塊。
    images: list[SimilarParagraph] = field(default_factory=list)


_index: VectorStoreIndex | None = None


def _get_index() -> VectorStoreIndex:
    global _index
    if _index is not None:
        return _index

    if not CHROMA_DIR.exists():
        raise FileNotFoundError(
            f"找不到向量庫 {CHROMA_DIR}，請先執行：python -m src.rag.build_index"
        )

    Settings.embed_model = VoyageEmbedding(model_name=EMBED_MODEL_NAME)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(COLLECTION_NAME)
    vector_store = ChromaVectorStore(chroma_collection=collection)
    _index = VectorStoreIndex.from_vector_store(vector_store)
    return _index


def _node_to_similar_paragraph(node: NodeWithScore) -> SimilarParagraph:
    meta = node.node.metadata
    categories = meta.get("categories", "")
    keywords = meta.get("keywords", "")
    images = meta.get("images", "")
    return SimilarParagraph(
        id=node.node.id_,
        paragraph=node.node.get_content(),
        source=meta.get("source", ""),
        page=meta.get("page", ""),
        categories=categories.split(",") if categories else [],
        keywords=keywords.split(",") if keywords else [],
        reason=meta.get("reason", ""),
        score=node.score or 0.0,
        images=images.split(",") if images else [],
    )


def _build_filters(category: str | None, source_type: str | None) -> MetadataFilters | None:
    """依分類／資料來源類型（論文／書籍）組出 metadata 篩選條件，兩者皆為 AND 關係。
    source_type 對應 build_index.py::_to_node() 依 id 前綴（B=書籍／P=論文）寫入的欄位。"""
    conditions = []
    if category:
        conditions.append(ExactMatchFilter(key="category_primary", value=category))
    if source_type:
        conditions.append(ExactMatchFilter(key="source_type", value=source_type))
    return MetadataFilters(filters=conditions) if conditions else None


def search_similar(
    paragraph: str,
    k: int = 3,
    category: str | None = None,
    source_type: str | None = None,
) -> list[SimilarParagraph]:
    """純語意檢索，回傳最相近的已分類段落（供動態 few-shot 使用）。"""
    index = _get_index()
    filters = _build_filters(category, source_type)
    retriever = index.as_retriever(similarity_top_k=k, filters=filters)
    nodes = retriever.retrieve(paragraph)
    return [_node_to_similar_paragraph(n) for n in nodes]


DEFAULT_IMAGE_K = 4


def search_images(
    query: str,
    k: int = DEFAULT_IMAGE_K,
    category: str | None = None,
    source_type: str | None = None,
) -> list[SimilarParagraph]:
    """跟 search_similar() 完全獨立的另一次檢索，只在「有附圖」（has_image=True，
    build_index.py::_to_node() 寫入的欄位）的段落裡找最相關的幾筆。

    圖片段落的文字往往只是表格儲存格擷取出來的幾個字（例如「南投縣信義鄉七星湖」），
    語意向量訊號很弱，如果跟一般段落混在同一個 k 名額裡用相似度排序，幾乎搶不贏
    內容完整的段落、很少真的被檢索到。獨立跑一次「只在有圖的段落裡找」，圖片才會
    穩定有機會被顯示出來，也不會佔用一般文字引用的 k 名額。"""
    index = _get_index()
    conditions = [ExactMatchFilter(key="has_image", value="true")]
    if category:
        conditions.append(ExactMatchFilter(key="category_primary", value=category))
    if source_type:
        conditions.append(ExactMatchFilter(key="source_type", value=source_type))
    retriever = index.as_retriever(similarity_top_k=k, filters=MetadataFilters(filters=conditions))
    nodes = retriever.retrieve(query)
    return [_node_to_similar_paragraph(n) for n in nodes]


# CitationQueryEngine 內部把每個引用片段的文字直接改寫成 "Source N:\n{原文}\n"
# （寫死在 llama_index 原始碼裡、不能用參數關掉），顯示給使用者看之前要把這個
# 內部標記去掉，不然引用來源的段落預覽會多出一行「Source 3:」。
_CITATION_PREFIX_RE = re.compile(r"^Source \d+:\s*\n")


def _strip_citation_prefix(text: str) -> str:
    return _CITATION_PREFIX_RE.sub("", text)


# 模板的少樣本範例裡示範了「回答：」這個標籤，Gemini 有時候會把它當成輸出格式的
# 一部分照抄一份到真正的答案開頭（例如「回答：信義鄉群山環繞...」），這裡把它
# 去掉，避免使用者在 UI 上看到多餘的「回答：」字樣。
_ANSWER_PREFIX_RE = re.compile(r"^\s*(回答|答案)[：:]\s*")


def _strip_answer_prefix(text: str) -> str:
    return _ANSWER_PREFIX_RE.sub("", text)


def _scope_clause(scope: str | None) -> str:
    if scope == SCOPE_XINYI:
        return (
            "\n如果某個資料來源談的是南投縣其他鄉鎮或整個南投縣、沒有明確關聯到"
            "信義鄉的內容，不要引用它來回答（除非問題本身就是問信義鄉以外的範圍）。"
        )
    return ""


def _citation_qa_template(scope: str | None) -> PromptTemplate:
    """CitationQueryEngine 的問答 prompt：翻成繁體中文，並依 scope 動態插入地理
    範圍限定句。範例裡刻意寫 "Source 1:" 英文（而非中文「來源 1」）是因為
    CitationQueryEngine 組 context_str 時真的就是塞這個英文格式，範例跟實際
    看到的格式一致，Gemini 比較不會混淆。

    使用者是教授／專業研究者，範例特意示範「把來源裡的具體細節——年代、人名、
    制度名稱——都寫進答案」，而不是只挑重點簡短帶過，引導模型往更詳細精確的
    方向回答，而不只是換句話說一遍。"""
    template_str = (
        "你是為學術研究者與專業人士服務的方志問答助理，回答對象具備相關領域背景，"
        "不需要簡化用詞或省略細節。請只根據下方提供的資料來源回答問題，不要使用"
        "你原本就知道的知識；回答時盡量把來源裡出現的具體事實都寫進去（例如確切"
        "年代、人名、地名、統計數據、制度或機構名稱），不要只挑重點簡短帶過或用"
        "籠統字眼概括。如果不同來源之間的說法有出入、或資料只涵蓋問題的部分面向，"
        "請如實指出這些落差與限制，不要為了讓答案看起來完整而抹平細節。\n"
        "引用資料來源時，在對應句子後面加上該來源的編號，例如：\n"
        "Source 1:\n信義鄉在日治時期設有蕃童教育所，昭和8年（1933年）設立於望鄉部落。\n"
        "Source 2:\n新高郡下轄六個街庄，信義鄉（當時稱久美庄）屬其中之一。\n"
        "問題：信義鄉在日治時期的行政與教育概況？\n"
        "答案：信義鄉在日治時期設有蕃童教育所，昭和8年（1933年）設立於望鄉部落 [1]；"
        "行政上隸屬新高郡管轄，當時稱為久美庄，屬新高郡下轄六個街庄之一 [2]。\n"
        "（中括號裡只寫數字本身，例如 [1]，不要寫成 [Source 1]；不要在答案開頭"
        "重複「答案：」這個字；上面範例只是示範引用格式，實際回答時要盡量把來源"
        "裡出現的具體細節都寫進去。）\n"
        f"{_scope_clause(scope)}\n"
        "以下是這次問題可用的資料來源：\n"
        "------\n"
        "{context_str}\n"
        "------\n"
        "問題：{query_str}\n"
        "回答："
    )
    return PromptTemplate(template_str)


def answer_question(
    question: str,
    k: int = 5,
    model: str = DEFAULT_LLM_MODEL,
    source_type: str | None = None,
    scope: str | None = None,
) -> AnswerWithCitations:
    """檢索相關段落，交給 Gemini 生成逐句標註引用編號（[1][2]…）的回答。
    source_type：限定只從「論文」或「書籍」來源檢索，None 表示不限。
    scope：SCOPE_XINYI 限定只用明確跟信義鄉相關的段落作答，None／SCOPE_NANTOU 不限。"""
    index = _get_index()
    Settings.llm = GoogleGenAI(
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        max_retries=DEFAULT_MAX_RETRIES,
    )

    filters = _build_filters(None, source_type)
    retriever = index.as_retriever(similarity_top_k=k, filters=filters)
    query_engine = CitationQueryEngine.from_args(
        index,
        retriever=retriever,
        citation_qa_template=_citation_qa_template(scope),
        citation_chunk_size=1024,
    )
    response = query_engine.query(question)

    citations = []
    for node in response.source_nodes:
        images = node.node.metadata.get("images", "")
        citations.append(Citation(
            id=node.node.id_,
            source=node.node.metadata.get("source", ""),
            page=node.node.metadata.get("page", ""),
            paragraph=_strip_citation_prefix(node.node.get_content()),
            score=node.score or 0.0,
            images=images.split(",") if images else [],
        ))

    # 圖片走獨立檢索（見 search_images() 說明），不佔用上面 k 個文字引用的名額，
    # 也不影響回答本身的生成（Gemini 完全不知道這批圖片的存在）。
    images = search_images(question, source_type=source_type)

    return AnswerWithCitations(
        answer=_strip_answer_prefix(str(response)), citations=citations, images=images
    )


def _print_search_results(results: list[SimilarParagraph]) -> None:
    for i, r in enumerate(results, 1):
        preview = r.paragraph[:60].replace("\n", " ")
        print(f"[{i}] {r.id} (score={r.score:.3f}) | {' / '.join(r.categories)}")
        print(f"    來源：{r.source} 第 {r.page} 頁")
        print(f"    {preview}...")


def _print_answer(result: AnswerWithCitations) -> None:
    print(result.answer)
    print("\n引用來源：")
    for c in result.citations:
        print(f"  - {c.id}｜{c.source} 第 {c.page} 頁（相關度 {c.score:.0%}）")
        preview = c.paragraph[:200].replace("\n", " ")
        print(f"    {preview}{'...' if len(c.paragraph) > 200 else ''}")
    if result.images:
        print("\n相關圖片：")
        for r in result.images:
            print(f"  - {r.id}｜{r.source} 第 {r.page} 頁 → {', '.join(r.images)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 查詢引擎（鄉志段落檢索與問答）")
    parser.add_argument("--ask", metavar="QUESTION", help="向鄉志編纂問答助手提問")
    parser.add_argument("--search", metavar="TEXT", help="純語意檢索相似段落")
    parser.add_argument("--k", type=int, default=5, help="檢索筆數（預設 5）")
    parser.add_argument("--category", default=None, help="限定分類（僅 --search 支援）")
    parser.add_argument(
        "--source-type", default=None, choices=["論文", "書籍"],
        help="限定資料來源（論文／書籍），預設不限",
    )
    parser.add_argument(
        "--scope", default=None, choices=[SCOPE_XINYI, SCOPE_NANTOU],
        help="地理範圍（僅 --ask 支援），預設不限",
    )
    args = parser.parse_args()

    if args.ask:
        result = answer_question(args.ask, k=args.k, source_type=args.source_type, scope=args.scope)
        _print_answer(result)
    elif args.search:
        results = search_similar(args.search, k=args.k, category=args.category, source_type=args.source_type)
        _print_search_results(results)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
