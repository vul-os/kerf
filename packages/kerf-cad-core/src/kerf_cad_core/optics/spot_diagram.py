"""
kerf_cad_core.optics.spot_diagram — Fan-of-rays spot diagram for sequential lens systems.

Public API
----------
SpotDiagramResult
    Dataclass holding image-plane ray intercepts, RMS spot radius,
    80%-encircled-energy radius, centroid, SVG diagram, and honest caveat.

compute_spot_diagram(lens_system_dict, field_angle_deg, wavelength_nm,
                     num_rays=49, use_skew_ray=False) -> SpotDiagramResult | dict
    Trace a grid of rays through a sequential lens system and compute the
    spot diagram at the paraxial image plane.

    When ``use_skew_ray=False`` (default) the original paraxial-meridional
    path is used for backward compatibility: exact Snell meridional y-intercept
    plus first-order sagittal x estimate (Hecht §5.7).

    When ``use_skew_ray=True`` a full 3-D hexapolar ray bundle is traced via
    ``trace_skew_ray`` (Born & Wolf §4.6 / Welford §5): 8 rings × 6 azimuth
    angles + pupil centre = up to 49 rays.  Both x and y image-plane
    intercepts are rigorous.  This is the preferred path for off-axis
    astigmatism and sagittal coma diagnosis.

Paraxial algorithm (use_skew_ray=False)
----------------------------------------
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

Skew-ray algorithm (use_skew_ray=True)
---------------------------------------
1.  Same lens system parse and paraxial image plane determination as above.

2.  Generate a hexapolar pupil bundle: 1 centre + N_rings × 6 azimuth samples
    (N_rings chosen so total ≈ num_rays).  Physical ray heights:
        hx = px * aperture_radius_mm,  hy = py * aperture_radius_mm.

3.  For each sample build a Ray3D:
        origin = (hx, hy, 0)                   — at the entrance pupil (z=0)
        direction = (−hx·tan_field/R, −hy·tan_field/R + tan_field, 1)
            normalised
    where tan_field = tan(field_angle_deg) and R ≈ aperture_radius_mm.
    This aims each ray from a unit-sphere object point at (0, −tan_field·∞, −∞)
    through the pupil sample.

4.  Build OpticalSurface list from surfaces dict with cumulative vertex_z_mm
    positions (using thickness t to advance the z-coordinate).

5.  Call trace_skew_ray(ray, optical_surfaces, n_before_first=n_object) for
    each sample.  For surviving (non-TIR) rays propagate the final ray to
    z = BFL (the paraxial image plane) to obtain (x_img, y_img).

6.  Collect, compute RMS / EE80 / centroid, render SVG.

Metric computations (both paths)
----------------------------------
    centroid = (mean_x, mean_y) over surviving intercepts
    rms_radius = sqrt(mean((xi - cx)^2 + (yi - cy)^2))   [Welford §8.2]
    encircled_80pct_radius = radius enclosing 80 % of rays, sorted by
        distance from centroid  [Hecht §6.3 energy-in-circle metric]

SVG: circle for each intercept, airy-disk circle for reference,
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
* Paraxial path: sagittal (x) intercepts are first-order estimates (Hecht §5.7);
  use use_skew_ray=True for rigorous x.
* Skew-ray path: conic surfaces only (no higher-order aspheric A4/A6 terms);
  sequential surfaces only; no vignetting clipping.
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
Born, M. & Wolf, E. — "Principles of Optics", 7th ed., 1999, §1.5.3, §4.6.
Kingslake, R. — "Lens Design Fundamentals", Academic Press, 1978, §2.

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
        "Sagittal (x) intercepts: paraxial path uses first-order estimates (Hecht §5.7); "
        "use use_skew_ray=True for rigorous 3-D skew-ray x (Born & Wolf §4.6). "
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
# Hexapolar pupil sampling (for skew-ray path)
# ---------------------------------------------------------------------------

def _hexapolar_pupil(num_rays: int) -> list[tuple[float, float]]:
    """
    Generate a hexapolar pupil grid of (px, py) normalised pupil samples.

    Layout: 1 centre point + N_rings rings of 6*ring_number samples each.
    The number of rings N_rings is chosen so that the total sample count is
    as close to num_rays as possible (1 + 6*(1+2+...+N) = 1 + 3*N*(N+1)).

    For num_rays=49: N_rings=3 gives 1+6+12+18=37 rays (close to 37);
    N_rings=4 gives 1+6+12+18+24=61.  We use N_rings chosen to minimise
    |total - num_rays| with the constraint total >= 7.

    All returned points satisfy px² + py² <= 1.

    References: Goodman "Introduction to Fourier Optics" §3.3 (hexapolar
    sampling); Smith "Modern Optical Engineering" §3.3 (pupil grids).
    """
    # Find N_rings that gives a total count bracketing num_rays
    best_n: int = 1
    best_diff: float = float("inf")
    for n in range(1, 20):
        total = 1 + 3 * n * (n + 1)  # hexapolar count for n rings
        diff = abs(total - num_rays)
        if diff < best_diff:
            best_diff = diff
            best_n = n
        if total >= num_rays:
            break

    pts: list[tuple[float, float]] = [(0.0, 0.0)]  # centre
    for ring in range(1, best_n + 1):
        r = ring / best_n  # normalised radius in [0, 1]
        n_pts = 6 * ring   # points on this ring
        for j in range(n_pts):
            theta = 2.0 * math.pi * j / n_pts
            px = r * math.cos(theta)
            py = r * math.sin(theta)
            pts.append((px, py))
    return pts


# ---------------------------------------------------------------------------
# Convert lens_system_dict surfaces to OpticalSurface list
# ---------------------------------------------------------------------------

def _build_optical_surfaces(
    surfaces: list[dict],
    first_vertex_z: float = 0.0,
) -> list:
    """
    Convert a list of surface dicts (kerf-cad-core format) to a list of
    ``OpticalSurface`` objects for use with ``trace_skew_ray``.

    Each surface dict has:
        c  (float)  curvature 1/R in mm^-1 (0 = flat → R=∞)
        t  (float)  thickness to next surface in mm
        n  (float)  refractive index after this surface
        k  (float, optional)  conic constant (default 0.0)

    The vertex_z of each surface is accumulated from first_vertex_z using
    the thickness values:
        vertex_z[0] = first_vertex_z
        vertex_z[i] = vertex_z[i-1] + surfaces[i-1]["t"]

    Returns a list of OpticalSurface objects.
    """
    from kerf_cad_core.optics.skew_ray_tracer import OpticalSurface

    result = []
    z = first_vertex_z
    for s in surfaces:
        c = float(s["c"])
        radius_mm = (1.0 / c) if abs(c) > 1e-18 else 0.0
        n_after = float(s["n"])
        k = float(s.get("k", 0.0))
        result.append(OpticalSurface(
            vertex_z_mm=z,
            radius_mm=radius_mm,
            refractive_index_after=n_after,
            conic_k=k,
        ))
        z += float(s["t"])
    # z after the loop is the z-coordinate at the exit of the last surface
    # (it equals sum of all thicknesses from first_vertex_z)
    return result, z


# ---------------------------------------------------------------------------
# Skew-ray spot computation
# ---------------------------------------------------------------------------

def _compute_skew_spot(
    surfaces: list[dict],
    field_angle_deg: float,
    wavelength_nm: float,
    aperture_radius_mm: float,
    n_object: float,
    bfl: float,
    num_rays: int,
) -> list[tuple[float, float]]:
    """
    Trace a hexapolar ray bundle through the optical system using the full
    3-D skew-ray engine and collect (x, y) intercepts at the paraxial image
    plane (z = bfl, measured from the last surface vertex).

    Algorithm (Born & Wolf §4.6 / Welford §5 / Smith §3.3):
    --------------------------------------------------------
    1. Build a hexapolar pupil grid of normalised (px, py) samples.

    2. For each sample, construct a Ray3D:
         - Origin:    (hx, hy, 0) where hx = px * R_ap, hy = py * R_ap.
           The entrance pupil is placed at z=0 (first surface vertex).
         - Direction: the ray aims from an infinitely distant object point at
           field angle θ, so the input direction cosines are:
               dx = 0.0          (no x tilt for meridional field)
               dy = sin(θ)
               dz = cos(θ)
           For a skew ray the origin offset (hx, hy) encodes the pupil
           coordinate; the direction is the same for all rays in a field
           (collimated object at infinity approximation).
           Reference: Welford §5.1 (pupil coordinates for infinite-conjugate
           trace); Kingslake §2.2 (ray bundle from infinity).

    3. Trace each Ray3D through the OpticalSurface list.

    4. Propagate the surviving ray's final position + direction to the image
       plane at z_image = z_last_vertex + bfl:
           t_img = (z_image - final_z) / final_dz
           x_img = final_x + t_img * final_dx
           y_img = final_y + t_img * final_dy

    5. Return list of (x_img, y_img) for non-TIR rays.

    References
    ----------
    Born & Wolf, "Principles of Optics", 7th ed., §4.6.
    Welford, "Aberrations of Optical Systems", §5.1-5.3.
    Kingslake, "Lens Design Fundamentals", §2.2.
    """
    from kerf_cad_core.optics.skew_ray_tracer import Ray3D, trace_skew_ray

    optical_surfaces, z_after_last = _build_optical_surfaces(surfaces, first_vertex_z=0.0)
    z_image = z_after_last + bfl  # absolute z of the paraxial image plane

    field_rad = math.radians(field_angle_deg)
    sin_f = math.sin(field_rad)
    cos_f = math.cos(field_rad)

    # Input ray direction: collimated beam from field angle θ (object at ∞)
    # Direction: (dx=0, dy=sin(θ), dz=cos(θ)) — meridional plane tilt.
    # Welford §5.1: for object at infinity, all rays in the bundle have the
    # same direction; pupil sampling is encoded in origin offsets.
    base_dir = (0.0, sin_f, cos_f)

    pupil_pts = _hexapolar_pupil(num_rays)
    intercepts: list[tuple[float, float]] = []

    for px, py in pupil_pts:
        hx = px * aperture_radius_mm
        hy = py * aperture_radius_mm
        try:
            ray = Ray3D(
                origin_xyz=(hx, hy, 0.0),
                direction_xyz=base_dir,
                wavelength_nm=wavelength_nm,
            )
        except ValueError:
            continue  # degenerate direction (should not happen)

        trace_result = trace_skew_ray(ray, optical_surfaces, n_before_first=n_object)

        if trace_result.tir_occurred:
            continue  # TIR — drop this ray

        # Propagate to image plane
        fx, fy, fz = trace_result.final_position_xyz
        ddx, ddy, ddz = trace_result.final_direction_xyz

        if abs(ddz) < 1e-18:
            continue  # ray parallel to image plane — pathological

        t_img = (z_image - fz) / ddz
        if not math.isfinite(t_img):
            continue

        x_img = fx + t_img * ddx
        y_img = fy + t_img * ddy

        if math.isfinite(x_img) and math.isfinite(y_img):
            intercepts.append((x_img, y_img))

    return intercepts


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_spot_diagram(
    lens_system_dict: dict,
    field_angle_deg: float,
    wavelength_nm: float,
    num_rays: int = 49,
    use_skew_ray: bool = False,
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
        Target number of rays to trace (default 49).
        Paraxial path: a ceil(sqrt(num_rays)) × ceil(sqrt(num_rays)) grid is
        built and points outside the unit disk are excluded.
        Skew-ray path: a hexapolar grid with approximately num_rays samples is
        built (1 + 3*N*(N+1) for N rings).
    use_skew_ray : bool
        If False (default), use the original paraxial-meridional path (exact
        meridional y via Snell; first-order sagittal x, Hecht §5.7).
        If True, use the full 3-D skew-ray engine (``trace_skew_ray``,
        Born & Wolf §4.6 / Welford §5) with a hexapolar pupil bundle.
        Skew-ray mode gives rigorous x and y intercepts and is preferred for
        off-axis field analysis (astigmatism, sagittal coma, field curvature).

    Returns
    -------
    SpotDiagramResult on success.
    dict {"ok": False, "reason": ...} on validation error.

    References
    ----------
    Hecht "Optics" 5e §6.3 (spot diagrams, encircled energy, aberration diagnosis).
    Welford "Aberrations of Optical Systems" §6 (Seidel field dependence),
        §8.2 (spot diagram construction), §5.2-5.3 (exact Snell conic trace).
    Born & Wolf "Principles of Optics" 7th ed. §1.5.3, §4.6.
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

    # ---- Trace ray bundle ---------------------------------------------------
    intercepts: list[tuple[float, float]] = []

    if use_skew_ray:
        # Full 3-D skew-ray bundle (Born & Wolf §4.6 / Welford §5).
        # Hexapolar pupil grid; both x and y intercepts are rigorous.
        intercepts = _compute_skew_spot(
            surfaces=surfaces,
            field_angle_deg=field_angle_deg,
            wavelength_nm=wavelength_nm,
            aperture_radius_mm=aperture_radius_mm,
            n_object=n_object,
            bfl=bfl,
            num_rays=num_rays,
        )
    else:
        # Paraxial-meridional path (original algorithm; default for backward
        # compatibility): exact meridional y via Snell; first-order sagittal x
        # estimate (Hecht §5.7).
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
    if use_skew_ray:
        caveat = (
            "Monochromatic only (single wavelength; chromatic aberration NOT modelled). "
            "3-D skew-ray trace (Born & Wolf §4.6 / Welford §5): both x and y "
            "intercepts are rigorous (hexapolar pupil bundle). "
            "Conic surfaces only (no higher-order A4/A6 aspheric terms). "
            "Sequential surfaces only; no non-sequential paths. "
            "Physical aperture clipping (vignetting) not applied. "
            "encircled_80pct_radius_mm is the geometric EE80 (ray-counting); it is NOT "
            "the diffraction-based encircled-energy radius. "
            "Stop assumed at first surface."
        )
        result_obj = SpotDiagramResult(
            image_points_xy=intercepts,
            rms_radius_mm=rms_radius,
            encircled_80pct_radius_mm=ee80_radius,
            centroid_xy=centroid,
            svg_diagram=svg,
            honest_caveat=caveat,
        )
    else:
        result_obj = SpotDiagramResult(
            image_points_xy=intercepts,
            rms_radius_mm=rms_radius,
            encircled_80pct_radius_mm=ee80_radius,
            centroid_xy=centroid,
            svg_diagram=svg,
        )
    return result_obj
