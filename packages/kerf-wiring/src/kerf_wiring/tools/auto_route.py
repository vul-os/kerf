"""
LLM tools: wiring_auto_route + wiring_check_clearance

wiring_auto_route
-----------------
Automatically route a cable/harness in 3D space from start to end, detouring
around AABB obstacles using a voxel A* search (Cheng-Quan 2001) with Catmull-Rom
path smoothing.

Input schema:
  {
    "start_point": [x, y, z],         # mm
    "end_point":   [x, y, z],         # mm
    "obstacles": [                    # optional
      {"min_pt": [x,y,z], "max_pt": [x,y,z], "name": "box1"},
      ...
    ],
    "cable_radius": 2.0,              # mm, default 2.0
    "voxel_size":   5.0               # mm, default 5.0
  }

Returns:
  ok_payload({
    "polyline": [[x,y,z], ...],
    "total_length": <float>,
    "bend_count": <int>,
    "collision_clearance_min": <float>
  })

wiring_check_clearance
----------------------
Compute clearance statistics for a previously-routed harness (or any supplied
polyline) against a set of AABB obstacles.  Also runs collision detection.

Input schema:
  {
    "polyline":    [[x,y,z], ...],     # route waypoints, mm
    "obstacles":   [{"min_pt":..., "max_pt":..., "name":...}, ...],
    "cable_radius": 2.0,              # mm, default 2.0
    "n_samples":   100                # sample count for clearance histogram, default 100
  }

Returns:
  ok_payload({
    "clearance": {
      "min": ..., "mean": ...,
      "percentile_10": ..., "percentile_25": ..., "percentile_50": ...,
      "percentile_75": ..., "percentile_90": ..., "percentile_95": ...,
      "max": ..., "n_samples": ...
    },
    "collisions": [
      {"segment_index":..., "point":[x,y,z], "obstacle_name":..., "penetration_depth":...},
      ...
    ],
    "collision_count": <int>
  })
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_wiring._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore

from kerf_wiring.auto_routing_3d import (
    Body,
    Route,
    auto_route_harness,
    compute_routing_clearance,
    detect_route_collisions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_bodies(raw: list) -> list[Body]:
    bodies = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"obstacle[{i}] must be an object")
        min_pt = item.get("min_pt")
        max_pt = item.get("max_pt")
        if min_pt is None or max_pt is None:
            raise ValueError(f"obstacle[{i}] must have 'min_pt' and 'max_pt'")
        name = str(item.get("name", f"obstacle_{i}"))
        bodies.append(Body(min_pt=tuple(min_pt), max_pt=tuple(max_pt), name=name))
    return bodies


def _route_to_dict(route: Route) -> dict:
    return {
        "polyline": [list(p) for p in route.polyline],
        "total_length": route.total_length,
        "bend_count": route.bend_count,
        "collision_clearance_min": (
            None if route.collision_clearance_min == float("inf")
            else route.collision_clearance_min
        ),
    }


# ---------------------------------------------------------------------------
# wiring_auto_route
# ---------------------------------------------------------------------------

wiring_auto_route_spec = ToolSpec(
    name="wiring_auto_route",
    description=(
        "Automatically route a cable or wire harness in 3D space from a start "
        "point to an end point, detouring around AABB obstacle bodies. "
        "Uses voxel-grid A* pathfinding (Cheng-Quan 2001) with Catmull-Rom "
        "spline smoothing and bend-penalty cost. "
        "Returns the smoothed 3D polyline, total length, bend count, and minimum "
        "clearance to obstacles. "
        "Typical use: route a cable bundle through a vehicle or machine DMU."
    ),
    input_schema={
        "type": "object",
        "required": ["start_point", "end_point"],
        "properties": {
            "start_point": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3, "maxItems": 3,
                "description": "Start position [x, y, z] in mm.",
            },
            "end_point": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3, "maxItems": 3,
                "description": "End position [x, y, z] in mm.",
            },
            "obstacles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["min_pt", "max_pt"],
                    "properties": {
                        "min_pt": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3,
                            "description": "Minimum corner [x,y,z] of bounding box, mm.",
                        },
                        "max_pt": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3,
                            "description": "Maximum corner [x,y,z] of bounding box, mm.",
                        },
                        "name": {
                            "type": "string",
                            "description": "Optional label for diagnostics.",
                        },
                    },
                },
                "description": (
                    "List of AABB obstacle bodies the route must avoid. "
                    "Each body is described by its axis-aligned bounding box."
                ),
                "default": [],
            },
            "cable_radius": {
                "type": "number",
                "exclusiveMinimum": 0,
                "default": 2.0,
                "description": "Outer radius of the cable bundle in mm (default 2.0).",
            },
            "voxel_size": {
                "type": "number",
                "exclusiveMinimum": 0,
                "default": 5.0,
                "description": (
                    "Voxel edge length in mm. Smaller = higher resolution "
                    "but slower (default 5.0)."
                ),
            },
        },
    },
)


@register(wiring_auto_route_spec, write=False)
async def wiring_auto_route(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    start = a.get("start_point")
    end = a.get("end_point")
    if not isinstance(start, list) or len(start) != 3:
        return err_payload("start_point must be [x, y, z]", "BAD_ARGS")
    if not isinstance(end, list) or len(end) != 3:
        return err_payload("end_point must be [x, y, z]", "BAD_ARGS")

    try:
        obstacles = _parse_bodies(a.get("obstacles") or [])
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    cable_radius = float(a.get("cable_radius", 2.0))
    voxel_size = float(a.get("voxel_size", 5.0))

    if cable_radius <= 0:
        return err_payload("cable_radius must be > 0", "BAD_ARGS")
    if voxel_size <= 0:
        return err_payload("voxel_size must be > 0", "BAD_ARGS")

    try:
        route = auto_route_harness(
            start,
            end,
            obstacles=obstacles,
            cable_radius=cable_radius,
            voxel_size=voxel_size,
        )
    except (ValueError, RuntimeError) as exc:
        return err_payload(str(exc), "ROUTING_FAILED")
    except Exception as exc:
        return err_payload(f"routing error: {exc}", "ERROR")

    return ok_payload(_route_to_dict(route))


# ---------------------------------------------------------------------------
# wiring_check_clearance
# ---------------------------------------------------------------------------

wiring_check_clearance_spec = ToolSpec(
    name="wiring_check_clearance",
    description=(
        "Compute clearance statistics and detect collisions for a routed cable "
        "or wire harness polyline against a set of AABB obstacle bodies. "
        "Returns min/mean/percentile clearance distances and a list of collision "
        "events. Use after wiring_auto_route to validate the route, or on any "
        "manually-defined polyline."
    ),
    input_schema={
        "type": "object",
        "required": ["polyline", "obstacles"],
        "properties": {
            "polyline": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3, "maxItems": 3,
                },
                "description": "Ordered 3D waypoints [x, y, z] in mm (≥ 2 points).",
            },
            "obstacles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["min_pt", "max_pt"],
                    "properties": {
                        "min_pt": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3,
                        },
                        "max_pt": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3,
                        },
                        "name": {"type": "string"},
                    },
                },
                "description": "List of AABB obstacle bodies.",
            },
            "cable_radius": {
                "type": "number",
                "exclusiveMinimum": 0,
                "default": 2.0,
                "description": "Cable outer radius in mm (default 2.0).",
            },
            "n_samples": {
                "type": "integer",
                "minimum": 2,
                "default": 100,
                "description": (
                    "Number of sample points along the route for the clearance "
                    "histogram (default 100)."
                ),
            },
        },
    },
)


@register(wiring_check_clearance_spec, write=False)
async def wiring_check_clearance(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    polyline = a.get("polyline")
    if not isinstance(polyline, list) or len(polyline) < 2:
        return err_payload("polyline must be an array of at least 2 [x,y,z] points", "BAD_ARGS")

    try:
        obstacles = _parse_bodies(a.get("obstacles") or [])
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    cable_radius = float(a.get("cable_radius", 2.0))
    n_samples = int(a.get("n_samples", 100))

    if cable_radius <= 0:
        return err_payload("cable_radius must be > 0", "BAD_ARGS")
    if n_samples < 2:
        return err_payload("n_samples must be >= 2", "BAD_ARGS")

    # Build a Route from the raw polyline (length and other metrics not needed here)
    try:
        pts = [tuple(float(v) for v in pt) for pt in polyline]
    except Exception as e:
        return err_payload(f"invalid polyline coordinates: {e}", "BAD_ARGS")

    # Compute arc-length for a minimal Route stub
    total_length = sum(
        ((pts[i + 1][0] - pts[i][0]) ** 2
         + (pts[i + 1][1] - pts[i][1]) ** 2
         + (pts[i + 1][2] - pts[i][2]) ** 2) ** 0.5
        for i in range(len(pts) - 1)
    )

    route = Route(
        polyline=pts,
        total_length=total_length,
        bend_count=0,
        collision_clearance_min=0.0,
    )

    try:
        clearance_stats = compute_routing_clearance(route, obstacles, n_samples=n_samples)
        collisions = detect_route_collisions(route, obstacles, cable_radius=cable_radius)
    except Exception as exc:
        return err_payload(f"clearance computation error: {exc}", "ERROR")

    return ok_payload({
        "clearance": clearance_stats,
        "collisions": [
            {
                "segment_index": c.segment_index,
                "point": list(c.point),
                "obstacle_name": c.obstacle_name,
                "penetration_depth": c.penetration_depth,
            }
            for c in collisions
        ],
        "collision_count": len(collisions),
    })
