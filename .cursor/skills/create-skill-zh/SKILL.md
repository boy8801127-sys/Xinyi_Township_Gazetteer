---
name: create-skill-zh
description: 引導使用者建立有效的 Cursor Agent 技能。使用時機：建立、撰寫或規劃新技能，或詢問技能結構、最佳實踐、SKILL.md 格式。
---
# 在 Cursor 中建立技能

本技能引導你建立有效的 Cursor Agent 技能。技能為 Markdown 檔案，教導 agent 執行特定任務：依團隊標準審查 PR、以偏好格式產生 commit 訊息、查詢資料庫結構，或任何專屬工作流程。

## 開始前：蒐集需求

建立技能前，向使用者蒐集：

1. **目的與範圍**：此技能要協助的具體任務或工作流程為何？
2. **存放位置**：個人技能（~/.cursor/skills/）還是專案技能（.cursor/skills/）？
3. **觸發情境**：何時應自動套用此技能？
4. **關鍵領域知識**：agent 需要哪些一般不會具備的專屬資訊？
5. **產出格式偏好**：是否有特定範本、格式或風格？
6. **既有模式**：是否有既有範例或慣例可依循？

### 從脈絡推斷

若有先前對話脈絡，可從討論內容推斷技能。可依工作流程、模式或領域知識建立技能。

### 蒐集額外資訊

若需釐清，請在有 AskQuestion 工具時使用，例如：
- 「此技能應存放在哪裡？」選項如 ["Personal (~/.cursor/skills/)", "Project (.cursor/skills/)"]
- 「此技能是否包含可執行腳本？」選項如 ["Yes", "No"]

若無該工具，則以對話方式詢問。

---

## 技能檔案結構

### 目錄配置

技能存放於內含 `SKILL.md` 的目錄：

```
skill-name/
├── SKILL.md              # 必填－主要指示
├── reference.md          # 選填－詳細文件
├── examples.md           # 選填－使用範例
└── scripts/              # 選填－工具腳本
    ├── validate.py
    └── helper.sh
```

### 存放位置

| 類型 | 路徑 | 範圍 |
|------|------|------|
| 個人 | ~/.cursor/skills/skill-name/ | 所有專案可用 |
| 專案 | .cursor/skills/skill-name/ | 與使用此儲存庫者共用 |

**重要**：切勿在 `~/.cursor/skills-cursor/` 建立技能。該目錄為 Cursor 內建技能專用，由系統自動管理。

### SKILL.md 結構

每個技能需有具 YAML 前置資料與 Markdown 內文的 `SKILL.md`：

```markdown
---
name: your-skill-name
description: Brief description of what this skill does and when to use it
---

# Your Skill Name

## Instructions
Clear, step-by-step guidance for the agent.

## Examples
Concrete examples of using this skill.
```

### 必填欄位

| 欄位 | 要求 | 用途 |
|-------|--------------|---------|
| `name` | 最多 64 字元，僅小寫字母/數字/連字號 | 技能唯一識別 |
| `description` | 最多 1024 字元，不可為空 | 協助 agent 判斷何時套用 |

---

## 撰寫有效的描述

描述對技能被發現**至關重要**，agent 依此決定是否套用。

### 描述最佳實踐

1. **以第三人稱撰寫**（描述會注入系統提示）：
   - ✅ 佳：「處理 Excel 檔案並產生報表」
   - ❌ 避免：「我可以幫你處理 Excel」
   - ❌ 避免：「你可以用這個來處理 Excel」

2. **具體並含觸發用語**：
   - ✅ 佳：「從 PDF 擷取文字與表格、填表、合併文件。於處理 PDF 或使用者提到 PDF、表單、文件擷取時使用。」
   - ❌ 模糊：「協助處理文件」

3. **同時包含「做什麼」與「何時用」**：
   - 做什麼：技能能力
   - 何時用：觸發情境

### 描述範例

```yaml
# PDF 處理
description: Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.

# Excel 分析
description: Analyze Excel spreadsheets, create pivot tables, generate charts. Use when analyzing Excel files, spreadsheets, tabular data, or .xlsx files.

# Git Commit 輔助
description: Generate descriptive commit messages by analyzing git diffs. Use when the user asks for help writing commit messages or reviewing staged changes.

# 程式碼審查
description: Review code for quality, security, and best practices following team standards. Use when reviewing pull requests, code changes, or when the user asks for a code review.
```

---

## 核心撰寫原則

### 1. 簡潔為上

脈絡視窗與對話歷史、其他技能、請求共用。每段資訊都要自問：agent 是否真的需要？能否假設 agent 已懂？這段是否值得佔用 token？

**佳（簡潔）**：只寫必要步驟與程式碼範例。**劣（冗長）**：從 PDF 格式定義開始長篇說明。

### 2. SKILL.md 控制在 500 行以內

為效能著想，主檔應簡潔，詳細內容用漸進揭露。

### 3. 漸進揭露

核心資訊放在 SKILL.md；詳細參考放在獨立檔案，需要時再讀取。參考僅一層深度，避免巢狀過深。

### 4. 設定適當自由度

依任務脆弱度選擇：
- **高**（文字指示）：多種可行做法、依脈絡而定，如程式碼審查指引
- **中**（偽碼/範本）：有偏好模式但可接受變化，如報表產生
- **低**（具體腳本）：操作易出錯、一致性重要，如資料庫遷移

---

## 常見模式

**範本模式**：提供產出格式範本。**範例模式**：產出品質依範例時，提供多組輸入/輸出範例。**工作流程模式**：以步驟與檢查清單拆解複雜操作。**條件工作流程**：依決策點引導（例如「建立新內容」→ 建立流程；「編輯既有內容」→ 編輯流程）。**回饋迴圈模式**：品質關鍵任務中，編輯後立即驗證，僅在通過後繼續。

---

## 工具腳本

預寫腳本優點：比產生程式碼穩定、省 token、省時間、使用一致。需註明 agent 應**執行**腳本（多數情況）還是**僅閱讀**參考。

---

## 應避免的反模式

1. **Windows 風格路徑**：用 `scripts/helper.py`，勿用 `scripts\helper.py`
2. **選項過多**：給一個預設與例外即可，勿列出一長串「可用 A 或 B 或 C…」
3. **時效性資訊**：勿寫「若在 2025 年 8 月前請用舊 API」；改為「現行方法」與「舊版（已棄用）」區塊
4. **術語不一致**：全文統一用同一詞（如只用「API 端點」不混用 URL/route/path）
5. **技能名稱過於籠統**：佳如 `processing-pdfs`；避免 `helper`、`utils`、`tools`

---

## 技能建立流程

### 階段一：探索－蒐集目的、存放位置、觸發情境、限制、既有範例

### 階段二：設計－草擬 name、撰寫第三人稱描述、規劃章節、判斷是否需要輔助檔案或腳本

### 階段三：實作－建立目錄、撰寫 SKILL.md（含 frontmatter）、必要時建立參考檔與腳本

### 階段四：驗證－確認 SKILL.md 未超過 500 行、描述具體含觸發用語、術語一致、檔案參考僅一層、可被發現與套用

---

## 完整範例

目錄：`code-review/SKILL.md`、`STANDARDS.md`、`examples.md`。SKILL.md 含 frontmatter（name: code-review，description 含「審查程式碼品質、安全性與可維護性…使用時機：審查 PR、檢視變更或使用者要求審查」）、Quick Start 步驟、Review Checklist、回饋格式（Critical/Suggestion/Nice to have）、Additional Resources 連結。

---

## 總結檢查清單

**核心品質**：描述具體含關鍵詞、含「做什麼」與「何時用」、第三人稱、SKILL.md 正文 500 行內、術語一致、範例具體。**結構**：檔案參考一層、漸進揭露得當、工作流程步驟清楚、無時效性資訊。**若含腳本**：腳本解決問題、套件已註明、錯誤處理明確、無 Windows 路徑。
