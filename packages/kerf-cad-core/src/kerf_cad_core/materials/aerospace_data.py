"""
kerf_cad_core.materials.aerospace_data — certified aerospace material property database.

Hand-authored database of 33 certified aerospace alloys and composites with full
mechanical, thermal, and fatigue properties.  All property values are typical
mid-range values based on publicly available sources:
  - MIL-HDBK-5J (Metallic Materials and Elements for Aerospace Vehicle Structures)
  - CMH-17 (Composite Materials Handbook)
  - ASM Handbook Volumes 1 & 2
  - AMS specifications (publicly available datasheets)
  - Callister & Rethwisch "Materials Science and Engineering", 9th ed.
  - Boyer, Collings & Welsch "Materials Properties Handbook: Titanium Alloys" (ASM)

No proprietary dataset is reproduced.  These are typical textbook/specification
mid-range estimates authored from publicly available engineering literature.

Property schema (SI unless noted)
----------------------------------
name                str    canonical name
category            str    material category
density_kg_m3       float  kg/m³
elastic_modulus_GPa float  GPa    Young's modulus (longitudinal for composites)
shear_modulus_GPa   float  GPa    shear modulus
poisson_ratio       float  —      Poisson ratio
yield_strength_MPa  float  MPa    0.2% proof / yield; tensile strength for composites
ultimate_strength_MPa float MPa   ultimate tensile strength
elongation_pct      float  %      elongation at break
cte_per_K           float  1/K    coefficient of thermal expansion (linear)
thermal_conductivity_W_mK float W/(m·K)
specific_heat_J_kgK float  J/(kg·K)
max_service_temp_C  float  °C     max continuous service temperature
fatigue_limit_MPa   float  MPa    S-N at 10^7 cycles (fully-reversed R=-1 unless noted)
fracture_toughness_K1c_MPa_sqrt_m float MPa·√m
specification       str    primary governing specification
description         str    brief description

Author: imranparuk
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Database — 33 certified aerospace materials
# ---------------------------------------------------------------------------

AEROSPACE_DB: list[dict[str, Any]] = [

    # =========================================================================
    # ALUMINIUM ALLOYS
    # =========================================================================

    {
        "name": "2024-T3",
        "category": "aluminium",
        "density_kg_m3": 2780.0,
        "elastic_modulus_GPa": 73.1,
        "shear_modulus_GPa": 28.0,
        "poisson_ratio": 0.33,
        "yield_strength_MPa": 345.0,
        "ultimate_strength_MPa": 483.0,
        "elongation_pct": 15.0,
        "cte_per_K": 23.2e-6,
        "thermal_conductivity_W_mK": 121.0,
        "specific_heat_J_kgK": 875.0,
        "max_service_temp_C": 130.0,
        "fatigue_limit_MPa": 138.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 37.0,
        "specification": "AMS 2770 / AMS-QQ-A-250/4",
        "description": (
            "Workhorse clad sheet alloy; dominant in fuselage skin and wing "
            "lower cover applications; excellent damage tolerance."
        ),
    },
    {
        "name": "2024-T4",
        "category": "aluminium",
        "density_kg_m3": 2780.0,
        "elastic_modulus_GPa": 73.1,
        "shear_modulus_GPa": 28.0,
        "poisson_ratio": 0.33,
        "yield_strength_MPa": 325.0,
        "ultimate_strength_MPa": 469.0,
        "elongation_pct": 19.0,
        "cte_per_K": 23.2e-6,
        "thermal_conductivity_W_mK": 121.0,
        "specific_heat_J_kgK": 875.0,
        "max_service_temp_C": 130.0,
        "fatigue_limit_MPa": 130.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 40.0,
        "specification": "AMS 2770 / AMS-QQ-A-250/4",
        "description": (
            "Solution heat-treated and naturally aged; higher elongation than "
            "T3; used in formed/bent structural sheet."
        ),
    },
    {
        "name": "6061-T6",
        "category": "aluminium",
        "density_kg_m3": 2700.0,
        "elastic_modulus_GPa": 68.9,
        "shear_modulus_GPa": 26.0,
        "poisson_ratio": 0.33,
        "yield_strength_MPa": 276.0,
        "ultimate_strength_MPa": 310.0,
        "elongation_pct": 12.0,
        "cte_per_K": 23.6e-6,
        "thermal_conductivity_W_mK": 167.0,
        "specific_heat_J_kgK": 896.0,
        "max_service_temp_C": 150.0,
        "fatigue_limit_MPa": 97.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 29.0,
        "specification": "AMS 2770 / AMS-QQ-A-200/8",
        "description": (
            "General-purpose structural alloy; excellent weldability and "
            "corrosion resistance; widely used in airframes, fittings, and "
            "hydraulic tubing."
        ),
    },
    {
        "name": "7050-T7451",
        "category": "aluminium",
        "density_kg_m3": 2830.0,
        "elastic_modulus_GPa": 71.7,
        "shear_modulus_GPa": 26.9,
        "poisson_ratio": 0.33,
        "yield_strength_MPa": 462.0,
        "ultimate_strength_MPa": 524.0,
        "elongation_pct": 10.0,
        "cte_per_K": 23.5e-6,
        "thermal_conductivity_W_mK": 157.0,
        "specific_heat_J_kgK": 860.0,
        "max_service_temp_C": 120.0,
        "fatigue_limit_MPa": 145.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 33.0,
        "specification": "AMS 4050 / AMS 2770",
        "description": (
            "High-strength plate alloy optimised for thick sections; "
            "superior stress-corrosion cracking resistance versus 7075-T6; "
            "used in heavy wing spars and bulkheads."
        ),
    },
    {
        "name": "7075-T6",
        "category": "aluminium",
        "density_kg_m3": 2810.0,
        "elastic_modulus_GPa": 71.7,
        "shear_modulus_GPa": 26.9,
        "poisson_ratio": 0.33,
        "yield_strength_MPa": 503.0,
        "ultimate_strength_MPa": 572.0,
        "elongation_pct": 11.0,
        "cte_per_K": 23.6e-6,
        "thermal_conductivity_W_mK": 130.0,
        "specific_heat_J_kgK": 860.0,
        "max_service_temp_C": 120.0,
        "fatigue_limit_MPa": 160.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 24.0,
        "specification": "AMS 4045 / AMS-QQ-A-250/12",
        "description": (
            "Highest-strength conventional aluminium alloy; used in wing "
            "upper skins, stringers, and spars where stress-corrosion "
            "cracking risk is managed."
        ),
    },
    {
        "name": "7075-T73",
        "category": "aluminium",
        "density_kg_m3": 2810.0,
        "elastic_modulus_GPa": 71.7,
        "shear_modulus_GPa": 26.9,
        "poisson_ratio": 0.33,
        "yield_strength_MPa": 434.0,
        "ultimate_strength_MPa": 503.0,
        "elongation_pct": 13.0,
        "cte_per_K": 23.6e-6,
        "thermal_conductivity_W_mK": 155.0,
        "specific_heat_J_kgK": 860.0,
        "max_service_temp_C": 120.0,
        "fatigue_limit_MPa": 145.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 31.0,
        "specification": "AMS 4045 / AMS 2770",
        "description": (
            "Over-aged 7075 with superior stress-corrosion cracking resistance; "
            "preferred for thick forgings and plate in salt environments."
        ),
    },
    {
        "name": "AlLi 2090-T83",
        "category": "aluminium",
        "density_kg_m3": 2590.0,
        "elastic_modulus_GPa": 76.6,
        "shear_modulus_GPa": 28.8,
        "poisson_ratio": 0.34,
        "yield_strength_MPa": 517.0,
        "ultimate_strength_MPa": 552.0,
        "elongation_pct": 5.0,
        "cte_per_K": 21.4e-6,
        "thermal_conductivity_W_mK": 84.0,
        "specific_heat_J_kgK": 880.0,
        "max_service_temp_C": 120.0,
        "fatigue_limit_MPa": 172.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 34.0,
        "specification": "AMS 2770 / AMS 4351",
        "description": (
            "Al-Li alloy with ~10% lower density and ~10% higher modulus than "
            "2024; used in fuselage frames and floor structures where weight "
            "and stiffness are critical."
        ),
    },

    # =========================================================================
    # TITANIUM ALLOYS
    # =========================================================================

    {
        "name": "Ti-6Al-4V annealed",
        "category": "titanium",
        "density_kg_m3": 4430.0,
        "elastic_modulus_GPa": 113.8,
        "shear_modulus_GPa": 44.0,
        "poisson_ratio": 0.342,
        "yield_strength_MPa": 828.0,
        "ultimate_strength_MPa": 897.0,
        "elongation_pct": 14.0,
        "cte_per_K": 8.6e-6,
        "thermal_conductivity_W_mK": 7.2,
        "specific_heat_J_kgK": 560.0,
        "max_service_temp_C": 315.0,
        "fatigue_limit_MPa": 510.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 75.0,
        "specification": "AMS 4928 / AMS-T-9046",
        "description": (
            "Most widely used titanium alloy; α+β microstructure; excellent "
            "balance of strength, toughness, and weldability; dominant in "
            "airframe fittings, fasteners, and fan blades."
        ),
    },
    {
        "name": "Ti-6Al-4V STA",
        "category": "titanium",
        "density_kg_m3": 4430.0,
        "elastic_modulus_GPa": 113.8,
        "shear_modulus_GPa": 44.0,
        "poisson_ratio": 0.342,
        "yield_strength_MPa": 1103.0,
        "ultimate_strength_MPa": 1172.0,
        "elongation_pct": 10.0,
        "cte_per_K": 8.6e-6,
        "thermal_conductivity_W_mK": 7.2,
        "specific_heat_J_kgK": 560.0,
        "max_service_temp_C": 315.0,
        "fatigue_limit_MPa": 620.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 55.0,
        "specification": "AMS 4928 / AMS 2801",
        "description": (
            "Ti-6Al-4V solution treated and aged; higher strength than "
            "annealed at cost of toughness; used in critical structural "
            "forgings and high-load landing gear components."
        ),
    },
    {
        "name": "Ti-6Al-2Sn-4Zr-2Mo",
        "category": "titanium",
        "density_kg_m3": 4540.0,
        "elastic_modulus_GPa": 114.0,
        "shear_modulus_GPa": 44.0,
        "poisson_ratio": 0.325,
        "yield_strength_MPa": 990.0,
        "ultimate_strength_MPa": 1035.0,
        "elongation_pct": 12.0,
        "cte_per_K": 9.0e-6,
        "thermal_conductivity_W_mK": 7.5,
        "specific_heat_J_kgK": 540.0,
        "max_service_temp_C": 450.0,
        "fatigue_limit_MPa": 580.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 66.0,
        "specification": "AMS 4919 / AMS 4975",
        "description": (
            "Near-α high-temperature titanium alloy; superior creep resistance "
            "over Ti-6-4; used in turbine compressor discs and high-temperature "
            "airframe structures."
        ),
    },
    {
        "name": "Ti Beta-21S",
        "category": "titanium",
        "density_kg_m3": 4940.0,
        "elastic_modulus_GPa": 100.0,
        "shear_modulus_GPa": 39.0,
        "poisson_ratio": 0.36,
        "yield_strength_MPa": 1207.0,
        "ultimate_strength_MPa": 1269.0,
        "elongation_pct": 8.0,
        "cte_per_K": 7.1e-6,
        "thermal_conductivity_W_mK": 6.7,
        "specific_heat_J_kgK": 530.0,
        "max_service_temp_C": 425.0,
        "fatigue_limit_MPa": 550.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 38.0,
        "specification": "AMS 4897 / AMS 4897",
        "description": (
            "Metastable β-titanium with high strength and excellent oxidation "
            "resistance; used in high-temperature engine nacelle and "
            "exhaust structures."
        ),
    },
    {
        "name": "CP Titanium Grade 2",
        "category": "titanium",
        "density_kg_m3": 4510.0,
        "elastic_modulus_GPa": 105.0,
        "shear_modulus_GPa": 40.0,
        "poisson_ratio": 0.37,
        "yield_strength_MPa": 275.0,
        "ultimate_strength_MPa": 345.0,
        "elongation_pct": 20.0,
        "cte_per_K": 8.9e-6,
        "thermal_conductivity_W_mK": 16.4,
        "specific_heat_J_kgK": 520.0,
        "max_service_temp_C": 260.0,
        "fatigue_limit_MPa": 170.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 65.0,
        "specification": "AMS 4941 / ASTM B265 Gr 2",
        "description": (
            "Commercially pure titanium; outstanding corrosion resistance; "
            "used in airframe fasteners, hydraulic tubing, and chemical-plant "
            "aerospace components."
        ),
    },

    # =========================================================================
    # STEELS
    # =========================================================================

    {
        "name": "AISI 4130 normalised",
        "category": "steel",
        "density_kg_m3": 7850.0,
        "elastic_modulus_GPa": 205.0,
        "shear_modulus_GPa": 80.0,
        "poisson_ratio": 0.29,
        "yield_strength_MPa": 435.0,
        "ultimate_strength_MPa": 670.0,
        "elongation_pct": 25.9,
        "cte_per_K": 11.2e-6,
        "thermal_conductivity_W_mK": 42.7,
        "specific_heat_J_kgK": 477.0,
        "max_service_temp_C": 400.0,
        "fatigue_limit_MPa": 310.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 65.0,
        "specification": "AMS 6370 / MIL-S-6758",
        "description": (
            "Chrome-molybdenum low-alloy steel; readily welded; used in tubular "
            "airframe structures, engine mounts, and light aircraft fuselage "
            "trusses."
        ),
    },
    {
        "name": "AISI 4340 Q&T",
        "category": "steel",
        "density_kg_m3": 7850.0,
        "elastic_modulus_GPa": 205.0,
        "shear_modulus_GPa": 80.0,
        "poisson_ratio": 0.29,
        "yield_strength_MPa": 1172.0,
        "ultimate_strength_MPa": 1276.0,
        "elongation_pct": 12.0,
        "cte_per_K": 12.3e-6,
        "thermal_conductivity_W_mK": 44.5,
        "specific_heat_J_kgK": 475.0,
        "max_service_temp_C": 430.0,
        "fatigue_limit_MPa": 620.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 80.0,
        "specification": "AMS 6415 / MIL-S-5000",
        "description": (
            "High-strength NiCrMo steel; excellent hardenability in thick "
            "sections; used in landing gear main cylinders, shafts, and "
            "critical structural forgings."
        ),
    },
    {
        "name": "17-4 PH H900",
        "category": "steel",
        "density_kg_m3": 7780.0,
        "elastic_modulus_GPa": 197.0,
        "shear_modulus_GPa": 77.0,
        "poisson_ratio": 0.28,
        "yield_strength_MPa": 1172.0,
        "ultimate_strength_MPa": 1310.0,
        "elongation_pct": 10.0,
        "cte_per_K": 10.8e-6,
        "thermal_conductivity_W_mK": 18.3,
        "specific_heat_J_kgK": 460.0,
        "max_service_temp_C": 315.0,
        "fatigue_limit_MPa": 620.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 55.0,
        "specification": "AMS 5604 / AMS 5643",
        "description": (
            "Martensitic precipitation-hardening stainless; combines high "
            "strength with corrosion resistance; used in aerospace fasteners, "
            "valve bodies, and structural castings."
        ),
    },
    {
        "name": "A-286",
        "category": "steel",
        "density_kg_m3": 7940.0,
        "elastic_modulus_GPa": 201.0,
        "shear_modulus_GPa": 77.0,
        "poisson_ratio": 0.31,
        "yield_strength_MPa": 793.0,
        "ultimate_strength_MPa": 1000.0,
        "elongation_pct": 25.0,
        "cte_per_K": 16.9e-6,
        "thermal_conductivity_W_mK": 14.7,
        "specific_heat_J_kgK": 502.0,
        "max_service_temp_C": 650.0,
        "fatigue_limit_MPa": 450.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 90.0,
        "specification": "AMS 5731 / AMS 5525",
        "description": (
            "Iron-base superalloy; high-temperature fastener standard; used in "
            "turbine bolts, afterburner components, and exhaust systems up to "
            "650 °C."
        ),
    },
    {
        "name": "AerMet 100",
        "category": "steel",
        "density_kg_m3": 7890.0,
        "elastic_modulus_GPa": 197.0,
        "shear_modulus_GPa": 77.0,
        "poisson_ratio": 0.28,
        "yield_strength_MPa": 1724.0,
        "ultimate_strength_MPa": 1965.0,
        "elongation_pct": 14.0,
        "cte_per_K": 11.2e-6,
        "thermal_conductivity_W_mK": 19.4,
        "specific_heat_J_kgK": 460.0,
        "max_service_temp_C": 370.0,
        "fatigue_limit_MPa": 760.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 126.0,
        "specification": "AMS 6532",
        "description": (
            "Ultra-high-strength secondary-hardening steel; outstanding "
            "fracture toughness at ≥1700 MPa strength; used in Navy carrier "
            "aircraft landing gear and tailhooks."
        ),
    },
    {
        "name": "300M",
        "category": "steel",
        "density_kg_m3": 7850.0,
        "elastic_modulus_GPa": 206.0,
        "shear_modulus_GPa": 80.0,
        "poisson_ratio": 0.28,
        "yield_strength_MPa": 1655.0,
        "ultimate_strength_MPa": 1931.0,
        "elongation_pct": 9.0,
        "cte_per_K": 11.2e-6,
        "thermal_conductivity_W_mK": 36.7,
        "specific_heat_J_kgK": 460.0,
        "max_service_temp_C": 350.0,
        "fatigue_limit_MPa": 690.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 66.0,
        "specification": "AMS 6257 / MIL-S-8844",
        "description": (
            "Modified 4340 with vanadium and silicon; very high strength for "
            "landing gear structural members; widely used in commercial and "
            "military main gear cylinders."
        ),
    },

    # =========================================================================
    # NICKEL SUPERALLOYS
    # =========================================================================

    {
        "name": "Inconel 718",
        "category": "nickel_superalloy",
        "density_kg_m3": 8190.0,
        "elastic_modulus_GPa": 200.0,
        "shear_modulus_GPa": 77.0,
        "poisson_ratio": 0.30,
        "yield_strength_MPa": 1034.0,
        "ultimate_strength_MPa": 1241.0,
        "elongation_pct": 12.0,
        "cte_per_K": 13.0e-6,
        "thermal_conductivity_W_mK": 11.4,
        "specific_heat_J_kgK": 435.0,
        "max_service_temp_C": 700.0,
        "fatigue_limit_MPa": 500.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 87.0,
        "specification": "AMS 5664 / AMS 5663",
        "description": (
            "Most widely used nickel superalloy; γ″-hardened NiCrFe alloy; "
            "dominant in turbine discs, casings, and rings up to 700 °C; "
            "excellent weldability."
        ),
    },
    {
        "name": "Inconel 625",
        "category": "nickel_superalloy",
        "density_kg_m3": 8440.0,
        "elastic_modulus_GPa": 207.0,
        "shear_modulus_GPa": 79.0,
        "poisson_ratio": 0.31,
        "yield_strength_MPa": 517.0,
        "ultimate_strength_MPa": 930.0,
        "elongation_pct": 42.5,
        "cte_per_K": 12.8e-6,
        "thermal_conductivity_W_mK": 9.8,
        "specific_heat_J_kgK": 410.0,
        "max_service_temp_C": 980.0,
        "fatigue_limit_MPa": 380.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 98.0,
        "specification": "AMS 5666 / AMS 5599",
        "description": (
            "Solution-strengthened NiCrMo alloy; outstanding oxidation and "
            "seawater corrosion resistance; used in thrust-reverser structures, "
            "cryogenic tanks, and bellows to 980 °C."
        ),
    },
    {
        "name": "Hastelloy X",
        "category": "nickel_superalloy",
        "density_kg_m3": 8220.0,
        "elastic_modulus_GPa": 205.0,
        "shear_modulus_GPa": 80.0,
        "poisson_ratio": 0.32,
        "yield_strength_MPa": 358.0,
        "ultimate_strength_MPa": 785.0,
        "elongation_pct": 43.0,
        "cte_per_K": 13.3e-6,
        "thermal_conductivity_W_mK": 9.1,
        "specific_heat_J_kgK": 419.0,
        "max_service_temp_C": 1080.0,
        "fatigue_limit_MPa": 300.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 105.0,
        "specification": "AMS 5754 / AMS 5536",
        "description": (
            "High oxidation and carburisation resistance NiCrFeMo alloy; "
            "used in combustion liners, afterburner components, and industrial "
            "gas turbine sheet-metal structures."
        ),
    },
    {
        "name": "Waspaloy",
        "category": "nickel_superalloy",
        "density_kg_m3": 8190.0,
        "elastic_modulus_GPa": 213.0,
        "shear_modulus_GPa": 84.0,
        "poisson_ratio": 0.30,
        "yield_strength_MPa": 795.0,
        "ultimate_strength_MPa": 1275.0,
        "elongation_pct": 25.0,
        "cte_per_K": 13.5e-6,
        "thermal_conductivity_W_mK": 11.0,
        "specific_heat_J_kgK": 420.0,
        "max_service_temp_C": 980.0,
        "fatigue_limit_MPa": 450.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 88.0,
        "specification": "AMS 5544 / AMS 5586",
        "description": (
            "γ′-hardened NiCoCrMo alloy; excellent high-temperature strength "
            "and oxidation resistance; used in turbine discs, blades, and "
            "compressor casings to ~980 °C."
        ),
    },
    {
        "name": "René 41",
        "category": "nickel_superalloy",
        "density_kg_m3": 8250.0,
        "elastic_modulus_GPa": 218.0,
        "shear_modulus_GPa": 84.0,
        "poisson_ratio": 0.30,
        "yield_strength_MPa": 1000.0,
        "ultimate_strength_MPa": 1400.0,
        "elongation_pct": 14.0,
        "cte_per_K": 12.3e-6,
        "thermal_conductivity_W_mK": 12.4,
        "specific_heat_J_kgK": 420.0,
        "max_service_temp_C": 980.0,
        "fatigue_limit_MPa": 500.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 70.0,
        "specification": "AMS 5545 / AMS 5596",
        "description": (
            "Age-hardenable NiCoCrMoAl alloy; high strength up to 980 °C; "
            "used in turbine spacers, bolts, and afterburner rings; strain-age "
            "cracking risk requires controlled welding."
        ),
    },
    {
        "name": "MAR-M 247",
        "category": "nickel_superalloy",
        "density_kg_m3": 8530.0,
        "elastic_modulus_GPa": 220.0,
        "shear_modulus_GPa": 86.0,
        "poisson_ratio": 0.30,
        "yield_strength_MPa": 862.0,
        "ultimate_strength_MPa": 1062.0,
        "elongation_pct": 9.0,
        "cte_per_K": 12.4e-6,
        "thermal_conductivity_W_mK": 12.0,
        "specific_heat_J_kgK": 390.0,
        "max_service_temp_C": 1050.0,
        "fatigue_limit_MPa": 420.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 22.0,
        "specification": "AMS 5368 (investment cast) / PWA 1455",
        "description": (
            "Directionally solidified or equiaxed cast superalloy; very high "
            "temperature capability via γ′ and carbide hardening with W, Ta, "
            "Hf; used in first-stage turbine blades."
        ),
    },

    # =========================================================================
    # COMPOSITES
    # =========================================================================

    {
        "name": "T300/5208 UD CFRP",
        "category": "composite",
        "density_kg_m3": 1550.0,
        "elastic_modulus_GPa": 138.0,    # longitudinal E11
        "shear_modulus_GPa": 7.1,        # in-plane G12
        "poisson_ratio": 0.30,           # ν12
        "yield_strength_MPa": 1500.0,    # longitudinal tensile strength
        "ultimate_strength_MPa": 1500.0,
        "elongation_pct": 1.1,
        "cte_per_K": 0.5e-6,             # longitudinal CTE
        "thermal_conductivity_W_mK": 5.0,
        "specific_heat_J_kgK": 900.0,
        "max_service_temp_C": 150.0,
        "fatigue_limit_MPa": 700.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 32.0,
        "specification": "CMH-17 Vol 2 / MIL-HDBK-17-2",
        "description": (
            "T300 carbon fibre / Narmco 5208 epoxy; first widely used "
            "aerospace CFRP; baseline for CMH-17 design allowables; used in "
            "secondary structure and tail surfaces."
        ),
    },
    {
        "name": "AS4/3501-6 UD CFRP",
        "category": "composite",
        "density_kg_m3": 1550.0,
        "elastic_modulus_GPa": 142.0,
        "shear_modulus_GPa": 7.6,
        "poisson_ratio": 0.30,
        "yield_strength_MPa": 2022.0,
        "ultimate_strength_MPa": 2022.0,
        "elongation_pct": 1.4,
        "cte_per_K": 0.4e-6,
        "thermal_conductivity_W_mK": 5.5,
        "specific_heat_J_kgK": 900.0,
        "max_service_temp_C": 150.0,
        "fatigue_limit_MPa": 780.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 30.0,
        "specification": "CMH-17 Vol 2 / BMS 8-79",
        "description": (
            "AS4 fibre / Hercules 3501-6 epoxy; well-characterised system with "
            "extensive CMH-17 B-basis allowables; used in wing ribs, spars, "
            "and pressure bulkheads."
        ),
    },
    {
        "name": "IM7/8552 UD CFRP",
        "category": "composite",
        "density_kg_m3": 1570.0,
        "elastic_modulus_GPa": 165.0,
        "shear_modulus_GPa": 8.7,
        "poisson_ratio": 0.30,
        "yield_strength_MPa": 2724.0,
        "ultimate_strength_MPa": 2724.0,
        "elongation_pct": 1.7,
        "cte_per_K": 0.3e-6,
        "thermal_conductivity_W_mK": 6.5,
        "specific_heat_J_kgK": 900.0,
        "max_service_temp_C": 180.0,
        "fatigue_limit_MPa": 900.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 45.0,
        "specification": "CMH-17 Vol 2 / BMS 8-276",
        "description": (
            "IM7 intermediate-modulus fibre / Hexcel 8552 toughened epoxy; "
            "industry-standard primary-structure prepreg; used in B787 and "
            "A350 wing boxes, fuselage barrels, and pressure vessels."
        ),
    },
    {
        "name": "S-glass/epoxy UD",
        "category": "composite",
        "density_kg_m3": 1900.0,
        "elastic_modulus_GPa": 48.3,
        "shear_modulus_GPa": 6.9,
        "poisson_ratio": 0.27,
        "yield_strength_MPa": 1700.0,
        "ultimate_strength_MPa": 1700.0,
        "elongation_pct": 3.5,
        "cte_per_K": 5.6e-6,
        "thermal_conductivity_W_mK": 0.36,
        "specific_heat_J_kgK": 840.0,
        "max_service_temp_C": 150.0,
        "fatigue_limit_MPa": 560.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 24.0,
        "specification": "CMH-17 Vol 2 / MIL-HDBK-17-3F",
        "description": (
            "S2-glass fibre / structural epoxy; superior specific tensile "
            "strength and impact toughness versus E-glass; used in helicopter "
            "rotor blades, radomes, and armour-grade fairings."
        ),
    },
    {
        "name": "Kevlar 49/epoxy UD",
        "category": "composite",
        "density_kg_m3": 1380.0,
        "elastic_modulus_GPa": 76.0,
        "shear_modulus_GPa": 2.1,
        "poisson_ratio": 0.34,
        "yield_strength_MPa": 1400.0,
        "ultimate_strength_MPa": 1400.0,
        "elongation_pct": 1.8,
        "cte_per_K": -3.0e-6,            # slightly negative longitudinal CTE
        "thermal_conductivity_W_mK": 0.17,
        "specific_heat_J_kgK": 1420.0,
        "max_service_temp_C": 150.0,
        "fatigue_limit_MPa": 450.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 18.0,
        "specification": "CMH-17 Vol 2 / MIL-HDBK-17-2",
        "description": (
            "Kevlar 49 aramid fibre / epoxy; extremely low density and high "
            "tensile strength; used in pressure vessels, radomes, and armour "
            "panels; poor compression and moisture absorption require careful "
            "design."
        ),
    },

    # =========================================================================
    # OTHER / SPECIALTY
    # =========================================================================

    {
        "name": "Be-Cu C17200 AT",
        "category": "copper_alloy",
        "density_kg_m3": 8260.0,
        "elastic_modulus_GPa": 128.0,
        "shear_modulus_GPa": 50.0,
        "poisson_ratio": 0.30,
        "yield_strength_MPa": 1103.0,
        "ultimate_strength_MPa": 1241.0,
        "elongation_pct": 4.0,
        "cte_per_K": 17.8e-6,
        "thermal_conductivity_W_mK": 105.0,
        "specific_heat_J_kgK": 420.0,
        "max_service_temp_C": 200.0,
        "fatigue_limit_MPa": 400.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 30.0,
        "specification": "AMS 4534 / ASTM B197",
        "description": (
            "Beryllium-copper peak-aged; highest-strength copper alloy; "
            "excellent conductivity, non-sparking, non-magnetic; used in "
            "aerospace springs, connectors, and bushings demanding both "
            "strength and electrical conductivity."
        ),
    },
    {
        "name": "Mg AZ31B-H24",
        "category": "magnesium",
        "density_kg_m3": 1770.0,
        "elastic_modulus_GPa": 45.0,
        "shear_modulus_GPa": 17.0,
        "poisson_ratio": 0.35,
        "yield_strength_MPa": 220.0,
        "ultimate_strength_MPa": 290.0,
        "elongation_pct": 15.0,
        "cte_per_K": 26.0e-6,
        "thermal_conductivity_W_mK": 77.0,
        "specific_heat_J_kgK": 1050.0,
        "max_service_temp_C": 120.0,
        "fatigue_limit_MPa": 90.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 18.0,
        "specification": "AMS 4375 / ASTM B90",
        "description": (
            "Lightest structural metal alloy; AZ31B sheet/plate in strain-"
            "hardened temper; used in aircraft interior panels, avionics "
            "housings, and heritage airframe structures."
        ),
    },
    {
        "name": "Mg WE43-T5",
        "category": "magnesium",
        "density_kg_m3": 1840.0,
        "elastic_modulus_GPa": 44.0,
        "shear_modulus_GPa": 17.0,
        "poisson_ratio": 0.35,
        "yield_strength_MPa": 200.0,
        "ultimate_strength_MPa": 250.0,
        "elongation_pct": 7.0,
        "cte_per_K": 26.7e-6,
        "thermal_conductivity_W_mK": 51.0,
        "specific_heat_J_kgK": 1050.0,
        "max_service_temp_C": 250.0,
        "fatigue_limit_MPa": 100.0,
        "fracture_toughness_K1c_MPa_sqrt_m": 14.0,
        "specification": "AMS 4427 / DEF STAN 02-747",
        "description": (
            "Rare-earth-hardened Mg-Y-Nd-Zr alloy; significantly better "
            "elevated-temperature strength and corrosion resistance than "
            "AZ-series; used in helicopter gearbox housings and military "
            "airframe castings."
        ),
    },
]
