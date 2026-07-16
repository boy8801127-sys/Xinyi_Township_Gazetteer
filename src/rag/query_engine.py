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
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from dotenv import load_dotenv
from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.schema import NodeWithScore
from llama_index.core.vector_stores import (
    ExactMatchFilter,
    MetadataFilters,
)
from llama_index.embeddings.voyageai import VoyageEmbedding
from llama_index.llms.google_genai import GoogleGenAI
from llama_index.vector_stores.chroma import ChromaVectorStore

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent.parent
CHROMA_DIR = ROOT / "vectorstore" / "chroma"
COLLECTION_NAME = "xinyi_paragraphs"

EMBED_MODEL_NAME = "voyage-3"
DEFAULT_LLM_MODEL = "gemini-3.1-flash-lite"
# 明確指定，不吃 GoogleGenAI 的預設值（None＝跟模型上限走、max_retries=3）——
# 分點列出＋多筆引用的回答容易超過幾百字，1024 給足夠空間；retries 拉高到 5 降低單次
# API 抖動就整段失敗的機率。
DEFAULT_MAX_TOKENS = 1024
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


@dataclass
class Citation:
    id: str
    source: str
    page: str


@dataclass
class AnswerWithCitations:
    answer: str
    citations: list[Citation] = field(default_factory=list)


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
    return SimilarParagraph(
        id=node.node.id_,
        paragraph=node.node.get_content(),
        source=meta.get("source", ""),
        page=meta.get("page", ""),
        categories=categories.split(",") if categories else [],
        keywords=keywords.split(",") if keywords else [],
        reason=meta.get("reason", ""),
        score=node.score or 0.0,
    )


def search_similar(
    paragraph: str,
    k: int = 3,
    category: str | None = None,
) -> list[SimilarParagraph]:
    """純語意檢索，回傳最相近的已分類段落（供動態 few-shot 使用）。"""
    index = _get_index()
    filters = None
    if category:
        filters = MetadataFilters(
            filters=[ExactMatchFilter(key="category_primary", value=category)]
        )
    retriever = index.as_retriever(similarity_top_k=k, filters=filters)
    nodes = retriever.retrieve(paragraph)
    return [_node_to_similar_paragraph(n) for n in nodes]


def answer_question(
    question: str,
    k: int = 5,
    model: str = DEFAULT_LLM_MODEL,
) -> AnswerWithCitations:
    """檢索相關段落，交給 Gemini 生成附引用來源的回答。"""
    index = _get_index()
    Settings.llm = GoogleGenAI(
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        max_retries=DEFAULT_MAX_RETRIES,
    )

    query_engine = index.as_query_engine(similarity_top_k=k)
    response = query_engine.query(question)

    citations = [
        Citation(
            id=node.node.id_,
            source=node.node.metadata.get("source", ""),
            page=node.node.metadata.get("page", ""),
        )
        for node in response.source_nodes
    ]
    return AnswerWithCitations(answer=str(response), citations=citations)


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
        print(f"  - {c.id}｜{c.source} 第 {c.page} 頁")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 查詢引擎（鄉志段落檢索與問答）")
    parser.add_argument("--ask", metavar="QUESTION", help="向鄉志編纂問答助手提問")
    parser.add_argument("--search", metavar="TEXT", help="純語意檢索相似段落")
    parser.add_argument("--k", type=int, default=5, help="檢索筆數（預設 5）")
    parser.add_argument("--category", default=None, help="限定分類（僅 --search 支援）")
    args = parser.parse_args()

    if args.ask:
        result = answer_question(args.ask, k=args.k)
        _print_answer(result)
    elif args.search:
        results = search_similar(args.search, k=args.k, category=args.category)
        _print_search_results(results)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
