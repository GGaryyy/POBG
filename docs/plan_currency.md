# 計畫：通貨資料（為裝備製作做準備）

核准後存為 `docs/plan_currency.md`。版本 0.14.0。沒有你的指示不 commit、不推送。

## 背景

通貨是裝備製作的主要材料，但目前 plugin 完全沒有通貨資料（README 寫著「不涵蓋製作與通貨」）。這一版只做**蒐集、整理、可查詢**，讓 AI 能用中英文回答「這個通貨做什麼、有什麼限制、幾級開始掉」，並附 poe2db 出處。製作流程本身（怎麼一步步做出一件裝備）是下一個計畫。

你的決定（2026-11-17）：
- **兌換價格這次不收**，只收效果；交易功能之後另外規劃。
- **每個通貨都抓單頁**，取得掉落等級。

## 調查結果（實際讀了 poe2db，18 個請求）

- 清單頁的 HTML 一次就包含所有分頁，每個通貨的**完整效果文字**都在裡面；中文頁網址代稱相同、結構相同，名稱與效果都有翻譯。
- 三個清單頁就涵蓋全部，約 630 個不重複的通貨：

| 清單頁 | 內容 |
|---|---|
| `Stackable_Currency` | 可堆疊通貨 145（製作寶珠含高階／完美版、碎片、深淵骨頭、精煉情緒、探險通貨、聯盟物品）、精髓 95、裂片 4、催化劑 26 |
| `Omen` | 預兆 50 |
| `Augment` | 符文與魂核 313 |

- 清單頁有：名稱、堆疊數量、**最小詞綴等級**（高階混沌石 35、完美 50）、效果文字、符文的需求等級與「各裝備類別的效果」。
- 單頁另外有：**掉落等級**、類別（Class）、標籤（Tags）、內部類型（例如 `CurrencyRerollRare`、`OmenOnChaosLowestLevelMod`）。
- 精髓在各裝備類別保證的詞綴與需求等級，**現有的詞綴資料已經有**（`modifiers_for` 的 `essence` / `perfect_essence` 群組），不用重抓，接上即可。
- 資料裡沒有的：掉落來源與機率、製作步驟、價格（這次不收）。

## 做法

沿用章節資料（0.13.0）的接法：收集程式 → `data/` → 名稱索引 → 查詢工具 → 更新範圍。

### 1. 收集：`src/scrapers/collect_currency.py`（新）

- 清單頁（3 頁 × 中英 = 6 個請求）：解析每個 `div.col` 項目的名稱、代稱、所在分頁（→ 類別）、`div.property`（堆疊數量、最小詞綴等級、限制數量）、效果行（`explicitMod` / `implicitMod` / `enchantMod` / `bondedMod`）、`div.requirements`。中英文以代稱合併。
- 單頁（每個通貨 1 個請求，只抓英文）：讀名稱／數值卡片的 DropLevel、Class、Tags、Type。把 `collect_campaign.py:417` 的 `parse_item_page` 需要的部分搬到共用處，兩邊共用。
- 類別只用頁面上看得到的分法：`currency`、`essence`、`splinter`、`catalyst`、`omen`、`augment`。可堆疊通貨分頁內的細分（骨頭、情緒、探險）頁面沒有標示，**不自己分類**，改提供單頁的 Type 與 Tags 讓 AI 篩選。
- 同一個通貨出現在多個分頁（13 個合金）：以代稱去重，保留第一個類別，其餘記在 `also_in`。
- 輸出 `data/currency/currency.jsonl`，每筆：`slug, category, name, name_zh_tw, stack_size, min_modifier_level, limit, requires_level, effects, effects_zh_tw, drop_level, item_class, tags, type, url_en, url_zh_tw, fetched_at`。
- `src/catalog/poe2db_sources.json` 新增 `currency` 來源（清單頁、分頁對類別、檔案路徑、`expect_min`：總數 500、各類別下限、中文比例 0.9）；`spec.py` 加 `CURRENCY_KINDS = ("currency",)`。

### 2. 更新範圍 `currency`（`src/tools/maintenance.py`）

- 約 640 個請求、間隔 0.8 秒，約 9 分鐘，所以**分批執行**，沿用裝備更新的做法（`_Budget`、`_start_or_resume`、`_sweep_stale_runs`）：每次呼叫抓一批，回傳 `done: false` 與剩餘數量，AI 繼續呼叫到完成，全部通過檢查才寫入。
- 日常更新不必每次 9 分鐘：預設只重抓清單頁（6 個請求），**單頁只抓還沒有掉落等級的新通貨**；要全部重抓時明確指定（實作時沿用 `update_data` 現有的選項形式）。
- 檢查不過（筆數不足、中文比例過低）就不覆寫舊資料，回報哪一頁有問題。
- `data_status` 回報通貨筆數與抓取日期；完成後重建名稱索引。
- `src/catalog/entity_index.py` 加 `_currency_entities`：`lookup_entity` 用中文或英文都找得到通貨。

### 3. 查詢工具：`src/tools/currency.py`（新，`CurrencyLookup`）

| 工具 | 用途 |
|---|---|
| `get_currency(name)` | 一個通貨的完整紀錄與出處。另外附 `related`：效果文字提到這個通貨的其他通貨（例如問混沌石會列出影響它的預兆），由資料比對得出。精髓會附一句「保證詞綴用 `modifiers_for` 的 essence 群組查」。 |
| `currency_by(category, text, max_level, limit)` | 依類別、效果文字或掉落等級篩選，例如「45 級前拿得到哪些製作寶珠」「哪些預兆影響崇高石」。 |

- 都是唯讀、附 poe2db 中英文連結與抓取日期；名稱比對沿用 `items.py:233` 的 `_resolve` 做法。
- `mcp_server.py` 註冊這兩個工具（22 → 24 個）；順便補上 `update_data` 說明裡漏掉的 `campaign`。
- `build_workflow.py` 的 `SERVER_INSTRUCTIONS`、更新步驟，以及 `skills/poe2-advisor`、`update`、`status` 三個 skill 加上通貨。**流派流程這次不改**，等製作功能一起做。
- `LIMIT_NOTES`／`not_in_data`：掉落來源與機率、價格、製作步驟不在資料裡，AI 要照實說。

### 4. 文件與版本

README（中英：資料範圍、「不涵蓋」那行改成只剩製作流程與價格、工具數）、`docs/tools*.md`、`docs/data*.md`、`docs/flow/`（指令流程圖加 update-currency）、ROADMAP、CHANGELOG；版本 0.14.0（pyproject、兩個 plugin.json、`src/__init__`、uv.lock、UA）。

## 錯誤處理

- 單頁 404 或沒有 DropLevel：該通貨的 `drop_level` 留空，不中斷整批；留空的比例超過門檻才視為失敗。
- 清單頁格式變了（1.0 上線）：筆數檢查不過就不寫入。
- 更新中斷：下次呼叫從上次的批次接續，過期的暫存會清掉。
- 資料檔不存在：工具回報要執行 `update currency`，不猜答案。

## 測試（全部用合成資料，仿照 `tests/campaign_support.py`）

- 單元（`tests/unit/test_collect_currency.py`）：
  - 清單項目解析：有無行內圖示的名稱、`<br />` 與長破折號範圍的效果文字、沒有效果行的通貨（工匠碎片）、名稱含等級（「(Level 5)」）。
  - 最小詞綴等級、堆疊數量、符文的需求等級與各類別效果。
  - 中英合併；中文缺漏時只留英文；重複項目去重並記錄 `also_in`。
  - 單頁的 DropLevel / Tags / Type；缺欄位時留空。
  - `expect_min` 不過時拋出錯誤。
- 整合（`tests/integration/test_currency_tools.py`）：`get_currency` 中英文查詢、查無名稱回傳候選、`related` 只比對完整名稱（「Chaos Orb」不會配到「Greater Chaos Orb」的文字以外的東西）、`currency_by` 各篩選與邊界（掉落等級剛好等於上限）、`lookup_entity` 找得到通貨。
- 更新（`test_maintenance*.py`）：分批與接續、只抓新通貨的單頁、失敗不覆寫、`data_status`。
- 既有測試：工具清單（24 個）、plugin 工具名稱比對、版本一致。
- 實測：實際執行一次 `update currency`（約 640 個請求），用真實資料查幾個通貨。
- 交付：測試報告、複查報告、CHANGELOG。

## 驗收

1. 用中文或英文問「高階混沌石做什麼？」得到效果、最小詞綴等級、掉落等級，並附 poe2db 連結。
2. 「哪些預兆會影響混沌石？」「第 2 章結束前拿得到哪些製作寶珠？」能由資料回答。
3. 問精髓時，AI 能接著用 `modifiers_for` 說出它在某裝備類別保證的詞綴。
4. 問價格、掉落機率時，AI 說本機資料沒有。
5. `update currency` 可中斷接續；之後的日常更新只需要幾個請求。

## 不在範圍內

- 裝備製作流程（下一個計畫）、兌換價格與交易。
- 地圖碎片、石板、試煉硬幣等非製作用的物品頁。
- 流派生成流程的改動。

## 實作補記（2026-11-17）

- 依計畫完成；與計畫不同處：
  - 每次呼叫最多 **50** 個請求、最多 16 次（計畫寫 60）：複查指出 60 個請求是專案裡最長的單次呼叫。
  - 單頁「讀到」的定義：要有掉落等級或類別才算；讀不到時保留舊資料的欄位與日期（複查發現的問題）。
  - poe2db 的單頁已改版（名稱／數值卡片），章節收集也受影響；新增共用的 `src/scrapers/item_page.py`，兩種版面都讀。
- 真實資料：620 個通貨（currency 145、essence 82、splinter 4、catalyst 26、omen 50、augment 313），全部有中文名稱與單頁資料。
- poe2db 對某些只來自特定內容的物品給 DropLevel 1（例如破裂石、獻祭寶珠）；已寫進 `not_in_data` 與工具文件，不另外推測。
- 報告：`docs/reports/test_report_2026-11-17.md`、`docs/reports/code_review_2026-11-17.md`。

