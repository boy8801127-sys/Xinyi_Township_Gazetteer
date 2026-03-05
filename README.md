# 信義鄉誌論文分類流程

從碩博士論文 PDF 擷取文字、切分段落、標註來源與頁數，並支援 LLM 段落匯出與手動合併後處理。產出格式對齊《南投縣信義鄉志》編纂凡例與撰寫格式。

## 功能

- **分類流程**：擷取 PDF → 切分標註 → 依類別關鍵字標籤 → 匯出各類別 CSV
- **LLM 段落匯出**：從 PDF 擷取摘要與內文段落，產出 `paragraphs_all.csv` 供 LLM 使用
- **手動合併**：將 ID 為空的列與上一列合併（適用於 Excel 合併儲存格後匯出）

## 環境

- Python 3.10+
- 依賴：PyMuPDF

```bash
pip install -r requirements.txt
```

或使用虛擬環境：

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux / macOS
pip install -r requirements.txt
```

## 使用

### 互動式入口（推薦）

在專案根目錄執行：

```bash
python main.py
```

選單選項：

| 選項 | 說明 |
|------|------|
| 1 | 執行完整分類流程（處理 paper 目錄內全部 PDF） |
| 2 | 執行分類流程（僅處理前 N 本 PDF） |
| 3 | 處理單一 PDF 檔案 |
| 4 | LLM 段落匯出：全部 PDF → paragraphs_all.csv + paragraphs_by_paper/ |
| 5 | LLM 段落匯出：僅處理前 N 本 PDF |
| 6 | 合併手動編輯後的段落（ID 為空者與上一列合併） |
| 7 | 結束 |

### 手動合併流程（選項 6）

1. 執行選項 4 或 5 產生 `paragraphs_all.csv`
2. 以 Excel 開啟，欲合併的列將 **ID 欄位清空**（由上往下合併）
3. 另存為 `paragraphs_all_first_arrange.csv` 或直接覆寫 `paragraphs_all.csv`
4. 執行選項 6，產出 `paragraphs_all_merged.csv`

## 產出

### 分類流程

- `output/總類別.csv`：所有段落（段落、來源文章、頁數、註腳、類別）
- `output/歷史篇.csv`、`output/地理篇.csv`、…：各類別段落

類別定義於 `This_plan/類別.txt`，關鍵字對應於 `This_plan/類別關鍵字.json`。

### LLM 段落匯出

- `output/paragraphs_all.csv`：全部段落，欄位：ID、段落、來源文章、頁數
- `output/paragraphs_by_paper/*.csv`：依論文分檔

### 合併後

- `output/paragraphs_all_merged.csv`：合併後的段落，ID 保留群組第一列

## 目錄結構

```
Xinyi_Township_Gazetteer/
├── main.py              # 互動式入口
├── requirements.txt
├── paper/               # 論文 PDF（輸入）
├── output/              # 產出 CSV
├── This_plan/           # 類別與關鍵字設定
└── src/
    ├── extract_pdf.py           # PDF 擷取
    ├── segment_and_annotate.py  # 切分與標註
    ├── classify_and_export.py   # 分類匯出
    ├── export_paragraphs.py     # LLM 段落匯出
    ├── export_paragraphs_v1.py  # 段落擷取（狀態機工作流）
    └── merge_paragraph_rows.py  # 手動合併處理
```
