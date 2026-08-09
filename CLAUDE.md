# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

「鄉志慧編（XinyiRAG）」：從碩博士論文 PDF 擷取、分類、標註《南投縣信義鄉志》編纂用的段落，並在這份已分類語料之上疊了一系列 AI 工程技術展示模組（RAG、LangChain chain/agent、Agentic RAG 問答、本地 fine-tuning），另外部署了一個公開的 Gradio + Cloud Run 展示網站。README.md 對每個模組都有完整說明（動機、架構圖、實測數據、CLI 用法），這份文件著重在「跨模組才看得出來」的整體架構與慣例。

輸入：`paper/碩博士論文/` 底下的學位論文 PDF（檔名前綴數字即為論文 ID，如 `01-xxx.pdf`，對應來源代碼 `98`）；`paper/期刊論文/` 底下是另一批期刊論文 PDF（檔名無數字前綴，對應來源代碼 `97`／華藝，走獨立的 `src/export_paragraphs_journal.py` 擷取分段流程，已完成「擷取＋分段→人工複核→Gemini 分類→匯入 Notion→併入 labeled_corpus.jsonl／向量庫」全流程，見下方「id／source 欄位格式」段落）

## 執行方式

```bash
# 虛擬環境（Windows）
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt              # 主要依賴（分類/Notion/RAG/LangChain）
pip install -r requirements-finetune.txt      # 另外裝：本地 fine-tuning 專用（torch/unsloth/trl，需要 GPU）

# 互動式選單入口（僅涵蓋 PDF 分類流程，見下）
python main.py

# CLI 直接執行分類流程（非互動）
python -m src.run_pipeline
python -m src.run_pipeline --max-pdfs 3
python -m src.run_pipeline --single paper/碩博士論文/01-xxx.pdf

# Notion 自動分類（產生 results/*.json，是後續所有 AI 模組的語料來源）
python notion_classify.py --first-only --dry-run
python notion_classify.py --all --batch        # Batch API，費用省 50%

# 後續 AI 模組（各自獨立的平行模組，見下方「架構說明」）
python -m src.data.build_labeled_corpus         # 合併 results/*.json → labeled_corpus.jsonl
python -m src.rag.build_index                   # 建 Chroma 向量索引
python -m src.rag.query_engine --ask "問題"
python -m src.langchain_pipeline.classify_chain --compare --sample 10
python -m src.langchain_pipeline.classify_agent --compare --sample 10
python -m src.langchain_pipeline.answer_agent --ask "問題"
python -m src.finetune.generate_qa --sample 20   # 會呼叫付費 API，執行前看 cost_warning.py 的花費估算
python -m src.finetune.prepare_dataset
python -m src.finetune.evaluate
```

Windows 若 `pip install` 出現 `UnicodeDecodeError: 'cp950' codec can't decode ...`，改用 `PYTHONUTF8=1 pip install -r requirements.txt`。

沒有測試套件（`pytest`/`unittest` 等），各模組靠 CLI 手動跑（`--text`／`--paper-id`／`--compare` 這類旗標）驗證。

## 架構說明

### 資料主幹：一份語料，多個模組共用

```
paper/碩博士論文/*.pdf
   │
   ├─（main.py 選項 1~6）→ extract_pdf → segment_and_annotate → classify_and_export → output/*.csv
   │                                                                                  （關鍵字比對分類，獨立產出，不餵給下游 AI 模組）
   │
   └─（main.py 選項 4~6）→ export_paragraphs → output/paragraphs_all_merged.csv
                                                        │
                                              匯入 Notion，人工/半自動整理
                                                        │
                                          notion_classify.py（Claude API 分類）
                                                        │
                                              results/*.json（斷點續傳快取）
                                                        │
                                    src/data/build_labeled_corpus.py
                                                        │
                                          src/data/labeled_corpus.jsonl
                                    （13,335 筆已分類段落，這是 RAG／LangChain／
                                     fine-tuning 全部模組共用的唯一語料來源）
                                                        │
                    ┌───────────────┬───────────────┬───────────────┬───────────────┐
                    ▼               ▼               ▼               ▼               ▼
              src/rag/      classify_chain.py  classify_agent.py  answer_agent.py  src/finetune/
           （向量索引/問答）  （動態 few-shot）   （agent 分類）   （agentic 問答）  （QLoRA 微調）
```

**兩條分類流程互不相通**：`main.py` 的「分類流程」（選項 1~3，依 `This_plan/類別關鍵字.json` 關鍵字比對）跟 `notion_classify.py`（Claude API 語意分類）是兩套獨立系統，各自輸出到 `output/*.csv` 和 `results/*.json`，沒有互相依賴。**所有後續的 AI 展示模組（RAG 起）都只吃 `notion_classify.py` 這條線的產出**，跟關鍵字分類流程無關。

### 平行實驗模組慣例（貫穿全專案的核心規範）

`labeled_corpus.jsonl` 之上疊的每一個模組（RAG → LangChain chain → LangChain agent → Agentic RAG 問答 → fine-tuning）都嚴格遵守：**新增檔案，絕不修改前一層的程式碼，只讀取前一層產出的共用資料／函式**。例如 `classify_agent.py` 會直接 import `classify_chain.py` 裡的 `CATEGORIES`／`ClassificationResult`／`_load_corpus` 等共用物件，但不會改動 `classify_chain.py` 本身；這幾個下游 AI 展示模組沒有任何一個會寫回 Notion 或修改 `results/`、`labeled_corpus.jsonl`。改動某個模組前，先確認同樣的邏輯有沒有已經在更上游的模組定義過，直接 import 沿用。

（例外：`src/data/` 底下屬於「產生語料」這一層本身的一次性遷移／整併腳本——如 `migrate_ids.py`、`migrate_notion_ids.py`、`build_labeled_corpus.py`——本來就是負責寫 `results/*.json`／`labeled_corpus.jsonl`／同步 Notion 的地方，不算違反這條規範；這條規範限制的是「語料之上」的下游展示模組，不是語料產生本身。）

### 多供應商 LLM 選型不是隨意的

不同模組刻意用不同 LLM 供應商，都是**實測比較後**的決定，不要不查證就假設全部統一：
- `notion_classify.py`／`classify_chain.py`／`classify_agent.py`：Claude（`claude-haiku-4-5`）
- `src/rag/query_engine.py` 的 `answer_question()`／`answer_agent.py`：改用 Gemini flash-lite 級距（`DEFAULT_LLM_MODEL = "gemini-flash-lite-latest"`，Google 官方別名，自動跟隨最新一代 flash-lite 模型，不寫死版本號），成本考量，公開展示網站也用這個模型控管費用。2026-07 實測比較過 `gemini-3.1-flash-lite`／`gemini-3.5-flash-lite`／`gemini-3.5-flash`，3.5-flash-lite 回答品質明顯較好、定價只小漲，3.5-flash（非 lite）貴 6 倍且容易撞 `MAX_TOKENS` 上限，不採用（細節見 `src/rag/query_engine.py` 裡 `DEFAULT_LLM_MODEL` 上方註解）
- `src/finetune/generate_qa.py`：Gemini（實測比較過 Claude／Gemini／Groq，Gemini 品質相當且成本約 1/8，Groq 有觀察到編造事實的幻覺問題）
- fine-tuning 基底模型只用 `twinkle-ai/gemma-3-4B-T1-it`（原本也測過 Llama 版本，但 chat template 格式風險較高而放棄，見 README「本地 Fine-tuning」章節）

### `.claude/hooks/`：PreToolUse 安全網（都攔截 Bash/PowerShell，不符合已知模式一律靜默放行）

五支 hook 都在 `.claude/settings.json` 註冊在同一個 `Bash|PowerShell` matcher 下，依序執行：

| Hook | 攔截什麼 | 動作 |
|------|----------|------|
| `cost_warning.py` | 已知的付費 API 呼叫模式（`classify_chain`／`classify_agent`／`generate_qa`／`notion_classify.py`／`classify_journal_with_gemini --run`／`build_index`／`query_engine` 等） | 轉成需要確認的權限提示，附上**基於真實 token 用量換算**的花費估計（每個估計背後都有一次真實呼叫的來源記錄在檔案開頭 docstring） |
| `destructive_confirm.py` | 刪除核心語料／向量庫（`vectorstore/chroma`、`labeled_corpus.jsonl`、`results/`、`images/books/`、`backup/`）、`git push` 到 master/main 或帶 `--force`、會真的寫回 Notion 的指令（`notion_classify.py` 非 `--dry-run`、`migrate_notion_ids.py`、`classify_journal_with_gemini --run` 非 `--dry-run`） | 轉成需要確認的權限提示 |
| `corpus_auto_backup.py` | 會覆寫 `labeled_corpus.jsonl` 或 Chroma 向量庫的腳本（`build_labeled_corpus`／`extract_books`／`build_index`／`add_to_index`／`patch_metadata`／`migrate_ids`／`migrate_vectorstore_ids`／`rename_migrated_images`／`promote_reviewed_images`） | 先自動跑 `python -m src.data.backup_corpus`（成功就靜默放行，失敗才轉成確認提示）；另外只動到 `vectorstore/chroma`／`deploy/rag_space/vectorstore/chroma` 其中一份時會提醒兩份是手動同步、記得同步過去 |
| `deploy_checklist.py` | `gcloud run deploy`／`gcloud builds submit` | 提醒確認「語意空間視覺化、語料庫分析、資料來源、技術說明、更新日誌」5 個分頁／artifact 內容是否要同步更新；`gcloud run deploy` 沒帶 `--memory=` 會額外提醒（見 `deploy/rag_space/KNOWN_ISSUES.md` 的 1Gi 記憶體不足教訓） |
| `deploy_review_reminder.py` | `gcloud run deploy`／`gcloud builds submit`（跟 `deploy_checklist.py` 抓同一組指令，但職責分開、各自獨立成一支 hook） | 提醒部署前要不要先跑 `/code-review`（審查這次要上線的變更）跟 `/doctor`（Claude Code 環境健檢） |

新增會呼叫付費 API／刪除或寫回共用資料／覆寫語料庫的腳本或指令模式時，記得同步在對應的 hook 加分支。`src/data/backup_corpus.py` 是 `corpus_auto_backup.py` 呼叫的通用備份工具（帶時間戳記、預設只保留最近 5 份，避免每次觸發都佔用大量硬碟空間），也可以手動執行：`python -m src.data.backup_corpus`。

### `src/config.py`：分類流程集中設定

`export_paragraphs.py`（v2）的 `run_on_paper_dir_for_paragraphs` 實際上內部呼叫的是 `export_paragraphs_v1.py` 的狀態機實作，v2 自己的 `extract_paragraphs_from_pdf` 目前只是備用、未串進主流程——改這塊之前先確認實際呼叫路徑。

### id／source 欄位格式（2026-07 標準化，見 `src/data/source_codes.py`）

`labeled_corpus.jsonl` 每筆的 `id` 格式是 `{來源代碼}-{原序號}-{段落序號}`，來源代碼是 14 種資料來源（論文、縣志、公文檔案等）各自固定的兩到三碼數字，定義在 `src/data/source_codes.py` 的 `SOURCE_CODES`，供之後新增其他來源類型時直接查表擴充，不要另外發明新的前綴規則：

- 論文（代碼 `98`，信義鄉布農族博碩士論文）：PDF 檔名以數字開頭（`01-`、`02-`…）對應論文序號，id 如 `98-11-200`。序號有缺號（03、04…）代表該論文尚未收入。`source` 欄位是腳註引用格式（`作者，〈篇名〉（學校地：系所，畢業年），頁X。`），書目資料存在 `src/data/paper_bibliography.json`（由 `src/data/build_paper_bibliography.py` 一次性從 `paper/信義鄉布農族博碩士論文.docx`＋`paper/台灣大專院校地址名冊.xls` 解析產生，之後新增的論文直接手動補一筆進 json，不用重跑該腳本），組裝邏輯在 `src/data/paper_bibliography.py::format_paper_citation()`。
- 縣志（代碼 `92`，南投縣志稿＆南投縣志＆續修南投縣志）：id 如 `92-01-079`，`source` 欄位維持 `南投縣志｜卷別 篇名｜條目名` 格式，不套用腳註格式。
- 期刊論文（代碼 `97`，華藝）：PDF 放在 `paper/期刊論文/`（檔名無數字前綴，序號依檔名排序 1~13，見 `paper/期刊論文/書目資料清單.csv`，已填妥），走獨立的 `src/export_paragraphs_journal.py`（呼叫 `export_paragraphs_v1.py::extract_paragraphs_from_pdf()` 新增的選用參數，傳入期刊專用的 `config.JOURNAL_BODY_START_KEYWORDS`／`JOURNAL_SECTION_HEADING_RE` 等設定，不影響學位論文既有呼叫路徑）擷取分段→人工複核（`split_and_merge_paragraphs_xlsx.py`／`merge_paragraph_rows.py`，比照學位論文的 Excel 合併儲存格慣例）→`src/data/classify_journal_with_gemini.py`（Gemini 分類、寫回 Notion）→`src/data/build_labeled_corpus.py` 的 `code_of(id) == "97"` 分支併入 `labeled_corpus.jsonl`。`source` 欄位引用格式由 `src/data/journal_bibliography.py::format_journal_citation()` 讀 `書目資料清單.csv` 組裝，格式跟論文一樣內含頁碼。全流程（含向量庫）已完成，目前 454 筆（13 篇）已在服役中的語料庫裡。
- `build_index.py` 的 `source_type`（UI／CLI 篩選用的「論文」／「書籍」粗分類）改用 `source_codes.py::source_type_for_id()` 查表，不要再用 id 前綴字母判斷。

### 部署（`deploy/rag_space/`）

Cloud Run 上線的 Gradio 展示網站，是 `query_engine.py`／`answer_agent.py` 的**獨立部署副本**，有自己的 git remote，整個 `deploy/` 在 `.gitignore` 裡被排除、不進這個主 repo 的版控——修改 RAG／agent 邏輯後若要同步更新展示網站，要記得手動同步過去，不會自動連動。詳見 `deploy/rag_space/README.md` 與 `KNOWN_ISSUES.md`。

### 其他

- `.cursor/skills/gazetteer-format-check`：依 `This_plan/信義鄉志服務建議書.pdf` 的編纂凡例／撰寫格式（紀年、標點、註腳格式等）檢核文稿的技能，處理跟鄉志正式出版格式相關的任務時用得上。
