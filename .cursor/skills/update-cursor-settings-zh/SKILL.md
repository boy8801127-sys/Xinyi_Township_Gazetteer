---
name: update-cursor-settings-zh
description: 修改 Cursor/VSCode 使用者設定（settings.json）。使用時機：變更編輯器設定、偏好、組態、主題、字型大小、tab 大小、儲存時格式化、自動儲存、快捷鍵或任何 settings.json 數值。
---
# 更新 Cursor 設定

本技能引導你修改 Cursor/VSCode 使用者設定。當你想變更編輯器設定、偏好、組態、主題、快捷鍵或任何 `settings.json` 數值時使用。

## 設定檔位置

| 作業系統 | 路徑 |
|----|------|
| macOS | ~/Library/Application Support/Cursor/User/settings.json |
| Linux | ~/.config/Cursor/User/settings.json |
| Windows | %APPDATA%\Cursor\User\settings.json |

## 修改前注意事項

1. **先讀取現有設定檔**以了解目前組態
2. **保留既有設定**－僅新增或修改使用者要求的項目
3. **寫入前驗證 JSON 語法**，避免破壞編輯器

## 修改設定

### 步驟 1：讀取目前設定

使用 Read 工具讀取上述路徑的 settings.json 目前內容。

### 步驟 2：識別要變更的設定

常見設定分類：
- **Editor**：`editor.fontSize`、`editor.tabSize`、`editor.wordWrap`、`editor.formatOnSave`
- **Workbench**：`workbench.colorTheme`、`workbench.iconTheme`、`workbench.sideBar.location`
- **Files**：`files.autoSave`、`files.exclude`、`files.associations`
- **Terminal**：`terminal.integrated.fontSize`、`terminal.integrated.shell.*`
- **Cursor 專用**：以 `cursor.` 或 `aipopup.` 為前綴的設定

### 步驟 3：更新設定

修改 settings.json 時：
1. 解析既有 JSON（注意註解－VSCode 設定支援含註解的 JSON）
2. 新增或更新所要求的設定
3. 保留其餘既有設定
4. 以適當格式（2 空格縮排）寫回

### 範例：變更字型大小

若使用者說「把字型調大」：

```json
{
  "editor.fontSize": 16
}
```

### 範例：啟用儲存時格式化

若使用者說「儲存時幫我格式化程式碼」：

```json
{
  "editor.formatOnSave": true
}
```

### 範例：變更主題

若使用者說「用深色主題」或「換主題」：

```json
{
  "workbench.colorTheme": "Default Dark Modern"
}
```

## 重要說明

1. **含註解的 JSON**：VSCode/Cursor 的 settings.json 支援註解（`//` 與 `/* */`）。讀取時注意可能有註解；寫入時盡量保留註解。

2. **可能需重新載入**：部分設定立即生效，部分需重新載入視窗或重啟 Cursor。若需重啟請告知使用者。

3. **備份**：重大變更時，可提醒使用者可在設定檔中用 Ctrl/Cmd+Z 復原，或若該檔有版控則還原變更。

4. **工作區與使用者設定**：
   - 使用者設定（本技能涵蓋）：套用於所有專案
   - 工作區設定（`.vscode/settings.json`）：僅套用於目前專案

5. **Commit 歸屬**：若使用者詢問 commit 歸屬，釐清是要改 **CLI agent** 還是 **IDE agent**。CLI agent 修改 `~/.cursor/cli-config.json`；IDE agent 由 **Cursor Settings > Agent > Attribution** 控制（非 settings.json）。

## 常見使用者請求對應設定

| 使用者請求 | 設定 |
|--------------|---------|
| 「字型大/小一點」 | `editor.fontSize` |
| 「改 tab 大小」 | `editor.tabSize` |
| 「儲存時格式化」 | `editor.formatOnSave` |
| 「自動換行」 | `editor.wordWrap` |
| 「換主題」 | `workbench.colorTheme` |
| 「隱藏小地圖」 | `editor.minimap.enabled` |
| 「自動儲存」 | `files.autoSave` |
| 「行號」 | `editor.lineNumbers` |
| 「括號配對」 | `editor.bracketPairColorization.enabled` |
| 「游標樣式」 | `editor.cursorStyle` |
| 「平滑捲動」 | `editor.smoothScrolling` |

## 流程

1. 讀取上述路徑的 settings.json
2. 解析 JSON 內容
3. 新增或修改所要求的設定
4. 將更新後的 JSON 寫回檔案
5. 告知使用者設定已變更，以及是否需要重新載入
