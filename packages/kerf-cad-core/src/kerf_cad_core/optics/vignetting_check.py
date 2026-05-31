"""
kerf_cad_core.optics.vignetting_check — Vignetting fraction at a given field
angle for a sequential lens system specified by per-surface clear-aperture
limits.

Public API
----------
compute_vignetting(spec, field_angle_deg, marginal_ray_at_stop_mm=10.0)
    -> VignettingReport | dict

Theory (Welford "Aberrations of Optical Systems" §3.7 / Hecht §5.7)
---------------------------------------------------------------------
Vignetting occurs when an off-axis ray bundle is partially or fully blocked
by clear-aperture (CA) limits at surfaces other than the aperture stop.  For a
field angle θ, the chief ray is displaced at each surface by:

    h_chief(z) = (z − z_stop) · tan(θ)          (paraxial, object at ∞)

A marginal ray at pupil height y_p (measured from the optical axis at the
entrance-pupil / aperture-stop plane) propagates to height:

    h(z, y_p) = y_p  +  (z − z_stop) · tan(θ)

The maximum pupil height that passes surface j (axial position z_j, CA radius
r_j) is:

    y_max_j = r_j − |h_chief_j|          if h_chief_j ≤ r_j, else 0
    y_min_j = −r_j − h_chief_j           (symmetric lower bound, magnitude |y_min_j|)

The effective half-pupil at the stop that clears surface j is:

    y_eff_j = min(r_j − |h_chief_j|, marginal_ray_at_stop_mm)

The effective entrance-pupil radius is:

    y_eff = min over all surfaces of y_eff_j

In the tangential (meridional) plane this gives a one-sided vignetting factor.
For a circular pupil, the fraction of the pupil area that clears all surfaces
is the intersection of the full disk (radius R = marginal_ray_at_stop_mm) with
a shifted disk of radius r_j at displacement Δ = (z_j − z_stop)·tan(θ).

Effective pupil area (Welford §3.7)
-------------------------------------
The clipped entrance-pupil area is computed as the intersection of the
unvignetted circular pupil (radius R, centred on axis) with the shadow cast by
each surface clear aperture.  The shadow of surface j is a shifted disk:

    disk_j: centre at Δ_j = (z_j − z_stop)·tan(θ) in the tangential direction
            radius R_j = r_j (CA half-diameter)

Because the aperture stop image (the entrance pupil) may be shifted relative to
the surface disk, the surviving pupil at the entrance-pupil plane is:

    Pupil_eff = Disk(R, 0) ∩ Disk(R_0, Δ_0) ∩ Disk(R_1, Δ_1) ∩ …

where Disk(r, d) = {(x,y) : x² + (y−d)² ≤ r²}.

For each surface j we compute the area of intersection of two circles:
  • Circle A: radius R_A = R (aperture stop radius), centred at (0,0)
  • Circle B: radius R_B = r_j (CA radius), centred at (0, Δ_j)

using the exact two-circle intersection area formula (Weisstein, "Circle-Circle
Intersection," MathWorld):

    A = R_A²·arccos((d²+R_A²−R_B²)/(2·d·R_A))
      + R_B²·arccos((d²+R_B²−R_A²)/(2·d·R_B))
      − ½·sqrt((−d+R_A+R_B)(d+R_A−R_B)(d−R_A+R_B)(d+R_A+R_B))

Special cases:
  d ≥ R_A + R_B  → no overlap (area = 0)
  d ≤ |R_A − R_B|→ smaller disk wholly inside larger (area = π·min²)

The effective pupil area is:
    A_eff = A_ij (intersection of stop disk with the most constraining surface)

vignetting_pct = (1 − A_eff / (π·R²)) × 100

The limiting surface is the one producing the smallest intersection area.

HONEST CAVEATS
--------------
  * Paraxial, thin-lens (chief-ray height at surface j = Δ_j = z_j·tan(θ) for
    stop at z=0); no exact ray trace through refracting surfaces.
  * Circular, rotationally-symmetric apertures only.
  * Tangential (meridional) plane chief-ray displacement; sagittal displacement
    of the pupil centroid is zero for a rotationally-symmetric system.
  * Diffraction-induced vignetting (Airy-disk broadening near a hard edge) is
    NOT modelled.
  * Chromatic pupil walk (wavelength-dependent chief-ray angle) is NOT modelled.
  * Stop assumed to coincide with the surface at axial_position_mm = 0 unless
    explicitly set via the reference surface of the spec.

References
----------
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986, §3.7.
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017, §5.7.
Smith, W.J. — "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008, §5.

Units: lengths in mm, angles in degrees at API boundary / radians internally.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _circle_intersection_area(r_a: float, r_b: float, d: float) -> float:
    """
    Area of intersection of two circles.

    Circle A: radius r_a, centred at origin.
    Circle B: radius r_b, centred at distance d from origin (along any axis).

    Uses the exact formula from Weisstein, "Circle-Circle Intersection," MathWorld.

    Parameters
    ----------
    r_a, r_b : float
        Radii of the two circles (mm).  Must be > 0.
    d : float
        Centre-to-centre separation (mm).  Must be >= 0.

    Returns
    -------
    float
        Intersection area (mm²).  Always in [0, π·min(r_a,r_b)²].
    """
    if d < 0.0:
        d = abs(d)  # separation is unsigned

    # Fully separated
    if d >= r_a + r_b:
        return 0.0

    # One circle fully inside the other
    if d <= abs(r_a - r_b):
        return math.pi * min(r_a, r_b) ** 2

    # General overlap — Weisstein exact formula
    cos_alpha = (d * d + r_a * r_a - r_b * r_b) / (2.0 * d * r_a)
    cos_beta = (d * d + r_b * r_b - r_a * r_a) / (2.0 * d * r_b)

    # Clamp for numerical safety
    cos_alpha = max(-1.0, min(1.0, cos_alpha))
    cos_beta = max(-1.0, min(1.0, cos_beta))

    alpha = math.acos(cos_alpha)    # half-angle at centre A
    beta = math.acos(cos_beta)      # half-angle at centre B

    # Kite-area term (triangle formed by the two centres + either intersection point)
    # = ½ · |cross product| — simplified via Heron-ish route:
    # Product of the four bracket terms for the square of the triangle area:
    radicand = (
        (-d + r_a + r_b)
        * (d + r_a - r_b)
        * (d - r_a + r_b)
        * (d + r_a + r_b)
    )
    if radicand < 0.0:
        radicand = 0.0
    kite = 0.5 * math.sqrt(radicand)

    area = r_a * r_a * alpha + r_b * r_b * beta - kite
    return max(0.0, area)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LensClearApertureSpec:
    """
    Specification of clear-aperture limits for a sequential lens system.

    Attributes
    ----------
    surfaces : list[dict]
        Ordered list of surface descriptors.  Each dict must contain:
          clear_aperture_radius_mm : float  — physical rim half-diameter (mm). > 0.
          axial_position_mm        : float  — vertex Z position along optical axis (mm).
                                              The aperture stop is at z = 0 (conventionally).

    Notes
    -----
    A "surface" here represents any physical aperture stop, lens rim, filter,
    or baffle that can clip the ray bundle.  The aperture stop itself should be
    included with axial_position_mm = 0 and clear_aperture_radius_mm equal to
    the pupil half-diameter.

    Example
    -------
    Two-element lens + image plane, stop at front surface::

        spec = LensClearApertureSpec(surfaces=[
            {"clear_aperture_radius_mm": 12.5, "axial_position_mm": 0.0},   # stop / L1 front
            {"clear_aperture_radius_mm": 12.5, "axial_position_mm": 5.0},   # L1 rear
            {"clear_aperture_radius_mm": 10.0, "axial_position_mm": 15.0},  # L2 front
            {"clear_aperture_radius_mm": 10.0, "axial_position_mm": 20.0},  # L2 rear
        ])
    """

    surfaces: list[dict]


@dataclass
class VignettingReport:
    """
    Result of a vignetting check at a single field angle.

    Attributes
    ----------
    field_angle_deg : float
        Input field angle (degrees).
    vignetting_pct : float
        Fraction of entrance-pupil area blocked by clear-aperture limits (%).
        Range [0, 100].  0 = no vignetting; 100 = fully vignetted.
    limiting_surface_idx : int | None
        Index into ``spec.surfaces`` of the surface that causes the most
        vignetting (smallest effective pupil area intersection).  None if the
        system is unvignetted (vignetting_pct == 0).
    effective_pupil_area_pct : float
        Fraction of the unvignetted entrance-pupil area that survives all
        clear-aperture constraints (%).  Range [0, 100].
        effective_pupil_area_pct = 100 − vignetting_pct.
    honest_caveat : str
        Plain-text scope disclaimer documenting algorithm limitations.

    Notes
    -----
    ``vignetting_pct + effective_pupil_area_pct == 100.0`` (within floating-point
    precision).

    References
    ----------
    Welford (1986) §3.7; Hecht (2017) §5.7.
    """

    field_angle_deg: float
    vignetting_pct: float
    limiting_surface_idx: Optional[int]
    effective_pupil_area_pct: float
    honest_caveat: str = field(
        default=(
            "SCOPE: paraxial chief-ray displacement (object at infinity); "
            "circular, rotationally-symmetric clear apertures only; "
            "stop at surface with axial_position_mm=0 or first surface if none. "
            "Diffraction-induced vignetting and chromatic pupil walk: NOT modelled. "
            "Pupil area = two-circle intersection (Weisstein); exact for circular CAs. "
            "Ref: Welford 1986 §3.7; Hecht §5.7."
        )
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "field_angle_deg": self.field_angle_deg,
            "vignetting_pct": self.vignetting_pct,
            "limiting_surface_idx": self.limiting_surface_idx,
            "effective_pupil_area_pct": self.effective_pupil_area_pct,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_vignetting(
    spec: LensClearApertureSpec,
    field_angle_deg: float,
    marginal_ray_at_stop_mm: float = 10.0,
) -> "VignettingReport | dict":
    """
    Compute the vignetting fraction (fraction of pupil light occluded by
    clear-aperture limits) at a given field angle.

    Theory: Welford "Aberrations of Optical Systems" §3.7 + Hecht §5.7.

    Algorithm
    ---------
    1. Accept a ``LensClearApertureSpec`` describing the physical clear-aperture
       radii and axial positions of all surfaces in the system.

    2. Assume the aperture stop is at z = 0 (the first surface with
       axial_position_mm = 0, or the surface with the minimum axial position
       used as a reference).

    3. For each surface j at axial position z_j and CA radius r_j:
       a. Compute the paraxial chief-ray displacement at that surface:
              Δ_j = z_j · tan(θ)
          where θ = field_angle_deg in radians.
       b. Compute the area of intersection of the full entrance-pupil disk
          (radius R = marginal_ray_at_stop_mm, centred at 0) with the CA disk
          (radius r_j, centred at Δ_j).

    4. The effective pupil area is the minimum intersection area across all
       surfaces (most constraining surface wins for each ray bundle).

    5. vignetting_pct = (1 − A_eff / A_full) × 100
       effective_pupil_area_pct = A_eff / A_full × 100

    Parameters
    ----------
    spec : LensClearApertureSpec
        Lens system clear-aperture specification.  Each surface must have:
          ``clear_aperture_radius_mm`` (float, > 0)
          ``axial_position_mm`` (float)
    field_angle_deg : float
        Field angle (degrees).  0 = on-axis.  Must be < 90°.
    marginal_ray_at_stop_mm : float
        Entrance-pupil (aperture-stop) half-diameter (mm).  Default 10.0 mm.
        Must be > 0.  Should be ≤ the CA of the aperture-stop surface.

    Returns
    -------
    VignettingReport
        Per-field vignetting result.
    dict {"ok": False, "reason": ...}
        On any validation error.

    References
    ----------
    Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986, §3.7.
    Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017, §5.7.
    """
    # ---- Validate spec -------------------------------------------------------
    if not isinstance(spec, LensClearApertureSpec):
        return _err("spec must be a LensClearApertureSpec instance")

    surfaces = spec.surfaces
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("spec.surfaces must be a non-empty list")

    for idx, surf in enumerate(surfaces):
        if not isinstance(surf, dict):
            return _err(f"spec.surfaces[{idx}] must be a dict")
        if "clear_aperture_radius_mm" not in surf:
            return _err(
                f"spec.surfaces[{idx}] missing key 'clear_aperture_radius_mm'"
            )
        if "axial_position_mm" not in surf:
            return _err(
                f"spec.surfaces[{idx}] missing key 'axial_position_mm'"
            )
        try:
            ca = float(surf["clear_aperture_radius_mm"])
            z = float(surf["axial_position_mm"])
        except (TypeError, ValueError) as exc:
            return _err(f"spec.surfaces[{idx}] has non-numeric value: {exc}")
        if not math.isfinite(ca) or ca <= 0.0:
            return _err(
                f"spec.surfaces[{idx}].clear_aperture_radius_mm must be finite and > 0"
            )
        if not math.isfinite(z):
            return _err(
                f"spec.surfaces[{idx}].axial_position_mm must be finite"
            )

    # ---- Validate scalar params ----------------------------------------------
    try:
        theta_deg = float(field_angle_deg)
    except (TypeError, ValueError):
        return _err(f"field_angle_deg must be a number, got {field_angle_deg!r}")
    if not math.isfinite(theta_deg):
        return _err("field_angle_deg must be finite")
    if abs(theta_deg) >= 90.0:
        return _err("field_angle_deg must be in (-90, +90) degrees")

    try:
        R = float(marginal_ray_at_stop_mm)
    except (TypeError, ValueError):
        return _err(
            f"marginal_ray_at_stop_mm must be a number, got {marginal_ray_at_stop_mm!r}"
        )
    if not math.isfinite(R) or R <= 0.0:
        return _err("marginal_ray_at_stop_mm must be finite and > 0")

    # ---- Paraxial chief-ray displacement at each surface --------------------
    theta_rad = math.radians(theta_deg)
    tan_theta = math.tan(theta_rad)

    # Unvignetted area (full entrance pupil)
    A_full = math.pi * R * R

    # Per-surface intersection area with the entrance-pupil disk
    areas: list[float] = []
    for surf in surfaces:
        z_j = float(surf["axial_position_mm"])
        r_j = float(surf["clear_aperture_radius_mm"])
        delta_j = z_j * tan_theta          # chief-ray height at surface j (paraxial)
        d_j = abs(delta_j)                 # separation between pupil-disk centre and CA-disk centre
        area_j = _circle_intersection_area(R, r_j, d_j)
        areas.append(area_j)

    # Effective area = minimum intersection area (most restrictive surface)
    min_area = min(areas)
    limiting_idx = int(areas.index(min_area))

    effective_pct = 100.0 * min_area / A_full
    vignetting_pct = 100.0 - effective_pct

    # Clamp to [0, 100] for floating-point safety
    effective_pct = max(0.0, min(100.0, effective_pct))
    vignetting_pct = max(0.0, min(100.0, vignetting_pct))

    # Limiting surface: None if unvignetted (all surfaces clear the full pupil)
    is_unvignetted = all(
        abs(a - A_full) < 1e-9 * A_full for a in areas
    )
    limiting_surface_idx: Optional[int] = None if is_unvignetted else limiting_idx

    return VignettingReport(
        field_angle_deg=theta_deg,
        vignetting_pct=vignetting_pct,
        limiting_surface_idx=limiting_surface_idx,
        effective_pupil_area_pct=effective_pct,
    )
