"""
search_string.py — Strings for the in-game search box (stash and vendor windows) that highlight
the gear a build wants, or the waystones a build can run.

The game's search is a regular expression, matched line by line and in any case (seen in the
strings poe2.re and Cabbage Forge produce, 2026-11-18: `mage$`, `\\d+ fire damage$`,
`^rarity: rare$`). For each wanted modifier this finds a piece of one of its lines, numbers written
as `\\d+`, that matches that line on every tier and no other line it knows of: every modifier of
the item class (all groups), modifier names, base and unique names, implicits, property lines with
their values, requirement lines, and the lines every item shows (catalog `atlas.search.fixed_lines`:
rarity, item level, quality; a waystone's revives, pack size, drop chance ...). For waystones: every
other waystone modifier, the tier names, their property lines and the same fixed lines. Every piece
is run with Python's `re` against all those lines before it is returned.

A piece tied to the end of its line (`$`) is taken before one tied to its start (`^`), and either
before a free one, whatever their length: a line the data does not have (a rare item's random
name, a Chinese fixed line the data has no wording for) is far less likely to end the same way.
A free piece is flagged `unanchored`.
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
MAX_SHOWN = 12               # clashes and shared lines listed per piece
MIN_AVOID_CHARS = 3          # an avoid entry shorter than this names too little
MAX_AVOID_MATCHES = 6        # an avoid entry naming more modifiers than this is too broad
NUMBER = "#"                 # a number in a line's search form
NUMBER_TEXT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"      # 1,000 or 12 or 1.5
RANGE_RE = re.compile(rf"\((-?{NUMBER_TEXT})\s*[—–-]\s*(-?{NUMBER_TEXT})\)")
NUMBER_RE = re.compile(NUMBER_TEXT)
UNUSABLE_RE = re.compile(r"[()\[\]（）［］]|\d\s*[—–]\s*-?\d")     # notation the game does not show
SPECIAL = set(".^$*+?{}[]\\|()")             # escaped in a piece
NEVER_IN_PIECE = set('"!\n')                  # would end or turn around the quoted string
LETTER_RE = re.compile(r"[^\W\d_]")
MOD_ID = re.compile(r"^waystone_\d+$", re.IGNORECASE)
INPUT_PARTS = re.compile(rf"{re.escape(LINE_JOIN)}|\n")     # the lines of a waystone_mods `text`
WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
QUOTE = '"'
ANCHOR_CLASSES = ("$", "^", "")      # tried in this order: tied to the end, to the start, free
PROPERTY_SAMPLE = "65"               # the value written into a waystone property line for the check
SOURCE_MODIFIER, SOURCE_IMPLICIT, SOURCE_UNIQUE = "modifier", "implicit", "unique"
SOURCE_NAME, SOURCE_PROPERTY, SOURCE_FIXED = "name", "property", "fixed"
SHAREABLE = {SOURCE_MODIFIER, SOURCE_IMPLICIT, SOURCE_UNIQUE}     # the same sentence here lights the item up too
NOT_CHECKED = {
    "en": ["The string is a regular expression; give it unchanged. It is checked against every modifier, name, "
           "implicit, property and requirement line the data has for this item class (or for waystones), and the "
           "lines every item shows that the catalog lists (rarity, item level, quality; a waystone's revives, pack "
           "size, drop chance ...). Not checked: a rare item's random name, other item classes in the same stash, "
           "and in Traditional Chinese the fixed lines the data has no wording for (normal rarity, corrupted, "
           "unidentified, most waystone property lines). Try it in the game before relying on it.",
           "The string must match the game client's language: use the zh-tw string in a Traditional Chinese client."],
    "zh-tw": ["字串是正則表達式，請原樣使用。它已對照這個裝備類別（或換界石）在資料裡的所有詞綴、名稱、固定詞綴、屬性行與需求行，"
              "以及目錄列出的每件物品都有的行（稀有度、物品等級、品質；換界石的復活次數、怪物數量、掉落機率等）。沒有檢查：稀有物品的隨機名稱、"
              "同一倉庫裡其他類別的物品，以及資料裡沒有中文寫法的固定行（普通稀有度、已腐化、未鑑定、大部分換界石屬性行）。請先在遊戲裡試過再依賴它。",
              "字串必須與遊戲客戶端的語言一致：繁體中文客戶端用 zh-tw 那串。"],
}
HOW_TO_USE = {
    "gear": {"en": "Paste a string into the search box of the stash or a vendor: items with any of the wanted "
                   "modifiers light up. Each string works on its own.",
             "zh-tw": "把字串貼到倉庫或商人視窗的搜尋框：有任一個想要詞綴的物品會亮起。每一串都可以單獨使用。"},
    "maps": {"en": "Paste the string into the stash search box: waystones with any of these modifiers stay dark, "
                   "the ones left lit do not have them, except the modifiers listed in `unmatched`, `missing` or "
                   "`left_out`, which the string does not cover.",
             "zh-tw": "把字串貼到倉庫的搜尋框：有這些詞綴的換界石不會亮，亮著的就是沒有這些詞綴的；"
                      "但 `unmatched`、`missing` 或 `left_out` 列出的詞綴不在字串裡。"},
}
NO_PIECE = "no piece of this modifier can be told apart from the other lines"
UNUSABLE = "the data writes this modifier in a notation the game does not show (e.g. [3,6]), so no piece is cut from it"
NO_WORDING = "no {lang} wording in the local data"
TIERS_DIFFER = "the tiers of this modifier share no line, so one piece cannot match them all"


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
    clash_count: int = 0
    shared: list[dict] = field(default_factory=list)
    unanchored: bool = False
    reason: str | None = None


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
        fixed = self._fixed("gear")
        others = {}
        for lang, suffix in (("en", ""), ("zh-tw", "_zh_tw")):
            others[lang] = [(SOURCE_MODIFIER, line) for f in families if _key(f) not in keys
                            for t in f["tiers"] for line in split_lines(t[text_field(lang)])]
            others[lang] += [(SOURCE_NAME, t[f"name{suffix}"]) for f in families for t in f["tiers"] if t.get(f"name{suffix}")]
            others[lang] += item_text(bases, uniques, suffix)
            others[lang] += [(SOURCE_FIXED, line) for line in fixed[lang] + self._requirements(bases + uniques, lang)]
        return {"kind": "gear", "item_class": page["label"], "item_class_zh_tw": page.get("label_zh_tw"),
                **self._strings(targets, others, leave_out=False), "unmatched": unmatched,
                "sources": [{"label": "poe2db (en)", "url": page["url_en"]},
                            {"label": "poe2db (zh-TW)", "url": page["url_zh_tw"]}]}

    def _fixed(self, kind: str) -> dict[str, list[str]]:
        return self.spec.source("atlas")["search"]["fixed_lines"][kind]

    def _requirements(self, records: list[dict], lang: str) -> list[str]:
        """Each item's requirement line as the game shows it ("Requires: Level 5, 12 Dex"), plus one
        line for each attribute: the stash holds other items than this class's."""
        words = self.spec.source("atlas")["search"]["fixed_lines"]["requirement"][lang]
        out = [f"{words['level'].format(level=PROPERTY_SAMPLE)}, 100 {word}" for word in words["attributes"].values()]
        for record in records:
            level = record.get("requires_level")
            parts = [words["level"].format(level=level)] if level else []
            parts += [f"{value} {words['attributes'][name]}" for name, value in (record.get("requires") or {}).items()
                      if name in words["attributes"]]
            if parts:
                out.append(", ".join(parts))
        return list(dict.fromkeys(out))

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
                named = next((t for t in family["tiers"] if t["id"].casefold() == clean_text(text).casefold()),
                             family["tiers"][-1])
                targets.append(Target(text, key, LINE_JOIN.join(named["lines"]),
                                      {"en": [t["lines"] for t in family["tiers"]],
                                       "zh-tw": [t["lines_zh_tw"] for t in family["tiers"] if t["lines_zh_tw"]]},
                                      {"id": named["id"], **({"modifiers_named": len(found)} if len(found) > 1 else {})}))
        keys = {t.key for t in targets}
        labels = self.atlas.labels()
        fixed = self._fixed("maps")
        others = {}
        for lang, lines_field in (("en", "lines"), ("zh-tw", "lines_zh_tw")):
            others[lang] = [(SOURCE_MODIFIER, line) for k, f in keyed if k not in keys
                            for t in f["tiers"] for line in t[lines_field]]
            others[lang] += [(SOURCE_PROPERTY, f"{label}: {PROPERTY_SAMPLE}") for label in labels[f"{lang}_properties"]]
            others[lang] += [(SOURCE_NAME, name) for name in labels[lang]]
            others[lang] += [(SOURCE_FIXED, line) for line in fixed[lang]]
        return {"kind": "maps", **self._strings(targets, others, leave_out=True), "unmatched": unmatched,
                "sources": self.atlas.sources()}

    # -- shared ------------------------------------------------------------------

    def _strings(self, targets: list[Target], others: dict, leave_out: bool) -> dict:
        source = self.spec.source("atlas")["search"]
        out = {}
        for lang in LANGS:
            minimum = source["min_fragment_cjk"] if lang == "zh-tw" else source["min_fragment_ascii"]
            shown_others = [(origin, form) for origin, line in others[lang] for form in shown(line)]
            pieces, rows, missing = [], [], []
            for target in targets:
                tiers = [[shown(line) for line in lines] for lines in target.tiers[lang] if lines]
                row = {"input": target.input, "matched": target.matched, **target.extra}
                found = best_piece(tiers, shown_others, minimum) if tiers else Found(None, reason=NO_WORDING.format(lang=lang))
                if found.piece is None:
                    missing.append({"input": target.input, "reason": found.reason or NO_PIECE})
                    rows.append({**row, "piece": None, "also_matches": []})
                    continue
                rows.append({**row, "piece": found.piece, "also_matches": found.clashes,
                             **({"also_matches_total": found.clash_count} if found.clash_count > len(found.clashes) else {}),
                             **({"shared_with": found.shared} if found.shared else {}),
                             **({"unanchored": True} if found.unanchored else {})})
                if found.piece not in pieces:
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
    ("+(31—33) to Strength" → "+31 to strength", "+33 to strength"); "1,000" is shown as 1000."""
    low = RANGE_RE.sub(lambda m: m.group(1), line)
    high = RANGE_RE.sub(lambda m: m.group(2), line)
    return list(dict.fromkeys(_plain_numbers(form).casefold() for form in (low, high)))


def _plain_numbers(line: str) -> str:
    return NUMBER_RE.sub(lambda m: m.group().replace(",", ""), line)


def usable(form: str) -> bool:
    """A shown line still holding the data's notation (brackets, a range) is not what the game shows."""
    return not UNUSABLE_RE.search(form)


def search_form(line: str) -> str:
    """A shown line with each number as one mark: what pieces are cut from (a mark becomes \\d+)."""
    return NUMBER_RE.sub(NUMBER, line)


def item_text(bases: list[dict], uniques: list[dict], suffix: str) -> list[tuple[str, str]]:
    """What the class's items show besides modifiers, with where it comes from: names, implicit and
    effect lines, unique modifiers and the property lines with their values ("Physical Damage: 13-18")."""
    out = []
    for kind, records in ((SOURCE_IMPLICIT, bases), (SOURCE_UNIQUE, uniques)):
        for record in records:
            if record.get(f"name{suffix}"):
                out.append((SOURCE_NAME, record[f"name{suffix}"]))
            for field_name in ("implicits", "effects", "mods"):
                out += [(kind, line) for line in record.get(f"{field_name}{suffix}") or [] if isinstance(line, str) and line]
            out += [(SOURCE_PROPERTY, line) for line in record.get(f"properties{suffix}") or [] if line]
    return out


# ---------------------------------------------------------------------------
# PIECES
# ---------------------------------------------------------------------------


def best_piece(tiers: list[list[list[str]]], others: list[tuple[str, str]], minimum: int) -> Found:
    """A piece of one line that matches that line on every tier (low and high values) and no other
    line. Tied to the line's end first, then to its start, then free; the shortest within each.
    `tiers`: per tier, per line, its shown forms; `others`: (where it comes from, shown line).
    A line with the same wording as the target's line, numbers aside, cannot be told apart by any
    piece (another group's copy, a hybrid's line, an implicit): it is not a clash, it is reported in
    `shared` with where it comes from. When every piece clashes: the piece with the fewest clashes."""
    lines = aligned_lines(tiers)
    if lines is None:
        return Found(None, reason=TIERS_DIFFER)
    lines = [forms for forms in lines if all(usable(form) for form in forms)]
    if not lines:
        return Found(None, reason=UNUSABLE)
    best: Found | None = None
    prepared = [(forms, *_split_others(others, forms)) for forms in lines]
    prepared.sort(key=lambda item: len(item[1]))           # the line no other modifier shares first
    for anchor in ANCHOR_CLASSES:
        for forms, shared, rest in prepared:
            decimal = any("." in number for form in forms for number in NUMBER_RE.findall(form))
            for regex in candidates(forms, minimum, anchor, decimal):
                pattern = re.compile(regex, re.IGNORECASE)
                if not all(pattern.search(form) for form in forms):
                    continue
                clashes = sorted({search_form(line) for line in rest if pattern.search(line)})
                if not clashes:
                    return Found(regex, [], 0, shared, unanchored=anchor == "")
                if best is None or len(clashes) < best.clash_count:
                    best = Found(regex, clashes[:MAX_SHOWN], len(clashes), shared, unanchored=anchor == "")
    return best or Found(None)


def aligned_lines(tiers: list[list[list[str]]]) -> list[list[str]] | None:
    """The target's lines, matched up across tiers by wording (not by position): for each wording
    every tier has, all its shown forms. None when the tiers share no wording."""
    by_tier = [{search_form(line[0]): line for line in tier} for tier in tiers]
    common = [wording for wording in by_tier[0] if all(wording in tier for tier in by_tier[1:])]
    if not common:
        return None
    return [list(dict.fromkeys(form for tier in by_tier for form in tier[wording])) for wording in common]


def _split_others(others: list[tuple[str, str]], forms: list[str]) -> tuple[list[dict], list[str]]:
    """(shared, rest): lines with the target line's wording from a modifier, implicit or unique
    (they light the item up too), and every other line."""
    wording = {search_form(form) for form in forms}
    shared: dict[str, str] = {}
    rest = []
    for origin, line in others:
        if search_form(line) in wording and origin in SHAREABLE:
            shared.setdefault(search_form(line), origin)
        elif search_form(line) not in wording:
            rest.append(line)
    return [{"line": line, "source": origin} for line, origin in sorted(shared.items())][:MAX_SHOWN], rest


def candidates(forms: list[str], minimum: int, anchor: str | None = None, decimal: bool = False) -> list[str]:
    """Pieces of the line as regular expressions, shortest first. `anchor`: "$" only pieces tied to
    the line's end, "^" tied to its start, "" free ones, None all of them. The pieces are cut from
    the first form; best_piece keeps those that also match the other forms."""
    form = search_form(forms[0])
    found: dict[str, int] = {}
    for start in range(len(form)):
        for end in range(start + 1, len(form) + 1):
            core = form[start:end]
            if core != core.strip() or any(ch in NEVER_IN_PIECE for ch in core):
                continue
            if len(LETTER_RE.findall(core)) < minimum:
                continue
            for tie in _anchors(start == 0, end == len(form)):
                if anchor is not None and _anchor_class(tie) != anchor:
                    continue
                regex = ("^" if "^" in tie else "") + to_regex(core, decimal) + ("$" if "$" in tie else "")
                found.setdefault(regex, len(regex))
    return sorted(found, key=lambda regex: (found[regex], regex))


def _anchors(at_start: bool, at_end: bool) -> list[str]:
    out = [""]
    if at_start:
        out.append("^")
    if at_end:
        out.append("$")
    if at_start and at_end:
        out.append("^$")
    return out


def _anchor_class(tie: str) -> str:
    return "$" if "$" in tie else "^" if "^" in tie else ""


def to_regex(core: str, decimal: bool = False) -> str:
    """A piece of a search form as a regular expression: a number mark as \\d+ ([\\d.]+ when the line
    has a decimal number), special characters escaped."""
    number = r"[\d.]+" if decimal else r"\d+"
    return "".join(number if ch == NUMBER else "\\" + ch if ch in SPECIAL else ch for ch in core)


# ---------------------------------------------------------------------------
# AVOIDED WAYSTONE MODIFIERS
# ---------------------------------------------------------------------------


def _avoided(text: str, keyed: list[tuple]) -> tuple[list[tuple], str | None]:
    """The waystone modifiers an avoid entry names: a modifier id (waystone_6), a whole `text` from
    waystone_mods (its lines joined by " / "), one line, or words of one line (numbers left out)."""
    if MOD_ID.match(text):
        found = [(k, f) for k, f in keyed if any(t["id"].casefold() == text.casefold() for t in f["tiers"])]
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
