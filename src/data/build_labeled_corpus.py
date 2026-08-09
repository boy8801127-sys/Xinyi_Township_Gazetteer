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

from .journal_bibliography import format_journal_citation
from .paper_bibliography import format_paper_citation
from .source_codes import code_of

ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = ROOT / "results"
OUTPUT_DIR = ROOT / "output"
CORPUS_PATH = ROOT / "src" / "data" / "labeled_corpus.jsonl"

CSV_CANDIDATES = [
    OUTPUT_DIR / "paragraphs_all_merged.csv",
    OUTPUT_DIR / "paragraphs_all.csv",
]

# 期刊論文（代碼 97）走獨立的擷取／人工複核流程（export_paragraphs_journal.py →
# split_and_merge_paragraphs_xlsx.py），最終合併結果存在單獨的 CSV，不寫進
# paragraphs_all_merged.csv（避免動到已經匯入 Notion 的既有 92／98 資料）——這裡
# 額外合併讀入即可。之後其他來源代碼若也有類似獨立複核流程，比照這裡加一行。
EXTRA_CSV_SOURCES = [
    OUTPUT_DIR / "paragraphs_journal_final.csv",
]


def _load_paragraph_csv() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    found_primary = False
    for path in CSV_CANDIDATES:
        if path.exists():
            print(f"讀取段落來源：{path.name}")
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                rows.update({row["ID"]: row for row in reader if row.get("ID")})
            found_primary = True
            break
    if not found_primary:
        raise FileNotFoundError(
            f"找不到段落 CSV，需先執行 LLM 段落匯出（main.py 選項 4/5）。"
            f"預期路徑：{[str(p) for p in CSV_CANDIDATES]}"
        )

    for path in EXTRA_CSV_SOURCES:
        if path.exists():
            print(f"讀取段落來源：{path.name}")
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                extra_rows = {row["ID"]: row for row in reader if row.get("ID")}
            # 額外來源不該動到主要 CSV 已經有的 ID（例如碰巧共用了同一個來源代碼
            # 前綴）——目前各來源代碼前綴互斥（97 vs 92／98），理論上不會撞，
            # 撞到印出警告總比悄悄覆蓋掉既有資料好察覺。
            collisions = set(extra_rows) & set(rows)
            if collisions:
                print(
                    f"⚠️ {path.name} 有 {len(collisions)} 筆 ID 跟既有段落來源重複，"
                    f"將被覆蓋（前 5 筆：{sorted(collisions)[:5]}）"
                )
            rows.update(extra_rows)

    return rows


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

            page = row.get("頁數", "")
            source = row.get("來源文章", "")
            if code_of(notion_id) == "98":
                paper_index = notion_id.split("-")[1]
                source = format_paper_citation(paper_index, page) or source
            elif code_of(notion_id) == "97":
                paper_index = notion_id.split("-")[1]
                source = format_journal_citation(paper_index, page) or source

            entry = {
                "id": notion_id,
                "paragraph": rec["paragraph"],
                "source": source,
                "page": page,
                "categories": rec["categories"],
                "reason": rec.get("reason", ""),
                "keywords": rec.get("keywords", []),
                "images": rec.get("images", []),
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
