"""
build_graph.py — Assemble the knowledge graph (NetworkX MultiDiGraph).

    python -m src.kg.build_graph

Node ids are "<type>:<key>":
    gem:<slug>  passive:<id>  keyword:<slug>  class:<slug>  ascendancy:<name>  weapon:<name>  family:<stat family>
Edges carry a `type` attribute:
    ADJACENT        passive → passive        (tree connection; kind tree / ascendancy / bridge)
    STARTS_AT       class → passive          (class start node)
    IN_ASCENDANCY   passive → ascendancy
    GEMCUTTING      class → gem              (tier, group label from the gemcutting table)
    HAS_TAG         gem → keyword            (listing tag slugs are keyword pages)
    REQUIRES_WEAPON gem → weapon
    SUPPORTS        support gem → skill gem  (from the skill's Supported By pane)
    MENTIONS        gem / passive / keyword → keyword
    GIVES_STAT      passive → family         (value, kind, text)
Every node that has a poe2db page keeps its url_en / url_zh_tw.
ADJACENT is stored in both directions so successor traversal sees the whole tree.
The graph is saved as JSON node-link data (no pickle: the file is loaded automatically by the
MCP server and must never be able to execute code).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import networkx as nx

from src.catalog.spec import GEM_KINDS, Spec, load_spec
from src.scrapers.common import atomic_write_text, read_jsonl, slug_from_href

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
GRAPH_PATH = BASE_DIR / "indexes" / "graph" / "knowledge_graph.json"
GRAPHML_PATH = BASE_DIR / "indexes" / "graph" / "knowledge_graph.graphml"
MIN_COUNTS = {"gem": 900, "passive": 4000, "keyword": 300, "family": 1000, "class": 6}
KEYWORDS_FILE = Path("kg") / "keywords.jsonl"
STATS_FILE = Path("kg") / "passive_stats.jsonl"
FAMILIES_FILE = Path("kg") / "stat_families.json"

# ---------------------------------------------------------------------------
# BUILD
# ---------------------------------------------------------------------------


def build_knowledge_graph(spec: Spec, data_dir: Path = DATA_DIR, min_counts: dict[str, int] | None = None) -> nx.MultiDiGraph:
    """Build from data/. Every input file is required; min_counts guards against a partial build."""
    g = nx.MultiDiGraph()
    keywords = _load(data_dir / KEYWORDS_FILE)
    _add_keywords(g, keywords)
    passives = _load(data_dir / _rel(spec.source("pob2_tree")["nodes_file"]))
    _add_passives(g, passives)
    _add_passive_edges(g, _load(data_dir / _rel(spec.source("pob2_tree")["edges_file"])))
    _add_stats(g, _load(data_dir / STATS_FILE))
    for kind in GEM_KINDS:
        _, source = spec.source_for_kind(kind)
        _add_gems(g, _load(data_dir / _rel(source["detail_file"])), kind)
        if source.get("gemcutting_file"):
            _add_gemcutting(g, _load(data_dir / _rel(source["gemcutting_file"])))
    _add_supports(g)
    _check_dangling(g)
    _add_zh_names(g, data_dir, spec, keywords)
    if min_counts:
        _check_counts(g, min_counts)
    return g


def _load(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"knowledge graph input missing: {path}")
    return read_jsonl(path)


def _check_counts(g: nx.MultiDiGraph, min_counts: dict[str, int]) -> None:
    counts = Counter(d["type"] for _, d in g.nodes(data=True))
    low = {t: counts.get(t, 0) for t, n in min_counts.items() if counts.get(t, 0) < n}
    if low:
        raise ValueError(f"knowledge graph too small, refusing to save: {low} (minimums {min_counts})")


def _rel(path: str) -> Path:
    return Path(path).relative_to("data")


def _ensure(g: nx.MultiDiGraph, node_id: str, **attrs) -> str:
    if node_id not in g:
        g.add_node(node_id, **attrs)
    else:
        for key, value in attrs.items():
            if value is not None and g.nodes[node_id].get(key) in (None, ""):
                g.nodes[node_id][key] = value
    return node_id


def _keyword(g: nx.MultiDiGraph, slug: str) -> str:
    return _ensure(g, f"keyword:{slug}", type="keyword", slug=slug)


# -- keywords -----------------------------------------------------------------

def _add_keywords(g: nx.MultiDiGraph, keywords: list[dict]) -> None:
    for kw in keywords:
        node = _ensure(g, f"keyword:{kw['slug']}", type="keyword", slug=kw["slug"], name=kw.get("name_en"),
                       name_zh_tw=kw.get("name_zh_tw"), url_en=kw.get("url_en"), url_zh_tw=kw.get("url_zh_tw"))
        for other in kw.get("see_also", []):
            g.add_edge(node, _keyword(g, other), type="MENTIONS")


# -- passives -----------------------------------------------------------------

def _add_passives(g: nx.MultiDiGraph, passives: list[dict]) -> None:
    for p in passives:
        node = _ensure(g, f"passive:{p['id']}", type="passive", node_type=p.get("type"), name=p.get("name"),
                       name_zh_tw=p.get("name_zh_tw"), slug=p.get("slug"), url_en=p.get("url_en"),
                       url_zh_tw=p.get("url_zh_tw"), ascendancy=p.get("ascendancy"), timeless=p.get("timeless"))
        for cls in p.get("class_start") or []:
            g.add_edge(_ensure(g, f"class:{cls}", type="class", name=cls), node, type="STARTS_AT")
        if p.get("ascendancy"):
            g.add_edge(node, _ensure(g, f"ascendancy:{p['ascendancy']}", type="ascendancy", name=p["ascendancy"]),
                       type="IN_ASCENDANCY")
        for slug in p.get("keyword_slugs") or []:
            g.add_edge(node, _keyword(g, slug), type="MENTIONS")


def _add_passive_edges(g: nx.MultiDiGraph, edges: list[dict]) -> None:
    for e in edges:
        a, b = f"passive:{e['from']}", f"passive:{e['to']}"
        g.add_edge(a, b, type="ADJACENT", kind=e.get("kind", "tree"))
        g.add_edge(b, a, type="ADJACENT", kind=e.get("kind", "tree"))


def _add_stats(g: nx.MultiDiGraph, rows: list[dict]) -> None:
    for row in rows:
        family = _ensure(g, f"family:{row['family']}", type="family", name=row["family"], parent=row["parent_family"])
        g.add_edge(f"passive:{row['node_id']}", family, type="GIVES_STAT", kind=row["kind"],
                   value=row["value"], text=row["text"])


# -- gems ---------------------------------------------------------------------

def _add_gems(g: nx.MultiDiGraph, records: list[dict], kind: str) -> None:
    for rec in records:
        slug = rec.get("slug") or slug_from_href(rec.get("href"))
        node = _ensure(g, f"gem:{slug}", type="gem", slug=slug, name=rec.get("name"), tier=rec.get("tier"),
                       url_en=rec.get("source_url"), url_zh_tw=rec.get("url_zh_tw"))
        kinds = g.nodes[node].setdefault("kinds", [])  # a spirit gem also appears in the skill listing
        if kind not in kinds:
            kinds.append(kind)
        for tag in rec.get("tag_slugs") or []:
            g.add_edge(node, _keyword(g, tag), type="HAS_TAG")
        for weapon in rec.get("requires_weapons") or []:
            g.add_edge(node, _ensure(g, f"weapon:{weapon}", type="weapon", name=weapon), type="REQUIRES_WEAPON")
        for kw in rec.get("keyword_slugs") or []:
            g.add_edge(node, _keyword(g, kw), type="MENTIONS")
        g.nodes[node]["supported_by"] = list(rec.get("supported_by") or [])


def _add_gemcutting(g: nx.MultiDiGraph, rows: list[dict]) -> None:
    for row in rows:
        cls = row.get("class_slug")
        gem = f"gem:{row['gem_slug']}"
        if not cls or gem not in g:
            continue
        g.add_edge(_ensure(g, f"class:{cls}", type="class", name=cls), gem, type="GEMCUTTING",
                   tier=row["tier"], group=row["class_name"])


def _add_supports(g: nx.MultiDiGraph) -> None:
    for node, data in list(g.nodes(data=True)):
        for support in data.pop("supported_by", None) or []:
            support_id = f"gem:{support}"
            if support_id in g:
                g.add_edge(support_id, node, type="SUPPORTS")


# -- Chinese names for nodes that are not poe2db pages -----------------------------

def _add_zh_names(g: nx.MultiDiGraph, data_dir: Path, spec: Spec, keywords: list[dict]) -> None:
    """Classes, ascendancies, stat families and weapons get name_zh_tw where a source has one."""
    names = {f"family:{name}": fam.get("name_zh_tw")
             for name, fam in _load_json(data_dir / FAMILIES_FILE, {}).items()}
    classes = _load_json(data_dir / _rel(spec.source("passive_tree_data")["classes_file"]), None)
    if classes is None:
        print("[WARN] classes.json missing; class and ascendancy nodes keep English names only "
              "(run python -m src.scrapers.collect_passives)", file=sys.stderr)
    for cls in (classes or {}).get("classes", []):
        names[f"class:{cls['name']}"] = cls.get("name_zh_tw")
        for asc in cls.get("ascendancies", []):
            names[f"ascendancy:{asc['name']}"] = asc.get("name_zh_tw")
    by_english = {(k.get("name_en") or "").casefold(): k.get("name_zh_tw") for k in keywords}
    for node, data in g.nodes(data=True):
        if data["type"] == "weapon":
            names[node] = by_english.get((data.get("name") or "").casefold())
    for node, zh in names.items():
        if zh and node in g and not g.nodes[node].get("name_zh_tw"):
            g.nodes[node]["name_zh_tw"] = zh


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _check_dangling(g: nx.MultiDiGraph) -> None:
    untyped = [n for n, d in g.nodes(data=True) if "type" not in d]
    if untyped:
        raise ValueError(f"{len(untyped)} graph nodes have no type (dangling edge endpoints), e.g. {untyped[:5]}")


# ---------------------------------------------------------------------------
# OUTPUT
# ---------------------------------------------------------------------------


def graph_summary(g: nx.MultiDiGraph) -> dict:
    return {
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
        "node_types": dict(Counter(d["type"] for _, d in g.nodes(data=True)).most_common()),
        "edge_types": dict(Counter(d["type"] for _, _, d in g.edges(data=True)).most_common()),
        "with_name_zh_tw": dict(Counter(d["type"] for _, d in g.nodes(data=True) if d.get("name_zh_tw")).most_common()),
    }


def save_graph(g: nx.MultiDiGraph, path: Path = GRAPH_PATH, graphml_path: Path | None = GRAPHML_PATH) -> None:
    """JSON node-link data, written atomically."""
    data = nx.node_link_data(g, edges="edges")
    atomic_write_text(path, json.dumps(data, ensure_ascii=False))
    if graphml_path is not None:
        nx.write_graphml(_graphml_safe(g), graphml_path)


def load_graph(path: Path = GRAPH_PATH) -> nx.MultiDiGraph:
    with Path(path).open(encoding="utf-8") as fh:
        data = json.load(fh)
    return nx.node_link_graph(data, directed=True, multigraph=True, edges="edges")


def _graphml_safe(g: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """GraphML only stores scalars: drop None, JSON-encode lists/dicts."""
    out = nx.MultiDiGraph()
    for node, data in g.nodes(data=True):
        out.add_node(node, **_scalar(data))
    for u, v, data in g.edges(data=True):
        out.add_edge(u, v, **_scalar(data))
    return out


def _scalar(data: dict) -> dict:
    clean = {}
    for key, value in data.items():
        if value is None:
            continue
        clean[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
    return clean


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the knowledge graph.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--out", type=Path, default=GRAPH_PATH)
    parser.add_argument("--no-graphml", action="store_true")
    args = parser.parse_args(argv)
    try:
        g = build_knowledge_graph(load_spec(), args.data_dir, min_counts=MIN_COUNTS)
    except (ValueError, FileNotFoundError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    save_graph(g, args.out, None if args.no_graphml else args.out.with_suffix(".graphml"))
    print("=== knowledge graph summary ===")
    for key, value in graph_summary(g).items():
        print(f"  {key}: {value}")
    print(f"wrote: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
