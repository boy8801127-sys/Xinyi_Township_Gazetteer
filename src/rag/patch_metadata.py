# -*- coding: utf-8 -*-
"""
零成本補丁：只更新「已經在 Chroma 索引裡」的段落的 metadata，不重新 embedding、
不呼叫 Voyage API。用途是 labeled_corpus.jsonl 的 metadata 欄位（例如新加的
images）有變動、但段落文字本身沒變時，把既有向量庫的 metadata 同步到最新。

跟 add_to_index.py 互補：add_to_index.py 負責把「還沒被索引過」的新段落嵌入
進去（會呼叫 Voyage API）；這支只處理「已經被索引過」的段落，純本機操作、
不呼叫 Voyage。兩支通常搭配著跑：先 patch_metadata 同步舊資料，再
add_to_index 補新資料。

【2026-08 修正】絕對不要改回 collection.update(ids=..., metadatas=...)：
LlamaIndex 存進 Chroma 時，每筆資料除了攤平的 metadata 欄位外，還會把整個
TextNode 序列化成一份 `_node_content` JSON 字串一起存進去；語意檢索
（collection.query()，也就是 query_engine.search_similar() 實際會走的路徑）
讀的是 `_node_content` 裡的 metadata，不是攤平欄位。collection.update() 只會
更新攤平欄位，`_node_content` 完全不會被動到——結果就是 collection.get(ids=..)
看起來像是修好了，但語意搜尋吐出來的還是舊資料（曾經在期刊論文頁碼修正時
踩到這個坑，19 筆資料 update() 後檢索出來還是舊頁碼）。

這裡改用 collection.upsert(...)：metadata 用 LlamaIndex 自己的
node_to_metadata_dict() 組（跟 ChromaVectorStore.add() 內部做的事完全一樣，
確保攤平欄位＋`_node_content` 一起同步），一次呼叫直接覆蓋既有資料，同樣不會
呼叫 Voyage API。**不要改回「先 collection.delete() 再 add()」**：那個寫法在
兩步之間有一段資料完全不在索引裡的空窗期，跑到一半中斷（斷線／OOM／Ctrl-C）
會直接掉資料，且這支工具刻意不重新呼叫 Voyage、救不回來，只能整庫從
backup_corpus.py 的備份還原重跑；upsert() 是單一原子呼叫，沒有這個空窗期。

使用方式：
    python -m src.rag.patch_metadata
"""
from __future__ import annotations

import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from llama_index.core.schema import MetadataMode
from llama_index.core.vector_stores.utils import node_to_metadata_dict

from .build_index import CHROMA_DIR, COLLECTION_NAME, _load_corpus, _to_node

# Chroma 對單次呼叫（get／upsert 的 ids 參數）的筆數有上限（實測遇過 max 5461），
# 全部批次操作（抓既有 embedding、upsert 補資料）都要照這個大小切。
_BATCH_SIZE = 5000


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

    emb_by_id: dict[str, list[float]] = {}
    for i in range(0, len(ids), _BATCH_SIZE):
        batch_ids = ids[i:i + _BATCH_SIZE]
        existing = collection.get(ids=batch_ids, include=["embeddings"])
        emb_by_id.update(zip(existing["ids"], existing["embeddings"]))

    nodes = []
    for e in to_patch:
        node = _to_node(e)
        node.embedding = list(emb_by_id[e["id"]])
        nodes.append(node)

    for i in range(0, len(nodes), _BATCH_SIZE):
        batch = nodes[i:i + _BATCH_SIZE]
        metadatas = []
        for node in batch:
            metadata_dict = node_to_metadata_dict(node, remove_text=True, flat_metadata=True)
            for key in metadata_dict:
                if metadata_dict[key] is None:
                    metadata_dict[key] = ""
            metadatas.append(metadata_dict)
        collection.upsert(
            ids=[node.node_id for node in batch],
            embeddings=[node.get_embedding() for node in batch],
            metadatas=metadatas,
            documents=[node.get_content(metadata_mode=MetadataMode.NONE) for node in batch],
        )

    with_images = sum(1 for e in to_patch if e.get("images"))
    print(f"完成，共更新 {len(to_patch)} 筆 metadata（其中 {with_images} 筆帶有 images），"
          "沿用既有 embedding upsert（攤平欄位＋_node_content 一起同步），未呼叫 Voyage API。")


if __name__ == "__main__":
    patch_metadata()
