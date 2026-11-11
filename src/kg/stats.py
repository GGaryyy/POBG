"""
stats.py — Normalise passive stat lines into searchable stat families (en + zh-TW).

    python -m src.kg.stats      # writes data/kg/passive_stats.jsonl + data/kg/stat_families.json

"12% increased Attack Speed"            → kind increased, value 12,  family "attack speed"
"Minions deal 10% increased Damage"     → kind increased, value 10,  family "minions damage"
"+5 to Strength"                        → kind flat,      value 5,   family "strength"
"20% of Armour also applies to Fire"    → kind of,        value 20,  family "armour also applies to fire"
Anything else keeps kind "text" and is still searchable by its template.

Chinese: English and Chinese templates (numbers → #) are paired on nodes whose line counts
match, and the majority pairing becomes the zh template of that English template. Small nodes
have no Chinese text of their own but inherit it through their English template.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from src.scrapers.common import atomic_write_text, read_jsonl, write_jsonl

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
NODES_PATH = BASE_DIR / "data" / "passive_tree" / "passive_nodes.jsonl"
STATS_PATH = BASE_DIR / "data" / "kg" / "passive_stats.jsonl"
FAMILIES_PATH = BASE_DIR / "data" / "kg" / "stat_families.json"
MIN_PARSED_RATIO = 0.80
FAMILY_NAME_CANDIDATES = 3

_NUM = r"[+-]?\(?\d+(?:\.\d+)?(?:\s*[—–-]\s*\d+(?:\.\d+)?\)?)?"
_NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
_SHAPES: list[tuple[str, re.Pattern]] = [
    ("subject", re.compile(rf"^(?P<subject>.+?)\s+(?:deal|have|take|gain|has)\s+(?P<value>{_NUM})%\s+"
                           r"(?P<kind>increased|reduced|more|less)\s+(?P<family>.+)$", re.I)),
    ("pct", re.compile(rf"^(?P<value>{_NUM})%\s+(?P<kind>increased|reduced|more|less|faster|slower)\s+(?P<family>.+)$", re.I)),
    ("subject_to", re.compile(rf"^(?P<subject>.+?)\s+(?:have|gain|has)\s+(?P<value>{_NUM})(?P<pct>%?)\s+to\s+(?P<family>.+)$", re.I)),
    ("to", re.compile(rf"^(?P<value>{_NUM})(?P<pct>%?)\s+to\s+(?P<family>.+)$", re.I)),
    ("chance", re.compile(rf"^(?:(?P<subject>.+?)\s+(?:have|has|gain)\s+)?(?P<value>{_NUM})%\s+"
                          r"(?P<family>chance (?:to|for|on|of) .+)$", re.I)),
    ("of", re.compile(rf"^(?P<value>{_NUM})%\s+of\s+(?P<family>.+)$", re.I)),
    ("gain", re.compile(rf"^(?P<family>gain .+?)\s+equal to\s+(?P<value>{_NUM})%\s+of\s+(?P<rest>.+)$", re.I)),
    ("penetration", re.compile(rf"^(?:.+?\s+)?penetrates?\s+(?P<value>{_NUM})%\s+(?:of\s+)?(?P<family>.+)$", re.I)),
    ("verb", re.compile(rf"^(?P<verb>gain|regenerate|recover|lose|grants?)\s+(?P<value>{_NUM})(?P<pct>%?)\s+(?:of\s+)?(?P<family>.+)$", re.I)),
    ("trailing", re.compile(rf"^(?P<head>.+?)\s+(?P<value>{_NUM})%\s+(?P<kind>increased|reduced|more|less|faster|slower)"
                            r"(?:\s+(?P<tail>.+))?$", re.I)),
    ("requires", re.compile(r"^requires\s+(?P<family>.+)$", re.I)),
]
_QUALIFIER_RE = re.compile(r"\s+(?:with|while|against|per|for|if|when|during|from)\s+.*$", re.I)

# ---------------------------------------------------------------------------
# NORMALISATION
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatAtom:
    text: str
    template: str
    kind: str
    value: float | None
    family: str
    parent_family: str

    def as_dict(self) -> dict:
        return asdict(self)


def template_of(text: str) -> str:
    """Numbers (including '(25—35)' ranges) replaced by '#', whitespace collapsed."""
    text = re.sub(r"\(\s*[+-]?\d+(?:\.\d+)?\s*[—–-]\s*[+-]?\d+(?:\.\d+)?\s*\)", "#", text)
    return " ".join(_NUMBER_RE.sub("#", text).split())


def normalise_stat(text: str) -> StatAtom:
    clean = " ".join(text.split())
    template = template_of(clean)
    for shape, pattern in _SHAPES:
        match = pattern.match(clean)
        if match is None:
            continue
        family = _family(shape, match)
        value = _value(match.group("value")) if "value" in match.groupdict() else None
        return StatAtom(text=clean, template=template, kind=_kind(shape, match), value=value,
                        family=family, parent_family=_parent(family))
    family = _strip_numbers(template)
    return StatAtom(text=clean, template=template, kind="text", value=_first_number(clean),
                    family=family, parent_family=_parent(family))


def _family(shape: str, match: re.Match) -> str:
    if shape in ("subject", "subject_to"):
        return _lower(f"{match.group('subject')} {match.group('family')}")
    if shape == "chance" and match.group("subject"):
        return _lower(f"{match.group('subject')} {match.group('family')}")
    if shape == "requires":
        return _lower(f"requires {match.group('family')}")
    if shape == "gain":
        return _lower(f"{match.group('family')} from {match.group('rest')}")
    if shape == "penetration":
        return _lower(f"{match.group('family')} penetration")
    if shape == "verb":
        return _lower(f"{match.group('verb')} {match.group('family')}")
    if shape == "trailing":
        return _lower(f"{match.group('head')} {match.group('tail') or ''}")
    return _lower(match.group("family"))


def _kind(shape: str, match: re.Match) -> str:
    if shape in ("subject", "pct", "trailing"):
        return match.group("kind").lower()
    if shape == "verb":
        return match.group("verb").lower().rstrip("s")
    if shape in ("to", "subject_to"):
        return "flat_percent" if match.group("pct") else "flat"
    return shape


def _value(token: str) -> float | None:
    numbers = _NUMBER_RE.findall(token)
    return float(numbers[0]) if numbers else None


def _first_number(text: str) -> float | None:
    found = _NUMBER_RE.search(text)
    return float(found.group(0)) if found else None


def _strip_numbers(template: str) -> str:
    return _lower(re.sub(r"[+-]?#%?", "", template))


def _parent(family: str) -> str:
    return _QUALIFIER_RE.sub("", family).strip() or family


def _lower(text: str) -> str:
    """Lower-case family text with any remaining numbers replaced by '#' (so 'per 5 Dexterity'
    and 'per 10 Dexterity' share one family)."""
    return " ".join(template_of(text).lower().split())


# ---------------------------------------------------------------------------
# zh-TW TEMPLATES
# ---------------------------------------------------------------------------


def learn_zh_templates(nodes: list[dict]) -> dict[str, str]:
    """English template → most frequent Chinese template, from line-aligned named nodes."""
    votes: dict[str, Counter] = defaultdict(Counter)
    for node in nodes:
        en, zh = node.get("stats") or [], node.get("stats_zh_tw") or []
        if not en or len(en) != len(zh):
            continue
        for en_line, zh_line in zip(en, zh, strict=True):
            if _number_signature(en_line) == _number_signature(zh_line):
                votes[template_of(en_line)][template_of(zh_line)] += 1
    return {en_t: counts.most_common(1)[0][0] for en_t, counts in votes.items()}


def _number_signature(text: str) -> tuple[str, ...]:
    return tuple(sorted(n.lstrip("+") for n in _NUMBER_RE.findall(text)))


# ---------------------------------------------------------------------------
# INDEX
# ---------------------------------------------------------------------------


def build_stat_index(nodes: list[dict]) -> tuple[list[dict], dict]:
    """One row per (node, stat line) plus a family summary."""
    zh_templates = learn_zh_templates(nodes)
    rows: list[dict] = []
    for node in nodes:
        zh_lines = node.get("stats_zh_tw") or []
        aligned = len(zh_lines) == len(node.get("stats") or [])
        for i, line in enumerate(node.get("stats") or []):
            atom = normalise_stat(line)
            rows.append({
                "node_id": node["id"],
                "line": i,
                **atom.as_dict(),
                "text_zh_tw": zh_lines[i] if aligned else None,
                "template_zh_tw": zh_templates.get(atom.template),
            })
    return rows, summarise_families(rows)


def summarise_families(rows: list[dict]) -> dict:
    families: dict[str, dict] = {}
    zh: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        fam = families.setdefault(row["family"], {"count": 0, "parent": row["parent_family"],
                                                  "kinds": Counter(), "examples": []})
        fam["count"] += 1
        fam["kinds"][row["kind"]] += 1
        if len(fam["examples"]) < 3 and row["text"] not in fam["examples"]:
            fam["examples"].append(row["text"])
        if row.get("template_zh_tw"):
            zh[row["family"]][row["template_zh_tw"]] += 1
    for name, fam in families.items():
        fam["kinds"] = dict(fam["kinds"])
        fam["name_zh_tw"] = _family_zh_name(zh.get(name))
    return dict(sorted(families.items(), key=lambda kv: -kv[1]["count"]))


def _family_zh_name(templates: Counter | None) -> str | None:
    """A Chinese label for a stat family: the shortest of its three most common Chinese templates."""
    if not templates:
        return None
    top = sorted(templates.items(), key=lambda kv: (-kv[1], kv[0]))[:FAMILY_NAME_CANDIDATES]
    return min((t for t, _ in top), key=lambda t: (len(t), t))


def parse_summary(rows: list[dict]) -> dict:
    total = len(rows) or 1
    kinds = Counter(r["kind"] for r in rows)
    return {
        "lines": len(rows),
        "parsed_ratio": round(1 - kinds.get("text", 0) / total, 3),
        "zh_template_ratio": round(sum(1 for r in rows if r["template_zh_tw"]) / total, 3),
        "kinds": dict(kinds.most_common()),
    }


def write_stat_index(rows: list[dict], families: dict, out: Path = STATS_PATH,
                     families_path: Path = FAMILIES_PATH) -> None:
    write_jsonl(out, rows)
    atomic_write_text(families_path, json.dumps(families, ensure_ascii=False, indent=1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the passive stat index.")
    parser.add_argument("--nodes", type=Path, default=NODES_PATH)
    parser.add_argument("--out", type=Path, default=STATS_PATH)
    parser.add_argument("--families", type=Path, default=FAMILIES_PATH)
    args = parser.parse_args(argv)
    rows, families = build_stat_index(read_jsonl(args.nodes))
    summary = parse_summary(rows)
    if summary["parsed_ratio"] < MIN_PARSED_RATIO:
        print(f"[ERROR] only {summary['parsed_ratio']:.0%} of stat lines parsed; regex drift? not writing",
              file=sys.stderr)
        return 1
    write_stat_index(rows, families, args.out, args.families)
    print("=== stat index summary ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print(f"  families: {len(families)}")
    print(f"wrote: {args.out}\nwrote: {args.families}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
