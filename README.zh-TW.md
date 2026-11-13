# POBG — 給 AI 助理用的 Path of Exile 2 資料與流派工具

[English](README.md) | **繁體中文**

用中文或英文問你的 AI 助理 **Path of Exile 2（流亡黯道 2）** 的問題，答案取自真實的遊戲資料，每項事實都附上出處連結與抓取日期。
要一個流派時，技能、天賦與裝備都會逐一和資料比對，最後附上可貼進
[Path of Building](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2)（PoB）的匯入碼，直接在 PoB 看數字。

POBG 是非官方的 [Model Context Protocol](https://modelcontextprotocol.io) server 與 Claude Code plugin。
資料是 [poe2db.tw](https://poe2db.tw)、[PathOfBuilding-PoE2](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2)
天賦樹與一份 [poe.ninja](https://poe.ninja/poe2/builds) 天梯快照的本機副本。本專案與 Grinding Gear Games、poe2db.tw、
PathOfBuilding、poe.ninja 均無隸屬關係。

POBG 只是站在巨人的肩膀上：沒有 poe2db.tw、Path of Building 社群與 poe.ninja 長期整理並公開的資料，就不會有這個專案。感謝他們。

## 快速開始

POBG 在你自己的電腦上執行。請先安裝 [uv](https://docs.astral.sh/uv/getting-started/installation/)，版本必須是
**0.13.4 以上**（`uv --version` 查看，`uv self update` 升級）。

**我們建議使用 Claude Code 或 Codex。** 兩者都以 plugin 安裝 POBG：plugin 會在你的電腦上啟動 MCP server（提供工具），並帶來流派說明與
`pobg` 指令。平常直接用一般的話提問；要檢查或更新資料時用 `pobg` 指令。這也是我們測試中產出完整流派的做法。

**Windows 使用者請用 WSL。** 這兩者我們都是裝在 WSL（Ubuntu）裡測試的，uv 也裝在 WSL 裡。Windows 上的
Claude Code 我們建議在 WSL 裡使用；Codex CLI 在 PowerShell 或 cmd 上沒有測過，所以無法說明在那裡的情況。macOS 與 Linux 不需要
額外準備。

### Claude Code（建議）

在 Claude Code 裡輸入這兩行：

```
/plugin marketplace add GGaryyy/POBG
/plugin install pobg@pobg
```

開一個新對話直接提問。第一次啟動時 uv 要準備 Python 與約 40 個套件，會稍久一點。指令以 `/pobg:` 開頭
（例如 `/pobg:status`，見[指令](#指令)）。

### Codex CLI（建議）

在終端機執行這兩行（不是在 Codex 的對話裡）：

```
codex plugin marketplace add GGaryyy/POBG
codex plugin add pobg@pobg
```

啟動 `codex` 直接提問，第一次啟動同樣會稍久一點。指令以 `$pobg:` 開頭（例如 `$pobg:status`；輸入 `$pobg` 會列出全部）。
請它給 Path of Building 匯入碼時，**請用 Codex 存下的檔案**：很長的匯入碼被重打到終端機上時可能出錯（2026-11-13 實測）。

### 其他 AI 應用

Claude Desktop、ChatGPT 桌面版、Cursor、VS Code、Gemini CLI 等也能把 POBG 當成本機 MCP server 使用，但步驟比較多，我們的測試也
比較少：各應用的設定方式與測試紀錄見 [docs/clients.zh-TW.md](docs/clients.zh-TW.md)。沒有 skill 時（例如 ChatGPT 桌面版）工具
可以用，但流派回答比較單薄。不支援網頁版的 ChatGPT 與 Claude：它們只能連線上的 MCP server，而 POBG 是在你的電腦上執行。

## 可以問什麼

- 「躍擊 10 等的消耗是多少？有哪些輔助寶石可以搭配？」
- 「哪些天賦有攻擊速度？」
- 「解釋暴擊」
- 「女巫要點到 Blood Magic 和 Resolute Technique 需要幾點天賦？」
- 「弓能出哪些詞綴？攻擊速度有哪幾階？」
- 「驟雨之弦有什麼詞綴？」
- 「給我一個 90 級閃電祈靈者流派，包含完整裝備以及 PoB 匯入碼」

## 流派回答會有什麼

助理依資料組出流派，而不是照抄熱門流派，並在寫出之前比對每個名稱：

- **技能與輔助寶石**：每一顆都附上寶石資料中的理由。
- **天賦**：目標天賦、到達它們的路線，以及用掉 123 點（昇華 8 點）中的幾點。
- **裝備**：每個部位的基底或傳奇；稀有裝備依重要性列出最多 3 條前綴、3 條後綴作為目標。
- **屬性與精魂**：需求與已有的對照，不足時該改什麼。
- **和天梯比較**：和 poe.ninja 天梯角色相同與不同之處。
- **來源**：以上每一項的 poe2db 連結。資料裡不存在的名稱會被移除並列出。
- **Path of Building 匯入碼**（見下節）。

## 匯入 Path of Building

複製回答中的匯入碼，在 Path of Building（PoE2）：**匯入/匯出** → 貼到「輸入網址或代碼」欄 → **匯入**。
請先把 PoB 更新到最新版（`/pobg:update-pob <你的 PoB 資料夾>` 會幫你更新，見
[docs/data.zh-TW.md](docs/data.zh-TW.md#更新-path-of-building)）。天賦樹取自 PoB 的開發分支，可能比它最新的正式版新：
較舊的 PoB 會略過它不認得的天賦與寶石，也可能拒絕天賦樹版本或昇華。

**匯入碼包含**：職業與昇華、天賦路線、技能組與輔助寶石、裝備，以及 PoB 配置頁的選項。流派說明寫在 PoB 的**備註**頁。

**由資料算出、不靠 AI 推測**：

- 角色等級：由配點算出（123 點為 100 級），或使用你指定的等級。
- 每顆技能寶石的等級：該角色等級能用的最高等級。
- 屬性天賦點選哪個屬性：優先補足寶石與裝備的需求。
- 精魂：常駐技能保留的精魂，對照任務獎勵、權杖、裝備與天賦上的精魂，算法與 PoB 相同。

**需要知道的假設**：

- **裝備數值是理想值。** 每條詞綴都取最高階的上限（例如「+(100—119) 最大生命」寫成「+119」）。實際裝備通常較低，
  可在 PoB 的物品頁修改；指定階級或數值留待之後加入。不含品質、符文、靈魂核心、插槽與珠寶；沒有武器時，攻擊技能會顯示為停用。
- **配置頁**只開啟流派本身有理由的項目：會獲得的球、會造成的異常狀態、閃電擊中會造成感電等。回答會列出每一項的理由。
  球類以最大顆數計算；想試較少的顆數，在配置頁「數量（如果不是最大值）」欄填入數字。
- **和天梯比較時**：poe.ninja 匯出的 PoB 對每個角色都開啟一組固定狀態，天梯角色的傷害可能單純因此較高。
  備註會列出天梯有開、但本流派沒有來源的狀態。

## 指令

POBG 共有四個指令。指令名稱在 Claude Code 和 Codex 裡完全一樣，只是兩個應用叫用的符號不同：Claude Code 用 `/`，Codex 用 `$`
（在 Codex 打 `$pobg` 會列出它們）。每個指令的完整流程圖（會呼叫什麼、在哪裡判斷、何時寫入）見
**[docs/flow/commands.zh-TW.md](docs/flow/commands.zh-TW.md)**。

| 指令 | Claude Code | Codex | 做什麼 |
|---|---|---|---|
| status | `/pobg:status` | `$pobg:status` | 列出每類資料有幾筆、何時抓的、已經多久。你同意後還可檢查線上網站：poe2db 頁面是否改版、天賦樹有沒有新版 |
| update | `/pobg:update <範圍> [名稱]` | `$pobg:update <範圍> [名稱]` | 遊戲改版後重新抓取**一類**資料。先列出會抓哪些，再實際更新 |
| update-pob | `/pobg:update-pob <資料夾>` | `$pobg:update-pob <資料夾>` | 把你的 Path of Building（PoE2，單獨安裝或放在 PoeCharm2 資料夾中）更新到最新版。先比對版本，你同意後才下載到舊資料夾旁的**新資料夾**；舊資料夾不會被修改或刪除 |
| poe2-advisor | `/pobg:poe2-advisor` | `$pobg:poe2-advisor` | 回答 PoE2 問題與撰寫流派時遵循的說明。不用自己下指令，提問時會自動套用 |

`update` 一定要指定範圍，沒有「全部更新」：

| 範圍 | 更新什麼 |
|---|---|
| `skill_gems` | 技能寶石 |
| `spirit_gems` | 精神寶石（常駐技能） |
| `support_gems` | 輔助寶石 |
| `passives` | 天賦樹，以及匯入碼用的 PoB 等級表與精魂任務獎勵 |
| `items` | 裝備基底、傳奇與詞綴（含藥劑、護符、珠寶）；加上類別名稱就只更新那幾類 |
| `glossary` | 名詞解釋 |
| `ninja` | poe.ninja 天梯快照（不保留角色或帳號名稱） |

範例（在 Codex 把 `/` 換成 `$`）：

```
/pobg:status
/pobg:update skill_gems
/pobg:update support_gems Fire Attunement, Brutality I
/pobg:update items Bows
/pobg:update-pob "D:\PoB\PoeCharm2"
```

也可以直接用說的，例如「更新超過 30 天的技能寶石」。只改數值的平衡改版不會改變寶石列表頁，單純的 update 會找不到要更新的
項目；這時請指定改版公告提到的寶石名稱，或要求更新超過 N 天的寶石。

在其他 AI 應用中，`status` 與 `update` 是 `pobg` server 提供的 prompt（Claude Desktop 的「+」選單、VS Code 的
`/pobg.status`、Gemini CLI 的斜線指令）；`update-pob` 則要在終端機執行。每個範圍的請求數與其他注意事項見
[docs/data.zh-TW.md](docs/data.zh-TW.md#指令)。

## 限制

- 資料是快照（寶石 2026-11-10；裝備、名詞解釋、天梯 2026-11-11）。平衡改版會改數字；`/pobg:status` 顯示新舊，
  `/pobg:update` 更新。
- POBG 檢查每個名稱是否存在並引用其資料，不判斷流派強不強，也不計算傷害；數字由 PoB 計算。
- 詞綴是隨機的：回答中的裝備是要找的目標，不代表一定拿得到。
- 天賦路線是夠好的路線，不保證最短；不規劃武器組天賦點與珠寶。
- 天梯比較用的是抽樣：數種排行各取前段，共約 600 個角色。
- 不包含：製作、通貨、出現權重、終局物品，以及少數基底與元技能寶石（[細節](docs/data.zh-TW.md#資料來源與使用範圍)）。

## 資料來源與授權

**程式碼**以 MIT License 釋出（見 `LICENSE`）。`data/` 內的**資料**不適用 MIT：

- Path of Exile 2 的內容屬於 Grinding Gear Games。
- poe2db.tw 的內容依照 poe2db 在其 [General disclaimer](https://poe2db.tw/us/General_disclaimer)
  頁面的聲明使用（2026-11-11 讀取）：「Wikis Content is available under CC BY-NC-SA 3.0 unless
  otherwise noted.」也就是要標示出處、不得商業使用，衍生資料須以相同授權分享。每筆紀錄都保留 poe2db 來源網址作為出處標示。
- 天賦樹與 PoB 的任務資料取自 PathOfBuilding-PoE2（MIT）。
- 天梯快照取自 poe.ninja，不保存角色或帳號名稱。

只有在有人執行更新時才會抓取資料，請求會表明身分並在每次請求之間等待；所有網址列在
[docs/data.md](docs/data.zh-TW.md#資料來源與使用範圍)。若要再利用這些資料，請遵循上述條款而非 MIT。本專案與上述各方
無隸屬關係，也未獲其背書。如果你是上述網站的維護者，希望本專案調整使用資料的方式，請開 issue。

## 給開發者

| 文件 | 內容 |
|---|---|
| [docs/clients.zh-TW.md](docs/clients.zh-TW.md) | 各 MCP 用戶端的設定、測試狀態 |
| [docs/tools.zh-TW.md](docs/tools.zh-TW.md) | 18 個 MCP 工具與 prompt、`export_pob` 算了什麼 |
| [docs/data.zh-TW.md](docs/data.zh-TW.md) | 資料來源、更新範圍、完整抓取、開發與測試 |
| [docs/flow/commands.zh-TW.md](docs/flow/commands.zh-TW.md) | 四個指令的完整流程圖 |
| [docs/flow/system_flow.md](docs/flow/system_flow.md) | 系統與資料流程圖（英文） |
| [ROADMAP.md](ROADMAP.md)、[CHANGELOG](docs/changelog/CHANGELOG.md) | 後續規劃、版本變更 |
