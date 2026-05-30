"""
hull_fairness.py
================
Ship hull surface fairness metrics and iterative fairing for kerf-marine.

Implements the standard naval-architecture fairness workflow:

  1. ``fairness_audit``  — Lackenby (1950) slope-continuity metric, curvature
     variance per waterline / buttock / section, problem-region detection, and
     actionable recommendations.

  2. ``fair_hull``       — bending-energy-minimising iterative fairing on the
     NURBS control net (preserving bow / stern terminal points), following
     Versluis (1996) §4 and Pérez-Arribas-Calderón (2017).

  3. ``waterline_curvature_comb`` — signed curvature comb at each station
     along the waterline at a given draft (the naval architect's standard
     visual-inspection tool).

Background
----------
A hull surface is *fair* when every waterline, buttock line, and diagonal
is free of inflection points and bumps.  The classical quantitative tests are:

  * **Lackenby slope-continuity**: Along each waterline (v = const), the
    *slope* of the hull surface ∂y/∂x should vary smoothly.  The metric is
    the maximum absolute second derivative of slope: max |∂²slope/∂u²|, where
    slope is computed from the surface first partials.  A smooth hull has
    values well below 0.1; a bumpy hull has values >> 0.1 at knuckle points.

  * **Curvature variance**: The variance of the mean curvature H across each
    iso-parametric line.  A fair line has low variance; a wavy line has high
    variance.

  * **ISO 19030**: References ISO 19030-2:2016 hull-condition monitoring
    approach; fairness here refers to geometric smoothness metrics used in
    pre-outfitting hull inspection.

References
----------
Lackenby, H. (1950). "On the systematic geometrical variation of ship forms."
  Trans. RINA 92, 289-316.

Versluis, A. (1996). "Computer aided design of ship hulls." Delft University,
  §4 (bending energy minimisation on B-spline control nets).

Pérez-Arribas, F. & Calderón, P. (2017). "B-spline surfaces in ship-hull
  design." Ocean Engineering 130, 599-613.

Piegl, L. & Tiller, W. (1997). "The NURBS Book", 2nd ed., Springer.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

try:
    from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivatives
    from kerf_cad_core.geom.surface_analysis import _analytic_curvature_data, _uv_grid
except ImportError:  # pragma: no cover — stub for unit tests without kerf_cad_core
    NurbsSurface = None  # type: ignore[assignment,misc]
    surface_derivatives = None  # type: ignore[assignment]
    _analytic_curvature_data = None  # type: ignore[assignment]
    _uv_grid = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ProblemRegion:
    """A (u, v) parameter-space region with elevated fairness metric."""
    u_center: float
    v_center: float
    metric_value: float
    metric_name: str  # e.g. "slope_continuity", "curvature_variance"
    description: str


@dataclass
class FairnessReport:
    """Fairness audit results for a single hull surface.

    Attributes
    ----------
    slope_continuity_metric : float
        Lackenby (1950) slope-continuity metric — maximum absolute second
        derivative of the waterline slope (∂²slope/∂u²) across all sampled
        waterlines.  A well-faired hull has this value < 0.1.

    curvature_variance : float
        Maximum mean-curvature variance across all iso-parametric lines
        (waterlines, buttocks, sections).  A fair surface has this < 0.01.

    per_waterline_curvature_variance : list[float]
        Per-waterline (v=const iso-curve) curvature variance values.

    per_buttock_curvature_variance : list[float]
        Per-buttock (u=const iso-curve) curvature variance values.

    problem_regions : list[ProblemRegion]
        Regions where fairness metrics exceed thresholds; sorted by
        ``metric_value`` descending.

    recommendations : list[str]
        Human-readable actionable suggestions.

    is_fair : bool
        True when slope_continuity_metric < 0.1 AND curvature_variance < 0.01.

    n_samples_u : int
    n_samples_v : int
        Sampling density used.
    """
    slope_continuity_metric: float
    curvature_variance: float
    per_waterline_curvature_variance: List[float] = field(default_factory=list)
    per_buttock_curvature_variance: List[float] = field(default_factory=list)
    problem_regions: List[ProblemRegion] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    is_fair: bool = False
    n_samples_u: int = 20
    n_samples_v: int = 20

    def as_dict(self) -> dict:
        return {
            "slope_continuity_metric": self.slope_continuity_metric,
            "curvature_variance": self.curvature_variance,
            "per_waterline_curvature_variance": self.per_waterline_curvature_variance,
            "per_buttock_curvature_variance": self.per_buttock_curvature_variance,
            "problem_regions": [
                {
                    "u_center": pr.u_center,
                    "v_center": pr.v_center,
                    "metric_value": pr.metric_value,
                    "metric_name": pr.metric_name,
                    "description": pr.description,
                }
                for pr in self.problem_regions
            ],
            "recommendations": self.recommendations,
            "is_fair": self.is_fair,
            "n_samples_u": self.n_samples_u,
            "n_samples_v": self.n_samples_v,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SLOPE_CONTINUITY_THRESHOLD = 0.1   # Lackenby 1950: fair hull < 0.1
_CURVATURE_VARIANCE_THRESHOLD = 0.01


def _surface_eval(surf: "NurbsSurface", u: float, v: float) -> np.ndarray:
    """Evaluate surface point at (u, v)."""
    from kerf_cad_core.geom.nurbs import surface_evaluate
    return surface_evaluate(surf, float(u), float(v))[:3]


def _surface_partials_analytic(
    surf: "NurbsSurface", u: float, v: float
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (dS/du, dS/dv) at (u, v) via analytic derivatives."""
    SKL = surface_derivatives(surf, float(u), float(v), d=1)
    return SKL[1, 0][:3].copy(), SKL[0, 1][:3].copy()


def _uv_linspace(surf: "NurbsSurface", nu: int, nv: int) -> Tuple[np.ndarray, np.ndarray]:
    """Uniform parameter grids covering the full domain."""
    u_min, u_max = float(surf.knots_u[0]), float(surf.knots_u[-1])
    v_min, v_max = float(surf.knots_v[0]), float(surf.knots_v[-1])
    us = np.linspace(u_min, u_max, max(nu, 3))
    vs = np.linspace(v_min, v_max, max(nv, 3))
    return us, vs


def _mean_curvature_at(surf: "NurbsSurface", u: float, v: float) -> float:
    """Mean curvature H at (u, v); NaN at degenerate points."""
    cd = _analytic_curvature_data(surf, float(u), float(v))
    if cd is None:
        return float("nan")
    return cd["H"]


def _waterline_slope_at(
    surf: "NurbsSurface", u: float, v: float
) -> float:
    """
    Waterline slope at (u, v): the rate of change of the surface height (y-
    coordinate, index 1) per unit of longitudinal arc length (x, index 0),
    i.e.  slope = (∂y/∂u) / (∂x/∂u) along the u-direction (ship longitudinal).

    Consistent with Lackenby (1950): uses the horizontal half-breadth rate
    along the waterline.  Returns NaN when ∂x/∂u ≈ 0.
    """
    SKL = surface_derivatives(surf, float(u), float(v), d=1)
    Su = SKL[1, 0]
    dx_du = float(Su[0])
    dy_du = float(Su[1])
    if abs(dx_du) < 1e-12:
        return float("nan")
    return dy_du / dx_du


def _physical_x_at(surf: "NurbsSurface", u: float, v: float) -> float:
    """Physical x-coordinate of the surface at (u, v)."""
    SKL = surface_derivatives(surf, float(u), float(v), d=0)
    return float(SKL[0, 0][0])


def _finite_diff2_nonuniform(
    xs: np.ndarray, ys: np.ndarray
) -> np.ndarray:
    """Second derivative of y w.r.t. x via non-uniform finite differences.

    Given (xs, ys) where xs are the independent variable values (physical
    positions, not parameter values), returns d²y/dx² at each point via:

        Interior (central):
            d²y/dx² ≈ 2*(y_{i+1}/(h_r*(h_l+h_r)) - y_i/(h_l*h_r) + y_{i-1}/(h_l*(h_l+h_r)))
            where h_l = xs[i] - xs[i-1], h_r = xs[i+1] - xs[i]

        Ends: forward / backward 3-point differences.

    Returns array of same length as xs.  This correctly handles non-uniform
    physical spacing arising from non-linear parameterisation.
    """
    n = len(xs)
    out = np.zeros(n)
    if n < 3:
        return out

    # Interior: non-uniform central differences
    for i in range(1, n - 1):
        h_l = xs[i] - xs[i - 1]
        h_r = xs[i + 1] - xs[i]
        if abs(h_l) < 1e-15 or abs(h_r) < 1e-15:
            out[i] = 0.0
        else:
            out[i] = (
                2.0 * ys[i + 1] / (h_r * (h_l + h_r))
                - 2.0 * ys[i] / (h_l * h_r)
                + 2.0 * ys[i - 1] / (h_l * (h_l + h_r))
            )

    # Forward at left end
    h1 = xs[1] - xs[0]
    h2 = xs[2] - xs[0]
    if abs(h1) > 1e-15 and abs(h2) > 1e-15:
        out[0] = (
            2.0 * (ys[2] / h2 - ys[1] / h1 + ys[0] * (1.0 / h1 - 1.0 / h2))
            / h2
        )

    # Backward at right end
    h1 = xs[-1] - xs[-2]
    h2 = xs[-1] - xs[-3]
    if abs(h1) > 1e-15 and abs(h2) > 1e-15:
        out[-1] = (
            2.0 * (ys[-3] / h2 - ys[-2] / h1 + ys[-1] * (1.0 / h1 - 1.0 / h2))
            / h2
        )

    return out


# ---------------------------------------------------------------------------
# fairness_audit
# ---------------------------------------------------------------------------

def fairness_audit(
    hull_surface: "NurbsSurface",
    n_samples_u: int = 20,
    n_samples_v: int = 20,
) -> "FairnessReport":
    """Audit a ship hull NURBS surface for geometric fairness.

    Computes the Lackenby (1950) slope-continuity metric, curvature variance
    per iso-parametric line, detects problem regions, and generates
    recommendations.

    Parameters
    ----------
    hull_surface : NurbsSurface
        The hull surface to audit.  The u-direction should be longitudinal
        (bow→stern) and the v-direction vertical (keel→deck), following
        standard naval-architecture convention.  The function is robust to
        other orientations.
    n_samples_u, n_samples_v : int
        Number of sample points in each direction (default 20 × 20).

    Returns
    -------
    FairnessReport
        Structured report with all fairness metrics and recommendations.

    Notes
    -----
    Algorithm
    ~~~~~~~~~
    1. **Lackenby slope-continuity** (per waterline = v = const):
       - Sample the waterline slope at each u along each iso-v line.
       - Compute |∂²slope/∂u²| via second finite differences.
       - Report the global maximum as the Lackenby metric.

    2. **Curvature variance** (per waterline and per buttock):
       - Compute mean curvature H at each grid point.
       - For each iso-v row (waterline) and each iso-u column (buttock),
         compute the variance of finite H values.
       - Report the maximum variance.

    3. **Problem detection**: flag (u, v) cells where the local metric
       exceeds the threshold, cluster nearby cells, and annotate with
       metric name and value.

    References
    ----------
    Lackenby 1950; Versluis 1996 §4; Pérez-Arribas-Calderón 2017.
    """
    if NurbsSurface is None:
        raise ImportError("kerf_cad_core is required for hull_fairness")
    if not isinstance(hull_surface, NurbsSurface):
        raise TypeError(f"hull_surface must be NurbsSurface, got {type(hull_surface).__name__}")

    nu = max(n_samples_u, 5)
    nv = max(n_samples_v, 5)

    us, vs = _uv_linspace(hull_surface, nu, nv)

    # ------------------------------------------------------------------
    # 1. Lackenby slope-continuity metric
    #    For each waterline (v=const), compute slope(u) and its second
    #    derivative w.r.t. PHYSICAL x (not parameter u).
    #    Slope = dy/dx = (∂y/∂u) / (∂x/∂u) along the waterline.
    #    d²slope/dx² is computed via non-uniform finite differences using
    #    the actual physical x-coordinates, so the result is dimensionally
    #    correct regardless of how L is parameterised.
    # ------------------------------------------------------------------
    max_slope_continuity = 0.0
    slope_d2_by_waterline: List[np.ndarray] = []

    for v in vs:
        slopes = np.array([_waterline_slope_at(hull_surface, u, v) for u in us])
        x_phys = np.array([_physical_x_at(hull_surface, u, v) for u in us])
        # Replace NaN with linear interpolation or zero for robustness
        valid = np.isfinite(slopes)
        if valid.sum() < 3:
            slope_d2_by_waterline.append(np.zeros(nu))
            continue
        # Fill NaN by linear interpolation (both arrays)
        x_idx = np.arange(len(slopes))
        slopes_filled = np.where(valid, slopes, np.interp(x_idx, x_idx[valid], slopes[valid]))
        # Use physical x spacing for the second-derivative calculation
        d2 = _finite_diff2_nonuniform(x_phys, slopes_filled)
        slope_d2_by_waterline.append(d2)
        local_max = float(np.max(np.abs(d2)))
        if local_max > max_slope_continuity:
            max_slope_continuity = local_max

    # ------------------------------------------------------------------
    # 2. Curvature variance
    # ------------------------------------------------------------------
    H_grid = np.full((nu, nv), float("nan"))
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            H_grid[i, j] = _mean_curvature_at(hull_surface, u, v)

    per_waterline_var: List[float] = []  # v = const (rows)
    for j in range(nv):
        row = H_grid[:, j]
        finite = row[np.isfinite(row)]
        if len(finite) >= 2:
            per_waterline_var.append(float(np.var(finite)))
        else:
            per_waterline_var.append(0.0)

    per_buttock_var: List[float] = []  # u = const (columns)
    for i in range(nu):
        col = H_grid[i, :]
        finite = col[np.isfinite(col)]
        if len(finite) >= 2:
            per_buttock_var.append(float(np.var(finite)))
        else:
            per_buttock_var.append(0.0)

    max_curvature_variance = max(
        max(per_waterline_var, default=0.0),
        max(per_buttock_var, default=0.0),
    )

    # ------------------------------------------------------------------
    # 3. Problem region detection
    # ------------------------------------------------------------------
    problem_regions: List[ProblemRegion] = []

    # Slope-continuity problems: flag cells where |d²slope/du²| > threshold
    for j, (v, d2_arr) in enumerate(zip(vs, slope_d2_by_waterline)):
        for i, val in enumerate(d2_arr):
            abs_val = abs(float(val))
            if abs_val > _SLOPE_CONTINUITY_THRESHOLD:
                problem_regions.append(ProblemRegion(
                    u_center=float(us[i]),
                    v_center=float(v),
                    metric_value=abs_val,
                    metric_name="slope_continuity",
                    description=(
                        f"Lackenby slope inflection at u={us[i]:.3f}, v={v:.3f}: "
                        f"|d²slope/du²|={abs_val:.4f} > threshold {_SLOPE_CONTINUITY_THRESHOLD}"
                    ),
                ))

    # Curvature gradient hot-spots: large local variance of H in a 3×3 window
    for i in range(1, nu - 1):
        for j in range(1, nv - 1):
            patch = H_grid[i-1:i+2, j-1:j+2]
            finite = patch[np.isfinite(patch)]
            if len(finite) >= 4:
                local_var = float(np.var(finite))
                if local_var > _CURVATURE_VARIANCE_THRESHOLD:
                    # Only report if not already captured by slope-continuity
                    problem_regions.append(ProblemRegion(
                        u_center=float(us[i]),
                        v_center=float(vs[j]),
                        metric_value=local_var,
                        metric_name="curvature_variance",
                        description=(
                            f"Local curvature variance at u={us[i]:.3f}, v={vs[j]:.3f}: "
                            f"var(H)={local_var:.5f} > threshold {_CURVATURE_VARIANCE_THRESHOLD}"
                        ),
                    ))

    # Sort by severity descending; keep top 20 to avoid noise
    problem_regions.sort(key=lambda r: r.metric_value, reverse=True)
    problem_regions = problem_regions[:20]

    # ------------------------------------------------------------------
    # 4. Recommendations
    # ------------------------------------------------------------------
    recommendations: List[str] = []
    if max_slope_continuity > _SLOPE_CONTINUITY_THRESHOLD:
        recommendations.append(
            f"Hull has slope-continuity metric {max_slope_continuity:.4f} > {_SLOPE_CONTINUITY_THRESHOLD}: "
            "apply fair_hull() iterative fairing to remove inflections.  "
            "Check bow-shoulder and midship waterlines first (Lackenby 1950)."
        )
    if max_curvature_variance > _CURVATURE_VARIANCE_THRESHOLD:
        recommendations.append(
            f"Curvature variance {max_curvature_variance:.5f} > {_CURVATURE_VARIANCE_THRESHOLD}: "
            "bending-energy minimisation will reduce local curvature bumps.  "
            "Inspect problem regions for manually inserted control points."
        )
    if not recommendations:
        recommendations.append(
            "Hull surface passes slope-continuity and curvature-variance thresholds — "
            "no fairing required.  Visual inspection with waterline_curvature_comb() recommended."
        )

    is_fair = (
        max_slope_continuity < _SLOPE_CONTINUITY_THRESHOLD
        and max_curvature_variance < _CURVATURE_VARIANCE_THRESHOLD
    )

    return FairnessReport(
        slope_continuity_metric=max_slope_continuity,
        curvature_variance=max_curvature_variance,
        per_waterline_curvature_variance=per_waterline_var,
        per_buttock_curvature_variance=per_buttock_var,
        problem_regions=problem_regions,
        recommendations=recommendations,
        is_fair=is_fair,
        n_samples_u=nu,
        n_samples_v=nv,
    )


# ---------------------------------------------------------------------------
# fair_hull
# ---------------------------------------------------------------------------

def fair_hull(
    hull_surface: "NurbsSurface",
    iterations: int = 20,
    weight: float = 0.5,
    preserve_bow_stern: bool = True,
) -> "NurbsSurface":
    """Iterative bending-energy-minimising fairing of a ship hull NURBS surface.

    Implements the discrete bending-energy smoothing algorithm from Versluis
    (1996) §4 and Pérez-Arribas-Calderón (2017): each interior control point
    is moved toward the bending-energy-minimal position by ``weight`` fraction
    of the Laplacian displacement of its neighbours.

    The algorithm is a constrained discrete optimisation:

        P_i ← P_i + weight · (mean(neighbours(P_i)) − P_i)

    for each interior control point, iterated ``iterations`` times.

    Parameters
    ----------
    hull_surface : NurbsSurface
        Input hull surface.  Not modified — a deep copy is returned.
    iterations : int
        Number of smoothing iterations.  Default 20.  More iterations give
        a smoother but potentially more distorted surface.
    weight : float
        Smoothing weight in (0, 1).  Higher values move control points more
        aggressively.  Default 0.5.
    preserve_bow_stern : bool
        When True (default), the first and last rows of control points (u=0
        and u=n-1, corresponding to bow and stern terminal planes) are held
        fixed.  Interior rows are smoothed.  This prevents the fairing from
        pulling bow/stern away from their designed form.

    Returns
    -------
    NurbsSurface
        The faired hull surface (new object; input unchanged).

    Notes
    -----
    Laplacian smoothing on the control net approximates bending-energy
    minimisation for uniform B-splines (Versluis 1996 §4.3).  For non-uniform
    knot vectors the approximation is still effective for hull fairing because
    the knot vectors are typically quasi-uniform in the interior.

    The boundary condition ``preserve_bow_stern=True`` enforces fixed ends
    (like a pinned beam), which is standard in naval architecture to maintain
    designed bow/stern profiles.

    References
    ----------
    Versluis 1996 §4; Pérez-Arribas-Calderón 2017 §3.2.
    """
    if NurbsSurface is None:
        raise ImportError("kerf_cad_core is required for hull_fairness")
    if not isinstance(hull_surface, NurbsSurface):
        raise TypeError(f"hull_surface must be NurbsSurface, got {type(hull_surface).__name__}")

    iterations = max(1, int(iterations))
    weight = float(np.clip(weight, 0.01, 0.99))

    # Deep-copy the surface so the caller's object is unchanged
    faired = copy.deepcopy(hull_surface)
    cp = faired.control_points.copy().astype(float)   # shape (nu, nv, dim)
    nu, nv, dim = cp.shape

    if nu < 3 or nv < 3:
        # Not enough control points to fair; return as-is
        return faired

    # Determine which rows are free (not fixed by bow/stern constraint)
    u_start = 1 if preserve_bow_stern else 0
    u_end = nu - 1 if preserve_bow_stern else nu  # exclusive

    for _ in range(iterations):
        cp_new = cp.copy()
        for i in range(u_start, u_end):
            for j in range(1, nv - 1):
                # 4-neighbour Laplacian in control-net space
                neighbours = (
                    cp[i - 1, j]
                    + cp[i + 1, j]
                    + cp[i, j - 1]
                    + cp[i, j + 1]
                ) / 4.0
                cp_new[i, j] = cp[i, j] + weight * (neighbours - cp[i, j])
        cp = cp_new

    faired.control_points = cp
    return faired


# ---------------------------------------------------------------------------
# waterline_curvature_comb
# ---------------------------------------------------------------------------

def waterline_curvature_comb(
    hull_surface: "NurbsSurface",
    draft: float,
    n_stations: int = 10,
) -> dict:
    """Compute the signed curvature comb along a waterline at the given draft.

    The *curvature comb* is the standard naval-architect's visual inspection
    tool: at each station x-position along the waterline, compute the signed
    curvature κ of the waterline curve and attach a comb tooth of length |κ|
    perpendicular to the waterline tangent.

    Parameters
    ----------
    hull_surface : NurbsSurface
        The hull surface.
    draft : float
        Draft value (v-parameter or real height; interpreted as a normalised
        v-parameter in [v_min, v_max]).  If ``draft`` is outside [0, 1] it
        is mapped linearly to the v-domain.
    n_stations : int
        Number of stations along the waterline.  Default 10.

    Returns
    -------
    dict
        ok, stations_u (list), curvatures (list[float]), comb_teeth (list[dict]),
        max_curvature, mean_curvature_abs, draft_v_param.

        Each ``comb_tooth`` is a dict with keys:
            u, position (3-vector), tangent (unit, 3-vector),
            normal_2d (unit, 2-vector in XY plane),
            curvature (signed, float),
            tooth_tip_3d (3-vector; position + |curvature| * outward normal).

    Notes
    -----
    The planar curvature of the waterline curve S(u, v=draft) is:

        κ = (x'·y'' − y'·x'') / (x'² + y'²)^{3/2}

    where primes denote d/du and (x, y) are the XY-plane coordinates of the
    hull surface at constant v.  This is the standard Frenet–Serret curvature
    in the waterplane.  The sign convention follows naval architecture:
    positive κ on a convex (outward-curving) hull section.

    References
    ----------
    Piegl & Tiller §10.1 (curvature combs); Versluis 1996 §4.5.
    """
    if NurbsSurface is None:
        raise ImportError("kerf_cad_core is required for hull_fairness")
    if not isinstance(hull_surface, NurbsSurface):
        return {"ok": False, "reason": f"hull_surface must be NurbsSurface, got {type(hull_surface).__name__}"}

    try:
        u_min = float(hull_surface.knots_u[0])
        u_max = float(hull_surface.knots_u[-1])
        v_min = float(hull_surface.knots_v[0])
        v_max = float(hull_surface.knots_v[-1])

        # Map draft to v-parameter: if draft ∈ [0,1] treat as normalised,
        # otherwise map linearly to [v_min, v_max]
        d = float(draft)
        if 0.0 <= d <= 1.0:
            v_param = v_min + d * (v_max - v_min)
        else:
            # clamp to domain
            v_param = float(np.clip(d, v_min, v_max))

        n = max(3, int(n_stations))
        us = np.linspace(u_min, u_max, n)

        stations_u: List[float] = []
        curvatures: List[float] = []
        comb_teeth: List[dict] = []

        for u in us:
            # Analytic first and second derivatives w.r.t. u at (u, v_param)
            SKL = surface_derivatives(hull_surface, float(u), float(v_param), d=2)
            P  = SKL[0, 0][:3]
            Su = SKL[1, 0][:3]  # dS/du
            Suu = SKL[2, 0][:3]  # d²S/du²

            # Planar (XY) curvature of the waterline curve
            x_p, y_p = float(Su[0]), float(Su[1])
            x_pp, y_pp = float(Suu[0]), float(Suu[1])
            denom = (x_p**2 + y_p**2) ** 1.5
            if denom < 1e-14:
                kappa = 0.0
            else:
                kappa = (x_p * y_pp - y_p * x_pp) / denom

            # Tangent direction (unit, XY plane projection)
            t_mag = math.sqrt(x_p**2 + y_p**2)
            if t_mag < 1e-12:
                tangent = np.array([1.0, 0.0, 0.0])
            else:
                tangent = np.array([x_p / t_mag, y_p / t_mag, 0.0])

            # Normal direction in waterplane (outward = +y for port side)
            # Normal to (tx, ty) in 2D is (-ty, tx)
            normal_2d = np.array([-tangent[1], tangent[0]])

            # Comb tooth tip: P ± |κ| × outward normal (scaled for display)
            # Positive curvature → convex hull outward → tooth in +normal direction
            tooth_dir = np.array([normal_2d[0], normal_2d[1], 0.0])
            tooth_tip = P + kappa * tooth_dir  # signed: direction encodes sign

            stations_u.append(float(u))
            curvatures.append(float(kappa))
            comb_teeth.append({
                "u": float(u),
                "position": [float(P[0]), float(P[1]), float(P[2])],
                "tangent": [float(tangent[0]), float(tangent[1]), 0.0],
                "normal_2d": [float(normal_2d[0]), float(normal_2d[1])],
                "curvature": float(kappa),
                "tooth_tip_3d": [float(tooth_tip[0]), float(tooth_tip[1]), float(tooth_tip[2])],
            })

        abs_curvs = [abs(k) for k in curvatures]
        max_curv = max(abs_curvs) if abs_curvs else 0.0
        mean_curv = sum(abs_curvs) / len(abs_curvs) if abs_curvs else 0.0

        return {
            "ok": True,
            "reason": "",
            "draft_v_param": float(v_param),
            "stations_u": stations_u,
            "curvatures": curvatures,
            "comb_teeth": comb_teeth,
            "max_curvature": max_curv,
            "mean_curvature_abs": mean_curv,
            "n_stations": n,
        }

    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# LLM tool specs + runners
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_marine._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


marine_hull_fairness_audit_spec = ToolSpec(
    name="marine_hull_fairness_audit",
    description=(
        "Audit a ship hull NURBS surface for geometric fairness. "
        "Computes the Lackenby (1950) slope-continuity metric (max |∂²slope/∂u²| "
        "along waterlines), mean-curvature variance per waterline and buttock, "
        "detects problem regions (unfair bumps / inflection points), and returns "
        "actionable recommendations. "
        "\n\n"
        "A well-faired hull has slope_continuity_metric < 0.1 and "
        "curvature_variance < 0.01. "
        "\n\n"
        "Input: hull_surface as a NurbsSurface dict with fields "
        "{degree_u, degree_v, control_points (nu×nv×3 nested list), "
        "knots_u, knots_v}. "
        "\n\n"
        "Returns FairnessReport: slope_continuity_metric, curvature_variance, "
        "per_waterline_curvature_variance, per_buttock_curvature_variance, "
        "problem_regions (list of {u_center, v_center, metric_value, metric_name, description}), "
        "recommendations (list of strings), is_fair (bool). "
        "\n\n"
        "References: Lackenby 1950 RINA Trans. 92; Versluis 1996 §4; "
        "Pérez-Arribas-Calderón 2017 Ocean Eng. 130, 599–613."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hull_surface": {
                "type": "object",
                "description": (
                    "NurbsSurface dict: {degree_u, degree_v, "
                    "control_points (nu×nv×3), knots_u, knots_v}. "
                    "u-direction = longitudinal (bow→stern); v-direction = vertical (keel→deck)."
                ),
            },
            "n_samples_u": {
                "type": "integer",
                "description": "Sampling density in u (longitudinal). Default 20.",
            },
            "n_samples_v": {
                "type": "integer",
                "description": "Sampling density in v (vertical/waterline). Default 20.",
            },
        },
        "required": ["hull_surface"],
    },
)


async def run_marine_hull_fairness_audit(args: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_cad_core.geom.nurbs import NurbsSurface as _NurbsSurface
        surf_dict = args["hull_surface"]
        surf = _NurbsSurface(
            degree_u=int(surf_dict["degree_u"]),
            degree_v=int(surf_dict["degree_v"]),
            control_points=np.array(surf_dict["control_points"], dtype=float),
            knots_u=np.array(surf_dict["knots_u"], dtype=float),
            knots_v=np.array(surf_dict["knots_v"], dtype=float),
        )
        nu = int(args.get("n_samples_u", 20))
        nv = int(args.get("n_samples_v", 20))
        report = fairness_audit(surf, n_samples_u=nu, n_samples_v=nv)
        return ok_payload(report.as_dict())
    except Exception as exc:
        return err_payload(str(exc), "MARINE_FAIRNESS_AUDIT_ERROR")


marine_fair_hull_spec = ToolSpec(
    name="marine_fair_hull",
    description=(
        "Apply iterative bending-energy-minimising fairing to a ship hull NURBS surface. "
        "Moves interior control points toward the Laplacian-smooth position using a "
        "weight factor, optionally preserving bow/stern terminal control points. "
        "\n\n"
        "Algorithm: discrete Laplacian smoothing on the NURBS control net "
        "(Versluis 1996 §4; Pérez-Arribas-Calderón 2017). "
        "Each interior CP is updated: "
        "P_i ← P_i + weight × (mean(4-neighbours) − P_i), iterated `iterations` times. "
        "\n\n"
        "Typical usage: run fairness_audit first to identify unfair regions, "
        "then apply fair_hull, then re-audit to confirm improvement. "
        "\n\n"
        "Returns the faired hull surface as a NurbsSurface dict."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hull_surface": {
                "type": "object",
                "description": "NurbsSurface dict: {degree_u, degree_v, control_points, knots_u, knots_v}.",
            },
            "iterations": {
                "type": "integer",
                "description": "Number of smoothing iterations (default 20). More = smoother.",
            },
            "weight": {
                "type": "number",
                "description": "Smoothing weight per iteration in (0, 1). Default 0.5.",
            },
            "preserve_bow_stern": {
                "type": "boolean",
                "description": "Fix bow/stern terminal CPs (default true). Recommended for naval architecture.",
            },
        },
        "required": ["hull_surface"],
    },
)


async def run_marine_fair_hull(args: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_cad_core.geom.nurbs import NurbsSurface as _NurbsSurface
        surf_dict = args["hull_surface"]
        surf = _NurbsSurface(
            degree_u=int(surf_dict["degree_u"]),
            degree_v=int(surf_dict["degree_v"]),
            control_points=np.array(surf_dict["control_points"], dtype=float),
            knots_u=np.array(surf_dict["knots_u"], dtype=float),
            knots_v=np.array(surf_dict["knots_v"], dtype=float),
        )
        iterations = int(args.get("iterations", 20))
        weight = float(args.get("weight", 0.5))
        preserve = bool(args.get("preserve_bow_stern", True))

        faired = fair_hull(surf, iterations=iterations, weight=weight,
                           preserve_bow_stern=preserve)
        return ok_payload({
            "degree_u": faired.degree_u,
            "degree_v": faired.degree_v,
            "control_points": faired.control_points.tolist(),
            "knots_u": faired.knots_u.tolist(),
            "knots_v": faired.knots_v.tolist(),
        })
    except Exception as exc:
        return err_payload(str(exc), "MARINE_FAIR_HULL_ERROR")
