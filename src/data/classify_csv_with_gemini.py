# -*- coding: utf-8 -*-
"""直接對本機 CSV 檔案的段落做 Gemini 分類與關鍵字擷取，把結果填回同一個 CSV，
不經過 Notion。

用在還沒決定怎麼匯入 Notion（母頁面、id 編號）之前，先把 categories／reason／
keywords 這三欄「填空」，方便先用 Excel 肉眼檢查分類結果——之後要匯入 Notion／
合併進 labeled_corpus.jsonl，再另外處理（欄位格式已經跟 import_paragraphs_to_notion.py
預期的很接近，屆時應該只需要另外補 id）。

分類邏輯（SYSTEM_PROMPT／分類任務／Gemini 模型與定價）全部直接從
classify_journal_with_gemini import 沿用，不複製也不改動那支（平行實驗模組慣例）。

CSV 欄位（比照信義鄉志＿《理蕃之友》系列的填寫範本）：
    來源代碼／id／paragraph(內文)／source(資料來源)／page(頁數)／
    categories／reason／keywords／images／備註
前兩列是範本說明列＋表頭列，從第 3 列開始才是資料。

用法：
    python -m src.data.classify_csv_with_gemini <csv_path> [<csv_path> ...] --estimate-cost
    python -m src.data.classify_csv_with_gemini <csv_path> [<csv_path> ...] --run --dry-run
    python -m src.data.classify_csv_with_gemini <csv_path> [<csv_path> ...] --run
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from .classify_journal_with_gemini import (
    AVG_INPUT_TOKENS_PER_ITEM,
    AVG_OUTPUT_TOKENS_PER_ITEM,
    GEMINI_INPUT_RATE,
    GEMINI_MODEL,
    GEMINI_OUTPUT_RATE,
    classify_paragraph_gemini,
)

SAVE_EVERY = 5
LIST_JOIN = "、"

HEADER = [
    "來源代碼", "id", "paragraph(內文)", "source(資料來源)", "page(頁數)",
    "categories", "reason", "keywords", "images", "備註",
]
_COL = {name: i for i, name in enumerate(HEADER)}


def _load_rows(csv_path: Path) -> tuple[list[str], list[str], list[list[str]]]:
    """回傳 (範本說明列, 表頭列, 資料列)。表頭列直接假設固定是 HEADER，不逐欄比對
    ——範本檔案是人工填寫、偶有欄位順序打字誤差的風險，但目前 6 份卷別檔案格式
    完全一致，先用固定順序，之後如果真的遇到欄位不一致再改成按欄名比對。"""
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        raise SystemExit(f"{csv_path} 內容不足兩列（範本說明列＋表頭列）")
    template_row, header_row = rows[0], rows[1]
    data_rows = [r for r in rows[2:] if any(c.strip() for c in r)]
    # 人工填寫的 CSV 常會漏填尾端的空欄，csv.reader 讀到的每列長度就會比 HEADER
    # 短——補齊到固定長度，避免後面用固定欄位索引存取時 IndexError。
    data_rows = [r + [""] * (len(HEADER) - len(r)) if len(r) < len(HEADER) else r for r in data_rows]
    return template_row, header_row, data_rows


def _save_rows(csv_path: Path, template_row: list[str], header_row: list[str], data_rows: list[list[str]]) -> None:
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(template_row)
        writer.writerow(header_row)
        writer.writerows(data_rows)


def _todo_count(csv_path: Path) -> int:
    _, _, data_rows = _load_rows(csv_path)
    return sum(
        1 for r in data_rows
        if r[_COL["paragraph(內文)"]].strip() and not r[_COL["categories"]].strip()
    )


def estimate_cost(csv_paths: list[Path]) -> None:
    total = 0
    for p in csv_paths:
        n = _todo_count(p)
        print(f"{p.name}：待分類 {n} 筆")
        total += n
    print(f"合計待分類：{total} 筆")
    if total == 0:
        print("沒有待分類的段落（categories 欄位都已經有值，或段落是空的）。")
        return
    input_cost = total * AVG_INPUT_TOKENS_PER_ITEM / 1e6 * GEMINI_INPUT_RATE
    output_cost = total * AVG_OUTPUT_TOKENS_PER_ITEM / 1e6 * GEMINI_OUTPUT_RATE
    est = input_cost + output_cost
    print(f"模型：{GEMINI_MODEL}")
    print(f"預估費用：約 ${est:.4f} USD（約 NT${est * 32:.2f}）")
    print("估算依據：沿用 notion_classify.py 對 10,099 筆既有資料的真實平均 token 用量換算，本次沒有呼叫任何付費 API。")


def _classify_file(csv_path: Path, dry_run: bool) -> None:
    template_row, header_row, data_rows = _load_rows(csv_path)
    todo_idx = [
        i for i, r in enumerate(data_rows)
        if r[_COL["paragraph(內文)"]].strip() and not r[_COL["categories"]].strip()
    ]
    print(f"\n=== {csv_path.name}：{len(todo_idx)} 筆待分類 ===")
    if not todo_idx:
        return
    if dry_run:
        for i in todo_idx[:3]:
            preview = data_rows[i][_COL["paragraph(內文)"]][:60].replace("\n", " ")
            print(f"  [dry-run] {preview}…")
        return

    for n, i in enumerate(todo_idx, 1):
        paragraph = data_rows[i][_COL["paragraph(內文)"]]
        try:
            parsed = classify_paragraph_gemini(paragraph)
            data_rows[i][_COL["categories"]] = LIST_JOIN.join(parsed["categories"])
            data_rows[i][_COL["reason"]] = parsed["reason"]
            data_rows[i][_COL["keywords"]] = LIST_JOIN.join(parsed["keywords"])
        except Exception as e:  # noqa: BLE001 - 單筆失敗要能繼續跑，不整批中斷
            print(f"  ⚠️ 第 {i + 3} 列分類失敗：{e}")
        if n % SAVE_EVERY == 0 or n == len(todo_idx):
            _save_rows(csv_path, template_row, header_row, data_rows)
            print(f"  {n}/{len(todo_idx)}（已存檔）", flush=True)


def run(csv_paths: list[Path], dry_run: bool) -> None:
    for p in csv_paths:
        _classify_file(p, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description="對本機 CSV 段落做 Gemini 分類，結果填回同一個 CSV")
    parser.add_argument("csv_paths", nargs="+", help="一或多個卷別 CSV 檔案路徑")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--estimate-cost", action="store_true", help="只估算費用，不呼叫任何付費 API")
    group.add_argument("--run", action="store_true", help="實際執行分類（可另外加 --dry-run 只預覽不呼叫 API）")
    parser.add_argument("--dry-run", action="store_true", help="配合 --run：只列出待分類筆數與前幾筆預覽，不呼叫 API")
    args = parser.parse_args()

    paths = [Path(p) for p in args.csv_paths]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"找不到檔案：{', '.join(str(p) for p in missing)}")

    if args.estimate_cost:
        estimate_cost(paths)
        return 0

    run(paths, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
