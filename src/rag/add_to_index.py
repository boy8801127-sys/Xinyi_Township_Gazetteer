# -*- coding: utf-8 -*-
"""
增量更新既有 Chroma 向量索引：只對 labeled_corpus.jsonl 裡「還不在索引中」的
新段落呼叫 Voyage embedding API，不重新嵌入已存在的段落。

跟 build_index.py 的差異：build_index.py 是「從零全量重建」（會刪掉整個
collection 再對全部段落重新嵌入一次）；這支是「只嵌入新增的部分」，append
進既有索引，已存在的段落完全不會被重新嵌入或刪除，適合語料只是新增一批
資料來源（而非既有段落內容變動）的情境。

前置作業：
    python -m src.data.build_labeled_corpus

使用方式：
    python -m src.rag.add_to_index
"""
from __future__ import annotations

import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from llama_index.core import Settings, StorageContext, VectorStoreIndex
from llama_index.embeddings.voyageai import VoyageEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from .build_index import (
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBED_MODEL_NAME,
    _load_corpus,
    _to_node,
)


def add_new_entries() -> None:
    entries = _load_corpus()
    print(f"語料庫共 {len(entries)} 筆")

    if not CHROMA_DIR.exists():
        raise FileNotFoundError(
            f"找不到既有向量庫 {CHROMA_DIR}，請先執行：python -m src.rag.build_index"
        )

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(COLLECTION_NAME)
    existing_ids = set(collection.get(include=[])["ids"])
    print(f"既有索引：{len(existing_ids)} 筆")

    new_entries = [e for e in entries if e["id"] not in existing_ids]
    if not new_entries:
        print("沒有新段落需要 embedding，索引已是最新。")
        return

    print(f"待新增：{len(new_entries)} 筆（只會對這些呼叫 Voyage embedding API）")

    Settings.embed_model = VoyageEmbedding(
        model_name=EMBED_MODEL_NAME,
        embed_batch_size=8,
    )

    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)

    nodes = [_to_node(e) for e in new_entries]
    print("開始 embedding 並寫入向量庫…")
    index.insert_nodes(nodes)

    print(f"\n完成，索引現有 {collection.count()} 筆（新增 {len(new_entries)} 筆，儲存於：{CHROMA_DIR}）")


if __name__ == "__main__":
    add_new_entries()
