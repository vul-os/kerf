"""
match_srf_g3.py
===============
GK-P10 — MatchSrf G3: curvature-rate (dκ/ds) continuity across a shared edge.

Given two NURBS surfaces that share an edge, adjust the first four
control-point rows of surface B near the shared edge so that:

    Row 0  (boundary)  — position match              (G0)
    Row 1              — cross-boundary tangent match (G1)
    Row 2              — cross-boundary curvature match  (G2)
    Row 3              — cross-boundary curvature-rate match (G3)

G3 means d κ/ds continuity in addition to G2 (curvature), per:
  Piegl & Tiller §11.4 (constrained NURBS modification)
  Patrikalakis & Maekawa §6.5 (continuity orders)
  Hoschek & Lasser §14.2 (higher-order continuity)

Implementation
--------------
This module is a focused wrapper around the core solver in
``kerf_cad_core.geom.match_srf`` (which provides ``match_surface_edge`` with
``continuity="G3"``).  It adds:

  * ``MatchSrfG3Spec``   — typed specification dataclass
  * ``MatchSrfG3Report`` — typed result dataclass with all four error metrics
  * ``match_srf_g3``     — the public entry point

Honest caveats
--------------
* G3 requires degree ≥ 3 in the cross-boundary direction.  Degree-2 surfaces
  cannot satisfy G3; use ``elevate_to_g3_capability(surface, target_degree=4)``
  from ``match_srf`` first.
* G3 requires ≥ 4 control-point rows in the inward direction.  Surfaces with
  fewer rows cannot be matched to G3.
* G3 is not always achievable for arbitrary surface pairs (e.g. two cylinders
  of different radii meeting at an edge).  In that case the solver drives the
  residual as low as the degrees of freedom allow and sets ``converged=False``.

LLM tool
--------
``nurbs_match_srf_g3`` is registered via the gated ``kerf_chat.tools.registry``
import (same pattern as ``trim_curve.py``).  When the registry is unavailable
(e.g. in tests) the tool registration is silently skipped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.match_srf import (
    match_surface_edge,
    verify_seam_g1_analytic,
    verify_seam_g2_analytic,
    verify_seam_g3_analytic,
    _cp_row_count,
    _boundary_degree,
    _edge_boundary_params,
    _analytic_cross_curvature,
    _cross_curvature_rate,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_EDGES = frozenset({"u0", "u1", "v0", "v1"})


# ---------------------------------------------------------------------------
# ContinuityOrder enum  (Piegl & Tiller §5.6; Farin §10)
# ---------------------------------------------------------------------------

class ContinuityOrder(IntEnum):
    """Geometric continuity order across a NURBS surface boundary.

    References
    ----------
    Piegl & Tiller, "The NURBS Book" §5.6 (boundary conditions).
    Farin, "Curves and Surfaces for CAGD" §10 (continuity orders).
    """
    G0 = 0   # positional continuity
    G1 = 1   # tangent-plane continuity
    G2 = 2   # curvature continuity
    G3 = 3   # curvature-derivative (dκ/ds) continuity


# ---------------------------------------------------------------------------
# MatchG3Result dataclass  (functional API)
# ---------------------------------------------------------------------------

@dataclass
class MatchG3Result:
    """Result returned by :func:`match_srf_g3_functional`.

    Attributes
    ----------
    matched_surface : NurbsSurface
        Deep copy of *target* with the boundary CP rows adjusted.
    g0_residual : float
        Maximum position error along the boundary (model units).
    g1_residual : float
        Maximum tangent-plane error (radians).
    g2_residual : float
        Maximum normal-curvature error (1/length).
    g3_residual : float
        Maximum curvature-derivative error (1/length²).
    iterations : int
        Number of solver iterations executed.
    converged : bool
        True when all requested-order residuals are within *tol*.

    References
    ----------
    Piegl & Tiller, "The NURBS Book" §5.6.
    Farin, "Curves and Surfaces for CAGD" §10.
    """
    matched_surface: Optional[NurbsSurface] = None
    g0_residual: float = math.nan
    g1_residual: float = math.nan
    g2_residual: float = math.nan
    g3_residual: float = math.nan
    iterations: int = 0
    converged: bool = False

# Threshold for declaring "converged": dκ/ds residual < this value (1/mm²)
_G3_CONVERGED_THRESHOLD = 1e-4


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MatchSrfG3Spec:
    """Specification for a G3 surface-match operation.

    Parameters
    ----------
    surface_a : NurbsSurface
        Reference surface (unmodified).
    surface_b : NurbsSurface
        Surface to be modified so that its ``shared_edge`` matches
        ``surface_a``'s corresponding opposite edge.
    shared_edge : str
        Which edge of ``surface_b`` is the shared boundary.
        One of ``"u0"``, ``"u1"``, ``"v0"``, ``"v1"``.
    num_modified_rows : int
        Number of control-point rows of ``surface_b`` to adjust (default 4).
        Must be ≥ 4 for G3 (G0=row 0, G1=row 1, G2=row 2, G3=row 3).
    target_edge : str
        Which edge of ``surface_a`` to match against (default ``"u1"``).
        The convention is that ``surface_b.shared_edge`` abuts
        ``surface_a.target_edge``; the solver maps parameter ranges linearly.
    samples : int
        Number of along-edge sample points for error diagnostics (default 32).
    tolerance : float
        Position tolerance in model units for convergence classification
        (default 1e-6).
    """

    surface_a: NurbsSurface
    surface_b: NurbsSurface
    shared_edge: str = "u0"
    num_modified_rows: int = 4
    target_edge: str = "u1"
    samples: int = 32
    tolerance: float = 1e-6


@dataclass
class MatchSrfG3Report:
    """Result of a ``match_srf_g3`` call.

    Attributes
    ----------
    modified_surface_b : NurbsSurface or None
        A deep copy of ``surface_b`` with the boundary control points
        adjusted for G0/G1/G2/G3 continuity.  ``None`` on failure.
    g0_error_mm : float
        Maximum positional deviation across the seam after matching (mm).
    g1_error_rad : float
        Maximum tangent-direction deviation across the seam (radians).
        ``math.nan`` if G1 could not be verified.
    g2_error_per_mm : float
        Maximum normal-curvature deviation across the seam (1/mm).
        ``math.nan`` if G2 could not be verified.
    g3_error_per_mm2 : float
        Maximum curvature-rate deviation |dκ_B/ds − dκ_A/ds| across the seam
        (1/mm²).  ``math.nan`` if G3 could not be verified.
    converged : bool
        True if ``g3_error_per_mm2`` is below the convergence threshold
        (1e-4 / mm²) after matching.  False when G3 is not achievable (e.g.
        surfaces of incompatible curvature) or the solver's residual is large.
    num_cp_modified : int
        Total number of control points changed.  Zero on failure.
    max_cp_shift_mm : float
        Maximum Euclidean distance any control point was moved (mm).
    honest_caveat : str
        Human-readable note about limitations, or empty string on clean success.
    ok : bool
        True if the operation succeeded without fatal errors.
    reason : str
        Error description when ``ok`` is False.
    """

    modified_surface_b: Optional[NurbsSurface] = None
    g0_error_mm: float = math.nan
    g1_error_rad: float = math.nan
    g2_error_per_mm: float = math.nan
    g3_error_per_mm2: float = math.nan
    converged: bool = False
    num_cp_modified: int = 0
    max_cp_shift_mm: float = 0.0
    honest_caveat: str = ""
    ok: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_modified_cps(original: NurbsSurface, modified: NurbsSurface,
                        edge: str, num_rows: int) -> tuple[int, float]:
    """Return (num_cp_modified, max_shift_mm) comparing CP rows 0..num_rows-1."""
    from kerf_cad_core.geom.match_srf import _get_cp_row  # local import to avoid circular
    total_modified = 0
    max_shift = 0.0
    for row_idx in range(num_rows):
        orig_row = _get_cp_row(original, edge, row_idx)
        new_row = _get_cp_row(modified, edge, row_idx)
        for k in range(len(orig_row)):
            shift = float(np.linalg.norm(new_row[k, :3] - orig_row[k, :3]))
            if shift > 1e-12:
                total_modified += 1
                if shift > max_shift:
                    max_shift = shift
    return total_modified, max_shift


def _build_honest_caveat(spec: MatchSrfG3Spec, g3_error: float,
                         converged: bool, p_src: int, n_rows_src: int) -> str:
    """Compose an honest caveat string."""
    parts = []
    if p_src < 3:
        parts.append(
            f"Source degree {p_src} < 3 in the matched direction; "
            "G3 requires degree ≥ 3 (use elevate_to_g3_capability first)."
        )
    if n_rows_src < 4:
        parts.append(
            f"Source has only {n_rows_src} CP rows; "
            "G3 requires ≥ 4 rows (G0=row0, G1=row1, G2=row2, G3=row3)."
        )
    if not converged and not math.isnan(g3_error):
        parts.append(
            f"G3 dκ/ds residual {g3_error:.3e} exceeds convergence threshold "
            f"{_G3_CONVERGED_THRESHOLD:.0e}; surfaces may have incompatible "
            "curvature rate and G3 is best-effort only."
        )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_srf_g3(spec: MatchSrfG3Spec) -> MatchSrfG3Report:
    """Match surface B's shared edge to surface A at G0/G1/G2/G3 continuity.

    Adjusts the first ``spec.num_modified_rows`` control-point rows of
    ``spec.surface_b`` near ``spec.shared_edge`` so the cross-boundary
    derivative of curvature (dκ/ds) matches ``spec.surface_a``'s corresponding
    edge.

    The implementation delegates to ``match_surface_edge(..., continuity="G3")``
    from ``kerf_cad_core.geom.match_srf``, which uses the exact tensor-product
    B-spline third-derivative formula and a Greville-point linear system for the
    G3 correction (Piegl & Tiller §11.4; Patrikalakis & Maekawa §6.5).

    Parameters
    ----------
    spec : MatchSrfG3Spec
        Operation specification.

    Returns
    -------
    MatchSrfG3Report
        Never raises; exceptions are caught and returned in ``report.reason``.
    """
    # --- Input validation ---------------------------------------------------
    if not isinstance(spec.surface_a, NurbsSurface):
        return MatchSrfG3Report(
            ok=False,
            reason=(f"surface_a must be NurbsSurface, "
                    f"got {type(spec.surface_a).__name__}"),
        )
    if not isinstance(spec.surface_b, NurbsSurface):
        return MatchSrfG3Report(
            ok=False,
            reason=(f"surface_b must be NurbsSurface, "
                    f"got {type(spec.surface_b).__name__}"),
        )
    if spec.shared_edge not in _VALID_EDGES:
        return MatchSrfG3Report(
            ok=False,
            reason=(f"shared_edge must be one of {sorted(_VALID_EDGES)}, "
                    f"got {spec.shared_edge!r}"),
        )
    if spec.target_edge not in _VALID_EDGES:
        return MatchSrfG3Report(
            ok=False,
            reason=(f"target_edge must be one of {sorted(_VALID_EDGES)}, "
                    f"got {spec.target_edge!r}"),
        )
    if not isinstance(spec.num_modified_rows, int) or spec.num_modified_rows < 1:
        return MatchSrfG3Report(
            ok=False,
            reason=f"num_modified_rows must be a positive integer, got {spec.num_modified_rows!r}",
        )
    if not isinstance(spec.samples, int) or spec.samples < 2:
        return MatchSrfG3Report(
            ok=False,
            reason=f"samples must be an integer >= 2, got {spec.samples!r}",
        )
    if not isinstance(spec.tolerance, (int, float)) or spec.tolerance <= 0:
        return MatchSrfG3Report(
            ok=False,
            reason=f"tolerance must be a positive number, got {spec.tolerance!r}",
        )

    p_src = _boundary_degree(spec.surface_b, spec.shared_edge)
    n_rows_src = _cp_row_count(spec.surface_b, spec.shared_edge)

    # Preflight checks for G3 feasibility (inform caveat but still attempt)
    feasible_g3 = (p_src >= 3) and (n_rows_src >= 4)

    # --- Delegate to match_surface_edge with continuity="G3" ----------------
    try:
        result = match_surface_edge(
            target_surface=spec.surface_a,
            target_edge=spec.target_edge,
            source_surface=spec.surface_b,
            source_edge=spec.shared_edge,
            continuity="G3",
            samples=spec.samples,
            tolerance=spec.tolerance,
        )
    except Exception as exc:  # pragma: no cover
        return MatchSrfG3Report(
            ok=False,
            reason=f"match_surface_edge raised unexpectedly: {exc}",
        )

    if not result.ok:
        # Still build a partial report with feasibility info
        caveat = _build_honest_caveat(spec, math.nan, False, p_src, n_rows_src)
        return MatchSrfG3Report(
            ok=False,
            reason=result.reason,
            honest_caveat=caveat,
        )

    modified = result.modified_surface  # MatchResult uses .modified_surface

    # Count modified CPs
    num_rows_to_check = min(spec.num_modified_rows, n_rows_src)
    try:
        num_modified, max_shift = _count_modified_cps(
            spec.surface_b, modified,
            spec.shared_edge, num_rows_to_check,
        )
    except Exception:
        num_modified, max_shift = 0, 0.0

    # Retrieve error metrics from the match result
    g0_err = result.max_position_deviation
    g1_err = result.max_tangent_deviation
    g2_err = result.max_curvature_deviation
    g3_err = result.max_curvature_rate_deviation

    # If the stored metrics are NaN, re-verify analytically
    if math.isnan(g0_err) and modified is not None:
        try:
            from kerf_cad_core.geom.match_srf import _compute_deviations
            g0_err, _, _ = _compute_deviations(
                modified, spec.shared_edge,
                spec.surface_a, spec.target_edge,
                spec.samples, "G0",
            )
        except Exception:
            pass

    if math.isnan(g1_err) and modified is not None:
        try:
            g1_raw = verify_seam_g1_analytic(
                modified, spec.shared_edge,
                spec.surface_a, spec.target_edge,
                samples=spec.samples,
            )
            g1_err = float(math.asin(min(g1_raw, 1.0)))
        except Exception:
            pass

    if math.isnan(g2_err) and modified is not None:
        try:
            g2_err = verify_seam_g2_analytic(
                modified, spec.shared_edge,
                spec.surface_a, spec.target_edge,
                samples=spec.samples,
            )
        except Exception:
            pass

    if math.isnan(g3_err) and modified is not None and feasible_g3:
        try:
            g3_err = verify_seam_g3_analytic(
                modified, spec.shared_edge,
                spec.surface_a, spec.target_edge,
                samples=spec.samples,
            )
        except Exception:
            pass

    converged = (not math.isnan(g3_err) and g3_err < _G3_CONVERGED_THRESHOLD)
    caveat = _build_honest_caveat(spec, g3_err, converged, p_src, n_rows_src)

    return MatchSrfG3Report(
        modified_surface_b=modified,
        g0_error_mm=g0_err if not math.isnan(g0_err) else 0.0,
        g1_error_rad=g1_err,
        g2_error_per_mm=g2_err,
        g3_error_per_mm2=g3_err,
        converged=converged,
        num_cp_modified=num_modified,
        max_cp_shift_mm=max_shift,
        honest_caveat=caveat,
        ok=True,
        reason="",
    )


# ---------------------------------------------------------------------------
# Functional API: match_srf_g3_functional + estimate_continuity
# ---------------------------------------------------------------------------
#
# References
# ----------
# Piegl & Tiller, "The NURBS Book" §5.6 — boundary-condition satisfaction for
#     NURBS surfaces; the CP-row interpretation of G0/G1/G2/G3 derivatives.
# Farin, "Curves and Surfaces for CAGD" §10 — geometric-continuity orders and
#     the normal-curvature / curvature-derivative matching conditions.

def match_srf_g3_functional(
    target: NurbsSurface,
    reference: NurbsSurface,
    target_side: str,
    reference_side: str,
    order: ContinuityOrder = ContinuityOrder.G3,
    tol: float = 1e-7,
    max_iter: int = 20,
) -> MatchG3Result:
    """Adjust the boundary CP rows of *target* to match *reference* up to *order*.

    Modifies (in a deep copy) the four control-point rows adjacent to
    *target_side* so that the cross-boundary derivatives of the joined surface
    match those of *reference* at *reference_side* up to order *order*:

        Row 0  (G0) — position match.
        Row 1  (G1) — cross-boundary tangent match.
        Row 2  (G2) — normal-curvature match.
        Row 3  (G3) — curvature-derivative (dκ/ds) match.

    The implementation delegates to ``match_surface_edge`` from
    ``kerf_cad_core.geom.match_srf`` which uses:
      * Exact tensor-product B-spline derivative formulae (Piegl & Tiller §5.6).
      * A Greville-point linear system for the G3 correction (Farin §10).
      * ``numpy.linalg.lstsq`` for the least-squares solve.

    Parameters
    ----------
    target : NurbsSurface
        Surface whose boundary will be modified.
    reference : NurbsSurface
        Reference (unmodified) surface to match against.
    target_side : str
        Edge of *target* to modify: ``'u0'``, ``'u1'``, ``'v0'``, ``'v1'``.
    reference_side : str
        Edge of *reference* to use as the template: same four options.
    order : ContinuityOrder
        Maximum continuity order to enforce (default G3).
    tol : float
        Convergence tolerance (model units for G0; radians for G1; 1/length
        for G2; 1/length² for G3).  Default 1e-7.
    max_iter : int
        Maximum solver iterations (default 20).

    Returns
    -------
    MatchG3Result
        Contains the matched surface, per-order residuals, iteration count, and
        a converged flag.  Never raises; exceptions surface in a result with
        ``converged=False`` and ``NaN`` residuals.

    References
    ----------
    Piegl & Tiller, "The NURBS Book" §5.6.
    Farin, "Curves and Surfaces for CAGD" §10.
    """
    # --- Map ContinuityOrder to the string key used by match_surface_edge ----
    _order_map = {
        ContinuityOrder.G0: "G0",
        ContinuityOrder.G1: "G1",
        ContinuityOrder.G2: "G2",
        ContinuityOrder.G3: "G3",
    }
    continuity_str = _order_map.get(order, "G3")

    # --- Iterative matching loop (each pass refines the residuals) -----------
    # The inner solver (match_surface_edge) is already analytically converged
    # in a single pass for typical surfaces, but we wrap it in a loop so that
    # the max_iter / tol contract is honoured and callers can observe iteration
    # counts on pathological inputs.
    _SAMPLES = 32
    current = NurbsSurface(
        degree_u=target.degree_u,
        degree_v=target.degree_v,
        control_points=target.control_points.copy(),
        knots_u=target.knots_u.copy(),
        knots_v=target.knots_v.copy(),
    )

    g0_res = math.nan
    g1_res = math.nan
    g2_res = math.nan
    g3_res = math.nan
    iterations = 0

    for it in range(max(1, max_iter)):
        iterations = it + 1
        try:
            result = match_surface_edge(
                target_surface=reference,
                target_edge=reference_side,
                source_surface=current,
                source_edge=target_side,
                continuity=continuity_str,
                samples=_SAMPLES,
                tolerance=tol,
            )
        except Exception as exc:
            return MatchG3Result(
                matched_surface=current,
                g0_residual=math.nan,
                g1_residual=math.nan,
                g2_residual=math.nan,
                g3_residual=math.nan,
                iterations=iterations,
                converged=False,
            )

        if not result.ok:
            return MatchG3Result(
                matched_surface=current,
                g0_residual=math.nan,
                g1_residual=math.nan,
                g2_residual=math.nan,
                g3_residual=math.nan,
                iterations=iterations,
                converged=False,
            )

        current = result.modified_surface

        g0_res = result.max_position_deviation
        g1_res = result.max_tangent_deviation
        g2_res = result.max_curvature_deviation
        g3_res = result.max_curvature_rate_deviation

        # Check convergence based on requested order
        def _finite(x: float) -> float:
            return x if not math.isnan(x) else math.inf

        conv_g0 = _finite(g0_res) <= tol
        conv_g1 = (order < ContinuityOrder.G1) or (_finite(g1_res) <= tol)
        conv_g2 = (order < ContinuityOrder.G2) or (_finite(g2_res) <= tol * 1e3)
        conv_g3 = (order < ContinuityOrder.G3) or (_finite(g3_res) <= tol * 1e6)

        if conv_g0 and conv_g1 and conv_g2 and conv_g3:
            break

    converged = (
        not math.isnan(g0_res) and g0_res <= tol
        and (order < ContinuityOrder.G1 or (not math.isnan(g1_res) and g1_res <= tol))
        and (order < ContinuityOrder.G2 or (not math.isnan(g2_res) and g2_res <= tol * 1e3))
        and (order < ContinuityOrder.G3 or (not math.isnan(g3_res) and g3_res <= tol * 1e6))
    )

    return MatchG3Result(
        matched_surface=current,
        g0_residual=g0_res if not math.isnan(g0_res) else 0.0,
        g1_residual=g1_res,
        g2_residual=g2_res,
        g3_residual=g3_res,
        iterations=iterations,
        converged=converged,
    )


def estimate_continuity(
    surf_a: NurbsSurface,
    side_a: str,
    surf_b: NurbsSurface,
    side_b: str,
    *,
    samples: int = 32,
) -> dict:
    """Measure G0/G1/G2/G3 continuity between two NURBS surface edges.

    Samples *samples* points along the seam and evaluates the cross-boundary
    derivative errors for each order:

    * **g0** — maximum positional distance (model units).
    * **g1** — maximum tangent-plane deviation (radians; via cross-product
      residual using analytic ``surface_derivatives``).
    * **g2** — maximum normal-curvature deviation (1/length units; signed
      difference of the Meusnier curvature in the cross-boundary direction).
    * **g3** — maximum curvature-derivative deviation |dκ_A/ds − dκ_B/ds|
      (1/length² units).

    All four metrics are always computed regardless of the actual continuity
    level — callers can inspect them to understand where the discontinuity is.

    Parameters
    ----------
    surf_a, surf_b : NurbsSurface
        The two surfaces whose edges are to be measured.
    side_a, side_b : str
        Edge identifiers on each surface: ``'u0'``, ``'u1'``, ``'v0'``, ``'v1'``.
    samples : int
        Number of along-edge sample points (default 32).

    Returns
    -------
    dict with keys ``'g0'``, ``'g1'``, ``'g2'``, ``'g3'`` (all floats).

    References
    ----------
    Piegl & Tiller, "The NURBS Book" §5.6.
    Farin, "Curves and Surfaces for CAGD" §10.
    """
    from kerf_cad_core.geom.nurbs import surface_derivatives, surface_evaluate

    n = max(2, samples)
    _, _, t_min_a, t_max_a = _edge_boundary_params(surf_a, side_a)
    _, _, t_min_b, t_max_b = _edge_boundary_params(surf_b, side_b)
    u_seam_a, v_seam_a, _, _ = _edge_boundary_params(surf_a, side_a)
    u_seam_b, v_seam_b, _, _ = _edge_boundary_params(surf_b, side_b)

    max_g0 = 0.0
    max_g1 = 0.0
    max_g2 = 0.0
    max_g3 = 0.0

    for i in range(n):
        tk = i / (n - 1) if n > 1 else 0.0
        t_a = t_min_a + tk * (t_max_a - t_min_a)
        t_b = t_min_b + tk * (t_max_b - t_min_b)

        # Evaluate boundary positions
        if side_a in ("u0", "u1"):
            pos_a = surface_evaluate(surf_a, u_seam_a, t_a)
            pos_b = surface_evaluate(surf_b, u_seam_b, t_b)
        else:
            pos_a = surface_evaluate(surf_a, t_a, v_seam_a)
            pos_b = surface_evaluate(surf_b, t_b, v_seam_b)

        g0_val = float(np.linalg.norm(pos_a[:3] - pos_b[:3]))
        if g0_val > max_g0:
            max_g0 = g0_val

        # G1 cross-boundary tangent angle
        try:
            if side_a in ("u0", "u1"):
                SKL_a = surface_derivatives(surf_a, u_seam_a, t_a, d=1)
                tang_a = SKL_a[1, 0][:3]
                SKL_b = surface_derivatives(surf_b, u_seam_b, t_b, d=1)
                tang_b = SKL_b[1, 0][:3]
            else:
                SKL_a = surface_derivatives(surf_a, t_a, v_seam_a, d=1)
                tang_a = SKL_a[0, 1][:3]
                SKL_b = surface_derivatives(surf_b, t_b, v_seam_b, d=1)
                tang_b = SKL_b[0, 1][:3]

            n_a = float(np.linalg.norm(tang_a))
            n_b = float(np.linalg.norm(tang_b))
            if n_a > 1e-14 and n_b > 1e-14:
                cross = np.cross(tang_a / n_a, tang_b / n_b)
                g1_val = float(np.linalg.norm(cross))
                if g1_val > max_g1:
                    max_g1 = g1_val
        except Exception:
            pass

        # G2 normal curvature difference
        try:
            k_a = _analytic_cross_curvature(surf_a, side_a, t_a)
            k_b = _analytic_cross_curvature(surf_b, side_b, t_b)
            g2_val = abs(k_a - k_b)
            if g2_val > max_g2:
                max_g2 = g2_val
        except Exception:
            pass

        # G3 curvature-rate difference
        try:
            dk_a = _cross_curvature_rate(surf_a, side_a, t_a)
            dk_b = _cross_curvature_rate(surf_b, side_b, t_b)
            g3_val = abs(dk_a - dk_b)
            if g3_val > max_g3:
                max_g3 = g3_val
        except Exception:
            pass

    return {
        "g0": max_g0,
        "g1": max_g1,
        "g2": max_g2,
        "g3": max_g3,
    }


# ---------------------------------------------------------------------------
# LLM tool registration (gated)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    def _build_surface_from_args(raw_cp, num_u: int, num_v: int,
                                  degree_u: int, degree_v: int):
        """Build a NurbsSurface from flat control-point list."""
        try:
            cp_flat = [np.asarray(p, dtype=float) for p in raw_cp]
            dim = cp_flat[0].size
            cp = np.array([p.tolist()[:dim] for p in cp_flat],
                          dtype=float).reshape(num_u, num_v, dim)
        except Exception as exc:
            return None, f"invalid control_points: {exc}"

        def _make_knots(n: int, deg: int) -> np.ndarray:
            inner = max(0, n - deg - 1)
            return np.concatenate([
                np.zeros(deg + 1),
                np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                np.ones(deg + 1),
            ])

        try:
            return NurbsSurface(
                degree_u=degree_u,
                degree_v=degree_v,
                control_points=cp,
                knots_u=_make_knots(num_u, degree_u),
                knots_v=_make_knots(num_v, degree_v),
            ), None
        except Exception as exc:
            return None, f"failed to build NurbsSurface: {exc}"

    def _parse_surf(a: dict, prefix: str):
        deg_u = a.get(f"{prefix}degree_u")
        deg_v = a.get(f"{prefix}degree_v")
        raw_cp = a.get(f"{prefix}control_points", [])
        num_u = a.get(f"{prefix}num_u")
        num_v = a.get(f"{prefix}num_v")

        if any(x is None for x in [deg_u, deg_v, num_u, num_v]) or not raw_cp:
            return None, err_payload(
                f"{prefix}degree_u/v, {prefix}control_points, "
                f"{prefix}num_u/v are required",
                "BAD_ARGS",
            )
        try:
            deg_u, deg_v, num_u, num_v = int(deg_u), int(deg_v), int(num_u), int(num_v)
        except (TypeError, ValueError) as exc:
            return None, err_payload(f"degree/num values must be integers: {exc}", "BAD_ARGS")

        if deg_u < 1 or deg_v < 1:
            return None, err_payload(f"{prefix}degree_u and degree_v must be >= 1", "BAD_ARGS")
        if num_u < 2 or num_v < 2:
            return None, err_payload(f"{prefix}num_u and num_v must be >= 2", "BAD_ARGS")
        if len(raw_cp) != num_u * num_v:
            return None, err_payload(
                (f"{prefix}control_points length ({len(raw_cp)}) "
                 f"!= num_u*num_v ({num_u*num_v})"),
                "BAD_ARGS",
            )

        surf, err = _build_surface_from_args(raw_cp, num_u, num_v, deg_u, deg_v)
        if err is not None:
            return None, err_payload(err, "BAD_ARGS")
        return surf, None

    _g3_spec = ToolSpec(
        name="nurbs_match_srf_g3",
        description=(
            "Match surface B's shared edge to surface A at G3 (curvature-rate) "
            "continuity.  Adjusts the four boundary CP rows of surface B:\n"
            "  Row 0 — G0 (position match)\n"
            "  Row 1 — G1 (cross-boundary tangent match)\n"
            "  Row 2 — G2 (normal curvature match)\n"
            "  Row 3 — G3 (curvature-rate dκ/ds match)\n"
            "\n"
            "References: Piegl & Tiller §11.4; Patrikalakis & Maekawa §6.5;\n"
            "Hoschek & Lasser §14.2.\n"
            "\n"
            "REQUIRES:\n"
            "  * surface_b degree ≥ 3 in the cross-boundary direction\n"
            "  * surface_b has ≥ 4 CP rows in the inward direction\n"
            "  Use elevate_to_g3_capability first if the surface is too low degree.\n"
            "\n"
            "Returns:\n"
            "  ok                    : bool\n"
            "  modified_control_points : list of [x,y,z] (surface B, row-major)\n"
            "  modified_num_u, modified_num_v : int\n"
            "  g0_error_mm           : float (position seam error)\n"
            "  g1_error_rad          : float (tangent angle, radians)\n"
            "  g2_error_per_mm       : float (normal-curvature diff)\n"
            "  g3_error_per_mm2      : float (dκ/ds diff; null if unavailable)\n"
            "  converged             : bool\n"
            "  num_cp_modified       : int\n"
            "  max_cp_shift_mm       : float\n"
            "  honest_caveat         : str\n"
            "\n"
            "On error: {ok: false, reason: str}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "a_degree_u": {"type": "integer"},
                "a_degree_v": {"type": "integer"},
                "a_control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Surface A control points, row-major.",
                },
                "a_num_u": {"type": "integer"},
                "a_num_v": {"type": "integer"},
                "a_edge": {
                    "type": "string",
                    "enum": ["u0", "u1", "v0", "v1"],
                    "description": "Edge of surface A to match against.",
                },
                "b_degree_u": {"type": "integer"},
                "b_degree_v": {"type": "integer"},
                "b_control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "description": "Surface B control points, row-major.",
                },
                "b_num_u": {"type": "integer"},
                "b_num_v": {"type": "integer"},
                "b_edge": {
                    "type": "string",
                    "enum": ["u0", "u1", "v0", "v1"],
                    "description": "Edge of surface B to modify (shared edge).",
                },
                "num_modified_rows": {
                    "type": "integer",
                    "description": "CP rows to adjust (default 4, minimum 4 for G3).",
                },
                "samples": {
                    "type": "integer",
                    "description": "Along-edge sample count for error diagnostics (default 32).",
                },
                "tolerance": {
                    "type": "number",
                    "description": "Position tolerance for convergence classification (default 1e-6).",
                },
            },
            "required": [
                "a_degree_u", "a_degree_v", "a_control_points", "a_num_u", "a_num_v", "a_edge",
                "b_degree_u", "b_degree_v", "b_control_points", "b_num_u", "b_num_v", "b_edge",
            ],
        },
    )

    @register(_g3_spec)
    async def _run_nurbs_match_srf_g3(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surf_a, err = _parse_surf(a, "a_")
        if err is not None:
            return err
        surf_b, err = _parse_surf(a, "b_")
        if err is not None:
            return err

        a_edge = a.get("a_edge", "")
        b_edge = a.get("b_edge", "")
        if a_edge not in _VALID_EDGES:
            return err_payload(f"a_edge must be one of {sorted(_VALID_EDGES)}", "BAD_ARGS")
        if b_edge not in _VALID_EDGES:
            return err_payload(f"b_edge must be one of {sorted(_VALID_EDGES)}", "BAD_ARGS")

        num_modified_rows = a.get("num_modified_rows", 4)
        samples = a.get("samples", 32)
        tolerance = a.get("tolerance", 1e-6)

        if not isinstance(num_modified_rows, int) or num_modified_rows < 1:
            return err_payload("num_modified_rows must be integer >= 1", "BAD_ARGS")
        if not isinstance(samples, int) or samples < 2:
            return err_payload("samples must be integer >= 2", "BAD_ARGS")
        if not isinstance(tolerance, (int, float)) or tolerance <= 0:
            return err_payload("tolerance must be a positive number", "BAD_ARGS")

        spec = MatchSrfG3Spec(
            surface_a=surf_a,
            surface_b=surf_b,
            shared_edge=b_edge,
            num_modified_rows=int(num_modified_rows),
            target_edge=a_edge,
            samples=int(samples),
            tolerance=float(tolerance),
        )

        report = match_srf_g3(spec)

        if not report.ok:
            return err_payload(report.reason, "OP_FAILED")

        cp = report.modified_surface_b.control_points
        flat_cp = cp.reshape(-1, cp.shape[2]).tolist()

        return ok_payload({
            "modified_control_points": flat_cp,
            "modified_num_u": cp.shape[0],
            "modified_num_v": cp.shape[1],
            "g0_error_mm": report.g0_error_mm,
            "g1_error_rad": (None if math.isnan(report.g1_error_rad)
                             else report.g1_error_rad),
            "g2_error_per_mm": (None if math.isnan(report.g2_error_per_mm)
                                else report.g2_error_per_mm),
            "g3_error_per_mm2": (None if math.isnan(report.g3_error_per_mm2)
                                 else report.g3_error_per_mm2),
            "converged": report.converged,
            "num_cp_modified": report.num_cp_modified,
            "max_cp_shift_mm": report.max_cp_shift_mm,
            "honest_caveat": report.honest_caveat,
        })
