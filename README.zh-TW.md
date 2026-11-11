# poe2db-mcp

[English](README.md) | **繁體中文**

一個非官方的 [Model Context Protocol](https://modelcontextprotocol.io) server，讓 AI 助理查到正確的
**Path of Exile 2（流亡黯道 2）** 資料、標明每項事實的出處並加以解釋，支援英文與繁體中文。

資料是 [poe2db.tw](https://poe2db.tw)（寶石、天賦樹、名詞解釋）、
[PathOfBuilding-PoE2](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2) 天賦樹，以及一份
[poe.ninja](https://poe.ninja/poe2/builds) 天梯快照的本機副本。工具回傳的每筆資料都帶有來源網址與抓取日期，
模型引用的是紀錄本身，而不是憑記憶猜數字。

本專案與 Grinding Gear Games、poe2db.tw、PathOfBuilding、poe.ninja 均無隸屬關係。

## 可以問什麼

接上 server 之後，可以這樣問你的 AI 助理：

- 「躍擊 10 等的消耗是多少？有哪些輔助寶石可以搭配？」
- 「哪些天賦有攻擊速度？」
- 「解釋暴擊」
- 「女巫要點到 Blood Magic 和 Resolute Technique 需要幾點天賦？」
- 「給我一個火系泰坦的流派」：回答裡的每顆寶石與每個天賦都會與資料比對，不存在的名稱會被移除，
  回答結尾附上來源清單。

## 安裝

需求：`PATH` 上要有 [uv](https://docs.astral.sh/uv/getting-started/installation/)。第一次啟動會依
`uv.lock` 鎖定的版本建立 Python 環境：四個直接相依套件（`mcp`、`networkx`、`requests`、
`beautifulsoup4`），連同它們的相依共約 40 個套件。

**Claude Code**（plugin：MCP server 加上 `/poe2db:poe2-advisor` skill）

```
/plugin marketplace add GGaryyy/poe2db-mcp
/plugin install poe2db@poe2db-mcp
```

**其他 MCP 用戶端**（Claude Desktop、Cursor、VS Code、Gemini CLI、Codex CLI 等）：先 clone 本 repo，
再註冊一個執行下列指令的 stdio server：

```
uv run --frozen --no-dev --directory /absolute/path/to/poe2db-mcp python -m src.tools.mcp_server
```

多數用戶端的設定就是這段 JSON：

```json
{
  "mcpServers": {
    "poe2db": {
      "command": "uv",
      "args": ["run", "--frozen", "--no-dev", "--directory", "/absolute/path/to/poe2db-mcp",
               "python", "-m", "src.tools.mcp_server"]
    }
  }
}
```

各用戶端的設定檔位置與格式、哪些用戶端實際測過、以及五個用來確認是否正常的提問，請看
**[docs/clients.md](docs/clients.md)**（英文）。

不支援 ChatGPT：它只能連接遠端 MCP server，而本專案是在本機以 stdio 執行。

## 指令

有兩個指令可以直接在 AI 用戶端裡維護資料。在 Claude Code 中它們是 plugin 的 skill；其他用戶端則是
`poe2db` server 提供的 MCP prompt（Claude Desktop 的「+」選單、VS Code 的 `/poe2db.status`、
Gemini CLI 的斜線指令）。

| 指令 | Claude Code | 做什麼 |
|---|---|---|
| status | `/poe2db:status` | 列出每類資料有幾筆、何時抓的、已經多久。需要時可再檢查線上網站（約 19 個請求）：頁面是否還能解析、天賦樹有沒有新版 |
| update | `/poe2db:update <範圍> [名稱]` | 重新抓取**一類**資料。先列出會抓哪些，再實際更新 |
| advisor | `/poe2db:poe2-advisor` | 不是資料指令：它是 Claude Code 回答 PoE2 問題與撰寫有出處流派時遵循的說明，會自動套用 |

`update` 一定要指定範圍，沒有「全部更新」：

| 範圍 | 抓什麼 | 每次呼叫的請求數 |
|---|---|---|
| `skill_gems`、`spirit_gems`、`support_gems` | 列表頁，然後只抓新增的、列表上有變動的、你指定名稱的、或超過 N 天沒更新的寶石 | 1 + 最多 20 顆（上限 40）；重複呼叫直到沒有剩餘 |
| `passives` | PathOfBuilding-PoE2 的天賦樹、poe2db 的兩個天賦樹資料檔與四個列表頁；並重建屬性索引 | 7 |

範例：`/poe2db:update skill_gems`、`/poe2db:update support_gems Fire Attunement, Brutality I`、
「更新超過 30 天的技能寶石」。

注意事項：

- 只改數值的平衡改版不會改變列表頁，所以單純的 update 會找不到要更新的項目。請指定改版公告提到的寶石名稱，
  或要求更新超過 N 天的寶石。
- 若頁面已無法解析，update 會停止，不寫入任何東西。單一頁面下載失敗則列為略過，下次 update 會再抓。
- 15 分鐘內抓過的寶石，在指定名稱或要求更新舊寶石時不會再抓一次，所以重複下同一個指令不會連續重抓同一頁。
- poe2db 的技能寶石列表也包含所有精神寶石。這類寶石只存一份，歸在精神寶石，所以要用 `spirit_gems` 更新。
- 同一個資料夾一次只會有一個 update 在跑，兩個用戶端共用同一個資料夾時也一樣。本機還沒有檔案的資料類別，
  第一次要在終端機完整抓取。
- 名詞解釋與天梯快照沒有指令可用（status 會說明原因）；完整重抓寶石與名詞解釋要在終端機執行，見「更新資料」。
- 天賦樹有新*版本*時 status 會回報，但 `update` 不會自動採用；那需要本專案釋出新版。
- update 改的是 server 執行所在的那份 `data/`。以 plugin 安裝時，plugin 更新會把它取代。

## 工具

| 工具 | 回答什麼 |
|---|---|
| `lookup_entity` | 名稱（英文／繁中）→ 實體、種類、兩個 poe2db 網址 |
| `get_gem`、`get_passive`、`explain_keyword` | 單筆紀錄與其來源 |
| `passives_with_stat` | 哪些天賦提供某個屬性 |
| `gems_by` | 依標籤、階級、職業、武器、種類或關鍵字篩選寶石 |
| `supports_for` | 可以輔助某技能的所有輔助寶石 |
| `reference_builds` | 天梯角色在用什麼（職業、主技能、排名、寶石、keystone；不含角色名稱） |
| `verify_build` | 檢查流派草稿裡的名稱；回傳事實、被移除的名稱與排好的來源清單 |
| `path_to` | 從職業起點點到目標天賦要依序點哪些節點；對照 123 / 8 點上限，並加總整條路線的屬性（近似路線） |
| `build_workflow` | 有出處的流派回答流程，給不支援 MCP prompt 的用戶端使用 |
| `refresh_gem` | 重新抓取 poe2db 上的一顆寶石頁面並取代本機紀錄 |
| `data_status` | 本機資料有哪些、多舊；需要時可檢查線上網站 |
| `update_data` | 重新抓取一類資料（必須指定範圍），每次呼叫的頁數有上限 |

Prompt：`build_guide`（流派流程）、`status` 與 `update`（上面的指令）。只有 `refresh_gem` 與
`update_data` 會變更資料；其餘十二個工具都標示為唯讀，其中只有 `data_status` 在被要求檢查線上網站時會連網。

## 資料來源與使用範圍

確切的網址樣式以 [`src/catalog/poe2db_sources.json`](src/catalog/poe2db_sources.json) 為準；下表是該檔案與
`src/fetch_poe_ninja_builds.py` 的摘要。沒有任何排程抓取：只有在有人執行蒐集程式或 `update` 指令時才會抓，
通常在遊戲改版之後。server 執行期間除非呼叫 `refresh_gem`、`update_data` 或 `data_status` 的線上檢查，
否則不會發出任何網路請求。

| 來源 | 網址 | 用到哪些部分 | 抓取範圍與頻率 |
|---|---|---|---|
| poe2db.tw 英文頁面 | `https://poe2db.tw/us/{slug}`：列表頁 `Skill_Gems`、`Spirit_Gems`、`Support_Gems`、`Keystone`、`Notable`，以及每顆寶石各一頁 | 寶石名稱、階級、標籤、消耗、需求、各等級數值表、品質、隱藏屬性、可搭配的輔助；keystone／notable 卡片（屬性文字、名詞連結） | 完整抓取時 5 個列表頁加 1,012 個寶石頁（技能 347、精神 53、輔助 612），每頁間隔 0.8 秒。更新時只抓 3 個寶石列表與有變動的寶石。`refresh_gem` 依要求抓 1 頁 |
| poe2db.tw 中文頁面 | `https://poe2db.tw/tw/{slug}`：同樣五個列表頁 | 寶石、keystone、notable 的繁體中文名稱 | 5 頁，存在本機快取；刪除快取後才會重抓 |
| poe2db hover 片段 | `https://cdn.poe2db.tw/cache2/{lang}/Poe_Data_KeywordPopups_hover/{hash}` (`lang` = `us` / `tw`) 與 `…/Poe_Data_GemEffects_hover/{hash}` | 名詞解釋（357 個名詞，英文與中文）；寶石 hover 只用來找中文的名詞連結 | 每個約 1.2 KB，間隔 0.3 秒，重建名詞解釋時才抓 |
| poe2db 天賦樹資料 | `https://poe2db.tw/data/passive-skill-tree/4.5/data_us.json` 與 `data_tw.json`（版本號取自 `https://poe2db.tw/tw/passive-skill-tree/` 及其在 `cdn.poe2db.tw/js/` 的 script） | 每個天賦節點的中文名稱與屬性文字、職業與昇華名稱、點數上限 | 重建天賦樹時抓 2 個檔案；檢視頁與 script 只在 probe 檢查新版本時讀取 |
| PathOfBuilding-PoE2 | `https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/src/TreeData/0_5/tree.json`（probe 另會列出 `https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/contents/src/TreeData?ref=dev`） | 天賦樹結構：所有節點、連線、名稱、屬性、keystone／notable 標記、職業起點、昇華、座標 | 重建天賦樹時抓 1 個檔案 |
| poe.ninja | `https://poe.ninja/poe2/api/data/index-state`、`https://poe.ninja/poe2/api/builds/{version}/search`、`https://poe.ninja/poe2/api/builds/dictionary/{hash}` | 天梯角色的職業、等級、主技能、寶石、keystone、聯盟、排名。角色名稱與帳號名稱在寫入前就丟棄 | 2026-03-04 抓的一份快照，共 588 個角色，聯盟為「Fate of the Vaal」（18 個請求，間隔 0.8 秒）。之後沒有再更新，原因見下 |

請求方式：

- 對 poe2db 與 GitHub 的請求會以
  `poe2db-mcp/0.7 (+https://github.com/GGaryyy/poe2db-mcp; research scraper)` 表明身分，每個頁面或檔案
  請求前等待 0.8 秒（hover 片段 0.3 秒），最多嘗試三次。`refresh_gem` 同樣等待 0.8 秒，一次只發一個請求。
- poe2db 的 `robots.txt` 只禁止 `/*/marked` 與 `/*/markdown_history`，兩者都不會被請求。單一天賦節點頁面
  （每頁 1.2 MB）刻意不抓。
- poe.ninja 的抓取程式讀的是 poe.ninja 網站自己使用的 JSON／protobuf 端點，那不是有文件的公開 API。它送出同樣
  表明身分的 `User-Agent`、間隔 0.8 秒，poe.ninja 在 2026-11-11 接受了這樣的請求。不過該站的回應格式已經改變，
  抓取程式目前讀不到任何資料；在解析器更新之前，這份（來自較早聯盟的）快照無法更新。
- 本 repo 內的快照：寶石與名詞解釋抓於 2026-11-10，天賦樹 `0_5`（poe2db 天賦樹資料 `4.5`），天梯
  2026-03-04。工具回傳的每筆紀錄都會註明自己的 `fetched_at`。

如果你是上述網站的維護者，希望本專案調整使用資料的方式，請開 issue。

## 更新資料

平常請用上面的 `status` 與 `update` 指令。下面的終端機做法用於第一次完整抓取、名詞解釋，以及開發蒐集程式時。

```bash
uv sync                                           # 只需一次：把 pytest 與 ruff 裝進 .venv
uv run python -m src.catalog.probe                # poe2db 的結構是否仍符合 catalog 的描述？
uv run python -m src.scrapers.collect_gems --kind all --changed-only   # 3 個列表頁 + 有變動的寶石
uv run python -m src.scrapers.collect_passives && uv run python -m src.scrapers.collect_glossary
uv run python -m src.catalog.entity_index build   # 雙語名稱索引（讀取寶石、天賦、名詞解釋）
uv run python -m src.kg.stats && uv run python -m src.kg.build_graph
```

完整抓取寶石（`collect_gems --kind all`，約 1,000 頁）只在第一次執行或 poe2db 改版面時需要。
頁面快取與 probe 指標寫到 `output/`（不進版控）。

## 開發

```bash
uv sync
uv run pytest            # 離線，只用合成的測試資料
uv run ruff check .
```

目錄：`src/catalog/`（來源目錄、probe、實體索引）、`src/scrapers/`（蒐集程式）、`src/kg/`（屬性索引、
知識圖）、`src/tools/`（查詢服務、流派工具、天賦路徑、資料狀態與更新、MCP server）、`skills/` 與 `.claude-plugin/`
（Claude Code plugin）、`data/`（蒐集到的資料）、`docs/`（用戶端說明、流程圖、changelog）。
後續規劃見 `ROADMAP.md`。

## 限制

- 資料是快照。平衡改版會改數字；請看 `fetched_at`（或執行 `status`），必要時用 `update`、`refresh_gem` 或蒐集程式。
- 天梯快照來自較早的聯盟，目前無法更新。
- `refresh_gem` 與 `update` 更新的是 server 執行所在的那份 `data/`。以 plugin 安裝時那是 plugin 自己的資料夾，plugin
  更新時會被取代；在 clone 下來的 repo 裡則會變成 git 中已修改的檔案。
- `path_to` 給的是夠好的路線，不保證最短，也不計算武器組天賦點與珠寶。
- `verify_build` 只檢查名稱是否存在並回傳其事實，不判斷流派強不強。
- 不包含裝備、傳奇物品、製作與終局內容。

## 授權

**程式碼**以 MIT License 釋出（見 `LICENSE`）。

`data/` 內的**資料**不適用 MIT：

- Path of Exile 2 的內容屬於 Grinding Gear Games。
- poe2db.tw 的內容依照 poe2db 在其 [General disclaimer](https://poe2db.tw/us/General_disclaimer)
  頁面的聲明使用（2026-11-11 讀取）：「Wikis Content is available under CC BY-NC-SA 3.0 unless
  otherwise noted.」也就是要標示出處、不得商業使用，衍生資料須以相同授權分享。每筆紀錄都保留 poe2db 來源網址作為出處標示。
- 天賦樹結構取自 PathOfBuilding-PoE2（MIT）。
- 天梯快照取自 poe.ninja，不保存角色或帳號名稱。

若要再利用這些資料，請遵循上述條款而非 MIT。本專案與上述各方無隸屬關係，也未獲其背書。
