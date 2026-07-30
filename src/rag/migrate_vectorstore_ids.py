# -*- coding: utf-8 -*-
"""
一次性腳本：把既有 Chroma 向量庫裡的 document id 從舊格式（P11-200／B01-079）
換成新格式（98-11-200／92-01-079），完全不重新呼叫 Voyage embedding API——段落
文字沒有變，只是換個 id／metadata 標籤：

    1. 用 collection.get(ids=舊id, include=["embeddings"]) 撈出既有向量
    2. 用新版 labeled_corpus.jsonl 重新算好的 metadata（source／source_type／
       images 都已經是新格式）＋撈出的舊 embedding，組成 TextNode，
       透過 ChromaVectorStore.add() 寫入新 id（ChromaVectorStore.add() 只是
       把 node.get_embedding() 直接寫進 Chroma，不會呼叫 embed model）
    3. 全部新 id 確認寫入成功、筆數吻合後，才刪除舊 id

前置：migrate_ids.py／rename_migrated_images.py／build_labeled_corpus.py 都要
已經跑過（新版 labeled_corpus.jsonl 要已經是新 id）。

使用方式（vectorstore/chroma 與 deploy/rag_space/vectorstore/chroma 各跑一次）：
    python -m src.rag.migrate_vectorstore_ids --chroma-path vectorstore/chroma
    python -m src.rag.migrate_vectorstore_ids --chroma-path deploy/rag_space/vectorstore/chroma
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore

from .build_index import COLLECTION_NAME, _load_corpus, _to_node

ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "output" / "id_migration_map.csv"
BATCH_SIZE = 2000  # 比照 patch_metadata.py 遇過的 Chroma 單次操作上限（5461）留餘裕


def _load_new_to_old_mapping() -> dict[str, str]:
    if not MAP_PATH.exists():
        raise FileNotFoundError(f"找不到 {MAP_PATH}，請先執行：python -m src.data.migrate_ids")
    mapping = {}
    with MAP_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            mapping[row["new_id"]] = row["old_id"]
    return mapping


def _batched(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def migrate(chroma_path: Path) -> None:
    new_to_old = _load_new_to_old_mapping()
    entries = _load_corpus()
    entries_by_new_id = {e["id"]: e for e in entries}

    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(COLLECTION_NAME)
    vector_store = ChromaVectorStore(chroma_collection=collection)

    before_count = collection.count()
    print(f"[{chroma_path}] 遷移前筆數：{before_count}")

    to_migrate = [
        (new_id, old_id) for new_id, old_id in new_to_old.items() if new_id in entries_by_new_id
    ]
    print(f"待遷移（新 id 在語料庫裡且對照表有舊 id）：{len(to_migrate)} 筆")

    added_new_ids: list[str] = []
    missing_old_ids: list[str] = []

    for batch in _batched(to_migrate, BATCH_SIZE):
        old_ids = [old_id for _, old_id in batch]
        fetched = collection.get(ids=old_ids, include=["embeddings"])
        embedding_by_old_id = dict(zip(fetched["ids"], fetched["embeddings"]))

        nodes = []
        for new_id, old_id in batch:
            embedding = embedding_by_old_id.get(old_id)
            if embedding is None:
                missing_old_ids.append(old_id)
                continue
            node = _to_node(entries_by_new_id[new_id])
            node.embedding = list(embedding)
            nodes.append(node)

        if nodes:
            added_new_ids.extend(vector_store.add(nodes))

    print(f"新 id 寫入成功：{len(added_new_ids)} 筆")
    if missing_old_ids:
        print(f"警告：{len(missing_old_ids)} 個舊 id 在向量庫裡找不到既有 embedding，"
              f"未寫入對應新 id，也不會刪除（保留原狀）：{missing_old_ids[:20]}")

    after_add_count = collection.count()
    print(f"寫入新 id 後筆數：{after_add_count}（預期 {before_count + len(added_new_ids)}）")

    if len(added_new_ids) != len(to_migrate) - len(missing_old_ids):
        raise RuntimeError("寫入筆數與預期不符，中止刪除舊 id 以免資料遺失，請人工檢查。")

    old_ids_to_delete = [old_id for new_id, old_id in to_migrate if old_id not in missing_old_ids]
    for batch in _batched(old_ids_to_delete, BATCH_SIZE):
        collection.delete(ids=batch)

    after_delete_count = collection.count()
    print(f"刪除舊 id 後筆數：{after_delete_count}（預期 {before_count}，即單純換了 id 標籤，總筆數不變）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma-path", required=True, type=Path)
    args = parser.parse_args()
    migrate(args.chroma_path)
