# -*- coding: utf-8 -*-
"""
合併 output/paragraphs_all_merged.csv（段落／來源／頁數）與 results/*.json
（Claude 分類結果）成統一語料，供 RAG 索引與 fine-tune 資料集共用。

使用方式：
    python -m src.data.build_labeled_corpus
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = ROOT / "results"
OUTPUT_DIR = ROOT / "output"
CORPUS_PATH = ROOT / "src" / "data" / "labeled_corpus.jsonl"

CSV_CANDIDATES = [
    OUTPUT_DIR / "paragraphs_all_merged.csv",
    OUTPUT_DIR / "paragraphs_all.csv",
]


def _load_paragraph_csv() -> dict[str, dict]:
    for path in CSV_CANDIDATES:
        if path.exists():
            print(f"讀取段落來源：{path.name}")
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                return {row["ID"]: row for row in reader if row.get("ID")}
    raise FileNotFoundError(
        f"找不到段落 CSV，需先執行 LLM 段落匯出（main.py 選項 4/5）。"
        f"預期路徑：{[str(p) for p in CSV_CANDIDATES]}"
    )


def _load_classified_records() -> list[dict]:
    records = []
    for path in sorted(RESULTS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        records.extend(data.get("records", []))
    return records


def build_corpus() -> None:
    csv_rows = _load_paragraph_csv()
    records = _load_classified_records()

    kept = 0
    skipped_no_categories = 0
    skipped_error = 0
    skipped_no_csv_match = 0
    duplicate_ids = 0

    category_counts: dict[str, int] = {}
    seen_ids: set[str] = set()

    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CORPUS_PATH.open("w", encoding="utf-8") as out:
        for rec in records:
            notion_id = rec.get("notion_id", "")

            if rec.get("error"):
                skipped_error += 1
                continue
            if not rec.get("categories"):
                skipped_no_categories += 1
                continue

            row = csv_rows.get(notion_id)
            if row is None:
                skipped_no_csv_match += 1
                continue

            if notion_id in seen_ids:
                duplicate_ids += 1
                continue
            seen_ids.add(notion_id)

            entry = {
                "id": notion_id,
                "paragraph": rec["paragraph"],
                "source": row.get("來源文章", ""),
                "page": row.get("頁數", ""),
                "categories": rec["categories"],
                "reason": rec.get("reason", ""),
                "keywords": rec.get("keywords", []),
            }
            out.write(json.dumps(entry, ensure_ascii=False) + "\n")
            kept += 1
            for cat in rec["categories"]:
                category_counts[cat] = category_counts.get(cat, 0) + 1

    print(f"\n輸出：{CORPUS_PATH}")
    print(f"保留筆數：{kept}")
    print(f"跳過（error）：{skipped_error}")
    print(f"跳過（無分類）：{skipped_no_categories}")
    print(f"跳過（CSV 無對應）：{skipped_no_csv_match}")
    print(f"跳過（重複 ID）：{duplicate_ids}")
    print("\n各分類筆數：")
    for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    build_corpus()
