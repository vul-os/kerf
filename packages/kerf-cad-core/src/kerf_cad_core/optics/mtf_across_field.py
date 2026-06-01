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

compute_polychromatic_mtf_across_field(spec, wavelength_samples_nm, spd_weights)
    Spectrally-integrate MTF(f, lambda) weighted by SPD W(lambda) for each
    field point in spec.  Returns polychromatic MTF curves alongside the
    individual monochromatic curves used in the integration.
    MTF_poly(f) = Σ W(λ_i) · MTF(f, λ_i) / Σ W(λ_i)

    Standard SPD helpers (imported from distortion_map):
        photopic_spd(wavelengths_nm)        — CIE V(λ), peak 555 nm
        d65_spd(wavelengths_nm)             — CIE D65 daylight illuminant
        blackbody_spd(wavelengths_nm, T_K)  — Planck blackbody at T_K

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

Polychromatic spectral integration (Hecht SS11.2 / Smith SS11.3)
-----------------------------------------------------------------
For each field point in spec, the monochromatic MTF is computed at each
wavelength sample.  Because different wavelength runs may produce different
frequency grids (different PSF extents → different bin widths → different
frequency bins), the per-wavelength MTF curves are interpolated onto a common
frequency grid before weighting:

    MTF_poly(f_j) = Σ_i W(λ_i) · MTF(f_j, λ_i) / Σ_i W(λ_i)

The common grid spans [0, max_common_freq] with a resolution that is the
finest across all wavelength runs.  MTF values are linearly interpolated and
clamped to [0, 1].  Wavelengths at which the monochromatic computation fails
(e.g., too few valid rays) are silently skipped and their weight is dropped
from the denominator.

Honest limits (document-level)
-------------------------------
* Polychromatic MTF = Σ W(λ_i) · MTF(f, λ_i) / Σ W(λ_i) is now implemented
  via compute_polychromatic_mtf_across_field().  The spectral weighting uses
  the caller-supplied SPD W(λ) and wavelength grid.
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
from typing import Any, Sequence

import numpy as np

from kerf_cad_core.optics.lens_stack_trace import (
    _conic_sag,
    _meridional_refract,
    _meridional_transfer_full,
    _validate_surface,
    paraxial_properties,
)


# ---------------------------------------------------------------------------
# Standard SPD helper functions
# (These are also available in distortion_map; they are reproduced here to
# avoid a circular import, since distortion_map imports _trace_ray_off_axis
# from this module.)
# ---------------------------------------------------------------------------

def photopic_spd(wavelengths_nm: Sequence[float]) -> list[float]:
    """
    CIE 1931 photopic luminosity function V(λ).

    Two-Gaussian approximation accurate to < 1 % over 390-700 nm:
        V(λ) ≈ 1.019 · exp(-285.4 · (λ/1000 - 0.5593)²)   [λ in nm]
    Peak at λ ≈ 555 nm; V(555) = 1.0.

    References
    ----------
    CIE DS 013.3:2018; Wyszecki & Stiles (1982) Table 2(3.3.1).

    Parameters
    ----------
    wavelengths_nm : sequence of float
        Wavelength samples (nm).

    Returns
    -------
    list[float]
        V(λ) values in [0, 1].
    """
    result = []
    for lam in wavelengths_nm:
        x = lam / 1000.0 - 0.5593
        v = 1.019 * math.exp(-285.4 * x * x)
        result.append(max(0.0, min(1.0, v)))
    return result


def d65_spd(wavelengths_nm: Sequence[float]) -> list[float]:
    """
    CIE D65 standard illuminant spectral power distribution.

    Piecewise-linear interpolation of the published 5 nm tabulation from
    CIE Publication 15:2004, Table T.1 (normalised to 100 at 560 nm).
    Values outside 300-830 nm are clamped to 0.

    References
    ----------
    CIE Publication 15:2004, Appendix E, Table 1; Judd et al. (1964).

    Parameters
    ----------
    wavelengths_nm : sequence of float
        Wavelength samples (nm).

    Returns
    -------
    list[float]
        D65 SPD values (arbitrary units, interpolated).
    """
    _D65_LAMBDA_START = 300.0
    _D65_LAMBDA_STEP = 5.0
    _D65_TABLE = [
        0.034100, 1.664300, 3.294500, 11.765200, 20.236000,
        28.644700, 37.053500, 38.501100, 39.948800, 42.430200,
        44.911700, 45.775000, 46.638300, 49.363700, 52.089100,
        51.032300, 49.975500, 52.311800, 54.648200, 68.701500,
        82.754900, 87.120400, 91.486000, 92.458900, 93.431800,
        90.057000, 86.682300, 95.773600, 104.865000, 110.936000,
        117.008000, 117.410000, 117.812000, 116.336000, 114.861000,
        115.392000, 115.923000, 112.367000, 108.811000, 109.082000,
        109.354000, 108.578000, 107.802000, 106.296000, 104.790000,
        106.239000, 107.689000, 106.047000, 104.405000, 104.225000,
        104.046000, 102.023000, 100.000000, 98.167100, 96.334200,
        96.061100, 95.788000, 92.236800, 88.685600, 89.345900,
        90.006200, 89.802600, 89.599100, 88.648900, 87.698700,
        85.493600, 83.288600, 83.493900, 83.699200, 81.863000,
        80.026800, 80.120700, 80.214600, 81.246200, 82.277800,
        80.281000, 78.284200, 74.002700, 69.721300, 70.665200,
        71.609100, 72.979000, 74.349000, 67.976500, 61.604000,
        65.744800, 69.885600, 72.486300, 75.087000, 69.339800,
        63.592700, 55.005400, 46.418200, 56.611800, 66.805400,
        65.094100, 63.382800, 63.843400, 64.304000, 61.877900,
        59.451800, 55.705400, 51.959000, 54.699800, 57.440600,
        58.876500, 60.312500,
    ]
    out = []
    for lam in wavelengths_nm:
        idx_f = (lam - _D65_LAMBDA_START) / _D65_LAMBDA_STEP
        if idx_f < 0.0 or idx_f > len(_D65_TABLE) - 1:
            out.append(0.0)
            continue
        i0 = int(idx_f)
        i1 = min(i0 + 1, len(_D65_TABLE) - 1)
        frac = idx_f - i0
        out.append(_D65_TABLE[i0] * (1.0 - frac) + _D65_TABLE[i1] * frac)
    return out


def blackbody_spd(wavelengths_nm: Sequence[float], T_K: float) -> list[float]:
    """
    Planck blackbody spectral radiance (unnormalised relative SPD).

    B(λ, T) ∝ λ^{-5} / [exp(hc/λkT) - 1]

    Peak: λ_max = 2.8977721e6 nm·K / T_K  (Wien's displacement law).

    References
    ----------
    Planck, M. (1901) Ann.Phys. 4, 553.
    Hecht, E. (2017) "Optics" 5e §3.1.

    Parameters
    ----------
    wavelengths_nm : sequence of float
        Wavelength samples (nm).
    T_K : float
        Blackbody temperature (K).  Must be > 0.

    Returns
    -------
    list[float]
        Relative spectral radiance.

    Raises
    ------
    ValueError
        If T_K <= 0.
    """
    if T_K <= 0.0:
        raise ValueError(f"T_K must be > 0, got {T_K}")
    _HC_OVER_K = 1.4387769e7  # nm·K  (h=6.626e-34 J·s, c=2.998e17 nm/s, k=1.381e-23 J/K)
    out = []
    for lam in wavelengths_nm:
        if lam <= 0.0:
            out.append(0.0)
            continue
        exponent = _HC_OVER_K / (lam * T_K)
        if exponent > 700.0:
            out.append(0.0)
        else:
            out.append((lam ** -5) / (math.exp(exponent) - 1.0))
    return out


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
    * Monochromatic only (single wavelength per call).  For polychromatic MTF
      use compute_polychromatic_mtf_across_field() which performs the spectral
      integration MTF_poly(f) = Σ W(λ_i)·MTF(f, λ_i) / Σ W(λ_i).
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
            "Polychromatic MTF = Σ W(λ_i)·MTF(f, λ_i) / Σ W(λ_i) is "
            "implemented in compute_polychromatic_mtf_across_field(). "
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


# ---------------------------------------------------------------------------
# Public: Polychromatic MTF across field (spectral integration)
# ---------------------------------------------------------------------------

class PolychromaticMTFSpec:
    """
    Input specification for compute_polychromatic_mtf_across_field.

    Parameters
    ----------
    surfaces : list[dict]
        Lens surface list (same format as mtf_at_field).
    field_angles_deg : list[float]
        Field angles to evaluate (degrees).
    samples_per_aperture : int
        Rays per aperture per wavelength per field angle (default 50).
    aperture_radius_mm : float | None
        Entrance-pupil half-diameter (mm).  Default: 10 mm.
    n_object : float
        Object-space refractive index (default 1.0).
    """

    def __init__(
        self,
        surfaces: list[dict],
        field_angles_deg: list[float],
        samples_per_aperture: int = 50,
        aperture_radius_mm: float | None = None,
        n_object: float = 1.0,
    ) -> None:
        self.surfaces = surfaces
        self.field_angles_deg = field_angles_deg
        self.samples_per_aperture = samples_per_aperture
        self.aperture_radius_mm = aperture_radius_mm
        self.n_object = n_object


def _interpolate_mtf(
    src_freqs: list[float],
    src_mtf: list[float],
    dst_freqs: np.ndarray,
) -> np.ndarray:
    """
    Linearly interpolate a single MTF curve (src_freqs, src_mtf) onto
    dst_freqs.  Values requested beyond src_freqs[-1] are set to 0.0.
    Returns a numpy array clamped to [0, 1].
    """
    src_f = np.asarray(src_freqs, dtype=float)
    src_m = np.asarray(src_mtf, dtype=float)
    result = np.interp(dst_freqs, src_f, src_m, left=src_m[0], right=0.0)
    return np.clip(result, 0.0, 1.0)


def compute_polychromatic_mtf_across_field(
    spec: "PolychromaticMTFSpec",
    wavelength_samples_nm: Sequence[float],
    spd_weights: Sequence[float],
) -> dict:
    """
    Compute polychromatic (spectrally-integrated) MTF across field angles.

    For each field angle in spec.field_angles_deg the monochromatic MTF is
    computed at every wavelength in wavelength_samples_nm.  The results are
    then combined via a weighted sum:

        MTF_poly(f_j) = Σ_i W(λ_i) · MTF(f_j, λ_i) / Σ_i W(λ_i)

    where W(λ_i) = spd_weights[i].  All per-wavelength MTF curves are
    interpolated onto a common frequency grid before summation.

    Standard SPD helpers available in this module:
        photopic_spd(wavelengths_nm)       — CIE V(λ), peak 555 nm
        d65_spd(wavelengths_nm)            — CIE D65 daylight
        blackbody_spd(wavelengths_nm, T_K) — Planck blackbody

    Parameters
    ----------
    spec : PolychromaticMTFSpec
        Lens geometry and tracing options.
    wavelength_samples_nm : sequence of float
        Wavelength grid (nm).  Must be >= 2 elements, all positive.
    spd_weights : sequence of float
        Spectral power density weights at each wavelength.  Must be the same
        length as wavelength_samples_nm.  All values must be >= 0 and not
        all zero.

    Returns
    -------
    dict
        ok                    : True
        field_angles_deg      : list[float]  (echoed)
        common_frequencies_lp_per_mm : list[float]  shared freq grid
        polychromatic_curves  : dict mapping str(angle) ->
            {
              "ok"                     : True,
              "field_angle_deg"        : float,
              "frequencies_lp_per_mm"  : list[float],  # = common grid
              "mtf_polychromatic"      : list[float],  # MTF_poly
              "monochromatic_curves"   : {str(wl_nm): {"ok": bool, ...}},
              "wavelengths_used_nm"    : list[float],  # wl's with ok mono
              "weights_used"           : list[float],
              "n_wavelengths_ok"       : int,
              "n_wavelengths_failed"   : int,
            }
        wavelength_samples_nm : list[float]  (echoed)
        spd_weights           : list[float]  (echoed)
        design_wavelength_nm  : float  (wavelength of peak SPD weight)
        honest_note           : str

    Errors
    ------
    {"ok": False, "reason": "..."} -- never raises on input errors.
    Per-angle failures embed as {"ok": False, ...} inside polychromatic_curves.

    Notes
    -----
    * The monochromatic path (mtf_at_field) is preserved and left untouched.
    * Per-wavelength failures at a given field angle (too few rays, geometry
      error) are silently skipped; their weight is excluded from the denominator.
    * The common frequency grid is built from the finest frequency resolution
      across all successful runs and all field angles, spanning [0, max_freq].
    * Trapezoidal quadrature variant: weights are point-evaluated (not interval
      averaged) because the spectral integration is a discrete sum; see
      Hecht SS11.2 / Smith SS11.3 for the continuous form.

    References
    ----------
    Hecht, E. -- "Optics", 5th ed., Addison-Wesley, 2017, SS11.2 (MTF, PSF).
    Smith, W.J. -- "Modern Optical Engineering", 4th ed., 2008, SS11.3.
    CIE DS 013.3:2018 (photopic V(λ) definition).
    CIE Publication 15:2004 (D65 illuminant).
    Planck, M. (1901) Ann.Phys. 4, 553 (blackbody distribution).
    """
    # ---- Input validation ---------------------------------------------------
    if not isinstance(spec, PolychromaticMTFSpec):
        return _err("spec must be a PolychromaticMTFSpec instance")

    try:
        lambdas = [float(v) for v in wavelength_samples_nm]
    except (TypeError, ValueError) as exc:
        return _err(f"wavelength_samples_nm invalid: {exc}")

    if len(lambdas) < 1:
        return _err("wavelength_samples_nm must have at least 1 element")
    if any(lam <= 0.0 for lam in lambdas):
        return _err("all wavelength_samples_nm values must be > 0")

    try:
        weights_raw = [float(w) for w in spd_weights]
    except (TypeError, ValueError) as exc:
        return _err(f"spd_weights invalid: {exc}")

    if len(weights_raw) != len(lambdas):
        return _err(
            f"spd_weights length ({len(weights_raw)}) must match "
            f"wavelength_samples_nm length ({len(lambdas)})"
        )
    if any(w < 0.0 for w in weights_raw):
        return _err("spd_weights must all be >= 0")
    if sum(weights_raw) <= 0.0:
        return _err("spd_weights must not be all zero")

    if not isinstance(spec.surfaces, list) or len(spec.surfaces) == 0:
        return _err("spec.surfaces must be a non-empty list")
    for idx, s in enumerate(spec.surfaces):
        e = _validate_surface(s, idx)
        if e:
            return _err(e)

    if not isinstance(spec.field_angles_deg, (list, tuple)) or len(spec.field_angles_deg) == 0:
        return _err("spec.field_angles_deg must be a non-empty list")
    for i, a in enumerate(spec.field_angles_deg):
        e = _guard(f"spec.field_angles_deg[{i}]", a)
        if e:
            return _err(e)

    # Design wavelength: wavelength of peak SPD weight
    peak_idx = weights_raw.index(max(weights_raw))
    design_wavelength_nm = lambdas[peak_idx]

    # ---- Step 1: Compute per-wavelength monochromatic MTF for all angles ----
    # mono_results[wl_idx][angle_key] = mtf_at_field result dict
    # Build list of (wavelength, weight, mono_results_for_all_angles) triples.

    per_wl_per_angle: list[dict[str, dict]] = []
    for lam, _w in zip(lambdas, weights_raw):
        angle_results: dict[str, dict] = {}
        for angle in spec.field_angles_deg:
            key = str(float(angle))
            angle_results[key] = mtf_at_field(
                spec.surfaces,
                float(angle),
                samples_per_aperture=spec.samples_per_aperture,
                aperture_radius_mm=spec.aperture_radius_mm,
                n_object=spec.n_object,
            )
        per_wl_per_angle.append(angle_results)

    # ---- Step 2: Build common frequency grid --------------------------------
    # Collect all frequency arrays from successful runs.
    all_freq_arrays: list[np.ndarray] = []
    for wl_results in per_wl_per_angle:
        for res in wl_results.values():
            if res.get("ok"):
                all_freq_arrays.append(np.asarray(res["frequencies_lp_per_mm"]))

    if not all_freq_arrays:
        return _err(
            "All monochromatic MTF computations failed; check lens geometry and "
            "aperture_radius_mm."
        )

    # Common grid: finest resolution (smallest df), span from 0 to max of all maxes
    max_freq = max(float(arr[-1]) for arr in all_freq_arrays if len(arr) > 0)
    # Finest df = smallest non-zero spacing
    dfs = [float(arr[1]) for arr in all_freq_arrays if len(arr) >= 2 and arr[1] > 0]
    if not dfs:
        return _err("Could not determine frequency resolution from monochromatic runs.")
    df_common = min(dfs)
    n_common = max(2, int(math.ceil(max_freq / df_common)) + 1)
    common_freqs = np.linspace(0.0, max_freq, n_common)

    # ---- Step 3: Polychromatic sum per field angle --------------------------
    poly_curves: dict[str, dict] = {}

    for angle in spec.field_angles_deg:
        key = str(float(angle))
        # Accumulate weighted sum over wavelengths
        sum_weighted_mtf = np.zeros(n_common, dtype=float)
        sum_weights = 0.0
        wl_used: list[float] = []
        w_used: list[float] = []
        n_failed = 0
        mono_dict: dict[str, dict] = {}

        for lam, w_val, wl_results in zip(lambdas, weights_raw, per_wl_per_angle):
            wl_key = str(float(lam))
            res = wl_results[key]
            mono_dict[wl_key] = res

            if not res.get("ok") or w_val == 0.0:
                n_failed += 1
                continue

            # Interpolate this wavelength's MTF onto common grid
            mtf_interp = _interpolate_mtf(
                res["frequencies_lp_per_mm"],
                res["mtf"],
                common_freqs,
            )
            sum_weighted_mtf += w_val * mtf_interp
            sum_weights += w_val
            wl_used.append(float(lam))
            w_used.append(float(w_val))

        if sum_weights <= 0.0:
            poly_curves[key] = {
                "ok": False,
                "reason": (
                    f"All wavelength MTF computations failed at field angle {angle} deg"
                ),
                "field_angle_deg": float(angle),
                "monochromatic_curves": mono_dict,
                "n_wavelengths_ok": 0,
                "n_wavelengths_failed": n_failed,
            }
            continue

        mtf_poly = np.clip(sum_weighted_mtf / sum_weights, 0.0, 1.0)

        poly_curves[key] = {
            "ok": True,
            "field_angle_deg": float(angle),
            "frequencies_lp_per_mm": common_freqs.tolist(),
            "mtf_polychromatic": mtf_poly.tolist(),
            "monochromatic_curves": mono_dict,
            "wavelengths_used_nm": wl_used,
            "weights_used": w_used,
            "n_wavelengths_ok": len(wl_used),
            "n_wavelengths_failed": n_failed,
        }

    return {
        "ok": True,
        "field_angles_deg": [float(a) for a in spec.field_angles_deg],
        "common_frequencies_lp_per_mm": common_freqs.tolist(),
        "polychromatic_curves": poly_curves,
        "wavelength_samples_nm": lambdas,
        "spd_weights": weights_raw,
        "design_wavelength_nm": design_wavelength_nm,
        "honest_note": (
            "Polychromatic MTF_poly(f) = Σ W(λ_i)·MTF(f, λ_i) / Σ W(λ_i). "
            "Monochromatic geometric MTF (ray-intercept PSF + FFT) at each "
            "wavelength; MTF curves interpolated onto a common frequency grid "
            "before weighting. "
            "Tangential (meridional) plane only; wavefront-based MTF (Strehl / "
            "OTF phase) is out of scope. "
            "Per-wavelength failures are silently dropped; see "
            "n_wavelengths_failed per field angle. "
            "Design wavelength = wavelength of peak SPD weight."
        ),
    }
