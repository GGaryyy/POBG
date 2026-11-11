"""
spec.py — Load and query the poe2db source catalog (poe2db_sources.json).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

SPEC_PATH = Path(__file__).resolve().parent / "poe2db_sources.json"
REQUIRED_TOP_LEVEL = ("spec_version", "verified_at", "base_url", "languages", "url_patterns",
                      "shared_selectors", "sources", "fields", "traps")
GEM_KINDS = ("skill_gem", "spirit_gem", "support_gem")
PASSIVE_KINDS = ("passive_keystone", "passive_notable", "passive_ascendancy")
ITEM_KINDS = ("item_base", "item_unique")

# ---------------------------------------------------------------------------
# SPEC
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    """Thin, validated view over the catalog JSON."""

    raw: dict

    # -- languages / urls -------------------------------------------------
    @property
    def languages(self) -> dict[str, str]:
        return dict(self.raw["languages"])

    def lang_path(self, lang: str) -> str:
        try:
            return self.raw["languages"][lang]
        except KeyError as exc:
            raise ValueError(f"unknown language {lang!r}; known: {sorted(self.raw['languages'])}") from exc

    def resolve_url(self, slug: str, lang: str = "en") -> str:
        return self.raw["url_patterns"]["page"].format(
            base=self.raw["base_url"], lang_path=self.lang_path(lang), slug=slug
        )

    def subterms(self) -> dict[str, list[dict]]:
        """{glossary slug: [{en, zh_tw}]}: named kinds of a glossary term (Frenzy Charge under Charges)."""
        return {slug: terms for slug, terms in self.raw.get("keyword_subterms", {}).items() if not slug.startswith("_")}

    # -- sources / sections ----------------------------------------------
    def source(self, name: str) -> dict:
        try:
            return self.raw["sources"][name]
        except KeyError as exc:
            raise ValueError(f"unknown source {name!r}") from exc

    def source_for_kind(self, kind: str) -> tuple[str, dict]:
        for name, src in self.raw["sources"].items():
            if src.get("kind") == kind:
                return name, src
        raise ValueError(f"no source with kind {kind!r}")

    def section(self, source: str, section: str) -> dict:
        sections = self.source(source).get("sections", {})
        try:
            return sections[section]
        except KeyError as exc:
            raise ValueError(f"unknown section {section!r} in source {source!r}") from exc

    def section_ids(self, source: str, section: str) -> dict[str, str]:
        return dict(self.section(source, section).get("ids", {}))

    def expect_min(self, source: str, section: str) -> int:
        return int(self.section(source, section).get("expect_min", 0))

    # -- selectors ---------------------------------------------------------
    def selector(self, name: str, lang: str = "en") -> str:
        try:
            value = self.raw["shared_selectors"][name]
        except KeyError as exc:
            raise ValueError(f"unknown selector {name!r}") from exc
        if isinstance(value, str):
            return value.format(lang_path=self.lang_path(lang))
        return value

    # -- fields ------------------------------------------------------------
    def field(self, kind: str, field: str) -> dict | None:
        """Field metadata for a kind, falling back to its family ('gem' or 'passive')."""
        fields = self.raw["fields"]
        family = "gem" if kind in GEM_KINDS else "passive" if kind.startswith("passive") else None
        specific = fields.get(f"{kind}.{field}")
        if specific is not None or family is None:
            return specific
        return fields.get(f"{family}.{field}")


def load_spec(path: Path = SPEC_PATH) -> Spec:
    """Read, validate and wrap the catalog JSON. Raises ValueError naming the bad path."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"catalog spec not found: {path}")
    with path.open(encoding="utf-8") as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"catalog spec {path} is not valid JSON: {exc}") from exc
    _validate(raw)
    return Spec(raw)


def _validate(raw: dict) -> None:
    for key in REQUIRED_TOP_LEVEL:
        if key not in raw:
            raise ValueError(f"spec missing required key: {key}")
    if not raw["languages"] or not all(raw["languages"].values()):
        raise ValueError("spec.languages must map every language to a non-empty path")
    if "en" not in raw["languages"]:
        raise ValueError("spec.languages must include 'en'")
    if "page" not in raw["url_patterns"]:
        raise ValueError("spec.url_patterns.page is required")
    if not isinstance(raw["fields"], dict) or not isinstance(raw["sources"], dict):
        raise ValueError("spec.fields and spec.sources must be objects")
    for src_name, src in raw["sources"].items():
        for sec_name, sec in src.get("sections", {}).items():
            if not isinstance(sec, dict):
                continue
            ids = sec.get("ids")
            if ids is None:
                continue
            if "en" not in ids or not ids["en"]:
                raise ValueError(f"sources.{src_name}.sections.{sec_name}.ids.en is required")
            if not isinstance(sec.get("expect_min", 0), int):
                raise ValueError(f"sources.{src_name}.sections.{sec_name}.expect_min must be an int")
    for field_name, meta in raw["fields"].items():
        if meta.get("reliability") not in ("ok", "partial", "unreliable"):
            raise ValueError(f"fields.{field_name}.reliability must be ok|partial|unreliable")
