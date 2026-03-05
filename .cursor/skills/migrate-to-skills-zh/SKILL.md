---
name: migrate-to-skills-zh
description: 將「智慧套用」的 Cursor 規則（.cursor/rules/*.mdc）與斜線指令（.cursor/commands/*.md）轉換為 Agent Skills 格式（.cursor/skills/）。使用時機：遷移規則或指令為技能、將 .mdc 規則轉為 SKILL.md 格式，或將指令整併至 skills 目錄。
disable-model-invocation: true
---
# 將規則與斜線指令遷移為技能

將 Cursor 規則（「智慧套用」）與斜線指令轉換為 Agent Skills 格式。

**關鍵：保留內文一字不差。勿修改、重新排版或「改進」－逐字複製。**

## 來源與目標位置

| 層級 | 來源 | 目標 |
|-------|--------|-------------|
| 專案 | `{workspaceFolder}/**/.cursor/rules/*.mdc`、`{workspaceFolder}/.cursor/commands/*.md` |
| 使用者 | `~/.cursor/commands/*.md` |

注意：
- 專案內的 Cursor 規則可能位於巢狀目錄，請徹底搜尋並使用 glob 模式。
- 略過 ~/.cursor/worktrees 內任何內容。
- 略過 ~/.cursor/skills-cursor。此目錄為 Cursor 內建技能專用，由系統自動管理。

## 要遷移的檔案判定

**規則**：若規則有 `description` 且**沒有** `globs`、**沒有** `alwaysApply: true`，則遷移。

**指令**：一律遷移－其為無 frontmatter 的純 Markdown。

## 轉換格式

### 規則：.mdc → SKILL.md

轉換前（.cursor/rules/my-rule.mdc）：含 `description`、`globs`、`alwaysApply: false` 的 frontmatter 與內文。

轉換後（.cursor/skills/my-rule/SKILL.md）：新增 `name` 欄位，移除 `globs`/`alwaysApply`，**內文完全保留**。

```markdown
---
name: my-rule
description: What this rule does
---
# Title
Body content...
```

### 指令：.md → SKILL.md

轉換前（.cursor/commands/commit.md）：純 Markdown，無 frontmatter。

轉換後（.cursor/skills/commit/SKILL.md）：新增 frontmatter，含 `name`（取自檔名）、`description`（由內容推斷）、`disable-model-invocation: true`，**內文完全保留**。

**說明**：`disable-model-invocation: true` 可避免模型自動呼叫此技能。斜線指令設計為由使用者透過 `/` 選單明確觸發，而非由模型自動建議。

## 注意事項

- `name` 僅能小寫與連字號
- `description` 對技能被發現至關重要
- 驗證遷移無誤後，可選擇刪除原始檔案

### 遷移規則（.mdc → SKILL.md）

1. 讀取規則檔
2. 從 frontmatter 擷取 `description`
3. 擷取內文（frontmatter 結尾 `---` 之後全部）
4. 建立技能目錄：`.cursor/skills/{skill-name}/`（skill name = 檔名去掉 .mdc）
5. 撰寫 `SKILL.md`，含新 frontmatter（`name`、`description`）與**與原文完全相同的內文**（保留所有空白、排版、程式碼區塊）
6. 刪除原始規則檔

### 遷移指令（.md → SKILL.md）

1. 讀取指令檔
2. 從第一個標題擷取描述（去掉 `#` 前綴）
3. 建立技能目錄：`.cursor/skills/{skill-name}/`（skill name = 檔名去掉 .md）
4. 撰寫 `SKILL.md`，含新 frontmatter（`name`、`description`、`disable-model-invocation: true`）、空行，以及**與原文完全相同的檔案內容**
5. 刪除原始指令檔

**關鍵：內文一字不差複製。勿重新排版、改錯字或「改進」任何內容。**

## 流程

若有 Task 工具可用：
勿自行讀取所有檔案，應委派子代理。你的工作是依檔案類別分派子代理並等候結果。

1. [ ] 若不存在則建立技能目錄（專案用 `.cursor/skills/`，使用者用 `~/.cursor/skills/`）
2. 並行分派三個 general purpose 子代理（勿用 explore），分別處理：專案規則（`{workspaceFolder}/**/.cursor/rules/*.mdc`）、使用者指令（`~/.cursor/commands/*.md`）、專案指令（`{workspaceFolder}/**/.cursor/commands/*.md`）：
   - [ ] 在給定模式中找出要遷移的檔案
   - [ ] 規則：檢查是否為「智慧套用」規則（有 `description`、無 `globs`、無 `alwaysApply: true`）。指令一律遷移。勿用終端機讀檔，使用 read 工具。
   - [ ] 列出要遷移的檔案；若為空則結束。
   - [ ] 對每個檔案：讀取後寫入新技能檔，**內文完全保留**。勿用終端機寫檔，使用 edit 工具。
   - [ ] 刪除原始檔案。勿用終端機刪除，使用 delete 工具。
   - [ ] 回傳已遷移的技能檔清單與原始路徑。
3. [ ] 等候所有子代理完成，向使用者彙總結果。重要：告知若欲復原遷移可請你協助。
4. [ ] 若使用者要求復原遷移，執行上述相反步驟還原原始檔案。

若無 Task 工具：
1. [ ] 若不存在則建立技能目錄
2. [ ] 在專案（`.cursor/`）與使用者（`~/.cursor/`）目錄中找出要遷移的檔案
3. [ ] 規則：檢查是否為「智慧套用」規則。指令一律遷移。勿用終端機讀檔，使用 read 工具。
4. [ ] 列出要遷移的檔案；若為空則結束。
5. [ ] 對每個檔案：讀取後寫入新技能檔，內文完全保留。勿用終端機寫檔，使用 edit 工具。
6. [ ] 刪除原始檔案。勿用終端機刪除，使用 delete 工具。
7. [ ] 向使用者彙總結果。重要：告知若欲復原遷移可請你協助。
8. [ ] 若使用者要求復原遷移，執行相反步驟還原原始檔案。
