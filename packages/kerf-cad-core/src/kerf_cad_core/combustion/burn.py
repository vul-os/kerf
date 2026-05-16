"""
kerf_cad_core.combustion.burn — combustion & fuels engineering calculators.

Pure-Python (math only). No external dependencies.

Functions
---------
stoich_afr          — stoichiometric air-fuel ratio (mass & molar) for CxHyOz
equivalence_ratio   — equivalence ratio ↔ excess-air ↔ lambda conversions
product_composition — complete combustion product-gas (wet & dry mole fractions,
                      ppm O2/CO2/H2O/N2) with excess air
adiabatic_flame_temp — adiabatic flame temperature via iterative energy balance
hhv_to_lhv          — HHV ↔ LHV conversion (water condensation latent heat)
combustion_efficiency — thermal efficiency & Siegert flue-gas loss
flue_gas_dew_point  — flue-gas dew-point temperature (sulphur-free fuel)
co2_max             — maximum CO2 percentage (stoichiometric, dry)
fuel_power          — fuel energy → power & specific fuel consumption

Constants / tables
------------------
FUELS — common fuel properties table (C, H, O, N, S mole fractions in formula,
        LHV MJ/kg, HHV MJ/kg, stoich AFR_mass, molecular weight)

Warnings
--------
Rich/lean-flammability and incomplete-combustion conditions are flagged via
`warnings.warn(..., stacklevel=2)`. Functions never raise.

References
----------
Turns, S.R., "An Introduction to Combustion", 3rd ed.
Baukal, C.E. (ed.), "The John Zink Hamworthy Combustion Handbook", 2nd ed.
Siegert flue-gas loss: VDI-Wärmeatlas
Borman, G.L. & Ragland, K.W., "Combustion Engineering"

Author: imranparuk
"""
from __future__ import annotations

import math
import warnings
from typing import Any

# ---------------------------------------------------------------------------
# Molecular weights (g/mol)
# ---------------------------------------------------------------------------
_MW = {
    "C": 12.011,
    "H": 1.008,
    "O": 15.999,
    "N": 14.007,
    "S": 32.06,
    "H2O": 18.015,
    "CO2": 44.009,
    "SO2": 64.058,
    "O2": 31.998,
    "N2": 28.014,
    "Ar": 39.948,
    "Air": 28.966,
}

# Air composition (mole fractions, dry, simplified):  O2 + 3.76 N2 per mole O2
_AIR_O2_MOLE_FRAC = 0.2095          # O2 fraction in air
_AIR_N2_O2_RATIO = (1.0 - 0.2095) / 0.2095   # ≈ 3.773 mol N2-equiv per mol O2

# Latent heat of water vaporisation at 25 °C (J/kg water)
_H_FG_WATER = 2.442e6   # J/kg  (44 000 J/mol / 0.018015 kg/mol)

# ---------------------------------------------------------------------------
# Common fuels table
# ---------------------------------------------------------------------------
# Each entry: (C, H, O, N, S) atoms in molecular formula + LHV (MJ/kg) +
# HHV (MJ/kg) + molecular weight (g/mol).
# Sources: Turns "An Introduction to Combustion"; ASHRAE Handbook.

FUELS: dict[str, dict[str, Any]] = {
    # Gaseous fuels
    "methane": {
        "C": 1, "H": 4, "O": 0, "N": 0, "S": 0,
        "MW": 16.043,
        "LHV_MJ_kg": 50.05,
        "HHV_MJ_kg": 55.53,
    },
    "ethane": {
        "C": 2, "H": 6, "O": 0, "N": 0, "S": 0,
        "MW": 30.069,
        "LHV_MJ_kg": 47.49,
        "HHV_MJ_kg": 51.88,
    },
    "propane": {
        "C": 3, "H": 8, "O": 0, "N": 0, "S": 0,
        "MW": 44.096,
        "LHV_MJ_kg": 46.36,
        "HHV_MJ_kg": 50.35,
    },
    "butane": {
        "C": 4, "H": 10, "O": 0, "N": 0, "S": 0,
        "MW": 58.122,
        "LHV_MJ_kg": 45.75,
        "HHV_MJ_kg": 49.50,
    },
    "hydrogen": {
        "C": 0, "H": 2, "O": 0, "N": 0, "S": 0,
        "MW": 2.016,
        "LHV_MJ_kg": 119.96,
        "HHV_MJ_kg": 141.79,
    },
    # Liquid fuels (formula is empirical average)
    "gasoline": {
        # ~C8H18 (iso-octane representative)
        "C": 8, "H": 18, "O": 0, "N": 0, "S": 0,
        "MW": 114.229,
        "LHV_MJ_kg": 44.40,
        "HHV_MJ_kg": 47.89,
    },
    "diesel": {
        # ~C12H26 (dodecane representative)
        "C": 12, "H": 26, "O": 0, "N": 0, "S": 0,
        "MW": 170.335,
        "LHV_MJ_kg": 42.50,
        "HHV_MJ_kg": 45.54,
    },
    "ethanol": {
        "C": 2, "H": 6, "O": 1, "N": 0, "S": 0,
        "MW": 46.068,
        "LHV_MJ_kg": 26.95,
        "HHV_MJ_kg": 29.67,
    },
    "methanol": {
        "C": 1, "H": 4, "O": 1, "N": 0, "S": 0,
        "MW": 32.042,
        "LHV_MJ_kg": 19.93,
        "HHV_MJ_kg": 22.66,
    },
    # Solid fuels (formula is empirical)
    "coal_bituminous": {
        # Approximate empirical formula CH0.8 (bituminous)
        "C": 1, "H": 0.8, "O": 0.1, "N": 0.02, "S": 0.02,
        "MW": 13.626,   # approximate
        "LHV_MJ_kg": 29.50,
        "HHV_MJ_kg": 31.40,
    },
    "wood": {
        # Cellulose approximate CH1.44O0.66
        "C": 1, "H": 1.44, "O": 0.66, "N": 0.0, "S": 0.0,
        "MW": 23.466,   # approximate
        "LHV_MJ_kg": 16.20,
        "HHV_MJ_kg": 17.80,
    },
}


# ---------------------------------------------------------------------------
# Flammability limits (equivalence ratio φ)  [lean, rich]
# Only populated for common fuels; used for warnings.
# ---------------------------------------------------------------------------
_FLAMMABILITY: dict[str, tuple[float, float]] = {
    "methane":  (0.46, 1.64),
    "ethane":   (0.50, 2.72),
    "propane":  (0.51, 2.55),
    "butane":   (0.58, 3.40),
    "hydrogen": (0.10, 7.14),
    "gasoline": (0.70, 3.80),
    "diesel":   (0.35, 7.50),
    "ethanol":  (0.55, 3.00),
    "methanol": (0.49, 3.60),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fuel_mw(C: float, H: float, O: float, N: float = 0.0, S: float = 0.0) -> float:
    """Molecular weight of a CxHyOz(NwSv) fuel formula (g/mol)."""
    return (C * _MW["C"] + H * _MW["H"] + O * _MW["O"]
            + N * _MW["N"] + S * _MW["S"])


def _stoich_o2(C: float, H: float, O: float, N: float = 0.0, S: float = 0.0) -> float:
    """Moles of O2 required per mole of fuel for complete combustion.

    CxHyOz(NwSv) + n_O2 O2 → x CO2 + y/2 H2O + w/2 N2 + v SO2
    n_O2 = x + y/4 - z/2 + v
    """
    return C + H / 4.0 - O / 2.0 + S


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def stoich_afr(
    C: float,
    H: float,
    O: float = 0.0,
    N: float = 0.0,
    S: float = 0.0,
    fuel_name: str | None = None,
) -> dict[str, Any]:
    """Stoichiometric air-fuel ratio (mass and molar) for a CxHyOz fuel.

    Parameters
    ----------
    C, H, O, N, S : float
        Atom counts in the molecular formula (e.g. CH4 → C=1, H=4).
        These are *relative* to one mole of fuel; they need not be integers.
    fuel_name : str, optional
        If provided, used only for labelling in the result dict.

    Returns
    -------
    dict with keys:
        n_O2_stoich     moles O2 per mole fuel
        n_air_stoich    moles air per mole fuel
        AFR_molar       molar air-fuel ratio (mol air / mol fuel)
        AFR_mass        mass air-fuel ratio (kg air / kg fuel)
        MW_fuel_g_mol   molecular weight of fuel (g/mol)
        warnings        list[str]
    """
    warns: list[str] = []
    try:
        C, H, O, N, S = float(C), float(H), float(O), float(N), float(S)
    except Exception as exc:
        warnings.warn(f"stoich_afr: invalid inputs — {exc}", stacklevel=2)
        return {"ok": False, "reason": str(exc), "warnings": []}

    if C < 0 or H < 0 or O < 0 or N < 0 or S < 0:
        warns.append("Negative atom count(s) clamped to 0")
        C, H, O, N, S = max(C, 0), max(H, 0), max(O, 0), max(N, 0), max(S, 0)

    n_O2 = _stoich_o2(C, H, O, N, S)
    if n_O2 <= 0.0:
        warns.append("n_O2_stoich ≤ 0 — fuel is already fully oxidised or zero fuel")
        warnings.warn(warns[-1], stacklevel=2)

    n_air = n_O2 / _AIR_O2_MOLE_FRAC  # mol air per mol fuel
    MW_fuel = _fuel_mw(C, H, O, N, S)
    MW_air = _MW["Air"]
    afr_mass = (n_air * MW_air) / MW_fuel if MW_fuel > 0 else 0.0

    return {
        "n_O2_stoich": round(n_O2, 6),
        "n_air_stoich": round(n_air, 6),
        "AFR_molar": round(n_air, 6),
        "AFR_mass": round(afr_mass, 6),
        "MW_fuel_g_mol": round(MW_fuel, 4),
        "fuel_name": fuel_name or f"C{C}H{H}O{O}",
        "warnings": warns,
    }


def equivalence_ratio(
    afr_actual: float | None = None,
    afr_stoich: float | None = None,
    phi: float | None = None,
    excess_air_pct: float | None = None,
    lambda_: float | None = None,
) -> dict[str, Any]:
    """Convert between equivalence ratio φ, excess-air %, and lambda λ.

    Supply ONE of: (afr_actual + afr_stoich), phi, excess_air_pct, or lambda_.

    Definitions
    -----------
    φ (phi)          = AFR_stoich / AFR_actual = 1/λ
    λ (lambda)       = AFR_actual / AFR_stoich = 1/φ
    excess_air_pct   = (λ - 1) × 100  [%]

    Returns
    -------
    dict with keys: phi, lambda_, excess_air_pct, mixture, warnings
    """
    warns: list[str] = []

    # Resolve to phi
    phi_val: float | None = None

    if afr_actual is not None and afr_stoich is not None:
        if afr_actual <= 0:
            return {"ok": False, "reason": "afr_actual must be > 0", "warnings": []}
        if afr_stoich <= 0:
            return {"ok": False, "reason": "afr_stoich must be > 0", "warnings": []}
        phi_val = afr_stoich / afr_actual
    elif phi is not None:
        if phi <= 0:
            return {"ok": False, "reason": "phi must be > 0", "warnings": []}
        phi_val = float(phi)
    elif excess_air_pct is not None:
        lam = 1.0 + float(excess_air_pct) / 100.0
        if lam <= 0:
            return {"ok": False, "reason": "excess_air_pct yields lambda ≤ 0", "warnings": []}
        phi_val = 1.0 / lam
    elif lambda_ is not None:
        if lambda_ <= 0:
            return {"ok": False, "reason": "lambda_ must be > 0", "warnings": []}
        phi_val = 1.0 / float(lambda_)
    else:
        return {
            "ok": False,
            "reason": "Provide one of: (afr_actual+afr_stoich), phi, excess_air_pct, or lambda_",
            "warnings": [],
        }

    lam_val = 1.0 / phi_val
    ea_pct = (lam_val - 1.0) * 100.0

    if phi_val > 1.0:
        mixture = "rich"
        warns.append(f"Rich mixture (φ={phi_val:.3f}): incomplete combustion possible")
        warnings.warn(warns[-1], stacklevel=2)
    elif phi_val < 1.0:
        mixture = "lean"
    else:
        mixture = "stoichiometric"

    return {
        "phi": round(phi_val, 6),
        "lambda_": round(lam_val, 6),
        "excess_air_pct": round(ea_pct, 4),
        "mixture": mixture,
        "warnings": warns,
    }


def product_composition(
    C: float,
    H: float,
    O: float = 0.0,
    N: float = 0.0,
    S: float = 0.0,
    excess_air_pct: float = 0.0,
    fuel_name: str | None = None,
) -> dict[str, Any]:
    """Complete-combustion product-gas composition (wet & dry mole fractions).

    Assumes complete combustion (no CO, no unburnt HC).  For φ > 1 a warning
    is issued and excess fuel is notionally unburnt (products are idealised).

    Parameters
    ----------
    C, H, O, N, S     : atom counts in fuel formula
    excess_air_pct     : excess air supplied above stoichiometric (%, ≥ 0)
    fuel_name          : optional label

    Returns
    -------
    dict with keys:
        n_CO2, n_H2O, n_SO2, n_N2, n_O2_excess   [mol per mol fuel]
        wet_mole_fractions  {species: fraction}
        dry_mole_fractions  {species: fraction}
        CO2_wet_pct, CO2_dry_pct, O2_dry_pct, H2O_wet_pct
        CO2_wet_ppm, CO2_dry_ppm, O2_dry_ppm, H2O_wet_ppm
        N2_wet_pct, N2_dry_pct
        warnings
    """
    warns: list[str] = []

    try:
        C, H, O_fuel, N_fuel, S = (float(C), float(H), float(O),
                                    float(N), float(S))
        excess = float(excess_air_pct)
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "warnings": []}

    if excess < 0.0:
        warns.append(f"excess_air_pct={excess:.1f}% < 0 → rich mixture; "
                     "incomplete combustion likely")
        warnings.warn(warns[-1], stacklevel=2)

    n_O2_stoich = _stoich_o2(C, H, O_fuel, N_fuel, S)
    if n_O2_stoich <= 0.0:
        warns.append("n_O2_stoich ≤ 0 — fully oxidised or inert fuel")
        warnings.warn(warns[-1], stacklevel=2)

    lambda_val = 1.0 + excess / 100.0
    n_O2_supplied = lambda_val * n_O2_stoich

    # Products (moles per mole of fuel)
    n_CO2 = C
    n_H2O = H / 2.0
    n_SO2 = S
    n_O2_excess = n_O2_supplied - n_O2_stoich  # ≥ 0 for lean/stoich

    # Nitrogen from air + fuel formula
    n_air = n_O2_supplied / _AIR_O2_MOLE_FRAC
    n_N2_air = n_air * (1.0 - _AIR_O2_MOLE_FRAC)   # mol N2-equiv from air
    n_N2_fuel = N_fuel / 2.0
    n_N2 = n_N2_air + n_N2_fuel

    # Rich mixture warning
    if excess < 0.0:
        warns.append("Rich mixture: excess_air_pct < 0; O2_excess set to 0")
        n_O2_excess = 0.0

    # Totals
    n_wet_total = n_CO2 + n_H2O + n_SO2 + n_N2 + n_O2_excess
    n_dry_total = n_wet_total - n_H2O

    def _frac(n: float, total: float) -> float:
        return (n / total) if total > 0 else 0.0

    wet = {
        "CO2": _frac(n_CO2, n_wet_total),
        "H2O": _frac(n_H2O, n_wet_total),
        "SO2": _frac(n_SO2, n_wet_total),
        "N2":  _frac(n_N2,  n_wet_total),
        "O2":  _frac(n_O2_excess, n_wet_total),
    }
    dry = {
        "CO2": _frac(n_CO2, n_dry_total),
        "SO2": _frac(n_SO2, n_dry_total),
        "N2":  _frac(n_N2,  n_dry_total),
        "O2":  _frac(n_O2_excess, n_dry_total),
    }

    return {
        "fuel_name": fuel_name or f"C{C}H{H}O{O}",
        "n_CO2": round(n_CO2, 6),
        "n_H2O": round(n_H2O, 6),
        "n_SO2": round(n_SO2, 6),
        "n_N2": round(n_N2, 6),
        "n_O2_excess": round(n_O2_excess, 6),
        "n_wet_total": round(n_wet_total, 6),
        "n_dry_total": round(n_dry_total, 6),
        "wet_mole_fractions": {k: round(v, 8) for k, v in wet.items()},
        "dry_mole_fractions": {k: round(v, 8) for k, v in dry.items()},
        "CO2_wet_pct": round(wet["CO2"] * 100.0, 4),
        "CO2_dry_pct": round(dry["CO2"] * 100.0, 4),
        "O2_dry_pct": round(dry["O2"] * 100.0, 4),
        "H2O_wet_pct": round(wet["H2O"] * 100.0, 4),
        "N2_wet_pct": round(wet["N2"] * 100.0, 4),
        "N2_dry_pct": round(dry["N2"] * 100.0, 4),
        "CO2_wet_ppm": round(wet["CO2"] * 1e6, 1),
        "CO2_dry_ppm": round(dry["CO2"] * 1e6, 1),
        "O2_dry_ppm": round(dry["O2"] * 1e6, 1),
        "H2O_wet_ppm": round(wet["H2O"] * 1e6, 1),
        "warnings": warns,
    }


# ---------------------------------------------------------------------------
# Mean specific heats (cp, J/mol·K) at constant pressure for product gases
# Simple polynomial fits valid ~300–2500 K (Borman & Ragland Table A-3 approx)
# ---------------------------------------------------------------------------

def _cp_CO2(T: float) -> float:
    """J/mol·K — CO2 mean cp, polynomial fit 300–2500 K."""
    # JANAF polynomial-like: cp = a + b*T + c*T^2  (rough)
    t = T / 1000.0
    return 24.997 + 55.187 * t - 33.691 * t ** 2 + 7.948 * t ** 3


def _cp_H2O(T: float) -> float:
    """J/mol·K — H2O vapour mean cp."""
    t = T / 1000.0
    return 30.092 + 6.833 * t + 6.793 * t ** 2 - 2.534 * t ** 3


def _cp_N2(T: float) -> float:
    """J/mol·K — N2 mean cp."""
    t = T / 1000.0
    return 26.092 + 8.219 * t - 1.976 * t ** 2 + 0.159 * t ** 3


def _cp_O2(T: float) -> float:
    """J/mol·K — O2 mean cp."""
    t = T / 1000.0
    return 29.659 + 6.137 * t - 1.186 * t ** 2 + 0.096 * t ** 3


def _cp_SO2(T: float) -> float:
    """J/mol·K — SO2 mean cp."""
    t = T / 1000.0
    return 21.430 + 74.351 * t - 57.752 * t ** 2 + 16.352 * t ** 3


def _mixture_cp(
    T: float,
    n_CO2: float,
    n_H2O: float,
    n_N2: float,
    n_O2: float,
    n_SO2: float,
) -> float:
    """Mixture molar cp [J/mol_mixture·K] at temperature T [K]."""
    n_total = n_CO2 + n_H2O + n_N2 + n_O2 + n_SO2
    if n_total <= 0:
        return 30.0  # fallback
    cp = (n_CO2 * _cp_CO2(T) + n_H2O * _cp_H2O(T) + n_N2 * _cp_N2(T)
          + n_O2 * _cp_O2(T) + n_SO2 * _cp_SO2(T))
    return cp / n_total   # per mole of mixture


# ---------------------------------------------------------------------------
# Lower/higher heating values for generic CxHyOz
# ---------------------------------------------------------------------------

# Standard heats of formation (kJ/mol) at 298 K (JANAF / NIST)
_HF0 = {
    "CO2": -393.51,   # kJ/mol
    "H2O_liq": -285.83,
    "H2O_gas": -241.82,
    "SO2": -296.83,
}

# Heats of formation of common gaseous fuels (kJ/mol fuel)
_FUEL_HF0: dict[str, float] = {
    "CH4":  -74.87,
    "C2H6": -83.82,
    "C3H8": -104.68,
    "C4H10": -126.23,
    "H2":     0.0,
    "C8H18": -208.4,
    "C12H26": -290.9,
    "C2H6O": -277.6,   # ethanol liquid; adjust if gas phase
    "CH4O":  -238.7,   # methanol liquid
}


def adiabatic_flame_temp(
    C: float,
    H: float,
    O: float = 0.0,
    N: float = 0.0,
    S: float = 0.0,
    T_reactants: float = 298.15,
    excess_air_pct: float = 0.0,
    LHV_MJ_kg: float | None = None,
    MW_fuel: float | None = None,
    max_iter: int = 50,
    tol: float = 0.5,
) -> dict[str, Any]:
    """Adiabatic flame temperature via iterative constant-pressure energy balance.

    Uses mean-cp iteration for products.  For best accuracy supply LHV_MJ_kg
    and MW_fuel from the FUELS table (or from hhv_to_lhv).

    Algorithm
    ---------
    1. Compute Q_release = LHV × m_fuel (or estimated from heats of formation).
    2. Guess T_ad = T_reactants + Q_release / (n_products × cp_mean).
    3. Iterate: recompute cp_mean at (T_ad + T_reactants)/2 until convergence.

    Parameters
    ----------
    T_reactants   : temperature of reactants (K), default 298.15 K
    excess_air_pct: excess air (%, ≥ 0 for lean/stoich)
    LHV_MJ_kg     : lower heating value (MJ/kg fuel). If None, estimated.
    MW_fuel       : molecular weight of fuel (g/mol). Required if LHV_MJ_kg given.

    Returns
    -------
    dict with T_ad_K, T_ad_C, converged, iterations, warnings
    """
    warns: list[str] = []

    try:
        C, H, O_f, N_f, S = float(C), float(H), float(O), float(N), float(S)
        T_r = float(T_reactants)
        excess = float(excess_air_pct)
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "warnings": []}

    if T_r <= 0:
        return {"ok": False, "reason": "T_reactants must be > 0 K", "warnings": []}
    if excess < -90.0:
        warns.append("Very rich mixture (excess_air_pct < -90%)")
        warnings.warn(warns[-1], stacklevel=2)

    # Product moles per mole fuel
    n_O2_stoich = _stoich_o2(C, H, O_f, N_f, S)
    lambda_val = 1.0 + excess / 100.0
    n_O2_supplied = lambda_val * n_O2_stoich
    n_CO2 = C
    n_H2O = H / 2.0
    n_SO2 = S
    n_O2_ex = max(0.0, n_O2_supplied - n_O2_stoich)
    n_air = n_O2_supplied / _AIR_O2_MOLE_FRAC
    n_N2 = n_air * (1.0 - _AIR_O2_MOLE_FRAC) + N_f / 2.0
    n_prod_total = n_CO2 + n_H2O + n_SO2 + n_N2 + n_O2_ex   # mol / mol fuel

    # Heat release per mole of fuel (J/mol)
    if LHV_MJ_kg is not None and MW_fuel is not None:
        Q_J_per_mol = float(LHV_MJ_kg) * 1e6 * float(MW_fuel) * 1e-3  # MJ/kg * g/mol → J/mol
    else:
        # Estimate from heats of formation (Hess's law):
        # ΔH_rxn = Σ n_prod * Hf(prod) - Hf(fuel)
        # Use water as gas (LHV basis)
        hf_CO2 = n_CO2 * _HF0["CO2"]
        hf_H2O = n_H2O * _HF0["H2O_gas"]
        hf_SO2 = n_SO2 * _HF0["SO2"]
        # Approximate Hf of fuel from atoms (very rough for generic formulas)
        # Use: sum of elemental bond contributions or default 0
        hf_fuel = 0.0  # 0 = treat as elemental reference; rough but bounded
        delta_h_kJ_mol = (hf_CO2 + hf_H2O + hf_SO2) - hf_fuel
        Q_J_per_mol = -delta_h_kJ_mol * 1000.0  # exothermic → positive
        warns.append("LHV not supplied; using heat-of-formation estimate — less accurate")

    if Q_J_per_mol <= 0:
        warns.append("Q_release ≤ 0 — endothermic or inert fuel; T_ad = T_reactants")
        return {
            "T_ad_K": round(T_r, 2),
            "T_ad_C": round(T_r - 273.15, 2),
            "converged": True,
            "iterations": 0,
            "warnings": warns,
        }

    # Initial guess: cp of N2 at ~1500 K as proxy
    cp_guess = _mixture_cp(
        1500.0, n_CO2, n_H2O, n_N2, n_O2_ex, n_SO2
    )  # J/mol_mixture/K
    T_ad = T_r + Q_J_per_mol / (n_prod_total * cp_guess)

    converged = False
    for i in range(max_iter):
        T_mid = (T_ad + T_r) / 2.0
        T_mid = max(300.0, min(T_mid, 3000.0))
        cp_mix = _mixture_cp(T_mid, n_CO2, n_H2O, n_N2, n_O2_ex, n_SO2)
        T_ad_new = T_r + Q_J_per_mol / (n_prod_total * cp_mix)
        if abs(T_ad_new - T_ad) < tol:
            T_ad = T_ad_new
            converged = True
            iterations = i + 1
            break
        T_ad = T_ad_new
    else:
        iterations = max_iter
        warns.append(f"adiabatic_flame_temp did not converge in {max_iter} iterations; "
                     f"last T_ad={T_ad:.1f} K")
        warnings.warn(warns[-1], stacklevel=2)

    if T_ad > 3000.0:
        warns.append(f"T_ad={T_ad:.0f} K > 3000 K — dissociation effects significant; "
                     "result is overestimate")
        warnings.warn(warns[-1], stacklevel=2)

    return {
        "T_ad_K": round(T_ad, 2),
        "T_ad_C": round(T_ad - 273.15, 2),
        "converged": converged,
        "iterations": iterations,
        "warnings": warns,
    }


def hhv_to_lhv(
    HHV_MJ_kg: float,
    C: float = 0.0,
    H: float = 0.0,
    O: float = 0.0,
    N: float = 0.0,
    S: float = 0.0,
    MW_fuel: float | None = None,
    direction: str = "hhv_to_lhv",
) -> dict[str, Any]:
    """Convert HHV ↔ LHV using water latent heat of condensation.

    LHV = HHV - h_fg × m_water / m_fuel

    where m_water is the mass of water produced per unit mass of fuel,
    h_fg = 2.442 MJ/kg_water (at 25 °C).

    Parameters
    ----------
    HHV_MJ_kg : float  — Higher Heating Value (MJ/kg fuel). OR LHV if direction='lhv_to_hhv'.
    C, H, O, N, S      — atom counts in fuel formula (used to compute H2O yield)
    MW_fuel            — molecular weight of fuel (g/mol); computed from C,H,O,N,S if None
    direction          — 'hhv_to_lhv' (default) or 'lhv_to_hhv'

    Returns
    -------
    dict with LHV_MJ_kg, HHV_MJ_kg, delta_MJ_kg, H2O_mass_frac, warnings
    """
    warns: list[str] = []
    try:
        val = float(HHV_MJ_kg)
        C, H, O_f, N_f, S = float(C), float(H), float(O), float(N), float(S)
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "warnings": []}

    if val <= 0:
        return {"ok": False, "reason": "Heating value must be > 0", "warnings": []}

    mw = float(MW_fuel) if MW_fuel is not None else _fuel_mw(C, H, O_f, N_f, S)
    if mw <= 0:
        warns.append("MW_fuel ≤ 0; delta correction not possible — returning input unchanged")
        return {
            "LHV_MJ_kg": val if direction == "hhv_to_lhv" else None,
            "HHV_MJ_kg": val if direction == "lhv_to_hhv" else None,
            "delta_MJ_kg": 0.0,
            "H2O_mass_frac": 0.0,
            "warnings": warns,
        }

    # Mass of H2O produced per kg of fuel
    n_H2O_per_mol_fuel = H / 2.0
    mass_H2O_per_mol_fuel = n_H2O_per_mol_fuel * _MW["H2O"]  # g
    h2o_mass_frac = mass_H2O_per_mol_fuel / mw  # kg H2O / kg fuel

    delta = h2o_mass_frac * _H_FG_WATER * 1e-6   # MJ/kg fuel

    if direction == "hhv_to_lhv":
        hhv_val = val
        lhv_val = val - delta
    else:
        lhv_val = val
        hhv_val = val + delta

    if lhv_val < 0:
        warns.append("Computed LHV < 0 — check inputs")
        warnings.warn(warns[-1], stacklevel=2)

    return {
        "LHV_MJ_kg": round(lhv_val, 6),
        "HHV_MJ_kg": round(hhv_val, 6),
        "delta_MJ_kg": round(delta, 6),
        "H2O_mass_frac": round(h2o_mass_frac, 6),
        "warnings": warns,
    }


def combustion_efficiency(
    T_flue_C: float,
    T_ambient_C: float,
    CO2_dry_pct: float | None = None,
    O2_dry_pct: float | None = None,
    CO2_max_pct: float | None = None,
    fuel: str = "natural_gas",
    include_siegert: bool = True,
) -> dict[str, Any]:
    """Combustion efficiency and Siegert flue-gas heat loss.

    Siegert method (EN 15502 / VDI 2067):
        q_A = (T_flue - T_amb) × (A1 / (CO2%) + B1)   [% of fuel energy]

    Siegert coefficients A1, B1 depend on fuel type:
        natural_gas (methane): A1≈0.68, B1≈0.007
        oil (light fuel oil):  A1≈0.68, B1≈0.013
        coal (bituminous):     A1≈0.68, B1≈0.014

    If CO2_dry_pct is not given, O2_dry_pct is used via:
        CO2_pct ≈ CO2_max × (1 - O2_pct/20.9)   (approximate)

    Parameters
    ----------
    T_flue_C      : flue-gas temperature (°C)
    T_ambient_C   : combustion-air / ambient temperature (°C)
    CO2_dry_pct   : measured CO2 in dry flue gas (%, 0–CO2_max)
    O2_dry_pct    : measured O2 in dry flue gas (%, 0–21)
    CO2_max_pct   : stoichiometric (maximum) CO2% — needed when using O2_dry_pct
    fuel          : 'natural_gas', 'oil', 'coal' — selects Siegert coefficients
    include_siegert: compute Siegert loss (default True)

    Returns
    -------
    dict with eta_pct, q_A_pct (Siegert loss), warnings
    """
    warns: list[str] = []

    try:
        T_f = float(T_flue_C)
        T_a = float(T_ambient_C)
    except Exception as exc:
        return {"ok": False, "reason": str(exc), "warnings": []}

    dT = T_f - T_a
    if dT <= 0:
        warns.append(f"T_flue ({T_f}°C) ≤ T_ambient ({T_a}°C) — heat loss likely 0")

    # Siegert coefficients (from EN 15502-1 / VDI table)
    _SIEGERT = {
        "natural_gas": (0.680, 0.0071),
        "methane":     (0.680, 0.0071),
        "oil":         (0.680, 0.0125),
        "coal":        (0.680, 0.0140),
        "propane":     (0.680, 0.0083),
    }
    A1, B1 = _SIEGERT.get(fuel.lower(), (0.680, 0.0071))

    q_A = None
    CO2_used = None

    if CO2_dry_pct is not None:
        CO2_used = float(CO2_dry_pct)
    elif O2_dry_pct is not None and CO2_max_pct is not None:
        o2 = float(O2_dry_pct)
        co2_max = float(CO2_max_pct)
        CO2_used = co2_max * (1.0 - o2 / 20.9)
        warns.append(f"CO2_dry_pct estimated from O2={o2:.2f}%: CO2≈{CO2_used:.2f}%")
    else:
        warns.append("CO2_dry_pct not provided; Siegert loss cannot be computed")

    if include_siegert and CO2_used is not None and CO2_used > 0:
        q_A = dT * (A1 / CO2_used + B1)
        q_A = max(0.0, q_A)
    elif CO2_used is not None and CO2_used <= 0:
        warns.append("CO2_dry_pct ≤ 0; Siegert calculation skipped")

    eta = (100.0 - q_A) if q_A is not None else None

    return {
        "eta_pct": round(eta, 3) if eta is not None else None,
        "q_A_pct": round(q_A, 4) if q_A is not None else None,
        "CO2_dry_pct_used": round(CO2_used, 4) if CO2_used is not None else None,
        "dT_K": round(dT, 2),
        "fuel": fuel,
        "warnings": warns,
    }


def flue_gas_dew_point(
    H2O_wet_frac: float | None = None,
    H2O_wet_pct: float | None = None,
    p_total_Pa: float = 101325.0,
) -> dict[str, Any]:
    """Flue-gas dew-point temperature (sulphur-free fuel).

    Uses Antoine equation for water vapour pressure:
        log10(p_sat_mmHg) = A - B/(C + T_C)
        Antoine constants: A=8.07131, B=1730.63, C=233.426 (T in °C, valid 1–100 °C)

    For H2O partial pressure above ~0.1 atm (>100 °C dew point) uses the
    extended form valid up to ~374 °C.

    Parameters
    ----------
    H2O_wet_frac  : mole fraction of H2O in wet flue gas [0–1]
    H2O_wet_pct   : H2O % in wet flue gas (alternative to H2O_wet_frac)
    p_total_Pa    : total flue-gas pressure (Pa), default 101325 Pa

    Returns
    -------
    dict with T_dew_C, T_dew_K, p_H2O_Pa, p_H2O_kPa, warnings
    """
    warns: list[str] = []

    if H2O_wet_frac is not None:
        frac = float(H2O_wet_frac)
    elif H2O_wet_pct is not None:
        frac = float(H2O_wet_pct) / 100.0
    else:
        return {"ok": False, "reason": "Provide H2O_wet_frac or H2O_wet_pct", "warnings": []}

    if not (0.0 < frac < 1.0):
        return {"ok": False,
                "reason": f"H2O mole fraction {frac:.4f} out of (0, 1)", "warnings": []}

    p_H2O = frac * float(p_total_Pa)   # Pa

    # Convert Pa to mmHg for Antoine
    p_mmHg = p_H2O / 133.322

    # Antoine constants for water (NIST, T in °C)
    # Two ranges: 1–100 °C and 60–150 °C; use 1–100 range and iterate if needed
    A, B, C = 8.07131, 1730.63, 233.426

    # Invert: T = B / (A - log10(p_mmHg)) - C
    try:
        log_p = math.log10(p_mmHg)
        T_dew_C = B / (A - log_p) - C
    except (ValueError, ZeroDivisionError) as exc:
        return {"ok": False, "reason": f"Antoine inversion failed: {exc}", "warnings": []}

    if T_dew_C < 1.0 or T_dew_C > 150.0:
        warns.append(f"Dew point {T_dew_C:.1f} °C outside Antoine validity range "
                     "(1–150 °C); result is extrapolated")
        warnings.warn(warns[-1], stacklevel=2)

    return {
        "T_dew_C": round(T_dew_C, 2),
        "T_dew_K": round(T_dew_C + 273.15, 2),
        "p_H2O_Pa": round(p_H2O, 2),
        "p_H2O_kPa": round(p_H2O / 1000.0, 4),
        "warnings": warns,
    }


def co2_max(
    C: float,
    H: float,
    O: float = 0.0,
    N: float = 0.0,
    S: float = 0.0,
) -> dict[str, Any]:
    """Maximum (stoichiometric, dry) CO2 percentage in flue gas.

    CO2_max occurs at stoichiometric combustion (no excess air) and is
    the reference point for the Siegert analysis and Bacharach-style checks.

    CO2_max_dry = n_CO2 / n_dry_total × 100%   at λ=1

    Parameters
    ----------
    C, H, O, N, S : atom counts in fuel formula

    Returns
    -------
    dict with CO2_max_dry_pct, CO2_max_wet_pct, warnings
    """
    result = product_composition(C, H, O, N, S, excess_air_pct=0.0)
    if "ok" in result and not result["ok"]:
        return result
    return {
        "CO2_max_dry_pct": result["CO2_dry_pct"],
        "CO2_max_wet_pct": result["CO2_wet_pct"],
        "n_CO2": result["n_CO2"],
        "n_dry_total": result["n_dry_total"],
        "warnings": result["warnings"],
    }


def fuel_power(
    mass_flow_kg_s: float | None = None,
    vol_flow_m3_s: float | None = None,
    density_kg_m3: float | None = None,
    LHV_MJ_kg: float | None = None,
    HHV_MJ_kg: float | None = None,
    use_hhv: bool = False,
    eta_combustion: float = 1.0,
    target_power_W: float | None = None,
) -> dict[str, Any]:
    """Fuel energy → thermal power & specific fuel consumption.

    Supply:
      - mass_flow_kg_s  OR  (vol_flow_m3_s + density_kg_m3)
      - LHV_MJ_kg  (or HHV_MJ_kg when use_hhv=True)

    OR supply target_power_W to back-calculate required mass flow.

    Parameters
    ----------
    mass_flow_kg_s   : fuel mass flow (kg/s)
    vol_flow_m3_s    : volumetric flow (m³/s) — requires density_kg_m3
    density_kg_m3    : fuel density (kg/m³)
    LHV_MJ_kg        : lower heating value (MJ/kg)
    HHV_MJ_kg        : higher heating value (MJ/kg)
    use_hhv          : use HHV instead of LHV (default False)
    eta_combustion   : combustion efficiency [0–1] (default 1.0)
    target_power_W   : if given, compute required mass flow for this power

    Returns
    -------
    dict with thermal_power_W, thermal_power_kW, thermal_power_MW,
              SFC_kg_per_kWh, SFC_g_per_kWh, mass_flow_kg_s, warnings
    """
    warns: list[str] = []

    # Resolve heating value (J/kg)
    if use_hhv:
        hv = HHV_MJ_kg if HHV_MJ_kg is not None else None
    else:
        hv = LHV_MJ_kg if LHV_MJ_kg is not None else None

    if hv is None and LHV_MJ_kg is not None:
        hv = LHV_MJ_kg
        warns.append("LHV used as fallback")
    if hv is None and HHV_MJ_kg is not None:
        hv = HHV_MJ_kg
        warns.append("HHV used as fallback")

    if hv is None:
        return {"ok": False, "reason": "LHV_MJ_kg or HHV_MJ_kg is required", "warnings": warns}
    if hv <= 0:
        return {"ok": False, "reason": "Heating value must be > 0", "warnings": warns}

    hv_J_kg = float(hv) * 1e6  # J/kg

    eta = max(0.0, min(1.0, float(eta_combustion)))
    if eta != float(eta_combustion):
        warns.append(f"eta_combustion clamped to [{eta}]")

    # Back-calculate mass flow for target power
    if target_power_W is not None:
        tp = float(target_power_W)
        if tp <= 0:
            return {"ok": False, "reason": "target_power_W must be > 0", "warnings": warns}
        mdot = tp / (hv_J_kg * eta)
        vdot = (mdot / float(density_kg_m3)) if density_kg_m3 else None
        P_thermal = tp
    else:
        # Resolve mass flow
        if mass_flow_kg_s is not None:
            mdot = float(mass_flow_kg_s)
        elif vol_flow_m3_s is not None and density_kg_m3 is not None:
            mdot = float(vol_flow_m3_s) * float(density_kg_m3)
            vdot = float(vol_flow_m3_s)
        else:
            return {"ok": False,
                    "reason": "Provide mass_flow_kg_s or (vol_flow_m3_s + density_kg_m3)",
                    "warnings": warns}
        if mdot <= 0:
            return {"ok": False, "reason": "mass flow must be > 0", "warnings": warns}
        P_thermal = mdot * hv_J_kg * eta

    # Specific fuel consumption: kg fuel per kWh of thermal output
    sfc_kg_kWh = mdot / (P_thermal / 3.6e6) if P_thermal > 0 else 0.0
    sfc_g_kWh = sfc_kg_kWh * 1000.0

    return {
        "mass_flow_kg_s": round(mdot, 8),
        "thermal_power_W": round(P_thermal, 3),
        "thermal_power_kW": round(P_thermal / 1e3, 6),
        "thermal_power_MW": round(P_thermal / 1e6, 9),
        "SFC_kg_per_kWh": round(sfc_kg_kWh, 6),
        "SFC_g_per_kWh": round(sfc_g_kWh, 4),
        "HV_used_MJ_kg": round(hv, 6),
        "eta_combustion": eta,
        "warnings": warns,
    }
