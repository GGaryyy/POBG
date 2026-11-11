"""
lookup.py — Cited, local-first lookups over the local poe2db data (the tool layer for AI agents).

Every result carries the poe2db URLs (English + Traditional Chinese) or, for passive nodes
without a poe2db page, the PoB2 tree it came from. Nothing here calls an LLM; answers come from
data/ and the knowledge graph, and `refresh_gem` is the only call that touches the network.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path

import networkx as nx

from src.catalog.entity_index import PASSIVE_TYPE_TO_KIND, EntityIndex
from src.catalog.spec import GEM_KINDS, Spec, load_spec
from src.kg.build_graph import GRAPH_PATH, build_knowledge_graph, load_graph
from src.scrapers.collect_gems import BROKEN_WARNINGS, DETAIL_CACHE_DIR
from src.scrapers.collect_passives import ZH_FROM_TREE_DATA
from src.scrapers.common import (
    DATA_LOCK_FILE,
    LockBusy,
    atomic_write_text,
    clean_text,
    fetch_html,
    file_lock,
    read_jsonl,
    safe_cache_name,
    write_jsonl,
)
from src.scrapers.gem_detail import parse_detail

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MAX_LIMIT = 200
MAX_STAT_LIMIT = 100   # passives_with_stat rows are large; 200 of them pass 140,000 characters
MAX_QUERY_LEN = 500    # names and free-text queries
MAX_FILTER_LEN = 120   # tag / class / weapon / text filters
EXAMPLES = 10
TREE_DATA_LABEL = "Passive tree data on poe2db"
LANGS = ("en", "zh-tw")
LISTING_FIELDS = ("tag_slugs", "attribute_colour", "summary")
NEGATIVE_KINDS = {"reduced", "less", "slower", "lose"}
ENTITY_KINDS = (*GEM_KINDS, *PASSIVE_TYPE_TO_KIND.values(), "keyword")
_CJK_RE = re.compile(r"[㐀-鿿]")
DATA_LOCK = threading.Lock()


class LookupFailed(ValueError):
    """Base class for lookup errors."""


class NotFound(LookupFailed):
    """The entity / keyword does not exist locally."""


class BadArgument(LookupFailed):
    """The arguments are invalid."""


class ServiceUnavailable(LookupFailed):
    """A required artefact is missing or a refresh could not be trusted."""


def is_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


# ---------------------------------------------------------------------------
# SERVICE
# ---------------------------------------------------------------------------


class LookupService:
    """Loads the entity index, records, glossary, stat index and graph once."""

    def __init__(self, base_dir: Path = BASE_DIR, spec: Spec | None = None, graph_path: Path | None = None) -> None:
        self.base_dir = base_dir
        self.spec = spec or load_spec()
        self.data_dir = base_dir / "data"
        self.index = EntityIndex.load(self.data_dir / "catalog" / "entity_index.jsonl", base_dir=base_dir)
        self.keywords = {k["slug"]: k for k in _optional(self.data_dir / "kg" / "keywords.jsonl")}
        nodes_file = self.data_dir / Path(self.spec.source("pob2_tree")["nodes_file"]).relative_to("data")
        self.passives = {p["id"]: p for p in read_jsonl(nodes_file)}
        self.passive_by_slug = {p["slug"]: p for p in self.passives.values() if p.get("slug")}
        self.stat_rows = _optional(self.data_dir / "kg" / "passive_stats.jsonl")
        self._zh_to_en = _invert_templates(self.stat_rows)
        self.gems = {kind: self._read_gems(kind) for kind in GEM_KINDS}
        self.graph_path = graph_path or base_dir / GRAPH_PATH.relative_to(BASE_DIR)
        self.graph = self._load_graph(self.graph_path)
        self._class_gems: dict[str, dict[str, dict]] | None = None
        pob2 = self.spec.source("pob2_tree")
        self._pob2_url = pob2["url"].format(version=pob2["version"])
        tree_data = self.spec.source("passive_tree_data")
        self._tree_data_url = tree_data["url"].format(version=tree_data["version"], lang=self.spec.raw["languages"]["zh-tw"])
        self.classes_doc = self._read_classes(self.data_dir / Path(tree_data["classes_file"]).relative_to("data"))
        self._class_aliases = _class_aliases(self.classes_doc)

    # -- entities -------------------------------------------------------------

    def lookup_entity(self, query: str, kind: str | None = None, limit: int = 5) -> dict:
        _require(query, "query")
        hits = self.index.find(clean_text(query), kind=_kind(kind, ENTITY_KINDS), limit=_limit(limit))
        keep = ("slug", "kind", "name_en", "name_zh_tw", "url_en", "url_zh_tw", "tier", "match_type")
        return {"query": query, "hits": [{k: h.get(k) for k in keep} for h in hits]}

    def get_gem(self, slug_or_name: str) -> dict:
        entity = self._resolve(slug_or_name, GEM_KINDS)
        kind, record = self._freshest_gem(entity["kind"], entity["slug"])
        result = {
            "gem": record,
            "keywords": self._keyword_briefs(record.get("keyword_slugs") or []),
            "sources": _sources(record.get("source_url"), record.get("url_zh_tw"), record.get("fetched_at")),
        }
        if kind == "support_gem":
            result["supports_skills"] = self._edge_names(f"gem:{entity['slug']}", "SUPPORTS", outgoing=True)
        else:
            result["supported_by"] = self._edge_names(f"gem:{entity['slug']}", "SUPPORTS", outgoing=False)
        return result

    def _freshest_gem(self, kind: str, slug: str) -> tuple[str, dict]:
        """poe2db lists every spirit gem among the skill gems too, so such a gem is stored once per
        kind and the copies can differ in age after a scoped update. Answer from the newest one."""
        copies = [(k, self.gems[k][slug]) for k in GEM_KINDS if slug in self.gems.get(k, {})]
        if len(copies) < 2:
            return kind, self._gem_record(kind, slug)
        return max(copies, key=lambda copy: (str(copy[1].get("fetched_at") or ""), copy[0] == kind))

    def get_passive(self, slug_or_id: str) -> dict:
        _require(slug_or_id, "slug or id")
        node = self.passives.get(str(slug_or_id)) or self.passive_by_slug.get(slug_or_id)
        if node is None:
            entity = self._resolve(slug_or_id, tuple(PASSIVE_TYPE_TO_KIND.values()))
            node = self.passives.get(str(entity.get("node_id"))) or self.passive_by_slug.get(entity["slug"])
        if node is None:
            raise NotFound(f"unknown passive {slug_or_id!r}")
        neighbors = [self._passive_brief(self.passives[n]) for n in node.get("neighbors", []) if n in self.passives]
        return {
            "passive": node,
            "keywords": self._keyword_briefs(node.get("keyword_slugs") or []),
            "neighbors": neighbors,
            "sources": self._passive_sources(node),
        }

    # -- stats ----------------------------------------------------------------

    def passives_with_stat(self, query: str, lang: str | None = None, kind: str | None = None,
                           include_without_page: bool = False, limit: int = 50) -> dict:
        """Which passive nodes give a stat. Nodes with a poe2db page come first; the rest
        (small / attribute / some ascendancy nodes, sourced from PoB2) are collapsed into counts
        unless include_without_page is set."""
        _require(query, "query")
        if not self.stat_rows:
            raise ServiceUnavailable("stat index missing; run python -m src.kg.stats")
        q = clean_text(query).lower()
        lang = _lang(lang) or ("zh-tw" if is_cjk(q) else "en")
        _cap(kind, "kind")
        en_templates = self._zh_query_templates(q) if lang == "zh-tw" else None
        matches = []
        for row in self.stat_rows:
            rank = _stat_rank(row, q, en_templates)
            if rank is None or (kind and row["kind"] != kind):
                continue
            matches.append((rank, row))
        matches.sort(key=lambda m: (m[0], -_signed(m[1])))
        result = self._stat_result(query, lang, matches, include_without_page, min(_limit(limit), MAX_STAT_LIMIT))
        kinds = {row["kind"] for row in self.stat_rows}
        if kind and kind not in kinds:   # a typo would otherwise look like "no passive gives this"
            result["available_kinds"] = sorted(kinds)
        return result

    def _stat_result(self, query: str, lang: str, matches: list, include_without_page: bool, limit: int) -> dict:
        families: dict[str, int] = {}
        with_page, without_page, seen = [], [], set()
        for _, row in matches:
            families[row["family"]] = families.get(row["family"], 0) + 1
            node = self.passives.get(row["node_id"])
            if node is None or node["id"] in seen:
                continue
            seen.add(node["id"])
            entry = {**self._passive_brief(node), "line": row["text"], "line_zh_tw": row.get("text_zh_tw"),
                     "value": row["value"], "kind": row["kind"], "family": row["family"]}
            (with_page if node.get("url_en") else without_page).append(entry)
        result = {
            "query": query, "lang": lang,
            "families": dict(sorted(families.items(), key=lambda kv: -kv[1])[:20]),
            "with_page": with_page[:limit],
            "with_page_total": len(with_page),
            "without_page": {
                "total": len(without_page),
                "by_type": _count(without_page, "type"),
                "by_family": dict(sorted(_count(without_page, "family").items(), key=lambda kv: -kv[1])[:10]),
                "source": self._pob2_url,
            },
        }
        if include_without_page:
            result["without_page"]["nodes"] = without_page[:limit]
        return result

    def _zh_query_templates(self, q: str) -> set[str]:
        """English templates whose Chinese template contains the query (reuses English ranks)."""
        return {en for zh, ens in self._zh_to_en.items() if q in zh for en in ens}

    # -- keywords -------------------------------------------------------------

    def explain_keyword(self, query: str, lang: str | None = None) -> dict:
        _require(query, "query")
        if not self.keywords:
            raise ServiceUnavailable("glossary missing; run python -m src.scrapers.collect_glossary")
        entry = self._find_keyword(clean_text(query))
        if entry is None:
            raise NotFound(f"unknown keyword {query!r}")
        lang = _lang(lang) or ("zh-tw" if is_cjk(query) else "en")
        text = entry.get("text_zh_tw") if lang == "zh-tw" and entry.get("text_zh_tw") else entry.get("text_en")
        return {
            "keyword": entry,
            "answer_text": text,
            "see_also": self._keyword_briefs(entry.get("see_also") or []),
            "mentioned_by": self._mentioned_by(f"keyword:{entry['slug']}"),
            "sources": _sources(entry.get("url_en"), entry.get("url_zh_tw"), entry.get("fetched_at")),
        }

    # -- structured gem filter --------------------------------------------------

    def gems_by(self, tag: str | None = None, tier: int | None = None, class_name: str | None = None,
                weapon: str | None = None, kind: str | None = None, limit: int = 50,
                text: str | None = None) -> dict:
        text = clean_text(text) if text else None
        for label, value in (("tag", tag), ("class_name", class_name), ("weapon", weapon), ("text", text)):
            _cap(value, label)
        if all(v is None or v == "" for v in (tag, tier, class_name, weapon, kind, text)):
            raise BadArgument("give at least one filter: tag, tier, class_name, weapon, kind or text")
        kind = _kind(kind, GEM_KINDS)
        class_gems = self._gems_for_class(class_name) if class_name else None
        hits = []
        for gem_kind in GEM_KINDS:
            if kind and gem_kind != kind:
                continue
            for rec in self.gems[gem_kind].values():
                if _gem_matches(rec, tag, tier, weapon, text) and (class_gems is None or rec["slug"] in class_gems):
                    hits.append({"slug": rec["slug"], "kind": gem_kind, "name": rec["name"], "tier": rec.get("tier"),
                                 "tags": rec.get("tags"), "url_en": rec.get("source_url"), "url_zh_tw": rec.get("url_zh_tw"),
                                 **({"gemcutting": class_gems[rec["slug"]]} if class_gems else {})})
        return {"filters": {"tag": tag, "tier": tier, "class_name": class_name, "weapon": weapon, "kind": kind,
                            "text": text},
                "total": len(hits), "gems": hits[:_limit(limit)]}

    # -- refresh (network) -------------------------------------------------------

    def refresh_gem(self, slug_or_name: str, fetcher=None) -> dict:
        """Re-fetch one gem page through the catalog, update its record in place, report changes.

        Refuses to overwrite the stored record when the fresh page does not parse (markup drift
        or an error page). The knowledge graph is not rebuilt; run python -m src.kg.build_graph.
        """
        entity = self._resolve(slug_or_name, GEM_KINDS)
        try:
            with DATA_LOCK, file_lock(self.data_dir / DATA_LOCK_FILE):
                return self._refresh_locked(entity, fetcher or self._polite_fetch)
        except LockBusy as exc:
            raise ServiceUnavailable(f"another process is updating this data folder ({exc}); try again later") from exc

    def _polite_fetch(self, url: str) -> str:
        """Refreshes are serialised by the lock, so this delay also caps how often a client can hit poe2db."""
        return fetch_html(url, delay=self.spec.raw["robots"]["polite_delay_seconds"])

    def _refresh_locked(self, entity: dict, fetch) -> dict:
        _, source = self.spec.source_for_kind(entity["kind"])
        path = self.base_dir / source["detail_file"]
        records = read_jsonl(path)
        position = next((i for i, r in enumerate(records) if r.get("slug") == entity["slug"]), None)
        if position is None:
            raise NotFound(f"gem {entity['slug']} is not in {source['detail_file']}")
        old = records[position]
        html = fetch(self.spec.resolve_url(entity["slug"], "en"))
        new = parse_detail(html, self.spec, entity["slug"], entity["kind"])
        broken = set(new["parse_warnings"]) & set(BROKEN_WARNINGS)
        if broken or not new.get("name"):
            raise ServiceUnavailable(f"fresh page for {entity['slug']} did not parse ({sorted(broken)}); "
                                     "kept the stored record — run python -m src.catalog.probe")
        for key in LISTING_FIELDS:
            new[key] = old.get(key)
        if new["tier"] is None:
            new["tier"] = old.get("tier")
        changed = sorted(k for k in new if k not in ("fetched_at", "parse_warnings") and new.get(k) != old.get(k))
        records[position] = new
        self._cache_detail_page(entity["slug"], html)
        write_jsonl(path, records)
        self.gems[entity["kind"]][entity["slug"]] = new
        self.index = EntityIndex.load(self.data_dir / "catalog" / "entity_index.jsonl", base_dir=self.base_dir)
        return {"slug": entity["slug"], "changed_fields": changed, "gem": new,
                "graph_stale": True,
                "sources": _sources(new["source_url"], new["url_zh_tw"], new["fetched_at"])}

    def _cache_detail_page(self, slug: str, html: str) -> None:
        cache_root = self.base_dir / DETAIL_CACHE_DIR.relative_to(BASE_DIR)
        atomic_write_text(cache_root / "en" / f"{safe_cache_name(slug)}.html", html)

    # -- loading helpers ---------------------------------------------------------

    def _read_gems(self, kind: str) -> dict[str, dict]:
        _, source = self.spec.source_for_kind(kind)
        path = self.base_dir / source["detail_file"]
        return {r["slug"]: r for r in read_jsonl(path)} if path.exists() else {}

    def _load_graph(self, path: Path) -> nx.MultiDiGraph | None:
        if path.exists():
            try:
                return load_graph(path)
            except (ValueError, KeyError, OSError) as exc:  # json.JSONDecodeError is a ValueError
                print(f"[WARN] knowledge graph unreadable ({exc}); rebuilding in memory", file=sys.stderr)
        try:
            return build_knowledge_graph(self.spec, self.data_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[WARN] knowledge graph unavailable: {exc}", file=sys.stderr)
            return None

    # -- helpers -----------------------------------------------------------------

    def _gem_record(self, kind: str, slug: str) -> dict:
        record = self.gems.get(kind, {}).get(slug)
        if record is None:
            raise NotFound(f"no local record for gem {slug}")
        return record

    def _resolve(self, query: str, kinds: tuple[str, ...]) -> dict:
        _require(query, "slug or name")
        query = clean_text(query)
        for kind in kinds:
            entity = self.index.get(query, kind=kind)
            if entity is not None:
                return entity.as_dict()
        for entity in self.index.exact(query):
            if entity.kind in kinds:
                return {**entity.as_dict(), "match_type": "exact"}
        raise NotFound(f"no {'/'.join(kinds)} matches {query!r}; try lookup_entity first")

    def _find_keyword(self, query: str) -> dict | None:
        if query in self.keywords:
            return self.keywords[query]
        q = query.lower()
        for field in ("name_en", "name_zh_tw", "slug"):
            for entry in self.keywords.values():
                if (entry.get(field) or "").lower() == q:
                    return entry
        candidates = [e for e in self.keywords.values()
                      if q in (e.get("name_en") or "").lower() or q in (e.get("name_zh_tw") or "")]
        return min(candidates, key=lambda e: len(e.get("name_en") or ""), default=None)

    def _keyword_briefs(self, slugs: list[str]) -> list[dict]:
        out = []
        for slug in slugs:
            kw = self.keywords.get(slug, {})
            out.append({"slug": slug, "name_en": kw.get("name_en"), "name_zh_tw": kw.get("name_zh_tw"),
                        "url_en": kw.get("url_en") or self.spec.resolve_url(slug, "en")})
        return out

    def _passive_brief(self, node: dict) -> dict:
        return {"id": node["id"], "name": node.get("name"), "name_zh_tw": node.get("name_zh_tw"),
                "type": node.get("type"), "ascendancy": node.get("ascendancy"),
                "url_en": node.get("url_en"), "url_zh_tw": node.get("url_zh_tw")}

    def _passive_sources(self, node: dict) -> list[dict]:
        if node.get("url_en"):
            return _sources(node["url_en"], node.get("url_zh_tw"), None)
        out = [{"label": f"PathOfBuilding-PoE2 tree {node.get('pob2_tree_version')}", "url": self._pob2_url}]
        if node.get("zh_source") == ZH_FROM_TREE_DATA:  # where the Chinese name and stat lines come from
            out.append({"label": TREE_DATA_LABEL, "url": self._tree_data_url})
        return out

    def canonical_class(self, name: str) -> str:
        """English class or ascendancy name for a Chinese (or English) one; the input when unknown."""
        return self._class_aliases.get(clean_text(name).casefold(), name)

    def class_info(self, name: str) -> dict | None:
        """{"class", "ascendancy"} for an English or Chinese class or ascendancy name; None when unknown."""
        english = self.canonical_class(name).casefold()
        for cls in (self.classes_doc or {}).get("classes", []):
            if cls["name"].casefold() == english:
                return {"class": cls["name"], "ascendancy": None}
            for asc in cls.get("ascendancies", []):
                if asc["name"].casefold() == english:
                    return {"class": cls["name"], "ascendancy": asc["name"]}
        return None

    def _read_classes(self, path: Path) -> dict | None:
        if not path.exists():
            print(f"[WARN] {path.name} missing; class names are matched in English only "
                  "(run python -m src.scrapers.collect_passives)", file=sys.stderr)
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[WARN] {path.name} unreadable ({type(exc).__name__}); class names are matched in English only",
                  file=sys.stderr)
            return None
        return doc if isinstance(doc, dict) else None

    def _edge_names(self, node_id: str, edge_type: str, outgoing: bool) -> dict:
        if self.graph is None or node_id not in self.graph:
            return {"total": 0, "examples": []}
        edges = self.graph.out_edges(node_id, data=True) if outgoing else self.graph.in_edges(node_id, data=True)
        others = [(v if outgoing else u) for u, v, d in edges if d.get("type") == edge_type]
        return {"total": len(others),
                "examples": [{"slug": self.graph.nodes[o].get("slug"), "name": self.graph.nodes[o].get("name")}
                             for o in others[:EXAMPLES]]}

    def _mentioned_by(self, node_id: str) -> dict:
        if self.graph is None or node_id not in self.graph:
            return {}
        groups: dict[str, list[dict]] = {"gem": [], "passive": [], "keyword": []}
        for u, _, d in self.graph.in_edges(node_id, data=True):
            data = self.graph.nodes[u]
            if d.get("type") in ("MENTIONS", "HAS_TAG") and data.get("type") in groups:
                groups[data["type"]].append({"name": data.get("name"), "slug": data.get("slug"),
                                             "url_en": data.get("url_en")})
        return {k: {"total": len(v), "examples": _dedupe_by_name(v)[:EXAMPLES]} for k, v in groups.items()}

    def _gems_for_class(self, class_name: str) -> dict[str, dict]:
        if self.graph is None:
            raise ServiceUnavailable("class filter needs the knowledge graph; run python -m src.kg.build_graph")
        if self._class_gems is None:
            self._class_gems = {}
            for u, v, d in self.graph.edges(data=True):
                if d.get("type") != "GEMCUTTING":
                    continue
                info = {"class": self.graph.nodes[u].get("name"), "group": d.get("group"), "tier": d.get("tier")}
                for key in {(info["class"] or "").lower(), (info["group"] or "").lower()}:
                    self._class_gems.setdefault(key, {})[self.graph.nodes[v]["slug"]] = info
        return self._class_gems.get(class_name.strip().lower(), {})


# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def _optional(path: Path) -> list[dict]:
    return read_jsonl(path) if path.exists() else []


def _require(value: str, label: str) -> None:
    if value is None or not str(value).strip():
        raise BadArgument(f"{label} must not be empty")
    _cap(value, label, MAX_QUERY_LEN)


def _cap(value, label: str, limit: int = MAX_FILTER_LEN) -> None:
    """Over-long text is refused before it can be echoed back in a result or an error."""
    if value is not None and len(str(value)) > limit:
        raise BadArgument(f"{label} is longer than {limit} characters")


def _limit(limit: int) -> int:
    if limit < 1:
        raise BadArgument("limit must be >= 1")
    return min(limit, MAX_LIMIT)


def answer_lang(lang: str | None, default: str = "en") -> str:
    """A validated answer language for callers outside this module."""
    return _lang(lang) or default


def _lang(lang: str | None) -> str | None:
    if lang is None or lang == "":
        return None
    _cap(lang, "lang")
    normalised = lang.strip().lower()
    if normalised not in LANGS:
        raise BadArgument(f"lang must be one of {LANGS}, not {lang!r}")
    return normalised


def _kind(kind: str | None, allowed: tuple[str, ...]) -> str | None:
    if kind is None or kind == "":
        return None
    _cap(kind, "kind")
    if kind not in allowed:
        raise BadArgument(f"kind must be one of {allowed}, not {kind!r}")
    return kind


def _class_aliases(doc: dict | None) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for cls in (doc or {}).get("classes", []):
        for entry in (cls, *cls.get("ascendancies", [])):
            for alias in (entry.get("name"), entry.get("name_zh_tw")):
                if alias and entry.get("name"):
                    aliases[alias.casefold()] = entry["name"]
    return aliases


def _sources(url_en: str | None, url_zh_tw: str | None, fetched_at: str | None) -> list[dict]:
    out = []
    if url_en:
        out.append({"label": "poe2db (en)", "url": url_en, "fetched_at": fetched_at})
    if url_zh_tw:
        out.append({"label": "poe2db (zh-TW)", "url": url_zh_tw, "fetched_at": fetched_at})
    return out


def _invert_templates(rows: list[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for row in rows:
        if row.get("template_zh_tw"):
            out.setdefault(row["template_zh_tw"].lower(), set()).add(row["template"])
    return out


def _stat_rank(row: dict, q: str, en_templates: set[str] | None) -> int | None:
    """0 exact family, 1 parent family, 2 family prefix, 3 substring. Chinese queries are
    ranked through the English template they translate to."""
    if en_templates is not None:
        if row["template"] not in en_templates and q not in (row.get("text_zh_tw") or "").lower():
            return None
        return 1 if row["family"] == row["parent_family"] else 2
    family, parent = row["family"], row["parent_family"]
    if family == q:
        return 0
    if parent == q:
        return 1
    if family.startswith(q):
        return 2
    if q in family or q in row["template"].lower():
        return 3
    return None


def _signed(row: dict) -> float:
    value = row.get("value") or 0
    return -value if row.get("kind") in NEGATIVE_KINDS else value


def _count(items: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        value = item.get(key) or "-"
        out[value] = out.get(value, 0) + 1
    return out


def _dedupe_by_name(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for item in items:
        if item["name"] not in seen:
            seen.add(item["name"])
            out.append(item)
    return out


def _gem_matches(rec: dict, tag: str | None, tier: int | None, weapon: str | None,
                 text: str | None = None) -> bool:
    if tier is not None and rec.get("tier") != tier:
        return False
    if text and text.lower() not in _gem_text(rec):
        return False
    if tag:
        t = tag.lower()
        tags = [x.lower() for x in (rec.get("tags") or []) + (rec.get("tag_slugs") or [])]
        if t not in tags:
            return False
    if weapon:
        w = weapon.lower()
        if not any(w in x.lower() for x in rec.get("requires_weapons") or []):
            return False
    return True


def _gem_text(rec: dict) -> str:
    """Lower-cased name, description and stat lines: what the free-text gem filter searches."""
    parts = [rec.get("name"), rec.get("description"), rec.get("main_stat"), rec.get("summary"),
             *(rec.get("extra_properties") or [])]
    return " ".join(p for p in parts if isinstance(p, str)).lower()
