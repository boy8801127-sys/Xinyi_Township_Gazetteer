# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

信義鄉誌論文分類流程：從碩博士論文 PDF 擷取段落，依關鍵字分類後匯出 CSV，供 LLM 輔助或人工編纂《南投縣信義鄉志》使用。

輸入：`paper/` 目錄下的論文 PDF（檔名前綴數字即為論文 ID，如 `01-xxx.pdf`）  
輸出：`output/` 目錄下的 CSV（段落、來源文章、頁數、分類）

## 執行方式

```bash
# 虛擬環境（Windows）
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 互動式選單入口（推薦）
python main.py

# CLI 直接執行分類流程（非互動）
python -m src.run_pipeline
python -m src.run_pipeline --max-pdfs 3
python -m src.run_pipeline --single paper/01-xxx.pdf
python -m src.run_pipeline --output-dir output/
```

## 架構說明

### 兩條獨立工作流

**分類流程**（`main.py` 選項 1~3）：

```
extract_pdf.py → segment_and_annotate.py → classify_and_export.py
```

- `extract_pdf.py`：PyMuPDF 擷取頁面文字行，注腳分離（依 `config.FOOTNOTE_Y_RATIO`）
- `segment_and_annotate.py`：依行距與章節 pattern 切分段落，標記來源與頁碼
- `classify_and_export.py`：讀取 `This_plan/類別關鍵字.json` 比對，輸出各分類 CSV

**LLM 段落匯出**（選項 4~5）：

- `export_paragraphs.py`（v2，目前使用）：無狀態機；直接合併所有行文字，依句號切句，再依章節 pattern 切分，最後合併短段。產出 `paragraphs_all.csv`（欄位：ID、段落、來源文章、頁數）及 `paragraphs_by_paper/*.csv`
- `export_paragraphs_v1.py`（舊版）：狀態機工作流，`run_on_paper_dir_for_paragraphs` 內部實際呼叫的是 v1

> **注意**：`export_paragraphs.py` 的 `run_on_paper_dir_for_paragraphs` 在內部 import 並呼叫 `export_paragraphs_v1.extract_paragraphs_from_pdf`，v2 的 `extract_paragraphs_from_pdf` 目前只作為備用實作。

**手動合併後處理**（選項 6）：

- `merge_paragraph_rows.py`：讀取 Excel 手動清空 ID 的行，與上一列合併後輸出 `paragraphs_all_merged.csv`

### 核心設定（`src/config.py`）

所有路徑、閾值、關鍵字列表集中管理。常需調整的參數：

| 參數 | 說明 |
|------|------|
| `FOOTNOTE_Y_RATIO` | 頁底注腳分離閾值（預設 0.80，即頁面下 20%） |
| `MAX_PARAGRAPH_LENGTH` | 段落字數上限（超過依句號再切，預設 200） |
| `MIN_PARAGRAPH_LENGTH` | 段落字數下限（過短與下段合併，預設 10） |
| `BODY_END_KEYWORDS` | 停止擷取的關鍵字（如「參考文獻」） |
| `SECTION_BREAK_PATTERNS` | 章節切分 regex（章 > 節 > 小節優先） |

### 分類設定（`This_plan/`）

- `類別.txt`：分類名稱清單（每行一個）
- `類別關鍵字.json`：`{"分類名稱": ["關鍵字1", "關鍵字2", ...]}` 對應

### 論文 ID 規則

PDF 檔名以數字開頭（`01-`、`02-`），匯出 CSV 的 ID 格式為 `P{論文序號}-{段落序號}`，如 `P1-3` 表示第 1 篇論文第 3 個段落。缺號（03、04…）表示論文尚未收入。

## 輸出目錄結構

```
output/
├── 總類別.csv                     # 全部段落（分類流程）
├── 歷史篇.csv、地理篇.csv …       # 各類別（分類流程）
├── paragraphs_all.csv             # LLM 段落匯出（主要輸入）
├── paragraphs_by_paper/           # 依論文分檔
├── paragraphs_all_merged.csv      # 手動合併後輸出
└── paragraphs_all_first_arrange.csv  # 手動合併前的輸入（若存在則優先讀取）
```
