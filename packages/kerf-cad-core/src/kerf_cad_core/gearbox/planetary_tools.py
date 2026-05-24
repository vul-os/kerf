"""
kerf_cad_core.gearbox.planetary_tools — LLM tool wrappers for planetary gearbox.

Registers four tools:

  planetary_stage_design
      Analyse a single-stage epicyclic (sun + planets + ring + carrier).
      Three modes: carrier_output, ring_output, sun_output.

  compound_planetary_design
      Stack two planetary stages and return combined ratio + efficiency.

  planetary_module_select
      Propose module + tooth counts satisfying ratio and load constraints.

All tools are pure-Python, deterministic, and never raise.
Errors are returned as {ok: false, errors: [...]}.

Author: imranparuk
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.gearbox.planetary import (
    planetary_stage,
    compound_planetary,
    planetary_module_select as _module_select,
    _VALID_MODES,
    _MODE_CARRIER_OUTPUT,
    _ETA_MESH_DEFAULT,
)


# ---------------------------------------------------------------------------
# Shared sub-schemas
# ---------------------------------------------------------------------------

_STAGE_ARGS_SCHEMA = {
    "type": "object",
    "description": "Arguments for a single planetary stage.",
    "properties": {
        "Z_sun":    {"type": "integer", "description": "Sun gear tooth count (>= 3)."},
        "Z_planet": {"type": "integer", "description": "Planet gear tooth count (>= 3)."},
        "Z_ring":   {"type": "integer", "description": "Ring (annulus) gear tooth count (>= 3). Must satisfy Z_ring = Z_sun + 2·Z_planet."},
        "N_planets": {"type": "integer", "description": "Number of planet gears (>= 2)."},
        "input_torque_Nm": {"type": "number", "description": "Input torque at the driving member (N·m, > 0)."},
        "mode": {
            "type": "string",
            "enum": sorted(_VALID_MODES),
            "description": (
                "Operating mode. "
                "'carrier_output': ring fixed, carrier is output (most common, ratio = 1 + Z_ring/Z_sun). "
                "'ring_output': carrier fixed, ring is output (ratio = -Z_ring/Z_sun, reversal). "
                "'sun_output': ring fixed, carrier drives, sun is output (ratio < 1, step-up)."
            ),
        },
        "eta_mesh": {"type": "number", "description": "Per-mesh efficiency (0 < η ≤ 1). Default 0.98 for ground spur gears."},
    },
    "required": ["Z_sun", "Z_planet", "Z_ring", "N_planets", "input_torque_Nm"],
}


# ---------------------------------------------------------------------------
# T-PG-1: planetary_stage_design
# ---------------------------------------------------------------------------

_ps_spec = ToolSpec(
    name="planetary_stage_design",
    description=(
        "Analyse a single-stage planetary (epicyclic) gearbox. "
        "\n"
        "Computes: "
        "  • Gear ratio (Willis/tabular method) "
        "  • Tooth-count constraint: Z_ring = Z_sun + 2·Z_planet "
        "  • Assembly constraint: (Z_sun + Z_ring) / N_planets ∈ ℤ "
        "  • Torque on each port: T_sun + T_ring + T_carrier = 0 "
        "  • Per-planet tangential load: F = |T_sun| / (N_planets · r_sun) "
        "  • Overall efficiency via torque method (Müller 1982) "
        "\n"
        "Three modes: "
        "  carrier_output — ring fixed, ratio = 1 + Z_ring/Z_sun (reduction) "
        "  ring_output    — carrier fixed, ratio = -Z_ring/Z_sun (reversal) "
        "  sun_output     — ring fixed, carrier drives, ratio < 1 (step-up) "
        "\n"
        "Returns {ok, ratio, efficiency, T_sun_Nm, T_ring_Nm, T_carrier_Nm, "
        "F_tangential_per_planet_N_per_module, assembly_integer, ...}. "
        "Never raises. Units: N·m, mm (module=1 basis for geometry). "
        "References: Shigley §13-7; Müller 1982."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Z_sun":             _STAGE_ARGS_SCHEMA["properties"]["Z_sun"],
            "Z_planet":          _STAGE_ARGS_SCHEMA["properties"]["Z_planet"],
            "Z_ring":            _STAGE_ARGS_SCHEMA["properties"]["Z_ring"],
            "N_planets":         _STAGE_ARGS_SCHEMA["properties"]["N_planets"],
            "input_torque_Nm":   _STAGE_ARGS_SCHEMA["properties"]["input_torque_Nm"],
            "mode":              _STAGE_ARGS_SCHEMA["properties"]["mode"],
            "eta_mesh":          _STAGE_ARGS_SCHEMA["properties"]["eta_mesh"],
        },
        "required": ["Z_sun", "Z_planet", "Z_ring", "N_planets", "input_torque_Nm"],
    },
)


@register(_ps_spec, write=False)
async def run_planetary_stage_design(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid JSON: {e}", "BAD_ARGS")

    required = ["Z_sun", "Z_planet", "Z_ring", "N_planets", "input_torque_Nm"]
    for field in required:
        if field not in a:
            return err_payload(f"missing required field '{field}'", "BAD_ARGS")

    try:
        result = planetary_stage(
            Z_sun=int(a["Z_sun"]),
            Z_planet=int(a["Z_planet"]),
            Z_ring=int(a["Z_ring"]),
            N_planets=int(a["N_planets"]),
            input_torque_Nm=float(a["input_torque_Nm"]),
            mode=str(a.get("mode", _MODE_CARRIER_OUTPUT)),
            eta_mesh=float(a.get("eta_mesh", _ETA_MESH_DEFAULT)),
        )
    except (TypeError, ValueError) as e:
        return err_payload(f"argument type error: {e}", "BAD_ARGS")

    return ok_payload(result)


# ---------------------------------------------------------------------------
# T-PG-2: compound_planetary_design
# ---------------------------------------------------------------------------

_cp_spec = ToolSpec(
    name="compound_planetary_design",
    description=(
        "Compose two single-stage planetary gearboxes in series (stacked). "
        "\n"
        "The output torque of stage 1 becomes the input of stage 2. "
        "Returns combined_ratio = ratio1 × ratio2 and "
        "combined_efficiency = η1 × η2, plus full per-stage detail. "
        "\n"
        "Use for high-reduction requirements (e.g. 20:1+ in one package) or "
        "Ravigneaux-like stacked epicyclic designs. "
        "\n"
        "Note: 'input_torque_Nm' in stage2 is overridden by the stage1 output torque. "
        "Never raises. References: Müller 1982; Shigley §13-7."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stage1": {**_STAGE_ARGS_SCHEMA, "description": "First planetary stage (driving side)."},
            "stage2": {**_STAGE_ARGS_SCHEMA, "description": "Second planetary stage (driven side). input_torque_Nm is overridden."},
        },
        "required": ["stage1", "stage2"],
    },
)


@register(_cp_spec, write=False)
async def run_compound_planetary_design(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid JSON: {e}", "BAD_ARGS")

    stage1 = a.get("stage1")
    stage2 = a.get("stage2")
    if stage1 is None or stage2 is None:
        return err_payload("missing required fields 'stage1' and/or 'stage2'", "BAD_ARGS")
    if not isinstance(stage1, dict) or not isinstance(stage2, dict):
        return err_payload("stage1 and stage2 must be objects", "BAD_ARGS")

    # Coerce integer types
    for stage in (stage1, stage2):
        for key in ("Z_sun", "Z_planet", "Z_ring", "N_planets"):
            if key in stage:
                try:
                    stage[key] = int(stage[key])
                except (TypeError, ValueError) as e:
                    return err_payload(f"{key}: {e}", "BAD_ARGS")
        for key in ("input_torque_Nm", "eta_mesh"):
            if key in stage:
                try:
                    stage[key] = float(stage[key])
                except (TypeError, ValueError) as e:
                    return err_payload(f"{key}: {e}", "BAD_ARGS")

    result = compound_planetary(stage1, stage2)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# T-PG-3: planetary_module_select
# ---------------------------------------------------------------------------

_pms_spec = ToolSpec(
    name="planetary_module_select",
    description=(
        "Propose ISO module and tooth counts for a planetary stage. "
        "\n"
        "Searches standard ISO modules (1 → 10 mm) and sun-tooth-counts to find "
        "combinations that: "
        "  1. Match target_ratio within ratio_tolerance (default 2%) "
        "  2. Satisfy tooth-count and assembly constraints "
        "  3. Keep per-planet tangential load ≤ allowable_planet_load_N "
        "\n"
        "Returns best candidate (smallest module meeting load) plus all valid "
        "candidates sorted by module. "
        "\n"
        "Example: target_ratio=4.0, mode=carrier_output → "
        "Z_sun=18, Z_planet=27, Z_ring=72 (3 planets, assembly_integer=30). "
        "\n"
        "Never raises. References: ISO 54:1996 (modules); Müller 1982."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_ratio": {
                "type": "number",
                "description": "Desired gear ratio n_in/n_out. Must be > 1 for carrier_output.",
            },
            "target_input_torque_Nm": {
                "type": "number",
                "description": "Input torque (N·m). Used to compute per-planet load.",
            },
            "allowable_planet_load_N": {
                "type": "number",
                "description": "Maximum allowable tangential load per planet (N).",
            },
            "mode": {
                "type": "string",
                "enum": sorted(_VALID_MODES),
                "description": "Operating mode (default 'carrier_output').",
            },
            "eta_mesh": {
                "type": "number",
                "description": "Per-mesh efficiency (default 0.98).",
            },
            "N_planets": {
                "type": "integer",
                "description": "Number of planet gears (default 3).",
            },
            "ratio_tolerance": {
                "type": "number",
                "description": "Fractional tolerance on ratio match (default 0.02 = 2%).",
            },
            "Z_sun_min": {
                "type": "integer",
                "description": "Minimum sun tooth count to search (default 12).",
            },
            "Z_sun_max": {
                "type": "integer",
                "description": "Maximum sun tooth count to search (default 40).",
            },
        },
        "required": ["target_ratio", "target_input_torque_Nm", "allowable_planet_load_N"],
    },
)


@register(_pms_spec, write=False)
async def run_planetary_module_select(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid JSON: {e}", "BAD_ARGS")

    required = ["target_ratio", "target_input_torque_Nm", "allowable_planet_load_N"]
    for field in required:
        if field not in a:
            return err_payload(f"missing required field '{field}'", "BAD_ARGS")

    try:
        kwargs: dict = {
            "target_ratio":            float(a["target_ratio"]),
            "target_input_torque_Nm":  float(a["target_input_torque_Nm"]),
            "allowable_planet_load_N": float(a["allowable_planet_load_N"]),
        }
        if "mode" in a:
            kwargs["mode"] = str(a["mode"])
        if "eta_mesh" in a:
            kwargs["eta_mesh"] = float(a["eta_mesh"])
        if "N_planets" in a:
            kwargs["N_planets"] = int(a["N_planets"])
        if "ratio_tolerance" in a:
            kwargs["ratio_tolerance"] = float(a["ratio_tolerance"])
        if "Z_sun_min" in a:
            kwargs["Z_sun_min"] = int(a["Z_sun_min"])
        if "Z_sun_max" in a:
            kwargs["Z_sun_max"] = int(a["Z_sun_max"])
    except (TypeError, ValueError) as e:
        return err_payload(f"argument type error: {e}", "BAD_ARGS")

    result = _module_select(**kwargs)
    return ok_payload(result)
