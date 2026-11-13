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

| 用戶端 | 狀態（2026-11-11、版本 0.7.0；另有註明日期者除外） |
|---|---|
| Claude Code — plugin（WSL；Windows 使用者建議這樣用） | 在 Linux（WSL）測過：用 `--plugin-dir` 從本機資料夾載入，只有一個 `pobg` server，已連線；`claude plugin validate --strict` 通過。從 GitHub 安裝：已在 macOS 測過（見下方）|
| Claude Desktop（Windows） | **2026-11-13 在應用程式內測過（0.10.0）**：`pobg` server 註冊在 `claude_desktop_config.json` 時，對話會呼叫工具（`data_status` 回報的是本機資料夾）。安裝程式（`install_desktop`，0.11.0）對真實設定檔的副本實際執行過，對真實設定檔只跑過檢查模式。更早：以腳本透過 Windows `uv.exe` 與 Python 3.12（系統字碼頁 950）用中文跑 MCP 對話 |
| 在 Claude Desktop 或 claude.ai 上傳 plugin（Customize → Plugins） | **拿不到工具**（2026-11-13 實測，0.10.0）：plugin 的檔案與 skill 會同步到雲端的隔離環境，但那裡不會啟動它的本機 MCP server，也連不到 poe2db。請用上面的 Claude Desktop 安裝方式 |
| MCP Inspector CLI（`npx @modelcontextprotocol/inspector --cli`） | 用十二個查詢與流派工具測過：`tools/list`、`prompts/list`、`tools/call` |
| Codex CLI（WSL，0.168.0） | **2026-11-13 測過（0.11.0）**：用 `codex mcp add` 加上 server，並把 `poe2-advisor`、`status`、`update` 三個 skill 資料夾複製到 `~/.codex/skills`。`pobg` 連上、18 個工具；查詢時讀了 skill、呼叫 `lookup_entity` 與 `get_gem` 並附 poe2db 連結；流派請求產生了完整的流派（117 個天賦節點，含 8 點昇華；14 件物品；5 個配置選項）與可匯入 PoB 的匯入碼。**匯入碼請用 Codex 存下的檔案，不要用終端機上顯示的**：請它印出來時，模型把 3,613 個字元的碼重打一遍，只對了約一半，PoB 會拒絕。PowerShell 與 cmd 上沒有測過。**plugin（0.12.0）**：從本機資料夾安裝到獨立的 Codex 設定資料夾，server 從 plugin 的資料夾啟動（18 個工具），skill 列為 `pobg:poe2-advisor`、`pobg:status`、`pobg:update`、`pobg:update-pob`。**在使用者的 Codex 從乾淨狀態安裝（2026-11-13，commit 4f9e637）**：先移除先前所有 POBG 相關設定（手動加的 server、複製的 skill、舊 plugin），再從乾淨的 clone 安裝：只有一支 `pobg` server，是 plugin 自己的，`data_dir` 在 `~/.codex/plugins/cache/pobg/pobg/0.12.0/data`；`$pobg:status` 讀了 skill 並呼叫 `data_status`；90 級流派請求走完整個流程（111 次工具呼叫），得到 3,576 字元的匯入碼，與 `export_pob` 回傳的完全相同，解碼後是完整的流派；`$pobg:update` 停在 Codex 對會寫入的 `update_data` 的核准；`update-pob --check` 可從 plugin 資料夾執行。（先前那次回報 0.12.0 的 `$pobg:status`，回答的是手動加的 server，不是 plugin 的）。**從 GitHub 安裝**：repo 仍是私人時，`codex plugin marketplace add GGaryyy/POBG` 與 SSH 網址都用這台電腦的 GitHub 權限裝到 0.12.0；其他人要等公開後。互動模式的 Codex 中，流派請求使用了 `pobg:poe2-advisor`，並自行把流派說明與匯入碼存成工作資料夾裡的檔案（這是 Codex 的做法，`export_pob` 不寫檔）；檔案裡的匯入碼可匯入 PoB |
| Claude Code（macOS） | **2026-11-13 從公開的 GitHub repo 安裝（0.12.0）**：README 的兩行一次輸入一行，安裝後可以使用。兩行一起貼上會失敗：Claude Code 會把它們當成同一個 marketplace 來源 |
| Codex CLI（macOS） | **2026-11-13 從公開的 GitHub repo 安裝（0.12.0）**：照 README 的兩行指令安裝，不需要其他步驟就能使用 |
| Cursor、VS Code、Gemini CLI | 未測試。下方設定依照 2026-11-11 讀到的各用戶端文件 |
| ChatGPT 桌面版（Windows） | **2026-11-13 在應用程式內測過（0.11.0）**：在 設定 → MCPs 加成自訂 STDIO server；問「躍擊 10 等的消耗是多少？」時呼叫了 `lookup_entity` 與 `get_gem`，回答了消耗並附 poe2db 連結。流派請求（「Lv90 傭兵 Tactician 擲彈流」）走完了整個流程：檢查過的寶石、天賦與裝備、`path_to`、來源清單，以及可匯入 PoB 0.23.1 的 `export_pob` 匯入碼。流派本身偏單薄（123 點只用 43 點、沒有昇華點、多個部位只有基底、沒有開啟配置選項），這是模型向工具要了什麼的問題，不是工具失敗。`status`、`update` 還沒試 |
| 網頁版 ChatGPT | 不支援：它只能透過 HTTPS 連遠端 MCP server |

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

把專案（[最新版本](https://github.com/GGaryyy/POBG/releases/latest)的 zip，或 clone）放到一個長期保留的資料夾，
再從那個資料夾註冊：

```
uv run --frozen --no-dev python -m src.tools.install_desktop            # 新增或更新 pobg server
uv run --frozen --no-dev python -m src.tools.install_desktop --check    # 只顯示會改什麼，不寫入
uv run --frozen --no-dev python -m src.tools.install_desktop --remove   # 移除
```

請先完全結束 Claude Desktop（系統匣的圖示也要結束）：它執行中會改寫自己的設定檔，可能把這次的變更蓋掉。
Windows 可以直接執行資料夾裡的 `install_claude_desktop.bat`，它會跑第一個指令（後面可接同樣的選項）。完成後再開啟 Claude Desktop。

安裝程式做的事：

- 找到 `claude_desktop_config.json`（Windows 在 `%APPDATA%\Claude`，也會找 Microsoft Store 版的資料夾；
  macOS 在 `~/Library/Application Support/Claude`；Linux 在 `~/.config/Claude`）。在別的位置時用 `--config <檔案>` 指定。
- 只寫入 `mcpServers.pobg` 這一項，內容是 `uv` 與這個資料夾的完整路徑。其他 server 與設定不會動，也不會被印出來。
  你自己加在 `pobg` 上的 `env` 會保留。
- 任何變更前先把檔案複製成 `claude_desktop_config.json.pobg-backup-<時間>`。不是合法 JSON、或在安裝過程中被改動的檔案會被拒絕，
  原樣保留。設定檔同時出現在兩個位置時（Store 版旁邊留有舊資料夾），會要求用 `--config` 指定。

若也想要指令（`/status`、`/update`、`/poe2-advisor`）與完整的流派說明，再把專案當成 plugin 上傳
（Customize → Plugins → 上傳含有 `.claude-plugin/` 的 zip）。本機 server 提供工具，plugin 提供 skill；兩者一起裝的組合已在
2026-11-13 實測。只上傳 plugin 只會帶進 skill：那裡的對話在雲端的隔離環境執行，不會啟動 plugin 的本機 MCP server。

要更新 POBG，把新版放進同一個資料夾，再執行一次安裝指令。資料則在對話裡更新（「更新技能寶石」）。

手動設定的做法：設定 → 開發者 → **Edit Config** 會開啟 `claude_desktop_config.json`：

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

如果 Claude Desktop 找不到 `uv`，在 `command` 填它的完整路徑（安裝程式會自動這樣做）。

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

## ChatGPT 桌面版

設定 → 搜尋「MCP」→ **MCPs** → 連接自訂 MCP，類型選 **STDIO**：

| 欄位 | 內容 |
|---|---|
| Name | `pobg` |
| Command to launch | uv 的完整路徑，例如 `C:\Users\you\.local\bin\uv.exe`（用 `where uv` 查詢） |
| Arguments | 每格一個：`run`、`--frozen`、`--no-dev`、`--directory`、POBG 的資料夾（例如 `C:\POBG`）、`python`、`-m`、`src.tools.mcp_server` |
| Environment variables | 不用填；只有資料夾同時給 WSL 使用時才加 `UV_PROJECT_ENVIRONMENT`（見上面 Claude Desktop 一節） |

路徑照原樣填，不用加引號，也不用把反斜線寫成兩個。儲存後開新對話直接提問。
這個設定存在 Codex CLI 也在用的 `~/.codex/config.toml`（下一節），所以兩種加法是同一份設定。

## Codex CLI

POBG 也是 Codex 的 plugin：它會啟動 MCP server 並帶來 skill，指令名稱和 Claude Code 一樣是 `pobg:` 開頭
（在 Codex 用 `$` 叫用：`$pobg:status`）。

```
codex plugin marketplace add GGaryyy/POBG
codex plugin add pobg@pobg
```

plugin 的檔案是 `.codex-plugin/plugin.json`、`.codex-plugin/mcp.json`（server，從 plugin 自己的資料夾啟動）與
`.agents/plugins/marketplace.json`。Codex 會把 plugin 複製到 `~/.codex/plugins/cache/`，第一次啟動時 uv 在那裡建立 Python 環境。

在上 GitHub 之前想用本機的版本測試，請從乾淨的 clone 安裝，不要直接用工作中的資料夾：Codex 會複製整個資料夾，
`.venv`、`output/` 也會一起過去，不管 `.gitignore` 怎麼寫。

```
git clone /path/to/POBG ~/pobg-codex-test
codex plugin marketplace add ~/pobg-codex-test
codex plugin add pobg@pobg
```

不裝 plugin、只加 server（`~/.codex/config.toml`）也能用，但就沒有 `pobg` 指令，流派說明只能靠 `build_workflow` 工具：


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
