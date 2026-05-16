"""
kerf_cad_core.combustion.tools — LLM tool wrappers for combustion & fuels engineering.

Registers tools with the Kerf tool registry:

  combustion_stoich_afr         — stoichiometric AFR (mass & molar) for CxHyOz fuels
  combustion_equivalence_ratio  — φ ↔ λ ↔ excess-air conversions
  combustion_product_composition — flue-gas composition (wet/dry, ppm) with excess air
  combustion_adiabatic_flame_temp — adiabatic flame temperature (iterative energy balance)
  combustion_hhv_to_lhv         — HHV ↔ LHV conversion (water latent heat)
  combustion_efficiency         — Siegert flue-gas heat loss & thermal efficiency
  combustion_flue_gas_dew_point — flue-gas dew-point temperature
  combustion_co2_max            — maximum (stoichiometric, dry) CO2%
  combustion_fuel_power         — fuel energy → thermal power & specific fuel consumption

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Turns, S.R., "An Introduction to Combustion", 3rd ed.
Baukal, C.E. (ed.), "The John Zink Hamworthy Combustion Handbook", 2nd ed.
Siegert method: EN 15502-1 / VDI 2067

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.combustion.burn import (
    stoich_afr,
    equivalence_ratio,
    product_composition,
    adiabatic_flame_temp,
    hhv_to_lhv,
    combustion_efficiency,
    flue_gas_dew_point,
    co2_max,
    fuel_power,
)


# ---------------------------------------------------------------------------
# Tool: combustion_stoich_afr
# ---------------------------------------------------------------------------

_stoich_afr_spec = ToolSpec(
    name="combustion_stoich_afr",
    description=(
        "Stoichiometric air-fuel ratio (mass and molar) for a CxHyOzNwSv fuel.\n"
        "\n"
        "Complete combustion reaction:\n"
        "  CₓHᵧOᵤNᵥSₛ + n_O₂·O₂ → x·CO₂ + y/2·H₂O + w/2·N₂ + s·SO₂\n"
        "  n_O₂ = x + y/4 − z/2 + s\n"
        "\n"
        "AFR_mass = (n_air × MW_air) / MW_fuel\n"
        "\n"
        "Reference values: CH₄ AFR_mass ≈ 17.2; C₃H₈ ≈ 15.6; gasoline ≈ 14.7\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {
                "type": "number",
                "description": "Carbon atom count in fuel formula (e.g. 1 for CH₄). Must be ≥ 0.",
            },
            "H": {
                "type": "number",
                "description": "Hydrogen atom count (e.g. 4 for CH₄). Must be ≥ 0.",
            },
            "O": {
                "type": "number",
                "description": "Oxygen atom count in fuel formula (0 for pure hydrocarbons). Default 0.",
            },
            "N": {
                "type": "number",
                "description": "Nitrogen atom count in fuel formula. Default 0.",
            },
            "S": {
                "type": "number",
                "description": "Sulphur atom count in fuel formula. Default 0.",
            },
            "fuel_name": {
                "type": "string",
                "description": "Optional label for the fuel (e.g. 'methane', 'propane').",
            },
        },
        "required": ["C", "H"],
    },
)


@register(_stoich_afr_spec, write=False)
async def run_stoich_afr(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("C") is None:
        return json.dumps({"ok": False, "reason": "C is required"})
    if a.get("H") is None:
        return json.dumps({"ok": False, "reason": "H is required"})

    kwargs: dict = {}
    for opt in ("O", "N", "S", "fuel_name"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = stoich_afr(a["C"], a["H"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: combustion_equivalence_ratio
# ---------------------------------------------------------------------------

_equiv_ratio_spec = ToolSpec(
    name="combustion_equivalence_ratio",
    description=(
        "Convert between equivalence ratio φ, excess-air %, and lambda λ.\n"
        "\n"
        "Definitions:\n"
        "  φ (phi)         = AFR_stoich / AFR_actual = 1/λ\n"
        "  λ (lambda)      = AFR_actual / AFR_stoich = 1/φ\n"
        "  excess_air_%    = (λ − 1) × 100\n"
        "\n"
        "Mixture: φ > 1 → rich (fuel-rich, incomplete combustion risk);\n"
        "         φ < 1 → lean (air-rich, excess O₂);\n"
        "         φ = 1 → stoichiometric.\n"
        "\n"
        "Supply ONE of: (afr_actual + afr_stoich), phi, excess_air_pct, or lambda_.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "afr_actual": {
                "type": "number",
                "description": "Actual air-fuel ratio (mass-based). Requires afr_stoich.",
            },
            "afr_stoich": {
                "type": "number",
                "description": "Stoichiometric air-fuel ratio (mass-based). Requires afr_actual.",
            },
            "phi": {
                "type": "number",
                "description": "Equivalence ratio φ = AFR_stoich/AFR_actual. Must be > 0.",
            },
            "excess_air_pct": {
                "type": "number",
                "description": "Excess air percentage (%). 0% = stoichiometric; 20% = λ=1.2.",
            },
            "lambda_": {
                "type": "number",
                "description": "Air-excess coefficient λ = AFR_actual/AFR_stoich. Must be > 0.",
            },
        },
        "required": [],
    },
)


@register(_equiv_ratio_spec, write=False)
async def run_equivalence_ratio(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    kwargs: dict = {}
    for opt in ("afr_actual", "afr_stoich", "phi", "excess_air_pct", "lambda_"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = equivalence_ratio(**kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: combustion_product_composition
# ---------------------------------------------------------------------------

_product_comp_spec = ToolSpec(
    name="combustion_product_composition",
    description=(
        "Complete-combustion product-gas composition for CxHyOz fuel with excess air.\n"
        "\n"
        "Assumes complete combustion (no CO, no unburnt hydrocarbons).\n"
        "Returns wet and dry mole fractions (and ppm) of CO₂, H₂O, O₂, N₂, SO₂.\n"
        "\n"
        "Excess air = 0% → stoichiometric; 10% → λ=1.1; −10% → rich (φ=1.11).\n"
        "\n"
        "Rich mixtures (excess_air_pct < 0) flag incomplete-combustion warnings.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {"type": "number", "description": "Carbon atom count. Must be ≥ 0."},
            "H": {"type": "number", "description": "Hydrogen atom count. Must be ≥ 0."},
            "O": {"type": "number", "description": "Oxygen atom count in fuel. Default 0."},
            "N": {"type": "number", "description": "Nitrogen atom count in fuel. Default 0."},
            "S": {"type": "number", "description": "Sulphur atom count in fuel. Default 0."},
            "excess_air_pct": {
                "type": "number",
                "description": (
                    "Excess air above stoichiometric (%). 0 = stoichiometric; "
                    "negative = rich mixture."
                ),
            },
            "fuel_name": {
                "type": "string",
                "description": "Optional fuel label for result annotation.",
            },
        },
        "required": ["C", "H"],
    },
)


@register(_product_comp_spec, write=False)
async def run_product_composition(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C", "H"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("O", "N", "S", "excess_air_pct", "fuel_name"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = product_composition(a["C"], a["H"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: combustion_adiabatic_flame_temp
# ---------------------------------------------------------------------------

_aft_spec = ToolSpec(
    name="combustion_adiabatic_flame_temp",
    description=(
        "Adiabatic flame temperature via iterative constant-pressure energy balance.\n"
        "\n"
        "Uses mean-cp iteration for product mixture (CO₂, H₂O, N₂, O₂, SO₂).\n"
        "For best accuracy supply LHV_MJ_kg and MW_fuel from the FUELS table.\n"
        "\n"
        "Reference values (stoichiometric, 25°C air):\n"
        "  CH₄ ≈ 2230 K; C₃H₈ ≈ 2267 K; H₂ ≈ 2480 K; gasoline ≈ 2275 K\n"
        "\n"
        "Flame temperatures > 3000 K trigger a dissociation warning (result overestimate).\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {"type": "number", "description": "Carbon atom count in fuel formula."},
            "H": {"type": "number", "description": "Hydrogen atom count."},
            "O": {"type": "number", "description": "Oxygen atom count in fuel. Default 0."},
            "N": {"type": "number", "description": "Nitrogen atom count in fuel. Default 0."},
            "S": {"type": "number", "description": "Sulphur atom count in fuel. Default 0."},
            "T_reactants": {
                "type": "number",
                "description": "Reactant (air + fuel) temperature (K). Default 298.15 K.",
            },
            "excess_air_pct": {
                "type": "number",
                "description": "Excess air (%). 0 = stoichiometric.",
            },
            "LHV_MJ_kg": {
                "type": "number",
                "description": "Lower heating value (MJ/kg). Improves accuracy significantly.",
            },
            "MW_fuel": {
                "type": "number",
                "description": "Fuel molecular weight (g/mol). Required with LHV_MJ_kg.",
            },
        },
        "required": ["C", "H"],
    },
)


@register(_aft_spec, write=False)
async def run_adiabatic_flame_temp(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C", "H"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("O", "N", "S", "T_reactants", "excess_air_pct", "LHV_MJ_kg", "MW_fuel"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = adiabatic_flame_temp(a["C"], a["H"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: combustion_hhv_to_lhv
# ---------------------------------------------------------------------------

_hhv_lhv_spec = ToolSpec(
    name="combustion_hhv_to_lhv",
    description=(
        "Convert HHV ↔ LHV using water condensation latent heat.\n"
        "\n"
        "LHV = HHV − h_fg × m_water/m_fuel\n"
        "h_fg = 2.442 MJ/kg_water (25°C)\n"
        "\n"
        "The H2O yield is computed from the fuel's hydrogen content.\n"
        "\n"
        "Reference: CH₄ HHV=55.53 MJ/kg, LHV=50.05 MJ/kg, Δ≈5.48 MJ/kg\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "HHV_MJ_kg": {
                "type": "number",
                "description": (
                    "Heating value (MJ/kg) to convert. HHV when direction='hhv_to_lhv'; "
                    "LHV when direction='lhv_to_hhv'."
                ),
            },
            "C": {"type": "number", "description": "Carbon atom count in fuel formula."},
            "H": {"type": "number", "description": "Hydrogen atom count."},
            "O": {"type": "number", "description": "Oxygen atom count. Default 0."},
            "N": {"type": "number", "description": "Nitrogen atom count. Default 0."},
            "S": {"type": "number", "description": "Sulphur atom count. Default 0."},
            "MW_fuel": {
                "type": "number",
                "description": "Fuel molecular weight (g/mol). Computed from C,H,O,N,S if not given.",
            },
            "direction": {
                "type": "string",
                "enum": ["hhv_to_lhv", "lhv_to_hhv"],
                "description": "'hhv_to_lhv' (default) or 'lhv_to_hhv'.",
            },
        },
        "required": ["HHV_MJ_kg", "C", "H"],
    },
)


@register(_hhv_lhv_spec, write=False)
async def run_hhv_to_lhv(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("HHV_MJ_kg", "C", "H"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("O", "N", "S", "MW_fuel", "direction"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = hhv_to_lhv(a["HHV_MJ_kg"], a["C"], a["H"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: combustion_efficiency
# ---------------------------------------------------------------------------

_eff_spec = ToolSpec(
    name="combustion_efficiency",
    description=(
        "Combustion efficiency and Siegert flue-gas heat loss.\n"
        "\n"
        "Siegert method (EN 15502 / VDI 2067):\n"
        "  q_A = (T_flue − T_amb) × (A₁/CO₂% + B₁)\n"
        "  η   = 100 − q_A   [%]\n"
        "\n"
        "Siegert coefficients by fuel:\n"
        "  natural_gas/methane: A₁=0.68, B₁=0.0071\n"
        "  oil:                 A₁=0.68, B₁=0.0125\n"
        "  coal:                A₁=0.68, B₁=0.0140\n"
        "  propane:             A₁=0.68, B₁=0.0083\n"
        "\n"
        "If CO2_dry_pct is not measured, provide O2_dry_pct + CO2_max_pct.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_flue_C": {
                "type": "number",
                "description": "Flue-gas temperature (°C).",
            },
            "T_ambient_C": {
                "type": "number",
                "description": "Combustion-air / ambient temperature (°C).",
            },
            "CO2_dry_pct": {
                "type": "number",
                "description": "Measured CO₂ in dry flue gas (%). Preferred input.",
            },
            "O2_dry_pct": {
                "type": "number",
                "description": "Measured O₂ in dry flue gas (%). Alternative to CO2_dry_pct.",
            },
            "CO2_max_pct": {
                "type": "number",
                "description": "Stoichiometric (max) CO₂%. Required when using O2_dry_pct.",
            },
            "fuel": {
                "type": "string",
                "enum": ["natural_gas", "methane", "oil", "coal", "propane"],
                "description": "Fuel type for Siegert coefficients. Default 'natural_gas'.",
            },
        },
        "required": ["T_flue_C", "T_ambient_C"],
    },
)


@register(_eff_spec, write=False)
async def run_combustion_efficiency(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_flue_C", "T_ambient_C"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("CO2_dry_pct", "O2_dry_pct", "CO2_max_pct", "fuel", "include_siegert"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = combustion_efficiency(a["T_flue_C"], a["T_ambient_C"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: combustion_flue_gas_dew_point
# ---------------------------------------------------------------------------

_dew_point_spec = ToolSpec(
    name="combustion_flue_gas_dew_point",
    description=(
        "Flue-gas dew-point temperature from H₂O mole fraction (sulphur-free fuel).\n"
        "\n"
        "Uses Antoine equation (NIST) for water vapour pressure:\n"
        "  log₁₀(p_sat_mmHg) = A − B/(C + T_°C)    A=8.071, B=1730.6, C=233.4\n"
        "\n"
        "If the fuel contains sulphur, the acid dew point is higher than the\n"
        "water dew point — this function computes water dew point only.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "H2O_wet_frac": {
                "type": "number",
                "description": "Mole fraction of H₂O in wet flue gas [0–1].",
            },
            "H2O_wet_pct": {
                "type": "number",
                "description": "H₂O percentage in wet flue gas (%). Alternative to H2O_wet_frac.",
            },
            "p_total_Pa": {
                "type": "number",
                "description": "Total flue-gas pressure (Pa). Default 101325 Pa.",
            },
        },
        "required": [],
    },
)


@register(_dew_point_spec, write=False)
async def run_flue_gas_dew_point(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("H2O_wet_frac") is None and a.get("H2O_wet_pct") is None:
        return json.dumps({"ok": False, "reason": "H2O_wet_frac or H2O_wet_pct is required"})

    kwargs: dict = {}
    for opt in ("H2O_wet_frac", "H2O_wet_pct", "p_total_Pa"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = flue_gas_dew_point(**kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: combustion_co2_max
# ---------------------------------------------------------------------------

_co2_max_spec = ToolSpec(
    name="combustion_co2_max",
    description=(
        "Maximum (stoichiometric, dry) CO₂ percentage in flue gas.\n"
        "\n"
        "CO₂_max occurs at stoichiometric combustion (λ=1, no excess air)\n"
        "and is the Bacharach / Siegert reference point.\n"
        "\n"
        "Reference values: CH₄ ≈ 11.7%; C₃H₈ ≈ 13.7%; gasoline ≈ 15.1%\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "C": {"type": "number", "description": "Carbon atom count in fuel formula."},
            "H": {"type": "number", "description": "Hydrogen atom count."},
            "O": {"type": "number", "description": "Oxygen atom count in fuel. Default 0."},
            "N": {"type": "number", "description": "Nitrogen atom count. Default 0."},
            "S": {"type": "number", "description": "Sulphur atom count. Default 0."},
        },
        "required": ["C", "H"],
    },
)


@register(_co2_max_spec, write=False)
async def run_co2_max(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("C", "H"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("O", "N", "S"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = co2_max(a["C"], a["H"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: combustion_fuel_power
# ---------------------------------------------------------------------------

_fuel_power_spec = ToolSpec(
    name="combustion_fuel_power",
    description=(
        "Fuel energy → thermal power and specific fuel consumption (SFC).\n"
        "\n"
        "  P_thermal = ṁ_fuel × LHV × η_combustion\n"
        "  SFC       = ṁ_fuel / P_thermal   [kg/kWh]\n"
        "\n"
        "Supply:\n"
        "  • mass_flow_kg_s  OR  (vol_flow_m3_s + density_kg_m3)\n"
        "  • LHV_MJ_kg  (or HHV_MJ_kg with use_hhv=true)\n"
        "OR supply target_power_W to back-calculate required mass flow.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mass_flow_kg_s": {
                "type": "number",
                "description": "Fuel mass flow rate (kg/s). Must be > 0.",
            },
            "vol_flow_m3_s": {
                "type": "number",
                "description": "Volumetric flow rate (m³/s). Requires density_kg_m3.",
            },
            "density_kg_m3": {
                "type": "number",
                "description": "Fuel density (kg/m³). Required with vol_flow_m3_s.",
            },
            "LHV_MJ_kg": {
                "type": "number",
                "description": "Lower heating value (MJ/kg). Preferred.",
            },
            "HHV_MJ_kg": {
                "type": "number",
                "description": "Higher heating value (MJ/kg). Used when use_hhv=true.",
            },
            "use_hhv": {
                "type": "boolean",
                "description": "Use HHV instead of LHV (default false).",
            },
            "eta_combustion": {
                "type": "number",
                "description": "Combustion efficiency [0–1] (default 1.0).",
            },
            "target_power_W": {
                "type": "number",
                "description": "Required thermal power (W). If given, back-calculates mass flow.",
            },
        },
        "required": [],
    },
)


@register(_fuel_power_spec, write=False)
async def run_fuel_power(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    kwargs: dict = {}
    for opt in (
        "mass_flow_kg_s", "vol_flow_m3_s", "density_kg_m3",
        "LHV_MJ_kg", "HHV_MJ_kg", "use_hhv", "eta_combustion", "target_power_W",
    ):
        if opt in a:
            kwargs[opt] = a[opt]

    result = fuel_power(**kwargs)
    return ok_payload(result)
