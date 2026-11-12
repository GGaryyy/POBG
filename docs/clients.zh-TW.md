# 連接 MCP 用戶端

[English](clients.md) | **繁體中文**

POBG 是在本機執行的 **stdio** MCP server。每個用戶端都用同一個指令啟動它：

```
uv run --frozen --no-dev --directory /absolute/path/to/POBG python -m src.tools.mcp_server
```

- 必須安裝 `uv` 0.13.4 以上（[安裝說明](https://docs.astral.sh/uv/getting-started/installation/)；
  `uv self update` 可升級），且用戶端要找得到它。
  用戶端回報「command not found」時，把 `uv` 的完整路徑填進 `command`（macOS / Linux 用 `which uv`，Windows 用 `where uv` 查詢）。
- `--directory` 後面的路徑是你 clone 本 repo 的位置。Windows 上在 JSON 裡要用雙反斜線：`"C:\\Users\\you\\POBG"`。
- 第一次啟動會下載約 40 個套件（四個直接相依），所以比較久（網路快的話幾秒，慢的話幾分鐘）。若用戶端放棄等待，
  先在終端機執行一次該指令，等它停住不動時按 Ctrl+C 結束，再重新啟動用戶端。
- server 除了 MCP 訊息之外不會輸出到 stdout；記錄寫到 stderr。
- 每次對話的第一個工具呼叫約需一秒：要載入資料並在記憶體中重建知識圖（知識圖不存在 repo 裡）。

## 測試過哪些用戶端

| 用戶端 | 狀態（2026-11-11，版本 0.7.0） |
|---|---|
| Claude Code — plugin | 在 Linux（WSL）測過：用 `--plugin-dir` 從本機資料夾載入，只有一個 `pobg` server，已連線；`claude plugin validate --strict` 通過。從 GitHub 安裝待第一次公開釋出後確認 |
| Claude Desktop（Windows） | 測過啟動方式：以腳本透過 Windows `uv.exe` 與 Python 3.12（系統字碼頁 950）跑 MCP 對話，用中文呼叫查詢與流派工具、`data_status` 與試跑的 `update_data`。應用程式內測試：待進行 |
| MCP Inspector CLI（`npx @modelcontextprotocol/inspector --cli`） | 用十二個查詢與流派工具測過：`tools/list`、`prompts/list`、`tools/call` |
| Cursor、VS Code、Gemini CLI、Codex CLI | 未測試。下方設定依照 2026-11-11 讀到的各用戶端文件 |
| ChatGPT | 不支援：它只能透過 HTTPS 連遠端 MCP server |

歡迎回報其他用戶端的結果：請開 issue，註明用戶端名稱與版本。

## Claude Code

Plugin（server + `/pobg:poe2-advisor` skill）：

```
/plugin marketplace add GGaryyy/POBG
/plugin install pobg@pobg
```

plugin 會把 Python 環境放在 plugin 自己的資料夾裡。若是在 clone 下來的 repo 中工作，改從資料夾載入 plugin：
`claude --plugin-dir .`（repo 沒有專案層級的 `.mcp.json`，所以 server 不會被註冊兩次）。

## Claude Desktop

設定 → 開發者 → **Edit Config** 會開啟 `claude_desktop_config.json`：

- macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows：`%APPDATA%\Claude\claude_desktop_config.json`
- Linux：`~/.config/Claude/claude_desktop_config.json`

把 server 加在既有設定旁邊，然後完全結束 Claude Desktop 再重新開啟：

```json
{
  "mcpServers": {
    "pobg": {
      "command": "uv",
      "args": ["run", "--frozen", "--no-dev", "--directory", "C:\\Users\\you\\POBG",
               "python", "-m", "src.tools.mcp_server"]
    }
  }
}
```

server 的 stderr 會寫到 `mcp-server-pobg.log`，位置在 `%APPDATA%\Claude\logs`（Windows）、`~/Library/Logs/Claude`（macOS）
或 `~/.config/Claude/logs`（Linux）。

若同一個資料夾也會從 WSL 或其他作業系統使用，加上
`"env": { "UV_PROJECT_ENVIRONMENT": "C:\\Users\\you\\AppData\\Local\\pobg\\venv" }` 讓兩邊的環境分開。

## Cursor

`~/.cursor/mcp.json`（所有專案）或 `.cursor/mcp.json`（單一專案）：

```json
{
  "mcpServers": {
    "pobg": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--frozen", "--no-dev", "--directory", "/absolute/path/to/POBG",
               "python", "-m", "src.tools.mcp_server"]
    }
  }
}
```

## VS Code（GitHub Copilot）

工作區的 `.vscode/mcp.json`，或使用者設定檔的 `mcp.json`。注意最上層的鍵是 `servers`，不是 `mcpServers`：

```json
{
  "servers": {
    "pobg": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--frozen", "--no-dev", "--directory", "/absolute/path/to/POBG",
               "python", "-m", "src.tools.mcp_server"]
    }
  }
}
```

## Gemini CLI

`~/.gemini/settings.json`（使用者）或 `.gemini/settings.json`（專案）使用上面 Claude Desktop 一節的 `mcpServers` JSON。
或在終端機執行：

```bash
gemini mcp add -s user pobg uv run --frozen --no-dev --directory /absolute/path/to/POBG python -m src.tools.mcp_server
```

## Codex CLI

`~/.codex/config.toml`：

```toml
[mcp_servers.pobg]
command = "uv"
args = ["run", "--frozen", "--no-dev", "--directory", "/absolute/path/to/POBG", "python", "-m", "src.tools.mcp_server"]
```

或：`codex mcp add pobg -- uv run --frozen --no-dev --directory /absolute/path/to/POBG python -m src.tools.mcp_server`

## 其他 stdio 用戶端

使用最上方的指令。不用 uv 的話，任何裝有 `mcp>=2.3,<3`、`networkx`、`requests` 與 `beautifulsoup4` 的 Python 3.10 以上
都可以（測試也需要 3.10 以上）：以 repo 資料夾為工作目錄執行 `python -m src.tools.mcp_server`。

## server 提供給用戶端的功能

| 功能 | 說明 |
|---|---|
| 工具 | 十八個。名稱只用字母、數字與 `_`；說明都少於 1,024 個字元；輸入 schema 是扁平物件（字串、整數、布林、字串列表） |
| 標註 | 十五個工具是 `readOnlyHint: true`、`openWorldHint: false`。`data_status` 是唯讀但 `openWorldHint: true`（有選用的線上檢查）。`refresh_gem` 與 `update_data` 是 `readOnlyHint: false`、`destructiveHint: true`、`openWorldHint: true`：它們會從來源抓取並取代本機紀錄，用戶端應在執行前詢問 |
| Prompt | `build_guide(request, lang)`、`status()`、`update(scope, names)`。不支援 prompt 的用戶端可呼叫 `build_workflow` 工具取得流派步驟，並直接呼叫 `data_status` / `update_data` |
| Server 說明 | 初始化時送出的一段「如何使用這些工具」；有些用戶端會忽略它，所以才有 `build_workflow` |
| 語言 | 查詢與回答支援英文與繁體中文；`lang` 為 `en` 或 `zh-tw` |

以內附資料量測的最大回應（JSON 字元數）：

| 工具 | 一般 | 最大 |
|---|---|---|
| `get_gem` | 3,600（中位數） | 28,100 |
| `get_passive`、`explain_keyword` | 1,300 – 2,500 | 7,500 |
| `passives_with_stat` | 20,000（預設 `limit` 50） | 72,700（`limit` 100 加 `include_without_page`） |
| `gems_by`、`supports_for` | 11,000 – 12,500（預設 `limit` 50） | 45,700（`limit` 200） |
| `reference_builds` | 2,900（預設 `limit` 5） | 14,700（`limit` 50） |
| `get_item` | 1,000（中位數） | 1,500 |
| `items_by` | 7,700（一個類別）；加 `with_lines` 為 12,000（25 個護符） | 26,800（`limit` 100） |
| `modifiers_for` | 25,600（預設 `limit` 20 個族群） | 37,200（`limit` 100） |
| `verify_build` | 每顆寶石約 600、每個天賦 340、每條詞綴 320（`detail` "brief"：各約 150） | 含裝備的完整流派（18 顆寶石、22 個天賦、9 件裝備、54 條詞綴）：46,000，`detail` "brief" 為 22,000 |
| `path_to` | 11,000（三個 keystone） | 72,900（40 個目標） |
| `data_status`、`update_data` | 2,700 / 1,000 以下 | 數千 |

2026-11-11 量測的時間：`data_status` 本機 0.4 秒，加線上檢查 39 秒（19 個請求）；`update_data` 試跑 2–3 秒；
指定三顆寶石 10 秒（4 個請求）；`passives` 17 秒（7 個請求）。20 頁的寶石更新約需一分鐘，所以工具逾時較短的用戶端
應傳入較小的 `max_gems`。`requests` 計算的是頁數；回應伺服器錯誤的頁面最多嘗試三次。

會限制工具輸出量的用戶端（Claude Code 在約 10,000 token 以上會警告）用預設值即可；只在需要時才調高 `limit`。

## 確認是否正常

在新對話中問這些問題（共六項）。右欄是正確回答的樣子。

| 提問 | 預期 |
|---|---|
| 「躍擊的消耗和標籤是什麼？」（或 "What does Leap Slam cost and what are its tags?"） | 助理呼叫 `lookup_entity` 與 `get_gem`；回答引用消耗與標籤，並連到 `https://poe2db.tw/tw/Leap_Slam`（或 `/us/`） |
| 「哪些天賦有攻擊速度？」 | `passives_with_stat`；附 poe2db 連結的核心天賦列表，以及小天賦的數量 |
| 「解釋暴擊」 | `explain_keyword`；名詞解釋的內容與其 poe2db 連結 |
| 「女巫要點到 Blood Magic 和 Resolute Technique 需要幾點天賦？」 | `path_to`；對照 123 點上限的總點數，標明是近似值，並列出路線 |
| `status` 指令（或「poe2db 的資料多舊？」） | `data_status`；各類資料的筆數、抓取日期與天數表格；天梯快照標為較舊 |
| 「給我一個火系泰坦的流派」 | 呼叫 `verify_build`（通常先呼叫 `gems_by` / `supports_for`），再呼叫 `path_to`；回答結尾有 poe2db 連結的「來源」清單，捏造的名稱會被列為已移除 |

如果助理沒有呼叫任何工具就回答，表示 server 沒有連上：請檢查用戶端的 MCP／連接器列表與記錄檔。
