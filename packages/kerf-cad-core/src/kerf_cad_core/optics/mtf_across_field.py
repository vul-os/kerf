"""
kerf_cad_core.optics.mtf_across_field — Modulation Transfer Function as a
function of field angle (off-axis position).

Public API
----------
mtf_at_field(surfaces, field_angle_deg, samples_per_aperture=50, aperture_radius_mm=None)
    Trace a uniform aperture bundle at a given field angle from a point source
    at infinity through the lens stack; histogram ray-intercept positions at
    the paraxial image plane to build a line-PSF; FFT the PSF to obtain the
    tangential MTF curve.
    Returns {"ok": True, "frequencies_lp_per_mm": [...], "mtf": [...],
             "psf_bins_mm": [...], "psf": [...], "field_angle_deg": ang,
             "n_rays_traced": n, "n_rays_vignetted": v}

mtf_curves_across_field(surfaces, field_angles_deg, samples_per_aperture=50,
                         aperture_radius_mm=None)
    Call mtf_at_field for each angle in the list; preserve input ordering.
    Returns {"ok": True, "curves": {angle_str: result, ...}}

Algorithm (Hecht "Optics" 5e SS11.2; Welford 1986 SS11.4)
----------------------------------------------------------
1.  Determine paraxial image distance (BFL) via a marginal paraxial trace.
2.  For a field angle theta, a point source at infinity generates rays with
    direction cosines (L, M) = (cos theta, sin theta) in the meridional plane.
3.  Sample the entrance-pupil uniformly in height:
        h_k = -R + k * 2R/(N-1)   for k = 0 .. N-1
    Each ray enters at height h_k with the same direction (L, M) from object
    space.  The ray is traced using the exact meridional Snell trace from
    lens_stack_trace.
4.  Ray intercepts at the paraxial image plane are collected (vignetting:
    rays that fail the Newton-Raphson convergence are discarded).
5.  Line-PSF: 1-D histogram of intercept Y values with adaptive bin width
        n_bins = max(8, ceil(2 * sqrt(N_valid)))   (Rice rule variant)
    The PSF is normalised to unit area (sum * bin_width = 1).
6.  MTF = |FFT(PSF)| / |FFT(PSF)[0]|
    computed via numpy.fft.rfft, spatial frequencies in lp/mm.

Honest limits (document-level)
-------------------------------
* Monochromatic only (single wavelength).  Polychromatic MTF requires
  integrating over the spectral weighting function W(lambda):
      MTF_poly(f) = integral W(lambda) MTF_mono(f, lambda) dlambda
                    / integral W(lambda) dlambda
  Out of scope for this module.
* Wavefront-based MTF (Strehl ratio, OTF phase) is out of scope; only the
  geometric (ray-intercept) PSF->FFT pipeline is implemented here.
* Sagittal MTF is not computed; only the tangential (meridional) plane.
* Vignetting is handled passively: vignetted rays are discarded and the
  vignetted fraction is reported in the output dict.

References
----------
Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, SS11.2 (PSF, MTF).
Welford, W.T. -- "Aberrations of Optical Systems", Adam Hilger, 1986, SS11.4.
Smith, W.J. -- "Modern Optical Engineering", 4th ed., 2008, SS11.3.

Units: lengths in mm, angles in degrees, spatial frequencies in lp/mm.
Author: imranparuk
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

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
# Single-ray off-axis meridional trace
# ---------------------------------------------------------------------------

def _trace_ray_off_axis(
    surfaces: list[dict],
    ray_h: float,                # entrance-pupil height (mm)
    field_angle_rad: float,      # field angle (rad)
    n_object: float,
    paraxial_image_dist: float,  # BFL (mm)
) -> float | None:
    """
    Trace a single meridional ray from a point source at infinity at
    *field_angle_rad*, entering the first surface at height *ray_h*.

    Returns the Y intercept at the paraxial image plane, or None on failure
    (TIR / missed surface / NaN).
    """
    # For a collimated bundle from field angle theta, every aperture ray has
    # the same direction cosines; only the entry height differs.
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
            # Propagate to sag baseline in current medium
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

    # Propagate to paraxial image plane
    if math.isnan(Y) or abs(L_val) < 1e-15:
        return None
    return Y + (M_val / L_val) * paraxial_image_dist


# ---------------------------------------------------------------------------
# Public: MTF at a single field angle
# ---------------------------------------------------------------------------

def mtf_at_field(
    surfaces: list[dict],
    field_angle_deg: float,
    samples_per_aperture: int = 50,
    aperture_radius_mm: float | None = None,
    n_object: float = 1.0,
) -> dict:
    """
    Compute the tangential (meridional) MTF at a single field angle.

    Parameters
    ----------
    surfaces : list of surface dicts (same format as trace_lens_stack).
        Required keys per surface: c (mm^-1), t (mm), n (>= 1.0).
        Optional: k (conic constant, default 0).
    field_angle_deg : float
        Field angle from the optical axis in degrees.  0 = on-axis.
    samples_per_aperture : int
        Number of rays across the entrance-pupil diameter (default 50).
        More rays give a smoother PSF and finer MTF frequency sampling.
    aperture_radius_mm : float | None
        Half-diameter of the entrance pupil (mm).  Default: 10 mm.
    n_object : float
        Refractive index of object space (default 1.0 = air).

    Returns
    -------
    dict
        ok                   : True
        field_angle_deg      : float (echoed)
        frequencies_lp_per_mm: list[float]  spatial frequencies in lp/mm
        mtf                  : list[float]  MTF values in [0, 1]
        psf_bins_mm          : list[float]  bin centres of line-PSF (mm)
        psf                  : list[float]  normalised line-PSF values
        n_rays_traced        : int
        n_rays_vignetted     : int
        aperture_radius_mm   : float
        note                 : str  (monochromatic caveat)

    Errors
    ------
    {"ok": False, "reason": "..."} -- never raises.

    Notes
    -----
    * Monochromatic only.  Polychromatic MTF = integral W(lambda) MTF(lambda)
      dlambda / integral W(lambda) dlambda -- not implemented.
    * Tangential plane only; sagittal MTF is out of scope.
    * Wavefront-based MTF (Strehl / OTF phase) is out of scope.
    """
    # Validate inputs
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")
    for idx, s in enumerate(surfaces):
        e = _validate_surface(s, idx)
        if e:
            return _err(e)
    e = _guard("field_angle_deg", field_angle_deg)
    if e:
        return _err(e)
    if not isinstance(samples_per_aperture, int) or samples_per_aperture < 3:
        return _err("samples_per_aperture must be an integer >= 3")
    if aperture_radius_mm is None:
        aperture_radius_mm = 10.0
    e = _guard("aperture_radius_mm", aperture_radius_mm, positive=True)
    if e:
        return _err(e)
    e = _guard("n_object", n_object)
    if e:
        return _err(e)
    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    field_rad = math.radians(float(field_angle_deg))
    R = float(aperture_radius_mm)
    N = int(samples_per_aperture)

    # Paraxial image distance (BFL)
    props = paraxial_properties(surfaces, n_object=n_object)
    if not props.get("ok"):
        return _err(f"paraxial_properties failed: {props.get('reason')}")
    bfl = props["BFL_mm"]
    if not math.isfinite(bfl):
        return _err("paraxial image distance is infinite (afocal system?)")

    # Trace bundle: uniform heights across entrance pupil
    ray_heights = np.linspace(-R, R, N)
    intercepts: list[float] = []
    vignetted = 0

    for h in ray_heights:
        y_img = _trace_ray_off_axis(surfaces, float(h), field_rad, float(n_object), bfl)
        if y_img is None or math.isnan(y_img) or not math.isfinite(y_img):
            vignetted += 1
        else:
            intercepts.append(y_img)

    n_valid = len(intercepts)
    if n_valid < 3:
        return _err(
            f"Too few valid rays ({n_valid}/{N}) at field angle {field_angle_deg} deg; "
            "check aperture_radius_mm and lens geometry"
        )

    # Line-PSF via 1-D histogram (Rice rule variant)
    pts = np.array(intercepts)
    n_bins = max(8, int(math.ceil(2.0 * math.sqrt(n_valid))))
    counts, bin_edges = np.histogram(pts, bins=n_bins)
    bin_centres = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    bin_width = bin_edges[1] - bin_edges[0]

    # Normalise to unit area (probability density)
    psf = counts.astype(float)
    total = psf.sum() * bin_width
    if total > 0.0:
        psf /= total

    # FFT -> MTF
    spectrum = np.fft.rfft(psf)
    mtf_raw = np.abs(spectrum)
    if mtf_raw[0] < 1e-18:
        return _err("PSF DC component is zero -- check input geometry")
    mtf_normalised = mtf_raw / mtf_raw[0]

    # Spatial frequencies: cycles per mm
    freqs = np.fft.rfftfreq(n_bins, d=bin_width)

    return {
        "ok": True,
        "field_angle_deg": float(field_angle_deg),
        "frequencies_lp_per_mm": freqs.tolist(),
        "mtf": mtf_normalised.tolist(),
        "psf_bins_mm": bin_centres.tolist(),
        "psf": psf.tolist(),
        "n_rays_traced": N,
        "n_rays_vignetted": vignetted,
        "aperture_radius_mm": R,
        "note": (
            "Monochromatic geometric MTF (ray-intercept PSF + FFT pipeline). "
            "Polychromatic MTF = integral_spectrum W(lambda) MTF(lambda) dlambda"
            " -- not implemented. "
            "Wavefront-based MTF (Strehl / OTF phase) is out of scope. "
            "Tangential plane only."
        ),
    }


# ---------------------------------------------------------------------------
# Public: MTF curves across multiple field angles
# ---------------------------------------------------------------------------

def mtf_curves_across_field(
    surfaces: list[dict],
    field_angles_deg: list[float],
    samples_per_aperture: int = 50,
    aperture_radius_mm: float | None = None,
    n_object: float = 1.0,
) -> dict:
    """
    Compute MTF curves at each field angle in *field_angles_deg*.

    Parameters
    ----------
    surfaces          : list of surface dicts (same as trace_lens_stack).
    field_angles_deg  : list of field angles in degrees (ordering preserved).
    samples_per_aperture : int  (default 50)
    aperture_radius_mm   : float | None  (default 10 mm)
    n_object             : float  (default 1.0)

    Returns
    -------
    dict
        ok     : True
        curves : dict mapping str(angle) -> mtf_at_field result dict.
                 Ordering matches input list.
        field_angles_deg : list[float]  (echoed, original ordering)

    Errors
    ------
    {"ok": False, "reason": "..."} on bad inputs.
    Per-angle failures are included inline as {"ok": False, ...} dicts inside
    `curves` rather than aborting the whole call.
    """
    if not isinstance(field_angles_deg, (list, tuple)) or len(field_angles_deg) == 0:
        return _err("field_angles_deg must be a non-empty list")
    for i, a in enumerate(field_angles_deg):
        e = _guard(f"field_angles_deg[{i}]", a)
        if e:
            return _err(e)

    curves: dict[str, dict] = {}
    for angle in field_angles_deg:
        key = str(float(angle))
        curves[key] = mtf_at_field(
            surfaces,
            float(angle),
            samples_per_aperture=samples_per_aperture,
            aperture_radius_mm=aperture_radius_mm,
            n_object=n_object,
        )

    return {
        "ok": True,
        "curves": curves,
        "field_angles_deg": [float(a) for a in field_angles_deg],
    }
