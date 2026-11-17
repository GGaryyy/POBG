"""
currency_support.py — A synthetic poe2db currency site (three listing pages in two languages and
each item's own page), in the shape the real pages have (checked 2026-11-17), plus a helper that
collects it into <base>/data/currency the way the collector does.

18 items: 8 in the Stackable Currency tab (Runic Alloy is also in the Essence tab), 3 essences,
1 splinter, 1 catalyst, 3 omens, 2 runes / soul cores. Flesh Catalyst has no Chinese entry.
Exalted Orb's page uses the older table layout; every other page uses name/value cards.
"""

from __future__ import annotations

import copy
from pathlib import Path

import requests

from src.catalog.spec import Spec, load_spec

# ---------------------------------------------------------------------------
# PAGE PARTS
# ---------------------------------------------------------------------------

ICON = '<img alt="Icon" height="16" src="https://cdn.poe2db.tw/image/Art/x.webp"/>'
KEYWORD = '<a class="KeywordPopups" data-keyword="{key}" href="{key}">{text}</a>'


def stack(label: str = "Stack Size", size: int = 20) -> str:
    return f'<div class="property">{label}: <span class="colourDefault">1 / {size}</span></div>'


def min_level(level: int, label: str = "Minimum Modifier Level") -> str:
    return (f'<div class="property">{KEYWORD.format(key="BetterCurrencyMinimumLevel", text=label)}: '
            f'<span class="colourDefault">{level}</span></div>')


def max_level(level: int, label: str = "Maximum Item Level") -> str:
    return (f'<div class="property">{KEYWORD.format(key="CurrencyMaximumItemLevel", text=label)}: '
            f'<span class="colourDefault">{level}</span></div>')


def limited(text: str, label: str = "Limited to") -> str:
    return f'<div class="property">{label}: <span class="colourDefault">{text}</span></div>'


def entry(slug: str, name: str, props: tuple = (), lines: tuple = (), *, requires: str | None = None,
          link_class: str = "item_currency StackableCurrency", icon: bool = True) -> str:
    """One listing entry. lines: (mod class, html) pairs, e.g. ("explicitMod", "Adds ...")."""
    first = f'<a class="{link_class}" href="{slug}"><img alt="Icon" class="w1" src="x.webp"/></a>'
    named = f'<a class="{link_class}" href="{slug}">{ICON if icon else ""}{name}</a>'
    body = "".join(props) + '<div class="separator"></div>'
    if requires:
        body += f'<div class="requirements">{requires}</div><div class="separator"></div>'
    body += "".join(f'<div class="{kind}">{html}</div>' for kind, html in lines)
    return (f'<div class="col"><div class="d-flex border-top rounded"><div class="flex-shrink-0">{first}</div>'
            f'<div class="flex-grow-1 ms-2">{named}<div>{body}</div></div></div></div>')


def pane(pane_id: str, header: str, entries: list[str]) -> str:
    return (f'<div class="tab-pane fade" id="{pane_id}"><div class="card"><h5 class="card-header">{header} '
            f'/{len(entries)}</h5><div class="row">{"".join(entries)}</div></div></div>')


def listing(*panes: str) -> str:
    tabs = "".join(f'<a data-bs-toggle="tab" href="#t{i}">tab</a>' for i in range(len(panes)))
    return f'<html><body><ul class="nav">{tabs}</ul><div class="tab-content">{"".join(panes)}</div></body></html>'


def card_page(fields: dict[str, str]) -> str:
    cards = "".join(f'<div class="col"><div class="card name-value p-1"><div class="name">{k} '
                    f'<span class="fas fa-info-circle"></span></div><div class="value">{v}</div></div></div>'
                    for k, v in fields.items())
    return f'<html><body><div class="newItemPopup"></div><div class="row">{cards}</div></body></html>'


def table_page(fields: dict[str, str]) -> str:
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in fields.items())
    return f'<html><body><div class="card"><table><tbody>{rows}</tbody></table></div></body></html>'


# ---------------------------------------------------------------------------
# THE ITEMS: slug -> (English, Chinese, drop level, class, tags, type)
# ---------------------------------------------------------------------------

ITEMS = {
    "Chaos_Orb": ("Chaos Orb", "混沌石", 12, "Stackable Currency", "currency", "CurrencyRerollRare"),
    "Greater_Chaos_Orb": ("Greater Chaos Orb", "高階混沌石", 35, "Stackable Currency", "currency", "CurrencyRerollRare2"),
    "Exalted_Orb": ("Exalted Orb", "崇高石", 2, "Stackable Currency", "currency", "CurrencyAddModToRare"),
    "Perfect_Exalted_Orb": ("Perfect Exalted Orb", "完美崇高石", 50, "Stackable Currency", "currency",
                            "CurrencyAddModToRare3"),
    "Artificers_Shard": ("Artificer's Shard", "工匠碎片", 5, "Stackable Currency", "currency_shard, currency",
                         "CurrencyAddEquipmentSocketShard"),
    "Gnawed_Jawbone": ("Gnawed Jawbone", "啃咬的顎骨", 40, "Stackable Currency", "currency", "AbyssJawbone"),
    "Thaumaturgic_Flux_Level_5": ("Thaumaturgic Flux (Level 5)", "奇術熔劑（等級 5）", 5, "Stackable Currency",
                                  "currency", "Flux5"),
    "Runic_Alloy": ("Runic Alloy", "符文合金", 60, "Stackable Currency", "currency", "Alloy"),
    "Essence_of_the_Body": ("Essence of the Body", "肉體精髓", 10, "Stackable Currency", "essence, currency",
                            "CurrencyEssenceLife"),
    "Greater_Essence_of_the_Body": ("Greater Essence of the Body", "高階肉體精髓", 60, "Stackable Currency",
                                    "essence, currency", "CurrencyGreaterEssenceLife"),
    "Perfect_Essence_of_the_Body": ("Perfect Essence of the Body", "完美肉體精髓", 72, "Stackable Currency",
                                    "essence, currency", "CurrencyPerfectEssenceLife"),
    "Breach_Splinter": ("Breach Splinter", "裂痕碎片", 66, "Stackable Currency", "breach", "BreachSplinter"),
    "Flesh_Catalyst": ("Flesh Catalyst", "血肉催化劑", 65, "Stackable Currency", "catalyst", "CatalystLife"),
    "Omen_of_Whittling": ("Omen of Whittling", "削切之兆", 75, "Omen", "", "OmenOnChaosLowestLevelMod"),
    "Omen_of_Greater_Exaltation": ("Omen of Greater Exaltation", "高階崇高之兆", 75, "Omen", "",
                                   "OmenOnExaltTwoMods"),
    "Omen_of_Dextral_Crystallisation": ("Omen of Dextral Crystallisation", "右手結晶之兆", 75, "Omen", "",
                                        "OmenPerfectEssenceSuffix"),
    "Desert_Rune": ("Desert Rune", "沙漠符文", 15, "SoulCore", "", "FireRune"),
    "Amanamus_Gaze": ("Amanamu's Gaze", "阿曼納姆的凝視", 1, "SoulCore", "", "AncientRune"),
}
NO_CHINESE = {"Flesh_Catalyst"}
TABLE_LAYOUT = {"Exalted_Orb"}


def _en_entries() -> dict[str, list[str]]:
    rare = KEYWORD.format(key="ItemRarity", text="Rare")
    return {
        "currency": [
            entry("Chaos_Orb", "Chaos Orb", (stack(),), (("explicitMod", f"Removes a random modifier and augments a "
                                                          f"{rare} item with a new random modifier"),)),
            entry("Greater_Chaos_Orb", "Greater Chaos Orb", (stack(), min_level(35)),
                  (("explicitMod", f"Removes a random modifier and augments a {rare} item with a new random modifier"),)),
            entry("Exalted_Orb", "Exalted Orb", (stack(),), (("explicitMod", f"Augments a {rare} item with a new "
                                                              "random modifier"),)),
            entry("Perfect_Exalted_Orb", "Perfect Exalted Orb", (stack(), min_level(50)),
                  (("explicitMod", f"Augments a {rare} item with a new random modifier"),)),
            entry("Artificers_Shard", "Artificer's Shard", (stack(size=10),)),
            entry("Gnawed_Jawbone", "Gnawed Jawbone", (stack(), max_level(64)),
                  (("explicitMod", "Desecrates a Rare Weapon or Quiver with a new unrevealed modifier"),)),
            entry("Thaumaturgic_Flux_Level_5", "Thaumaturgic Flux (Level 5)", (stack(),),
                  (("explicitMod", "Used to craft a Level 5 Thaumaturgic item"),)),
            entry("Runic_Alloy", "Runic Alloy", (stack(),), (("explicitMod", "Adds a Runic modifier"),)),
        ],
        "essence": [
            entry("Essence_of_the_Body", "Essence of the Body", (stack(size=10),),
                  (("explicitMod", "Upgrades a Magic item to a Rare item, adding a guaranteed modifier"),
                   ("explicitMod", 'Body Armour: +(30<span class="ndash">—</span>39) to maximum Life'))),
            entry("Greater_Essence_of_the_Body", "Greater Essence of the Body", (stack(size=10),),
                  (("explicitMod", "Upgrades a Magic item to a Rare item, adding a guaranteed modifier"),
                   ("explicitMod", 'Belt, Body Armour, Helmet or Shield: +(100<span class="ndash">—</span>119) to '
                                   "maximum Life"))),
            entry("Perfect_Essence_of_the_Body", "Perfect Essence of the Body", (stack(size=10),),
                  (("explicitMod", "Removes a random modifier and augments a Rare item with a new guaranteed "
                                   "modifier"),)),
            entry("Runic_Alloy", "Runic Alloy", (stack(),), (("explicitMod", "Adds a Runic modifier"),)),
        ],
        "splinter": [entry("Breach_Splinter", "Breach Splinter", (stack(size=100),),
                           (("explicitMod", "Combine 100 Splinters to create a Breachstone"),))],
        "catalyst": [entry("Flesh_Catalyst", "Flesh Catalyst", (stack(),),
                           (("explicitMod", "Adds quality that enhances Life modifiers on a Ring or Amulet"),))],
        "omen": [
            entry("Omen_of_Whittling", "Omen of Whittling", (stack(size=10),),
                  (("explicitMod", "While this item is active in your inventory your next<br/>\nChaos Orb will "
                                   "remove the lowest level modifier"),), link_class="whiteitem Omen", icon=False),
            entry("Omen_of_Greater_Exaltation", "Omen of Greater Exaltation", (stack(size=10),),
                  (("explicitMod", "While this item is active in your inventory your next Exalted Orb will add two "
                                   "random modifiers"),), link_class="whiteitem Omen", icon=False),
            entry("Omen_of_Dextral_Crystallisation", "Omen of Dextral Crystallisation", (stack(size=10),),
                  (("explicitMod", "While this item is active in your inventory your next Perfect Essence will "
                                   "remove only Suffix modifiers"),), link_class="whiteitem Omen", icon=False),
        ],
        "augment": [
            entry("Desert_Rune", "Desert Rune", (stack(size=10),),
                  (("implicitMod", 'Martial Weapon: Adds <span class="mod-value">7</span> to '
                                   '<span class="mod-value">11</span> Fire Damage'),
                   ("implicitMod", 'Armour: <span class="mod-value">+14</span>% to Fire Resistance'),
                   ("bondedMod", "Bonded:"), ("bondedMod", "Armour: +20 to maximum Life")),
                  requires='Requires: <span class="colourDefault">Level 15</span>', link_class="whiteitem SoulCore",
                  icon=False),
            entry("Amanamus_Gaze", "Amanamu's Gaze", (limited("1 Ancient Augment"),),
                  (("implicitMod", "Helmet: +1 to Level of all Minion Skills"),),
                  requires='Requires: <span class="colourDefault">Level 20</span>', link_class="whiteitem SoulCore",
                  icon=False),
        ],
    }


def _zh_entries() -> dict[str, list[str]]:
    """The Chinese entries by English slug: Chinese name, properties and effect text."""
    out: dict[str, str] = {}
    for slug, (_, zh, *_rest) in ITEMS.items():
        if slug in NO_CHINESE:
            continue
        props = [stack("堆疊數量")]
        if slug == "Greater_Chaos_Orb":
            props.append(min_level(35, "最小詞綴等級"))
        if slug == "Amanamus_Gaze":
            props = [limited("1 遠古增幅", "限制")]
        lines = (("explicitMod", f"{zh}的效果"),)
        if slug == "Omen_of_Whittling":
            lines = (("explicitMod", "此物品在你的背包裡啟動時，你的下一個<br/>混沌石會移除最低等級的詞綴"),)
        if slug == "Desert_Rune":
            lines = (("implicitMod", "軍用武器: 附加7至11火焰傷害"), ("implicitMod", "護甲: +14%火焰抗性"))
        out[slug] = entry(slug, zh, tuple(props), lines)
    return out


def site_pages() -> dict[str, str]:
    """{url: html} for every page the collector reads."""
    spec = load_spec()
    en, zh = _en_entries(), _zh_entries()
    pages: dict[str, str] = {}

    def put(slug: str, html: str, lang: str = "en") -> None:
        pages[spec.resolve_url(slug, lang)] = html

    junk = pane("Junk", "Junk", [entry("Mystery_Leaguestone", "Mystery Leaguestone")])
    put("Stackable_Currency", listing(pane("StackableCurrencyItem", "Stackable Currency Item", en["currency"]),
                                      pane("Essence", "Essence", en["essence"]), junk,
                                      pane("SplinterItem", "Splinter Item", en["splinter"]),
                                      pane("CatalystItem", "Catalyst Item", en["catalyst"])))
    put("Omen", listing(pane("OmenItem", "Omen Item", en["omen"]),
                        pane("OmenRef", "Omen Ref", [entry("Chaos_Orb", "Chaos Orb")])))
    put("Augment", listing(pane("AugmentItem", "Augment Item", en["augment"]),
                           pane("AugmentRef", "Augment Ref", [entry("Exalted_Orb", "Exalted Orb")])))
    stackable = [s for s in ITEMS if s not in ("Omen_of_Whittling", "Omen_of_Greater_Exaltation",
                                               "Omen_of_Dextral_Crystallisation", "Desert_Rune", "Amanamus_Gaze")]
    put("Stackable_Currency", listing(pane("可堆疊通貨物品", "可堆疊通貨 物品", [zh[s] for s in stackable if s in zh]),
                                      pane("精髓", "精髓", [zh["Runic_Alloy"]])), "zh-tw")
    put("Omen", listing(pane("預兆物品", "預兆 物品", [zh[s] for s in ITEMS if s.startswith("Omen_")])), "zh-tw")
    put("Augment", listing(pane("增幅物品", "增幅 物品", [zh["Desert_Rune"], zh["Amanamus_Gaze"]])), "zh-tw")
    for slug, (name, _, drop, item_class, tags, kind) in ITEMS.items():
        fields = {"Currency Exchange": "160 Gold", "DropLevel": str(drop), "BaseType": name, "Class": item_class,
                  "Tags": tags, "Type": f"Metadata/Items/Currency/{kind}"}
        if not tags:
            del fields["Tags"]
        put(slug, table_page(fields) if slug in TABLE_LAYOUT else card_page(fields))
    return pages


class CurrencySite:
    """A fetcher over the synthetic site that counts its requests; an unknown page is a 404."""

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


def currency_spec(**expect) -> Spec:
    """The real catalog with minimums this small site meets (or the ones given)."""
    raw = copy.deepcopy(load_spec().raw)
    raw["sources"]["currency"]["expect_min"] = {
        "records": 10, "categories": {"currency": 5, "essence": 2, "splinter": 1, "catalyst": 1, "omen": 2,
                                      "augment": 2},
        "zh_ratio": 0.9, "detail_ratio": 0.9, **expect}
    return Spec(raw)


def write_currency_data(base: Path, cache_dir: Path) -> list[dict]:
    """Collect the synthetic site and write data/currency/currency.jsonl under `base`."""
    from src.scrapers import collect_currency
    spec = currency_spec()
    records, _ = collect_currency.collect(spec, fetch=CurrencySite(), cache_dir=cache_dir)
    collect_currency.write(spec, base, records)
    return records
