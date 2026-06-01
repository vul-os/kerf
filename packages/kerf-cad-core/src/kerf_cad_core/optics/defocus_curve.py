"""
kerf_cad_core.optics.defocus_curve — Through-focus spot-RMS curve.

Public API
----------
compute_defocus_curve(surfaces, field_angle_deg=0.0, defocus_range_mm=0.5,
                      samples=21, aperture_radius_mm=10.0, n_object=1.0,
                      n_rays=51, use_skew_ray=False,
                      spectral_weights=None) -> DefocusCurveResult | dict

Algorithm
---------
For each defocus step Δz in linspace(-defocus_range_mm, +defocus_range_mm, samples):
  1.  Compute paraxial image distance (BFL) from the unperturbed stack.
  2.  The evaluation plane is at BFL + Δz from the last surface.

  MERIDIONAL MODE (use_skew_ray=False, default):
  3.  Trace N uniformly-sampled aperture rays at the given field angle through
      the stack using exact meridional Snell + Newton-Raphson (lens_stack_trace).
  4.  Propagate each ray an additional Δz beyond the nominal paraxial image plane.
  5.  Collect Y intercepts at the shifted plane; compute RMS spot size.
  6.  RMS(Δz) = sqrt(mean((y_i - mean_y)^2)) over surviving rays.

  SKEW-RAY MODE (use_skew_ray=True):
  3.  Sample a 2-D uniform grid of entrance-pupil positions (Nx × Ny rays) at
      (x_p, y_p) with x_p^2 + y_p^2 <= aperture_radius_mm^2.
  4.  Each pupil position becomes a Ray3D with direction cosines encoding both
      field angle (tilted toward +y by field_angle_rad) and aperture height,
      traced via trace_skew_ray through the OpticalSurface sequence built from
      the surface-dict list.
  5.  After the last surface, propagate each ray to the evaluation plane at
      z = z_last_surface + eval_dist, intersect by the parametric formula
      x(t) = x0 + t*dx,  y(t) = y0 + t*dy  where t = (z_eval - z0) / dz.
  6.  2-D RMS = sqrt(mean((x_i - mean_x)^2 + (y_i - mean_y)^2)) — full 3-D
      spot radius capturing both sagittal and tangential contributions.

  SPECTRAL WEIGHTING (spectral_weights != None, only with use_skew_ray=True):
  For each (wavelength_nm, weight) pair, trace the full skew-ray bundle at that
  wavelength (using the given refractive indices, which the caller is responsible
  for setting per wavelength).  Weighted RMS is the weighted sum:
      RMS_spectral(Δz) = sqrt( Σ w_i * RMS_i(Δz)^2 / Σ w_i )
  where the weight w_i is the spectral power density at wavelength_i.
  This gives the polychromatic through-focus RMS correctly weighted by the
  source spectrum (Hecht §6.3; Welford §6.5).

Result
------
  defocus_axis_mm      : list[float] — Δz values (mm), Δz=0 = paraxial best focus
  rms_per_defocus_mm   : list[float] — RMS spot radius at each Δz (mm)
  best_focus_shift_mm  : float       — Δz at which RMS is minimal
  min_rms_mm           : float       — RMS value at best focus
  bfl_mm               : float       — nominal paraxial image distance (mm)
  n_rays_valid         : list[int]   — surviving ray counts per Δz step
  honest_flag          : str         — caveats

Depth bar (Welford 1986 §11.5 / Hecht §6.5)
---------------------------------------------
* Ideal singlet, 0° field:  RMS minimum at Δz ≈ 0; parabolic growth on both sides.
* Aberrated singlet (spherical aberration): marginal rays focus closer to the lens
  than paraxial rays; RMS minimum shifts toward negative Δz (marginal-focus side).
* Field angle > 0°: minimum shifts due to field curvature / astigmatism.
* Chromatic stack: best-focus shift depends on wavelength; use spectral_weights
  to compute the polychromatic through-focus curve, or separate calls per λ.

Honest flags
------------
MERIDIONAL MODE (default):
  Polychromatic defocus curves require per-wavelength tracing weighted by
  spectral power density — use spectral_weights with use_skew_ray=True.
  Astigmatic best-focus splitting (sagittal vs. tangential) requires full
  3-D skew-ray tracing — use use_skew_ray=True.  The reported RMS is the
  meridional (tangential) spot radius only.
SKEW-RAY MODE (use_skew_ray=True):
  Full 3-D spot RMS via trace_skew_ray (Born & Wolf §4.6 / Welford §5).
  Spectral weighting via spectral_weights list[(wavelength_nm, weight)] uses
  per-wavelength bundles weighted by spectral power density (Hecht §6.3).
PARAXIAL IMAGE PLANE REFERENCE:
  Δz is measured from the paraxial BFL, which equals the marginal-ray best
  focus only for a perfect unaberrated system.

References
----------
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, §11.5
    (through-focus MTF and spot-size curves), §5 (skew-ray tracing), §6.5
    (longitudinal chromatic aberration and spectral weighting).
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, §6.3 (chromatic
    aberration and spectral weighting), §6.5 (depth of focus, defocus, and
    the paraxial image plane).
Born, M. & Wolf, E. -- "Principles of Optics", 7th ed., §4.6 (skew-ray
    tracing through conicoid surfaces).

Units: lengths in mm, angles in degrees.
Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Optional

from kerf_cad_core.optics.lens_stack_trace import (
    _conic_sag,
    _meridional_refract,
    _meridional_transfer_full,
    _validate_surface,
    paraxial_properties,
)
from kerf_cad_core.optics.skew_ray_tracer import (
    Ray3D,
    OpticalSurface,
    trace_skew_ray,
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
# 3-D skew-ray bundle helpers
# ---------------------------------------------------------------------------

def _build_optical_surfaces(surfaces: list[dict]) -> tuple:
    """
    Convert a list of surface dicts (c, t, n, k) to OpticalSurface objects.

    The vertex_z_mm of each surface is computed by accumulating the thickness
    values: surface 0 is at z=0, surface j is at z = sum(t[0..j-1]).

    Returns (list[OpticalSurface], z_exit) where z_exit is the z-coordinate
    after the last surface (i.e. after propagating through all thicknesses).
    """
    osurfs = []
    z = 0.0
    for surf in surfaces:
        c = float(surf["c"])
        r = (1.0 / c) if abs(c) > 1e-18 else 0.0
        n_after = float(surf["n"])
        k = float(surf.get("k", 0.0))
        osurfs.append(OpticalSurface(
            vertex_z_mm=z,
            radius_mm=r,
            refractive_index_after=n_after,
            conic_k=k,
        ))
        z += float(surf["t"])
    return osurfs, z   # z is now the z-coordinate of the exit plane (after last surface)


def _sample_pupil_grid(aperture_radius_mm: float, n_rings: int) -> list[tuple[float, float]]:
    """
    Sample a 2-D entrance-pupil grid using a polar grid with *n_rings* rings.

    Returns a list of (x_p, y_p) pupil coordinates inside the aperture circle.
    Includes the on-axis point (0, 0) plus rings at r = k/n_rings * R for k=1..n_rings,
    each with 6*k azimuthal samples.  This gives good angular coverage for skew rays.
    """
    pts: list[tuple[float, float]] = [(0.0, 0.0)]
    R = aperture_radius_mm
    for ring in range(1, n_rings + 1):
        r = R * ring / n_rings
        n_phi = 6 * ring
        for j in range(n_phi):
            phi = 2.0 * math.pi * j / n_phi
            pts.append((r * math.cos(phi), r * math.sin(phi)))
    return pts


def _trace_skew_bundle_at_plane(
    surfaces: list[dict],
    field_angle_rad: float,
    n_object: float,
    aperture_radius_mm: float,
    n_rings: int,
    eval_z: float,        # absolute z-coordinate of the evaluation plane
    wavelength_nm: float = 587.6,
) -> list[tuple[float, float]]:
    """
    Trace a 3-D bundle of skew rays through *surfaces* and collect (x, y)
    intercepts at the evaluation plane z = *eval_z*.

    The ray bundle models an on-axis (or off-axis) point source at infinity:
    each ray starts at a pupil point (x_p, y_p, 0) with direction tilted by
    field_angle_rad in the Y-Z plane.

    For a point source at infinity at field angle θ, rays are collimated with
    direction (0, sin θ, cos θ).  The entrance-pupil point (x_p, y_p) is the
    transverse starting position.

    Returns a list of valid (x, y) intercepts at the evaluation plane.
    """
    # Build OpticalSurface sequence and get z of last surface vertex
    osurfs, z_exit = _build_optical_surfaces(surfaces)

    # Field direction: the chief ray travels at angle field_angle_rad in Y-Z plane
    dx_field = 0.0
    dy_field = math.sin(field_angle_rad)
    dz_field = math.cos(field_angle_rad)

    pts = _sample_pupil_grid(aperture_radius_mm, n_rings)
    intercepts: list[tuple[float, float]] = []

    for xp, yp in pts:
        # Origin: pupil point at z=0 (before first surface)
        ray = Ray3D(
            origin_xyz=(xp, yp, 0.0),
            direction_xyz=(dx_field, dy_field, dz_field),
            wavelength_nm=wavelength_nm,
        )

        result = trace_skew_ray(ray, osurfs, n_before_first=n_object)
        if result.tir_occurred:
            continue

        # Propagate from final position to evaluation plane
        fx, fy, fz = result.final_position_xyz
        fdx, fdy, fdz = result.final_direction_xyz

        if abs(fdz) < 1e-15:
            continue  # ray parallel to evaluation plane

        t = (eval_z - fz) / fdz
        if not math.isfinite(t):
            continue

        xi = fx + t * fdx
        yi = fy + t * fdy

        if math.isfinite(xi) and math.isfinite(yi):
            intercepts.append((xi, yi))

    return intercepts


def _rms_2d(pts: list[tuple[float, float]]) -> float:
    """
    2-D centroid-subtracted RMS spot radius.

    RMS = sqrt( mean( (x_i - mean_x)^2 + (y_i - mean_y)^2 ) )

    This is the standard polychromatic RMS spot radius used in lens design
    (Welford 1986 §11.5; Zemax convention).
    """
    n = len(pts)
    if n < 2:
        return math.nan
    mean_x = sum(p[0] for p in pts) / n
    mean_y = sum(p[1] for p in pts) / n
    variance = sum((p[0] - mean_x) ** 2 + (p[1] - mean_y) ** 2 for p in pts) / n
    return math.sqrt(variance)


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
    rms_per_defocus_mm   : RMS spot radius at each Δz (mm).
    best_focus_shift_mm  : Δz at which RMS is minimal.
    min_rms_mm           : minimum RMS value.
    bfl_mm               : nominal back focal length (paraxial image distance, mm).
    n_rays_valid         : surviving ray count per defocus step.
    honest_flag          : caveats string.
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
    use_skew_ray: bool = False,
    spectral_weights: Optional[list[tuple[float, float]]] = None,
) -> "DefocusCurveResult | dict":
    """
    Compute the through-focus RMS spot-size curve for a lens stack.

    For a uniform aperture bundle at *field_angle_deg*, traces rays at each
    of *samples* defocus positions Δz in [-defocus_range_mm, +defocus_range_mm]
    and reports the RMS spot radius at each shifted evaluation plane.

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
        In meridional mode: N meridional rays. In skew-ray mode: number of
        concentric pupil rings (n_rings = max(3, n_rays // 6)).
    use_skew_ray : bool
        If True, use the 3-D skew-ray tracer (trace_skew_ray) to trace a
        2-D pupil grid, computing the full 2-D RMS spot including sagittal
        and tangential contributions.  If False (default), use the meridional
        ray tracer (faster but tangential-only).
    spectral_weights : list[tuple[float, float]] or None
        Optional list of (wavelength_nm, weight) pairs for polychromatic
        defocus computation.  Only effective when use_skew_ray=True.
        Each entry traces a separate skew-ray bundle at the given wavelength
        (using the surface refractive indices as-is — the caller must supply
        wavelength-specific n values if chromatic aberration is relevant).
        Weighted RMS:  sqrt( Σ w_i * RMS_i^2 / Σ w_i ).
        Default: None (monochromatic, d-line 587.6 nm).

    Returns
    -------
    DefocusCurveResult  on success (has .to_dict() for serialisation).
    dict {"ok": False, "reason": "..."}  on input error.

    References
    ----------
    Welford (1986) §11.5 — through-focus MTF and geometric spot-size curves.
    Welford (1986) §5    — skew-ray tracing through conicoid surfaces.
    Welford (1986) §6.5  — longitudinal chromatic aberration; spectral weighting.
    Hecht (2017) §6.3    — chromatic aberration and spectral power density.
    Hecht (2017) §6.5    — defocus, depth of focus, and the paraxial image plane.
    Born & Wolf (1999) §4.6 — 3-D skew-ray tracing through conicoid surfaces.
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

    if spectral_weights is not None:
        if not use_skew_ray:
            return _err("spectral_weights requires use_skew_ray=True")
        if not isinstance(spectral_weights, (list, tuple)) or len(spectral_weights) == 0:
            return _err("spectral_weights must be a non-empty list of (wavelength_nm, weight) pairs")
        for i, sw in enumerate(spectral_weights):
            if not (hasattr(sw, '__len__') and len(sw) == 2):
                return _err(f"spectral_weights[{i}] must be a (wavelength_nm, weight) pair")
            wl, wt = float(sw[0]), float(sw[1])
            if wl <= 0.0:
                return _err(f"spectral_weights[{i}] wavelength_nm must be > 0")
            if wt < 0.0:
                return _err(f"spectral_weights[{i}] weight must be >= 0")

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

    rms_list: list[float] = []
    n_valid_list: list[int] = []

    if use_skew_ray:
        # --- 3-D skew-ray mode ---
        # Determine number of pupil rings from n_rays
        n_rings = max(3, N // 6)

        # Compute the z-coordinate of the last surface vertex (needed for eval_z)
        z_last = sum(float(s["t"]) for s in surfaces)
        # eval_z = z_last + eval_dist where eval_dist = bfl + dz
        # Note: bfl is already the distance from the last surface to the paraxial image

        if spectral_weights is not None:
            # Normalise weights
            sw_list = [(float(wl), float(wt)) for wl, wt in spectral_weights]
            total_weight = sum(wt for _, wt in sw_list)
            if total_weight <= 0.0:
                return _err("spectral_weights: total weight must be > 0")
        else:
            sw_list = [(587.6, 1.0)]
            total_weight = 1.0

        for dz in defocus_axis:
            eval_dist = bfl + dz      # distance from last surface to eval plane
            eval_z = z_last + eval_dist  # absolute z of evaluation plane

            if spectral_weights is not None:
                # Polychromatic: weighted-RMS combination
                weighted_rms2_sum = 0.0
                w_sum = 0.0
                n_valid = 0
                for wl_nm, wt in sw_list:
                    if wt <= 0.0:
                        continue
                    pts = _trace_skew_bundle_at_plane(
                        surfaces, field_rad, float(n_object), R, n_rings,
                        eval_z, wavelength_nm=wl_nm,
                    )
                    rms_i = _rms_2d(pts)
                    if math.isfinite(rms_i):
                        weighted_rms2_sum += wt * rms_i * rms_i
                        w_sum += wt
                        n_valid = max(n_valid, len(pts))
                n_valid_list.append(n_valid)
                if w_sum > 0.0:
                    rms_list.append(math.sqrt(weighted_rms2_sum / w_sum))
                else:
                    rms_list.append(math.nan)
            else:
                # Monochromatic skew-ray
                pts = _trace_skew_bundle_at_plane(
                    surfaces, field_rad, float(n_object), R, n_rings,
                    eval_z, wavelength_nm=587.6,
                )
                n_valid_list.append(len(pts))
                rms_list.append(_rms_2d(pts))

    else:
        # --- Meridional mode (original) ---
        ray_heights = [
            -R + k * (2.0 * R / (N - 1)) for k in range(N)
        ]

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

    # Build honest_flag based on mode
    if use_skew_ray and spectral_weights is not None:
        flag = (
            "SKEW-RAY + SPECTRAL MODE: 3-D skew-ray bundle via trace_skew_ray "
            "(Born & Wolf §4.6 / Welford §5). Full 2-D RMS spot radius "
            "(sagittal + tangential contributions). "
            "Polychromatic: weighted RMS over "
            f"{len(spectral_weights)} spectral band(s) by spectral power density "
            "(Hecht §6.3 / Welford §6.5). "
            "Δz=0 is the paraxial BFL; for aberrated systems the RMS minimum may "
            "lie at Δz≠0 (spherical aberration, field curvature, chromatic shift)."
        )
    elif use_skew_ray:
        flag = (
            "SKEW-RAY MODE: 3-D skew-ray bundle via trace_skew_ray "
            "(Born & Wolf §4.6 / Welford §5). Full 2-D RMS spot radius "
            "(sagittal + tangential contributions). "
            "MONOCHROMATIC (d-line 587.6 nm). "
            "For polychromatic defocus use spectral_weights parameter. "
            "Δz=0 is the paraxial BFL; for aberrated systems the RMS minimum may "
            "lie at Δz≠0 (spherical aberration, field curvature)."
        )
    else:
        flag = (
            "MONOCHROMATIC ONLY: polychromatic defocus curves require per-wavelength "
            "traces weighted by spectral power density — use use_skew_ray=True "
            "with spectral_weights. "
            "MERIDIONAL ONLY: sagittal/astigmatic focus splitting requires full "
            "3-D skew-ray trace — use use_skew_ray=True. "
            "Δz=0 is the paraxial BFL; for aberrated systems the RMS minimum may "
            "lie at Δz≠0 (spherical aberration, field curvature)."
        )

    return DefocusCurveResult(
        defocus_axis_mm=defocus_axis,
        rms_per_defocus_mm=rms_list,
        best_focus_shift_mm=defocus_axis[best_idx],
        min_rms_mm=best_rms,
        bfl_mm=bfl,
        n_rays_valid=n_valid_list,
        honest_flag=flag,
    )
