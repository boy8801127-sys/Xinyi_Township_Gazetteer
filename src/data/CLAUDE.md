# src/data/ — 語料庫欄位慣例

## id／source 欄位格式（2026-07 標準化，見 `src/data/source_codes.py`）

`labeled_corpus.jsonl` 每筆的 `id` 格式是 `{來源代碼}-{原序號}-{段落序號}`，來源代碼是 14 種資料來源（論文、縣志、公文檔案等）各自固定的兩到三碼數字，定義在 `src/data/source_codes.py` 的 `SOURCE_CODES`，供之後新增其他來源類型時直接查表擴充，不要另外發明新的前綴規則：

- 論文（代碼 `98`，信義鄉布農族博碩士論文）：PDF 檔名以數字開頭（`01-`、`02-`…）對應論文序號，id 如 `98-11-200`。序號有缺號（03、04…）代表該論文尚未收入。`source` 欄位是腳註引用格式（`作者，〈篇名〉（學校地：系所，畢業年），頁X。`），書目資料存在 `src/data/paper_bibliography.json`（由 `src/data/build_paper_bibliography.py` 一次性從 `paper/信義鄉布農族博碩士論文.docx`＋`paper/台灣大專院校地址名冊.xls` 解析產生，之後新增的論文直接手動補一筆進 json，不用重跑該腳本），組裝邏輯在 `src/data/paper_bibliography.py::format_paper_citation()`。
- 縣志（代碼 `92`，南投縣志稿＆南投縣志＆續修南投縣志）：id 如 `92-01-079`，`source` 欄位維持 `南投縣志｜卷別 篇名｜條目名` 格式，不套用腳註格式。
- 期刊論文（代碼 `97`，華藝）：PDF 放在 `paper/期刊論文/`（檔名無數字前綴，序號依檔名排序 1~13，見 `paper/期刊論文/書目資料清單.csv`，已填妥），走獨立的 `src/export_paragraphs_journal.py`（呼叫 `export_paragraphs_v1.py::extract_paragraphs_from_pdf()` 新增的選用參數，傳入期刊專用的 `config.JOURNAL_BODY_START_KEYWORDS`／`JOURNAL_SECTION_HEADING_RE` 等設定，不影響學位論文既有呼叫路徑）擷取分段→人工複核（`split_and_merge_paragraphs_xlsx.py`／`merge_paragraph_rows.py`，比照學位論文的 Excel 合併儲存格慣例）→`src/data/classify_journal_with_gemini.py`（Gemini 分類、寫回 Notion）→`src/data/build_labeled_corpus.py` 的 `code_of(id) == "97"` 分支併入 `labeled_corpus.jsonl`。`source` 欄位引用格式由 `src/data/journal_bibliography.py::format_journal_citation()` 讀 `書目資料清單.csv` 組裝，格式跟論文一樣內含頁碼。全流程（含向量庫）已完成，目前 454 筆（13 篇）已在服役中的語料庫裡。
- `build_index.py` 的 `source_type`（UI／CLI 篩選用的「論文」／「書籍」粗分類）改用 `source_codes.py::source_type_for_id()` 查表，不要再用 id 前綴字母判斷。
