# -*- coding: utf-8 -*-
"""步驟 3：依類別關鍵字自動標籤並匯出各類別 CSV 與總類別 CSV。"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from . import config


def load_categories(category_file: Path | None = None) -> list[str]:
    """讀取類別.txt，每行一個類別名，略過空行。"""
    p = category_file or config.CATEGORY_FILE
    if not p.is_file():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    return [ln.strip() for ln in lines if ln.strip()]


def load_keywords(keywords_file: Path | None = None) -> dict[str, list[str]]:
    """讀取類別關鍵字.json，{ "歷史篇": ["歷史", ...], ... }。"""
    p = keywords_file or config.KEYWORDS_FILE
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def classify_paragraph(text: str, keywords: dict[str, list[str]]) -> str:
    """
    依關鍵字出現次數為每類計分，回傳得分最高的類別；同分或無匹配則回傳「未分類」。
    """
    return classify_paragraph_with_keywords(text, keywords)[0]


def classify_paragraph_with_keywords(
    text: str, keywords: dict[str, list[str]]
) -> tuple[str, list[str]]:
    """
    依關鍵字為每類計分，回傳 (得分最高類別, 該類命中的關鍵字 list)。
    同分或無匹配則回傳 ("未分類", [])。
    """
    if not keywords:
        return "未分類", []
    scores: dict[str, int] = {cat: 0 for cat in keywords}
    matched_by_cat: dict[str, list[str]] = {cat: [] for cat in keywords}
    for cat, kws in keywords.items():
        for kw in kws:
            if kw in text:
                scores[cat] += 1
                matched_by_cat[cat].append(kw)
    best = max(scores.values())
    if best == 0:
        return "未分類", []
    candidates = [c for c, s in scores.items() if s == best]
    chosen = candidates[0] if len(candidates) == 1 else "未分類"
    return chosen, matched_by_cat.get(chosen, [])


def classify_rows(rows: list[dict[str, Any]], keywords: dict[str, list[str]]) -> list[dict[str, Any]]:
    """為每筆 row 加上「類別」與「關鍵字」欄位。關鍵字以頓號連接。"""
    out = []
    for r in rows:
        row = dict(r)
        cat, kws = classify_paragraph_with_keywords(row.get("段落", ""), keywords)
        row["類別"] = cat
        row["關鍵字"] = "、".join(kws) if kws else ""
        out.append(row)
    return out


def merge_consecutive_same_category(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    將連續且類別相同的 row 合併為一筆。段落以。連接，頁數為起始頁或「起始–結束」，
    註腳取第一筆，關鍵字取聯集去重後以頓號連接。
    """
    if not rows:
        return []
    out: list[dict[str, Any]] = []
    cur = dict(rows[0])
    for r in rows[1:]:
        if r.get("類別") == cur.get("類別") and r.get("來源文章") == cur.get("來源文章"):
            cur["段落"] = (cur.get("段落", "") or "") + "。" + (r.get("段落", "") or "")
            cur_page = cur.get("頁數")
            end_page = r.get("頁數")
            if end_page is not None and cur_page != end_page:
                cur["頁數"] = f"{cur_page}–{end_page}"
            kw_cur = (cur.get("關鍵字") or "").split("、")
            kw_r = (r.get("關鍵字") or "").split("、")
            cur["關鍵字"] = "、".join(dict.fromkeys([k for k in kw_cur + kw_r if k]))
        else:
            out.append(cur)
            cur = dict(r)
    out.append(cur)
    return out


def export_csv(rows: list[dict[str, Any]], out_path: Path, columns: list[str] | None = None) -> None:
    """將 rows 寫入 CSV。預設欄位順序：段落、來源文章、頁數、註腳、類別、關鍵字。"""
    cols = columns or ["段落", "來源文章", "頁數", "註腳", "類別", "關鍵字"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def _sanitize_filename_for_csv(name: str) -> str:
    """將來源文章名稱轉成可當檔名的字串，去掉 \\ / : * ? \" < > |，副檔名 .csv。"""
    for c in '\\/:*?"<>|':
        name = name.replace(c, "_")
    name = name.strip() or "未命名"
    if name.lower().endswith(".pdf"):
        name = name[:-4] + ".csv"
    elif not name.endswith(".csv"):
        name = name + ".csv"
    return name


def run_export(
    rows: list[dict[str, Any]],
    output_dir: Path | None = None,
    category_file: Path | None = None,
    keywords_file: Path | None = None,
) -> tuple[Path, list[Path]]:
    """
    對已標註的 rows 做分類、合併同類相鄰段、並匯出：
    - 總類別.csv：全部段落
    - 歷史篇.csv、地理篇.csv、...：各類別段落
    - 論文/：依來源文章，每篇論文一個 CSV
    回傳 (總類別路徑, [所有寫出的 CSV 路徑])。
    """
    out_dir = output_dir or config.OUTPUT_DIR
    categories = load_categories(category_file)
    keywords = load_keywords(keywords_file)
    classified = classify_rows(rows, keywords)
    classified = merge_consecutive_same_category(classified)
    cols = ["段落", "來源文章", "頁數", "註腳", "類別", "關鍵字"]
    paths: list[Path] = []
    # 總類別
    all_path = out_dir / "總類別.csv"
    export_csv(classified, all_path, cols)
    paths.append(all_path)
    # 各類別
    for cat in categories:
        sub = [r for r in classified if r.get("類別") == cat]
        if sub:
            p = out_dir / f"{cat}.csv"
            export_csv(sub, p, cols)
            paths.append(p)
    # 依論文分別儲存
    papers_dir = out_dir / "論文"
    by_source: dict[str, list[dict[str, Any]]] = {}
    for r in classified:
        src = r.get("來源文章", "") or "未命名"
        by_source.setdefault(src, []).append(r)
    for source_name, sub in by_source.items():
        fname = _sanitize_filename_for_csv(source_name)
        p = papers_dir / fname
        export_csv(sub, p, cols)
        paths.append(p)
    return all_path, paths


if __name__ == "__main__":
    import sys
    from .segment_and_annotate import run_on_paper_dir
    # 僅跑 1 本測試
    rows = run_on_paper_dir(max_pdfs=1)
    if not rows:
        print("無段落可匯出", file=sys.stderr)
        sys.exit(1)
    all_path, paths = run_export(rows)
    print(f"已匯出總類別: {all_path}", file=sys.stderr)
    for p in paths[1:]:
        print(f"   {p.name}", file=sys.stderr)
    print("OK")
