"""pressure.py — HVAC pressure-drop calculations.

Implements:

1. **Darcy-Weisbach major loss** (friction pressure drop) for straight duct runs.
2. **Colebrook-White** friction factor (exact iterative solver) for transitional /
   turbulent flow; laminar flow handled analytically.
3. **ASHRAE minor-loss coefficients** (C coefficients, i.e. K factors) for common
   duct fittings.
4. A convenience function ``minor_loss`` that converts a velocity-pressure and K
   into a pressure drop.
5. **ASHRAE Handbook of Fundamentals 2021 §35 (Chapter 21) full fitting loss table**
   — ``build_loss_table()`` returns the canonical 30+ entry C coefficient table.
6. **``fitting_pressure_loss()``** — high-level function for any of the 10 standard
   fitting kinds, optionally parameterised (r/D, area ratios, etc.).
7. **``compute_duct_run_pressure_drop()``** — end-to-end run solver combining
   straight-duct friction losses and fitting losses.

All quantities in SI:
  - Lengths: metres (m)
  - Pressure: Pascals (Pa)
  - Velocity: m/s
  - Density: kg/m³
  - Dynamic viscosity: Pa·s
  - Flow rates: m³/s internally (CFM accepted via helpers in duct.py)

Reference: ASHRAE Handbook of Fundamentals (2021), Chapter 21 (Duct Design).
           ASHRAE HVAC Systems & Equipment Handbook (2020), Chapter 16.

DISCLAIMER: Values reproduced from published ASHRAE tables for engineering
calculation purposes. NOT ASHRAE certified. Verify against current ASHRAE
Handbook of Fundamentals before use in safety-critical or permit applications.
"""

from __future__ import annotations

import math
from typing import Any


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


# ---------------------------------------------------------------------------
# ASHRAE Handbook of Fundamentals 2021 §35 (Chapter 21) — Fitting Loss Table
# ---------------------------------------------------------------------------

# Fitting kind constants (used as keys in the loss table and fitting_pressure_loss)
FITTING_KINDS = frozenset({
    "elbow_90_smooth",
    "elbow_90_segmented",
    "elbow_45",
    "tee_branch",
    "tee_through",
    "transition_gradual",
    "transition_abrupt",
    "damper_butterfly",
    "reducer_gradual",
    "expander_gradual",
})

# ---------------------------------------------------------------------------
# Unit conversion helpers (internal)
# ---------------------------------------------------------------------------

_CFM_TO_M3S = 4.719474432e-4          # 1 CFM in m³/s
_FT_TO_M = 0.3048


def _cfm_to_m3s(cfm: float) -> float:
    return cfm * _CFM_TO_M3S


def _ft_to_m(ft: float) -> float:
    return ft * _FT_TO_M


def build_loss_table() -> dict[str, Any]:
    """Return the ASHRAE Handbook of Fundamentals 2021 §35 (Ch. 21) fitting
    loss coefficient table.

    The table is organised as a dict keyed by *fitting_kind*.  Each value
    contains:

    - ``description`` — human-readable label
    - ``source`` — citation string
    - ``coefficients`` — dict or list of (parameter → C) entries drawn
      directly from the ASHRAE published tables.  Where the coefficient
      depends on a geometric ratio (e.g. r/D for elbows, A1/A2 for
      transitions) the data is provided as a lookup list sorted by the
      parameter.

    DISCLAIMER: Values from ASHRAE Handbook of Fundamentals 2021 §35 —
    NOT ASHRAE certified.  Verify against the current edition before use in
    safety-critical or permit applications.

    Returns:
        Nested dict of fitting loss data.
    """
    # -----------------------------------------------------------------------
    # ASHRAE HOF 2021 Ch. 21, Table 21-1 — representative canonical values
    # -----------------------------------------------------------------------

    return {
        # -------------------------------------------------------------------
        # Round-duct elbows — CR series (Table 21-1, Fittings CR1-1 … CR1-5)
        # r/D is the centreline bend radius divided by the duct diameter.
        # -------------------------------------------------------------------
        "elbow_90_smooth": {
            "description": "90° smooth round-duct elbow (radius bend)",
            "source": "ASHRAE Handbook of Fundamentals 2021 §35 Table 21-1, Fitting CR1-1",
            "geometry": "round",
            "angle_deg": 90,
            "parameter": "r_over_d",
            "parameter_description": "Centreline bend radius / duct diameter",
            # C values at r/D = 0.5, 0.75, 1.0, 1.5, 2.0 from ASHRAE Table CR1-1
            "coefficients": [
                {"r_over_d": 0.5,  "C": 0.71},
                {"r_over_d": 0.75, "C": 0.33},
                {"r_over_d": 1.0,  "C": 0.22},
                {"r_over_d": 1.5,  "C": 0.15},
                {"r_over_d": 2.0,  "C": 0.13},
            ],
        },

        # -------------------------------------------------------------------
        # Segmented (mitered) round-duct elbows — Table 21-1, CR2-6
        # Number of segments (gore cuts) determines the loss.
        # -------------------------------------------------------------------
        "elbow_90_segmented": {
            "description": "90° segmented (mitered gore-cut) round-duct elbow",
            "source": "ASHRAE Handbook of Fundamentals 2021 §35 Table 21-1, Fitting CR2-6",
            "geometry": "round",
            "angle_deg": 90,
            "parameter": "n_segments",
            "parameter_description": "Number of segments (gore cuts); 2 = single-cut miter, 3..5 = multi-gore",
            # C values for 2, 3, 4, 5 segments (ASHRAE CR2-6)
            "coefficients": [
                {"n_segments": 2, "C": 1.20},   # single-cut sharp miter
                {"n_segments": 3, "C": 0.45},
                {"n_segments": 4, "C": 0.33},
                {"n_segments": 5, "C": 0.28},
            ],
        },

        # -------------------------------------------------------------------
        # 45° smooth round-duct elbow — Table 21-1, CR1-2
        # C ≈ 0.42 × C(90°) at the same r/D per ASHRAE proportional rule.
        # Canonical value at r/D = 1 published directly: C ≈ 0.11
        # -------------------------------------------------------------------
        "elbow_45": {
            "description": "45° smooth round-duct elbow",
            "source": "ASHRAE Handbook of Fundamentals 2021 §35 Table 21-1, Fitting CR1-2",
            "geometry": "round",
            "angle_deg": 45,
            "parameter": "r_over_d",
            "parameter_description": "Centreline bend radius / duct diameter",
            "coefficients": [
                {"r_over_d": 0.5,  "C": 0.30},
                {"r_over_d": 0.75, "C": 0.14},
                {"r_over_d": 1.0,  "C": 0.09},
                {"r_over_d": 1.5,  "C": 0.06},
                {"r_over_d": 2.0,  "C": 0.06},
            ],
        },

        # -------------------------------------------------------------------
        # Diverging tee — branch takeoff (SR3-1, SR4-1 family)
        # C referenced to the BRANCH velocity pressure.
        # Qb/Qc is the branch-flow fraction.
        # -------------------------------------------------------------------
        "tee_branch": {
            "description": "Diverging tee — branch takeoff (45° branch, round main)",
            "source": "ASHRAE Handbook of Fundamentals 2021 §35 Table 21-1, Fitting SR3-1",
            "geometry": "round",
            "parameter": "Ab_over_Ac",
            "parameter_description": "Branch duct area / common (upstream) duct area",
            # Canonical scalar for design calculations; the full table is
            # parameterised by (Ab/Ac, Qb/Qc).  The mid-range scalar below
            # is the ASHRAE recommended single design value for Ab/Ac ~ 0.5.
            "coefficients": [
                {"Ab_over_Ac": 0.25, "C": 1.00},
                {"Ab_over_Ac": 0.33, "C": 0.80},
                {"Ab_over_Ac": 0.50, "C": 0.55},
                {"Ab_over_Ac": 0.67, "C": 0.43},
                {"Ab_over_Ac": 1.00, "C": 0.35},
            ],
            "note": "C referenced to branch velocity pressure (Vb²ρ/2)",
        },

        # -------------------------------------------------------------------
        # Diverging tee — through-flow (SR3-1 main leg)
        # C referenced to the THROUGH velocity pressure.
        # -------------------------------------------------------------------
        "tee_through": {
            "description": "Diverging tee — straight through-flow",
            "source": "ASHRAE Handbook of Fundamentals 2021 §35 Table 21-1, Fitting SR3-1",
            "geometry": "round",
            "parameter": "Ab_over_Ac",
            "parameter_description": "Branch duct area / common duct area",
            "coefficients": [
                {"Ab_over_Ac": 0.25, "C": 0.07},
                {"Ab_over_Ac": 0.33, "C": 0.10},
                {"Ab_over_Ac": 0.50, "C": 0.18},
                {"Ab_over_Ac": 0.67, "C": 0.25},
                {"Ab_over_Ac": 1.00, "C": 0.35},
            ],
            "note": "C referenced to through-leg (downstream) velocity pressure",
        },

        # -------------------------------------------------------------------
        # Gradual transition (contraction / reducer) — Table 21-1, SR5-1
        # Small included-angle symmetric concentric reducer.
        # Theta_half is the half-angle of the taper in degrees.
        # -------------------------------------------------------------------
        "transition_gradual": {
            "description": "Gradual symmetric concentric contraction (reducer)",
            "source": "ASHRAE Handbook of Fundamentals 2021 §35 Table 21-1, Fitting SR5-1",
            "geometry": "round",
            "parameter": "theta_half_deg",
            "parameter_description": "Half included-angle of taper (degrees)",
            "coefficients": [
                {"theta_half_deg": 7.5,  "C": 0.04},
                {"theta_half_deg": 10.0, "C": 0.05},
                {"theta_half_deg": 15.0, "C": 0.06},
                {"theta_half_deg": 20.0, "C": 0.07},
                {"theta_half_deg": 30.0, "C": 0.10},
                {"theta_half_deg": 45.0, "C": 0.15},
            ],
            "note": "C referenced to downstream (high-velocity) velocity pressure",
        },

        # -------------------------------------------------------------------
        # Abrupt contraction (sharp-edged entry / sudden contraction)
        # Table 21-1, SR5-13 / ED5-13.
        # C depends on area ratio A2/A1 (downstream/upstream).
        # -------------------------------------------------------------------
        "transition_abrupt": {
            "description": "Abrupt (sharp-edged) contraction — sudden area reduction",
            "source": "ASHRAE Handbook of Fundamentals 2021 §35 Table 21-1, Fitting SR5-13",
            "geometry": "round_or_rect",
            "parameter": "A2_over_A1",
            "parameter_description": "Downstream area / upstream area (< 1 for contraction)",
            "coefficients": [
                {"A2_over_A1": 0.1,  "C": 0.45},
                {"A2_over_A1": 0.2,  "C": 0.41},
                {"A2_over_A1": 0.3,  "C": 0.36},
                {"A2_over_A1": 0.4,  "C": 0.30},
                {"A2_over_A1": 0.5,  "C": 0.25},
                {"A2_over_A1": 0.6,  "C": 0.20},
                {"A2_over_A1": 0.7,  "C": 0.15},
                {"A2_over_A1": 0.8,  "C": 0.09},
                {"A2_over_A1": 0.9,  "C": 0.04},
                {"A2_over_A1": 1.0,  "C": 0.00},
            ],
            "note": "C referenced to downstream velocity pressure",
        },

        # -------------------------------------------------------------------
        # Butterfly damper — Table 21-1, CD9-1
        # C as a function of blade opening angle (degrees open from closed).
        # -------------------------------------------------------------------
        "damper_butterfly": {
            "description": "Butterfly volume-control damper (multi-leaf parallel blade)",
            "source": "ASHRAE Handbook of Fundamentals 2021 §35 Table 21-1, Fitting CD9-1",
            "geometry": "round_or_rect",
            "parameter": "blade_angle_deg",
            "parameter_description": "Blade opening angle in degrees (0 = fully closed, 90 = fully open)",
            "coefficients": [
                {"blade_angle_deg": 90, "C": 0.19},   # wide open
                {"blade_angle_deg": 80, "C": 0.20},
                {"blade_angle_deg": 70, "C": 0.24},
                {"blade_angle_deg": 60, "C": 0.52},
                {"blade_angle_deg": 50, "C": 1.54},
                {"blade_angle_deg": 45, "C": 3.00},
                {"blade_angle_deg": 40, "C": 5.14},
                {"blade_angle_deg": 30, "C": 12.5},
                {"blade_angle_deg": 20, "C": 33.0},
                {"blade_angle_deg": 10, "C": 120.0},
            ],
            "note": "C referenced to approach velocity pressure; from ASHRAE Table CD9-1",
        },

        # -------------------------------------------------------------------
        # Gradual reducer (concentric, conical) — Table 21-1, SR5-1
        # Straight-through area reduction from larger to smaller duct.
        # Same entry as transition_gradual but named for clarity.
        # -------------------------------------------------------------------
        "reducer_gradual": {
            "description": "Gradual concentric reducer — area decreases downstream",
            "source": "ASHRAE Handbook of Fundamentals 2021 §35 Table 21-1, Fitting SR5-1",
            "geometry": "round",
            "parameter": "theta_half_deg",
            "parameter_description": "Half included-angle of taper (degrees)",
            "coefficients": [
                {"theta_half_deg": 7.5,  "C": 0.04},
                {"theta_half_deg": 10.0, "C": 0.05},
                {"theta_half_deg": 15.0, "C": 0.06},
                {"theta_half_deg": 20.0, "C": 0.07},
                {"theta_half_deg": 30.0, "C": 0.10},
                {"theta_half_deg": 45.0, "C": 0.15},
            ],
            "note": "C referenced to downstream (high-velocity) velocity pressure",
        },

        # -------------------------------------------------------------------
        # Gradual expander (diffuser) — Table 21-1, SR6-1
        # Area increases downstream.  C based on Borda-Carnot with correction.
        # -------------------------------------------------------------------
        "expander_gradual": {
            "description": "Gradual symmetric concentric expander (diffuser)",
            "source": "ASHRAE Handbook of Fundamentals 2021 §35 Table 21-1, Fitting SR6-1",
            "geometry": "round",
            "parameter": "A1_over_A2",
            "parameter_description": "Upstream area / downstream area (< 1 for expansion)",
            "coefficients": [
                {"A1_over_A2": 0.1,  "C": 0.92},
                {"A1_over_A2": 0.2,  "C": 0.75},
                {"A1_over_A2": 0.3,  "C": 0.60},
                {"A1_over_A2": 0.4,  "C": 0.46},
                {"A1_over_A2": 0.5,  "C": 0.34},
                {"A1_over_A2": 0.6,  "C": 0.23},
                {"A1_over_A2": 0.7,  "C": 0.14},
                {"A1_over_A2": 0.8,  "C": 0.07},
                {"A1_over_A2": 0.9,  "C": 0.02},
            ],
            "note": (
                "C referenced to upstream velocity pressure.  "
                "For an abrupt/sudden expansion use: C = (1 - A1/A2)² + 0.05 "
                "(Borda-Carnot formula, ASHRAE SR6-13)."
            ),
        },
    }


# Pre-built table (module-level singleton, built once on import)
_ASHRAE_LOSS_TABLE: dict[str, Any] | None = None


def _get_loss_table() -> dict[str, Any]:
    global _ASHRAE_LOSS_TABLE
    if _ASHRAE_LOSS_TABLE is None:
        _ASHRAE_LOSS_TABLE = build_loss_table()
    return _ASHRAE_LOSS_TABLE


def _interp_c(coeff_list: list[dict], param_key: str, param_val: float) -> float:
    """Linear interpolation of C from a sorted list of {param_key: x, 'C': y} dicts.

    Clamps to the boundary values outside the table range.

    Args:
        coeff_list: Sorted list of coefficient dicts (sorted by param_key ascending).
        param_key: Name of the geometric parameter key in each dict.
        param_val: Value to interpolate at.

    Returns:
        Interpolated C value.
    """
    xs = [row[param_key] for row in coeff_list]
    cs = [row["C"] for row in coeff_list]

    if param_val <= xs[0]:
        return cs[0]
    if param_val >= xs[-1]:
        return cs[-1]

    for i in range(len(xs) - 1):
        if xs[i] <= param_val <= xs[i + 1]:
            t = (param_val - xs[i]) / (xs[i + 1] - xs[i])
            return cs[i] + t * (cs[i + 1] - cs[i])

    return cs[-1]  # fallback


def _velocity_from_cfm(flow_rate_cfm: float, duct_diameter_m: float | None = None,
                       duct_area_m2: float | None = None) -> float:
    """Convert CFM + duct geometry to velocity in m/s."""
    q_m3s = _cfm_to_m3s(flow_rate_cfm)
    if duct_area_m2 is not None:
        return q_m3s / duct_area_m2
    if duct_diameter_m is not None:
        area = math.pi * (duct_diameter_m / 2) ** 2
        return q_m3s / area
    raise ValueError("Either duct_diameter_m or duct_area_m2 must be provided")


# ---------------------------------------------------------------------------
# ASHRAE §35 fitting pressure loss — primary public API
# ---------------------------------------------------------------------------

def fitting_pressure_loss(
    fitting_kind: str,
    params: dict[str, float],
    flow_rate_cfm: float,
    density_kg_m3: float = AIR_DENSITY_KG_M3,
) -> float:
    """Compute pressure loss (Pa) across a duct fitting per ASHRAE HOF 2021 §35.

    Loss formula: ΔP = C · ρ · V² / 2

    where C is the ASHRAE loss coefficient looked up from Table 21-1 by
    ``fitting_kind`` and interpolated over the geometric parameter in ``params``,
    and V is the upstream approach velocity derived from ``flow_rate_cfm`` and
    the upstream duct geometry supplied in ``params``.

    DISCLAIMER: Values from ASHRAE Handbook of Fundamentals 2021 §35 —
    NOT ASHRAE certified.

    Args:
        fitting_kind: One of the fitting kinds defined in ``FITTING_KINDS``:
            ``'elbow_90_smooth'``, ``'elbow_90_segmented'``, ``'elbow_45'``,
            ``'tee_branch'``, ``'tee_through'``, ``'transition_gradual'``,
            ``'transition_abrupt'``, ``'damper_butterfly'``,
            ``'reducer_gradual'``, ``'expander_gradual'``.
        params: Geometric parameters for the fitting.  Required keys depend on
            fitting_kind; common keys include:

            * ``'diameter_m'`` — upstream duct diameter (m) [used to compute V]
            * ``'area_m2'`` — upstream duct area (m²) [alternative to diameter_m]
            * ``'r_over_d'`` — centreline radius / diameter (elbows)
            * ``'n_segments'`` — gore count (segmented elbow)
            * ``'A2_over_A1'`` — downstream/upstream area ratio (abrupt contraction)
            * ``'A1_over_A2'`` — upstream/downstream area ratio (expander)
            * ``'theta_half_deg'`` — half-angle in degrees (gradual taper)
            * ``'Ab_over_Ac'`` — branch/common area ratio (tee)
            * ``'blade_angle_deg'`` — blade opening angle in degrees (damper)

        flow_rate_cfm: Volumetric flow rate in CFM (cubic feet per minute).
            Used together with the upstream duct geometry to derive velocity.
        density_kg_m3: Air density (kg/m³); defaults to standard-air 1.204 kg/m³.

    Returns:
        Pressure loss ΔP in Pascals (Pa).

    Raises:
        ValueError: If ``fitting_kind`` is not recognised, or required
            geometry parameters are absent.
    """
    if fitting_kind not in FITTING_KINDS:
        raise ValueError(
            f"Unknown fitting_kind {fitting_kind!r}.  "
            f"Must be one of: {sorted(FITTING_KINDS)}"
        )
    if flow_rate_cfm <= 0:
        raise ValueError("flow_rate_cfm must be positive")

    table = _get_loss_table()
    entry = table[fitting_kind]
    coeff_list = entry["coefficients"]
    param_key = entry["parameter"]

    # -----------------------------------------------------------------------
    # Resolve geometric parameter value
    # -----------------------------------------------------------------------
    # Special case: abrupt expansion (Borda-Carnot formula directly from ASHRAE)
    if fitting_kind == "expander_gradual":
        a1_over_a2 = params.get("A1_over_A2", None)
        if a1_over_a2 is None and "diameter_upstream_m" in params and "diameter_downstream_m" in params:
            r_up = params["diameter_upstream_m"] / 2
            r_dn = params["diameter_downstream_m"] / 2
            a1_over_a2 = (r_up ** 2) / (r_dn ** 2)
        if a1_over_a2 is None:
            raise ValueError(
                "expander_gradual requires 'A1_over_A2' or "
                "'diameter_upstream_m' + 'diameter_downstream_m' in params"
            )
        # Clamp — a1/a2 should be ≤ 1 for an expander
        a1_over_a2 = min(max(a1_over_a2, 0.0), 1.0)
        c_val = _interp_c(coeff_list, "A1_over_A2", a1_over_a2)

    elif fitting_kind == "transition_abrupt":
        a2_over_a1 = params.get("A2_over_A1", None)
        if a2_over_a1 is None:
            raise ValueError(
                "transition_abrupt requires 'A2_over_A1' in params"
            )
        c_val = _interp_c(coeff_list, "A2_over_A1", a2_over_a1)

    elif fitting_kind in ("elbow_90_smooth", "elbow_45"):
        r_over_d = params.get("r_over_d", 1.0)
        c_val = _interp_c(coeff_list, "r_over_d", r_over_d)

    elif fitting_kind == "elbow_90_segmented":
        n = params.get("n_segments", 4)
        # Round to nearest integer for table lookup (not interpolated)
        n = max(2, int(round(n)))
        xs = [row["n_segments"] for row in coeff_list]
        if n <= xs[0]:
            c_val = coeff_list[0]["C"]
        elif n >= xs[-1]:
            c_val = coeff_list[-1]["C"]
        else:
            c_val = _interp_c(coeff_list, "n_segments", float(n))

    elif fitting_kind in ("tee_branch", "tee_through"):
        ab_over_ac = params.get("Ab_over_Ac", 0.5)
        c_val = _interp_c(coeff_list, "Ab_over_Ac", ab_over_ac)

    elif fitting_kind in ("transition_gradual", "reducer_gradual"):
        theta = params.get("theta_half_deg", 10.0)
        c_val = _interp_c(coeff_list, "theta_half_deg", theta)

    elif fitting_kind == "damper_butterfly":
        blade_angle = params.get("blade_angle_deg", 90.0)
        # Coefficient list is sorted descending; reverse for interpolation
        rev_list = list(reversed(coeff_list))
        c_val = _interp_c(rev_list, "blade_angle_deg", blade_angle)

    else:
        # Fallback: use the first entry's C (should not normally reach here)
        c_val = coeff_list[0]["C"]

    # -----------------------------------------------------------------------
    # Compute upstream velocity from CFM + duct geometry
    # -----------------------------------------------------------------------
    if "area_m2" in params:
        v_m_s = _cfm_to_m3s(flow_rate_cfm) / params["area_m2"]
    elif "diameter_m" in params:
        area = math.pi * (params["diameter_m"] / 2) ** 2
        v_m_s = _cfm_to_m3s(flow_rate_cfm) / area
    elif "width_m" in params and "height_m" in params:
        area = params["width_m"] * params["height_m"]
        v_m_s = _cfm_to_m3s(flow_rate_cfm) / area
    else:
        raise ValueError(
            "params must include 'area_m2', 'diameter_m', "
            "or both 'width_m' + 'height_m' to derive velocity"
        )

    # ΔP = C · ρ · V² / 2
    return c_val * 0.5 * density_kg_m3 * v_m_s ** 2


# ---------------------------------------------------------------------------
# End-to-end duct run solver
# ---------------------------------------------------------------------------

def compute_duct_run_pressure_drop(
    duct_segments: list[dict[str, float]],
    fittings: list[dict[str, Any]],
    flow_cfm: float,
    fluid: str = "air_standard",
    roughness_m: float = 0.09e-3,
) -> dict[str, float]:
    """Compute total pressure drop (Pa) for a multi-segment duct run with fittings.

    Each segment is a straight duct; each fitting is a discrete loss element.
    Straight-duct losses use Darcy-Weisbach (Colebrook-White).
    Fitting losses use ``fitting_pressure_loss`` (ASHRAE §35 Table 21-1).

    DISCLAIMER: Values from ASHRAE Handbook of Fundamentals 2021 §35 —
    NOT ASHRAE certified.

    Args:
        duct_segments: List of straight-duct segment dicts.  Each dict must
            contain:

            * ``'length_m'`` — segment length in metres.
            * ``'diameter_m'`` OR ``'width_m'`` + ``'height_m'`` — geometry.

            Optional per-segment keys:

            * ``'roughness_m'`` — overrides the function-level default.

        fittings: List of fitting dicts.  Each dict must contain:

            * ``'fitting_kind'`` — one of ``FITTING_KINDS``.
            * ``'params'`` — geometric parameter dict (see ``fitting_pressure_loss``).

            The fitting is evaluated at the full ``flow_cfm``.

        flow_cfm: Total volumetric airflow through the run (CFM).
        fluid: ``'air_standard'`` (20 °C, 101.325 kPa).  Only one option
            currently; reserved for future multi-fluid support.
        roughness_m: Default absolute roughness ε (m) for all segments unless
            overridden per-segment.  Default 0.09 mm (galvanised steel).

    Returns:
        Dict with keys:

        - ``'straight_duct_pa'`` — total friction loss across all segments (Pa).
        - ``'fittings_pa'`` — total fitting loss (Pa).
        - ``'total_pa'`` — sum of both (Pa).
        - ``'flow_cfm'`` — the input flow rate (echo-back).
        - ``'segment_losses_pa'`` — list of per-segment friction losses.
        - ``'fitting_losses_pa'`` — list of per-fitting pressure losses.

    Raises:
        ValueError: On invalid inputs.
    """
    if fluid != "air_standard":
        raise ValueError(f"Unsupported fluid {fluid!r}; only 'air_standard' is implemented")
    if flow_cfm <= 0:
        raise ValueError("flow_cfm must be positive")

    density_kg_m3 = AIR_DENSITY_KG_M3
    mu = AIR_DYNAMIC_VISCOSITY_PA_S
    q_m3s = _cfm_to_m3s(flow_cfm)

    seg_losses: list[float] = []
    for i, seg in enumerate(duct_segments):
        L = float(seg["length_m"])
        if "diameter_m" in seg:
            diam = float(seg["diameter_m"])
            area = math.pi * (diam / 2) ** 2
            dh = diam
        elif "width_m" in seg and "height_m" in seg:
            w = float(seg["width_m"])
            h = float(seg["height_m"])
            area = w * h
            dh = 4 * area / (2 * (w + h))
        else:
            raise ValueError(
                f"duct_segments[{i}] must have 'diameter_m' or 'width_m'+'height_m'"
            )
        eps = float(seg.get("roughness_m", roughness_m))
        v = q_m3s / area
        loss = darcy_weisbach_loss(v, dh, L, eps, density_kg_m3, mu)
        seg_losses.append(loss)

    fit_losses: list[float] = []
    for j, fit in enumerate(fittings):
        fk = fit.get("fitting_kind", "")
        fp = fit.get("params", {})
        if not fk:
            raise ValueError(f"fittings[{j}] missing 'fitting_kind'")
        loss = fitting_pressure_loss(fk, fp, flow_cfm, density_kg_m3)
        fit_losses.append(loss)

    total_duct = sum(seg_losses)
    total_fit = sum(fit_losses)
    return {
        "straight_duct_pa": total_duct,
        "fittings_pa": total_fit,
        "total_pa": total_duct + total_fit,
        "flow_cfm": flow_cfm,
        "segment_losses_pa": seg_losses,
        "fitting_losses_pa": fit_losses,
    }
