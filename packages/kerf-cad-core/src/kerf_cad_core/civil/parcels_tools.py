"""
kerf_cad_core.civil.parcels_tools — LLM tool wrappers for parcel geometry
and lot-layout subdivision.

Registers two tools with the Kerf tool registry:

  parcel_polygon_stats  — Area, perimeter and centroid of a closed polygon
                          (shoelace formula; ASCE Manual 21 / BLM §6).

  parcel_subdivide      — Rectangular-grid lot-layout subdivision of a
                          parent parcel targeting a given lot area with
                          minimum frontage and setback constraints
                          (AASHTO Green Book 2018 §3 / BLM Manual §6).

All tools are pure-Python; no OCC dependency.
Inputs validated; errors returned as {ok: false, reason: ...} — never raises.

Units: metres or feet (caller's choice; module is unit-agnostic).
Author: imranparuk
"""
from __future__ import annotations

import json
from dataclasses import asdict

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.civil.parcels import (
    Parcel,
    SubdivisionSpec,
    polygon_area,
    polygon_centroid,
    polygon_perimeter,
    subdivide_parcel,
)


# ---------------------------------------------------------------------------
# Tool: parcel_polygon_stats
# ---------------------------------------------------------------------------

_stats_spec = ToolSpec(
    name="parcel_polygon_stats",
    description=(
        "Compute area, perimeter, and centroid of a closed 2-D polygon.\n"
        "\n"
        "The polygon is supplied as a list of [x, y] vertices (any unit — "
        "metres or feet).  The last vertex need not repeat the first; "
        "the polygon is automatically closed.\n"
        "\n"
        "Geometric formulas (ASCE Manual 21 / BLM Manual §6):\n"
        "  Area      : Shoelace (Gauss) formula — A = 0.5·|Σ(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)|\n"
        "  Centroid  : cx = (1/6A)·Σ(xᵢ+xᵢ₊₁)(xᵢ·yᵢ₊₁−xᵢ₊₁·yᵢ)\n"
        "  Perimeter : Σ Euclidean edge lengths\n"
        "\n"
        "Returns {ok, area, perimeter, centroid_x, centroid_y, orientation}.\n"
        "orientation = 'CCW' (positive area) or 'CW' (negative area).\n"
        "\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "boundary": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": (
                    "Closed polygon as a list of [x, y] vertex pairs, "
                    "e.g. [[0,0],[10,0],[10,5],[0,5]].  Minimum 3 vertices."
                ),
                "minItems": 3,
            },
        },
        "required": ["boundary"],
    },
)


@register(_stats_spec, write=False)
async def run_parcel_polygon_stats(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_boundary = a.get("boundary")
    if raw_boundary is None:
        return json.dumps({"ok": False, "reason": "boundary is required"})

    try:
        boundary: list[tuple[float, float]] = [
            (float(v[0]), float(v[1])) for v in raw_boundary
        ]
    except (TypeError, IndexError, ValueError) as exc:
        return json.dumps({"ok": False, "reason": f"boundary parse error: {exc}"})

    if len(boundary) < 3:
        return json.dumps({"ok": False, "reason": "boundary must have at least 3 vertices"})

    signed_area = polygon_area(boundary)
    area = abs(signed_area)
    perim = polygon_perimeter(boundary)
    cx, cy = polygon_centroid(boundary)

    return ok_payload({
        "ok": True,
        "area": round(area, 6),
        "perimeter": round(perim, 6),
        "centroid_x": round(cx, 6),
        "centroid_y": round(cy, 6),
        "orientation": "CCW" if signed_area >= 0 else "CW",
        "note": (
            "Area computed via Shoelace formula (ASCE Manual 21). "
            "Units match input vertices."
        ),
    })


# ---------------------------------------------------------------------------
# Tool: parcel_subdivide
# ---------------------------------------------------------------------------

_subdivide_spec = ToolSpec(
    name="parcel_subdivide",
    description=(
        "Subdivide a parent parcel into lots using a rectangular-grid layout.\n"
        "\n"
        "Design method (AASHTO Green Book 2018 §3 / BLM Manual §6 / ASCE Manual 21):\n"
        "  • Lot depth  = target_lot_area / minimum_frontage\n"
        "  • Lots arranged in a grid within the parent bounding box\n"
        "  • Front setback strip reserved along the access-road edge\n"
        "  • Side and rear setbacks applied per lot\n"
        "  • Lots whose centroid falls outside the parent polygon are dropped\n"
        "\n"
        "Returns {ok, n_lots, average_lot_area, waste_area, parcels[], honest_caveat}.\n"
        "Each parcel has {parcel_id, boundary[[x,y]...], area, perimeter, centroid}.\n"
        "\n"
        "Honest caveat: rectangular-grid only — irregular parent boundaries "
        "require a licensed surveyor for title-quality subdivision plats.\n"
        "\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "parent_boundary": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "Parent parcel polygon as [[x,y]...] vertices (≥ 3).",
                "minItems": 3,
            },
            "target_lot_area": {
                "type": "number",
                "description": "Target area per lot in m² or ft² (> 0).",
            },
            "minimum_frontage": {
                "type": "number",
                "description": "Minimum lot frontage along access road in same units as boundary (> 0).",
            },
            "access_road_polyline": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "Access road polyline [[x,y]...] (used for orientation hint).",
            },
            "setback_front": {
                "type": "number",
                "description": "Front setback from road edge in same units as boundary (≥ 0).",
            },
            "setback_side": {
                "type": "number",
                "description": "Side setback in same units as boundary (≥ 0).",
            },
            "setback_rear": {
                "type": "number",
                "description": "Rear setback in same units as boundary (≥ 0).",
            },
        },
        "required": [
            "parent_boundary",
            "target_lot_area",
            "minimum_frontage",
            "access_road_polyline",
            "setback_front",
            "setback_side",
            "setback_rear",
        ],
    },
)


@register(_subdivide_spec, write=False)
async def run_parcel_subdivide(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    def _parse_poly(key: str) -> list[tuple[float, float]] | None:
        raw = a.get(key)
        if raw is None:
            return None
        try:
            return [(float(v[0]), float(v[1])) for v in raw]
        except (TypeError, IndexError, ValueError):
            return None

    parent = _parse_poly("parent_boundary")
    if parent is None:
        return json.dumps({"ok": False, "reason": "parent_boundary is required and must be [[x,y]...]"})

    road = _parse_poly("access_road_polyline")
    if road is None:
        road = []

    try:
        target_lot_area = float(a["target_lot_area"])
        minimum_frontage = float(a["minimum_frontage"])
        setback_front = float(a["setback_front"])
        setback_side = float(a["setback_side"])
        setback_rear = float(a["setback_rear"])
    except (KeyError, TypeError, ValueError) as exc:
        return json.dumps({"ok": False, "reason": f"numeric parse error: {exc}"})

    spec = SubdivisionSpec(
        parent_boundary=parent,
        target_lot_area=target_lot_area,
        minimum_frontage=minimum_frontage,
        access_road_polyline=road,
        setback_front=setback_front,
        setback_side=setback_side,
        setback_rear=setback_rear,
    )

    report = subdivide_parcel(spec)

    parcels_out = []
    for p in report.parcels:
        parcels_out.append({
            "parcel_id": p.parcel_id,
            "boundary": [[x, y] for x, y in p.boundary],
            "area": p.area,
            "perimeter": p.perimeter,
            "centroid": list(p.centroid),
        })

    return ok_payload({
        "ok": True,
        "n_lots": report.n_lots,
        "average_lot_area": report.average_lot_area,
        "waste_area": report.waste_area,
        "honest_caveat": report.honest_caveat,
        "parcels": parcels_out,
    })
