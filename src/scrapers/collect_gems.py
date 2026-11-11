"""
collect_gems.py — Collect skill / spirit / support gem data from poe2db into JSONL.

    python -m src.scrapers.collect_gems --kind all                       # full re-collect
    python -m src.scrapers.collect_gems --kind all --changed-only        # incremental update
    python -m src.scrapers.collect_gems --kind skill --slugs Leap_Slam Bonestorm
    python -m src.scrapers.collect_gems --kind skill --older-than 30     # refresh stale records
    python -m src.scrapers.collect_gems --kind skill --limit 5 --out-dir output/smoke

Per kind:  listing page → rows → one detail page per slug → validated records →
           <kind>_Detail.jsonl (existing path), <kind>_Listing.jsonl, <kind>_Gemcutting.jsonl

Incremental mode (--changed-only / --slugs / --older-than) still fetches the listing page
(3 requests for all kinds) but only re-fetches detail pages for gems that are new, whose
listing row (name / tier / tags) changed, whose stored record is broken or stale, or that
were named explicitly. Gems that left the listing are dropped from the detail file.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import requests

from src.catalog.spec import GEM_KINDS, Spec, load_spec
from src.scrapers.common import (atomic_write_text, cached_fetch, fetch_html, file_time_iso, read_jsonl,
                                 safe_cache_name, write_jsonl)
from src.scrapers.gem_detail import parse_detail
from src.scrapers.gem_listing import ListingRow, parse_gemcutting, parse_listing

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DETAIL_CACHE_DIR = BASE_DIR / "output" / "cache" / "detail"
PAGE_CACHE_DIR = BASE_DIR / "output" / "cache" / "pages"
KIND_ALIASES = {"skill": "skill_gem", "spirit": "spirit_gem", "support": "support_gem"}
DEFAULT_DELAY_SECONDS = 0.8
MAX_SKIP_RATIO = 0.02
MIN_ALLOWED_SKIPS = 1            # one failed page never aborts a run on its own
MAX_BROKEN_RATIO = 0.02          # records whose popup could not be parsed
BROKEN_WARNINGS = ("no_popup", "no_popup_content", "name_from_slug")
PROGRESS_EVERY = 25
TARGET_PRIORITY = ("requested", "new", "listing_changed", "broken", "stale")   # fetch order under a cap
# poe2db's Skill Gems page also lists every spirit gem. A gem is stored once: under the kind
# named here when that kind's data already holds it.
OWNED_BY = {"skill_gem": ("spirit_gem",)}
SUPPORTED_LANGS = ("en",)        # the detail parser matches English labels only
NULL_RATE_FIELDS = ("tier", "level_range", "cost", "main_stat", "requires_level",
                    "requires_stats", "requires_weapons", "description", "quality_effects", "game_id",
                    "keyword_slugs", "supported_by")

Fetcher = Callable[[str], str]

# ---------------------------------------------------------------------------
# COLLECTION
# ---------------------------------------------------------------------------


class CollectionError(Exception):
    """Raised when a collection run must not overwrite existing data."""


def collect_kind(
    kind: str,
    spec: Spec,
    *,
    out_dir: Path,
    lang: str = "en",
    delay: float = DEFAULT_DELAY_SECONDS,
    limit: int | None = None,
    fetcher: Fetcher | None = None,
    changed_only: bool = False,
    slugs: list[str] | None = None,
    older_than_days: int | None = None,
    cache_dir: Path | None = None,
    from_cache: bool = False,
    listing_cache_dir: Path | None = None,
    max_targets: int | None = None,
    dry_run: bool = False,
    skip_recent_seconds: float = 0,
) -> dict:
    """Collect one gem kind end-to-end. Returns a summary dict (aggregates only).

    Full mode re-fetches every detail page. Incremental mode (any of changed_only, slugs,
    older_than_days) keeps existing records and re-fetches only the selected gems.
    When cache_dir is given (the CLI uses output/cache/detail/), every fetched detail page is
    written to cache_dir/<lang>/<slug>.html; with from_cache=True cached pages are re-parsed
    instead of fetched (parser fixes without a new crawl).
    max_targets (incremental only) caps the detail pages of one run; the rest stay selected for
    the next run (`targets_left`). dry_run fetches the listing, reports what would be fetched
    and writes nothing. skip_recent_seconds keeps `slugs` and `older_than_days` from selecting a
    gem fetched that recently, so repeated capped runs with the same arguments come to an end.
    """
    source_name, source = spec.source_for_kind(kind)
    fetch = fetcher or (lambda url: fetch_html(url, delay=delay))
    if lang not in SUPPORTED_LANGS:
        raise CollectionError(f"{kind}: detail parsing supports {SUPPORTED_LANGS}, not {lang!r}")

    listing_html = _listing_page(spec, source["slug"], lang, fetch, listing_cache_dir, from_cache)
    rows = parse_listing(listing_html, spec, source_name, lang)
    expect_min = spec.expect_min(source_name, "list")
    if len(rows) < expect_min:
        raise CollectionError(
            f"{kind}: listing returned {len(rows)} gems, below expect_min={expect_min}; "
            "the page markup probably changed. Run `python -m src.catalog.probe`."
        )
    gemcutting = parse_gemcutting(listing_html, spec, source_name, lang)
    elsewhere = _stored_under_another_kind(kind, spec, out_dir)
    listed = len(rows)
    rows = [row for row in rows if row.slug not in elsewhere]
    if limit is not None:
        rows = rows[:limit]

    detail_path = out_dir / Path(source["detail_file"]).relative_to("data")
    listing_path = out_dir / Path(source["listing_file"]).relative_to("data")
    incremental = changed_only or bool(slugs) or older_than_days is not None
    existing = _load_existing(detail_path) if incremental else {}
    if (max_targets is not None or dry_run) and not incremental:
        raise CollectionError(f"{kind}: max_targets and dry_run need an incremental mode")
    previous_rows: dict[str, dict] = {}
    reasons: dict[str, int] = {}
    recent = 0
    if incremental:
        previous_rows = _load_existing(listing_path)
        fresh_after = datetime.now(timezone.utc) - timedelta(seconds=skip_recent_seconds) if skip_recent_seconds else None
        targets, reasons, recent = _select_targets(rows, previous_rows, existing, slugs or [], older_than_days,
                                                   fresh_after)
    else:
        targets = rows
    targets_total = len(targets)
    pending = targets[max_targets:] if max_targets is not None else []
    targets = targets[:max_targets] if max_targets is not None else targets
    current = {r.slug for r in rows}
    if dry_run:
        return {"kind": kind, "mode": "dry_run", "listing_rows": len(rows), "records": len(existing),
                "stored_elsewhere": listed - len(rows) if limit is None else 0,
                "refetched": 0, "targets_total": targets_total, "targets_left": targets_total,
                "reasons": reasons, "recently_fetched": recent, "added": sorted(current - set(existing)),
                "removed": sorted(set(existing) - current), "skipped": [], "files": []}

    detail_fetch = _cached_fetch(fetch, cache_dir, lang, from_cache)
    fetched, skipped = _collect_details(targets, kind, spec, lang, detail_fetch)
    if len(skipped) > max(MIN_ALLOWED_SKIPS, int(len(targets) * MAX_SKIP_RATIO)):
        raise CollectionError(
            f"{kind}: {len(skipped)} of {len(targets)} detail pages failed ({skipped[:5]}...); aborting without writing."
        )
    _validate_parse_quality(fetched, kind)
    records = _merge_records(rows, existing, fetched) if incremental else fetched
    _validate_records(records, kind)

    write_jsonl(detail_path, records)
    unfetched = {r.slug for r in pending} | set(skipped)
    write_jsonl(listing_path, _listing_rows(rows, unfetched, previous_rows, spec, kind, lang))
    gemcutting_path = None
    if source.get("gemcutting_file") and gemcutting:
        gemcutting_path = out_dir / Path(source["gemcutting_file"]).relative_to("data")
        write_jsonl(gemcutting_path, (_gemcutting_record(g, spec, source["slug"], lang) for g in gemcutting))

    stored = {r["slug"] for r in records}
    return {
        "kind": kind,
        "mode": "incremental" if incremental else "full",
        "listing_rows": len(rows),
        "stored_elsewhere": listed - len(rows) if limit is None else 0,
        "records": len(records),
        "refetched": len(fetched),
        "targets_total": targets_total,
        "targets_left": len(pending),
        "reasons": reasons,
        "recently_fetched": recent,
        "added": sorted(stored - set(existing)) if incremental else [],
        "removed": sorted(set(existing) - current) if incremental else [],
        "skipped": skipped,
        "gemcutting_rows": len(gemcutting),
        "null_rate": _null_rates(records),
        "warnings": dict(Counter(w for r in fetched for w in r["parse_warnings"])),
        "files": [str(p) for p in (detail_path, listing_path, gemcutting_path) if p],
    }


# ---------------------------------------------------------------------------
# INCREMENTAL SELECTION
# ---------------------------------------------------------------------------


def _stored_under_another_kind(kind: str, spec: Spec, out_dir: Path) -> set[str]:
    slugs: set[str] = set()
    for owner in OWNED_BY.get(kind, ()):
        _, source = spec.source_for_kind(owner)
        slugs |= set(_load_existing(out_dir / Path(source["detail_file"]).relative_to("data")))
    return slugs


def _load_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {rec["slug"]: rec for rec in read_jsonl(path) if rec.get("slug")}


def _listing_signature(row: dict | ListingRow) -> tuple:
    data = row.as_dict() if isinstance(row, ListingRow) else row
    return (data.get("name"), data.get("tier"), tuple(data.get("tag_slugs") or []))


def _select_targets(
    rows: list[ListingRow],
    previous_rows: dict[str, dict],
    existing: dict[str, dict],
    wanted: list[str],
    older_than_days: int | None,
    fresh_after: datetime | None = None,
) -> tuple[list[ListingRow], dict[str, int], int]:
    """Rows worth a detail fetch (requested first, then new, changed on the listing, broken, stale),
    how many rows each reason selected, and how many requested / stale rows were left out because
    their record was fetched after fresh_after."""
    cutoff = None
    if older_than_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    selected: list[tuple[int, ListingRow]] = []
    counts: Counter = Counter()
    recent = 0
    for row in rows:
        record = existing.get(row.slug)
        reasons = []
        if record is None:
            reasons.append("new")
        elif row.slug not in previous_rows or _listing_signature(previous_rows[row.slug]) != _listing_signature(row):
            reasons.append("listing_changed")
        elif any(w in BROKEN_WARNINGS for w in record.get("parse_warnings", [])):
            reasons.append("broken")
        fresh = record is not None and fresh_after is not None and not _fetched_before(record, fresh_after)
        stale = cutoff is not None and record is not None and _fetched_before(record, cutoff)
        if fresh and (row.slug in wanted or stale):
            recent += 1
        elif row.slug in wanted:
            reasons.append("requested")
        if stale and not fresh:
            reasons.append("stale")
        if reasons:
            counts.update(reasons)
            selected.append((min(TARGET_PRIORITY.index(r) for r in reasons), row))
    selected.sort(key=lambda pair: pair[0])   # stable: listing order within a priority
    return [row for _, row in selected], dict(counts), recent


def _fetched_before(record: dict, cutoff: datetime) -> bool:
    try:
        fetched = datetime.fromisoformat(record.get("fetched_at") or "")
    except ValueError:
        return True
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return fetched < cutoff


def _merge_records(rows: list[ListingRow], existing: dict[str, dict], fetched: list[dict]) -> list[dict]:
    """Listing order; freshly fetched records replace stored ones; gems no longer listed are dropped."""
    fresh = {r["slug"]: r for r in fetched}
    merged: list[dict] = []
    for row in rows:
        record = fresh.get(row.slug) or existing.get(row.slug)
        if record is not None:
            merged.append(record)
    return merged


def _listing_page(spec: Spec, page: str, lang: str, fetch: Fetcher, cache_dir: Path | None, from_cache: bool) -> str:
    """Listing HTML: from the page cache under --from-cache (no network), else live (and cached)."""
    url = spec.resolve_url(page, lang)
    if cache_dir is None:
        return fetch(url)
    cache_file = cache_dir / f"{lang}_{safe_cache_name(page)}.html"
    if from_cache:
        html = cached_fetch(url, cache_file, fetch, offline=True)
        if html is None:
            raise CollectionError(f"--from-cache: listing {lang}/{page} is not cached at {cache_file}")
        return html
    html = fetch(url)
    atomic_write_text(cache_file, html)
    return html


class _CachedFetcher:
    """Fetch detail pages through a disk cache; remembers when each page was really fetched."""

    def __init__(self, fetch: Fetcher, folder: Path, from_cache: bool) -> None:
        self._fetch = fetch
        self._folder = folder
        self._from_cache = from_cache
        self.fetched_at: dict[str, str] = {}
        folder.mkdir(parents=True, exist_ok=True)

    def __call__(self, url: str) -> str:
        path = self._folder / f"{safe_cache_name(url.rsplit('/', 1)[-1])}.html"
        if self._from_cache and path.exists():
            html = path.read_text(encoding="utf-8")
        else:
            html = self._fetch(url)
            atomic_write_text(path, html)
        self.fetched_at[url] = file_time_iso(path)
        return html


def _cached_fetch(fetch: Fetcher, cache_dir: Path | None, lang: str, from_cache: bool) -> Fetcher:
    """Wrap the fetcher so detail pages are cached on disk and optionally served from it."""
    if cache_dir is None:
        return fetch
    return _CachedFetcher(fetch, cache_dir / lang, from_cache)


def _collect_details(
    rows: list[ListingRow], kind: str, spec: Spec, lang: str, fetch: Fetcher
) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    skipped: list[str] = []
    total = len(rows)
    for i, row in enumerate(rows, 1):
        url = spec.resolve_url(row.slug, lang)
        try:
            html = fetch(url)
        except (requests.RequestException, ValueError) as exc:
            print(f"[WARN] skip {row.slug}: {exc}", file=sys.stderr)
            skipped.append(row.slug)
            continue
        record = parse_detail(html, spec, row.slug, kind, lang)
        if isinstance(fetch, _CachedFetcher) and url in fetch.fetched_at:
            record["fetched_at"] = fetch.fetched_at[url]  # cached page: cite when it was really fetched
        _merge_listing(record, row)
        records.append(record)
        if i % PROGRESS_EVERY == 0 or i == total:
            print(f"[INFO] {kind}: {i}/{total} detail pages", file=sys.stderr)
    return records, skipped


def _merge_listing(record: dict, row: ListingRow) -> None:
    record["tag_slugs"] = row.tag_slugs
    record["attribute_colour"] = row.attribute_colour
    record["summary"] = row.row_text
    if record["tier"] is None and row.tier is not None:
        record["tier"] = row.tier
        record["parse_warnings"].append("tier_from_listing")
    if not record["tags"] and row.tag_names:
        record["tags"] = list(row.tag_names)
        record["parse_warnings"].append("tags_from_listing")


# ---------------------------------------------------------------------------
# VALIDATION / OUTPUT SHAPES
# ---------------------------------------------------------------------------


def _validate_records(records: list[dict], kind: str) -> None:
    seen: set[str] = set()
    for rec in records:
        for key in ("name", "slug", "href"):
            if not rec.get(key):
                raise CollectionError(f"{kind}: record missing {key}: {rec.get('slug')}")
        if rec["slug"] in seen:
            raise CollectionError(f"{kind}: duplicate slug {rec['slug']}")
        seen.add(rec["slug"])
        if rec["tier"] is not None and not isinstance(rec["tier"], int):
            raise CollectionError(f"{kind}: non-int tier for {rec['slug']}: {rec['tier']!r}")
        for key in ("level_range", "requires_level"):
            value = rec[key]
            if value is not None and not (len(value) == 2 and value[0] <= value[1]):
                raise CollectionError(f"{kind}: bad {key} for {rec['slug']}: {value!r}")


def _validate_parse_quality(records: list[dict], kind: str) -> None:
    """Refuse to overwrite data when the detail popup itself stopped parsing (markup drift)."""
    if not records:
        return
    broken = [r["slug"] for r in records if any(w in BROKEN_WARNINGS for w in r["parse_warnings"])]
    if len(broken) / len(records) > MAX_BROKEN_RATIO:
        raise CollectionError(
            f"{kind}: {len(broken)} of {len(records)} detail pages had no parsable popup "
            f"({broken[:5]}...); the detail markup probably changed. Run `python -m src.catalog.probe`."
        )


def _listing_rows(rows: list[ListingRow], pending: set[str], previous: dict[str, dict], spec: Spec, kind: str,
                  lang: str):
    """Listing rows to store. A gem left for a later run keeps its previous row (or none when it
    is new), so the next run still sees it as changed."""
    for row in rows:
        if row.slug not in pending:
            yield _listing_record(row, spec, kind, lang)
        elif row.slug in previous:
            yield previous[row.slug]


def _listing_record(row: ListingRow, spec: Spec, kind: str, lang: str) -> dict:
    return {
        **row.as_dict(),
        "kind": kind,
        "lang": lang,
        "url": spec.resolve_url(row.slug, lang),
    }


def _gemcutting_record(row, spec: Spec, page_slug: str, lang: str) -> dict:
    return {
        **row.as_dict(),
        "gem_url": spec.resolve_url(row.gem_slug, lang),
        "source_url": spec.resolve_url(page_slug, lang),
    }


def _null_rates(records: list[dict]) -> dict[str, float]:
    if not records:
        return {}
    return {
        field: round(sum(1 for r in records if r.get(field) in (None, [], "")) / len(records), 3)
        for field in NULL_RATE_FIELDS
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect poe2db gem data into JSONL.")
    parser.add_argument("--kind", choices=[*KIND_ALIASES, "all"], default="all")
    parser.add_argument("--lang", choices=list(SUPPORTED_LANGS), default="en")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help=f"defaults to {BASE_DIR / 'data'}; required together with --limit")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--limit", type=int, default=None, help="only the first N gems (smoke runs)")
    parser.add_argument("--changed-only", action="store_true",
                        help="incremental: re-fetch only new / changed / broken gems, keep the rest")
    parser.add_argument("--slugs", nargs="+", default=None, help="incremental: re-fetch these slugs")
    parser.add_argument("--older-than", type=int, default=None, metavar="DAYS",
                        help="incremental: also re-fetch records fetched more than DAYS ago")
    parser.add_argument("--from-cache", action="store_true",
                        help=f"re-parse detail pages cached under {DETAIL_CACHE_DIR} instead of fetching them")
    parser.add_argument("--no-cache", action="store_true", help="do not write detail pages to the cache")
    args = parser.parse_args(argv)
    if args.limit is not None and args.out_dir is None:
        parser.error("--limit is a smoke run; give an explicit --out-dir so data/ is not overwritten")
    if args.out_dir is None:
        args.out_dir = BASE_DIR / "data"
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    spec = load_spec()
    kinds = list(GEM_KINDS) if args.kind == "all" else [KIND_ALIASES[args.kind]]
    kinds.sort(key=lambda kind: kind in OWNED_BY)      # owners first: spirit gems before the skill listing
    summaries: list[dict] = []
    failed = False
    for kind in kinds:
        try:
            summaries.append(
                collect_kind(kind, spec, out_dir=args.out_dir, lang=args.lang, delay=args.delay, limit=args.limit,
                             changed_only=args.changed_only, slugs=args.slugs, older_than_days=args.older_than,
                             cache_dir=None if args.no_cache else DETAIL_CACHE_DIR, from_cache=args.from_cache,
                             listing_cache_dir=None if args.no_cache else PAGE_CACHE_DIR)
            )
        except (CollectionError, requests.RequestException) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            failed = True
            break
    _print_summary(summaries)
    return 1 if failed else 0


def _print_summary(summaries: list[dict]) -> None:
    print("\n=== collect_gems summary ===")
    for s in summaries:
        print(f"{s['kind']} [{s['mode']}]: listing={s['listing_rows']} records={s['records']} "
              f"refetched={s['refetched']} gemcutting={s['gemcutting_rows']} skipped={len(s['skipped'])}")
        if s["added"] or s["removed"]:
            print(f"  added: {s['added']}\n  removed: {s['removed']}")
        if s["skipped"]:
            print("  skipped slugs:", ", ".join(s["skipped"]))
        print("  null_rate:", ", ".join(f"{k}={v:.0%}" for k, v in s["null_rate"].items()))
        if s["warnings"]:
            print("  warnings:", s["warnings"])
        for f in s["files"]:
            print("  wrote:", f)


if __name__ == "__main__":
    sys.exit(main())
