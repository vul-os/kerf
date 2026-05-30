"""
curvature_metrics.py
====================
Curvature-comb peak detection and variance metrics for NURBS curves and surfaces.

Implements the Farin (1990) curvature-comb analysis approach for Class-A surface
quality assessment.  A curvature comb plots κ(s) — the signed curvature as a
function of arc length — as "teeth" perpendicular to the curve.  Peaks in the
comb (local maxima of |κ|) and the statistical distribution of κ reveal
oscillation, waviness, and sharp corners that would be visible in highlight-line
or reflection-line inspection.

Public API
----------
curvature_comb_peaks(curve, n_samples, threshold_factor) -> CurvaturePeakReport
    Detect local maxima in |κ(s)| above threshold_factor × κ_mean.

curvature_variance_metric(curve, n_samples) -> dict
    Variance, std-dev, skewness, kurtosis of κ; total variation ∫|dκ/ds|·ds.

isophote_density_metric(surface, n_samples) -> dict
    Isophote density per Pottmann-Wallner (2001) Ch 10 — density of isophote
    lines per unit area; high density ↔ high curvature regions.

Integration with continuity_audit
----------------------------------
``continuity_audit(..., include_curvature_metrics=True)`` adds
``curvature_metrics`` to the output dict: for each shared edge, the dominant
isocurve curvature variance and peak count are reported.

References
----------
Farin, G., "Curves and Surfaces for CAGD", 4th ed., Academic Press 1997
(1990 first ed.), §17 — curvature analysis, curvature combs.

Pottmann, H. & Wallner, J., "Computational Line Geometry", Springer 2001,
Ch 10 — isophote lines and normal curvature density.

Piegl, L. & Tiller, W., "The NURBS Book", 2nd ed., Springer 1997, §6.1 —
surface curvature and fundamental forms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface, curve_derivative


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CurvaturePeak:
    """A single detected curvature-comb peak."""

    # Normalised arc-length parameter s ∈ [0, 1]
    param_s: float
    # 3-D location on the curve
    location: np.ndarray
    # |κ| at the peak
    magnitude: float
    # Sharpness = 1 / half-width (how narrow the peak is in arc-length)
    sharpness: float

    def as_dict(self) -> dict:
        return {
            "param_s": float(self.param_s),
            "location": self.location.tolist(),
            "magnitude": float(self.magnitude),
            "sharpness": float(self.sharpness),
        }


@dataclass
class CurvaturePeakReport:
    """Result of curvature_comb_peaks()."""

    ok: bool
    reason: str = ""
    peaks: List[CurvaturePeak] = field(default_factory=list)
    kappa_values: List[float] = field(default_factory=list)
    kappa_mean: float = 0.0
    kappa_max: float = 0.0
    threshold: float = 0.0
    n_samples: int = 0

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "peaks": [p.as_dict() for p in self.peaks],
            "num_peaks": len(self.peaks),
            "kappa_values": [float(k) for k in self.kappa_values],
            "kappa_mean": float(self.kappa_mean),
            "kappa_max": float(self.kappa_max),
            "threshold": float(self.threshold),
            "n_samples": self.n_samples,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _curve_domain(curve: NurbsCurve) -> Tuple[float, float]:
    """Return (u_min, u_max) of the curve's knot domain."""
    return float(curve.knots[0]), float(curve.knots[-1])


def _sample_curvature(
    curve: NurbsCurve,
    n: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample curvature κ(s) along curve at *n* equi-parameter points.

    Returns (params, kappas, arc_lengths) where:
        params      : n parameter values (uniform in knot domain)
        kappas      : |κ| at each sample  (unsigned, for peak detection)
        arc_lengths : cumulative chord-length approximation (for TV integral)

    Curvature of a parametric curve C(t):

        κ = |C' × C''| / |C'|³        (cross-product formula for 3-D curves)

    For a planar 2-D curve the cross product reduces to the scalar:

        κ = |x'y'' - y'x''| / (x'² + y'²)^{3/2}

    Using rational-correct derivatives from ``curve_derivative``.

    Reference: Farin §2.6; Piegl & Tiller §6.1.
    """
    u_min, u_max = _curve_domain(curve)
    params = np.linspace(u_min, u_max, max(3, n))
    kappas = np.zeros(len(params))
    pts = np.zeros((len(params), 3))

    for i, t in enumerate(params):
        try:
            c1 = curve_derivative(curve, t, order=1)
            c2 = curve_derivative(curve, t, order=2)
        except Exception:
            kappas[i] = 0.0
            continue

        # Pad to 3-D if needed
        if c1.size < 3:
            c1 = np.concatenate([c1, np.zeros(3 - c1.size)])
        if c2.size < 3:
            c2 = np.concatenate([c2, np.zeros(3 - c2.size)])

        c1 = c1[:3]
        c2 = c2[:3]

        speed = float(np.linalg.norm(c1))
        if speed < 1e-15:
            kappas[i] = 0.0
            continue

        cross = np.cross(c1, c2)
        kappas[i] = float(np.linalg.norm(cross)) / (speed ** 3)

        # Point position
        try:
            pt = curve.evaluate(float(t))
            if pt.size < 3:
                pt = np.concatenate([pt, np.zeros(3 - pt.size)])
            pts[i] = pt[:3]
        except Exception:
            pts[i] = np.zeros(3)

    # Cumulative chord-length arc-lengths
    diffs = np.diff(pts, axis=0)
    chord_lens = np.sqrt(np.sum(diffs ** 2, axis=1))
    arc_lengths = np.concatenate([[0.0], np.cumsum(chord_lens)])

    return params, kappas, arc_lengths


# ---------------------------------------------------------------------------
# curvature_comb_peaks
# ---------------------------------------------------------------------------

def curvature_comb_peaks(
    curve: NurbsCurve,
    n_samples: int = 100,
    threshold_factor: float = 2.0,
) -> CurvaturePeakReport:
    """Detect curvature-comb peaks along a NURBS curve (Farin 1990 §17).

    Samples the curvature κ(t) at *n_samples* uniformly-spaced parameter
    values, detects local maxima where κ > threshold_factor × κ_mean, and
    returns each peak with its location, magnitude, and sharpness
    (1 / half-width in normalised arc-length).

    A "peak" is a local maximum of |κ|: a sample point where κ(i) > κ(i−1)
    and κ(i) > κ(i+1) AND κ(i) > threshold_factor × κ_mean.

    Sharpness is measured as the reciprocal of the half-width at half-maximum
    (HWHM) of the peak, computed by linear interpolation to find where κ falls
    below κ_peak / 2 on each side.  A knife-edge corner has sharpness → ∞;
    a broad smooth bulge has sharpness near 1.

    Parameters
    ----------
    curve : NurbsCurve
    n_samples : int
        Number of equi-parameter samples (default 100).
    threshold_factor : float
        Peaks must exceed this multiple of κ_mean to be reported
        (default 2.0 — filters background curvature variation).

    Returns
    -------
    CurvaturePeakReport
        ok, peaks (list of CurvaturePeak), kappa_values, kappa_mean,
        kappa_max, threshold, n_samples.

    Never raises.

    References
    ----------
    Farin, G., "Curves and Surfaces for CAGD" §17 (curvature analysis).
    Piegl & Tiller §6.1 (curvature formulas).
    """
    if not isinstance(curve, NurbsCurve):
        return CurvaturePeakReport(
            ok=False,
            reason=f"expected NurbsCurve, got {type(curve).__name__}",
        )

    n = max(5, int(n_samples))

    try:
        params, kappas, arc_lengths = _sample_curvature(curve, n)
    except Exception as exc:
        return CurvaturePeakReport(ok=False, reason=str(exc))

    total_arc = float(arc_lengths[-1]) if len(arc_lengths) > 0 else 0.0
    # Normalised arc-length ∈ [0, 1]
    if total_arc > 1e-15:
        s_norm = arc_lengths / total_arc
    else:
        s_norm = np.linspace(0.0, 1.0, len(arc_lengths))

    kappa_mean = float(np.mean(kappas))
    kappa_max = float(np.max(kappas))
    threshold = threshold_factor * kappa_mean

    peaks: List[CurvaturePeak] = []

    # Local-maximum detection (interior samples only)
    for i in range(1, len(kappas) - 1):
        k = kappas[i]
        if k <= threshold:
            continue
        if k >= kappas[i - 1] and k >= kappas[i + 1]:
            # Compute sharpness = 1 / HWHM (half-width at half-maximum)
            half_val = k / 2.0
            # Left half-width: walk left until κ ≤ half_val
            left_s = s_norm[i]
            for j in range(i - 1, -1, -1):
                if kappas[j] <= half_val:
                    # Linear interpolation
                    frac = (kappas[j + 1] - half_val) / max(
                        kappas[j + 1] - kappas[j], 1e-20
                    )
                    left_s = s_norm[j] + frac * (s_norm[j + 1] - s_norm[j])
                    break
            else:
                left_s = s_norm[0]

            # Right half-width
            right_s = s_norm[i]
            for j in range(i + 1, len(kappas)):
                if kappas[j] <= half_val:
                    frac = (kappas[j - 1] - half_val) / max(
                        kappas[j - 1] - kappas[j], 1e-20
                    )
                    right_s = s_norm[j - 1] + frac * (s_norm[j] - s_norm[j - 1])
                    break
            else:
                right_s = s_norm[-1]

            half_width = 0.5 * (float(right_s) - float(left_s))
            sharpness = 1.0 / half_width if half_width > 1e-15 else 1e6

            # Evaluate curve position at peak parameter
            try:
                pt = curve.evaluate(float(params[i]))
                if pt.size < 3:
                    pt = np.concatenate([pt, np.zeros(3 - pt.size)])
                pt = pt[:3].copy()
            except Exception:
                pt = np.zeros(3)

            peaks.append(
                CurvaturePeak(
                    param_s=float(s_norm[i]),
                    location=pt,
                    magnitude=float(k),
                    sharpness=float(sharpness),
                )
            )

    return CurvaturePeakReport(
        ok=True,
        reason="",
        peaks=peaks,
        kappa_values=kappas.tolist(),
        kappa_mean=kappa_mean,
        kappa_max=kappa_max,
        threshold=threshold,
        n_samples=n,
    )


# ---------------------------------------------------------------------------
# curvature_variance_metric
# ---------------------------------------------------------------------------

def curvature_variance_metric(
    curve: NurbsCurve,
    n_samples: int = 100,
) -> dict:
    """Statistical distribution of curvature κ(s) along a NURBS curve.

    Computes:

    * **variance** : Var(κ)  — zero for a circle (constant κ)
    * **std_dev**  : √Var(κ)
    * **skewness** : third standardised moment (scipy.stats.skew)
    * **kurtosis** : excess kurtosis (scipy.stats.kurtosis, Fisher definition)
    * **total_variation** : ∫|dκ/ds| · ds — sum of |κ(s+ds) - κ(s)|
      (chord-length weighted so it is arc-length independent)

    A uniform-curvature curve (circle, line) has variance = 0 and
    total_variation = 0.  A curve with oscillatory curvature has high
    variance; a curve with a single sharp feature has high total_variation
    but possibly lower variance.

    Parameters
    ----------
    curve : NurbsCurve
    n_samples : int
        Number of equi-parameter samples (default 100).

    Returns
    -------
    dict
        ok, variance, std_dev, skewness, kurtosis, total_variation,
        kappa_mean, kappa_max, kappa_min, n_samples.

    Never raises.

    References
    ----------
    Farin, G., §17.  Total variation: Farin (1990) curvature-comb quality
    criterion; also used in Alias / ICEM Surf class-A workflows.
    """
    if not isinstance(curve, NurbsCurve):
        return {"ok": False, "reason": f"expected NurbsCurve, got {type(curve).__name__}"}

    n = max(5, int(n_samples))

    try:
        _params, kappas, arc_lengths = _sample_curvature(curve, n)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}

    try:
        from scipy.stats import skew as _skew, kurtosis as _kurtosis  # type: ignore[import]
        _scipy_ok = True
    except ImportError:
        _scipy_ok = False

    variance = float(np.var(kappas))
    std_dev = float(np.std(kappas))
    kappa_mean = float(np.mean(kappas))
    kappa_max = float(np.max(kappas))
    kappa_min = float(np.min(kappas))

    if _scipy_ok and len(kappas) >= 3:
        skewness = float(_skew(kappas, bias=True))
        kurtosis_val = float(_kurtosis(kappas, fisher=True, bias=True))
    else:
        # Fallback manual computation
        if std_dev > 1e-15 and len(kappas) >= 3:
            z = (kappas - kappa_mean) / std_dev
            skewness = float(np.mean(z ** 3))
            kurtosis_val = float(np.mean(z ** 4)) - 3.0
        else:
            skewness = 0.0
            kurtosis_val = 0.0

    # Total variation: ∫|dκ/ds| · ds
    # Discretised as Σ |κ(i+1) - κ(i)| (arc-length step included via chord len)
    # The chord lengths serve as the arc-length measure ds.
    chord_lens = np.diff(arc_lengths)
    dkappa = np.abs(np.diff(kappas))
    # TV = Σ |Δκ_i|  (independent of chord length; chord only matters for
    # density but the standard definition is just sum of absolute increments)
    total_variation = float(np.sum(dkappa))

    return {
        "ok": True,
        "reason": "",
        "variance": variance,
        "std_dev": std_dev,
        "skewness": skewness,
        "kurtosis": kurtosis_val,
        "total_variation": total_variation,
        "kappa_mean": kappa_mean,
        "kappa_max": kappa_max,
        "kappa_min": kappa_min,
        "n_samples": n,
    }


# ---------------------------------------------------------------------------
# isophote_density_metric
# ---------------------------------------------------------------------------

def isophote_density_metric(
    surface: NurbsSurface,
    n_samples: int = 20,
    light_dir: Optional[Sequence[float]] = None,
) -> dict:
    """Isophote density metric (Pottmann-Wallner 2001 Ch 10).

    An *isophote* is a curve on a surface where the illumination cosine
    μ = n̂ · L̂ is constant (iso-brightness contour).  The density of
    isophote lines in a region is proportional to the local rate of change
    of μ, which in turn is governed by the curvature (via the Weingarten
    equations).  High isophote density signals high curvature or normal
    variation; low density signals a flat / cylindrical region.

    Concretely, the local isophote density is:

        ρ(u, v) = |∇_S μ(u, v)|

    where ∇_S μ is the surface gradient of the illumination cosine field.
    This is computed as:

        ∇_S μ = (∂μ/∂u · E_inverse + ∂μ/∂v · F_inverse) in parameter space
                projected back to 3-D via the metric tensor.

    Implemented via the Weingarten equations (do Carmo §3.3):

        dμ/du = (dn/du) · L̂
        dμ/dv = (dn/dv) · L̂

    where dn/du and dn/dv are the surface normal rate-of-change vectors.

    Parameters
    ----------
    surface : NurbsSurface
    n_samples : int
        Grid resolution N for an N×N sampling (default 20 → 400 samples).
    light_dir : 3-element sequence or None
        Illumination direction (default [0, 0, 1]).

    Returns
    -------
    dict
        ok, density_grid (n×n array of ρ), mean_density, max_density,
        std_density, spatial_variation (std of density — high for hypar),
        light_dir (list), n_samples.

    Never raises.

    References
    ----------
    Pottmann & Wallner, "Computational Line Geometry", Springer 2001, Ch 10.
    do Carmo, "Differential Geometry of Curves and Surfaces" §3.3.
    """
    if not isinstance(surface, NurbsSurface):
        return {"ok": False, "reason": f"expected NurbsSurface, got {type(surface).__name__}"}

    n = max(3, int(n_samples))
    n = min(n, 100)  # cap to avoid excessive compute

    if light_dir is None:
        L = np.array([0.0, 0.0, 1.0])
    else:
        L = np.asarray(light_dir, dtype=float).ravel()[:3]
        lnrm = float(np.linalg.norm(L))
        if lnrm < 1e-15:
            L = np.array([0.0, 0.0, 1.0])
        else:
            L = L / lnrm

    # Import surface analysis internals locally to avoid circular import at
    # module level.  curvature_metrics.py is a sibling module to surface_analysis.py.
    try:
        from kerf_cad_core.geom.surface_analysis import (
            _analytic_curvature_data,
            _uv_grid,
        )
    except Exception as exc:
        return {"ok": False, "reason": f"surface_analysis import failed: {exc}"}

    u_min = float(surface.knots_u[0])
    u_max = float(surface.knots_u[-1])
    v_min = float(surface.knots_v[0])
    v_max = float(surface.knots_v[-1])
    us = np.linspace(u_min, u_max, n)
    vs = np.linspace(v_min, v_max, n)

    density_grid = np.zeros((n, n))

    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            cd = _analytic_curvature_data(surface, float(u), float(v))
            if cd is None:
                density_grid[i, j] = float("nan")
                continue

            # Weingarten: rate of change of surface normal
            E, F, G = cd["E"], cd["F"], cd["G"]
            e_ff, f_ff, g_ff = cd["e"], cd["f"], cd["g"]
            EGF2 = cd["EGF2"]
            Su, Sv = cd["Su"], cd["Sv"]

            # dn/du via Weingarten equations (do Carmo §3.3, eq. 2)
            a11 = (f_ff * F - e_ff * G) / EGF2
            a12 = (e_ff * F - f_ff * E) / EGF2
            b11 = (g_ff * F - f_ff * G) / EGF2
            b12 = (f_ff * F - g_ff * E) / EGF2

            dn_du = a11 * Su + a12 * Sv
            dn_dv = b11 * Su + b12 * Sv

            # Gradient of μ = n̂·L̂ in surface parameter space
            dmu_du = float(np.dot(dn_du, L))
            dmu_dv = float(np.dot(dn_dv, L))

            # Surface gradient magnitude (arc-length normalised by metric)
            # |∇_S μ|² = g^{uu} (dμ/du)² + 2g^{uv}(dμ/du)(dμ/dv) + g^{vv}(dμ/dv)²
            # where g^{ij} is the inverse metric (g^{uu}=G/EGF2, etc.)
            g_uu = G / EGF2
            g_uv = -F / EGF2
            g_vv = E / EGF2

            grad_sq = (g_uu * dmu_du * dmu_du
                       + 2.0 * g_uv * dmu_du * dmu_dv
                       + g_vv * dmu_dv * dmu_dv)

            density_grid[i, j] = math.sqrt(max(0.0, grad_sq))

    valid = density_grid[np.isfinite(density_grid)]
    if len(valid) == 0:
        return {"ok": False, "reason": "all surface samples degenerate"}

    mean_density = float(np.mean(valid))
    max_density = float(np.max(valid))
    std_density = float(np.std(valid))

    return {
        "ok": True,
        "reason": "",
        "density_grid": density_grid.tolist(),
        "mean_density": mean_density,
        "max_density": max_density,
        "std_density": std_density,
        "spatial_variation": std_density,   # alias: high for hypar, low for flat/sphere
        "light_dir": L.tolist(),
        "n_samples": n,
    }


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

    # ------------------------------------------------------------------
    # Helper: build NurbsCurve from LLM tool args
    # ------------------------------------------------------------------

    def _build_curve_from_args(a: dict):
        """Build NurbsCurve from tool args dict. Returns (curve, error_str)."""
        degree = a.get("degree")
        raw_cp = a.get("control_points", [])
        if degree is None or not raw_cp:
            return None, "degree and control_points are required"

        try:
            degree = int(degree)
        except (TypeError, ValueError) as exc:
            return None, f"degree must be an integer: {exc}"

        try:
            cp = np.array([[float(x) for x in p] for p in raw_cp], dtype=float)
        except Exception as exc:
            return None, f"invalid control_points: {exc}"

        n = cp.shape[0]
        if n < degree + 1:
            return None, f"need at least degree+1={degree+1} control points, got {n}"

        # Build clamped uniform knot vector
        inner = max(0, n - degree - 1)
        knots = np.concatenate([
            np.zeros(degree + 1),
            np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
            np.ones(degree + 1),
        ])

        weights_raw = a.get("weights")
        weights = None
        if weights_raw is not None:
            try:
                weights = np.array([float(w) for w in weights_raw], dtype=float)
                if len(weights) != n:
                    return None, f"weights length {len(weights)} != num_control_points={n}"
            except Exception as exc:
                return None, f"invalid weights: {exc}"

        try:
            from kerf_cad_core.geom.nurbs import NurbsCurve as _NC
            curve = _NC(degree=degree, control_points=cp, knots=knots, weights=weights)
        except Exception as exc:
            return None, f"failed to build NurbsCurve: {exc}"

        return curve, ""

    # ------------------------------------------------------------------
    # Helper: build NurbsSurface from LLM tool args
    # ------------------------------------------------------------------

    def _build_surface_from_args_cm(a: dict):
        """Build NurbsSurface from tool args dict. Returns (surface, error_str)."""
        degree_u = a.get("degree_u")
        degree_v = a.get("degree_v")
        raw_cp = a.get("control_points", [])
        num_u = a.get("num_u")
        num_v = a.get("num_v")

        if any(x is None for x in [degree_u, degree_v, num_u, num_v]) or not raw_cp:
            return None, "degree_u, degree_v, control_points, num_u, num_v are required"

        try:
            degree_u, degree_v = int(degree_u), int(degree_v)
            num_u, num_v = int(num_u), int(num_v)
        except (TypeError, ValueError) as exc:
            return None, f"degree/num must be integers: {exc}"

        if len(raw_cp) != num_u * num_v:
            return None, (
                f"control_points length {len(raw_cp)} != num_u*num_v={num_u*num_v}"
            )

        try:
            cp_flat = [np.asarray(p, dtype=float) for p in raw_cp]
            dim = cp_flat[0].size
            cp = np.array([p.tolist()[:dim] for p in cp_flat], dtype=float).reshape(
                num_u, num_v, dim
            )
        except Exception as exc:
            return None, f"invalid control_points: {exc}"

        def _make_knots(n_cp: int, deg: int) -> np.ndarray:
            inner = max(0, n_cp - deg - 1)
            return np.concatenate([
                np.zeros(deg + 1),
                np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
                np.ones(deg + 1),
            ])

        try:
            from kerf_cad_core.geom.nurbs import NurbsSurface as _NS
            surface = _NS(
                degree_u=degree_u, degree_v=degree_v,
                control_points=cp,
                knots_u=_make_knots(num_u, degree_u),
                knots_v=_make_knots(num_v, degree_v),
            )
        except Exception as exc:
            return None, f"failed to build NurbsSurface: {exc}"

        return surface, ""

    # ------------------------------------------------------------------
    # nurbs_curvature_metrics
    # ------------------------------------------------------------------

    _curvature_metrics_spec = ToolSpec(
        name="nurbs_curvature_metrics",
        description=(
            "Curvature-comb peak detection and variance metrics for a NURBS curve "
            "(Farin 1990 §17).  Detects local maxima in |κ(s)| above threshold_factor "
            "× κ_mean and returns each peak with its arc-length parameter, 3-D location, "
            "magnitude, and sharpness.  Also returns variance, std_dev, skewness, "
            "kurtosis, and total variation ∫|dκ/ds|·ds.\n\n"
            "Inputs:\n"
            "  degree        (int)   NURBS degree\n"
            "  control_points (array) list of [x,y,z] or [x,y] control points\n"
            "  weights       (array, optional) rational weights\n"
            "  n_samples     (int, optional) curvature sample count (default 100)\n"
            "  threshold_factor (float, optional) peak threshold multiplier (default 2.0)\n\n"
            "Returns: {ok, peaks [{param_s, location, magnitude, sharpness}], "
            "num_peaks, kappa_mean, kappa_max, variance, std_dev, skewness, "
            "kurtosis, total_variation, n_samples}. Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree": {
                    "type": "integer",
                    "description": "NURBS degree (1=linear, 2=quadratic, 3=cubic).",
                },
                "control_points": {
                    "type": "array",
                    "description": "List of [x,y,z] or [x,y] control points.",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "weights": {
                    "type": "array",
                    "description": "Optional rational weights (one per control point).",
                    "items": {"type": "number"},
                },
                "n_samples": {
                    "type": "integer",
                    "description": "Number of curvature samples (default 100).",
                },
                "threshold_factor": {
                    "type": "number",
                    "description": "Peaks must exceed this × κ_mean (default 2.0).",
                },
            },
            "required": ["degree", "control_points"],
        },
    )

    @register(_curvature_metrics_spec)
    async def run_nurbs_curvature_metrics(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        curve, err = _build_curve_from_args(a)
        if curve is None:
            return err_payload(err, "BAD_ARGS")

        n = int(a.get("n_samples", 100))
        thresh = float(a.get("threshold_factor", 2.0))

        peak_report = curvature_comb_peaks(curve, n_samples=n, threshold_factor=thresh)
        if not peak_report.ok:
            return err_payload(peak_report.reason, "OP_FAILED")

        variance_result = curvature_variance_metric(curve, n_samples=n)
        if not variance_result["ok"]:
            return err_payload(variance_result["reason"], "OP_FAILED")

        payload = {
            **peak_report.as_dict(),
            "variance": variance_result["variance"],
            "std_dev": variance_result["std_dev"],
            "skewness": variance_result["skewness"],
            "kurtosis": variance_result["kurtosis"],
            "total_variation": variance_result["total_variation"],
        }
        return ok_payload(payload)
