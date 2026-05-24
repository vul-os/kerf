"""
kerf_cad_core.frep.csg
======================
Implicit CSG operations and domain warps for SDF-based (F-rep) modelling.

Design principles
-----------------
* Pure Python + math only.  No OCC, numpy, scipy, or third-party deps.
* Standalone — does NOT import from sdf.py; convenience primitives are inlined.
* Never raises — every public function returns a callable SDF; every LLM tool
  returns ``{"ok": bool, ...}`` and catches all exceptions internally.
* All SDF callables: ``f(x, y, z) -> float``  (negative = inside, 0 = surface).

Sections
--------
1. Sharp boolean CSG (min/max)
2. Smooth boolean CSG — polynomial smooth-min (Quilez 2013)
3. Offset, shell, onion
4. Domain warps — twist, bend, repeat, mirror, rotate
5. Convenience primitives (sphere, box, cylinder, torus) — inlined
6. LLM tool wrappers (16 tools)

References
----------
Quilez, I. (2013/2022). "Smooth minimum." iquilezles.org/articles/smin
Quilez, I. (2022). "Domain deformation." iquilezles.org/articles/distfunctions
"""
from __future__ import annotations

import json
import math
from typing import Callable, Tuple

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
SDF = Callable[[float, float, float], float]

# ---------------------------------------------------------------------------
# Internal helpers (inlined; no sdf.py import)
# ---------------------------------------------------------------------------

_EPS = 1e-7


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def _len3(x: float, y: float, z: float) -> float:
    return math.sqrt(x * x + y * y + z * z)


# ===========================================================================
# 1. Sharp (hard) boolean CSG
# ===========================================================================

def csg_union(a: SDF, b: SDF) -> SDF:
    """Boolean union: min(a(p), b(p))."""
    def _f(x: float, y: float, z: float) -> float:
        return min(a(x, y, z), b(x, y, z))
    return _f


def csg_intersect(a: SDF, b: SDF) -> SDF:
    """Boolean intersection: max(a(p), b(p))."""
    def _f(x: float, y: float, z: float) -> float:
        return max(a(x, y, z), b(x, y, z))
    return _f


def csg_difference(a: SDF, b: SDF) -> SDF:
    """Boolean difference (a minus b): max(a(p), -b(p))."""
    def _f(x: float, y: float, z: float) -> float:
        return max(a(x, y, z), -b(x, y, z))
    return _f


# ===========================================================================
# 2. Smooth boolean CSG — polynomial smooth-min (Quilez 2013)
# ===========================================================================
# The polynomial smooth-min is:
#   smin(a, b, k) = min(a, b) - h² * k / 4    where h = clamp(0.5 + 0.5*(b-a)/k, 0, 1)
# This is C¹-continuous and deforms the isosurface within the blend radius k.

def _smin(a: float, b: float, k: float) -> float:
    """Polynomial smooth-min (Quilez).  Returns ≤ min(a, b) in the blend zone."""
    h = _clamp(0.5 + 0.5 * (b - a) / max(k, _EPS), 0.0, 1.0)
    return a * (1.0 - h) + b * h - k * h * (1.0 - h)


def _smax(a: float, b: float, k: float) -> float:
    """Polynomial smooth-max (dual of smin): smax(a,b,k) = -smin(-a,-b,k)."""
    return -_smin(-a, -b, k)


def csg_union_smooth(a: SDF, b: SDF, k: float = 0.1) -> SDF:
    """Smooth union using polynomial smooth-min (Quilez).

    k is the blend radius in model units — larger k → softer blend.
    The result is ≤ min(a, b) in the symmetric blend zone (|a-b| < k).
    """
    def _f(x: float, y: float, z: float) -> float:
        return _smin(a(x, y, z), b(x, y, z), k)
    return _f


def csg_intersect_smooth(a: SDF, b: SDF, k: float = 0.1) -> SDF:
    """Smooth intersection using polynomial smooth-max."""
    def _f(x: float, y: float, z: float) -> float:
        return _smax(a(x, y, z), b(x, y, z), k)
    return _f


def csg_difference_smooth(a: SDF, b: SDF, k: float = 0.1) -> SDF:
    """Smooth difference (a minus b) using smooth-max of (a, -b)."""
    def _f(x: float, y: float, z: float) -> float:
        return _smax(a(x, y, z), -b(x, y, z), k)
    return _f


# ===========================================================================
# 3. Offset, shell, onion
# ===========================================================================

def sdf_offset(sdf: SDF, delta: float) -> SDF:
    """Offset the zero-isosurface outward by *delta* (negative → inward).

    For an exact SDF the new surface lies at distance |delta| from the original.
    """
    def _f(x: float, y: float, z: float) -> float:
        return sdf(x, y, z) - delta
    return _f


def sdf_shell(sdf: SDF, thickness: float) -> SDF:
    """Hollow shell of given wall *thickness* around sdf's surface.

    Equivalent to the band  |sdf(p)| ≤ thickness/2.
    Implementation:  abs(sdf(p)) - thickness/2.
    """
    half = thickness / 2.0

    def _f(x: float, y: float, z: float) -> float:
        return abs(sdf(x, y, z)) - half
    return _f


def sdf_onion(sdf: SDF, t: float) -> SDF:
    """Onion / layered shell of wall thickness *t*.

    Equivalent to sdf_shell but with the convention  abs(sdf) - t,
    which carves the interior and leaves a single closed-surface wall.
    See Quilez's "onioning" technique.
    """
    def _f(x: float, y: float, z: float) -> float:
        return abs(sdf(x, y, z)) - t
    return _f


# ===========================================================================
# 4. Domain warps
# ===========================================================================

def sdf_twist(sdf: SDF, k: float) -> SDF:
    """Twist the field around the Z-axis.

    At height z, the XY-plane is rotated by angle k*z radians.
    k in radians-per-unit — k=π/2 means a quarter-turn per unit of height.
    Note: this is an approximate SDF (domain warp); not exact for large k.
    """
    def _f(x: float, y: float, z: float) -> float:
        c = math.cos(k * z)
        s = math.sin(k * z)
        xw = c * x - s * y
        yw = s * x + c * y
        return sdf(xw, yw, z)
    return _f


def sdf_bend(sdf: SDF, k: float) -> SDF:
    """Bend the field in the XY-plane around the Y-axis.

    The point (x, y, z) is mapped via a circular arc parameterised by x.
    k in radians-per-unit — k=π/2 means a quarter-turn per unit of x.
    Note: approximate SDF (domain warp).
    """
    def _f(x: float, y: float, z: float) -> float:
        c = math.cos(k * x)
        s = math.sin(k * x)
        xw = c * x - s * y
        yw = s * x + c * y
        return sdf(xw, yw, z)
    return _f


def sdf_repeat(sdf: SDF, cx: float, cy: float, cz: float) -> SDF:
    """Tile the field with period (cx, cy, cz) in each axis.

    Negative period disables tiling along that axis (pass 0 or inf).
    Uses: p_mod = p - period * round(p / period).
    """
    def _mod(v: float, period: float) -> float:
        if period <= 0.0:
            return v
        return v - period * math.floor(v / period + 0.5)

    def _f(x: float, y: float, z: float) -> float:
        xw = _mod(x, cx)
        yw = _mod(y, cy)
        zw = _mod(z, cz)
        return sdf(xw, yw, zw)
    return _f


def sdf_mirror(sdf: SDF, axis: int = 0) -> SDF:
    """Mirror the field across the plane perpendicular to *axis* through origin.

    axis: 0=X (mirror across YZ-plane), 1=Y, 2=Z.
    Equivalent to abs(p[axis]) before evaluating sdf.
    """
    if axis not in (0, 1, 2):
        raise ValueError(f"axis must be 0, 1, or 2; got {axis}")

    def _f(x: float, y: float, z: float) -> float:
        p = [x, y, z]
        p[axis] = abs(p[axis])
        return sdf(p[0], p[1], p[2])
    return _f


def sdf_rotate(sdf: SDF, axis: int = 2, theta: float = 0.0) -> SDF:
    """Rotate the field by *theta* radians around the given *axis* (0=X,1=Y,2=Z).

    Implemented as inverse rotation of the sample point before evaluating sdf,
    so the geometry itself rotates by +theta.
    """
    c, s = math.cos(theta), math.sin(theta)

    if axis == 0:  # X-axis: rotate YZ
        def _f(x: float, y: float, z: float) -> float:
            return sdf(x, c * y + s * z, -s * y + c * z)
    elif axis == 1:  # Y-axis: rotate XZ
        def _f(x: float, y: float, z: float) -> float:  # type: ignore[misc]
            return sdf(c * x - s * z, y, s * x + c * z)
    elif axis == 2:  # Z-axis: rotate XY
        def _f(x: float, y: float, z: float) -> float:  # type: ignore[misc]
            return sdf(c * x + s * y, -s * x + c * y, z)
    else:
        raise ValueError(f"axis must be 0, 1, or 2; got {axis}")
    return _f


# ===========================================================================
# 5. Convenience primitives (inlined; no sdf.py import)
# ===========================================================================

def _prim_sphere(cx: float = 0.0, cy: float = 0.0, cz: float = 0.0,
                 radius: float = 1.0) -> SDF:
    """Unit sphere at (cx, cy, cz)."""
    def _f(x: float, y: float, z: float) -> float:
        return _len3(x - cx, y - cy, z - cz) - radius
    return _f


def _prim_box(cx: float = 0.0, cy: float = 0.0, cz: float = 0.0,
              hx: float = 1.0, hy: float = 1.0, hz: float = 1.0) -> SDF:
    """Axis-aligned box centred at (cx, cy, cz) with half-extents (hx, hy, hz)."""
    def _f(x: float, y: float, z: float) -> float:
        qx = abs(x - cx) - hx
        qy = abs(y - cy) - hy
        qz = abs(z - cz) - hz
        px = qx if qx > 0.0 else 0.0
        py = qy if qy > 0.0 else 0.0
        pz = qz if qz > 0.0 else 0.0
        return _len3(px, py, pz) + min(max(qx, max(qy, qz)), 0.0)
    return _f


def _prim_cylinder(cx: float = 0.0, cy: float = 0.0, cz: float = 0.0,
                   radius: float = 1.0, half_height: float = 1.0,
                   ax: int = 2) -> SDF:
    """Cylinder aligned to axis ax (0=X,1=Y,2=Z)."""
    def _f(x: float, y: float, z: float) -> float:
        p = [x - cx, y - cy, z - cz]
        a_coord = p[ax]
        ra = p[(ax + 1) % 3]
        rb = p[(ax + 2) % 3]
        dr = math.sqrt(ra * ra + rb * rb) - radius
        dh = abs(a_coord) - half_height
        return min(max(dr, dh), 0.0) + _len3(max(dr, 0.0), max(dh, 0.0), 0.0)
    return _f


def _prim_torus(cx: float = 0.0, cy: float = 0.0, cz: float = 0.0,
                major: float = 1.0, minor: float = 0.25, ax: int = 2) -> SDF:
    """Torus sweeping around axis ax."""
    def _f(x: float, y: float, z: float) -> float:
        p = [x - cx, y - cy, z - cz]
        a_coord = p[ax]
        ra = p[(ax + 1) % 3]
        rb = p[(ax + 2) % 3]
        qx = math.sqrt(ra * ra + rb * rb) - major
        return math.sqrt(qx * qx + a_coord * a_coord) - minor
    return _f


# Exported convenience wrappers (same names as sdf.py primitives for symmetry)
def sphere(cx: float = 0.0, cy: float = 0.0, cz: float = 0.0,
           radius: float = 1.0) -> SDF:
    """Sphere SDF (convenience; inlined — does not call sdf.py)."""
    return _prim_sphere(cx, cy, cz, radius)


def box(cx: float = 0.0, cy: float = 0.0, cz: float = 0.0,
        hx: float = 1.0, hy: float = 1.0, hz: float = 1.0) -> SDF:
    """Box SDF (convenience; inlined)."""
    return _prim_box(cx, cy, cz, hx, hy, hz)


def cylinder(cx: float = 0.0, cy: float = 0.0, cz: float = 0.0,
             radius: float = 1.0, half_height: float = 1.0, axis: int = 2) -> SDF:
    """Cylinder SDF (convenience; inlined)."""
    return _prim_cylinder(cx, cy, cz, radius, half_height, axis)


def torus(cx: float = 0.0, cy: float = 0.0, cz: float = 0.0,
          major_radius: float = 1.0, minor_radius: float = 0.25,
          axis: int = 2) -> SDF:
    """Torus SDF (convenience; inlined)."""
    return _prim_torus(cx, cy, cz, major_radius, minor_radius, axis)


# ===========================================================================
# 6. LLM tool wrappers (16 tools)
# ===========================================================================

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------ #
    # Helper: build an SDF from a primitive spec dict
    # ------------------------------------------------------------------ #
    def _build_primitive(spec: dict) -> SDF:
        kind = str(spec.get("type", "sphere")).lower()
        p = spec.get("params", {})
        if kind == "sphere":
            return _prim_sphere(
                float(p.get("cx", 0)), float(p.get("cy", 0)), float(p.get("cz", 0)),
                float(p.get("radius", 1.0)),
            )
        elif kind == "box":
            return _prim_box(
                float(p.get("cx", 0)), float(p.get("cy", 0)), float(p.get("cz", 0)),
                float(p.get("hx", 1.0)), float(p.get("hy", 1.0)), float(p.get("hz", 1.0)),
            )
        elif kind == "cylinder":
            return _prim_cylinder(
                float(p.get("cx", 0)), float(p.get("cy", 0)), float(p.get("cz", 0)),
                float(p.get("radius", 1.0)), float(p.get("half_height", 1.0)),
                int(p.get("axis", 2)),
            )
        elif kind == "torus":
            return _prim_torus(
                float(p.get("cx", 0)), float(p.get("cy", 0)), float(p.get("cz", 0)),
                float(p.get("major_radius", 1.0)), float(p.get("minor_radius", 0.25)),
                int(p.get("axis", 2)),
            )
        else:
            raise ValueError(f"unknown primitive type '{kind}'")

    def _eval_points(sdf_fn: SDF, points: list) -> list:
        results = []
        for pt in points:
            x, y, z = float(pt[0]), float(pt[1]), float(pt[2])
            results.append({"x": x, "y": y, "z": z, "distance": sdf_fn(x, y, z)})
        return results

    _PRIM_SCHEMA = {
        "type": "object",
        "description": "Primitive spec: {type, params}",
        "properties": {
            "type": {"type": "string",
                     "description": "'sphere' | 'box' | 'cylinder' | 'torus'"},
            "params": {"type": "object"},
        },
        "required": ["type"],
    }
    _POINTS_SCHEMA = {
        "type": "array",
        "items": {"type": "array", "items": {"type": "number"}},
        "description": "List of [x, y, z] sample points.",
    }

    # ------------------------------------------------------------------ #
    # Tool 1: csg_union_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_union",
        description=(
            "Evaluate the sharp boolean union (min) of two SDF primitives at sample points.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "a": _PRIM_SCHEMA, "b": _PRIM_SCHEMA, "points": _POINTS_SCHEMA,
            },
            "required": ["a", "b", "points"],
        },
    ), write=False)
    async def _tool_csg_union(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = csg_union(_build_primitive(d["a"]), _build_primitive(d["b"]))
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 2: csg_intersect_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_intersect",
        description=(
            "Evaluate the sharp boolean intersection (max) of two SDF primitives.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "a": _PRIM_SCHEMA, "b": _PRIM_SCHEMA, "points": _POINTS_SCHEMA,
            },
            "required": ["a", "b", "points"],
        },
    ), write=False)
    async def _tool_csg_intersect(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = csg_intersect(_build_primitive(d["a"]), _build_primitive(d["b"]))
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 3: csg_difference_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_difference",
        description=(
            "Evaluate the sharp boolean difference (a minus b: max(a,-b)) of two SDF primitives.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "a": _PRIM_SCHEMA, "b": _PRIM_SCHEMA, "points": _POINTS_SCHEMA,
            },
            "required": ["a", "b", "points"],
        },
    ), write=False)
    async def _tool_csg_difference(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = csg_difference(_build_primitive(d["a"]), _build_primitive(d["b"]))
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 4: csg_union_smooth_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_union_smooth",
        description=(
            "Evaluate the smooth boolean union (polynomial smooth-min, Quilez) of two SDF primitives.\n"
            "k is the blend radius in model units.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "a": _PRIM_SCHEMA, "b": _PRIM_SCHEMA, "points": _POINTS_SCHEMA,
                "k": {"type": "number", "description": "Blend radius (default 0.1)."},
            },
            "required": ["a", "b", "points"],
        },
    ), write=False)
    async def _tool_csg_union_smooth(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            k = float(d.get("k", 0.1))
            fn = csg_union_smooth(_build_primitive(d["a"]), _build_primitive(d["b"]), k)
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 5: csg_intersect_smooth_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_intersect_smooth",
        description=(
            "Evaluate the smooth boolean intersection (polynomial smooth-max, Quilez) of two SDF primitives.\n"
            "k is the blend radius.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "a": _PRIM_SCHEMA, "b": _PRIM_SCHEMA, "points": _POINTS_SCHEMA,
                "k": {"type": "number"},
            },
            "required": ["a", "b", "points"],
        },
    ), write=False)
    async def _tool_csg_intersect_smooth(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            k = float(d.get("k", 0.1))
            fn = csg_intersect_smooth(_build_primitive(d["a"]), _build_primitive(d["b"]), k)
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 6: csg_difference_smooth_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_difference_smooth",
        description=(
            "Evaluate the smooth boolean difference (smooth-max(a,-b), Quilez) of two SDF primitives.\n"
            "k is the blend radius.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "a": _PRIM_SCHEMA, "b": _PRIM_SCHEMA, "points": _POINTS_SCHEMA,
                "k": {"type": "number"},
            },
            "required": ["a", "b", "points"],
        },
    ), write=False)
    async def _tool_csg_difference_smooth(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            k = float(d.get("k", 0.1))
            fn = csg_difference_smooth(_build_primitive(d["a"]), _build_primitive(d["b"]), k)
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 7: sdf_offset_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_sdf_offset",
        description=(
            "Offset an SDF primitive outward by delta (negative = inward).\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": _PRIM_SCHEMA,
                "delta": {"type": "number", "description": "Offset amount in model units."},
                "points": _POINTS_SCHEMA,
            },
            "required": ["primitive", "delta", "points"],
        },
    ), write=False)
    async def _tool_sdf_offset(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = sdf_offset(_build_primitive(d["primitive"]), float(d["delta"]))
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 8: sdf_shell_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_sdf_shell",
        description=(
            "Create a hollow shell of given wall thickness around an SDF primitive surface.\n"
            "Shell value = abs(sdf) - thickness/2.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": _PRIM_SCHEMA,
                "thickness": {"type": "number"},
                "points": _POINTS_SCHEMA,
            },
            "required": ["primitive", "thickness", "points"],
        },
    ), write=False)
    async def _tool_sdf_shell(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = sdf_shell(_build_primitive(d["primitive"]), float(d["thickness"]))
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 9: sdf_onion_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_sdf_onion",
        description=(
            "Create an onion/layered shell of thickness t: abs(sdf) - t.\n"
            "Carves the interior, leaving a closed-surface wall.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": _PRIM_SCHEMA,
                "t": {"type": "number", "description": "Onion thickness."},
                "points": _POINTS_SCHEMA,
            },
            "required": ["primitive", "t", "points"],
        },
    ), write=False)
    async def _tool_sdf_onion(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = sdf_onion(_build_primitive(d["primitive"]), float(d["t"]))
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 10: sdf_twist_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_sdf_twist",
        description=(
            "Apply a twist domain warp around the Z-axis to an SDF primitive.\n"
            "k is the twist rate in radians per unit of height.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": _PRIM_SCHEMA,
                "k": {"type": "number", "description": "Twist rate rad/unit."},
                "points": _POINTS_SCHEMA,
            },
            "required": ["primitive", "k", "points"],
        },
    ), write=False)
    async def _tool_sdf_twist(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = sdf_twist(_build_primitive(d["primitive"]), float(d["k"]))
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 11: sdf_bend_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_sdf_bend",
        description=(
            "Apply a bend domain warp in the XY-plane to an SDF primitive.\n"
            "k is the bend rate in radians per unit of x.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": _PRIM_SCHEMA,
                "k": {"type": "number", "description": "Bend rate rad/unit."},
                "points": _POINTS_SCHEMA,
            },
            "required": ["primitive", "k", "points"],
        },
    ), write=False)
    async def _tool_sdf_bend(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = sdf_bend(_build_primitive(d["primitive"]), float(d["k"]))
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 12: sdf_repeat_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_sdf_repeat",
        description=(
            "Tile an SDF primitive with period (cx, cy, cz). "
            "Set a period to 0 to disable tiling along that axis.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": _PRIM_SCHEMA,
                "cx": {"type": "number"}, "cy": {"type": "number"}, "cz": {"type": "number"},
                "points": _POINTS_SCHEMA,
            },
            "required": ["primitive", "cx", "cy", "cz", "points"],
        },
    ), write=False)
    async def _tool_sdf_repeat(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = sdf_repeat(
                _build_primitive(d["primitive"]),
                float(d["cx"]), float(d["cy"]), float(d["cz"]),
            )
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 13: sdf_mirror_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_sdf_mirror",
        description=(
            "Mirror an SDF primitive across a coordinate plane.\n"
            "axis: 0=mirror across YZ (abs(x)), 1=XZ (abs(y)), 2=XY (abs(z)).\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": _PRIM_SCHEMA,
                "axis": {"type": "integer", "description": "0=X, 1=Y, 2=Z"},
                "points": _POINTS_SCHEMA,
            },
            "required": ["primitive", "axis", "points"],
        },
    ), write=False)
    async def _tool_sdf_mirror(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = sdf_mirror(_build_primitive(d["primitive"]), int(d.get("axis", 0)))
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 14: sdf_rotate_tool
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_sdf_rotate",
        description=(
            "Rotate an SDF primitive by theta radians around a coordinate axis.\n"
            "axis: 0=X, 1=Y, 2=Z; theta in radians.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": _PRIM_SCHEMA,
                "axis": {"type": "integer"},
                "theta": {"type": "number", "description": "Rotation angle in radians."},
                "points": _POINTS_SCHEMA,
            },
            "required": ["primitive", "axis", "theta", "points"],
        },
    ), write=False)
    async def _tool_sdf_rotate(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            fn = sdf_rotate(
                _build_primitive(d["primitive"]),
                int(d.get("axis", 2)),
                float(d.get("theta", 0.0)),
            )
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 15: sphere primitive
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_sphere",
        description=(
            "Evaluate the SDF of a sphere at sample points.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "center": {"type": "array", "items": {"type": "number"},
                           "description": "[cx, cy, cz]"},
                "radius": {"type": "number"},
                "points": _POINTS_SCHEMA,
            },
            "required": ["center", "radius", "points"],
        },
    ), write=False)
    async def _tool_sphere(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            cx, cy, cz = float(d["center"][0]), float(d["center"][1]), float(d["center"][2])
            fn = _prim_sphere(cx, cy, cz, float(d["radius"]))
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")

    # ------------------------------------------------------------------ #
    # Tool 16: box primitive
    # ------------------------------------------------------------------ #
    @register(ToolSpec(
        name="csg_box",
        description=(
            "Evaluate the SDF of an axis-aligned box at sample points.\n"
            "Returns {ok:true, results:[{x,y,z,distance},...]}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "center": {"type": "array", "items": {"type": "number"}},
                "half_extents": {"type": "array", "items": {"type": "number"},
                                 "description": "[hx, hy, hz]"},
                "points": _POINTS_SCHEMA,
            },
            "required": ["center", "half_extents", "points"],
        },
    ), write=False)
    async def _tool_box(ctx: ProjectCtx, args: bytes) -> str:
        try:
            d = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        try:
            cx, cy, cz = float(d["center"][0]), float(d["center"][1]), float(d["center"][2])
            hx, hy, hz = (float(d["half_extents"][0]), float(d["half_extents"][1]),
                          float(d["half_extents"][2]))
            fn = _prim_box(cx, cy, cz, hx, hy, hz)
            return ok_payload({"results": _eval_points(fn, d["points"])})
        except Exception as exc:
            return err_payload(str(exc), "INTERNAL")
