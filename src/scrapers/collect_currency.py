"""
collect_currency.py — Currency items (orbs, essences, splinters, catalysts, omens, runes and soul
cores) from poe2db's listing pages and each item's own page.

    python -m src.scrapers.collect_currency            # 6 listing pages + one page per item (cached)
    python -m src.scrapers.collect_currency --offline  # cache only

1. Each listing page (catalog `currency.listings`), in English and Traditional Chinese, holds every
   item of its tabs: name, stack size, minimum modifier level, limits, required level and the
   effect lines. The category is the English tab the item is in; Chinese entries join by slug.
2. Each item's own page (English) gives the drop level, item class, tags and internal type.
   Details already collected can be reused (`reuse`), so a routine update reads only new items.

Writes data/currency/currency.jsonl. Nothing is written when the pages no longer parse into the
catalog's minimums. Prices are not collected.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Callable

import requests
from bs4 import Tag

from src.catalog.spec import Spec, load_spec
from src.scrapers.common import (
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
from src.scrapers.item_page import drop_level, item_fields

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = BASE_DIR / "output" / "cache" / "currency"
SOURCE = "currency"
LANGS = ("en", "zh-tw")
LINE_KINDS = {"explicitMod": "effects", "implicitMod": "implicits", "enchantMod": "enchants", "bondedMod": "bonded"}
MIN_MODIFIER_KEYWORD = "BetterCurrencyMinimumLevel"
MAX_ITEM_LEVEL_KEYWORD = "CurrencyMaximumItemLevel"
STACK_VALUE = re.compile(r"^\d+\s*/\s*(\d+)$")
LIMIT_LABELS = ("Limited to", "限制")
FIRST_NUMBER = re.compile(r"\d+")
REQUIRED_LEVEL = re.compile(r"(?:Level|等級)\s*(\d+)")

Fetcher = Callable[[str], str]


class CurrencyBuildError(Exception):
    """The pages did not give a usable currency list; nothing is written."""


# ---------------------------------------------------------------------------
# LISTING PAGES
# ---------------------------------------------------------------------------


def parse_listing(html: str, panes: dict[str, str] | None = None) -> list[dict]:
    """The item entries of a listing page, in page order. With `panes` ({tab id: category}) only
    those tabs are read and each entry gets its category; without, every tab is read (the
    Chinese page, whose tab ids are Chinese) and the category is None."""
    out = []
    for pane in make_soup(html).select("div.tab-pane"):
        category = panes.get(pane.get("id") or "") if panes is not None else None
        if panes is not None and category is None:
            continue
        for col in pane.select("div.col"):
            entry = parse_entry(col)
            if entry is not None:
                out.append({**entry, "category": category})
    return out


def parse_entry(col: Tag) -> dict | None:
    """One listing entry: slug, name, properties, required level and effect lines by kind."""
    body = col.select_one("div.flex-grow-1")
    link = body.select_one("a[href]") if body is not None else None
    slug = slug_from_href(link.get("href")) if link is not None else None
    name = clean_text(link.get_text(" ", strip=True)) if link is not None else ""
    if not slug or not name:
        return None
    try:
        safe_cache_name(slug)
    except ValueError:                    # a slug that cannot name a cache file cannot be fetched safely either
        print(f"[WARN] currency: entry {name!r} skipped, unusual slug {slug!r}", file=sys.stderr)
        return None
    entry: dict = {"slug": slug, "name": name, "stack_size": None, "min_modifier_level": None,
                   "max_item_level": None, "limit": None, "requires_level": None, "properties": [],
                   **{kind: [] for kind in LINE_KINDS.values()}}
    for prop in body.select("div.property"):
        _read_property(entry, prop)
    requirement = body.select_one("div.requirements")
    if requirement is not None:
        level = REQUIRED_LEVEL.search(requirement.get_text(" ", strip=True))
        entry["requires_level"] = int(level.group(1)) if level else None
    for div in body.select("div[class]"):
        kind = next((LINE_KINDS[c] for c in div.get("class", []) if c in LINE_KINDS), None)
        text = line_text(div) if kind else ""
        if text:
            entry[kind].append(text)
    return entry


def _read_property(entry: dict, prop: Tag) -> None:
    text = line_text(prop)
    if not text:
        return
    entry["properties"].append(text)
    keyword_link = prop.select_one("a[data-keyword]")
    keyword = keyword_link.get("data-keyword") if keyword_link is not None else None
    value_node = prop.select_one("span.colourDefault")
    value = clean_text(value_node.get_text(" ", strip=True)) if value_node is not None else ""
    stack = STACK_VALUE.match(value)
    if keyword == MIN_MODIFIER_KEYWORD:
        entry["min_modifier_level"] = _number(value)
    elif keyword == MAX_ITEM_LEVEL_KEYWORD:
        entry["max_item_level"] = _number(value)
    elif text.startswith(LIMIT_LABELS):
        entry["limit"] = clean_text(re.split(r"[:：]", text, maxsplit=1)[-1])
    elif stack and entry["stack_size"] is None:
        entry["stack_size"] = int(stack.group(1))


def line_text(node: Tag) -> str:
    """The text of one line; a <br> inside a sentence ("your next<br>Chaos Orb") is a space."""
    for br in node.find_all("br"):
        br.replace_with(" ")
    return clean_text(node.get_text(""))


def _number(text: str) -> int | None:
    match = FIRST_NUMBER.search(text or "")
    return int(match.group()) if match else None


# ---------------------------------------------------------------------------
# ITEM PAGES
# ---------------------------------------------------------------------------


def parse_detail(html: str) -> dict:
    """{"drop_level", "item_class", "tags", "type"} from an item's own page."""
    fields = item_fields(html)
    tags = [t.strip() for t in fields.get("Tags", "").split(",") if t.strip()]
    return {"drop_level": drop_level(fields), "item_class": fields.get("Class"), "tags": tags,
            "type": fields.get("Type")}


# ---------------------------------------------------------------------------
# ASSEMBLY
# ---------------------------------------------------------------------------


def merge_entries(english: list[dict], chinese: list[dict]) -> list[dict]:
    """One record per slug: the first English entry wins (its tab is the category; later tabs go
    to `also_in`). The Chinese entry of that slug with the most lines gives the *_zh_tw fields, so a
    short cross-reference entry in another tab does not stand in for the item's own."""
    zh: dict[str, dict] = {}
    for entry in chinese:
        known = zh.get(entry["slug"])
        if known is None or _line_count(entry) > _line_count(known):
            zh[entry["slug"]] = entry
    records: dict[str, dict] = {}
    for entry in english:
        known = records.get(entry["slug"])
        if known is not None:
            if entry["category"] != known["category"] and entry["category"] not in known["also_in"]:
                known["also_in"].append(entry["category"])
            continue
        other = zh.get(entry["slug"], {})
        record = {"slug": entry["slug"], "category": entry["category"], "also_in": [], "name": entry["name"],
                  "name_zh_tw": other.get("name")}
        for key in ("stack_size", "min_modifier_level", "max_item_level", "limit", "requires_level"):
            record[key] = entry[key]
        for key in ("properties", *LINE_KINDS.values()):
            record[key] = entry[key]
            record[f"{key}_zh_tw"] = other.get(key, [])
        records[entry["slug"]] = record
    return list(records.values())


def _line_count(entry: dict) -> int:
    return sum(len(entry.get(kind) or []) for kind in ("properties", *LINE_KINDS.values()))


def detail_parsed(detail: dict | None) -> bool:
    """An item page counts as read only when it gave its facts: a page that loads but whose facts
    box is gone (a layout change) must not pass for one."""
    return bool(detail) and (detail.get("drop_level") is not None or bool(detail.get("item_class")))


def add_details(record: dict, detail: dict | None, fetched_at: str | None) -> dict:
    """The record with its item-page fields; None for each when the page gave none."""
    detail = detail if detail_parsed(detail) else {}
    return {**record, "drop_level": detail.get("drop_level"), "item_class": detail.get("item_class"),
            "tags": detail.get("tags", []), "type": detail.get("type"),
            "detail_fetched_at": fetched_at if detail else None}


def check(records: list[dict], spec: Spec) -> None:
    """Raise CurrencyBuildError when the result is below the catalog's minimums."""
    expect = spec.source(SOURCE)["expect_min"]
    problems = []
    total = len(records)
    if total < expect["records"]:
        problems.append(f"{total} items (expected at least {expect['records']})")
    for category, minimum in expect["categories"].items():
        count = sum(1 for r in records if r["category"] == category)
        if count < minimum:
            problems.append(f"{count} {category} items (expected at least {minimum})")
    if total:
        zh = sum(1 for r in records if r.get("name_zh_tw")) / total
        if zh < expect["zh_ratio"]:
            problems.append(f"{zh:.0%} have a Chinese name (expected {expect['zh_ratio']:.0%})")
        detailed = sum(1 for r in records if r.get("detail_fetched_at")) / total
        if detailed < expect["detail_ratio"]:
            problems.append(f"{detailed:.0%} have their item page read (expected {expect['detail_ratio']:.0%})")
    if problems:
        raise CurrencyBuildError("the currency pages did not parse as expected: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# COLLECT
# ---------------------------------------------------------------------------


def listing_urls(spec: Spec) -> list[str]:
    return [spec.resolve_url(listing["slug"], lang) for listing in spec.source(SOURCE)["listings"] for lang in LANGS]


def collect(spec: Spec, *, fetch: Fetcher, cache_dir: Path = CACHE_DIR, offline: bool = False,
            reuse: dict[str, dict] | None = None, fallback: dict[str, dict] | None = None) -> tuple[list[dict], dict]:
    """(records, summary). Item pages are read for every item not in `reuse` (slug: an earlier
    record whose item-page fields are kept without a request). An item page that cannot be read or
    gives no facts keeps the fields of its `fallback` record (an earlier one, possibly old), or
    leaves them empty; the check refuses a result where too many are. Raises CurrencyBuildError."""
    reuse, fallback = reuse or {}, fallback or {}
    fetched_at = now_iso()
    records = merge_entries(*_listings(spec, fetch, cache_dir, offline))
    out, failed, reused = [], [], 0
    for record in records:
        earlier = reuse.get(record["slug"])
        if earlier and earlier.get("detail_fetched_at"):
            out.append(add_details(record, earlier, earlier["detail_fetched_at"]))
            reused += 1
            continue
        try:
            html = cached_fetch(spec.resolve_url(record["slug"], "en"), _detail_file(cache_dir, record["slug"]),
                                fetch, offline)
        except requests.RequestException as exc:      # a missing item page costs its drop level, not the update
            print(f"[WARN] currency: item page {record['slug']}: {exc}", file=sys.stderr)
            html = None
        detail = parse_detail(html) if html else None
        if detail_parsed(detail):
            out.append(add_details(record, detail, fetched_at))
            continue
        failed.append(record["slug"])
        earlier = fallback.get(record["slug"]) or {}
        out.append(add_details(record, earlier, earlier.get("detail_fetched_at")))
    out = [{**r, "url_en": spec.resolve_url(r["slug"], "en"), "url_zh_tw": spec.resolve_url(r["slug"], "zh-tw"),
            "fetched_at": fetched_at} for r in out]
    check(out, spec)
    return out, {"records": len(out), "item_pages_read": len(out) - len(failed) - reused,
                 "item_pages_reused": reused, "item_pages_failed": failed}


def pending_pages(spec: Spec, cache_dir: Path, reuse: dict[str, dict] | None = None,
                  failed: set[str] = frozenset()) -> int | None:
    """Pages a run still has to fetch, from what is cached: None until the listing pages are in.
    `failed`: URLs that failed in this run and are not asked again."""
    reuse = reuse or {}
    if not all(_listing_file(cache_dir, url).exists() for url in listing_urls(spec)):
        return None
    english = []
    for listing in spec.source(SOURCE)["listings"]:
        html = _listing_file(cache_dir, spec.resolve_url(listing["slug"], "en")).read_text(encoding="utf-8")
        english += parse_listing(html, listing["panes"])
    slugs = {e["slug"] for e in english if not (reuse.get(e["slug"]) or {}).get("detail_fetched_at")}
    return sum(1 for slug in slugs if not _detail_file(cache_dir, slug).exists()
               and spec.resolve_url(slug, "en") not in failed)


def _listings(spec: Spec, fetch: Fetcher, cache_dir: Path, offline: bool) -> tuple[list[dict], list[dict]]:
    english, chinese = [], []
    for listing in spec.source(SOURCE)["listings"]:
        for lang in LANGS:
            url = spec.resolve_url(listing["slug"], lang)
            html = cached_fetch(url, _listing_file(cache_dir, url), fetch, offline)
            if html is None:
                raise CurrencyBuildError(f"{url} is not cached and offline was given")
            if lang == "en":
                english += parse_listing(html, listing["panes"])
            else:
                chinese += parse_listing(html)
    return english, chinese


def _listing_file(cache_dir: Path, url: str) -> Path:
    lang, slug = url.rstrip("/").rsplit("/", 2)[-2:]
    return cache_dir / "listings" / lang / f"{safe_cache_name(slug)}.html"


def _detail_file(cache_dir: Path, slug: str) -> Path:
    return cache_dir / "items" / f"{safe_cache_name(slug)}.html"


def read_records(spec: Spec, base_dir: Path) -> list[dict]:
    path = base_dir / spec.source(SOURCE)["currency_file"]
    return read_jsonl(path) if path.exists() else []


def write(spec: Spec, base_dir: Path, records: list[dict]) -> None:
    write_jsonl(base_dir / spec.source(SOURCE)["currency_file"], records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect currency items from poe2db.")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh-item-pages", action="store_true",
                        help="fetch every item page again instead of reusing the stored drop levels")
    args = parser.parse_args(argv)
    spec = load_spec()
    delay = spec.raw["robots"]["polite_delay_seconds"]
    stored = {r["slug"]: r for r in read_records(spec, BASE_DIR)}
    if not args.offline:      # fetched_at says "now": the listings (and item pages asked for) must be fetched now
        shutil.rmtree(CACHE_DIR / "listings", ignore_errors=True)
        if args.refresh_item_pages:
            shutil.rmtree(CACHE_DIR / "items", ignore_errors=True)
    try:
        records, summary = collect(spec, fetch=lambda url: fetch_html(url, delay=delay), offline=args.offline,
                                   reuse={} if args.refresh_item_pages else stored, fallback=stored)
    except (CurrencyBuildError, requests.RequestException) as exc:
        print(f"[ERROR] {exc}; nothing was written", file=sys.stderr)
        return 1
    write(spec, BASE_DIR, records)
    print("=== collect_currency summary ===")
    for category in dict.fromkeys(r["category"] for r in records):
        print(f"  {category}: {sum(1 for r in records if r['category'] == category)}")
    print(f"  records {summary['records']}, item pages read {summary['item_pages_read']}, "
          f"failed {len(summary['item_pages_failed'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
