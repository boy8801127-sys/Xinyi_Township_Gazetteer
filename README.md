# 鄉志慧編（XinyiRAG）—— 信義鄉志論文分類系統

從碩博士論文 PDF 擷取文字、切分段落、標註來源與頁數，並支援 LLM 段落匯出與手動合併後處理。產出格式對齊《南投縣信義鄉志》編纂凡例與撰寫格式。

## 功能

- **分類流程**：擷取 PDF → 切分標註 → 依類別關鍵字標籤 → 匯出各類別 CSV
- **LLM 段落匯出**：從 PDF 擷取摘要與內文段落，產出 `paragraphs_all.csv` 供 LLM 使用
- **手動合併**：將 ID 為空的列與上一列合併（適用於 Excel 合併儲存格後匯出）
- **Notion 自動分類**：呼叫 **Claude API** 對 Notion 資料庫中的段落做分類與關鍵字擷取，透過提示語工程讓回覆格式化為固定 JSON schema，再自動寫回 Notion 對應欄位（詳見〈[Notion 自動分類](#notion-自動分類claude-api)〉）
- **RAG 鄉志編纂問答助手**：用 **LlamaIndex + Chroma + Voyage embeddings** 把已分類段落建成向量索引，可用自然語言提問並取得附引用來源（論文＋頁碼）的回答，也可做純語意檢索（詳見〈[RAG 進階實驗](#rag-進階實驗llamaindex--chroma--voyage)〉）
- **LangChain 動態 Few-shot 分類 Chain**：用 **LangChain（LCEL）**串接 RAG 檢索與 Claude 結構化輸出，讓分類 prompt 的 few-shot 範例依待分類段落動態抽換，取代固定範例（詳見〈[LangChain 動態 Few-shot 分類 Chain](#langchain-動態-few-shot-分類-chain)〉）
- **LangChain Agent 編排**：用 **LangChain（`create_agent`）**讓模型自行決定要不要呼叫檢索工具、呼叫幾次、查什麼，而非把流程寫死在程式碼裡，展示 chain（固定編排）與 agent（模型自主編排）的差異（詳見〈[LangChain Agent 編排](#langchain-agent-編排)〉）
- **本地 Fine-tuning（Twinkle AI）**：用 **Unsloth QLoRA** 在本機 GPU 對台灣語境 fine-tuned 的開源模型（Twinkle AI 系列）做監督式微調，把分類知識直接內化進模型權重，取代推論時的 in-context 範例／工具檢索（詳見〈[本地 Fine-tuning（Twinkle AI）](#本地-fine-tuningtwinkle-ai)〉）

## 環境

- Python 3.10+
- 依賴：PyMuPDF、openpyxl、anthropic、notion-client、python-dotenv、llama-index、chromadb、voyageai、langchain-core、langchain-anthropic、langchain

```bash
pip install -r requirements.txt
```

> 若要跑本地 Fine-tuning（見〈[本地 Fine-tuning（Twinkle AI）](#本地-fine-tuningtwinkle-ai)〉），另外安裝 `requirements-finetune.txt`（torch、unsloth、trl 等重量級 ML 套件，需要本機 GPU，獨立於上面的主要依賴）：
> ```bash
> pip install -r requirements-finetune.txt
> ```

> Windows 繁體中文系統若安裝時出現 `UnicodeDecodeError: 'cp950' codec can't decode ...`（`requirements.txt` 內含中文註解），改用 `PYTHONUTF8=1 pip install -r requirements.txt` 即可。

若要使用 Notion 自動分類流程或 RAG 進階實驗，需在專案根目錄建立 `.env`（**不會被版控追蹤**）：

```bash
ANTHROPIC_API_KEY=sk-ant-xxxxx
NOTION_API_KEY=ntn_xxxxx
NOTION_DATABASE_ID_1=xxxxxxxx      # Notion 頁面 1（內含多個 child_database）
NOTION_DATABASE_ID_2=xxxxxxxx      # Notion 頁面 2（選用，--all 才需要）
VOYAGE_API_KEY=pa-xxxxx            # RAG embedding（Voyage AI，僅 RAG 進階實驗需要）
GOOGLE_API_KEY=xxxxxxxx            # Fine-tuning：generate_qa.py 生成合成 QA 對（僅本地 Fine-tuning 需要）
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

## Notion 自動分類（Claude API）

段落匯出到 Notion 後，用 **Claude API**（`claude-haiku-4-5`）逐段判斷所屬篇章並擷取關鍵字，寫回 Notion 的「分類」「分類原因」「關鍵字」欄位，取代人工逐筆分類。

### 提示語工程：讓回覆公式化

分類品質與可解析性主要靠 `notion_classify.py` 裡的 `SYSTEM_PROMPT` 控制：

- **鎖定角色與範圍**：系統提示詞開頭固定「你是《南投縣信義鄉志》的編纂助理」，並把 `This_plan/類別.txt`（分類清單）與 `This_plan/信義鄉志架構分類.txt`（各篇章內容範圍）整段塞入提示詞，讓 Claude 分類時有依據，不是憑空猜測。
- **明確的輸出規則**：規定最多選 1～2 個分類、分類原因限制 20～50 字、關鍵字限制 3～5 個，並要求「只輸出純 JSON，不加任何說明文字」。
- **Few-shot 範例固定格式**：提示詞內附上「單一分類」與「跨兩分類」兩組範例 JSON，讓模型的回覆格式高度一致，方便程式直接 `json.loads` 解析，不需額外做自然語言擷取。
- **程式端二次防呆**（`_parse_claude_json` / `_normalize_category`）：即使模型吐出的分類名稱有些微出入（漏字、多字），也會用前綴比對修正回合法分類；`reason` 超長會截斷、`keywords` 超過 5 個會截斷，避免寫入 Notion 時因格式不符而失敗。

### 執行模式

```bash
python notion_classify.py --first-only --dry-run   # 先預覽第一個 Notion 資料庫的分類結果，不寫入
python notion_classify.py --first-only              # 確認無誤後，寫入第一個資料庫
python notion_classify.py --all                     # 即時模式，處理兩個頁面下的全部論文
python notion_classify.py --all --batch              # Batch 模式，費用省 50%（見下）
python notion_classify.py --submit-all               # 一次送出所有論文的 batch，不等待
python notion_classify.py --collect-all               # 輪詢所有 batch，完成後統一寫回 Notion
python notion_classify.py --batch-resume <batch_id>   # 續跑中斷的 batch
python notion_classify.py --apply-local results/xxx.json  # 只補寫尚未成功寫入 Notion 的記錄
```

### Batch API：大量處理省 50% 費用

`--batch` 會改用 Claude 的 Message Batches API 非同步送出整批段落，等全部處理完再一次收回結果，Input/Output token 單價都是即時 API 的一半。`calc_cost.py <batch_id>` 可查詢指定 batch 的實際 token 用量並試算美金／台幣費用。

### 容錯與斷點續傳

- 每個 Notion child_database 對應一份 `results/*.json` 本地快取，內含每筆段落的分類結果與 `written_to_notion` 狀態；**每處理完一筆就落地存檔**，中途斷線也不會遺失已完成的分類。
- 重新執行時只會處理 `written_to_notion=false` 的記錄，不會重複呼叫 Claude 或重複寫入 Notion。
- `fix_errors.py` 用來針對性修復少數寫入失敗的記錄（例如關鍵字含逗號被 Notion multi-select 拒絕、或寫入當下網路中斷），會重用 `notion_classify.py` 的分類與寫入函式。
- 首次執行會自動在 Notion 資料庫新增「分類」「分類原因」「關鍵字」三個欄位（`ensure_data_source_properties`），不用手動建欄位。

### 輔助腳本

| 腳本 | 用途 |
|------|------|
| `src/split_and_merge_paragraphs_xlsx.py` | 匯出的段落 xlsx 後處理：合併孤兒空白 ID、依 `P{論文序號}` 分篇、合併跨列的段落／頁數，輸出各篇 xlsx 與合併總檔 |
| `calc_cost.py` | 查詢指定 batch 的 token 用量，試算 Claude Batch API 費用 |
| `fix_errors.py` | 修復個別寫入失敗的分類記錄 |

> `results/`、`batch_states/`、`.env` 皆為執行過程產物與機密設定，已列入 `.gitignore`，不會上傳版控。

## RAG 進階實驗（LlamaIndex + Chroma + Voyage）

在 Notion 自動分類流程產出的標註資料（`results/*.json`）之上，額外做了一個**平行的實驗性模組**，把已分類段落建成可語意檢索的知識庫，不影響、也不依賴正式的 `notion_classify.py` 流程。這是作品集／技術展示用途，示範 RAG 架構的實作方式：Retrieval（LlamaIndex + Chroma 向量庫 + Voyage embeddings）＋ Generation（Gemini 依檢索結果生成含引用的回答）。

### 架構

```
output/paragraphs_all_merged.csv ─┐
                                    ├─> src/data/build_labeled_corpus.py ─> labeled_corpus.jsonl
results/*.json（Claude 分類結果）─┘                                              │
                                                                                  ▼
                                                              src/rag/build_index.py
                                                          （Voyage embedding → Chroma 向量庫）
                                                                                  │
                                                                                  ▼
                                                             src/rag/query_engine.py
                                                    search_similar()／answer_question()
```

- **語料整備**（`src/data/build_labeled_corpus.py`）：以段落 ID 合併 CSV 的段落／來源／頁碼與 `results/*.json` 的分類結果，只保留分類成功且無錯誤的紀錄，輸出成 `labeled_corpus.jsonl`。目前實際跑出 10,099 筆乾淨標註段落。
- **建索引**（`src/rag/build_index.py`）：每筆段落轉成 LlamaIndex 的 `TextNode`，metadata 帶來源論文、頁碼、分類、關鍵字；用 Voyage AI 的 `voyage-3` 模型做 embedding（支援繁體中文），寫入本機持久化的 Chroma 向量庫。
- **查詢引擎**（`src/rag/query_engine.py`）：
  - `search_similar(paragraph, k, category=None)`：純語意檢索，可用 `category_primary` metadata 過濾分類，用途是之後串進分類流程做「動態 few-shot」（取代目前寫死在 prompt 裡的固定範例）
  - `answer_question(question, k)`：檢索＋用 Gemini（`gemini-3.1-flash-lite`）生成有依據的回答，並回傳引用的來源清單（論文＋頁碼），降低憑空捏造答案的風險

### 使用方式

```bash
python -m src.data.build_labeled_corpus   # 產生 labeled_corpus.jsonl
python -m src.rag.build_index             # 建立 Chroma 向量索引（呼叫 Voyage API）

python -m src.rag.query_engine --ask "信義鄉在日治時期發生過哪些重要史事？"
python -m src.rag.query_engine --search "布農族祭典" --k 5
python -m src.rag.query_engine --search "部落產業" --category 經濟篇
```

> `labeled_corpus.jsonl`、`vectorstore/` 皆為可重新產生的執行產物，已列入 `.gitignore`。

### Agentic 版問答（`src/langchain_pipeline/answer_agent.py`）

`answer_question()` 每次固定檢索 `k` 筆就直接生成答案：問題若是廣泛性的歷史提問（例如「發生過哪些重要事件」），檢索一次很容易只看到單一面向，全面性會不如直接問一般 LLM——但直接問一般 LLM 又會失去 RAG「每個論點都有真實引用來源」的優勢，答案容易夾雜通用知識拼湊出來、查無來源的內容。

`answer_agent.py` 沿用 `classify_agent.py` 的 `langchain.agents.create_agent` 編排方式，把檢索包成工具交給 Gemini，讓模型自己判斷：
- 要不要呼叫檢索工具、呼叫幾次（最多 6 次，用 `ToolCallLimitMiddleware` 針對這個工具本身硬性把關；`recursion_limit` 是另一層、對整個 agent 推理迴圈的步數上限）
- 用什麼查詢字句（可自行改寫成更精準的關鍵詞、換不同切入角度分次檢索）

系統提示明確禁止用檢索不到的通用知識填補答案，只是鼓勵模型在問題廣泛時主動多角度查詢，藉此在不犧牲引用可信度的前提下提升回答的全面性。

實測：「南投縣信義鄉在日治時期發生過哪些重要的事情？」單次版預設 `k=5` 檢索不到相關段落、誠實回答「未提及」；agentic 版換了 3 次關鍵字後查到內容，回答涵蓋 4 個不同面向、附 5 筆引用來源。另一題「信義鄉的集團移住政策，前因後果？」單次版本身就答得不錯（5 筆引用），agentic 版只查了 1 次（判斷單次已足夠），但透過系統提示要求的分面向整理，補上了單次版沒有的因果脈絡細節（3 筆引用）——這說明 agentic 版的優勢不只來自多查幾次，也來自對同一批檢索結果做更完整的綜合整理。

```bash
python -m src.langchain_pipeline.answer_agent --ask "南投縣信義鄉在日治時期發生過哪些重要的事情？"
python -m src.langchain_pipeline.answer_agent --compare --ask "..."   # 同一題並列比較單次版與 agent 版
```

> 跟 `classify_agent.py --compare` 一樣不做自動化「正確率」評分——這裡沒有標準答案可比對，只印出兩版答案、引用段落數、agent 實際呼叫工具次數與查詢字句，供人肉眼判斷全面性有沒有真的提升。

### 線上展示（Google Cloud Run）

把 RAG 問答助手（單次版＋agentic 版）包成 Gradio 介面，用 Docker 容器部署到 Google Cloud Run，作為作品集的公開展示：

**🔗 線上網址：https://xinyi-gazetteer-rag-155352595280.asia-east1.run.app**

- 部署用程式碼獨立放在 `deploy/rag_space/`（不進本 repo 版控），內容是 `query_engine.py`／`answer_agent.py` 的部署用副本＋ Gradio `app.py` ＋已建好的 `vectorstore/chroma/`＋ `Dockerfile`
- 生成模型改用 Gemini（免費額度可控管公開展示的成本），embedding 仍是 Voyage；兩把 API key 存在 Secret Manager，以密鑰方式注入容器，不寫死在映像檔或程式碼裡
- 提問次數限制以**來源 IP**為準（`IP_LIMIT=3`），而不是瀏覽器 `gr.State`——`gr.State` 綁定的 session 一重新整理頁面就會重新產生、歸零，擋不住「刷新頁面繼續問」，改用 IP 才是真正有效的關卡；另有模組層級的全域上限（`GLOBAL_LIMIT=200`）兜底
- UI 有一個收合的「進階選項」，輸入正確的管理者密碼可以跳過提問次數限制（密碼存在 Secret Manager 的 `ADMIN_PASSWORD`，用 `hmac.compare_digest` 做固定時間比對，不寫死在程式碼或版控裡），方便作者自己測試不受訪客額度卡住
- 已知殘留限制（純記憶體實作，沒接外部資料庫，是有意識的取捨）：容器閒置太久被 Cloud Run 縮到 0 後，下次冷啟動是全新行程，IP／全域計數會歸零；`max-instances` 設為 `1`，確保同一時間只有一個容器行程、避免多容器各自維護計數導致實際上限變成倍數
- Cloud Run 預設 `min-instances=0`（無流量時自動縮到 0，不跑背景費用），冷啟動後第一次請求會慢幾秒，UI 上已加提示；送出問題後畫面會先顯示「思考中」的 loading 訊息，避免使用者以為當掉
- 用 Gradio 的 `mcp_server=True` 讓這個服務同時是網頁 demo 也是 MCP server，可被 MCP client 直接呼叫（已知限制：MCP 呼叫沒有瀏覽器請求可取得來源 IP，會統一算在同一個桶子裡，比照一般訪客的上限）
- 有設定 Cloud Monitoring：Uptime check 每 5 分鐘檢查首頁是否能正常載入，另有「網站載入失敗」與「5xx 錯誤率」兩條告警政策，異常時 email 通知作者；GCP 帳單也設了每月預算警示（約 20 美元，50%／80%／100% 三個門檻）
- 每筆問答都會背景記錄一份到作者自己的 Google Sheet（`qa_logger.py`），供日後分析訪客實際問了什麼、回答品質如何——用 Cloud Run 原生附掛的服務帳戶身份寫入（作者的 Sheet 只需分享「編輯者」權限給該服務帳戶信箱），不需要另外的金鑰檔；寫入失敗不影響使用者拿到的回答（背景執行緒＋例外全部吞掉，只印警告到 log）
- 已知限制與上線後待改進項目整理成 [`deploy/rag_space/KNOWN_ISSUES.md`](deploy/rag_space/KNOWN_ISSUES.md)（純記憶體限流的殘留風險、後續優先改進順序、部署維運速查指令）

⚠️ 本展示僅供參考，回答可能不完全準確，正式資料請查證原始文獻。

## LangChain 動態 Few-shot 分類 Chain

在 RAG 模組之上，再做一個**平行的實驗性模組**，示範用 **LangChain（LCEL）**編排「檢索 → 組 prompt → 結構化輸出」的分類流程，一樣不影響、也不依賴正式的 `notion_classify.py` 分類流程，純作技術示範。

### 動機

`notion_classify.py` 對每個段落分類時，prompt 裡固定寫死兩組 few-shot 範例，不論待分類段落內容為何都套用同一組；輸出解析也是手刻的 JSON 解析＋分類名稱修正邏輯。這個模組改用：

- **動態 few-shot**：每次分類前，先用 RAG 模組的 `search_similar()` 找出跟待分類段落語意最相近、且已完成分類的真實範例，取代寫死的固定範例，讓範例更貼近實際待分類內容。
- **結構化輸出（`with_structured_output`）**：用 Pydantic schema 定義分類結果，`categories` 欄位在型別層級就限制只能是分類清單中的合法名稱，不需要再靠字串前綴比對做二次修正。

### 有無 LangChain 的差異

| 項目 | 沒有 LangChain（`notion_classify.py` 既有流程） | 有 LangChain（`classify_chain.py`） |
|------|------------------------------------------------|--------------------------------------|
| Few-shot 範例 | 寫死在 `SYSTEM_PROMPT` 裡固定 2 組範例，所有段落共用 | 每次即時用 RAG 檢索跟段落語意最相近的真實已分類範例，逐段動態抽換 |
| 輸出格式保證 | 手寫 `_parse_claude_json()` + `_normalize_category()`，靠字串前綴比對修正模型吐錯的分類名稱 | Pydantic schema + `with_structured_output()`，`categories` 在型別層級就限制為合法分類名稱，不需二次修正 |
| 流程串接方式 | 函式依序手動呼叫（送 prompt → parse → normalize → 寫入 Notion） | 用 LCEL（`\|` 運算子）把「檢索→組 prompt→結構化輸出」組成一條可重用、可單獨呼叫的 `classify_chain` pipeline |
| 失敗重試 | 個別腳本手寫 `try/except` 與迴圈 | `Runnable.with_retry()` 宣告式設定重試次數與重試條件 |
| 可組合性 | 換 few-shot 範例、換模型都要改同一支腳本內部邏輯 | chain 的每一步都是獨立 `Runnable`，理論上可單獨替換檢索器、prompt 組裝、LLM，不動其他步驟 |
| 定位 | 已驗證穩定、正式寫入 Notion 的生產流程 | 平行的實驗／展示模組，示範 chain 編排技術，不寫入 Notion |

### 實測數據（`--compare` 抽樣結果）

用 `--compare` 對既有語料抽樣（共 23 筆，seed 42／1／7 三批）比較動態 chain 與既有標註：

| 指標 | 數值 |
|------|------|
| 抽樣筆數 | 23 |
| 與既有標註完全一致 | 18/23（78%） |
| 與既有標註至少部分重疊 | 22/23（96%） |

> ⚠️ 這裡的「一致率」衡量的是動態 chain 與既有標註（即 `notion_classify.py` 舊流程的輸出）**答案相不相似**，既有標註本身並非人工驗證過的 ground truth，所以這不是正確率，兩者分類不同時無法判斷哪一個才是對的。若要量化真正的正確性提升，需要另外找一批樣本做人工判讀當 ground truth 再比較。

### 架構

```
待分類段落
   │
   ▼
RunnableLambda(_retrieve_examples)   ── 呼叫 src/rag/query_engine.search_similar()
   │                                    過濾「無法判斷」與自我匹配
   ▼
RunnableLambda(_build_prompt)        ── 組成 System + 動態 few-shot（Human/AI 訊息對）+ 待分類段落
   │
   ▼
ChatAnthropic(claude-haiku-4-5).with_structured_output(ClassificationResult)
   │
   ▼
ClassificationResult（categories／reason／keywords，型別已驗證）
```

### 使用方式

```bash
python -m src.langchain_pipeline.classify_chain --text "段落文字…"        # 單段測試，印出動態 few-shot 範例與分類結果
python -m src.langchain_pipeline.classify_chain --paper-id P11-199       # 從語料撈一筆段落，並對照原本的分類
python -m src.langchain_pipeline.classify_chain --compare --sample 10    # 抽樣比較動態 chain 與既有語料的靜態分類，統計一致率
```

`--compare` 直接拿 `labeled_corpus.jsonl` 裡既有的分類結果（即 `notion_classify.py` 固定 few-shot 版本產出）當基準，不會重新呼叫舊流程，也不會產生額外的分類費用。

> 這是展示用途，不影響正式流程；不會寫入 Notion，也不會修改 `results/`、`labeled_corpus.jsonl`。

## LangChain Agent 編排

在 `classify_chain.py` 之上，再做一個**平行的實驗性模組**（`classify_agent.py`），示範 **chain** 與 **agent** 在編排哲學上的差異。

### Chain vs Agent

`classify_chain.py` 是一條**固定** pipeline：不論段落內容為何，永遠檢索固定 `k`（3）筆範例、永遠用完整段落文字當查詢字句、永遠只呼叫一次 Claude——流程順序是**程式碼決定**的。

`classify_agent.py` 改用 `langchain.agents.create_agent`，把檢索包成一個工具（tool）交給 Claude，讓**模型自己決定**：
- 要不要呼叫檢索工具（段落內容清楚、有把握時可以直接作答，完全不查）
- 呼叫幾次（最多 3 次，並用 `recursion_limit` 硬性把關，避免工具呼叫迴圈失控燒錢）
- 用什麼查詢字句（可以自行改寫成更精準的關鍵詞，不一定要用段落原文）
- 要不要限定分類篩選範圍

### 實測數據（`--compare --sample 23 --seed 42`，與 chain 版本同樣本數）

| 指標 | Chain（固定檢索 3 筆） | Agent（自主決定） |
|------|----------------------|-------------------|
| 抽樣筆數 | 23 | 23 |
| 與既有標註完全一致 | 18/23（78%） | 13/23（57%） |
| 與既有標註至少部分重疊 | 22/23（96%） | 22/23（96%） |
| 平均每筆呼叫檢索次數 | 固定 3 次 | 0.5 次 |
| 完全不檢索的筆數 | 0/23（0%） | 13/23（57%） |

> ⚠️ 跟前面 chain 的說明一樣，這是「跟舊方法答案像不像」的**一致率**，不是正確率。這裡真正有意思的是**取捨**：agent 平均只呼叫 0.5 次檢索工具（chain 固定呼叫 3 次），代表過半數段落它認為靠自身判斷就夠、不需要參考範例，明顯降低檢索呼叫與對應的 token 成本；但代價是與舊方法基準的貼合度也從 78% 降到 57%（部分重疊率則持平在 96%，代表方向大致仍抓得住，只是細節判斷跟舊方法出入變大）。這正是 chain（穩定、可預期）與 agent（彈性、成本可能更低，但行為波動較大）在工程取捨上的具體展示。

### 架構

```
待分類段落
   │
   ▼
create_agent(model=ChatAnthropic, tools=[search_similar_paragraphs], response_format=ClassificationResult)
   │
   ├─ 模型決定：直接作答 ────────────────────────────► ClassificationResult
   │
   └─ 模型決定：呼叫 search_similar_paragraphs(query, k, category)
        │         （包裝 src/rag/query_engine.search_similar()，query 可由模型自行改寫）
        ▼
      最多重複 3 次（recursion_limit=10 為硬性防線）
        │
        ▼
      ClassificationResult（categories／reason／keywords，型別已驗證）
```

### 使用方式

```bash
python -m src.langchain_pipeline.classify_agent --text "段落文字…"        # 單段測試，印出實際呼叫工具次數與查詢字句
python -m src.langchain_pipeline.classify_agent --paper-id P13-1126      # 從語料撈一筆段落，並對照原本的分類
python -m src.langchain_pipeline.classify_agent --compare --sample 10    # 抽樣比較 agent 與既有語料的靜態分類，統計一致率與平均呼叫次數
```

`--compare` 跟 `classify_chain.py` 一樣，直接拿 `labeled_corpus.jsonl` 裡既有的分類結果當基準，不會重新呼叫舊流程。

> 這是展示用途，不影響正式流程；不會寫入 Notion，也不會修改 `results/`、`labeled_corpus.jsonl`。

## 本地 Fine-tuning（Twinkle AI）

在 RAG／LangChain chain／agent 之上，再做最後一個**平行的實驗性模組**（`src/finetune/`），示範跟前面三者不同路線的技術：不是在推論時檢索或編排，而是把信義鄉相關知識**直接微調進模型權重**。

### 動機：跟 RAG 問答的差異

`src/rag/query_engine.py` 的 `answer_question()` 是「推論時檢索＋引用來源」：每次問問題都重新去向量庫找相關段落，答案附上引用的論文與頁碼，可追溯、不容易編造。這個模組反過來，是「訓練時就把知識內化進模型參數」：微調後的模型直接回答問題，推論時不檢索、也不附來源——換取的是不用額外查詢步驟，代價是沒有引用來源可以查證、也更容易在模型沒學到的地方編造答案。兩者是刻意做成對照的技術路線，不是要取代 RAG。

### 基底模型：Twinkle AI（台灣語境 fine-tuned 開源模型）

選用 [Twinkle AI](https://huggingface.co/twinkle-ai) 在 Hugging Face 上發布的模型當基底，而非通用的英文中心模型，因為它已經針對台灣語境（地名、歷史事件、法律用語等）做過對齊：

| 模型 | 基底 | 參數量 | 定位重點 |
|------|------|--------|----------|
| `twinkle-ai/gemma-3-4B-T1-it` | Gemma 3 | 4B | 訓練重點是台灣人文/社會/地方文史語境，跟信義鄉誌內容最貼題；HF 上是 gated license，需先接受授權 |

原本也試過 `twinkle-ai/Llama-3.2-3B-F1-Instruct`（3B，無 gated 授權限制），但這個模型用 Hermes 格式訓練，chat template 跟標準格式不同，要讓 `train_on_responses_only`（只對 assistant 回答算 loss）正確運作需要額外驗證 marker 字串、風險較高，權衡之下改成只用 Gemma——Gemma 是 Google 官方標準 chat template，風險低很多，仍然保留 Twinkle 對台灣語境預先適配過的優勢。

本機環境：RTX 5060 Laptop GPU（8GB VRAM），用 **Unsloth + QLoRA（4-bit）** 微調——8GB 消費級顯卡足以微調 3B/4B 模型，且不受 Colab session 時長與重複上傳資料的限制。

### 訓練資料：合成 QA 對

`labeled_corpus.jsonl` 的段落是敘述性文字，不是現成的問答對，所以先用 LLM（`generate_qa.py`）把每個段落轉成 0~2 組合成 QA 對再拿去微調，讓模型學到的是「怎麼回答問題」而不只是「行文風格」。這一步會呼叫付費 API，比照專案一貫做法**逐筆落地快取＋可斷點續傳**，重新執行只處理尚未生成過的段落，不會重複計費；執行前 `.claude/hooks/cost_warning.py` 會先跳出花費估算再讓使用者決定要不要繼續。

**生成模型選型**：實際用 5 個代表性段落（涵蓋不同篇章＋1 個「無法判斷」邊界案例）比較過 Claude Haiku 4.5／Gemini 3.1 Flash-Lite／Groq（Llama 3.3 70B Versatile）三家：

| 供應商 | 全量 10,099 筆預估花費 | 觀察 |
|---|---|---|
| **Gemini 3.1 Flash-Lite（採用）** | **~$3.4 USD** | 品質與 Claude 相當，正確處理「無法判斷」邊界案例 |
| Groq Llama 3.3 70B | ~$5.5 USD | 較便宜，但實測中發現會編造段落沒提到的資訊（例如把信義鄉布農族祭儀誤植為「泰雅族」），訓練資料正確性風險較高，未採用 |
| Claude Haiku 4.5 | ~$28.3 USD | 品質最佳，但成本是 Gemini 的約 8 倍 |

最終選用 **Gemini 3.1 Flash-Lite**：品質不輸 Claude，成本卻大幅降低，也沒有觀察到 Groq 那樣的幻覺問題。

### 架構

```
src/data/labeled_corpus.jsonl（10,099 筆已分類段落）
        │
        ▼
src/finetune/generate_qa.py          ── 呼叫 Gemini 對每段生成 0~2 組合成 QA 對
        │                                （逐筆落地快取，可斷點續傳）
        ▼
src/finetune/data/qa_pairs.jsonl
        │
        ▼
src/finetune/prepare_dataset.py      ── 依段落既有分類分層抽樣切出 held-out 評估集
        │                                （段落層級切分，避免同段落的 QA 洩漏到兩邊）
        ▼
src/finetune/data/{train.jsonl, eval_ids.json}
        │
        ▼
src/finetune/train.ipynb             ── Unsloth QLoRA，逐格執行：載入 4-bit 基底模型
        │                                → 掛 LoRA → smoke test → 全量訓練 → 存 adapter
        ▼
src/finetune/adapters/gemma/
        │
        ▼
src/finetune/evaluate.py             ── 對 held-out QA 並列印出模型答案 vs 參考答案
```

### 使用方式

```bash
python -m src.finetune.generate_qa --sample 20   # 先小量測試，控制花費
python -m src.finetune.generate_qa --all          # 處理全部尚未生成過的段落（會先看到花費估算）
python -m src.finetune.prepare_dataset            # 切 train/eval

# 開啟 src/finetune/train.ipynb，逐格執行

python -m src.finetune.evaluate
python -m src.finetune.evaluate --text "信義鄉在日治時期發生過哪些重要史事？"
```

> ⚠️ 訓練資料的參考答案是 Gemini 生成的合成資料，不是人工驗證過的 ground truth；開放式問答也沒有簡單的字串比對可以衡量對錯，所以 `evaluate.py` 只並列印出模型答案與參考答案供人工判讀，不提供自動判定的「正確率」，延續本專案一貫「不虛構一致率／正確率」的誠實標註原則。
>
> 本機訓練不呼叫計量付費 API（只有 `generate_qa.py` 這一步例外，且已有 `cost_warning.py` 揭露機制），是展示用途，不影響正式流程；不會寫入 Notion，也不會修改 `results/`、`labeled_corpus.jsonl`。

### 已上傳的 LoRA adapter

訓練完成的 adapter（依 held-out loss 選出的 epoch 2 checkpoint）已公開上傳到 Hugging Face：[wesleyishere123/gemma-3-4b-xinyi-gazetteer-lora](https://huggingface.co/wesleyishere123/gemma-3-4b-xinyi-gazetteer-lora)。model card 完整記錄了訓練方式與 `evaluate.py` 實測發現的限制（具體事實／專有名詞容易有幻覺，不建議直接拿來回答需要精確史實的問題，建議改用本專案的 RAG 系統）。

## 目錄結構

```
Xinyi_Township_Gazetteer/
├── main.py              # 互動式入口
├── notion_classify.py   # Notion 自動分類（Claude API）
├── fix_errors.py         # 修復個別寫入失敗的分類記錄
├── calc_cost.py           # Batch API 用量與費用試算
├── requirements.txt
├── .env                  # Claude／Notion API 金鑰（不上傳版控）
├── paper/                # 論文 PDF（輸入，不上傳版控）
├── output/                # 產出 CSV（不上傳版控）
├── results/                # Notion 分類本地快取（不上傳版控）
├── batch_states/            # Batch API 送出狀態（不上傳版控）
├── This_plan/            # 類別與關鍵字設定
├── vectorstore/           # RAG 向量庫（不上傳版控）
└── src/
    ├── extract_pdf.py               # PDF 擷取
    ├── segment_and_annotate.py      # 切分與標註
    ├── classify_and_export.py       # 分類匯出
    ├── export_paragraphs.py         # LLM 段落匯出
    ├── export_paragraphs_v1.py      # 段落擷取（狀態機工作流）
    ├── merge_paragraph_rows.py      # 手動合併處理
    ├── split_and_merge_paragraphs_xlsx.py  # 段落 xlsx 分篇／合併後處理
    ├── data/
    │   └── build_labeled_corpus.py  # 合併段落與分類結果 → labeled_corpus.jsonl（不上傳版控）
    ├── rag/
    │   ├── build_index.py           # 建立 LlamaIndex + Chroma 向量索引
    │   └── query_engine.py          # 語意檢索／問答助手查詢引擎
    ├── langchain_pipeline/
    │   ├── classify_chain.py        # LangChain LCEL 動態 few-shot 分類 chain
    │   └── classify_agent.py        # LangChain agent 編排（模型自主決定是否／如何檢索）
    └── finetune/
        ├── generate_qa.py           # 呼叫 Gemini 對段落生成合成 QA 對（可斷點續傳，不上傳版控）
        ├── prepare_dataset.py       # 切 held-out 評估集／訓練集，轉 QA chat 格式
        ├── train.ipynb              # Unsloth QLoRA 微調，逐格執行
        ├── evaluate.py              # 對 held-out QA 並列印出模型答案 vs 參考答案
        ├── data/                    # QA 快取／train.jsonl／eval_ids.json（不上傳版控）
        └── adapters/                # LoRA adapter 權重（不上傳版控）
```
