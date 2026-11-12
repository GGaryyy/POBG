"""
collect_items.py — Gear bases, unique items and the modifiers each item class can roll, from
poe2db's item class pages (English + Traditional Chinese).

    python -m src.scrapers.collect_items             # every page in the catalog (about 138 requests)
    python -m src.scrapers.collect_items --offline   # re-parse the page cache only

One page per item class (e.g. /us/Bows) lists its bases and uniques as cards and embeds every
modifier the class can roll as a JSON object (`new ModsView({...})`). Armour modifiers live on
pages split by attribute type (Body_Armours_str_dex ...), which also list the bases using them.
Nothing is written unless every page parsed, every tab count matched, and the totals reach the
catalog's minimums. Modifier weights are not in the game files and are not stored.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests
from bs4 import BeautifulSoup, Tag

from src.catalog.spec import Spec, load_spec
from src.scrapers.common import (
    atomic_write_text,
    cached_fetch,
    clean_text,
    fetch_html,
    make_soup,
    now_iso,
    read_jsonl,
    safe_cache_name,
    slug_from_href,
    write_jsonl,
)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PAGE_CACHE_DIR = BASE_DIR / "output" / "cache" / "items"
LANGS = ("en", "zh-tw")
SOURCE = "item_pages"
EFFECT_SELECTOR = ".utilityMod, .enchantMod"   # what a charm grants when used; a jewel's fixed line
TITLE_SEPARATOR = " - "            # "Jewels - PoE2DB, Path of Exile Wiki"
TAB_COUNT_RE = re.compile(r"/\s*(\d+)\s*$")
LEVEL_RE = re.compile(r"Level\s+(\d+)")
ATTRIBUTE_RE = re.compile(r"(\d+)\s+(Str|Dex|Int)\b")
TAG_RE = re.compile(r'data-tag="([^"]+)"')
LINE_BREAK = "\n"          # between the stat lines of one modifier in its stored text
ATTRIBUTE_SUFFIXES = ("str", "dex", "int")
AFFIX_BY_GENERATION_ID = {"1": "prefix", "2": "suffix"}   # ModGenerationTypeID; `gen` names them per language
MIN_MOD_TEXT_RATIO = 0.95
NUMBER_RE = re.compile(r"[+\-]?\(?\d+(?:\.\d+)?(?:\s*[—–-]\s*\d+(?:\.\d+)?)?\)?")

Fetcher = Callable[[str], str]


class ItemCollectionError(Exception):
    """Raised when a collection run must not overwrite existing data."""


@dataclass
class ClassPage:
    """What one language version of a class page holds."""

    slug: str
    label: str | None = None        # the class name in the modifier object
    title: str | None = None        # the page title before " - ": the class name on pages without that object
    bases: list[dict] = field(default_factory=list)
    uniques: list[dict] = field(default_factory=list)
    mods: dict[str, list[dict]] = field(default_factory=dict)
    has_mod_object: bool = False


# ---------------------------------------------------------------------------
# PARSING ONE PAGE
# ---------------------------------------------------------------------------


def parse_class_page(html: str, spec: Spec, slug: str) -> ClassPage:
    """Bases, uniques and modifier groups of one class page, in the page's language.
    Raises ItemCollectionError when a tab's card count differs from the count in its title."""
    soup = make_soup(html)
    page = ClassPage(slug=slug)
    if soup.title:
        page.title = clean_text(soup.title.get_text("").split(TITLE_SEPARATOR)[0]) or None
    counts = _tab_counts(soup)
    for pane in soup.select("div.tab-pane[id]"):
        expected = counts.get(pane["id"])
        cards = pane.select("div.flex-grow-1")
        bases = [c for c in cards if c.select_one(":scope > a.whiteitem")]
        uniques = [c for c in cards if c.select_one("a.UniqueItem")]
        # A pane holding only bases (or only uniques) is a list; panes that mix kinds are references.
        if bases and len(bases) == len(cards) and not page.bases:
            _check_count(slug, pane["id"], len(bases), expected)
            page.bases = [_parse_base(card) for card in bases]
        elif uniques and len(uniques) == len(cards):
            _check_count(slug, pane["id"], len(uniques), expected)
            page.uniques += [_parse_unique(card) for card in uniques]
    mod_object = _mod_object(html, spec)
    if mod_object is not None:
        page.has_mod_object = True
        page.label = clean_text(make_soup(mod_object.get("baseitem", {}).get("link_name", "")).get_text(""))
        page.mods = _mod_groups(mod_object, spec)
    return page


def _tab_counts(soup: BeautifulSoup) -> dict[str, int]:
    """{pane id: N} from tab links whose text ends with '/N'."""
    counts: dict[str, int] = {}
    for link in soup.select("a.nav-link[href^='#']"):
        match = TAB_COUNT_RE.search(link.get_text(" ", strip=True))
        if match:
            counts[link["href"][1:]] = int(match.group(1))
    return counts


def _check_count(slug: str, pane: str, found: int, expected: int | None) -> None:
    if expected is not None and found != expected:
        raise ItemCollectionError(f"{slug}: tab {pane} lists {expected} items but {found} cards parsed; "
                                  "the page markup probably changed")


def _parse_base(card: Tag) -> dict:
    link = card.select_one("a.whiteitem")
    requirement = _text(card.select_one(".requirements"))
    return {
        "slug": slug_from_href(link.get("href")),
        "name": _text(link),
        "properties": [_text(p) for p in card.select(".property")],
        "requirements": requirement,
        "implicits": _mod_lines(card.select(".implicitMod")),
        "effects": [_text(m) for m in card.select(EFFECT_SELECTOR)],
    }


def _parse_unique(card: Tag) -> dict:
    """Two card layouts exist: the name in span.uniqueName inside the link, or (newer uniques) the
    link text itself with span.uniqueTypeLine next to it."""
    link = card.select_one("a.UniqueItem")
    name = link.select_one(".uniqueName")
    return {
        "slug": slug_from_href(link.get("href")),
        "name": _text(name) if name else (clean_text(link.find(string=True, recursive=False) or "")
                                          or clean_text(link.get_text("")) or None),
        "base": _text(card.select_one(".uniqueTypeLine")),
        "requirements": _text(card.select_one(".requirements")),
        "implicits": _mod_lines(card.select(".implicitMod")),
        "mods": _mod_lines(card.select(".explicitMod")),
    }


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    return clean_text(node.get_text("")) or None


def stat_lines(node: Tag) -> list[str]:
    """The stat lines of a modifier node. One modifier can hold several stats, separated by <br>
    on the page (e.g. "% increased Physical Damage" and "+# to Accuracy Rating"); each is its
    own line, as the game and Path of Building show it."""
    for text in node.find_all(string=True):          # a line break in the page source is not a new stat
        if LINE_BREAK in text:
            text.replace_with(text.replace(LINE_BREAK, " "))
    for br in node.find_all("br"):
        br.replace_with(LINE_BREAK)
    return [line for line in (clean_text(part) for part in node.get_text("").split(LINE_BREAK)) if line]


def _mod_lines(nodes: list[Tag]) -> list[str]:
    return [line for node in nodes for line in stat_lines(node)]


def _mod_object(html: str, spec: Spec) -> dict | None:
    match = re.search(spec.source(SOURCE)["mod_object_pattern"], html, re.S)
    if match is None:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ItemCollectionError(f"modifier object is not valid JSON: {exc}") from exc


def _mod_groups(mod_object: dict, spec: Spec) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for group in spec.source(SOURCE)["mod_groups"]:
        rows = mod_object.get(group) or []
        groups[group] = [_mod_row(row, group) for row in rows if isinstance(row, dict)]
    return groups


def _mod_row(row: dict, group: str) -> dict:
    name_soup = make_soup(str(row.get("Name") or ""))
    source = name_soup.select_one("a[href]")
    return {
        "group": group,
        "affix": AFFIX_BY_GENERATION_ID.get(str(row.get("ModGenerationTypeID"))),
        "name": clean_text(name_soup.get_text("")) or None,
        "source_slug": slug_from_href(source.get("href")) if source else None,
        "level": _int(row.get("Level")),
        "family": "+".join(row.get("ModFamilyList") or []) or None,
        "text": LINE_BREAK.join(stat_lines(make_soup(str(row.get("str") or "")))) or None,
        "tags": TAG_RE.findall(" ".join(str(t) for t in row.get("mod_no") or [])),
    }


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# JOINING LANGUAGES AND PAGES
# ---------------------------------------------------------------------------


def build_records(spec: Spec, pages: dict[str, dict[str, ClassPage]], fetched_at: str) -> tuple[dict, dict]:
    """Records for every output file plus a summary, from {slug: {lang: ClassPage}}."""
    page_meta = {p["slug"]: p for p in spec.source(SOURCE)["pages"]}
    summary: Counter = Counter()
    bases: dict[str, dict] = {}
    uniques: dict[str, dict] = {}
    modifiers: list[dict] = []
    classes: list[dict] = []
    for slug, meta in page_meta.items():
        en, zh = pages[slug]["en"], pages[slug].get("zh-tw")
        urls = {"url_en": spec.resolve_url(slug, "en"), "url_zh_tw": spec.resolve_url(slug, "zh-tw")}
        label = en.label or en.title or slug.replace("_", " ")
        label_zh = _zh_label(label, zh)
        _check_page(slug, meta["roles"], en)
        if "items" in meta["roles"]:
            for base in _join_by_slug(en.bases, zh.bases if zh else [], summary, "bases"):
                bases.setdefault(base["slug"], _base_record(base, (label, label_zh), slug, spec, fetched_at))
            for unique in _join_uniques(en.uniques, zh.uniques if zh else [], summary):
                record = _unique_record(unique, (label, label_zh), slug, spec, fetched_at)
                first = uniques.setdefault(record["slug"], record)
                if first is not record and first["item_page"] == slug:        # another version of the same unique
                    first.setdefault("variants", []).append(
                        {k: record[k] for k in ("base", "base_zh_tw", "implicits", "implicits_zh_tw", "mods", "mods_zh_tw")})
        if "mods" in meta["roles"]:
            rows = _join_mods(en.mods, zh.mods if zh else {}, summary)
            modifiers += [{"mod_page": slug, **row, "fetched_at": fetched_at} for row in _with_tiers(rows)]
            classes.append({"slug": slug, "label": label, "label_zh_tw": label_zh,
                            "group": meta["group"], "attributes": _attributes(slug),
                            "bases": [b["slug"] for b in en.bases], **urls})
    link(bases, uniques, classes)
    summary.update(pages=len(page_meta), bases=len(bases), uniques=len(uniques), modifiers=len(modifiers),
                   bases_without_mod_page=sum(1 for b in bases.values() if b["mod_page"] is None))
    records = {"bases": list(bases.values()), "uniques": list(uniques.values()), "modifiers": modifiers,
               "classes": {"fetched_at": fetched_at, "pages": classes}}
    return records, dict(summary)


def _zh_label(label: str, zh: ClassPage | None) -> str | None:
    """The Chinese class name: from the modifier object, or the page title where that object is
    missing or left in English (Charms)."""
    if zh is None:
        return None
    if zh.label and zh.label != label:
        return zh.label
    return zh.title or zh.label


def _join_uniques(en: list[dict], zh: list[dict], summary: Counter) -> list[dict]:
    """Like _join_by_slug, but a unique listed several times (versions on different bases) is
    joined by position among the cards of that slug."""
    by_slug: dict[str, list[dict]] = defaultdict(list)
    for row in zh:
        by_slug[row["slug"]].append(row)
    seen: Counter = Counter()
    out = []
    for row in en:
        versions = by_slug.get(row["slug"], [])
        other = versions[seen[row["slug"]]] if seen[row["slug"]] < len(versions) else None
        seen[row["slug"]] += 1
        summary["uniques_zh_missing"] += other is None
        out.append({**row, "zh": other})
    return out


def _check_page(slug: str, roles: list[str], page: ClassPage) -> None:
    """Every page must still yield what the catalog takes from it; one page quietly parsing to
    nothing would otherwise drop a whole item class."""
    if "items" in roles and not page.bases and not page.uniques:
        raise ItemCollectionError(f"{slug}: no bases or uniques parsed; the markup probably changed")
    if "mods" in roles and not page.has_mod_object:
        raise ItemCollectionError(f"{slug}: no modifier object on the page; the markup probably changed")
    if "mods" in roles and not page.mods.get("normal"):
        raise ItemCollectionError(f"{slug}: no normal modifiers parsed; the modifier object probably changed")


def link(bases: dict[str, dict], uniques: dict[str, dict], classes: list[dict]) -> None:
    """Point every base at the modifier page that lists it, and every unique at its base."""
    for base in bases.values():
        base["mod_page"] = None
    for page in classes:
        listed = [*page["bases"], page["slug"]]        # a jewel's modifiers are on the jewel's own page
        for base_slug in listed:
            if base_slug in bases and bases[base_slug]["mod_page"] is None:
                bases[base_slug]["mod_page"] = page["slug"]
    names = {b["name"]: b["slug"] for b in bases.values()}
    for unique in uniques.values():
        unique["base_slug"] = names.get(unique["base"])


def merge_records(spec: Spec, old: dict, fresh: dict, refreshed: list[str]) -> dict:
    """Old records with the refreshed pages replaced by the fresh ones: bases and uniques by the
    item page they came from (an item that left the page goes), modifiers by modifier page. An item
    listed on two pages keeps the record of the page that comes first in the catalog, as in a
    full run."""
    roles = {p["slug"]: p["roles"] for p in spec.source(SOURCE)["pages"]}
    order = [p["slug"] for p in spec.source(SOURCE)["pages"]]
    mod_pages = {slug for slug in refreshed if "mods" in roles[slug]}
    bases = _merge_items(old["bases"], fresh["bases"], set(refreshed), order)
    uniques = _merge_items(old["uniques"], fresh["uniques"], set(refreshed), order)
    pages = {p["slug"]: p for p in old["classes"]["pages"] if p["slug"] not in mod_pages}
    pages.update({p["slug"]: p for p in fresh["classes"]["pages"]})
    classes = sorted(pages.values(), key=lambda p: order.index(p["slug"]) if p["slug"] in order else len(order))
    link(bases, uniques, classes)
    rank = {slug: i for i, slug in enumerate(order)}
    modifiers = sorted([m for m in old["modifiers"] if m["mod_page"] not in mod_pages] + fresh["modifiers"],
                       key=lambda m: rank.get(m["mod_page"], len(order)))      # catalog order, as a full run writes
    return {"bases": list(bases.values()), "uniques": list(uniques.values()), "modifiers": modifiers,
            "classes": {"fetched_at": fresh["classes"]["fetched_at"], "pages": classes}}


def _merge_items(old: list[dict], fresh: list[dict], refreshed: set[str], order: list[str]) -> dict[str, dict]:
    rank = {slug: i for i, slug in enumerate(order)}
    kept = [r for r in old if r.get("item_page") not in refreshed]
    merged: dict[str, dict] = {}
    for record in sorted(kept + fresh, key=lambda r: rank.get(r.get("item_page"), len(order))):
        merged.setdefault(record["slug"], record)
    return merged


def read_records(spec: Spec, data_dir: Path) -> dict | None:
    """The stored item records, or None when any file is missing."""
    source = spec.source(SOURCE)
    paths = {key: data_dir / Path(source[f"{key}_file"]).relative_to("data") for key in ("bases", "uniques", "modifiers")}
    classes = data_dir / Path(source["classes_file"]).relative_to("data")
    if not classes.exists() or not all(p.exists() for p in paths.values()):
        return None
    return {**{key: read_jsonl(path) for key, path in paths.items()},
            "classes": json.loads(classes.read_text(encoding="utf-8"))}


def _join_by_slug(en: list[dict], zh: list[dict], summary: Counter, label: str) -> list[dict]:
    by_slug = {row["slug"]: row for row in zh}
    out = []
    for row in en:
        other = by_slug.get(row["slug"])
        summary[f"{label}_zh_missing"] += other is None
        out.append({**row, "zh": other})
    return out


def _join_mods(en: dict[str, list[dict]], zh: dict[str, list[dict]], summary: Counter) -> list[dict]:
    """The two languages list a group's modifiers in the same order; a group whose families or
    levels do not line up keeps English only, so no Chinese text is ever attached to the wrong row."""
    rows = []
    for group, en_rows in en.items():
        zh_rows = zh.get(group) or []
        aligned = len(zh_rows) == len(en_rows) and all(
            (a["family"], a["level"], a["affix"]) == (b["family"], b["level"], b["affix"]) for a, b in zip(en_rows, zh_rows))
        if en_rows and not aligned:
            summary["mod_groups_english_only"] += 1
        for i, row in enumerate(en_rows):
            other = zh_rows[i] if aligned else {}
            rows.append({**row, "name_zh_tw": other.get("name"), "text_zh_tw": other.get("text")})
    return rows


def modifier_template(text: str | None) -> str:
    """A modifier text with every number and range replaced by #, lower-cased: the form all tiers
    of one modifier share. One family can hold several modifiers (e.g. +# to Level of all Minion
    Skills / all Spell Skills), so tiers are counted per template, not per family."""
    return clean_text(NUMBER_RE.sub("#", (text or "").casefold()))


def _with_tiers(rows: list[dict]) -> list[dict]:
    """Tier 1 is the highest required level within (group, affix, family, template) on one page."""
    families: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        families[(row["group"], row["affix"], row["family"], modifier_template(row["text"]))].append(row)
    for members in families.values():
        ranked = sorted(members, key=lambda r: -(r["level"] or 0))
        for tier, row in enumerate(ranked, 1):
            row["tier"], row["tiers"] = tier, len(ranked)
    return rows


def _base_record(base: dict, labels: tuple[str, str | None], page: str, spec: Spec, fetched_at: str) -> dict:
    zh = base.pop("zh") or {}
    return {
        "slug": base["slug"], "name": base["name"], "name_zh_tw": zh.get("name"),
        "item_class": labels[0], "item_class_zh_tw": labels[1], "item_page": page,
        "properties": base["properties"], "properties_zh_tw": zh.get("properties", []),
        "implicits": base["implicits"], "implicits_zh_tw": zh.get("implicits", []),
        "effects": base["effects"], "effects_zh_tw": zh.get("effects", []),
        **_requirements(base["requirements"]), "mod_page": None,
        "url_en": spec.resolve_url(base["slug"], "en"), "url_zh_tw": spec.resolve_url(base["slug"], "zh-tw"),
        "fetched_at": fetched_at,
    }


def _unique_record(unique: dict, labels: tuple[str, str | None], page: str, spec: Spec, fetched_at: str) -> dict:
    zh = unique.pop("zh") or {}
    return {
        "slug": unique["slug"], "name": unique["name"], "name_zh_tw": zh.get("name"),
        "base": unique["base"], "base_zh_tw": zh.get("base"), "base_slug": None,
        "item_class": labels[0], "item_class_zh_tw": labels[1], "item_page": page,
        **_requirements(unique["requirements"]),
        "implicits": unique["implicits"], "implicits_zh_tw": zh.get("implicits", []),
        "mods": unique["mods"], "mods_zh_tw": zh.get("mods", []),
        "url_en": spec.resolve_url(unique["slug"], "en"), "url_zh_tw": spec.resolve_url(unique["slug"], "zh-tw"),
        "fetched_at": fetched_at,
    }


def _requirements(text: str | None) -> dict:
    level = LEVEL_RE.search(text or "")
    stats = {name.lower(): int(value) for value, name in ATTRIBUTE_RE.findall(text or "")}
    return {"requires_level": int(level.group(1)) if level else None, "requires": stats}


def _attributes(slug: str) -> list[str]:
    parts = slug.lower().split("_")
    return [p for p in parts if p in ATTRIBUTE_SUFFIXES]


# ---------------------------------------------------------------------------
# VALIDATION / RUN
# ---------------------------------------------------------------------------


def validate(records: dict, summary: dict, spec: Spec, partial: bool = False) -> None:
    """partial: only some pages were collected, so the catalog-wide minimum counts do not apply."""
    minimum = spec.source(SOURCE)["expect_min"]
    for key in ("bases", "uniques", "modifiers"):
        if not partial and summary[key] < minimum[key]:
            raise ItemCollectionError(f"only {summary[key]} {key} parsed, below expect_min={minimum[key]}")
    with_text = sum(1 for m in records["modifiers"] if m["text"])
    if with_text < MIN_MOD_TEXT_RATIO * len(records["modifiers"]):
        raise ItemCollectionError(f"only {with_text} of {len(records['modifiers'])} modifiers have text")
    for key in ("bases", "uniques"):
        named = [r for r in records[key] if r.get("name")]
        if len(named) != len(records[key]):
            raise ItemCollectionError(f"{len(records[key]) - len(named)} {key} have no name")
    zh = sum(1 for r in records["bases"] + records["uniques"] if r.get("name_zh_tw"))
    total = len(records["bases"]) + len(records["uniques"])
    summary["zh_name_ratio"] = round(zh / total, 3) if total else 0.0
    if summary["zh_name_ratio"] < minimum["zh_ratio"]:
        raise ItemCollectionError(f"only {summary['zh_name_ratio']:.0%} of bases and uniques have a Chinese name")
    mods = records["modifiers"]
    summary["modifier_zh_ratio"] = round(sum(1 for m in mods if m.get("text_zh_tw")) / len(mods), 3) if mods else 0.0
    if mods and summary["modifier_zh_ratio"] < minimum["zh_ratio"]:
        raise ItemCollectionError(f"only {summary['modifier_zh_ratio']:.0%} of modifiers have Chinese text; "
                                  "the Chinese pages probably no longer line up")


def collect(spec: Spec, fetch: Fetcher, *, cache_dir: Path | None = None, offline: bool = False,
            slugs: list[str] | None = None) -> tuple[dict, dict]:
    """Fetch (or read from cache_dir) every catalog page, then parse them; return records and
    summary. Every page is fetched before any is parsed, so a resumed run whose budget ends during
    the fetches does not parse the pages it already has."""
    wanted = [p["slug"] for p in spec.source(SOURCE)["pages"] if slugs is None or p["slug"] in slugs]
    html: dict[tuple[str, str], str] = {}
    for slug in wanted:
        for lang in LANGS:
            url = spec.resolve_url(slug, lang)
            if cache_dir is not None:
                body = cached_fetch(url, cache_dir / lang / f"{safe_cache_name(slug)}.html", fetch, offline)
            else:
                body = fetch(url)
            if body is None:
                raise ItemCollectionError(f"{lang}/{slug} is not cached and --offline was given")
            html[slug, lang] = body
    pages = {slug: {lang: parse_class_page(html[slug, lang], spec, slug) for lang in LANGS} for slug in wanted}
    return build_records(_only_pages(spec, wanted), pages, now_iso())


def _only_pages(spec: Spec, slugs: list[str]) -> Spec:
    raw = json.loads(json.dumps(spec.raw))
    raw["sources"][SOURCE]["pages"] = [p for p in raw["sources"][SOURCE]["pages"] if p["slug"] in slugs]
    return Spec(raw)


def write_records(spec: Spec, out_dir: Path, records: dict) -> list[Path]:
    source = spec.source(SOURCE)
    paths = []
    for key in ("bases", "uniques", "modifiers"):
        path = out_dir / Path(source[f"{key}_file"]).relative_to("data")
        write_jsonl(path, records[key])
        paths.append(path)
    classes_path = out_dir / Path(source["classes_file"]).relative_to("data")
    atomic_write_text(classes_path, json.dumps(records["classes"], ensure_ascii=False, indent=1) + "\n")
    return [*paths, classes_path]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect gear bases, uniques and modifiers from poe2db.")
    parser.add_argument("--offline", action="store_true", help="read the page cache only")
    parser.add_argument("--out-dir", type=Path, default=BASE_DIR / "data")
    args = parser.parse_args(argv)
    spec = load_spec()
    delay = spec.raw["robots"]["polite_delay_seconds"]
    try:
        records, summary = collect(spec, lambda url: fetch_html(url, delay=delay), cache_dir=PAGE_CACHE_DIR,
                                   offline=args.offline)
        validate(records, summary, spec)
    except (ItemCollectionError, requests.RequestException) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    paths = write_records(spec, args.out_dir, records)
    print("=== collect_items summary ===")
    for key, value in sorted(summary.items()):
        print(f"  {key}: {value}")
    print("\n".join(f"wrote: {p}" for p in paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
