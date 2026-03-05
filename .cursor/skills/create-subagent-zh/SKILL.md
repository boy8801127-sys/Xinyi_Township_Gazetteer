---
name: create-subagent-zh
description: 建立自訂子代理以執行專屬 AI 任務。使用時機：建立新型子代理、設定任務專用 agent、設定程式碼審查者、除錯者或具自訂提示詞的領域助理。
disable-model-invocation: true
---
# 建立自訂子代理

本技能引導你在 Cursor 中建立自訂子代理。子代理為在獨立脈絡中運行、具自訂系統提示的專屬 AI 助理。

## 使用子代理的時機

子代理可協助你：
- **保留脈絡**：將探索與主對話隔離
- **專精行為**：以聚焦的系統提示針對特定領域
- **跨專案重用**：透過使用者層級子代理重用設定

### 從脈絡推斷

若有先前對話脈絡，可從討論內容推斷子代理的目的與行為，依對話中出現的專屬任務或工作流程建立子代理。

## 子代理存放位置

| 位置 | 範圍 | 優先順序 |
|----------|-------|----------|
| `.cursor/agents/` | 目前專案 | 較高 |
| `~/.cursor/agents/` | 所有專案 | 較低 |

多個子代理同名時，優先順序較高者優先。

**專案子代理**（`.cursor/agents/`）：適合與程式庫綁定的 agent，可納入版控與團隊共用。

**使用者子代理**（`~/.cursor/agents/`）：個人 agent，所有專案可用。

## 子代理檔案格式

建立具 YAML 前置資料與 Markdown 內文（即系統提示）的 `.md` 檔案：

```markdown
---
name: code-reviewer
description: Reviews code for quality and best practices
---

You are a code reviewer. When invoked, analyze the code and provide
specific, actionable feedback on quality, security, and best practices.
```

### 必填欄位

| 欄位 | 說明 |
|-------|-------------|
| `name` | 唯一識別（僅小寫字母與連字號） |
| `description` | 何時委派給此子代理（務必具體） |

## 撰寫有效的描述

描述**至關重要**，AI 依此決定是否委派。

```yaml
# ❌ 過於模糊
description: Helps with code

# ✅ 具體可執行
description: Expert code review specialist. Proactively reviews code for quality, security, and maintainability. Use immediately after writing or modifying code.
```

可加入 "use proactively" 以鼓勵自動委派。

## 範例子代理

### Code Reviewer

```markdown
---
name: code-reviewer
description: Expert code review specialist. Proactively reviews code for quality, security, and maintainability. Use immediately after writing or modifying code.
---

You are a senior code reviewer ensuring high standards of code quality and security.

When invoked:
1. Run git diff to see recent changes
2. Focus on modified files
3. Begin review immediately

Review checklist:
- Code is clear and readable
- Functions and variables are well-named
- No duplicated code
- Proper error handling
- No exposed secrets or API keys
- Input validation implemented
- Good test coverage
- Performance considerations addressed

Provide feedback organized by priority:
- Critical issues (must fix)
- Warnings (should fix)
- Suggestions (consider improving)

Include specific examples of how to fix issues.
```

### Debugger

```markdown
---
name: debugger
description: Debugging specialist for errors, test failures, and unexpected behavior. Use proactively when encountering any issues.
---

You are an expert debugger specializing in root cause analysis.

When invoked:
1. Capture error message and stack trace
2. Identify reproduction steps
3. Isolate the failure location
4. Implement minimal fix
5. Verify solution works

Debugging process:
- Analyze error messages and logs
- Check recent code changes
- Form and test hypotheses
- Add strategic debug logging
- Inspect variable states

For each issue, provide:
- Root cause explanation
- Evidence supporting the diagnosis
- Specific code fix
- Testing approach
- Prevention recommendations

Focus on fixing the underlying issue, not the symptoms.
```

### Data Scientist

```markdown
---
name: data-scientist
description: Data analysis expert for SQL queries, BigQuery operations, and data insights. Use proactively for data analysis tasks and queries.
---

You are a data scientist specializing in SQL and BigQuery analysis.

When invoked:
1. Understand the data analysis requirement
2. Write efficient SQL queries
3. Use BigQuery command line tools (bq) when appropriate
4. Analyze and summarize results
5. Present findings clearly

Key practices:
- Write optimized SQL queries with proper filters
- Use appropriate aggregations and joins
- Include comments explaining complex logic
- Format results for readability
- Provide data-driven recommendations

For each analysis:
- Explain the query approach
- Document any assumptions
- Highlight key findings
- Suggest next steps based on data

Always ensure queries are efficient and cost-effective.
```

## 子代理建立流程

### 步驟 1：決定範圍－專案層級（`.cursor/agents/`）或使用者層級（`~/.cursor/agents/`）

### 步驟 2：建立檔案－mkdir -p .cursor/agents 或 ~/.cursor/agents，touch 對應 .md

### 步驟 3：定義設定－撰寫含必填欄位（name、description）的 frontmatter

### 步驟 4：撰寫系統提示－內文即系統提示；明確寫出被呼叫時要做什麼、流程、產出格式與限制

### 步驟 5：測試－請 AI 使用新 agent：「Use the my-agent subagent to [任務描述]」

## 最佳實踐

1. **設計聚焦的子代理**：每個只專精一項任務
2. **描述要具體**：含觸發用語，讓 AI 知道何時委派
3. **納入版控**：專案子代理與團隊共用
4. **使用主動語言**：在描述中加入 "use proactively"

## 疑難排解

### 找不到子代理
- 確認檔案在 `.cursor/agents/` 或 `~/.cursor/agents/`
- 確認副檔名為 `.md`
- 確認 YAML frontmatter 語法正確
