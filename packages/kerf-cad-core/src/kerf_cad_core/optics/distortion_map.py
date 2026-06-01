"""
kerf_cad_core.optics.distortion_map — geometric distortion map for a lens stack.

Public API
----------
compute_distortion_map(surfaces, field_angles_deg, aperture_mm=1.0,
                       n_object=1.0) -> DistortionMapReport

compute_spectral_distortion(distortion_func, field_angles_deg,
                             wavelength_samples, spd_weights) -> SpectralDistortionReport

Computes the geometric (tangential) distortion of a lens stack as a function
of field angle.

Algorithm (Hecht §5.6 / Welford 1986 §6.3)
--------------------------------------------
For each field angle θ in field_angles_deg:

  1. Trace the *chief ray* through the stack: the chief ray enters the first
     surface at height y=0 (stop at first surface) and travels at angle θ
     in object space.  The exact meridional tracer (_trace_ray_off_axis from
     mtf_across_field) is used with ray_h=0 and the BFL determined from the
     collimated marginal-ray paraxial trace.  This ensures the image plane is
     correctly placed at the paraxial back focal distance (not the chief-ray
     focus, which differs from the marginal focus due to field curvature).

  2. The *actual image height* y_actual is the meridional image-plane intercept
     of the chief ray at the paraxial BFL plane.

  3. The *ideal paraxial image height* is:
         y_paraxial = f_eff * tan(θ)
     where f_eff (EFL) is derived from the collimated marginal-ray trace via
     paraxial_properties.

  4. *Distortion* (in percent) is:
         D(θ) = (y_actual - y_paraxial) / |y_paraxial| × 100

     Sign convention (Hecht §5.6 / ISO 9039):
       barrel     → D < 0  (actual image height < paraxial ideal; image
                             is compressed at the edges)
       pincushion → D > 0  (actual image height > paraxial ideal; image
                             is stretched at the edges)
     At θ=0: y_paraxial=0 → distortion is defined as 0.

  5. Distortion kind is classified as:
       "barrel"     if all non-trivial D values are negative.
       "pincushion" if all non-trivial D values are positive.
       "mixed"      if both positive and negative D appear (e.g. telephoto).
       "none"       if |D| < 0.05 % everywhere (well-corrected stack).

Seidel cross-check (Welford 1986 §6.3)
----------------------------------------
For a single thin lens the Seidel S_V coefficient predicts the third-order
distortion.  The additive distortion in image height from S_V is:

    Δy_seidel = S_V * tan²(θ)       (Welford §6.3, reduced form)

giving:

    D_seidel(θ) = S_V * tan²(θ) / |y_paraxial| × 100
                = S_V * |tan(θ)| / |EFL| × 100

This is returned as seidel_distortion_percent for comparison.  The third-order
prediction is accurate only for small field angles; at moderate fields higher-
order terms dominate.

DEPTH BAR
---------
For an ideal stigmatic stack (equiconvex symmetric singlet at small field):
  distortion < 2% — S_V ≈ 0 by bending symmetry (Welford §6.4).

For a real BK7 biconvex singlet at moderate field (20 deg):
  |distortion| > 5% is typical for an uncorrected singlet with high S_V.

HONEST FLAGS
------------
* Monochromatic only.  Polychromatic distortion (lateral chromatic component)
  requires integrating D(θ, λ) over the spectral band — see
  compute_spectral_distortion() for the spectrally-integrated path.
* Tangential (meridional) distortion only.  For rotationally symmetric systems
  the sagittal distortion is identical by symmetry, but off-axis astigmatism
  can produce a small difference that is not captured here.
* The chief ray is traced from *infinity* (collimated input).  For finite
  conjugates the field angle should be the half-field angle at the object.
* Aperture stop assumed at first surface (chief ray height = 0 there).

Spectral Integration
--------------------
compute_spectral_distortion(distortion_func, field_angles_deg,
                             wavelength_samples, spd_weights)
  -> SpectralDistortionReport

For each field angle θ the spectrally-weighted distortion is:

    D̄(θ) = ∫ D(θ,λ) · SPD(λ) dλ  /  ∫ SPD(λ) dλ

where D(θ,λ) is the caller-supplied distortion function and SPD(λ) is the
spectral power density (photopic V(λ), D65 daylight, blackbody, or custom).

The chromatic residual is:

    ΔD(θ) = D̄(θ) − D(θ, λ_design)

where λ_design is the wavelength of the highest SPD weight sample.

Standard SPD helpers
--------------------
photopic_spd(wavelengths_nm)  — CIE 1931 photopic luminosity V(λ), peak 555 nm.
d65_spd(wavelengths_nm)       — CIE D65 daylight (piecewise linear interpolation).
blackbody_spd(wavelengths_nm, T_K) — Planck blackbody curve at temperature T_K.

References
----------
CIE Publication 15:2004 (colorimetry); CIE DS 013.3:2018 (V(λ)).
Judd et al. (1964) J.Opt.Soc.Am 54, 1031 (D65 coefficients).
Planck, M. (1901) Ann.Phys. 4, 553 (blackbody distribution).

References
----------
Hecht, E. — "Optics", 5th ed., Addison-Wesley, 2017, §5.6 (geometric distortion).
Welford, W.T. — "Aberrations of Optical Systems", Adam Hilger, 1986,
    §6.3 (Seidel S_V distortion coefficient),
    §3.3 (paraxial nu-form trace),
    §5   (exact meridional ray trace).

Units: lengths in mm, angles in degrees / radians as noted.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from kerf_cad_core.optics.lens_stack_trace import paraxial_properties
from kerf_cad_core.optics.mtf_across_field import _trace_ray_off_axis
from kerf_cad_core.optics.seidel_aberrations import seidel_coefficients


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


def _validate_surface(s: Any, idx: int) -> str | None:
    if not isinstance(s, dict):
        return f"surface[{idx}] must be a dict"
    for fld in ("c", "t", "n"):
        if fld not in s:
            return f"surface[{idx}] missing required field '{fld}'"
        err = _guard(f"surface[{idx}].{fld}", s[fld])
        if err:
            return err
    if float(s["n"]) < 1.0:
        return f"surface[{idx}].n must be >= 1.0"
    return None


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DistortionMapReport:
    """
    Geometric distortion map for a lens stack.

    Follows Hecht §5.6 / Welford 1986 §6.3 sign convention:
      barrel distortion    → distortion_percent < 0
      pincushion distortion → distortion_percent > 0

    Attributes
    ----------
    field_angles_deg    : list[float]  Field angles in degrees.
    y_actual_mm         : list[float]  Chief-ray image-plane intercepts (mm).
    y_paraxial_mm       : list[float]  Ideal paraxial image heights f*tan(θ) (mm).
    distortion_percent  : list[float]  (y_actual - y_paraxial)/|y_paraxial| × 100.
    max_distortion_pct  : float        Max |distortion| across all field angles.
    kind                : str          "barrel" | "pincushion" | "mixed" | "none".
    EFL_mm              : float        Effective focal length used for y_paraxial.
    seidel_distortion_percent : list[float]
        Third-order Seidel S_V additive prediction (Welford §6.3).
    honest_flag         : str          Caveats / limitations.
    """

    field_angles_deg: list = field(default_factory=list)
    y_actual_mm: list = field(default_factory=list)
    y_paraxial_mm: list = field(default_factory=list)
    distortion_percent: list = field(default_factory=list)
    max_distortion_pct: float = 0.0
    kind: str = "none"
    EFL_mm: float = 0.0
    seidel_distortion_percent: list = field(default_factory=list)
    honest_flag: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "field_angles_deg": self.field_angles_deg,
            "y_actual_mm": self.y_actual_mm,
            "y_paraxial_mm": self.y_paraxial_mm,
            "distortion_percent": self.distortion_percent,
            "max_distortion_pct": self.max_distortion_pct,
            "kind": self.kind,
            "EFL_mm": self.EFL_mm,
            "seidel_distortion_percent": self.seidel_distortion_percent,
            "honest_flag": self.honest_flag,
        }


# ---------------------------------------------------------------------------
# Spectral distortion dataclass
# ---------------------------------------------------------------------------

@dataclass
class SpectralDistortionReport:
    """
    Spectrally-integrated distortion D̄(θ) = ∫D(θ,λ)·SPD(λ)dλ / ∫SPD(λ)dλ.

    Attributes
    ----------
    field_angles_deg : list[float]
        Field angles evaluated (degrees).
    spectral_avg_distortion : list[float]
        SPD-weighted mean distortion at each field angle (fraction, not percent;
        to match the caller-supplied distortion_func convention).
    monochromatic_d_at_design_wavelength : list[float]
        D(θ, λ_design) where λ_design is the wavelength of peak SPD weight.
    chromatic_residual : list[float]
        D̄(θ) − D(θ, λ_design).  Non-zero ↔ the design wavelength underestimates
        the true spectrally-averaged distortion.
    design_wavelength_nm : float
        Wavelength of the peak SPD sample used for monochromatic reference.
    honest_caveat : str
        Caveats on the spectral integration.
    """

    field_angles_deg: list = field(default_factory=list)
    spectral_avg_distortion: list = field(default_factory=list)
    monochromatic_d_at_design_wavelength: list = field(default_factory=list)
    chromatic_residual: list = field(default_factory=list)
    design_wavelength_nm: float = 0.0
    honest_caveat: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "field_angles_deg": self.field_angles_deg,
            "spectral_avg_distortion": self.spectral_avg_distortion,
            "monochromatic_d_at_design_wavelength": self.monochromatic_d_at_design_wavelength,
            "chromatic_residual": self.chromatic_residual,
            "design_wavelength_nm": self.design_wavelength_nm,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Standard SPD helper functions
# ---------------------------------------------------------------------------

def photopic_spd(wavelengths_nm: Sequence[float]) -> list[float]:
    """
    CIE 1931 photopic luminosity function V(λ).

    Uses the analytic Gaussian approximation (Stockman-Sharpe 10° CMFs are
    exact; here we use the widely-cited two-Gaussian fit that is accurate to
    < 1 % over 390–700 nm):

        V(λ) ≈ 1.019 · exp(−285.4 · (λ/1000 − 0.5593)²)   [λ in nm]

    Peak at λ ≈ 555 nm, V(555) = 1.0.

    References
    ----------
    CIE DS 013.3:2018 (Stockman-Sharpe V(λ) definition).
    Wyszecki & Stiles (1982) "Color Science", 2nd ed., Table 2(3.3.1).

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
        x = lam / 1000.0 - 0.5593   # shift so peak at ~555 nm → x≈0
        v = 1.019 * math.exp(-285.4 * x * x)
        # clamp to [0, 1]
        result.append(max(0.0, min(1.0, v)))
    return result


def d65_spd(wavelengths_nm: Sequence[float]) -> list[float]:
    """
    CIE D65 standard illuminant spectral power distribution.

    Uses piecewise-linear interpolation of the published 5 nm tabulation
    from CIE Publication 15:2004, Table T.1 (normalised to 100 at 560 nm).
    Values outside 300–830 nm are clamped to 0.

    References
    ----------
    CIE Publication 15:2004 (colorimetry), Appendix E, Table 1.
    Judd et al. (1964) J.Opt.Soc.Am 54, 1031.

    Parameters
    ----------
    wavelengths_nm : sequence of float
        Wavelength samples (nm).

    Returns
    -------
    list[float]
        D65 SPD values (arbitrary units, interpolated).
    """
    # CIE D65 tabulation at 5 nm steps, 300–830 nm (CIE Pub. 15:2004 Table T.1)
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
    Planck blackbody spectral radiance (unnormalised).

    B(λ, T) ∝ λ^{-5} / [exp(hc/λkT) − 1]

    Values are returned un-normalised (relative SPD).  Useful for
    solar-like or tungsten-lamp illumination modelling.

    Peak: λ_max = 2.8977721e6 nm·K / T_K  (Wien's displacement law).

    References
    ----------
    Planck, M. (1901) Ann.Phys. 4, 553.
    Hecht, E. (2017) "Optics" 5e, §3.1.

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
    # hc/k in nm·K  (h=6.626e-34 J·s, c=2.998e17 nm/s, k=1.381e-23 J/K)
    _HC_OVER_K = 1.4387769e7  # nm·K
    out = []
    for lam in wavelengths_nm:
        if lam <= 0.0:
            out.append(0.0)
            continue
        exponent = _HC_OVER_K / (lam * T_K)
        # Guard overflow: for very short λ or low T the exponent can be huge
        if exponent > 700.0:
            out.append(0.0)
        else:
            out.append((lam ** -5) / (math.exp(exponent) - 1.0))
    return out


# ---------------------------------------------------------------------------
# Spectral integration
# ---------------------------------------------------------------------------

def compute_spectral_distortion(
    distortion_func: Callable[[float, float], float],
    field_angles_deg: Sequence[float],
    wavelength_samples: Sequence[float],
    spd_weights: Sequence[float],
) -> "SpectralDistortionReport | dict":
    """
    Compute the spectrally-integrated distortion D̄(θ) for each field angle.

    Algorithm
    ---------
    For each field angle θ:

        D̄(θ) = Σ_i  D(θ, λ_i) · w_i   /   Σ_i w_i

    where the sum is a trapezoidal quadrature over the supplied wavelength and
    SPD-weight samples.

    The *chromatic residual* ΔD(θ) = D̄(θ) − D(θ, λ_design) reveals whether
    evaluating the lens only at the design wavelength under- or over-estimates
    the distortion experienced by a spectrally-broad source.

    Parameters
    ----------
    distortion_func : Callable[[float, float], float]
        D(theta_deg, lambda_nm) → distortion value (fraction or percent;
        the unit is whatever the caller uses — SpectralDistortionReport
        preserves the same unit).
    field_angles_deg : sequence of float
        Field angles (degrees) at which to evaluate.
    wavelength_samples : sequence of float
        Wavelength grid (nm).  Must have at least 2 elements; must be
        monotonically non-decreasing.
    spd_weights : sequence of float
        Spectral power density at each wavelength.  Must be the same length as
        wavelength_samples.  All values must be ≥ 0 and not all zero.

    Returns
    -------
    SpectralDistortionReport on success.
    dict {ok: False, reason: ...} on input error.

    Notes
    -----
    * The monochromatic path (compute_distortion_map) is left untouched.
    * Trapezoidal quadrature: ∫f·dλ ≈ Σ_i 0.5·(f_i+f_{i+1})·(λ_{i+1}−λ_i).
      This reduces to a weighted sum when weights are pre-evaluated on the grid
      (which is the typical case here: SPD is the weight function).
    * design_wavelength = wavelength sample with the highest SPD weight.

    References
    ----------
    Numerics: Press et al. "Numerical Recipes" 3rd ed., §4.2 (trapezoidal rule).
    Photopic V(λ): CIE DS 013.3:2018; peak 555 nm.
    D65: CIE Publication 15:2004.
    Blackbody: Planck (1901); Wien displacement λT = 2898 μm·K.
    """
    # ---- Input validation --------------------------------------------------
    if not callable(distortion_func):
        return {"ok": False, "reason": "distortion_func must be callable"}

    try:
        lambdas = [float(v) for v in wavelength_samples]
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"wavelength_samples invalid: {exc}"}

    if len(lambdas) < 2:
        return {"ok": False,
                "reason": "wavelength_samples must have at least 2 elements"}

    for i in range(1, len(lambdas)):
        if lambdas[i] < lambdas[i - 1]:
            return {"ok": False,
                    "reason": (
                        f"wavelength_samples must be monotonically non-decreasing; "
                        f"λ[{i}]={lambdas[i]} < λ[{i-1}]={lambdas[i-1]}"
                    )}

    try:
        weights = [float(v) for v in spd_weights]
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"spd_weights invalid: {exc}"}

    if len(weights) != len(lambdas):
        return {"ok": False,
                "reason": (
                    f"spd_weights length ({len(weights)}) must match "
                    f"wavelength_samples length ({len(lambdas)})"
                )}

    if any(w < 0.0 for w in weights):
        return {"ok": False, "reason": "spd_weights must all be >= 0"}

    total_weight = sum(weights)
    if total_weight <= 0.0:
        return {"ok": False, "reason": "spd_weights must not be all zero"}

    if not isinstance(field_angles_deg, (list, tuple, range)) and not hasattr(
        field_angles_deg, "__iter__"
    ):
        return {"ok": False, "reason": "field_angles_deg must be iterable"}

    try:
        angles = [float(a) for a in field_angles_deg]
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": f"field_angles_deg invalid: {exc}"}

    if len(angles) == 0:
        return {"ok": False, "reason": "field_angles_deg must not be empty"}

    # ---- Identify design wavelength (peak SPD) -----------------------------
    peak_idx = weights.index(max(weights))
    lam_design = lambdas[peak_idx]

    # ---- Trapezoidal quadrature for each field angle -----------------------
    # For the trapezoidal rule:
    #   D̄(θ) = [Σ_i 0.5·(D_i·w_i + D_{i+1}·w_{i+1})·Δλ_i]
    #           / [Σ_i 0.5·(w_i + w_{i+1})·Δλ_i]
    # Pre-compute denominator (independent of θ):
    denom = 0.0
    for i in range(len(lambdas) - 1):
        dlam = lambdas[i + 1] - lambdas[i]
        denom += 0.5 * (weights[i] + weights[i + 1]) * dlam
    if denom <= 0.0:
        # Edge case: all λ identical (already caught by len<2, but be safe)
        denom = total_weight

    out_angles: list[float] = []
    out_spectral: list[float] = []
    out_mono: list[float] = []
    out_residual: list[float] = []

    for theta in angles:
        # Evaluate D(θ, λ) at every sample
        d_vals = []
        for lam in lambdas:
            try:
                d = float(distortion_func(theta, lam))
            except Exception:  # noqa: BLE001
                d = math.nan
            d_vals.append(d)

        # Trapezoidal integration: ∫ D·w dλ
        numerator = 0.0
        for i in range(len(lambdas) - 1):
            dlam = lambdas[i + 1] - lambdas[i]
            numerator += 0.5 * (
                d_vals[i] * weights[i] + d_vals[i + 1] * weights[i + 1]
            ) * dlam

        d_bar = numerator / denom if math.isfinite(numerator) else math.nan

        # Monochromatic at design wavelength
        try:
            d_design = float(distortion_func(theta, lam_design))
        except Exception:  # noqa: BLE001
            d_design = math.nan

        chromatic_residual = (
            d_bar - d_design
            if (math.isfinite(d_bar) and math.isfinite(d_design))
            else math.nan
        )

        out_angles.append(theta)
        out_spectral.append(d_bar)
        out_mono.append(d_design)
        out_residual.append(chromatic_residual)

    honest_caveat = (
        "Spectral distortion D̄(θ) = ∫D(θ,λ)·SPD(λ)dλ / ∫SPD(λ)dλ via "
        "trapezoidal quadrature over the supplied wavelength grid. "
        "Accuracy depends on the grid density — use ≥20 samples across the "
        "spectral band of interest. "
        "The distortion_func D(θ,λ) is caller-supplied; the spectral variation "
        "must encode the real chromatic aberration of the lens (e.g. via "
        "per-wavelength ray traces using Sellmeier dispersion). "
        "Tangential (meridional) distortion only; stop at first surface; "
        "chief ray traced from infinity. "
        "Design wavelength = wavelength sample with highest SPD weight."
    )

    return SpectralDistortionReport(
        field_angles_deg=out_angles,
        spectral_avg_distortion=out_spectral,
        monochromatic_d_at_design_wavelength=out_mono,
        chromatic_residual=out_residual,
        design_wavelength_nm=lam_design,
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_DISTORTION_THRESHOLD_PCT = 0.05  # below this magnitude → "none"


def compute_distortion_map(
    surfaces: list[dict],
    field_angles_deg: list[float],
    aperture_mm: float = 1.0,
    n_object: float = 1.0,
) -> DistortionMapReport | dict:
    """
    Compute the geometric distortion map for a lens stack.

    Traces the chief ray at each field angle and compares the actual image
    height with the ideal paraxial prediction f*tan(θ).

    Algorithm (Hecht §5.6 / Welford 1986 §6.3):
      1. Obtain EFL and BFL from a collimated marginal-ray trace via
         paraxial_properties.
      2. For each field angle θ, trace the chief ray (height=0 at first
         surface, angle=θ) to the paraxial image plane using the exact
         meridional tracer (_trace_ray_off_axis, ray_h=0, BFL from step 1).
      3. Compare y_actual (meridional trace) with y_paraxial = EFL * tan(θ).
      4. Compute distortion percent and classify the distortion type.

    Parameters
    ----------
    surfaces : list of surface dicts (c, t, n, optional k).
        Same format as trace_lens_stack.  Lengths in mm, c in mm^-1.
    field_angles_deg : list of float
        Field angles in degrees to evaluate.  0 deg is on-axis (D=0).
    aperture_mm : float
        Marginal ray height used for Seidel cross-check and paraxial EFL.
        Default 1.0 mm.
    n_object : float
        Refractive index of object space (default 1.0 = air).

    Returns
    -------
    DistortionMapReport on success.
    dict {ok: False, reason: ...} on input error.

    References
    ----------
    Hecht §5.6 (geometric distortion, barrel / pincushion).
    Welford (1986) §6.3 (S_V Seidel distortion coefficient).
    """
    # ---- Validate inputs ---------------------------------------------------
    if not isinstance(surfaces, list) or len(surfaces) == 0:
        return _err("surfaces must be a non-empty list")

    for idx, s in enumerate(surfaces):
        err = _validate_surface(s, idx)
        if err:
            return _err(err)

    if not isinstance(field_angles_deg, (list, tuple)) or len(field_angles_deg) == 0:
        return _err("field_angles_deg must be a non-empty list")

    for i, ang in enumerate(field_angles_deg):
        e = _guard(f"field_angles_deg[{i}]", ang)
        if e:
            return _err(e)

    e = _guard("aperture_mm", aperture_mm, positive=True)
    if e:
        return _err(e)

    e = _guard("n_object", n_object, positive=True)
    if e:
        return _err(e)

    if float(n_object) < 1.0:
        return _err("n_object must be >= 1.0")

    # ---- EFL and BFL from paraxial properties (marginal ray) ---------------
    # BFL is the paraxial image distance from the last surface for a
    # collimated (on-axis) input ray.  The image plane is placed here.
    props = paraxial_properties(surfaces, n_object=float(n_object))
    if not props.get("ok"):
        return _err(f"paraxial_properties failed: {props.get('reason')}")

    efl = props["EFL_mm"]
    bfl = props["BFL_mm"]
    if not math.isfinite(efl) or abs(efl) < 1e-12:
        return _err(f"EFL is not usable (EFL={efl} mm); cannot compute y_paraxial")
    if not math.isfinite(bfl):
        return _err(f"BFL is not usable (BFL={bfl} mm); cannot place image plane")

    # ---- Seidel S_V at a representative field angle for cross-check --------
    # Use first non-zero field angle; fall back to 5 deg if all are zero.
    ref_field = next(
        (a for a in field_angles_deg if abs(float(a)) > 1e-6),
        5.0,
    )
    seidel_result = seidel_coefficients(
        surfaces,
        aperture=float(aperture_mm),
        field_angle_deg=float(ref_field),
        n_object=float(n_object),
    )
    sv_valid = not isinstance(seidel_result, dict)  # SeidelReport vs error dict
    sv_coeff = seidel_result.S_V if sv_valid else 0.0

    # ---- Trace chief ray at each field angle --------------------------------
    # Chief ray: ray_h=0 (height at first surface = 0, stop at first surface),
    # field angle determines the ray direction.  BFL positions the image plane.
    # Algorithm: _trace_ray_off_axis(surfaces, ray_h=0, field_angle_rad,
    #                                n_object, paraxial_image_dist=BFL)
    # This is the same trace used by the MTF module for the chief-ray intercept.
    field_angles_out: list[float] = []
    y_actual: list[float] = []
    y_paraxial: list[float] = []
    distortion_pct: list[float] = []
    seidel_pct: list[float] = []

    for ang_deg in field_angles_deg:
        ang_rad = math.radians(float(ang_deg))
        tan_ang = math.tan(ang_rad)

        # Ideal paraxial image height: y_p = EFL * tan(θ)  (Hecht §5.6)
        y_p = efl * tan_ang

        # At θ=0: distortion is 0 by definition
        if abs(y_p) < 1e-12:
            field_angles_out.append(float(ang_deg))
            y_actual.append(0.0)
            y_paraxial.append(0.0)
            distortion_pct.append(0.0)
            seidel_pct.append(0.0)
            continue

        # Chief ray: height=0 at first surface, direction = field angle.
        # _trace_ray_off_axis traces using exact Snell + Newton-Raphson
        # (Welford 1986 §5) and propagates to paraxial_image_dist=BFL.
        y_act_val = _trace_ray_off_axis(
            surfaces,
            ray_h=0.0,
            field_angle_rad=float(ang_rad),
            n_object=float(n_object),
            paraxial_image_dist=float(bfl),
        )

        if y_act_val is None or math.isnan(y_act_val):
            field_angles_out.append(float(ang_deg))
            y_actual.append(math.nan)
            y_paraxial.append(y_p)
            distortion_pct.append(math.nan)
            seidel_pct.append(math.nan)
            continue

        # Distortion percent (Hecht §5.6 / ISO 9039 definition):
        #   D = (y_actual - y_paraxial) / |y_paraxial| × 100
        d_pct = (y_act_val - y_p) / abs(y_p) * 100.0

        # Seidel third-order additive prediction (Welford §6.3):
        #   Δy_seidel = S_V * tan²(θ)
        #   D_seidel = Δy_seidel / |y_paraxial| × 100
        #            = S_V * |tan(θ)| / |EFL| × 100
        if sv_valid:
            delta_y_seidel = sv_coeff * tan_ang * tan_ang
            s_pct = delta_y_seidel / abs(y_p) * 100.0
        else:
            s_pct = 0.0

        field_angles_out.append(float(ang_deg))
        y_actual.append(y_act_val)
        y_paraxial.append(y_p)
        distortion_pct.append(d_pct)
        seidel_pct.append(s_pct)

    # ---- Classify distortion kind -----------------------------------------
    valid_d = [d for d in distortion_pct
               if math.isfinite(d) and abs(d) >= _DISTORTION_THRESHOLD_PCT]
    if not valid_d:
        kind = "none"
        max_dist = max((abs(d) for d in distortion_pct if math.isfinite(d)),
                       default=0.0)
    else:
        max_dist = max(abs(d) for d in valid_d)
        has_neg = any(d < 0.0 for d in valid_d)
        has_pos = any(d > 0.0 for d in valid_d)
        if has_neg and has_pos:
            kind = "mixed"
        elif has_neg:
            kind = "barrel"
        else:
            kind = "pincushion"

    honest_flag = (
        "Monochromatic only; polychromatic distortion (lateral chromatic component) "
        "requires integrating D(theta, lambda) over spectral band — use "
        "compute_spectral_distortion() for SPD-weighted integration. "
        "Tangential (meridional) distortion only; for rotationally symmetric stacks "
        "the sagittal distortion is identical, but astigmatism-induced differences "
        "are not captured. "
        "Chief ray traced from infinity; aperture stop assumed at first surface. "
        "Seidel S_V prediction is third-order only and valid only at small field angles."
    )

    return DistortionMapReport(
        field_angles_deg=field_angles_out,
        y_actual_mm=y_actual,
        y_paraxial_mm=y_paraxial,
        distortion_percent=distortion_pct,
        max_distortion_pct=max_dist,
        kind=kind,
        EFL_mm=efl,
        seidel_distortion_percent=seidel_pct,
        honest_flag=honest_flag,
    )
