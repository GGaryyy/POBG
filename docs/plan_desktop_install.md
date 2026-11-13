# 計畫：Claude Desktop 安裝（本機 MCP server，從 zip 或 clone）

狀態：2026-11-13 核准。沒有使用者的指示不 commit、不推送、不建立 Release、不公開 repo。

## 背景

2026-11-13 的實測（上傳 0.10.0 的 plugin zip 到你的工作區）：

| 情況 | 結果 |
|---|---|
| 桌面版一般聊天、網頁版，只靠上傳的 plugin | 工作階段跑在雲端隔離環境，plugin 自帶的本機 MCP server 不會啟動，只有 skill |
| 桌面版，`pobg` 註冊在 Claude Desktop 自己的設定檔 | 工具正常運作（`Data dir` 是本機資料夾） |

你的決定：MCP server 留在本機，由桌面版直接操作。README 的 plugin 安裝保留給 Claude Code；另外提供
「下載 zip 或 clone 專案 → 把本機 MCP server 裝進 Claude Desktop」。你選了：附一個安裝指令、用 GitHub Release 提供 zip。

目前要手動編輯 `claude_desktop_config.json`（`docs/clients.md`），JSON 格式、Windows 反斜線、`uv` 的完整路徑是最容易出錯的地方。

## 新使用者的流程（目標）

1. 安裝 uv 0.13.4 以上。
2. 從 GitHub Releases 下載 `pobg-<版本>.zip`，解壓到固定位置（例如 `C:\POBG`）。
3. 在資料夾裡執行安裝：Windows 點兩下 `install_claude_desktop.bat`；或任何系統執行
   `uv run --frozen --no-dev python -m src.tools.install_desktop`。
4. 完全結束 Claude Desktop 再重開，直接提問。

之後更新資料：在桌面版對話裡說「更新技能寶石」（server 在本機，有網路，`update` 可用）。
更新程式：下載新版 zip 解壓，再執行一次安裝。移除：加 `--remove`。

## 要新增或修改的檔案

| 檔案 | 內容 |
|---|---|
| `src/tools/install_desktop.py`（新） | 安裝指令，見下節 |
| `install_claude_desktop.bat`（新，根目錄） | Windows 用：執行上面的指令、顯示結果、等使用者按鍵。只是入口，沒有邏輯 |
| `tests/unit/test_install_desktop.py`（新） | 見「測試」 |
| `README.md`、`README.zh-TW.md` | 「快速開始」分成兩條路：Claude Code（plugin，不變）與 Claude Desktop（zip → 安裝指令）；說明上傳 plugin 在桌面版聊天與網頁版不會啟動工具 |
| `docs/clients.md`、`docs/clients.zh-TW.md` | Claude Desktop 一節改成以安裝指令為主，手動 JSON 留作備用；「測試過哪些」表更新為 2026-11-13 的結果 |
| `docs/data.md`、`docs/data.zh-TW.md` | 加「發佈」一小節：怎麼產生 Release 的 zip |
| `docs/flow/commands_charts.json` 等 | 不動（安裝不是 plugin 指令） |
| `ROADMAP.md`、`docs/changelog/CHANGELOG.md`、版本檔 | 版本 0.11.0（含先前未發佈的 `ninja` 改名與文件）；ROADMAP 的「一鍵安裝」項目註明已有安裝指令，`.mcpb` 仍待研究 |

## `install_desktop.py` 的設計

沿用 `src/tools/pob_update.py` 的做法：獨立的命令列程式、不是 MCP 工具、結果以 JSON 印在 stdout、
常數區塊置頂、錯誤不印 traceback。

```
python -m src.tools.install_desktop            # 安裝或更新 pobg 的註冊
python -m src.tools.install_desktop --check    # 只顯示會做什麼，不寫入
python -m src.tools.install_desktop --remove   # 移除 pobg 的註冊
選項：--config <設定檔路徑>   找不到設定檔時自行指定
```

步驟：

1. **找設定檔**：Windows `%APPDATA%\Claude\claude_desktop_config.json`（另檢查 Microsoft Store 版的位置）、
   macOS `~/Library/Application Support/Claude/…`、Linux `~/.config/Claude/…`。Claude 的資料夾不存在 →
   回報「找不到 Claude Desktop」，不建立任何東西。
2. **找 uv 的完整路徑**：`uv run` 會提供（環境變數 `UV`），否則用 `shutil.which`。找不到 → 報錯並說明。
3. **專案資料夾**：程式自己所在的 repo 根目錄（`src/tools/lookup.py` 的 `BASE_DIR`）的絕對路徑。
4. **寫入**：只動 `mcpServers.pobg` 這一項，內容為
   `<uv 完整路徑> run --frozen --no-dev --directory <資料夾> python -m src.tools.mcp_server`。
   其他 server 與其他設定原樣保留。
5. **安全措施**：
   - 寫入前把原檔複製成 `claude_desktop_config.json.pobg-backup-<時間>`；
   - 原檔不是合法 JSON → 不寫入、不覆蓋，回報錯誤；
   - 先寫暫存檔再取代（不會留下寫到一半的設定檔）；
   - 已經是相同內容 → 回報「已安裝」，不寫入、不備份；
   - 輸出只包含 `pobg` 這一項與檔案路徑，**不印出其他 server 的內容**（可能含金鑰）。
6. **輸出**：做了什麼（installed / updated / unchanged / removed）、設定檔與備份的位置、以及下一步
   「完全結束 Claude Desktop 再重新開啟」。

不連網、不讀寫 `data/`。

## 錯誤處理

| 情況 | 行為 |
|---|---|
| 找不到 Claude Desktop 的資料夾 | 報錯，提示用 `--config` 指定；不建立檔案 |
| 設定檔不存在但資料夾存在 | 建立只含 `pobg` 的新設定檔 |
| 設定檔不是合法 JSON、或 `mcpServers` 不是物件 | 報錯，檔案不變 |
| 找不到 uv | 報錯，附安裝網址 |
| 沒有寫入權限、磁碟錯誤 | 報錯，原檔不變（暫存檔清掉） |
| `--remove` 但沒有 `pobg` | 回報「沒有註冊」，不寫入 |
| 已有不同內容的 `pobg`（例如舊路徑） | 取代，並在輸出列出原本的指令 |

## Release 的 zip

- 內容與今天測試用的相同：`.claude-plugin/`、`skills/`、`src/`、`data/`、`pyproject.toml`、`uv.lock`、
  兩份 README、`LICENSE`、`install_claude_desktop.bat`；不含測試、文件、計畫與報告。約 3 MB。
- 用 `git archive --prefix=POBG/` 從版本標籤產生，解壓後是單一的 `POBG` 資料夾；指令寫進 `docs/data.md`。
- README 連到 `https://github.com/GGaryyy/POBG/releases/latest`。
- 建立標籤與 Release 是對外的動作：repo 公開後，等你說了我才做。

## 測試（離線，只用暫存資料夾）

`tests/unit/test_install_desktop.py`：

- 新設定檔：建立後只有 `pobg`，指令與參數正確；
- 既有設定檔：其他 server、其他頂層設定逐字保留；有備份檔且內容等於原檔；
- 重複執行：第二次回報 unchanged，沒有新的備份；
- 既有不同的 `pobg`：被取代，輸出含原指令；
- `--check`：檔案逐位元不變；`--remove`：只移除 `pobg`；沒有時不寫入；
- 壞掉的 JSON、`mcpServers` 型別不對：報錯且檔案不變；
- 找不到 Claude 資料夾、找不到 uv：報錯，不建立檔案；
- 含空白與反斜線的路徑：寫出的 JSON 讀回後相同；
- 三種作業系統的設定檔位置（以 monkeypatch 模擬）；
- 輸出不含其他 server 的內容。

實測：

- 對你真正的設定檔只跑 `--check`（唯讀）；
- 用設定檔的副本實際安裝一次，再以 Windows `uv.exe` 啟動寫入的指令，確認 server 起得來；
- **真正寫入你的 Claude Desktop 設定檔由你自己執行**（或你說了我才做），然後在桌面版問一題確認。

## 交付

測試 → `docs/reports/` 的測試報告與程式碼複查（這支程式會改使用者的設定檔，交給 `reviewer` 做一次獨立複查）→
CHANGELOG → 回報。

## 驗收

1. 在乾淨的資料夾解壓 zip、執行安裝指令後，Claude Desktop 重開就有 `pobg` 的工具，`Data dir` 是解壓的資料夾。
2. 安裝不會動到設定檔裡的其他 server；任何失敗都不改原檔；每次寫入前有備份。
3. README 讓 PoB 使用者照著做得完：兩條路各自的步驟、解壓後資料夾不能刪、怎麼更新與移除。
4. 全部測試、`ruff`、plugin 嚴格驗證、Windows 啟動檢查通過。

## 不在範圍內

- `.mcpb` 一鍵安裝包、命令列版的工具（網頁版用）、線上服務。
- 自動下載或自動更新 POBG 本身。
- 公開 repo、建立 Release（等你的指示）。
