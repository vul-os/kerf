"""
kerf_cad_core.optics.defocus_curve — Through-focus spot-RMS curve.

Public API
----------
compute_defocus_curve(surfaces, field_angle_deg=0.0, defocus_range_mm=0.5,
                      samples=21, aperture_radius_mm=10.0, n_object=1.0,
                      n_rays=51) -> DefocusCurveResult | dict

Algorithm
---------
For each defocus step Δz in linspace(-defocus_range_mm, +defocus_range_mm, samples):
  1.  Compute paraxial image distance (BFL) from the unperturbed stack.
  2.  The evaluation plane is at BFL + Δz from the last surface.
  3.  Trace N uniformly-sampled aperture rays at the given field angle through
      the stack using exact meridional Snell + Newton-Raphson (lens_stack_trace).
  4.  Propagate each ray an additional Δz beyond the nominal paraxial image plane.
  5.  Collect Y intercepts at the shifted plane; compute RMS spot size.
  6.  RMS(Δz) = sqrt(mean(y_i^2)) over surviving rays  [meridional RMS].

Result
------
  defocus_axis_mm      : list[float] — Δz values (mm), Δz=0 = paraxial best focus
  rms_per_defocus_mm   : list[float] — RMS spot radius at each Δz (mm)
  best_focus_shift_mm  : float       — Δz at which RMS is minimal
  min_rms_mm           : float       — RMS value at best focus
  bfl_mm               : float       — nominal paraxial image distance (mm)
  n_rays_valid         : list[int]   — surviving ray counts per Δz step

Depth bar (Welford 1986 §11.5 / Hecht §6.5)
---------------------------------------------
* Ideal singlet, 0° field:  RMS minimum at Δz ≈ 0; parabolic growth on both sides.
* Aberrated singlet (spherical aberration): marginal rays focus closer to the lens
  than paraxial rays; RMS minimum shifts toward negative Δz (marginal-focus side).
* Field angle > 0°: minimum shifts due to field curvature / astigmatism.
* Chromatic stack: best-focus shift depends on wavelength; use separate calls per
  wavelength and overlay curves.

Honest flags
------------
MONOCHROMATIC ONLY.  Polychromatic defocus curves require per-wavelength tracing
  weighted by spectral power density — not implemented.
DEFOCUS ONLY.  Astigmatic best-focus splitting (sagittal vs. tangential) requires
  full 3-D skew-ray tracing — not implemented.  The reported RMS is the meridional
  (tangential) spot radius only.
PARAXIAL IMAGE PLANE REFERENCE.  Δz is measured from the paraxial BFL, which equals
  the marginal-ray best focus only for a perfect unaberrated system.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §11.5
    (through-focus MTF and spot-size curves).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §6.5
    (depth of focus, defocus, and the paraxial image plane).

Units: lengths in mm, angles in degrees.
Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any

from kerf_cad_core.optics.lens_stack_trace import (
    _conic_sag,
    _meridional_refract,
    _meridional_transfer_full,
    _validate_surface,
    paraxial_properties,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"ok": False, "reason": msg}


def _guard(name: str, value: Any, *, positive: bool = False,
           finite: bool = True) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{name} must be a number, got {value!r}"
    if finite and not math.isfinite(v):
        return f"{name} must be finite"
    if positive and v <= 0.0:
        return f"{name} must be > 0, got {v}"
    return None


# ---------------------------------------------------------------------------
# Single-ray meridional trace (returns Y at the *shifted* evaluation plane)
# ---------------------------------------------------------------------------

def _trace_ray_at_plane(
    surfaces: list[dict],
    ray_h: float,
    field_angle_rad: float,
    n_object: float,
    eval_dist: float,      # distance from last surface to evaluation plane (mm)
) -> float | None:
    """
    Trace a single meridional ray from a point source at infinity at
    *field_angle_rad*, entering at height *ray_h*.  Returns the Y intercept
    at the plane that is *eval_dist* mm from the last surface vertex, or None
    on failure.
    """
    L_val = math.cos(field_angle_rad)
    M_val = math.sin(field_angle_rad)
    Y = float(ray_h)
    n_mer = float(n_object)

    for idx, surf in enumerate(surfaces):
        c = float(surf["c"])
        k = float(surf.get("k", 0.0))
        t = float(surf["t"])
        n_prime = float(surf["n"])

        L_prime, M_prime, tir = _meridional_refract(Y, L_val, M_val, n_mer, n_prime, c, k)
        if tir or math.isnan(L_prime):
            return None

        if t == 0.0 or idx == len(surfaces) - 1:
            # Propagate to sag baseline in current surface frame
            if abs(L_prime) > 1e-15:
                z_sag = _conic_sag(Y, c, k)
                if not math.isnan(z_sag):
                    Y_next = Y + (M_prime / L_prime) * (-z_sag)
                else:
                    Y_next = Y
            else:
                Y_next = Y
        else:
            next_surf = surfaces[idx + 1]
            c_next = float(next_surf["c"])
            k_next = float(next_surf.get("k", 0.0))
            Y_next, _ = _meridional_transfer_full(
                Y, L_prime, M_prime, c, k, t, c_next, k_next
            )

        if math.isnan(Y_next):
            return None

        Y = Y_next
        L_val = L_prime
        M_val = M_prime
        n_mer = n_prime

    # Propagate to the evaluation plane (eval_dist from last surface)
    if math.isnan(Y) or abs(L_val) < 1e-15:
        return None
    return Y + (M_val / L_val) * eval_dist


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DefocusCurveResult:
    """
    Through-focus RMS spot-size curve result.

    Attributes
    ----------
    defocus_axis_mm      : Δz values (mm); Δz=0 is the paraxial image plane.
    rms_per_defocus_mm   : meridional RMS spot radius at each Δz (mm).
    best_focus_shift_mm  : Δz at which RMS is minimal.
    min_rms_mm           : minimum RMS value.
    bfl_mm               : nominal back focal length (paraxial image distance, mm).
    n_rays_valid         : surviving ray count per defocus step.
    honest_flag          : caveats string (monochromatic; meridional only).
    """
    defocus_axis_mm: list[float]
    rms_per_defocus_mm: list[float]
    best_focus_shift_mm: float
    min_rms_mm: float
    bfl_mm: float
    n_rays_valid: list[int]
    honest_flag: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = True
        return d


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_defocus_curve(
    surfaces: list[dict],
    field_angle_deg: float = 0.0,
    defocus_range_mm: float = 0.5,
    samples: int = 21,
    aperture_radius_mm: float = 10.0,
    n_object: float = 1.0,
    n_rays: int = 51,
) -> "DefocusCurveResult | dict":
    """
    Compute the through-focus RMS spot-size curve for a lens stack.

    For a uniform aperture bundle at *field_angle_deg*, traces rays at each
    of *samples* defocus positions Δz in [-defocus_range_mm, +defocus_range_mm]
    and reports the meridional RMS spot radius at each shifted evaluation plane.

    Parameters
    ----------
    surfaces : list of surface dicts (c, t, n, optional k).
    field_angle_deg : float
        Field angle from the optical axis (degrees, default 0.0 = on-axis).
    defocus_range_mm : float
        Half-width of the defocus scan (mm, default 0.5 mm). Range is
        [-defocus_range_mm, +defocus_range_mm].
    samples : int
        Number of defocus steps (default 21). Must be >= 3.
    aperture_radius_mm : float
        Entrance-pupil half-diameter (mm, default 10 mm).
    n_object : float
        Refractive index of object space (default 1.0).
    n_rays : int
        Number of rays sampled across the entrance-pupil diameter (default 51).

    Returns
    -------
    DefocusCurveResult  on success (has .to_dict() for serialisation).
    dict {"ok": False, "reason": "..."}  on input error.

    References
    ----------
    Welford (1986) §11.5 — through-focus MTF and geometric spot-size curves.
    Hecht (2017) §6.5    — defocus, depth of focus, and the paraxial image plane.
    """
    # --- Validation ---
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")
    for idx, s in enumerate(surfaces):
        e = _validate_surface(s, idx)
        if e:
            return _err(e)
    for nm, val in [
        ("field_angle_deg", field_angle_deg),
        ("defocus_range_mm", defocus_range_mm),
        ("aperture_radius_mm", aperture_radius_mm),
        ("n_object", n_object),
    ]:
        e = _guard(nm, val, positive=(nm in ("defocus_range_mm", "aperture_radius_mm")))
        if e:
            return _err(e)
    if not isinstance(samples, int) or samples < 3:
        return _err("samples must be an integer >= 3")
    if not isinstance(n_rays, int) or n_rays < 3:
        return _err("n_rays must be an integer >= 3")
    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    # --- Paraxial BFL ---
    props = paraxial_properties(surfaces, n_object=float(n_object))
    if not props.get("ok"):
        return _err(f"paraxial_properties failed: {props.get('reason')}")
    bfl = props["BFL_mm"]
    if not math.isfinite(bfl):
        return _err("paraxial image distance is infinite (afocal system?)")

    field_rad = math.radians(float(field_angle_deg))
    R = float(aperture_radius_mm)
    N = int(n_rays)

    # Defocus axis: linspace(-range, +range, samples)
    dz_step = 2.0 * defocus_range_mm / (samples - 1)
    defocus_axis = [
        -float(defocus_range_mm) + i * dz_step for i in range(samples)
    ]

    # Pre-compute uniform ray heights
    ray_heights = [
        -R + k * (2.0 * R / (N - 1)) for k in range(N)
    ]

    rms_list: list[float] = []
    n_valid_list: list[int] = []

    for dz in defocus_axis:
        eval_dist = bfl + dz  # absolute distance from last surface to eval plane
        intercepts: list[float] = []

        for h in ray_heights:
            y = _trace_ray_at_plane(
                surfaces, h, field_rad, float(n_object), eval_dist
            )
            if y is not None and math.isfinite(y):
                intercepts.append(y)

        n_valid = len(intercepts)
        n_valid_list.append(n_valid)

        if n_valid < 2:
            rms_list.append(math.nan)
            continue

        # Meridional RMS: centroid-subtracted
        mean_y = sum(intercepts) / n_valid
        variance = sum((y - mean_y) ** 2 for y in intercepts) / n_valid
        rms_list.append(math.sqrt(variance))

    # Best-focus: Δz with minimum RMS (ignoring nan)
    best_idx = 0
    best_rms = math.inf
    for i, rms in enumerate(rms_list):
        if math.isfinite(rms) and rms < best_rms:
            best_rms = rms
            best_idx = i

    return DefocusCurveResult(
        defocus_axis_mm=defocus_axis,
        rms_per_defocus_mm=rms_list,
        best_focus_shift_mm=defocus_axis[best_idx],
        min_rms_mm=best_rms,
        bfl_mm=bfl,
        n_rays_valid=n_valid_list,
        honest_flag=(
            "MONOCHROMATIC ONLY: polychromatic defocus curves require per-wavelength "
            "traces weighted by spectral power density (not implemented). "
            "MERIDIONAL ONLY: sagittal/astigmatic focus splitting requires full "
            "3-D skew-ray trace (not implemented). "
            "Δz=0 is the paraxial BFL; for aberrated systems the RMS minimum may "
            "lie at Δz≠0 (spherical aberration, field curvature)."
        ),
    )
