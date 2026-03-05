# -*- coding: utf-8 -*-
"""信義鄉誌論文分類流程：擷取 PDF → 切分標註 → 分類匯出。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .segment_and_annotate import run_on_paper_dir, run_on_pdf
from .extract_pdf import list_papers
from .classify_and_export import run_export


def main() -> int:
    parser = argparse.ArgumentParser(description="信義鄉誌論文分類：PDF → 段落標註 → 類別 CSV")
    parser.add_argument("--paper-dir", type=Path, default=config.PAPER_DIR, help="論文 PDF 目錄")
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR, help="CSV 輸出目錄")
    parser.add_argument("--max-pdfs", type=int, default=None, help="最多處理幾本 PDF（預設全部）")
    parser.add_argument("--single", type=Path, default=None, help="僅處理單一 PDF 路徑")
    args = parser.parse_args()

    if args.single is not None:
        if not args.single.is_file():
            print(f"檔案不存在: {args.single}", file=sys.stderr)
            return 1
        rows = run_on_pdf(args.single)
    else:
        if not args.paper_dir.is_dir():
            print(f"論文目錄不存在: {args.paper_dir}", file=sys.stderr)
            return 1
        pdfs = list_papers(args.paper_dir)
        if not pdfs:
            print(f"未找到 PDF: {args.paper_dir}", file=sys.stderr)
            return 1
        rows = run_on_paper_dir(paper_dir=args.paper_dir, max_pdfs=args.max_pdfs)

    if not rows:
        print("未產生任何段落", file=sys.stderr)
        return 1

    all_path, paths = run_export(rows, output_dir=args.output_dir)
    print(f"總類別: {all_path} ({len(rows)} 段)")
    for p in paths[1:]:
        print(f"  {p.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
