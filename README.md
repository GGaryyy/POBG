# POBG — Path of Exile 2 data and build tools for AI assistants

**English** | [繁體中文](README.zh-TW.md)

POBG is an unofficial [Model Context Protocol](https://modelcontextprotocol.io) server and
Claude Code plugin. It lets an AI assistant look up accurate **Path of Exile 2** data, cite where
each fact came from, and give build advice in which every gem and passive has been checked
against that data — in English or Traditional Chinese.

The data is a local copy of [poe2db.tw](https://poe2db.tw) (gems, passive tree, glossary), the
[PathOfBuilding-PoE2](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2) passive
tree and a [poe.ninja](https://poe.ninja/poe2/builds) ladder snapshot. Every answer the tools
return carries the source URL and the date it was fetched, so the model quotes records instead
of guessing numbers from memory.

Not affiliated with Grinding Gear Games, poe2db.tw, PathOfBuilding or poe.ninja.

## What you can ask

Once the server is connected, ask your assistant things like:

- "What does Leap Slam cost at level 10, and which supports work with it?" / 「躍擊 10 等的消耗是多少？」
- "Which passives give attack speed?" / 「哪些天賦有攻擊速度？」
- "Explain Critical Hits." / 「解釋暴擊」
- "How many passive points does a Witch need to reach Blood Magic and Resolute Technique?"
- "What modifiers can a bow roll, and what are the attack speed tiers?" / 「弓能出哪些詞綴？」
- "What does Quill Rain do?" / 「驟雨之弦有什麼詞綴？」
- "Give me a fire Titan build" — every gem, passive, item and target modifier in the answer is
  checked against the data, names that do not exist are removed, and the answer ends with a source list.

## Install

Requirements: [uv](https://docs.astral.sh/uv/getting-started/installation/) on `PATH`. The
first start creates a Python environment from the versions pinned in `uv.lock`: four direct
dependencies (`mcp`, `networkx`, `requests`, `beautifulsoup4`), about 40 packages with
their own dependencies.

**Claude Code** (plugin: the MCP server plus the `/pobg:poe2-advisor` skill)

```
/plugin marketplace add GGaryyy/POBG
/plugin install pobg@pobg
```

**Any other MCP client** (Claude Desktop, Cursor, VS Code, Gemini CLI, Codex CLI, …): clone the
repo, then register a stdio server that runs

```
uv run --frozen --no-dev --directory /absolute/path/to/POBG python -m src.tools.mcp_server
```

For most clients that is this JSON:

```json
{
  "mcpServers": {
    "pobg": {
      "command": "uv",
      "args": ["run", "--frozen", "--no-dev", "--directory", "/absolute/path/to/POBG",
               "python", "-m", "src.tools.mcp_server"]
    }
  }
}
```

Config file locations, per-client formats, which clients were actually tested, and five
prompts to check that it works: **[docs/clients.md](docs/clients.md)**.

ChatGPT is not supported: it only connects to remote MCP servers, and this project runs
locally over stdio.

## Commands

Two commands look after the data from inside the AI client. In Claude Code they are plugin
skills; every other client gets them as MCP prompts of the `pobg` server (the "+" menu in
Claude Desktop, `/pobg.status` in VS Code, slash commands in Gemini CLI).

| Command | Claude Code | What it does |
|---|---|---|
| status | `/pobg:status` | Shows, per data set, how many records there are, when they were fetched and how old they are. On request it also checks the live sites (about 19 requests): do the pages still parse, is there a newer passive tree |
| update | `/pobg:update <scope> [names]` | Re-fetches **one** data set. Shows what would be fetched first, then updates it |
| advisor | `/pobg:poe2-advisor` | Not a data command: the instructions Claude Code follows to answer PoE2 questions and write cited builds. It is applied automatically |

`update` always needs a scope; there is no "update everything":

| Scope | Fetches | Requests per call |
|---|---|---|
| `skill_gems`, `spirit_gems`, `support_gems` | The listing page, then only gems that are new, changed on the listing, named by you, or older than N days | 1 + at most 20 gems (40 at most); repeated until nothing is left |
| `passives` | The PathOfBuilding-PoE2 tree, poe2db's two tree data files and four listing pages; the stat index is rebuilt | 7 |
| `items` | Gear bases, unique items and modifiers from the 69 item class pages (English and Chinese; gear, flasks, charms, jewels); add item class names (`Bows`, `Body Armours`) to update only those | At most 20 requests per call (10 class pages in both languages, about 600 KB each), 138 in all; repeated until done, and written only when every page is fetched and checked |
| `glossary` | Every glossary term (English and Chinese hover snippets), found through the listing pages and a few gem pages | At most 50 per call (under a minute), about 750 in all; repeated until done, and written only when the whole glossary has been fetched |
| `ladder` | A new poe.ninja snapshot of the current league: class, level, skills, keystones. No character or account names are kept | At most 14 |

Examples: `/pobg:update skill_gems`, `/pobg:update support_gems Fire Attunement, Brutality I`,
`/pobg:update items Bows`, "update the skill gems older than 30 days".

Good to know:

- A balance patch that only changes numbers does not change the listing page, so a plain
  update finds nothing. Name the gems from the patch notes, or ask for gems older than N days.
- If a page no longer parses, the update stops and nothing is written. A single page that
  cannot be downloaded is reported as skipped and picked up by the next update.
- A gem fetched in the last 15 minutes is not fetched again when you name it or ask for old
  gems, so repeating a command never fetches the same page twice in a row.
- poe2db lists every spirit gem among the skill gems too. Such a gem is stored once, as a
  spirit gem, so it is updated by `spirit_gems`.
- Only one update runs on a data folder at a time, also across two clients using the same
  folder. A data set that has no local file yet needs a first crawl from a terminal.
- A first full gem crawl is done from a terminal, see "Updating the data".
- A glossary or items update keeps its progress under `output/cache/` for 30 minutes, so an
  interrupted one continues instead of starting over. Terms it cannot reach keep their previous text.
- A newer passive tree *version* is reported by status but not adopted by `update`; that needs
  a new release of this project.
- The update changes the copy of `data/` the server runs from. In a plugin install a plugin
  update replaces it.

## Tools

| Tool | Answers |
|---|---|
| `lookup_entity` | name (English / 繁中) → entity, kind, both poe2db URLs |
| `get_gem`, `get_passive`, `explain_keyword` | one record with its sources |
| `passives_with_stat` | which passives give a stat |
| `gems_by` | gems by tag, tier, class, weapon, kind or free text |
| `supports_for` | every support gem that can support a skill |
| `reference_builds` | what ladder characters run (class, main skill, rank, gems, keystones — no character names); a build answer uses it to show how the generated build differs from the ladder, not to pick the build |
| `verify_build` | checks a draft build's gems, passives, items and target modifiers ("Rings: +#% to Fire Resistance": the whole modifier, at most 3 prefixes and 3 suffixes per item; a partial wording comes back with candidates); returns facts, removed names and a finished source list |
| `path_to` | which passives to allocate, in order, to reach target passives from a class start; points against the 123 / 8 limits and the route's stat totals (approximate route) |
| `get_item` | one gear base (properties, requirements, implicit) or unique item (its modifiers), with sources |
| `items_by` | bases and uniques by item class, kind, required level or text |
| `modifiers_for` | what an item class (or a base or unique's class) can roll: modifiers grouped by family, every tier's level and value range, prefix or suffix; also desecrated, essence, corrupted and socketable effects |
| `build_workflow` | the step-by-step workflow for a cited build answer, for clients that cannot use MCP prompts |
| `refresh_gem` | re-fetches one gem page from poe2db and replaces the local record |
| `data_status` | what the local data holds and how old it is; on request, a check of the live sites |
| `update_data` | re-fetches one data set (a scope is required: three gem kinds, passives, items, glossary, ladder), a bounded number of requests per call |

Prompts: `build_guide` (the build workflow), `status` and `update` (the commands above). Only
`refresh_gem` and `update_data` change anything; the other fifteen tools are marked read-only,
and of those only `data_status` can reach the network, when asked to check the live sites.

## Data sources and scope of use

The exact URL patterns live in [`src/catalog/poe2db_sources.json`](src/catalog/poe2db_sources.json);
this table is a summary of that file and of `src/fetch_poe_ninja_builds.py`. Nothing is fetched
on a schedule: data is fetched only when someone runs a collector or the `update` command,
normally after a game patch. A running server makes no network request unless `refresh_gem`,
`update_data` or the online check of `data_status` is called.

| Source | URL | What is taken | How much, how often |
|---|---|---|---|
| poe2db.tw English pages | `https://poe2db.tw/us/{slug}` — listings `Skill_Gems`, `Spirit_Gems`, `Support_Gems`, `Keystone`, `Notable`, and one page per gem | Gem name, tier, tags, cost, requirements, per-level table, quality, hidden stats, which supports fit; keystone / notable cards (stat lines, glossary links) | 5 listing pages + 1,012 gem pages (347 skill, 53 spirit, 612 support) on a full run, 0.8 s apart. An update run fetches the 3 gem listings and only the gems that changed. `refresh_gem` fetches one page on request |
| poe2db.tw Chinese pages | `https://poe2db.tw/tw/{slug}` — the same five listings | Traditional Chinese names of gems, keystones and notables | 5 pages, cached locally; re-fetched only when the cache is deleted |
| poe2db item class pages | `https://poe2db.tw/us/{slug}` and `https://poe2db.tw/tw/{slug}` for the 69 item class pages listed under `item_pages` (weapons, off-hands, armour by attribute type such as `Body_Armours_str_dex`, jewellery, belts, life and mana flasks, charms, jewels and the eight jewel pages that hold their modifiers) | Gear bases (properties, requirements, implicits), unique items (modifier text), and the modifier data the page embeds: every modifier the class can roll with its name, level, prefix / suffix, family and text, plus desecrated, essence, corrupted and socketable effects. Spawn weights are not stored | 138 pages (about 600 KB each), 0.8 s apart, when `update items` is run |
| poe2db hover snippets | `https://cdn.poe2db.tw/cache2/{lang}/Poe_Data_KeywordPopups_hover/{hash}` (`lang` = `us` / `tw`) and `…/Poe_Data_GemEffects_hover/{hash}` | Glossary explanations (357 terms, English + Chinese); gem hovers only to find the Chinese glossary links | About 1.2 KB each, 0.3 s apart, when the glossary is rebuilt |
| poe2db passive tree data | `https://poe2db.tw/data/passive-skill-tree/4.5/data_us.json` and `data_tw.json` (version read from `https://poe2db.tw/tw/passive-skill-tree/` and its script on `cdn.poe2db.tw/js/`) | Chinese name and stat lines of every passive node, class and ascendancy names, point limits | 2 files when the passive tree is rebuilt; the viewer page and script only when the probe checks for a new version |
| PathOfBuilding-PoE2 | `https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/src/TreeData/0_5/tree.json` (the probe also lists `https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/contents/src/TreeData?ref=dev`) | Passive tree structure: every node, connections, names, stats, keystone / notable flags, class starts, ascendancies, positions | 1 file when the passive tree is rebuilt |
| poe.ninja | `https://poe.ninja/poe2/api/data/index-state`, `https://poe.ninja/poe2/api/builds/{version}/search`, `https://poe.ninja/poe2/api/builds/dictionary/{hash}` | Ladder characters: class, level, main skill, gems, keystones, league, rank. Character and account names are discarded before anything is written | About 600 characters per snapshot (the top 100 of several sort orders): at most 14 requests, 0.8 s apart, when `update ladder` is run. The snapshot in this repo is from 2026-11-11, league "Runes of Aldur" |

How the requests are made:

- poe2db and GitHub requests identify themselves as
  `POBG/0.8 (+https://github.com/GGaryyy/POBG; research scraper)`, wait 0.8 s
  before every page or file (0.3 s before a hover snippet) and make at most three attempts.
  `refresh_gem` waits the same 0.8 s, one request at a time.
- poe2db's `robots.txt` disallows only `/*/marked` and `/*/markdown_history`; neither is
  requested. Individual passive node pages (1.2 MB each) are deliberately not crawled.
- The poe.ninja fetcher reads the endpoints the poe.ninja site itself uses (JSON, protobuf and a
  binary dictionary format). They are not a documented public API and their layout has changed
  before, so the fetcher refuses to write a snapshot that looks wrong. It sends the same
  identifying `User-Agent` and waits 0.8 s between requests.
- Snapshot in this repo: gems fetched 2026-11-10, glossary, ladder and items 2026-11-11, passive tree
  `0_5` (poe2db tree data `4.5`). Every record returned by a tool states its own `fetched_at`.

If you maintain one of these sites and want the project to change how it uses your data,
please open an issue.

## Updating the data

Day to day, use the `status` and `update` commands above. The terminal route below is for a
first full crawl and for work on the collectors.

```bash
uv sync                                           # once: adds pytest and ruff to .venv
uv run python -m src.catalog.probe                # is poe2db still shaped the way the catalog expects?
uv run python -m src.scrapers.collect_gems --kind all --changed-only   # 3 listings + changed gems only
uv run python -m src.scrapers.collect_passives && uv run python -m src.scrapers.collect_glossary
uv run python -m src.scrapers.collect_items      # 138 item class pages: bases, uniques, modifiers
uv run python -m src.catalog.entity_index build   # bilingual name index (reads gems, passives, glossary, items)
uv run python -m src.kg.stats && uv run python -m src.kg.build_graph
```

A full gem crawl (`collect_gems --kind all`, about 1,000 pages) is only needed for a first run
or after poe2db changes its markup. Page caches and probe metrics go to `output/` (git-ignored).

## Development

```bash
uv sync
uv run pytest            # offline, synthetic fixtures only
uv run ruff check .
```

Layout: `src/catalog/` (source catalog, probe, entity index), `src/scrapers/` (collectors),
`src/kg/` (stat index, knowledge graph), `src/tools/` (lookup service, build tools, pathing,
data status and updates, MCP server), `skills/` and `.claude-plugin/` (Claude Code plugin), `data/` (the collected
data), `docs/` (client guide, flow diagrams, changelog). See `ROADMAP.md` for what is next.

## Limits

- The data is a snapshot. Balance patches change numbers; check `fetched_at` (or run `status`)
  and use `update`, `refresh_gem` or the collectors.
- `refresh_gem` and `update` change the copy of `data/` the server runs from. In a plugin install that is
  the plugin's own folder, which a plugin update replaces; in a clone it shows up as a
  modified file in git.
- `path_to` returns a good route, not a proven shortest one, and does not model weapon-set
  passive points or jewels.
- `verify_build` checks that names exist and returns their facts. It does not judge whether a
  build is strong.
- The ladder is a sample (about 600 characters near the top of several rankings), not the
  whole ladder.
- Modifiers are random. `modifiers_for` lists what an item class *can* roll; build answers name
  target modifiers in order of importance, not what an item will have. Spawn weights, crafting,
  currency, damage and defence totals are not covered.
- 103 bases (mostly Runeforged variants, and the Timeless Jewel) appear on no modifier page, so
  `modifiers_for` cannot answer for them. Endgame items are not covered. Thirteen gems on
  poe2db's meta gem page (Cast on Death, Demon Magus …) are on no gem listing and are not
  collected.

## License

The **code** is released under the MIT License (`LICENSE`).

The **data** in `data/` is not covered by MIT:

- Path of Exile 2 content belongs to Grinding Gear Games.
- The poe2db.tw material is used under the terms poe2db states on its
  [General disclaimer](https://poe2db.tw/us/General_disclaimer) page (read 2026-11-11):
  "Wikis Content is available under CC BY-NC-SA 3.0 unless otherwise noted." That means
  attribution, non-commercial use, and sharing derived data under the same licence. Every
  record keeps its poe2db source URL as attribution.
- The passive tree structure comes from PathOfBuilding-PoE2 (MIT).
- The ladder snapshot comes from poe.ninja and stores no character or account names.

If you reuse the data, follow those terms rather than MIT. This project is not affiliated
with or endorsed by any of these parties.
