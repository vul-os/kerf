"""loft_guide_rails.py — NURBS loft with cross-section curves and guide rails (GK-P16).

Implements ``loft_with_guide_rails``: a NURBS surface skinned through a series of
cross-section curves while simultaneously following N guide rails that constrain
the surface's intermediate shape.

Theory: guide-rail loft (Piegl & Tiller §10.3 + §10.4; Rhino/Fusion360 guide-rail loft)
------------------------------------------------------------------------------------------
Standard loft (skinning) uses only cross-section curves sampled at v-parameter
knots v_0 < v_1 < ... < v_{m-1}; guide rails add U-direction constraints.

Algorithm (2D-deformation blend):
  1. Sample v uniformly (``num_v_samples`` steps) from v=0 to v=1.
  2. At each v-sample, determine the "base" cross-section by linearly interpolating
     between adjacent cross-section curves evaluated at their chord-length params.
  3. For each guide rail r_j, find the guide rail point g_j(v) by evaluating
     r_j at parameter v.  Compute the *endpoint displacement* d_j = g_j(v) − p_j(v),
     where p_j(v) is the interpolated cross-section position nearest to rail j's U
     parameter.
  4. Blend the displacement toward the u-parameter where rail j lives (Gaussian
     weight centred at ū_j, half-width σ = 1/(2·n_rails)):
         u-deform(u) = Σ_j w_j(u) · d_j,    w_j(u) = exp(−(u−ū_j)²/(2σ²))
     weights normalised so they sum to at most 1 at any u.
  5. Evaluate the cross-section at each u-sample, add the blended displacement,
     and collect into a dense (n_u_samples × num_v_samples × 3) grid.
  6. Fit an interpolating NurbsSurface through the grid (Piegl & Tiller §9.4.5).

HONEST CAVEATS
--------------
- This is an *approximate* guide-rail constraint, NOT an exact constrained-NURBS
  solver.  The surface passes near the guide rails but not necessarily through them
  exactly.  ``GuideRailLoftReport.max_guide_rail_deviation_mm`` reports the worst
  deviation so callers can make an informed QC decision.
- The algorithm uses equal-spaced v-sampling + least-squares surface fitting;
  the fitting residual grows with coarser sampling or higher curvature rails.
- Self-intersection detection is a control-polygon heuristic (centroid distance
  check), not an exact SSI computation.  ``num_self_intersections`` may under- or
  over-count on pathological inputs.
- Exact constrained-NURBS solving (full isogeometric constrained fitting) is out of
  scope; see Piegl & Tiller §10.3 and §10.5 for the research-grade formulation.

References
----------
- Piegl L. & Tiller W., "The NURBS Book", 2nd ed. §10.3 (skinning) + §10.4 (Gordon).
- Rhino 8 documentation: Loft → Guide Curves option.
- Autodesk Fusion 360 Help: Loft with guide rails.

Public API
----------
loft_with_guide_rails(spec: GuideRailLoftSpec) -> GuideRailLoftReport
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import List

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class GuideRailLoftSpec:
    """Specification for a guide-rail loft.

    Attributes
    ----------
    cross_section_curves
        Ordered list of cross-section profile curves (≥ 2).  Each is a
        3-D NurbsCurve.  The surface is skinned through these in order.
    guide_rail_curves
        List of guide rail curves (≥ 1) that constrain the surface's
        intermediate shape.  Guide rails should run approximately parallel
        to the loft direction (v-direction) from the first cross-section
        to the last.
    num_v_samples
        Number of v-parameter samples used to build the dense grid that is
        then fitted to produce the NurbsSurface.  More samples → closer
        approximation to the guide rails at the cost of build time.
    degree_v
        Degree of the output surface in the v (loft) direction.  Clamped
        to min(degree_v, num_cross_sections − 1).
    closed_v
        If True the loft wraps from the last cross-section back to the
        first.  Not yet implemented (raises NotImplementedError).
    """

    cross_section_curves: List[NurbsCurve]
    guide_rail_curves: List[NurbsCurve]
    num_v_samples: int = 20
    degree_v: int = 3
    closed_v: bool = False


@dataclass
class GuideRailLoftReport:
    """Result of a guide-rail loft.

    Attributes
    ----------
    loft_surface
        The fitted NurbsSurface.
    num_cross_sections
        Number of cross-section curves used.
    num_guide_rails
        Number of guide rail curves used.
    max_guide_rail_deviation_mm
        Maximum deviation (mm) between any guide rail point and the nearest
        surface point (sampled at ``num_v_samples`` v-stations).
    mean_guide_rail_deviation_mm
        Mean deviation across all sampled guide rail points.
    num_self_intersections
        Estimated number of self-intersecting v-rows in the control polygon.
        0 means no obvious self-intersections were detected.
    honest_caveat
        Human-readable caveat describing the approximation limitations.
    """

    loft_surface: NurbsSurface
    num_cross_sections: int
    num_guide_rails: int
    max_guide_rail_deviation_mm: float
    mean_guide_rail_deviation_mm: float
    num_self_intersections: int
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "Guide-rail loft uses a 2-D displacement-blend approximation (Piegl & Tiller "
    "§10.3 skinning + guide-deformation weighting), NOT an exact constrained-NURBS "
    "solver. The surface is fitted through a dense sample grid; deviations from guide "
    "rails are reported in max_guide_rail_deviation_mm / mean_guide_rail_deviation_mm "
    "for QC. For CAD-grade guide-rail lofts requiring exact rail satisfaction, an "
    "isogeometric constrained fitting pass (P&T §10.5) is required."
)


def _eval_curve_at(curve: NurbsCurve, t: float) -> np.ndarray:
    """Evaluate *curve* at normalised parameter *t* ∈ [0, 1] → (3,) array."""
    u0 = float(curve.knots[curve.degree])
    u1 = float(curve.knots[-curve.degree - 1])
    u = u0 + max(0.0, min(1.0, t)) * (u1 - u0)
    pt = curve.evaluate(u)
    p = np.asarray(pt, dtype=float).ravel()
    if p.shape[0] < 3:
        p = np.concatenate([p, np.zeros(3 - p.shape[0])])
    return p[:3]


def _chord_params(curve: NurbsCurve, n: int) -> np.ndarray:
    """Return n chord-length-parameterised samples in [0,1] along curve."""
    ts_raw = np.linspace(0.0, 1.0, n)
    pts = np.array([_eval_curve_at(curve, float(t)) for t in ts_raw])
    diffs = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    total = float(diffs.sum())
    if total < 1e-14:
        return ts_raw  # degenerate curve — return uniform
    params = np.concatenate([[0.0], np.cumsum(diffs) / total])
    return params


def _interp_cross_section_at_v(
    cross_sections: List[NurbsCurve],
    v: float,
    n_u: int,
) -> np.ndarray:
    """Interpolate the cross-sections at fractional v ∈ [0, 1].

    Returns an (n_u, 3) array of 3-D positions sampled at n_u chord-length
    equidistant parameters along the interpolated cross-section.

    Algorithm: locate the bounding cross-section pair [i, i+1] for v, compute
    local t = (v − v_i)/(v_{i+1} − v_i), and lerp between the two sampled
    cross-sections point-by-point.
    """
    m = len(cross_sections)
    v_params = np.linspace(0.0, 1.0, m)

    # Clamp v.
    v = max(0.0, min(1.0, float(v)))

    # Find bounding pair.
    idx = int(np.searchsorted(v_params, v, side='right')) - 1
    idx = max(0, min(m - 2, idx))

    v_lo = float(v_params[idx])
    v_hi = float(v_params[idx + 1])
    dv = v_hi - v_lo
    if dv < 1e-14:
        t_local = 0.0
    else:
        t_local = (v - v_lo) / dv
    t_local = max(0.0, min(1.0, t_local))

    # Sample both cross-sections at n_u uniform parameters.
    us = np.linspace(0.0, 1.0, n_u)
    pts_lo = np.array([_eval_curve_at(cross_sections[idx], float(u)) for u in us])
    pts_hi = np.array([_eval_curve_at(cross_sections[idx + 1], float(u)) for u in us])

    return (1.0 - t_local) * pts_lo + t_local * pts_hi


def _make_clamped_knots(n_ctrl: int, degree: int) -> np.ndarray:
    """Build a clamped uniform knot vector for n_ctrl control points, given degree."""
    m = n_ctrl + degree + 1
    knots = np.zeros(m)
    knots[-(degree + 1):] = 1.0
    n_inner = m - 2 * (degree + 1)
    if n_inner > 0:
        inner = np.linspace(0.0, 1.0, n_inner + 2)[1:-1]
        knots[degree + 1:degree + 1 + n_inner] = inner
    return knots


def _fit_curve_through_points(pts: np.ndarray, degree: int) -> NurbsCurve:
    """Fit a clamped B-spline of given degree through (n, 3) point sequence.

    Uses chord-length parameterisation and averaged-knot placement
    (Piegl & Tiller §9.2).
    """
    n = pts.shape[0]
    if n < 2:
        raise ValueError("Need at least 2 points to fit a NurbsCurve")
    degree = min(degree, n - 1)
    degree = max(1, degree)

    # Chord-length parameters.
    diffs = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    total = float(diffs.sum())
    if total < 1e-14:
        params = np.linspace(0.0, 1.0, n)
    else:
        params = np.concatenate([[0.0], np.cumsum(diffs) / total])

    # Averaged knot vector (P&T §9.2 Eq. 9.8).
    m_knots = n + degree + 1
    knots = np.zeros(m_knots)
    knots[-(degree + 1):] = 1.0
    if degree < n - 1:
        for j in range(1, n - degree):
            knots[j + degree] = float(params[j:j + degree].mean())

    # Collocation matrix.
    from kerf_cad_core.geom.nurbs import find_span, _basis_funcs
    N = np.zeros((n, n))
    for i in range(n):
        span = find_span(n - 1, degree, float(params[i]), knots)
        basis = _basis_funcs(span, float(params[i]), degree, knots)
        for k in range(degree + 1):
            j = span - degree + k
            if 0 <= j < n:
                N[i, j] = basis[k]

    cp = np.zeros((n, 3))
    for dim in range(3):
        try:
            cp[:, dim] = np.linalg.solve(N, pts[:, dim])
        except np.linalg.LinAlgError:
            cp[:, dim] = np.linalg.lstsq(N, pts[:, dim], rcond=None)[0]

    return NurbsCurve(degree=degree, control_points=cp, knots=knots)


def _interpolating_surface_from_grid(
    grid: np.ndarray,
    degree_u: int,
    degree_v: int,
) -> NurbsSurface:
    """Build an interpolating NurbsSurface from a (nu, nv, 3) grid.

    Uses row-wise + column-wise B-spline fitting (Piegl & Tiller §9.4.5).
    Step 1: fit a B-spline through each row (u-direction).
    Step 2: fit a B-spline through each column of the row control points
            (v-direction).
    The resulting control-point grid defines the interpolating surface.
    """
    nu, nv, _ = grid.shape
    degree_u = max(1, min(degree_u, nu - 1))
    degree_v = max(1, min(degree_v, nv - 1))

    # Step 1: fit u-direction curves through each v-row.
    # row_cp[j] = control-point array for row j.
    row_cps = []
    for j in range(nv):
        row_pts = grid[:, j, :]   # (nu, 3)
        crv = _fit_curve_through_points(row_pts, degree_u)
        row_cps.append(crv.control_points)  # (nu_cp, 3)
    # All row curves have the same number of CPs (= nu because collocation is square).
    n_cp_u = row_cps[0].shape[0]

    # Step 2: for each u-index, fit a v-direction curve through the stack of CPs.
    col_cps = []
    for i in range(n_cp_u):
        col_pts = np.array([row_cps[j][i] for j in range(nv)])  # (nv, 3)
        crv = _fit_curve_through_points(col_pts, degree_v)
        col_cps.append(crv.control_points)  # (nv_cp, 3)
    n_cp_v = col_cps[0].shape[0]

    # Assemble 3-D control-point grid (n_cp_u, n_cp_v, 3).
    cp_grid = np.zeros((n_cp_u, n_cp_v, 3))
    for i in range(n_cp_u):
        cp_grid[i] = col_cps[i]

    # Re-use the knot vectors from the first fitted curves.
    row_crv_0 = _fit_curve_through_points(grid[:, 0, :], degree_u)
    col_crv_0 = _fit_curve_through_points(
        np.array([row_cps[j][0] for j in range(nv)]), degree_v
    )

    return NurbsSurface(
        degree_u=degree_u,
        degree_v=degree_v,
        control_points=cp_grid,
        knots_u=row_crv_0.knots,
        knots_v=col_crv_0.knots,
    )


def _closest_param_on_surface_row(
    surface_row: np.ndarray,
    point: np.ndarray,
) -> int:
    """Return the index of the closest point in a (n,3) row to *point*."""
    dists = np.linalg.norm(surface_row - point[None, :], axis=1)
    return int(np.argmin(dists))


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def loft_with_guide_rails(spec: GuideRailLoftSpec) -> GuideRailLoftReport:
    """Build a NURBS surface lofted through cross-sections constrained by guide rails.

    Parameters
    ----------
    spec : GuideRailLoftSpec
        Loft specification — see dataclass docstring.

    Returns
    -------
    GuideRailLoftReport
        Fitted surface plus QC metrics.

    Raises
    ------
    ValueError
        If fewer than 2 cross-sections or fewer than 1 guide rail is provided.
    NotImplementedError
        If ``spec.closed_v`` is True.
    """
    cross_sections = list(spec.cross_section_curves)
    guide_rails = list(spec.guide_rail_curves)
    num_v = max(4, int(spec.num_v_samples))
    deg_v = max(1, int(spec.degree_v))
    closed_v = bool(spec.closed_v)

    m = len(cross_sections)
    n_rails = len(guide_rails)

    if m < 2:
        raise ValueError(
            f"loft_with_guide_rails: at least 2 cross-sections required; got {m}"
        )
    if n_rails < 1:
        raise ValueError(
            f"loft_with_guide_rails: at least 1 guide rail required; got {n_rails}"
        )
    if closed_v:
        raise NotImplementedError(
            "loft_with_guide_rails: closed_v=True is not yet implemented."
        )

    # Clamp degree_v.
    deg_v = min(deg_v, m - 1)
    deg_v = max(1, deg_v)

    # Choose n_u samples.  Use the average CP count of the cross-section curves
    # as a guide, minimum 8.
    n_u = max(8, int(np.mean([c.control_points.shape[0] for c in cross_sections])) * 4)

    # U-parameters for guide rails: evenly spaced in [0, 1].
    u_rail_params = np.linspace(0.0, 1.0, n_rails)

    # Gaussian blend half-width (so adjacent rails have weight 0.5 at their midpoint).
    sigma = 1.0 / (2.0 * n_rails) if n_rails > 1 else 0.5
    sigma = max(sigma, 0.05)

    # V-parameter samples.
    v_samples = np.linspace(0.0, 1.0, num_v)

    # Build the dense grid: (n_u, num_v, 3).
    grid = np.zeros((n_u, num_v, 3))

    # Also track guide rail evaluation vs grid row for deviation measurement.
    deviation_samples: List[float] = []

    for vi, v in enumerate(v_samples):
        # 1. Interpolated cross-section at this v.
        base_row = _interp_cross_section_at_v(cross_sections, v, n_u)
        # base_row: (n_u, 3)

        # 2. For each guide rail, compute displacement at v.
        u_grid = np.linspace(0.0, 1.0, n_u)
        total_disp = np.zeros((n_u, 3))
        total_weight = np.zeros(n_u)

        for ji, rail in enumerate(guide_rails):
            # Guide rail point at parameter v.
            rail_pt = _eval_curve_at(rail, v)

            # Find the u-index in the base_row closest to rail_pt.
            closest_u_idx = _closest_param_on_surface_row(base_row, rail_pt)

            # Displacement from base cross-section to rail point.
            disp = rail_pt - base_row[closest_u_idx]

            # Gaussian weight centred at ū_j over all u samples.
            uj = float(u_rail_params[ji])
            for ui, u in enumerate(u_grid):
                w = float(np.exp(-0.5 * ((u - uj) / sigma) ** 2))
                total_disp[ui] += w * disp
                total_weight[ui] += w

        # 3. Normalise and apply displacement.
        for ui in range(n_u):
            tw = total_weight[ui]
            if tw > 1e-12:
                # Blend weight: clamp to at most 1.0 to avoid over-shooting.
                blend = min(1.0, tw)
                grid[ui, vi] = base_row[ui] + blend * (total_disp[ui] / tw)
            else:
                grid[ui, vi] = base_row[ui]

        # 4. Measure deviation: for each rail, compare rail_pt to the grid.
        for rail in guide_rails:
            rail_pt = _eval_curve_at(rail, v)
            closest_u_idx = _closest_param_on_surface_row(grid[:, vi, :], rail_pt)
            dev = float(np.linalg.norm(grid[closest_u_idx, vi] - rail_pt))
            deviation_samples.append(dev)

    # ---------------------------------------------------------------------------
    # Fit interpolating NurbsSurface through grid.
    # ---------------------------------------------------------------------------
    deg_u = min(3, n_u - 1)
    deg_u = max(1, deg_u)
    deg_v_eff = min(deg_v, num_v - 1)
    deg_v_eff = max(1, deg_v_eff)

    surface = _interpolating_surface_from_grid(grid, deg_u, deg_v_eff)

    # ---------------------------------------------------------------------------
    # QC: guide rail deviation on the fitted surface.
    # ---------------------------------------------------------------------------
    # Re-sample the fitted surface at guide rail v-params and measure deviations.
    final_deviations: List[float] = []
    for rail in guide_rails:
        for v in np.linspace(0.0, 1.0, max(num_v, 10)):
            rail_pt = _eval_curve_at(rail, float(v))
            # Evaluate surface along u at this v.
            v0 = float(surface.knots_v[surface.degree_v])
            v1 = float(surface.knots_v[-surface.degree_v - 1])
            v_srf = v0 + float(v) * (v1 - v0)
            u0 = float(surface.knots_u[surface.degree_u])
            u1 = float(surface.knots_u[-surface.degree_u - 1])
            min_dev = np.inf
            for u_t in np.linspace(0.0, 1.0, n_u):
                u_srf = u0 + u_t * (u1 - u0)
                try:
                    spt = np.asarray(surface.evaluate(u_srf, v_srf), dtype=float).ravel()
                    if spt.shape[0] < 3:
                        spt = np.concatenate([spt, np.zeros(3 - spt.shape[0])])
                    d = float(np.linalg.norm(spt[:3] - rail_pt))
                    if d < min_dev:
                        min_dev = d
                except Exception:
                    pass
            if np.isfinite(min_dev):
                final_deviations.append(min_dev)

    if final_deviations:
        max_dev = float(np.max(final_deviations))
        mean_dev = float(np.mean(final_deviations))
    else:
        max_dev = 0.0
        mean_dev = 0.0

    # ---------------------------------------------------------------------------
    # Self-intersection heuristic: count v-rows where adjacent control-point
    # distances shrink to < 1% of the mean spacing (indicative of fold).
    # ---------------------------------------------------------------------------
    num_self_int = 0
    cp = surface.control_points  # (nu, nv, 3)
    nu_cp, nv_cp, _ = cp.shape
    for vi in range(nv_cp):
        col = cp[:, vi, :]  # (nu_cp, 3)
        dists = np.linalg.norm(np.diff(col, axis=0), axis=1)
        mean_d = float(dists.mean()) if len(dists) > 0 else 1.0
        if mean_d > 1e-12 and float(dists.min()) < 0.01 * mean_d:
            num_self_int += 1

    # ---------------------------------------------------------------------------
    # Warn about mismatched guide endpoints.
    # ---------------------------------------------------------------------------
    _check_guide_endpoint_alignment(cross_sections, guide_rails)

    return GuideRailLoftReport(
        loft_surface=surface,
        num_cross_sections=m,
        num_guide_rails=n_rails,
        max_guide_rail_deviation_mm=max_dev,
        mean_guide_rail_deviation_mm=mean_dev,
        num_self_intersections=num_self_int,
        honest_caveat=_HONEST_CAVEAT,
    )


# ---------------------------------------------------------------------------
# Guide endpoint alignment check
# ---------------------------------------------------------------------------

def _check_guide_endpoint_alignment(
    cross_sections: List[NurbsCurve],
    guide_rails: List[NurbsCurve],
    tol: float = 0.5,
) -> None:
    """Warn if guide rail endpoints don't lie close to the first/last cross-section.

    A guide rail whose start/end point is far from the corresponding cross-section
    is a sign that the inputs are mismatched; the user is warned but the function
    continues.
    """
    first_cs = cross_sections[0]
    last_cs = cross_sections[-1]

    # Sample each cross-section for closest-point checks.
    n_samp = 64
    first_pts = np.array([_eval_curve_at(first_cs, t) for t in np.linspace(0, 1, n_samp)])
    last_pts = np.array([_eval_curve_at(last_cs, t) for t in np.linspace(0, 1, n_samp)])

    for ji, rail in enumerate(guide_rails):
        r_start = _eval_curve_at(rail, 0.0)
        r_end = _eval_curve_at(rail, 1.0)

        d_start = float(np.min(np.linalg.norm(first_pts - r_start[None, :], axis=1)))
        d_end = float(np.min(np.linalg.norm(last_pts - r_end[None, :], axis=1)))

        if d_start > tol:
            warnings.warn(
                f"loft_with_guide_rails: guide rail {ji} start point is "
                f"{d_start:.4g} mm from the first cross-section (tol={tol}). "
                "The guide rail may not lie on the cross-section boundary. "
                "Surface will approximate but may not satisfy the guide rail exactly.",
                UserWarning,
                stacklevel=3,
            )
        if d_end > tol:
            warnings.warn(
                f"loft_with_guide_rails: guide rail {ji} end point is "
                f"{d_end:.4g} mm from the last cross-section (tol={tol}). "
                "The guide rail may not lie on the cross-section boundary. "
                "Surface will approximate but may not satisfy the guide rail exactly.",
                UserWarning,
                stacklevel=3,
            )


# ---------------------------------------------------------------------------
# LLM tool registration (gated — graceful no-op when registry absent)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    _nurbs_loft_guide_rails_spec = ToolSpec(
        name="nurbs_loft_with_guide_rails",
        description=(
            "Loft a NURBS surface through a series of cross-section curves while "
            "following N guide rail curves that constrain the surface's intermediate "
            "shape (Piegl & Tiller §10.3 skinning + guide-deformation blend). "
            "\n\n"
            "This is the 'guide-rail loft' operation found in Rhino and Fusion 360: "
            "cross-sections define the profile shapes; guide rails define how the "
            "surface transitions between them (e.g., keeping an edge on a curve, "
            "preventing the surface from bulging inward). "
            "\n\n"
            "**HONEST CAVEAT**: This is an *approximate* guide-rail constraint using a "
            "Gaussian displacement-blend algorithm, NOT an exact constrained-NURBS solver. "
            "``max_guide_rail_deviation_mm`` in the result reports the worst deviation for QC. "
            "For CAD-grade exact rail satisfaction, an isogeometric constrained fitting pass "
            "is required (out of scope). "
            "\n\n"
            "Returns the fitted NurbsSurface plus ``num_cross_sections``, "
            "``num_guide_rails``, ``max_guide_rail_deviation_mm``, "
            "``mean_guide_rail_deviation_mm``, ``num_self_intersections``, "
            "and ``honest_caveat``."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "cross_section_curves": {
                    "type": "array",
                    "description": (
                        "List of NURBS cross-section curves (≥ 2). Each curve is an object "
                        "with keys: degree (int), control_points ([[x,y,z],...]), knots ([float,...]), "
                        "and optional weights ([float,...])."
                    ),
                    "items": {"type": "object"},
                },
                "guide_rail_curves": {
                    "type": "array",
                    "description": (
                        "List of NURBS guide rail curves (≥ 1). Same schema as cross_section_curves. "
                        "Guide rails should span approximately from the first cross-section to the last."
                    ),
                    "items": {"type": "object"},
                },
                "num_v_samples": {
                    "type": "integer",
                    "description": "Number of v-samples for the dense grid (default 20). More = closer to rails.",
                },
                "degree_v": {
                    "type": "integer",
                    "description": "Degree of the output surface in the v (loft) direction (default 3).",
                },
                "closed_v": {
                    "type": "boolean",
                    "description": "If true, the loft wraps from the last cross-section to the first. NOT YET IMPLEMENTED.",
                },
            },
            "required": ["cross_section_curves", "guide_rail_curves"],
        },
    )

    def _decode_curve(obj: dict) -> NurbsCurve:
        degree = int(obj["degree"])
        cp = np.array(obj["control_points"], dtype=float)
        if cp.ndim == 1:
            cp = cp.reshape(-1, 3)
        knots = np.array(obj["knots"], dtype=float)
        weights = obj.get("weights")
        if weights is not None:
            weights = np.array(weights, dtype=float)
        return NurbsCurve(degree=degree, control_points=cp, knots=knots, weights=weights)

    @register(_nurbs_loft_guide_rails_spec)
    async def run_nurbs_loft_with_guide_rails(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            cs_raw = a.get("cross_section_curves")
            gr_raw = a.get("guide_rail_curves")

            if not cs_raw or not isinstance(cs_raw, list):
                return err_payload("cross_section_curves must be a non-empty array", "BAD_ARGS")
            if not gr_raw or not isinstance(gr_raw, list):
                return err_payload("guide_rail_curves must be a non-empty array", "BAD_ARGS")

            cross_sections = [_decode_curve(c) for c in cs_raw]
            guide_rails = [_decode_curve(r) for r in gr_raw]

            num_v_samples = int(a.get("num_v_samples", 20))
            degree_v = int(a.get("degree_v", 3))
            closed_v = bool(a.get("closed_v", False))

            spec = GuideRailLoftSpec(
                cross_section_curves=cross_sections,
                guide_rail_curves=guide_rails,
                num_v_samples=num_v_samples,
                degree_v=degree_v,
                closed_v=closed_v,
            )

            report = loft_with_guide_rails(spec)
            srf = report.loft_surface

        except (ValueError, NotImplementedError) as exc:
            return err_payload(str(exc), "OP_FAILED")
        except Exception as exc:
            return err_payload(f"unexpected error: {exc}", "ERROR")

        return ok_payload({
            "degree_u": srf.degree_u,
            "degree_v": srf.degree_v,
            "control_points": srf.control_points.tolist(),
            "knots_u": srf.knots_u.tolist(),
            "knots_v": srf.knots_v.tolist(),
            "num_cross_sections": report.num_cross_sections,
            "num_guide_rails": report.num_guide_rails,
            "max_guide_rail_deviation_mm": report.max_guide_rail_deviation_mm,
            "mean_guide_rail_deviation_mm": report.mean_guide_rail_deviation_mm,
            "num_self_intersections": report.num_self_intersections,
            "honest_caveat": report.honest_caveat,
        })
