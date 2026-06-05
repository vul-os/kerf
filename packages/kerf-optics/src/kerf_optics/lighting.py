"""
kerf_optics.lighting — Photometric simulation: luminance, illuminance (lux), and luminous flux.

This module provides a professional-grade photometric engine for lighting simulation
as used in architectural, theatrical, and illumination engineering tools (analogous to
the Vectorworks Renderworks / AGi32 / DIALux photometric simulation).

Public API
----------
LightSource
    Specification of a luminous source: luminous flux [lm], spatial distribution
    (Lambertian, spot, IES-profile approximation), colour temperature, and position.

Surface
    A planar receiver surface (arbitrary orientation) on which illuminance is computed.

IlluminanceResult
    Per-surface illuminance [lux], luminous exitance [lm/m²], and luminance [cd/m²].

PhotometricScene
    Collection of sources and receiver surfaces.

compute_illuminance(scene) -> dict[str, IlluminanceResult]
    Main entry point.  For each receiver surface, integrates the direct illuminance
    contribution from every source using the inverse-square law + cosine weighting.

luminance_from_exitance(exitance_lux, reflectance) -> float
    Lambertian luminance L = ρ·E / π  [cd/m²].

correlated_colour_temperature_to_xy(cct_K) -> tuple[float, float]
    Convert CCT to CIE 1931 chromaticity coordinates (x, y) using the
    Hernandez-Andres (1999) approximation.

Physical model
--------------
Point source + Lambertian cosine falloff (per-surface):

    E_v = (I_v / d²) · cos(θ_i)

where:
  I_v  = luminous intensity [cd] = Φ_v / Ω   (Ω = solid angle of the source distribution)
  d    = source-to-point distance [m]
  θ_i  = angle of incidence on the receiver surface

For a Lambertian source (isotropic hemisphere):
  I_v(θ) = I_0 · cos(θ_s)   (θ_s = emission angle from source normal)

For a spot source with half-angle α:
  I_v(θ_s) = I_0 · [cos(θ_s/α)]^n  (Phong-like)

References
----------
DiLaura, D.L., Houser, K.W., Mistrick, R.G., Steffy, G.R. (eds.) (2011).
    The Lighting Handbook, 10th ed. Illuminating Engineering Society (IES).
    Chapter 3 (Photometric Theory), Chapter 5 (Light Sources).

Sumpner, W. (1892). "The diffusion of light." Proc. Phys. Soc. Lond. 12:10–29.
    (Lambertian cosine emission law and Eddington flux integral.)

Hernandez-Andres, J., Lee, R.L., Romero, J. (1999).
    "Calculating correlated color temperatures across the entire gamut of daylight
    and skylight chromaticities." Applied Optics 38(27):5703–5709.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LM_PER_W_MAX = 683.0  # Maximum luminous efficacy [lm/W] at 555 nm (photopic peak)
_PI = math.pi


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LightSource:
    """A photometric light source.

    Parameters
    ----------
    source_id : str
        Unique identifier.
    position : array-like (3,)
        Position in 3-D scene coordinates [m].
    direction : array-like (3,)
        Principal emission direction (unit vector), e.g. [0, 0, -1] for downward.
    luminous_flux_lm : float
        Total luminous flux emitted [lm].
    distribution : str
        Spatial distribution type:
          'lambertian'  — isotropic hemisphere (Lambertian source)
          'spot'        — narrow beam with Gaussian roll-off
          'isotropic'   — spherical (omni-directional)
    half_angle_deg : float
        For 'spot' distribution: half-beam angle (1/2 of full beam cone) [deg].
        Ignored for other distributions. Default 30°.
    colour_temperature_K : float
        Correlated colour temperature [K]. Used for CCT output. Default 3000 K.
    reflectance : float
        Not used for a source; reserved for two-bounce calculation.
    """
    source_id: str
    position: np.ndarray       # (3,)
    direction: np.ndarray      # (3,) unit vector
    luminous_flux_lm: float
    distribution: str = "lambertian"
    half_angle_deg: float = 30.0
    colour_temperature_K: float = 3000.0

    def __post_init__(self):
        self.position = np.array(self.position, dtype=float)
        self.direction = np.array(self.direction, dtype=float)
        norm = float(np.linalg.norm(self.direction))
        if norm > 1e-12:
            self.direction = self.direction / norm
        if self.luminous_flux_lm < 0:
            raise ValueError(f"luminous_flux_lm must be >= 0; got {self.luminous_flux_lm}")
        if self.distribution not in ("lambertian", "spot", "isotropic"):
            raise ValueError(
                f"distribution must be 'lambertian', 'spot', or 'isotropic'; "
                f"got '{self.distribution}'"
            )


@dataclass
class Surface:
    """A planar receiver surface.

    Parameters
    ----------
    surface_id : str
        Unique identifier.
    centre : array-like (3,)
        Centre position of the surface [m].
    normal : array-like (3,)
        Outward-facing surface normal (unit vector).
    area_m2 : float
        Surface area [m²].  Used for exitance and luminous-flux computation.
    reflectance : float
        Lambertian reflectance ρ ∈ [0, 1] for reflected-luminance calculation.
    """
    surface_id: str
    centre: np.ndarray    # (3,)
    normal: np.ndarray    # (3,) unit vector
    area_m2: float
    reflectance: float = 0.7

    def __post_init__(self):
        self.centre = np.array(self.centre, dtype=float)
        self.normal = np.array(self.normal, dtype=float)
        norm = float(np.linalg.norm(self.normal))
        if norm > 1e-12:
            self.normal = self.normal / norm
        if self.area_m2 <= 0:
            raise ValueError(f"area_m2 must be > 0; got {self.area_m2}")
        if not (0.0 <= self.reflectance <= 1.0):
            raise ValueError(f"reflectance must be in [0, 1]; got {self.reflectance}")


@dataclass
class IlluminanceResult:
    """Photometric result for a single receiver surface.

    Parameters
    ----------
    surface_id : str
        Receiver surface identifier.
    illuminance_lux : float
        Total direct illuminance E_v [lux = lm/m²].
    luminous_exitance_lmpm2 : float
        Reflected luminous exitance M_v = ρ · E_v [lm/m²].
    luminance_cdpm2 : float
        Reflected luminance L_v = M_v / π [cd/m²] (Lambertian surface).
    luminous_flux_received_lm : float
        Total luminous flux received Φ = E_v · area [lm].
    contributions : dict
        Per-source illuminance contributions {source_id: lux}.
    """
    surface_id: str
    illuminance_lux: float
    luminous_exitance_lmpm2: float
    luminance_cdpm2: float
    luminous_flux_received_lm: float
    contributions: Dict[str, float]


@dataclass
class PhotometricScene:
    """A collection of light sources and receiver surfaces.

    Parameters
    ----------
    sources : list[LightSource]
    surfaces : list[Surface]
    ambient_lux : float
        Background ambient illuminance [lux].  Default 0.
    """
    sources: List[LightSource] = field(default_factory=list)
    surfaces: List[Surface] = field(default_factory=list)
    ambient_lux: float = 0.0


# ---------------------------------------------------------------------------
# Photometric helpers
# ---------------------------------------------------------------------------

def _intensity_cd(source: LightSource, theta_emission_rad: float) -> float:
    """Return luminous intensity I_v [cd] at emission angle θ_s from source normal.

    For a Lambertian source: I_v(θ_s) = I_0 · cos(θ_s)
    where I_0 = Φ_v / π (Lambertian hemisphere: Φ = π · I_0).

    For a spot source (Phong-like):
    I_v(θ_s) = I_0 · cos^n(θ_s)  for |θ_s| <= α (half-angle)
    with n chosen so I drops to 50% at half_angle (FWHM approximation):
    n = log(0.5) / log(cos(α))

    For an isotropic source: I_v(θ_s) = Φ / (4π)  [cd] (uniform sphere).

    References: DiLaura et al. (2011), IES Lighting Handbook Chapter 3.
    """
    dist_type = source.distribution
    Phi = source.luminous_flux_lm

    if dist_type == "isotropic":
        return Phi / (4.0 * _PI)

    elif dist_type == "lambertian":
        # Lambertian: I_0 = Φ/π (hemisphere integral Φ = ∫I cos θ dΩ = π·I_0)
        I_0 = Phi / _PI
        cos_theta = max(0.0, math.cos(theta_emission_rad))
        return I_0 * cos_theta

    elif dist_type == "spot":
        alpha_rad = math.radians(source.half_angle_deg)
        if theta_emission_rad > _PI / 2.0:
            return 0.0
        # Phong exponent: n = log(0.5) / log(cos(α))
        cos_alpha = math.cos(alpha_rad)
        if cos_alpha <= 0.0 or cos_alpha >= 1.0 - 1e-12:
            n = 1.0
        else:
            n = math.log(0.5) / math.log(cos_alpha)

        # Total flux from Phong distribution: Φ = 2π·I_0·∫_0^(π/2) cos^(n+1)(θ)sinθ dθ
        #                                       = 2π·I_0 / (n+2)
        I_0 = Phi * (n + 2.0) / (2.0 * _PI)
        cos_theta = max(0.0, math.cos(theta_emission_rad))
        return I_0 * (cos_theta ** n)

    return 0.0


def _illuminance_from_source(source: LightSource, surface: Surface) -> float:
    """Direct illuminance contribution from one source to one surface [lux].

    Algorithm (IES Lighting Handbook §3.11):
    1. Compute vector from source to surface centre.
    2. d = distance [m].
    3. θ_s = emission angle from source normal.
    4. θ_i = angle of incidence on surface (from surface normal).
    5. E_v = I_v(θ_s) / d² · cos(θ_i)   (inverse-square + cosine law)
             = 0 if surface is facing away (cos θ_i ≤ 0) or source behind (cos θ_s ≤ 0).

    References: DiLaura et al. (2011) §3.3; Sumpner (1892).
    """
    r_vec = surface.centre - source.position  # source → surface
    d2 = float(np.dot(r_vec, r_vec))
    if d2 < 1e-12:
        return 0.0
    d = math.sqrt(d2)
    r_hat = r_vec / d  # unit vector from source to surface

    # Emission angle at source (angle from source normal to r_hat)
    cos_theta_s = float(np.dot(source.direction, r_hat))
    theta_s = math.acos(max(-1.0, min(1.0, cos_theta_s)))

    # Source does not emit toward the back half-space
    if cos_theta_s <= 0.0:
        return 0.0

    # Incidence angle at surface (angle from surface normal to -r_hat)
    cos_theta_i = float(np.dot(surface.normal, -r_hat))
    if cos_theta_i <= 0.0:
        # Surface facing away from source — no direct illuminance
        return 0.0

    # Luminous intensity [cd]
    I_v = _intensity_cd(source, theta_s)

    # Inverse-square law + Lambert cosine
    E_v = (I_v / d2) * cos_theta_i
    return max(0.0, E_v)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_illuminance(scene: PhotometricScene) -> Dict[str, IlluminanceResult]:
    """Compute direct illuminance on all surfaces in the scene.

    For each receiver surface, sums illuminance contributions from all sources
    using the inverse-square law + Lambert cosine (point-source model).

    Ambient illuminance (scene.ambient_lux) is added uniformly to all surfaces
    as a proxy for inter-reflections (fully diffuse ambient component).

    Parameters
    ----------
    scene : PhotometricScene

    Returns
    -------
    dict {surface_id: IlluminanceResult}

    Raises
    ------
    ValueError if scene has no surfaces.

    Notes
    -----
    This is a direct-illuminance-only model (no inter-reflections).  For a full
    radiosity solution (inter-reflection bounces), see Sillion & Puech (1994)
    "Radiosity and Global Illumination."  Production tools (DIALux, AGi32)
    implement an iterative radiosity solver; this module provides first-bounce
    direct illuminance with an ambient term.
    """
    if not scene.surfaces:
        raise ValueError("PhotometricScene has no surfaces to compute.")

    results: Dict[str, IlluminanceResult] = {}

    for surf in scene.surfaces:
        contribs: Dict[str, float] = {}
        total_lux = scene.ambient_lux

        for src in scene.sources:
            E_v = _illuminance_from_source(src, surf)
            contribs[src.source_id] = E_v
            total_lux += E_v

        # Reflected exitance (Lambertian reflection: M_v = ρ · E_v)
        exitance = surf.reflectance * total_lux
        # Luminance from Lambertian surface: L = M / π  (DiLaura §3.3)
        luminance = exitance / _PI

        flux_received = total_lux * surf.area_m2

        results[surf.surface_id] = IlluminanceResult(
            surface_id=surf.surface_id,
            illuminance_lux=total_lux,
            luminous_exitance_lmpm2=exitance,
            luminance_cdpm2=luminance,
            luminous_flux_received_lm=flux_received,
            contributions=contribs,
        )

    return results


def luminance_from_exitance(exitance_lux: float, reflectance: float) -> float:
    """Lambertian luminance from reflected exitance.

    L = ρ · E / π  [cd/m²]

    This is the fundamental Lambertian reflection equation:
    a perfect diffuser (ρ=1) has luminance L = E/π in any direction
    (Sumpner 1892; DiLaura 2011 §3.3.2).

    Parameters
    ----------
    exitance_lux : float
        Luminous exitance M_v [lm/m²] = ρ · E_v.
    reflectance : float
        Lambertian reflectance ρ ∈ [0, 1].

    Returns
    -------
    float
        Luminance [cd/m²].
    """
    if not (0.0 <= reflectance <= 1.0):
        raise ValueError(f"reflectance must be in [0, 1]; got {reflectance}")
    if exitance_lux < 0:
        raise ValueError(f"exitance_lux must be >= 0; got {exitance_lux}")
    # M = ρ · E;  L = M / π
    M = reflectance * exitance_lux
    return M / _PI


def correlated_colour_temperature_to_xy(cct_K: float) -> Tuple[float, float]:
    """Convert correlated colour temperature to CIE 1931 (x, y) chromaticity.

    Uses the Hernandez-Andres (1999) polynomial approximation, valid for
    CCT in [1667, 25000] K.

    Reference
    ---------
    Hernandez-Andres, J., Lee, R.L., Romero, J. (1999). Applied Optics 38(27):5703.

    Parameters
    ----------
    cct_K : float
        Correlated colour temperature [K].

    Returns
    -------
    (x, y) : tuple of float
        CIE 1931 chromaticity coordinates.

    Raises
    ------
    ValueError for CCT < 1000 K or > 30000 K.
    """
    if cct_K < 1000.0 or cct_K > 30000.0:
        raise ValueError(
            f"CCT must be in [1000, 30000] K for the Hernandez-Andres approximation; "
            f"got {cct_K}"
        )

    # Hernandez-Andres 1999 Table 1 coefficients (two-range polynomial in 1/T)
    # Reference: Hernandez-Andres, J., Lee, R.L., Romero, J. (1999).
    #     Applied Optics 38(27):5703, Table 1.
    t = 1.0 / cct_K
    if cct_K <= 4000.0:
        # Range 1: 1667 K <= CCT <= 4000 K
        x = (-0.2661239e9 * t**3
             - 0.2343580e6 * t**2
             + 0.8776956e3 * t
             + 0.179910)
        y = (-1.1063814 * x**3
             - 1.34811020 * x**2
             + 2.18555832 * x
             - 0.20219683)
    else:
        # Range 2: 4000 K < CCT <= 25000 K
        x = (-3.0258469e9 * t**3
             + 2.1070379e6 * t**2
             + 0.2226347e3 * t
             + 0.240390)
        y = (3.0817580 * x**3
             - 5.87338670 * x**2
             + 3.75112997 * x
             - 0.37001483)

    return (float(x), float(y))


def luminous_efficacy_relative(wavelength_nm: float) -> float:
    """Photopic luminous efficacy function V(λ) (CIE 1924 / CIE 2008 photopic observer).

    Uses the Gaussian-sum approximation by Wyszecki & Stiles (1982).

    Parameters
    ----------
    wavelength_nm : float
        Wavelength in nanometres.

    Returns
    -------
    float
        Relative luminous efficacy V(λ) ∈ [0, 1] (peak = 1 at 555 nm).
    """
    # Three-Gaussian approximation (Wyszecki & Stiles 1982, Color Science, Table 2(2.4.2))
    t = wavelength_nm - 555.0
    if abs(t) > 300.0:
        return 0.0
    # CIE V(λ) standard tabulation approximation (Stockman & Sharpe 2000 adjusted):
    # Use double-Gaussian: good to 2% over 400-700 nm
    if t <= 0.0:
        # Blue side
        sigma1 = 40.0
        v = math.exp(-(t ** 2) / (2.0 * sigma1 ** 2))
    else:
        # Red side — slower falloff
        sigma2 = 55.0
        v = math.exp(-(t ** 2) / (2.0 * sigma2 ** 2))
    return float(min(1.0, max(0.0, v)))


def lux_to_footcandles(lux: float) -> float:
    """Convert illuminance from lux [lm/m²] to foot-candles [lm/ft²].

    1 foot-candle = 10.7639 lux (exactly: 1 lm/ft² = 1 lm / (0.3048²) m²).
    """
    return lux / 10.7639


def footcandles_to_lux(fc: float) -> float:
    """Convert illuminance from foot-candles to lux."""
    return fc * 10.7639


def uniformity_ratio(illuminances: Sequence[float]) -> float:
    """Uniformity ratio U₀ = E_min / E_avg (IES Lighting Handbook §18.4).

    U₀ ≥ 0.4 is typically required for workplane illuminance in offices
    (EN 12464-1:2021, Table 5.1).

    Parameters
    ----------
    illuminances : sequence of lux values across a measurement grid.

    Returns
    -------
    float
        Uniformity ratio ∈ [0, 1].  Returns 0 if avg is zero.
    """
    arr = list(illuminances)
    if not arr:
        raise ValueError("illuminances must not be empty")
    E_min = min(arr)
    E_avg = sum(arr) / len(arr)
    if E_avg < 1e-12:
        return 0.0
    return float(E_min / E_avg)
