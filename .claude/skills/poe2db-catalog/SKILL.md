---
name: poe2db-catalog
description: Use whenever the task involves Path of Exile 2 game data in this repo — answering a question about a gem or passive node, citing where a number came from, checking whether poe2db changed, or updating / re-scraping the data. Routes lookups through the entity index and the source catalog instead of model memory or a full re-crawl.
---

# poe2db catalog

The repo keeps a machine-readable description of poe2db.tw (`src/catalog/poe2db_sources.json`)
and an exact-match entity index (`data/catalog/entity_index.jsonl`). Use them; do not answer
PoE2 numbers from memory and do not re-crawl the whole site to refresh one gem.

This skill is for maintaining the data. To answer player questions or write build advice from
it, use the `poe2-advisor` skill (`skills/poe2-advisor/SKILL.md`) and the `pobg` MCP tools.

All commands run from the repo root; prefix them with `uv run` (after `uv sync`) or activate
`.venv` first.

## 0. Prefer the MCP tools

When the `pobg` MCP server is connected (start Claude Code with `claude --plugin-dir .` in this
repo, or install the plugin), use its tools instead of the
commands below: `lookup_entity`, `get_gem`, `get_passive`, `passives_with_stat`,
`explain_keyword`, `gems_by`, `supports_for`, `path_to`, `refresh_gem`. They return records
with source URLs.
Without MCP, the same functions are in `src/tools/lookup.py` (`LookupService`).

To see how old the data is or to update one data set from an AI client, use the `status` and
`update` skills (`skills/status`, `skills/update`; tools `data_status`, `update_data`). The
commands below are the terminal route, needed for a full crawl and for the glossary.

## 1. Look something up

```bash
python -m src.catalog.entity_index find "躍擊"            # or "Leap Slam", "resolute technique"
python -m src.catalog.entity_index find "herald" --kind spirit_gem
```

Each hit gives `slug`, `kind`, `name_en`, `name_zh_tw`, `url_en`, `url_zh_tw`, `record_file`,
`record_key`, `match_type` (exact > prefix > substring). For the full record:

```python
from src.catalog import EntityIndex
idx = EntityIndex.load()
hit = idx.find("Leap Slam", kind="skill_gem")[0]
rec = idx.record(hit)          # the JSONL record: tier, cost, level_effects, quality_effects, fetched_at ...
```

Answer rules:
- Quote the record, then cite `url_en` (and `url_zh_tw` when answering in Chinese) plus `fetched_at`.
- If `find` returns nothing, say so; try the other language or a `--kind` filter before giving up.
- Passive nodes of kind `passive_ascendancy` have no poe2db page (`url_en` is null); say the name comes from PoB2.

## 2. Explain a field correctly

Field semantics live in the catalog's `fields` block (`Spec.field(kind, name)`); the traps list
is `traps`. The ones that bite most often:

| Field | Meaning |
|---|---|
| `tier` | Different scale per kind: skill 1–13 (odd), spirit 4/8/14, support 1–5. Never compare across kinds. |
| `cost` | Skill: flat range like `(14 — 97) Mana`. Spirit: `30 Spirit` reservation. Support: `Mana: 110%` is a multiplier, not a cost. |
| `level_effects` | Per-level rows keyed by the page's column headers; use them for "at level N" questions. |
| `extra_properties` vs `hidden_stats` | Visible tooltip lines vs internal stat ids (`is area damage [1]`); hidden ones explain mechanics but are not shown to players. |
| `requires_level` | `[a, b]` across gem levels; a fixed-level gem is `[65, 65]`. |
| `parse_warnings` | Non-empty means part of the record was backfilled; mention it if it matters. |

## 3. Before touching the scraper: probe

```bash
python -m src.catalog.probe            # exit 1 + [WARN] lines on drift; metrics in output/metrics/latest_catalog_probe.json
```

If it reports drift, the fix is a catalog edit (`poe2db_sources.json`: selector, section id,
`expect_min`) plus a fixture update under `tests/fixtures/html/`, then `pytest tests/unit`.

## 4. Update data after a patch (incremental, not a full crawl)

```bash
python -m src.scrapers.collect_gems --kind all --changed-only        # 3 listing requests + only new/changed gems
python -m src.scrapers.collect_gems --kind skill --slugs Leap_Slam    # a specific gem the patch notes mention
python -m src.scrapers.collect_gems --kind all --older-than 30        # refresh anything older than 30 days
python -m src.catalog.entity_index build                              # then rebuild the index (uses cached /tw/ pages)
```

`--changed-only` re-fetches a gem when it is new, its listing row (name / tier / tags) changed,
its stored record is broken, or it was named with `--slugs`; gems that left the listing are
dropped. A balance patch that only changes numbers does not change the listing row, so after
patch notes use `--slugs` for the gems named there, or `--older-than` to sweep.
A full crawl (`--kind all`, ≈1,000 pages at 0.8 s) is only for the first run or after a markup
change. `--limit` is a smoke run and requires an explicit `--out-dir`.
Every fetched detail page is cached under `output/cache/detail/en/<slug>.html`; after a parser
fix run `collect_gems --kind all --from-cache` to re-parse without touching the site.

To refresh Traditional Chinese names, delete `output/cache/tw/` before `entity_index build`.

## 5. Passive tree, stats and glossary

```bash
python -m src.scrapers.collect_passives     # PoB2 tree.json (structure) + poe2db cards (slugs, zh-TW, keywords)
python -m src.kg.stats                      # stat families for "which passives give X" (en + zh-TW)
python -m src.scrapers.collect_glossary     # keyword explanations (hover snippets, en + zh-TW)
python -m src.kg.build_graph                # knowledge graph: SUPPORTS, MENTIONS, GIVES_STAT, STARTS_AT ...
```

Small / attribute nodes have no poe2db page; cite the PoB2 tree (`pob2_tree` in the catalog)
for them. "Which passives give X" answers list nodes with a page first and summarise the rest.
When the probe says a newer PoB2 tree exists, bump `pob2_tree.version` in the catalog and rerun
`collect_passives`.

## Files

- `src/catalog/poe2db_sources.json` — the catalog (selectors, ids per language, fields, traps)
- `docs/flow/system_flow.md` — how the pieces connect
