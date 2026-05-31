"""
NURBS-SURFACE-CROSS-SECTION
============================
Compute the planar cross-section curve C(t) of a NurbsSurface S(u,v)
intersected with a plane P defined by a point and normal.

Algorithm (Sederberg CAGD §7.3 + Patrikalakis-Maekawa "Shape Interrogation" §5):
  1. Sample S(u,v) on a (nu × nv) grid, evaluate signed distance d(u,v) to P.
  2. Walk all grid edges (u-adjacent pairs and v-adjacent pairs); detect sign
     changes  (d_A * d_B < 0  or exact zero-crossing).
  3. Refine each crossing via bisection in parameter space (5 iterations,
     positional error ≈ cell_size / 2^5 ≈ cell_size / 32).
  4. Chain ordered intersection points into polyline components using a
     neighbour-graph walk.
  5. Detect closed loops (first ≈ last point).

Public API
----------
compute_surface_cross_section(surface, plane_point, plane_normal, nu=50, nv=50)
    -> SurfaceCrossSectionResult

SurfaceCrossSectionResult dataclass:
    intersection_points_3d : list[tuple[float,float,float]]
    num_intersections       : int
    num_components          : int
    is_closed_loop          : bool   (True if ANY component is a closed loop)
    honest_caveat           : str

LLM tool: ``nurbs_compute_surface_cross_section``  (gated import).

HONEST:
  - Sample-based: sub-cell features (thin necks, tangential near-grazing
    intersections) can be missed at low nu/nv.
  - 5-iteration bisection yields ~1/32 of the initial cell size accuracy;
    not sub-pixel for very coarse grids.
  - Component ordering is greedy nearest-neighbour — may produce incorrect
    topology for surfaces with multiple interleaved loops.
  - Closed-loop detection uses a distance threshold (≤ 3× mean point spacing).

References:
  Sederberg, T.W. "Computer Aided Geometric Design" §7.3 (surface-plane
  intersection).  Patrikalakis-Maekawa "Shape Interrogation for Computer
  Aided Design and Manufacturing" §5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_evaluate


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass
class SurfaceCrossSectionResult:
    """Result of a NURBS surface / plane cross-section computation.

    Attributes
    ----------
    intersection_points_3d : list of (x, y, z) tuples
        All intersection points in world space, ordered into components.
        Points from each chain are contiguous; components are separated in
        order (component 0 first, then component 1, etc.).
    num_intersections : int
        Total number of intersection points across all components.
    num_components : int
        Number of independent polyline chains detected.
    is_closed_loop : bool
        True if any component forms a closed loop (first ≈ last point).
    honest_caveat : str
        Scope and accuracy caveats.
    """
    intersection_points_3d: List[Tuple[float, float, float]]
    num_intersections: int
    num_components: int
    is_closed_loop: bool
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_knots_clamped(n: int, degree: int) -> np.ndarray:
    """Build a clamped uniform knot vector for n control points at given degree."""
    inner = max(0, n - degree - 1)
    return np.concatenate([
        np.zeros(degree + 1),
        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
        np.ones(degree + 1),
    ])


def _eval_surface(surf: NurbsSurface, u: float, v: float) -> np.ndarray:
    """Evaluate S(u,v), clamp parameters to knot domain."""
    u0 = float(surf.knots_u[0])
    u1 = float(surf.knots_u[-1])
    v0 = float(surf.knots_v[0])
    v1 = float(surf.knots_v[-1])
    u = max(u0, min(u1, float(u)))
    v = max(v0, min(v1, float(v)))
    return surface_evaluate(surf, u, v)


def _signed_dist_plane(point: np.ndarray, n: np.ndarray, d: float) -> float:
    """Signed distance of 3D point to plane n·x = d (n is unit)."""
    return float(np.dot(n, point)) - d


def _bisect_crossing(
    surf: NurbsSurface,
    ua: float, va: float, da: float,
    ub: float, vb: float, db: float,
    n: np.ndarray, d: float,
    niters: int = 5,
) -> Tuple[float, float, np.ndarray]:
    """Bisect a sign-change edge in (u,v) space to locate the crossing.

    Parameters
    ----------
    ua, va : float  — parameter of point with signed distance da
    ub, vb : float  — parameter of point with signed distance db
    da, db : float  — signed distances (da*db <= 0)
    n, d   : plane coefficients (n·x = d)
    niters : int    — bisection iterations (5 → error ≈ cell_size/32)

    Returns
    -------
    (um, vm, point3d)  — parameter midpoint and world-space intersection
    """
    for _ in range(niters):
        um = 0.5 * (ua + ub)
        vm = 0.5 * (va + vb)
        pm = _eval_surface(surf, um, vm)
        dm = _signed_dist_plane(pm, n, d)
        if abs(dm) < 1e-15:
            return um, vm, pm
        if da * dm <= 0.0:
            ub, vb, db = um, vm, dm
        else:
            ua, va, da = um, vm, dm
    um = 0.5 * (ua + ub)
    vm = 0.5 * (va + vb)
    pm = _eval_surface(surf, um, vm)
    return um, vm, pm


# ---------------------------------------------------------------------------
# Component chaining (greedy nearest-neighbour)
# ---------------------------------------------------------------------------

def _chain_points(
    raw_pts: List[Tuple[float, float, float]],
) -> List[List[Tuple[float, float, float]]]:
    """Chain unordered intersection points into connected polyline components.

    Strategy: repeatedly build a component by extending from the current
    endpoint using the nearest unused point (greedy).  A component ends when
    either no nearby point exists OR the endpoint is close enough to the
    start (closed loop detected).

    Returns a list of components; each component is a list of (x,y,z) tuples.
    """
    if not raw_pts:
        return []

    pts = [np.array(p, dtype=float) for p in raw_pts]
    used = [False] * len(pts)
    n = len(pts)

    if n == 0:
        return []

    # Compute mean nearest-neighbour spacing to set the closure threshold.
    # Use a simple O(n^2) approach; for n≤50×50=2500 that is fine.
    if n >= 2:
        min_dists = []
        for i in range(min(n, 200)):  # sample at most 200 for speed
            best = math.inf
            for j in range(n):
                if j != i:
                    dist = float(np.linalg.norm(pts[i] - pts[j]))
                    if dist < best:
                        best = dist
            min_dists.append(best)
        mean_spacing = float(np.mean(min_dists)) if min_dists else 0.0
        closure_thresh = max(3.0 * mean_spacing, 1e-9)
        # Maximum gap to extend a chain (won't connect across large voids)
        extend_thresh = max(4.0 * mean_spacing, 1e-9)
    else:
        closure_thresh = 1e-9
        extend_thresh = math.inf

    components: List[List[Tuple[float, float, float]]] = []

    while True:
        # Find first unused point
        start_idx = -1
        for i in range(n):
            if not used[i]:
                start_idx = i
                break
        if start_idx < 0:
            break

        used[start_idx] = True
        chain = [tuple(pts[start_idx].tolist())]  # type: ignore[misc]

        while True:
            current = pts[[i for i, c in enumerate(chain)
                           if c == tuple(chain[-1])][0]] if False else np.array(chain[-1])
            # Find nearest unused point within extend_thresh
            best_dist = math.inf
            best_idx = -1
            for i in range(n):
                if not used[i]:
                    dist = float(np.linalg.norm(pts[i] - current))
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = i
            if best_idx < 0 or best_dist > extend_thresh:
                # Check if we can close the loop
                if len(chain) >= 3:
                    start_pt = np.array(chain[0])
                    if float(np.linalg.norm(current - start_pt)) <= closure_thresh:
                        chain.append(chain[0])  # close the loop
                break
            used[best_idx] = True
            chain.append(tuple(pts[best_idx].tolist()))  # type: ignore[misc]

            # Check closure
            if len(chain) >= 3:
                start_pt = np.array(chain[0])
                if float(np.linalg.norm(pts[best_idx] - start_pt)) <= closure_thresh:
                    chain.append(chain[0])  # close the loop
                    break

        components.append(chain)

    return components


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def compute_surface_cross_section(
    surface: NurbsSurface,
    plane_point: Tuple[float, float, float],
    plane_normal: Tuple[float, float, float],
    nu: int = 50,
    nv: int = 50,
) -> SurfaceCrossSectionResult:
    """Compute the planar cross-section of a NurbsSurface.

    Intersects ``surface`` with the plane defined by ``plane_point`` and
    ``plane_normal``, returning an ordered 3D polyline of intersection points.

    Algorithm (Sederberg CAGD §7.3; Patrikalakis-Maekawa §5):
      1. Sample S(u,v) on a (nu × nv) uniform grid over the knot domain.
      2. Compute signed distance d(u,v) = (S(u,v) − P) · n̂ for each sample.
      3. Walk all grid edges; detect sign changes (d_A * d_B < 0).
      4. Refine each crossing via 5 bisection iterations in (u,v) space.
      5. Chain points greedily into polyline components.

    Parameters
    ----------
    surface : NurbsSurface
        The B-spline / NURBS surface to intersect.
    plane_point : (x, y, z)
        Any point on the cutting plane.
    plane_normal : (nx, ny, nz)
        Normal vector of the cutting plane (need not be unit-length).
    nu : int
        Number of grid samples in u direction (default 50).
    nv : int
        Number of grid samples in v direction (default 50).

    Returns
    -------
    SurfaceCrossSectionResult
    """
    nu = max(2, int(nu))
    nv = max(2, int(nv))

    # Normalise plane normal
    pn = np.asarray(plane_normal, dtype=float).ravel()
    pn_norm = float(np.linalg.norm(pn))
    if pn_norm < 1e-15:
        return SurfaceCrossSectionResult(
            intersection_points_3d=[],
            num_intersections=0,
            num_components=0,
            is_closed_loop=False,
            honest_caveat="Plane normal is zero — no intersection computed.",
        )
    pn = pn / pn_norm
    pp = np.asarray(plane_point, dtype=float).ravel()
    d_plane = float(np.dot(pn, pp))

    # Parameter domain
    u0 = float(surface.knots_u[0])
    u1 = float(surface.knots_u[-1])
    v0 = float(surface.knots_v[0])
    v1 = float(surface.knots_v[-1])

    us = np.linspace(u0, u1, nu)
    vs = np.linspace(v0, v1, nv)

    # Evaluate surface and compute signed distances on grid
    pts_grid = np.empty((nu, nv, 3), dtype=float)
    sd_grid = np.empty((nu, nv), dtype=float)
    for i in range(nu):
        for j in range(nv):
            p = _eval_surface(surface, us[i], vs[j])
            pts_grid[i, j] = p[:3] if p.size >= 3 else np.pad(p, (0, 3 - p.size))
            sd_grid[i, j] = float(np.dot(pn, pts_grid[i, j])) - d_plane

    # Collect crossing points by walking grid edges
    # Edge types: u-edges (fixed j, vary i) and v-edges (fixed i, vary j)
    crossing_pts: List[Tuple[float, float, float]] = []

    # u-direction edges: (i, j) — (i+1, j)
    for i in range(nu - 1):
        for j in range(nv):
            da = sd_grid[i, j]
            db = sd_grid[i + 1, j]
            if da * db < 0.0:
                _, _, pm = _bisect_crossing(
                    surface,
                    us[i], vs[j], da,
                    us[i + 1], vs[j], db,
                    pn, d_plane,
                )
                crossing_pts.append((float(pm[0]), float(pm[1]), float(pm[2])))
            elif abs(da) < 1e-15 and abs(db) >= 1e-15:
                p = pts_grid[i, j]
                crossing_pts.append((float(p[0]), float(p[1]), float(p[2])))

    # v-direction edges: (i, j) — (i, j+1)
    for i in range(nu):
        for j in range(nv - 1):
            da = sd_grid[i, j]
            db = sd_grid[i, j + 1]
            if da * db < 0.0:
                _, _, pm = _bisect_crossing(
                    surface,
                    us[i], vs[j], da,
                    us[i], vs[j + 1], db,
                    pn, d_plane,
                )
                crossing_pts.append((float(pm[0]), float(pm[1]), float(pm[2])))
            elif abs(da) < 1e-15 and abs(db) >= 1e-15:
                p = pts_grid[i, j]
                crossing_pts.append((float(p[0]), float(p[1]), float(p[2])))

    # Remove near-duplicates (within tight tolerance)
    deduped: List[Tuple[float, float, float]] = []
    tol_dedup = 1e-9
    for pt in crossing_pts:
        pnp = np.array(pt)
        dup = False
        for existing in deduped:
            if float(np.linalg.norm(pnp - np.array(existing))) < tol_dedup:
                dup = True
                break
        if not dup:
            deduped.append(pt)

    if not deduped:
        return SurfaceCrossSectionResult(
            intersection_points_3d=[],
            num_intersections=0,
            num_components=0,
            is_closed_loop=False,
            honest_caveat=(
                "No intersection found. Either the plane does not intersect the "
                "surface within the current (nu, nv) grid, or the intersection "
                "is sub-cell-size. Increase nu/nv for finer sampling."
            ),
        )

    # Chain into components
    components = _chain_points(deduped)
    num_components = len(components)

    # Flatten component list into ordered result
    flat_pts: List[Tuple[float, float, float]] = []
    is_any_closed = False
    for comp in components:
        if len(comp) >= 3 and comp[0] == comp[-1]:
            is_any_closed = True
        flat_pts.extend(comp)

    honest_caveat = (
        "Sample-based intersection (nu={nu}, nv={nv}): sub-cell features "
        "(thin necks, tangential near-grazing intersections) may be missed. "
        "Bisection accuracy ≈ cell_size/32. Component ordering is greedy "
        "nearest-neighbour — may mis-order interleaved loops. "
        "Closed-loop detection uses 3× mean point spacing threshold. "
        "Reference: Sederberg CAGD §7.3; Patrikalakis-Maekawa §5."
    ).format(nu=nu, nv=nv)

    return SurfaceCrossSectionResult(
        intersection_points_3d=flat_pts,
        num_intersections=len(flat_pts),
        num_components=num_components,
        is_closed_loop=is_any_closed,
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# LLM tool registration (gated import — mirrors section_contour.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _cross_section_spec = ToolSpec(
        name="nurbs_compute_surface_cross_section",
        description=(
            "Compute the planar cross-section curve of a NurbsSurface S(u,v)\n"
            "intersected with a plane P (point + normal).\n"
            "\n"
            "Algorithm (Sederberg CAGD §7.3; Patrikalakis-Maekawa §5):\n"
            "  1. Sample S(u,v) on a (nu × nv) grid.\n"
            "  2. Compute signed distance d(u,v) = (S − P) · n̂ for each sample.\n"
            "  3. Walk grid edges; detect sign changes.\n"
            "  4. Refine each crossing via 5 bisection iterations in (u,v) space.\n"
            "  5. Chain points into ordered polyline components.\n"
            "\n"
            "Returns:\n"
            "  intersection_points_3d : list of [x,y,z] — ordered 3D polyline\n"
            "  num_intersections      : int — total intersection points\n"
            "  num_components         : int — number of independent chains\n"
            "  is_closed_loop         : bool — True if any component forms a loop\n"
            "  honest_caveat          : str — accuracy and scope caveats\n"
            "\n"
            "HONEST: Sample-based — sub-cell features may be missed at low nu/nv.\n"
            "Bisection accuracy ≈ cell_size/32 (5 iterations).\n"
            "Never raises — returns {ok:false, reason} for invalid inputs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u": {
                    "type": "integer",
                    "description": "B-spline degree in u direction (>= 1).",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "B-spline degree in v direction (>= 1).",
                },
                "control_points": {
                    "type": "array",
                    "description": (
                        "Flat list of [x,y,z] control points, row-major "
                        "(num_u * num_v entries)."
                    ),
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "num_u": {
                    "type": "integer",
                    "description": "Number of control points in u direction.",
                },
                "num_v": {
                    "type": "integer",
                    "description": "Number of control points in v direction.",
                },
                "plane_point": {
                    "type": "array",
                    "description": "Any point on the cutting plane [x, y, z].",
                    "items": {"type": "number"},
                },
                "plane_normal": {
                    "type": "array",
                    "description": "Plane normal vector [nx, ny, nz] (need not be unit).",
                    "items": {"type": "number"},
                },
                "nu": {
                    "type": "integer",
                    "description": "Grid samples in u direction (default 50).",
                },
                "nv": {
                    "type": "integer",
                    "description": "Grid samples in v direction (default 50).",
                },
                "knots_u": {
                    "type": "array",
                    "description": "Optional knot vector in u (clamped uniform generated if omitted).",
                    "items": {"type": "number"},
                },
                "knots_v": {
                    "type": "array",
                    "description": "Optional knot vector in v (clamped uniform generated if omitted).",
                    "items": {"type": "number"},
                },
                "weights": {
                    "type": "array",
                    "description": "Optional flat list of (num_u * num_v) rational weights.",
                    "items": {"type": "number"},
                },
            },
            "required": [
                "degree_u", "degree_v", "control_points", "num_u", "num_v",
                "plane_point", "plane_normal",
            ],
        },
    )

    @register(_cross_section_spec)
    async def _tool_nurbs_compute_surface_cross_section(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        degree_u = a.get("degree_u")
        degree_v = a.get("degree_v")
        raw_cp = a.get("control_points", [])
        num_u = a.get("num_u")
        num_v = a.get("num_v")
        plane_point = a.get("plane_point")
        plane_normal = a.get("plane_normal")
        nu_grid = int(a.get("nu") or 50)
        nv_grid = int(a.get("nv") or 50)

        if (degree_u is None or degree_v is None or not raw_cp
                or not num_u or not num_v
                or plane_point is None or plane_normal is None):
            return err_payload(
                "degree_u, degree_v, control_points, num_u, num_v, "
                "plane_point, plane_normal are required",
                "BAD_ARGS",
            )

        try:
            degree_u = int(degree_u)
            degree_v = int(degree_v)
            num_u = int(num_u)
            num_v = int(num_v)
        except (TypeError, ValueError) as exc:
            return err_payload(f"degree/num values must be integers: {exc}", "BAD_ARGS")

        if degree_u < 1 or degree_v < 1:
            return err_payload("degree_u and degree_v must be >= 1", "BAD_ARGS")
        if num_u < 2 or num_v < 2:
            return err_payload("num_u and num_v must be >= 2", "BAD_ARGS")
        if len(raw_cp) != num_u * num_v:
            return err_payload(
                f"control_points length ({len(raw_cp)}) != num_u*num_v ({num_u*num_v})",
                "BAD_ARGS",
            )

        try:
            cp_flat = np.array(raw_cp, dtype=float)
            if cp_flat.ndim == 1:
                cp_flat = cp_flat.reshape(-1, 3)
            cp = cp_flat.reshape(num_u, num_v, cp_flat.shape[-1])
        except Exception as exc:
            return err_payload(f"invalid control_points: {exc}", "BAD_ARGS")

        raw_ku = a.get("knots_u")
        raw_kv = a.get("knots_v")

        def _clamped_knots(n: int, deg: int) -> np.ndarray:
            inner = max(0, n - deg - 1)
            return np.concatenate([
                np.zeros(deg + 1),
                np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                np.ones(deg + 1),
            ])

        try:
            knots_u = (np.array(raw_ku, dtype=float)
                       if raw_ku is not None else _clamped_knots(num_u, degree_u))
            knots_v = (np.array(raw_kv, dtype=float)
                       if raw_kv is not None else _clamped_knots(num_v, degree_v))
        except Exception as exc:
            return err_payload(f"invalid knots: {exc}", "BAD_ARGS")

        raw_w = a.get("weights")
        weights = None
        if raw_w is not None:
            try:
                weights = np.array(raw_w, dtype=float).reshape(num_u, num_v)
            except Exception as exc:
                return err_payload(f"invalid weights: {exc}", "BAD_ARGS")

        try:
            surf = NurbsSurface(
                degree_u=degree_u,
                degree_v=degree_v,
                control_points=cp,
                knots_u=knots_u,
                knots_v=knots_v,
                weights=weights,
            )
        except Exception as exc:
            return err_payload(f"could not construct NurbsSurface: {exc}", "BAD_ARGS")

        try:
            result = compute_surface_cross_section(
                surf,
                plane_point=tuple(float(x) for x in plane_point),  # type: ignore[arg-type]
                plane_normal=tuple(float(x) for x in plane_normal),  # type: ignore[arg-type]
                nu=nu_grid,
                nv=nv_grid,
            )
        except Exception as exc:
            return err_payload(f"compute_surface_cross_section failed: {exc}", "OP_FAILED")

        return ok_payload({
            "intersection_points_3d": [list(p) for p in result.intersection_points_3d],
            "num_intersections": result.num_intersections,
            "num_components": result.num_components,
            "is_closed_loop": result.is_closed_loop,
            "honest_caveat": result.honest_caveat,
        })
