# -*- coding: utf-8 -*-
"""
零成本補丁：只更新「已經在 Chroma 索引裡」的段落的 metadata，不重新 embedding、
不呼叫 Voyage API。用途是 labeled_corpus.jsonl 的 metadata 欄位（例如新加的
images）有變動、但段落文字本身沒變時，把既有向量庫的 metadata 同步到最新。

跟 add_to_index.py 互補：add_to_index.py 負責把「還沒被索引過」的新段落嵌入
進去（會呼叫 Voyage API）；這支只處理「已經被索引過」的段落，純本機
collection.update(...)。兩支通常搭配著跑：先 patch_metadata 同步舊資料，
再 add_to_index 補新資料。

使用方式：
    python -m src.rag.patch_metadata
"""
from __future__ import annotations

import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb

from .build_index import CHROMA_DIR, COLLECTION_NAME, _load_corpus, _to_node


def patch_metadata() -> None:
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

    to_patch = [e for e in entries if e["id"] in existing_ids]
    if not to_patch:
        print("沒有已存在的段落需要補 metadata。")
        return

    ids = [e["id"] for e in to_patch]
    metadatas = [_to_node(e).metadata for e in to_patch]
    batch_size = 5000  # Chroma 對單次 update 的 batch 數有上限（實測遇過 max 5461）
    for i in range(0, len(ids), batch_size):
        collection.update(ids=ids[i:i + batch_size], metadatas=metadatas[i:i + batch_size])

    with_images = sum(1 for e in to_patch if e.get("images"))
    print(f"完成，共更新 {len(to_patch)} 筆 metadata（其中 {with_images} 筆帶有 images），"
          "embedding 完全沒有變動、未呼叫 Voyage API。")


if __name__ == "__main__":
    patch_metadata()
