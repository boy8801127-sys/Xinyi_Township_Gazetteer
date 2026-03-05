# -*- coding: utf-8 -*-
"""
將手動合併後的段落 CSV 進行欄位合併。

僅做「ID 為空者與上一列合併」：
- 段落：以「。」串接同群各列
- 頁數：合併為 min–max
- ID：保留群組第一列的 ID
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from typing import Any

try:
    from . import config
except ImportError:
    config = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "output" if config is None else config.OUTPUT_DIR

FIELDNAMES = ["ID", "段落", "來源文章", "頁數"]


def _parse_page_range(page_str: str) -> tuple[int, int]:
    """解析頁數字串，回傳 (起始頁, 結束頁)。支援 5、5–6、12-15 等格式。"""
    s = (page_str or "").strip()
    if not s:
        return 0, 0
    # 支援 –（en-dash）、-（hyphen）
    parts = re.split(r"[–\-]", s, maxsplit=1)
    try:
        start = int(parts[0].strip())
        end = int(parts[1].strip()) if len(parts) > 1 else start
        return start, end
    except (ValueError, IndexError):
        return 0, 0


def _merge_page_ranges(page_strs: list[str]) -> str:
    """合併多個頁數範圍為 min–max。"""
    if not page_strs:
        return ""
    pages: list[tuple[int, int]] = []
    for s in page_strs:
        start, end = _parse_page_range(s)
        if start > 0 or end > 0:
            pages.append((start, end))
    if not pages:
        return page_strs[0].strip() if page_strs else ""
    min_p = min(p[0] for p in pages)
    max_p = max(p[1] for p in pages)
    if min_p == max_p:
        return str(min_p)
    return f"{min_p}–{max_p}"


def merge_paragraph_rows(
    input_path: Path,
    output_path: Path | None = None,
    encoding: str = "utf-8-sig",
) -> Path:
    """
    讀取含合併標記的 CSV，將 ID 為空的列與上一列合併後輸出。

    - 段落：以「。」串接同群各列
    - 頁數：合併為 min–max
    - 來源文章、ID：取群組第一列
    """
    output_path = output_path or input_path.parent / (
        input_path.stem + "_merged.csv"
    )

    groups: list[list[dict[str, Any]]] = []
    current_group: list[dict[str, Any]] = []

    with open(input_path, "r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)  # 使用檔案標題列，支援含/不含區段
        for row in reader:
            row_id = (row.get("ID") or "").strip()
            para = (row.get("段落") or "").strip()
            source = (row.get("來源文章") or "").strip()
            pages = (row.get("頁數") or "").strip()

            # 跳過標題列
            if row_id == "ID":
                continue

            if row_id:
                if current_group:
                    groups.append(current_group)
                current_group = [{"ID": row_id, "段落": para, "來源文章": source, "頁數": pages}]
            else:
                current_group.append({"ID": "", "段落": para, "來源文章": source, "頁數": pages})

        if current_group:
            groups.append(current_group)

    merged_rows: list[dict[str, Any]] = []
    for group in groups:
        first = group[0]
        paragraphs = [r["段落"] for r in group if r["段落"]]
        page_strs = [r["頁數"] for r in group if r["頁數"]]
        merged_rows.append({
            "ID": first["ID"],
            "段落": "。".join(paragraphs),
            "來源文章": first["來源文章"],
            "頁數": _merge_page_ranges(page_strs),
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding=encoding) as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(merged_rows)

    return output_path


def main() -> int:
    """命令列入口：python -m src.merge_paragraph_rows [input.csv] [output.csv]"""
    if len(sys.argv) < 2:
        default_input = DEFAULT_OUTPUT_DIR / "paragraphs_all_first_arrange.csv"
        if default_input.exists():
            input_path = default_input
        else:
            print("用法: python -m src.merge_paragraph_rows <input.csv> [output.csv]", file=sys.stderr)
            print(f"範例: python -m src.merge_paragraph_rows {default_input}", file=sys.stderr)
            return 1
    else:
        input_path = Path(sys.argv[1])

    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    if not input_path.exists():
        print(f"檔案不存在: {input_path}", file=sys.stderr)
        return 1

    try:
        out = merge_paragraph_rows(input_path, output_path)
        print(f"已合併並輸出: {out}")
        return 0
    except Exception as e:
        print(f"錯誤: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sys.exit(main())
