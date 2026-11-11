"""
passive_tree_data.py — Read the data file behind poe2db's passive tree viewer.

poe2db publishes one JSON per language (data_us.json, data_tw.json) with the same node ids as
PathOfBuilding-PoE2. We use it for text only: Traditional Chinese names and stat lines of every
node, and the Chinese names of classes and ascendancies. Pure parsing, no IO.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# "[CriticalDamageBonus|暴擊傷害加成]" -> "暴擊傷害加成", "[Spirit]" -> "Spirit"
_MARKUP_RE = re.compile(r"\[(?:[^\[\]|]*\|)?([^\[\]|]*)\]")

# ---------------------------------------------------------------------------
# TEXT
# ---------------------------------------------------------------------------


def strip_markup(text: str) -> str:
    return _MARKUP_RE.sub(lambda m: m.group(1), text)


def clean_lines(stats: list[str]) -> list[str]:
    """One entry per stat as the file lists them: markup removed, whitespace collapsed."""
    return [" ".join(strip_markup(s).split()) for s in stats if isinstance(s, str) and s.strip()]


def node_texts(tree: dict) -> dict[str, dict]:
    """{node id: {"name", "stats"}} for every real node of one language file."""
    out: dict[str, dict] = {}
    for raw in tree.get("nodes", {}).values():
        if not isinstance(raw, dict) or "skill" not in raw:
            continue
        out[str(raw["skill"])] = {"name": " ".join(strip_markup(str(raw.get("name") or "")).split()),
                                  "stats": clean_lines(raw.get("stats") or [])}
    return out


def align_wrapped(en_lines: list[str], zh_lines: list[str]) -> list[str] | None:
    """Chinese lines regrouped the way collect_passives.join_wrapped regroups the English ones.

    English continuation lines start lower-case and are joined to the previous line; the same
    positions are joined in Chinese. None when the two languages do not list the same number of lines.
    """
    if len(en_lines) != len(zh_lines):
        return None
    out: list[str] = []
    for en, zh in zip(en_lines, zh_lines, strict=True):
        if out and en[:1].islower():
            out[-1] = f"{out[-1]}{zh}"
        else:
            out.append(zh)
    return out


# ---------------------------------------------------------------------------
# CLASSES
# ---------------------------------------------------------------------------


def class_names(us: dict, tw: dict) -> list[dict]:
    """Classes with their ascendancies in both languages, paired by position and checked by id."""
    out: list[dict] = []
    for en, zh in zip(us.get("classes") or [], tw.get("classes") or [], strict=False):
        ascendancies = []
        for a_en, a_zh in zip(en.get("ascendancies") or [], zh.get("ascendancies") or [], strict=False):
            if a_en.get("id") != a_zh.get("id") or not a_en.get("name"):
                continue
            ascendancies.append({"id": a_en.get("id"), "name": a_en["name"], "name_zh_tw": a_zh.get("name") or None})
        if en.get("name"):
            out.append({"name": en["name"], "name_zh_tw": zh.get("name") or None, "ascendancies": ascendancies})
    return out
