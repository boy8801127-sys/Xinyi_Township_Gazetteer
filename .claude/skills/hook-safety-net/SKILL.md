---
name: hook-safety-net
description: 說明這個 repo 的 5 支 PreToolUse hook（cost_warning.py／destructive_confirm.py／corpus_auto_backup.py／deploy_checklist.py／deploy_review_reminder.py）各自攔截什麼、怎麼加新分支。新增會呼叫付費 API、刪除或寫回共用資料、覆寫語料庫的腳本或指令模式時，都應該先看這份確認要不要同步加 hook 分支。
---

# `.claude/hooks/`：PreToolUse 安全網

都攔截 Bash/PowerShell，不符合已知模式一律靜默放行。五支 hook 都在 `.claude/settings.json` 註冊在同一個 `Bash|PowerShell` matcher 下，依序執行：

| Hook | 攔截什麼 | 動作 |
|------|----------|------|
| `cost_warning.py` | 已知的付費 API 呼叫模式（`classify_chain`／`classify_agent`／`generate_qa`／`notion_classify.py`／`classify_journal_with_gemini --run`／`build_index`／`query_engine` 等） | 轉成需要確認的權限提示，附上**基於真實 token 用量換算**的花費估計（每個估計背後都有一次真實呼叫的來源記錄在檔案開頭 docstring） |
| `destructive_confirm.py` | 刪除核心語料／向量庫（`vectorstore/chroma`、`labeled_corpus.jsonl`、`results/`、`images/books/`、`backup/`）、`git push` 到 master/main 或帶 `--force`、會真的寫回 Notion 的指令（`notion_classify.py` 非 `--dry-run`、`migrate_notion_ids.py`、`classify_journal_with_gemini --run` 非 `--dry-run`） | 轉成需要確認的權限提示 |
| `corpus_auto_backup.py` | 會覆寫 `labeled_corpus.jsonl` 或 Chroma 向量庫的腳本（`build_labeled_corpus`／`extract_books`／`build_index`／`add_to_index`／`patch_metadata`／`migrate_ids`／`migrate_vectorstore_ids`／`rename_migrated_images`／`promote_reviewed_images`） | 先自動跑 `python -m src.data.backup_corpus`（成功就靜默放行，失敗才轉成確認提示）；另外只動到 `vectorstore/chroma`／`deploy/rag_space/vectorstore/chroma` 其中一份時會提醒兩份是手動同步、記得同步過去 |
| `deploy_checklist.py` | `gcloud run deploy`／`gcloud builds submit` | 提醒確認「語意空間視覺化、語料庫分析、資料來源、技術說明、更新日誌」5 個分頁／artifact 內容是否要同步更新；`gcloud run deploy` 沒帶 `--memory=` 會額外提醒（見 `deploy/rag_space/KNOWN_ISSUES.md` 的 1Gi 記憶體不足教訓） |
| `deploy_review_reminder.py` | `gcloud run deploy`／`gcloud builds submit`（跟 `deploy_checklist.py` 抓同一組指令，但職責分開、各自獨立成一支 hook） | 提醒部署前要不要先跑 `/code-review`（審查這次要上線的變更）跟 `/doctor`（Claude Code 環境健檢） |

新增會呼叫付費 API／刪除或寫回共用資料／覆寫語料庫的腳本或指令模式時，記得同步在對應的 hook 加分支。`src/data/backup_corpus.py` 是 `corpus_auto_backup.py` 呼叫的通用備份工具（帶時間戳記、預設只保留最近 5 份，避免每次觸發都佔用大量硬碟空間），也可以手動執行：`python -m src.data.backup_corpus`。
