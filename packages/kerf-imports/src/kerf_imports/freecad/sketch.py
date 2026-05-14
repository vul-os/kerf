"""
sketch.py — T3 Sketch translator: FreeCAD Sketcher → Kerf .sketch JSON.

Usage::

    from kerf_imports.freecad.sketch import translate_sketch

    payload = translate_sketch(obj)   # obj: FCStdObject of type Sketcher::SketchObject
    # payload["entities"]   — list of geometry entities
    # payload["constraints"] — list of constraint dicts
    # payload["warnings"]   — list of warning strings (dropped / degraded constraints)

The returned dict is the Kerf .sketch payload (ready to be JSON-serialised and
inserted into the DB as file content).

Constraint numeric Type mapping sourced from:
  https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Sketcher/App/Constraint.h
"""
from __future__ import annotations

import logging
import math
from typing import Any

from .types import FCStdObject

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FreeCAD Sketcher constraint numeric enum → Kerf type
# ---------------------------------------------------------------------------
# Values taken directly from Sketcher/App/Constraint.h (stable since 0.17).
#
# Each entry: (fc_type_int, kerf_type_str | None, notes)
# None = drop with warning.

_CONSTRAINT_TYPE_MAP: dict[int, str | None] = {
    1:  "coincident",       # Coincident
    2:  "h",                # Horizontal
    3:  "v",                # Vertical
    4:  "parallel",         # Parallel
    5:  "tangent",          # Tangent
    6:  "distance",         # Distance
    7:  "distance_x",       # DistanceX
    8:  "distance_y",       # DistanceY
    9:  "angle",            # Angle
    10: "perpendicular",    # Perpendicular
    11: "radius",           # Radius
    12: "equal",            # Equal  (branch by entity type in _translate_constraint)
    13: "point_on_object",  # PointOnObject
    14: "symmetric",        # Symmetric
    15: None,               # InternalAlignment — FreeCAD-internal, drop with warning
    16: None,               # SnellsLaw — refraction, out of Kerf vocabulary
    17: "block",            # Block
    18: "diameter",         # Diameter
    19: None,               # Weight — B-spline weight, out of Kerf v1
}

# Human-readable names for warnings
_FC_TYPE_NAMES: dict[int, str] = {
    1: "Coincident",
    2: "Horizontal",
    3: "Vertical",
    4: "Parallel",
    5: "Tangent",
    6: "Distance",
    7: "DistanceX",
    8: "DistanceY",
    9: "Angle",
    10: "Perpendicular",
    11: "Radius",
    12: "Equal",
    13: "PointOnObject",
    14: "Symmetric",
    15: "InternalAlignment",
    16: "SnellsLaw",
    17: "Block",
    18: "Diameter",
    19: "Weight",
}

# Constraint types that are dropped with an explicit warning.
_DROP_WITH_WARNING: frozenset[int] = frozenset({15, 16, 19})

# Geometry type identifiers from FreeCAD's Part::GeomLineSegment etc.
_GEOM_LINE = "Part::GeomLineSegment"
_GEOM_ARC = "Part::GeomArcOfCircle"
_GEOM_CIRCLE = "Part::GeomCircle"
_GEOM_POINT = "Part::GeomPoint"
_GEOM_ELLIPSE = "Part::GeomEllipse"
_GEOM_ARC_ELLIPSE = "Part::GeomArcOfEllipse"
_GEOM_BSPLINE = "Part::GeomBSplineCurve"
_GEOM_PARABOLA = "Part::GeomArcOfParabola"
_GEOM_HYPERBOLA = "Part::GeomArcOfHyperbola"

# External-geometry index threshold: indices < -3 are external-geometry refs
# in FreeCAD (indices -1, -2 are the axes; < -3 are user-added external edges).
_EXTERNAL_GEO_THRESHOLD = -3


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def translate_sketch(obj: FCStdObject) -> dict[str, Any]:
    """
    Translate a ``Sketcher::SketchObject`` FCStdObject into a Kerf ``.sketch`` JSON dict.

    Parameters
    ----------
    obj :
        An :class:`~kerf_imports.freecad.types.FCStdObject` with
        ``type == "Sketcher::SketchObject"``.  Must have ``Geometry`` and
        ``Constraints`` properties (as parsed by ``property_parsers.py``).

    Returns
    -------
    dict
        Kerf ``.sketch`` payload with keys:
        ``entities``    — list of entity dicts
        ``constraints`` — list of constraint dicts
        ``warnings``    — list of human-readable warning strings
        ``plane``       — sketch plane metadata (best-effort from Attachment props)
        ``freecad_ref`` — provenance ``{ "name": obj.name, "label": obj.label }``
    """
    warnings: list[str] = []

    # ── Geometry entities ─────────────────────────────────────────────────────
    raw_geom: list[dict] = obj.properties.get("Geometry") or []
    entities = _translate_geometry(raw_geom, warnings)

    # ── Constraints ──────────────────────────────────────────────────────────
    raw_constraints: list[dict] = obj.properties.get("Constraints") or []
    constraints = _translate_constraints(raw_constraints, raw_geom, entities, warnings)

    # ── Plane ─────────────────────────────────────────────────────────────────
    plane = _extract_plane(obj)

    return {
        "entities": entities,
        "constraints": constraints,
        "plane": plane,
        "warnings": warnings,
        "freecad_ref": {
            "name": obj.name,
            "label": obj.label,
            "type": obj.type,
        },
    }


# ---------------------------------------------------------------------------
# Geometry translation
# ---------------------------------------------------------------------------

def _translate_geometry(
    raw_geom: list[dict],
    warnings: list[str],
) -> list[dict]:
    """Translate a list of FreeCAD geometry primitives to Kerf entities."""
    entities: list[dict] = []
    for idx, g in enumerate(raw_geom):
        ent = _translate_geom_entry(idx, g, warnings)
        if ent is not None:
            entities.append(ent)
    return entities


def _translate_geom_entry(
    idx: int,
    g: dict,
    warnings: list[str],
) -> dict | None:
    """Translate one geometry entry.  Returns None only for truly unknown types."""
    gtype = g.get("type", "")
    construction = g.get("construction", False)
    if isinstance(construction, str):
        construction = construction.lower() in ("true", "1")

    ent: dict[str, Any] = {
        "id": f"g{idx}",
        "fc_index": idx,
    }
    if construction:
        ent["construction"] = True

    if gtype == _GEOM_LINE:
        ent["type"] = "line"
        start = g.get("Start", {})
        end = g.get("End", {})
        ent["start"] = _vec2(start)
        ent["end"] = _vec2(end)

    elif gtype == _GEOM_ARC:
        ent["type"] = "arc"
        center = g.get("Center", {})
        ent["center"] = _vec2(center)
        ent["radius"] = float(g.get("Radius", {}).get("value", 0) if isinstance(g.get("Radius"), dict) else g.get("Radius", 0) or 0)
        ent["start_angle"] = math.degrees(float(g.get("StartAngle", {}).get("value", 0) if isinstance(g.get("StartAngle"), dict) else g.get("StartAngle", 0) or 0))
        ent["end_angle"] = math.degrees(float(g.get("EndAngle", {}).get("value", 0) if isinstance(g.get("EndAngle"), dict) else g.get("EndAngle", 0) or 0))

    elif gtype == _GEOM_CIRCLE:
        ent["type"] = "circle"
        center = g.get("Center", {})
        ent["center"] = _vec2(center)
        ent["radius"] = float(g.get("Radius", {}).get("value", 0) if isinstance(g.get("Radius"), dict) else g.get("Radius", 0) or 0)

    elif gtype == _GEOM_POINT:
        ent["type"] = "point"
        loc = g.get("Pos", g.get("Location", {}))
        ent["point"] = _vec2(loc)

    elif gtype in (_GEOM_ELLIPSE, _GEOM_ARC_ELLIPSE):
        # Ellipses / arcs-of-ellipse: mark as construction with a warning.
        ent["type"] = "ellipse"
        ent["construction"] = True
        center = g.get("Center", {})
        ent["center"] = _vec2(center)
        warnings.append(
            f"geometry #{idx} (type={gtype!r}): ellipses are imported as "
            "construction-only in Kerf v1 — B-spline/ellipse internal "
            "alignments are not representable."
        )

    elif gtype in (_GEOM_BSPLINE,):
        ent["type"] = "bspline"
        ent["construction"] = True
        warnings.append(
            f"geometry #{idx} (type={gtype!r}): B-spline curves are imported "
            "as construction-only in Kerf v1."
        )

    elif gtype in (_GEOM_PARABOLA, _GEOM_HYPERBOLA):
        ent["type"] = "conic"
        ent["construction"] = True
        warnings.append(
            f"geometry #{idx} (type={gtype!r}): conic arc imported as "
            "construction-only in Kerf v1."
        )

    else:
        # Unknown geometry type — emit as a construction point with a warning.
        ent["type"] = "unknown"
        ent["construction"] = True
        warnings.append(
            f"geometry #{idx}: unrecognised geometry type {gtype!r} — "
            "emitted as construction placeholder."
        )

    return ent


def _vec2(d: dict | None) -> dict[str, float]:
    """Extract a 2-D {x, y} dict from a FreeCAD vector dict (drops z)."""
    if not d:
        return {"x": 0.0, "y": 0.0}
    return {
        "x": float(d.get("x", 0) or 0),
        "y": float(d.get("y", 0) or 0),
    }


# ---------------------------------------------------------------------------
# Constraint translation
# ---------------------------------------------------------------------------

def _translate_constraints(
    raw: list[dict],
    raw_geom: list[dict],
    entities: list[dict],
    warnings: list[str],
) -> list[dict]:
    """Translate FreeCAD constraint list to Kerf constraint list."""
    result: list[dict] = []
    for idx, c in enumerate(raw):
        translated = _translate_constraint(idx, c, raw_geom, entities, warnings)
        if translated is not None:
            result.append(translated)
    return result


def _translate_constraint(
    idx: int,
    c: dict,
    raw_geom: list[dict],
    entities: list[dict],
    warnings: list[str],
) -> dict | None:
    """
    Translate one FreeCAD constraint dict.

    Returns a Kerf constraint dict, or None if the constraint is dropped.
    """
    fc_type: int = int(c.get("Type", -1))
    name: str = c.get("Name", "") or f"c{idx}"
    first: int = int(c.get("First", -1))
    second: int = int(c.get("Second", -1))
    third: int = int(c.get("Third", -1))
    first_pos: int = int(c.get("FirstPos", 0))
    second_pos: int = int(c.get("SecondPos", 0))
    value: float | None = c.get("Value")
    if value is not None:
        value = float(value)

    # -------------------------------------------------------------------
    # Check for drop-with-warning types first
    # -------------------------------------------------------------------
    if fc_type in _DROP_WITH_WARNING:
        type_name = _FC_TYPE_NAMES.get(fc_type, str(fc_type))
        _reason = {
            15: "FreeCAD-internal B-spline/ellipse alignment (not in Kerf vocabulary)",
            16: "Snell's-Law refraction constraint (not in Kerf vocabulary)",
            19: "B-spline weight (not in Kerf v1 sketch)",
        }.get(fc_type, "unsupported constraint type")
        warnings.append(
            f"sketch constraint #{idx} ({name!r}, type={type_name}): "
            f"dropped — {_reason}."
        )
        return None

    kerf_type = _CONSTRAINT_TYPE_MAP.get(fc_type)
    if kerf_type is None:
        type_name = _FC_TYPE_NAMES.get(fc_type, str(fc_type))
        warnings.append(
            f"sketch constraint #{idx} ({name!r}, type={type_name} [{fc_type}]): "
            "unknown constraint type — dropped."
        )
        return None

    # -------------------------------------------------------------------
    # Check for external-geometry references
    # -------------------------------------------------------------------
    if first < _EXTERNAL_GEO_THRESHOLD or second < _EXTERNAL_GEO_THRESHOLD:
        warnings.append(
            f"sketch constraint #{idx} ({name!r}): references external geometry "
            "(index < -3) — dropped; Kerf v1 does not support in-sketch "
            "references to external body edges."
        )
        return None

    # -------------------------------------------------------------------
    # Build the base constraint dict
    # -------------------------------------------------------------------
    kc: dict[str, Any] = {
        "id": f"c{idx}",
        "type": kerf_type,
    }
    if name and name != f"c{idx}":
        kc["fc_name"] = name

    # -------------------------------------------------------------------
    # Per-type enrichment
    # -------------------------------------------------------------------

    if fc_type == 1:  # Coincident
        kc["first"] = _entity_ref(first, first_pos)
        kc["second"] = _entity_ref(second, second_pos)

    elif fc_type in (2, 3):  # Horizontal / Vertical
        if second >= 0:
            # Point-pair form: H=0 distance on y (or x for V) between two pts
            if fc_type == 2:
                kc["type"] = "distance_y"
                kc["value"] = 0.0
            else:
                kc["type"] = "distance_x"
                kc["value"] = 0.0
            kc["first"] = _entity_ref(first, first_pos)
            kc["second"] = _entity_ref(second, second_pos)
        else:
            # Line form
            kc["first"] = _entity_ref(first, first_pos)

    elif fc_type == 4:  # Parallel
        kc["first"] = _entity_ref(first, 0)
        kc["second"] = _entity_ref(second, 0)

    elif fc_type == 5:  # Tangent
        kc["first"] = _entity_ref(first, first_pos)
        kc["second"] = _entity_ref(second, second_pos)

    elif fc_type == 6:  # Distance
        kc["first"] = _entity_ref(first, first_pos)
        if second >= 0:
            kc["second"] = _entity_ref(second, second_pos)
        if value is not None:
            kc["value"] = value

    elif fc_type in (7, 8):  # DistanceX / DistanceY
        kc["first"] = _entity_ref(first, first_pos)
        if second >= 0:
            kc["second"] = _entity_ref(second, second_pos)
        if value is not None:
            kc["value"] = value

    elif fc_type == 9:  # Angle
        kc["first"] = _entity_ref(first, first_pos)
        if second >= 0:
            kc["second"] = _entity_ref(second, second_pos)
        if value is not None:
            kc["value"] = math.degrees(value)  # FreeCAD stores in radians

    elif fc_type == 10:  # Perpendicular
        kc["first"] = _entity_ref(first, first_pos)
        kc["second"] = _entity_ref(second, second_pos)

    elif fc_type == 11:  # Radius
        kc["first"] = _entity_ref(first, 0)
        if value is not None:
            kc["value"] = value

    elif fc_type == 12:  # Equal
        # Branch on entity type to choose equal_length vs equal_radius
        first_gtype = _geom_type_at(first, raw_geom)
        if first_gtype in (_GEOM_CIRCLE, _GEOM_ARC):
            kc["type"] = "equal_radius"
        else:
            kc["type"] = "equal_length"
        kc["first"] = _entity_ref(first, 0)
        kc["second"] = _entity_ref(second, 0)

    elif fc_type == 13:  # PointOnObject
        # Branch on host type: point_on_line vs point_on_arc
        second_gtype = _geom_type_at(second, raw_geom)
        if second_gtype in (_GEOM_CIRCLE, _GEOM_ARC):
            kc["type"] = "point_on_arc"
        else:
            kc["type"] = "point_on_line"
        kc["first"] = _entity_ref(first, first_pos)
        kc["second"] = _entity_ref(second, 0)

    elif fc_type == 14:  # Symmetric
        kc["first"] = _entity_ref(first, first_pos)
        kc["second"] = _entity_ref(second, second_pos)
        if third >= 0:
            kc["axis"] = _entity_ref(third, 0)

    elif fc_type == 17:  # Block
        kc["first"] = _entity_ref(first, 0)
        # Also emit coordinate constraints at the solved value if we have them.
        # (We don't have solved values at parse time, so we emit block only.)

    elif fc_type == 18:  # Diameter
        kc["first"] = _entity_ref(first, 0)
        if value is not None:
            kc["value"] = value

    return kc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity_ref(geo_index: int, vertex_pos: int) -> dict[str, Any]:
    """
    Build a Kerf entity reference dict.

    ``geo_index`` is the FreeCAD geometry index (0-based).
    ``vertex_pos`` encodes which vertex: 0 = edge/full, 1 = start, 2 = end, 3 = center.
    """
    ref: dict[str, Any] = {"entity_id": f"g{geo_index}"}
    pos_map = {1: "start", 2: "end", 3: "center"}
    if vertex_pos in pos_map:
        ref["vertex"] = pos_map[vertex_pos]
    return ref


def _geom_type_at(geo_index: int, raw_geom: list[dict]) -> str:
    """Return the FreeCAD geometry type string at the given index, or '' if out of range."""
    if 0 <= geo_index < len(raw_geom):
        return raw_geom[geo_index].get("type", "")
    return ""


def _extract_plane(obj: FCStdObject) -> dict[str, Any]:
    """
    Best-effort extraction of the sketch attachment / placement as a plane dict.

    FreeCAD stores the attachment mode in the Attachment properties; the
    Placement property carries the actual transform.  We capture the raw
    Placement for provenance; resolving it to a Kerf face-anchored plane
    requires the importing body's geometry (deferred to T4/T6).
    """
    plane: dict[str, Any] = {"type": "world_xy"}

    placement = obj.properties.get("Placement")
    if placement and isinstance(placement, dict):
        plane["freecad_placement"] = placement

    # AttachmentOffset, MapMode etc. — capture verbatim
    for key in ("MapMode", "MapPathParameter", "MapReversed", "AttachmentOffset"):
        val = obj.properties.get(key)
        if val is not None:
            plane[f"freecad_{key.lower()}"] = val

    return plane
