# 計畫：Phase 15 收尾 ＋ Phase 16 裝備與詞綴資料

2026-11-11 核准。
所有工作都在該資料夾進行；沒有你的指示不會 commit、不會推送、不會公開。

執行順序：**先做完第 0 部分的三件收尾，全部通過後才開始 Phase 16。**

---

## 第 0 部分：Phase 15 收尾（先做）

| # | 項目 | 做法 | 完成標準 |
|---|---|---|---|
| 0-1 | 天賦來源沒有抓取日期 | 蒐集天賦樹時把抓取時間寫進每個節點（`fetched_at`），`get_passive`、`verify_build`、`path_to` 的來源清單就會像寶石一樣顯示「擷取於 日期」。現有資料用 `update passives` 重抓一次（7 個請求）補上日期 | 流派回答的來源清單中，天賦那幾筆也有日期；測試涵蓋 |
| 0-2 | 新資料夾的 floorplan 沒更新 | 用 floorplan skill 更新：補上天梯與名詞解釋更新、改名、移除 `.mcp.json` 之後的檔案說明與近期工作 | 所有檔案都有說明、沒有未歸類的檔案 |
| 0-3 | 後兩輪檢查的修正沒有再送獨立檢查 | 請 `reviewer` 做一次複查，範圍只限第二、三輪檢查之後改過的程式：重複呼叫會結束的機制、鎖檔、名詞解釋逐欄位合併與各項門檻、天梯解析器的防護、每顆寶石只存一份 | 複查結論為通過；若有 High 以上的問題先修完並補測試，結果寫進 code review 報告 |

| 0-4 | 本機資料夾改名 | 舊資料夾 `POBG` → `POBG-legacy`，新資料夾 `poe2db-mcp` → `POBG`，與 GitHub 上的名稱一致 | 見下方步驟 |

第 0 部分的 0-1 到 0-3 做完後：跑完整測試、更新 changelog 與報告，向你回報，等你說 commit
才 commit。

**0-4 需要重開 Claude Code**，因為目前這個對話的工作目錄就是舊的 `POBG` 資料夾，
對話進行中無法把它改名。做法：

1. 我先做好不需要改名就能準備的事：把 Claude Desktop 設定裡的路徑改成 `D:\IT\githubProbject\POBG`、
   在專案記憶裡記下新位置與 Phase 16 的進度。
2. 我給你三行指令。你**結束這個 Claude Code 對話**後在終端機執行：
   ```
   mv /mnt/d/IT/githubProbject/POBG /mnt/d/IT/githubProbject/POBG-legacy
   mv /mnt/d/IT/githubProbject/poe2db-mcp /mnt/d/IT/githubProbject/POBG
   cd /mnt/d/IT/githubProbject/POBG && uv sync
   ```
   最後一行是重建 `.venv`（虛擬環境裡記著舊路徑，改名後要重建）。
3. 在新的 `POBG` 資料夾重新開 Claude Code，並重開 Claude Desktop。
4. 新對話會沿用現有的專案記憶（記憶是依資料夾路徑存放的，新資料夾改名後的路徑正好對應到
   現在這份），本計畫也已存在 repo 的 `docs/plan_gear_data.md`，所以可以直接接著做 Phase 16。

改名後舊資料夾的 git 遠端仍指向 `POBG-legacy`，不受影響。

---

## 第 1 部分：Phase 16 裝備與詞綴資料

### 背景

目前工具懂寶石、天賦樹、名詞解釋，但完全不懂裝備。流派的傷害與生存取決於武器基底、
能出的詞綴、傳奇、珠寶與藥劑，而且每一季都會變。你在 2026-11-11 決定納入「第一級與
第二級」：裝備、詞綴、傳奇、珠寶、藥劑與護符，加上血脈輔助寶石、元技能寶石、昇華頁、
鑲嵌物。匯出到 Path of Building 排在這之後，製作與通貨再之後。

調查 poe2db 的結果（只讀、6 個請求、沒有存任何資料）：

| 發現 | 意義 |
|---|---|
| 每個裝備類別頁（例如 `/us/Bows`，765 KB）直接列出該類的**所有基底與數值**（35 把弓：傷害、暴擊、攻速、需求、固定詞綴）以及**所有傳奇與其詞綴**（11 把） | 基底與傳奇不必逐一開頁面，每類一個請求就夠 |
| 同一頁內嵌一份 JSON（395 KB），含該類能出的所有詞綴：一般詞綴（弓有 140 條：名稱、等級、前綴／後綴、族群、文字）、褻瀆（17）、腐化（12）、精髓（31）、鑲嵌物（99 個符文與靈魂核心對這類裝備的效果）等 | 詞綴與鑲嵌物來自同一個請求，而且是結構化資料，不用從表格硬抓 |
| 詞綴索引列出 **81 個類別頁**（防具依屬性類型再細分，例如 `Body_Armours_str_dex_int`；珠寶 8、藥劑 3） | 全部裝備與詞綴約需英文 81 頁 + 中文 81 頁 |
| `/us/Unique_item` 一頁列出全部 **496 件傳奇**（武器 88、防具 221、其他 139、栽培 48） | 可用來核對各類別頁的傳奇清單 |
| poe2db 註明詞綴權重「無法從遊戲檔取得」 | 不儲存、不回報權重 |
| 血脈輔助寶石、元技能寶石、昇華頁還沒打開看過 | 這幾類在 16b 第一步先看版面，再寫程式 |

### 詞綴在流派建議中的定位（你的指示）

這個階段蒐集到的是「某個部位或某類武器**可能出現**哪些詞綴」，不是玩家一定拿得到的東西。
詞綴是隨機的：打怪掉落、商人販售、用通貨點出來都是機率，只有到製作階段才比較有機會
做出完全符合需求的裝備。因此：

- 流派建議對每個部位只列出**最值得追求的少數幾條詞綴**（每個部位最多 5 條，依重要性排序），
  當作「目標」，而不是把該部位能出的詞綴全部列出來。
- 回答要明確說明：這些是優先目標，實際裝備不一定能全部湊齊；怎麼把它們做出來屬於之後的
  製作階段。
- 工具層面：`modifiers_for` 預設只回傳符合查詢條件的詞綴族群，不是整份清單；`verify_build`
  會檢查建議的每條詞綴「這個部位確實出得了」，並回傳它的數值範圍與需求等級，避免建議了
  該部位根本不會出現的詞綴。
- 不做的事：不估計機率（poe2db 沒有可靠的權重）、不計算湊齊的成本、不提供製作步驟。

### 範圍與順序

分成兩段，各自有測試、真實執行、獨立檢查與 commit：

- **16a：裝備基底、詞綴、鑲嵌物、傳奇**（主體）
- **16b：珠寶、藥劑與護符、血脈輔助寶石、元技能寶石、昇華頁**

16a commit 之後才開始 16b；16b 重用 16a 的蒐集程式與工具。

### 設計（16a）

**1. 來源目錄與 probe**
- `src/catalog/poe2db_sources.json`：新增來源 `item_classes`（類別頁清單、各自的種類與最低筆數）
  與 `unique_items`，以及基底卡片、傳奇卡片的 selector、內嵌詞綴物件的名稱；`fields` 補上
  每個欄位的意義。
- `src/catalog/probe.py`：抽一個類別頁檢查基底、傳奇與詞綴物件，讓 `status` 的線上檢查
  也能發現這裡的版面變動。

**2. 蒐集程式 `src/scrapers/collect_items.py`（新增）**
- `parse_class_page(html, spec, class_slug, lang)` → 基底、傳奇、詞綴、鑲嵌物。
  重用 `src/scrapers/common.py` 的 `make_soup`、`clean_text`、`slug_from_href` 與
  `hover.py` 的 `keyword_refs`；詞綴文字去除 HTML 標記的方式與寶石文字相同。
- 英文與中文頁面的對應：基底與傳奇用 slug 對，詞綴用同一組內的位置對（與天賦蒐集程式
  對兩種語言的做法相同）。
- 寫入前驗證（與其他蒐集程式一致）：筆數不低於最低值、每個基底都有名稱與類別、
  至少 95% 的詞綴有文字，並回報中文覆蓋率。
- 輸出（LF 換行、原子寫入、每件只存一份）：
  - `data/items/bases.jsonl`：slug、中英名稱、類別、數值、需求、固定詞綴、來源網址、抓取時間
  - `data/items/uniques.jsonl`：slug、名稱、基底、類別、需求、詞綴文字（中英）、來源網址、抓取時間
  - `data/items/modifiers/<類別>.jsonl`：組別（一般、褻瀆、腐化、精髓…）、名稱、前綴／後綴、需求等級、族群、文字（中英）
  - `data/items/socketables.jsonl`：符文／靈魂核心，以及它在各類裝備上的效果
- 不儲存權重。

**3. 查詢與工具**
- 名稱索引（`src/catalog/entity_index.py`）新增兩種：`item_base`、`item_unique`，
  讓 `lookup_entity` 能用中英文找到裝備。詞綴不進索引。
- `LookupService`（`src/tools/lookup.py`）與三個唯讀的 MCP 工具：
  - `get_item(name)`：一件基底或傳奇的數值與來源。
  - `items_by(item_class, kind, text, max_level, limit)`：某類的基底或傳奇，或詞綴中提到某文字的傳奇。
  - `modifiers_for(item_class, group, affix, text, max_level, limit)`：某類裝備能出哪些詞綴，
    依族群分組、階級依序排列；也包含該類可用的鑲嵌物。
- `verify_build` 新增兩個可選清單：
  - `items`：傳奇與基底名稱和寶石、天賦一樣逐一比對，並出現在程式產生的來源清單中。
  - `affixes`：每筆是「裝備類別 + 想要的詞綴文字」。工具確認該類別出得了這條詞綴，
    回傳它的階級數、數值範圍與最低需求等級；出不了的列入 `unverified` 並給相近的詞綴。
    每個類別最多 5 條。
- 流程文字與 `poe2-advisor` skill 增加一步：先挑裝備基底或傳奇，再為每個部位挑最多 5 條
  優先詞綴並驗證；回答中說明詞綴是隨機的、這些是目標而非保證，並明確說明「不計算傷害」。
- 工具總數變成十七個；可攜性測試會自動涵蓋新工具。

**4. status 與 update**
- `data_status` 列出新的資料類別。
- `update_data` 新增範圍 `items`。完整更新約 162 個大頁面，所以沿用名詞解釋的可接續暫存
  機制（抽成 `src/tools/maintenance.py` 內共用的一段）：每次呼叫固定頁數、全部抓完並通過
  驗證才一次寫入、驗證失敗不寫入。`names` 可以限定只更新幾個裝備類別。

### 設計（16b）

- 第一步各看一頁：血脈輔助寶石、元技能寶石、一個昇華職業、珠寶、藥劑、護符，
  把發現補進本計畫，再寫程式。
- 珠寶、藥劑、護符本身就是裝備類別，直接重用 `collect_items.py`。
- 血脈輔助寶石與元技能寶石若是寶石列表，就擴充寶石蒐集程式（`src/scrapers/collect_gems.py`）；
  已經存在的元技能寶石不重複儲存。
- 昇華頁的說明加進 `data/passive_tree/classes.json`。

### 會動到的檔案

| 檔案 | 變更 |
|---|---|
| `src/scrapers/collect_items.py` | 新的蒐集與解析程式 |
| `src/catalog/poe2db_sources.json`、`src/catalog/probe.py`、`src/catalog/entity_index.py` | 新來源、probe 檢查、新的索引種類 |
| `src/tools/lookup.py`、`build_tools.py`、`mcp_server.py`、`build_workflow.py`、`maintenance.py` | 裝備查詢、`verify_build` 的 items、三個工具、流程步驟、`items` 範圍、共用的暫存機制 |
| `skills/poe2-advisor/SKILL.md`、`skills/update/SKILL.md`、`skills/status/SKILL.md` | 裝備步驟、新範圍 |
| `data/items/**` | 新資料（預估約 15 MB，第一次執行後實測） |
| `tests/fixtures/html/` | 小型的合成類別頁（中英），內含詞綴物件 |
| 文件：兩份 README（工具、資料來源表、限制）、`docs/clients.md`、roadmap、changelog `[0.8.0]`、流程圖、報告 | |

### 錯誤處理

| 情況 | 行為 |
|---|---|
| 類別頁沒有詞綴物件，或基底少於最低筆數 | 蒐集中止、不寫入；probe 會回報 |
| 中英文頁面在某一組的筆數不一致 | 該組只保留英文並計入摘要；不寫入對不上的中文 |
| 頁面下載失敗 | 與名詞解釋相同：該次呼叫失敗或下次重試；整個流程通過驗證前不寫入 |
| 工具收到不存在的裝備或類別名稱 | 與寶石相同：回報查無並給相近名稱 |
| `verify_build` 收到資料中沒有的裝備 | 列入 `unverified` 並給建議 |
| 傳奇出現在類別頁但不在 `/us/Unique_item`，或相反 | 計數並寫進蒐集摘要，不視為錯誤 |

### 測試（離線，只用合成資料）

| 檔案 | 重點 |
|---|---|
| `tests/unit/test_collect_items.py` | 基底與傳奇每個欄位都解析到；詞綴各組；標記去除；中文依 slug／位置對應；語言不一致時退回英文；缺物件與筆數不足會中止；權重絕不儲存 |
| `tests/integration/test_lookup_items.py` | `get_item`、`items_by`、`modifiers_for` 的中英文查詢、上限、查無、來源與日期 |
| `tests/integration/test_build_tools_verify.py`（擴充） | `items` 會被驗證並引用；不存在的裝備列為未驗證 |
| `tests/integration/test_maintenance.py`（擴充） | `items` 範圍：分批、接續、驗證失敗時檔案逐位元不變、類別篩選 |
| `tests/integration/test_mcp_server.py`、可攜性與 manifest 測試 | 十七個工具、標註、skill 與流程文字都有提到 |

真實網站上的端對端驗證：完整蒐集一次（約 162 個請求，間隔 0.8 秒，背景執行）、筆數與頁面
標題比對（例如 35 把弓的基底、11 把傳奇弓、傳奇總數 496）、資料大小、工具回應時間、
Windows 啟動檢查，以及在 Claude Code 問一個會提到裝備的流派問題。

### 驗收標準

1. 每一類裝備的基底、傳奇、詞綴、鑲嵌物都已存入，含中英文與 poe2db 來源網址；筆數與頁面
   標題相符，不相符處在報告中說明。
2. `get_item`、`items_by`、`modifiers_for` 載入後回應在 50 毫秒內。
3. `verify_build` 會檢查裝備名稱與建議的詞綴；編造的裝備名稱、或該部位出不了的詞綴，
   不會被當成已驗證。流派回答中每個部位的建議詞綴不超過 5 條，並說明詞綴是隨機的。
4. `update items` 每次呼叫有上限、可接續，整個流程通過驗證前不寫入。
5. 離線測試全過；`src/tools` 與新蒐集程式的覆蓋率維持 90% 以上。
6. plugin 仍通過嚴格驗證；repo 大小實測並回報。
7. 新程式經過獨立檢查，發現的問題在 commit 前處理完。
8. 沒有你的指示不 commit、不推送。

### 不在範圍內

傷害與防禦的計算；詞綴權重；製作方式與通貨（再下下個階段）；物品價格；終局物品
（換界石、碑牌、聖物）；匯出到 Path of Building（下一個階段）。
