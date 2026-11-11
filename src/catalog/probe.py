"""
probe.py — Check that poe2db still matches the catalog spec (markup-drift detector).

    python -m src.catalog.probe            # all sources, en + zh-tw
    python -m src.catalog.probe --lang en  # one language

For every listing source and language it fetches the page once, counts what the catalog
selectors find per section, and compares against `expect_min`. For gem_detail it parses one
sample page per kind. Aggregate results go to output/metrics/ and the exit code is 1 on drift.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from src.catalog.spec import Spec, load_spec
from src.scrapers.collect_items import ItemCollectionError, parse_class_page
from src.scrapers.common import fetch_html, find_section, make_soup
from src.scrapers.gem_detail import parse_detail
from src.scrapers.gem_listing import parse_gemcutting, parse_listing
from src.scrapers.hover import keyword_hover_url, parse_keyword_hover
from src.scrapers.passive_tree_data import node_texts

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
METRICS_DIR = BASE_DIR / "output" / "metrics"
LISTING_SOURCES = ("skill_gems_listing", "spirit_gems_listing", "support_gems_listing")
PASSIVE_SOURCES = ("passive_keystones", "passive_notables")
DETAIL_MIN_PROPERTIES = 2

Fetcher = Callable[[str], str]

# ---------------------------------------------------------------------------
# PROBE
# ---------------------------------------------------------------------------


def run_probe(spec: Spec, langs: list[str], fetcher: Fetcher | None = None) -> dict:
    """Probe every source for the given languages. Returns the metrics document."""
    fetch = fetcher or (lambda url: fetch_html(url, delay=spec.raw["robots"]["polite_delay_seconds"]))
    checks: list[dict] = []
    for lang in langs:
        for name in LISTING_SOURCES:
            checks.extend(_probe_listing(spec, name, lang, fetch))
        for name in PASSIVE_SOURCES:
            checks.extend(_probe_passive(spec, name, lang, fetch))
    checks.extend(_probe_detail(spec, fetch))
    checks.append(_probe_keyword_hover(spec, fetch))
    checks.append(_probe_pob2_version(spec, fetch))
    checks.extend(_probe_tree_data(spec, fetch))
    checks.extend(_probe_items(spec, fetch))
    return {
        "run_id": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S"),
        "stage": "catalog_probe",
        "spec_version": spec.raw["spec_version"],
        "spec_verified_at": spec.raw["verified_at"],
        "languages": langs,
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
    }


def _probe_listing(spec: Spec, source: str, lang: str, fetch: Fetcher) -> list[dict]:
    url = spec.resolve_url(spec.source(source)["slug"], lang)
    html, error, elapsed = _timed_fetch(url, fetch)
    if html is None:
        return [_check(source, "page", lang, url, 0, 1, error, elapsed)]
    rows = parse_listing(html, spec, source, lang)
    out = [_check(source, "list", lang, url, len(rows), spec.expect_min(source, "list"), None, elapsed)]
    sections = spec.source(source)["sections"]
    if "gemcutting" in sections:
        gc = parse_gemcutting(html, spec, source, lang)
        out.append(_check(source, "gemcutting", lang, url, len(gc), spec.expect_min(source, "gemcutting"), None, elapsed))
    soup = make_soup(html)
    for sec_name in (s for s in sections if s not in ("list", "gemcutting")):
        meta = sections[sec_name]
        node = find_section(soup, meta.get("ids", {}), lang, meta.get("pane_index"))
        out.append(_check(source, sec_name, lang, url, _section_count(node, meta, spec, lang),
                          spec.expect_min(source, sec_name), None, elapsed))
    return out


def _section_count(node, meta: dict, spec: Spec, lang: str) -> int:
    """Table sections (declared with ``columns``) count data rows; the rest count gem anchors."""
    if node is None:
        return 0
    if meta.get("columns"):
        return sum(1 for tr in node.select("tr") if len(tr.find_all("td")) >= 2)
    return len(node.select(spec.selector("gem_anchor", lang)))


def _probe_passive(spec: Spec, source: str, lang: str, fetch: Fetcher) -> list[dict]:
    url = spec.resolve_url(spec.source(source)["slug"], lang)
    html, error, elapsed = _timed_fetch(url, fetch)
    if html is None:
        return [_check(source, "page", lang, url, 0, 1, error, elapsed)]
    soup = make_soup(html)
    sections = spec.source(source)["sections"]
    out = []
    for sec_name, meta in sections.items():
        node = find_section(soup, meta.get("ids", {}), lang, meta.get("pane_index"))
        selector = spec.selector("passive_anchor") if sec_name == "list" else spec.selector("passive_alt_anchor")
        count = len(node.select(selector)) if node is not None else 0
        out.append(_check(source, sec_name, lang, url, count, spec.expect_min(source, sec_name), None, elapsed))
    return out


def _probe_detail(spec: Spec, fetch: Fetcher) -> list[dict]:
    out = []
    for kind, slug in spec.source("gem_detail")["samples"].items():
        url = spec.resolve_url(slug, "en")
        html, error, elapsed = _timed_fetch(url, fetch)
        if html is None:
            out.append(_check("gem_detail", kind, "en", url, 0, 1, error, elapsed))
            continue
        rec = parse_detail(html, spec, slug, kind)
        filled = sum(1 for k in ("tier", "level_range", "cost", "requires_stats", "description", "game_id") if rec.get(k))
        problems = list(rec["parse_warnings"])
        if not rec.get("name") or "name_from_slug" in problems:
            problems.append("name_missing")
        out.append(_check("gem_detail", kind, "en", url, filled, DETAIL_MIN_PROPERTIES,
                          ", ".join(problems) or None, elapsed))
    return out


def _probe_keyword_hover(spec: Spec, fetch: Fetcher) -> dict:
    sample = spec.source("keyword_hover")["samples"]["en"]
    url = keyword_hover_url(spec, "en", sample["hash"])
    html, error, elapsed = _timed_fetch(url, fetch)
    entry = parse_keyword_hover(html, spec) if html else None
    ok_fields = int(bool(entry and entry["slug"] == sample["slug"] and entry["text"]))
    return _check("keyword_hover", "sample", "en", url, ok_fields, 1, error, elapsed)


def _probe_pob2_version(spec: Spec, fetch: Fetcher) -> dict:
    """Drift when PathOfBuilding-PoE2 publishes a tree newer than the pinned version."""
    source = spec.source("pob2_tree")
    url = source["versions_api"]
    text, error, elapsed = _timed_fetch(url, fetch)
    if text is None:
        return _check("pob2_tree", "version", "-", url, 0, 1, error, elapsed)
    try:
        versions = sorted(e["name"] for e in json.loads(text) if re.fullmatch(r"\d+_\d+", e.get("name", "")))
    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        return _check("pob2_tree", "version", "-", url, 0, 1, f"unexpected API response: {exc}", elapsed)
    as_tuple = lambda v: tuple(int(x) for x in v.split("_"))  # noqa: E731
    latest = max(versions, key=as_tuple, default=None)
    newer = latest is not None and as_tuple(latest) > as_tuple(source["version"])
    note = f"pinned {source['version']}, latest {latest}" + (" — update pob2_tree.version" if newer else "")
    return _check("pob2_tree", "version", "-", url, 0 if newer else 1, 1, note if newer else None, elapsed)


def _probe_tree_data(spec: Spec, fetch: Fetcher) -> list[dict]:
    """poe2db's tree viewer still serves the pinned data version, and the zh-TW file is complete."""
    source = spec.source("passive_tree_data")
    return [_probe_tree_data_version(source, fetch), _probe_tree_data_file(spec, source, fetch)]


def _probe_tree_data_version(source: dict, fetch: Fetcher) -> dict:
    name, page_url = "passive_tree_data", source["viewer_page"]
    page, error, elapsed = _timed_fetch(page_url, fetch)
    if page is None:
        return _check(name, "version", "-", page_url, 0, 1, error, elapsed)
    script = re.search(source["viewer_script_pattern"], page)
    if script is None:
        return _check(name, "version", "-", page_url, 0, 1, "viewer script not found on the page", elapsed)
    text, error, elapsed = _timed_fetch(script.group(0), fetch)
    if text is None:
        return _check(name, "version", "-", script.group(0), 0, 1, error, elapsed)
    found = re.search(source["version_pattern"], text)
    if found is None:
        return _check(name, "version", "-", script.group(0), 0, 1, "version not found in the viewer script", elapsed)
    same = found.group(1) == source["version"]
    note = None if same else f"pinned {source['version']}, viewer uses {found.group(1)} — update passive_tree_data.version"
    return _check(name, "version", "-", script.group(0), 1 if same else 0, 1, note, elapsed)


def _probe_tree_data_file(spec: Spec, source: dict, fetch: Fetcher) -> dict:
    url = source["url"].format(version=source["version"], lang=spec.raw["languages"]["zh-tw"])
    expect = source["expect_min"]["nodes"]
    text, error, elapsed = _timed_fetch(url, fetch)
    if text is None:
        return _check("passive_tree_data", "nodes", "zh-tw", url, 0, expect, error, elapsed)
    try:
        count = len(node_texts(json.loads(text)))
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        return _check("passive_tree_data", "nodes", "zh-tw", url, 0, expect, f"unexpected data file: {exc}", elapsed)
    return _check("passive_tree_data", "nodes", "zh-tw", url, count, expect, None, elapsed)


def _probe_items(spec: Spec, fetch: Fetcher) -> list[dict]:
    """One item class page still lists its bases and uniques and embeds its modifier object."""
    sample = spec.source("item_pages")["probe_sample"]
    url = spec.resolve_url(sample["slug"], "en")
    expect = sample["expect_min"]
    html, error, elapsed = _timed_fetch(url, fetch)
    if html is None:
        return [_check("item_pages", section, "en", url, 0, expect[section], error, elapsed) for section in expect]
    try:
        page = parse_class_page(html, spec, sample["slug"])
    except ItemCollectionError as exc:
        return [_check("item_pages", section, "en", url, 0, expect[section], str(exc), elapsed) for section in expect]
    found = {"bases": len(page.bases), "uniques": len(page.uniques), "modifiers": len(page.mods.get("normal", []))}
    return [_check("item_pages", section, "en", url, found[section], expect[section], None, elapsed) for section in expect]


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def _timed_fetch(url: str, fetch: Fetcher) -> tuple[str | None, str | None, float]:
    start = time.perf_counter()
    try:
        return fetch(url), None, round(time.perf_counter() - start, 2)
    except requests.RequestException as exc:
        return None, f"{type(exc).__name__}: {exc}", round(time.perf_counter() - start, 2)


def _check(source: str, section: str, lang: str, url: str, count: int, expect_min: int,
           error: str | None = None, elapsed: float | None = None) -> dict:
    ok = error is None and count >= expect_min
    return {"source": source, "section": section, "lang": lang, "url": url, "count": count,
            "expect_min": expect_min, "ok": ok, "error": error, "elapsed_s": elapsed}


def write_metrics(doc: dict, metrics_dir: Path = METRICS_DIR) -> Path:
    metrics_dir.mkdir(parents=True, exist_ok=True)
    path = metrics_dir / f"catalog_probe_{doc['run_id']}.json"
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    (metrics_dir / "latest_catalog_probe.json").write_text(text, encoding="utf-8")
    return path


def print_report(doc: dict) -> None:
    print(f"{'source':24} {'section':12} {'lang':6} {'count':>6} {'min':>5}  status")
    for c in doc["checks"]:
        status = "ok" if c["ok"] else "DRIFT"
        print(f"{c['source']:24} {c['section']:12} {c['lang']:6} {c['count']:>6} {c['expect_min']:>5}  {status}")
        if not c["ok"]:
            print(f"[WARN] drift: {c['source']}/{c['section']} ({c['lang']}) count={c['count']} "
                  f"expect_min={c['expect_min']} error={c['error']}", file=sys.stderr)
    print(f"\noverall: {'ok' if doc['ok'] else 'DRIFT DETECTED'} (spec verified {doc['spec_verified_at']})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe poe2db against the catalog spec.")
    parser.add_argument("--lang", action="append", help="language code (repeatable); default en + zh-tw")
    parser.add_argument("--metrics-dir", type=Path, default=METRICS_DIR)
    args = parser.parse_args(argv)
    spec = load_spec()
    langs = args.lang or list(spec.languages)
    doc = run_probe(spec, langs)
    path = write_metrics(doc, args.metrics_dir)
    print_report(doc)
    print(f"metrics: {path}")
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
