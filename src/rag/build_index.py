# -*- coding: utf-8 -*-
"""
用 LlamaIndex + Chroma + Voyage embeddings 為 labeled_corpus.jsonl 建立向量索引。

前置作業：
    python -m src.data.build_labeled_corpus

使用方式：
    python -m src.rag.build_index
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from dotenv import load_dotenv
from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.embeddings.voyageai import VoyageEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS_PATH = ROOT / "src" / "data" / "labeled_corpus.jsonl"
CHROMA_DIR = ROOT / "vectorstore" / "chroma"
COLLECTION_NAME = "xinyi_paragraphs"

EMBED_MODEL_NAME = "voyage-3"


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


def _to_node(entry: dict) -> TextNode:
    categories = entry.get("categories", [])
    keywords = entry.get("keywords", [])
    images = entry.get("images", [])
    # id 前綴代表資料來源類型（見 src/data/extract_books.py／export_paragraphs.py 的編號規則）：
    # B 開頭＝《南投縣志》等書籍內容，其餘（P 開頭）＝碩博士論文，供 UI／CLI 依來源篩選用。
    source_type = "書籍" if entry["id"].startswith("B") else "論文"
    return TextNode(
        id_=entry["id"],
        text=entry["paragraph"],
        metadata={
            "source": entry.get("source", ""),
            "page": str(entry.get("page", "")),
            "category_primary": categories[0] if categories else "無法判斷",
            "categories": ",".join(categories),
            "keywords": ",".join(keywords),
            "reason": entry.get("reason", ""),
            "source_type": source_type,
            "images": ",".join(images),
            # 獨立於 categories/source_type 之外，讓 query_engine.search_images() 能用
            # ExactMatchFilter 篩出「有圖」的段落，不用對逗號接字串做子字串比對。
            # 存字串而不是 Python bool——llama_index 的 MetadataFilter.value 型別只接受
            # str/int/float/list，不接受 bool（實測過，傳 True 會被 pydantic 直接拒絕）。
            "has_image": "true" if images else "false",
        },
    )


def build_index() -> None:
    entries = _load_corpus()
    print(f"讀取語料：{len(entries)} 筆")

    nodes = [_to_node(e) for e in entries]

    Settings.embed_model = VoyageEmbedding(
        model_name=EMBED_MODEL_NAME,
        embed_batch_size=8,
    )

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(COLLECTION_NAME)

    if collection.count() > 0:
        print(f"清空既有集合（原有 {collection.count()} 筆），重新建立索引…")
        client.delete_collection(COLLECTION_NAME)
        collection = client.get_or_create_collection(COLLECTION_NAME)

    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    print("開始 embedding 並寫入向量庫（依資料量可能需數分鐘）…")
    VectorStoreIndex(
        nodes,
        storage_context=storage_context,
        show_progress=True,
    )

    print(f"\n索引完成，共 {collection.count()} 筆，儲存於：{CHROMA_DIR}")


if __name__ == "__main__":
    build_index()
