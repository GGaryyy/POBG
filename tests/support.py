"""Shared helpers for offline scraper/catalog tests."""

from __future__ import annotations

import copy
from pathlib import Path

from src.catalog.spec import Spec, load_spec

FIXTURES = Path(__file__).parent / "fixtures"
HTML_DIR = FIXTURES / "html"
JSONL_DIR = FIXTURES / "jsonl"


def html(name: str) -> str:
    return (HTML_DIR / name).read_text(encoding="utf-8")


def lowered_spec(value: int = 0) -> Spec:
    """Real spec with every section expect_min set to `value`."""
    raw = copy.deepcopy(load_spec().raw)
    for src in raw["sources"].values():
        for sec in src.get("sections", {}).values():
            if isinstance(sec, dict) and "expect_min" in sec:
                sec["expect_min"] = value
    raw["sources"]["passive_tree_data"]["expect_min"]["nodes"] = value
    return Spec(raw)


def fixture_text(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


def mini_tree() -> dict:
    """Synthetic PoB2 tree (tests/fixtures/pob2/tree_mini.json)."""
    import json
    return json.loads(fixture_text("pob2", "tree_mini.json"))


def mini_tree_data() -> dict:
    """Synthetic poe2db tree viewer data (tests/fixtures/poe2db_tree), shaped like load_tree_data's result."""
    import json
    return {"version": "4.5",
            "en": json.loads(fixture_text("poe2db_tree", "data_us_mini.json")),
            "zh-tw": json.loads(fixture_text("poe2db_tree", "data_tw_mini.json")),
            "urls": {"en": "https://poe2db.tw/data/passive-skill-tree/4.5/data_us.json",
                     "zh-tw": "https://poe2db.tw/data/passive-skill-tree/4.5/data_tw.json"}}


def mini_spec(tree_data_nodes: int = 10, zh_name_ratio: float = 0.7, **expect) -> Spec:
    """Real spec whose pob2_tree / passive_tree_data expect_min are lowered so the mini tree passes validation."""
    raw = copy.deepcopy(load_spec().raw)
    raw["sources"]["passive_tree_data"]["expect_min"] = {"nodes": tree_data_nodes, "zh_name_ratio": zh_name_ratio}
    raw["sources"]["pob2_tree"]["expect_min"] = {
        "nodes": 10, "keystones": 1, "notables": 3, "class_starts": 1, "ascendancy_starts": 1,
        "poe2db_name_match_ratio": 0.7, **expect}
    return Spec(raw)
