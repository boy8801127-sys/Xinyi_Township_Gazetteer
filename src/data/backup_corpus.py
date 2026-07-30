# -*- coding: utf-8 -*-
"""
通用語料庫備份工具：把 labeled_corpus.jsonl、results/*.json、
output/paragraphs_all_merged.csv、images/books/（含 deploy 副本）、
vectorstore/chroma/（含 deploy 副本）備份到帶時間戳記（精確到秒，避免同一天內
重複執行互相覆蓋）的 backup/ 資料夾。

跟 backup_before_id_migration.py（那次 id 格式遷移專用、一次性、同一天內只能跑
一次）不同，這支是給 `.claude/hooks/corpus_auto_backup.py` 每次要覆寫語料庫／
向量庫前自動呼叫用的，因此沿用同一份 TARGETS 清單但改成可重複執行、並附上
「只保留最近 N 份」的清理邏輯，避免每次觸發都留下上百 MB 到 GB 等級的備份、
長期把硬碟塞滿。

使用方式：
    python -m src.data.backup_corpus
    python -m src.data.backup_corpus --keep 10   # 保留份數上限（預設 5）
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from .backup_before_id_migration import ROOT, TARGETS

BACKUP_DIR = ROOT / "backup"
DEFAULT_KEEP = 5


def backup() -> Path:
    dest_root = BACKUP_DIR / f"corpus_{datetime.now():%Y%m%d_%H%M%S}"
    dest_root.mkdir(parents=True)
    print(f"備份目的地：{dest_root}\n")

    for name, src in TARGETS:
        dest = dest_root / name
        if not src.exists():
            print(f"跳過（來源不存在）：{src}")
            continue
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        print(f"已備份：{src}")

    print(f"\n備份完成：{dest_root}")
    return dest_root


def prune(keep: int) -> None:
    """只保留最近 keep 份 corpus_* 備份（不動 pre_id_migration_* 這類一次性備份）。"""
    if not BACKUP_DIR.exists():
        return
    snapshots = sorted(BACKUP_DIR.glob("corpus_*"), key=lambda p: p.name, reverse=True)
    for old in snapshots[keep:]:
        shutil.rmtree(old)
        print(f"清理舊備份：{old}")


def main() -> None:
    parser = argparse.ArgumentParser(description="語料庫／向量庫通用備份工具")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help=f"保留最近幾份備份（預設 {DEFAULT_KEEP}）")
    args = parser.parse_args()

    backup()
    prune(args.keep)


if __name__ == "__main__":
    main()
