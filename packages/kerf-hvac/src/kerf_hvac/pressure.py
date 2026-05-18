"""pressure.py — HVAC pressure-drop calculations.

Implements:

1. **Darcy-Weisbach major loss** (friction pressure drop) for straight duct runs.
2. **Colebrook-White** friction factor (exact iterative solver) for transitional /
   turbulent flow; laminar flow handled analytically.
3. **ASHRAE minor-loss coefficients** (C coefficients, i.e. K factors) for common
   duct fittings.
4. A convenience function ``minor_loss`` that converts a velocity-pressure and K
   into a pressure drop.

All quantities in SI:
  - Lengths: metres (m)
  - Pressure: Pascals (Pa)
  - Velocity: m/s
  - Density: kg/m³
  - Dynamic viscosity: Pa·s

Reference: ASHRAE Handbook of Fundamentals (2021), Chapter 21 (Duct Design).
           ASHRAE HVAC Systems & Equipment Handbook (2020), Chapter 16.
"""

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Air properties (standard conditions: 20 °C, 101.325 kPa)
# ---------------------------------------------------------------------------

AIR_DENSITY_KG_M3 = 1.204      # kg/m³ at 20 °C
AIR_DYNAMIC_VISCOSITY_PA_S = 1.81e-5  # Pa·s at 20 °C


# ---------------------------------------------------------------------------
# ASHRAE minor-loss K coefficients for common fittings
# ---------------------------------------------------------------------------

# 90° rectangular elbow (radius, with turning vanes, W:H ~ 1:1)
# ASHRAE HOF 2021 Table 8, Fitting ED5-1: K ≈ 0.20–0.35 range
# Midpoint value (no turning vanes, R/W = 1.0): K ≈ 0.30
ELBOW_90_RECT_K: float = 0.30

# 90° round duct elbow (smooth bend, R/D = 1.5)
# ASHRAE CR1-2: K ≈ 0.11
ELBOW_90_ROUND_K: float = 0.11

# 45° rectangular elbow (half-turn)
ELBOW_45_RECT_K: float = 0.15

# Tee — main through-flow branch
# ASHRAE Figure 6-17 (diverging tee, straight-through): K ≈ 0.10
TEE_MAIN_K: float = 0.10

# Tee — branch takeoff
# ASHRAE Figure 6-17 (diverging tee, branch at 90°): K ≈ 0.90
TEE_BRANCH_K: float = 0.90

# Reducer / transition (concentric, 15° half-angle)
REDUCER_K: float = 0.04

# Abrupt contraction (sharp-edged inlet)
CONTRACTION_SHARP_K: float = 0.50

# Abrupt expansion (Borda-Carnot)
# K is defined relative to upstream velocity pressure; value depends on area ratio
# This is the coefficient used when A2 >> A1: K ≈ 1.0
EXPANSION_ABRUPT_K: float = 1.0

# Duct terminal / end cap
CAP_K: float = 1.0

# Round flex duct section (per metre at full extension)
FLEX_PER_METRE_K: float = 0.50


# ---------------------------------------------------------------------------
# Friction factor — Colebrook-White iterative solver
# ---------------------------------------------------------------------------

def friction_factor(
    reynolds: float,
    relative_roughness: float,
    tol: float = 1e-8,
    max_iter: int = 100,
) -> float:
    """Compute the Darcy-Weisbach friction factor f.

    Uses the analytical formula for laminar flow (Re < 2300) and the
    Colebrook-White equation solved by the Halley / fixed-point iteration
    for turbulent flow.

    Args:
        reynolds: Reynolds number (dimensionless, must be > 0).
        relative_roughness: ε/D (dimensionless).
        tol: Convergence tolerance for f (default 1e-8).
        max_iter: Maximum iterations (default 100).

    Returns:
        Darcy friction factor f (dimensionless).
    """
    if reynolds <= 0:
        raise ValueError("Reynolds number must be positive")

    # Laminar regime
    if reynolds < 2300:
        return 64.0 / reynolds

    # Turbulent: Colebrook-White
    # 1/√f = -2 log10(ε/(3.7 D) + 2.51/(Re √f))
    # Initial guess: Swamee-Jain approximation
    eps_D = relative_roughness
    if eps_D == 0.0:
        # Smooth duct: use Filonenko formula
        f = (0.790 * math.log(reynolds) - 1.640) ** -2
    else:
        # Swamee-Jain
        f = 0.25 / (math.log10(eps_D / 3.7 + 5.74 / reynolds ** 0.9)) ** 2

    for _ in range(max_iter):
        lhs = 1.0 / math.sqrt(f)
        rhs_inner = eps_D / 3.7 + 2.51 / (reynolds * math.sqrt(f))
        rhs = -2.0 * math.log10(rhs_inner)
        f_new = (1.0 / rhs) ** 2
        if abs(f_new - f) < tol:
            return f_new
        f = f_new

    return f  # return best estimate if not converged


# ---------------------------------------------------------------------------
# Darcy-Weisbach pressure loss
# ---------------------------------------------------------------------------

def darcy_weisbach_loss(
    velocity_m_s: float,
    hydraulic_diameter_m: float,
    length_m: float,
    roughness_m: float = 0.09e-3,
    density_kg_m3: float = AIR_DENSITY_KG_M3,
    dynamic_viscosity_pa_s: float = AIR_DYNAMIC_VISCOSITY_PA_S,
) -> float:
    """Compute pressure drop (Pa) for a straight duct run.

    Uses the Darcy-Weisbach equation:

        ΔP = f · (L / D_h) · (ρ · v² / 2)

    where f is the Darcy friction factor from Colebrook-White.

    Args:
        velocity_m_s: Mean flow velocity (m/s).
        hydraulic_diameter_m: Hydraulic diameter D_h (m).
        length_m: Duct run length (m).
        roughness_m: Absolute roughness ε (m).  Default 0.09 mm (galvanised steel).
        density_kg_m3: Air density (kg/m³).  Default 1.204 kg/m³ at 20 °C.
        dynamic_viscosity_pa_s: Dynamic viscosity (Pa·s).  Default 1.81×10⁻⁵.

    Returns:
        Pressure drop ΔP in Pascals (Pa).
    """
    if velocity_m_s <= 0:
        raise ValueError("velocity_m_s must be positive")
    if hydraulic_diameter_m <= 0:
        raise ValueError("hydraulic_diameter_m must be positive")
    if length_m < 0:
        raise ValueError("length_m must be non-negative")
    if roughness_m < 0:
        raise ValueError("roughness_m must be non-negative")

    if length_m == 0.0:
        return 0.0

    re = density_kg_m3 * velocity_m_s * hydraulic_diameter_m / dynamic_viscosity_pa_s
    eps_D = roughness_m / hydraulic_diameter_m
    f = friction_factor(re, eps_D)

    dynamic_pressure = 0.5 * density_kg_m3 * velocity_m_s ** 2
    return f * (length_m / hydraulic_diameter_m) * dynamic_pressure


# ---------------------------------------------------------------------------
# Minor losses
# ---------------------------------------------------------------------------

def velocity_pressure(
    velocity_m_s: float,
    density_kg_m3: float = AIR_DENSITY_KG_M3,
) -> float:
    """Dynamic (velocity) pressure in Pascals: P_v = ρ v² / 2."""
    return 0.5 * density_kg_m3 * velocity_m_s ** 2


def minor_loss(
    velocity_m_s: float,
    k_coefficient: float,
    density_kg_m3: float = AIR_DENSITY_KG_M3,
) -> float:
    """Compute minor pressure loss for a fitting.

    ΔP_minor = K · P_v = K · (ρ v² / 2)

    Args:
        velocity_m_s: Mean approach velocity (m/s).
        k_coefficient: Loss coefficient K (dimensionless).
        density_kg_m3: Air density (kg/m³).

    Returns:
        Pressure loss in Pascals (Pa).
    """
    return k_coefficient * velocity_pressure(velocity_m_s, density_kg_m3)


# ---------------------------------------------------------------------------
# System pressure loss (combined major + minor)
# ---------------------------------------------------------------------------

def total_duct_loss(
    velocity_m_s: float,
    hydraulic_diameter_m: float,
    length_m: float,
    fittings_k: list[float] | None = None,
    roughness_m: float = 0.09e-3,
    density_kg_m3: float = AIR_DENSITY_KG_M3,
    dynamic_viscosity_pa_s: float = AIR_DYNAMIC_VISCOSITY_PA_S,
) -> dict[str, float]:
    """Compute total pressure loss for a duct section including fittings.

    Args:
        velocity_m_s: Mean flow velocity (m/s).
        hydraulic_diameter_m: Hydraulic diameter D_h (m).
        length_m: Straight run length (m).
        fittings_k: List of K coefficients for fittings in this section.
        roughness_m: Absolute roughness ε (m).
        density_kg_m3: Air density (kg/m³).
        dynamic_viscosity_pa_s: Dynamic viscosity (Pa·s).

    Returns:
        Dict with keys:
          - ``friction_pa``: Major (friction) pressure drop.
          - ``fittings_pa``: Minor (fitting) pressure drop.
          - ``total_pa``: Sum of both.
          - ``velocity_pressure_pa``: Dynamic pressure.
          - ``friction_factor``: Darcy friction factor f.
    """
    fittings_k = fittings_k or []
    friction = darcy_weisbach_loss(
        velocity_m_s, hydraulic_diameter_m, length_m, roughness_m, density_kg_m3, dynamic_viscosity_pa_s
    )
    fittings = sum(minor_loss(velocity_m_s, k, density_kg_m3) for k in fittings_k)
    pv = velocity_pressure(velocity_m_s, density_kg_m3)
    re = density_kg_m3 * velocity_m_s * hydraulic_diameter_m / dynamic_viscosity_pa_s
    eps_D = roughness_m / hydraulic_diameter_m
    f = friction_factor(re, eps_D)
    return {
        "friction_pa": friction,
        "fittings_pa": fittings,
        "total_pa": friction + fittings,
        "velocity_pressure_pa": pv,
        "friction_factor": f,
    }
