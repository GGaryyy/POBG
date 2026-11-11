"""
collect_glossary.py — Build the keyword glossary (en + zh-TW) from poe2db keyword hovers.

    python -m src.scrapers.collect_glossary            # fetch missing hovers (~1 KB each, cached)
    python -m src.scrapers.collect_glossary --offline  # cache only

1. Harvest keyword links (slug + per-language hover hash) from pages already cached locally:
   passive listing cards, gem listing pages, and English gem detail pages.
2. Breadth-first over keyword hovers in each language: every explanation links further terms.
3. Write data/kg/keywords.jsonl — one entry per slug with names, explanations, see-also links
   and both source URLs.
"""

from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path
from typing import Callable

import requests

from src.catalog.spec import Spec, load_spec
from src.catalog.spec import GEM_KINDS
from src.scrapers.common import cached_fetch, fetch_html, make_soup, now_iso, read_jsonl, slug_from_href, write_jsonl
from src.scrapers.hover import KeywordRef, hover_hash, keyword_hover_url, keyword_refs, parse_keyword_hover
from src.scrapers.passive_listing import PASSIVE_SOURCES, parse_passive_listing

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
PAGE_CACHE_DIR = BASE_DIR / "output" / "cache" / "pages"
DETAIL_CACHE_DIR = BASE_DIR / "output" / "cache" / "detail"
HOVER_CACHE_DIR = BASE_DIR / "output" / "cache" / "hover"
KEYWORDS_PATH = BASE_DIR / "data" / "kg" / "keywords.jsonl"
GEM_LISTING_SOURCES = ("skill_gems_listing", "spirit_gems_listing", "support_gems_listing")
LANGS = ("en", "zh-tw")
MIN_EN_TEXT_RATIO = 0.95
TARGET_ZH_TEXT_RATIO = 0.95

Fetcher = Callable[[str], str]

# ---------------------------------------------------------------------------
# HARVEST
# ---------------------------------------------------------------------------


def harvest_refs(spec: Spec, *, page_cache: Path = PAGE_CACHE_DIR,
                 detail_cache: Path = DETAIL_CACHE_DIR) -> dict[str, dict[str, str]]:
    """{slug: {lang: hover_hash}} from every locally cached page that links keywords."""
    hashes: dict[str, dict[str, str]] = {}
    for lang in LANGS:
        for ref in _listing_refs(spec, lang, page_cache):
            _remember(hashes, ref, lang)
    popup_sel = spec.selector("popup")
    for page in sorted((detail_cache / "en").glob("*.html")) if (detail_cache / "en").exists() else []:
        soup = make_soup(page.read_text(encoding="utf-8"))
        for ref in keyword_refs(soup.select_one(popup_sel), spec):
            _remember(hashes, ref, "en")
    return hashes


def _listing_refs(spec: Spec, lang: str, page_cache: Path) -> list[KeywordRef]:
    refs: list[KeywordRef] = []
    for source in PASSIVE_SOURCES:
        page = page_cache / f"{lang}_{spec.source(source)['slug']}.html"
        if page.exists():
            for card in parse_passive_listing(page.read_text(encoding="utf-8"), spec, source, lang):
                refs.extend(card.keywords)
    for source in GEM_LISTING_SOURCES:
        page = page_cache / f"{lang}_{spec.source(source)['slug']}.html"
        if page.exists():
            soup = make_soup(page.read_text(encoding="utf-8"))
            for pane in soup.select(spec.selector("tab_pane")):
                refs.extend(keyword_refs(pane, spec))
    return refs


def _remember(hashes: dict[str, dict[str, str]], ref: KeywordRef, lang: str) -> None:
    if ref.hash:
        hashes.setdefault(ref.slug, {}).setdefault(lang, ref.hash)


# ---------------------------------------------------------------------------
# zh-TW GAP FILL
# ---------------------------------------------------------------------------


def fill_from_gem_hovers(spec: Spec, hashes: dict[str, dict[str, str]], *, fetch: Fetcher, lang: str = "zh-tw",
                         data_dir: Path = DATA_DIR, page_cache: Path = PAGE_CACHE_DIR,
                         cache_dir: Path = HOVER_CACHE_DIR, offline: bool = False) -> int:
    """For terms with no hash in `lang`, read the hover of one gem that mentions them.

    Returns the number of gem hovers read. Extends `hashes` in place.
    """
    missing = {slug for slug, by_lang in hashes.items() if lang not in by_lang}
    if not missing:
        return 0
    gem_hashes = _gem_hover_hashes(spec, lang, page_cache)
    mentions = _gems_mentioning(spec, data_dir)
    read = 0
    for slug in sorted(missing):
        if lang in hashes.get(slug, {}):
            continue  # found through an earlier gem hover
        gem = next((g for g in mentions.get(slug, []) if g in gem_hashes), None)
        if gem is None:
            continue
        url = spec.raw["url_patterns"]["gem_hover"].format(lang_path=spec.lang_path(lang), hash=gem_hashes[gem])
        try:
            html = cached_fetch(url, cache_dir / lang / "gem" / f"{gem_hashes[gem]}.html", fetch, offline)
        except requests.RequestException as exc:
            print(f"[WARN] gem hover {lang}/{gem}: {exc}", file=sys.stderr)
            continue
        if html is None:
            continue
        read += 1
        for ref in keyword_refs(make_soup(html), spec):
            _remember(hashes, ref, lang)
    return read


def _gem_hover_hashes(spec: Spec, lang: str, page_cache: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    anchor_sel = spec.selector("gem_anchor", lang)
    for source in GEM_LISTING_SOURCES:
        page = page_cache / f"{lang}_{spec.source(source)['slug']}.html"
        if not page.exists():
            continue
        for a in make_soup(page.read_text(encoding="utf-8")).select(anchor_sel):
            slug, hash_ = slug_from_href(a.get("href")), hover_hash(a.get("data-hover"))
            if slug and hash_:
                out.setdefault(slug, hash_)
    return out


def _gems_mentioning(spec: Spec, data_dir: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for kind in GEM_KINDS:
        _, source = spec.source_for_kind(kind)
        path = data_dir / Path(source["detail_file"]).relative_to("data")
        for rec in read_jsonl(path) if path.exists() else []:
            for kw in rec.get("keyword_slugs") or []:
                out.setdefault(kw, []).append(rec["slug"])
    return out


# ---------------------------------------------------------------------------
# CRAWL
# ---------------------------------------------------------------------------


def crawl(spec: Spec, hashes: dict[str, dict[str, str]], *, fetch: Fetcher,
          cache_dir: Path = HOVER_CACHE_DIR, offline: bool = False) -> dict[str, dict[str, dict]]:
    """Breadth-first over keyword hovers per language. Returns {lang: {slug: parsed}}.

    Links discovered inside explanations extend `hashes` in place.
    """
    parsed: dict[str, dict[str, dict]] = {lang: {} for lang in LANGS}
    for lang in LANGS:
        queue = deque(slug for slug, by_lang in hashes.items() if lang in by_lang)
        seen = set(queue)
        while queue:
            slug = queue.popleft()
            hash_ = hashes[slug][lang]
            html = _hover(spec, lang, hash_, fetch, cache_dir, offline)
            entry = parse_keyword_hover(html, spec) if html else None
            if entry is None:
                continue
            parsed[lang][slug] = entry
            for ref in entry["refs"]:
                _remember(hashes, ref, lang)
                if ref.hash and ref.slug not in seen:
                    seen.add(ref.slug)
                    queue.append(ref.slug)
    return parsed


def _hover(spec: Spec, lang: str, hash_: str, fetch: Fetcher, cache_dir: Path, offline: bool) -> str | None:
    url = keyword_hover_url(spec, lang, hash_)
    try:
        return cached_fetch(url, cache_dir / lang / "keyword" / f"{hash_}.html", fetch, offline)
    except requests.RequestException as exc:
        print(f"[WARN] keyword hover {lang}/{hash_[:12]}: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------------------------


def build_entries(spec: Spec, parsed: dict[str, dict[str, dict]]) -> list[dict]:
    slugs = sorted(set(parsed["en"]) | set(parsed["zh-tw"]))
    fetched_at = now_iso()
    entries = []
    for slug in slugs:
        en, zh = parsed["en"].get(slug), parsed["zh-tw"].get(slug)
        see_also = []
        for entry in (en, zh):
            for ref in (entry or {}).get("refs", []):
                if ref.slug != slug and ref.slug not in see_also:
                    see_also.append(ref.slug)
        entries.append({
            "slug": slug,
            "name_en": (en or {}).get("name"),
            "name_zh_tw": (zh or {}).get("name"),
            "text_en": (en or {}).get("text"),
            "text_zh_tw": (zh or {}).get("text"),
            "see_also": see_also,
            "url_en": spec.resolve_url(slug, "en"),
            "url_zh_tw": spec.resolve_url(slug, "zh-tw"),
            "fetched_at": fetched_at,
        })
    return entries


def coverage(entries: list[dict]) -> dict:
    total = len(entries) or 1
    return {
        "keywords": len(entries),
        "text_en": round(sum(1 for e in entries if e["text_en"]) / total, 3),
        "text_zh_tw": round(sum(1 for e in entries if e["text_zh_tw"]) / total, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the poe2db keyword glossary.")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--out", type=Path, default=KEYWORDS_PATH)
    args = parser.parse_args(argv)
    spec = load_spec()
    delay = spec.raw["robots"]["hover_delay_seconds"]
    hashes = harvest_refs(spec)
    print(f"[INFO] harvested {len(hashes)} keyword slugs "
          f"(en {sum('en' in h for h in hashes.values())}, zh-tw {sum('zh-tw' in h for h in hashes.values())})",
          file=sys.stderr)
    fetch = lambda url: fetch_html(url, delay=delay)  # noqa: E731
    gem_hovers = fill_from_gem_hovers(spec, hashes, fetch=fetch, offline=args.offline)
    print(f"[INFO] read {gem_hovers} zh-TW gem hovers to fill missing keyword hashes", file=sys.stderr)
    parsed = crawl(spec, hashes, fetch=fetch, offline=args.offline)
    # terms discovered during the crawl may still lack zh-TW; one more fill + crawl closes most gaps
    if fill_from_gem_hovers(spec, hashes, fetch=fetch, offline=args.offline):
        parsed = crawl(spec, hashes, fetch=fetch, offline=args.offline)
    entries = build_entries(spec, parsed)
    cov = coverage(entries)
    if cov["text_en"] < MIN_EN_TEXT_RATIO:
        print(f"[ERROR] only {cov['text_en']:.0%} of keywords have English text; not writing", file=sys.stderr)
        return 1
    write_jsonl(args.out, entries)
    if cov["text_zh_tw"] < TARGET_ZH_TEXT_RATIO:
        print(f"[WARN] zh-TW text coverage {cov['text_zh_tw']:.0%} below {TARGET_ZH_TEXT_RATIO:.0%}", file=sys.stderr)
    print("=== collect_glossary summary ===")
    for key, value in cov.items():
        print(f"  {key}: {value}")
    missing_zh = [e["slug"] for e in entries if not e["text_zh_tw"]]
    if missing_zh:
        print(f"  missing zh-TW ({len(missing_zh)}): {', '.join(missing_zh[:15])}{' ...' if len(missing_zh) > 15 else ''}")
    print(f"wrote: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
