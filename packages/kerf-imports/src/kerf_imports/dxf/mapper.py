"""
mapper.py — DXF entity model → Kerf .sketch / .drawing (T-6).

Maps a :class:`~kerf_imports.dxf.entities.DxfDocument` (produced by the
T-5 reader) onto Kerf's canonical JSON schemas:

``.sketch`` (Geom2 / closed-loop representation)
-------------------------------------------------
Schema mirrors the FreeCAD sketch translator output::

    {
      "version": 1,
      "entities": [
        {"id": "e0", "type": "line", "start": {"x": 0, "y": 0}, "end": {"x": 10, "y": 0}},
        {"id": "e1", "type": "circle", "center": {"x": 5, "y": 5}, "radius": 3.0},
        {"id": "e2", "type": "arc", "center": ..., "radius": ...,
         "start_angle": 0.0, "end_angle": 90.0},
        {"id": "e3", "type": "polyline", "points": [[x,y], ...], "closed": false},
        ...
      ],
      "constraints": [],
      "plane": {"type": "world_xy"},
      "warnings": [...],
      "dxf_ref": {"units": "mm", "layers": [...]}
    }

``.drawing`` (annotations / sheet layout)
------------------------------------------
Entities that look like text labels, or that live on annotation layers, are
mapped to a minimal ``.drawing`` payload following the TechDraw translator::

    {
      "sheets": [
        {
          "id": "sh-0",
          "frame": {"size": "A3", "orientation": "landscape", ...},
          "views": [],
          "dimensions": [],
          "annotations": [
            {"id": "a0", "type": "text", "x": ..., "y": ..., "value": "...", "height": ...}
          ],
          "centerlines": [],
          "breaks": [],
          "symbols": []
        }
      ],
      "warnings": [...],
      "dxf_ref": {"units": "mm"}
    }

Heuristic layer-based routing
------------------------------
Entities are routed to ``.sketch`` or ``.drawing`` based on their layer:
  - Layers whose lowercase name contains any of the ANNOTATION_KEYWORDS
    (``text``, ``dim``, ``anno``, ``note``, ``label``, ``title``) are
    treated as annotation layers → ``.drawing`` annotations.
  - TEXT/MTEXT entities always go to ``.drawing`` annotations regardless
    of layer.
  - Everything else goes to ``.sketch``.

Public API::

    from kerf_imports.dxf.mapper import dxf_to_sketch, dxf_to_drawing, dxf_to_both
"""
from __future__ import annotations

import math
from typing import Any

from kerf_imports.dxf.entities import (
    DxfArc,
    DxfCircle,
    DxfDocument,
    DxfInsert,
    DxfLine,
    DxfLwPolyline,
    DxfPolyline,
    DxfText,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Layer-name substrings that indicate annotation content
_ANNOTATION_KEYWORDS = frozenset({"text", "dim", "anno", "note", "label", "title"})

_SKETCH_VERSION = 1


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def dxf_to_sketch(doc: DxfDocument, expand_inserts: bool = True) -> dict[str, Any]:
    """
    Map a :class:`DxfDocument` to a Kerf ``.sketch`` payload.

    Only geometry entities (LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC) and
    block INSERT references are included.  TEXT entities are excluded (use
    :func:`dxf_to_drawing` for those).

    Parameters
    ----------
    doc:
        Parsed DXF document.
    expand_inserts:
        When True (default) INSERT references are expanded into their
        constituent primitives.  When False, INSERT entities are emitted
        as a single ``{"type": "insert", ...}`` entity for the caller to
        handle.

    Returns
    -------
    dict
        Kerf ``.sketch`` JSON payload.
    """
    warnings: list[str] = list(doc.warnings)
    entities_out: list[dict[str, Any]] = []
    layers_seen: set[str] = set()

    source = doc.expand_inserts() if expand_inserts else doc.entities

    idx = 0
    for ent in source:
        layer = getattr(ent, "layer", "0")
        layers_seen.add(layer)

        if _is_annotation_layer(layer):
            continue  # annotation layers go to .drawing

        if isinstance(ent, DxfText):
            continue  # TEXT always → .drawing

        kerf_ent = _entity_to_sketch(ent, idx, warnings)
        if kerf_ent is not None:
            entities_out.append(kerf_ent)
            idx += 1

    return {
        "version": _SKETCH_VERSION,
        "entities": entities_out,
        "constraints": [],
        "plane": {"type": "world_xy"},
        "warnings": warnings,
        "dxf_ref": {
            "units": doc.units,
            "layers": sorted(layers_seen),
        },
    }


def dxf_to_drawing(doc: DxfDocument, expand_inserts: bool = True) -> dict[str, Any]:
    """
    Map a :class:`DxfDocument` to a Kerf ``.drawing`` payload.

    Currently maps:
      - TEXT/MTEXT entities → annotations
      - Entities on annotation layers → annotations (via bounding box)

    The sheet frame defaults to A3 landscape; size/orientation can be
    overridden by the caller after the fact.

    Returns
    -------
    dict
        Kerf ``.drawing`` JSON payload.
    """
    warnings: list[str] = list(doc.warnings)
    annotations: list[dict[str, Any]] = []

    source = doc.expand_inserts() if expand_inserts else doc.entities

    idx = 0
    for ent in source:
        if isinstance(ent, DxfText):
            annotations.append({
                "id": f"a{idx}",
                "type": "text",
                "x": ent.x,
                "y": ent.y,
                "value": ent.value,
                "height": ent.height,
                "rotation": ent.rotation,
                "layer": ent.layer,
            })
            idx += 1
            continue

        layer = getattr(ent, "layer", "0")
        if _is_annotation_layer(layer):
            # Emit geometry on annotation layers as a placeholder annotation
            bbox = _entity_bbox(ent)
            if bbox:
                cx = (bbox[0] + bbox[2]) / 2
                cy = (bbox[1] + bbox[3]) / 2
                annotations.append({
                    "id": f"a{idx}",
                    "type": "geometry_annotation",
                    "x": cx,
                    "y": cy,
                    "layer": layer,
                })
                idx += 1

    sheet: dict[str, Any] = {
        "id": "sh-0",
        "frame": {
            "size": "A3",
            "orientation": "landscape",
            "title": "",
            "scale_label": "1:1",
            "template": "default",
        },
        "views": [],
        "dimensions": [],
        "annotations": annotations,
        "centerlines": [],
        "breaks": [],
        "symbols": [],
    }

    return {
        "sheets": [sheet],
        "warnings": warnings,
        "dxf_ref": {"units": doc.units},
    }


def dxf_to_both(
    doc: DxfDocument,
    expand_inserts: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Convenience: return (sketch_payload, drawing_payload) in one call.

    Both payloads share warnings from the document.
    """
    return dxf_to_sketch(doc, expand_inserts), dxf_to_drawing(doc, expand_inserts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_annotation_layer(layer: str) -> bool:
    """Return True if the layer name looks like an annotation layer."""
    lower = layer.lower()
    return any(kw in lower for kw in _ANNOTATION_KEYWORDS)


def _entity_to_sketch(
    ent: object,
    idx: int,
    warnings: list[str],
) -> dict[str, Any] | None:
    """Convert one DXF entity to a Kerf sketch entity dict, or None to skip."""
    eid = f"e{idx}"

    if isinstance(ent, DxfLine):
        return {
            "id": eid,
            "type": "line",
            "start": {"x": ent.x1, "y": ent.y1},
            "end":   {"x": ent.x2, "y": ent.y2},
            "layer": ent.layer,
        }

    if isinstance(ent, DxfCircle):
        return {
            "id": eid,
            "type": "circle",
            "center": {"x": ent.cx, "y": ent.cy},
            "radius": ent.radius,
            "layer": ent.layer,
        }

    if isinstance(ent, DxfArc):
        return {
            "id": eid,
            "type": "arc",
            "center": {"x": ent.cx, "y": ent.cy},
            "radius": ent.radius,
            "start_angle": ent.start_angle,
            "end_angle": ent.end_angle,
            "layer": ent.layer,
        }

    if isinstance(ent, (DxfLwPolyline, DxfPolyline)):
        return {
            "id": eid,
            "type": "polyline",
            "points": ent.points,
            "closed": ent.closed,
            "layer": ent.layer,
        }

    if isinstance(ent, DxfInsert):
        # When not expanding inserts, emit as an insert placeholder
        return {
            "id": eid,
            "type": "insert",
            "block_name": ent.block_name,
            "position": {"x": ent.x, "y": ent.y},
            "x_scale": ent.x_scale,
            "y_scale": ent.y_scale,
            "rotation_deg": ent.rotation_deg,
            "layer": ent.layer,
        }

    # Unknown or unhandled type — emit with warning
    type_name = type(ent).__name__
    warnings.append(f"Unsupported entity type {type_name!r} at index {idx} — skipped")
    return None


def _entity_bbox(ent: object) -> tuple[float, float, float, float] | None:
    """Return (xmin, ymin, xmax, ymax) for supported entity types, or None."""
    if isinstance(ent, DxfLine):
        return (
            min(ent.x1, ent.x2), min(ent.y1, ent.y2),
            max(ent.x1, ent.x2), max(ent.y1, ent.y2),
        )
    if isinstance(ent, DxfCircle):
        return (
            ent.cx - ent.radius, ent.cy - ent.radius,
            ent.cx + ent.radius, ent.cy + ent.radius,
        )
    if isinstance(ent, DxfArc):
        return (
            ent.cx - ent.radius, ent.cy - ent.radius,
            ent.cx + ent.radius, ent.cy + ent.radius,
        )
    if isinstance(ent, (DxfLwPolyline, DxfPolyline)):
        if not ent.points:
            return None
        xs = [p[0] for p in ent.points]
        ys = [p[1] for p in ent.points]
        return min(xs), min(ys), max(xs), max(ys)
    return None


# ---------------------------------------------------------------------------
# Loop detection helper (exported for tests)
# ---------------------------------------------------------------------------

_TOL = 1e-6  # mm tolerance for endpoint coincidence


def find_closed_loops(sketch_payload: dict[str, Any]) -> list[list[str]]:
    """
    Find chains of sketch entities that form closed loops.

    A loop is a sequence of entity IDs where each entity's end-point
    coincides (within ``_TOL``) with the next entity's start-point, and the
    last entity's end-point coincides with the first entity's start-point.

    Only LINE and ARC entities are considered; CIRCLE entities are
    trivially closed loops on their own.

    Returns a list of loops, each loop being a list of entity IDs.
    The return order is arbitrary.  Entities that don't form a loop are
    not included.
    """
    entities = sketch_payload.get("entities", [])
    loops: list[list[str]] = []

    # Circles are trivially closed
    for e in entities:
        if e.get("type") == "circle":
            loops.append([e["id"]])

    # Build adjacency for lines and arcs
    def start_of(e: dict) -> tuple[float, float] | None:
        if e["type"] == "line":
            s = e["start"]
            return s["x"], s["y"]
        if e["type"] == "arc":
            c, r = e["center"], e["radius"]
            a = math.radians(e["start_angle"])
            return c["x"] + r * math.cos(a), c["y"] + r * math.sin(a)
        if e["type"] == "polyline":
            pts = e.get("points", [])
            if pts:
                return pts[0][0], pts[0][1]
        return None

    def end_of(e: dict) -> tuple[float, float] | None:
        if e["type"] == "line":
            en = e["end"]
            return en["x"], en["y"]
        if e["type"] == "arc":
            c, r = e["center"], e["radius"]
            a = math.radians(e["end_angle"])
            return c["x"] + r * math.cos(a), c["y"] + r * math.sin(a)
        if e["type"] == "polyline":
            pts = e.get("points", [])
            if pts:
                if e.get("closed"):
                    return pts[0][0], pts[0][1]
                return pts[-1][0], pts[-1][1]
        return None

    candidates = [e for e in entities if e.get("type") in ("line", "arc", "polyline")]

    # Greedy chain-finding (sufficient for axis-aligned + simple curved sketches)
    visited: set[str] = set()

    for start_ent in candidates:
        if start_ent["id"] in visited:
            continue
        chain = [start_ent]
        visited.add(start_ent["id"])
        current_end = end_of(start_ent)
        if current_end is None:
            continue

        changed = True
        while changed:
            changed = False
            for e in candidates:
                if e["id"] in visited:
                    continue
                e_start = start_of(e)
                if e_start is None:
                    continue
                if (abs(current_end[0] - e_start[0]) < _TOL and
                        abs(current_end[1] - e_start[1]) < _TOL):
                    chain.append(e)
                    visited.add(e["id"])
                    current_end = end_of(e)
                    changed = True
                    break

        # Check if closed
        chain_start = start_of(chain[0])
        if (chain_start is not None and current_end is not None and
                abs(current_end[0] - chain_start[0]) < _TOL and
                abs(current_end[1] - chain_start[1]) < _TOL and
                len(chain) >= 1):
            loops.append([e["id"] for e in chain])

    return loops
