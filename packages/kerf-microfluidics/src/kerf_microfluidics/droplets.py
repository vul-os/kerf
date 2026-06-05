"""
Droplet-generation physics for digital microfluidics.

Implements:
  - T-junction droplet size (squeezing + dripping regimes)
  - Flow-focusing droplet size (PDMS geometry)
  - Droplet spacing and generation frequency
  - Capillary number and Weber number utilities
  - Rayleigh-Plateau instability breakup length

References
----------
van Steijn, V., Kleijn, C. R., & Kreutzer, M. T. (2010).
    Predictive model for the size of bubbles and droplets created in
    microfluidic T-junctions.  *Lab on a Chip*, 10(19), 2513–2518.
    https://doi.org/10.1039/c002625e

Garstecki, P., Fuerstman, M. J., Stone, H. A., & Whitesides, G. M. (2006).
    Formation of droplets and bubbles in a microfluidic T-junction —
    scaling and mechanism of break-up.  *Lab on a Chip*, 6(3), 437–446.
    https://doi.org/10.1039/b510841a

Anna, S. L., Bontoux, N., & Stone, H. A. (2003).
    Formation of dispersions using "flow focusing" in microchannels.
    *Applied Physics Letters*, 82(3), 364–366.
    https://doi.org/10.1063/1.1537519

Rayleigh, J. W. S. (1878).
    On the instability of jets.
    *Proceedings of the London Mathematical Society*, 10, 4–13.

DISCLAIMER
----------
These models are published analytical correlations — NOT certified for
medical-device, IVD, or safety-critical use.  Results must be validated
against fabricated device measurements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Named result types
# ---------------------------------------------------------------------------

@dataclass
class TJunctionDroplet:
    """Output of :func:`t_junction_droplet_size`."""
    droplet_length_m: float
    """Expected droplet length (m) measured along the main channel."""
    droplet_volume_m3: float
    """Estimated droplet volume (m³) = length × cross-section area."""
    generation_frequency_hz: float
    """Droplet production rate (Hz)."""
    spacing_m: float
    """Centre-to-centre droplet spacing in the outlet channel (m)."""
    capillary_number: float
    """Continuous-phase capillary number Ca = μ_c Q_c / (γ w_c h)."""
    regime: str
    """'squeezing' (Ca < 0.01) or 'dripping' (Ca ≥ 0.01)."""
    model: str
    """Citation for the correlation used."""


@dataclass
class FlowFocusingDroplet:
    """Output of :func:`flow_focusing_droplet_size`."""
    droplet_diameter_m: float
    """Expected droplet diameter (m)."""
    droplet_volume_m3: float
    """Estimated droplet volume (m³) = π/6 · d³."""
    generation_frequency_hz: float
    """Droplet production rate (Hz)."""
    capillary_number: float
    """Ca = μ_c Q_c / (γ h²)."""
    model: str


@dataclass
class RayleighPlateauResult:
    """Output of :func:`rayleigh_plateau_breakup`."""
    most_unstable_wavelength_m: float
    """Wavelength of maximum growth λ_max ≈ 9.02 r₀ (Rayleigh 1878)."""
    breakup_time_s: float
    """e-folding growth time τ = (ρ r₀³ / γ)^½ / σ_max where σ_max is the
    maximum growth rate from the full dispersion relation."""
    droplet_diameter_m: float
    """Estimated droplet diameter from mass conservation: d ≈ 1.89 r₀."""
    thread_radius_m: float
    """Input thread radius r₀ (m)."""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def capillary_number(
    viscosity_pa_s: float,
    flow_rate_m3s: float,
    width_m: float,
    height_m: float,
    surface_tension_n_per_m: float,
) -> float:
    """
    Capillary number for a rectangular microchannel.

    Ca = μ U / γ  where U = Q / (w·h) is the mean velocity.

    Parameters
    ----------
    viscosity_pa_s : float
        Dynamic viscosity of the continuous phase [Pa·s].
    flow_rate_m3s : float
        Volumetric flow rate of continuous phase [m³/s].
    width_m : float
        Channel width [m].
    height_m : float
        Channel height [m].
    surface_tension_n_per_m : float
        Interfacial tension [N/m].

    Returns
    -------
    float
        Capillary number Ca (dimensionless).
    """
    if viscosity_pa_s <= 0:
        raise ValueError("viscosity_pa_s must be positive")
    if flow_rate_m3s < 0:
        raise ValueError("flow_rate_m3s must be >= 0")
    if width_m <= 0 or height_m <= 0:
        raise ValueError("width_m and height_m must be positive")
    if surface_tension_n_per_m <= 0:
        raise ValueError("surface_tension_n_per_m must be positive")

    U = flow_rate_m3s / (width_m * height_m)
    return viscosity_pa_s * U / surface_tension_n_per_m


def weber_number(
    density_kg_m3: float,
    flow_rate_m3s: float,
    width_m: float,
    height_m: float,
    surface_tension_n_per_m: float,
) -> float:
    """
    Weber number We = ρ U² L / γ  (L = hydraulic diameter D_h = 2wh/(w+h)).

    Parameters
    ----------
    density_kg_m3 : float
        Density of continuous phase [kg/m³].
    flow_rate_m3s : float
        Volumetric flow rate [m³/s].
    width_m : float
        Channel width [m].
    height_m : float
        Channel height [m].
    surface_tension_n_per_m : float
        Interfacial tension [N/m].

    Returns
    -------
    float
        Weber number We (dimensionless).
    """
    if density_kg_m3 <= 0:
        raise ValueError("density_kg_m3 must be positive")
    U = flow_rate_m3s / (width_m * height_m)
    D_h = 2.0 * width_m * height_m / (width_m + height_m)
    return density_kg_m3 * U**2 * D_h / surface_tension_n_per_m


# ---------------------------------------------------------------------------
# T-junction droplet size
# ---------------------------------------------------------------------------

def t_junction_droplet_size(
    q_continuous_ul_min: float,
    q_dispersed_ul_min: float,
    channel_width_m: float,
    channel_height_m: float,
    dispersed_channel_width_m: float,
    viscosity_continuous_pa_s: float,
    surface_tension_n_per_m: float,
    *,
    alpha: float = 1.0,
    beta: float = 1.0,
) -> TJunctionDroplet:
    """
    Predict droplet length from a T-junction using the Garstecki 2006 /
    van Steijn 2010 models.

    **Squeezing regime** (Ca < 0.01, geometry-dominated):

        L / w_c = α + β (Q_d / Q_c)                 [Garstecki 2006 eq. 1]

    where w_c is the outlet channel width, Q_d/Q_c is the flow ratio,
    and α, β ≈ 1.0 for square-ish channels.

    **Dripping regime** (Ca ≥ 0.01, viscous-dominated):

        L / w_c = α                                  [Garstecki 2006 eq. 2]

    For both regimes the droplet volume is estimated as L × w_c × h
    (block slug geometry).

    Parameters
    ----------
    q_continuous_ul_min : float
        Continuous-phase flow rate [µL/min].
    q_dispersed_ul_min : float
        Dispersed-phase (drop) flow rate [µL/min].
    channel_width_m : float
        Outlet channel width w_c [m].
    channel_height_m : float
        Channel height h [m] (same for all arms).
    dispersed_channel_width_m : float
        Dispersed-phase inlet arm width w_d [m].
    viscosity_continuous_pa_s : float
        Continuous-phase dynamic viscosity [Pa·s].
    surface_tension_n_per_m : float
        Interfacial tension γ [N/m].
    alpha : float
        Empirical prefactor (default 1.0 for square channels).
        Garstecki 2006 Table 1: α ≈ 1 for w_d/w_c ≈ 1.
    beta : float
        Empirical slope coefficient (default 1.0).

    Returns
    -------
    TJunctionDroplet
    """
    _UL_MIN_TO_M3S = 1e-9 / 60.0

    if q_continuous_ul_min <= 0:
        raise ValueError("q_continuous_ul_min must be positive")
    if q_dispersed_ul_min <= 0:
        raise ValueError("q_dispersed_ul_min must be positive")
    if channel_width_m <= 0 or channel_height_m <= 0:
        raise ValueError("channel dimensions must be positive")
    if dispersed_channel_width_m <= 0:
        raise ValueError("dispersed_channel_width_m must be positive")
    if viscosity_continuous_pa_s <= 0 or surface_tension_n_per_m <= 0:
        raise ValueError("viscosity and surface tension must be positive")

    Q_c = q_continuous_ul_min * _UL_MIN_TO_M3S
    Q_d = q_dispersed_ul_min * _UL_MIN_TO_M3S

    Ca = capillary_number(
        viscosity_continuous_pa_s, Q_c,
        channel_width_m, channel_height_m,
        surface_tension_n_per_m,
    )

    flow_ratio = Q_d / Q_c

    if Ca < 0.01:
        # Squeezing regime — Garstecki 2006 eq. 1
        L_norm = alpha + beta * flow_ratio
        regime = "squeezing"
        model = "Garstecki 2006 Lab Chip 6:437 eq.1 (squeezing)"
    else:
        # Dripping regime — Garstecki 2006 eq. 2
        # Droplet size governed by viscous + surface-tension balance; weak flow ratio.
        # van Steijn 2010 gives a refined expression including Ca^(1/3) corrections.
        # Here we use the simple Garstecki limit plus the van Steijn leading correction:
        #   L/w_c ≈ α(Ca)^{-1/3} * (Q_d/Q_c)^{2/3}   [van Steijn 2010 eq. 6]
        L_norm = alpha * Ca**(-1.0 / 3.0) * flow_ratio**(2.0 / 3.0)
        regime = "dripping"
        model = "van Steijn 2010 Lab Chip 10:2513 eq.6 (dripping)"

    droplet_length_m = L_norm * channel_width_m

    # Volume: slug approximates as rectangular block of length L, width w_c, height h
    cross_section_m2 = channel_width_m * channel_height_m
    droplet_volume_m3 = droplet_length_m * cross_section_m2

    # Plug moves at velocity ≈ Q_total / cross_section
    Q_total = Q_c + Q_d
    U_plug = Q_total / cross_section_m2

    # Generation frequency: f = U_plug / (L + gap); gap ≈ 0 in squeezing, small in dripping
    # A widely used approximation is f ≈ Q_total / V_droplet
    generation_frequency_hz = Q_total / droplet_volume_m3

    # Centre-to-centre spacing (distance plug travels per generation cycle)
    spacing_m = U_plug / generation_frequency_hz

    return TJunctionDroplet(
        droplet_length_m=droplet_length_m,
        droplet_volume_m3=droplet_volume_m3,
        generation_frequency_hz=generation_frequency_hz,
        spacing_m=spacing_m,
        capillary_number=Ca,
        regime=regime,
        model=model,
    )


# ---------------------------------------------------------------------------
# Flow-focusing droplet size
# ---------------------------------------------------------------------------

def flow_focusing_droplet_size(
    q_continuous_ul_min: float,
    q_dispersed_ul_min: float,
    orifice_width_m: float,
    orifice_height_m: float,
    viscosity_continuous_pa_s: float,
    surface_tension_n_per_m: float,
    *,
    k_ff: float = 0.4,
) -> FlowFocusingDroplet:
    """
    Predict droplet diameter from a flow-focusing device.

    Anna et al. (2003) showed that in the stable dripping regime:

        d / h ≈ k_ff · (Q_d / Q_c)^(1/2)

    where h is the orifice height and k_ff ≈ 0.4 for PDMS devices.

    Parameters
    ----------
    q_continuous_ul_min : float
        Continuous-phase flow rate [µL/min].
    q_dispersed_ul_min : float
        Dispersed-phase flow rate [µL/min].
    orifice_width_m : float
        Orifice width [m].
    orifice_height_m : float
        Orifice height [m] (characteristic dimension).
    viscosity_continuous_pa_s : float
        Continuous-phase dynamic viscosity [Pa·s].
    surface_tension_n_per_m : float
        Interfacial tension γ [N/m].
    k_ff : float
        Empirical prefactor (Anna 2003, default 0.4).

    Returns
    -------
    FlowFocusingDroplet
    """
    _UL_MIN_TO_M3S = 1e-9 / 60.0

    if q_continuous_ul_min <= 0 or q_dispersed_ul_min <= 0:
        raise ValueError("flow rates must be positive")
    if orifice_width_m <= 0 or orifice_height_m <= 0:
        raise ValueError("orifice dimensions must be positive")
    if viscosity_continuous_pa_s <= 0 or surface_tension_n_per_m <= 0:
        raise ValueError("viscosity and surface tension must be positive")
    if k_ff <= 0:
        raise ValueError("k_ff must be positive")

    Q_c = q_continuous_ul_min * _UL_MIN_TO_M3S
    Q_d = q_dispersed_ul_min * _UL_MIN_TO_M3S

    Ca = capillary_number(
        viscosity_continuous_pa_s, Q_c,
        orifice_width_m, orifice_height_m,
        surface_tension_n_per_m,
    )

    flow_ratio = Q_d / Q_c
    d = k_ff * orifice_height_m * math.sqrt(flow_ratio)

    volume = math.pi / 6.0 * d**3

    Q_total = Q_c + Q_d
    frequency = Q_total / volume

    return FlowFocusingDroplet(
        droplet_diameter_m=d,
        droplet_volume_m3=volume,
        generation_frequency_hz=frequency,
        capillary_number=Ca,
        model="Anna 2003 Appl Phys Lett 82:364 (flow-focusing)",
    )


# ---------------------------------------------------------------------------
# Rayleigh-Plateau instability
# ---------------------------------------------------------------------------

def rayleigh_plateau_breakup(
    thread_radius_m: float,
    density_kg_m3: float,
    surface_tension_n_per_m: float,
) -> RayleighPlateauResult:
    """
    Estimate Rayleigh-Plateau instability breakup parameters for a liquid thread.

    The classical analysis (Rayleigh 1878, Chandrasekhar 1961) gives the
    dispersion relation for an inviscid cylindrical thread:

        ω² = (γ / (ρ r₀³)) · x²(1 − x²)          for x = k r₀ ∈ (0, 1)

    where ω is the growth rate and k is the wavenumber.  Maximum growth
    occurs at x_max ≈ 0.6966 (Weber 1931), giving:

        λ_max = 2π r₀ / x_max ≈ 9.02 r₀
        ω_max² = (γ / ρ r₀³) · 0.0717

    The resulting droplet diameter comes from volume conservation:
    one wavelength of thread → one droplet, so:

        (π r₀² λ_max) = (π/6) d³  →  d ≈ 1.89 r₀

    Parameters
    ----------
    thread_radius_m : float
        Initial thread radius r₀ [m].
    density_kg_m3 : float
        Thread liquid density ρ [kg/m³].
    surface_tension_n_per_m : float
        Surface tension γ [N/m].

    Returns
    -------
    RayleighPlateauResult
    """
    if thread_radius_m <= 0:
        raise ValueError("thread_radius_m must be positive")
    if density_kg_m3 <= 0:
        raise ValueError("density_kg_m3 must be positive")
    if surface_tension_n_per_m <= 0:
        raise ValueError("surface_tension_n_per_m must be positive")

    r0 = thread_radius_m
    rho = density_kg_m3
    gamma = surface_tension_n_per_m

    # Most unstable wavenumber: x_max = k r₀ ≈ 0.6966
    x_max = 0.6966
    lambda_max = 2.0 * math.pi * r0 / x_max   # ≈ 9.02 r₀

    # Maximum growth rate (inviscid Rayleigh 1878):
    # ω_max² = (γ / ρ r₀³) · x_max²(1 − x_max²)
    omega_max_sq = (gamma / (rho * r0**3)) * x_max**2 * (1.0 - x_max**2)
    omega_max = math.sqrt(omega_max_sq)
    # e-folding time (1 / ω_max)
    tau = 1.0 / omega_max

    # Droplet diameter from volume conservation (one λ of thread → one sphere)
    # π r₀² λ = π/6 d³  →  d³ = 6 r₀² λ  →  d = (6 r₀² λ)^(1/3)
    d_droplet = (6.0 * r0**2 * lambda_max) ** (1.0 / 3.0)

    return RayleighPlateauResult(
        most_unstable_wavelength_m=lambda_max,
        breakup_time_s=tau,
        droplet_diameter_m=d_droplet,
        thread_radius_m=r0,
    )
