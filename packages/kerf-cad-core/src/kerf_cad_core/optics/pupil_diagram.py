"""
kerf_cad_core.optics.pupil_diagram — spot diagrams and pupil illumination maps
for sequential lens stacks.

Public API
----------
compute_pupil_diagram(surfaces, field_angles_deg, n_rays_per_field=200,
                      aperture_radius_mm=10.0, n_object=1.0) -> PupilDiagramReport
    For each field angle, trace a uniform grid of rays across the entrance
    pupil, collect intercept positions at the paraxial image plane (spot
    diagram), and record which pupil positions survived (exit-pupil
    illumination map).

Theory
------
A *spot diagram* (Welford 1986 §8.2) is the locus of ray intersections at the
image plane for a bundle of rays launched from a single object point.  Each ray
is parameterised by its (px, py) normalised position in the entrance pupil.
For a perfect (stigmatic) system every ray hits the same image point; for an
aberrated system the spread is proportional to the wavefront error.

Pupil filling (Hecht §5.7 stops and pupils):
    The entrance pupil is filled with a uniform rectangular grid of N points
    within the unit disk (|p| <= 1).  The grid coordinates are scaled by
    `aperture_radius_mm` to give physical heights at the first surface.

    Because the tracer is meridional (1-D), the x-component of the pupil
    position is carried as a transverse offset via the field-angle decomposition:
        field_angle_total = arctan(tan(theta_field) + py * aperture / EFL)
    to first order; in practice we project each (px, py) pupil sample onto the
    meridional plane:
        h_meridional = py * aperture_radius_mm
        u_ray        = field_angle_rad  (chief-ray tilt, fixed per field point)
    and record the sagittal offset px as a stored tag only (it cannot be
    independently traced in a meridional-only tracer).  The x-intercept at the
    image plane is therefore estimated from the thin-lens paraxial relation:
        x_img = -px * aperture_radius_mm / EFL * BFL
    (first-order sagittal image; valid only when astigmatism is small).

    This is an HONEST LIMITATION: full 3-D skew-ray tracing is required for a
    rigorous sagittal spot diagram.  The meridional (y) intercept is exact via
    Newton-Raphson; the sagittal (x) intercept is first-order only.

Exit-pupil illumination map:
    A ray that reaches the image plane without TIR or NaN contributes a point
    at its normalised pupil coordinates (px, py).  The surviving set is the
    illuminated region of the exit pupil.  Vignetted rays (blocked at any
    aperture) appear as gaps.  Since the tracer does not model physical aperture
    clipping, all rays of the entrance-pupil grid survive in the absence of TIR;
    the map thus reflects only TIR-blocked and divergent rays.

RMS spot radius (Welford 1986 §8.2):
    rms = sqrt(mean((y_i - y_chief)^2 + (x_i - x_chief)^2))

Seidel cross-check:
    For coma (S_II) the tangential (y-only) RMS grows approximately as
        rms_y ~ S_II * theta (linear in field; Welford 1986 §8.3).
    The ratio rms_y(14deg) / rms_y(0deg) should be >> 1 for a real singlet.
    The full 2-D RMS includes the first-order sagittal (x) contribution which
    is nearly constant across field angles (pupil position mapping); therefore
    the y-only spread is the meaningful aberration diagnostic.

HONEST FLAGS
------------
* Monochromatic only.  Polychromatic spot diagrams require per-wavelength
  tracing weighted by spectral power density and are out of scope.
* Sagittal (x) intercepts are first-order estimates; rigorous x requires
  full 3-D skew-ray tracing (not implemented in this tracer).
* Exit-pupil *position* is estimated from the paraxial rear-nodal distance;
  a proper exit-pupil trace requires tracing the chief ray from image space.
* Physical aperture clipping is not applied here; vignetting should be
  assessed with `chief_ray_vignetting.compute_vignetting`.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986,
    §8.2 (spot diagrams), §8.3 (coma spot shape), §3.5 (exit-pupil position).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017,
    §5.7 (stops and pupils, entrance/exit pupil definitions).
Smith, W.J. -- "Modern Optical Engineering", 4th ed., McGraw-Hill, 2008,
    §3.3 (spot-diagram construction).

Units: lengths in mm, angles in radians (degrees where noted).

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from kerf_cad_core.optics.lens_stack_trace import (
    paraxial_properties,
    trace_lens_stack,
)


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


def _pupil_grid(n_rays: int) -> list[tuple[float, float]]:
    """
    Return a uniform Cartesian grid of (px, py) points filling the unit disk
    |p| <= 1.  n_rays is the *target* total; actual count may differ slightly
    due to disk clipping.

    We use a square grid of side ceil(sqrt(n_rays)) and keep only points with
    px^2 + py^2 <= 1.

    References: Welford 1986 §8.2 (uniform aperture sampling).
    """
    side = max(2, math.ceil(math.sqrt(n_rays)))
    pts: list[tuple[float, float]] = []
    for i in range(side):
        for j in range(side):
            # Map [0, side-1] -> [-1, 1] symmetrically
            px = -1.0 + 2.0 * i / (side - 1) if side > 1 else 0.0
            py = -1.0 + 2.0 * j / (side - 1) if side > 1 else 0.0
            if px * px + py * py <= 1.0 + 1e-9:
                pts.append((px, py))
    return pts


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SpotFieldData:
    """Spot diagram data for a single field angle."""
    field_angle_deg: float
    # List of (x_mm, y_mm) ray intercepts at the paraxial image plane.
    # x is first-order sagittal estimate; y is exact meridional trace.
    intercepts_mm: list[tuple[float, float]] = field(default_factory=list)
    # Chief-ray intercept at image plane (px=0, py=0 pupil centre)
    chief_ray_y_mm: float = 0.0
    chief_ray_x_mm: float = 0.0
    # RMS spot radius (mm) over all surviving rays (2-D, includes sagittal x)
    rms_spot_radius_mm: float = 0.0
    # Meridional (y-only) RMS spot radius (mm) — pure aberration signal
    rms_spot_y_mm: float = 0.0
    # Maximum ray distance from chief ray (mm)
    max_ray_distance_mm: float = 0.0
    # Number of rays successfully traced
    n_rays_traced: int = 0
    # Number of rays that failed (TIR, NaN)
    n_rays_failed: int = 0
    # Surviving pupil coordinates (for exit-pupil illumination map)
    pupil_coords_surviving: list[tuple[float, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "field_angle_deg": self.field_angle_deg,
            "intercepts_mm": self.intercepts_mm,
            "chief_ray_y_mm": self.chief_ray_y_mm,
            "chief_ray_x_mm": self.chief_ray_x_mm,
            "rms_spot_radius_mm": self.rms_spot_radius_mm,
            "rms_spot_y_mm": self.rms_spot_y_mm,
            "max_ray_distance_mm": self.max_ray_distance_mm,
            "n_rays_traced": self.n_rays_traced,
            "n_rays_failed": self.n_rays_failed,
            "pupil_coords_surviving": self.pupil_coords_surviving,
        }


@dataclass
class PupilDiagramReport:
    """
    Result of compute_pupil_diagram.

    References
    ----------
    Welford 1986 §8.2; Hecht §5.7.
    """
    # Per-field spot data
    spots_per_field: list[SpotFieldData] = field(default_factory=list)
    # RMS spot radius per field (mm, 2-D including sagittal), same order as spots_per_field
    rms_spot_size_per_field: list[float] = field(default_factory=list)
    # Meridional (y-only) RMS per field (pure aberration signal)
    rms_spot_y_per_field: list[float] = field(default_factory=list)
    # Estimated exit-pupil position from last surface (mm).
    # Positive = behind last surface (usual case for real lenses).
    # Estimation: exit pupil ~ BFL for an entrance-pupil-at-first-surface system.
    # For rigorous exit-pupil location, trace the chief ray from image space
    # (Welford 1986 §3.5).
    exit_pupil_pos_mm: float = 0.0
    # Aperture radius used (mm)
    aperture_radius_mm: float = 10.0
    # EFL from paraxial properties (mm)
    EFL_mm: float = 0.0
    # Honest-flag string
    honest_flag: str = (
        "Monochromatic only. Sagittal (x) intercepts are first-order estimates "
        "(full 3-D skew-ray tracing required for rigorous x). "
        "rms_spot_radius_mm includes x; rms_spot_y_mm is meridional-only (aberration signal). "
        "Exit-pupil position is a paraxial estimate (chief-ray back-trace not implemented). "
        "Physical aperture clipping not applied; use optics_compute_vignetting for RI."
    )

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "spots_per_field": [s.to_dict() for s in self.spots_per_field],
            "rms_spot_size_per_field": self.rms_spot_size_per_field,
            "rms_spot_y_per_field": self.rms_spot_y_per_field,
            "exit_pupil_pos_mm": self.exit_pupil_pos_mm,
            "aperture_radius_mm": self.aperture_radius_mm,
            "EFL_mm": self.EFL_mm,
            "honest_flag": self.honest_flag,
        }


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute_pupil_diagram(
    surfaces: list[dict],
    field_angles_deg: list[float],
    n_rays_per_field: int = 200,
    aperture_radius_mm: float = 10.0,
    n_object: float = 1.0,
) -> "PupilDiagramReport | dict":
    """
    Compute spot diagrams and pupil illumination maps for a lens stack.

    For each field angle in `field_angles_deg`:
      1.  Build a uniform grid of (px, py) pupil coordinates over the unit disk
          (Welford 1986 §8.2 sampling).
      2.  For each pupil sample, launch a meridional ray:
              ray_h = py * aperture_radius_mm
              ray_u = field_angle_rad
          and trace through the lens stack using `trace_lens_stack` (exact
          Snell + Newton-Raphson conic intersect).
      3.  Collect the meridional image-plane intercept y_img =
          meridional_image_Y_mm from each trace.  Compute the first-order
          sagittal estimate x_img = -px * aperture_radius_mm * BFL / EFL
          (paraxial, valid for near-stigmatic systems; Hecht §5.7).
      4.  Derive:
            chief ray:       px=0, py=0 → chief_ray_y_mm, chief_ray_x_mm=0
            RMS spot (2-D):  sqrt(mean((y-y_chief)^2 + (x-x_chief)^2))
            RMS spot y-only: sqrt(mean((y-y_chief)^2))  — aberration signal
            max distance:    max(|intercept - chief_ray|)
            exit-pupil pos:  BFL (paraxial estimate; Welford 1986 §3.5)

    Parameters
    ----------
    surfaces : list[dict]
        Ordered surface list with c (mm^-1), t (mm), n (>=1.0), optional k.
    field_angles_deg : list[float]
        Field angles in degrees.  0 = on-axis.
    n_rays_per_field : int
        Target number of rays per field.  Actual count may differ slightly
        because grid points outside the unit disk are excluded.  Default 200.
    aperture_radius_mm : float
        Entrance-pupil half-diameter (mm).  Default 10 mm.
    n_object : float
        Refractive index of object space.  Default 1.0 (air).

    Returns
    -------
    PupilDiagramReport or dict
        dict on validation error: {"ok": False, "reason": ...}
        PupilDiagramReport on success.

    References
    ----------
    Welford 1986 §8.2 (spot diagrams), §8.3 (coma spot shape), §3.5 (pupils).
    Hecht §5.7 (stops and pupils; entrance/exit pupil definitions).
    """
    # --- Validate surfaces ---------------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")
    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    # --- Validate other inputs -----------------------------------------------
    if not isinstance(field_angles_deg, (list, tuple)) or len(field_angles_deg) == 0:
        return _err("field_angles_deg must be a non-empty list")
    try:
        angles_rad = [math.radians(float(a)) for a in field_angles_deg]
    except (TypeError, ValueError) as exc:
        return _err(f"field_angles_deg: {exc}")

    try:
        n_rays_per_field = int(n_rays_per_field)
        if n_rays_per_field < 1:
            return _err("n_rays_per_field must be >= 1")
    except (TypeError, ValueError):
        return _err("n_rays_per_field must be an integer")

    try:
        aperture_radius_mm = float(aperture_radius_mm)
        if aperture_radius_mm <= 0.0 or not math.isfinite(aperture_radius_mm):
            return _err("aperture_radius_mm must be > 0 and finite")
    except (TypeError, ValueError):
        return _err("aperture_radius_mm must be a number")

    try:
        n_object = float(n_object)
        if n_object < 1.0:
            return _err("n_object must be >= 1.0")
    except (TypeError, ValueError):
        return _err("n_object must be a number")

    # --- Paraxial system properties ------------------------------------------
    props = paraxial_properties(surfaces, n_object=n_object)
    if not props.get("ok"):
        return _err(f"paraxial_properties failed: {props.get('reason')}")

    efl = props["EFL_mm"]
    bfl = props["BFL_mm"]

    # Exit-pupil position estimate (paraxial, entrance pupil at first surface):
    # For a system with stop at front surface, exit pupil is conjugate to
    # entrance pupil via the system matrix.  A simple estimate is the rear
    # nodal-plane position ≈ BFL - EFL (for a thin lens this is ~0 at infinity
    # focus).  We report BFL as the distance from last surface to the image
    # plane, which is also a reasonable proxy for exit-pupil distance when the
    # stop is at the entrance (Welford 1986 §3.5).
    exit_pupil_pos_mm = bfl

    # First-order sagittal scale: x_img = -px * R_ap * (BFL / EFL)
    # This is the thin-lens paraxial imaging of the pupil x-offset onto the
    # image plane (image-space chief ray transverse magnification).
    if math.isfinite(efl) and abs(efl) > 1e-12 and math.isfinite(bfl):
        sag_scale = bfl / efl
    else:
        sag_scale = 1.0

    # --- Pupil grid ----------------------------------------------------------
    pupil_pts = _pupil_grid(n_rays_per_field)

    # --- Per-field trace -----------------------------------------------------
    spots_per_field: list[SpotFieldData] = []
    rms_list: list[float] = []
    rms_y_list: list[float] = []

    for angle_rad in angles_rad:
        angle_deg = math.degrees(angle_rad)
        sfd = SpotFieldData(field_angle_deg=angle_deg)

        # Chief-ray trace: px=0, py=0
        chief_result = trace_lens_stack(
            surfaces,
            ray_h=0.0,
            ray_u=angle_rad,
            n_object=n_object,
        )
        if chief_result.get("ok") and not math.isnan(
            chief_result.get("meridional_image_Y_mm", math.nan)
        ):
            sfd.chief_ray_y_mm = chief_result["meridional_image_Y_mm"]
        else:
            sfd.chief_ray_y_mm = 0.0
        sfd.chief_ray_x_mm = 0.0  # on-axis in sagittal plane for centre pupil

        intercepts: list[tuple[float, float]] = []
        surviving_pupils: list[tuple[float, float]] = []
        failed = 0

        for px, py in pupil_pts:
            ray_h = py * aperture_radius_mm
            result = trace_lens_stack(
                surfaces,
                ray_h=ray_h,
                ray_u=angle_rad,
                n_object=n_object,
            )
            y_img = result.get("meridional_image_Y_mm", math.nan) if result.get("ok") else math.nan

            if math.isnan(y_img) or result.get("tir"):
                failed += 1
                continue

            # First-order sagittal intercept (Hecht §5.7, paraxial estimate)
            x_img = -px * aperture_radius_mm * sag_scale + sfd.chief_ray_x_mm

            intercepts.append((x_img, y_img))
            surviving_pupils.append((px, py))

        sfd.intercepts_mm = intercepts
        sfd.pupil_coords_surviving = surviving_pupils
        sfd.n_rays_traced = len(intercepts)
        sfd.n_rays_failed = failed

        # RMS spot radius (Welford 1986 §8.2) and max distance from chief ray
        if intercepts:
            cx, cy = sfd.chief_ray_x_mm, sfd.chief_ray_y_mm
            sq_dists = [
                (xi - cx) ** 2 + (yi - cy) ** 2
                for xi, yi in intercepts
            ]
            sq_dists_y = [(yi - cy) ** 2 for _, yi in intercepts]
            sfd.rms_spot_radius_mm = math.sqrt(sum(sq_dists) / len(sq_dists))
            sfd.rms_spot_y_mm = math.sqrt(sum(sq_dists_y) / len(sq_dists_y))
            sfd.max_ray_distance_mm = math.sqrt(max(sq_dists))
        else:
            sfd.rms_spot_radius_mm = 0.0
            sfd.rms_spot_y_mm = 0.0
            sfd.max_ray_distance_mm = 0.0

        spots_per_field.append(sfd)
        rms_list.append(sfd.rms_spot_radius_mm)
        rms_y_list.append(sfd.rms_spot_y_mm)

    return PupilDiagramReport(
        spots_per_field=spots_per_field,
        rms_spot_size_per_field=rms_list,
        rms_spot_y_per_field=rms_y_list,
        exit_pupil_pos_mm=exit_pupil_pos_mm,
        aperture_radius_mm=aperture_radius_mm,
        EFL_mm=efl,
    )
