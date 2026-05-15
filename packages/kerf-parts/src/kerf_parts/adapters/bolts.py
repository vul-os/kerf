"""BOLTS adapter — SCAFFOLD (fetch wired, conversion is a documented TODO).

BOLTS (https://github.com/boltsparts/BOLTS, LGPL) is a library of
*parametric* standard mechanical parts (ISO/DIN/EN bolts, nuts, washers,
profiles...). Each "class" is described by YAML/`.blt` collection files plus
parametric backends (FreeCAD `.py`, OpenSCAD `.scad`). Faithfully turning
those into Kerf parts means evaluating the parameter tables to enumerate
concrete sizes — that is a sizeable piece of work, so it is intentionally
left as a TODO. The fetch IS fully wired (the manifest entry clones the
repo into the cache), and this adapter implements the registry interface so
the pipeline runs end to end (it just yields zero parts today).

WHAT IS REAL:  manifest entry + fetch into .parts-cache/bolts/.
WHAT IS TODO:  parse blt/YAML collections, expand parameter tables into
               concrete .part rows (one per standard size), and link the
               FreeCAD parametric backend via kerf_imports' FreeCAD path.
"""
from __future__ import annotations

from pathlib import Path

from ..manifest import Source
from ..model import KerfPart

# Where BOLTS keeps its collection definitions, for the future implementer.
_COLLECTION_GLOBS = ("data/**/*.blt", "data/**/*.yaml")


def discover_collections(src_dir) -> list[Path]:
    """Locate BOLTS collection definition files (used by tests + future impl)."""
    src = Path(src_dir)
    found: list[Path] = []
    for pattern in _COLLECTION_GLOBS:
        found.extend(sorted(src.glob(pattern)))
    return found


def adapt(source: Source, src_dir) -> list[KerfPart]:
    """SCAFFOLD: returns []. See module docstring for the conversion TODO."""
    # Intentionally a no-op conversion. Kept as a clean seam: a future
    # implementer iterates discover_collections(src_dir), expands parameter
    # tables, and appends KerfPart(category="mechanical/fastener", ...).
    return []
