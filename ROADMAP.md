# Roadmap

## Goal

> Let an AI quickly find accurate Path of Exile 2 data, cite the source, and explain it.

The product is a local MCP server and a Claude Code plugin. The user's own AI client is the
interface; there is no web UI and no hosted service. The priority is that any MCP-capable
client connects without friction.

## Done

| Area | What exists |
|---|---|
| Source catalog | `src/catalog/poe2db_sources.json` describes every page, selector and field; `probe.py` detects drift before a crawl |
| Collectors | Gems (listing + detail, incremental updates), passive tree (PathOfBuilding-PoE2 structure + poe2db text), glossary (hover snippets), ladder snapshot (poe.ninja, no names), gear, flasks, charms and jewels (0.8.0: 1,762 bases, 434 uniques, 17,719 modifiers from 69 item class pages) |
| Bilingual index | English and Traditional Chinese names for gems, every passive node, classes, ascendancies and stat families |
| Knowledge graph | Stat index ("which passives give X"), supports ↔ skills, glossary mentions |
| Tools | Seventeen MCP tools: cited lookups, gear (`get_item`, `items_by`, `modifiers_for`), `verify_build` (gems, passives, items, target modifiers), `path_to` (passive route and point cost), `build_workflow`, `data_status`, `update_data` |
| Commands | `status` and `update <scope>` as plugin skills and MCP prompts: see how old the data is and re-fetch one data set at a time (three gem kinds, passives, items, glossary, ladder) from inside the AI client |
| Packaging | stdio MCP server started with `uv run`; Claude Code plugin with the `poe2-advisor` skill |
| Client readiness (0.7.0) | Tool annotations and titles, tool-only fallback for the workflow, portability tests, Windows launcher tested, client guide |

## Next (in this order, decided 2026-11-11)

The data covers gems, the passive tree, the glossary and (0.8.0) gear, flask, charm and jewel
bases, uniques and modifiers. Phase 1 is done; export to Path of Building is next.

| # | Phase | What | Why |
|---|---|---|---|
| 1 | Gear and modifier data (done in 0.8.0) | Equipment bases, modifiers and tiers (incl. desecrated, essence, corrupted, socketable effects), unique items, jewels, flasks and charms | Gear and its modifiers decide damage and defences; it changes every league |
| 1 | Gem and ascendancy gaps (checked in 0.8.0) | Lineage supports were already covered (77 of 77); socketables came with the modifiers; ascendancy pages add nothing the tree data lacks; 13 gems on the meta gem page are on no gem listing and were left out | Completes what a build can name |
| 2 | Export to Path of Building | A tool that turns a verified build (class, ascendancy, passive route from `path_to`, skill groups) into a Path of Building import code | The advice can be opened, checked and continued in PoB. The passive node ids are already PoB's |
| 3 | Crafting and currency | Crafting methods, currency, essences, catalysts, omens, liquid emotions | How to obtain the gear, after the gear itself is known |

Also open:

| Item | Why |
|---|---|
| Patch notes as an update signal | poe2db's version pages list the gems and uniques each patch changed; a plain `update` cannot see number-only changes |
| Confirm more clients | Cursor, VS Code, Gemini CLI and Codex CLI configurations are written from their docs but not tested |
| Remote transport | ChatGPT and other hosted clients only reach remote MCP servers. Needs a decision on hosting first |
| Ladder depth | The snapshot is about 600 characters from the top of several rankings; poe.ninja's layout is undocumented and has changed once already, so the fetcher needs watching |
| New passive tree versions | `status` reports a newer version, but adopting it needs a catalog change and a release; the 1.0 release will add classes, weapons and acts |
| One-click install for Claude Desktop | An `.mcpb` bundle, once its support for uv projects is verified |

Out of scope for the data: endgame mechanics, monsters, quests, lore and cosmetics.

## Not planned

A web UI, a hosted public instance, and the earlier local LangGraph / Ollama pipeline.

## Key decisions

| Decision | Choice | Reason |
|---|---|---|
| Source of truth | poe2db.tw pages described by a versioned catalog | Provenance per field; drift is detectable |
| Entity resolution | Exact alias index, no fuzzy matching | Deterministic, explainable, bilingual |
| Build advice | The model searches freely; only names verified by exact match may appear; the source list is rendered by code | Stops invented gems and passives |
| Passive routes | Steiner-tree approximation, stated as approximate | Exact answers are not computable at tree size |
| Scraping etiquette | 0.8 s before each page (from the catalog), identifying User-Agent, at most three attempts | Be a polite, identifiable client |
| Privacy | Ladder character and account names are never written or returned | Only build shape matters |
