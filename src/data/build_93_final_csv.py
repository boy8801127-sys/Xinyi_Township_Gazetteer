# -*- coding: utf-8 -*-
"""把理蕃之友／理蕃誌稿（來源代碼 93）6 卷的本機 CSV（classify_csv_with_gemini.py
分類、import_csv_to_notion.py 匯入 Notion 用的格式：id／paragraph(內文)／
source(資料來源)／page(頁數)…）轉成 build_labeled_corpus.py 的 EXTRA_CSV_SOURCES
預期格式（ID／段落／頁數／來源文章），輸出到 output/paragraphs_93_final.csv。

output/ 整個目錄不進版控，這份合併結果只存在本機——之後如果需要重新產生（例如
output/ 被清掉、或分類結果有異動要重新合併），直接重跑這支即可，不用再手動兜資料。

用法：
    python -m src.data.build_93_final_csv <csv_path> [<csv_path> ...]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from .import_csv_to_notion import load_rows

OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "output" / "paragraphs_93_final.csv"


def build(csv_paths: list[Path]) -> None:
    out_rows = []
    for p in csv_paths:
        rows = load_rows(p)
        for r in rows:
            out_rows.append({
                "ID": r["id"].strip(),
                "段落": r["paragraph(內文)"],
                "頁數": r["page(頁數)"],
                "來源文章": r["source(資料來源)"],
            })

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ID", "段落", "頁數", "來源文章"])
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"寫入 {OUTPUT_PATH}：{len(out_rows)} 筆")


def main() -> int:
    parser = argparse.ArgumentParser(description="把理蕃之友／理蕃誌稿卷別 CSV 合併成 build_labeled_corpus.py 用的 final CSV")
    parser.add_argument("csv_paths", nargs="+", help="一或多個已填好 id 的卷別 CSV")
    args = parser.parse_args()

    paths = [Path(p) for p in args.csv_paths]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"找不到檔案：{', '.join(str(p) for p in missing)}")

    build(paths)
    return 0


if __name__ == "__main__":
    sys.exit(main())
