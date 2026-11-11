"""
entity_index.py — Build and query the entity index.

    python -m src.catalog.entity_index build            # fetch /tw/ listing pages (cached)
    python -m src.catalog.entity_index build --offline  # use output/cache/pages/ only
    python -m src.catalog.entity_index find "躍擊"

One entry per gem (from the three *_Detail.jsonl files) and per named passive node
(Keystone / Notable / Ascendancy), joined by slug to the Traditional Chinese names scraped
from the /tw/ listing pages. The index is the exact-match lookup layer: name (en or zh-TW)
→ slug, kind, source URLs and the local record.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from urllib.parse import unquote
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from src.catalog.spec import GEM_KINDS, Spec, load_spec
from src.scrapers.common import (clean_text, fetch_html, find_section, make_soup, now_iso, read_jsonl,
                                 slug_from_href, write_jsonl)
from src.scrapers.gem_listing import parse_listing

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = BASE_DIR / "data" / "catalog" / "entity_index.jsonl"
TW_CACHE_DIR = BASE_DIR / "output" / "cache" / "pages"
PASSIVE_TYPE_TO_KIND = {"Keystone": "passive_keystone", "Notable": "passive_notable", "Ascendancy": "passive_ascendancy"}
PASSIVE_SOURCES = ("passive_keystones", "passive_notables")
GEM_LISTING_SOURCES = ("skill_gems_listing", "spirit_gems_listing", "support_gems_listing")
COVERAGE_TARGETS = {"gem": 0.95, "passive": 0.90}  # passive = keystones + notables
MATCH_ORDER = ("exact", "prefix", "substring")

_ALIAS_STRIP_RE = re.compile(r"[\s'’\-_:,.()]+")

Fetcher = Callable[[str], str]

# ---------------------------------------------------------------------------
# ENTRY
# ---------------------------------------------------------------------------


@dataclass
class Entity:
    slug: str
    kind: str
    name_en: str
    name_zh_tw: str | None
    url_en: str | None
    url_zh_tw: str | None
    tier: int | None = None
    tag_slugs: list[str] = field(default_factory=list)
    game_id: str | None = None
    record_file: str | None = None
    record_key: dict | None = None
    node_id: str | None = None
    aliases: list[str] = field(default_factory=list)
    built_at: str | None = None

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, raw: dict) -> "Entity":
        known = {k: raw.get(k) for k in cls.__dataclass_fields__}
        known["tag_slugs"] = known.get("tag_slugs") or []
        known["aliases"] = known.get("aliases") or []
        return cls(**known)


def make_aliases(*names: str | None) -> list[str]:
    """Deterministic lookup keys: casefolded, NFKC, punctuation/space stripped."""
    out: list[str] = []
    for name in names:
        if not name:
            continue
        folded = unicodedata.normalize("NFKC", name).casefold().strip()
        for variant in (folded, _ALIAS_STRIP_RE.sub("", folded)):
            if variant and variant not in out:
                out.append(variant)
    return out


# ---------------------------------------------------------------------------
# BUILD
# ---------------------------------------------------------------------------


def build_entity_index(
    spec: Spec,
    *,
    data_dir: Path = BASE_DIR / "data",
    zh_names: dict[str, str] | None = None,
    passive_slugs: dict[str, str] | None = None,
    fetcher: Fetcher | None = None,
    cache_dir: Path = TW_CACHE_DIR,
    offline: bool = False,
) -> list[Entity]:
    """Assemble entities from local JSONL plus names scraped from the listing pages.

    zh_names: slug → zh-TW name (gems and passives). passive_slugs: English passive name → slug.
    Both are fetched (with on-disk cache) when not supplied.
    """
    if zh_names is None:
        zh_names = fetch_zh_names(spec, fetcher=fetcher, cache_dir=cache_dir, offline=offline)
    nodes = read_jsonl(data_dir / Path(spec.source("pob2_tree")["nodes_file"]).relative_to("data"))
    if passive_slugs is None and any("slug" not in n for n in nodes):  # legacy node schema only
        passive_slugs = fetch_passive_en_slugs(spec, fetcher=fetcher, cache_dir=cache_dir, offline=offline)
    built_at = now_iso()
    entities = _gem_entities(spec, data_dir, zh_names, built_at)
    entities += _passive_entities(spec, nodes, zh_names, passive_slugs or {}, built_at)
    entities += _keyword_entities(spec, data_dir, built_at)
    entities += _item_entities(spec, data_dir, built_at)
    _check_unique(entities)
    return entities


def _gem_entities(spec: Spec, data_dir: Path, zh: dict[str, str], built_at: str) -> list[Entity]:
    out: list[Entity] = []
    for kind in GEM_KINDS:
        _, source = spec.source_for_kind(kind)
        rel = Path(source["detail_file"])
        path = data_dir / rel.relative_to("data")
        for rec in read_jsonl(path):
            slug = rec.get("slug") or slug_from_href(rec.get("href"))
            if not slug:
                continue
            name_zh = zh.get(slug)
            out.append(Entity(
                slug=slug, kind=kind, name_en=rec["name"], name_zh_tw=name_zh,
                url_en=spec.resolve_url(slug, "en"), url_zh_tw=spec.resolve_url(slug, "zh-tw"),
                tier=rec.get("tier"), tag_slugs=list(rec.get("tag_slugs") or []), game_id=rec.get("game_id"),
                record_file=rel.as_posix(), record_key={"slug": slug},
                aliases=make_aliases(rec["name"], name_zh), built_at=built_at,
            ))
    return out


def _passive_entities(
    spec: Spec, nodes: list[dict], zh: dict[str, str], passive_slugs: dict[str, str], built_at: str
) -> list[Entity]:
    """Keystones, notables and named ascendancy nodes; one entity per poe2db slug."""
    rel = Path(spec.source("pob2_tree")["nodes_file"])
    known_slugs = set(passive_slugs.values())
    out: list[Entity] = []
    seen: set[str] = set()
    for node in nodes:
        kind = PASSIVE_TYPE_TO_KIND.get(node.get("type"))
        name = node.get("name")
        if kind is None or not name or not _indexable(node):
            continue
        node_id = str(node["id"])
        slug = _node_slug(node, node_id, name, passive_slugs, known_slugs)
        key = slug or f"node_{node_id}"
        if key in seen:
            continue
        seen.add(key)
        name_zh = node.get("name_zh_tw") or (zh.get(slug) if slug else None)
        out.append(Entity(
            slug=key, kind=kind, name_en=name, name_zh_tw=name_zh,
            url_en=spec.resolve_url(slug, "en") if slug else None,
            url_zh_tw=spec.resolve_url(slug, "zh-tw") if slug else None,
            record_file=rel.as_posix(), record_key={"id": node_id}, node_id=node_id,
            aliases=make_aliases(name, name_zh), built_at=built_at,
        ))
    return out


def _indexable(node: dict) -> bool:
    """Ascendancy small nodes have generic names ('Life', 'Mana'); index only notables and starts."""
    if node.get("type") != "Ascendancy":
        return True
    return bool(node.get("is_notable") or node.get("is_ascendancy_start") or node.get("slug"))


def _node_slug(node: dict, node_id: str, name: str, passive_slugs: dict[str, str], known: set[str]) -> str | None:
    if "slug" in node:
        return node["slug"]
    return node_id if not node_id.isdigit() else _passive_slug(name, passive_slugs, known)


def _item_entities(spec: Spec, data_dir: Path, built_at: str) -> list[Entity]:
    """Gear bases and unique items, when the item data exists."""
    source = spec.raw["sources"].get("item_pages")
    out: list[Entity] = []
    for kind, key in (("item_base", "bases_file"), ("item_unique", "uniques_file")):
        rel = Path(source[key]) if source else None
        path = data_dir / rel.relative_to("data") if rel else None
        if path is None or not path.exists():
            continue
        for rec in read_jsonl(path):
            out.append(Entity(
                slug=rec["slug"], kind=kind, name_en=rec["name"], name_zh_tw=rec.get("name_zh_tw"),
                url_en=rec.get("url_en"), url_zh_tw=rec.get("url_zh_tw"),
                record_file=rel.as_posix(), record_key={"slug": rec["slug"]},
                aliases=make_aliases(rec["name"], rec.get("name_zh_tw")), built_at=built_at,
            ))
    return out


def _keyword_entities(spec: Spec, data_dir: Path, built_at: str) -> list[Entity]:
    path = data_dir / "kg" / "keywords.jsonl"
    if not path.exists():
        return []
    out = []
    subterms = spec.subterms()
    for kw in read_jsonl(path):
        name = kw.get("name_en") or kw["slug"].replace("_", " ")
        kinds = [n for term in subterms.get(kw["slug"], []) for n in (term["en"], term["en"] + "s", term.get("zh_tw"))]
        out.append(Entity(
            slug=kw["slug"], kind="keyword", name_en=name, name_zh_tw=kw.get("name_zh_tw"),
            url_en=kw.get("url_en"), url_zh_tw=kw.get("url_zh_tw"),
            record_file="data/kg/keywords.jsonl", record_key={"slug": kw["slug"]},
            aliases=make_aliases(name, kw.get("name_zh_tw"), *kinds), built_at=built_at,
        ))
    return out


def _passive_slug(name: str, passive_slugs: dict[str, str], known_slugs: set[str]) -> str | None:
    """Numeric-id nodes have no slug of their own; resolve it from the /us/ listing by name."""
    if name in passive_slugs:
        return passive_slugs[name]
    candidate = name.replace("'", "").replace(" ", "_")
    return candidate if candidate in known_slugs else None


def _check_unique(entities: list[Entity]) -> None:
    seen: dict[str, str] = {}
    for e in entities:
        key = f"{e.kind}:{e.slug}"
        if key in seen:
            raise ValueError(f"duplicate entity {key} ({seen[key]} / {e.name_en})")
        seen[key] = e.name_en


# ---------------------------------------------------------------------------
# zh-TW NAMES
# ---------------------------------------------------------------------------


def fetch_zh_names(
    spec: Spec, *, fetcher: Fetcher | None = None, cache_dir: Path = TW_CACHE_DIR, offline: bool = False,
    sources: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """slug → zh-TW name from the five /tw/ listing pages (three gem pages, Keystone, Notable),
    or only from the listing sources named in `sources`."""
    fetch = fetcher or (lambda url: fetch_html(url, delay=spec.raw["robots"]["polite_delay_seconds"]))
    names: dict[str, str] = {}
    wanted = lambda name: sources is None or name in sources  # noqa: E731
    for source_name in filter(wanted, GEM_LISTING_SOURCES):
        html = _page(spec, spec.source(source_name)["slug"], "zh-tw", fetch, cache_dir, offline)
        if html is None:
            continue
        for row in parse_listing(html, spec, source_name, "zh-tw"):
            names.setdefault(row.slug, row.name)
    for source_name in filter(wanted, PASSIVE_SOURCES):
        page_slug = spec.source(source_name)["slug"]
        html = _page(spec, page_slug, "zh-tw", fetch, cache_dir, offline)
        if html is not None:
            for slug, name in _passive_names(html, spec, source_name, "zh-tw").items():
                names.setdefault(slug, name)
    return names


def fetch_passive_en_slugs(
    spec: Spec, *, fetcher: Fetcher | None = None, cache_dir: Path = TW_CACHE_DIR, offline: bool = False
) -> dict[str, str]:
    """English passive name → slug from the /us/ Keystone and Notable pages."""
    fetch = fetcher or (lambda url: fetch_html(url, delay=spec.raw["robots"]["polite_delay_seconds"]))
    out: dict[str, str] = {}
    for source_name in PASSIVE_SOURCES:
        html = _page(spec, spec.source(source_name)["slug"], "en", fetch, cache_dir, offline)
        if html is not None:
            for slug, name in _passive_names(html, spec, source_name, "en").items():
                out.setdefault(name, slug)
    return out


def _passive_names(html: str, spec: Spec, source_name: str, lang: str) -> dict[str, str]:
    soup = make_soup(html)
    out: dict[str, str] = {}
    for sec_name, meta in spec.source(source_name)["sections"].items():
        node = find_section(soup, meta.get("ids", {}), lang, meta.get("pane_index"))
        if node is None:
            continue
        selector = spec.selector("passive_anchor") if sec_name == "list" else spec.selector("passive_alt_anchor")
        for a in node.select(selector):
            slug = slug_from_href(a.get("href"))
            name = clean_text(a.get_text(" ", strip=True))
            if slug and name:
                out.setdefault(slug, name)
    return out


def _page(spec: Spec, slug: str, lang: str, fetch: Fetcher, cache_dir: Path, offline: bool) -> str | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{lang}_{slug}.html"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    if offline:
        print(f"[WARN] offline and no cache for {lang}/{slug}", file=sys.stderr)
        return None
    try:
        html = fetch(spec.resolve_url(slug, lang))
    except requests.RequestException as exc:
        print(f"[WARN] could not fetch {lang}/{slug}: {exc}", file=sys.stderr)
        return None
    cached.write_text(html, encoding="utf-8")
    return html


# ---------------------------------------------------------------------------
# LOOKUP
# ---------------------------------------------------------------------------


class EntityIndex:
    """In-memory lookup over entity_index.jsonl (stdlib only)."""

    def __init__(self, entities: list[Entity], base_dir: Path = BASE_DIR) -> None:
        self._entities = entities
        self._base_dir = base_dir
        self._by_slug: dict[str, list[Entity]] = {}
        self._by_alias: dict[str, list[Entity]] = {}
        self._records: dict[str, dict[str, dict]] = {}  # record_file -> key value -> record
        for e in entities:
            self._by_slug.setdefault(e.slug, []).append(e)
            decoded = unquote(e.slug)
            if decoded != e.slug:
                self._by_slug.setdefault(decoded, []).append(e)
            for alias in e.aliases:
                self._by_alias.setdefault(alias, []).append(e)

    @classmethod
    def load(cls, path: Path = INDEX_PATH, base_dir: Path = BASE_DIR) -> "EntityIndex":
        return cls([Entity.from_dict(r) for r in read_jsonl(path)], base_dir=base_dir)

    def __len__(self) -> int:
        return len(self._entities)

    def get(self, slug: str, kind: str | None = None) -> Entity | None:
        for e in self._by_slug.get(slug, []) or self._by_slug.get(unquote(slug), []):
            if kind is None or e.kind == kind:
                return e
        return None

    def exact(self, query: str, kind: str | None = None) -> list[Entity]:
        """Entities with an alias equal to the query. Dictionary lookups only, no scan."""
        found: list[Entity] = []
        seen: set[int] = set()
        for key in make_aliases(query):
            for e in self._by_alias.get(key, []):
                if id(e) not in seen and (kind is None or e.kind == kind):
                    seen.add(id(e))
                    found.append(e)
        return found

    def find(self, query: str, kind: str | None = None, limit: int = 5) -> list[dict]:
        """Exact alias match first, then prefix, then substring. Each hit carries match_type."""
        keys = make_aliases(query)
        if not keys:
            return []
        hits: list[dict] = []
        seen: set[int] = set()

        def add(e: Entity, match_type: str) -> None:
            if id(e) in seen or (kind is not None and e.kind != kind):
                return
            seen.add(id(e))
            hits.append({**e.as_dict(), "match_type": match_type})

        for key in keys:
            for e in self._by_alias.get(key, []):
                add(e, "exact")
        # One plain comprehension per key: this scan runs for every unknown name of a build.
        scans = (("prefix", lambda key: {a for a in self._by_alias if a.startswith(key)}),
                 ("substring", lambda key: {a for a in self._by_alias if key in a}))
        for match_type, scan in scans:
            if len(hits) >= limit:
                break
            matched = set().union(*(scan(key) for key in keys))
            for alias in sorted(matched, key=lambda a: (len(a), a)):
                for e in self._by_alias[alias]:
                    add(e, match_type)
        return hits[:limit]

    def record(self, entity: Entity | dict) -> dict | None:
        """Load the full local record the entity points at."""
        data = entity.as_dict() if isinstance(entity, Entity) else entity
        if not data.get("record_file") or not data.get("record_key"):
            return None
        key, value = next(iter(data["record_key"].items()))
        return self._records_for(data["record_file"], key).get(str(value))

    def _records_for(self, record_file: str, key: str) -> dict[str, dict]:
        """Parse a record file once; only files under <base_dir>/data are allowed."""
        cache_key = f"{record_file}|{key}"
        if cache_key not in self._records:
            path = (self._base_dir / record_file).resolve()
            if not path.is_relative_to((self._base_dir / "data").resolve()):
                raise ValueError(f"record_file must live under data/: {record_file}")
            table: dict[str, dict] = {}
            for rec in read_jsonl(path):
                rec_value = rec.get(key)
                if rec_value is None and key == "slug":
                    rec_value = slug_from_href(rec.get("href"))
                if rec_value is not None:
                    table.setdefault(str(rec_value), rec)
            self._records[cache_key] = table
        return self._records[cache_key]


# ---------------------------------------------------------------------------
# REPORTING / CLI
# ---------------------------------------------------------------------------


def coverage_summary(entities: list[Entity]) -> dict:
    groups = {"gem": [e for e in entities if e.kind in GEM_KINDS],
              "passive": [e for e in entities if e.kind in ("passive_keystone", "passive_notable")]}
    summary: dict = {"total": len(entities), "by_kind": {}}
    for e in entities:
        summary["by_kind"][e.kind] = summary["by_kind"].get(e.kind, 0) + 1
    for group, ents in groups.items():
        with_zh = sum(1 for e in ents if e.name_zh_tw)
        summary[f"{group}_zh_tw_coverage"] = round(with_zh / len(ents), 3) if ents else None
    return summary


def _print_summary(summary: dict) -> None:
    print("=== entity index summary ===")
    print(f"total: {summary['total']}")
    for kind, n in summary["by_kind"].items():
        print(f"  {kind}: {n}")
    for group, target in COVERAGE_TARGETS.items():
        cov = summary.get(f"{group}_zh_tw_coverage")
        flag = "" if cov is None or cov >= target else f"  [WARN below target {target:.0%}]"
        print(f"  {group} zh-TW coverage: {cov if cov is None else f'{cov:.1%}'}{flag}")
        if flag:
            print(f"[WARN] {group} zh-TW coverage {cov:.1%} below {target:.0%}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or query the entity index.")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--offline", action="store_true")
    b.add_argument("--out", type=Path, default=INDEX_PATH)
    f = sub.add_parser("find")
    f.add_argument("query")
    f.add_argument("--kind")
    f.add_argument("--index", type=Path, default=INDEX_PATH)
    args = parser.parse_args(argv)
    spec = load_spec()

    if args.command == "build":
        entities = build_entity_index(spec, offline=args.offline)
        write_jsonl(args.out, (e.as_dict() for e in entities))
        _print_summary(coverage_summary(entities))
        print(f"wrote: {args.out}")
        return 0

    index = EntityIndex.load(args.index)
    for hit in index.find(args.query, kind=args.kind):
        print(json.dumps(hit, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
