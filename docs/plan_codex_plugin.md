# 計畫：Codex plugin，讓兩邊的用法一致

狀態：2026-11-13 核准。沒有使用者的指示不 commit、不推送、不公開 repo。

## 背景

你要的體驗（2026-11-13）：Claude Code 和 Codex 都是「**安裝 plugin，由 MCP 驅動**」；平常直接問問題，
要更新或下指令時用 **`pobg` 前綴**。不要因為用戶端不同而有不同的問法。

目前 Codex 的做法是手動 `codex mcp add` 加上複製三個 skill 資料夾。這樣裝出來的 skill 沒有 `pobg` 前綴、
`update-pob` 不能用、步驟也和 Claude Code 不同。

## 已查到的事實（來自你電腦上的 Codex 0.168.0 與它內建的 plugin-creator）

| 項目 | Claude Code | Codex |
|---|---|---|
| 登記來源 | `/plugin marketplace add GGaryyy/POBG` | `codex plugin marketplace add GGaryyy/POBG`（接受 `owner/repo`、Git 網址或本機路徑） |
| 安裝 | `/plugin install pobg@pobg` | `codex plugin add pobg@pobg` |
| plugin 資訊檔 | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json`，以 `"skills": "./skills/"`、`"mcpServers": "<檔案路徑>"` 指向內容 |
| marketplace 檔 | `.claude-plugin/marketplace.json` | `.agents/plugins/marketplace.json` |
| skill | `skills/<名稱>/SKILL.md` | 相同格式；今天複製過去的三個都能讀 |
| 本機 MCP server | 寫在 plugin.json 裡 | 寫在另一個 JSON 檔（內建 plugin 用 `.mcp.json`，路徑相對於 plugin 根目錄） |

所以同一個 repo 可以同時是兩邊的 plugin，`skills/` 共用一份。

## 還不知道、必須先實測的事（第一步）

這些查不到文件，會決定後面怎麼寫，所以先用本機路徑裝一次來確認：

1. **指令前綴的實際樣子**：plugin 的 skill 在 Codex 裡怎麼叫用（`pobg:status`、`$pobg:status` 或別的寫法）。
   這是你最在意的一點。
2. **MCP 設定檔能不能放在 `.codex-plugin/` 裡**。不能放在 repo 根目錄的 `.mcp.json`：Claude Code 會把它當成
   專案的 MCP 設定，造成同一支 server 被註冊兩次（現有測試 `test_the_plugin_is_the_only_place_that_registers_the_server` 就是在防這個）。
3. **plugin 根目錄怎麼表示**：相對路徑加 `cwd`，還是 `${PLUGIN_ROOT}` 這類變數。
4. **Python 環境放哪裡**：Claude 用 `${CLAUDE_PLUGIN_DATA}/venv`；Codex 的 plugin 快取資料夾能不能寫入 `.venv`。
5. **skill 開頭的 Claude 專用欄位**（`argument-hint`、`disable-model-invocation`）：Codex 是忽略還是報錯；
   `update` 和 `update-pob` 在 Codex 是否仍只能由使用者啟動。
6. **skill 內文的變數**：`update-pob` 用了 `${CLAUDE_PLUGIN_ROOT}`，Codex 不會代換。

實測方式：在 scratchpad 複製一份 repo，加上草稿的 `.codex-plugin/` 與 `.agents/`，用
`codex plugin marketplace add <本機路徑>` 與 `codex plugin add` 安裝到 **WSL 的 Codex**，看 `/mcp`、
指令清單與一次查詢。測完用 `codex plugin remove` 與 `codex plugin marketplace remove` 移除。
這會動到你 WSL 的 `~/.codex` 設定（新增再移除一個 plugin 與 marketplace），核准本計畫即表示同意這一步。

**第一步的結果我會先回報給你**，特別是前綴的寫法，再繼續後面的步驟。如果 Codex 的前綴和 Claude 的
`/pobg:` 無法做到一樣，由你決定要統一成哪一種。

## 要新增或修改的檔案（依第一步結果微調）

| 檔案 | 內容 |
|---|---|
| `.codex-plugin/plugin.json`（新） | 名稱 `pobg`、版本、說明、`interface`（顯示名稱、30 字元內的短說明、類別、預設提問）、`skills`、`mcpServers` |
| `.codex-plugin/mcp.json`（新，位置依實測） | `pobg` server：`uv run --frozen --no-dev --directory <plugin 根目錄> python -m src.tools.mcp_server` |
| `.agents/plugins/marketplace.json`（新） | marketplace `pobg`，列出 plugin `pobg`，來源為 repo 本身 |
| `skills/update-pob/SKILL.md` | 指令不再依賴 Claude 專用變數，兩邊都能執行（寫法依實測） |
| `skills/*/SKILL.md` | 文中提到指令的地方（`/pobg:update` 等）改成兩邊都成立的說法 |
| `tests/unit/test_plugin_manifest.py` | 兩份資訊檔的名稱與版本一致；Codex 的 MCP 指令與 Claude 的相同；repo 根目錄仍沒有 `.mcp.json`；marketplace 檔列出 `pobg` |
| `README.md`、`README.zh-TW.md` | Codex 一節改成兩行安裝指令，和 Claude Code 並列；「指令」一節寫出兩邊的 `pobg` 前綴用法；移除手動複製 skill 的說明 |
| `docs/clients*.md`、`docs/data*.md`（版本檔清單）、`ROADMAP.md`、CHANGELOG、版本號 | 對應更新；版本 0.12.0 |

Release 的 zip 也要包含 `.codex-plugin/` 與 `.agents/`（`docs/data.md` 的打包指令）。

## 測試

- 單元測試：上表 `test_plugin_manifest.py` 的新檢查；全部既有測試、`ruff`、`claude plugin validate --strict`
  仍要通過（確認新增的檔案沒有破壞 Claude 這邊）。
- 實測（WSL 的 Codex，從本機路徑安裝）：
  - `/mcp` 顯示 `pobg` 連上、18 個工具；
  - 用 `pobg` 前綴執行 status 與 update（預覽模式）；
  - 問一題查詢、一題流派，匯入碼的檔案可匯入 PoB；
  - Claude Code 從同一個資料夾載入（`--plugin-dir`）仍只有一支 `pobg` server。
- 從 GitHub 安裝（`owner/repo`）要等 repo 公開後才能測，列入公開後的清單。

## 交付

測試 → 測試報告與複查報告（`docs/reports/`）→ CHANGELOG → 回報。改動是設定檔與文件為主，不另外找獨立複查。

## 驗收

1. Codex 用兩行指令裝好後，不用再手動加 server 或複製 skill。
2. 兩邊都能直接問問題；下指令時用同一套 `pobg` 前綴的寫法（確切寫法以第一步的實測為準，並經你確認）。
3. Claude Code 這邊的行為不變：一支 server、四個指令、嚴格驗證通過。
4. README 的 Claude Code 與 Codex 兩節結構相同。

## 不在範圍內

- ChatGPT 桌面版、Claude Desktop 的安裝方式（維持現狀，之後再測）。
- 上架到 OpenAI 的公開 plugin 目錄。
- 匯入碼被模型重打出錯的問題（你已決定先不處理）。
- 公開 repo、建立 Release。
