"""
U.S. Standard Atmosphere 1976 model.

Covers altitudes from 0 to 86 km using the defined geopotential layer
structure with piecewise lapse rates and isothermal layers.

Reference: NOAA/NASA/USAF U.S. Standard Atmosphere, 1976.
"""

from __future__ import annotations

import math
from typing import NamedTuple


# Universal gas constant (J/mol/K)
_R_STAR: float = 8.31432

# Molar mass of dry air (kg/mol)
_M0: float = 0.0289644

# Specific gas constant for dry air (J/kg/K)
_R: float = _R_STAR / _M0  # 287.05287...

# Standard sea-level gravity (m/s²)
_G0: float = 9.80665

# Earth radius (m) — used to convert geometric to geopotential altitude
_R_EARTH: float = 6356766.0

# Ratio used in geopotential conversion
_K: float = _R_EARTH / (_R_EARTH + 1.0)  # updated per loop below

# Sutherland's constants for dynamic viscosity
_BETA_S: float = 1.458e-6   # kg/(m·s·K^0.5)
_S_SUTH: float = 110.4       # K

# Specific heat ratio for dry air
_GAMMA: float = 1.4

# Layer table: (base geopotential altitude m, base temperature K, lapse rate K/m)
# Layers as defined in USSA76 Table 4
_LAYERS: list[tuple[float, float, float]] = [
    (0.0,      288.15,  -0.0065),   # Troposphere
    (11_000.0, 216.65,   0.0),      # Tropopause (isothermal)
    (20_000.0, 216.65,   0.001),    # Stratosphere-1
    (32_000.0, 228.65,   0.0028),   # Stratosphere-2
    (47_000.0, 270.65,   0.0),      # Stratopause (isothermal)
    (51_000.0, 270.65,  -0.0028),   # Mesosphere-1
    (71_000.0, 214.65,  -0.002),    # Mesosphere-2
    (86_000.0, 186.87,   0.0),      # Mesopause sentinel
]

# Pre-compute base pressures for each layer using hydrostatic equation.
# Populated at module import time.
_BASE_PRESSURES: list[float] = []


def _compute_base_pressures() -> list[float]:
    pressures = [101325.0]  # P0 at sea level
    for i in range(1, len(_LAYERS)):
        h_b, T_b, L_b = _LAYERS[i - 1]
        h_next, _, _ = _LAYERS[i]
        P_b = pressures[i - 1]
        delta_h = h_next - h_b
        if L_b == 0.0:
            # Isothermal layer
            P_next = P_b * math.exp(-_G0 * delta_h / (_R * T_b))
        else:
            P_next = P_b * (T_b / (T_b + L_b * delta_h)) ** (_G0 / (_R * L_b))
        pressures.append(P_next)
    return pressures


_BASE_PRESSURES = _compute_base_pressures()


class AtmosphereState(NamedTuple):
    """Atmospheric state at a given altitude."""
    temperature_K: float
    pressure_Pa: float
    density_kg_m3: float
    speed_of_sound_m_s: float
    viscosity_Pa_s: float


def geometric_to_geopotential(h_geom_m: float) -> float:
    """Convert geometric altitude (m) to geopotential altitude (m)."""
    return (_R_EARTH * h_geom_m) / (_R_EARTH + h_geom_m)


def atmosphere(altitude_m: float, geometric: bool = True) -> AtmosphereState:
    """
    Compute U.S. Standard Atmosphere 1976 properties at the given altitude.

    Parameters
    ----------
    altitude_m:
        Altitude in metres. Geometric by default; set ``geometric=False``
        to pass a geopotential altitude directly.
    geometric:
        If True (default), treat *altitude_m* as geometric and convert
        internally to geopotential.

    Returns
    -------
    AtmosphereState
        Named tuple with temperature, pressure, density, speed of sound,
        and dynamic viscosity.
    """
    if altitude_m < 0.0:
        raise ValueError(f"Altitude must be >= 0 m, got {altitude_m}")
    if altitude_m > 86_000.0:
        raise ValueError(f"Altitude must be <= 86 000 m, got {altitude_m}")

    # Work in geopotential altitude
    h: float = geometric_to_geopotential(altitude_m) if geometric else altitude_m

    # Find the layer
    layer_idx = 0
    for i in range(len(_LAYERS) - 1):
        if h >= _LAYERS[i][0]:
            layer_idx = i
        else:
            break

    h_b, T_b, L_b = _LAYERS[layer_idx]
    P_b = _BASE_PRESSURES[layer_idx]
    delta_h = h - h_b

    # Temperature
    T = T_b + L_b * delta_h

    # Pressure
    if L_b == 0.0:
        P = P_b * math.exp(-_G0 * delta_h / (_R * T_b))
    else:
        P = P_b * (T_b / T) ** (_G0 / (_R * L_b))

    # Density from ideal gas law: ρ = P / (R·T)
    rho = P / (_R * T)

    # Speed of sound: a = sqrt(γ·R·T)
    a = math.sqrt(_GAMMA * _R * T)

    # Dynamic viscosity via Sutherland's formula
    mu = _BETA_S * T**1.5 / (T + _S_SUTH)

    return AtmosphereState(
        temperature_K=T,
        pressure_Pa=P,
        density_kg_m3=rho,
        speed_of_sound_m_s=a,
        viscosity_Pa_s=mu,
    )


def mach_number(true_airspeed_m_s: float, altitude_m: float, geometric: bool = True) -> float:
    """Return Mach number given true airspeed and altitude."""
    state = atmosphere(altitude_m, geometric=geometric)
    return true_airspeed_m_s / state.speed_of_sound_m_s


def dynamic_pressure(true_airspeed_m_s: float, altitude_m: float, geometric: bool = True) -> float:
    """Return dynamic pressure q = 0.5·ρ·V² (Pa)."""
    rho = atmosphere(altitude_m, geometric=geometric).density_kg_m3
    return 0.5 * rho * true_airspeed_m_s**2
