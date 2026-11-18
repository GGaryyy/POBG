"""
search_string.py — Strings for the in-game search box (stash and vendor windows) that highlight
the gear a build wants, or the waystones a build can run.

The string is worked out from the data, never written by the model: for each wanted modifier the
shortest piece of its wording (no numbers, which change from tier to tier) that no other text of
that item class has; for waystones, the pieces of the modifiers to leave out, after "!". A piece
is checked against every modifier of the item class (all groups), the implicits, property labels
and names of its bases — or against every waystone modifier and the waystone tiers' names and
property labels. What still matches something else is listed in `also_matches`; a modifier with
no wording in a language is listed in that language's `missing`.

Syntax used (community guides, not GGG): the whole string in quotes, "|" for either, "!" at the
start to leave out. Nothing else of regular expressions is used, so a piece never holds . + ( )
and the like. The game also reads lines this data does not have (a waystone's pack size or
rarity, other item classes in the same stash), so a string has to be tried in the game.
"""

from __future__ import annotations

import re

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
MIN_AVOID_CHARS = 3          # an avoid entry shorter than this names too little
MAX_AVOID_MATCHES = 6        # an avoid entry naming more modifiers than this is too broad
SPLIT_RE = re.compile(r"[#\\^$.|?*+()\[\]{}\"!,:;\n]")      # never inside a piece
WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")    # an English word (letters, "monster's")
CJK_RUN_RE = re.compile(r"[㐀-鿿]+")
CJK_EDGE = set("的上有在於為和與及個此之其被時中或")          # a Chinese piece neither starts nor ends with these
CJK_SOLID = 3                # Chinese pieces this long are preferred: shorter ones cut words more often
FUNCTION_WORDS = {"from", "with", "have", "your", "that", "this", "while", "when", "into", "than", "take", "deal",
                  "gain", "also", "each", "were", "been", "they", "them", "their", "there", "which", "per",
                  "less", "more", "increased", "reduced", "adds", "additional"}      # on almost every modifier
EDGE_WORDS = {"of", "on", "as", "in", "the", "a", "an", "and", "or", "for", "with", "from", "per", "by", "at",
              "is", "are", "have", "has", "be", "your", "you"}       # a piece of several words does not start or end so
MOD_ID = re.compile(r"^waystone_\d+$")
INPUT_PARTS = re.compile(rf"\s*{re.escape(LINE_JOIN.strip())}\s*|\n")     # the lines of a waystone_mods `text`
QUOTE = '"'
NOT_CHECKED = {
    "en": ["Checked against the data of this item class (or of waystones) only: the game also reads lines the data "
           "does not have (a waystone's pack size and rarity lines, other item classes in the same stash). Try the "
           "string in the game before relying on it.",
           "The string must match the game client's language: use the zh-tw string in a Traditional Chinese client."],
    "zh-tw": ["只對照這個裝備類別（或換界石）的資料檢查：遊戲還會比對資料裡沒有的文字（換界石的怪物數量與稀有度等行、"
              "同一倉庫裡其他類別的物品）。請先在遊戲裡試過再依賴它。",
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
            if check["matched"]:
                family = check["family"]
                if all(t["key"] != _key(family) for t in targets):
                    targets.append({"input": text, "key": _key(family), "matched": family["tiers"][0]["text"],
                                    "en": _lines(family["template"]), "zh-tw": _lines(family["template_zh_tw"])})
            else:
                unmatched.append({"input": text, "reason": check["reason"],
                                  "suggestions": [s["text"] for s in check.get("suggestions", [])]})
        others = {"en": [(_key(f), _lines(f["template"])) for f in families],
                  "zh-tw": [(_key(f), _lines(f["template_zh_tw"])) for f in families]}
        bases = [b for b in self.items.bases.values() if b.get("mod_page") == page["slug"]]
        for lang, suffix in (("en", ""), ("zh-tw", "_zh_tw")):
            others[lang].append((("bases",), _base_text(bases, suffix)))
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
                if all(t["key"] != key for t in targets):
                    best = family["tiers"][-1]
                    targets.append({"input": text, "key": key, "matched": LINE_JOIN.join(best["lines"]),
                                    "id": best["id"], "en": family["templates"], "zh-tw": family["templates_zh_tw"]})
        labels = self.atlas.labels()
        others = {lang: [(k, f["templates"] if lang == "en" else f["templates_zh_tw"]) for k, f in keyed]
                  + [(("labels",), labels[lang])] for lang in LANGS}
        return {"kind": "maps", **self._strings(targets, others, leave_out=True), "unmatched": unmatched,
                "sources": self.atlas.sources()}

    # -- shared ------------------------------------------------------------------

    def _strings(self, targets: list[dict], others: dict, leave_out: bool) -> dict:
        source = self.spec.source("atlas")["search"]
        out = {}
        for lang in LANGS:
            minimum = source["min_fragment_cjk"] if lang == "zh-tw" else source["min_fragment_ascii"]
            wanted_keys = {t["key"] for t in targets}
            wanted_lines = {tuple(t[lang]) for t in targets}      # the same wording in another group is the same line
            rest = [(key, lines) for key, lines in others[lang] if key not in wanted_keys and tuple(lines) not in wanted_lines]
            pieces, rows, missing = [], [], []
            for target in targets:
                piece, clashes = shortest_piece(target[lang], rest, minimum)
                row = {"input": target["input"], "matched": target["matched"], "piece": piece, "also_matches": clashes}
                rows.append({**row, **({"id": target["id"]} if "id" in target else {})})
                if piece is None:
                    missing.append({"input": target["input"], "reason": f"no {lang} wording in the local data"})
                elif piece not in pieces:
                    pieces.append(piece)
            strings, left_out = pack(pieces, source["max_chars"], leave_out)
            out[lang] = {"strings": strings, "pieces": rows,
                         **({"left_out": left_out} if left_out else {}), **({"missing": missing} if missing else {})}
        return out


# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def shortest_piece(lines: list[str], others: list[tuple], minimum: int) -> tuple[str | None, list[str]]:
    """The best piece that no other entry's lines hold, taken from the first line that has one (a
    modifier's first line says what it does; later lines are often shared), and [] — or, when
    every piece is shared, the piece shared with the fewest others and what it also matches.
    Pieces of several English words (or of three Chinese characters) come before single words:
    a lone word is more likely to be found in text the data does not have."""
    best, best_clashes = None, None
    for line in lines:
        edges = CJK_RUN_RE.findall(line)
        for candidate in sorted(set(_pieces(line, minimum)), key=lambda c: _rank(c, edges)):
            clashes = [lines_[0] for _, lines_ in others if lines_ and any(candidate in other for other in lines_)]
            if not clashes:
                return candidate, []
            if best_clashes is None or len(clashes) < len(best_clashes):
                best, best_clashes = candidate, clashes
    return best, best_clashes or []


def _rank(piece: str, runs: list[str]) -> tuple:
    """Order of preference: several words (three Chinese characters) before one word; in Chinese a
    piece at the start or end of a run of characters (more often a whole word); then the shortest."""
    if is_cjk(piece):
        inside = not any(run.startswith(piece) or run.endswith(piece) for run in runs)
        return (len(piece) < CJK_SOLID, inside, len(piece), piece)
    return (" " not in piece, False, len(piece), piece)


def _pieces(line: str, minimum: int):
    """Pieces a search can use: in English whole words (one or more in a row; several words do not
    start or end with "of", "to" and the like), in Chinese a run of Chinese characters that does not
    start or end with a particle such as 的 or 上."""
    for part in SPLIT_RE.split(line):
        if is_cjk(part):
            for run in CJK_RUN_RE.findall(part):
                for start in range(len(run)):
                    for end in range(start + minimum, len(run) + 1):
                        piece = run[start:end]
                        if piece[0] not in CJK_EDGE and piece[-1] not in CJK_EDGE:
                            yield piece
            continue
        words = list(WORD_RE.finditer(part))
        for i, first in enumerate(words):
            for j in range(i, len(words)):
                last = words[j]
                piece = part[first.start():last.end()]
                if len(piece) < minimum:
                    continue
                if i == j and piece not in FUNCTION_WORDS:
                    yield piece
                elif i != j and first.group() not in EDGE_WORDS and last.group() not in EDGE_WORDS:
                    yield piece


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


def _lines(text: str | None) -> list[str]:
    return [line for line in (text or "").split("\n") if line]


def _base_text(bases: list[dict], suffix: str) -> list[str]:
    """What the game shows on the class's items besides modifiers: base names, implicit and effect
    lines, and the labels of the property lines ("Armour", "Critical Hit Chance")."""
    out = []
    for base in bases:
        name = base.get(f"name{suffix}")
        if name:
            out.append(name.casefold())
        for field in ("implicits", "effects"):
            out += [template(line) for line in base.get(f"{field}{suffix}") or []]
        out += [line.split(":")[0].strip().casefold() for line in base.get(f"properties{suffix}") or [] if ":" in line]
    return out


def _key(family: dict) -> tuple:
    return (family["group"], family["affix"], family["family"], family["template"])


def _map_key(family: dict) -> tuple:
    return (family["affix"], tuple(family["templates"]))
