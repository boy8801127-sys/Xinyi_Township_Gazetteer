# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

「鄉志慧編（XinyiRAG）」：從碩博士論文 PDF 擷取、分類、標註《南投縣信義鄉志》編纂用的段落，並在這份已分類語料之上疊了一系列 AI 工程技術展示模組（RAG、LangChain chain/agent、Agentic RAG 問答、本地 fine-tuning），另外部署了一個公開的 Gradio + Cloud Run 展示網站。README.md 對每個模組都有完整說明（動機、架構圖、實測數據、CLI 用法），這份文件著重在「跨模組才看得出來」的整體架構與慣例。

輸入：`paper/` 目錄下的論文 PDF（檔名前綴數字即為論文 ID，如 `01-xxx.pdf`）

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
python -m src.run_pipeline --single paper/01-xxx.pdf

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
paper/*.pdf
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
                                    （10,099 筆已分類段落，這是 RAG／LangChain／
                                     fine-tuning 全部模組共用的唯一語料來源）
                                                        │
                    ┌───────────────┬───────────────┬───────────────┬───────────────┐
                    ▼               ▼               ▼               ▼               ▼
              src/rag/      classify_chain.py  classify_agent.py  answer_agent.py  src/finetune/
           （向量索引/問答）  （動態 few-shot）   （agent 分類）   （agentic 問答）  （QLoRA 微調）
```

**兩條分類流程互不相通**：`main.py` 的「分類流程」（選項 1~3，依 `This_plan/類別關鍵字.json` 關鍵字比對）跟 `notion_classify.py`（Claude API 語意分類）是兩套獨立系統，各自輸出到 `output/*.csv` 和 `results/*.json`，沒有互相依賴。**所有後續的 AI 展示模組（RAG 起）都只吃 `notion_classify.py` 這條線的產出**，跟關鍵字分類流程無關。

### 平行實驗模組慣例（貫穿全專案的核心規範）

`labeled_corpus.jsonl` 之上疊的每一個模組（RAG → LangChain chain → LangChain agent → Agentic RAG 問答 → fine-tuning）都嚴格遵守：**新增檔案，絕不修改前一層的程式碼，只讀取前一層產出的共用資料／函式**。例如 `classify_agent.py` 會直接 import `classify_chain.py` 裡的 `CATEGORIES`／`ClassificationResult`／`_load_corpus` 等共用物件，但不會改動 `classify_chain.py` 本身；沒有任何模組會寫回 Notion 或修改 `results/`、`labeled_corpus.jsonl`。改動某個模組前，先確認同樣的邏輯有沒有已經在更上游的模組定義過，直接 import 沿用。

### 多供應商 LLM 選型不是隨意的

不同模組刻意用不同 LLM 供應商，都是**實測比較後**的決定，不要不查證就假設全部統一：
- `notion_classify.py`／`classify_chain.py`／`classify_agent.py`：Claude（`claude-haiku-4-5`）
- `src/rag/query_engine.py` 的 `answer_question()`／`answer_agent.py`：改用 Gemini（`gemini-3.1-flash-lite`，成本考量，公開展示網站也用這個模型控管費用）
- `src/finetune/generate_qa.py`：Gemini（實測比較過 Claude／Gemini／Groq，Gemini 品質相當且成本約 1/8，Groq 有觀察到編造事實的幻覺問題）
- fine-tuning 基底模型只用 `twinkle-ai/gemma-3-4B-T1-it`（原本也測過 Llama 版本，但 chat template 格式風險較高而放棄，見 README「本地 Fine-tuning」章節）

### 成本控管：`.claude/hooks/cost_warning.py`

PreToolUse hook，攔截 Bash/PowerShell 指令，比對是否匹配已知的付費 API 呼叫模式（`classify_chain`／`classify_agent`／`generate_qa`／`notion_classify.py`／`build_index`／`query_engine` 等），符合就強制轉成需要使用者確認的權限提示，並附上**基於真實 token 用量換算**的花費估計（不是憑感覺估的數字，每個估計背後都有一次真實呼叫的來源記錄在檔案開頭的 docstring）。新增任何會呼叫付費 API 的腳本或指令模式時，記得同步在這支 hook 加對應分支。

### `src/config.py`：分類流程集中設定

| 參數 | 說明 |
|------|------|
| `FOOTNOTE_Y_RATIO` | 頁底注腳分離閾值（預設 0.80） |
| `MAX_PARAGRAPH_LENGTH` / `MIN_PARAGRAPH_LENGTH` | 段落切分的字數上下限 |
| `BODY_END_KEYWORDS` | 停止擷取的關鍵字（如「參考文獻」） |
| `SECTION_BREAK_PATTERNS` | 章節切分 regex（章 > 節 > 小節優先） |

`export_paragraphs.py`（v2）的 `run_on_paper_dir_for_paragraphs` 實際上內部呼叫的是 `export_paragraphs_v1.py` 的狀態機實作，v2 自己的 `extract_paragraphs_from_pdf` 目前只是備用、未串進主流程——改這塊之前先確認實際呼叫路徑。

### 論文 ID 規則

PDF 檔名以數字開頭（`01-`、`02-`…），對應到匯出資料的 ID 格式 `P{論文序號}-{段落序號}`（如 `P1-3`）。序號有缺號（03、04…）代表該論文尚未收入。

### 部署（`deploy/rag_space/`）

Cloud Run 上線的 Gradio 展示網站，是 `query_engine.py`／`answer_agent.py` 的**獨立部署副本**，有自己的 git remote，整個 `deploy/` 在 `.gitignore` 裡被排除、不進這個主 repo 的版控——修改 RAG／agent 邏輯後若要同步更新展示網站，要記得手動同步過去，不會自動連動。詳見 `deploy/rag_space/README.md` 與 `KNOWN_ISSUES.md`。

### 其他

- `.cursor/skills/gazetteer-format-check`：依 `This_plan/信義鄉志服務建議書.pdf` 的編纂凡例／撰寫格式（紀年、標點、註腳格式等）檢核文稿的技能，處理跟鄉志正式出版格式相關的任務時用得上。
- `results/`、`batch_states/`、`.env`、`output/`、`vectorstore/`、`src/finetune/data/`、`src/finetune/adapters/`、`deploy/` 都是執行產物或機密設定，已在 `.gitignore`，不會進版控。
