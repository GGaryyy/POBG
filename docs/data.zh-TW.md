# 資料：來源、更新與開發

[English](data.md) | **繁體中文**

POBG 的資料從哪裡來、怎麼抓取與保持更新，以及如何開發。給玩家的概覽在 [README](../README.zh-TW.md)。

## 指令

有兩個指令可以直接在 AI 用戶端裡維護資料。在 Claude Code 中它們是 plugin 的 skill；其他用戶端則是 `pobg` server 提供的
MCP prompt（Claude Desktop 的「+」選單、VS Code 的 `/pobg.status`、Gemini CLI 的斜線指令）。另有一個指令用來更新你的
Path of Building。

| 指令 | Claude Code | 做什麼 |
|---|---|---|
| status | `/pobg:status` | 列出每類資料有幾筆、何時抓的、已經多久。需要時可再檢查線上網站（約 19 個請求）：頁面是否還能解析、天賦樹有沒有新版 |
| update | `/pobg:update <範圍> [名稱]` | 重新抓取**一類**資料。先列出會抓哪些，再實際更新 |
| update-pob | `/pobg:update-pob <資料夾>` | 把你的 Path of Building（PoE2，單獨安裝或放在 PoeCharm2 資料夾中）更新到最新版。先比對版本，你同意後才下載到舊資料夾旁邊的**新資料夾** |

`update` 一定要指定範圍，沒有「全部更新」：

| 範圍 | 抓什麼 | 每次呼叫的請求數 |
|---|---|---|
| `skill_gems`、`spirit_gems`、`support_gems` | 列表頁，然後只抓新增的、列表上有變動的、你指定名稱的、或超過 N 天沒更新的寶石 | 1 + 最多 20 顆（上限 40）；重複呼叫直到沒有剩餘 |
| `passives` | PathOfBuilding-PoE2 的天賦樹與任務獎勵（匯入碼用的 PoB 等級表與精魂獎勵）、poe2db 的兩個天賦樹資料檔與四個列表頁；並重建屬性索引 | 8 |
| `items` | 69 個裝備類別頁（中英；裝備、藥劑、護符、珠寶）上的基底、傳奇與詞綴；加上類別名稱（`Bows`、`Body Armours`）就只更新那幾類 | 每次呼叫最多 20 個請求（即 10 個類別頁的中英兩版，每頁約 600 KB），總共 138 個請求；重複呼叫直到完成，全部抓完並通過檢查才一次寫入 |
| `glossary` | 所有名詞解釋（英文與中文的 hover 片段），透過列表頁與少數寶石頁找到 | 每次呼叫最多 50 個（一分鐘內），總共約 750 個；重複呼叫直到完成，全部抓完才一次寫入 |
| `ninja` | poe.ninja 目前聯盟的新快照：職業、等級、技能、keystone。不保留角色或帳號名稱 | 最多 14 |

範例：`/pobg:update skill_gems`、`/pobg:update support_gems Fire Attunement, Brutality I`、`/pobg:update items Bows`、
「更新超過 30 天的技能寶石」。

注意事項：

- 只改數值的平衡改版不會改變列表頁，所以單純的 update 會找不到要更新的項目。請指定改版公告提到的寶石名稱，
  或要求更新超過 N 天的寶石。
- 若頁面已無法解析，update 會停止，不寫入任何東西。單一頁面下載失敗則列為略過，下次 update 會再抓。
- 15 分鐘內抓過的寶石，在指定名稱或要求更新舊寶石時不會再抓一次，所以重複下同一個指令不會連續重抓同一頁。
- poe2db 的技能寶石列表也包含所有精神寶石。這類寶石只存一份，歸在精神寶石，所以要用 `spirit_gems` 更新。
- 同一個資料夾一次只會有一個 update 在跑，兩個用戶端共用同一個資料夾時也一樣。本機還沒有檔案的資料類別，
  第一次要在終端機完整抓取（見下方）。
- 名詞解釋與裝備的更新會把進度暫存在 `output/cache/` 30 分鐘，中斷後會接續而不是重來。抓不到的名詞保留原本的內容。
- 天賦樹有新*版本*時 status 會回報，但 `update` 不會自動採用；那需要本專案釋出新版。
- `refresh_gem` 與 `update` 更新的是 server 執行所在的那份 `data/`。以 plugin 安裝時那是 plugin 自己的資料夾，plugin
  更新時會被取代；在 clone 下來的 repo 裡則會變成 git 中已修改的檔案。

### 更新 Path of Building

`update-pob` 只是 Claude Code 的 skill。在其他用戶端或自己手動執行時，在本資料夾跑同一支程式：

```
uv run python -m src.tools.pob_update --dir "G:\POB\poe2\PoeCharm2-20250410" --check   # 只比對版本
uv run python -m src.tools.pob_update --dir "G:\POB\poe2\PoeCharm2-20250410"           # 更新
```

它會下載 Path of Building 的正式版檔案（約 380 MB），並與 GitHub 公布的 SHA-256 核對；PoeCharm2 資料夾還會
下載 PoeCharm2 最新一次提交（沒有公布的雜湊可核對）。存過的 build 與 PoeCharm2 的語言設定會複製過去；
`Settings.xml` 不會，因為裡面有帳號登入資訊，所以要重新登入。舊資料夾不會被修改或刪除。

## 資料來源與使用範圍

確切的網址樣式以 [`src/catalog/poe2db_sources.json`](../src/catalog/poe2db_sources.json) 為準；下表是該檔案與
`src/fetch_poe_ninja_builds.py` 的摘要。沒有任何排程抓取：只有在有人執行蒐集程式或 `update` 指令時才會抓，
通常在遊戲改版之後。server 執行期間除非呼叫 `refresh_gem`、`update_data` 或 `data_status` 的線上檢查，
否則不會發出任何網路請求。

| 來源 | 網址 | 用到哪些部分 | 抓取範圍與頻率 |
|---|---|---|---|
| poe2db.tw 英文頁面 | `https://poe2db.tw/us/{slug}`：列表頁 `Skill_Gems`、`Spirit_Gems`、`Support_Gems`、`Keystone`、`Notable`，以及每顆寶石各一頁 | 寶石名稱、階級、標籤、消耗、需求、各等級數值表、品質、隱藏屬性、可搭配的輔助；keystone／notable 卡片（屬性文字、名詞連結） | 完整抓取時 5 個列表頁加 1,012 個寶石頁（技能 347、精神 53、輔助 612），每頁間隔 0.8 秒。更新時只抓 3 個寶石列表與有變動的寶石。`refresh_gem` 依要求抓 1 頁 |
| poe2db.tw 中文頁面 | `https://poe2db.tw/tw/{slug}`：同樣五個列表頁 | 寶石、keystone、notable 的繁體中文名稱 | 5 頁，存在本機快取；刪除快取後才會重抓 |
| poe2db 裝備類別頁 | `https://poe2db.tw/us/{slug}` 與 `https://poe2db.tw/tw/{slug}`，即 `item_pages` 列出的 69 個類別頁（武器、副手、依屬性類型細分的防具如 `Body_Armours_str_dex`、飾品、腰帶、生命與魔力藥劑、護符、珠寶，以及 8 個存放珠寶詞綴的珠寶頁） | 裝備基底（數值、需求、固定詞綴）、傳奇（詞綴文字），以及頁面內嵌的詞綴資料：該類能出的每條詞綴的名稱、等級、前綴／後綴、族群與文字，另含褻瀆、精髓、腐化與鑲嵌物效果。不儲存出現權重 | 執行 `update items` 時抓 138 頁（每頁約 600 KB），間隔 0.8 秒 |
| poe2db hover 片段 | `https://cdn.poe2db.tw/cache2/{lang}/Poe_Data_KeywordPopups_hover/{hash}`（`lang` = `us` / `tw`）與 `…/Poe_Data_GemEffects_hover/{hash}` | 名詞解釋（357 個名詞，英文與中文）；寶石 hover 只用來找中文的名詞連結 | 每個約 1.2 KB，間隔 0.3 秒，重建名詞解釋時才抓 |
| poe2db 天賦樹資料 | `https://poe2db.tw/data/passive-skill-tree/4.5/data_us.json` 與 `data_tw.json`（版本號取自 `https://poe2db.tw/tw/passive-skill-tree/` 及其在 `cdn.poe2db.tw/js/` 的 script） | 每個天賦節點的中文名稱與屬性文字、職業與昇華名稱、點數上限 | 重建天賦樹時抓 2 個檔案；檢視頁與 script 只在 probe 檢查新版本時讀取 |
| PathOfBuilding-PoE2 | `https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/src/TreeData/0_5/tree.json` 與 `…/dev/src/Data/QuestRewards.lua`（probe 另會列出 `https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/contents/src/TreeData?ref=dev`） | 天賦樹結構：所有節點、連線、名稱、屬性、keystone／notable 標記、職業起點、昇華、座標；PoB 用來算角色等級的章節表與精魂任務獎勵 | 重建天賦樹時抓 2 個檔案 |
| poe.ninja | `https://poe.ninja/poe2/api/data/index-state`、`https://poe.ninja/poe2/api/builds/{version}/search`、`https://poe.ninja/poe2/api/builds/dictionary/{hash}` | 天梯角色的職業、等級、主技能、寶石、keystone、聯盟、排名。角色名稱與帳號名稱在寫入前就丟棄 | 每份快照約 600 個角色（數種排序各取前 100 名）：執行 `update ninja` 時最多 14 個請求，間隔 0.8 秒。本 repo 內的快照抓於 2026-11-11，聯盟為「Runes of Aldur」 |

請求方式：

- 對 poe2db 與 GitHub 的請求會以
  `POBG/0.12 (+https://github.com/GGaryyy/POBG; research scraper)` 表明身分，每個頁面或檔案
  請求前等待 0.8 秒（hover 片段 0.3 秒），最多嘗試三次。`refresh_gem` 同樣等待 0.8 秒，一次只發一個請求。
- poe2db 的 `robots.txt` 只禁止 `/*/marked` 與 `/*/markdown_history`，兩者都不會被請求。單一天賦節點頁面
  （每頁 1.2 MB）刻意不抓。
- poe.ninja 的抓取程式讀的是 poe.ninja 網站自己使用的端點（JSON、protobuf 與一種二進位字典格式）。那不是有文件的
  公開 API，格式以前就改過，所以抓到的快照看起來不對時程式會拒絕寫入。它送出同樣表明身分的 `User-Agent`，
  請求之間等待 0.8 秒。
- 本 repo 內的快照：寶石抓於 2026-11-10，名詞解釋、天梯與裝備抓於 2026-11-11，天賦樹 `0_5`（poe2db 天賦樹資料 `4.5`）
  與其任務獎勵抓於 2026-11-12。工具回傳的每筆紀錄都會註明自己的 `fetched_at`。

沒有蒐集：有 103 種基底（多為符文鍛造版本，以及永恆珠寶 Timeless Jewel）不在任何詞綴頁上，`modifiers_for` 無法回答它們；
poe2db 元技能寶石頁上有 13 顆寶石（Cast on Death、Demon Magus 等）不在任何寶石列表上。

如果你是上述網站的維護者，希望本專案調整使用資料的方式，請開 issue。

## 在終端機完整抓取

平常請用 `status` 與 `update` 指令。終端機做法用於第一次完整抓取，以及開發蒐集程式時。

```bash
uv sync                                           # 只需一次：把 pytest 與 ruff 裝進 .venv
uv run python -m src.catalog.probe                # poe2db 的結構是否仍符合 catalog 的描述？
uv run python -m src.scrapers.collect_gems --kind all --changed-only   # 3 個列表頁 + 有變動的寶石
uv run python -m src.scrapers.collect_passives && uv run python -m src.scrapers.collect_glossary
uv run python -m src.scrapers.collect_items      # 138 個裝備類別頁：基底、傳奇、詞綴
uv run python -m src.catalog.entity_index build   # 雙語名稱索引（讀取寶石、天賦、名詞解釋、裝備）
uv run python -m src.kg.stats && uv run python -m src.kg.build_graph
```

完整抓取寶石（`collect_gems --kind all`，約 1,000 頁）只在第一次執行或 poe2db 改版面時需要。
頁面快取與 probe 指標寫到 `output/`（不進版控）。

## 發佈

每個版本附一個 zip，給不用 git、要把 POBG 裝進 Claude Desktop 的人。裡面只有 server 需要的檔案
（沒有測試、文件、計畫與報告），解壓後是單一的 `POBG` 資料夾：

```bash
git archive --format=zip --prefix=POBG/ -o output/pobg-<版本>.zip v<版本> \
    .claude-plugin .codex-plugin .agents skills src data pyproject.toml uv.lock README.md README.zh-TW.md LICENSE install_claude_desktop.bat
gh release create v<版本> output/pobg-<版本>.zip --title "POBG <版本>" --notes-file <說明檔>
```

版本號寫在 `pyproject.toml`、`.claude-plugin/plugin.json`、`.codex-plugin/plugin.json`、`src/__init__.py`、`uv.lock`，以及
`src/scrapers/common.py` 的 `User-Agent`。

## 開發

```bash
uv sync
uv run pytest            # 離線，只用合成的測試資料
uv run ruff check .
```

目錄：`src/catalog/`（來源目錄、probe、實體索引）、`src/scrapers/`（蒐集程式）、`src/kg/`（屬性索引、知識圖）、
`src/tools/`（查詢服務、流派工具、PoB 匯出與更新、天賦路徑、資料狀態與更新、Claude Desktop 安裝程式、MCP server）、`skills/` 與 `.claude-plugin/`
（Claude Code plugin）、`.codex-plugin/` 與 `.agents/`（Codex plugin）、`data/`（蒐集到的資料）、`docs/`（用戶端說明、工具、流程圖、計畫、報告、changelog）。
後續規劃見 [`ROADMAP.md`](../ROADMAP.md)。
