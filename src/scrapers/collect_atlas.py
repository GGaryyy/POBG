"""
collect_atlas.py — The atlas facts a build up to Tier 16 maps is planned against, from poe2db's
Waystones page (English and Traditional Chinese, 2 requests).

    python -m src.scrapers.collect_atlas            # fetch the two pages (cached)
    python -m src.scrapers.collect_atlas --offline  # cache only

The page holds every table in one response; the catalog names the tabs (`atlas.panes`, the
Chinese tab ids are Chinese):

- the waystone tiers and their area levels (Tier 1 = 65 ... Tier 16 = 80 in 0.5);
- the elemental resistance penalty by level;
- the waystone modifiers (prefix or suffix and their lines). The Chinese table lists the same rows
  in the same order, so rows join by place, checked by level and prefix / suffix.

Writes data/atlas/atlas.json and data/atlas/waystone_mods.jsonl. Nothing is written when the page
no longer parses into the catalog's minimums. Map bosses, the pinnacle fights and the atlas
passives are not collected.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Callable

import requests
from bs4 import Tag

from src.catalog.spec import Spec, load_spec
from src.scrapers.common import (
    atomic_write_text,
    cached_fetch,
    clean_text,
    fetch_html,
    make_soup,
    now_iso,
    slug_from_href,
    write_jsonl,
)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = BASE_DIR / "output" / "cache" / "atlas"
SOURCE = "atlas"
LANGS = ("en", "zh-tw")
TIER_IN_NAME = re.compile(r"(?:Tier|階級)\s*(\d+)")
FIRST_NUMBER = re.compile(r"-?\d+")
MINUS_SIGNS = str.maketrans({"−": "-", "–": "-", "—": "-"})      # poe2db may print a typographic minus
AFFIX_WORDS = {"prefix": "prefix", "suffix": "suffix", "前綴": "prefix", "後綴": "suffix"}
LINE_BREAK = "\n"

Fetcher = Callable[[str], str]


class AtlasBuildError(Exception):
    """The page did not give usable atlas tables; nothing is written."""


# ---------------------------------------------------------------------------
# PARSING
# ---------------------------------------------------------------------------


def _pane(soup, pane_id: str) -> Tag:
    pane = soup.find("div", id=pane_id)
    if pane is None:
        raise AtlasBuildError(f"the Waystones page has no {pane_id!r} tab")
    return pane


def parse_tiers(pane: Tag, level_label: str) -> tuple[list[dict], list[str]]:
    """[{tier, name, slug, area_level}] from the waystone item tab, in tier order, and the labels of
    the property lines shown with them ("Area Level"). The area level is the property with
    `level_label`, never another number."""
    out, labels = [], []
    for col in pane.select("div.col"):
        link = next((a for a in col.find_all("a", href=True) if a.get_text(strip=True)), None)
        if link is None:
            continue
        name = clean_text(link.get_text(""))
        tier, level = TIER_IN_NAME.search(name), None
        for prop in col.select("div.property"):
            label, _, value = clean_text(prop.get_text(" ")).partition(":")
            labels += [label.strip()] if label.strip() not in labels else []
            if label.strip() == level_label:
                level = _number(value)
        if tier is None or level is None:
            continue
        out.append({"tier": int(tier.group(1)), "name": name, "slug": slug_from_href(link["href"]), "area_level": level})
    return sorted(out, key=lambda row: row["tier"]), labels


def parse_penalty(pane: Tag) -> list[dict]:
    """[{level, penalty}] from the resistance penalty tab, by level."""
    out = []
    for row in pane.select("tbody tr"):
        cells = [clean_text(td.get_text(" ")) for td in row.find_all("td")]
        if len(cells) >= 2 and _number(cells[0]) is not None and _number(cells[1]) is not None:
            out.append({"level": _number(cells[0]), "penalty": _number(cells[1])})
    return sorted(out, key=lambda row: row["level"])


def parse_mods(pane: Tag) -> list[dict]:
    """[{level, affix, lines}] from the waystone modifier tab, in page order (rows without lines kept,
    so the two languages still line up by place)."""
    out = []
    for row in pane.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        affix = AFFIX_WORDS.get(clean_text(cells[1].get_text(" ")).casefold())
        out.append({"level": _number(cells[0].get_text(" ")), "affix": affix, "lines": cell_lines(cells[2])})
    return out


def cell_lines(cell: Tag) -> list[str]:
    """The lines of a table cell, split at <br>."""
    for br in cell.find_all("br"):
        br.replace_with(LINE_BREAK)
    return [line for line in (clean_text(part) for part in cell.get_text("").split(LINE_BREAK)) if line]


def parse_page(html: str, panes: dict[str, str]) -> dict:
    soup = make_soup(html)
    tiers, labels = parse_tiers(_pane(soup, panes["tiers"]), panes["area_level_label"])
    return {"tiers": tiers, "labels": labels,
            "penalty": parse_penalty(_pane(soup, panes["penalty"])),
            "mods": parse_mods(_pane(soup, panes["mods"]))}


def _number(text: str | None) -> int | None:
    match = FIRST_NUMBER.search((text or "").translate(MINUS_SIGNS))
    return int(match.group()) if match else None


# ---------------------------------------------------------------------------
# MERGING AND CHECKS
# ---------------------------------------------------------------------------


def merge(en: dict, zh: dict, spec: Spec, fetched_at: str) -> tuple[dict, list[dict]]:
    """The atlas facts and the modifier records, both languages joined."""
    source = spec.source(SOURCE)
    url_en, url_zh = spec.resolve_url(source["slug"], "en"), spec.resolve_url(source["slug"], "zh-tw")
    zh_names = {row["tier"]: row["name"] for row in zh["tiers"]}
    tiers = [{**row, "name_zh_tw": zh_names.get(row["tier"])} for row in en["tiers"]]
    atlas = {"tiers": tiers, "resistance_penalty": en["penalty"], "labels": {"en": en["labels"], "zh-tw": zh["labels"]},
             "url_en": url_en, "url_zh_tw": url_zh, "fetched_at": fetched_at}
    joined = len(en["mods"]) == len(zh["mods"])
    mods = []
    for index, row in enumerate(en["mods"]):
        if not row["lines"]:
            continue
        other = zh["mods"][index] if joined else None
        same = other is not None and (other["level"], other["affix"]) == (row["level"], row["affix"])
        # the id is the row's place on the page: it moves when poe2db adds a row
        mods.append({"id": f"waystone_{index + 1}", "affix": row["affix"], "level": row["level"],
                     "lines": row["lines"], "lines_zh_tw": other["lines"] if same else [],
                     "url_en": url_en, "url_zh_tw": url_zh, "fetched_at": fetched_at})
    return atlas, mods


def check(atlas: dict, mods: list[dict], spec: Spec) -> None:
    """Raise AtlasBuildError when the result is below the catalog's minimums or a stage tier is missing."""
    source = spec.source(SOURCE)
    expect = source["expect_min"]
    problems = []
    if len(atlas["tiers"]) < expect["tiers"]:
        problems.append(f"{len(atlas['tiers'])} waystone tiers (expected at least {expect['tiers']})")
    known = {row["tier"] for row in atlas["tiers"]}
    missing = [tier for tier in source["stage_tiers"] if tier not in known]
    if missing:
        problems.append(f"no waystone tier {', '.join(map(str, missing))} on the page (catalog atlas.stage_tiers)")
    levels = [row["area_level"] for row in atlas["tiers"]]
    if levels != sorted(levels) or len(set(levels)) != len(levels):
        problems.append("the waystone area levels do not rise with the tier")
    penalties = [row["penalty"] for row in atlas["resistance_penalty"]]
    if any(p > 0 for p in penalties) or penalties != sorted(penalties, reverse=True):
        problems.append("the resistance penalty is not zero or less and falling with the level")
    if len(atlas["resistance_penalty"]) < expect["penalty_rows"]:
        problems.append(f"{len(atlas['resistance_penalty'])} resistance penalty rows "
                        f"(expected at least {expect['penalty_rows']})")
    if len(mods) < expect["mods"]:
        problems.append(f"{len(mods)} waystone modifiers (expected at least {expect['mods']})")
    zh_ratio = sum(1 for m in mods if m["lines_zh_tw"]) / len(mods) if mods else 0
    if mods and zh_ratio < expect["zh_ratio"]:
        problems.append(f"only {zh_ratio:.0%} of the modifiers have Chinese lines (expected {expect['zh_ratio']:.0%})")
    if any(not m["affix"] for m in mods):
        problems.append("a waystone modifier is neither prefix nor suffix")
    if problems:
        raise AtlasBuildError("the Waystones page did not parse: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# COLLECTING AND WRITING
# ---------------------------------------------------------------------------


def collect(spec: Spec, *, fetch: Fetcher, cache_dir: Path = CACHE_DIR, offline: bool = False) -> dict:
    """{"atlas", "mods"}: both pages parsed, joined and checked."""
    source = spec.source(SOURCE)
    parsed = {}
    for lang in LANGS:
        url = spec.resolve_url(source["slug"], lang)
        html = cached_fetch(url, cache_dir / f"{source['slug']}.{lang}.html", fetch, offline=offline)
        if html is None:
            raise AtlasBuildError(f"{url} is not in the cache (offline)")
        parsed[lang] = parse_page(html, source["panes"][lang])
    atlas, mods = merge(parsed["en"], parsed["zh-tw"], spec, now_iso())
    check(atlas, mods, spec)
    return {"atlas": atlas, "mods": mods}


def write(spec: Spec, base_dir: Path, result: dict) -> None:
    source = spec.source(SOURCE)
    path = base_dir / source["atlas_file"]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(result["atlas"], ensure_ascii=False, indent=1) + "\n")
    write_jsonl(base_dir / source["mods_file"], result["mods"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect the waystone tiers, resistance penalty and waystone modifiers.")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    spec = load_spec()
    delay = spec.raw["robots"]["polite_delay_seconds"]
    if not args.offline:      # fetched_at says "now": the pages must be fetched now
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
    try:
        result = collect(spec, fetch=lambda url: fetch_html(url, delay=delay), cache_dir=CACHE_DIR, offline=args.offline)
    except (AtlasBuildError, requests.RequestException) as exc:
        print(f"nothing written: {exc}", file=sys.stderr)
        return 1
    write(spec, BASE_DIR, result)
    tiers = result["atlas"]["tiers"]
    print(f"{len(tiers)} waystone tiers (Tier {tiers[0]['tier']} = area {tiers[0]['area_level']} ... "
          f"Tier {tiers[-1]['tier']} = area {tiers[-1]['area_level']}), "
          f"{len(result['atlas']['resistance_penalty'])} resistance penalty rows, {len(result['mods'])} waystone modifiers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
