"""
openings.py — IfcOpeningElement (windows/doors) → .bim opening node.

IFC opening model
-----------------
Windows and doors are represented by two coupled entities:

  IfcWindow / IfcDoor
      The product element, with its own ObjectPlacement (host-relative) and
      Representation.  Carries Name, GlobalId, OverallWidth, OverallHeight,
      PredefinedType.

  IfcOpeningElement
      A void cut into the host wall.  The window/door fills this void.
      Related via IfcRelFillsElement:
          FillsVoids → [IfcRelFillsElement]
              RelatingOpeningElement → IfcOpeningElement
                  VoidsElements → [IfcRelVoidsElement]
                      RelatingBuildingElement → host wall

.bim opening schema
-------------------
{
    "kind": "window" | "door",          # from entity class
    "level": "L1",                      # resolved via host wall or direct containment
    "position": [x, y, z],             # mm, world-space origin of the element
    "width": 900,                       # mm  (OverallWidth or representation fallback)
    "height": 2100,                     # mm  (OverallHeight or representation fallback)
    "host_wall": "Wall Name",           # name of the containing wall (if resolvable)
    "name": "D-01",                     # element Name attribute
    "ifc_guid": "...",                  # GlobalId for round-trip reference
}

Placement chain note
--------------------
Windows/doors carry an ObjectPlacement that is host-relative (i.e.
RelativeTo points to the host wall's placement).
ifcopenshell.util.placement.get_local_placement() chains the full hierarchy
and returns the absolute 4×4 world matrix.

MEP distribution elements are handled in mep.py.
"""
from __future__ import annotations

from typing import Any

_FALLBACK_WIDTH = 900.0
_FALLBACK_HEIGHT = 2100.0

_DOOR_FALLBACK_HEIGHT = 2100.0
_DOOR_FALLBACK_WIDTH = 900.0
_WIN_FALLBACK_HEIGHT = 1200.0
_WIN_FALLBACK_WIDTH = 900.0


def _placement_origin(ifc_entity) -> tuple[float, float, float]:
    """Return (x, y, z) world-space origin via placement chain. (0,0,0) on failure."""
    try:
        from ifcopenshell.util.placement import get_local_placement  # type: ignore
        placement = getattr(ifc_entity, "ObjectPlacement", None)
        if placement is None:
            return (0.0, 0.0, 0.0)
        matrix = get_local_placement(placement)
        return (float(matrix[0, 3]), float(matrix[1, 3]), float(matrix[2, 3]))
    except Exception:
        return (0.0, 0.0, 0.0)


def _storey_name_for(ifc_element, level_guid_to_name: dict[str, str]) -> str:
    """Walk ContainedInStructure to find the parent storey name."""
    try:
        rels = getattr(ifc_element, "ContainedInStructure", None) or []
        for rel in rels:
            structure = getattr(rel, "RelatingStructure", None)
            if structure is None:
                continue
            ifc_type = getattr(structure, "is_a", lambda: "")()
            if ifc_type == "IfcBuildingStorey":
                gid = getattr(structure, "GlobalId", "")
                return level_guid_to_name.get(gid, getattr(structure, "Name", "") or "")
    except Exception:
        pass
    return ""


def _host_wall_name_for(ifc_element) -> str:
    """
    Walk FillsVoids → IfcRelFillsElement → RelatingOpeningElement →
    VoidsElements → IfcRelVoidsElement → RelatingBuildingElement to
    find the host wall name.
    """
    try:
        fills_voids = getattr(ifc_element, "FillsVoids", None) or []
        for rel_fills in fills_voids:
            opening = getattr(rel_fills, "RelatingOpeningElement", None)
            if opening is None:
                continue
            voids_rels = getattr(opening, "VoidsElements", None) or []
            for voids_rel in voids_rels:
                host = getattr(voids_rel, "RelatingBuildingElement", None)
                if host is None:
                    continue
                host_type = getattr(host, "is_a", lambda: "")()
                if "Wall" in host_type:
                    return str(getattr(host, "Name", "") or "")
    except Exception:
        pass
    return ""


def _get_opening_dimensions(ifc_element, warnings: list[str]) -> tuple[float, float]:
    """
    Extract width and height for a window or door.

    Strategy:
    1. OverallWidth / OverallHeight attributes (most IFC exporters set these).
    2. IfcExtrudedAreaSolid with IfcRectangleProfileDef in the Body rep.
    3. Fallback to category defaults with warning.
    """
    gid = getattr(ifc_element, "GlobalId", "?")
    name = getattr(ifc_element, "Name", None) or gid
    ifc_type = getattr(ifc_element, "is_a", lambda: "")()
    is_door = "Door" in ifc_type

    fw = _DOOR_FALLBACK_WIDTH if is_door else _WIN_FALLBACK_WIDTH
    fh = _DOOR_FALLBACK_HEIGHT if is_door else _WIN_FALLBACK_HEIGHT

    # Strategy 1: explicit overall dimensions
    w = getattr(ifc_element, "OverallWidth", None)
    h = getattr(ifc_element, "OverallHeight", None)
    if w is not None and h is not None:
        try:
            return float(w), float(h)
        except (TypeError, ValueError):
            pass

    # Strategy 2: read from extruded solid profile
    try:
        rep = getattr(ifc_element, "Representation", None)
        if rep is not None:
            for shape_rep in (getattr(rep, "Representations", None) or []):
                rep_id = getattr(shape_rep, "RepresentationIdentifier", "")
                if rep_id not in ("Body", ""):
                    continue
                for item in (getattr(shape_rep, "Items", None) or []):
                    item_type = getattr(item, "is_a", lambda: "")()
                    if item_type == "IfcExtrudedAreaSolid":
                        profile = getattr(item, "SweptArea", None)
                        if profile is not None:
                            pt = getattr(profile, "is_a", lambda: "")()
                            if pt == "IfcRectangleProfileDef":
                                xd = getattr(profile, "XDim", None)
                                yd = getattr(profile, "YDim", None)
                                depth = getattr(item, "Depth", None)
                                if xd and yd and depth:
                                    # XDim = width, Depth = height for most exporters
                                    return float(xd), float(depth)
    except Exception:
        pass

    warnings.append(
        f"{ifc_type} {name!r}: could not extract dimensions; "
        f"using defaults (width={fw}, height={fh})"
    )
    return fw, fh


def translate_opening(
    ifc_element,
    level_guid_to_name: dict[str, str],
    warnings: list[str],
) -> dict[str, Any]:
    """
    Translate one IfcWindow or IfcDoor into a .bim opening dict.

    Args:
        ifc_element:        The IFC window or door entity.
        level_guid_to_name: GlobalId → level name map.
        warnings:           Mutable list; non-fatal issues appended here.

    Returns:
        A dict matching the .bim opening JSON schema, or {} on hard failure.
    """
    ifc_type = getattr(ifc_element, "is_a", lambda: "")()
    if "Window" not in ifc_type and "Door" not in ifc_type:
        warnings.append(
            f"translate_opening called on non-opening entity {ifc_type!r} "
            f"(id={getattr(ifc_element, 'GlobalId', '?')}) — skipped"
        )
        return {}

    kind = "window" if "Window" in ifc_type else "door"
    gid = getattr(ifc_element, "GlobalId", "")
    name = str(getattr(ifc_element, "Name", None) or gid)

    position = _placement_origin(ifc_element)
    level_name = _storey_name_for(ifc_element, level_guid_to_name)
    host_wall = _host_wall_name_for(ifc_element)
    width, height = _get_opening_dimensions(ifc_element, warnings)

    return {
        "kind": kind,
        "level": level_name,
        "position": [round(position[0], 3), round(position[1], 3), round(position[2], 3)],
        "width": width,
        "height": height,
        "host_wall": host_wall,
        "name": name,
        "ifc_guid": gid,
    }
