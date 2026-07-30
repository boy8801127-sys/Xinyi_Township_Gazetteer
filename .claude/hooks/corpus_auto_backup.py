#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PreToolUse hook（Bash / PowerShell）。

執行前偵測指令是否會覆寫／變動核心語料（labeled_corpus.jsonl）或 Chroma
向量庫，若是，先自動跑一次 `python -m src.data.backup_corpus`（備份成功就靜默
放行，不打斷使用者），備份失敗才轉成「ask」提醒。另外，如果指令只會動到
`vectorstore/chroma`／`deploy/rag_space/vectorstore/chroma` 其中一份（這兩份
是手動同步的獨立副本，見 CLAUDE.md「部署」一節），會額外提醒記得同步另一份。

新增會覆寫語料庫／向量庫的腳本時，記得同步在 _CORPUS_MUTATING_PATTERNS 加對應
模式（比照 CLAUDE.md 對 cost_warning.py 的要求）。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if sys.stdin.encoding and sys.stdin.encoding.lower() != "utf-8":
    sys.stdin.reconfigure(encoding="utf-8")

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parent.parent.parent)

_VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
_PYTHON = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable

# 會覆寫／變動 labeled_corpus.jsonl 或 Chroma 向量庫的腳本，跑之前先自動備份。
_CORPUS_MUTATING_PATTERNS = [
    "build_labeled_corpus",
    "extract_books",
    "build_index",
    "add_to_index",
    "patch_metadata",
    "migrate_ids",
    "migrate_vectorstore_ids",
    "rename_migrated_images",
    "promote_reviewed_images",
]

# 只會動到 vectorstore/chroma 其中一份、沒有自動同步機制的腳本；命中時額外提醒。
_SINGLE_VECTORSTORE_PATTERNS = ["build_index", "add_to_index", "patch_metadata", "migrate_vectorstore_ids"]


def _run_backup() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [_PYTHON, "-m", "src.data.backup_corpus"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=90,
        )
        if result.returncode == 0:
            return True, result.stdout
        return False, (result.stderr or result.stdout)
    except Exception as e:  # noqa: BLE001 - 備份失敗要能回報原因，不是讓 hook 整個掛掉
        return False, str(e)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    if not cmd:
        return

    if not any(p in cmd for p in _CORPUS_MUTATING_PATTERNS):
        return

    ok, log = _run_backup()

    if not ok:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    f"⚠️ 這個指令會變動語料庫／向量庫，執行前自動備份失敗：\n{log[:500]}\n"
                    f"要不要先手動排除備份問題，還是仍要在沒有新備份的情況下繼續？"
                ),
            }
        }
        print(json.dumps(output, ensure_ascii=True))
        return

    if any(p in cmd for p in _SINGLE_VECTORSTORE_PATTERNS) and "deploy" not in cmd.lower():
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    "✅ 已自動備份。提醒：這個指令只會更新 vectorstore/chroma（本機／CLI 用的那份），"
                    "deploy/rag_space/vectorstore/chroma 是手動同步的獨立副本，不會跟著變動——"
                    "如果部署站也要反映這次變動，記得對 deploy 路徑另外跑一次或手動同步過去。"
                ),
            }
        }
        print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()
