# -*- coding: utf-8 -*-
"""
id／source 格式標準化遷移前的一次性資料備份。

備份 labeled_corpus.jsonl、results/*.json、output/paragraphs_all_merged.csv、
images/books/（含 deploy 副本）、vectorstore/chroma/（含 deploy 副本）到帶時間戳記的
backup/ 資料夾，供遷移腳本（migrate_ids.py／rename_migrated_images.py／
migrate_vectorstore_ids.py）萬一出錯時還原。

使用方式：
    python -m src.data.backup_before_id_migration
"""
from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent

TARGETS: list[tuple[str, Path]] = [
    ("labeled_corpus.jsonl", ROOT / "src" / "data" / "labeled_corpus.jsonl"),
    ("results", ROOT / "results"),
    ("paragraphs_all_merged.csv", ROOT / "output" / "paragraphs_all_merged.csv"),
    ("images_books", ROOT / "images" / "books"),
    ("deploy_images_books", ROOT / "deploy" / "rag_space" / "images" / "books"),
    ("vectorstore_chroma", ROOT / "vectorstore" / "chroma"),
    ("deploy_vectorstore_chroma", ROOT / "deploy" / "rag_space" / "vectorstore" / "chroma"),
]


def backup() -> Path:
    dest_root = ROOT / "backup" / f"pre_id_migration_{date.today():%Y%m%d}"
    if dest_root.exists():
        raise FileExistsError(
            f"備份目的地已存在，避免誤覆蓋前一次備份，請手動確認/清理後再執行：{dest_root}"
        )

    dest_root.mkdir(parents=True)
    print(f"備份目的地：{dest_root}\n")

    for name, src in TARGETS:
        dest = dest_root / name
        if not src.exists():
            print(f"跳過（來源不存在）：{src}")
            continue
        if src.is_dir():
            shutil.copytree(src, dest)
            n = sum(1 for _ in dest.rglob("*") if _.is_file())
            print(f"已備份目錄：{src} -> {dest}（{n} 個檔案）")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            print(f"已備份檔案：{src} -> {dest}")

    print(f"\n備份完成：{dest_root}")
    return dest_root


if __name__ == "__main__":
    backup()
