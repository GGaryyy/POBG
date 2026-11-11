"""
maintenance.py — Data status and scoped updates: the layer behind the `status` and `update`
commands (MCP tools `data_status` and `update_data`).

An update always names one scope and fetches a bounded number of pages; nothing here crawls
everything. The collectors keep their own guards (expect_min, parse quality), so a page that no
longer parses stops the update before anything is written. Caches live in a temporary folder
for one call only: a fresh clone has none, and a stale one must not answer an update.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests

from src import __version__
from src import fetch_poe_ninja_builds as ladder
from src.catalog.entity_index import EntityIndex, build_entity_index, fetch_zh_names
from src.catalog.probe import run_probe
from src.catalog.spec import Spec, load_spec
from src.kg.build_graph import GRAPH_PATH, build_knowledge_graph, save_graph
from src.kg.stats import MIN_PARSED_RATIO, build_stat_index, parse_summary, write_stat_index
from src.scrapers import collect_glossary as glossary
from src.scrapers.collect_gems import CollectionError, collect_kind
from src.scrapers.collect_passives import PassiveBuildError, load_tree_data, write_passives
from src.scrapers.collect_passives import build as build_passives
from src.scrapers.common import (
    DATA_LOCK_FILE,
    LockBusy,
    MIN_CACHEABLE_BYTES,
    cached_fetch,
    fetch_html,
    file_lock,
    now_iso,
    read_jsonl,
    safe_cache_name,
    write_jsonl,
)
from src.tools.lookup import BASE_DIR, DATA_LOCK, BadArgument, ServiceUnavailable

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

GEM_SCOPES = {"skill_gems": "skill_gem", "spirit_gems": "spirit_gem", "support_gems": "support_gem"}
PASSIVES = "passives"
LADDER = "ladder"
GLOSSARY = "glossary"
UPDATE_SCOPES = (*GEM_SCOPES, PASSIVES, GLOSSARY, LADDER)
WHOLE_SET_SCOPES = (PASSIVES, GLOSSARY, LADDER)      # re-fetched as a whole: no names, ages, caps or dry run
NOT_UPDATABLE: dict[str, str] = {}      # data sets without an update scope, with the reason
DEFAULT_MAX_GEMS = 20
MAX_GEMS = 40                    # detail pages per call: keeps one tool call under about a minute
MAX_NAMES = 40
MAX_NAME_LEN = 120
MAX_OLDER_THAN_DAYS = 3650
RECENT_SECONDS = 900             # a named or stale gem fetched this recently is not fetched again
GLOSSARY_BATCH = 50              # requests per glossary call; the run is resumed by the next call
GLOSSARY_RUN_SECONDS = 1800      # how long a half-finished glossary run may be resumed
GLOSSARY_GEM_PAGES = 20          # gem pages read to find terms that no listing page links
MIN_GLOSSARY_KEPT_RATIO = 0.9    # a refresh that reaches fewer of the known terms is not written
MIN_GLOSSARY_ZH_RATIO = 0.5      # ... nor one that finds Chinese text for fewer of the terms that had it
MAX_CONSECUTIVE_FAILURES = 5     # network errors in a row before a glossary call gives up
GLOSSARY_TEXT_FIELDS = ("name_en", "name_zh_tw", "text_en", "text_zh_tw")
MIN_LADDER_SHARE_OF_PREVIOUS = 0.5   # same league: a snapshot this much smaller than the last is refused
HOVER_HOST = "cdn.poe2db.tw"
MIN_LADDER_ROWS = 100            # a ladder snapshot below these marks is not written
MIN_LADDER_CLASS_RATIO = 0.9
MIN_LADDER_SKILL_RATIO = 0.5
PROBE_LANGS = ["en", "zh-tw"]
CHANGED_NODE_FIELDS = ("name", "name_zh_tw", "type", "stats", "stats_zh_tw", "neighbors")
NOTHING_WRITTEN = "Nothing was written. Run data_status with check_online=true to see what changed on the site."
REPAIR_HINT = "The data files were updated; run the same update again to rebuild it."
PARTIAL_WRITE = "Some data files may already be updated; run the same update again to finish it."
BUSY = "an update, refresh or online check is already running; try again when it has finished"

Fetcher = Callable[[str], str]

# ---------------------------------------------------------------------------
# SERVICE
# ---------------------------------------------------------------------------


class _Counting:
    """A fetcher that counts its requests."""

    def __init__(self, fetch: Fetcher) -> None:
        self.fetch, self.count = fetch, 0

    def __call__(self, url: str) -> str:
        self.count += 1
        return self.fetch(url)


class _BudgetSpent(Exception):
    """This call has made all the requests it may; the next call continues from the cache."""


class _Budget:
    """A fetcher that stops after `limit` requests in total, gives up after several network errors
    in a row, and asks for a URL that failed in this run only once."""

    def __init__(self, counting: _Counting, limit: int, failed_file: Path, required: set[str] = frozenset()) -> None:
        self.counting, self.limit, self.failed_file, self.required = counting, limit, failed_file, required
        self.failed = set(_read_json(failed_file).get("urls", []))
        self.streak = 0

    def __call__(self, url: str) -> str:
        if url in self.failed:
            raise requests.ConnectionError("failed earlier in this run; not asked again")
        if self.counting.count >= self.limit:
            raise _BudgetSpent
        try:
            body = self.counting(url)
        except requests.RequestException:
            if url in self.required:
                raise                      # a page the crawl cannot do without: the call fails, a later call retries it
            self._remember_failure(url)
            raise
        self.streak = 0
        if len(body.encode("utf-8")) < MIN_CACHEABLE_BYTES:
            self._remember_failure(url, counts_toward_streak=False)   # too small to cache: never asked again this run
        return body

    def _remember_failure(self, url: str, counts_toward_streak: bool = True) -> None:
        self.failed.add(url)
        self.failed_file.parent.mkdir(parents=True, exist_ok=True)
        self.failed_file.write_text(json.dumps({"urls": sorted(self.failed)}), encoding="utf-8")
        if counts_toward_streak:
            self.streak += 1
            if self.streak >= MAX_CONSECUTIVE_FAILURES:
                raise ServiceUnavailable(
                    f"{self.streak} requests in a row failed; the site or the network is down. Nothing was "
                    "written; what was fetched so far is kept, so calling again later continues")


class DataMaintenance:
    """Reports what the local data holds and updates one data set at a time."""

    def __init__(self, base_dir: Path = BASE_DIR, spec: Spec | None = None, graph_path: Path | None = None) -> None:
        self.base_dir = base_dir
        self.spec = spec or load_spec()
        self.data_dir = base_dir / "data"
        self.graph_path = graph_path or base_dir / GRAPH_PATH.relative_to(BASE_DIR)
        self.index_path = self.data_dir / "catalog" / "entity_index.jsonl"
        self.ladder_path = self.data_dir / "community_builds" / "poe_ninja_builds.jsonl"
        self.keywords_path = self.data_dir / "kg" / "keywords.jsonl"
        self.glossary_run = base_dir / "output" / "cache" / "glossary_update"

    # -- status ---------------------------------------------------------------

    def status(self) -> dict:
        """What is stored locally and how old it is. No network."""
        pob2, tree_data = self.spec.source("pob2_tree"), self.spec.source("passive_tree_data")
        return {
            "version": __version__,
            "data_dir": str(self.data_dir),
            "writable": self._writable(),
            "catalog": {"spec_version": self.spec.raw["spec_version"], "verified_at": self.spec.raw["verified_at"],
                        "pob2_tree_version": pob2["version"], "tree_data_version": tree_data["version"]},
            "datasets": [*(self._gem_status(scope) for scope in GEM_SCOPES), self._passive_status(),
                         self._glossary_status(), self._ladder_status(), self._index_status()],
            "update_scopes": list(UPDATE_SCOPES),
            "not_updatable": dict(NOT_UPDATABLE),
        }

    def online_check(self, fetch: Fetcher | None = None) -> dict:
        """Probe the live sources: do the pages still parse, is there a newer passive tree?"""
        counting = _Counting(fetch or self._polite_fetch)
        if not DATA_LOCK.acquire(blocking=False):      # two crawlers at once would halve the polite delay
            raise ServiceUnavailable(BUSY)
        try:
            with file_lock(self.data_dir / DATA_LOCK_FILE), contextlib.redirect_stdout(sys.stderr):
                doc = run_probe(self.spec, PROBE_LANGS, fetcher=counting)
        except LockBusy as exc:
            raise ServiceUnavailable(f"another process is updating this data folder ({exc}); try again later") from exc
        finally:
            DATA_LOCK.release()
        problems = [{key: check[key] for key in ("source", "section", "lang", "count", "expect_min", "error")}
                    for check in doc["checks"] if not check["ok"]]
        return {"ok": doc["ok"], "checks": len(doc["checks"]), "requests": counting.count, "problems": problems,
                "checked_at": now_iso()}

    def _gem_status(self, scope: str) -> dict:
        _, source = self.spec.source_for_kind(GEM_SCOPES[scope])
        return {"name": scope, "update_scope": scope, **_dated(self.base_dir / source["detail_file"])}

    def _passive_status(self) -> dict:
        nodes_path = self.base_dir / self.spec.source("pob2_tree")["nodes_file"]
        classes = _read_json(self.base_dir / self.spec.source("passive_tree_data")["classes_file"])
        nodes, error = _rows(nodes_path)
        fetched = classes.get("fetched_at")
        return {"name": PASSIVES, "update_scope": PASSIVES, "records": len(nodes), **error,
                "tree_version": next((n.get("pob2_tree_version") for n in nodes if n.get("pob2_tree_version")), None),
                "tree_data_version": classes.get("version"),
                "oldest_fetched_at": fetched, "newest_fetched_at": fetched, "oldest_age_days": _age_days(fetched)}

    def _glossary_status(self) -> dict:
        return {"name": GLOSSARY, "update_scope": GLOSSARY, **_dated(self.keywords_path)}

    def _ladder_status(self) -> dict:
        path = self.ladder_path
        rows, _ = _rows(path)
        return {"name": LADDER, "update_scope": LADDER, "league": rows[0].get("league") if rows else None,
                **_dated(path)}

    def _index_status(self) -> dict:
        return {"name": "entity_index", "update_scope": None, "note": "rebuilt by every update",
                **_dated(self.index_path, field="built_at")}

    # -- update ---------------------------------------------------------------

    def update(self, scope: str, names: list[str] | None = None, older_than_days: int | None = None,
               max_gems: int = DEFAULT_MAX_GEMS, dry_run: bool = False, fetch: Fetcher | None = None) -> dict:
        """Update one data set. Gem scopes fetch at most max_gems pages per call (`left` says how
        many remain); dry_run only reports what would be fetched."""
        scope = _scope(scope)
        _check_options(scope, names, older_than_days, max_gems, dry_run)
        if not dry_run and not self._writable():
            raise ServiceUnavailable(f"the data folder {self.data_dir} is not writable; nothing was fetched")
        if not DATA_LOCK.acquire(blocking=False):
            raise ServiceUnavailable(BUSY)
        counting = _Counting(fetch or self._polite_fetch)
        try:
            # A dry run writes nothing, so it does not need the cross-process lock. The SDK already
            # keeps stdout for the protocol; the redirect only keeps stray prints out of it.
            with contextlib.ExitStack() as stack:
                if not dry_run:
                    stack.enter_context(file_lock(self.data_dir / DATA_LOCK_FILE))
                stack.enter_context(contextlib.redirect_stdout(sys.stderr))
                if scope == PASSIVES:
                    result = self._update_passives(counting)
                elif scope == LADDER:
                    result = self._update_ladder(counting)
                elif scope == GLOSSARY:
                    result = self._update_glossary(counting)
                else:
                    result = self._update_gems(scope, names or [], older_than_days, max_gems, dry_run, counting)
        except LockBusy as exc:
            raise ServiceUnavailable(f"another process is updating this data folder ({exc}); try again later") from exc
        finally:
            DATA_LOCK.release()
        return {"scope": scope, "dry_run": dry_run, **result, "requests": counting.count}

    def _update_gems(self, scope: str, names: list[str], older_than_days: int | None, max_gems: int,
                     dry_run: bool, fetch: _Counting) -> dict:
        kind = GEM_SCOPES[scope]
        source_name, source = self.spec.source_for_kind(kind)
        if not (self.base_dir / source["detail_file"]).exists():
            raise ServiceUnavailable(f"there is no local {scope} data to update; a first crawl is done in a terminal: "
                                     "uv run python -m src.scrapers.collect_gems --kind all")
        slugs = self._gem_slugs(kind, names)
        try:
            summary = collect_kind(kind, self.spec, out_dir=self.data_dir, fetcher=fetch, changed_only=True,
                                   slugs=slugs, older_than_days=older_than_days, max_targets=max_gems,
                                   dry_run=dry_run, skip_recent_seconds=RECENT_SECONDS)
        except CollectionError as exc:
            raise ServiceUnavailable(f"{exc} {NOTHING_WRITTEN}") from exc
        except requests.RequestException as exc:
            raise ServiceUnavailable(f"network error: {exc}. {NOTHING_WRITTEN}") from exc
        except OSError as exc:
            raise ServiceUnavailable(f"a data file could not be written ({exc}). {PARTIAL_WRITE}") from exc
        except ValueError as exc:
            raise ServiceUnavailable(f"a local gem file is unreadable ({exc}). {NOTHING_WRITTEN}") from exc
        result = {"selected": summary["targets_total"], "updated": summary["refetched"],
                  "left": summary["targets_left"], "reasons": summary["reasons"],
                  "recently_updated": summary["recently_fetched"], "added": summary["added"],
                  "removed": summary["removed"], "skipped": summary["skipped"], "records": summary["records"]}
        if dry_run:
            return result
        return {**result, **self._rebuild_derived(fetch, kind)}

    def _gem_slugs(self, kind: str, names: list[str]) -> list[str]:
        if not names:
            return []
        if not self.index_path.exists():
            raise ServiceUnavailable("entity index missing; run an update without names first")
        index = EntityIndex.load(self.index_path, base_dir=self.base_dir)
        slugs, unknown = [], []
        for name in names:
            entity = index.get(name, kind) or next(iter(index.exact(name, kind=kind)), None)
            if entity is None:
                close = [hit["name_en"] for hit in index.find(name, kind=kind, limit=3)]
                unknown.append(f"{name!r}" + (f" (close: {', '.join(close)})" if close else ""))
            else:
                slugs.append(entity.slug)
        if unknown:
            raise BadArgument(f"not a {kind} in the local data: {'; '.join(unknown)}. Nothing was fetched.")
        return slugs

    def _update_passives(self, fetch: _Counting) -> dict:
        nodes_path = self.base_dir / self.spec.source("pob2_tree")["nodes_file"]
        old = {n["id"]: n for n in read_jsonl(nodes_path)} if nodes_path.exists() else {}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp)
                tree_data = load_tree_data(self.spec, fetch=fetch, cache_dir=cache / "tree_data")
                nodes, edges, summary = build_passives(
                    self.spec, fetch=fetch, pob2_cache=cache / "pob2", page_cache=cache / "pages",
                    tree_data_cache=cache / "tree_data", tree_data=tree_data)
        except (PassiveBuildError, requests.RequestException) as exc:
            raise ServiceUnavailable(f"{exc}. {NOTHING_WRITTEN}") from exc
        except (KeyError, IndexError, TypeError) as exc:
            traceback.print_exc(file=sys.stderr)   # a changed source and a bug look alike here; keep the trace
            raise ServiceUnavailable(f"the passive tree source changed shape ({type(exc).__name__}: {exc}). "
                                     f"{NOTHING_WRITTEN}") from exc
        rows, families = build_stat_index(nodes)
        ratio = parse_summary(rows)["parsed_ratio"]
        if ratio < MIN_PARSED_RATIO:
            raise ServiceUnavailable(f"only {ratio:.0%} of the passive stat lines parsed. {NOTHING_WRITTEN}")
        try:
            write_passives(self.spec, self.data_dir, nodes, edges, tree_data, summary["built_at"])
            write_stat_index(rows, families, self.data_dir / "kg" / "passive_stats.jsonl",
                             self.data_dir / "kg" / "stat_families.json")
        except OSError as exc:
            raise ServiceUnavailable(f"a data file could not be written ({exc}). {PARTIAL_WRITE}") from exc
        new = {n["id"]: n for n in nodes}
        changed = sum(1 for node_id in new.keys() & old.keys()
                      if any(new[node_id].get(f) != old[node_id].get(f) for f in CHANGED_NODE_FIELDS))
        return {"records": len(nodes), "edges": len(edges), "stat_lines": len(rows), "changed": changed,
                "added": len(new.keys() - old.keys()), "removed": len(old.keys() - new.keys()),
                "tree_version": self.spec.source("pob2_tree")["version"], "tree_data_version": tree_data["version"],
                **self._rebuild_derived(fetch, None)}

    def _update_glossary(self, counting: _Counting) -> dict:
        """Refresh every glossary term. One call makes at most GLOSSARY_BATCH requests and keeps what
        it fetched under output/cache; the next call continues. The file is written once, when the
        whole crawl is in the cache and passes the checks."""
        old = {entry["slug"]: entry for entry in _rows(self.keywords_path)[0] if entry.get("slug")}
        if not old:
            raise ServiceUnavailable("there is no local glossary to update; a first crawl is done in a terminal: "
                                     "uv run python -m src.scrapers.collect_glossary")
        try:
            self._start_or_resume_glossary_run()
            fetch = _Budget(counting, GLOSSARY_BATCH, self.glossary_run / "failed.json", self._glossary_listing_urls())
            parsed = self._crawl_glossary(fetch, set(old))
        except _BudgetSpent:
            cached = sum(1 for _ in (self.glossary_run / "hover").rglob("*.html"))
            return {"done": False, "left": max(2 * len(old) - cached, 1), "fetched": counting.count,
                    "note": "not finished: call update_data with scope glossary again to continue"}
        except requests.RequestException as exc:      # (a RequestException is also an OSError: keep this first)
            raise ServiceUnavailable(f"network error: {exc}. Nothing was written; what was fetched so far is kept, "
                                     "so calling again continues from there") from exc
        except OSError as exc:
            raise ServiceUnavailable(f"the update cache under output/ could not be used ({exc}). {NOTHING_WRITTEN}") from exc
        fresh = {entry["slug"]: entry for entry in glossary.build_entries(self.spec, parsed)}
        self._check_glossary(old, fresh)
        merged = {slug: _merge_term(old.get(slug), fresh.get(slug)) for slug in sorted(set(old) | set(fresh))}
        try:
            write_jsonl(self.keywords_path, merged.values())
        except OSError as exc:
            raise ServiceUnavailable(f"the glossary file could not be written ({exc}); the old one is kept") from exc
        failed = len(fetch.failed)
        derived = self._rebuild_derived(fetch, None)   # before the run cache goes: a repeat then costs no requests
        shutil.rmtree(self.glossary_run, ignore_errors=True)
        changed = sum(1 for slug in fresh if slug in old
                      and any(merged[slug].get(f) != old[slug].get(f) for f in GLOSSARY_TEXT_FIELDS))
        return {"done": True, "left": 0, "records": len(merged), "refreshed": len(fresh), "changed": changed,
                "added": sorted(set(fresh) - set(old)), "kept_without_refresh": len(set(old) - set(fresh)),
                "failed_requests": failed, **derived}

    def _glossary_listing_urls(self) -> set[str]:
        return {self.spec.resolve_url(self.spec.source(source)["slug"], lang)
                for lang in glossary.LANGS for source in (*glossary.PASSIVE_SOURCES, *glossary.GEM_LISTING_SOURCES)}

    def _check_glossary(self, old: dict[str, dict], fresh: dict[str, dict]) -> None:
        """Refuse a crawl that reached too few known terms, mostly lacks English text, or lost the
        Chinese text of most terms that had it (a zh-TW outage must not look like a refresh)."""
        reached = [slug for slug in fresh if slug in old]
        with_english = sum(1 for entry in fresh.values() if entry.get("text_en"))
        had_zh = [slug for slug in reached if old[slug].get("text_zh_tw")]
        has_zh = sum(1 for slug in had_zh if fresh[slug].get("text_zh_tw"))
        if (len(reached) < MIN_GLOSSARY_KEPT_RATIO * len(old)
                or with_english < glossary.MIN_EN_TEXT_RATIO * len(fresh)
                or has_zh < MIN_GLOSSARY_ZH_RATIO * len(had_zh)):
            shutil.rmtree(self.glossary_run, ignore_errors=True)
            raise ServiceUnavailable(
                f"the glossary crawl reached {len(reached)} of {len(old)} known terms, {with_english} of {len(fresh)} "
                f"have English text and {has_zh} of {len(had_zh)} kept their Chinese text. {NOTHING_WRITTEN}")

    def _start_or_resume_glossary_run(self) -> None:
        marker = self.glossary_run / "started"
        if self.glossary_run.exists():
            newest = max((p.stat().st_mtime for p in self.glossary_run.rglob("*") if p.is_file()), default=0.0)
            if not marker.exists() or time.time() - newest > GLOSSARY_RUN_SECONDS:
                shutil.rmtree(self.glossary_run)   # idle too long to resume: the hover hashes may have moved on
        if not marker.exists():
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(now_iso(), encoding="utf-8")

    def _crawl_glossary(self, fetch: Fetcher, known: set[str]) -> dict[str, dict[str, dict]]:
        """The collector's crawl over a run cache: listing pages, then gem pages for the known terms
        no listing links, then every hover snippet. Cached pages cost nothing, so a later call
        gets further."""
        pages, hover, detail = (self.glossary_run / name for name in ("pages", "hover", "detail"))
        for lang in glossary.LANGS:
            for source in (*glossary.PASSIVE_SOURCES, *glossary.GEM_LISTING_SOURCES):
                slug = self.spec.source(source)["slug"]
                cached_fetch(self.spec.resolve_url(slug, lang), pages / f"{lang}_{slug}.html", fetch)
        hashes = glossary.harvest_refs(self.spec, page_cache=pages, detail_cache=detail)
        mentions = glossary._gems_mentioning(self.spec, self.data_dir)
        gems = sorted({mentions[slug][0] for slug in known - set(hashes) if mentions.get(slug)})[:GLOSSARY_GEM_PAGES]
        for gem in gems:     # optional: a gem page that fails only means fewer terms are found through it
            try:
                cached_fetch(self.spec.resolve_url(gem, "en"), detail / "en" / f"{safe_cache_name(gem)}.html", fetch)
            except requests.RequestException as exc:
                print(f"[WARN] glossary: gem page {gem}: {exc}", file=sys.stderr)
        if gems:
            hashes = glossary.harvest_refs(self.spec, page_cache=pages, detail_cache=detail)
        options = {"fetch": fetch, "data_dir": self.data_dir, "page_cache": pages, "cache_dir": hover}
        glossary.fill_from_gem_hovers(self.spec, hashes, **options)
        parsed = glossary.crawl(self.spec, hashes, fetch=fetch, cache_dir=hover)
        if glossary.fill_from_gem_hovers(self.spec, hashes, **options):
            parsed = glossary.crawl(self.spec, hashes, fetch=fetch, cache_dir=hover)
        return parsed

    def _update_ladder(self, counting: _Counting) -> dict:
        """A new poe.ninja snapshot (at most 14 requests). Character and account names are used in
        memory to tell characters apart and are never written."""
        previous, _ = _rows(self.ladder_path)

        def get_json(url: str) -> dict:
            counting.count += 1
            return ladder._get_json(url)

        def get_binary(url: str) -> bytes:
            counting.count += 1
            return ladder._get_binary(url)

        try:
            records = ladder._validate(ladder.collect_builds(get_json, get_binary))
        except requests.RequestException as exc:
            raise ServiceUnavailable(f"network error: {exc}. {NOTHING_WRITTEN}") from exc
        except (RuntimeError, KeyError, TypeError, ValueError, AttributeError) as exc:
            traceback.print_exc(file=sys.stderr)
            raise ServiceUnavailable(f"poe.ninja answered in an unexpected shape ({type(exc).__name__}: {exc}). "
                                     f"{NOTHING_WRITTEN}") from exc
        _check_ladder(records, previous)
        try:
            ladder._write_jsonl(records, self.ladder_path)
        except OSError as exc:
            raise ServiceUnavailable(f"the ladder file could not be written ({exc}); the old snapshot is kept") from exc
        return {"records": len(records), "league": records[0]["league"],
                "previous_records": len(previous), "previous_league": previous[0].get("league") if previous else None}

    def _rebuild_derived(self, fetch: Fetcher, gem_kind: str | None) -> dict:
        """Entity index and, when a graph file exists, the knowledge graph."""
        try:
            entities = self._rebuild_index(fetch, gem_kind)
            if self.graph_path.exists():
                graphml = self.graph_path.with_suffix(".graphml")
                save_graph(build_knowledge_graph(self.spec, self.data_dir), self.graph_path,
                           graphml if graphml.exists() else None)
        except (requests.RequestException, ValueError, OSError) as exc:
            raise ServiceUnavailable(f"the name index or graph was not rebuilt ({exc}). {REPAIR_HINT}") from exc
        return {"index_entities": entities}

    def _rebuild_index(self, fetch: Fetcher, gem_kind: str | None) -> int:
        """Chinese names are reused from the current index. The updated gem scope's own /tw/ listing
        is fetched (one request) when any of its gems still has no Chinese name; other scopes are
        left as they are."""
        zh = self._known_zh_names()
        if gem_kind and self._gems_without_zh(gem_kind, zh):
            source_name, _ = self.spec.source_for_kind(gem_kind)
            with tempfile.TemporaryDirectory() as tmp:
                zh.update(fetch_zh_names(self.spec, fetcher=fetch, cache_dir=Path(tmp), sources=(source_name,)))
        entities = build_entity_index(self.spec, data_dir=self.data_dir, zh_names=zh, passive_slugs={})
        write_jsonl(self.index_path, (entity.as_dict() for entity in entities))
        return len(entities)

    def _known_zh_names(self) -> dict[str, str]:
        if not self.index_path.exists():
            return {}
        return {row["slug"]: row["name_zh_tw"] for row in read_jsonl(self.index_path)
                if row.get("name_zh_tw") and row.get("kind") != "keyword"}

    def _gems_without_zh(self, kind: str, zh: dict[str, str]) -> bool:
        _, source = self.spec.source_for_kind(kind)
        return any(record.get("slug") not in zh for record in read_jsonl(self.base_dir / source["detail_file"]))

    # -- helpers --------------------------------------------------------------

    def _polite_fetch(self, url: str) -> str:
        robots = self.spec.raw["robots"]
        delay = robots["hover_delay_seconds"] if urlparse(url).hostname == HOVER_HOST else robots["polite_delay_seconds"]
        return fetch_html(url, delay=delay)

    def _writable(self) -> bool:
        return self.data_dir.is_dir() and os.access(self.data_dir, os.W_OK)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def _scope(scope: str | None) -> str:
    wanted = (scope or "").strip().lower()
    if wanted in UPDATE_SCOPES:
        return wanted
    if wanted in NOT_UPDATABLE:
        raise BadArgument(f"{wanted} cannot be updated by command: {NOT_UPDATABLE[wanted]}")
    raise BadArgument(f"scope is required and must be one of: {', '.join(UPDATE_SCOPES)} "
                      "(one data set per call; there is no update for everything)")


def _check_options(scope: str, names: list[str] | None, older_than_days: int | None, max_gems: int,
                   dry_run: bool) -> None:
    if isinstance(max_gems, bool) or not isinstance(max_gems, int):
        raise BadArgument("max_gems must be a whole number")
    if older_than_days is not None and (isinstance(older_than_days, bool) or not isinstance(older_than_days, int)):
        raise BadArgument("older_than_days must be a whole number")
    if scope in WHOLE_SET_SCOPES:
        if names or older_than_days is not None or dry_run or max_gems != DEFAULT_MAX_GEMS:
            raise BadArgument("names, older_than_days, max_gems and dry_run only apply to the gem scopes; "
                              f"a {scope} update always re-fetches the whole data set")
        return
    if not 1 <= max_gems <= MAX_GEMS:
        raise BadArgument(f"max_gems must be between 1 and {MAX_GEMS}")
    if older_than_days is not None and not 0 <= older_than_days <= MAX_OLDER_THAN_DAYS:
        raise BadArgument(f"older_than_days must be between 0 and {MAX_OLDER_THAN_DAYS}")
    if names and len(names) > MAX_NAMES:
        raise BadArgument(f"at most {MAX_NAMES} names per call")
    for name in names or []:
        if not isinstance(name, str) or not name.strip():
            raise BadArgument("names must be non-empty strings")
        if len(name) > MAX_NAME_LEN:
            raise BadArgument(f"a name is longer than {MAX_NAME_LEN} characters")


def _check_ladder(records: list[dict], previous: list[dict]) -> None:
    """Refuse a snapshot that is too small, mostly unnamed, without keystones, or much smaller than
    the last one of the same league: the site's format has probably changed."""
    total = len(records)
    with_class = sum(1 for r in records if r.get("class"))
    with_skill = sum(1 for r in records if r.get("main_skill"))
    with_keystones = sum(1 for r in records if r.get("keystones"))
    same_league = bool(previous) and total > 0 and previous[0].get("league") == records[0].get("league")
    if (total < MIN_LADDER_ROWS or with_class < MIN_LADDER_CLASS_RATIO * total
            or with_skill < MIN_LADDER_SKILL_RATIO * total or with_keystones == 0
            or (same_league and total < MIN_LADDER_SHARE_OF_PREVIOUS * len(previous))):
        raise ServiceUnavailable(f"poe.ninja returned {total} characters, {with_class} with a class, {with_skill} with "
                                 f"a skill and {with_keystones} with keystones (the previous snapshot has "
                                 f"{len(previous)}); its response format has probably changed. The old snapshot is kept.")


def _merge_term(old: dict | None, fresh: dict | None) -> dict:
    """A refreshed glossary term never loses text: a field the crawl did not get keeps its old value,
    and then the entry keeps its old date too, so a citation never claims older text is new."""
    if old is None or fresh is None:
        return fresh or old
    merged = {**old, **{key: value for key, value in fresh.items() if value not in (None, "", [])}}
    if any(old.get(field) and not fresh.get(field) for field in GLOSSARY_TEXT_FIELDS):
        merged["fetched_at"] = old.get("fetched_at")
    return merged


def _rows(path: Path) -> tuple[list[dict], dict]:
    """The rows of a JSONL file, or none plus an `error` entry when it cannot be read."""
    if not path.exists():
        return [], {}
    try:
        return read_jsonl(path), {}
    except (ValueError, OSError) as exc:
        return [], {"error": f"unreadable ({type(exc).__name__}); update this data set or restore the file"}


def _dated(path: Path, field: str = "fetched_at") -> dict:
    """Record count and the oldest / newest date of one JSONL file (zeros when it is missing)."""
    rows, error = _rows(path)
    dates = sorted(str(row[field]) for row in rows if row.get(field))
    oldest, newest = (dates[0], dates[-1]) if dates else (None, None)
    return {"records": len(rows), f"oldest_{field}": oldest, f"newest_{field}": newest,
            "oldest_age_days": _age_days(oldest), **error}


def _age_days(stamp: str | None) -> int | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - when).days, 0)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}
