# -*- coding: utf-8 -*-
"""
一次性腳本：把 output/paragraphs_all_merged.csv 的 ID 欄與 results/*.json 各筆記錄的
notion_id 欄，從舊格式 `P{論文序號}-{段落序號}`／`B{書籍序號}-{段落序號}` 改成新格式
`98-{論文序號}-{段落序號}`／`92-{書籍序號}-{段落序號}`（見 src/data/source_codes.py）。

縣志（B 開頭）記錄額外把 images 欄位裡的舊圖片檔名同步換成新檔名（實體檔案改名
由 rename_migrated_images.py 另外處理，這裡只改 JSON 裡記錄的檔名字串）。

執行前必須已經跑過 backup_before_id_migration.py，否則直接中止。
可重複執行：若掃到的 id 已經是新格式（不符合舊格式 pattern），視為已遷移，略過不報錯。

使用方式：
    python -m src.data.migrate_ids
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = ROOT / "results"
CSV_PATH = ROOT / "output" / "paragraphs_all_merged.csv"
BACKUP_DIR_GLOB = "pre_id_migration_*"
MAP_OUTPUT_PATH = ROOT / "output" / "id_migration_map.csv"

_OLD_ID_RE = re.compile(r"^([PB])(\d+)-(.+)$")
_CODE_FOR_LETTER = {"P": "98", "B": "92"}


def _old_to_new(old_id: str) -> str | None:
    m = _OLD_ID_RE.match(old_id)
    if not m:
        return None
    letter, num, rest = m.groups()
    return f"{_CODE_FOR_LETTER[letter]}-{num}-{rest}"


def _require_backup() -> None:
    backups = list((ROOT / "backup").glob(BACKUP_DIR_GLOB)) if (ROOT / "backup").exists() else []
    if not backups:
        raise RuntimeError(
            "找不到任何 backup/pre_id_migration_* 備份資料夾，請先執行："
            "python -m src.data.backup_before_id_migration"
        )
    print(f"已確認備份存在：{[p.name for p in backups]}")


def _collect_all_ids() -> set[str]:
    ids: set[str] = set()
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            i = row.get("ID")
            if i:
                ids.add(i)
    for fp in RESULTS_DIR.glob("*.json"):
        data = json.loads(fp.read_text(encoding="utf-8"))
        for rec in data.get("records", []):
            nid = rec.get("notion_id")
            if nid:
                ids.add(nid)
    return ids


def _build_mapping() -> dict[str, str]:
    all_ids = _collect_all_ids()
    mapping = {}
    unmatched = []
    for old_id in all_ids:
        new_id = _old_to_new(old_id)
        if new_id is None:
            unmatched.append(old_id)
        else:
            mapping[old_id] = new_id
    if unmatched:
        print(f"以下 {len(unmatched)} 個 id 已是新格式（或不符合舊格式），略過：{unmatched[:10]}")
    print(f"建立 id 對照表：{len(mapping)} 筆")
    return mapping


def _migrate_csv(mapping: dict[str, str]) -> None:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    changed = 0
    for row in rows:
        old_id = row.get("ID")
        if old_id in mapping:
            row["ID"] = mapping[old_id]
            changed += 1

    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CSV 已更新：{changed}/{len(rows)} 列")


def _migrate_results(mapping: dict[str, str]) -> list[dict]:
    """回傳給 output CSV 用的列：{old_id, new_id, page_id, is_notion_uuid}"""
    map_rows: list[dict] = []
    total_changed = 0

    for fp in sorted(RESULTS_DIR.glob("*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        file_changed = 0
        for rec in data.get("records", []):
            old_id = rec.get("notion_id")
            if old_id not in mapping:
                continue
            new_id = mapping[old_id]
            old_page_id = rec.get("page_id", "")
            is_placeholder_page_id = old_page_id == old_id
            rec["notion_id"] = new_id
            if is_placeholder_page_id:
                rec["page_id"] = new_id

            images = rec.get("images")
            if images:
                new_images = []
                for fname in images:
                    stem, ext = fname.rsplit(".", 1) if "." in fname else (fname, "")
                    new_stem = mapping.get(stem, stem)
                    new_images.append(f"{new_stem}.{ext}" if ext else new_stem)
                rec["images"] = new_images

            map_rows.append({
                "old_id": old_id,
                "new_id": new_id,
                "page_id": rec.get("page_id", ""),
                "is_notion_uuid": (not is_placeholder_page_id) and bool(rec.get("written_to_notion")),
            })
            file_changed += 1

        if file_changed:
            fp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        total_changed += file_changed

    print(f"results/*.json 已更新：{total_changed} 筆記錄")
    return map_rows


def _write_map_csv(map_rows: list[dict]) -> None:
    MAP_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MAP_OUTPUT_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["old_id", "new_id", "page_id", "is_notion_uuid"])
        writer.writeheader()
        writer.writerows(map_rows)
    print(f"對照表輸出：{MAP_OUTPUT_PATH}（{len(map_rows)} 筆）")


def migrate() -> None:
    _require_backup()
    mapping = _build_mapping()
    if not mapping:
        print("沒有需要遷移的 id，結束。")
        return
    _migrate_csv(mapping)
    map_rows = _migrate_results(mapping)
    _write_map_csv(map_rows)


if __name__ == "__main__":
    migrate()
