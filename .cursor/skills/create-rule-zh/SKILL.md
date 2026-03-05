---
name: create-rule-zh
description: 建立 Cursor 規則以提供持久化 AI 指引。使用時機：建立規則、訂定程式碼規範、專案慣例、檔案類型規則、建立 RULE.md，或詢問 .cursor/rules/、AGENTS.md。
---
# 建立 Cursor 規則

在 `.cursor/rules/` 建立專案規則，為 AI agent 提供持久化脈絡。

## 蒐集需求

建立規則前，先確認：

1. **目的**：此規則要約束或傳達什麼？
2. **範圍**：應一律套用，還是僅針對特定檔案？
3. **檔案模式**：若為檔案專用，要使用哪些 glob 模式？

### 從脈絡推斷

若對話中已有脈絡，可從討論內容推斷規則。若涵蓋多個主題或模式，可建立多條規則。若脈絡已足夠，勿重複詢問。

### 必問問題

若使用者未指定範圍，請問：
- 「此規則應一律套用，還是僅在處理特定檔案時套用？」

若使用者提到特定檔案但未給出具體模式，請問：
- 「此規則應套用到哪些檔案模式？」（例如 `**/*.ts`、`backend/**/*.py`）

務必釐清檔案模式。

若有 AskQuestion 工具，可用以有效蒐集上述資訊。

---

## 規則檔案格式

規則為 `.cursor/rules/` 下具 YAML 前置資料（frontmatter）的 `.mdc` 檔案：

```
.cursor/rules/
  typescript-standards.mdc
  react-patterns.mdc
  api-conventions.mdc
```

### 檔案結構

```markdown
---
description: Brief description of what this rule does
globs: **/*.ts  # File pattern for file-specific rules
alwaysApply: false  # Set to true if rule should always apply
---

# Rule Title

Your rule content here...
```

### 前置資料欄位

| 欄位 | 類型 | 說明 |
|-------|------|-------------|
| `description` | string | 規則用途（於規則選擇器顯示） |
| `globs` | string | 檔案模式－規則在符合檔案開啟時套用 |
| `alwaysApply` | boolean | 若為 true，則於每次對話套用 |

---

## 規則設定方式

### 一律套用

適用於應在每次對話都套用的通用標準：

```yaml
---
description: Core coding standards for the project
alwaysApply: true
---
```

### 僅套用於特定檔案

適用於僅在處理特定檔案類型時套用的規則：

```yaml
---
description: TypeScript conventions for this project
globs: **/*.ts
alwaysApply: false
---
```

---

## 最佳實踐

### 保持規則簡潔

- **50 行以內**：規則應簡短扼要
- **一則規則一個關注點**：將大型規則拆成多個聚焦小則
- **可執行**：寫得像清楚的內部文件
- **具體範例**：盡量提供具體修正範例

---

## 規則範例

### TypeScript 規範

```markdown
---
description: TypeScript coding standards
globs: **/*.ts
alwaysApply: false
---

# Error Handling

\`\`\`typescript
// ❌ BAD
try {
  await fetchData();
} catch (e) {}

// ✅ GOOD
try {
  await fetchData();
} catch (e) {
  logger.error('Failed to fetch', { error: e });
  throw new DataFetchError('Unable to retrieve data', { cause: e });
}
\`\`\`
```

### React 模式

```markdown
---
description: React component patterns
globs: **/*.tsx
alwaysApply: false
---

# React Patterns

- Use functional components
- Extract custom hooks for reusable logic
- Colocate styles with components
```

---

## 檢查清單

- [ ] 檔案為 `.mdc` 格式且位於 `.cursor/rules/`
- [ ] 前置資料設定正確
- [ ] 內容在 500 行以內
- [ ] 包含具體範例
