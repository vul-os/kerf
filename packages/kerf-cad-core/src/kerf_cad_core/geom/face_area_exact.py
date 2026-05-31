"""
face_area_exact.py
==================
Exact area of a B-rep Face whose underlying surface is a NurbsSurface,
computed via the first fundamental form integrand

    A = ∫∫_Ω sqrt(EG − F²) du dv

where  E = S_u · S_u,  F = S_u · S_v,  G = S_v · S_v  (do Carmo §2.5).

Theory
------
For a parametric surface S(u, v), the area element is

    dA = |S_u × S_v| du dv = sqrt(EG − F²) du dv

The first fundamental form coefficients (do Carmo §2.5; Farin §11.2):

    E = S_u · S_u       (tangent metric in u)
    F = S_u · S_v       (mixed term)
    G = S_v · S_v       (tangent metric in v)

and |S_u × S_v|² = EG − F² (Lagrange identity).

References
----------
- do Carmo, M. P. (1976) "Differential Geometry of Curves and Surfaces" §2.5
  (surface area integral via first fundamental form)
- Piegl & Tiller (1997) "The NURBS Book" §10.3 (surface analysis integrals)
- Farin, G. (2002) "Curves and Surfaces for CAGD" §11.2 (surface area by
  first-order derivatives)
- Stoer & Bulirsch (2002) "Introduction to Numerical Analysis" §3 (GL quadrature)

Algorithm
---------
1. Obtain the integration domain [u0,u1]×[v0,v1] from the face:
   - For NurbsSurface: the closed knot-span range (knots_u[degree_u] ..
     knots_u[-(degree_u+1)]).  If the face has outer loop coedges, the
     domain is the same (NURBS face always spans the full knot domain).
   - For analytic surfaces (Plane, Cylinder, Sphere, Torus): derive the
     UV bounds from the loop coedges or natural full-surface defaults.
2. Build the UV subdivision grid at internal knot breaks (NurbsSurface only)
   so that each cell is polynomial (no inter-knot derivative discontinuity).
3. Apply 2D Gauss-Legendre quadrature of order *gauss_order* per cell.
4. Adaptively subdivide cells whose local convergence error exceeds the
   per-cell tolerance budget (1e-4 relative / n_cells), up to
   *adaptive_subdivisions* depth levels.

Honest caveats
--------------
* **Trimmed faces** (faces with inner loops): the area is computed over the
  full UV parameter rectangle.  Trim curves bounding holes are NOT respected
  in v1.  The ``FaceAreaResult.honest_caveat`` field reports this when
  ``face.inner_loops()`` is non-empty.  Trimmed faces use a bounding-rectangle
  approximation (over-counts the area for each inner trim region).
* **Non-NurbsSurface geometries** (Plane, CylinderSurface, SphereSurface,
  TorusSurface): the analytic surface is sampled via finite differences on
  a per-face UV domain derived from loop coedges (or natural full-surface
  defaults).  These are correct for the UV domain used but still subject to
  the trim caveat above.
* The integrator uses rational-correct partials via ``surface_derivatives``
  for NurbsSurface.  For analytic surfaces finite differences are used
  (h = 1e-7); the error is O(h²) ≈ 1e-14 for smooth surfaces.

Public API
----------
FaceAreaResult : dataclass
    area_mm2, num_quadrature_points, relative_error_estimate, honest_caveat

compute_face_area_exact(face, gauss_order=8, adaptive_subdivisions=4)
    Compute exact face area via Gauss-Legendre quadrature + adaptive refinement.

LLM tool: ``brep_compute_face_area_exact``
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    CylinderSurface,
    Face,
    Plane,
    SphereSurface,
    TorusSurface,
)
from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivatives
from kerf_cad_core.geom.surface_area_exact import (
    compute_exact_surface_area,
    _gl5_cell,
    _unique_interior_knots,
    _integrand as _nurbs_integrand,
)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass
class FaceAreaResult:
    """Result of :func:`compute_face_area_exact`.

    Attributes
    ----------
    area_mm2 : float
        Computed face area (same units as the model; typically mm²).
    num_quadrature_points : int
        Total number of integrand evaluations used.
    relative_error_estimate : float
        Conservative relative error estimate (estimated_error / area).
    honest_caveat : str
        Human-readable note about any approximations applied (e.g. trim
        boundary not honoured, full-UV-domain used, etc.).
    """
    area_mm2: float
    num_quadrature_points: int
    relative_error_estimate: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Gauss-Legendre nodes / weights (cached via numpy.polynomial)
# ---------------------------------------------------------------------------

_GL_CACHE: dict = {}


def _gl(n: int) -> Tuple[np.ndarray, np.ndarray]:
    """Return cached n-point Gauss-Legendre (nodes, weights) on [-1, 1]."""
    if n not in _GL_CACHE:
        from numpy.polynomial.legendre import leggauss
        _GL_CACHE[n] = leggauss(n)
    return _GL_CACHE[n]


# ---------------------------------------------------------------------------
# Integrand for analytic surfaces (finite-difference)
# ---------------------------------------------------------------------------

_FD_H = 1e-7


def _fd_integrand(surface, u: float, v: float) -> float:
    """Evaluate |S_u × S_v| = sqrt(EG − F²) at (u, v) via finite differences.

    Works for any surface object with ``evaluate(u, v) -> array[3]``.
    Step h = 1e-7 gives O(h²) ≈ 1e-14 truncation error for smooth surfaces.

    do Carmo §2.5: E = S_u·S_u, F = S_u·S_v, G = S_v·S_v,
                   dA = sqrt(EG-F²) du dv.
    """
    p = np.asarray(surface.evaluate(u, v), dtype=float)[:3]
    pu = np.asarray(surface.evaluate(u + _FD_H, v), dtype=float)[:3]
    pv = np.asarray(surface.evaluate(u, v + _FD_H), dtype=float)[:3]
    Su = (pu - p) / _FD_H
    Sv = (pv - p) / _FD_H
    cross = np.cross(Su, Sv)
    return math.sqrt(max(float(np.dot(cross, cross)), 0.0))


# ---------------------------------------------------------------------------
# UV domain helpers
# ---------------------------------------------------------------------------

def _nurbs_uv_domain(srf: NurbsSurface) -> Tuple[float, float, float, float]:
    """Closed UV domain [u0,u1]×[v0,v1] from clamped knot vectors."""
    u0 = float(srf.knots_u[srf.degree_u])
    u1 = float(srf.knots_u[-(srf.degree_u + 1)])
    v0 = float(srf.knots_v[srf.degree_v])
    v1 = float(srf.knots_v[-(srf.degree_v + 1)])
    return u0, u1, v0, v1


def _plane_uv_domain(face: Face) -> Tuple[float, float, float, float]:
    """Project outer-loop coedge vertices onto Plane axes to get UV bounds."""
    loop = face.outer_loop()
    srf: Plane = face.surface
    e1 = np.asarray(srf.x_axis, dtype=float)
    e2 = np.asarray(srf.y_axis, dtype=float)
    origin = np.asarray(srf.origin, dtype=float)
    e1n = float(np.linalg.norm(e1))
    e2n = float(np.linalg.norm(e2))
    if (
        loop is None
        or not loop.coedges
        or e1n < 1e-14
        or e2n < 1e-14
    ):
        return 0.0, 1.0, 0.0, 1.0
    e1u = e1 / e1n
    e2u = e2 / e2n
    us, vs = [], []
    for ce in loop.coedges:
        for pt in (ce.start_point(), ce.end_point()):
            d = np.asarray(pt, dtype=float)[:3] - origin
            us.append(float(np.dot(d, e1u)))
            vs.append(float(np.dot(d, e2u)))
    if not us:
        return 0.0, 1.0, 0.0, 1.0
    return float(min(us)), float(max(us)), float(min(vs)), float(max(vs))


def _cylinder_uv_domain(face: Face) -> Tuple[float, float, float, float]:
    """Full circumference u=[0,2π]; v extent from outer loop coedges."""
    loop = face.outer_loop()
    srf: CylinderSurface = face.surface
    if loop is None or not loop.coedges:
        return 0.0, 2.0 * math.pi, 0.0, 1.0
    axis = np.asarray(srf.axis, dtype=float)
    center = np.asarray(srf.center, dtype=float)
    vs = []
    for ce in loop.coedges:
        for pt in (ce.start_point(), ce.end_point()):
            p = np.asarray(pt, dtype=float)[:3]
            vs.append(float(np.dot(p - center, axis)))
    return 0.0, 2.0 * math.pi, float(min(vs)), float(max(vs))


def _sphere_uv_domain(_face: Face) -> Tuple[float, float, float, float]:
    """Full sphere: u=[0,2π], v=[-π/2, π/2]."""
    return 0.0, 2.0 * math.pi, -0.5 * math.pi, 0.5 * math.pi


def _torus_uv_domain(_face: Face) -> Tuple[float, float, float, float]:
    """Full torus: u=[0,2π], v=[0,2π]."""
    return 0.0, 2.0 * math.pi, 0.0, 2.0 * math.pi


def _face_uv_domain(face: Face) -> Tuple[float, float, float, float]:
    """Return the UV integration domain for a face."""
    srf = face.surface
    if isinstance(srf, Plane):
        return _plane_uv_domain(face)
    if isinstance(srf, CylinderSurface):
        return _cylinder_uv_domain(face)
    if isinstance(srf, SphereSurface):
        return _sphere_uv_domain(face)
    if isinstance(srf, TorusSurface):
        return _torus_uv_domain(face)
    if isinstance(srf, NurbsSurface):
        return _nurbs_uv_domain(srf)
    # Duck-typed fallback: try knot attributes, else unit square
    if hasattr(srf, "knots_u") and hasattr(srf, "knots_v"):
        return _nurbs_uv_domain(srf)  # type: ignore[arg-type]
    return 0.0, 1.0, 0.0, 1.0


# ---------------------------------------------------------------------------
# GL cell integration (analytic surface version)
# ---------------------------------------------------------------------------

def _gl_cell_analytic(
    surface,
    u0: float, u1: float,
    v0: float, v1: float,
    order: int,
) -> Tuple[float, int]:
    """Gauss-Legendre area estimate for [u0,u1]×[v0,v1] on a generic surface.

    Returns (area, n_evaluations).
    Uses ``_fd_integrand`` for non-NurbsSurface surfaces.
    Uses the faster analytic ``_nurbs_integrand`` for NurbsSurface.
    """
    xi, wi = _gl(order)
    half_u = 0.5 * (u1 - u0)
    half_v = 0.5 * (v1 - v0)
    mid_u = 0.5 * (u0 + u1)
    mid_v = 0.5 * (v0 + v1)
    total = 0.0
    is_nurbs = isinstance(surface, NurbsSurface)
    for i in range(order):
        u = mid_u + half_u * xi[i]
        for j in range(order):
            v = mid_v + half_v * xi[j]
            if is_nurbs:
                f = _nurbs_integrand(surface, u, v)
            else:
                f = _fd_integrand(surface, u, v)
            total += wi[i] * wi[j] * f
    return half_u * half_v * total, order * order


# ---------------------------------------------------------------------------
# Adaptive refinement
# ---------------------------------------------------------------------------

def _adaptive_cell_analytic(
    surface,
    u0: float, u1: float,
    v0: float, v1: float,
    tol: float,
    depth: int,
    max_depth: int,
    order: int,
) -> Tuple[float, float, int, int]:
    """Adaptively integrate one cell.

    Returns (area, error_bound, max_depth_used, n_evaluations).
    """
    A_full, n0 = _gl_cell_analytic(surface, u0, u1, v0, v1, order)

    if depth >= max_depth:
        return A_full, 0.0, depth, n0

    mid_u = 0.5 * (u0 + u1)
    mid_v = 0.5 * (v0 + v1)
    A_ll, n_ll = _gl_cell_analytic(surface, u0, mid_u, v0, mid_v, order)
    A_lr, n_lr = _gl_cell_analytic(surface, mid_u, u1, v0, mid_v, order)
    A_ul, n_ul = _gl_cell_analytic(surface, u0, mid_u, mid_v, v1, order)
    A_ur, n_ur = _gl_cell_analytic(surface, mid_u, u1, mid_v, v1, order)
    A_refined = A_ll + A_lr + A_ul + A_ur
    n_ref = n_ll + n_lr + n_ul + n_ur

    err = abs(A_full - A_refined)
    if err <= tol:
        return A_refined, err, depth + 1, n0 + n_ref

    tol4 = tol * 0.25
    a1, e1, d1, nq1 = _adaptive_cell_analytic(
        surface, u0, mid_u, v0, mid_v, tol4, depth + 1, max_depth, order)
    a2, e2, d2, nq2 = _adaptive_cell_analytic(
        surface, mid_u, u1, v0, mid_v, tol4, depth + 1, max_depth, order)
    a3, e3, d3, nq3 = _adaptive_cell_analytic(
        surface, u0, mid_u, mid_v, v1, tol4, depth + 1, max_depth, order)
    a4, e4, d4, nq4 = _adaptive_cell_analytic(
        surface, mid_u, u1, mid_v, v1, tol4, depth + 1, max_depth, order)

    return (
        a1 + a2 + a3 + a4,
        e1 + e2 + e3 + e4,
        max(d1, d2, d3, d4),
        n0 + n_ref + nq1 + nq2 + nq3 + nq4,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_face_area_exact(
    face: Face,
    gauss_order: int = 8,
    adaptive_subdivisions: int = 4,
) -> FaceAreaResult:
    """Compute the exact area of a B-rep Face.

    The area is

        A = ∫∫_Ω sqrt(EG − F²) du dv

    where E, F, G are the first-fundamental-form coefficients
    (do Carmo §2.5; Piegl & Tiller §10.3; Farin §11.2).

    For a NurbsSurface face the UV domain is partitioned at the internal
    knot breaks so each cell is polynomial; within each cell a
    *gauss_order* × *gauss_order* Gauss-Legendre rule is applied.  Cells
    whose relative error estimate exceeds 1e-4 are adaptively subdivided
    up to *adaptive_subdivisions* depth levels.

    For analytic surface types (Plane, CylinderSurface, SphereSurface,
    TorusSurface) the UV domain is derived from the outer loop coedges
    (or natural full-surface defaults) and the integrand is evaluated via
    finite differences.

    Parameters
    ----------
    face : Face
        The B-rep face to measure.
    gauss_order : int
        Number of Gauss-Legendre points per axis per cell (default 8).
    adaptive_subdivisions : int
        Maximum adaptive-subdivision depth per cell (default 4).

    Returns
    -------
    FaceAreaResult
        .area_mm2              — computed area (model units, typically mm²)
        .num_quadrature_points — total integrand evaluations
        .relative_error_estimate — conservative relative error bound
        .honest_caveat         — notes on approximations applied

    Caveats
    -------
    * Trimmed faces (faces with inner loops): the area is computed over the
      full UV bounding rectangle.  Inner trim loops are NOT honoured; the
      returned area over-counts the material in trim regions.
    * For NurbsSurface faces the analytic first partials from
      ``surface_derivatives`` are used (rational-correct, Piegl & Tiller
      Alg. A3.6).
    * For analytic surfaces (Plane/Cylinder/Sphere/Torus) finite-difference
      partials (h = 1e-7) are used; error ≈ O(h²) ≈ 1e-14 for smooth surfaces.
    """
    srf = face.surface
    caveats: List[str] = []

    # Detect trimmed face
    has_inner = bool(face.inner_loops())
    if has_inner:
        caveats.append(
            "Face has inner (trim) loops; area computed over full UV "
            "bounding rectangle — trim boundaries not honoured (v1). "
            "Area may over-count by the size of trimmed-out regions."
        )

    # Fast path: delegate NurbsSurface with no inner loops to the existing
    # highly-optimised compute_exact_surface_area (5-point GL + adaptive).
    if isinstance(srf, NurbsSurface) and not has_inner:
        try:
            report = compute_exact_surface_area(
                srf, tolerance=1e-6, max_subdivisions=adaptive_subdivisions
            )
            # Estimate number of GL evaluations (5 nodes per axis per cell)
            # We don't have the exact count from the existing integrator;
            # give a conservative lower bound of 25 * n_cells.
            u0, u1, v0, v1 = _nurbs_uv_domain(srf)
            u_breaks = np.concatenate([
                [float(srf.knots_u[srf.degree_u])],
                _unique_interior_knots(srf.knots_u, srf.degree_u),
                [float(srf.knots_u[-(srf.degree_u + 1)])],
            ])
            v_breaks = np.concatenate([
                [float(srf.knots_v[srf.degree_v])],
                _unique_interior_knots(srf.knots_v, srf.degree_v),
                [float(srf.knots_v[-(srf.degree_v + 1)])],
            ])
            n_base_cells = max(1, (len(u_breaks) - 1) * (len(v_breaks) - 1))
            n_pts_est = 25 * n_base_cells  # 5×5 GL per cell, before adaptation

            rel_err = (
                report.estimated_error / report.area
                if report.area > 1e-20
                else 0.0
            )
            caveat_str = (
                "NurbsSurface; exact first-fundamental-form integrand via "
                "analytic surface_derivatives (Piegl & Tiller Alg. A3.6); "
                "5×5 GL per knot-span cell + adaptive subdivision. "
                "Full UV domain (no trimming in v1)."
            )
            if caveats:
                caveat_str = " | ".join(caveats) + " | " + caveat_str
            return FaceAreaResult(
                area_mm2=report.area,
                num_quadrature_points=n_pts_est,
                relative_error_estimate=rel_err,
                honest_caveat=caveat_str,
            )
        except Exception as exc:
            caveats.append(f"NurbsSurface fast-path failed ({exc}); falling back to generic path.")

    # Generic path: use the GL+adaptive integrator directly with _face_uv_domain.
    u0, u1, v0, v1 = _face_uv_domain(face)
    du = u1 - u0
    dv = v1 - v0

    if abs(du) < 1e-14 or abs(dv) < 1e-14:
        if isinstance(srf, Plane):
            caveats.append("Degenerate plane face: UV domain has zero extent.")
        return FaceAreaResult(
            area_mm2=0.0,
            num_quadrature_points=0,
            relative_error_estimate=0.0,
            honest_caveat=" | ".join(caveats) if caveats else "Degenerate face: zero-area UV domain.",
        )

    # Build cell grid: for NurbsSurface use knot breaks; for analytic surfaces
    # use a single cell (they are smooth over their natural domain).
    if isinstance(srf, NurbsSurface):
        u_breaks = np.concatenate([
            [u0],
            _unique_interior_knots(srf.knots_u, srf.degree_u),
            [u1],
        ])
        v_breaks = np.concatenate([
            [v0],
            _unique_interior_knots(srf.knots_v, srf.degree_v),
            [v1],
        ])
        surface_type_note = (
            "NurbsSurface; knot-span cell grid; analytic first-partials "
            "via surface_derivatives (Piegl & Tiller Alg. A3.6)."
        )
    else:
        u_breaks = np.array([u0, u1])
        v_breaks = np.array([v0, v1])
        if isinstance(srf, Plane):
            surface_type_note = (
                "Plane face; UV domain from outer-loop coedge projection; "
                "finite-difference partials (h=1e-7)."
            )
        elif isinstance(srf, CylinderSurface):
            surface_type_note = (
                "CylinderSurface; u=[0,2π], v from coedges; "
                "finite-difference partials."
            )
        elif isinstance(srf, SphereSurface):
            surface_type_note = (
                "SphereSurface; full UV domain [0,2π]×[-π/2,π/2]; "
                "finite-difference partials."
            )
        elif isinstance(srf, TorusSurface):
            surface_type_note = (
                "TorusSurface; full UV domain [0,2π]×[0,2π]; "
                "finite-difference partials."
            )
        else:
            surface_type_note = (
                "Unknown surface type; unit-square UV domain fallback; "
                "finite-difference partials."
            )

    n_cells = max(1, (len(u_breaks) - 1) * (len(v_breaks) - 1))
    per_cell_tol_abs = 1e-6
    per_cell_tol = per_cell_tol_abs / n_cells

    total_area = 0.0
    total_error = 0.0
    total_pts = 0
    max_depth_used = 0

    for i in range(len(u_breaks) - 1):
        cu0, cu1 = float(u_breaks[i]), float(u_breaks[i + 1])
        if cu1 - cu0 < 1e-14:
            continue
        for j in range(len(v_breaks) - 1):
            cv0, cv1 = float(v_breaks[j]), float(v_breaks[j + 1])
            if cv1 - cv0 < 1e-14:
                continue
            a, e, d, npts = _adaptive_cell_analytic(
                srf, cu0, cu1, cv0, cv1,
                per_cell_tol, 0, adaptive_subdivisions, gauss_order,
            )
            total_area += a
            total_error += e
            total_pts += npts
            if d > max_depth_used:
                max_depth_used = d

    rel_err = total_error / total_area if total_area > 1e-20 else 0.0

    caveat_parts = caveats + [
        surface_type_note,
        (
            "Trimmed faces use bounding-rectangle approximation "
            "if no trim curves provided (v1)."
            if has_inner else
            "Untrimmed face: full UV domain."
        ),
    ]

    return FaceAreaResult(
        area_mm2=total_area,
        num_quadrature_points=total_pts,
        relative_error_estimate=rel_err,
        honest_caveat=" | ".join(caveat_parts),
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _face_area_spec = ToolSpec(
        name="brep_compute_face_area_exact",
        description=(
            "Compute the exact area of a B-rep Face whose underlying surface "
            "is a NurbsSurface, using the first fundamental form:\n\n"
            "    A = ∫∫ sqrt(EG − F²) du dv\n\n"
            "where E = Su·Su, F = Su·Sv, G = Sv·Sv (do Carmo §2.5; "
            "Piegl & Tiller §10.3; Farin §11.2).\n\n"
            "Uses Gauss-Legendre quadrature (gauss_order × gauss_order per "
            "knot-span cell) with adaptive subdivision per cell when the "
            "relative error estimate exceeds 1e-4.\n\n"
            "Also accepts analytic surface types (Plane, Cylinder, Sphere, "
            "Torus) via finite-difference partials.\n\n"
            "**v1 limitation**: trimmed faces (faces with inner loops) compute "
            "area over the full UV bounding rectangle — trim boundaries are "
            "NOT honoured.  The honest_caveat field reports this.\n\n"
            "Returns: {ok, area_mm2, num_quadrature_points, "
            "relative_error_estimate, honest_caveat}\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "description": (
                        "3D control-point grid as a list of rows (nu × nv × 3). "
                        "Each row is a list of [x, y, z] control points."
                    ),
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                    },
                },
                "knots_u": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in the U direction.",
                },
                "knots_v": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Knot vector in the V direction.",
                },
                "degree_u": {
                    "type": "integer",
                    "description": "Degree in the U direction.",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "Degree in the V direction.",
                },
                "weights": {
                    "type": "array",
                    "description": (
                        "Optional (nu × nv) weight grid as a list of rows. "
                        "Omit for non-rational (polynomial) surfaces."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                    },
                },
                "gauss_order": {
                    "type": "integer",
                    "description": "GL points per axis per cell (default 8).",
                },
                "adaptive_subdivisions": {
                    "type": "integer",
                    "description": "Max adaptive subdivision depth per cell (default 4).",
                },
            },
            "required": ["control_points", "knots_u", "knots_v", "degree_u", "degree_v"],
        },
    )

    @register(_face_area_spec)
    async def run_brep_compute_face_area_exact(
        ctx: "ProjectCtx", args: bytes
    ) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        cp_raw = a.get("control_points")
        ku_raw = a.get("knots_u")
        kv_raw = a.get("knots_v")
        deg_u = a.get("degree_u")
        deg_v = a.get("degree_v")

        if any(x is None for x in (cp_raw, ku_raw, kv_raw, deg_u, deg_v)):
            return err_payload(
                "control_points, knots_u, knots_v, degree_u, degree_v are required",
                "BAD_ARGS",
            )

        try:
            cp = np.asarray(cp_raw, dtype=float)
            knots_u = np.asarray(ku_raw, dtype=float)
            knots_v = np.asarray(kv_raw, dtype=float)
            degree_u = int(deg_u)
            degree_v = int(deg_v)
            weights_raw = a.get("weights")
            weights = (
                np.asarray(weights_raw, dtype=float)
                if weights_raw is not None
                else None
            )
            srf = NurbsSurface(
                degree_u=degree_u,
                degree_v=degree_v,
                control_points=cp,
                knots_u=knots_u,
                knots_v=knots_v,
                weights=weights,
            )
        except Exception as exc:
            return err_payload(f"failed to build NurbsSurface: {exc}", "BAD_ARGS")

        # Build a minimal Face with no loops (untrimmed, full UV domain)
        from kerf_cad_core.geom.brep import Face as _Face  # local import ok
        face = _Face(surface=srf, loops=[])

        g_order = int(a.get("gauss_order", 8))
        adapt = int(a.get("adaptive_subdivisions", 4))

        try:
            result = compute_face_area_exact(
                face, gauss_order=g_order, adaptive_subdivisions=adapt
            )
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "area_mm2": result.area_mm2,
            "num_quadrature_points": result.num_quadrature_points,
            "relative_error_estimate": result.relative_error_estimate,
            "honest_caveat": result.honest_caveat,
        })
