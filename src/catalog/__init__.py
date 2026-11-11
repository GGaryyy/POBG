"""Source catalog: spec loader, probe and entity index.

Submodules are imported lazily so `python -m src.catalog.entity_index` does not import the
module twice (runpy warning) and `load_spec` stays cheap to import.
"""

from __future__ import annotations

from importlib import import_module

__all__ = ["EntityIndex", "Spec", "build_entity_index", "load_spec"]

_LOCATIONS = {
    "EntityIndex": "src.catalog.entity_index",
    "build_entity_index": "src.catalog.entity_index",
    "Spec": "src.catalog.spec",
    "load_spec": "src.catalog.spec",
}


def __getattr__(name: str):
    if name in _LOCATIONS:
        return getattr(import_module(_LOCATIONS[name]), name)
    raise AttributeError(f"module 'src.catalog' has no attribute {name!r}")
