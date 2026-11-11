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
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from src import __version__
from src.catalog.entity_index import EntityIndex, build_entity_index, fetch_zh_names
from src.catalog.probe import run_probe
from src.catalog.spec import Spec, load_spec
from src.kg.build_graph import GRAPH_PATH, build_knowledge_graph, save_graph
from src.kg.stats import MIN_PARSED_RATIO, build_stat_index, parse_summary, write_stat_index
from src.scrapers.collect_gems import CollectionError, collect_kind
from src.scrapers.collect_passives import PassiveBuildError, load_tree_data, write_passives
from src.scrapers.collect_passives import build as build_passives
from src.scrapers.common import DATA_LOCK_FILE, LockBusy, fetch_html, file_lock, now_iso, read_jsonl, write_jsonl
from src.tools.lookup import BASE_DIR, DATA_LOCK, BadArgument, ServiceUnavailable

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

GEM_SCOPES = {"skill_gems": "skill_gem", "spirit_gems": "spirit_gem", "support_gems": "support_gem"}
PASSIVES = "passives"
UPDATE_SCOPES = (*GEM_SCOPES, PASSIVES)
NOT_UPDATABLE = {
    "glossary": "terminal only: uv run python -m src.scrapers.collect_glossary (about 700 small requests)",
    "ladder": "the poe.ninja fetcher does not parse the site's current response format; the snapshot stays as it is",
}
DEFAULT_MAX_GEMS = 20
MAX_GEMS = 40                    # detail pages per call: keeps one tool call under about a minute
MAX_NAMES = 40
MAX_NAME_LEN = 120
MAX_OLDER_THAN_DAYS = 3650
RECENT_SECONDS = 900             # a named or stale gem fetched this recently is not fetched again
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


class DataMaintenance:
    """Reports what the local data holds and updates one data set at a time."""

    def __init__(self, base_dir: Path = BASE_DIR, spec: Spec | None = None, graph_path: Path | None = None) -> None:
        self.base_dir = base_dir
        self.spec = spec or load_spec()
        self.data_dir = base_dir / "data"
        self.graph_path = graph_path or base_dir / GRAPH_PATH.relative_to(BASE_DIR)
        self.index_path = self.data_dir / "catalog" / "entity_index.jsonl"

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
            with contextlib.redirect_stdout(sys.stderr):
                doc = run_probe(self.spec, PROBE_LANGS, fetcher=counting)
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
        return {"name": "glossary", "update_scope": None, "note": NOT_UPDATABLE["glossary"],
                **_dated(self.data_dir / "kg" / "keywords.jsonl")}

    def _ladder_status(self) -> dict:
        path = self.data_dir / "community_builds" / "poe_ninja_builds.jsonl"
        rows, _ = _rows(path)
        return {"name": "ladder", "update_scope": None, "note": NOT_UPDATABLE["ladder"],
                "league": rows[0].get("league") if rows else None, **_dated(path)}

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
        return fetch_html(url, delay=self.spec.raw["robots"]["polite_delay_seconds"])

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
    if scope == PASSIVES:
        if names or older_than_days is not None or dry_run or max_gems != DEFAULT_MAX_GEMS:
            raise BadArgument("names, older_than_days, max_gems and dry_run only apply to the gem scopes; "
                              "a passives update always re-fetches the whole tree (7 requests)")
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
