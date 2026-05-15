"""
sites.py — IfcSite → .bim site metadata.

The .bim site block:
    {
        "name": "...",
        "latitude": <decimal degrees>,
        "longitude": <decimal degrees>,
        "elevation": <mm>
    }

IFC stores lat/lon as a tuple of (degrees, minutes, seconds[, millionths])
per RefLatitude / RefLongitude.  RefElevation is in project length units
(mm for our projects).
"""
from __future__ import annotations

from typing import Any


def _dms_to_decimal(dms) -> float:
    """Convert an IFC DMS tuple/list to decimal degrees."""
    if dms is None:
        return 0.0
    try:
        parts = list(dms)
        deg = float(parts[0]) if parts else 0.0
        mins = float(parts[1]) if len(parts) > 1 else 0.0
        secs = float(parts[2]) if len(parts) > 2 else 0.0
        micro = float(parts[3]) if len(parts) > 3 else 0.0
        sign = -1.0 if deg < 0 else 1.0
        return sign * (abs(deg) + mins / 60.0 + (secs + micro / 1_000_000.0) / 3600.0)
    except (TypeError, ValueError, IndexError):
        return 0.0


def translate_site(ifc_site) -> dict[str, Any]:
    """
    Translate one IfcSite entity into a .bim site dict.

    Only one site is meaningful per project; the caller should pass the
    first IfcSite it finds.
    """
    name = getattr(ifc_site, "Name", None) or "Site"

    lat = _dms_to_decimal(getattr(ifc_site, "RefLatitude", None))
    lon = _dms_to_decimal(getattr(ifc_site, "RefLongitude", None))
    elev = 0.0
    try:
        raw_elev = getattr(ifc_site, "RefElevation", None)
        if raw_elev is not None:
            elev = float(raw_elev)
    except (TypeError, ValueError):
        pass

    return {
        "name": str(name),
        "latitude": lat,
        "longitude": lon,
        "elevation": elev,
    }
