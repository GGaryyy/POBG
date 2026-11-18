"""
atlas_support.py — A synthetic poe2db Waystones page (English and Traditional Chinese) in the shape
the real page has (checked 2026-11-17): the waystone tier tab, the waystone modifier table and the
resistance penalty table, each in a tab whose id differs by language. Plus a helper that collects
it into <base>/data/atlas the way the collector does.

Tiers 1-16 are area levels 65-80. Modifiers (in page order): a prefix row without lines (skipped),
rare monster modifiers, two tiers of extra fire, reduced extra damage from crits, less effect of
curses, players cursed with Enfeeble.
"""

from __future__ import annotations

import copy
from pathlib import Path

import requests

from src.catalog.spec import Spec, load_spec

PENALTY = [(1, 0), (16, -10), (33, -20), (45, -30), (54, -40), (60, -50), (65, -60)]
# (level, en affix, zh affix, en lines, zh lines)
MODS = [
    (1, "Prefix", "前綴", [], []),
    (1, "Suffix", "後綴", ["Rare Monsters have <span class='mod-value'>1</span> additional Modifiers",
                         "<span class='mod-value'>10</span>% increased Waystones found in Area"],
     ["稀有怪物有<span class='mod-value'>1</span>個額外詞綴", "增加<span class='mod-value'>10</span>%此區域找到的換界石"]),
    (1, "Prefix", "前綴", ["Monsters deal <span class='mod-value'>(5<span class='ndash'>—</span>9)</span>% of Damage as Extra Fire",
                         "<span class='mod-value'>15</span>% more Waystones found in Area"],
     ["怪物造成等同於傷害<span class='mod-value'>(5—9)</span>%的額外火焰傷害", "此區域找到<span class='mod-value'>15</span>%更多換界石"]),
    (1, "Prefix", "前綴", ["Monsters deal <span class='mod-value'>(10<span class='ndash'>—</span>14)</span>% of Damage as Extra Fire",
                         "<span class='mod-value'>15</span>% more Waystones found in Area"],
     ["怪物造成等同於傷害<span class='mod-value'>(10—14)</span>%的額外火焰傷害", "此區域找到<span class='mod-value'>15</span>%更多換界石"]),
    (1, "Suffix", "後綴", ["Monsters take <span class='mod-value'>(20—25)</span>% reduced Extra Damage from Critical Hits",
                         "<span class='mod-value'>10</span>% more Waystones found in Area"],
     ["怪物遭暴擊時，減少<span class='mod-value'>(20—25)</span>%承受的額外傷害", "此區域找到<span class='mod-value'>10</span>%更多換界石"]),
    (1, "Suffix", "後綴", ["<span class='mod-value'>(20—30)</span>% less effect of Curses on Monsters",
                         "<span class='mod-value'>10</span>% more Rarity of Items found in this Area"],
     ["怪物身上的詛咒具有<span class='mod-value'>(20—30)</span>%更少效果", "此區域找到的物品擁有<span class='mod-value'>10</span>%更多稀有度"]),
    (1, "Suffix", "後綴", ["Players are periodically Cursed with Enfeeble", "<span class='mod-value'>20</span>% more Waystones found in Area"],
     ["玩家正在持續被衰弱詛咒", "此區域找到<span class='mod-value'>20</span>%更多換界石"]),
]
PANES = {"en": {"tiers": "WaystonesItem", "mods": "WaystonesMods", "penalty": "LevelResistPenalty",
                "area_level_label": "Area Level"},
         "zh-tw": {"tiers": "換界石物品", "mods": "換界石Mods", "penalty": "LevelResistPenalty",
                   "area_level_label": "區域等級"}}


def tier_col(tier: int, lang: str) -> str:
    name = f"換界石（階級 {tier}）" if lang == "zh-tw" else f"Waystone (Tier {tier})"
    label = "區域等級" if lang == "zh-tw" else "Area Level"
    href = f"Waystone_%28Tier_{tier}%29"
    return (f'<div class="col"><div class="d-flex border-top rounded"><div class="flex-shrink-0"><a class="whiteitem Map" '
            f'href="{href}"><img alt="EndgameMap{tier}"/></a></div><div class="flex-grow-1 ms-2"><a class="whiteitem Map" '
            f'href="{href}">{name}</a><div><div class="property">{label}: <span class="colourDefault">{64 + tier}</span>'
            f'</div></div></div></div></div>')


def table(heads: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in heads)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="table-responsive"><table class="table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def pane(pane_id: str, header: str, inner: str) -> str:
    return f'<div class="tab-pane fade" id="{pane_id}"><div class="card mb-2"><h5 class="card-header">{header}</h5>{inner}</div></div>'


def waystones_page(lang: str, *, tiers: range = range(1, 17), mods: list | None = None, penalty: list | None = None,
                   panes: dict | None = None) -> str:
    zh = lang == "zh-tw"
    ids = (panes or PANES)[lang]
    tier_html = '<div class="row">' + "".join(tier_col(t, lang) for t in tiers) + "</div>"
    mod_rows = [[str(level), zh_affix if zh else en_affix, "<br/>".join(zh_lines if zh else en_lines)]
                for level, en_affix, zh_affix, en_lines, zh_lines in (MODS if mods is None else mods)]
    penalty_rows = [[str(level), str(value)] for level, value in (PENALTY if penalty is None else penalty)]
    return ("<html><body>"
            + pane(ids["tiers"], "Waystones Item /16", tier_html)
            + pane("EndGameMaps", "EndGame Maps /3", "<div>Map bosses are not collected</div>")
            + pane(ids["mods"], "Waystones Mods /7", table(["等級" if zh else "Level", "Pre/Suf", "Description"], mod_rows))
            + pane(ids["penalty"], "Level Resist Penalty /7", table(["Level", "Resist Penalty"], penalty_rows))
            + "</body></html>")


def site_pages(**en_options) -> dict[str, str]:
    spec = load_spec()
    return {spec.resolve_url("Waystones", "en"): waystones_page("en", **en_options),
            spec.resolve_url("Waystones", "zh-tw"): waystones_page("zh-tw")}


class AtlasSite:
    """A fetcher over the synthetic page that counts its requests; an unknown page is a 404."""

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = pages if pages is not None else site_pages()
        self.calls: list[str] = []

    def __call__(self, url: str) -> str:
        self.calls.append(url)
        if url not in self.pages:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(f"404 for {url}", response=response)
        return self.pages[url]


def atlas_spec(**expect) -> Spec:
    """The real catalog with minimums this small page meets (or the ones given)."""
    raw = copy.deepcopy(load_spec().raw)
    raw["sources"]["atlas"]["expect_min"] = {"tiers": 10, "mods": 4, "penalty_rows": 5, "zh_ratio": 0.8, **expect}
    return Spec(raw)


def write_atlas_data(base: Path, cache_dir: Path) -> dict:
    """Collect the synthetic page and write data/atlas/* under `base`, the way the collector does."""
    from src.scrapers import collect_atlas
    spec = atlas_spec()
    result = collect_atlas.collect(spec, fetch=AtlasSite(), cache_dir=cache_dir)
    collect_atlas.write(spec, base, result)
    return result
