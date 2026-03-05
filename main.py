# -*- coding: utf-8 -*-
"""信義鄉誌論文分類流程 — 終端機互動入口。執行：python main.py"""
from __future__ import annotations

import sys
from pathlib import Path

# 專案根目錄加入 path，以便匯入 src
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_pipeline(paper_dir: Path, output_dir: Path, max_pdfs: int | None = None, single: Path | None = None) -> bool:
    """執行擷取 → 切分標註 → 分類匯出，回傳是否成功。"""
    from src import config
    from src.segment_and_annotate import run_on_paper_dir, run_on_pdf
    from src.extract_pdf import list_papers
    from src.classify_and_export import run_export

    if single is not None:
        if not single.is_file():
            print(f"檔案不存在: {single}")
            return False
        rows = run_on_pdf(single)
    else:
        if not paper_dir.is_dir():
            print(f"論文目錄不存在: {paper_dir}")
            return False
        pdfs = list_papers(paper_dir)
        if not pdfs:
            print(f"未找到 PDF: {paper_dir}")
            return False
        rows = run_on_paper_dir(paper_dir=paper_dir, max_pdfs=max_pdfs)

    if not rows:
        print("未產生任何段落。")
        return False

    all_path, paths = run_export(rows, output_dir=output_dir)
    print(f"\n已匯出 總類別: {all_path}（共 {len(rows)} 段）")
    for p in paths[1:]:
        print(f"  - {p.name}")
    return True


def main() -> None:
    from src import config

    paper_dir = config.PAPER_DIR
    output_dir = config.OUTPUT_DIR

    print("=" * 50)
    print("  信義鄉誌論文分類流程")
    print("=" * 50)
    print(f"  論文目錄: {paper_dir}")
    print(f"  輸出目錄: {output_dir}")
    print()

    while True:
        print("\n請選擇操作：")
        print("  【分類流程】")
        print("    1) 執行完整分類流程（處理 paper 目錄內全部 PDF）")
        print("    2) 執行分類流程（僅處理前 N 本 PDF）")
        print("    3) 處理單一 PDF 檔案（分類流程）")
        print("  【LLM 段落匯出】")
        print("    4) 全部 PDF → paragraphs_all.csv + paragraphs_by_paper/")
        print("    5) 僅處理前 N 本 PDF")
        print("  【手動編輯後處理】")
        print("    6) 合併手動編輯後的段落（ID 為空者與上一列合併）")
        print("  7) 結束")
        try:
            choice = input("\n輸入選項 (1~7): ").strip() or "7"
        except (EOFError, KeyboardInterrupt):
            print("\n再見。")
            break

        if choice == "7":
            print("再見。")
            break

        if choice == "1":
            print("\n開始處理全部 PDF…")
            ok = run_pipeline(paper_dir, output_dir, max_pdfs=None, single=None)
            if not ok:
                print("執行失敗，請檢查目錄與檔案。")

        elif choice == "2":
            try:
                n_str = input("請輸入要處理的 PDF 數量（正整數）: ").strip()
                n = int(n_str)
                if n < 1:
                    print("請輸入至少 1。")
                    continue
            except ValueError:
                print("請輸入有效數字。")
                continue
            print(f"\n開始處理前 {n} 本 PDF…")
            ok = run_pipeline(paper_dir, output_dir, max_pdfs=n, single=None)
            if not ok:
                print("執行失敗，請檢查目錄與檔案。")

        elif choice == "3":
            path_str = input("請輸入 PDF 完整路徑（或相對 paper 的檔名）: ").strip()
            if not path_str:
                print("未輸入路徑。")
                continue
            p = Path(path_str)
            if not p.is_absolute():
                p = paper_dir / p.name
            if not p.is_file():
                print(f"找不到檔案: {p}")
                continue
            print(f"\n開始處理: {p.name}")
            ok = run_pipeline(paper_dir, output_dir, max_pdfs=None, single=p)
            if not ok:
                print("執行失敗。")

        elif choice in ("4", "5"):
            from src.export_paragraphs import (
                run_on_paper_dir_for_paragraphs,
                export_paragraphs_all,
                export_paragraphs_by_paper,
            )

            max_n = None
            if choice == "5":
                try:
                    n_str = input("請輸入要處理的 PDF 數量（正整數）: ").strip()
                    max_n = int(n_str)
                    if max_n < 1:
                        print("請輸入至少 1。")
                        continue
                except ValueError:
                    print("請輸入有效數字。")
                    continue

            label = "全部" if max_n is None else f"前 {max_n} 本"
            print(f"\n開始 LLM 段落匯出（{label} PDF）…")
            rows = run_on_paper_dir_for_paragraphs(paper_dir=paper_dir, max_pdfs=max_n)
            if not rows:
                print("未產生任何段落。")
                continue
            all_path = export_paragraphs_all(rows, output_dir)
            by_paths = export_paragraphs_by_paper(rows, output_dir)
            print(f"\n已匯出全部段落：{all_path}（共 {len(rows)} 段）")
            for bp in by_paths:
                print(f"  - {bp.name}")

        elif choice == "6":
            from src.merge_paragraph_rows import merge_paragraph_rows

            default_input = output_dir / "paragraphs_all_first_arrange.csv"
            if not default_input.exists():
                default_input = output_dir / "paragraphs_all.csv"
            if not default_input.exists():
                print(f"找不到輸入檔，請先執行選項 4 或 5 產生段落 CSV。")
                print(f"  或將手動編輯的 CSV 命名為 paragraphs_all_first_arrange.csv 置於 {output_dir}")
                continue
            try:
                out = merge_paragraph_rows(default_input)
                print(f"\n已合併並輸出：{out}")
            except Exception as e:
                print(f"執行失敗：{e}")

        else:
            print("請輸入 1~7。")


if __name__ == "__main__":
    main()
