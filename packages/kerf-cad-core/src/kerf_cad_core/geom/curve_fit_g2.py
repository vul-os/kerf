"""curve_fit_g2.py — NURBS-CURVE-FIT-G2: degree-5 B-spline curve fitting with
G2 (curvature-continuous) end conditions.

Given a set of 3-D data points and prescribed tangent + curvature vectors at
both endpoints, this module fits a single degree-5 B-spline (NURBS) curve that:
  - Interpolates the data points (with tolerance dictated by the least-squares
    residual);
  - Satisfies prescribed first-derivative (tangent) conditions at t=0 and t=1;
  - Satisfies prescribed second-derivative (curvature) conditions at t=0 and t=1.

The four extra DOF consumed by the G2 end conditions require at least 4 interior
free control points, so the minimum meaningful input is ``n = degree + 1 + 4 = 10``
data points; for smaller datasets the solver falls back to a minimum knot span
that keeps the system determined.

Algorithm (Piegl & Tiller §9.4 — Local interpolation with end conditions; Farin
"CAGD" Ch 10)
--------------
1. Chord-length parameterisation: t_0 = 0, t_n = 1,
   t_k = t_{k-1} + |P_k − P_{k-1}| / total_chord_length.

2. Knot vector: clamped (multiplicity degree+1 at both ends), interior knots
   chosen by the averaging rule (Piegl & Tiller §9.2 Eq 9.8):
     ξ_{j+degree} = (1/degree) Σ_{i=j}^{j+degree-1} t_i.
   This is applied to the *interior* parameters only (excluding endpoints).

3. Collocation matrix A: A[k, i] = N_{i, degree}(t_k) evaluated via the stable
   Cox-de Boor triangular recurrence.  Rows 0..n_pts−1 are data-point equations.

4. Derivative-condition rows:
   - Rows n_pts..n_pts+1: C'(0) = T_start, C'(1) = T_end  (first-order, G1).
   - Rows n_pts+2..n_pts+3: C''(0) = K_start, C''(1) = K_end (second-order, G2).
   These rows use the B-spline derivative basis (Algorithm A2.3 from Piegl &
   Tiller; basis-function derivatives at t=0 and t=1).

5. Solve (A | b) via ``numpy.linalg.lstsq`` with ``rcond=None``.

6. Compute residuals in mm.

Caveats (honest)
----------------
- **Chord-length parameterisation** is used for robustness and simplicity.
  Centripetal parameterisation (Foley & Nielsen 1989; Lee 1989) can give smaller
  oscillations for high-aspect-ratio curves and is recommended when data has
  large variation in spacing.  It is *not* used here.
- For very small point counts (< degree + 1) the system is severely
  under-determined; the solver still returns a result but residuals will be high.
- The curvature vector K as required here is the *parametric second derivative*
  C''(t), not the Frenet curvature vector κ(s).  If you have a geometric
  curvature κ and unit normal n̂, then C'' = κ |C'|² n̂ + (C'·C'') C'/|C'|²
  (more precisely, the relationship depends on the arc-length scaling).
  For blending against adjacent surfaces the simplest approach is to pass the
  second derivative of the adjacent curve evaluated at the join point directly.

References
----------
* Piegl, L. & Tiller, W. (1997).  "The NURBS Book", 2nd ed., Springer.
  §9.4 "Local interpolation with end conditions"; §9.2 knot placement.
* Farin, G. (2002).  "Curves and Surfaces for CAGD", 5th ed., Morgan Kaufmann.
  Ch. 10 "Cubic spline interpolation".
* Lee, E.T.Y. (1989).  "Choosing nodes in parametric curve interpolation."
  CAD 21(6):363–370.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    _basis_funcs,
    _basis_funcs_derivs,
    find_span,
)

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class G2FitSpec:
    """Input specification for a G2-continuous NURBS curve fit.

    Attributes
    ----------
    data_points
        Ordered sequence of 3-D data points (x, y, z) to interpolate.
        Minimum meaningful count: ``degree + 5`` (= 10 for degree 5).
    start_tangent_xyz
        Prescribed first parametric derivative C'(0).  This is NOT a unit
        tangent — magnitude matters (controls curve speed at the start).
    start_curvature_xyz
        Prescribed second parametric derivative C''(0).  For G2 blending
        against an adjacent curve evaluate that curve's C'' at the join.
    end_tangent_xyz
        Prescribed first parametric derivative C'(1).
    end_curvature_xyz
        Prescribed second parametric derivative C''(1).
    """

    data_points: List[Tuple[float, float, float]]
    start_tangent_xyz: Tuple[float, float, float]
    start_curvature_xyz: Tuple[float, float, float]
    end_tangent_xyz: Tuple[float, float, float]
    end_curvature_xyz: Tuple[float, float, float]


@dataclass
class G2FitResult:
    """Output from :func:`fit_curve_g2`.

    Attributes
    ----------
    fitted_curve
        The fitted degree-5 B-spline (NurbsCurve, non-rational).
    max_residual_mm
        Maximum positional residual |C(t_k) − P_k| in mm.
    mean_residual_mm
        Mean positional residual across all data points.
    start_g2_residual
        ||C''(0) − K_start|| — curvature error at the start endpoint.
    end_g2_residual
        ||C''(1) − K_end|| — curvature error at the end endpoint.
    honest_caveat
        Human-readable disclaimer about algorithm limitations.
    """

    fitted_curve: NurbsCurve
    max_residual_mm: float
    mean_residual_mm: float
    start_g2_residual: float
    end_g2_residual: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _chord_params(pts: np.ndarray) -> np.ndarray:
    """Chord-length parameterisation.  Returns t in [0, 1]."""
    n = len(pts)
    t = np.zeros(n)
    for k in range(1, n):
        t[k] = t[k - 1] + float(np.linalg.norm(pts[k] - pts[k - 1]))
    total = t[-1]
    if total < 1e-14:
        # Degenerate: all points coincident — uniform spacing fallback.
        t = np.linspace(0.0, 1.0, n)
    else:
        t /= total
    # Clamp to [0, 1] to handle floating-point drift.
    t[0] = 0.0
    t[-1] = 1.0
    return t


def _clamped_knots(n_ctrl: int, degree: int, params: np.ndarray) -> np.ndarray:
    """Build a clamped B-spline knot vector using the averaging rule.

    The interior knots are placed at the averages of *degree* consecutive
    interior parameter values (Piegl & Tiller §9.2, Eq. 9.8).

    Parameters
    ----------
    n_ctrl
        Number of control points.
    degree
        B-spline degree.
    params
        Data parameter values (chord-length, sorted, first=0, last=1).
    """
    n_inner_knots = n_ctrl - degree - 1  # number of interior knot spans
    knots = np.zeros(n_ctrl + degree + 1)
    # Clamped: first (degree+1) = 0, last (degree+1) = 1.
    knots[:degree + 1] = 0.0
    knots[-(degree + 1):] = 1.0

    # Interior knots via averaging rule on interior params (excluding t=0, t=1).
    inner_params = params[1:-1]  # shape (n_pts - 2,)
    for j in range(n_inner_knots):
        # Average over inner_params[j : j+degree].
        segment = inner_params[j: j + degree]
        if len(segment) > 0:
            knots[degree + 1 + j] = float(np.mean(segment))
        else:
            # Fallback: uniform.
            knots[degree + 1 + j] = (j + 1) / (n_inner_knots + 1)

    # Ensure monotonicity (can drift for very sparse data).
    for i in range(1, len(knots)):
        if knots[i] < knots[i - 1]:
            knots[i] = knots[i - 1]

    return knots


def _basis_row(t_val: float, n_ctrl: int, degree: int, knots: np.ndarray) -> np.ndarray:
    """Evaluate all n_ctrl B-spline basis functions at t_val."""
    row = np.zeros(n_ctrl)
    t_val = float(np.clip(t_val, knots[degree], knots[-(degree + 1)]))
    span = find_span(n_ctrl - 1, degree, t_val, knots)
    N = _basis_funcs(span, t_val, degree, knots)
    for r in range(degree + 1):
        row[span - degree + r] = N[r]
    return row


def _deriv_basis_row(
    t_val: float,
    n_ctrl: int,
    degree: int,
    knots: np.ndarray,
    order: int,
) -> np.ndarray:
    """Evaluate the ``order``-th derivative of all B-spline basis functions at t_val."""
    row = np.zeros(n_ctrl)
    t_val = float(np.clip(t_val, knots[degree], knots[-(degree + 1)]))
    span = find_span(n_ctrl - 1, degree, t_val, knots)
    ders = _basis_funcs_derivs(span, t_val, degree, knots, order)  # (order+1, degree+1)
    d_row = ders[order]  # (degree+1,)
    for r in range(degree + 1):
        row[span - degree + r] = d_row[r]
    return row


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def _endpoint_cps_from_derivs(
    P0: np.ndarray,
    T0: np.ndarray,
    K0: np.ndarray,
    P1: np.ndarray,
    T1: np.ndarray,
    K1: np.ndarray,
    degree: int,
    knots: np.ndarray,
) -> tuple:
    """Compute the first two and last two control points from G2 end conditions.

    For a clamped degree-p B-spline with knot vector U, the endpoint derivative
    formulas (Piegl & Tiller §9.4, Eqs 9.26–9.29) give:

        C(0)   = P_0
        C'(0)  = p * (P_1 - P_0) / U[p+1]
        C''(0) = p*(p-1) * [(P_2 - P_1)/U[p+2] - (P_1 - P_0)/U[p+1]] / U[p+2]

    and symmetrically at t=1 (with U reversed, i.e. (1-U)[-p-1] = U[p+1] for
    a normalised [0,1] knot vector).

    Parameters
    ----------
    P0, P1 : (3,) ndarray — first and last data points.
    T0, K0 : (3,) — prescribed C'(0), C''(0).
    T1, K1 : (3,) — prescribed C'(1), C''(1).
    degree  : B-spline degree p.
    knots   : clamped knot vector.

    Returns
    -------
    (cp0, cp1, cp_nm1, cp_nm2) — the four boundary control points.
    cp0   = P_0
    cp1   = P_1  (derived from T0)
    cp_nm1 = P_{n-1}  (derived from T1)
    cp_nm2 = P_{n-2}  (derived from K1)
    """
    p = degree
    # Knot deltas at the start clamped region.
    # u[p+1] is the first distinct interior knot (may equal 0 if all-clamped, which
    # would be degenerate — guard below).
    u_p1 = float(knots[p + 1])   # the first non-zero interior knot
    u_p2 = float(knots[p + 2])   # second from the clamped start

    # At the end: the last distinct interior knots are knots[n_ctrl-1] and knots[n_ctrl-2].
    # n_ctrl = n - degree (len(knots) = n_ctrl + degree + 1, so n_ctrl = len(knots)-degree-1).
    n_ctrl = len(knots) - p - 1
    u_nm1 = float(1.0 - knots[n_ctrl - 1])   # = 1 - ξ_n  where n = n_ctrl-1
    u_nm2 = float(1.0 - knots[n_ctrl - 2])   # = 1 - ξ_{n-1}

    # Guards against degenerate zero-width knot spans.
    eps = 1e-14

    # --- Start CPs ---
    # P_0 = C(0)
    cp0 = P0.copy()

    # P_1 from C'(0): T0 = p*(P_1 - P_0)/u[p+1]
    #   => P_1 = P_0 + T0*u[p+1]/p
    if abs(u_p1) > eps:
        cp1 = cp0 + T0 * u_p1 / float(p)
    else:
        # Degenerate: use uniform spacing fallback (P_1 = P_0 + T0/p).
        cp1 = cp0 + T0 / float(p)

    # P_2 from C''(0):
    #   C''(0) = p*(p-1) * [(P_2-P_1)/ξ_{p+2} - (P_1-P_0)/ξ_{p+1}] / ξ_{p+1}
    # (P&T §9.4; the outer denominator is ξ_{p+1} not ξ_{p+2})
    #   => (P_2-P_1)/u_p2 = K0*u_p1/(p*(p-1)) + (P_1-P_0)/u_p1
    #   => P_2 = P_1 + u_p2 * [K0*u_p1/(p*(p-1)) + (P_1-P_0)/u_p1]
    # (This formula is exact only when p >= 2.)
    if p >= 2 and abs(u_p2) > eps and abs(u_p1) > eps:
        alpha = K0 * u_p1 / (float(p) * float(p - 1)) + (cp1 - cp0) / u_p1
        cp2 = cp1 + u_p2 * alpha
    else:
        cp2 = cp1 + (cp1 - cp0)  # uniform fallback

    # --- End CPs ---
    # P_{n} = C(1)
    cp_n = P1.copy()

    # P_{n-1} from C'(1): T1 = p*(P_n - P_{n-1})/u[-p-2+1]
    # For a clamped [0,1] knot vector, the end-side analogue uses
    #   delta = 1 - knots[-(p+2)].
    if abs(u_nm1) > eps:
        cp_nm1 = cp_n - T1 * u_nm1 / float(p)
    else:
        cp_nm1 = cp_n - T1 / float(p)

    # P_{n-2} from C''(1):
    #   C''(1) = p*(p-1)/u_nm1 * [(P_n-P_{n-1})/u_nm1 - (P_{n-1}-P_{n-2})/u_nm2]
    # Rearranged:
    #   (P_{n-1}-P_{n-2})/u_nm2 = (P_n-P_{n-1})/u_nm1 - K1*u_nm1/(p*(p-1))
    #   P_{n-2} = P_{n-1} - u_nm2 * [(P_n-P_{n-1})/u_nm1 - K1*u_nm1/(p*(p-1))]
    if p >= 2 and abs(u_nm1) > eps and abs(u_nm2) > eps:
        term = (cp_n - cp_nm1) / u_nm1 - K1 * u_nm1 / (float(p) * float(p - 1))
        cp_nm2 = cp_nm1 - u_nm2 * term
    else:
        cp_nm2 = cp_nm1 - (cp_n - cp_nm1)

    return cp0, cp1, cp2, cp_nm2, cp_nm1, cp_n


def fit_curve_g2(
    spec: G2FitSpec,
    degree: int = 5,
) -> G2FitResult:
    """Fit a degree-``degree`` B-spline to ``spec.data_points`` with G2 end conditions.

    Approach (Piegl & Tiller §9.4):
    1. Chord-length parameterise the data points.
    2. Build a clamped knot vector whose interior knots use the P&T averaging
       rule with n_ctrl = n_pts + 4 (square system for degree 5; for lower
       degrees n_ctrl is capped at n_pts + degree - 1 to keep the averaging
       rule well-defined, and the system is solved by weighted least squares).
    3. Fix the first three and last three control points analytically from the
       G1 / G2 endpoint formulas (P&T §9.4 Eqs 9.26–9.29).
    4. Build a collocation system for the remaining n_ctrl - 6 interior CPs
       using the positional data rows with the endpoint CP contributions moved
       to the right-hand side.
    5. Solve via ``numpy.linalg.lstsq``.

    Parameters
    ----------
    spec
        :class:`G2FitSpec` with data points + prescribed tangent/curvature vectors.
    degree
        B-spline degree (default 5; must be ≥ 2 for G2).

    Returns
    -------
    :class:`G2FitResult`
    """
    if degree < 2:
        raise ValueError("degree must be >= 2 for G2 continuity")

    pts_raw = np.array(spec.data_points, dtype=float)
    if pts_raw.ndim != 2 or pts_raw.shape[1] != 3:
        raise ValueError("data_points must be a list of (x, y, z) triples")
    n_pts = len(pts_raw)
    if n_pts < 2:
        raise ValueError("At least 2 data points required")

    T0 = np.array(spec.start_tangent_xyz, dtype=float)
    K0 = np.array(spec.start_curvature_xyz, dtype=float)
    T1 = np.array(spec.end_tangent_xyz, dtype=float)
    K1 = np.array(spec.end_curvature_xyz, dtype=float)

    # ── 1. Chord-length parameterisation ──────────────────────────────────
    t_params = _chord_params(pts_raw)

    # ── 2. Choose number of control points ────────────────────────────────
    # For degree p, the averaging rule (P&T §9.2 Eq 9.8) needs:
    #   n_inner_knots = n_ctrl - p - 1
    # and the averaging window for each interior knot is p params, so we need
    #   len(inner_params) >= n_inner_knots + p - 1.
    # inner_params = t_params[1:-1] has len = n_pts - 2.
    # => n_ctrl - p - 1 + p - 1 <= n_pts - 2
    # => n_ctrl <= n_pts + degree - 1
    # But we also want n_ctrl >= degree + 1 + 2 (at least 2 free interior CPs).
    # Compromise: n_ctrl = min(n_pts + degree - 1, n_pts + 4) always capped at
    # n_pts + degree - 1 for the averaging to stay well-defined.
    n_ctrl = max(min(n_pts + degree - 1, n_pts + 4), degree + 1)

    # ── 3. Knot vector ─────────────────────────────────────────────────────
    inner_params = t_params[1:-1]  # len = n_pts - 2
    n_inner_knots = n_ctrl - degree - 1
    # n_inner_knots <= n_pts - 2 is guaranteed by the cap above.
    # Build extended params (endpoints included) for _clamped_knots.
    ext_params = np.concatenate([[0.0], inner_params, [1.0]])
    knots = _clamped_knots(n_ctrl, degree, ext_params)

    # ── 4. Compute fixed boundary CPs from G2 end conditions ──────────────
    # The first 3 and last 3 CPs are determined analytically.
    # The total n_ctrl must be >= 6 for this to leave free interior CPs.
    # For small n_pts this may overlap — handled below via fallback to lstsq.
    P0 = pts_raw[0]
    P_last = pts_raw[-1]
    cp0, cp1, cp2, cp_nm2, cp_nm1, cp_n = _endpoint_cps_from_derivs(
        P0, T0, K0, P_last, T1, K1, degree, knots
    )

    n_boundary = 6  # 3 at start + 3 at end; indices 0,1,2 and n-3,n-2,n-1.
    n_free = n_ctrl - n_boundary  # number of unconstrained interior CPs.

    if n_free <= 0:
        # Tiny dataset: build full collocation system and solve with lstsq,
        # accepting that G2 constraints are only satisfied approximately.
        # This path is uncommon — needs n_pts <= degree + 1.
        n_rows = n_pts + 4
        A_full = np.zeros((n_rows, n_ctrl))
        b_full = np.zeros((n_rows, 3))
        for k in range(n_pts):
            A_full[k] = _basis_row(t_params[k], n_ctrl, degree, knots)
            b_full[k] = pts_raw[k]
        A_full[n_pts] = _deriv_basis_row(0.0, n_ctrl, degree, knots, 1)
        b_full[n_pts] = T0
        A_full[n_pts + 1] = _deriv_basis_row(1.0, n_ctrl, degree, knots, 1)
        b_full[n_pts + 1] = T1
        A_full[n_pts + 2] = _deriv_basis_row(0.0, n_ctrl, degree, knots, 2)
        b_full[n_pts + 2] = K0
        A_full[n_pts + 3] = _deriv_basis_row(1.0, n_ctrl, degree, knots, 2)
        b_full[n_pts + 3] = K1
        ctrl_pts, _, _, _ = np.linalg.lstsq(A_full, b_full, rcond=None)
    else:
        # Assemble fixed boundary CPs array.
        fixed_cps = np.zeros((n_ctrl, 3))
        fixed_cps[0] = cp0
        fixed_cps[1] = cp1
        fixed_cps[2] = cp2
        fixed_cps[n_ctrl - 3] = cp_nm2
        fixed_cps[n_ctrl - 2] = cp_nm1
        fixed_cps[n_ctrl - 1] = cp_n

        # Interior indices (3 .. n_ctrl-4 inclusive).
        interior_idx = list(range(3, n_ctrl - 3))
        assert len(interior_idx) == n_free

        # Build reduced collocation system: A_red is (n_pts, n_free).
        # b_red[k] = pts_raw[k] - sum_{j in boundary} N_j(t_k) * fixed_cps[j]
        A_full_pos = np.zeros((n_pts, n_ctrl))
        for k in range(n_pts):
            A_full_pos[k] = _basis_row(t_params[k], n_ctrl, degree, knots)

        # Columns for boundary CPs.
        boundary_idx = list(range(3)) + list(range(n_ctrl - 3, n_ctrl))
        A_boundary = A_full_pos[:, boundary_idx]  # (n_pts, 6)
        boundary_vals = np.vstack([cp0, cp1, cp2, cp_nm2, cp_nm1, cp_n])  # (6, 3)
        rhs = pts_raw - A_boundary @ boundary_vals  # (n_pts, 3)

        A_red = A_full_pos[:, interior_idx]  # (n_pts, n_free)

        if n_pts < n_free:
            # Under-determined: still solvable via lstsq (minimum-norm solution).
            free_vals, _, _, _ = np.linalg.lstsq(A_red, rhs, rcond=None)
        else:
            free_vals, _, _, _ = np.linalg.lstsq(A_red, rhs, rcond=None)

        ctrl_pts = fixed_cps.copy()
        for idx, fi in enumerate(interior_idx):
            ctrl_pts[fi] = free_vals[idx]

    # ── 5. Build NurbsCurve ────────────────────────────────────────────────
    curve = NurbsCurve(
        degree=degree,
        control_points=ctrl_pts,
        knots=knots,
    )

    # ── 6. Compute residual metrics ────────────────────────────────────────
    pos_residuals = []
    for k in range(n_pts):
        t_k = float(t_params[k])
        pt_eval = curve.evaluate(t_k)
        pos_residuals.append(float(np.linalg.norm(pt_eval - pts_raw[k])))

    max_res = float(np.max(pos_residuals)) if pos_residuals else 0.0
    mean_res = float(np.mean(pos_residuals)) if pos_residuals else 0.0

    # G2 residuals at endpoints.
    C_deriv_start = curve.derivative(0.0, order=2)
    C_deriv_end = curve.derivative(1.0, order=2)
    start_g2_res = float(np.linalg.norm(C_deriv_start - K0))
    end_g2_res = float(np.linalg.norm(C_deriv_end - K1))

    caveat = (
        "Chord-length parameterisation used (not centripetal). "
        "For high-aspect-ratio data or data with large spacing variation, "
        "centripetal parameterisation (Lee 1989) may give smaller oscillations. "
        "Curvature vectors are *parametric* second derivatives C''(t), not "
        "Frenet curvature κ(s) — pass C'' of the adjacent curve for blending. "
        "Boundary control points are determined analytically (P&T §9.4 Eqs 9.26–9.29); "
        "interior control points are solved by least squares over data points. "
        "For n_pts < degree+4 the interior system may be underdetermined."
    )

    return G2FitResult(
        fitted_curve=curve,
        max_residual_mm=max_res,
        mean_residual_mm=mean_res,
        start_g2_residual=start_g2_res,
        end_g2_residual=end_g2_res,
        honest_caveat=caveat,
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

    _fit_g2_spec = ToolSpec(
        name="nurbs_fit_curve_g2",
        description=(
            "Fit a degree-5 NURBS B-spline curve to a set of 3-D data points with G2 "
            "(curvature) continuity at both endpoints.\n"
            "\n"
            "Prescribe tangent (first parametric derivative) and curvature (second parametric "
            "derivative) vectors at the start and end of the curve — required for smooth "
            "blending against adjacent surfaces or curves.\n"
            "\n"
            "Algorithm: chord-length parameterisation + clamped knot averaging + "
            "least-squares collocation with 4 derivative-condition rows (Piegl & Tiller §9.4).\n"
            "\n"
            "Returns:\n"
            "  ok                  : bool\n"
            "  curve               : {control_points, knots, degree}\n"
            "  max_residual_mm     : float — worst-case positional error\n"
            "  mean_residual_mm    : float — mean positional error\n"
            "  start_g2_residual   : float — ||C''(0) − K_start||\n"
            "  end_g2_residual     : float — ||C''(1) − K_end||\n"
            "  honest_caveat       : str\n"
            "\n"
            "HONEST caveats:\n"
            "  - Chord-length parameterisation; centripetal may give better results for "
            "    high-aspect-ratio curves (set degree=5 and re-check residuals).\n"
            "  - Curvature vectors are *parametric* second derivatives C''(t), NOT the "
            "    Frenet curvature κ·n̂ — for blending use the adjacent curve's C''(t_join).\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "required": ["data_points", "start_tangent", "start_curvature",
                         "end_tangent", "end_curvature"],
            "properties": {
                "data_points": {
                    "type": "array",
                    "description": "List of [x, y, z] data points to fit.",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "minItems": 2,
                },
                "start_tangent": {
                    "type": "array",
                    "description": "Prescribed C'(0) — first parametric derivative at start [x, y, z].",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "start_curvature": {
                    "type": "array",
                    "description": "Prescribed C''(0) — second parametric derivative at start [x, y, z].",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "end_tangent": {
                    "type": "array",
                    "description": "Prescribed C'(1) — first parametric derivative at end [x, y, z].",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "end_curvature": {
                    "type": "array",
                    "description": "Prescribed C''(1) — second parametric derivative at end [x, y, z].",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "degree": {
                    "type": "integer",
                    "description": "B-spline degree (default 5; must be ≥ 2).",
                    "default": 5,
                    "minimum": 2,
                },
            },
        },
    )

    @register(_fit_g2_spec)
    async def run_nurbs_fit_curve_g2(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        dp_raw = a.get("data_points")
        st_raw = a.get("start_tangent")
        sk_raw = a.get("start_curvature")
        et_raw = a.get("end_tangent")
        ek_raw = a.get("end_curvature")

        if any(v is None for v in [dp_raw, st_raw, sk_raw, et_raw, ek_raw]):
            return err_payload(
                "data_points, start_tangent, start_curvature, end_tangent, "
                "end_curvature are all required",
                "BAD_ARGS",
            )

        try:
            data_pts = [tuple(float(c) for c in pt) for pt in dp_raw]
            T0 = tuple(float(c) for c in st_raw)
            K0 = tuple(float(c) for c in sk_raw)
            T1 = tuple(float(c) for c in et_raw)
            K1 = tuple(float(c) for c in ek_raw)
        except Exception as exc:
            return err_payload(f"invalid coordinate data: {exc}", "BAD_ARGS")

        deg = int(a.get("degree", 5))
        if deg < 2:
            return err_payload("degree must be >= 2", "BAD_ARGS")

        spec = G2FitSpec(
            data_points=data_pts,
            start_tangent_xyz=T0,
            start_curvature_xyz=K0,
            end_tangent_xyz=T1,
            end_curvature_xyz=K1,
        )

        try:
            result = fit_curve_g2(spec, degree=deg)
        except Exception as exc:
            return err_payload(f"curve fit failed: {exc}", "OP_FAILED")

        return ok_payload({
            "curve": {
                "control_points": result.fitted_curve.control_points.tolist(),
                "knots": result.fitted_curve.knots.tolist(),
                "degree": result.fitted_curve.degree,
            },
            "max_residual_mm": result.max_residual_mm,
            "mean_residual_mm": result.mean_residual_mm,
            "start_g2_residual": result.start_g2_residual,
            "end_g2_residual": result.end_g2_residual,
            "honest_caveat": result.honest_caveat,
        })
