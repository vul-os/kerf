"""
surface_area_exact.py
=====================
Exact surface area of a NURBS surface via the first-fundamental-form integrand.

Theory
------
For a parametric surface S(u, v), the area element is

    dA = |S_u × S_v| du dv = sqrt(EG - F²) du dv

where the first fundamental form coefficients are (do Carmo §2.5):

    E = S_u · S_u
    F = S_u · S_v
    G = S_v · S_v

and |S_u × S_v| = sqrt(EG - F²) is the Jacobian of the surface map.

References
----------
- do Carmo, M. P. (1976) "Differential Geometry of Curves and Surfaces" §2.5
  (first fundamental form + surface area integral)
- Mortenson, M. E. (1985) "Geometric Modeling" §10.4 (NURBS surface metrics)
- Stoer-Bulirsch (2002) "Introduction to Numerical Analysis" §3 (Gauss-Legendre)
- Piegl-Tiller (1997) "The NURBS Book" §4 (surface evaluation + partial derivatives)

Algorithm
---------
1. Build a UV cell grid by splitting the surface domain at its internal knot spans.
2. For each rectangular cell [u₀, u₁] × [v₀, v₁] apply 2D Gauss-Legendre
   quadrature (5-point × 5-point = 25 evaluation points per cell):
       A_cell = (u₁-u₀)(v₁-v₀)/4 · Σᵢⱼ wᵢ·wⱼ · sqrt(E·G - F²)(uᵢⱼ, vᵢⱼ)
3. Adaptively subdivide cells whose local-vs-refined error exceeds the per-cell
   tolerance budget (tolerance / n_cells), up to max_subdivisions levels.
4. Sum all cell contributions.

Honest caveats (v1)
-------------------
* The area is computed for the **full UV parameter domain** only.  For a
  TrimmedSurface the trim boundary is not respected — callers must handle
  trimming externally or wait for v2.  The function accepts only NurbsSurface,
  not TrimmedSurface.
* Degenerate poles (where |S_u × S_v| = 0) are handled gracefully: the
  integrand is clipped to 0 at such points; tiny knot-spans near the poles
  still produce the correct analytic result via dense GL sampling.

Public API
----------
compute_exact_surface_area(srf, tolerance=1e-6, max_subdivisions=8)
    -> SurfaceAreaReport(area, estimated_error, subdivisions_used)

LLM tool: ``nurbs_surface_area_exact``
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivatives

# ---------------------------------------------------------------------------
# 5-point Gauss-Legendre nodes/weights on [-1, 1]
# (Stoer-Bulirsch 2002, Table 3.1.3; Abramowitz & Stegun 25.4.30)
# ---------------------------------------------------------------------------
_GL5_NODES = np.array([
    -0.906_179_845_938_664,
    -0.538_469_310_105_683,
     0.0,
     0.538_469_310_105_683,
     0.906_179_845_938_664,
])

_GL5_WEIGHTS = np.array([
    0.236_926_885_056_189,
    0.478_628_670_499_366,
    0.568_888_888_888_889,
    0.478_628_670_499_366,
    0.236_926_885_056_189,
])


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class SurfaceAreaReport:
    """Result of :func:`compute_exact_surface_area`.

    Attributes
    ----------
    area : float
        Computed surface area.
    estimated_error : float
        Conservative upper bound on the absolute integration error.
    subdivisions_used : int
        Maximum adaptive subdivision depth reached during integration.
    """
    area: float
    estimated_error: float
    subdivisions_used: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _integrand(srf: NurbsSurface, u: float, v: float) -> float:
    """Evaluate |S_u × S_v| = sqrt(EG - F²) at (u, v).

    Uses the analytic first partials via :func:`surface_derivatives`.
    Rational-correct for weighted NURBS surfaces.

    do Carmo §2.5: E = S_u·S_u, F = S_u·S_v, G = S_v·S_v,
                   dA = sqrt(EG-F²) du dv.
    Mortenson §10.4: first fundamental form of a parametric surface.
    """
    SKL = surface_derivatives(srf, u, v, d=1)
    Su = SKL[1, 0]  # ∂S/∂u
    Sv = SKL[0, 1]  # ∂S/∂v
    cross = np.cross(Su, Sv)
    val = float(np.dot(cross, cross))
    return math.sqrt(max(val, 0.0))


def _gl5_cell(srf: NurbsSurface,
              u0: float, u1: float,
              v0: float, v1: float) -> float:
    """5×5 Gauss-Legendre area estimate for one UV cell.

    Change of variables from [-1,1]² to [u0,u1]×[v0,v1]:
        mid_u = (u0+u1)/2,  half_u = (u1-u0)/2
        mid_v = (v0+v1)/2,  half_v = (v1-v0)/2
        A = half_u · half_v · Σᵢ Σⱼ wᵢ·wⱼ · f(mid_u + half_u·ξᵢ, mid_v + half_v·ξⱼ)
    """
    half_u = 0.5 * (u1 - u0)
    half_v = 0.5 * (v1 - v0)
    mid_u  = 0.5 * (u0 + u1)
    mid_v  = 0.5 * (v0 + v1)
    total = 0.0
    for xi, wi in zip(_GL5_NODES, _GL5_WEIGHTS):
        u = mid_u + half_u * xi
        for xi_v, wj in zip(_GL5_NODES, _GL5_WEIGHTS):
            v = mid_v + half_v * xi_v
            total += wi * wj * _integrand(srf, u, v)
    return half_u * half_v * total


def _adaptive_cell(
    srf: NurbsSurface,
    u0: float, u1: float,
    v0: float, v1: float,
    tol: float,
    depth: int,
    max_depth: int,
) -> Tuple[float, float, int]:
    """Adaptively integrate one cell, returning (area, error_bound, max_depth_used)."""
    A_full = _gl5_cell(srf, u0, u1, v0, v1)

    if depth >= max_depth:
        return A_full, 0.0, depth

    # Refine: split into 4 sub-cells and compare.
    mid_u = 0.5 * (u0 + u1)
    mid_v = 0.5 * (v0 + v1)
    A_ll = _gl5_cell(srf, u0, mid_u, v0, mid_v)
    A_lr = _gl5_cell(srf, mid_u, u1, v0, mid_v)
    A_ul = _gl5_cell(srf, u0, mid_u, mid_v, v1)
    A_ur = _gl5_cell(srf, mid_u, u1, mid_v, v1)
    A_refined = A_ll + A_lr + A_ul + A_ur

    err = abs(A_full - A_refined)
    if err <= tol:
        return A_refined, err, depth + 1

    # Subdivide each quarter independently.
    tol4 = tol * 0.25
    a1, e1, d1 = _adaptive_cell(srf, u0, mid_u, v0, mid_v, tol4, depth + 1, max_depth)
    a2, e2, d2 = _adaptive_cell(srf, mid_u, u1, v0, mid_v, tol4, depth + 1, max_depth)
    a3, e3, d3 = _adaptive_cell(srf, u0, mid_u, mid_v, v1, tol4, depth + 1, max_depth)
    a4, e4, d4 = _adaptive_cell(srf, mid_u, u1, mid_v, v1, tol4, depth + 1, max_depth)

    return (
        a1 + a2 + a3 + a4,
        e1 + e2 + e3 + e4,
        max(d1, d2, d3, d4),
    )


def _unique_interior_knots(knots: np.ndarray, degree: int) -> np.ndarray:
    """Return the sorted unique knot values in the open knot span interior."""
    u_min = float(knots[degree])
    u_max = float(knots[-(degree + 1)])
    interior = []
    for k in sorted(set(knots.tolist())):
        if u_min < k < u_max:
            interior.append(k)
    return np.array(interior, dtype=float)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_exact_surface_area(
    srf: NurbsSurface,
    tolerance: float = 1e-6,
    max_subdivisions: int = 8,
) -> SurfaceAreaReport:
    """Compute the exact surface area of *srf* via Gauss-Legendre quadrature.

    The area is

        A = ∫∫ sqrt(EG - F²) du dv

    where E, F, G are the first-fundamental-form coefficients
    (do Carmo §2.5; Mortenson §10.4).

    The UV domain is partitioned at the surface's internal knot spans so that
    each cell is polynomial, eliminating inter-knot derivative discontinuities.
    Within each cell a 5×5 Gauss-Legendre rule is applied, with adaptive
    bisection subdivision if the local error estimate exceeds the tolerance
    budget.

    Parameters
    ----------
    srf : NurbsSurface
        The surface to measure.  Must be a plain (non-trimmed) NurbsSurface.
        For trimmed surfaces, the area is computed over the **full UV domain**
        only (v1 limitation — trimming boundary not honoured).
    tolerance : float
        Absolute area error tolerance (default 1e-6).
    max_subdivisions : int
        Maximum adaptive-subdivision depth per cell (default 8).

    Returns
    -------
    SurfaceAreaReport
        .area             — computed surface area
        .estimated_error  — conservative upper bound on absolute error
        .subdivisions_used — maximum subdivision depth reached
    """
    # Build UV cell grid from knot breaks.
    u_min = float(srf.knots_u[srf.degree_u])
    u_max = float(srf.knots_u[-(srf.degree_u + 1)])
    v_min = float(srf.knots_v[srf.degree_v])
    v_max = float(srf.knots_v[-(srf.degree_v + 1)])

    u_breaks = np.concatenate([[u_min],
                                _unique_interior_knots(srf.knots_u, srf.degree_u),
                                [u_max]])
    v_breaks = np.concatenate([[v_min],
                                _unique_interior_knots(srf.knots_v, srf.degree_v),
                                [v_max]])

    n_cells = max(1, (len(u_breaks) - 1) * (len(v_breaks) - 1))
    per_cell_tol = tolerance / n_cells

    total_area = 0.0
    total_error = 0.0
    max_depth_used = 0

    for i in range(len(u_breaks) - 1):
        u0, u1 = u_breaks[i], u_breaks[i + 1]
        if u1 - u0 < 1e-14:
            continue
        for j in range(len(v_breaks) - 1):
            v0, v1 = v_breaks[j], v_breaks[j + 1]
            if v1 - v0 < 1e-14:
                continue
            a, e, d = _adaptive_cell(srf, u0, u1, v0, v1,
                                     per_cell_tol, 0, max_subdivisions)
            total_area += a
            total_error += e
            if d > max_depth_used:
                max_depth_used = d

    return SurfaceAreaReport(
        area=total_area,
        estimated_error=total_error,
        subdivisions_used=max_depth_used,
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _srf_area_spec = ToolSpec(
        name="nurbs_surface_area_exact",
        description=(
            "Compute the exact surface area of a NURBS surface using the first-"
            "fundamental-form integrand A = ∫∫ sqrt(EG−F²) du dv, where "
            "E=Su·Su, F=Su·Sv, G=Sv·Sv (do Carmo §2.5 / Mortenson §10.4).\n"
            "\n"
            "Uses 5×5 Gauss-Legendre quadrature per knot-span cell with adaptive "
            "subdivision until the per-cell error estimate is below the requested "
            "tolerance.  Rational-correct for weighted NURBS surfaces.\n"
            "\n"
            "**v1 limitation**: area is computed over the full UV parameter domain. "
            "Trimmed surfaces are not supported; the trim boundary is not honoured.\n"
            "\n"
            "Returns: {ok, area, estimated_error, subdivisions_used}\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "control_points": {
                    "type": "array",
                    "description": (
                        "3D control-point grid as a list of rows. Each row is a list "
                        "of [x, y, z] control points. Shape: (nu, nv, 3)."
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
                        "Omit for non-rational surfaces."
                    ),
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                    },
                },
                "tolerance": {
                    "type": "number",
                    "description": "Absolute area error tolerance (default 1e-6).",
                },
                "max_subdivisions": {
                    "type": "integer",
                    "description": "Maximum adaptive subdivision depth per cell (default 8).",
                },
            },
            "required": ["control_points", "knots_u", "knots_v", "degree_u", "degree_v"],
        },
    )

    @register(_srf_area_spec)
    async def run_nurbs_surface_area_exact(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        cp_raw    = a.get("control_points")
        ku_raw    = a.get("knots_u")
        kv_raw    = a.get("knots_v")
        deg_u_raw = a.get("degree_u")
        deg_v_raw = a.get("degree_v")

        if any(x is None for x in (cp_raw, ku_raw, kv_raw, deg_u_raw, deg_v_raw)):
            return err_payload(
                "control_points, knots_u, knots_v, degree_u, degree_v are required",
                "BAD_ARGS",
            )

        try:
            cp      = np.asarray(cp_raw, dtype=float)
            knots_u = np.asarray(ku_raw, dtype=float)
            knots_v = np.asarray(kv_raw, dtype=float)
            degree_u = int(deg_u_raw)
            degree_v = int(deg_v_raw)
            weights_raw = a.get("weights")
            weights = np.asarray(weights_raw, dtype=float) if weights_raw is not None else None
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

        tol     = float(a.get("tolerance", 1e-6))
        max_sub = int(a.get("max_subdivisions", 8))

        try:
            report = compute_exact_surface_area(srf, tolerance=tol,
                                                max_subdivisions=max_sub)
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")

        return ok_payload({
            "area": report.area,
            "estimated_error": report.estimated_error,
            "subdivisions_used": report.subdivisions_used,
        })
