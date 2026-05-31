"""
kerf_cad_core.optics.spot_diagram — Fan-of-rays spot diagram for sequential lens systems.

Public API
----------
SpotDiagramResult
    Dataclass holding image-plane ray intercepts, RMS spot radius,
    80%-encircled-energy radius, centroid, SVG diagram, and honest caveat.

compute_spot_diagram(lens_system_dict, field_angle_deg, wavelength_nm,
                     num_rays=49) -> SpotDiagramResult | dict
    Trace a grid of rays through a sequential lens system and compute the
    spot diagram at the paraxial image plane.

Algorithm (Hecht "Optics" 5e §6.3 / Welford "Aberrations of Optical Systems" §6)
----------------------------------------------------------------------------------
1.  Parse the lens system: a dict with keys ``surfaces`` (list of surface
    dicts as used by ``lens_stack_trace``) and optionally ``aperture_radius_mm``
    and ``n_object``.

2.  Determine the paraxial image plane (BFL from ``paraxial_properties``).

3.  Generate a uniform rectangular grid of (px, py) normalised pupil samples
    over the unit disk (|p|² ≤ 1), side = ceil(sqrt(num_rays)).  Physical
    ray height at the first surface is py * aperture_radius_mm.

4.  Trace each sample using ``trace_lens_stack`` (exact Snell + Newton-Raphson
    conic intersect, Welford 1986 §5.2-5.3).  The meridional y-intercept at
    the paraxial image plane is the exact trace result; the sagittal x-intercept
    is a first-order estimate (paraxial, Hecht §5.7):
        x_img = -px * aperture_radius_mm * (BFL / EFL)
    to first order; valid when astigmatism is small.

5.  Collect surviving (x, y) intercepts (excluding TIR / NaN rays).

6.  Compute:
      centroid = (mean_x, mean_y) over surviving intercepts
      rms_radius = sqrt(mean((xi - cx)^2 + (yi - cy)^2))   [Welford §8.2]
      encircled_80pct_radius = radius enclosing 80 % of rays, sorted by
          distance from centroid  [Hecht §6.3 energy-in-circle metric]

7.  Render SVG: circle for each intercept, airy-disk circle for reference,
    centroid marker, and scale bar.

RMS spot radius (Welford §8.2)
-------------------------------
    rms = sqrt( (1/N) Σ [(xi - cx)² + (yi - cy)²] )

80%-encircled-energy radius (Hecht §6.3)
-----------------------------------------
    Sort rays by distance from centroid, take the distance of ray #ceil(0.8*N).
    This is the geometric EE80 radius.  For a diffraction-limited Airy pattern
    EE80 ≈ 1.84 × r_Airy (Hecht §10.2); for an aberrated system it is larger.

HONEST LIMITATIONS
------------------
* Monochromatic only — single wavelength (wavelength_nm used for Airy
  reference only; dispersion/chromatic aberration NOT modelled).
* Sagittal (x) intercepts are first-order paraxial estimates.  Full 3-D
  skew-ray tracing is required for rigorous off-axis x.
* Physical aperture clipping (vignetting) is NOT applied.  Use
  ``optics_compute_vignetting`` separately.
* No wavefront OPD analysis; Strehl ratio not computed.
* Stop assumed at first surface (entrance pupil = front surface).

References
----------
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017, §6.3 (spot diagrams,
    encircled energy), §5.7 (pupils), §10.2 (Airy diffraction, EE80).
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986,
    §6 (Seidel aberration field dependence), §8.2 (spot diagrams), §5.2-5.3
    (exact Snell + Newton-Raphson conic intersect).
Smith, W.J. — "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008,
    §3.3 (spot-diagram construction).

Units: lengths in mm, angles in degrees (where noted), wavelengths in nm.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _validate_surface(s: Any, idx: int) -> str | None:
    if not isinstance(s, dict):
        return f"surface[{idx}] must be a dict"
    for fld in ("c", "t", "n"):
        if fld not in s:
            return f"surface[{idx}] missing required field '{fld}'"
        try:
            v = float(s[fld])
        except (TypeError, ValueError):
            return f"surface[{idx}].{fld} must be a number"
        if not math.isfinite(v):
            return f"surface[{idx}].{fld} must be finite"
    if float(s["n"]) < 1.0:
        return f"surface[{idx}].n must be >= 1.0"
    return None


def _pupil_grid(num_rays: int) -> list[tuple[float, float]]:
    """
    Return a uniform Cartesian grid of (px, py) points over the unit disk
    |p|² <= 1.  num_rays is the *target* count; actual may differ slightly
    due to disk clipping.

    Grid side = ceil(sqrt(num_rays)).  Points outside the unit disk are
    excluded.  For num_rays=49, side=7 and the disk captures ~37 points.

    References: Welford 1986 §8.2 (uniform aperture sampling).
    """
    side = max(2, math.ceil(math.sqrt(num_rays)))
    pts: list[tuple[float, float]] = []
    for i in range(side):
        for j in range(side):
            px = -1.0 + 2.0 * i / (side - 1) if side > 1 else 0.0
            py = -1.0 + 2.0 * j / (side - 1) if side > 1 else 0.0
            if px * px + py * py <= 1.0 + 1e-9:
                pts.append((px, py))
    return pts


def _airy_radius_mm(wavelength_nm: float, f_number: float) -> float:
    """
    First dark ring of the Airy diffraction pattern (mm).

        r_Airy = 1.22 * λ * N   (Hecht §10.2, eq. 10.50)

    wavelength_nm : wavelength in nm
    f_number      : F/# = EFL / (2 * aperture_radius_mm)
    """
    lam_mm = wavelength_nm * 1e-6  # nm -> mm
    return 1.22 * lam_mm * f_number


# ---------------------------------------------------------------------------
# SVG renderer
# ---------------------------------------------------------------------------

def _render_svg(
    intercepts: list[tuple[float, float]],
    centroid: tuple[float, float],
    rms_mm: float,
    ee80_mm: float,
    airy_mm: float,
    plot_half_mm: float,
) -> str:
    """
    Render an SVG spot diagram.

    Canvas: 400 × 440 px, with a 380 × 380 px plot area plus a legend row.
    The coordinate system has (0, 0) at the centroid, y-up (flipped to
    SVG screen y-down convention).

    Elements:
        • Blue circles:  ray intercepts
        • Red ring:      RMS radius
        • Green ring:    80 %-encircled-energy radius
        • Dashed ring:   Airy disk radius (diffraction limit reference)
        • Orange dot:    centroid
        • Scale bar:     represents 0.1 * plot_half_mm
    """
    W, H_plot = 400, 380
    margin = 10
    cx_px = W // 2
    cy_px = H_plot // 2 + margin

    # mm → pixels
    if plot_half_mm <= 0.0:
        plot_half_mm = 0.01
    scale = (W // 2 - margin) / plot_half_mm  # px / mm

    def to_px(xmm: float, ymm: float) -> tuple[float, float]:
        """Convert mm (with centroid at origin, y-up) to SVG px."""
        sx = cx_px + xmm * scale
        sy = cy_px - ymm * scale  # flip y for screen
        return round(sx, 2), round(sy, 2)

    def ring_svg(r_mm: float, color: str, dash: str = "", label: str = "") -> str:
        if r_mm <= 0.0 or not math.isfinite(r_mm):
            return ""
        r_px = r_mm * scale
        d_attr = f' stroke-dasharray="{dash}"' if dash else ""
        title = f"<title>{label}</title>" if label else ""
        return (
            f'<circle cx="{cx_px}" cy="{cy_px}" r="{round(r_px, 2)}" '
            f'fill="none" stroke="{color}" stroke-width="1.5"{d_attr}>'
            f"{title}</circle>"
        )

    # Intercept dots
    dot_parts: list[str] = []
    cx_mm, cy_mm = centroid
    for xmm, ymm in intercepts:
        sx, sy = to_px(xmm - cx_mm, ymm - cy_mm)
        dot_parts.append(
            f'<circle cx="{sx}" cy="{sy}" r="1.5" fill="#3b82f6" opacity="0.7"/>'
        )

    dots_svg = "\n  ".join(dot_parts)

    # Rings
    rms_ring = ring_svg(rms_mm, "#ef4444", label="RMS radius")
    ee80_ring = ring_svg(ee80_mm, "#22c55e", label="EE80 radius")
    airy_ring = ring_svg(airy_mm, "#f97316", "4 3", label="Airy disk radius")

    # Centroid marker
    ccx, ccy = to_px(0.0, 0.0)
    centroid_svg = (
        f'<line x1="{ccx - 5}" y1="{ccy}" x2="{ccx + 5}" y2="{ccy}" '
        f'stroke="#f59e0b" stroke-width="1.5"/>'
        f'<line x1="{ccx}" y1="{ccy - 5}" x2="{ccx}" y2="{ccy + 5}" '
        f'stroke="#f59e0b" stroke-width="1.5"/>'
    )

    # Scale bar: 0.1 * plot_half_mm wide
    bar_mm = max(0.01 * plot_half_mm, round(0.1 * plot_half_mm, 4))
    bar_px = bar_mm * scale
    bx1 = margin + 5
    bx2 = bx1 + bar_px
    by = H_plot + margin + 12
    scale_bar_svg = (
        f'<line x1="{round(bx1, 2)}" y1="{by}" x2="{round(bx2, 2)}" y2="{by}" '
        f'stroke="#374151" stroke-width="2"/>'
        f'<text x="{round(bx1, 2)}" y="{by + 14}" font-size="10" fill="#374151">'
        f'{round(bar_mm * 1000, 2)} µm</text>'
    )

    # Legend
    legend_y = H_plot + margin + 30
    legend_svg = (
        f'<rect x="140" y="{legend_y - 8}" width="10" height="10" fill="#3b82f6" opacity="0.7"/>'
        f'<text x="155" y="{legend_y}" font-size="9" fill="#374151">Rays</text>'
        f'<line x1="190" y1="{legend_y - 4}" x2="200" y2="{legend_y - 4}" '
        f'stroke="#ef4444" stroke-width="1.5"/>'
        f'<text x="205" y="{legend_y}" font-size="9" fill="#374151">RMS</text>'
        f'<line x1="240" y1="{legend_y - 4}" x2="250" y2="{legend_y - 4}" '
        f'stroke="#22c55e" stroke-width="1.5"/>'
        f'<text x="255" y="{legend_y}" font-size="9" fill="#374151">EE80</text>'
        f'<line x1="295" y1="{legend_y - 4}" x2="305" y2="{legend_y - 4}" '
        f'stroke="#f97316" stroke-width="1.5" stroke-dasharray="4 3"/>'
        f'<text x="310" y="{legend_y}" font-size="9" fill="#374151">Airy</text>'
    )

    total_h = H_plot + 60
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{W}" height="{total_h}" '
        f'viewBox="0 0 {W} {total_h}">\n'
        f'  <!-- Spot diagram background -->\n'
        f'  <rect width="{W}" height="{total_h}" fill="#f9fafb"/>\n'
        f'  <!-- Plot area -->\n'
        f'  <rect x="{margin}" y="{margin}" width="{W - 2 * margin}" '
        f'height="{H_plot}" fill="white" stroke="#e5e7eb" stroke-width="1"/>\n'
        f'  <!-- Crosshair -->\n'
        f'  <line x1="{cx_px}" y1="{margin}" x2="{cx_px}" y2="{H_plot + margin}" '
        f'stroke="#d1d5db" stroke-width="0.5" stroke-dasharray="3 3"/>\n'
        f'  <line x1="{margin}" y1="{cy_px}" x2="{W - margin}" y2="{cy_px}" '
        f'stroke="#d1d5db" stroke-width="0.5" stroke-dasharray="3 3"/>\n'
        f'  <!-- Intercepts -->\n'
        f'  {dots_svg}\n'
        f'  <!-- RMS ring -->\n'
        f'  {rms_ring}\n'
        f'  <!-- EE80 ring -->\n'
        f'  {ee80_ring}\n'
        f'  <!-- Airy ring -->\n'
        f'  {airy_ring}\n'
        f'  <!-- Centroid -->\n'
        f'  {centroid_svg}\n'
        f'  <!-- Scale bar -->\n'
        f'  {scale_bar_svg}\n'
        f'  <!-- Legend -->\n'
        f'  {legend_svg}\n'
        f'</svg>'
    )
    return svg


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class SpotDiagramResult:
    """
    Spot diagram result for a single (field angle, wavelength) combination.

    Fields
    ------
    image_points_xy : list[tuple[float, float]]
        Ray intercept (x, y) positions at the paraxial image plane (mm).
        y is the exact meridional trace result (Welford 1986 §5.2-5.3);
        x is a first-order sagittal estimate (Hecht §5.7).
    rms_radius_mm : float
        2-D RMS spot radius = sqrt(mean((xi-cx)^2 + (yi-cy)^2)) (mm).
        Includes the first-order sagittal x contribution.
        Welford 1986 §8.2.
    encircled_80pct_radius_mm : float
        Radius from centroid enclosing 80% of surviving rays (mm).
        Geometric EE80; for diffraction-limited Airy EE80 ≈ 1.84 × r_Airy.
        Hecht 5e §6.3 (encircled-energy metric).
    centroid_xy : tuple[float, float]
        Centroid of surviving ray intercepts (x_mean, y_mean) in mm.
    svg_diagram : str
        SVG string of the spot diagram with RMS, EE80, and Airy-disk rings,
        centroid marker, and scale bar.
    honest_caveat : str
        Human-readable statement of scope limitations.

    References
    ----------
    Hecht §6.3; Welford §8.2.
    """

    image_points_xy: list[tuple[float, float]] = field(default_factory=list)
    rms_radius_mm: float = 0.0
    encircled_80pct_radius_mm: float = 0.0
    centroid_xy: tuple[float, float] = (0.0, 0.0)
    svg_diagram: str = ""
    honest_caveat: str = (
        "Monochromatic only (single wavelength; wavelength_nm used for Airy reference "
        "only; chromatic aberration NOT modelled). "
        "Sagittal (x) intercepts are first-order paraxial estimates — rigorous x "
        "requires full 3-D skew-ray tracing (not implemented). "
        "Physical aperture clipping (vignetting) not applied. "
        "encircled_80pct_radius_mm is the geometric EE80 (ray-counting); it is NOT "
        "the diffraction-based encircled-energy radius. "
        "Stop assumed at first surface."
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "image_points_xy": self.image_points_xy,
            "rms_radius_mm": self.rms_radius_mm,
            "encircled_80pct_radius_mm": self.encircled_80pct_radius_mm,
            "centroid_xy": list(self.centroid_xy),
            "svg_diagram": self.svg_diagram,
            "honest_caveat": self.honest_caveat,
            "n_rays": len(self.image_points_xy),
        }


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_spot_diagram(
    lens_system_dict: dict,
    field_angle_deg: float,
    wavelength_nm: float,
    num_rays: int = 49,
) -> "SpotDiagramResult | dict":
    """
    Trace a fan of rays through a sequential lens system and compute the
    spot diagram at the paraxial image plane.

    Parameters
    ----------
    lens_system_dict : dict
        Lens system description.  Required key:
            ``surfaces`` : list of surface dicts, each with:
                c   (float) curvature 1/R (mm^-1); 0 = flat
                t   (float) thickness to next surface (mm); last surface: 0
                n   (float) refractive index AFTER this surface (>= 1.0)
                k   (float, optional) conic constant (default 0 = sphere)
        Optional keys:
            ``aperture_radius_mm`` (float, default 10.0) — entrance-pupil
                half-diameter in mm.
            ``n_object``           (float, default 1.0) — refractive index
                of the object-space medium.
    field_angle_deg : float
        Field angle (degrees).  0 = on-axis.
    wavelength_nm : float
        Wavelength in nm.  Used only for the Airy-disk reference in the SVG
        and honest caveat.  Dispersion (chromatic aberration) is NOT modelled.
        E.g. 550.0 for green light.
    num_rays : int
        Target number of rays to trace (default 49).  A ceil(sqrt(num_rays)) ×
        ceil(sqrt(num_rays)) grid is built and points outside the unit disk are
        excluded; actual traced count may be slightly less.

    Returns
    -------
    SpotDiagramResult on success.
    dict {"ok": False, "reason": ...} on validation error.

    References
    ----------
    Hecht "Optics" 5e §6.3 (spot diagrams, encircled energy, aberration diagnosis).
    Welford "Aberrations of Optical Systems" §6 (Seidel field dependence),
        §8.2 (spot diagram construction), §5.2-5.3 (exact Snell conic trace).
    """
    # Lazy import to avoid circular dependencies and OCC
    from kerf_cad_core.optics.lens_stack_trace import (
        paraxial_properties,
        trace_lens_stack,
    )

    # ---- Validate lens_system_dict -----------------------------------------
    if not isinstance(lens_system_dict, dict):
        return _err("lens_system_dict must be a dict")

    surfaces = lens_system_dict.get("surfaces")
    if surfaces is None:
        return _err("lens_system_dict missing required key 'surfaces'")
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("lens_system_dict.surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    # ---- Validate scalars ---------------------------------------------------
    try:
        field_angle_deg = float(field_angle_deg)
        if not math.isfinite(field_angle_deg):
            return _err("field_angle_deg must be finite")
    except (TypeError, ValueError):
        return _err("field_angle_deg must be a number")

    try:
        wavelength_nm = float(wavelength_nm)
        if not math.isfinite(wavelength_nm) or wavelength_nm <= 0.0:
            return _err("wavelength_nm must be a positive finite number")
    except (TypeError, ValueError):
        return _err("wavelength_nm must be a number")

    try:
        num_rays = int(num_rays)
        if num_rays < 1:
            return _err("num_rays must be >= 1")
    except (TypeError, ValueError):
        return _err("num_rays must be an integer")

    try:
        aperture_radius_mm = float(lens_system_dict.get("aperture_radius_mm", 10.0))
        if aperture_radius_mm <= 0.0 or not math.isfinite(aperture_radius_mm):
            return _err("aperture_radius_mm must be > 0 and finite")
    except (TypeError, ValueError):
        return _err("aperture_radius_mm must be a number")

    try:
        n_object = float(lens_system_dict.get("n_object", 1.0))
        if n_object < 1.0:
            return _err("n_object must be >= 1.0")
    except (TypeError, ValueError):
        return _err("n_object must be a number")

    # ---- Paraxial system properties ----------------------------------------
    props = paraxial_properties(surfaces, n_object=n_object)
    if not props.get("ok"):
        return _err(f"paraxial_properties failed: {props.get('reason')}")

    efl = props["EFL_mm"]
    bfl = props["BFL_mm"]

    # First-order sagittal scale: x_img = -px * R_ap * (BFL / EFL)
    if math.isfinite(efl) and abs(efl) > 1e-12 and math.isfinite(bfl):
        sag_scale = bfl / efl
    else:
        sag_scale = 1.0

    # F/# = EFL / (2 * aperture_radius_mm)
    if math.isfinite(efl) and abs(efl) > 1e-12:
        f_number = abs(efl) / (2.0 * aperture_radius_mm)
    else:
        f_number = float("inf")

    # ---- Pupil grid ---------------------------------------------------------
    field_angle_rad = math.radians(field_angle_deg)
    pupil_pts = _pupil_grid(num_rays)

    # Chief-ray intercept: px=0, py=0 pupil centre
    chief_result = trace_lens_stack(
        surfaces, ray_h=0.0, ray_u=field_angle_rad, n_object=n_object
    )
    if chief_result.get("ok") and not math.isnan(
        chief_result.get("meridional_image_Y_mm", math.nan)
    ):
        chief_y = chief_result["meridional_image_Y_mm"]
    else:
        chief_y = 0.0
    chief_x = 0.0  # sagittal centre

    # ---- Trace all pupil samples -------------------------------------------
    intercepts: list[tuple[float, float]] = []

    for px, py in pupil_pts:
        ray_h = py * aperture_radius_mm
        result = trace_lens_stack(
            surfaces,
            ray_h=ray_h,
            ray_u=field_angle_rad,
            n_object=n_object,
        )
        y_img = (
            result.get("meridional_image_Y_mm", math.nan)
            if result.get("ok")
            else math.nan
        )
        if math.isnan(y_img) or result.get("tir"):
            continue

        # First-order sagittal x (Hecht §5.7)
        x_img = chief_x - px * aperture_radius_mm * sag_scale
        intercepts.append((x_img, y_img))

    if not intercepts:
        return _err(
            "No rays reached the image plane. "
            "Check surfaces, aperture_radius_mm, and field_angle_deg."
        )

    # ---- RMS spot radius (Welford §8.2) ------------------------------------
    cx = sum(p[0] for p in intercepts) / len(intercepts)
    cy = sum(p[1] for p in intercepts) / len(intercepts)
    centroid = (cx, cy)

    sq_dists = [(xi - cx) ** 2 + (yi - cy) ** 2 for xi, yi in intercepts]
    rms_radius = math.sqrt(sum(sq_dists) / len(sq_dists))

    # ---- 80%-encircled-energy radius (Hecht §6.3) --------------------------
    distances = sorted(math.sqrt(d) for d in sq_dists)
    n_80 = max(1, math.ceil(0.80 * len(distances)))
    ee80_radius = distances[min(n_80 - 1, len(distances) - 1)]

    # ---- Airy disk reference (Hecht §10.2, eq. 10.50) ----------------------
    airy_mm = _airy_radius_mm(wavelength_nm, f_number)

    # ---- SVG ----------------------------------------------------------------
    max_dist = max(math.sqrt(d) for d in sq_dists) if sq_dists else 0.0
    plot_half = max(max_dist * 1.3, airy_mm * 1.5, 1e-6)
    svg = _render_svg(intercepts, centroid, rms_radius, ee80_radius, airy_mm, plot_half)

    # ---- Build result -------------------------------------------------------
    result_obj = SpotDiagramResult(
        image_points_xy=intercepts,
        rms_radius_mm=rms_radius,
        encircled_80pct_radius_mm=ee80_radius,
        centroid_xy=centroid,
        svg_diagram=svg,
    )
    return result_obj
