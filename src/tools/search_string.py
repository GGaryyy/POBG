"""
search_string.py — Strings for the in-game search box (stash and vendor windows) that highlight
the gear a build wants, or the waystones a build can run.

The game's search is a regular expression, matched line by line and in any case (seen in the
strings poe2.re and Cabbage Forge produce, 2026-11-18: `mage$`, `\\d+ fire damage$`,
`^rarity: rare$`). For each wanted modifier this finds the shortest piece of one of its lines,
numbers written as `\\d+`, optionally tied to the line's start (`^`) or end (`$`), that matches that
line on every tier and no other line the data has for that item class: every modifier of every
group, modifier names, base and unique names, implicits and property lines with their values
("Physical Damage: 13-18"). For waystones: every other waystone modifier, the tier names and
their property lines. Every piece is run with Python's `re` against all those lines before it is
returned.

Lines the data does not have (rarity, item level, requirements, a rare's random name, a
waystone's pack size and rarity lines) are not checked: `not_checked` says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.scrapers.collect_items import modifier_template as template
from src.scrapers.common import clean_text
from src.tools.atlas import LINE_JOIN, AtlasLookup
from src.tools.items import ItemLookup, _families
from src.tools.lookup import BadArgument, _cap, _require, is_cjk

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

KINDS = ("gear", "maps")
LANGS = ("en", "zh-tw")
MAX_ENTRIES = 12
MAX_CLASHES_SHOWN = 12
MIN_AVOID_CHARS = 3          # an avoid entry shorter than this names too little
MAX_AVOID_MATCHES = 6        # an avoid entry naming more modifiers than this is too broad
NUMBER = "#"                 # a number in a line's search form
RANGE_RE = re.compile(r"\((-?\d+(?:\.\d+)?)\s*[—–-]\s*(-?\d+(?:\.\d+)?)\)")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
SPECIAL = set(".^$*+?{}[]\\|()")             # escaped in a piece
NEVER_IN_PIECE = set('"!\n#')                 # would end or turn around the quoted string; # is a number mark
LETTER_RE = re.compile(r"[^\W\d_]")
MOD_ID = re.compile(r"^waystone_\d+$")
INPUT_PARTS = re.compile(rf"\s*{re.escape(LINE_JOIN.strip())}\s*|\n")     # the lines of a waystone_mods `text`
WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
QUOTE = '"'
ANCHOR_ORDER = {"$": 0, "^": 1, "": 2, "^$": 3}     # at equal length: tied to the end first
PROPERTY_SAMPLE = "65"        # the value written into a waystone property line for the check
NOT_CHECKED = {
    "en": ["The string is a regular expression; give it unchanged. It is checked against every modifier, name, "
           "implicit and property line the data has for this item class (or for waystones), not against lines the "
           "data does not have: rarity, item level, requirements, a rare item's random name, a waystone's pack "
           "size and rarity lines, other item classes in the same stash. Try it in the game before relying on it.",
           "The string must match the game client's language: use the zh-tw string in a Traditional Chinese client."],
    "zh-tw": ["字串是正則表達式，請原樣使用。它已對照這個裝備類別（或換界石）在資料裡的所有詞綴、名稱、固定詞綴與屬性行檢查；"
              "資料沒有的行沒有檢查：稀有度、物品等級、需求、稀有物品的隨機名稱、換界石的怪物數量與稀有度等行、同一倉庫裡其他類別的物品。"
              "請先在遊戲裡試過再依賴它。",
              "字串必須與遊戲客戶端的語言一致：繁體中文客戶端用 zh-tw 那串。"],
}
HOW_TO_USE = {
    "gear": {"en": "Paste a string into the search box of the stash or a vendor: items with any of the wanted "
                   "modifiers light up. Each string works on its own.",
             "zh-tw": "把字串貼到倉庫或商人視窗的搜尋框：有任一個想要詞綴的物品會亮起。每一串都可以單獨使用。"},
    "maps": {"en": "Paste the string into the stash search box: waystones with any of these modifiers stay dark, "
                   "the ones left lit do not have them (except what `left_out` or `missing` lists).",
             "zh-tw": "把字串貼到倉庫的搜尋框：有這些詞綴的換界石不會亮，亮著的就是沒有這些詞綴的"
                      "（`left_out` 或 `missing` 列出的除外）。"},
}


@dataclass
class Target:
    """One wanted (or avoided) modifier: per language, its lines on each tier."""
    input: str
    key: tuple
    matched: str
    tiers: dict[str, list[list[str]]]
    extra: dict = field(default_factory=dict)       # the id of a waystone modifier


@dataclass
class Found:
    piece: str | None
    clashes: list[str] = field(default_factory=list)
    shared: list[str] = field(default_factory=list)


class SearchStrings:
    """Builds search strings from the item and atlas lookups."""

    def __init__(self, items: ItemLookup, atlas: AtlasLookup, spec) -> None:
        self.items = items
        self.atlas = atlas
        self.spec = spec

    def search_string(self, kind: str, modifiers: list[str], item: str | None = None) -> dict:
        if kind not in KINDS:
            raise BadArgument(f"kind must be one of {KINDS}")
        if not isinstance(modifiers, list) or not modifiers:
            raise BadArgument("modifiers must be a non-empty list of modifier texts")
        if len(modifiers) > MAX_ENTRIES:
            raise BadArgument(f"modifiers takes at most {MAX_ENTRIES} entries")
        for entry in modifiers:
            if not isinstance(entry, str):
                raise BadArgument("each modifier must be a text")
            _require(entry, "modifier")
        if item is not None and not isinstance(item, str):
            raise BadArgument("item must be a text")
        lang = "zh-tw" if any(is_cjk(m) for m in modifiers) else "en"
        if kind == "gear":
            _require(item, "item")
            result = self._gear(item, modifiers)
        else:
            _cap(item, "item")
            result = self._maps(modifiers)
        return {**result, "how_to_use": HOW_TO_USE[kind][lang], "not_checked": NOT_CHECKED[lang]}

    # -- gear --------------------------------------------------------------------

    def _gear(self, item: str, modifiers: list[str]) -> dict:
        page = self.items.resolve_page(item)
        families = _families(self.items.modifiers.get(page["slug"], []))      # every group: all can be on an item
        targets, unmatched = [], []
        for text in modifiers:
            check = self.items.check_affix(page["slug"], text)
            if not check["matched"]:
                unmatched.append({"input": text, "reason": check["reason"],
                                  "suggestions": [s["text"] for s in check.get("suggestions", [])]})
                continue
            family = check["family"]
            if any(t.key == _key(family) for t in targets):
                continue
            targets.append(Target(text, _key(family), family["tiers"][0]["text"],
                                  {lang: [split_lines(t[text_field(lang)]) for t in family["tiers"]] for lang in LANGS}))
        keys = {t.key for t in targets}
        bases = [b for b in self.items.bases.values() if b.get("mod_page") == page["slug"]]
        uniques = [u for u in self.items.uniques.values() if u.get("base_slug") in {b["slug"] for b in bases}]
        others = {}
        for lang, suffix in (("en", ""), ("zh-tw", "_zh_tw")):
            others[lang] = [line for f in families if _key(f) not in keys
                            for t in f["tiers"] for line in split_lines(t[text_field(lang)])]
            others[lang] += [t[f"name{suffix}"] for f in families for t in f["tiers"] if t.get(f"name{suffix}")]
            others[lang] += item_text(bases, uniques, suffix)
        return {"kind": "gear", "item_class": page["label"], "item_class_zh_tw": page.get("label_zh_tw"),
                **self._strings(targets, others, leave_out=False), "unmatched": unmatched,
                "sources": [{"label": "poe2db (en)", "url": page["url_en"]},
                            {"label": "poe2db (zh-TW)", "url": page["url_zh_tw"]}]}

    # -- maps --------------------------------------------------------------------

    def _maps(self, avoid: list[str]) -> dict:
        keyed = [(_map_key(f), f) for f in self.atlas.families()]
        targets, unmatched = [], []
        for text in avoid:
            found, reason = _avoided(clean_text(text), keyed)
            if reason:
                unmatched.append({"input": text, "reason": reason})
                continue
            for key, family in found:
                if any(t.key == key for t in targets):
                    continue
                best = family["tiers"][-1]
                targets.append(Target(text, key, LINE_JOIN.join(best["lines"]),
                                      {"en": [t["lines"] for t in family["tiers"]],
                                       "zh-tw": [t["lines_zh_tw"] for t in family["tiers"] if t["lines_zh_tw"]]},
                                      {"id": best["id"]}))
        keys = {t.key for t in targets}
        labels = self.atlas.labels()
        others = {}
        for lang, lines_field in (("en", "lines"), ("zh-tw", "lines_zh_tw")):
            others[lang] = [line for k, f in keyed if k not in keys for t in f["tiers"] for line in t[lines_field]]
            others[lang] += [f"{label}: {PROPERTY_SAMPLE}" for label in labels[f"{lang}_properties"]]
            others[lang] += labels[lang]
        return {"kind": "maps", **self._strings(targets, others, leave_out=True), "unmatched": unmatched,
                "sources": self.atlas.sources()}

    # -- shared ------------------------------------------------------------------

    def _strings(self, targets: list[Target], others: dict, leave_out: bool) -> dict:
        source = self.spec.source("atlas")["search"]
        out = {}
        for lang in LANGS:
            minimum = source["min_fragment_cjk"] if lang == "zh-tw" else source["min_fragment_ascii"]
            shown_others = [form for line in others[lang] for form in shown(line)]
            pieces, rows, missing = [], [], []
            for target in targets:
                tiers = [[shown(line) for line in lines] for lines in target.tiers[lang] if lines]
                row = {"input": target.input, "matched": target.matched, **target.extra}
                if not tiers:
                    missing.append({"input": target.input, "reason": f"no {lang} wording in the local data"})
                    rows.append({**row, "piece": None, "also_matches": []})
                    continue
                found = best_piece(tiers, shown_others, minimum)
                rows.append({**row, "piece": found.piece, "also_matches": found.clashes,
                             **({"shared_with": found.shared} if found.shared else {})})
                if found.piece and found.piece not in pieces:
                    pieces.append(found.piece)
            strings, left_out = pack(pieces, source["max_chars"], leave_out)
            out[lang] = {"strings": strings, "pieces": rows,
                         **({"left_out": left_out} if left_out else {}), **({"missing": missing} if missing else {})}
        return out


# ---------------------------------------------------------------------------
# LINES
# ---------------------------------------------------------------------------


def text_field(lang: str) -> str:
    return "text" if lang == "en" else "text_zh_tw"


def split_lines(text: str | None) -> list[str]:
    """A modifier's stored text as the lines an item shows (a hybrid modifier has two)."""
    return [clean_text(line) for line in (text or "").split("\n") if clean_text(line)]


def shown(line: str) -> list[str]:
    """A line as the item shows it, lower-cased, with each range at its low and at its high end
    ("+(31—33) to Strength" → "+31 to strength", "+33 to strength")."""
    low = RANGE_RE.sub(lambda m: m.group(1), line)
    high = RANGE_RE.sub(lambda m: m.group(2), line)
    return list(dict.fromkeys([low.casefold(), high.casefold()]))


def search_form(line: str) -> str:
    """A shown line with each number as one mark: what pieces are cut from (a mark becomes \\d+)."""
    return NUMBER_RE.sub(NUMBER, line)


def item_text(bases: list[dict], uniques: list[dict], suffix: str) -> list[str]:
    """What the class's items show besides modifiers: names, implicit and effect lines, and the
    property lines with their values ("Physical Damage: 13-18")."""
    out = []
    for record in [*bases, *uniques]:
        if record.get(f"name{suffix}"):
            out.append(record[f"name{suffix}"])
        for field_name in ("implicits", "effects", "properties"):
            out += [line for line in record.get(f"{field_name}{suffix}") or [] if line]
    return out


# ---------------------------------------------------------------------------
# PIECES
# ---------------------------------------------------------------------------


def best_piece(tiers: list[list[list[str]]], others: list[str], minimum: int) -> Found:
    """The shortest piece of one line that matches that line on every tier (low and high values)
    and no other line. `tiers`: per tier, per line, its shown forms. A line with the same wording
    as the target's line, numbers aside, cannot be told apart by any piece (another group's or a
    hybrid modifier's copy of it): it is not a clash, it is reported in `shared`. When every piece
    clashes: the piece with the fewest clashes and what it also matches."""
    best: Found | None = None
    lines = range(max(len(tier) for tier in tiers))
    for index in sorted(lines, key=lambda i: len(_same_wording(others, _forms(tiers, i)))):
        forms = _forms(tiers, index)
        shared = _same_wording(others, forms)
        rest = [line for line in others if line not in set(shared)]
        for regex in candidates(forms, minimum):
            pattern = re.compile(regex, re.IGNORECASE)
            if not all(pattern.search(form) for form in forms):
                continue
            clashes = sorted({search_form(line) for line in rest if pattern.search(line)})
            wordings = sorted({search_form(line) for line in shared})[:MAX_CLASHES_SHOWN]
            if not clashes:
                return Found(regex, [], wordings)
            if best is None or len(clashes) < len(best.clashes):
                best = Found(regex, clashes[:MAX_CLASHES_SHOWN], wordings)
    return best or Found(None)


def _same_wording(others: list[str], forms: list[str]) -> list[str]:
    wording = {search_form(form) for form in forms}
    return sorted({line for line in others if search_form(line) in wording})


def _forms(tiers: list[list[list[str]]], index: int) -> list[str]:
    """Every shown form of line `index` over the tiers (a tier without that line is skipped)."""
    return list(dict.fromkeys(form for tier in tiers if index < len(tier) for form in tier[index]))


def candidates(forms: list[str], minimum: int) -> list[str]:
    """Every piece of the line, as a regular expression, shortest first; at equal length one tied to
    the line's end comes first, then one tied to its start. The pieces are cut from the first form;
    best_piece keeps those that also match the other forms."""
    form = search_form(forms[0])
    found: dict[str, tuple] = {}
    for start in range(len(form)):
        for end in range(start + 1, len(form) + 1):
            core = form[start:end]
            if core != core.strip() or any(ch in NEVER_IN_PIECE for ch in core.replace(NUMBER, "")):
                continue
            if len(LETTER_RE.findall(core)) < minimum:
                continue
            for anchor in _anchors(start == 0, end == len(form)):
                regex = ("^" if "^" in anchor else "") + to_regex(core) + ("$" if "$" in anchor else "")
                found.setdefault(regex, (len(regex), ANCHOR_ORDER[anchor], regex))
    return [regex for regex, _ in sorted(found.items(), key=lambda pair: pair[1])]


def _anchors(at_start: bool, at_end: bool) -> list[str]:
    out = [""]
    if at_start:
        out.append("^")
    if at_end:
        out.append("$")
    if at_start and at_end:
        out.append("^$")
    return out


def to_regex(core: str) -> str:
    """A piece of a search form as a regular expression: a number mark as \\d+, special characters
    escaped."""
    return "".join(r"\d+" if ch == NUMBER else "\\" + ch if ch in SPECIAL else ch for ch in core)


# ---------------------------------------------------------------------------
# AVOIDED WAYSTONE MODIFIERS
# ---------------------------------------------------------------------------


def _avoided(text: str, keyed: list[tuple]) -> tuple[list[tuple], str | None]:
    """The waystone modifiers an avoid entry names: a modifier id (waystone_6), a whole `text` from
    waystone_mods (its lines joined by " / "), one line, or words of one line (numbers left out)."""
    if MOD_ID.match(text):
        found = [(k, f) for k, f in keyed if any(t["id"] == text for t in f["tiers"])]
        return found, None if found else f"no waystone modifier has the id {text}"
    if len(text) < MIN_AVOID_CHARS:
        return [], f"too short; give at least {MIN_AVOID_CHARS} characters of the modifier"
    parts = [template(p) for p in INPUT_PARTS.split(text) if p.strip()]
    found = [(k, f) for k, f in keyed if all(any(p == line for line in _both(f)) for p in parts)] \
        or [(k, f) for k, f in keyed if all(any(_names(p, line) for line in _both(f)) for p in parts)]
    if not found:
        return [], "no waystone modifier has these words"
    if len(found) > MAX_AVOID_MATCHES:
        return [], f"names {len(found)} waystone modifiers; use more of the modifier's words (waystone_mods shows them)"
    return found, None


def _both(family: dict) -> list[str]:
    return family["templates"] + family["templates_zh_tw"]


def _names(wanted: str, line: str) -> bool:
    """The request's words (numbers left out) are all in the line, or it is part of the line."""
    if wanted in line:
        return True
    asked = set(WORD_RE.findall(wanted)) if not is_cjk(wanted) else set()
    return bool(asked) and asked <= set(WORD_RE.findall(line))


# ---------------------------------------------------------------------------
# STRINGS
# ---------------------------------------------------------------------------


def pack(pieces: list[str], max_chars: int, leave_out: bool) -> tuple[list[str], list[str]]:
    """Pieces joined by "|" in quotes, each string within max_chars. Wanted gear can take several
    strings (each is searched on its own); pieces to leave out must all be in one, so those that
    do not fit are returned as left out."""
    head = QUOTE + ("!" if leave_out else "")
    strings, current, left_out = [], [], []
    for piece in pieces:
        trial = head + "|".join([*current, piece]) + QUOTE
        if len(trial) <= max_chars:
            current.append(piece)
        elif leave_out:
            left_out.append(piece)
        elif current:
            strings.append(head + "|".join(current) + QUOTE)
            current = [piece] if len(head + piece + QUOTE) <= max_chars else []
            if not current:
                left_out.append(piece)
        else:
            left_out.append(piece)
    if current:
        strings.append(head + "|".join(current) + QUOTE)
    return strings, left_out


def _key(family: dict) -> tuple:
    return (family["group"], family["affix"], family["family"], family["template"])


def _map_key(family: dict) -> tuple:
    return (family["affix"], tuple(family["templates"]))
