"""
End-of-life circularity: EN 15978 Module D credit calculation + Ellen MacArthur MCI.

References:
  - EN 15978:2011 §11.4 — Module D (beyond system boundary): net benefits from
    reuse, recovery, and recycling.
  - EU Circular Economy Action Plan (2020) — circular economy performance metrics.
  - Ellen MacArthur Foundation, "Circularity Indicators: An Approach to Measuring
    Circularity" (2015) — Material Circularity Indicator (MCI) methodology.
  - ISO 14044:2006 — LCA framework: allocation, system expansion, credit rules.
  - ICE v3 (Univ. of Bath) — embodied-carbon displacement factors.

IMPORTANT: This module implements EN 15978 + MCI calculation methods.
It does NOT produce an EN-certified LCA report. Results should be used for
design-stage comparative analysis only. Certified EPDs require accredited
third-party verification.

Module D scope (EN 15978 §11.4):
  "The potential net benefits or loads from reuse, recovery and/or recycling
  potential expressed beyond the system boundary of the building."
  Module D is INFORMATIONAL — reported separately, not summed into A1–C lifecycle.

EN 15978 Module D credit formula:
  credit = recovery_efficiency × displacement_factor × virgin_material_GWP

Ellen MacArthur MCI formula (simplified):
  MCI = F_utility × (1 − 0.9 × V × W)
  where:
    F_utility = lifetime utility factor (service life vs. industry average)
    V = virgin / non-circular input fraction
    W = waste / landfill/incineration leakage fraction
  Mapped onto available data per the EMF indicator methodology paper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kerf_lca.materials import lookup_material
from kerf_lca.phases import GRID_FACTORS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ICE v3 displacement factors for recycling credit (fraction of virgin GWP
# credited as Module D benefit).  Source: ICE v3 Table 3 + EN 15978 annex.
# Represents the fraction of avoided virgin-production burden allocated to
# the recycling system via 50:50 allocation (EN 15978 default approach).
_DEFAULT_DISPLACEMENT_FACTOR = 0.50  # 50:50 allocation (EN 15978 Annex D)

# High-quality recycling loops (closed-loop) use substitution factor = 1.0
# (avoided virgin burden = 100%) before recovery efficiency discount.
# Source: EN 15978 §11.4.2 formula + ICE v3 methodology notes.
_CLOSED_LOOP_DISPLACEMENT = 1.0

# Recovery efficiency defaults by material class (source: Eurostat 2022 recycling
# rate statistics, WRAP material flows, EN 15978 informative examples).
_MATERIAL_RECOVERY_EFFICIENCY: dict[str, float] = {
    "metals":    0.90,   # steel/aluminium: high closed-loop recovery
    "plastics":  0.35,   # mixed plastics recycling rate (EU 2022)
    "glass":     0.75,   # container + flat glass combined
    "timber":    0.45,   # timber/wood products (energy recovery + recycling)
    "concrete":  0.80,   # downcycling to aggregate — lower value retention
    "paper":     0.65,   # paper/cardboard (EU average)
    "rubber":    0.30,   # rubber recycling
    "composites": 0.15,  # CFRP/GFRP: largely landfill today
    "ceramic":   0.25,   # ceramics / refractories
    "other":     0.30,   # catch-all
}

# Reuse displacement factor (avoided re-manufacture, EN 15978 annex I.3).
# Reuse avoids full production GWP; credit = reuse_efficiency × full_GWP.
_REUSE_DISPLACEMENT_FACTOR = 1.0

# Incineration with energy recovery: net electrical output.
# Source: CEWEP (Confederation of European Waste-to-Energy Plants) 2022 average.
_INCINERATION_NET_ENERGY_KWH_PER_KG = 0.50  # kWh electrical / kg waste (conservative)

# Industry-average service life by material category (years) — for MCI utility factor.
# Source: Building Research Establishment (BRE) service life data; EN 15978 RSL tables.
_INDUSTRY_AVG_LIFETIME_YEARS: dict[str, float] = {
    "metals":     50.0,
    "plastics":   15.0,
    "glass":      30.0,
    "timber":     35.0,
    "concrete":   60.0,
    "paper":       1.0,
    "rubber":      8.0,
    "composites": 25.0,
    "ceramic":    40.0,
    "other":      20.0,
}

# ---------------------------------------------------------------------------
# EolScenario dataclass
# ---------------------------------------------------------------------------


@dataclass
class EolScenario:
    """
    End-of-life scenario parameters for Module D credit calculation.

    Attributes:
        scenario_type: one of 'landfill' / 'recycling' / 'reuse' /
            'incineration_with_energy_recovery' / 'composting'.
        recycled_content_credit_kg_co2_per_kg: (informational) credit per kg
            for using recycled material as input vs virgin — from the supply-side.
            Typically embodied_carbon_virgin − embodied_carbon_recycled.
        recovery_efficiency: fraction of end-of-life material actually
            recovered via the stated pathway (0–1).  Accounts for collection
            losses, sorting efficiency, process yield.
        displacement_factor: fraction of virgin-material production burden
            displaced by each kg recycled/reused (0–1).
            EN 15978: 1.0 for closed-loop substitution, 0.5 for 50:50 allocation.
    """

    scenario_type: str
    recycled_content_credit_kg_co2_per_kg: float = 0.0
    recovery_efficiency: float = 0.85
    displacement_factor: float = _DEFAULT_DISPLACEMENT_FACTOR

    _VALID_TYPES = frozenset([
        "landfill",
        "recycling",
        "reuse",
        "incineration_with_energy_recovery",
        "composting",
    ])

    def __post_init__(self) -> None:
        if self.scenario_type not in self._VALID_TYPES:
            raise ValueError(
                f"Invalid scenario_type '{self.scenario_type}'. "
                f"Valid types: {sorted(self._VALID_TYPES)}"
            )
        if not (0.0 <= self.recovery_efficiency <= 1.0):
            raise ValueError("recovery_efficiency must be in [0, 1].")
        if not (0.0 <= self.displacement_factor <= 1.0):
            raise ValueError("displacement_factor must be in [0, 1].")

    @classmethod
    def landfill(cls) -> "EolScenario":
        """No beneficial recovery; Module D credit = 0."""
        return cls(
            scenario_type="landfill",
            recycled_content_credit_kg_co2_per_kg=0.0,
            recovery_efficiency=0.0,
            displacement_factor=0.0,
        )

    @classmethod
    def recycling(
        cls,
        recovery_efficiency: float = 0.85,
        displacement_factor: float = _DEFAULT_DISPLACEMENT_FACTOR,
        recycled_content_credit_kg_co2_per_kg: float = 0.0,
    ) -> "EolScenario":
        """Open- or closed-loop recycling with EN 15978 50:50 allocation default."""
        return cls(
            scenario_type="recycling",
            recycled_content_credit_kg_co2_per_kg=recycled_content_credit_kg_co2_per_kg,
            recovery_efficiency=recovery_efficiency,
            displacement_factor=displacement_factor,
        )

    @classmethod
    def reuse(cls, recovery_efficiency: float = 0.90) -> "EolScenario":
        """
        Direct reuse — component re-enters the use phase without reprocessing.
        Displacement factor = 1.0 (full avoided re-manufacture credit).
        """
        return cls(
            scenario_type="reuse",
            recycled_content_credit_kg_co2_per_kg=0.0,
            recovery_efficiency=recovery_efficiency,
            displacement_factor=_REUSE_DISPLACEMENT_FACTOR,
        )

    @classmethod
    def incineration_with_energy_recovery(
        cls, recovery_efficiency: float = 0.85
    ) -> "EolScenario":
        """Waste-to-energy: grid electricity displacement credit."""
        return cls(
            scenario_type="incineration_with_energy_recovery",
            recycled_content_credit_kg_co2_per_kg=0.0,
            recovery_efficiency=recovery_efficiency,
            displacement_factor=0.0,  # overridden in compute_module_d_credit
        )

    @classmethod
    def composting(cls, recovery_efficiency: float = 0.70) -> "EolScenario":
        """Biological treatment / composting (organic materials)."""
        return cls(
            scenario_type="composting",
            recycled_content_credit_kg_co2_per_kg=0.0,
            recovery_efficiency=recovery_efficiency,
            displacement_factor=0.10,  # peat/fertiliser displacement (minor)
        )


# ---------------------------------------------------------------------------
# Module D credit calculation (EN 15978 §11.4)
# ---------------------------------------------------------------------------


def compute_module_d_credit(
    material: str,
    mass_kg: float,
    eol_scenario: EolScenario,
    *,
    grid_region: str = "WORLD",
) -> dict[str, Any]:
    """
    Compute the EN 15978 Module D end-of-life benefit (carbon credit).

    Module D represents "net benefits or loads from reuse, recovery and/or
    recycling potential expressed beyond the system boundary" (EN 15978 §11.4).
    It is INFORMATIONAL — not included in the A1–C total; reported separately.

    Formula by scenario:
      recycling / reuse:
        credit_kg_CO2 = mass_kg × recovery_efficiency × displacement_factor
                        × embodied_carbon_per_kg_virgin
      incineration_with_energy_recovery:
        credit_kg_CO2 = mass_kg × recovery_efficiency × energy_kWh_per_kg
                        × grid_emission_factor_kgCO2_per_kWh
      landfill / composting:
        credit_kg_CO2 = 0  (no net benefit)

    Args:
        material: material name/key (resolved via ICE v3 lookup).
        mass_kg: mass of end-of-life material (kg).
        eol_scenario: EolScenario dataclass with pathway parameters.
        grid_region: ISO 3166-1 alpha-2 key for electricity grid emission factor
            (used in incineration_with_energy_recovery only).

    Returns:
        dict with:
          material_id, material_label, mass_kg,
          scenario_type, recovery_efficiency, displacement_factor,
          embodied_carbon_factor_kg_co2_per_kg,
          module_d_credit_kg_co2  (positive = benefit, i.e. carbon saved),
          method_note,
          warning  (if material not found),
          honesty_note.
    """
    if mass_kg <= 0:
        raise ValueError("mass_kg must be positive.")

    mat = lookup_material(material)
    warning = ""
    if mat is None:
        warning = (
            f"Material '{material}' not found in ICE v3 database. "
            "Module D credit calculated using zero embodied-carbon factor."
        )
        embodied_factor = 0.0
        mat_id = ""
        mat_label = material
        category = "other"
    else:
        embodied_factor = mat["embodied_carbon_kg_co2_per_kg"]
        mat_id = mat["id"]
        mat_label = mat["label"]
        category = mat.get("category", "other")

    stype = eol_scenario.scenario_type
    eta = eol_scenario.recovery_efficiency   # recovery efficiency
    q   = eol_scenario.displacement_factor   # displacement factor / substitution ratio

    credit = 0.0
    method_note = ""

    if stype == "recycling":
        # EN 15978 §11.4.2 formula:
        # Module D = (eta_rec × Q_rec / Q_in) × (GWP_secondary - GWP_virgin)
        # Simplified to: credit = mass × eta × q × embodied_factor_virgin
        credit = mass_kg * eta * q * embodied_factor
        method_note = (
            f"EN 15978 §11.4 recycling credit: {mass_kg} kg × "
            f"η={eta} × q={q} × {embodied_factor:.4f} kg CO₂/kg = "
            f"{credit:.4f} kg CO₂ saved"
        )

    elif stype == "reuse":
        # Reuse avoids full re-manufacture; displacement_factor=1.0 per EN 15978 annex.
        # credit = mass × eta × 1.0 × full_embodied_factor
        credit = mass_kg * eta * _REUSE_DISPLACEMENT_FACTOR * embodied_factor
        method_note = (
            f"EN 15978 §11.4 reuse credit: {mass_kg} kg × "
            f"η={eta} × displacement=1.0 × {embodied_factor:.4f} = "
            f"{credit:.4f} kg CO₂ saved"
        )

    elif stype == "incineration_with_energy_recovery":
        # EN 15978 Module D: credit = recovered energy × grid emission factor
        # (system expansion / avoided electricity production)
        grid_ef = GRID_FACTORS.get(grid_region.upper(), GRID_FACTORS["WORLD"])
        recovered_energy_kWh = mass_kg * eta * _INCINERATION_NET_ENERGY_KWH_PER_KG
        credit = recovered_energy_kWh * grid_ef
        method_note = (
            f"EN 15978 §11.4 energy-recovery credit: {mass_kg} kg × "
            f"η={eta} × {_INCINERATION_NET_ENERGY_KWH_PER_KG} kWh/kg × "
            f"{grid_ef} kg CO₂/kWh ({grid_region}) = {credit:.4f} kg CO₂ saved"
        )

    elif stype == "landfill":
        credit = 0.0
        method_note = "Landfill: no Module D credit (no beneficial recovery)."

    elif stype == "composting":
        # Minor peat/fertiliser displacement
        credit = mass_kg * eta * eol_scenario.displacement_factor * 0.10
        method_note = (
            f"Composting: minor nutrient-displacement credit "
            f"({credit:.4f} kg CO₂ saved)."
        )

    result: dict[str, Any] = {
        "material_id": mat_id,
        "material_label": mat_label,
        "mass_kg": mass_kg,
        "scenario_type": stype,
        "recovery_efficiency": eta,
        "displacement_factor": q,
        "embodied_carbon_factor_kg_co2_per_kg": embodied_factor,
        "module_d_credit_kg_co2": round(credit, 6),
        "method_note": method_note,
        "honesty_note": (
            "Module D is informational per EN 15978:2011 §11.4 — "
            "reported separately from the A1–C lifecycle total. "
            "NOT an EN-certified LCA report."
        ),
    }
    if warning:
        result["warning"] = warning
    return result


# ---------------------------------------------------------------------------
# Material Circularity Indicator (Ellen MacArthur Foundation)
# ---------------------------------------------------------------------------


def circularity_index(
    material: str,
    design_intent: dict,
) -> float:
    """
    Compute the Material Circularity Indicator (MCI) per Ellen MacArthur Foundation
    methodology (2015, "Circularity Indicators: An Approach to Measuring Circularity").

    MCI ∈ [0, 1] where 1.0 = fully circular, 0.0 = fully linear.

    Full EMF formula (product level):
      MCI = F_utility × (1 − 0.9 × V × W)
    where:
      F_utility = min(L / L_avg, 1) × min(X / X_avg, 1)
          L     = product lifetime (years)
          L_avg = industry average lifetime for the material class
          X     = usage intensity (relative utilisation; set to 1 if unknown)
          X_avg = industry average utilisation (= 1 by default)
      V = (1 − R_in)        = virgin / non-circular input fraction
          R_in = recycled input fraction (0–1)
      W = (1 − R_out × C_r) = unrecovered waste fraction
          R_out = fraction of material recycled/reused at EoL
          C_r   = recyclability quality factor (0–1; 1 = same quality)

    The factor 0.9 is the EMF scaling constant; V×W product approaches 1
    for fully linear (virgin in, landfill out).

    Args:
        material: material name/key (ICE v3).
        design_intent: dict with optional keys:
            recycled_input_fraction  (float, 0–1): fraction of mass from
                recycled/reused sources at point of manufacture.
                Default: material's ICE v3 recycled_content_pct / 100.
            eol_recycling_fraction   (float, 0–1): fraction of product mass
                recycled/reused at end of life.
                Default: material's ICE v3 recyclability_pct / 100.
            recyclability_quality    (float, 0–1): quality of recycling loop
                (1.0 = same-quality closed-loop; 0.5 = open-loop / downcycling).
                Default: 0.9 for metals/glass, 0.5 for others.
            lifetime_years           (float): product service life in years.
                Default: industry average for material class.
            eol_scenario             (str): 'recycling' | 'reuse' | 'landfill' |
                'incineration_with_energy_recovery' | 'composting'.
                Overrides eol_recycling_fraction if set.

    Returns:
        MCI value ∈ [0, 1].
    """
    mat = lookup_material(material)
    category = mat.get("category", "other") if mat else "other"

    # --- Defaults from ICE v3 database ---
    if mat is not None:
        r_in_default = mat.get("recycled_content_pct", 0) / 100.0
        r_out_default = mat.get("recyclability_pct", 30) / 100.0
    else:
        r_in_default = 0.0
        r_out_default = 0.30

    # --- Read design_intent overrides ---
    r_in = float(design_intent.get("recycled_input_fraction", r_in_default))
    r_in = max(0.0, min(1.0, r_in))

    # EoL scenario override: if specified, look up default recovery rate
    eol_scenario_str = (design_intent.get("eol_scenario") or "").lower()
    if eol_scenario_str in ("recycling", "reuse"):
        # Use material's recyclability as base, possibly overridden further
        r_out_base = r_out_default
    elif eol_scenario_str in ("landfill", "composting"):
        r_out_base = 0.0
    elif eol_scenario_str == "incineration_with_energy_recovery":
        # Energy recovery is partial circularity — treated as ~30% equivalent
        # per EMF guidance (energy recovery is "less circular" than material recycling)
        r_out_base = 0.30
    else:
        r_out_base = r_out_default

    r_out = float(design_intent.get("eol_recycling_fraction", r_out_base))
    r_out = max(0.0, min(1.0, r_out))

    # Recyclability quality factor — closed-loop metals/glass score higher
    if category in ("metals", "glass"):
        c_r_default = 0.90  # near-closed-loop quality
    else:
        c_r_default = 0.50
    c_r = float(design_intent.get("recyclability_quality", c_r_default))
    c_r = max(0.0, min(1.0, c_r))

    # --- Utility factor F_utility ---
    lifetime_years = design_intent.get("lifetime_years")
    avg_lifetime = _INDUSTRY_AVG_LIFETIME_YEARS.get(category, 20.0)
    if lifetime_years is not None:
        lifetime_years = float(lifetime_years)
        # Cap at 1.0 (longer life improves circularity up to industry avg)
        f_utility = min(lifetime_years / avg_lifetime, 1.0)
    else:
        f_utility = 1.0  # no lifetime penalty if not specified

    # Usage intensity X / X_avg → assume 1.0 (unknown)
    # f_utility stays as-is (single-factor: only lifetime)

    # --- V and W factors ---
    V = 1.0 - r_in          # virgin input fraction
    W = 1.0 - r_out * c_r  # unrecovered waste fraction

    # --- MCI ---
    mci = f_utility * (1.0 - 0.9 * V * W)
    mci = max(0.0, min(1.0, mci))

    return round(mci, 4)


# ---------------------------------------------------------------------------
# Full lifecycle carbon (cradle-to-grave + Module D)
# ---------------------------------------------------------------------------


def compute_full_lifecycle_carbon(
    material: str,
    mass_kg: float,
    lifetime_years: float,
    eol_scenario: EolScenario,
    *,
    use_phase_kg_co2: float = 0.0,
    transport_kg_co2: float = 0.0,
    grid_region: str = "WORLD",
) -> dict[str, Any]:
    """
    Cradle-to-grave GWP + EN 15978 Module D credit.

    Scope:
      A1–A3  Cradle-to-gate (ICE v3 embodied carbon)
      A4     Transport (supplied separately or zero)
      B1–B7  Use phase (supplied separately or zero)
      C3–C4  End-of-life processing (waste management)
      D      Module D benefit — recycling / reuse / energy recovery credit

    Module D is INFORMATIONAL and reported separately per EN 15978:2011 §11.4.
    The "total_with_module_d" figure is provided for design-stage comparison
    only, not as a certified declaration.

    Args:
        material: material name/key.
        mass_kg: mass in kg.
        lifetime_years: product service life in years (for context/reporting).
        eol_scenario: EolScenario defining the EoL pathway.
        use_phase_kg_co2: Module B use-phase GWP (kg CO₂-eq). Default 0.
        transport_kg_co2: Module A4/C2 transport GWP (kg CO₂-eq). Default 0.
        grid_region: grid emission region for incineration energy credit.

    Returns:
        dict with:
          material_id, material_label, mass_kg, lifetime_years,
          a1_a3_cradle_to_gate_kg_co2,
          b_use_phase_kg_co2,
          transport_kg_co2,
          c3_c4_eol_processing_kg_co2,
          total_cradle_to_grave_kg_co2  (A1–C, excluding Module D),
          module_d_credit_kg_co2        (positive = benefit),
          total_with_module_d_kg_co2    (informational),
          circularity_index,
          module_d_breakdown,
          honesty_note.
    """
    if mass_kg <= 0:
        raise ValueError("mass_kg must be positive.")
    if lifetime_years <= 0:
        raise ValueError("lifetime_years must be positive.")

    mat = lookup_material(material)
    warning = ""
    if mat is None:
        warning = (
            f"Material '{material}' not found in ICE v3 database. "
            "Embodied carbon set to 0.0."
        )
        embodied_factor = 0.0
        mat_id = ""
        mat_label = material
    else:
        embodied_factor = mat["embodied_carbon_kg_co2_per_kg"]
        mat_id = mat["id"]
        mat_label = mat["label"]

    # A1–A3: cradle-to-gate
    a1_a3 = embodied_factor * mass_kg

    # C3–C4: EoL processing burden (small positive, not the Module D credit)
    # Landfill: ~0.025 kg CO₂/kg transport + burial
    # Recycling: ~0.020 kg CO₂/kg (collection + sorting)
    # Incineration: ~0.05 kg CO₂/kg process
    _eol_process_factors = {
        "landfill":                         0.025,
        "recycling":                        0.020,
        "reuse":                            0.010,
        "incineration_with_energy_recovery": 0.050,
        "composting":                       0.015,
    }
    c3_c4 = mass_kg * _eol_process_factors.get(eol_scenario.scenario_type, 0.025)

    # Module D credit
    module_d_result = compute_module_d_credit(
        material, mass_kg, eol_scenario, grid_region=grid_region
    )
    module_d_credit = module_d_result["module_d_credit_kg_co2"]

    # Totals
    total_ctg = a1_a3 + use_phase_kg_co2 + transport_kg_co2 + c3_c4
    total_with_d = total_ctg - module_d_credit  # subtract credit (it's a benefit)

    # MCI
    design_intent: dict[str, Any] = {
        "eol_scenario": eol_scenario.scenario_type,
        "lifetime_years": lifetime_years,
    }
    if mat is not None:
        design_intent["recycled_input_fraction"] = mat.get("recycled_content_pct", 0) / 100.0
        design_intent["eol_recycling_fraction"] = mat.get("recyclability_pct", 30) / 100.0

    mci = circularity_index(material, design_intent)

    result: dict[str, Any] = {
        "material_id": mat_id,
        "material_label": mat_label,
        "mass_kg": mass_kg,
        "lifetime_years": lifetime_years,
        "a1_a3_cradle_to_gate_kg_co2": round(a1_a3, 6),
        "b_use_phase_kg_co2": round(use_phase_kg_co2, 6),
        "transport_kg_co2": round(transport_kg_co2, 6),
        "c3_c4_eol_processing_kg_co2": round(c3_c4, 6),
        "total_cradle_to_grave_kg_co2": round(total_ctg, 6),
        "module_d_credit_kg_co2": round(module_d_credit, 6),
        "total_with_module_d_kg_co2": round(total_with_d, 6),
        "circularity_index": mci,
        "module_d_breakdown": module_d_result,
        "honesty_note": (
            "EN 15978 + Ellen MacArthur MCI methods applied. "
            "Module D is informational (beyond system boundary) per EN 15978:2011 §11.4. "
            "NOT an EN-certified LCA report. "
            "Use project-specific EPDs for certified declarations."
        ),
    }
    if warning:
        result["warning"] = warning
    return result
