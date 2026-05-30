"""
kerf_cad_core.optics.relative_illum_map — 2-D relative illumination (RI) map
across the image plane for a sequential lens stack.

Public API
----------
compute_relative_illum_map(
    surfaces, image_grid_size=33, sensor_half_height_mm=15,
    aperture_radius_mm=10, clear_apertures_mm=None,
    n_marginal_rays=8, n_object=1.0
) -> RelIllumMapReport

Theory (Welford 1986 §4.5 / Hecht §6.6 / Slyusarev §3.4)
-----------------------------------------------------------
For an ideal optical system the natural photometric fall-off of illumination
across the image plane follows the cos⁴(θ) law:

    E(θ) / E(0)  =  cos⁴(θ)                             [Hecht §6.6 eq. 6.68]

where θ is the half-field angle subtended at the entrance pupil by the image
point at height h on the sensor:

    θ = arctan(h / f)   (for object at infinity, f = EFL)

Four factors each contribute one power of cos(θ): projected area of lens
stop (×cos θ), obliquity factor of solid angle (×cos θ), image-plane tilt
(×cos θ), and image-irradiance / luminance conversion (×cos θ).  Slyusarev
§3.4 derives the same result via étendue conservation.

For a real system with physical aperture clipping, the marginal-ray bundle
is truncated at one or more lens rims, making the effective pupil area
smaller for off-axis field angles.  The RI then drops *below* the cos⁴
baseline, especially at large field angles (Welford 1986 §4.5).

For wide-angle lenses (θ_max > 50°): the cos⁴ law predicts RI ≈ 16% at the
extreme corner for a sensor subtending 2×θ_max.  Physical clipping
typically reduces this further; a practical wide-angle lens shows RI in the
range 30–50% at the image corner.

Algorithm
---------
1.  For each image-plane sample point (x_s, y_s) on a symmetric grid
    [-sensor_half_height_mm, +sensor_half_height_mm]^2, compute the
    corresponding field angle:

        θ(x_s, y_s) = arctan(r_s / EFL)
        r_s = sqrt(x_s^2 + y_s^2)

    For a rotationally-symmetric stack (honest flag) the azimuth of (x_s, y_s)
    does not affect RI, so RI depends only on r_s.  The full 2-D map is
    obtained by evaluating RI at each (x_s, y_s) independently, exploiting
    rotational symmetry internally but returning the complete 2-D grid so the
    caller can use the map for visualisation or reflection.

2.  At each grid point, call compute_vignetting with a single field angle
    equal to θ(x_s, y_s).  This traces n_marginal_rays around the pupil
    rim and returns the surviving fraction = RI.

3.  The result is a (image_grid_size × image_grid_size) 2-D list of RI
    values in [0, 1], plus ancillary data.

Rotational-symmetry shortcut
-----------------------------
Because RI depends only on radial field angle θ(r_s), the implementation
pre-computes RI on a 1-D radial grid and maps it back to 2-D, which keeps
runtime manageable for large grid sizes.

HONEST FLAG / SCOPE
-------------------
  * Monochromatic only (polychromatic vignetting from chromatic pupil walk
    is out of scope — see compute_vignetting honest flag).
  * Assumes a rotationally-symmetric stack.  Anamorphic / off-axis stops
    produce non-circular RI maps that this implementation cannot model.
  * EFL is derived from a paraxial marginal trace (h=1, u=0 → image
    distance = BFL ≈ EFL for distant objects).  For near objects the field
    angle must be supplied as an external override.
  * Sagittal-ray component is projected onto the meridional plane (inherited
    from compute_vignetting).
  * Sensor acceptance tilt (field-lens / telecentricity) is not modelled.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §4.5 (vignetting apertures and relative illumination).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017,
    §6.6 (illumination fall-off, cos⁴ law).
Slyusarev, G.G. -- "Aberration and Optical Design Theory", Hilger, 1984,
    §3.4 (irradiance distribution, étendue, vignetting).

Units: lengths in mm, angles in radians internally / degrees at API boundary.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from kerf_cad_core.optics.chief_ray_vignetting import compute_vignetting
from kerf_cad_core.optics.lens_stack_trace import (
    _validate_surface,
    paraxial_properties,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _guard(name: str, value: Any, *, positive: bool = False) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if not math.isfinite(v):
        return f"{name} must be finite"
    if positive and v <= 0.0:
        return f"{name} must be > 0, got {v}"
    return None


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class RelIllumMapReport:
    """
    2-D relative illumination map across the image plane.

    Attributes
    ----------
    ri_map : list[list[float]]
        (image_grid_size × image_grid_size) grid of RI values in [0, 1].
        Row 0 is the top (y = +sensor_half_height_mm), row[-1] is the bottom.
        Column 0 is the left (x = -sensor_half_height_mm).
        With no clear_apertures_mm (all surfaces infinite): ri_map = all 1.0
        (no physical aperture clipping).  Physical clipping requires finite CAs.
    cos4_map : list[list[float]]
        Ideal cos⁴(θ) baseline RI map — the natural photometric fall-off
        (Hecht §6.6): 1.0 at centre, ≤ 1.0 everywhere else.
    image_extent : float
        Half-side of the sensor square (mm), same as sensor_half_height_mm.
    max_field_angle : float
        Field angle (degrees) at the sensor corner = arctan(sqrt(2)*extent/EFL).
    efl_mm : float
        Effective focal length used to map sensor position → field angle (mm).
    image_grid_size : int
        Number of grid points per side.
    aperture_radius_mm : float
        Entrance-pupil half-diameter used for the trace (mm).
    corner_ri : float
        RI at the image corner (worst case, from aperture clipping model).
    corner_cos4 : float
        cos⁴ baseline at the image corner.
    honest_flag : str
        Scope disclaimer (monochromatic; rotationally symmetric; etc.).

    References
    ----------
    Welford 1986 §4.5; Hecht §6.6; Slyusarev §3.4.
    """
    ri_map: list[list[float]]
    cos4_map: list[list[float]]
    image_extent: float
    max_field_angle: float
    efl_mm: float
    image_grid_size: int
    aperture_radius_mm: float
    corner_ri: float
    corner_cos4: float
    honest_flag: str = (
        "SCOPE: monochromatic; rotationally-symmetric stack assumed "
        "(map is azimuthally symmetric — full 2-D output is for visualisation). "
        "ri_map models physical aperture clipping only; without clear_apertures_mm "
        "all ri values = 1.0 (no physical blocking). "
        "cos4_map always shows the natural cos⁴(θ) photometric baseline. "
        "Polychromatic vignetting, anamorphic stops, field-lens telecentricity: "
        "NOT modelled. "
        "Ref: Welford 1986 §4.5; Hecht §6.6; Slyusarev §3.4."
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "ri_map": self.ri_map,
            "cos4_map": self.cos4_map,
            "image_extent": self.image_extent,
            "max_field_angle": self.max_field_angle,
            "efl_mm": self.efl_mm,
            "image_grid_size": self.image_grid_size,
            "aperture_radius_mm": self.aperture_radius_mm,
            "corner_ri": self.corner_ri,
            "corner_cos4": self.corner_cos4,
            "honest_flag": self.honest_flag,
        }


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def compute_relative_illum_map(
    surfaces: list[dict],
    image_grid_size: int = 33,
    sensor_half_height_mm: float = 15.0,
    aperture_radius_mm: float = 10.0,
    clear_apertures_mm: list[float] | None = None,
    n_marginal_rays: int = 8,
    n_object: float = 1.0,
) -> "RelIllumMapReport | dict":
    """
    Compute a 2-D relative illumination (RI) map across the image plane.

    For each grid point (x_s, y_s) on the sensor, compute the field angle
    θ = arctan(r_s / EFL) and evaluate RI(θ) via marginal-ray clipping.
    Returns a (image_grid_size × image_grid_size) RI heatmap.

    The ri_map reflects PHYSICAL APERTURE CLIPPING only:
      - Without clear_apertures_mm: ri_map = all 1.0 (no physical blocking).
      - With finite clear_apertures_mm: ri_map < 1.0 where rays are blocked.
    The cos4_map always reflects the natural cos⁴(θ) photometric baseline
    (Hecht §6.6): illumination fall-off independent of aperture clipping.

    Theory: Welford 1986 §4.5 + Hecht §6.6 + Slyusarev §3.4.

    Parameters
    ----------
    surfaces : list[dict]
        Sequential lens surfaces.  Each dict: c (mm^-1), t (mm), n (>=1.0).
    image_grid_size : int
        Number of grid points per side.  Default 33 (odd → exact centre sample).
        Minimum 3.
    sensor_half_height_mm : float
        Half-side of the sensor square (mm).  Defines the image extent.
        Default 15 mm (30 mm diagonal ≈ full-frame).
    aperture_radius_mm : float
        Entrance-pupil half-diameter (mm).  Default 10 mm.
    clear_apertures_mm : list[float] | None
        Per-surface clear aperture radii (mm).  If None, all surfaces are
        treated as infinite (no physical clipping — ri_map = all 1.0).
    n_marginal_rays : int
        Marginal rays sampled per field angle.  Default 8, minimum 4.
    n_object : float
        Refractive index of object space.  Default 1.0 (air).

    Returns
    -------
    RelIllumMapReport
        Dataclass with ri_map, cos4_map, image_extent, max_field_angle, efl_mm,
        corner_ri, corner_cos4.
    dict {"ok": False, "reason": ...}
        On any validation error.

    References
    ----------
    Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §4.5.
    Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §6.6.
    Slyusarev, G.G. -- "Aberration and Optical Design Theory", Hilger, 1984, §3.4.
    """
    # ---- Validate surfaces --------------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")
    for idx, s in enumerate(surfaces):
        e = _validate_surface(s, idx)
        if e:
            return _err(e)

    # ---- Validate scalar params ---------------------------------------------
    for nm, val in [("sensor_half_height_mm", sensor_half_height_mm),
                    ("aperture_radius_mm", aperture_radius_mm),
                    ("n_object", n_object)]:
        e = _guard(nm, val, positive=True)
        if e:
            return _err(e)

    if not isinstance(image_grid_size, int) or image_grid_size < 3:
        return _err("image_grid_size must be an integer >= 3")
    if n_marginal_rays < 4:
        return _err("n_marginal_rays must be >= 4")

    # ---- Derive EFL via paraxial marginal trace ------------------------------
    props = paraxial_properties(surfaces, n_object=n_object)
    if not props.get("ok"):
        return _err(f"paraxial_properties failed: {props.get('reason')}")
    efl_mm = float(props["EFL_mm"])
    if not math.isfinite(efl_mm) or efl_mm <= 0.0:
        # Fallback: use BFL if EFL is infinite (afocal or zero-power system)
        bfl = float(props.get("BFL_mm", 50.0))
        efl_mm = abs(bfl) if math.isfinite(bfl) and bfl != 0.0 else 50.0

    sensor_half_height_mm = float(sensor_half_height_mm)
    aperture_radius_mm = float(aperture_radius_mm)

    # ---- Build 1-D radial grid then map to 2-D (rotational symmetry) --------
    # Grid positions along one axis: symmetric around 0
    step = 2.0 * sensor_half_height_mm / (image_grid_size - 1)
    coords = [-sensor_half_height_mm + i * step for i in range(image_grid_size)]

    # Pre-compute unique radial distances (rounded to avoid float duplicates)
    _PREC = 9  # decimal places for deduplication
    unique_r: set[float] = set()
    for xi in coords:
        for yi in coords:
            r = round(math.sqrt(xi * xi + yi * yi), _PREC)
            unique_r.add(r)

    # Sort radii and compute RI for each via compute_vignetting
    sorted_r = sorted(unique_r)
    # Convert radii → field angles (degrees)
    field_angles_deg = [math.degrees(math.atan2(r, efl_mm)) for r in sorted_r]

    vig_result = compute_vignetting(
        surfaces,
        field_angles_deg,
        aperture_radius_mm=aperture_radius_mm,
        clear_apertures_mm=clear_apertures_mm,
        n_marginal_rays=n_marginal_rays,
        n_object=n_object,
    )
    if isinstance(vig_result, dict):
        return _err(f"compute_vignetting failed: {vig_result.get('reason')}")

    # Build lookup: radial distance → (ri, cos4)
    ri_lookup: dict[float, float] = {}
    cos4_lookup: dict[float, float] = {}
    for r, ri, cos4 in zip(sorted_r, vig_result.relative_illumination,
                           vig_result.cos4_baseline):
        ri_lookup[r] = ri
        cos4_lookup[r] = cos4

    # ---- Assemble 2-D maps --------------------------------------------------
    ri_map: list[list[float]] = []
    cos4_map: list[list[float]] = []
    for yi in coords:
        row_ri: list[float] = []
        row_c4: list[float] = []
        for xi in coords:
            r = round(math.sqrt(xi * xi + yi * yi), _PREC)
            row_ri.append(ri_lookup[r])
            row_c4.append(cos4_lookup[r])
        ri_map.append(row_ri)
        cos4_map.append(row_c4)

    # ---- Sensor corner statistics -------------------------------------------
    # Corner is at (±sensor_half_height_mm, ±sensor_half_height_mm)
    r_corner = round(sensor_half_height_mm * math.sqrt(2.0), _PREC)
    theta_corner_deg = math.degrees(math.atan2(r_corner, efl_mm))
    corner_cos4 = math.cos(math.radians(theta_corner_deg)) ** 4
    # Use bottom-right corner from the map
    corner_ri = ri_map[-1][-1]

    return RelIllumMapReport(
        ri_map=ri_map,
        cos4_map=cos4_map,
        image_extent=sensor_half_height_mm,
        max_field_angle=theta_corner_deg,
        efl_mm=efl_mm,
        image_grid_size=image_grid_size,
        aperture_radius_mm=aperture_radius_mm,
        corner_ri=corner_ri,
        corner_cos4=corner_cos4,
    )
