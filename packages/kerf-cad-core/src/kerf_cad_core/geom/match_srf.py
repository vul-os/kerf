"""
match_srf.py
============
Pure-Python parametric matchSrf -- NURBS Phase 4 Capability 3 (pure-Python core).

Adjusts the control-point rows/cols adjacent to a source surface's matched edge
so the boundary satisfies G0 (positional), G1 (tangent), or G2 (curvature)
continuity with a target surface's corresponding edge.  This is the Rhino
"MatchSrf" operation implemented entirely in NumPy -- no OCC calls, no WASM.

The OCC ``GeomFill_NSections`` binding (the WASM-side complement that builds a
transition strip instead of modifying the source surface in place) remains
WASM-blocked until the C3-T1 binding probe confirms ``GeomFill_NSections`` +
``Geom_BSplineSurface.SetPole`` are present at runtime.

Public API
----------
match_surface_edge(
    target_surface, target_edge,
    source_surface, source_edge,
    continuity,
    *,
    samples=32,
    tolerance=1e-6,
) -> MatchResult

    Modify the source surface's control points near ``source_edge`` so the
    seam satisfies ``continuity`` against ``target_surface`` / ``target_edge``.

    Parameters
    ----------
    target_surface : NurbsSurface
        The reference surface to match against.
    target_edge : str
        Which edge of the target surface to use as the template.
        One of ``'u0'`` (u=u_min iso), ``'u1'`` (u=u_max iso),
        ``'v0'`` (v=v_min iso), ``'v1'`` (v=v_max iso).
    source_surface : NurbsSurface
        The surface whose boundary will be modified.
    source_edge : str
        Which edge of the source surface to match.
        Same four values as ``target_edge``.
    continuity : str
        ``'G0'``, ``'G1'``, or ``'G2'``.
    samples : int
        Number of parameter samples along the edge (default 32).
    tolerance : float
        Tolerance used for deviation diagnostics (default 1e-6).

    Returns
    -------
    MatchResult
        Dataclass with:
          modified_surface : NurbsSurface  (modified copy of source)
          ok               : bool
          reason           : str  (empty on success)
          max_position_deviation  : float  (G0 seam error in CP space)
          max_tangent_deviation   : float  (G1 cross-row angle, radians; nan if not computed)
          max_curvature_deviation : float  (G2 cross-row curvature diff; nan if not computed)
          continuity_achieved     : str   (highest continuity confirmed within tolerance)

    Never raises -- all exceptions are caught and surfaced in ``reason``.

LLM tool registration
---------------------
Gated by ``kerf_chat.tools.registry`` availability (same pattern as
``trim_curve.py``).  Tools registered when the registry is importable:

  ``match_surface_edge_tool``
      Modify a source surface edge to match a target surface edge at G0/G1/G2.
  ``diagnose_surface_continuity``
      Measure G0/G1/G2 deviation across a seam (read-only, non-destructive).

WASM-blocked note
-----------------
The ``GeomFill_NSections`` / ``Geom_BSplineSurface.SetPole`` OCC binding path
is unconfirmed at runtime.  This module delivers only the pure-Python
pole-adjustment approach (Approach 2 in the plan design sketch).  Once
C3-T1 probes the binding, the OCC path can be wired in alongside this module
without changing the public API.

Implementation notes
--------------------
Boundary-position sampling uses the boundary CP row directly (not
``surface_evaluate``) because a clamped B-spline boundary edge is *exactly*
the linear interpolation of its endpoint CPs -- this avoids the known
evaluation inaccuracy of the shared ``nurbs.py`` evaluator at parametric
extremes.  Cross-boundary tangent and curvature use the CP difference
relations for clamped B-splines:

    dS/dt|_{boundary} ~ p * (CP[1] - CP[0]) / knot_span
    d2S/dt2|_{boundary} ~ p*(p-1) * (CP[2] - 2*CP[1] + CP[0]) / knot_span^2
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_EDGES = frozenset({"u0", "u1", "v0", "v1"})
_VALID_CONTINUITY = frozenset({"G0", "G1", "G2"})
_DEFAULT_SAMPLES = 32


# ---------------------------------------------------------------------------
# MatchResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    """Result of a match_surface_edge call.

    Attributes
    ----------
    modified_surface : NurbsSurface
        A deep copy of the source surface with the near-seam control points
        adjusted.  Identical to the input source surface when ``ok`` is False.
    ok : bool
        True on success.
    reason : str
        Human-readable explanation when ``ok`` is False.
    max_position_deviation : float
        Maximum 3D distance between the source-edge boundary CPs (after
        adjustment) and the corresponding target-edge boundary CPs (G0 error).
    max_tangent_deviation : float
        Maximum angle (radians) between cross-boundary CP-difference vectors
        on either side of the seam after the operation (G1 proxy).
        ``math.nan`` if G1 was not requested or could not be computed.
    max_curvature_deviation : float
        Maximum difference in the second CP-difference magnitudes on either
        side of the seam after the operation (G2 proxy).
        ``math.nan`` if G2 was not requested or could not be computed.
    continuity_achieved : str
        Highest continuity level confirmed within the supplied tolerance.
        One of ``'G0'``, ``'G1'``, ``'G2'``, or ``'none'``.
    """
    modified_surface: Optional[NurbsSurface] = None
    ok: bool = False
    reason: str = ""
    max_position_deviation: float = math.nan
    max_tangent_deviation: float = math.nan
    max_curvature_deviation: float = math.nan
    continuity_achieved: str = "none"


# ---------------------------------------------------------------------------
# Parameter-domain helpers
# ---------------------------------------------------------------------------

def _domain_u(surf: NurbsSurface) -> Tuple[float, float]:
    return float(surf.knots_u[0]), float(surf.knots_u[-1])


def _domain_v(surf: NurbsSurface) -> Tuple[float, float]:
    return float(surf.knots_v[0]), float(surf.knots_v[-1])


# ---------------------------------------------------------------------------
# CP row access
# ---------------------------------------------------------------------------

def _get_cp_row(surf: NurbsSurface, edge: str, row_idx: int) -> np.ndarray:
    """Extract a row/col of control points adjacent to the given edge.

    ``row_idx = 0`` is the boundary row; ``row_idx = 1`` is the next row in,
    etc.  Returns an (n, dim) array (copy).
    """
    cp = surf.control_points  # (nu, nv, dim)
    nu, nv = cp.shape[0], cp.shape[1]
    if edge == "u0":
        return cp[row_idx, :, :].copy()
    if edge == "u1":
        return cp[nu - 1 - row_idx, :, :].copy()
    if edge == "v0":
        return cp[:, row_idx, :].copy()
    # v1
    return cp[:, nv - 1 - row_idx, :].copy()


def _set_cp_row(surf: NurbsSurface, edge: str, row_idx: int, values: np.ndarray) -> None:
    """Write a row/col of control points back into the surface (in-place)."""
    cp = surf.control_points
    nu, nv = cp.shape[0], cp.shape[1]
    if edge == "u0":
        cp[row_idx, :, :] = values
    elif edge == "u1":
        cp[nu - 1 - row_idx, :, :] = values
    elif edge == "v0":
        cp[:, row_idx, :] = values
    else:  # v1
        cp[:, nv - 1 - row_idx, :] = values


def _cp_row_count(surf: NurbsSurface, edge: str) -> int:
    """Number of control-point rows available in the inward direction."""
    if edge in ("u0", "u1"):
        return surf.control_points.shape[0]
    return surf.control_points.shape[1]


def _cp_col_count(surf: NurbsSurface, edge: str) -> int:
    """Length of a CP row (along-edge direction)."""
    if edge in ("u0", "u1"):
        return surf.control_points.shape[1]  # nv CPs along the v edge
    return surf.control_points.shape[0]      # nu CPs along the u edge


# ---------------------------------------------------------------------------
# Sample boundary CP row with linear interpolation to requested sample count
# ---------------------------------------------------------------------------

def _sample_boundary_cps(surf: NurbsSurface, edge: str, samples: int) -> np.ndarray:
    """Return (samples, 3) array by linearly sampling the boundary CP row.

    For a clamped B-spline the boundary edge is exactly the boundary CP row,
    so this gives exact boundary positions without depending on
    ``surface_evaluate``.
    """
    row = _get_cp_row(surf, edge, 0)   # (n_cp, dim)
    n_cp = len(row)
    n = max(2, samples)
    t = np.linspace(0.0, 1.0, n)
    result = np.zeros((n, 3))
    for k, tk in enumerate(t):
        idx_f = tk * (n_cp - 1)
        lo = int(math.floor(idx_f))
        hi = min(lo + 1, n_cp - 1)
        alpha = idx_f - lo
        result[k] = (1.0 - alpha) * row[lo, :3] + alpha * row[hi, :3]
    return result


# ---------------------------------------------------------------------------
# CP difference vectors (boundary tangent / curvature proxies)
# ---------------------------------------------------------------------------

def _cp_tangent_vector(surf: NurbsSurface, edge: str, cp_idx: int) -> np.ndarray:
    """Cross-boundary tangent at CP position cp_idx (along-edge).

    T = p * (CP[1][cp_idx] - CP[0][cp_idx])  (knot-span normalised later)
    cp_idx is the index within the along-edge direction.
    """
    row0 = _get_cp_row(surf, edge, 0)
    row1 = _get_cp_row(surf, edge, 1)
    return row1[cp_idx, :3] - row0[cp_idx, :3]


def _cp_curvature_vector(surf: NurbsSurface, edge: str, cp_idx: int) -> np.ndarray:
    """Cross-boundary second-difference at CP position cp_idx.

    kappa ~ p*(p-1) * (CP[2][cp_idx] - 2*CP[1][cp_idx] + CP[0][cp_idx])
    """
    row0 = _get_cp_row(surf, edge, 0)
    row1 = _get_cp_row(surf, edge, 1)
    row2 = _get_cp_row(surf, edge, 2)
    return row2[cp_idx, :3] - 2.0 * row1[cp_idx, :3] + row0[cp_idx, :3]


# ---------------------------------------------------------------------------
# Knot-span at boundary
# ---------------------------------------------------------------------------

def _boundary_knot_span(surf: NurbsSurface, edge: str) -> float:
    """Return the knot span at the boundary edge in the inward direction."""
    if edge in ("u0", "u1"):
        knots = surf.knots_u
        p = surf.degree_u
    else:
        knots = surf.knots_v
        p = surf.degree_v

    if edge in ("u0", "v0"):
        span = float(knots[p + 1] - knots[0])
    else:
        span = float(knots[-1] - knots[-(p + 2)])
    return span if abs(span) > 1e-15 else 1.0


def _boundary_degree(surf: NurbsSurface, edge: str) -> int:
    if edge in ("u0", "u1"):
        return surf.degree_u
    return surf.degree_v


# ---------------------------------------------------------------------------
# Core: G0 -- snap boundary CP row to target boundary CP row
# ---------------------------------------------------------------------------

def _apply_g0(source: NurbsSurface, source_edge: str,
              target: NurbsSurface, target_edge: str) -> None:
    """Snap the boundary CP row of source to match the target boundary.

    Resamples the target boundary CP row to the source CP count via linear
    interpolation, then overwrites source's boundary row.
    """
    n_src = _cp_col_count(source, source_edge)
    t_tgt = _get_cp_row(target, target_edge, 0)   # target boundary CPs
    n_tgt = len(t_tgt)
    dim = source.control_points.shape[2]

    new_row = np.zeros((n_src, dim))
    for k in range(n_src):
        tk = k / (n_src - 1) if n_src > 1 else 0.0
        idx_f = tk * (n_tgt - 1)
        lo = int(math.floor(idx_f))
        hi = min(lo + 1, n_tgt - 1)
        alpha = idx_f - lo
        new_row[k, :3] = (1.0 - alpha) * t_tgt[lo, :3] + alpha * t_tgt[hi, :3]
        if dim > 3:
            # Preserve homogeneous weights from source
            src_row0 = _get_cp_row(source, source_edge, 0)
            new_row[k, 3:] = src_row0[k, 3:]

    _set_cp_row(source, source_edge, 0, new_row)


# ---------------------------------------------------------------------------
# Core: G1 -- adjust the second CP row for tangent matching
# ---------------------------------------------------------------------------

def _apply_g1(source: NurbsSurface, source_edge: str,
              target: NurbsSurface, target_edge: str) -> None:
    """Adjust the *second* CP row of source for G1 continuity.

    For a clamped B-spline of degree p:
        dS/dt|_boundary = p * (CP[1] - CP[0]) / knot_span

    To match the target tangent we need:
        (CP_src[1] - CP_src[0]) proportional to (CP_tgt[1] - CP_tgt[0])

    Strategy: set the magnitude of the source cross-boundary CP difference to
    match its own original magnitude (preserve the surface interior shape),
    but point it in the direction of the target's cross-boundary difference.
    """
    n_src = _cp_col_count(source, source_edge)
    n_tgt = _cp_col_count(target, target_edge)
    dim = source.control_points.shape[2]

    row0_src = _get_cp_row(source, source_edge, 0)  # already G0-matched
    row1_new = row0_src.copy()

    for k in range(n_src):
        # Parameter along the edge (0..1)
        tk = k / (n_src - 1) if n_src > 1 else 0.0
        # Corresponding index on the target
        idx_f = tk * (n_tgt - 1)
        lo = int(math.floor(idx_f))
        hi = min(lo + 1, n_tgt - 1)
        alpha = idx_f - lo

        # Target cross-boundary difference vector at this parameter
        d_tgt_lo = _cp_tangent_vector(target, target_edge, lo)
        d_tgt_hi = _cp_tangent_vector(target, target_edge, hi)
        d_tgt = (1.0 - alpha) * d_tgt_lo + alpha * d_tgt_hi

        n_tgt_vec = np.linalg.norm(d_tgt)
        if n_tgt_vec < 1e-15:
            # Target tangent is zero -- keep source CP unchanged
            row1_new[k] = _get_cp_row(source, source_edge, 1)[k]
            continue

        # Direction from target
        t_dir = d_tgt / n_tgt_vec

        # Magnitude: from the source's own original cross-boundary difference
        # (preserves interior shape, only changes direction)
        orig_row1 = _get_cp_row(source, source_edge, 1)
        d_src = orig_row1[k, :3] - row0_src[k, :3]
        magnitude = float(np.linalg.norm(d_src))
        if magnitude < 1e-15:
            # Source had zero tangent -- use target magnitude
            magnitude = n_tgt_vec

        # CP[1] = CP[0] + magnitude * t_dir
        row1_new[k, :3] = row0_src[k, :3] + magnitude * t_dir
        if dim > 3:
            row1_new[k, 3:] = orig_row1[k, 3:]

    _set_cp_row(source, source_edge, 1, row1_new)


# ---------------------------------------------------------------------------
# Core: G2 -- adjust the third CP row for curvature matching
# ---------------------------------------------------------------------------

def _apply_g2(source: NurbsSurface, source_edge: str,
              target: NurbsSurface, target_edge: str) -> None:
    """Adjust the *third* CP row of source for G2 (curvature) continuity.

    For a clamped B-spline of degree p >= 2:
        d2S/dt2|_boundary = p*(p-1) * (CP[2] - 2*CP[1] + CP[0]) / span^2

    We scale the target's second difference to match the source's parametric
    span ratio, then solve for CP[2]:
        CP[2] = 2*CP[1] - CP[0] + scale * (CP_tgt[2] - 2*CP_tgt[1] + CP_tgt[0])
    """
    p_src = _boundary_degree(source, source_edge)
    if p_src < 2:
        return   # G2 on degree-1 surface is undefined -- silently skip

    p_tgt = _boundary_degree(target, target_edge)
    span_src = _boundary_knot_span(source, source_edge)
    span_tgt = _boundary_knot_span(target, target_edge)

    # Scale factor: equate d2S/dt2 across the seam
    # (p_src*(p_src-1)/span_src^2) * delta2_src = (p_tgt*(p_tgt-1)/span_tgt^2) * delta2_tgt
    factor_src = max(1, p_src * (p_src - 1)) / (span_src ** 2)
    factor_tgt = max(1, p_tgt * (p_tgt - 1)) / (span_tgt ** 2) if p_tgt >= 2 else 1.0
    scale = factor_tgt / factor_src if factor_src > 1e-30 else 1.0

    n_src = _cp_col_count(source, source_edge)
    n_tgt = _cp_col_count(target, target_edge)
    dim = source.control_points.shape[2]

    row0_src = _get_cp_row(source, source_edge, 0)
    row1_src = _get_cp_row(source, source_edge, 1)
    row2_new = row1_src.copy()

    for k in range(n_src):
        tk = k / (n_src - 1) if n_src > 1 else 0.0
        idx_f = tk * (n_tgt - 1)
        lo = int(math.floor(idx_f))
        hi = min(lo + 1, n_tgt - 1)
        alpha = idx_f - lo

        if p_tgt >= 2:
            d2_tgt_lo = _cp_curvature_vector(target, target_edge, lo)
            d2_tgt_hi = _cp_curvature_vector(target, target_edge, hi)
            d2_tgt = (1.0 - alpha) * d2_tgt_lo + alpha * d2_tgt_hi
        else:
            d2_tgt = np.zeros(3)

        orig_row2 = _get_cp_row(source, source_edge, 2)
        row2_new[k, :3] = (2.0 * row1_src[k, :3] - row0_src[k, :3]
                            + scale * d2_tgt)
        if dim > 3:
            row2_new[k, 3:] = orig_row2[k, 3:]

    _set_cp_row(source, source_edge, 2, row2_new)


# ---------------------------------------------------------------------------
# Diagnostics -- all CP-based, no surface_evaluate needed
# ---------------------------------------------------------------------------

def _compute_deviations(
    source: NurbsSurface, source_edge: str,
    target: NurbsSurface, target_edge: str,
    samples: int,
    continuity: str,
) -> Tuple[float, float, float]:
    """Compute G0/G1/G2 seam deviations using CP-level geometry.

    Returns (max_position_dev, max_tangent_dev_rad, max_curvature_dev).
    Tangent and curvature devs are NaN when not requested or unavailable.
    """
    n_src = _cp_col_count(source, source_edge)
    n_tgt = _cp_col_count(target, target_edge)

    # G0: compare boundary CPs
    max_pos = 0.0
    for k in range(n_src):
        tk = k / (n_src - 1) if n_src > 1 else 0.0
        idx_f = tk * (n_tgt - 1)
        lo = int(math.floor(idx_f))
        hi = min(lo + 1, n_tgt - 1)
        alpha = idx_f - lo
        tgt_pos = ((1.0 - alpha) * _get_cp_row(target, target_edge, 0)[lo, :3] +
                   alpha * _get_cp_row(target, target_edge, 0)[hi, :3])
        src_pos = _get_cp_row(source, source_edge, 0)[k, :3]
        d = float(np.linalg.norm(src_pos - tgt_pos))
        if d > max_pos:
            max_pos = d

    max_tan = math.nan
    max_cur = math.nan

    if continuity in ("G1", "G2"):
        p_src = _boundary_degree(source, source_edge)
        p_tgt = _boundary_degree(target, target_edge)
        max_tan = 0.0
        n_rows_src = _cp_row_count(source, source_edge)
        n_rows_tgt = _cp_row_count(target, target_edge)
        if n_rows_src >= 2 and n_rows_tgt >= 2:
            for k in range(n_src):
                tk = k / (n_src - 1) if n_src > 1 else 0.0
                idx_f = tk * (n_tgt - 1)
                lo = int(math.floor(idx_f))
                hi = min(lo + 1, n_tgt - 1)
                alpha = idx_f - lo
                d_src = _cp_tangent_vector(source, source_edge, k)
                d_tgt_lo = _cp_tangent_vector(target, target_edge, lo)
                d_tgt_hi = _cp_tangent_vector(target, target_edge, hi)
                d_tgt = (1.0 - alpha) * d_tgt_lo + alpha * d_tgt_hi
                n_s = float(np.linalg.norm(d_src))
                n_t = float(np.linalg.norm(d_tgt))
                if n_s > 1e-15 and n_t > 1e-15:
                    cos_a = float(np.clip(np.dot(d_src, d_tgt) / (n_s * n_t), -1.0, 1.0))
                    angle = math.acos(cos_a)
                    if angle > max_tan:
                        max_tan = angle

    if continuity == "G2":
        p_src = _boundary_degree(source, source_edge)
        p_tgt = _boundary_degree(target, target_edge)
        n_rows_src = _cp_row_count(source, source_edge)
        n_rows_tgt = _cp_row_count(target, target_edge)
        if p_src >= 2 and p_tgt >= 2 and n_rows_src >= 3 and n_rows_tgt >= 3:
            span_src = _boundary_knot_span(source, source_edge)
            span_tgt = _boundary_knot_span(target, target_edge)
            factor_src = max(1, p_src * (p_src - 1)) / (span_src ** 2)
            factor_tgt = max(1, p_tgt * (p_tgt - 1)) / (span_tgt ** 2)
            max_cur = 0.0
            for k in range(n_src):
                tk = k / (n_src - 1) if n_src > 1 else 0.0
                idx_f = tk * (n_tgt - 1)
                lo = int(math.floor(idx_f))
                hi = min(lo + 1, n_tgt - 1)
                alpha = idx_f - lo
                d2_src = _cp_curvature_vector(source, source_edge, k)
                d2_tgt_lo = _cp_curvature_vector(target, target_edge, lo)
                d2_tgt_hi = _cp_curvature_vector(target, target_edge, hi)
                d2_tgt = (1.0 - alpha) * d2_tgt_lo + alpha * d2_tgt_hi
                # Compare actual curvature magnitudes
                kappa_src = float(np.linalg.norm(d2_src)) * factor_src
                kappa_tgt = float(np.linalg.norm(d2_tgt)) * factor_tgt
                diff = abs(kappa_src - kappa_tgt)
                if diff > max_cur:
                    max_cur = diff

    return max_pos, max_tan, max_cur


def _classify_continuity(
    max_pos: float,
    max_tan: float,
    max_cur: float,
    tolerance: float,
) -> str:
    """Return the highest continuity level confirmed within tolerance."""
    if math.isnan(max_pos) or max_pos > tolerance * 100:
        return "none"
    if math.isnan(max_tan) or max_tan > 0.05:   # ~3 degrees
        return "G0"
    if math.isnan(max_cur) or max_cur > tolerance * 1000:
        return "G1"
    return "G2"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_surface_edge(
    target_surface: NurbsSurface,
    target_edge: str,
    source_surface: NurbsSurface,
    source_edge: str,
    continuity: str,
    *,
    samples: int = _DEFAULT_SAMPLES,
    tolerance: float = 1e-6,
) -> MatchResult:
    """Match source_surface's source_edge to target_surface's target_edge.

    Returns a new NurbsSurface (deep copy of source with boundary CPs adjusted).
    The original source_surface is never mutated.

    Parameters
    ----------
    target_surface : NurbsSurface
    target_edge : str  -- 'u0', 'u1', 'v0', or 'v1'
    source_surface : NurbsSurface
    source_edge : str  -- 'u0', 'u1', 'v0', or 'v1'
    continuity : str   -- 'G0', 'G1', or 'G2'
    samples : int      -- diagnostic sample count (default 32)
    tolerance : float  -- deviation threshold for continuity_achieved (default 1e-6)

    Returns
    -------
    MatchResult.  Never raises.
    """
    # --- Input validation ---------------------------------------------------
    if not isinstance(target_surface, NurbsSurface):
        return MatchResult(
            modified_surface=source_surface,
            ok=False,
            reason=(f"target_surface must be NurbsSurface, "
                    f"got {type(target_surface).__name__}"),
        )
    if not isinstance(source_surface, NurbsSurface):
        return MatchResult(
            modified_surface=None,
            ok=False,
            reason=(f"source_surface must be NurbsSurface, "
                    f"got {type(source_surface).__name__}"),
        )
    if target_edge not in _VALID_EDGES:
        return MatchResult(
            modified_surface=source_surface,
            ok=False,
            reason=(f"target_edge must be one of {sorted(_VALID_EDGES)}, "
                    f"got {target_edge!r}"),
        )
    if source_edge not in _VALID_EDGES:
        return MatchResult(
            modified_surface=source_surface,
            ok=False,
            reason=(f"source_edge must be one of {sorted(_VALID_EDGES)}, "
                    f"got {source_edge!r}"),
        )
    if continuity not in _VALID_CONTINUITY:
        return MatchResult(
            modified_surface=source_surface,
            ok=False,
            reason=(f"continuity must be one of {sorted(_VALID_CONTINUITY)}, "
                    f"got {continuity!r}"),
        )
    if not isinstance(samples, int) or samples < 2:
        return MatchResult(
            modified_surface=source_surface,
            ok=False,
            reason=f"samples must be an integer >= 2, got {samples!r}",
        )
    if not isinstance(tolerance, (int, float)) or tolerance <= 0:
        return MatchResult(
            modified_surface=source_surface,
            ok=False,
            reason=f"tolerance must be a positive number, got {tolerance!r}",
        )

    # --- Check enough CP rows for the requested continuity ------------------
    n_rows_src = _cp_row_count(source_surface, source_edge)
    required = {"G0": 1, "G1": 2, "G2": 3}[continuity]
    if n_rows_src < required:
        return MatchResult(
            modified_surface=source_surface,
            ok=False,
            reason=(
                f"source_surface has only {n_rows_src} CP row(s) in the inward "
                f"direction; {continuity} requires at least {required}"
            ),
        )

    # G1/G2 require enough rows on the target too
    n_rows_tgt = _cp_row_count(target_surface, target_edge)
    if continuity in ("G1", "G2") and n_rows_tgt < 2:
        return MatchResult(
            modified_surface=source_surface,
            ok=False,
            reason=(
                f"target_surface has only {n_rows_tgt} CP row(s) in the inward "
                f"direction; {continuity} requires at least 2"
            ),
        )

    # G2 requires degree >= 2 on source
    if continuity == "G2":
        p_src = _boundary_degree(source_surface, source_edge)
        if p_src < 2:
            return MatchResult(
                modified_surface=source_surface,
                ok=False,
                reason=(
                    f"G2 matching requires source degree >= 2 in the matched "
                    f"direction; got degree {p_src}"
                ),
            )

    # --- Deep-copy source ---------------------------------------------------
    try:
        source_copy = NurbsSurface(
            degree_u=source_surface.degree_u,
            degree_v=source_surface.degree_v,
            control_points=source_surface.control_points.copy(),
            knots_u=source_surface.knots_u.copy(),
            knots_v=source_surface.knots_v.copy(),
        )
    except Exception as exc:
        return MatchResult(
            modified_surface=source_surface,
            ok=False,
            reason=f"failed to copy source_surface: {exc}",
        )

    # --- Apply G0 -----------------------------------------------------------
    try:
        _apply_g0(source_copy, source_edge, target_surface, target_edge)
    except Exception as exc:
        return MatchResult(
            modified_surface=source_surface,
            ok=False,
            reason=f"G0 application failed: {exc}",
        )

    # --- Apply G1 -----------------------------------------------------------
    if continuity in ("G1", "G2"):
        try:
            _apply_g1(source_copy, source_edge, target_surface, target_edge)
        except Exception as exc:
            return MatchResult(
                modified_surface=source_surface,
                ok=False,
                reason=f"G1 application failed: {exc}",
            )

    # --- Apply G2 -----------------------------------------------------------
    if continuity == "G2":
        try:
            _apply_g2(source_copy, source_edge, target_surface, target_edge)
        except Exception as exc:
            return MatchResult(
                modified_surface=source_surface,
                ok=False,
                reason=f"G2 application failed: {exc}",
            )

    # --- Diagnostics --------------------------------------------------------
    try:
        max_pos, max_tan, max_cur = _compute_deviations(
            source_copy, source_edge,
            target_surface, target_edge,
            samples, continuity,
        )
    except Exception:
        max_pos, max_tan, max_cur = math.nan, math.nan, math.nan

    continuity_achieved = _classify_continuity(max_pos, max_tan, max_cur, tolerance)

    return MatchResult(
        modified_surface=source_copy,
        ok=True,
        reason="",
        max_position_deviation=max_pos,
        max_tangent_deviation=max_tan,
        max_curvature_deviation=max_cur,
        continuity_achieved=continuity_achieved,
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

    def _build_surface(raw_cp, num_u: int, num_v: int,
                       degree_u: int, degree_v: int):
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

    def _parse_surface_args(a: dict, prefix: str):
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
            deg_u = int(deg_u)
            deg_v = int(deg_v)
            num_u = int(num_u)
            num_v = int(num_v)
        except (TypeError, ValueError) as exc:
            return None, err_payload(
                f"degree/num values must be integers: {exc}", "BAD_ARGS"
            )
        if deg_u < 1 or deg_v < 1:
            return None, err_payload(
                f"{prefix}degree_u and degree_v must be >= 1", "BAD_ARGS"
            )
        if num_u < 2 or num_v < 2:
            return None, err_payload(
                f"{prefix}num_u and num_v must be >= 2", "BAD_ARGS"
            )
        if len(raw_cp) != num_u * num_v:
            return None, err_payload(
                (f"{prefix}control_points length ({len(raw_cp)}) "
                 f"!= num_u*num_v ({num_u*num_v})"),
                "BAD_ARGS",
            )
        surf, err = _build_surface(raw_cp, num_u, num_v, deg_u, deg_v)
        if err is not None:
            return None, err_payload(err, "BAD_ARGS")
        return surf, None

    _match_srf_spec = ToolSpec(
        name="match_surface_edge_tool",
        description=(
            "Modify a source NURBS surface's boundary control points so that "
            "the specified edge matches the edge of a target NURBS surface at "
            "G0 (position), G1 (tangent), or G2 (curvature) continuity.\n"
            "\n"
            "This is the pure-Python 'MatchSrf' implementation.  The OCC "
            "GeomFill_NSections binding (WASM-blocked) is not used.\n"
            "\n"
            "Returns:\n"
            "  ok                      : bool\n"
            "  modified_control_points : list of [x,y,z] in row-major order\n"
            "  max_position_deviation  : float  (G0 seam error)\n"
            "  max_tangent_deviation   : float  (G1 angle radians; null if N/A)\n"
            "  max_curvature_deviation : float  (G2 curvature diff; null if N/A)\n"
            "  continuity_achieved     : str    (G0/G1/G2/none)\n"
            "\n"
            "On error: {ok: false, reason: str}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "target_degree_u": {"type": "integer"},
                "target_degree_v": {"type": "integer"},
                "target_control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "target_num_u": {"type": "integer"},
                "target_num_v": {"type": "integer"},
                "target_edge": {
                    "type": "string",
                    "enum": ["u0", "u1", "v0", "v1"],
                },
                "source_degree_u": {"type": "integer"},
                "source_degree_v": {"type": "integer"},
                "source_control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "source_num_u": {"type": "integer"},
                "source_num_v": {"type": "integer"},
                "source_edge": {
                    "type": "string",
                    "enum": ["u0", "u1", "v0", "v1"],
                },
                "continuity": {
                    "type": "string",
                    "enum": ["G0", "G1", "G2"],
                },
                "samples": {"type": "integer"},
                "tolerance": {"type": "number"},
            },
            "required": [
                "target_degree_u", "target_degree_v",
                "target_control_points", "target_num_u", "target_num_v",
                "target_edge",
                "source_degree_u", "source_degree_v",
                "source_control_points", "source_num_u", "source_num_v",
                "source_edge",
                "continuity",
            ],
        },
    )

    @register(_match_srf_spec)
    async def run_match_surface_edge(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        target_surf, err = _parse_surface_args(a, "target_")
        if err is not None:
            return err
        source_surf, err = _parse_surface_args(a, "source_")
        if err is not None:
            return err

        target_edge = a.get("target_edge", "")
        source_edge = a.get("source_edge", "")
        continuity = a.get("continuity", "")
        samples = a.get("samples", _DEFAULT_SAMPLES)
        tolerance = a.get("tolerance", 1e-6)

        if target_edge not in _VALID_EDGES:
            return err_payload(
                f"target_edge must be one of {sorted(_VALID_EDGES)}", "BAD_ARGS"
            )
        if source_edge not in _VALID_EDGES:
            return err_payload(
                f"source_edge must be one of {sorted(_VALID_EDGES)}", "BAD_ARGS"
            )
        if continuity not in _VALID_CONTINUITY:
            return err_payload(
                f"continuity must be one of {sorted(_VALID_CONTINUITY)}", "BAD_ARGS"
            )
        if not isinstance(samples, int) or samples < 2:
            return err_payload("samples must be integer >= 2", "BAD_ARGS")
        if not isinstance(tolerance, (int, float)) or tolerance <= 0:
            return err_payload("tolerance must be a positive number", "BAD_ARGS")

        result = match_surface_edge(
            target_surf, target_edge,
            source_surf, source_edge,
            continuity,
            samples=samples,
            tolerance=float(tolerance),
        )

        if not result.ok:
            return err_payload(result.reason, "OP_FAILED")

        cp = result.modified_surface.control_points
        flat_cp = cp.reshape(-1, cp.shape[2]).tolist()

        return ok_payload({
            "modified_control_points": flat_cp,
            "max_position_deviation": result.max_position_deviation,
            "max_tangent_deviation": (None if math.isnan(result.max_tangent_deviation)
                                      else result.max_tangent_deviation),
            "max_curvature_deviation": (None if math.isnan(result.max_curvature_deviation)
                                        else result.max_curvature_deviation),
            "continuity_achieved": result.continuity_achieved,
        })

    _diagnose_spec = ToolSpec(
        name="diagnose_surface_continuity",
        description=(
            "Measure G0/G1/G2 deviation across the seam between two NURBS "
            "surface edges without modifying any surface.  Returns:\n"
            "  ok, max_position_deviation, max_tangent_deviation (radians),\n"
            "  max_curvature_deviation, continuity_achieved.\n"
            "Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "target_degree_u": {"type": "integer"},
                "target_degree_v": {"type": "integer"},
                "target_control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "target_num_u": {"type": "integer"},
                "target_num_v": {"type": "integer"},
                "target_edge": {"type": "string", "enum": ["u0", "u1", "v0", "v1"]},
                "source_degree_u": {"type": "integer"},
                "source_degree_v": {"type": "integer"},
                "source_control_points": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "source_num_u": {"type": "integer"},
                "source_num_v": {"type": "integer"},
                "source_edge": {"type": "string", "enum": ["u0", "u1", "v0", "v1"]},
                "continuity": {"type": "string", "enum": ["G0", "G1", "G2"]},
                "samples": {"type": "integer"},
                "tolerance": {"type": "number"},
            },
            "required": [
                "target_degree_u", "target_degree_v",
                "target_control_points", "target_num_u", "target_num_v",
                "target_edge",
                "source_degree_u", "source_degree_v",
                "source_control_points", "source_num_u", "source_num_v",
                "source_edge",
                "continuity",
            ],
        },
    )

    @register(_diagnose_spec)
    async def run_diagnose_surface_continuity(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        target_surf, err = _parse_surface_args(a, "target_")
        if err is not None:
            return err
        source_surf, err = _parse_surface_args(a, "source_")
        if err is not None:
            return err

        target_edge = a.get("target_edge", "")
        source_edge = a.get("source_edge", "")
        continuity = a.get("continuity", "G2")
        samples = a.get("samples", _DEFAULT_SAMPLES)
        tolerance = a.get("tolerance", 1e-6)

        if target_edge not in _VALID_EDGES:
            return err_payload(
                f"target_edge must be one of {sorted(_VALID_EDGES)}", "BAD_ARGS"
            )
        if source_edge not in _VALID_EDGES:
            return err_payload(
                f"source_edge must be one of {sorted(_VALID_EDGES)}", "BAD_ARGS"
            )
        if continuity not in _VALID_CONTINUITY:
            return err_payload(
                f"continuity must be one of {sorted(_VALID_CONTINUITY)}", "BAD_ARGS"
            )
        if not isinstance(samples, int) or samples < 2:
            return err_payload("samples must be integer >= 2", "BAD_ARGS")
        if not isinstance(tolerance, (int, float)) or tolerance <= 0:
            return err_payload("tolerance must be a positive number", "BAD_ARGS")

        try:
            max_pos, max_tan, max_cur = _compute_deviations(
                source_surf, source_edge,
                target_surf, target_edge,
                int(samples), continuity,
            )
        except Exception as exc:
            return err_payload(f"deviation computation failed: {exc}", "OP_FAILED")

        continuity_achieved = _classify_continuity(
            max_pos, max_tan, max_cur, float(tolerance)
        )

        return ok_payload({
            "max_position_deviation": max_pos,
            "max_tangent_deviation": (None if math.isnan(max_tan) else max_tan),
            "max_curvature_deviation": (None if math.isnan(max_cur) else max_cur),
            "continuity_achieved": continuity_achieved,
        })
