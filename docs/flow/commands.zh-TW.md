# 指令流程

[English](commands.md) | **繁體中文**

POBG 在 Claude Code 中有四個指令。這份文件畫出每個指令從輸入到結束的完整路線：會呼叫哪些工具、在哪裡做判斷、
什麼情況會停下來、什麼時候才寫入資料。

| 指令 | 用途 | 會連網嗎 | 會寫入嗎 |
|---|---|---|---|
| [`/pobg:poe2-advisor`](#pobgpoe2-advisor有出處的流派回答) | 回答 PoE2 問題、撰寫有出處的流派與 PoB 匯入碼 | 不會 | 不會 |
| [`/pobg:status`](#pobgstatus資料有多舊) | 各類資料的筆數與新舊 | 你同意檢查線上網站時才會（約 19 個請求） | 不會 |
| [`/pobg:update <範圍>`](#pobgupdate-範圍更新一類資料) | 重新抓取一類資料 | 會 | 會，驗證通過後寫入 `data/` |
| [`/pobg:update-pob <資料夾>`](#pobgupdate-pob-資料夾更新你的-path-of-building) | 更新你電腦上的 Path of Building | 會（GitHub） | 只寫到舊資料夾旁的新資料夾 |

在其他 AI 應用中，`status` 與 `update` 是 `pobg` server 的 prompt，流派流程是 `build_guide` prompt 或 `build_workflow`
工具，步驟相同；`update-pob` 則在終端機執行同一支程式。

圖例：方框是動作，菱形是判斷，圓角框是開始或結束。

## `/pobg:poe2-advisor`：有出處的流派回答

不用自己下指令：在 Claude Code 問 PoE2 問題或要流派時會自動套用。步驟的出處是
[`src/tools/build_workflow.py`](../../src/tools/build_workflow.py)。整個過程只讀本地資料，不連網、不寫檔。

```mermaid
flowchart TD
    A(["玩家要一個流派"]) --> B["套用流程<br/>poe2-advisor skill、build_guide prompt<br/>或 build_workflow 工具"]
    B --> C["步驟 2：由資料找候選<br/>lookup_entity、gems_by、supports_for、<br/>passives_with_stat、get_gem、get_passive"]
    C --> C2["裝備：items_by、get_item 選基底或傳奇<br/>modifiers_for 選目標詞綴<br/>每件最多 3 前綴 + 3 後綴"]
    C2 --> C3["每個選擇都要有資料上的理由<br/>不能是「天梯都在用」"]
    C3 --> D["步驟 3：verify_build<br/>一次送出所有寶石、天賦、裝備、目標詞綴"]
    D --> E{"有 unverified<br/>的名稱？"}
    E -- "有，還沒修滿兩輪" --> F["步驟 4：刪除該名稱<br/>或用 suggestions、重新搜尋取代"]
    F --> D
    E -- "修了兩輪仍有" --> G["捨棄仍未通過的名稱"]
    G --> H
    E -- "沒有" --> H["步驟 5：path_to<br/>職業或昇華 + 已驗證的天賦<br/>回傳路線、順序、點數"]
    H --> I{"over：超過<br/>123 點或昇華 8 點？"}
    I -- "是" --> J["拿掉 added_points 最大的天賦"]
    J --> H
    I -- "否" --> K["步驟 6：reference_builds<br/>讀天梯快照，只用來說明差異<br/>不含角色名稱"]
    K --> L["步驟 7：撰寫回答<br/>數字、消耗、標籤、效果只用 verified 的事實<br/>目標詞綴是要找的目標，不計算傷害"]
    L --> M["步驟 8：結尾附上 sources_markdown<br/>原樣貼上，內含被移除的名稱"]
    M --> N["步驟 9：export_pob<br/>職業、targets、技能組、裝備、指定等級"]
    N --> O{"屬性或精魂<br/>need 大於 have？"}
    O -- "是，可以修" --> P["換寶石、減少常駐技能或保留精魂的輔助、<br/>在裝備加屬性或精魂詞綴"]
    P --> N
    O -- "是，修不了" --> Q2["明白說出缺什麼"]
    Q2 --> Q
    O -- "否" --> Q["回答附上：匯入碼、how_to_import、notes、<br/>not_exported、屬性與精魂、<br/>PoB 配置選項與各自的依據"]
    Q --> R(["玩家把匯入碼貼進 PoB<br/>匯入/匯出 → 貼上 → 匯入"])
```

### `export_pob` 裡面算了什麼

角色等級、寶石等級、屬性、精魂與配置都由資料算出，模型不自己推算。

```mermaid
flowchart TD
    A(["export_pob 的輸入<br/>職業或昇華、targets、技能組、裝備<br/>可選：character_level、attribute、config"]) --> B["天賦路線：path_to<br/>PoB 沒有 id 的昇華被拿掉，路線重算"]
    B --> C["技能組：逐一檢查名稱<br/>輔助寶石必須能輔助該技能"]
    C --> D["裝備：基底與傳奇對照本地資料<br/>稀有詞綴要是該類能出的完整詞綴<br/>3 前綴 + 3 後綴、同族群一條<br/>數值取最高階的上限；副手規則依 PoB"]
    D --> X["不通過的名稱、輔助、詞綴<br/>不放入匯入碼，列在 not_exported"]
    D --> E{"有指定<br/>character_level？"}
    E -- "有" --> F["使用指定的等級<br/>點數需要更高等級時加註"]
    E -- "沒有" --> G["用掉的天賦點 → PoB 的等級公式與章節表<br/>123 點為 100 級"]
    F --> H
    G --> H["寶石等級：等級表中需求不高於角色等級的<br/>最高一列，最高 20；輔助寶石沒有等級"]
    H --> I["屬性<br/>需求 = 各技能寶石需求的最大值、<br/>輔助「+N」總和、裝備需求最大值，三者取最大<br/>已有 = 職業基礎 + 天賦與裝備的固定屬性"]
    I --> J["路線上的屬性天賦點<br/>優先補足需求，或依指定的 attribute"]
    J --> K["精魂<br/>需求 =（常駐技能保留量 + 輔助的額外保留）× 保留倍率<br/>已有 = 所有精魂任務獎勵 + 權杖基礎精魂 +<br/>裝備與天賦的固定精魂<br/>只給範圍或沒給保留量的技能列入 unknown"]
    K --> L{"config<br/>開啟？（預設開）"}
    L -- "否" --> N
    L -- "是" --> M["逐項找依據，有才開啟<br/>球：流派會獲得<br/>敵人狀態：流派會造成<br/>感電、冰緩、點燃：該元素的傷害技能，<br/>或攻擊流派的主手武器<br/>「無法……」排除該技能組<br/>曝曬、近期暴擊"]
    M --> N["寫成 PoB 的 XML<br/>Build、Tree、Skills、Items、Config、Notes"]
    N --> O["zlib 壓縮 → urlsafe base64"]
    O --> P(["回傳 code、how_to_import、notes、<br/>not_exported、summary<br/>不寫檔、不連網"])
```

## `/pobg:status`：資料有多舊

出處：[`skills/status/SKILL.md`](../../skills/status/SKILL.md)、`src/tools/maintenance.py` 的 `status` 與 `online_check`。
這個指令不會呼叫 `update_data`。

```mermaid
flowchart TD
    A(["/pobg:status"]) --> B["data_status<br/>只讀本地檔案，不連網"]
    B --> C["每類資料列出：筆數、抓取時間、天數、<br/>可以用哪個 update 範圍更新"]
    C --> D["指出過舊的資料<br/>包含天梯快照與它的聯盟"]
    D --> E{"詢問使用者：<br/>要檢查線上網站嗎？"}
    E -- "不要" --> J
    E -- "要" --> F["data_status check_online=true<br/>約 19 個請求，間隔 0.8 秒"]
    F --> G["poe2db：各類頁面<br/>是否仍能照 catalog 的描述解析"]
    F --> H["GitHub：PathOfBuilding-PoE2<br/>有沒有新的天賦樹版本"]
    G --> I["回報 problems"]
    H --> I
    I --> J{"有需要<br/>更新的資料？"}
    J -- "有" --> K(["告訴使用者指令：<br/>/pobg:update 加一個範圍"])
    J -- "沒有" --> L(["結束"])
```

天賦樹有新**版本**時 status 會回報，但 `update` 不會自動採用；那需要 POBG 釋出新版。

## `/pobg:update <範圍>`：更新一類資料

出處：[`skills/update/SKILL.md`](../../skills/update/SKILL.md)、`src/tools/maintenance.py` 的 `update`。
一次只更新一個範圍，沒有「全部更新」。所有請求都表明身分（`POBG/0.10`），每個頁面或檔案前等待 0.8 秒
（hover 片段 0.3 秒）。

### 總覽：先看範圍

```mermaid
flowchart TD
    A(["/pobg:update 範圍 名稱"]) --> B{"第一個字是七個範圍<br/>之一嗎？"}
    B -- "不是，或沒寫" --> C(["不呼叫 update_data<br/>請使用者選一個範圍"])
    B -- "是" --> D["update_data<br/>檢查參數：名稱最多 40 個"]
    D --> E{"同一個資料夾已有<br/>update、refresh 或<br/>線上檢查在跑？"}
    E -- "是" --> F(["回報忙碌中，稍後再試<br/>不寫入"])
    E -- "否" --> G{"哪個範圍？"}
    G -- "skill_gems、spirit_gems、support_gems" --> H["寶石流程"]
    G -- "passives" --> I["天賦樹流程"]
    G -- "items" --> J["裝備流程"]
    G -- "glossary" --> K["名詞解釋流程"]
    G -- "ladder" --> L["天梯流程"]
    H --> M["寫入後重建名稱索引<br/>server 在鎖外重新載入資料"]
    I --> M
    J --> M
    K --> M
    L --> M
    M --> N(["同一個對話立刻看到新資料"])
```

任何一次呼叫回傳錯誤時，顯示錯誤並停止；不會改用其他範圍再試。更新改的是 server 執行所在的那份 `data/`。

### `skill_gems`、`spirit_gems`、`support_gems`

```mermaid
flowchart TD
    A(["範圍是三種寶石之一<br/>可加寶石名稱，或「超過 N 天」"]) --> B["update_data dry_run=true<br/>抓列表頁：1 個請求"]
    B --> C["挑出要抓的寶石<br/>新增的、列表上有變動的、<br/>指定名稱的、超過 N 天沒更新的"]
    C --> C2["15 分鐘內抓過的寶石不再抓"]
    C2 --> D["告訴使用者：selected、reasons、<br/>added、removed"]
    D --> E{"selected<br/>等於 0？"}
    E -- "是" --> F(["這類資料已是最新，結束"])
    E -- "否" --> G{"selected<br/>超過 60？"}
    G -- "是" --> H{"使用者確認？<br/>每顆寶石一個請求"}
    H -- "不同意" --> F2(["結束，不寫入"])
    H -- "同意" --> I
    G -- "否" --> I["update_data dry_run=false<br/>每次最多 20 顆，上限 40<br/>每頁間隔 0.8 秒"]
    I --> J{"頁面還能解析、<br/>驗證通過？"}
    J -- "否" --> K(["中止，不寫入任何東西<br/>建議用 status 檢查線上網站"])
    J -- "是" --> L["寫回該類寶石的資料檔<br/>下載失敗的單一頁面列為 skipped，下次再抓"]
    L --> M{"left 大於 0，<br/>且未滿 10 次呼叫？"}
    M -- "是" --> I
    M -- "否" --> N(["回報 updated、added、removed、skipped"])
```

- 只改數值的平衡改版不會改變列表頁，所以單純的 update 會得到 `selected` = 0。請指定改版公告提到的寶石名稱，或要求更新超過 N 天的寶石。
- poe2db 的技能寶石列表也包含所有精神寶石；這類寶石只存一份，由 `spirit_gems` 更新。

### `passives`

```mermaid
flowchart TD
    A(["範圍是 passives<br/>不接受其他參數"]) --> B["一次呼叫，共 8 個請求"]
    B --> C["GitHub：PathOfBuilding-PoE2 的 tree.json<br/>節點、連線、職業起點、昇華"]
    B --> D["GitHub：QuestRewards.lua<br/>PoB 等級用的章節表、精魂任務獎勵"]
    B --> E["poe2db：天賦樹資料檔 data_us、data_tw<br/>每個節點的中文名稱與屬性"]
    B --> F["poe2db：Keystone、Notable 列表頁<br/>中英各一，共 4 頁"]
    D --> D2{"QuestRewards<br/>下載成功？"}
    D2 -- "否" --> D3["照常更新天賦樹<br/>匯入碼改用備用等級並加註"]
    D2 -- "是" --> G
    D3 --> G
    C --> G["組出節點、邊與 classes.json"]
    E --> G
    F --> G
    G --> H{"驗證通過？"}
    H -- "否" --> I(["中止，不寫入"])
    H -- "是" --> J["寫入節點、邊、classes.json<br/>重建屬性索引與名稱索引"]
    J --> K(["回報 records、changed、added、removed<br/>與天賦樹版本"])
```

### `items`

```mermaid
flowchart TD
    A(["範圍是 items<br/>可加裝備類別名稱，例如 Bows"]) --> B["決定要抓的頁面<br/>全部：69 個類別頁 × 中英 = 138 個請求<br/>指定類別：只抓那幾類與其屬性子頁"]
    B --> C["update_data<br/>這次呼叫最多 20 個請求<br/>即 10 個類別頁的中英兩版，每頁約 600 KB"]
    C --> D["進度暫存在 output/cache 30 分鐘<br/>中斷後接續，不重來"]
    D --> E{"done：<br/>全部頁面都抓到了？"}
    E -- "否，未滿 8 次呼叫" --> C
    E -- "否，已滿 8 次" --> F(["請使用者 30 分鐘內再下一次指令<br/>到此為止沒有寫入"])
    E -- "是" --> G["解析基底、傳奇與頁面內嵌的詞綴資料<br/>中英對齊、計算階級"]
    G --> H{"筆數與詞綴資料<br/>通過檢查？"}
    H -- "否" --> I(["中止，不寫入"])
    H -- "是" --> J["一次寫入基底、傳奇、詞綴<br/>只更新部分類別時與原有資料合併"]
    J --> K(["回報 bases、uniques、modifiers"])
```

### `glossary`

```mermaid
flowchart TD
    A(["範圍是 glossary<br/>不接受其他參數"]) --> B["update_data<br/>這次呼叫最多 50 個請求，約一分鐘內"]
    B --> C["透過列表頁與少數寶石頁找到名詞<br/>再抓每個名詞的中英 hover 片段<br/>全部約 750 個請求"]
    C --> D{"連續 5 次<br/>網路錯誤？"}
    D -- "是" --> E(["這次呼叫放棄，進度保留"])
    D -- "否" --> F{"done：<br/>全部抓完了？"}
    F -- "否，未滿 20 次呼叫" --> B
    F -- "否，已滿 20 次" --> G(["請使用者 30 分鐘內再下一次指令<br/>會從停下的地方接續"])
    F -- "是" --> H{"抓到的名詞不少於原有的 90%，<br/>中文內容不少於原有的 50%？"}
    H -- "否" --> I(["不寫入"])
    H -- "是" --> J["逐欄位合併後一次寫入<br/>抓不到的名詞保留原本的內容"]
    J --> K(["回報 records、refreshed、changed、<br/>added、kept_without_refresh"])
```

### `ladder`

```mermaid
flowchart TD
    A(["範圍是 ladder<br/>不接受其他參數"]) --> B["一次呼叫，最多 14 個請求到 poe.ninja<br/>間隔 0.8 秒"]
    B --> C["讀目前聯盟與數種排序各前 100 名<br/>共約 600 個角色"]
    C --> D["只留職業、等級、主技能、寶石、<br/>keystone、聯盟、排名<br/>角色與帳號名稱在寫入前丟棄"]
    D --> E{"快照看起來正常？<br/>至少 100 筆、九成有職業、半數有技能；<br/>同聯盟時不少於上一份的一半"}
    E -- "否" --> F(["拒絕寫入，保留舊快照"])
    E -- "是" --> G["取代天梯快照"]
    G --> H(["回報 records、league<br/>聯盟換了還有 previous_league"])
```

## `/pobg:update-pob <資料夾>`：更新你的 Path of Building

出處：[`skills/update-pob/SKILL.md`](../../skills/update-pob/SKILL.md)、`src/tools/pob_update.py`。
這個指令只能由使用者啟動，模型不能自己執行。它不是 MCP 工具，而是在 plugin 資料夾裡執行
`python -m src.tools.pob_update`。

```mermaid
flowchart TD
    A(["/pobg:update-pob 資料夾"]) --> B{"有給資料夾嗎？"}
    B -- "沒有" --> C(["請使用者提供後停止<br/>不會搜尋硬碟"])
    B -- "有" --> D{"路徑含有引號、<br/>反引號或錢字號？"}
    D -- "是" --> E(["不執行任何東西<br/>請使用者改資料夾名稱或自己執行"])
    D -- "否" --> F["第一步：--check<br/>2 個請求到 GitHub，不寫入"]
    F --> G["辨識資料夾<br/>有 manifest.xml：單獨的 PoB<br/>有 PoeCharm3.exe：PoeCharm2，PoB 在裡面"]
    G --> H["回報 installed 與 latest<br/>PoeCharm2 另回報最新提交與日期"]
    H --> I{"up_to_date？"}
    I -- "是" --> J(["已是最新，結束"])
    I -- "否" --> K["說明更新會做什麼<br/>下載 PoB 正式版約 380 MB 並核對 SHA-256<br/>PoeCharm2 另下載約 30 MB，沒有雜湊可核對<br/>解壓到舊資料夾旁的新資料夾"]
    K --> L{"使用者同意？"}
    L -- "否" --> M(["結束，什麼都沒下載"])
    L -- "是" --> N["第二步：不加 --check 執行<br/>可能要幾分鐘，逾時設 10 分鐘"]
    N --> O["下載到暫存工作資料夾<br/>大小不得超過公布的大小"]
    O --> P{"SHA-256 與 GitHub<br/>公布的相符？"}
    P -- "否" --> Q(["報錯，清掉暫存<br/>舊資料夾不變"])
    P -- "是" --> R["解壓<br/>拒絕會跳出目錄的路徑，限制解壓後大小"]
    R --> S["複製存過的 build（Builds）<br/>與 PoeCharm2 的語言設定<br/>不讀也不複製 Settings.xml"]
    S --> T["改名成新資料夾<br/>防毒掃描擋住時重試 5 次"]
    T --> U(["回報 new_folder、version、<br/>builds_copied、checksum、next<br/>舊資料夾不修改、不刪除；要重新登入"])
```

- 指令被中途停止時，舊資料夾旁可能留下 `.pobg-update-…` 工作資料夾；下次執行會在一小時後清掉它，也可以自己刪除。
- 新資料夾確認能用之後，舊資料夾由使用者自己決定要不要刪。
- 在其他 AI 應用或手動執行時的指令見 [docs/data.zh-TW.md](../data.zh-TW.md#更新-path-of-building)。
