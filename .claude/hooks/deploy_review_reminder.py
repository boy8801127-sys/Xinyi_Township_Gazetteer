#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PreToolUse hook（Bash / PowerShell）。

部署到 Cloud Run 前（`gcloud run deploy`／`gcloud builds submit`）強制轉為
「ask」，先問要不要跑 /code-review（審查這次要上線的變更）跟 /doctor
（Claude Code 環境健檢）再繼續部署。跟 deploy_checklist.py 抓同一組部署指令
pattern，但職責分開各自獨立成一支 hook（同一個 matcher 下可以掛多支，各自
互不影響）——這支只管「部署前要不要先做品質檢查」，不管分頁／artifact 同步或
--memory 旗標那些既有檢查。

不符合已知部署指令模式的指令一律放行，不列印任何內容。
"""
import json
import re
import sys

if sys.stdin.encoding and sys.stdin.encoding.lower() != "utf-8":
    sys.stdin.reconfigure(encoding="utf-8")

_DEPLOY_RE = re.compile(r"\bgcloud\s+run\s+deploy\b|\bgcloud\s+builds\s+submit\b")


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    if not cmd or not _DEPLOY_RE.search(cmd):
        return

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": (
                "🔍 部署前提醒：要不要先跑 /code-review（審查這次要上線的變更）"
                "跟 /doctor（Claude Code 環境健檢），確認沒問題再繼續部署？"
            ),
        }
    }
    print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()
