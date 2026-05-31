"""
kerf_cad_core.optics.sagitta_arrow_chart — Conic + aspheric surface sagitta computation
and SVG arrow-chart visualisation.

Standard surface formula (ISO 10110-12 / Welford "Aberrations of Optical Systems" §3.3):

    z(r) = c·r² / (1 + √(1 − (1+k)·c²·r²))  +  Σ aᵢ·r^(2i+2)

where:
  c  = 1/R  (curvature; R = radius of curvature in mm)
  k  = conic constant (k=0 sphere; k=-1 paraboloid; k<-1 hyperboloid; k>0 oblate)
  aᵢ = even-power aspheric coefficients (a₁ acts on r⁴, a₂ on r⁶, …)
       The list is [a₁, a₂, a₃, …] → contribution aᵢ·r^(2·(i+1)+2) = aᵢ·r^(2i+4) ?
       Following ISO 10110-12 §6.2 indexing: aspheric_coeffs[0] is A₂ (r⁴ term), etc.
       i.e. Σ_{i=0}^{N-1} aspheric_coeffs[i] · r^(2*(i+2))  → r⁴, r⁶, r⁸, ...

Honest caveats:
  - Conic + even-power polynomial asphere only (ISO 10110-12 §6.2).
  - No Zernike / freeform / Q-polynomial surface support.
  - No off-axis / XY polynomial surface terms.
  - Validity at r = R_aperture requires (1+k)·c²·R² ≤ 1 (radicand ≥ 0).
  - Arrow slope markers show dz/dr (not the surface normal direction).

References
----------
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986, §3.3.
ISO 10110-12:2019 — Optics and photonics — Preparation of drawings for optical
    elements and systems — Part 12: Aspheric surfaces.
Smith, W.J. — "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008.

Units: lengths in mm.
Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AsphericSurfaceSpec:
    """
    Specification of a conic + even-power aspheric optical surface.

    Attributes
    ----------
    radius_mm : float
        Paraxial radius of curvature R (mm).  c = 1/R.
        Positive for a centre-of-curvature to the right (standard sign convention).
        Use a very large value (e.g. 1e12) for a flat surface.
    conic_k : float
        Conic constant k.
          k =  0  → sphere
          k = -1  → paraboloid
          k < -1  → hyperboloid
          k > -1 and k ≠ 0 → ellipsoid (oblate if k > 0)
    aspheric_coeffs : list[float]
        Even-power aspheric polynomial coefficients following ISO 10110-12 §6.2.
        Index 0 = A₂ (multiplies r⁴), index 1 = A₃ (r⁶), index 2 = A₄ (r⁸), etc.
        Empty list → pure conic surface.
    clear_aperture_radius_mm : float
        Semi-diameter of the clear aperture (mm).  Sagitta is sampled from r=0
        to r = clear_aperture_radius_mm.
    """
    radius_mm: float
    conic_k: float
    aspheric_coeffs: List[float]
    clear_aperture_radius_mm: float


@dataclass
class SagittaArrowChartResult:
    """
    Result of compute_sagitta_arrow_chart.

    Attributes
    ----------
    sagitta_samples : list of (r, z) tuples
        Sampled (r, z(r)) pairs in mm.
    max_sagitta_mm : float
        z at r = clear_aperture_radius_mm (edge sagitta).
    conic_only_sagitta_mm : float
        Edge sagitta from the conic term alone (aspheric_coeffs=0).
    aspheric_contribution_mm : float
        Difference max_sagitta_mm − conic_only_sagitta_mm.
    svg_chart : str
        SVG string with sagitta profile curve and sagittal arrow markers.
    honest_caveat : str
        Plain-text caveats about model scope.
    """
    sagitta_samples: List[Tuple[float, float]]
    max_sagitta_mm: float
    conic_only_sagitta_mm: float
    aspheric_contribution_mm: float
    svg_chart: str
    honest_caveat: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = True
        return d


# ---------------------------------------------------------------------------
# Core maths
# ---------------------------------------------------------------------------

_CONIC_DOMAIN_EPS = 1e-9  # floating-point tolerance for radicand clamping


def _conic_sag(r: float, c: float, k: float) -> float:
    """
    Conic-section sagitta:  z = c·r² / (1 + √(1 − (1+k)·c²·r²))

    Returns float, or raises ValueError if the radicand is significantly negative
    (r meaningfully exceeds the domain boundary for this conic).
    Tiny negative values within _CONIC_DOMAIN_EPS of zero are clamped to 0 to
    handle floating-point round-off at exact domain boundaries (e.g. hemisphere).
    """
    discriminant = 1.0 - (1.0 + k) * c * c * r * r
    if discriminant < -_CONIC_DOMAIN_EPS:
        raise ValueError(
            f"radicand is negative ({discriminant:.6g}) at r={r:.4g} mm — "
            "aperture exceeds conic domain limit; reduce clear_aperture_radius_mm "
            "or adjust conic_k."
        )
    # Clamp to zero to avoid sqrt of tiny negative float
    discriminant = max(discriminant, 0.0)
    return c * r * r / (1.0 + math.sqrt(discriminant))


def _aspheric_term(r: float, coeffs: list[float]) -> float:
    """Sum of even-power aspheric terms: Σ coeffs[i] * r^(2*(i+2))."""
    total = 0.0
    for i, a in enumerate(coeffs):
        total += a * r ** (2 * (i + 2))
    return total


def _sagitta(r: float, c: float, k: float, coeffs: list[float]) -> float:
    """Full aspheric sagitta z(r)."""
    return _conic_sag(r, c, k) + _aspheric_term(r, coeffs)


def _dz_dr(r: float, c: float, k: float, coeffs: list[float], eps: float = 1e-7) -> float:
    """
    Numerical derivative dz/dr at r via central-difference (or forward-difference at r=0).
    Returns 0.0 on any arithmetic failure.
    """
    if r < eps:
        # At r=0 the derivative is 0 by symmetry for any even-power surface
        return 0.0
    try:
        z_plus = _sagitta(r + eps, c, k, coeffs)
        z_minus = _sagitta(r - eps, c, k, coeffs)
        return (z_plus - z_minus) / (2.0 * eps)
    except (ValueError, ZeroDivisionError):
        return 0.0


# ---------------------------------------------------------------------------
# SVG generation
# ---------------------------------------------------------------------------

_SVG_W = 480
_SVG_H = 300
_PAD_L = 55
_PAD_R = 20
_PAD_T = 20
_PAD_B = 45


def _build_svg(samples: list[tuple[float, float]], r_max: float, z_max: float,
               c: float, k: float, coeffs: list[float]) -> str:
    """
    Build an SVG chart:
      - Polyline of z(r)
      - Axes with tick labels
      - Arrow markers at every 5th sample showing local slope dz/dr
      - Title + legend
    """
    plot_w = _SVG_W - _PAD_L - _PAD_R
    plot_h = _SVG_H - _PAD_T - _PAD_B

    # Guard against degenerate z range
    z_min_plot = 0.0
    z_max_plot = z_max if z_max > 0 else 1.0

    def to_px(r: float, z: float) -> tuple[float, float]:
        """Map (r, z) in mm to SVG pixel coordinates."""
        x = _PAD_L + (r / r_max) * plot_w if r_max > 0 else _PAD_L
        y = _PAD_T + plot_h - ((z - z_min_plot) / (z_max_plot - z_min_plot)) * plot_h
        return round(x, 2), round(y, 2)

    # Polyline points
    pts = []
    for r, z in samples:
        px, py = to_px(r, z)
        pts.append(f"{px},{py}")
    polyline_pts = " ".join(pts)

    # Arrow markers (every 5th sample index, skip index 0)
    arrows: list[str] = []
    arrow_len_px = 18.0
    for idx, (r, z) in enumerate(samples):
        if idx == 0 or idx % 5 != 0:
            continue
        slope = _dz_dr(r, c, k, coeffs)
        # direction in data-space: (1, slope); normalise to pixel space
        # Note: y-axis is inverted in SVG
        dx_data = 1.0
        dy_data = slope
        # scale factor for pixel space
        scale_r = plot_w / r_max if r_max > 0 else 1.0
        scale_z = plot_h / (z_max_plot - z_min_plot) if (z_max_plot - z_min_plot) > 0 else 1.0
        dx_px = dx_data * scale_r
        dy_px = -dy_data * scale_z  # negative because SVG y is down
        length = math.sqrt(dx_px ** 2 + dy_px ** 2)
        if length < 1e-9:
            continue
        dx_n = dx_px / length
        dy_n = dy_px / length
        ax, ay = to_px(r, z)
        # arrow tail and head
        x1 = ax - dx_n * arrow_len_px * 0.5
        y1 = ay - dy_n * arrow_len_px * 0.5
        x2 = ax + dx_n * arrow_len_px * 0.5
        y2 = ay + dy_n * arrow_len_px * 0.5
        # arrowhead as a small triangle at (x2, y2)
        # perpendicular direction
        perp_x = -dy_n
        perp_y = dx_n
        head_size = 5.0
        hx1 = x2 - dx_n * head_size + perp_x * head_size * 0.4
        hy1 = y2 - dy_n * head_size + perp_y * head_size * 0.4
        hx2 = x2 - dx_n * head_size - perp_x * head_size * 0.4
        hy2 = y2 - dy_n * head_size - perp_y * head_size * 0.4
        arrows.append(
            f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#e74c3c" stroke-width="1.5"/>\n'
            f'  <polygon points="{x2:.1f},{y2:.1f} {hx1:.1f},{hy1:.1f} {hx2:.1f},{hy2:.1f}" '
            f'fill="#e74c3c"/>'
        )

    # Axis ticks — 5 divisions
    x_ticks = []
    z_ticks = []
    for i in range(6):
        frac = i / 5.0
        # x axis (radius)
        r_val = frac * r_max
        xpx = _PAD_L + frac * plot_w
        ypx = _PAD_T + plot_h
        x_ticks.append(
            f'  <line x1="{xpx:.1f}" y1="{ypx:.1f}" x2="{xpx:.1f}" y2="{ypx+5:.1f}" '
            f'stroke="#333" stroke-width="1"/>\n'
            f'  <text x="{xpx:.1f}" y="{ypx+16:.1f}" font-size="10" text-anchor="middle" '
            f'fill="#333">{r_val:.2g}</text>'
        )
        # z axis (sagitta)
        z_val = z_min_plot + frac * (z_max_plot - z_min_plot)
        xpx_z = _PAD_L
        ypx_z = _PAD_T + plot_h - frac * plot_h
        z_ticks.append(
            f'  <line x1="{xpx_z-5:.1f}" y1="{ypx_z:.1f}" x2="{xpx_z:.1f}" y2="{ypx_z:.1f}" '
            f'stroke="#333" stroke-width="1"/>\n'
            f'  <text x="{xpx_z-8:.1f}" y="{ypx_z+4:.1f}" font-size="10" text-anchor="end" '
            f'fill="#333">{z_val:.3g}</text>'
        )

    arrows_svg = "\n".join(arrows)
    x_ticks_svg = "\n".join(x_ticks)
    z_ticks_svg = "\n".join(z_ticks)

    ax_left = _PAD_L
    ax_bottom = _PAD_T + plot_h
    ax_right = _PAD_L + plot_w
    ax_top = _PAD_T

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_SVG_W} {_SVG_H}" width="{_SVG_W}" height="{_SVG_H}">
  <!-- Background -->
  <rect width="{_SVG_W}" height="{_SVG_H}" fill="#fafafa" rx="4"/>
  <!-- Plot area border -->
  <rect x="{ax_left}" y="{ax_top}" width="{plot_w}" height="{plot_h}"
        fill="white" stroke="#ccc" stroke-width="1"/>
  <!-- X axis -->
  <line x1="{ax_left}" y1="{ax_bottom}" x2="{ax_right}" y2="{ax_bottom}"
        stroke="#333" stroke-width="1.5"/>
  <!-- Y axis -->
  <line x1="{ax_left}" y1="{ax_top}" x2="{ax_left}" y2="{ax_bottom}"
        stroke="#333" stroke-width="1.5"/>
  <!-- X ticks + labels -->
{x_ticks_svg}
  <!-- Y ticks + labels -->
{z_ticks_svg}
  <!-- Axis titles -->
  <text x="{ax_left + plot_w // 2}" y="{_SVG_H - 6}" font-size="11" text-anchor="middle" fill="#333">
    Radius r (mm)
  </text>
  <text x="12" y="{ax_top + plot_h // 2}" font-size="11" text-anchor="middle" fill="#333"
        transform="rotate(-90,12,{ax_top + plot_h // 2})">
    Sagitta z (mm)
  </text>
  <!-- Sagitta profile polyline -->
  <polyline points="{polyline_pts}"
            fill="none" stroke="#2980b9" stroke-width="2" stroke-linejoin="round"/>
  <!-- Slope arrow markers (every 5th sample) -->
{arrows_svg}
  <!-- Chart title -->
  <text x="{ax_left + plot_w // 2}" y="{ax_top - 5}" font-size="11" font-weight="bold"
        text-anchor="middle" fill="#222">
    Sagitta z(r) — Conic + Aspheric Surface
  </text>
</svg>"""
    return svg


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_HONEST_CAVEAT = (
    "SCOPE: Standard conic + even-power aspheric surface (ISO 10110-12 §6.2). "
    "Conic term follows Welford §3.3 formula z = c·r²/(1+√(1−(1+k)c²r²)). "
    "Aspheric polynomial: Σ aᵢ·r^(2i+4) (i=0,1,2,…; r⁴ term first). "
    "NOT IMPLEMENTED: Zernike polynomial surfaces, freeform/XY polynomial surfaces, "
    "Q-polynomial aspheres (Forbes 2007), off-axis conics, tilted/decentred surfaces. "
    "Arrow markers show dz/dr (local slope), not the surface normal direction. "
    "Validity: radicand (1−(1+k)c²r²) must be ≥ 0 at the aperture edge."
)


def compute_sagitta_arrow_chart(
    spec: AsphericSurfaceSpec,
    num_samples: int = 50,
) -> "SagittaArrowChartResult | dict":
    """
    Compute sagitta z(r) for a conic + aspheric optical surface over the clear aperture
    and generate an SVG chart with sagittal arrow markers.

    Parameters
    ----------
    spec : AsphericSurfaceSpec
        Surface specification (R, k, aspheric coefficients, clear aperture radius).
    num_samples : int
        Number of radial sample points (default 50).
        Samples are at r = i · R_aperture / num_samples for i = 0, 1, …, num_samples.

    Returns
    -------
    SagittaArrowChartResult  on success.
    dict {"ok": False, "reason": "..."}  on input error.

    References
    ----------
    Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986, §3.3.
    ISO 10110-12:2019 — Aspheric surface specification.
    """
    # --- Validation ---
    try:
        R = float(spec.radius_mm)
        k = float(spec.conic_k)
        R_ap = float(spec.clear_aperture_radius_mm)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"spec field conversion failed: {exc}"}

    if not math.isfinite(R) or R == 0.0:
        return {"ok": False, "reason": "radius_mm must be a finite non-zero number"}
    if not math.isfinite(k):
        return {"ok": False, "reason": "conic_k must be finite"}
    if not math.isfinite(R_ap) or R_ap <= 0.0:
        return {"ok": False, "reason": "clear_aperture_radius_mm must be > 0"}
    if not isinstance(num_samples, int) or num_samples < 2:
        return {"ok": False, "reason": "num_samples must be an integer >= 2"}

    coeffs: list[float]
    try:
        coeffs = [float(a) for a in spec.aspheric_coeffs]
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"aspheric_coeffs conversion failed: {exc}"}
    for i, a in enumerate(coeffs):
        if not math.isfinite(a):
            return {"ok": False, "reason": f"aspheric_coeffs[{i}] is not finite"}

    c = 1.0 / R

    # Check domain validity at aperture edge
    # Allow a small epsilon (1e-9) for floating-point round-off at the exact domain boundary
    _DOMAIN_EPS = 1e-9
    discriminant_edge = 1.0 - (1.0 + k) * c * c * R_ap * R_ap
    if discriminant_edge < -_DOMAIN_EPS:
        return {
            "ok": False,
            "reason": (
                f"Radicand at aperture edge is negative ({discriminant_edge:.6g}). "
                "The conic surface does not extend to r = clear_aperture_radius_mm. "
                "Reduce clear_aperture_radius_mm or adjust conic_k."
            ),
        }

    # --- Sample z(r) ---
    samples: list[tuple[float, float]] = []
    for i in range(num_samples + 1):
        r = i * R_ap / num_samples
        try:
            z = _sagitta(r, c, k, coeffs)
        except ValueError as exc:
            return {"ok": False, "reason": f"sagitta computation failed at r={r:.4g}: {exc}"}
        samples.append((r, z))

    # --- Key scalar metrics ---
    r_edge, z_edge = samples[-1]
    max_sagitta = z_edge

    # Conic-only at edge
    try:
        z_conic_edge = _conic_sag(r_edge, c, k)
    except ValueError:
        z_conic_edge = float("nan")

    aspheric_contrib = max_sagitta - z_conic_edge if math.isfinite(z_conic_edge) else float("nan")

    # --- Build SVG ---
    z_vals = [z for _, z in samples]
    z_max_chart = max(z_vals) if z_vals else 1.0
    svg = _build_svg(samples, R_ap, z_max_chart, c, k, coeffs)

    return SagittaArrowChartResult(
        sagitta_samples=samples,
        max_sagitta_mm=max_sagitta,
        conic_only_sagitta_mm=z_conic_edge,
        aspheric_contribution_mm=aspheric_contrib,
        svg_chart=svg,
        honest_caveat=_HONEST_CAVEAT,
    )
