# -*- coding: utf-8 -*-
"""
一次性腳本：讀 migrate_ids.py 產生的 output/id_migration_map.csv，把
images/books/、deploy/rag_space/images/books/ 兩份目錄底下、檔名是舊 id 的圖片
實體檔案改名成新 id（副檔名不變，同目錄內 rename，不搬動內容）。

執行前 migrate_ids.py 必須已經跑過（否則 id_migration_map.csv 不存在）。
可重複執行：目標新檔名已存在就跳過，舊檔名已經不存在（代表已經改過）也跳過。

使用方式：
    python -m src.data.rename_migrated_images
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "output" / "id_migration_map.csv"

IMAGE_DIRS = [
    ROOT / "images" / "books",
    ROOT / "deploy" / "rag_space" / "images" / "books",
]


def _load_mapping() -> dict[str, str]:
    if not MAP_PATH.exists():
        raise FileNotFoundError(f"找不到 {MAP_PATH}，請先執行：python -m src.data.migrate_ids")
    mapping = {}
    with MAP_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            mapping[row["old_id"]] = row["new_id"]
    return mapping


def rename_all() -> None:
    mapping = _load_mapping()

    for image_dir in IMAGE_DIRS:
        if not image_dir.exists():
            print(f"跳過（目錄不存在）：{image_dir}")
            continue

        renamed = skipped_exists = skipped_no_match = 0
        for path in sorted(image_dir.iterdir()):
            if not path.is_file():
                continue
            stem = path.stem
            new_stem = mapping.get(stem)
            if new_stem is None:
                skipped_no_match += 1
                continue
            new_path = path.with_name(f"{new_stem}{path.suffix}")
            if new_path.exists():
                skipped_exists += 1
                continue
            path.rename(new_path)
            renamed += 1

        print(f"{image_dir}：改名 {renamed} 個，已是新檔名跳過 {skipped_exists} 個，"
              f"對照表無此 id 跳過 {skipped_no_match} 個")


if __name__ == "__main__":
    rename_all()
