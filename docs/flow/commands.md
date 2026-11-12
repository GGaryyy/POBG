# Command flows

**English** | [繁體中文](commands.zh-TW.md)

POBG has four commands in Claude Code. This document draws the whole route of each one, from
what you type to where it ends: which tools are called, where a decision is made, what makes it
stop, and when data is written.

| Command | Purpose | Uses the network | Writes anything |
|---|---|---|---|
| [`/pobg:poe2-advisor`](#pobgpoe2-advisor-a-cited-build-answer) | Answers PoE2 questions, writes cited builds and PoB codes | No | No |
| [`/pobg:status`](#pobgstatus-how-old-is-the-data) | Record counts and age of each data set | Only when you agree to check the live sites (about 19 requests) | No |
| [`/pobg:update <scope>`](#pobgupdate-scope-update-one-data-set) | Re-fetches one data set | Yes | Yes, to `data/` after validation |
| [`/pobg:update-pob <folder>`](#pobgupdate-pob-folder-update-your-path-of-building) | Updates the Path of Building on your computer | Yes (GitHub) | Only a new folder next to the old one |

In other AI apps `status` and `update` are prompts of the `pobg` server and the build workflow
is the `build_guide` prompt or the `build_workflow` tool, with the same steps; `update-pob` is
the same program run from a terminal.

Legend: a box is an action, a diamond is a decision, a rounded box is a start or an end.

## `/pobg:poe2-advisor`: a cited build answer

You do not run it yourself: it is applied automatically when you ask Claude Code a PoE2 question
or ask for a build. The steps come from
[`src/tools/build_workflow.py`](../../src/tools/build_workflow.py). The whole route reads local
data only: no network, no file written.

```mermaid
flowchart TD
    A(["The player asks for a build"]) --> B["Apply the workflow<br/>poe2-advisor skill, build_guide prompt<br/>or build_workflow tool"]
    B --> C["Step 2: gather candidates from the data<br/>lookup_entity, gems_by, supports_for,<br/>passives_with_stat, get_gem, get_passive"]
    C --> C2["Gear: items_by, get_item for a base or unique<br/>modifiers_for for target modifiers<br/>at most 3 prefixes + 3 suffixes per item"]
    C2 --> C3["Every choice needs a reason from the records<br/>never 'ladder characters use it'"]
    C3 --> D["Step 3: verify_build<br/>all gems, passives, items and target modifiers at once"]
    D --> E{"Any unverified<br/>names?"}
    E -- "yes, fewer than two rounds done" --> F["Step 4: drop the name, or replace it<br/>from its suggestions or a new search"]
    F --> D
    E -- "still some after two rounds" --> G["Drop what is still unverified"]
    G --> H
    E -- "none" --> H["Step 5: path_to<br/>class or ascendancy + verified passives<br/>returns route, order and points"]
    H --> I{"over: more than<br/>123 points or 8 ascendancy?"}
    I -- "yes" --> J["Drop the passives with the largest added_points"]
    J --> H
    I -- "no" --> K["Step 6: reference_builds<br/>reads the ladder snapshot, only to describe differences<br/>no character names"]
    K --> L["Step 7: write the answer<br/>numbers, costs, tags and effects from verified facts only<br/>target modifiers are goals, damage is not calculated"]
    L --> M["Step 8: end with sources_markdown<br/>unchanged, it lists the removed names"]
    M --> N["Step 9: export_pob<br/>class, targets, skill groups, gear, asked level"]
    N --> O{"Attributes or Spirit:<br/>need above have?"}
    O -- "yes, fixable" --> P["Other gems, fewer persistent skills or Spirit-reserving<br/>supports, attribute or Spirit modifiers on gear"]
    P --> N
    O -- "yes, not fixable" --> Q2["Say plainly what is missing"]
    Q2 --> Q
    O -- "no" --> Q["The answer shows: the code, how_to_import, notes,<br/>not_exported, attributes and Spirit,<br/>PoB Configuration options with their evidence"]
    Q --> R(["The player pastes the code into PoB<br/>Import/Export Build, paste, Import"])
```

### What `export_pob` works out

Character level, gem levels, attributes, Spirit and Configuration come from the data; the model
does not work them out.

```mermaid
flowchart TD
    A(["export_pob input<br/>class or ascendancy, targets, skill groups, gear<br/>optional: character_level, attribute, config"]) --> B["Passive route: path_to<br/>an ascendancy PoB has no id for is dropped and the route made again"]
    B --> C["Skill groups: each name is checked<br/>a support must be able to support the skill"]
    C --> D["Gear: bases and uniques against the local data<br/>a rare's modifiers must be whole modifiers the class can roll<br/>3 prefixes + 3 suffixes, one per family<br/>values at the upper end of the best tier, PoB's off-hand rules"]
    D --> X["Names, supports and modifiers that fail<br/>stay out of the code and go to not_exported"]
    D --> E{"character_level<br/>given?"}
    E -- "yes" --> F["Use that level<br/>note it when the points need a higher one"]
    E -- "no" --> G["Points spent, through PoB's level formula and act table<br/>123 points is level 100"]
    F --> H
    G --> H["Gem levels: the highest level-table row the<br/>character level allows, at most 20, supports have no level"]
    H --> I["Attributes<br/>need = the highest of: each skill gem's requirement,<br/>the supports' +N summed, the highest gear requirement<br/>have = class base + fixed attributes on passives and gear"]
    I --> J["Attribute passives on the route<br/>cover the requirements first, or follow attribute"]
    J --> K["Spirit<br/>need = (persistent skill's reservation + supports' extra) x multipliers<br/>have = every Spirit quest reward + a sceptre's base Spirit +<br/>fixed Spirit on gear and passives<br/>range-only or missing reservations go to unknown"]
    K --> L{"config on?<br/>(default on)"}
    L -- "no" --> N
    L -- "yes" --> M["Each option needs evidence in the build<br/>charges it gains, enemy states it inflicts<br/>Shock, Chill, Ignite: a damaging skill of that element,<br/>or an attack build's main-hand weapon<br/>a 'cannot' line rules it out for its skill group<br/>Exposure, Crit Recently"]
    M --> N["Written as PoB's XML<br/>Build, Tree, Skills, Items, Config, Notes"]
    N --> O["zlib, then urlsafe base64"]
    O --> P(["Returns code, how_to_import, notes,<br/>not_exported, summary<br/>no file written, no request made"])
```

## `/pobg:status`: how old is the data

From [`skills/status/SKILL.md`](../../skills/status/SKILL.md) and `status` / `online_check` in
`src/tools/maintenance.py`. This command never calls `update_data`.

```mermaid
flowchart TD
    A(["/pobg:status"]) --> B["data_status<br/>reads local files only, no network"]
    B --> C["Per data set: records, fetch time, age in days,<br/>and which update scope refreshes it"]
    C --> D["Point out what is old<br/>including the ladder snapshot and its league"]
    D --> E{"Ask the user:<br/>check the live sites?"}
    E -- "no" --> J
    E -- "yes" --> F["data_status check_online=true<br/>about 19 requests, 0.8 s apart"]
    F --> G["poe2db: do the pages of each kind<br/>still parse the way the catalog expects"]
    F --> H["GitHub: is there a newer<br/>PathOfBuilding-PoE2 passive tree version"]
    G --> I["Report problems"]
    H --> I
    I --> J{"Anything that<br/>should be updated?"}
    J -- "yes" --> K(["Name the command:<br/>/pobg:update with one scope"])
    J -- "no" --> L(["Done"])
```

A newer passive tree **version** is reported by status but not adopted by `update`; that needs a
new release of POBG.

## `/pobg:update <scope>`: update one data set

From [`skills/update/SKILL.md`](../../skills/update/SKILL.md) and `update` in
`src/tools/maintenance.py`. One scope per command; there is no "update everything". Every
request identifies itself (`POBG/0.10`) and waits 0.8 s before each page or file (0.3 s before a
hover snippet).

### Overview: the scope first

```mermaid
flowchart TD
    A(["/pobg:update scope names"]) --> B{"Is the first word one<br/>of the seven scopes?"}
    B -- "no, or missing" --> C(["update_data is not called<br/>the user is asked to pick a scope"])
    B -- "yes" --> D["update_data<br/>arguments checked: at most 40 names"]
    D --> E{"Is an update, refresh or<br/>online check already running<br/>on this data folder?"}
    E -- "yes" --> F(["Reports busy, try again later<br/>nothing written"])
    E -- "no" --> G{"Which scope?"}
    G -- "skill_gems, spirit_gems, support_gems" --> H["Gem flow"]
    G -- "passives" --> I["Passive tree flow"]
    G -- "items" --> J["Items flow"]
    G -- "glossary" --> K["Glossary flow"]
    G -- "ladder" --> L["Ladder flow"]
    H --> M["After writing, the name index is rebuilt<br/>the server reloads the data outside the lock"]
    I --> M
    J --> M
    K --> M
    L --> M
    M --> N(["The same conversation sees the new data"])
```

When any call returns an error, the error is shown and the command stops; it never tries another
scope. The update changes the copy of `data/` the server runs from.

### `skill_gems`, `spirit_gems`, `support_gems`

```mermaid
flowchart TD
    A(["The scope is one of the three gem kinds<br/>optionally gem names, or 'older than N days'"]) --> B["update_data dry_run=true<br/>fetches the listing page: 1 request"]
    B --> C["Select the gems to fetch<br/>new, changed on the listing,<br/>named by you, older than N days"]
    C --> C2["A gem fetched in the last 15 minutes is not fetched again"]
    C2 --> D["Tell the user: selected, reasons,<br/>added, removed"]
    D --> E{"selected<br/>is 0?"}
    E -- "yes" --> F(["This data set is up to date, stop"])
    E -- "no" --> G{"selected<br/>above 60?"}
    G -- "yes" --> H{"User confirms?<br/>one request per gem"}
    H -- "no" --> F2(["Stop, nothing written"])
    H -- "yes" --> I
    G -- "no" --> I["update_data dry_run=false<br/>at most 20 gems per call, 40 at most<br/>0.8 s between pages"]
    I --> J{"Pages still parse and<br/>pass validation?"}
    J -- "no" --> K(["Stops, nothing is written<br/>suggests status with the online check"])
    J -- "yes" --> L["Writes that gem kind's data file<br/>a single page that fails to download is skipped<br/>and picked up next time"]
    L --> M{"left above 0 and<br/>fewer than 10 calls?"}
    M -- "yes" --> I
    M -- "no" --> N(["Report updated, added, removed, skipped"])
```

- A balance patch that only changes numbers does not change the listing page, so a plain update
  gets `selected` = 0. Name the gems from the patch notes, or ask for gems older than N days.
- poe2db lists every spirit gem among the skill gems too; such a gem is stored once and updated
  by `spirit_gems`.

### `passives`

```mermaid
flowchart TD
    A(["The scope is passives<br/>no other argument"]) --> B["One call, 8 requests"]
    B --> C["GitHub: PathOfBuilding-PoE2 tree.json<br/>nodes, connections, class starts, ascendancies"]
    B --> D["GitHub: QuestRewards.lua<br/>PoB's act table for the level, Spirit quest rewards"]
    B --> E["poe2db: tree data files data_us, data_tw<br/>Chinese name and stats of every node"]
    B --> F["poe2db: Keystone and Notable listings<br/>English and Chinese, 4 pages"]
    D --> D2{"QuestRewards<br/>downloaded?"}
    D2 -- "no" --> D3["The tree is still updated<br/>build codes fall back for the level, with a note"]
    D2 -- "yes" --> G
    D3 --> G
    C --> G["Build nodes, edges and classes.json"]
    E --> G
    F --> G
    G --> H{"Validation<br/>passes?"}
    H -- "no" --> I(["Stops, nothing written"])
    H -- "yes" --> J["Writes nodes, edges, classes.json<br/>rebuilds the stat index and the name index"]
    J --> K(["Report records, changed, added, removed<br/>and the tree versions"])
```

### `items`

```mermaid
flowchart TD
    A(["The scope is items<br/>optionally item class names such as Bows"]) --> B["Decide the pages<br/>all: 69 class pages in two languages = 138 requests<br/>named classes: only those and their attribute pages"]
    B --> C["update_data<br/>at most 20 requests this call<br/>10 class pages in both languages, about 600 KB each"]
    C --> D["Progress is kept under output/cache for 30 minutes<br/>an interrupted run continues"]
    D --> E{"done: every<br/>page fetched?"}
    E -- "no, fewer than 8 calls" --> C
    E -- "no, 8 calls made" --> F(["Ask the user to run the command again within 30 minutes<br/>nothing written so far"])
    E -- "yes" --> G["Parse bases, uniques and the modifier data in the page<br/>align English and Chinese, compute tiers"]
    G --> H{"Counts and modifier<br/>data pass the checks?"}
    H -- "no" --> I(["Stops, nothing written"])
    H -- "yes" --> J["Writes bases, uniques and modifiers together<br/>merged with the existing data when only some classes"]
    J --> K(["Report bases, uniques, modifiers"])
```

### `glossary`

```mermaid
flowchart TD
    A(["The scope is glossary<br/>no other argument"]) --> B["update_data<br/>at most 50 requests this call, under a minute"]
    B --> C["Terms are found through the listings and a few gem pages<br/>then each term's English and Chinese hover snippet<br/>about 750 requests in all"]
    C --> D{"Five network errors<br/>in a row?"}
    D -- "yes" --> E(["This call gives up, progress is kept"])
    D -- "no" --> F{"done: the whole<br/>glossary fetched?"}
    F -- "no, fewer than 20 calls" --> B
    F -- "no, 20 calls made" --> G(["Ask the user to run the command again within 30 minutes<br/>it continues where it stopped"])
    F -- "yes" --> H{"At least 90% of the known terms reached,<br/>Chinese text for at least 50% of those that had it?"}
    H -- "no" --> I(["Not written"])
    H -- "yes" --> J["Merged field by field and written at once<br/>terms it could not reach keep their previous text"]
    J --> K(["Report records, refreshed, changed,<br/>added, kept_without_refresh"])
```

### `ladder`

```mermaid
flowchart TD
    A(["The scope is ladder<br/>no other argument"]) --> B["One call, at most 14 requests to poe.ninja<br/>0.8 s apart"]
    B --> C["Reads the current league and the top 100 of several sort orders<br/>about 600 characters"]
    C --> D["Keeps class, level, main skill, gems,<br/>keystones, league, rank<br/>character and account names are discarded before writing"]
    D --> E{"Does the snapshot look right?<br/>at least 100 rows, 90% with a class, half with a skill,<br/>same league: not below half the previous one"}
    E -- "no" --> F(["Refused, the old snapshot stays"])
    E -- "yes" --> G["Replaces the ladder snapshot"]
    G --> H(["Report records and league<br/>and previous_league when the league changed"])
```

## `/pobg:update-pob <folder>`: update your Path of Building

From [`skills/update-pob/SKILL.md`](../../skills/update-pob/SKILL.md) and
`src/tools/pob_update.py`. Only the user can start this command; the model cannot run it on its
own. It is not an MCP tool: it runs `python -m src.tools.pob_update` from the plugin's folder.

```mermaid
flowchart TD
    A(["/pobg:update-pob folder"]) --> B{"Was a folder given?"}
    B -- "no" --> C(["Ask for it and stop<br/>the disk is never searched"])
    B -- "yes" --> D{"Does the path contain a double quote,<br/>a backtick or a dollar sign?"}
    D -- "yes" --> E(["Nothing is run<br/>rename the folder or run the command yourself"])
    D -- "no" --> F["First run: --check<br/>2 requests to GitHub, writes nothing"]
    F --> G["Recognise the folder<br/>manifest.xml: Path of Building alone<br/>PoeCharm3.exe: PoeCharm2 with PoB inside"]
    G --> H["Report installed and latest<br/>for PoeCharm2 also its latest commit and date"]
    H --> I{"up_to_date?"}
    I -- "yes" --> J(["Already current, stop"])
    I -- "no" --> K["Explain what the update does<br/>downloads PoB's release, about 380 MB, checked against SHA-256<br/>PoeCharm2 also about 30 MB, no published checksum<br/>unpacks into a new folder next to the old one"]
    K --> L{"User agrees?"}
    L -- "no" --> M(["Stop, nothing downloaded"])
    L -- "yes" --> N["Second run: without --check<br/>can take minutes, 10-minute timeout"]
    N --> O["Downloads into a temporary work folder<br/>never more than the published size"]
    O --> P{"SHA-256 matches what<br/>GitHub publishes?"}
    P -- "no" --> Q(["Error, work folder removed<br/>the old folder is unchanged"])
    P -- "yes" --> R["Unpacks<br/>refuses paths that leave the folder, bounds the unpacked size"]
    R --> S["Copies saved builds (Builds)<br/>and PoeCharm2's language setting<br/>Settings.xml is never opened or copied"]
    S --> T["Renames to the new folder<br/>retried 5 times if a virus scan blocks it"]
    T --> U(["Report new_folder, version,<br/>builds_copied, checksum, next<br/>the old folder is never changed or deleted, sign in again"])
```

- If the command is stopped part-way, a `.pobg-update-…` work folder may be left next to the old
  one; the next run removes it after an hour, or you can delete it.
- Once the new folder works, deleting the old one is up to you.
- The command for other AI apps or by hand: [docs/data.md](../data.md#updating-path-of-building).
