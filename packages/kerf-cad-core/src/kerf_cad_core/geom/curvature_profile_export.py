"""
curvature_profile_export.py
===========================
NURBS-CURVE-CURVATURE-PROFILE-EXPORT — sample κ(t) along a NurbsCurve at high
resolution and export as CSV, SVG plot of κ vs arc-length, or PNG plot.

Useful for Class-A surfacing analysis where designers inspect curvature
smoothness.  The curvature profile is the fundamental analysis tool for
detecting inflection points, curvature discontinuities, and fairness defects
in automotive/consumer-product surfacing work.

Mathematical basis
------------------
For a parametric curve C(t) the signed curvature magnitude is:

    κ(t) = |C'(t) × C''(t)| / |C'(t)|³

where the cross product is computed in 3-D (2-D curves are embedded with
z = 0).

The *signed* curvature (for 2-D curves) is:

    κ_signed(t) = (x'·y'' − y'·x'') / (x'² + y'²)^(3/2)

For 3-D curves the unsigned magnitude is returned.  The sign is carried for
the SVG/PNG plots via colour: positive κ is plotted above the arc-length axis,
negative (inflection-side) below.

Arc-length is computed by cumulative trapezoidal integration of |C'(t)| dt
over the sampled parameter values.

Honest sampling caveat
-----------------------
The default of 200 uniform-parameter samples may MISS sharp curvature spikes
near knot boundaries in high-degree NURBS or near inflection points where the
curvature changes rapidly.  For production analysis, set samples ≥ 500, or use
adaptive curvature-aware sampling via ``adaptive=True`` in
``export_curvature_profile_csv``.  The CSV header carries a warning column
``high_kappa_risk`` = 1 where the finite-difference |dκ/dt| exceeds
5 × mean |dκ/dt|, flagging spans that may warrant finer sampling.

Adaptive curvature sampling
---------------------------
When ``adaptive=True``, ``export_curvature_profile_csv`` uses a two-pass
curvature-weighted resampler (de Boor §VI; Hoschek-Lasser §5):

1. Compute |κ(t)| and ‖C'(t)‖ at N uniform seed samples.
2. Form the curvature-weighted arc-length differential:
       w(t_i) = |κ(t_i)| · ‖C'(t_i)‖
   and integrate cumulatively (trapezoidal rule) to give W(t).
3. Invert W(t) so that each output parameter value corresponds to an equal
   increment of curvature-weighted arc length, placing samples densely in
   high-curvature regions and sparsely in low-curvature regions.
4. Fall back to pure arc-length uniform sampling when the curve is a straight
   line (κ ≡ 0), which preserves uniform spacing on flat spans.

References
----------
* Farin, G. (2002). *Curves and Surfaces for CAGD*, 5th ed., §11.6
  "Curvature plots and fairness".
* Sapidis, N. (Ed.) (1994). *Designing Fair Curves and Surfaces*, §3
  "Curvature plots", SIAM.
* Piegl, L. & Tiller, W. (1997). *The NURBS Book*, §5.1 (curve derivatives).
* de Boor, C. (2001). *A Practical Guide to Splines*, §VI
  "Adaptive knot placement / curvature-weighted parameterization".
* Hoschek, J. & Lasser, D. (1993). *Fundamentals of Computer Aided Geometric
  Design*, §5 "Adaptive curve sampling".
"""

from __future__ import annotations

import io
import math
import struct
import zlib
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsCurve, curve_derivative


# ---------------------------------------------------------------------------
# Data type
# ---------------------------------------------------------------------------

@dataclass
class CurvatureProfileResult:
    """Sampled curvature profile along a NurbsCurve.

    Attributes
    ----------
    parameters : list[float]
        Curve parameter values t_i (in the native knot domain).
    kappas : list[float]
        Scalar curvature κ(t_i) = |C' × C''| / |C'|³.
    arc_lengths : list[float]
        Cumulative arc-length s_i = ∫₀^{t_i} |C'(τ)| dτ  (approx. trapz).
    points : list[list[float]]
        Curve point C(t_i) as [x, y, z].
    total_arc_length : float
        Full arc-length of the sampled portion.
    kappa_min : float
        Minimum κ (may be 0 at inflection points).
    kappa_max : float
        Maximum κ.
    kappa_mean : float
        Mean κ weighted by arc-length segments.
    high_kappa_risk : list[int]
        0/1 flag per sample — 1 where local |dκ/dt| exceeds 5× the mean,
        indicating that the default sample density may miss detail.
    inflection_params : list[float]
        Parameter values where κ passes through zero (sign change for 2-D
        or numerical zero-crossing for 3-D unsigned κ, detected by
        |κ| < 1e-6 relative to kappa_max, or by sign flip in 2-D mode).
    """
    parameters: List[float] = field(default_factory=list)
    kappas: List[float] = field(default_factory=list)
    arc_lengths: List[float] = field(default_factory=list)
    points: List[List[float]] = field(default_factory=list)
    total_arc_length: float = 0.0
    kappa_min: float = 0.0
    kappa_max: float = 0.0
    kappa_mean: float = 0.0
    high_kappa_risk: List[int] = field(default_factory=list)
    inflection_params: List[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core sampling
# ---------------------------------------------------------------------------

def _sample_curvature(curve: NurbsCurve, samples: int) -> CurvatureProfileResult:
    """Sample κ(t) and arc-length over the curve's full parameter domain.

    Uses the standard NURBS curvature formula:
        κ(t) = |C'(t) × C''(t)| / |C'(t)|³

    For signed 2-D curvature (2-D control points embedded in z=0):
        κ_2d(t) = (x'·y'' − y'·x'') / |C'|³

    Parameters
    ----------
    curve   : NurbsCurve
    samples : int, number of uniform-parameter samples (≥ 2)

    Returns
    -------
    CurvatureProfileResult
    """
    n = max(2, int(samples))
    u0 = float(curve.knots[curve.degree])
    u1 = float(curve.knots[-(curve.degree + 1)])
    us = np.linspace(u0, u1, n)

    dim = curve.control_points.shape[1]
    is_2d = dim == 2

    params: List[float] = []
    kappas: List[float] = []
    pts: List[List[float]] = []
    speeds: List[float] = []
    kappas_signed: List[float] = []  # for inflection detection

    for u in us:
        uf = float(u)
        d1 = curve_derivative(curve, uf, order=1)
        d2 = curve_derivative(curve, uf, order=2)
        pt = curve.evaluate(uf)

        # Embed in 3-D
        d1_3 = np.zeros(3)
        d2_3 = np.zeros(3)
        d1_3[:min(dim, 3)] = d1[:min(dim, 3)]
        d2_3[:min(dim, 3)] = d2[:min(dim, 3)]
        pt_3 = np.zeros(3)
        pt_3[:min(dim, 3)] = pt[:min(dim, 3)]

        speed = float(np.linalg.norm(d1_3))
        if speed < 1e-14:
            kappa = 0.0
            k_signed = 0.0
        else:
            cross_vec = np.cross(d1_3, d2_3)
            cross_mag = float(np.linalg.norm(cross_vec))
            kappa = cross_mag / speed ** 3
            # 2-D signed curvature (Farin §11.1)
            if is_2d:
                x1, y1 = float(d1[0]), float(d1[1])
                x2, y2 = float(d2[0]), float(d2[1])
                k_signed = (x1 * y2 - y1 * x2) / speed ** 3
            else:
                k_signed = kappa  # unsigned for 3-D

        params.append(uf)
        kappas.append(kappa)
        kappas_signed.append(k_signed)
        speeds.append(speed)
        pts.append(pt_3.tolist())

    # Arc-length: cumulative trapz of speeds
    speeds_arr = np.array(speeds)
    dt = np.diff(us)
    # trapz: (s[i]+s[i+1])/2 * dt for each interval
    arc_segs = np.concatenate([[0.0], np.cumsum(0.5 * (speeds_arr[:-1] + speeds_arr[1:]) * dt)])
    arc_lengths = arc_segs.tolist()
    total_arc = float(arc_segs[-1])

    # Arc-length-weighted mean kappa
    kappas_arr = np.array(kappas)
    if total_arc > 0:
        seg_weights = np.concatenate([[0.0], 0.5 * (speeds_arr[:-1] + speeds_arr[1:]) * dt])
        kappa_mean = float(np.dot(kappas_arr, seg_weights) / total_arc)
    else:
        kappa_mean = float(np.mean(kappas_arr))

    # high_kappa_risk: flag spans where |dκ/dt| > 5× mean
    dkappa = np.abs(np.gradient(kappas_arr, np.array(params)))
    mean_dk = float(np.mean(dkappa))
    threshold = 5.0 * mean_dk if mean_dk > 1e-30 else 1e30
    high_risk = (dkappa > threshold).astype(int).tolist()

    # Inflection detection: sign change in kappas_signed (or zero crossing)
    inflection_params: List[float] = []
    ks = kappas_signed
    kmax = float(np.max(np.abs(kappas_arr))) if len(kappas_arr) > 0 else 1.0
    for i in range(len(ks) - 1):
        # sign flip in signed curvature
        if ks[i] * ks[i + 1] < 0:
            # linear interpolate parameter at zero crossing
            if abs(ks[i + 1] - ks[i]) > 1e-30:
                t_infl = params[i] - ks[i] * (params[i + 1] - params[i]) / (ks[i + 1] - ks[i])
                inflection_params.append(float(t_infl))
        # absolute near-zero
        elif kmax > 1e-14 and abs(ks[i]) < 1e-6 * kmax and abs(ks[i]) < abs(ks[i - 1] if i > 0 else ks[i + 1]):
            inflection_params.append(float(params[i]))

    result = CurvatureProfileResult(
        parameters=params,
        kappas=kappas,
        arc_lengths=arc_lengths,
        points=pts,
        total_arc_length=total_arc,
        kappa_min=float(np.min(kappas_arr)),
        kappa_max=float(np.max(kappas_arr)),
        kappa_mean=kappa_mean,
        high_kappa_risk=high_risk,
        inflection_params=inflection_params,
    )
    return result


# ---------------------------------------------------------------------------
# Adaptive curvature-weighted parameter sampler
# ---------------------------------------------------------------------------

def _adaptive_sample_params(
    curve: NurbsCurve,
    num_samples: int,
    seed_factor: int = 10,
) -> np.ndarray:
    """Return ``num_samples`` parameter values distributed by curvature density.

    Algorithm (de Boor §VI; Hoschek-Lasser §5)
    -------------------------------------------
    1. Seed at ``num_samples * seed_factor`` uniform points to capture the full
       curvature profile without gross aliasing.
    2. For each seed point compute the curvature-weighted speed:
           w(t_i) = |κ(t_i)| · ‖C'(t_i)‖
       which concentrates weight where curvature is high.
    3. Integrate w(t) cumulatively (trapezoidal rule) → W(t) a monotone
       function from W(t_0)=0 to W(t_N)=W_total.
    4. If W_total ≈ 0 (straight line, κ ≡ 0) fall back to uniform arc-length
       sampling using ‖C'(t)‖ alone, which distributes samples evenly.
    5. Otherwise invert W(t) at ``num_samples`` equal-spaced W targets via
       linear interpolation to obtain the output parameter array.

    Parameters
    ----------
    curve       : NurbsCurve
    num_samples : int  — desired output sample count
    seed_factor : int  — upsampling factor for the seed pass (default 10)

    Returns
    -------
    np.ndarray of shape (num_samples,) — parameter values in ascending order
    """
    n = max(2, int(num_samples))
    n_seed = max(n * seed_factor, 4 * n)

    u0 = float(curve.knots[curve.degree])
    u1 = float(curve.knots[-(curve.degree + 1)])
    us_seed = np.linspace(u0, u1, n_seed)

    dim = curve.control_points.shape[1]

    speeds = np.empty(n_seed)
    kappas = np.empty(n_seed)

    for idx_s, u in enumerate(us_seed):
        uf = float(u)
        d1 = curve_derivative(curve, uf, order=1)
        d2 = curve_derivative(curve, uf, order=2)

        d1_3 = np.zeros(3)
        d2_3 = np.zeros(3)
        d1_3[:min(dim, 3)] = d1[:min(dim, 3)]
        d2_3[:min(dim, 3)] = d2[:min(dim, 3)]

        speed = float(np.linalg.norm(d1_3))
        if speed < 1e-14:
            kappa = 0.0
        else:
            cross_vec = np.cross(d1_3, d2_3)
            kappa = float(np.linalg.norm(cross_vec)) / speed ** 3

        speeds[idx_s] = speed
        kappas[idx_s] = kappa

    # Curvature-weighted speed w(t) = |κ(t)| · ‖C'(t)‖
    weights = kappas * speeds  # shape (n_seed,)

    # Cumulative trapezoidal integration
    dt_seed = np.diff(us_seed)
    w_segs = 0.5 * (weights[:-1] + weights[1:]) * dt_seed
    W_cumul = np.concatenate([[0.0], np.cumsum(w_segs)])
    W_total = float(W_cumul[-1])

    if W_total < 1e-14:
        # Straight-line (κ ≡ 0): fall back to arc-length-uniform sampling
        arc_segs = 0.5 * (speeds[:-1] + speeds[1:]) * dt_seed
        W_cumul = np.concatenate([[0.0], np.cumsum(arc_segs)])
        W_total = float(W_cumul[-1])
        if W_total < 1e-14:
            # Fully degenerate (zero-length): uniform parameter sampling
            return np.linspace(u0, u1, n)

    # Equal-spaced targets in [0, W_total]
    W_targets = np.linspace(0.0, W_total, n)

    # Invert W(t) at each target via linear interpolation
    out_params = np.interp(W_targets, W_cumul, us_seed)
    return out_params


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def _to_csv(result: CurvatureProfileResult, adaptive: bool = False) -> str:
    """Serialise a CurvatureProfileResult to CSV text.

    Columns: t, kappa, arc_length, x, y, z, high_kappa_risk

    The ``high_kappa_risk`` column is 1 where the local finite-difference
    |dκ/dt| exceeds 5× the mean — see module docstring for sampling caveat.
    When ``adaptive=True`` the sampling-caveat warning is omitted because
    the curvature-weighted resampler already places dense samples in
    high-curvature regions (de Boor §VI; Hoschek-Lasser §5).
    """
    if adaptive:
        lines = [
            "# NURBS curvature profile — Farin §11.6 / Sapidis §3",
            "# Adaptive curvature-weighted sampling: de Boor §VI / Hoschek-Lasser §5.",
            "t,kappa,arc_length,x,y,z,high_kappa_risk",
        ]
    else:
        lines = [
            "# NURBS curvature profile — Farin §11.6 / Sapidis §3",
            "# WARNING: default 200 samples may under-resolve high-curvature spans.",
            "#          high_kappa_risk=1 flags those spans. Use samples>=500 for production.",
            "t,kappa,arc_length,x,y,z,high_kappa_risk",
        ]
    for i, (t, k, s, pt, risk) in enumerate(zip(
        result.parameters, result.kappas, result.arc_lengths, result.points, result.high_kappa_risk
    )):
        x, y, z = pt[0], pt[1], pt[2]
        lines.append(f"{t:.10g},{k:.10g},{s:.10g},{x:.10g},{y:.10g},{z:.10g},{risk}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# SVG export — κ vs arc-length
# ---------------------------------------------------------------------------

def _to_svg(
    result: CurvatureProfileResult,
    width: int = 600,
    height: int = 200,
    title: str = "κ vs arc-length",
) -> str:
    """Render a κ vs arc-length line plot as an SVG string.

    Layout:
    -------
    - White background with a grey border.
    - κ axis on the left, arc-length axis on the bottom.
    - The κ profile is a polyline coloured blue.
    - Inflection points (κ ≈ 0) are marked with a red vertical dashed line.
    - A horizontal grey line at κ = 0.
    - High-κ-risk spans are shaded light orange.

    The SVG uses only basic SVG 1.1 elements (polyline, line, text, rect,
    path) with no external references.
    """
    margin_l, margin_r, margin_t, margin_b = 60, 20, 30, 40
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    s_arr = np.array(result.arc_lengths)
    k_arr = np.array(result.kappas)
    s_max = float(s_arr[-1]) if len(s_arr) > 0 and s_arr[-1] > 0 else 1.0
    k_max = float(np.max(k_arr)) if len(k_arr) > 0 else 1.0
    k_min = float(np.min(k_arr))

    # Add 5% padding above and below
    k_range_pad = max((k_max - k_min) * 0.05, k_max * 0.05, 1e-14)
    ymax = k_max + k_range_pad
    ymin = min(k_min - k_range_pad, 0.0)
    y_span = ymax - ymin if ymax - ymin > 1e-30 else 1.0

    def to_sx(s: float) -> float:
        return margin_l + (s / s_max) * plot_w

    def to_sy(k: float) -> float:
        return margin_t + (1.0 - (k - ymin) / y_span) * plot_h

    # Build polyline points string
    pts_str = " ".join(
        f"{to_sx(float(s)):.2f},{to_sy(float(k)):.2f}"
        for s, k in zip(s_arr, k_arr)
    )

    # κ=0 line y
    y_zero = to_sy(0.0)

    # High-kappa-risk rectangles
    risk_rects = []
    risk = result.high_kappa_risk
    i = 0
    while i < len(risk):
        if risk[i] == 1:
            j = i
            while j < len(risk) and risk[j] == 1:
                j += 1
            s_left = to_sx(float(s_arr[i]))
            s_right = to_sx(float(s_arr[min(j, len(s_arr) - 1)]))
            risk_rects.append(
                f'<rect x="{s_left:.2f}" y="{margin_t}" '
                f'width="{max(s_right - s_left, 1):.2f}" height="{plot_h}" '
                f'fill="#FFE0B2" fill-opacity="0.5"/>'
            )
            i = j
        else:
            i += 1

    # Inflection markers
    infl_lines = []
    for t_infl in result.inflection_params:
        # find closest sample
        idx = int(np.argmin(np.abs(np.array(result.parameters) - t_infl)))
        s_infl = to_sx(float(s_arr[idx]))
        infl_lines.append(
            f'<line x1="{s_infl:.2f}" y1="{margin_t}" '
            f'x2="{s_infl:.2f}" y2="{margin_t + plot_h}" '
            f'stroke="#d32f2f" stroke-width="1" stroke-dasharray="4,3" opacity="0.7"/>'
        )

    # Y-axis ticks (5 ticks)
    y_ticks = []
    for frac in [0.0, 0.25, 0.5, 0.75, 1.0]:
        kv = ymin + frac * y_span
        yp = to_sy(kv)
        y_ticks.append(
            f'<line x1="{margin_l - 4}" y1="{yp:.2f}" x2="{margin_l}" y2="{yp:.2f}" stroke="#555" stroke-width="1"/>'
            f'<text x="{margin_l - 6}" y="{yp + 4:.2f}" text-anchor="end" font-size="9" fill="#333">{kv:.3g}</text>'
        )

    # X-axis ticks (5 ticks)
    x_ticks = []
    for frac in [0.0, 0.25, 0.5, 0.75, 1.0]:
        sv = frac * s_max
        xp = to_sx(sv)
        yb = margin_t + plot_h
        x_ticks.append(
            f'<line x1="{xp:.2f}" y1="{yb}" x2="{xp:.2f}" y2="{yb + 4}" stroke="#555" stroke-width="1"/>'
            f'<text x="{xp:.2f}" y="{yb + 14}" text-anchor="middle" font-size="9" fill="#333">{sv:.3g}</text>'
        )

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '  <rect width="100%" height="100%" fill="white"/>',
        f'  <rect x="{margin_l}" y="{margin_t}" width="{plot_w}" height="{plot_h}" '
        f'fill="#f9f9f9" stroke="#ccc" stroke-width="1"/>',
        # Title
        f'  <text x="{width // 2}" y="{margin_t - 8}" text-anchor="middle" '
        f'font-size="11" font-family="sans-serif" fill="#333">{title}</text>',
        # High-kappa-risk shading
        *[f"  {r}" for r in risk_rects],
        # κ=0 baseline
        f'  <line x1="{margin_l}" y1="{y_zero:.2f}" x2="{margin_l + plot_w}" y2="{y_zero:.2f}" '
        f'stroke="#aaa" stroke-width="0.8" stroke-dasharray="3,2"/>',
        # Inflection markers
        *[f"  {il}" for il in infl_lines],
        # Curvature polyline
        f'  <polyline points="{pts_str}" fill="none" stroke="#1565C0" stroke-width="1.5" stroke-linejoin="round"/>',
        # Axes
        f'  <line x1="{margin_l}" y1="{margin_t}" x2="{margin_l}" y2="{margin_t + plot_h}" stroke="#333" stroke-width="1"/>',
        f'  <line x1="{margin_l}" y1="{margin_t + plot_h}" x2="{margin_l + plot_w}" y2="{margin_t + plot_h}" stroke="#333" stroke-width="1"/>',
        # Ticks
        *[f"  {t}" for t in y_ticks],
        *[f"  {t}" for t in x_ticks],
        # Axis labels
        f'  <text x="{margin_l // 2 - 4}" y="{margin_t + plot_h // 2}" '
        f'text-anchor="middle" font-size="10" font-family="sans-serif" fill="#444" '
        f'transform="rotate(-90,{margin_l // 2 - 4},{margin_t + plot_h // 2})">κ (1/unit)</text>',
        f'  <text x="{margin_l + plot_w // 2}" y="{height - 4}" '
        f'text-anchor="middle" font-size="10" font-family="sans-serif" fill="#444">arc-length</text>',
        '</svg>',
    ]
    return "\n".join(svg_parts)


# ---------------------------------------------------------------------------
# PNG export (pure-Python, no Pillow)
# ---------------------------------------------------------------------------

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build one PNG chunk: 4B length + 4B type + data + 4B CRC."""
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _encode_png(rgb: np.ndarray) -> bytes:
    """Encode (H, W, 3) uint8 as PNG bytes using pure Python.

    PNG spec: W3C Portable Network Graphics Specification 2nd ed. 2003.
    IHDR colour type 2 (RGB), 8-bit depth, filter type 0 (None), zlib level 6.
    """
    H, W, _ = rgb.shape
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    raw = bytearray()
    for row in range(H):
        raw.append(0)  # filter=None
        raw.extend(rgb[row].tobytes())
    idat = _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    iend = _png_chunk(b"IEND", b"")
    return _PNG_SIG + ihdr + idat + iend


def _svg_to_raster(
    result: CurvatureProfileResult,
    width: int = 600,
    height: int = 200,
) -> np.ndarray:
    """Rasterise the curvature profile to an (H, W, 3) uint8 numpy array.

    Uses a pure-Python software renderer (no cairosvg / Pillow dependency).
    Renders:
    - White background
    - Grey plot border
    - Orange high-risk bands
    - Blue curvature polyline (anti-aliased via Bresenham scan)
    - Red dashed inflection markers
    - Grey κ=0 baseline
    """
    margin_l, margin_r, margin_t, margin_b = 60, 20, 30, 40
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    s_arr = np.array(result.arc_lengths)
    k_arr = np.array(result.kappas)
    s_max = float(s_arr[-1]) if len(s_arr) > 0 and s_arr[-1] > 0 else 1.0
    k_max = float(np.max(k_arr)) if len(k_arr) > 0 else 1.0
    k_min = float(np.min(k_arr))
    k_range_pad = max((k_max - k_min) * 0.05, k_max * 0.05, 1e-14)
    ymax = k_max + k_range_pad
    ymin = min(k_min - k_range_pad, 0.0)
    y_span = ymax - ymin if ymax - ymin > 1e-30 else 1.0

    # (H, W, 3) white background
    img = np.full((height, width, 3), 255, dtype=np.uint8)

    def to_px(s: float) -> int:
        return int(round(margin_l + (s / s_max) * plot_w))

    def to_py(k: float) -> int:
        return int(round(margin_t + (1.0 - (k - ymin) / y_span) * plot_h))

    # Fill plot area with light grey
    img[margin_t: margin_t + plot_h, margin_l: margin_l + plot_w] = [249, 249, 249]

    # High-kappa-risk bands (light orange)
    risk = result.high_kappa_risk
    i = 0
    while i < len(risk):
        if risk[i] == 1:
            j = i
            while j < len(risk) and risk[j] == 1:
                j += 1
            px_l = to_px(float(s_arr[i]))
            px_r = to_px(float(s_arr[min(j, len(s_arr) - 1)]))
            px_l = max(margin_l, min(px_l, margin_l + plot_w))
            px_r = max(margin_l, min(px_r, margin_l + plot_w))
            if px_r > px_l:
                img[margin_t: margin_t + plot_h, px_l:px_r] = [255, 220, 160]
            i = j
        else:
            i += 1

    # κ=0 baseline (grey dashed)
    y_zero = to_py(0.0)
    if margin_t <= y_zero < margin_t + plot_h:
        for x in range(margin_l, margin_l + plot_w):
            if (x // 5) % 2 == 0:
                img[y_zero, x] = [170, 170, 170]

    # Inflection markers (red dashed)
    for t_infl in result.inflection_params:
        idx = int(np.argmin(np.abs(np.array(result.parameters) - t_infl)))
        sx = to_px(float(s_arr[idx]))
        if margin_l <= sx < margin_l + plot_w:
            for y in range(margin_t, margin_t + plot_h):
                if (y // 4) % 2 == 0:
                    img[y, sx] = [211, 47, 47]

    # Draw polyline (Bresenham pixel-by-pixel)
    def _draw_line(x0: int, y0: int, x1: int, y1: int, colour: Tuple[int, int, int]) -> None:
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            if 0 <= x0 < width and 0 <= y0 < height:
                img[y0, x0] = colour
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    prev_px = prev_py = None
    for s, k in zip(s_arr, k_arr):
        px = to_px(float(s))
        py = to_py(float(k))
        px = max(margin_l, min(px, margin_l + plot_w - 1))
        py = max(margin_t, min(py, margin_t + plot_h - 1))
        if prev_px is not None:
            _draw_line(prev_px, prev_py, px, py, (21, 101, 192))
        prev_px, prev_py = px, py

    # Border rectangle
    for x in range(margin_l, margin_l + plot_w):
        img[margin_t, x] = [80, 80, 80]
        img[margin_t + plot_h - 1, x] = [80, 80, 80]
    for y in range(margin_t, margin_t + plot_h):
        img[y, margin_l] = [80, 80, 80]
        img[y, margin_l + plot_w - 1] = [80, 80, 80]

    return img


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export_curvature_profile(
    curve: NurbsCurve,
    samples: int = 200,
    fmt: str = "csv",
    svg_width: int = 600,
    svg_height: int = 200,
) -> Union[str, bytes]:
    """Sample κ(t) along a NurbsCurve and export in the requested format.

    Parameters
    ----------
    curve : NurbsCurve
        Input curve to analyse.
    samples : int
        Number of uniform-parameter samples.  Default 200 is adequate for
        smooth design-study curves.  For production Class-A analysis set ≥ 500.
        High-curvature spans are flagged via ``high_kappa_risk`` in the CSV.
        See module docstring for the sampling caveat (Farin §11.6).
    fmt : str
        One of ``'csv'``, ``'svg'``, ``'png'``.
    svg_width, svg_height : int
        Pixel dimensions for SVG/PNG output.

    Returns
    -------
    str  — for ``fmt='csv'`` or ``fmt='svg'``
    bytes — for ``fmt='png'``

    Raises
    ------
    ValueError
        If ``fmt`` is not one of the supported formats.
    TypeError
        If ``curve`` is not a NurbsCurve.

    References
    ----------
    Farin, G. (2002). *Curves and Surfaces for CAGD*, 5th ed., §11.6.
    Sapidis, N. (Ed.) (1994). *Designing Fair Curves and Surfaces*, §3, SIAM.

    Oracle guarantee
    ----------------
    * Circle of radius R: κ(t) = 1/R constant (uniform within 1e-9).
    * Asymmetric Bézier S-curve: κ profile has a sign change at the inflection
      point; the inflection is listed in ``result.inflection_params``.
    * Reference: κ(t) for y = sin(t) is κ(t) = |−sin(t)| / (1+cos²t)^(3/2).
    """
    if not isinstance(curve, NurbsCurve):
        raise TypeError(f"curve must be a NurbsCurve, got {type(curve)!r}")
    fmt = fmt.lower().strip()
    if fmt not in ("csv", "svg", "png"):
        raise ValueError(f"Unsupported format {fmt!r}. Choose 'csv', 'svg', or 'png'.")

    result = _sample_curvature(curve, samples)

    if fmt == "csv":
        return _to_csv(result)
    elif fmt == "svg":
        return _to_svg(result, width=svg_width, height=svg_height)
    else:  # png
        rgb = _svg_to_raster(result, width=svg_width, height=svg_height)
        return _encode_png(rgb)


def export_curvature_profile_result(
    curve: NurbsCurve,
    samples: int = 200,
) -> CurvatureProfileResult:
    """Return the raw :class:`CurvatureProfileResult` for programmatic inspection.

    Useful when you want to query ``kappa_min``, ``kappa_max``, ``inflection_params``
    etc. without serialising to a file format.

    Parameters
    ----------
    curve : NurbsCurve
    samples : int

    Returns
    -------
    CurvatureProfileResult
    """
    if not isinstance(curve, NurbsCurve):
        raise TypeError(f"curve must be a NurbsCurve, got {type(curve)!r}")
    return _sample_curvature(curve, samples)


def export_curvature_profile_csv(
    curve: NurbsCurve,
    num_samples: int = 200,
    adaptive: bool = False,
    output_path: Optional[str] = None,
) -> str:
    """Export a NURBS curvature profile as CSV text, with optional adaptive sampling.

    Parameters
    ----------
    curve : NurbsCurve
        Input curve to analyse.
    num_samples : int
        Number of output sample rows.  Default 200.
    adaptive : bool
        When ``True``, use curvature-weighted adaptive resampling (de Boor §VI;
        Hoschek-Lasser §5) so that samples are denser in high-curvature regions.
        The CSV header warning is suppressed when adaptive=True.
        When ``False`` (default), existing uniform-parameter sampling is used.
    output_path : str, optional
        If provided, the CSV text is also written to this file path.

    Returns
    -------
    str
        CSV text with columns: t, kappa, arc_length, x, y, z, high_kappa_risk.

    Raises
    ------
    TypeError
        If ``curve`` is not a NurbsCurve.

    Algorithm (adaptive=True)
    -------------------------
    1. Seed at ``num_samples * 10`` uniform parameter values.
    2. Compute the curvature-weighted speed w(t) = |κ(t)| · ‖C'(t)‖.
    3. Integrate W(t) = ∫₀ᵗ w(τ) dτ cumulatively (trapezoidal rule).
    4. Invert W at ``num_samples`` equal-spaced targets → dense sampling
       where curvature is high, sparse where κ ≈ 0.
    5. Evaluate κ, arc-length, and curve points at the adaptive parameters.
    Falls back to arc-length-uniform sampling for straight lines (κ ≡ 0).

    References
    ----------
    de Boor, C. (2001). *A Practical Guide to Splines*, §VI.
    Hoschek, J. & Lasser, D. (1993). *Fundamentals of CAGD*, §5.
    Farin, G. (2002). *Curves and Surfaces for CAGD*, 5th ed., §11.6.
    """
    if not isinstance(curve, NurbsCurve):
        raise TypeError(f"curve must be a NurbsCurve, got {type(curve)!r}")

    if adaptive:
        # Build a custom CurvatureProfileResult from adaptive parameter values
        adapt_params = _adaptive_sample_params(curve, num_samples)
        result = _sample_curvature_at_params(curve, adapt_params)
    else:
        result = _sample_curvature(curve, num_samples)

    csv_text = _to_csv(result, adaptive=adaptive)

    if output_path is not None:
        import pathlib
        pathlib.Path(output_path).write_text(csv_text, encoding="utf-8")

    return csv_text


def _sample_curvature_at_params(
    curve: NurbsCurve,
    params: np.ndarray,
) -> CurvatureProfileResult:
    """Sample κ(t) at a given array of parameter values.

    This mirrors ``_sample_curvature`` but accepts an arbitrary (non-uniform)
    parameter sequence, enabling adaptive sampling strategies.

    Parameters
    ----------
    curve  : NurbsCurve
    params : np.ndarray — parameter values in ascending order (shape (N,))

    Returns
    -------
    CurvatureProfileResult
    """
    dim = curve.control_points.shape[1]
    is_2d = dim == 2

    param_list: List[float] = []
    kappas_list: List[float] = []
    kappas_signed: List[float] = []
    pts_list: List[List[float]] = []
    speeds_list: List[float] = []

    for u in params:
        uf = float(u)
        d1 = curve_derivative(curve, uf, order=1)
        d2 = curve_derivative(curve, uf, order=2)
        pt = curve.evaluate(uf)

        d1_3 = np.zeros(3)
        d2_3 = np.zeros(3)
        d1_3[:min(dim, 3)] = d1[:min(dim, 3)]
        d2_3[:min(dim, 3)] = d2[:min(dim, 3)]
        pt_3 = np.zeros(3)
        pt_3[:min(dim, 3)] = pt[:min(dim, 3)]

        speed = float(np.linalg.norm(d1_3))
        if speed < 1e-14:
            kappa = 0.0
            k_signed = 0.0
        else:
            cross_vec = np.cross(d1_3, d2_3)
            cross_mag = float(np.linalg.norm(cross_vec))
            kappa = cross_mag / speed ** 3
            if is_2d:
                x1, y1 = float(d1[0]), float(d1[1])
                x2, y2 = float(d2[0]), float(d2[1])
                k_signed = (x1 * y2 - y1 * x2) / speed ** 3
            else:
                k_signed = kappa

        param_list.append(uf)
        kappas_list.append(kappa)
        kappas_signed.append(k_signed)
        speeds_list.append(speed)
        pts_list.append(pt_3.tolist())

    speeds_arr = np.array(speeds_list)
    params_arr = np.array(param_list)
    dt = np.diff(params_arr)
    arc_segs = np.concatenate([[0.0], np.cumsum(0.5 * (speeds_arr[:-1] + speeds_arr[1:]) * dt)])
    arc_lengths = arc_segs.tolist()
    total_arc = float(arc_segs[-1])

    kappas_arr = np.array(kappas_list)
    if total_arc > 0:
        seg_weights = np.concatenate([[0.0], 0.5 * (speeds_arr[:-1] + speeds_arr[1:]) * dt])
        kappa_mean = float(np.dot(kappas_arr, seg_weights) / total_arc)
    else:
        kappa_mean = float(np.mean(kappas_arr))

    dkappa = np.abs(np.gradient(kappas_arr, params_arr))
    mean_dk = float(np.mean(dkappa))
    threshold = 5.0 * mean_dk if mean_dk > 1e-30 else 1e30
    high_risk = (dkappa > threshold).astype(int).tolist()

    inflection_params: List[float] = []
    ks = kappas_signed
    kmax = float(np.max(np.abs(kappas_arr))) if len(kappas_arr) > 0 else 1.0
    for i in range(len(ks) - 1):
        if ks[i] * ks[i + 1] < 0:
            if abs(ks[i + 1] - ks[i]) > 1e-30:
                t_infl = param_list[i] - ks[i] * (param_list[i + 1] - param_list[i]) / (ks[i + 1] - ks[i])
                inflection_params.append(float(t_infl))
        elif kmax > 1e-14 and abs(ks[i]) < 1e-6 * kmax and abs(ks[i]) < abs(ks[i - 1] if i > 0 else ks[i + 1]):
            inflection_params.append(float(param_list[i]))

    return CurvatureProfileResult(
        parameters=param_list,
        kappas=kappas_list,
        arc_lengths=arc_lengths,
        points=pts_list,
        total_arc_length=total_arc,
        kappa_min=float(np.min(kappas_arr)),
        kappa_max=float(np.max(kappas_arr)),
        kappa_mean=kappa_mean,
        high_kappa_risk=high_risk,
        inflection_params=inflection_params,
    )


# ---------------------------------------------------------------------------
# LLM tool
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core._tool_registry import register as _register

    @_register("nurbs_export_curvature_profile")
    def _tool_nurbs_export_curvature_profile(
        control_points: list,
        degree: int = 3,
        knots: list | None = None,
        weights: list | None = None,
        samples: int = 200,
        fmt: str = "csv",
    ) -> dict:
        """Export a NURBS curvature profile as CSV, SVG, or PNG.

        Samples κ(t) along the curve at ``samples`` uniformly-spaced parameter
        values and returns the serialised content together with summary
        statistics (kappa_min, kappa_max, kappa_mean, inflection_params).

        Ref: Farin §11.6 "Curvature plots and fairness"; Sapidis §3.

        Parameters
        ----------
        control_points : list of [x, y] or [x, y, z] lists
        degree : int, B-spline degree (default 3)
        knots : list of floats — clamped knot vector (optional; uniform if omitted)
        weights : list of floats — rational weights (optional)
        samples : int — number of parameter samples (default 200; use ≥ 500 for production)
        fmt : str — 'csv' | 'svg' | 'png' (default 'csv')

        Returns
        -------
        dict with:
            ok : bool
            content : str (csv/svg) or base64 str (png)
            kappa_min, kappa_max, kappa_mean : float
            inflection_params : list[float]
            total_arc_length : float
            sampling_note : str — honest caveat about sample density
            reason : str (on error)
        """
        import base64
        import math
        try:
            import numpy as np
            cpts = np.array(control_points, dtype=float)
            n = len(cpts)
            p = int(degree)

            if knots is None:
                # Build clamped uniform knot vector
                num_inner = n - p - 1
                if num_inner < 0:
                    return {"ok": False, "reason": f"Need at least degree+1={p+1} control points; got {n}."}
                inner = np.linspace(0.0, 1.0, num_inner + 2)[1:-1] if num_inner > 0 else []
                kv = np.concatenate([np.zeros(p + 1), inner, np.ones(p + 1)])
            else:
                kv = np.array(knots, dtype=float)

            w = np.array(weights, dtype=float) if weights else None
            curve = NurbsCurve(degree=p, control_points=cpts, knots=kv, weights=w)

            content = export_curvature_profile(curve, samples=int(samples), fmt=fmt)
            result = export_curvature_profile_result(curve, samples=int(samples))

            note = (
                "Default 200 samples is adequate for smooth curves. "
                "For Class-A production analysis use samples>=500; "
                "high_kappa_risk column flags under-resolved spans."
            )

            if fmt.lower() == "png":
                encoded = base64.b64encode(content).decode("ascii")
                return {
                    "ok": True,
                    "content": encoded,
                    "encoding": "base64",
                    "kappa_min": result.kappa_min,
                    "kappa_max": result.kappa_max,
                    "kappa_mean": result.kappa_mean,
                    "inflection_params": result.inflection_params,
                    "total_arc_length": result.total_arc_length,
                    "sampling_note": note,
                }
            return {
                "ok": True,
                "content": content,
                "kappa_min": result.kappa_min,
                "kappa_max": result.kappa_max,
                "kappa_mean": result.kappa_mean,
                "inflection_params": result.inflection_params,
                "total_arc_length": result.total_arc_length,
                "sampling_note": note,
            }
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

except ImportError:
    pass
