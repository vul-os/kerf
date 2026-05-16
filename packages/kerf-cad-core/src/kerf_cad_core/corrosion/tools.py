"""
kerf_cad_core.corrosion.tools — LLM tool wrappers for corrosion engineering
& cathodic protection.

Registers ten tools with the Kerf tool registry:

  galvanic_couple           — galvanic series potentials & driving voltage
  faraday_corrosion_rate    — Faraday's Law: current density → mpy/mm·yr/g·m⁻²·d⁻¹
  penetration_remaining_life — wall loss penetration depth & remaining life
  sacrificial_anode_demand  — CP current demand from coating breakdown & bare area
  anode_mass_design_life    — sacrificial anode net mass for design life
  anode_count_dwight        — number of anodes from Dwight groundbed resistance
  iccp_sizing               — ICCP rectifier voltage/current sizing
  pourbaix_region           — Pourbaix (E-pH) region: immune/passive/corrosion
  corrosivity_category      — atmospheric/soil corrosivity category
  coating_breakdown_factor  — time-varying CBF for CP current demand

All tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: "..."} — tools never raise.

References
----------
NACE SP0169-2013  — Control of External Corrosion on Underground/Submerged
                    Metallic Piping Systems
DNV-RP-B401:2021  — Cathodic Protection Design
Fontana, M.G.     — Corrosion Engineering, 3rd ed.
ASTM G102-89      — Standard Practice for Calculation of Corrosion Rates

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.corrosion.cp import (
    galvanic_couple,
    faraday_corrosion_rate,
    penetration_remaining_life,
    sacrificial_anode_demand,
    anode_mass_design_life,
    anode_count_dwight,
    iccp_sizing,
    pourbaix_region,
    corrosivity_category,
    coating_breakdown_factor,
)


# ---------------------------------------------------------------------------
# Tool: galvanic_couple
# ---------------------------------------------------------------------------

_galvanic_couple_spec = ToolSpec(
    name="galvanic_couple",
    description=(
        "Analyse a galvanic couple from the galvanic series.\n"
        "\n"
        "Returns open-circuit potentials (V vs SHE) for both metals, the "
        "driving voltage (E_cathode − E_anode), and the area-ratio effect.\n"
        "\n"
        "High cathode-to-anode area ratios concentrate corrosion attack on the "
        "anode (small anode paired with large cathode = accelerated wastage).\n"
        "\n"
        "Available metals include: magnesium, zinc, aluminum, mild_steel, "
        "carbon_steel, cast_iron, brass, bronze, copper, stainless_304_passive, "
        "stainless_316_passive, titanium, platinum, gold, and more.\n"
        "\n"
        "Warnings are raised for driving voltage > 1.0 V, unfavorable area "
        "ratios (>= 10), and negligible potential difference (< 0.05 V).\n"
        "\n"
        "Errors: {ok:false, reason} for unknown metals or invalid areas. "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "anode_metal": {
                "type": "string",
                "description": (
                    "Name of the (predicted) anode metal from the galvanic series "
                    "table. The more active (negative) metal will always be "
                    "treated as the anode regardless of the order supplied."
                ),
            },
            "cathode_metal": {
                "type": "string",
                "description": "Name of the cathode (more noble) metal.",
            },
            "anode_area_m2": {
                "type": "number",
                "description": "Exposed anode area (m²). Default 1.0. Must be > 0.",
            },
            "cathode_area_m2": {
                "type": "number",
                "description": "Exposed cathode area (m²). Default 1.0. Must be > 0.",
            },
        },
        "required": ["anode_metal", "cathode_metal"],
    },
)


@register(_galvanic_couple_spec, write=False)
async def run_galvanic_couple(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("anode_metal") is None:
        return json.dumps({"ok": False, "reason": "anode_metal is required"})
    if a.get("cathode_metal") is None:
        return json.dumps({"ok": False, "reason": "cathode_metal is required"})

    kwargs: dict = {}
    if "anode_area_m2" in a:
        kwargs["anode_area_m2"] = a["anode_area_m2"]
    if "cathode_area_m2" in a:
        kwargs["cathode_area_m2"] = a["cathode_area_m2"]

    result = galvanic_couple(a["anode_metal"], a["cathode_metal"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: faraday_corrosion_rate
# ---------------------------------------------------------------------------

_faraday_corrosion_rate_spec = ToolSpec(
    name="faraday_corrosion_rate",
    description=(
        "Compute corrosion rate from Faraday's Law.\n"
        "\n"
        "Given a corrosion current density, the metal's equivalent weight "
        "(EW = molar_mass / valence), and its density, returns:\n"
        "  • corrosion_rate_mpy     — mils per year (1 mil = 0.0254 mm)\n"
        "  • corrosion_rate_mm_yr  — penetration rate (mm/yr)\n"
        "  • corrosion_rate_g_m2_d — mass loss rate (g·m⁻²·d⁻¹)\n"
        "\n"
        "Common equivalent weights:\n"
        "  • Steel/iron (Fe, n=2): EW = 27.93 g/mol\n"
        "  • Zinc (Zn, n=2): EW = 32.69 g/mol\n"
        "  • Aluminum (Al, n=3): EW = 8.99 g/mol\n"
        "  • Copper (Cu, n=2): EW = 31.77 g/mol\n"
        "\n"
        "References: Fontana Corrosion Engineering eq. 3-2; ASTM G102-89.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "current_density_A_m2": {
                "type": "number",
                "description": (
                    "Corrosion current density (A/m²). Must be >= 0. "
                    "Typical bare steel: 0.01–1.0 A/m²."
                ),
            },
            "equivalent_weight_g_mol": {
                "type": "number",
                "description": (
                    "Equivalent weight of the corroding metal (g/mol) = "
                    "molar_mass / valence. Must be > 0. "
                    "Steel: 27.93; Zn: 32.69; Al: 8.99; Cu: 31.77."
                ),
            },
            "density_g_cm3": {
                "type": "number",
                "description": (
                    "Density of the corroding metal (g/cm³). Must be > 0. "
                    "Steel ≈ 7.87; Zn ≈ 7.13; Al ≈ 2.70; Cu ≈ 8.96."
                ),
            },
        },
        "required": ["current_density_A_m2", "equivalent_weight_g_mol", "density_g_cm3"],
    },
)


@register(_faraday_corrosion_rate_spec, write=False)
async def run_faraday_corrosion_rate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("current_density_A_m2", "equivalent_weight_g_mol", "density_g_cm3"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = faraday_corrosion_rate(
        a["current_density_A_m2"],
        a["equivalent_weight_g_mol"],
        a["density_g_cm3"],
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: penetration_remaining_life
# ---------------------------------------------------------------------------

_penetration_remaining_life_spec = ToolSpec(
    name="penetration_remaining_life",
    description=(
        "Estimate remaining life from corrosion wall loss.\n"
        "\n"
        "  remaining_life [yr] = (wall_thickness − min_thickness) / corrosion_rate\n"
        "\n"
        "Returns the available wall loss allowance, remaining service life, "
        "and warnings for < 5 yr or < 10 yr remaining life.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wall_thickness_mm": {
                "type": "number",
                "description": "Current measured wall thickness (mm). Must be > 0.",
            },
            "corrosion_rate_mm_yr": {
                "type": "number",
                "description": (
                    "Corrosion (penetration) rate (mm/yr). Must be >= 0. "
                    "If 0, remaining life is infinite."
                ),
            },
            "minimum_thickness_mm": {
                "type": "number",
                "description": (
                    "Minimum acceptable wall thickness (mm). Default 0.0. "
                    "Must be < wall_thickness_mm."
                ),
            },
        },
        "required": ["wall_thickness_mm", "corrosion_rate_mm_yr"],
    },
)


@register(_penetration_remaining_life_spec, write=False)
async def run_penetration_remaining_life(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("wall_thickness_mm", "corrosion_rate_mm_yr"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "minimum_thickness_mm" in a:
        kwargs["minimum_thickness_mm"] = a["minimum_thickness_mm"]

    result = penetration_remaining_life(
        a["wall_thickness_mm"], a["corrosion_rate_mm_yr"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: sacrificial_anode_demand
# ---------------------------------------------------------------------------

_sacrificial_anode_demand_spec = ToolSpec(
    name="sacrificial_anode_demand",
    description=(
        "Calculate total cathodic protection current demand for a coated structure.\n"
        "\n"
        "  I_total [A] = bare_area × (1 − coating_efficiency) × i_c [A/m²]\n"
        "\n"
        "Typical design current densities (NACE SP0169 / DNV-RP-B401):\n"
        "  • Buried pipeline (good coating): 10–20 mA/m²\n"
        "  • Buried bare steel: 50–100 mA/m²\n"
        "  • Submerged seawater: 60–150 mA/m²\n"
        "\n"
        "Warnings raised for coating efficiency < 50% and current density > 150 mA/m².\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bare_area_m2": {
                "type": "number",
                "description": "Total structure surface area (m²). Must be > 0.",
            },
            "coating_efficiency": {
                "type": "number",
                "description": (
                    "Fraction of area protected by intact coating [0, 1]. "
                    "1.0 = fully coated; 0.0 = fully bare."
                ),
            },
            "current_density_mA_m2": {
                "type": "number",
                "description": (
                    "Design CP current density for bare steel (mA/m²). Must be > 0. "
                    "Typical: 20–150 mA/m²."
                ),
            },
        },
        "required": ["bare_area_m2", "coating_efficiency", "current_density_mA_m2"],
    },
)


@register(_sacrificial_anode_demand_spec, write=False)
async def run_sacrificial_anode_demand(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("bare_area_m2", "coating_efficiency", "current_density_mA_m2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = sacrificial_anode_demand(
        a["bare_area_m2"], a["coating_efficiency"], a["current_density_mA_m2"]
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: anode_mass_design_life
# ---------------------------------------------------------------------------

_anode_mass_design_life_spec = ToolSpec(
    name="anode_mass_design_life",
    description=(
        "Calculate net sacrificial anode mass required for a given design life.\n"
        "\n"
        "  M_net [kg] = (I [A] × T [yr] × 8760 h/yr) / (u × C [A·h/kg])\n"
        "\n"
        "Anode electrochemical capacities:\n"
        "  • aluminum:  2000 A·h/kg  (DNV-RP-B401 preferred for offshore)\n"
        "  • zinc:       780 A·h/kg  (reliable in seawater)\n"
        "  • magnesium: 1100 A·h/kg  (preferred for buried pipelines)\n"
        "\n"
        "Warnings raised for large anode mass (> 10,000 kg) — suggesting ICCP — "
        "and design life > 30 yr.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "current_A": {
                "type": "number",
                "description": "Total protection current required (A). Must be > 0.",
            },
            "design_life_yr": {
                "type": "number",
                "description": "Required service life (years). Must be > 0.",
            },
            "utilisation_factor": {
                "type": "number",
                "description": (
                    "Fraction of anode consumed at end of life (0, 1]. "
                    "Default 0.85 per DNV-RP-B401."
                ),
            },
            "anode_type": {
                "type": "string",
                "enum": ["aluminum", "zinc", "magnesium"],
                "description": (
                    "Anode alloy: 'aluminum' (default, 2000 A·h/kg), "
                    "'zinc' (780 A·h/kg), or 'magnesium' (1100 A·h/kg)."
                ),
            },
        },
        "required": ["current_A", "design_life_yr"],
    },
)


@register(_anode_mass_design_life_spec, write=False)
async def run_anode_mass_design_life(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("current_A", "design_life_yr"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "utilisation_factor" in a:
        kwargs["utilisation_factor"] = a["utilisation_factor"]
    if "anode_type" in a:
        kwargs["anode_type"] = a["anode_type"]

    result = anode_mass_design_life(a["current_A"], a["design_life_yr"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: anode_count_dwight
# ---------------------------------------------------------------------------

_anode_count_dwight_spec = ToolSpec(
    name="anode_count_dwight",
    description=(
        "Determine number of sacrificial anodes using the Dwight groundbed "
        "resistance formula.\n"
        "\n"
        "Dwight (1936) formula for a single vertical rod anode:\n"
        "  R_a ≈ (ρ / 2πL) × (ln(8L/d) − 1)   [deep burial approximation]\n"
        "\n"
        "Current output per anode:  I_anode = driving_voltage / R_a\n"
        "Number of anodes:  N = ceil(total_current / I_anode)\n"
        "\n"
        "Driving voltage for sacrificial anodes (typical):\n"
        "  • Aluminum in seawater: 0.25–0.35 V\n"
        "  • Zinc in seawater/soil: 0.15–0.25 V\n"
        "  • Magnesium in soil: 0.60–0.90 V\n"
        "\n"
        "Warnings raised for high resistivity (> 100 Ω·m), large anode count "
        "(> 100), and very low current per anode.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "total_current_A": {
                "type": "number",
                "description": "Total CP current required (A). Must be > 0.",
            },
            "anode_length_m": {
                "type": "number",
                "description": "Individual anode length (m). Must be > 0.",
            },
            "anode_radius_m": {
                "type": "number",
                "description": "Individual anode radius (m) = diameter / 2. Must be > 0.",
            },
            "soil_resistivity_ohm_m": {
                "type": "number",
                "description": (
                    "Soil or seawater resistivity (Ω·m). Must be > 0. "
                    "Seawater ≈ 0.2–0.5; moist soil ≈ 5–50; dry soil > 100."
                ),
            },
            "driving_voltage_V": {
                "type": "number",
                "description": (
                    "Net driving voltage (V) = anode potential − structure potential. "
                    "Must be > 0. Typical: 0.15–0.90 V for sacrificial anodes."
                ),
            },
            "burial_depth_m": {
                "type": "number",
                "description": "Anode burial depth (m). Default 1.0. Must be > 0.",
            },
        },
        "required": [
            "total_current_A",
            "anode_length_m",
            "anode_radius_m",
            "soil_resistivity_ohm_m",
            "driving_voltage_V",
        ],
    },
)


@register(_anode_count_dwight_spec, write=False)
async def run_anode_count_dwight(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in (
        "total_current_A",
        "anode_length_m",
        "anode_radius_m",
        "soil_resistivity_ohm_m",
        "driving_voltage_V",
    ):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "burial_depth_m" in a:
        kwargs["burial_depth_m"] = a["burial_depth_m"]

    result = anode_count_dwight(
        a["total_current_A"],
        a["anode_length_m"],
        a["anode_radius_m"],
        a["soil_resistivity_ohm_m"],
        a["driving_voltage_V"],
        **kwargs,
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: iccp_sizing
# ---------------------------------------------------------------------------

_iccp_sizing_spec = ToolSpec(
    name="iccp_sizing",
    description=(
        "Size an impressed current cathodic protection (ICCP) rectifier.\n"
        "\n"
        "Design current:\n"
        "  I_design = area × (1 − coating_eff) × i_c × safety_factor × attenuation\n"
        "\n"
        "Rectifier voltage:\n"
        "  V_rect = I_design × R_groundbed + 2 V (back-EMF)   [min 12 V]\n"
        "\n"
        "Typical parameters:\n"
        "  • safety_factor: 1.25 (default)\n"
        "  • current density: 20–150 mA/m² depending on environment/coating\n"
        "  • groundbed resistance: 0.5–10 Ω depending on soil/installation\n"
        "\n"
        "Warnings for coating efficiency < 50%, I_design > 100 A, V_rect > 50 V, "
        "and over-protection (I_design < 0.5 A).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "protected_area_m2": {
                "type": "number",
                "description": "Total structure surface area (m²). Must be > 0.",
            },
            "coating_efficiency": {
                "type": "number",
                "description": "Fraction of area with intact coating [0, 1].",
            },
            "current_density_mA_m2": {
                "type": "number",
                "description": (
                    "Design CP current density for bare steel (mA/m²). Must be > 0."
                ),
            },
            "groundbed_resistance_ohm": {
                "type": "number",
                "description": (
                    "Total groundbed-to-electrolyte resistance (Ω). Must be > 0."
                ),
            },
            "safety_factor": {
                "type": "number",
                "description": "Safety factor on current demand (default 1.25). Must be >= 1.",
            },
            "attenuation_factor": {
                "type": "number",
                "description": (
                    "Attenuation factor for long pipelines (default 1.0 = none). "
                    "Must be >= 1."
                ),
            },
        },
        "required": [
            "protected_area_m2",
            "coating_efficiency",
            "current_density_mA_m2",
            "groundbed_resistance_ohm",
        ],
    },
)


@register(_iccp_sizing_spec, write=False)
async def run_iccp_sizing(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in (
        "protected_area_m2",
        "coating_efficiency",
        "current_density_mA_m2",
        "groundbed_resistance_ohm",
    ):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "safety_factor" in a:
        kwargs["safety_factor"] = a["safety_factor"]
    if "attenuation_factor" in a:
        kwargs["attenuation_factor"] = a["attenuation_factor"]

    result = iccp_sizing(
        a["protected_area_m2"],
        a["coating_efficiency"],
        a["current_density_mA_m2"],
        a["groundbed_resistance_ohm"],
        **kwargs,
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: pourbaix_region
# ---------------------------------------------------------------------------

_pourbaix_region_spec = ToolSpec(
    name="pourbaix_region",
    description=(
        "Classify the corrosion state from a simplified Pourbaix (E-pH) diagram.\n"
        "\n"
        "Returns one of three regions:\n"
        "  • 'immune'   — metal is thermodynamically stable; no corrosion\n"
        "  • 'passive'  — stable oxide film; kinetically protected\n"
        "  • 'corrosion'— active dissolution; corrosion is occurring\n"
        "\n"
        "Supported metals: iron, steel (same as iron), zinc, aluminum, copper.\n"
        "Valid at 25 °C; not valid for elevated temperature.\n"
        "\n"
        "Common reference potential conversions:\n"
        "  • vs Cu/CuSO4 (CSE): add +0.316 V to get V vs SHE\n"
        "  • vs SCE:             add +0.242 V to get V vs SHE\n"
        "  • vs Ag/AgCl:         add +0.197 V to get V vs SHE\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "potential_V_she": {
                "type": "number",
                "description": (
                    "Electrode potential vs SHE (standard hydrogen electrode), V. "
                    "For pipeline steel: NACE protection criterion −850 mV CSE = "
                    "−534 mV SHE."
                ),
            },
            "pH": {
                "type": "number",
                "description": "Solution pH (0–14).",
            },
            "metal": {
                "type": "string",
                "enum": ["iron", "steel", "zinc", "aluminum", "copper"],
                "description": "Metal for Pourbaix analysis. Default 'iron'.",
            },
        },
        "required": ["potential_V_she", "pH"],
    },
)


@register(_pourbaix_region_spec, write=False)
async def run_pourbaix_region(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("potential_V_she", "pH"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "metal" in a:
        kwargs["metal"] = a["metal"]

    result = pourbaix_region(a["potential_V_she"], a["pH"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: corrosivity_category
# ---------------------------------------------------------------------------

_corrosivity_category_spec = ToolSpec(
    name="corrosivity_category",
    description=(
        "Determine the ISO 12944 corrosivity category (C1–C5) from soil "
        "resistivity or atmospheric environment.\n"
        "\n"
        "Supply either soil_resistivity_ohm_m OR environment, not both.\n"
        "\n"
        "Soil resistivity ranges (NACE SP0169 / ASTM):\n"
        "  • < 2 Ω·m    → C5 Extremely corrosive (seawater/saturated)\n"
        "  • 2–10 Ω·m   → C4 Very corrosive\n"
        "  • 10–30 Ω·m  → C3 Moderately corrosive\n"
        "  • 30–100 Ω·m → C2 Mildly corrosive\n"
        "  • > 100 Ω·m  → C1 Low corrosivity\n"
        "\n"
        "Atmospheric environments: rural, urban, industrial, marine, offshore, "
        "tropical_marine, severe_industrial, indoor_dry.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "soil_resistivity_ohm_m": {
                "type": "number",
                "description": (
                    "Soil resistivity (Ω·m). Must be >= 0. "
                    "Provide this OR environment, not both."
                ),
            },
            "environment": {
                "type": "string",
                "enum": [
                    "rural", "urban", "industrial", "marine", "offshore",
                    "tropical_marine", "severe_industrial", "indoor_dry",
                ],
                "description": (
                    "Atmospheric environment type (ISO 12944). "
                    "Provide this OR soil_resistivity_ohm_m, not both."
                ),
            },
        },
        "required": [],
    },
)


@register(_corrosivity_category_spec, write=False)
async def run_corrosivity_category(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("soil_resistivity_ohm_m") is None and a.get("environment") is None:
        return json.dumps({
            "ok": False,
            "reason": "Either soil_resistivity_ohm_m or environment is required.",
        })

    kwargs: dict = {}
    if "soil_resistivity_ohm_m" in a:
        kwargs["soil_resistivity_ohm_m"] = a["soil_resistivity_ohm_m"]
    if "environment" in a:
        kwargs["environment"] = a["environment"]

    result = corrosivity_category(**kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: coating_breakdown_factor
# ---------------------------------------------------------------------------

_coating_breakdown_factor_spec = ToolSpec(
    name="coating_breakdown_factor",
    description=(
        "Calculate the time-varying coating breakdown factor (CBF) for CP "
        "current demand calculations.\n"
        "\n"
        "CBF increases linearly from an initial to a final value over the "
        "design life (DNV-RP-B401 / ISO 15589-1 assumption):\n"
        "\n"
        "  CBF(t) = CBF_initial + (CBF_final − CBF_initial) × (t / T_design)\n"
        "\n"
        "Typical values (DNV-RP-B401 Table 10-1):\n"
        "  • Excellent coating: CBF_initial=0.005, CBF_final=0.02\n"
        "  • Good coating:      CBF_initial=0.01,  CBF_final=0.05  (default)\n"
        "  • Poor coating:      CBF_initial=0.03,  CBF_final=0.20\n"
        "\n"
        "Warnings raised if age > design_life (coating expired) or CBF > 10%.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "age_yr": {
                "type": "number",
                "description": "Current age of the coating (years). Must be >= 0.",
            },
            "design_life_yr": {
                "type": "number",
                "description": "Total design life of the coating (years). Must be > 0.",
            },
            "initial_breakdown_frac": {
                "type": "number",
                "description": (
                    "Coating breakdown fraction at time zero [0, 1]. "
                    "Default 0.01 (1%)."
                ),
            },
            "final_breakdown_frac": {
                "type": "number",
                "description": (
                    "Coating breakdown fraction at end of design life [0, 1]. "
                    "Default 0.05 (5%). Must be >= initial_breakdown_frac."
                ),
            },
        },
        "required": ["age_yr", "design_life_yr"],
    },
)


@register(_coating_breakdown_factor_spec, write=False)
async def run_coating_breakdown_factor(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("age_yr", "design_life_yr"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "initial_breakdown_frac" in a:
        kwargs["initial_breakdown_frac"] = a["initial_breakdown_frac"]
    if "final_breakdown_frac" in a:
        kwargs["final_breakdown_frac"] = a["final_breakdown_frac"]

    result = coating_breakdown_factor(a["age_yr"], a["design_life_yr"], **kwargs)
    return ok_payload(result)
