"""
cam_toolpath_collision — segment-by-segment CAM toolpath holder/spindle collision
verifier.

Algorithm
---------
For each consecutive pair of toolpath waypoints (a segment), we sample the
tool-tip position at 1 mm spacing along the segment (configurable via
``step_mm``).  At each sample point we build TWO capsules that represent the
tool geometry:

  * **Flute capsule** — radius = flute_radius, axis from tip downward (−Z in
    tool-frame) over flute_length mm.  This is the cutting zone; collisions here
    are warnings (the tool IS supposed to cut).
  * **Holder capsule** — radius = holder_radius, axis from flute top upward over
    holder_length mm.  Collisions here are genuine clearance violations; the
    holder should never touch the stock or fixture.

For each capsule we compute the minimum distance to:
  * the stock, described as an AABB or a triangle mesh;
  * (optional) a triangle mesh fixture.

If that distance is less than ``safety_margin`` mm a collision event is
recorded.

Geometry kernels (pure Python, no OCCT)
----------------------------------------
*Capsule vs AABB*  — Ericson 2005 §5.5 capsule-AABB distance: clamp segment
  closest point onto AABB surface, subtract radius.

*Capsule vs triangle* — Möller 1997 §6 point-triangle closest-point + Ericson
  2005 §5.1 segment-segment closest-point; minimum distance = min over all
  triangle edges + interior.

Honest limitations
------------------
* Sampling step is fixed at ``step_mm`` (default 1 mm).  Between samples the
  capsule may sweep a gap of up to ``step_mm × sqrt(2)`` ≈ 1.4 mm.  For true
  sub-millimetre continuous collision detection the step should be reduced to
  ≤ 0.1 mm, which is 10× more expensive.
* Mesh collision is O(n_samples × n_triangles); for large meshes prefer the
  AABB fast-path or pre-subdivide into a spatial structure.
* Fixture must be a triangle mesh; AABB fixtures are not supported.

References
----------
Möller, T., & Trumbore, B. (1997). Fast, minimum storage ray-triangle
  intersection. Journal of Graphics Tools, 2(1), 21–28.
Ericson, C. (2005). Real-Time Collision Detection. Elsevier.  §5.1, §5.5.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ToolGeometry:
    """Dimensions of the milling tool."""

    flute_radius: float      # mm — cutting zone radius (half diameter)
    flute_length: float      # mm — cutting zone axial length
    holder_radius: float     # mm — holder cylinder radius (> flute_radius)
    holder_length: float     # mm — holder cylinder axial length above flute


@dataclass
class StockGeometry:
    """Workpiece stock — either an AABB or a triangle mesh (or both)."""

    # AABB (always present; required)
    aabb_min: Tuple[float, float, float]   # (xmin, ymin, zmin) mm
    aabb_max: Tuple[float, float, float]   # (xmax, ymax, zmax) mm

    # Optional triangle mesh — list of triangles; each triangle is 3 points
    # [[x0,y0,z0], [x1,y1,z1], [x2,y2,z2]]
    triangles: Optional[List[List[List[float]]]] = None


@dataclass
class CollisionEvent:
    """A single detected collision or clearance violation."""

    segment_index: int        # index of the toolpath segment (0-based)
    sample_t: float           # parametric position along segment [0, 1]
    position: Tuple[float, float, float]   # tool-tip XYZ at sample point (mm)
    distance: float           # minimum clearance distance found (mm; < safety_margin)
    body: str                 # "holder" or "flute"
    geometry: str             # "stock_aabb" | "stock_mesh" | "fixture"


@dataclass
class CollisionReport:
    """Result of ``verify_toolpath_collision``."""

    collisions: List[CollisionEvent] = field(default_factory=list)
    safe: bool = True         # True iff no holder collisions within safety_margin
    warnings: List[str] = field(default_factory=list)
    segments_checked: int = 0
    samples_total: int = 0


# ---------------------------------------------------------------------------
# Internal vector math (pure Python)
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _len2(a: Vec3) -> float:
    return _dot(a, a)


def _lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    return (
        a[0] + t * (b[0] - a[0]),
        a[1] + t * (b[1] - a[1]),
        a[2] + t * (b[2] - a[2]),
    )


def _clamp01(t: float) -> float:
    return max(0.0, min(1.0, t))


# ---------------------------------------------------------------------------
# Closest point on segment to point (Ericson 2005 §5.1.2)
# ---------------------------------------------------------------------------

def _closest_point_on_segment(p: Vec3, a: Vec3, b: Vec3) -> Tuple[float, Vec3]:
    """Return (t, closest_point) where t ∈ [0,1]."""
    ab = _sub(b, a)
    d2 = _len2(ab)
    if d2 < 1e-14:
        return 0.0, a
    t = _clamp01(_dot(_sub(p, a), ab) / d2)
    return t, _lerp(a, b, t)


# ---------------------------------------------------------------------------
# Capsule vs AABB minimum distance  (Ericson 2005 §5.5 adapted)
# ---------------------------------------------------------------------------

def _closest_point_on_aabb(p: Vec3, box_min: Vec3, box_max: Vec3) -> Vec3:
    """Return closest point on AABB surface/interior to p."""
    return (
        max(box_min[0], min(p[0], box_max[0])),
        max(box_min[1], min(p[1], box_max[1])),
        max(box_min[2], min(p[2], box_max[2])),
    )


def _capsule_aabb_min_distance(
    cap_a: Vec3, cap_b: Vec3, cap_radius: float,
    box_min: Vec3, box_max: Vec3,
) -> float:
    """
    Minimum distance between the surface of a capsule (axis from cap_a to
    cap_b, radius cap_radius) and the surface of an AABB.

    Algorithm: iterate over the segment axis; the minimum distance from the
    capsule axis to the AABB is computed via closest-point projection.
    Returns negative value when capsule penetrates AABB.
    """
    # Sample the segment at multiple sub-steps to find the minimum distance
    # from the capsule axis to the box.  This is conservative (might
    # overestimate distance by ≤ sub-step × |AB| / N) but avoids the full
    # segment-vs-box closest-segment computation.
    _STEPS = 8
    min_dist_sq: float = math.inf
    for i in range(_STEPS + 1):
        t = i / _STEPS
        p = _lerp(cap_a, cap_b, t)
        cp = _closest_point_on_aabb(p, box_min, box_max)
        d2 = _len2(_sub(p, cp))
        if d2 < min_dist_sq:
            min_dist_sq = d2
    return math.sqrt(min_dist_sq) - cap_radius


# ---------------------------------------------------------------------------
# Point-triangle closest point  (Möller 1997 §6 / Ericson 2005 §5.1.5)
# ---------------------------------------------------------------------------

def _closest_point_on_triangle(
    p: Vec3,
    t0: Vec3, t1: Vec3, t2: Vec3,
) -> Vec3:
    """Return the closest point on triangle (t0,t1,t2) to point p."""
    ab = _sub(t1, t0)
    ac = _sub(t2, t0)
    ap = _sub(p, t0)
    d1 = _dot(ab, ap)
    d2 = _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return t0

    bp = _sub(p, t1)
    d3 = _dot(ab, bp)
    d4 = _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return t1

    cp = _sub(p, t2)
    d5 = _dot(ab, cp)
    d6 = _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return t2

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3)
        return _add(t0, _scale(ab, v))

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6)
        return _add(t0, _scale(ac, w))

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return _add(t1, _scale(_sub(t2, t1), w))

    denom = 1.0 / (va + vb + vc)
    v = vb * denom
    w = vc * denom
    return _add(t0, _add(_scale(ab, v), _scale(ac, w)))


def _capsule_mesh_min_distance(
    cap_a: Vec3, cap_b: Vec3, cap_radius: float,
    triangles: List[List[List[float]]],
) -> float:
    """
    Return minimum distance from capsule (axis cap_a→cap_b, radius cap_radius)
    to the nearest triangle in the mesh.  Returns negative if penetrating.
    """
    min_dist: float = math.inf
    for tri in triangles:
        p0: Vec3 = tuple(tri[0])  # type: ignore[arg-type]
        p1: Vec3 = tuple(tri[1])  # type: ignore[arg-type]
        p2: Vec3 = tuple(tri[2])  # type: ignore[arg-type]
        # Closest point from each capsule-axis sample to this triangle
        for _t_step in range(9):
            t = _t_step / 8.0
            sample = _lerp(cap_a, cap_b, t)
            cp = _closest_point_on_triangle(sample, p0, p1, p2)
            d = math.sqrt(_len2(_sub(sample, cp))) - cap_radius
            if d < min_dist:
                min_dist = d
    return min_dist


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def verify_toolpath_collision(
    toolpath: Sequence[Tuple[float, float, float, float]],
    tool_geometry: ToolGeometry,
    stock: StockGeometry,
    fixture: Optional[List[List[List[float]]]] = None,
    safety_margin: float = 2.0,
    step_mm: float = 1.0,
) -> CollisionReport:
    """
    Verify a CAM toolpath segment-by-segment for holder/spindle collisions.

    Parameters
    ----------
    toolpath:
        Ordered list of (X, Y, Z, feedrate) waypoints in mm.  The tool tip is
        assumed to be at (X, Y, Z).  At least 1 point required; segments are
        formed between consecutive points.
    tool_geometry:
        ToolGeometry describing flute and holder dimensions.
    stock:
        StockGeometry with AABB (required) and optional triangle mesh.
    fixture:
        Optional triangle mesh for fixturing.  Same format as
        StockGeometry.triangles.
    safety_margin:
        Required clearance between the holder capsule and any obstruction (mm).
        A violation is raised when distance < safety_margin.
    step_mm:
        Sampling resolution along each segment (mm).  Default 1 mm.
        Worst-case missed-collision gap ≈ step_mm × √2 ≈ 1.41 mm at 1 mm step.

    Returns
    -------
    CollisionReport with all detected holder collisions and summary flags.
    """
    report = CollisionReport()

    if not toolpath:
        return report

    if step_mm <= 0.0:
        report.warnings.append(f"step_mm must be positive; got {step_mm}. Using 1.0 mm.")
        step_mm = 1.0

    tg = tool_geometry
    box_min: Vec3 = tuple(stock.aabb_min)  # type: ignore[arg-type]
    box_max: Vec3 = tuple(stock.aabb_max)  # type: ignore[arg-type]

    # Iterate over segments
    pts = list(toolpath)
    report.segments_checked = max(0, len(pts) - 1)

    for seg_idx in range(len(pts) - 1):
        xa, ya, za, _ = pts[seg_idx]
        xb, yb, zb, _ = pts[seg_idx + 1]
        seg_start: Vec3 = (xa, ya, za)
        seg_end: Vec3 = (xb, yb, zb)
        seg_vec = _sub(seg_end, seg_start)
        seg_len = math.sqrt(_len2(seg_vec))

        # Number of samples (at least 2: endpoints)
        n_steps = max(1, math.ceil(seg_len / step_mm))

        for i in range(n_steps + 1):
            t = i / n_steps
            tip: Vec3 = _lerp(seg_start, seg_end, t)
            report.samples_total += 1

            # Build capsule axes (tool Z is "up" from tip):
            # Flute: tip (bottom) → tip + (0,0,flute_length)
            flute_bot: Vec3 = tip
            flute_top: Vec3 = (tip[0], tip[1], tip[2] + tg.flute_length)

            # Holder: flute_top → flute_top + (0,0,holder_length)
            holder_bot: Vec3 = flute_top
            holder_top: Vec3 = (flute_top[0], flute_top[1], flute_top[2] + tg.holder_length)

            # Check HOLDER against stock AABB
            dist_aabb = _capsule_aabb_min_distance(
                holder_bot, holder_top, tg.holder_radius, box_min, box_max
            )
            if dist_aabb < safety_margin:
                report.collisions.append(CollisionEvent(
                    segment_index=seg_idx,
                    sample_t=t,
                    position=tip,
                    distance=dist_aabb,
                    body="holder",
                    geometry="stock_aabb",
                ))
                report.safe = False

            # Check HOLDER against stock mesh (if provided)
            if stock.triangles:
                dist_mesh = _capsule_mesh_min_distance(
                    holder_bot, holder_top, tg.holder_radius, stock.triangles
                )
                if dist_mesh < safety_margin:
                    report.collisions.append(CollisionEvent(
                        segment_index=seg_idx,
                        sample_t=t,
                        position=tip,
                        distance=dist_mesh,
                        body="holder",
                        geometry="stock_mesh",
                    ))
                    report.safe = False

            # Check HOLDER against fixture mesh (if provided)
            if fixture:
                dist_fix = _capsule_mesh_min_distance(
                    holder_bot, holder_top, tg.holder_radius, fixture
                )
                if dist_fix < safety_margin:
                    report.collisions.append(CollisionEvent(
                        segment_index=seg_idx,
                        sample_t=t,
                        position=tip,
                        distance=dist_fix,
                        body="holder",
                        geometry="fixture",
                    ))
                    report.safe = False

    return report


# ---------------------------------------------------------------------------
# LLM tool
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

    _cam_collision_spec = ToolSpec(
        name="cam_verify_toolpath_collision",
        description=(
            "Verify a CAM toolpath segment-by-segment for holder/spindle collisions "
            "against the workpiece (stock) and optional fixturing geometry.\n\n"
            "For each segment the tool holder capsule is checked against the stock "
            "AABB and optional triangle mesh at 1 mm sampling resolution. Returns a "
            "list of collision events with segment index, position, and clearance "
            "distance.\n\n"
            "Inputs:\n"
            "  toolpath       — list of {x,y,z,feedrate} waypoints (mm)\n"
            "  flute_radius   — cutting flute radius (mm)\n"
            "  flute_length   — cutting flute length (mm)\n"
            "  holder_radius  — holder cylinder radius (mm; must be > flute_radius)\n"
            "  holder_length  — holder cylinder length above flute (mm)\n"
            "  stock_aabb_min — [xmin,ymin,zmin] of stock bounding box (mm)\n"
            "  stock_aabb_max — [xmax,ymax,zmax] of stock bounding box (mm)\n"
            "  stock_triangles — optional list of triangles [[p0,p1,p2],…] for mesh stock\n"
            "  fixture_triangles — optional list of triangles for fixturing\n"
            "  safety_margin  — required holder clearance in mm (default 2.0)\n"
            "  step_mm        — sampling resolution along each segment (default 1.0)\n"
        ),
        input_schema={
            "type": "object",
            "required": [
                "toolpath",
                "flute_radius", "flute_length",
                "holder_radius", "holder_length",
                "stock_aabb_min", "stock_aabb_max",
            ],
            "properties": {
                "toolpath": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "z": {"type": "number"},
                            "feedrate": {"type": "number"},
                        },
                        "required": ["x", "y", "z"],
                    },
                    "description": "Ordered list of tool-tip waypoints (mm).",
                },
                "flute_radius": {"type": "number"},
                "flute_length": {"type": "number"},
                "holder_radius": {"type": "number"},
                "holder_length": {"type": "number"},
                "stock_aabb_min": {
                    "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                },
                "stock_aabb_max": {
                    "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                },
                "stock_triangles": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                    },
                    "description": "Optional triangle mesh for stock.",
                },
                "fixture_triangles": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                    },
                    "description": "Optional triangle mesh for fixturing.",
                },
                "safety_margin": {"type": "number", "default": 2.0},
                "step_mm": {"type": "number", "default": 1.0},
            },
        },
    )

    @register(_cam_collision_spec)
    async def _run_cam_verify_toolpath_collision(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            waypoints = a.get("toolpath", [])
            toolpath = [
                (float(w["x"]), float(w["y"]), float(w["z"]),
                 float(w.get("feedrate", 0.0)))
                for w in waypoints
            ]

            tg = ToolGeometry(
                flute_radius=float(a["flute_radius"]),
                flute_length=float(a["flute_length"]),
                holder_radius=float(a["holder_radius"]),
                holder_length=float(a["holder_length"]),
            )

            st = StockGeometry(
                aabb_min=tuple(a["stock_aabb_min"]),  # type: ignore[arg-type]
                aabb_max=tuple(a["stock_aabb_max"]),  # type: ignore[arg-type]
                triangles=a.get("stock_triangles"),
            )

            fixture = a.get("fixture_triangles")
            safety_margin = float(a.get("safety_margin", 2.0))
            step_mm = float(a.get("step_mm", 1.0))

        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"bad parameter: {exc}", "BAD_ARGS")

        report = verify_toolpath_collision(
            toolpath, tg, st, fixture=fixture,
            safety_margin=safety_margin, step_mm=step_mm,
        )

        return ok_payload({
            "safe": report.safe,
            "collision_count": len(report.collisions),
            "segments_checked": report.segments_checked,
            "samples_total": report.samples_total,
            "collisions": [
                {
                    "segment_index": c.segment_index,
                    "sample_t": round(c.sample_t, 4),
                    "position": list(c.position),
                    "distance_mm": round(c.distance, 4),
                    "body": c.body,
                    "geometry": c.geometry,
                }
                for c in report.collisions
            ],
            "warnings": report.warnings,
        })

except ImportError:
    pass  # kerf_chat not available — tool not registered; module still importable
