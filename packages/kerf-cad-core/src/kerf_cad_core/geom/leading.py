"""
leading.py
==========
Class-A *leading* surface quality workflow — hot-spot flagging pass.

Identifies surface hot-spots on a NurbsSurface by combining three
orthogonal analysis passes:

1. **comb-peak** — curvature-comb peak detection.
   Samples the principal curvature k1 across a UV grid (via the
   second fundamental form, identical to the T-104a residual oracle
   in ``surface_analysis``).  A hot-spot is emitted wherever the
   absolute curvature exceeds a neighbourhood-local threshold
   (``comb_threshold`` × median absolute curvature).

2. **zebra-break** — zebra-stripe discontinuity detection.
   Evaluates the zebra-stripe scalar from ``surface_analysis.zebra_stripe``
   across a UV grid, then measures the magnitude of the finite-difference
   gradient of that field.  A sharp gradient jump above ``zebra_threshold``
   indicates a G1/G2 discontinuity visible in a zebra-map view.

3. **g3-dropout** — G3 (third-order) continuity dropout detection.
   A surface satisfies G3 along isocurves when its third directional
   derivative of curvature is continuous and small.  We approximate this
   by computing the discrete second difference of mean curvature H along
   both u-iso and v-iso lines.  A G3 dropout is flagged where the second
   curvature difference (Δ²H) exceeds ``g3_threshold``.  A surface that
   is only G2-matched (e.g. degree-3 NURBS with a G2-matched seam) will
   show a step in Δ²H at the seam, producing a g3-dropout hot-spot.

API
---
``run_leading_pass(surface, ...) -> LeadingReport``
    Main entry point.  Accepts a NurbsSurface and threshold overrides.
    Returns a ``LeadingReport`` with a list of ``LeadingHotspot`` dicts.

Data types
----------
``LeadingHotspot``:
    location  : (u, v)        — surface parameter location
    severity  : float         — dimensionless severity score ≥ 0
    kind      : str           — one of 'comb-peak', 'zebra-break', 'g3-dropout'
    context   : str           — human-readable diagnostic message

``LeadingReport``:
    hotspots  : list[LeadingHotspot]
    ok        : bool
    reason    : str

Design notes
------------
* Pure-Python / NumPy only — no OCC, no WASM dependency.
* Imports only from existing T-104a/f/g modules:
    - ``kerf_cad_core.geom.surface_analysis``  (T-104f zebra, T-104g harness)
    - ``kerf_cad_core.geom.nurbs``              (T-104a substrate)
* Never raises — all exceptions are caught and surfaced as LeadingReport.ok=False.
* Threshold defaults are tuned for Class-A automotive surfaces (millimetre units).
  Pass ``comb_threshold``, ``zebra_threshold``, ``g3_threshold`` to override.

References
----------
Riesenfeld, R.F., "On Chaikin's algorithm", CGIP 4(3) 1975.
Farin, G., "Curves and Surfaces for CAGD", 5th ed., MK 2002 — §22 (class-A).
Peters, J. & Reif, U., "Subdivision Surfaces", Springer 2008 — §11 G3 / HOC.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_derivatives
from kerf_cad_core.geom.surface_analysis import (
    _analytic_curvature_data,
    _uv_grid,
    zebra_stripe,
)

# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

_HotspotKind = Literal["comb-peak", "zebra-break", "g3-dropout"]


@dataclass
class LeadingHotspot:
    """A single surface quality hot-spot detected by the leading pass."""

    location: Tuple[float, float]
    """Surface parameter coordinates (u, v)."""

    severity: float
    """Dimensionless severity score (≥ 0).  Higher = worse."""

    kind: str
    """One of 'comb-peak', 'zebra-break', 'g3-dropout'."""

    context: str
    """Human-readable diagnostic message."""


@dataclass
class LeadingReport:
    """Output of a leading surface quality pass."""

    hotspots: List[LeadingHotspot] = field(default_factory=list)
    """All detected hot-spots, ordered by descending severity."""

    ok: bool = True
    """False when the analysis could not complete."""

    reason: str = ""
    """Error message when ok=False."""


# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------

_DEFAULT_NU: int = 20
_DEFAULT_NV: int = 20

# Comb-peak: flag points where |k1| > comb_threshold * median(|k1| over grid).
# A value of 3.0 means "flag curvature peaks 3× above the median".
_DEFAULT_COMB_THRESHOLD: float = 3.0

# Zebra-break: flag points where the normalised zebra-gradient magnitude
# exceeds this value (0 = perfectly uniform, 1 = maximum possible step).
_DEFAULT_ZEBRA_THRESHOLD: float = 0.6

# G3-dropout: flag points where |Δ²H| (second difference of mean curvature
# along an iso-direction) exceeds this absolute threshold.
_DEFAULT_G3_THRESHOLD: float = 1e-3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_curvature_data(surf: NurbsSurface, u: float, v: float) -> Optional[dict]:
    """Wrapper around _analytic_curvature_data that absorbs exceptions."""
    try:
        return _analytic_curvature_data(surf, u, v)
    except Exception:
        return None


def _build_curvature_grid(
    surf: NurbsSurface,
    us: np.ndarray,
    vs: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (k1_grid, H_grid) of shape (nu, nv).

    Degenerate/failed points are stored as NaN.
    """
    nu, nv = len(us), len(vs)
    k1_grid = np.full((nu, nv), float("nan"))
    H_grid = np.full((nu, nv), float("nan"))
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            cd = _safe_curvature_data(surf, u, v)
            if cd is not None:
                k1_grid[i, j] = cd["k1"]
                H_grid[i, j] = cd["H"]
    return k1_grid, H_grid


def _build_zebra_grid(
    surf: NurbsSurface,
    us: np.ndarray,
    vs: np.ndarray,
    n_stripes: int = 8,
) -> np.ndarray:
    """Return zebra-stripe scalar grid of shape (nu, nv).

    Uses the analytic zebra_stripe function from surface_analysis.
    """
    nu, nv = len(us), len(vs)
    z_grid = np.full((nu, nv), float("nan"))
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            val = zebra_stripe(surf, u, v, n_stripes=n_stripes)
            if math.isfinite(val):
                z_grid[i, j] = val
    return z_grid


# ---------------------------------------------------------------------------
# Pass 1: comb-peak detection
# ---------------------------------------------------------------------------

def _find_comb_peaks(
    surf: NurbsSurface,
    us: np.ndarray,
    vs: np.ndarray,
    k1_grid: np.ndarray,
    threshold: float,
) -> List[LeadingHotspot]:
    """Flag grid points where |k1| is a local outlier vs. the median.

    Strategy: compute the median of |k1| over valid (non-NaN) samples.
    Any point where |k1| > threshold * median_k1 is a comb-peak hot-spot.
    If the surface is flat (median ≈ 0) we use an absolute fallback so the
    threshold never collapses.
    """
    hotspots: List[LeadingHotspot] = []
    flat = np.abs(k1_grid[~np.isnan(k1_grid)])
    if len(flat) == 0:
        return hotspots

    median_k1 = float(np.median(flat))
    # Absolute floor so we don't flag everything on a nearly-flat surface.
    abs_floor = 1e-6
    cutoff = max(abs_floor, threshold * max(median_k1, abs_floor))

    nu, nv = k1_grid.shape
    for i in range(nu):
        for j in range(nv):
            val = k1_grid[i, j]
            if math.isnan(val):
                continue
            abs_val = abs(val)
            if abs_val > cutoff:
                severity = abs_val / cutoff  # > 1 by construction
                hotspots.append(LeadingHotspot(
                    location=(float(us[i]), float(vs[j])),
                    severity=severity,
                    kind="comb-peak",
                    context=(
                        f"|k1|={abs_val:.4g} exceeds {threshold:.1f}× "
                        f"median={median_k1:.4g} (cutoff={cutoff:.4g})"
                    ),
                ))
    return hotspots


# ---------------------------------------------------------------------------
# Pass 2: zebra-break detection
# ---------------------------------------------------------------------------

def _find_zebra_breaks(
    surf: NurbsSurface,
    us: np.ndarray,
    vs: np.ndarray,
    z_grid: np.ndarray,
    threshold: float,
) -> List[LeadingHotspot]:
    """Flag grid points where the zebra-stripe gradient is sharply discontinuous.

    The zebra field Z(u, v) ∈ [0, 1] varies smoothly on a Class-A surface.
    A sharp jump in Z indicates a tangent (G1) or curvature (G2) discontinuity.
    We measure the magnitude of the finite-difference gradient of Z normalised
    by the grid spacing.
    """
    hotspots: List[LeadingHotspot] = []
    nu, nv = z_grid.shape
    if nu < 3 or nv < 3:
        return hotspots

    # Grid spacings in parameter space.
    du = (float(us[-1]) - float(us[0])) / max(nu - 1, 1)
    dv = (float(vs[-1]) - float(vs[0])) / max(nv - 1, 1)
    if du < 1e-15 or dv < 1e-15:
        return hotspots

    for i in range(1, nu - 1):
        for j in range(1, nv - 1):
            z_c = z_grid[i, j]
            z_up = z_grid[i - 1, j]
            z_dn = z_grid[i + 1, j]
            z_lt = z_grid[i, j - 1]
            z_rt = z_grid[i, j + 1]

            if any(math.isnan(x) for x in [z_c, z_up, z_dn, z_lt, z_rt]):
                continue

            # Central-difference gradient, normalised by the grid spacing.
            dz_du = (z_dn - z_up) / (2.0 * du)
            dz_dv = (z_rt - z_lt) / (2.0 * dv)
            grad_mag = math.sqrt(dz_du * dz_du + dz_dv * dz_dv)

            if grad_mag > threshold:
                severity = grad_mag / threshold
                hotspots.append(LeadingHotspot(
                    location=(float(us[i]), float(vs[j])),
                    severity=severity,
                    kind="zebra-break",
                    context=(
                        f"zebra gradient={grad_mag:.4g} "
                        f"exceeds threshold={threshold:.4g}; "
                        f"Z={z_c:.3f}"
                    ),
                ))
    return hotspots


# ---------------------------------------------------------------------------
# Pass 3: G3-dropout detection
# ---------------------------------------------------------------------------

def _find_g3_dropouts(
    surf: NurbsSurface,
    us: np.ndarray,
    vs: np.ndarray,
    H_grid: np.ndarray,
    threshold: float,
) -> List[LeadingHotspot]:
    """Flag grid points where the second difference of H indicates a G3 dropout.

    G3 continuity requires that the rate of change of curvature (the third
    derivative of position) is matched across boundaries.  For a sampled
    mean-curvature field H(u, v) on a uniform grid, the second finite difference
    Δ²H along each iso-direction approximates the second-order curvature
    derivative.  A step in Δ²H is a hallmark of a surface that is only G2-matched.

    We flag points where max(|Δ²H_u|, |Δ²H_v|) > threshold.
    """
    hotspots: List[LeadingHotspot] = []
    nu, nv = H_grid.shape
    if nu < 3 or nv < 3:
        return hotspots

    du = (float(us[-1]) - float(us[0])) / max(nu - 1, 1)
    dv = (float(vs[-1]) - float(vs[0])) / max(nv - 1, 1)
    if du < 1e-15 or dv < 1e-15:
        return hotspots

    for i in range(1, nu - 1):
        for j in range(1, nv - 1):
            H_c = H_grid[i, j]
            H_up = H_grid[i - 1, j]
            H_dn = H_grid[i + 1, j]
            H_lt = H_grid[i, j - 1]
            H_rt = H_grid[i, j + 1]

            if any(math.isnan(x) for x in [H_c, H_up, H_dn, H_lt, H_rt]):
                continue

            # Second difference Δ²H in u: (H[i+1,j] - 2H[i,j] + H[i-1,j]) / du²
            d2H_u = (H_dn - 2.0 * H_c + H_up) / (du * du)
            # Second difference Δ²H in v: (H[i,j+1] - 2H[i,j] + H[i,j-1]) / dv²
            d2H_v = (H_rt - 2.0 * H_c + H_lt) / (dv * dv)

            worst = max(abs(d2H_u), abs(d2H_v))
            if worst > threshold:
                severity = worst / threshold
                direction = "u" if abs(d2H_u) >= abs(d2H_v) else "v"
                hotspots.append(LeadingHotspot(
                    location=(float(us[i]), float(vs[j])),
                    severity=severity,
                    kind="g3-dropout",
                    context=(
                        f"Δ²H/{direction}={d2H_u if direction == 'u' else d2H_v:.4g} "
                        f"exceeds G3 threshold={threshold:.4g}; "
                        f"H={H_c:.4g} at ({us[i]:.3f}, {vs[j]:.3f})"
                    ),
                ))
    return hotspots


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_leading_pass(
    surface: NurbsSurface,
    *,
    nu: int = _DEFAULT_NU,
    nv: int = _DEFAULT_NV,
    comb_threshold: float = _DEFAULT_COMB_THRESHOLD,
    zebra_threshold: float = _DEFAULT_ZEBRA_THRESHOLD,
    g3_threshold: float = _DEFAULT_G3_THRESHOLD,
    n_stripes: int = 8,
) -> LeadingReport:
    """Run the full Class-A leading quality pass on a NurbsSurface.

    Parameters
    ----------
    surface         : NurbsSurface
    nu, nv          : UV sampling grid resolution (default 20×20)
    comb_threshold  : comb-peak flag threshold (× median k1; default 3.0)
    zebra_threshold : zebra-break gradient threshold (default 0.6)
    g3_threshold    : G3-dropout |Δ²H| threshold (default 1e-3)
    n_stripes       : number of zebra stripes (default 8)

    Returns
    -------
    LeadingReport
        hotspots: all flagged hot-spots sorted by descending severity
        ok      : False if the analysis failed (reason field set)
    """
    try:
        if not isinstance(surface, NurbsSurface):
            return LeadingReport(
                ok=False,
                reason=f"expected NurbsSurface, got {type(surface).__name__}",
            )

        nu = int(max(5, min(nu, 100)))
        nv = int(max(5, min(nv, 100)))

        us, vs = _uv_grid(surface, nu, nv)

        # Build shared grids once.
        k1_grid, H_grid = _build_curvature_grid(surface, us, vs)
        z_grid = _build_zebra_grid(surface, us, vs, n_stripes=n_stripes)

        hotspots: List[LeadingHotspot] = []

        # Pass 1: comb-peaks
        hotspots.extend(_find_comb_peaks(surface, us, vs, k1_grid, comb_threshold))

        # Pass 2: zebra-breaks
        hotspots.extend(_find_zebra_breaks(surface, us, vs, z_grid, zebra_threshold))

        # Pass 3: G3 dropouts
        hotspots.extend(_find_g3_dropouts(surface, us, vs, H_grid, g3_threshold))

        # Sort by descending severity so the worst problems appear first.
        hotspots.sort(key=lambda h: h.severity, reverse=True)

        return LeadingReport(hotspots=hotspots, ok=True, reason="")

    except Exception as exc:
        return LeadingReport(ok=False, reason=str(exc))
