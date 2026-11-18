"""
atlas.py — The atlas facts on top of LookupService: waystone tiers, the resistance penalty, the
waystone modifiers, and the map stages a build up to Tier 16 is planned against.

Every number comes from poe2db's Waystones page (data/atlas). The map stages (catalog
`atlas.stage_tiers`, Tier 1 / 10 / 16 in 0.5) follow the campaign stages: their level is the
tier's area level, and their ascendancy points add the endgame trials the catalog lists
(`atlas.endgame_trials`, hand-checked). Map bosses and pinnacle fights are not in the data.
"""

from __future__ import annotations

import copy
import json
import re
import threading

from src.scrapers.collect_items import modifier_template as template
from src.scrapers.common import clean_text, read_jsonl
from src.tools.lookup import BadArgument, LookupService, ServiceUnavailable, _cap, _limit, _sources, is_cjk

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

SOURCE = "atlas"
REBUILD_HINT = "atlas data missing; update it with update_data scope atlas"
MAP_STAGE_PREFIX = "maps_t"
AFFIXES = ("prefix", "suffix")
DEFAULT_LIMIT = 40
LINE_JOIN = " / "
NOT_IN_DATA = {
    "en": ["How hard a modifier makes a map for a build: not calculated; the lines say what changes.",
           "Monster damage and life by area level, map bosses and the pinnacle fights: not in the local data.",
           "How Tier 16 waystones are obtained: not in the local data.",
           "Atlas passives, tablets and desecrated waystone modifiers: not collected."],
    "zh-tw": ["某個詞綴讓地圖對這個流派有多難：沒有計算，只有詞綴寫了什麼。",
              "各區域等級的怪物傷害與生命、地圖頭目與巔峰頭目：本機資料沒有。",
              "T16 換界石怎麼取得：本機資料沒有。",
              "輿圖天賦、石板與褻瀆換界石詞綴：未收集。"],
}
TIER_NAME = {"en": "Maps, Tier {tier}", "zh-tw": "地圖（階級 {tier}）"}
TIER_WORDS = re.compile(r"^(?:(?:t|tier|maps?\s*t?|map\s*tier|階級|地圖)\s*(\d+)|第\s*(\d+)\s*階)$")


class AtlasLookup:
    """Loads the atlas files once, on first use."""

    def __init__(self, lookup: LookupService) -> None:
        self.lookup = lookup
        self._loaded = False
        self._lock = threading.Lock()
        self.atlas: dict = {}
        self.mods: list[dict] = []

    def _load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            source = self.lookup.spec.source(SOURCE)
            paths = [self.lookup.base_dir / source[key] for key in ("atlas_file", "mods_file")]
            if not all(p.exists() for p in paths):
                raise ServiceUnavailable(REBUILD_HINT)
            try:
                atlas = json.loads(paths[0].read_text(encoding="utf-8"))
                mods = read_jsonl(paths[1])
                _check_shape(atlas, mods)
            except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
                raise ServiceUnavailable(f"the atlas data is unreadable ({type(exc).__name__}); "
                                         "update it with update_data scope atlas") from exc
            self.atlas, self.mods = atlas, mods
            self._loaded = True

    # -- stages ------------------------------------------------------------------

    def map_stages(self, after_order: int, after_level: int = 0) -> list[dict]:
        """The map stages in the campaign stages' shape, ordered after `after_order`; the first one's
        area levels start after `after_level` (the last act's)."""
        self._load()
        source = self.lookup.spec.source(SOURCE)
        tiers = {row["tier"]: row for row in self.atlas["tiers"]}
        out, previous = [], after_level or None
        for offset, tier in enumerate(source["stage_tiers"], 1):
            row = tiers.get(tier)
            if row is None:
                raise ServiceUnavailable(f"the atlas data has no waystone tier {tier}; update it with update_data "
                                         "scope atlas")
            level = row["area_level"]
            trials = [{"area": None, "name": t["trial"], "name_zh_tw": t.get("trial_zh_tw"), "area_level": t["area_level"],
                       "ascendancy_points": t["points"]}
                      for t in source.get("endgame_trials", []) if (out[-1]["area_level_max"] if out else 0)
                      < t["area_level"] <= level]
            out.append({"id": f"{MAP_STAGE_PREFIX}{tier}", "order": after_order + offset, "kind": "maps", "tier": tier,
                        "page": source["slug"], "name": TIER_NAME["en"].format(tier=tier),
                        "name_zh_tw": TIER_NAME["zh-tw"].format(tier=tier),
                        "area_level_min": previous + 1 if previous else level, "area_level_max": level,
                        "areas": [], "bosses": [], "rewards": [], "trials": trials,
                        "url_en": self.atlas["url_en"], "url_zh_tw": self.atlas["url_zh_tw"]})
            previous = level
        return out

    def penalty_at(self, level: int) -> int | None:
        """The elemental resistance penalty from this level on (None when the table is empty)."""
        self._load()
        rows = [r["penalty"] for r in self.atlas.get("resistance_penalty", []) if r["level"] <= level]
        return rows[-1] if rows else None

    def trials_source(self) -> str:
        source = self.lookup.spec.source(SOURCE)
        return self.lookup.spec.resolve_url(source["endgame_trials_slug"], "en")

    # -- waystone modifiers --------------------------------------------------------------

    def waystone_mods(self, text: str | None = None, affix: str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
        """Waystone modifiers, one entry per modifier with its tiers, by words in its lines (either
        language) and by prefix or suffix."""
        self._load()
        _cap(text, "text")
        if affix not in (None, "", *AFFIXES):
            raise BadArgument(f"affix must be one of {AFFIXES}")
        text = clean_text(text) if isinstance(text, str) else None
        wanted = template(text) if text else None
        lang = "zh-tw" if text and is_cjk(text) else "en"
        families = [f for f in self.families() if (not affix or f["affix"] == affix)
                    and (not wanted or any(wanted in line for line in f["templates"] + f["templates_zh_tw"]))]
        return {"filters": {"text": text or None, "affix": affix or None}, "total": len(families),
                "modifiers": [_family_brief(f) for f in families[:_limit(limit)]],
                "note": "Waystone modifiers make a map harder and give more rewards; each line is what the modifier "
                        "does. Higher tiers of a modifier have larger numbers.",
                "not_in_data": NOT_IN_DATA[lang], "sources": self.sources()}

    def families(self) -> list[dict]:
        """The modifier rows grouped by wording (numbers left out), in page order."""
        self._load()
        groups: dict[tuple, dict] = {}
        for mod in self.mods:
            templates = [template(line) for line in mod["lines"]]
            key = (mod["affix"], tuple(templates))
            entry = groups.setdefault(key, {"affix": mod["affix"], "templates": templates,
                                            "templates_zh_tw": [template(line) for line in mod.get("lines_zh_tw") or []],
                                            "tiers": []})
            entry["tiers"].append({"id": mod["id"], "lines": mod["lines"], "lines_zh_tw": mod.get("lines_zh_tw") or []})
        return list(groups.values())

    def labels(self) -> dict[str, list[str]]:
        """Other text on a waystone, by language: the tier names ("en", "zh-tw") and the labels of
        their property lines ("en_properties", "zh-tw_properties", e.g. "Area Level")."""
        self._load()
        labels = self.atlas.get("labels") or {}
        return {"en": [t["name"] for t in self.atlas["tiers"]],
                "zh-tw": [t["name_zh_tw"] for t in self.atlas["tiers"] if t.get("name_zh_tw")],
                "en_properties": list(labels.get("en", [])), "zh-tw_properties": list(labels.get("zh-tw", []))}

    def sources(self) -> list[dict]:
        self._load()
        return _sources(self.atlas.get("url_en"), self.atlas.get("url_zh_tw"), self.atlas.get("fetched_at"))

    def facts(self) -> dict:
        """The tier table and the penalty table, for campaign_stages."""
        self._load()
        return {"tiers": copy.deepcopy(self.atlas["tiers"]),
                "resistance_penalty": copy.deepcopy(self.atlas.get("resistance_penalty", []))}


# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def _check_shape(atlas: dict, mods: list[dict]) -> None:
    """Raise ValueError when the files parse but do not hold what the lookups read."""
    tiers, penalty = atlas["tiers"], atlas.get("resistance_penalty", [])
    if not isinstance(tiers, list) or not tiers or not isinstance(penalty, list):
        raise ValueError("no tier list, or a penalty table that is not a list")
    if not all(isinstance(atlas.get(key), str) for key in ("url_en", "url_zh_tw")):
        raise ValueError("no source URLs")
    for row in [*tiers, *penalty]:
        keys = ("tier", "area_level") if row in tiers else ("level", "penalty")
        if not isinstance(row, dict) or not all(isinstance(row.get(k), int) and not isinstance(row.get(k), bool)
                                                for k in keys):
            raise ValueError(f"a row without whole numbers for {', '.join(keys)}")
    if any(not isinstance(m, dict) or not m.get("lines") or not m.get("id") for m in mods):
        raise ValueError("a modifier without an id or lines")


def tier_from_words(text: str) -> int | None:
    """16 for "T16", "tier 16", "maps_t16", "階級 16", "第 16 階"; None otherwise."""
    match = TIER_WORDS.match(clean_text(text).casefold().replace("_", " "))
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def _family_brief(family: dict) -> dict:
    best = family["tiers"][-1]          # the last listed: poe2db lists a modifier's tiers from the smallest numbers
    return {"affix": family["affix"], "id": best["id"], "lines": best["lines"], "lines_zh_tw": best["lines_zh_tw"],
            "tiers": len(family["tiers"]), "ids": [t["id"] for t in family["tiers"]],
            "text": LINE_JOIN.join(best["lines"])}
