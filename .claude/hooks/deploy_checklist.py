#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PreToolUse hook（Bash / PowerShell）。

部署到 Cloud Run 前（`gcloud run deploy`／`gcloud builds submit`）強制轉為
「ask」，提醒兩件事：

1. 語料庫或問答邏輯有變動時，「語意空間視覺化」「語料庫分析」「資料來源」
   「技術說明」「更新日誌」這 5 個分頁／artifact 的內容是不是也要同步更新
   （這幾個都是手動維護的快照，不會自動反映最新狀態，見這幾頁自己的
   「資料快照：」標記）。
2. `gcloud run deploy` 有沒有帶 `--memory=`——沒帶會用回 Cloud Run 服務現有設定，
   之前語料庫成長導致啟動記憶體超過預設 1Gi 而部署失敗過一次，見
   `deploy/rag_space/KNOWN_ISSUES.md`「記憶體上限已從 1Gi 調高到 2Gi」。

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

    lines = ["📋 部署前檢查清單："]

    lines.append(
        "1. 語料庫／問答邏輯若有變動，確認以下分頁／artifact 內容還準不準確，"
        "需要的話先更新：語意空間視覺化、語料庫分析、資料來源、技術說明、更新日誌。"
    )

    is_run_deploy = bool(re.search(r"\bgcloud\s+run\s+deploy\b", cmd))
    if is_run_deploy and "--memory" not in cmd:
        lines.append(
            "2. ⚠️ 這個 `gcloud run deploy` 沒有帶 `--memory=`，會沿用服務現有設定——"
            "之前語料庫變大導致啟動記憶體超過 1Gi 預設值、部署失敗過一次，"
            "建議明確帶上 `--memory=2Gi`（或依 KNOWN_ISSUES.md 最新數字），"
            "不要依賴預設值。"
        )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "\n".join(lines),
        }
    }
    print(json.dumps(output, ensure_ascii=True))


if __name__ == "__main__":
    main()
