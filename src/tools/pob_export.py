"""
pob_export.py — Path of Building build codes.

A PoB build code is the build's XML, zlib-compressed and base64-encoded with '-' and '_' in place
of '+' and '/'. PoB opens it from Import/Export → "Import from code". This module only builds and
reads codes; which names go in is decided (and verified) by build_tools.export_pob. Nothing here
writes files or touches the network.
"""

from __future__ import annotations

import base64
import binascii
import re
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

ROOT = "PathOfBuilding2"
TARGET_VERSION = "0_1"        # PoB's liveTargetVersion for PoE2 builds
MAX_LEVEL = 100
GEM_LEVEL = 20
SUPPORT_LEVEL = 1             # PoE2 support gems have no levels; PoB shows them as 1
GEM_QUALITY = 0
ATTRIBUTES = ("str", "dex", "int")   # PoB's AttributeOverride lists, in this order
RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)\s*(?:—|–|-)\s*(-?\d+(?:\.\d+)?)\)")   # "(80—89)" in modifier text
ITEM_SET_ID = "1"
CONFIG_SET_ID = "1"
ACTIVATED_SLOTS = ("Flask", "Charm")
NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
SKILL_SET_TITLE = "POBG"
MAX_CODE_LEN = 200_000        # decode_code refuses anything longer
MAX_XML_LEN = 2_000_000       # and anything that inflates past this


class BadCode(ValueError):
    """The text is not a PoB build code."""


# ---------------------------------------------------------------------------
# DATA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PobGem:
    name: str          # English name; PoB falls back to it when it does not know gem_id
    gem_id: str        # PoB gemId = the game's item type, e.g. Metadata/Items/Gems/SkillGemIceShot
    variant_id: str    # PoB variantId = the game id, e.g. IceShot
    support: bool = False
    level: int = GEM_LEVEL   # skill gems: the highest level the character can use; supports have none


@dataclass(frozen=True)
class PobSkillGroup:
    label: str
    gems: tuple[PobGem, ...]


@dataclass(frozen=True)
class PobItem:
    slot: str                      # PoB slot name, e.g. "Weapon 1", "Ring 2"
    rarity: str                    # NORMAL, RARE or UNIQUE
    name: str                      # unique name, or a plain label for a rare (PoB does not use it)
    base: str                      # base type name, which PoB looks the item up by
    implicits: tuple[str, ...] = ()
    explicits: tuple[str, ...] = ()


@dataclass
class PobBuild:
    title: str
    class_name: str
    class_id: int                  # PoB classInternalId (tree.json integerId)
    ascendancy_name: str | None
    ascendancy_id: str | None      # PoB ascendancyInternalId, e.g. Ranger1
    tree_version: str              # e.g. 0_5
    nodes: list[str] = field(default_factory=list)
    groups: list[PobSkillGroup] = field(default_factory=list)
    main_group: int = 1            # 1-based, as PoB counts
    notes: str = ""
    attributes: dict[str, list[str]] = field(default_factory=dict)   # "str"/"dex"/"int" -> attribute node ids
    level: int = 1                 # the level PoB's automatic mode works out (pob_level), or the one asked for
    auto_level: bool = True        # False keeps a level the caller asked for
    items: list[PobItem] = field(default_factory=list)
    config: list[str] = field(default_factory=list)   # PoB configuration options switched on (check boxes)


# ---------------------------------------------------------------------------
# FUNCTIONS
# ---------------------------------------------------------------------------


def build_xml(build: PobBuild) -> str:
    """The build as PoB's XML: Build, Tree and Skills sections, plus Notes when given. The
    character level is written (see pob_level); PoB's automatic mode stays on unless a level was
    asked for. Attribute passives get
    their attribute through Overrides, as PoB saves a choice made on its tree; PoB reads all three
    lists, so all three are written. Text PoB cannot hold in XML is dropped."""
    root = ET.Element(ROOT)
    ET.SubElement(root, "Build", {
        "level": str(build.level), "targetVersion": TARGET_VERSION, "className": build.class_name,
        "ascendClassName": build.ascendancy_name or "None", "mainSocketGroup": str(build.main_group),
        "characterLevelAutoMode": "true" if build.auto_level else "false", "viewMode": "TREE",
    })
    tree = ET.SubElement(root, "Tree", {"activeSpec": "1"})
    spec = ET.SubElement(tree, "Spec", {
        "title": xml_text(build.title), "treeVersion": build.tree_version, "classInternalId": str(build.class_id),
        "ascendancyInternalId": build.ascendancy_id or "", "secondaryAscendClassId": "0",
        "nodes": ",".join(build.nodes), "masteryEffects": "",
    })
    if any(build.attributes.values()):
        overrides = ET.SubElement(spec, "Overrides")
        ET.SubElement(overrides, "AttributeOverride",
                      {f"{key}Nodes": ",".join(build.attributes.get(key, [])) for key in ATTRIBUTES})
    skills = ET.SubElement(root, "Skills", {"activeSkillSet": "1", "defaultGemQuality": str(GEM_QUALITY)})
    skill_set = ET.SubElement(skills, "SkillSet", {"id": "1", "title": SKILL_SET_TITLE})
    for group in build.groups:
        skill = ET.SubElement(skill_set, "Skill", {
            "enabled": "true", "includeInFullDPS": "false", "label": xml_text(group.label),
            "mainActiveSkill": "1", "mainActiveSkillCalcs": "1",
        })
        for gem in group.gems:
            ET.SubElement(skill, "Gem", {
                "nameSpec": xml_text(gem.name), "gemId": gem.gem_id, "variantId": gem.variant_id,
                "level": str(SUPPORT_LEVEL if gem.support else gem.level), "quality": str(GEM_QUALITY), "enabled": "true",
                "enableGlobal1": "true", "enableGlobal2": "false", "count": "1",
            })
    if build.items:
        _items_section(root, build.items)
    if build.config:
        config = ET.SubElement(root, "Config", {"activeConfigSet": CONFIG_SET_ID})
        config_set = ET.SubElement(config, "ConfigSet", {"id": CONFIG_SET_ID, "title": "Default"})
        for name in build.config:
            ET.SubElement(config_set, "Input", {"name": name, "boolean": "true"})
    if build.notes:
        ET.SubElement(root, "Notes").text = xml_text(build.notes)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def item_text(item: PobItem) -> str:
    """An item as PoB writes it when it saves a build (Item.lua BuildRaw): rarity, name, base,
    the implicit count, then one modifier per line. A normal item has no separate name line."""
    implicits, explicits = _stat_lines(item.implicits), _stat_lines(item.explicits)
    head = [item.base] if item.rarity == "NORMAL" else [item.name, item.base]
    lines = [f"Rarity: {item.rarity}", *(" ".join(xml_text(line).split()) for line in head),
             f"Implicits: {len(implicits)}", *implicits, *explicits]
    return "\n".join(lines)


def _stat_lines(texts: tuple[str, ...]) -> list[str]:
    """One PoB line per stat: a modifier text with several stats is one line each."""
    lines = [xml_text(line).strip() for text in texts for line in text.split("\n")]
    return [line for line in lines if line]


def upper_value(text: str) -> str:
    """A modifier with every "(low—high)" range replaced by its upper end, as written."""
    return RANGE.sub(lambda m: m.group(2), text)


def _items_section(root: ET.Element, items: list[PobItem]) -> None:
    section = ET.SubElement(root, "Items", {"activeItemSet": ITEM_SET_ID, "useSecondWeaponSet": "false"})
    for item_id, item in enumerate(items, 1):
        ET.SubElement(section, "Item", {"id": str(item_id)}).text = item_text(item)
    item_set = ET.SubElement(section, "ItemSet", {"id": ITEM_SET_ID, "useSecondWeaponSet": "false"})
    for item_id, item in enumerate(items, 1):
        slot = {"name": item.slot, "itemId": str(item_id)}
        if item.slot.startswith(ACTIVATED_SLOTS):
            slot["active"] = "true"            # PoB applies a flask or charm only when its slot is switched on
        ET.SubElement(item_set, "Slot", slot)


def xml_text(value: str) -> str:
    """Text without the characters XML 1.0 cannot hold (control characters, lone surrogates)."""
    return NOT_XML.sub("", value)


def pob_level(points: int, acts: list[dict]) -> int:
    """The character level PoB's automatic mode sets for this many passive points
    (Build.lua EstimatePlayerProgress, without weapon-set points or the extra points a few
    ascendancy passives grant, which cannot be exported yet). PoB sets it after
    calculating, without calculating again, so a code that says level 1 shows level-1 numbers;
    writing this level keeps the first view right."""
    act = 0
    while True:
        level = min(max(points + 1 - acts[act]["quest_points"], acts[act]["level"]), MAX_LEVEL)
        if act == len(acts) - 1 or level <= acts[act + 1]["level"]:
            return level
        act += 1


def encode_code(xml_text: str) -> str:
    """XML → PoB build code."""
    return base64.urlsafe_b64encode(zlib.compress(xml_text.encode("utf-8"), 9)).decode("ascii")


def decode_code(code: str) -> str:
    """PoB build code → XML text. Raises BadCode for anything else."""
    text = "".join(str(code).split())
    if not text or len(text) > MAX_CODE_LEN:
        raise BadCode("not a build code (empty or too long)")
    inflater = zlib.decompressobj()
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        xml_bytes = inflater.decompress(raw, MAX_XML_LEN)
        xml_text = xml_bytes.decode("utf-8")
    except (binascii.Error, zlib.error, UnicodeDecodeError, ValueError) as exc:
        raise BadCode(f"not a build code ({type(exc).__name__})") from exc
    if inflater.unconsumed_tail:
        raise BadCode("the build code inflates past the size limit")
    if not inflater.eof:
        raise BadCode("the build code is cut off")
    return xml_text
