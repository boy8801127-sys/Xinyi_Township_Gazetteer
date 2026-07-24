# -*- coding: utf-8 -*-
"""
讀回 output/images_review.csv 的人工審閱結果（photo／table 兩欄），把核准的圖片
寫回 results/books_南投縣志.json 各筆 record 的 "images" 欄位——這是唯一寫入
正式 results/*.json 的地方，之後 build_labeled_corpus.py 完全不用碰圖片邏輯，
只要照抄 rec.get("images", []) 就好。

判斷規則：一列只要 photo／table 任一欄非空白就算核准，該列的圖片會被列進
對應 id 的 "images"；兩欄都空白（不管是本來就沒被 extract_books.py 猜中、
還是人工看過確認不是）就是排除，"images" 維持空陣列。

之後如果重新審閱、改標記，改完 CSV 直接重跑這支腳本即可覆寫，不用重跑
整個 extract_books.py（圖片本體已經在 images/books/，不會重新抽取）。

前置作業：
    python -m src.data.extract_books
    （然後人工審閱 output/images_review.csv 的 photo／table 兩欄）

使用方式：
    python -m src.data.promote_reviewed_images
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
IMAGES_REVIEW_CSV_PATH = ROOT / "output" / "images_review.csv"
RESULTS_PATH = ROOT / "results" / "books_南投縣志.json"


def _load_approved_images() -> dict[str, list[str]]:
    """回傳 {id: [圖片檔名]}，只包含 photo／table 任一欄有標記的列。"""
    if not IMAGES_REVIEW_CSV_PATH.exists():
        raise FileNotFoundError(
            f"找不到 {IMAGES_REVIEW_CSV_PATH}，請先執行：python -m src.data.extract_books"
        )
    approved: dict[str, list[str]] = {}
    with IMAGES_REVIEW_CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("photo") or "").strip() or (row.get("table") or "").strip():
                image_id = row["ID"]
                filename = row["圖片檔名"]
                if image_id and filename:
                    approved.setdefault(image_id, []).append(filename)
    return approved


def promote() -> None:
    approved = _load_approved_images()
    print(f"審閱結果：{len(approved)} 筆核准圖片（{IMAGES_REVIEW_CSV_PATH.name}）")

    if not RESULTS_PATH.exists():
        raise FileNotFoundError(
            f"找不到 {RESULTS_PATH}，請先執行：python -m src.data.extract_books"
        )
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    updated = 0
    for rec in data.get("records", []):
        images = approved.get(rec.get("page_id", ""), [])
        rec["images"] = images
        if images:
            updated += 1

    RESULTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已寫回：{RESULTS_PATH}（{updated} 筆 record 帶有核准圖片）")
    print("下一步：python -m src.data.build_labeled_corpus")


if __name__ == "__main__":
    promote()
