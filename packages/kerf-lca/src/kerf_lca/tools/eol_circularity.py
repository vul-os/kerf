"""
LLM tools: Module D EoL circularity (EN 15978)

Three tools are registered:

1. lca_module_d_credit
   EN 15978 Module D credit for recycling, reuse, or energy recovery.

2. lca_circularity_index
   Ellen MacArthur MCI (0–1) for a material + design intent.

3. lca_full_lifecycle
   Cradle-to-grave + Module D breakdown with MCI.

Reference: EN 15978:2011 §11.4; Ellen MacArthur Foundation MCI methodology (2015).
IMPORTANT: Results are design-stage estimates — NOT EN-certified LCA declarations.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_lca._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_lca.eol_circularity import (
    EolScenario,
    circularity_index,
    compute_full_lifecycle_carbon,
    compute_module_d_credit,
)

# ---------------------------------------------------------------------------
# Shared schema components
# ---------------------------------------------------------------------------

_SCENARIO_ENUM = ["landfill", "recycling", "reuse", "incineration_with_energy_recovery", "composting"]

_SCENARIO_OBJECT = {
    "type": "object",
    "description": (
        "End-of-life scenario parameters. "
        "scenario_type: landfill | recycling | reuse | incineration_with_energy_recovery | composting."
    ),
    "required": ["scenario_type"],
    "properties": {
        "scenario_type": {"type": "string", "enum": _SCENARIO_ENUM},
        "recovery_efficiency": {
            "type": "number",
            "description": "Fraction of material actually recovered (0–1). Default 0.85.",
        },
        "displacement_factor": {
            "type": "number",
            "description": (
                "Fraction of virgin-material GWP displaced per kg recycled/reused (0–1). "
                "EN 15978 default 0.5 (50:50 allocation); 1.0 for closed-loop."
            ),
        },
    },
}


def _parse_scenario(s: dict) -> EolScenario:
    """Build an EolScenario from a dict; raises ValueError on bad input."""
    stype = s.get("scenario_type", "")
    kwargs: dict[str, Any] = {"scenario_type": stype}
    if "recovery_efficiency" in s:
        kwargs["recovery_efficiency"] = float(s["recovery_efficiency"])
    if "displacement_factor" in s:
        kwargs["displacement_factor"] = float(s["displacement_factor"])
    if "recycled_content_credit_kg_co2_per_kg" in s:
        kwargs["recycled_content_credit_kg_co2_per_kg"] = float(
            s["recycled_content_credit_kg_co2_per_kg"]
        )
    return EolScenario(**kwargs)


# ---------------------------------------------------------------------------
# Tool 1: lca_module_d_credit
# ---------------------------------------------------------------------------

module_d_credit_spec = ToolSpec(
    name="lca_module_d_credit",
    description=(
        "Compute the EN 15978 Module D end-of-life carbon credit for a material "
        "at its end-of-life. Module D (beyond system boundary) quantifies the net "
        "benefit from recycling, reuse, or energy recovery, per EN 15978:2011 §11.4. "
        "Returns the kg CO₂-eq saved for each scenario type. "
        "IMPORTANT: Module D is informational and reported separately — NOT added to "
        "the A1–C lifecycle total. NOT an EN-certified LCA report."
    ),
    input_schema={
        "type": "object",
        "required": ["material", "mass_kg", "eol_scenario"],
        "properties": {
            "material": {
                "type": "string",
                "description": "Material name or ICE v3 key (e.g. 'steel', 'aluminium_primary').",
            },
            "mass_kg": {
                "type": "number",
                "description": "Mass of end-of-life material in kg.",
            },
            "eol_scenario": _SCENARIO_OBJECT,
            "grid_region": {
                "type": "string",
                "description": (
                    "Grid region for incineration electricity credit "
                    "(US | EU | CN | ZA | GB | WORLD). Default WORLD."
                ),
            },
        },
    },
)


@register(module_d_credit_spec)
async def run_lca_module_d_credit(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    material = a.get("material")
    if not material:
        return err_payload("'material' is required", "BAD_ARGS")

    mass_raw = a.get("mass_kg")
    if mass_raw is None:
        return err_payload("'mass_kg' is required", "BAD_ARGS")
    try:
        mass_kg = float(mass_raw)
        if mass_kg <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return err_payload("'mass_kg' must be a positive number", "BAD_ARGS")

    scenario_dict = a.get("eol_scenario")
    if not isinstance(scenario_dict, dict):
        return err_payload("'eol_scenario' must be an object with 'scenario_type'", "BAD_ARGS")

    try:
        scenario = _parse_scenario(scenario_dict)
    except Exception as e:
        return err_payload(str(e), "BAD_ARGS")

    grid_region = a.get("grid_region", "WORLD")

    try:
        result = compute_module_d_credit(
            material, mass_kg, scenario, grid_region=grid_region
        )
    except Exception as e:
        return err_payload(str(e), "CALC_ERROR")

    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool 2: lca_circularity_index
# ---------------------------------------------------------------------------

circularity_index_spec = ToolSpec(
    name="lca_circularity_index",
    description=(
        "Compute the Material Circularity Indicator (MCI) for a material and design "
        "intent, per Ellen MacArthur Foundation methodology (2015). "
        "MCI ∈ [0, 1]: 0 = fully linear (virgin input, landfill), 1 = fully circular. "
        "Considers: recycled input fraction, EoL recycling/reuse rate, recyclability "
        "quality (closed- vs open-loop), and product lifetime vs industry average. "
        "Formula: MCI = F_utility × (1 − 0.9 × V × W)."
    ),
    input_schema={
        "type": "object",
        "required": ["material"],
        "properties": {
            "material": {
                "type": "string",
                "description": "Material name or ICE v3 key.",
            },
            "design_intent": {
                "type": "object",
                "description": (
                    "Design and end-of-life intent. All keys optional; defaults "
                    "come from ICE v3 database for the material."
                ),
                "properties": {
                    "recycled_input_fraction": {
                        "type": "number",
                        "description": "Fraction of mass from recycled sources (0–1).",
                    },
                    "eol_recycling_fraction": {
                        "type": "number",
                        "description": "Fraction of product mass recycled/reused at EoL (0–1).",
                    },
                    "recyclability_quality": {
                        "type": "number",
                        "description": (
                            "Quality of the recycling loop (0–1). "
                            "1.0 = closed-loop same quality; 0.5 = open-loop / downcycling."
                        ),
                    },
                    "lifetime_years": {
                        "type": "number",
                        "description": "Product service life in years.",
                    },
                    "eol_scenario": {
                        "type": "string",
                        "enum": _SCENARIO_ENUM,
                        "description": "EoL pathway; overrides eol_recycling_fraction default.",
                    },
                },
            },
        },
    },
)


@register(circularity_index_spec)
async def run_lca_circularity_index(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    material = a.get("material")
    if not material:
        return err_payload("'material' is required", "BAD_ARGS")

    design_intent = a.get("design_intent") or {}
    if not isinstance(design_intent, dict):
        return err_payload("'design_intent' must be an object", "BAD_ARGS")

    try:
        mci = circularity_index(material, design_intent)
    except Exception as e:
        return err_payload(str(e), "CALC_ERROR")

    return ok_payload({
        "material": material,
        "design_intent": design_intent,
        "circularity_index": mci,
        "interpretation": (
            "1.0 = fully circular (100% recycled input, 100% recycled EoL, full quality). "
            "0.0 = fully linear (virgin input, landfill disposal). "
            "Per Ellen MacArthur Foundation MCI methodology."
        ),
        "honesty_note": (
            "MCI is a design-stage indicator only. "
            "NOT an EN-certified assessment or verified environmental declaration."
        ),
    })


# ---------------------------------------------------------------------------
# Tool 3: lca_full_lifecycle
# ---------------------------------------------------------------------------

full_lifecycle_spec = ToolSpec(
    name="lca_full_lifecycle",
    description=(
        "Compute the full lifecycle carbon footprint (cradle-to-grave + EN 15978 Module D) "
        "for a material: A1–A3 embodied carbon + B use phase + A4/C2 transport + "
        "C3/C4 EoL processing + Module D recycling/reuse credit. "
        "Returns total cradle-to-grave GWP, the Module D credit, and the net total "
        "with Module D applied (informational, design-stage comparison only). "
        "Also reports the MCI circularity index. "
        "NOT an EN-certified LCA report."
    ),
    input_schema={
        "type": "object",
        "required": ["material", "mass_kg", "lifetime_years", "eol_scenario"],
        "properties": {
            "material": {
                "type": "string",
                "description": "Material name or ICE v3 key.",
            },
            "mass_kg": {
                "type": "number",
                "description": "Mass of the part/component in kg.",
            },
            "lifetime_years": {
                "type": "number",
                "description": "Product service life in years.",
            },
            "eol_scenario": _SCENARIO_OBJECT,
            "use_phase_kg_co2": {
                "type": "number",
                "description": (
                    "Module B use-phase GWP (kg CO₂-eq). "
                    "Use lifecycle_phases tool to compute this. Default 0."
                ),
            },
            "transport_kg_co2": {
                "type": "number",
                "description": "Module A4/C2 transport GWP (kg CO₂-eq). Default 0.",
            },
            "grid_region": {
                "type": "string",
                "description": (
                    "Grid emission region for energy-recovery credit "
                    "(US | EU | CN | ZA | GB | WORLD). Default WORLD."
                ),
            },
        },
    },
)


@register(full_lifecycle_spec)
async def run_lca_full_lifecycle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    material = a.get("material")
    if not material:
        return err_payload("'material' is required", "BAD_ARGS")

    for field_name in ("mass_kg", "lifetime_years"):
        val = a.get(field_name)
        if val is None:
            return err_payload(f"'{field_name}' is required", "BAD_ARGS")
        try:
            if float(val) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return err_payload(f"'{field_name}' must be a positive number", "BAD_ARGS")

    scenario_dict = a.get("eol_scenario")
    if not isinstance(scenario_dict, dict):
        return err_payload("'eol_scenario' must be an object with 'scenario_type'", "BAD_ARGS")

    try:
        scenario = _parse_scenario(scenario_dict)
    except Exception as e:
        return err_payload(str(e), "BAD_ARGS")

    try:
        result = compute_full_lifecycle_carbon(
            material=material,
            mass_kg=float(a["mass_kg"]),
            lifetime_years=float(a["lifetime_years"]),
            eol_scenario=scenario,
            use_phase_kg_co2=float(a.get("use_phase_kg_co2") or 0.0),
            transport_kg_co2=float(a.get("transport_kg_co2") or 0.0),
            grid_region=a.get("grid_region", "WORLD"),
        )
    except Exception as e:
        return err_payload(str(e), "CALC_ERROR")

    return ok_payload(result)
