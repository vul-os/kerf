"""
levels.py — IfcBuildingStorey → .bim level node.

.bim level schema:
    { "name": "L1", "elevation": 0 }

Elevation is in the project length unit (mm for Kerf projects).
IFC BuildingStorey.Elevation is already in project units.
"""
from __future__ import annotations

from typing import Any


def translate_level(ifc_storey) -> dict[str, Any]:
    """
    Translate one IfcBuildingStorey into a .bim level dict.

    Returns a dict with:
        name        – the storey Name attribute (or a fallback)
        elevation   – float, in project length units (mm)

    The caller is expected to also record GlobalId → level_name mapping so
    that walls/slabs/spaces can resolve their level reference.
    """
    name = getattr(ifc_storey, "Name", None) or getattr(ifc_storey, "GlobalId", "L?")
    name = str(name)

    elevation = 0.0
    try:
        raw = getattr(ifc_storey, "Elevation", None)
        if raw is not None:
            elevation = float(raw)
    except (TypeError, ValueError):
        pass

    return {
        "name": name,
        "elevation": elevation,
    }
