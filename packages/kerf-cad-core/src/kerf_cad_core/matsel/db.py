"""
kerf_cad_core.matsel.db — engineering material-property database and Ashby selection.

Contains a hand-authored database of ~40 common engineering materials with
typical textbook properties, plus lookup, filtering, and Ashby merit-index
ranking functions.

All property values are typical mid-range textbook estimates.  They are
original author-authored numbers based on publicly available engineering
textbook ranges (Ashby "Materials Selection in Mechanical Design", Callister
"Materials Science and Engineering", Shigley "Mechanical Engineering Design").
No proprietary dataset is reproduced.

Property keys
-------------
density     float  kg/m³
E           float  GPa     Young's modulus
sigma_y     float  MPa     0.2% proof / yield strength
sigma_uts   float  MPa     ultimate tensile strength
sigma_e     float  MPa     fully-reversed endurance limit (~10^7 cycles)
                            0 if fatigue data not typically quoted (e.g. some ceramics)
k           float  W/(m·K) thermal conductivity
CTE         float  µm/(m·K)
T_max       float  °C      approximate continuous service temperature
cost_rel    float  —       relative cost index (mild steel AISI 1020 = 1.0)
family      str    material family label

Merit-index helpers
-------------------
specific_stiffness  E/ρ          (GPa·m³/kg)
specific_strength   sigma_y/ρ    (MPa·m³/kg)
light_stiff_beam    E^0.5/ρ      (GPa^0.5·m³/kg)  — minimise mass, stiffness-limited beam
light_strong_plate  sigma_y^(2/3)/ρ  — minimise mass, strength-limited plate
cost_per_stiffness  cost_rel·ρ/E — relative cost per unit stiffness

Functions
---------
get_material(name)                     → dict or None
list_materials()                       → list[str]
filter_materials(constraints)          → {"ok": True/False, "materials": [...], "warnings": [...]}
ashby_rank(index, candidates, top_n)   → ranked list with index value
select_material(constraints, objective)→ {"ok":..., "ranked": [...], "warnings": [...]}

Functions never raise; errors are returned as {"ok": False, "reason": "..."}.

Author: imranparuk
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Material database
# ---------------------------------------------------------------------------
# Each entry is keyed by a short canonical name.
# Properties follow SI units as described in the module docstring.

_DB: dict[str, dict[str, Any]] = {

    # ── Steels ────────────────────────────────────────────────────────────
    "AISI_1020": {
        "family": "steel",
        "density": 7850.0,   # kg/m³
        "E": 200.0,          # GPa
        "sigma_y": 210.0,    # MPa
        "sigma_uts": 380.0,  # MPa
        "sigma_e": 190.0,    # MPa
        "k": 51.9,           # W/(m·K)
        "CTE": 11.7,         # µm/(m·K)
        "T_max": 400.0,      # °C
        "cost_rel": 1.0,
    },
    "AISI_1045": {
        "family": "steel",
        "density": 7850.0,
        "E": 200.0,
        "sigma_y": 390.0,
        "sigma_uts": 620.0,
        "sigma_e": 310.0,
        "k": 49.8,
        "CTE": 11.7,
        "T_max": 400.0,
        "cost_rel": 1.1,
    },
    "AISI_4140_QT": {
        "family": "steel",
        "density": 7850.0,
        "E": 205.0,
        "sigma_y": 655.0,
        "sigma_uts": 1020.0,
        "sigma_e": 510.0,
        "k": 42.6,
        "CTE": 12.3,
        "T_max": 450.0,
        "cost_rel": 1.4,
    },
    "AISI_4340_QT": {
        "family": "steel",
        "density": 7850.0,
        "E": 205.0,
        "sigma_y": 1170.0,
        "sigma_uts": 1280.0,
        "sigma_e": 640.0,
        "k": 44.5,
        "CTE": 12.3,
        "T_max": 450.0,
        "cost_rel": 1.8,
    },
    "SS_304": {
        "family": "stainless_steel",
        "density": 8000.0,
        "E": 193.0,
        "sigma_y": 215.0,
        "sigma_uts": 505.0,
        "sigma_e": 240.0,
        "k": 16.2,
        "CTE": 17.2,
        "T_max": 870.0,
        "cost_rel": 3.5,
    },
    "SS_316L": {
        "family": "stainless_steel",
        "density": 8000.0,
        "E": 193.0,
        "sigma_y": 170.0,
        "sigma_uts": 485.0,
        "sigma_e": 230.0,
        "k": 16.3,
        "CTE": 16.0,
        "T_max": 870.0,
        "cost_rel": 4.0,
    },
    "SS_17-4PH": {
        "family": "stainless_steel",
        "density": 7780.0,
        "E": 197.0,
        "sigma_y": 1170.0,
        "sigma_uts": 1310.0,
        "sigma_e": 620.0,
        "k": 18.3,
        "CTE": 10.8,
        "T_max": 480.0,
        "cost_rel": 6.0,
    },

    # ── Aluminium alloys ──────────────────────────────────────────────────
    "Al_6061_T6": {
        "family": "aluminium",
        "density": 2700.0,
        "E": 69.0,
        "sigma_y": 276.0,
        "sigma_uts": 310.0,
        "sigma_e": 97.0,
        "k": 167.0,
        "CTE": 23.6,
        "T_max": 150.0,
        "cost_rel": 2.2,
    },
    "Al_7075_T6": {
        "family": "aluminium",
        "density": 2810.0,
        "E": 71.7,
        "sigma_y": 503.0,
        "sigma_uts": 572.0,
        "sigma_e": 160.0,
        "k": 130.0,
        "CTE": 23.6,
        "T_max": 120.0,
        "cost_rel": 3.2,
    },
    "Al_2024_T3": {
        "family": "aluminium",
        "density": 2780.0,
        "E": 73.1,
        "sigma_y": 345.0,
        "sigma_uts": 483.0,
        "sigma_e": 140.0,
        "k": 121.0,
        "CTE": 23.2,
        "T_max": 130.0,
        "cost_rel": 3.0,
    },

    # ── Titanium alloys ───────────────────────────────────────────────────
    "Ti_6Al4V": {
        "family": "titanium",
        "density": 4430.0,
        "E": 113.8,
        "sigma_y": 880.0,
        "sigma_uts": 950.0,
        "sigma_e": 510.0,
        "k": 7.2,
        "CTE": 8.6,
        "T_max": 300.0,
        "cost_rel": 20.0,
    },
    "Ti_CP_Grade2": {
        "family": "titanium",
        "density": 4510.0,
        "E": 105.0,
        "sigma_y": 275.0,
        "sigma_uts": 345.0,
        "sigma_e": 170.0,
        "k": 16.4,
        "CTE": 8.9,
        "T_max": 260.0,
        "cost_rel": 15.0,
    },

    # ── Magnesium alloys ──────────────────────────────────────────────────
    "Mg_AZ31B": {
        "family": "magnesium",
        "density": 1770.0,
        "E": 45.0,
        "sigma_y": 200.0,
        "sigma_uts": 262.0,
        "sigma_e": 90.0,
        "k": 77.0,
        "CTE": 26.0,
        "T_max": 120.0,
        "cost_rel": 3.8,
    },
    "Mg_AZ91D": {
        "family": "magnesium",
        "density": 1810.0,
        "E": 45.0,
        "sigma_y": 160.0,
        "sigma_uts": 230.0,
        "sigma_e": 70.0,
        "k": 51.0,
        "CTE": 26.0,
        "T_max": 110.0,
        "cost_rel": 3.5,
    },

    # ── Common polymers ───────────────────────────────────────────────────
    "Nylon_PA66": {
        "family": "polymer",
        "density": 1140.0,
        "E": 2.8,
        "sigma_y": 55.0,
        "sigma_uts": 80.0,
        "sigma_e": 25.0,
        "k": 0.25,
        "CTE": 80.0,
        "T_max": 120.0,
        "cost_rel": 1.8,
    },
    "PEEK": {
        "family": "polymer",
        "density": 1320.0,
        "E": 3.6,
        "sigma_y": 91.0,
        "sigma_uts": 100.0,
        "sigma_e": 40.0,
        "k": 0.25,
        "CTE": 47.0,
        "T_max": 250.0,
        "cost_rel": 60.0,
    },
    "PTFE": {
        "family": "polymer",
        "density": 2200.0,
        "E": 0.5,
        "sigma_y": 12.0,
        "sigma_uts": 25.0,
        "sigma_e": 8.0,
        "k": 0.25,
        "CTE": 120.0,
        "T_max": 260.0,
        "cost_rel": 10.0,
    },
    "PC": {
        "family": "polymer",
        "density": 1200.0,
        "E": 2.4,
        "sigma_y": 55.0,
        "sigma_uts": 65.0,
        "sigma_e": 22.0,
        "k": 0.20,
        "CTE": 65.0,
        "T_max": 120.0,
        "cost_rel": 2.5,
    },
    "HDPE": {
        "family": "polymer",
        "density": 950.0,
        "E": 0.9,
        "sigma_y": 25.0,
        "sigma_uts": 30.0,
        "sigma_e": 10.0,
        "k": 0.44,
        "CTE": 130.0,
        "T_max": 80.0,
        "cost_rel": 0.8,
    },
    "ABS": {
        "family": "polymer",
        "density": 1050.0,
        "E": 2.1,
        "sigma_y": 40.0,
        "sigma_uts": 45.0,
        "sigma_e": 15.0,
        "k": 0.17,
        "CTE": 95.0,
        "T_max": 80.0,
        "cost_rel": 1.5,
    },
    "POM_Delrin": {
        "family": "polymer",
        "density": 1410.0,
        "E": 3.1,
        "sigma_y": 65.0,
        "sigma_uts": 70.0,
        "sigma_e": 28.0,
        "k": 0.31,
        "CTE": 110.0,
        "T_max": 100.0,
        "cost_rel": 2.8,
    },

    # ── Composites ────────────────────────────────────────────────────────
    "CFRP_UD_0deg": {
        "family": "composite",
        "density": 1550.0,
        "E": 135.0,
        "sigma_y": 1500.0,   # tensile strength (composites don't yield classically)
        "sigma_uts": 1500.0,
        "sigma_e": 700.0,
        "k": 5.0,
        "CTE": 0.5,
        "T_max": 150.0,
        "cost_rel": 40.0,
    },
    "CFRP_Quasi": {
        "family": "composite",
        "density": 1570.0,
        "E": 55.0,
        "sigma_y": 550.0,
        "sigma_uts": 550.0,
        "sigma_e": 260.0,
        "k": 3.0,
        "CTE": 3.0,
        "T_max": 150.0,
        "cost_rel": 38.0,
    },
    "GFRP_Woven": {
        "family": "composite",
        "density": 1850.0,
        "E": 20.0,
        "sigma_y": 230.0,
        "sigma_uts": 280.0,
        "sigma_e": 100.0,
        "k": 0.35,
        "CTE": 12.0,
        "T_max": 150.0,
        "cost_rel": 4.5,
    },
    "GFRP_UD": {
        "family": "composite",
        "density": 1900.0,
        "E": 40.0,
        "sigma_y": 700.0,
        "sigma_uts": 700.0,
        "sigma_e": 280.0,
        "k": 0.35,
        "CTE": 7.0,
        "T_max": 150.0,
        "cost_rel": 5.0,
    },

    # ── Woods (structural) ────────────────────────────────────────────────
    "Douglas_Fir": {
        "family": "wood",
        "density": 530.0,
        "E": 13.0,           # along grain
        "sigma_y": 38.0,     # compressive parallel to grain
        "sigma_uts": 85.0,   # tensile parallel to grain (MOR)
        "sigma_e": 25.0,
        "k": 0.14,
        "CTE": 3.8,
        "T_max": 70.0,
        "cost_rel": 0.3,
    },
    "Balsa": {
        "family": "wood",
        "density": 130.0,
        "E": 3.5,
        "sigma_y": 5.0,
        "sigma_uts": 20.0,
        "sigma_e": 6.0,
        "k": 0.055,
        "CTE": 4.0,
        "T_max": 60.0,
        "cost_rel": 1.2,
    },
    "Oak_Red": {
        "family": "wood",
        "density": 740.0,
        "E": 12.5,
        "sigma_y": 52.0,
        "sigma_uts": 100.0,
        "sigma_e": 30.0,
        "k": 0.17,
        "CTE": 4.2,
        "T_max": 70.0,
        "cost_rel": 0.5,
    },

    # ── Ceramics ──────────────────────────────────────────────────────────
    "Alumina_99": {
        "family": "ceramic",
        "density": 3960.0,
        "E": 380.0,
        "sigma_y": 260.0,    # compressive strength (ceramics used in compression)
        "sigma_uts": 260.0,  # flexural strength (MOR)
        "sigma_e": 0.0,      # fatigue not typically quoted
        "k": 30.0,
        "CTE": 8.1,
        "T_max": 1600.0,
        "cost_rel": 12.0,
    },
    "SiC": {
        "family": "ceramic",
        "density": 3160.0,
        "E": 410.0,
        "sigma_y": 400.0,
        "sigma_uts": 400.0,
        "sigma_e": 0.0,
        "k": 120.0,
        "CTE": 4.0,
        "T_max": 1500.0,
        "cost_rel": 50.0,
    },
    "Si3N4": {
        "family": "ceramic",
        "density": 3200.0,
        "E": 300.0,
        "sigma_y": 700.0,
        "sigma_uts": 700.0,
        "sigma_e": 0.0,
        "k": 30.0,
        "CTE": 3.2,
        "T_max": 1200.0,
        "cost_rel": 80.0,
    },
    "Zirconia_TZP": {
        "family": "ceramic",
        "density": 6050.0,
        "E": 210.0,
        "sigma_y": 1000.0,  # flexural strength
        "sigma_uts": 1000.0,
        "sigma_e": 0.0,
        "k": 2.0,
        "CTE": 10.5,
        "T_max": 900.0,
        "cost_rel": 30.0,
    },
    "Borosilicate_Glass": {
        "family": "ceramic",
        "density": 2230.0,
        "E": 64.0,
        "sigma_y": 30.0,
        "sigma_uts": 50.0,
        "sigma_e": 0.0,
        "k": 1.2,
        "CTE": 3.3,
        "T_max": 450.0,
        "cost_rel": 2.0,
    },

    # ── Cast irons ────────────────────────────────────────────────────────
    "Gray_CI_G25": {
        "family": "cast_iron",
        "density": 7200.0,
        "E": 105.0,
        "sigma_y": 165.0,
        "sigma_uts": 180.0,
        "sigma_e": 85.0,
        "k": 46.0,
        "CTE": 11.0,
        "T_max": 300.0,
        "cost_rel": 0.7,
    },
    "Ductile_CI_65-45": {
        "family": "cast_iron",
        "density": 7100.0,
        "E": 169.0,
        "sigma_y": 310.0,
        "sigma_uts": 450.0,
        "sigma_e": 210.0,
        "k": 36.0,
        "CTE": 12.5,
        "T_max": 350.0,
        "cost_rel": 0.9,
    },

    # ── Copper alloys ─────────────────────────────────────────────────────
    "Cu_ETP": {
        "family": "copper",
        "density": 8940.0,
        "E": 117.0,
        "sigma_y": 70.0,
        "sigma_uts": 230.0,
        "sigma_e": 70.0,
        "k": 390.0,
        "CTE": 17.0,
        "T_max": 200.0,
        "cost_rel": 5.0,
    },
    "Brass_C360": {
        "family": "copper",
        "density": 8500.0,
        "E": 97.0,
        "sigma_y": 124.0,
        "sigma_uts": 340.0,
        "sigma_e": 100.0,
        "k": 115.0,
        "CTE": 20.5,
        "T_max": 200.0,
        "cost_rel": 4.5,
    },
    "BeCu_C17200": {
        "family": "copper",
        "density": 8260.0,
        "E": 128.0,
        "sigma_y": 1100.0,
        "sigma_uts": 1240.0,
        "sigma_e": 400.0,
        "k": 105.0,
        "CTE": 17.8,
        "T_max": 200.0,
        "cost_rel": 35.0,
    },

    # ── Nickel superalloys ────────────────────────────────────────────────
    "Inconel_718": {
        "family": "nickel_superalloy",
        "density": 8190.0,
        "E": 200.0,
        "sigma_y": 1034.0,
        "sigma_uts": 1240.0,
        "sigma_e": 500.0,
        "k": 11.4,
        "CTE": 13.0,
        "T_max": 700.0,
        "cost_rel": 25.0,
    },
    "Hastelloy_C276": {
        "family": "nickel_superalloy",
        "density": 8890.0,
        "E": 205.0,
        "sigma_y": 283.0,
        "sigma_uts": 690.0,
        "sigma_e": 250.0,
        "k": 10.2,
        "CTE": 11.2,
        "T_max": 1040.0,
        "cost_rel": 22.0,
    },
}

# Computed properties cached lazily on first access
_DERIVED_CACHE: dict[str, dict[str, float]] = {}


def _derived(name: str, props: dict) -> dict[str, float]:
    """Compute and cache Ashby merit indices for a material."""
    if name in _DERIVED_CACHE:
        return _DERIVED_CACHE[name]
    rho = props["density"]       # kg/m³
    E = props["E"]               # GPa
    sy = props["sigma_y"]        # MPa
    cost = props["cost_rel"]

    # Specific stiffness: E/ρ  [GPa·m³/kg]
    spec_stiff = E / rho

    # Specific strength: σy/ρ  [MPa·m³/kg]
    spec_str = sy / rho

    # Light stiff beam: E^(1/2)/ρ  — minimise mass of a stiffness-limited beam
    light_stiff = math.sqrt(E) / rho

    # Light strong plate: σy^(2/3)/ρ  — minimise mass of a yield-limited plate
    light_strong = sy ** (2.0 / 3.0) / rho

    # Cost per stiffness: cost_rel × ρ / E  — relative cost per unit stiffness
    cost_per_stiff = cost * rho / E if E > 0 else float("inf")

    result = {
        "specific_stiffness": spec_stiff,
        "specific_strength": spec_str,
        "light_stiff_beam": light_stiff,
        "light_strong_plate": light_strong,
        "cost_per_stiffness": cost_per_stiff,
    }
    _DERIVED_CACHE[name] = result
    return result


# ---------------------------------------------------------------------------
# Valid constraint keys (base + derived)
# ---------------------------------------------------------------------------

_BASE_PROPS = {
    "density", "E", "sigma_y", "sigma_uts", "sigma_e",
    "k", "CTE", "T_max", "cost_rel",
}

_DERIVED_PROPS = {
    "specific_stiffness", "specific_strength",
    "light_stiff_beam", "light_strong_plate",
    "cost_per_stiffness",
}

_ALL_PROPS = _BASE_PROPS | _DERIVED_PROPS

_VALID_OBJECTIVES = {
    "specific_stiffness",
    "specific_strength",
    "light_stiff_beam",
    "light_strong_plate",
    "cost_per_stiffness",
    # lower-is-better raw properties
    "density",
    "cost_rel",
    "CTE",
}

# For objectives where a lower value is better
_LOWER_IS_BETTER = {"cost_per_stiffness", "density", "cost_rel", "CTE"}


def _get_prop_value(name: str, props: dict, prop: str) -> float | None:
    """Return numeric value for *prop* from base props or derived indices."""
    if prop in _BASE_PROPS:
        return float(props.get(prop, 0.0))
    if prop in _DERIVED_PROPS:
        return _derived(name, props).get(prop)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_material(name: str) -> dict | None:
    """Return full property dict for material *name*, or None if not found.

    The returned dict includes both base properties and computed Ashby indices.
    """
    props = _DB.get(name)
    if props is None:
        return None
    result = {"name": name}
    result.update(props)
    result.update(_derived(name, props))
    return result


def list_materials() -> list[str]:
    """Return sorted list of all material names in the database."""
    return sorted(_DB.keys())


def filter_materials(
    constraints: dict[str, dict[str, float]],
) -> dict:
    """Filter the material database against min/max property constraints.

    Parameters
    ----------
    constraints : dict
        Mapping of property_name → {"min": value, "max": value}.
        Each entry may have "min", "max", or both.
        Property names may be any key in _ALL_PROPS.

    Returns
    -------
    dict
        ok        : True
        materials : list of material names passing all constraints
        warnings  : list of warning strings (e.g. empty result set)

    Never raises.  Returns ok=False only for type errors.
    """
    warnings: list[str] = []

    if not isinstance(constraints, dict):
        return {"ok": False, "reason": "constraints must be a dict"}

    # Validate constraint keys
    for prop in constraints:
        if prop not in _ALL_PROPS:
            warnings.append(
                f"Unknown property {prop!r}; valid: {sorted(_ALL_PROPS)}"
            )

    passing: list[str] = []

    for mat_name, props in _DB.items():
        ok = True
        for prop, bounds in constraints.items():
            if prop not in _ALL_PROPS:
                continue  # already warned above

            val = _get_prop_value(mat_name, props, prop)
            if val is None:
                ok = False
                break

            lo = bounds.get("min")
            hi = bounds.get("max")

            if lo is not None:
                try:
                    if val < float(lo):
                        ok = False
                        break
                except (TypeError, ValueError):
                    warnings.append(f"Non-numeric min for {prop!r}: {lo!r}")
                    ok = False
                    break

            if hi is not None:
                try:
                    if val > float(hi):
                        ok = False
                        break
                except (TypeError, ValueError):
                    warnings.append(f"Non-numeric max for {prop!r}: {hi!r}")
                    ok = False
                    break

        if ok:
            passing.append(mat_name)

    if not passing:
        warnings.append(
            "No materials satisfy all constraints; consider relaxing one or more bounds."
        )

    return {"ok": True, "materials": sorted(passing), "warnings": warnings}


def ashby_rank(
    index: str,
    candidates: list[str] | None = None,
    top_n: int | None = None,
    ascending: bool | None = None,
) -> dict:
    """Rank materials by a named Ashby merit index or raw property.

    Parameters
    ----------
    index : str
        Merit index or raw property name.  Supported:
          "specific_stiffness"   — E/ρ              (higher is better)
          "specific_strength"    — σy/ρ             (higher is better)
          "light_stiff_beam"     — E^0.5/ρ          (higher is better)
          "light_strong_plate"   — σy^(2/3)/ρ       (higher is better)
          "cost_per_stiffness"   — cost·ρ/E         (lower is better)
          "density"                                  (lower is better)
          "cost_rel"                                 (lower is better)
          "CTE"                                      (lower is better)
          ...and any key in _ALL_PROPS.
    candidates : list[str] | None
        Subset of material names to rank.  None = all materials.
    top_n : int | None
        Return at most this many results.  None = all.
    ascending : bool | None
        Override sort direction.  None = use default for this index.

    Returns
    -------
    dict
        ok      : True
        index   : index name used
        ranked  : list of {"name": ..., "value": ..., "rank": ...} dicts
                  sorted best-first
        warnings: list of warning strings
    """
    warnings: list[str] = []

    if index not in _ALL_PROPS:
        return {
            "ok": False,
            "reason": (
                f"Unknown index {index!r}. Valid: {sorted(_ALL_PROPS)}"
            ),
        }

    if candidates is None:
        mat_names = list(_DB.keys())
    else:
        mat_names = []
        for n in candidates:
            if n in _DB:
                mat_names.append(n)
            else:
                warnings.append(f"Unknown material {n!r} — skipped.")

    scores: list[tuple[str, float]] = []
    for name in mat_names:
        props = _DB[name]
        val = _get_prop_value(name, props, index)
        if val is None or not math.isfinite(val):
            warnings.append(f"{name}: could not compute {index!r} — skipped.")
            continue
        scores.append((name, val))

    if ascending is None:
        sort_ascending = index in _LOWER_IS_BETTER
    else:
        sort_ascending = bool(ascending)

    scores.sort(key=lambda x: x[1], reverse=(not sort_ascending))

    if top_n is not None:
        try:
            scores = scores[: int(top_n)]
        except (TypeError, ValueError):
            warnings.append(f"top_n {top_n!r} is not a valid integer — returning all.")

    ranked = [
        {"name": name, "value": value, "rank": i + 1}
        for i, (name, value) in enumerate(scores)
    ]

    return {
        "ok": True,
        "index": index,
        "ranked": ranked,
        "warnings": warnings,
    }


def select_material(
    constraints: dict[str, dict[str, float]],
    objective: str = "specific_stiffness",
    top_n: int = 10,
) -> dict:
    """Select and rank materials matching constraints, optimised by objective.

    This is the primary Ashby selection function.  It:
      1. Filters the database to materials satisfying all constraints.
      2. Ranks the survivors by the chosen Ashby merit index.
      3. Returns the top_n results with index values.

    Parameters
    ----------
    constraints : dict
        Property constraints as accepted by filter_materials().
    objective : str
        Merit index or property to optimise.  Default: "specific_stiffness".
    top_n : int
        Maximum number of results to return.  Default: 10.

    Returns
    -------
    dict
        ok       : True
        objective: objective used
        ranked   : ranked list (same format as ashby_rank)
        warnings : accumulated warnings from both filtering and ranking
    """
    warnings: list[str] = []

    if objective not in _ALL_PROPS:
        return {
            "ok": False,
            "reason": (
                f"Unknown objective {objective!r}. Valid: {sorted(_ALL_PROPS)}"
            ),
        }

    filt = filter_materials(constraints)
    warnings.extend(filt.get("warnings", []))

    if not filt["ok"]:
        return {"ok": False, "reason": filt.get("reason", "filter failed"), "warnings": warnings}

    survivors = filt["materials"]
    if not survivors:
        return {
            "ok": True,
            "objective": objective,
            "ranked": [],
            "warnings": warnings,
        }

    rank_result = ashby_rank(index=objective, candidates=survivors, top_n=top_n)
    warnings.extend(rank_result.get("warnings", []))

    return {
        "ok": True,
        "objective": objective,
        "ranked": rank_result["ranked"],
        "warnings": warnings,
    }
