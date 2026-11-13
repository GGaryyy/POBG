# Data: sources, updates and development

**English** | [繁體中文](data.zh-TW.md)

Where POBG's data comes from, how it is fetched and kept current, and how to work on the code.
The player-facing overview is in the [README](../README.md).

## Commands

Two commands look after the data from inside the AI client. In Claude Code they are plugin
skills; every other client gets them as MCP prompts of the `pobg` server (the "+" menu in
Claude Desktop, `/pobg.status` in VS Code, slash commands in Gemini CLI). A third one updates
your Path of Building.

| Command | Claude Code | What it does |
|---|---|---|
| status | `/pobg:status` | Shows, per data set, how many records there are, when they were fetched and how old they are. On request it also checks the live sites (about 19 requests): do the pages still parse, is there a newer passive tree |
| update | `/pobg:update <scope> [names]` | Re-fetches **one** data set. Shows what would be fetched first, then updates it |
| update-pob | `/pobg:update-pob <folder>` | Updates your Path of Building (PoE2), alone or inside a PoeCharm2 folder, to the latest release. Checks versions first; after you agree, downloads into a **new folder** next to the old one |

`update` always needs a scope; there is no "update everything":

| Scope | Fetches | Requests per call |
|---|---|---|
| `skill_gems`, `spirit_gems`, `support_gems` | The listing page, then only gems that are new, changed on the listing, named by you, or older than N days | 1 + at most 20 gems (40 at most); repeated until nothing is left |
| `passives` | The PathOfBuilding-PoE2 tree and quest rewards (PoB's level table and Spirit rewards for exported codes), poe2db's two tree data files and four listing pages; the stat index is rebuilt | 8 |
| `items` | Gear bases, unique items and modifiers from the 69 item class pages (English and Chinese; gear, flasks, charms, jewels); add item class names (`Bows`, `Body Armours`) to update only those | At most 20 requests per call (10 class pages in both languages, about 600 KB each), 138 in all; repeated until done, and written only when every page is fetched and checked |
| `glossary` | Every glossary term (English and Chinese hover snippets), found through the listing pages and a few gem pages | At most 50 per call (under a minute), about 750 in all; repeated until done, and written only when the whole glossary has been fetched |
| `ninja` | A new poe.ninja snapshot of the current league: class, level, skills, keystones. No character or account names are kept | At most 14 |

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
  folder. A data set that has no local file yet needs a first crawl from a terminal (below).
- A glossary or items update keeps its progress under `output/cache/` for 30 minutes, so an
  interrupted one continues instead of starting over. Terms it cannot reach keep their previous text.
- A newer passive tree *version* is reported by status but not adopted by `update`; that needs
  a new release of this project.
- `refresh_gem` and `update` change the copy of `data/` the server runs from. In a plugin
  install that is the plugin's own folder, which a plugin update replaces; in a clone it shows
  up as a modified file in git.

### Updating Path of Building

`update-pob` is a Claude Code skill only. In any other client, or by hand, run the same program
from this folder:

```
uv run python -m src.tools.pob_update --dir "G:\POB\poe2\PoeCharm2-20250410" --check   # versions only
uv run python -m src.tools.pob_update --dir "G:\POB\poe2\PoeCharm2-20250410"           # update
```

It downloads Path of Building's release file (about 380 MB) and checks it against the SHA-256
GitHub publishes; a PoeCharm2 folder also gets the latest PoeCharm2 commit (no published
checksum). Saved builds and PoeCharm2's language setting are copied; `Settings.xml` is not,
because it holds your account login, so you sign in again. The old folder is never changed or
deleted.

## Sources and scope of use

The exact URL patterns live in [`src/catalog/poe2db_sources.json`](../src/catalog/poe2db_sources.json);
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
| PathOfBuilding-PoE2 | `https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding-PoE2/dev/src/TreeData/0_5/tree.json` and `…/dev/src/Data/QuestRewards.lua` (the probe also lists `https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/contents/src/TreeData?ref=dev`) | Passive tree structure: every node, connections, names, stats, keystone / notable flags, class starts, ascendancies, positions; PoB's act table for the character level and its Spirit quest rewards | 2 files when the passive tree is rebuilt |
| poe.ninja | `https://poe.ninja/poe2/api/data/index-state`, `https://poe.ninja/poe2/api/builds/{version}/search`, `https://poe.ninja/poe2/api/builds/dictionary/{hash}` | Ladder characters: class, level, main skill, gems, keystones, league, rank. Character and account names are discarded before anything is written | About 600 characters per snapshot (the top 100 of several sort orders): at most 14 requests, 0.8 s apart, when `update ninja` is run. The snapshot in this repo is from 2026-11-11, league "Runes of Aldur" |

How the requests are made:

- poe2db and GitHub requests identify themselves as
  `POBG/0.11 (+https://github.com/GGaryyy/POBG; research scraper)`, wait 0.8 s
  before every page or file (0.3 s before a hover snippet) and make at most three attempts.
  `refresh_gem` waits the same 0.8 s, one request at a time.
- poe2db's `robots.txt` disallows only `/*/marked` and `/*/markdown_history`; neither is
  requested. Individual passive node pages (1.2 MB each) are deliberately not crawled.
- The poe.ninja fetcher reads the endpoints the poe.ninja site itself uses (JSON, protobuf and a
  binary dictionary format). They are not a documented public API and their layout has changed
  before, so the fetcher refuses to write a snapshot that looks wrong. It sends the same
  identifying `User-Agent` and waits 0.8 s between requests.
- Snapshot in this repo: gems fetched 2026-11-10, glossary, ladder and items 2026-11-11, passive
  tree `0_5` (poe2db tree data `4.5`) with its quest rewards 2026-11-12. Every record returned by
  a tool states its own `fetched_at`.

Not collected: 103 bases (mostly Runeforged variants, and the Timeless Jewel) appear on no
modifier page, so `modifiers_for` cannot answer for them; thirteen gems on poe2db's meta gem page
(Cast on Death, Demon Magus …) are on no gem listing.

If you maintain one of these sites and want the project to change how it uses your data,
please open an issue.

## Full crawl from a terminal

Day to day, use the `status` and `update` commands. The terminal route is for a first full
crawl and for work on the collectors.

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

## Releasing

A release carries a zip for people who install POBG in Claude Desktop without git. It holds only
what the server needs (no tests, docs, plans or reports) and unpacks to a single `POBG` folder:

```bash
git archive --format=zip --prefix=POBG/ -o output/pobg-<version>.zip v<version> \
    .claude-plugin skills src data pyproject.toml uv.lock README.md README.zh-TW.md LICENSE install_claude_desktop.bat
gh release create v<version> output/pobg-<version>.zip --title "POBG <version>" --notes-file <notes>
```

The version is in `pyproject.toml`, `.claude-plugin/plugin.json`, `src/__init__.py`, `uv.lock` and the
`User-Agent` in `src/scrapers/common.py`.

## Development

```bash
uv sync
uv run pytest            # offline, synthetic fixtures only
uv run ruff check .
```

Layout: `src/catalog/` (source catalog, probe, entity index), `src/scrapers/` (collectors),
`src/kg/` (stat index, knowledge graph), `src/tools/` (lookup service, build tools, PoB export
and updater, pathing, data status and updates, the Claude Desktop installer, MCP server), `skills/` and `.claude-plugin/`
(Claude Code plugin), `data/` (the collected data), `docs/` (client guide, tools, flow diagrams,
plans, reports, changelog). See [`ROADMAP.md`](../ROADMAP.md) for what is next.
