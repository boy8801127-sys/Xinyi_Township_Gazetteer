#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PreToolUse hook（Bash / PowerShell）。

攔截三類不可逆／影響共用狀態的操作，強制轉為「ask」並附上具體原因，
不符合已知模式的指令一律放行、不列印任何內容：

1. 刪除核心語料／向量庫資料（vectorstore/chroma、labeled_corpus.jsonl、
   results/、images/books/、backup/）——這些要嘛是重新產生要花時間／付費
   API 額度（見 cost_warning.py），要嘛是遷移前的安全網（backup/），刪掉
   容易後悔。
2. git push 到 master/main，或帶 --force／-f 的 push——會影響遠端共用分支，
   force push 還可能覆蓋別人（或自己之後）的提交。
3. 會真的寫回 Notion 資料庫的指令（notion_classify.py 非 --dry-run、
   migrate_notion_ids.py、classify_journal_with_gemini.py --run 非 --dry-run）
   ——Notion 資料庫是共用、線上的，寫錯沒有簡單的復原機制（不像本機檔案可以
   從 backup/ 還原）。

新增會刪除／寫回共用資料的腳本或指令模式時，記得同步在這支 hook 加對應分支
（比照 CLAUDE.md 對 cost_warning.py 的要求）。
"""
import json
import re
import subprocess
import sys

if sys.stdin.encoding and sys.stdin.encoding.lower() != "utf-8":
    sys.stdin.reconfigure(encoding="utf-8")

# 核心語料／向量庫路徑（不分正反斜線）：具體檔名／子路徑用子字串比對即可；
# 目錄名稱（results、backup）容易是其他字串的一部分，用 \b 界定完整字詞邊界。
_PROTECTED_SUBSTRINGS = [
    "vectorstore/chroma", "vectorstore\\chroma",
    "labeled_corpus.jsonl",
    "images/books", "images\\books",
]
_PROTECTED_WORD_RE = re.compile(r"\b(results|backup)\b", re.IGNORECASE)

_DELETE_VERB_RE = re.compile(
    r"\brm\s+-\w*[rf]\w*[rf]?\w*\b"      # rm -rf / -fr / -r -f 這類
    r"|\bRemove-Item\b"
    r"|\brd\s+/s\b|\brmdir\s+/s\b"
    r"|shutil\.rmtree\s*\("
    r"|delete_collection\s*\(",
    re.IGNORECASE,
)


def _hits_protected_path(cmd: str) -> str | None:
    for hint in _PROTECTED_SUBSTRINGS:
        if hint.lower() in cmd.lower():
            return hint
    m = _PROTECTED_WORD_RE.search(cmd)
    return m.group(0) if m else None


def _current_branch() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _check_delete(cmd: str) -> str | None:
    if not _DELETE_VERB_RE.search(cmd):
        return None
    hint = _hits_protected_path(cmd)
    if not hint:
        return None
    return (
        f"⚠️ 這個指令看起來會刪除核心語料／向量庫資料（命中「{hint}」），"
        f"而且不一定能簡單復原（除非 backup/ 底下有對應的備份）。"
        f"確定要刪除嗎？建議先確認 backup/ 有沒有夠新的備份。"
    )


def _check_git_push(cmd: str) -> str | None:
    if not re.search(r"\bgit\s+push\b", cmd):
        return None
    is_force = bool(re.search(r"--force\b|(?<!\w)-f\b", cmd))
    m = re.search(r"\bgit\s+push\b[^\n|;&]*?\b(master|main)\b", cmd)
    is_to_main = bool(m)
    if not is_to_main:
        # 沒有明講分支名稱時（例如單純 `git push` 或 `git push origin`），
        # 用目前所在分支判斷是不是直接推到 master/main。
        branch = _current_branch()
        if branch in ("master", "main") and not re.search(r"\bgit\s+push\b\s+\S+\s+\S+", cmd):
            is_to_main = True
    if not is_force and not is_to_main:
        return None
    reasons = []
    if is_force:
        reasons.append("帶了 --force／-f，可能覆蓋遠端已存在的提交")
    if is_to_main:
        reasons.append("目標是 master／main，會直接影響共用的主分支")
    return f"⚠️ 這個 git push {'且'.join(reasons)}。確定要繼續嗎？"


def _check_notion_write(cmd: str) -> str | None:
    if "migrate_notion_ids.py" in cmd or "migrate_notion_ids" in cmd:
        return "⚠️ 這個指令會批次寫入 Notion 資料庫的 \"ID\" 欄位（線上共用資料，寫錯沒有一鍵復原機制）。確定要繼續嗎？"
    if "notion_classify.py" in cmd and "--dry-run" not in cmd:
        return "⚠️ 這個指令會把分類結果實際寫回 Notion 資料庫（線上共用資料）。確定要繼續嗎？（--dry-run 可以先看結果不寫回）"
    if "classify_journal_with_gemini" in cmd and "--run" in cmd and "--dry-run" not in cmd:
        return "⚠️ 這個指令會把期刊論文分類結果實際寫回 Notion 資料庫（線上共用資料）。確定要繼續嗎？（--dry-run 可以先看結果不寫回）"
    if "classify_paper_with_gemini" in cmd and "--run" in cmd and "--dry-run" not in cmd:
        return "⚠️ 這個指令會把學位論文分類結果實際寫回 Notion 資料庫（線上共用資料）。確定要繼續嗎？（--dry-run 可以先看結果不寫回）"
    if "import_paragraphs_to_notion" in cmd and "--run" in cmd:
        if "--database-id" in cmd:
            return "⚠️ 這個指令會接續寫入既有 Notion database（續傳模式，已匯入的列會自動略過）。確定要繼續嗎？（--dry-run 可以先預覽）"
        return "⚠️ 這個指令會在 Notion 母頁面底下新建一個 database 並寫入整批段落（線上共用資料；若中途失敗要重跑，改用 --database-id 續傳，否則會產生重複的 database）。確定要繼續嗎？（--dry-run 可以先預覽）"
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    if not cmd:
        return

    reason = _check_delete(cmd) or _check_git_push(cmd) or _check_notion_write(cmd)
    if reason is None:
        return

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()
