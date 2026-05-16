"""
kerf_cad_core.refrigeration.tools — LLM tool wrappers for vapor-compression
refrigeration & heat-pump design.

Registers tools with the Kerf tool registry:

  refrig_saturation_pressure     — saturation pressure at a given temperature
  refrig_single_stage_cycle      — single-stage vapor-compression cycle analysis
  refrig_tons_of_refrigeration   — convert cooling capacity between units
  refrig_compressor_sizing       — mass flow, volumetric flow, displacement
  refrig_superheat_subcool_effect — effect of superheat/subcooling on COP
  refrig_two_stage_cycle         — two-stage cycle with flash intercooler
  refrig_cascade_cycle           — cascade cycle (two refrigerants)
  refrig_defrost_energy          — defrost energy estimate for low-temp coils
  refrig_pressure_ratio_check    — pressure ratio and discharge temperature check

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
ASHRAE Fundamentals Handbook, 2021 edition.
Stoecker, W.F. & Jones, J.W., "Refrigeration and Air Conditioning", 2nd ed.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.refrigeration.cycle import (
    saturation_pressure,
    single_stage_cycle,
    tons_of_refrigeration,
    compressor_sizing,
    superheat_subcool_effect,
    two_stage_cycle,
    cascade_cycle,
    defrost_energy,
    pressure_ratio_check,
    SUPPORTED_REFRIGERANTS,
)

_REFRIGERANT_ENUM = SUPPORTED_REFRIGERANTS

# ---------------------------------------------------------------------------
# Tool: refrig_saturation_pressure
# ---------------------------------------------------------------------------

_sat_pressure_spec = ToolSpec(
    name="refrig_saturation_pressure",
    description=(
        "Saturation pressure of a refrigerant at a given temperature.\n"
        "\n"
        "Uses per-refrigerant Antoine / Clausius-Clapeyron correlations fitted "
        "to NIST/ASHRAE data. Supported refrigerants: R134a, R410A, R717 "
        "(ammonia), R744 (CO₂), R290 (propane).\n"
        "\n"
        "Returns P_sat_Pa (Pa), T_K.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_C": {
                "type": "number",
                "description": "Saturation temperature (°C). Can be negative.",
            },
            "refrigerant": {
                "type": "string",
                "enum": _REFRIGERANT_ENUM,
                "description": "Refrigerant name (default R134a).",
            },
        },
        "required": ["T_C"],
    },
)


@register(_sat_pressure_spec, write=False)
async def run_saturation_pressure(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("T_C") is None:
        return json.dumps({"ok": False, "reason": "T_C is required"})

    kwargs: dict = {}
    if "refrigerant" in a:
        kwargs["refrigerant"] = a["refrigerant"]

    result = saturation_pressure(a["T_C"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: refrig_single_stage_cycle
# ---------------------------------------------------------------------------

_single_stage_spec = ToolSpec(
    name="refrig_single_stage_cycle",
    description=(
        "Single-stage vapor-compression refrigeration cycle analysis.\n"
        "\n"
        "Given evaporator and condenser saturation temperatures plus the "
        "refrigerating capacity, computes:\n"
        "  • Saturation pressures and pressure ratio\n"
        "  • Specific refrigerating effect and compressor work (ideal + real)\n"
        "  • COP (cooling) and heating COP\n"
        "  • Mass flow rate and volumetric/displacement flow\n"
        "  • Condenser duty and estimated discharge temperature\n"
        "  • Capacity in tons of refrigeration (TR)\n"
        "\n"
        "Flags: low COP, excessive pressure ratio (>10), high discharge temp "
        "(>130°C), liquid floodback risk in `warnings` list — never raises.\n"
        "\n"
        "Supported refrigerants: R134a, R410A, R717, R744, R290.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_evap_C": {
                "type": "number",
                "description": "Evaporator saturation temperature (°C). Must be < T_cond_C.",
            },
            "T_cond_C": {
                "type": "number",
                "description": "Condenser saturation temperature (°C). Must be > T_evap_C.",
            },
            "capacity_W": {
                "type": "number",
                "description": "Refrigerating capacity Q_L (W). Must be > 0.",
            },
            "refrigerant": {
                "type": "string",
                "enum": _REFRIGERANT_ENUM,
                "description": "Refrigerant (default R134a).",
            },
            "eta_isentropic": {
                "type": "number",
                "description": "Compressor isentropic efficiency (default 0.75).",
            },
            "superheat_K": {
                "type": "number",
                "description": "Suction superheat (K, default 5). < 3 K flags floodback risk.",
            },
            "subcool_K": {
                "type": "number",
                "description": "Condenser liquid subcooling (K, default 3).",
            },
            "eta_volumetric": {
                "type": "number",
                "description": "Compressor volumetric efficiency (default 0.85).",
            },
        },
        "required": ["T_evap_C", "T_cond_C", "capacity_W"],
    },
)


@register(_single_stage_spec, write=False)
async def run_single_stage_cycle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_evap_C", "T_cond_C", "capacity_W"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("refrigerant", "eta_isentropic", "superheat_K", "subcool_K", "eta_volumetric"):
        if k in a:
            kwargs[k] = a[k]

    result = single_stage_cycle(a["T_evap_C"], a["T_cond_C"], a["capacity_W"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: refrig_tons_of_refrigeration
# ---------------------------------------------------------------------------

_tons_spec = ToolSpec(
    name="refrig_tons_of_refrigeration",
    description=(
        "Convert cooling capacity between W, kW, tons of refrigeration (TR), "
        "and BTU/h.\n"
        "\n"
        "1 TR = 3516.853 W = 3.517 kW = 12,000 BTU/h.\n"
        "Provide exactly one non-zero input; all four unit values are returned.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "capacity_W":    {"type": "number", "description": "Capacity in watts (W)."},
            "capacity_kW":   {"type": "number", "description": "Capacity in kilowatts (kW)."},
            "capacity_TR":   {"type": "number", "description": "Capacity in tons of refrigeration (TR)."},
            "capacity_BTUh": {"type": "number", "description": "Capacity in BTU/h."},
        },
        "required": [],
    },
)


@register(_tons_spec, write=False)
async def run_tons_of_refrigeration(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = tons_of_refrigeration(
        capacity_W=a.get("capacity_W", 0.0),
        capacity_TR=a.get("capacity_TR", 0.0),
        capacity_kW=a.get("capacity_kW", 0.0),
        capacity_BTUh=a.get("capacity_BTUh", 0.0),
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: refrig_compressor_sizing
# ---------------------------------------------------------------------------

_comp_sizing_spec = ToolSpec(
    name="refrig_compressor_sizing",
    description=(
        "Size a vapor-compression compressor: mass flow, volumetric flow, "
        "displacement, power, COP, and pressure ratio.\n"
        "\n"
        "Derives all compressor-sizing quantities from a single-stage cycle "
        "analysis at the specified operating conditions.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "capacity_W": {
                "type": "number",
                "description": "Refrigerating capacity (W). Must be > 0.",
            },
            "T_evap_C": {
                "type": "number",
                "description": "Evaporator saturation temperature (°C).",
            },
            "T_cond_C": {
                "type": "number",
                "description": "Condenser saturation temperature (°C).",
            },
            "refrigerant": {
                "type": "string",
                "enum": _REFRIGERANT_ENUM,
                "description": "Refrigerant (default R134a).",
            },
            "eta_isentropic": {
                "type": "number",
                "description": "Isentropic efficiency (default 0.75).",
            },
            "superheat_K": {
                "type": "number",
                "description": "Suction superheat (K, default 5).",
            },
            "subcool_K": {
                "type": "number",
                "description": "Liquid subcooling (K, default 3).",
            },
            "eta_volumetric": {
                "type": "number",
                "description": "Volumetric efficiency (default 0.85).",
            },
        },
        "required": ["capacity_W", "T_evap_C", "T_cond_C"],
    },
)


@register(_comp_sizing_spec, write=False)
async def run_compressor_sizing(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("capacity_W", "T_evap_C", "T_cond_C"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("refrigerant", "eta_isentropic", "superheat_K", "subcool_K", "eta_volumetric"):
        if k in a:
            kwargs[k] = a[k]

    result = compressor_sizing(a["capacity_W"], a["T_evap_C"], a["T_cond_C"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: refrig_superheat_subcool_effect
# ---------------------------------------------------------------------------

_sh_sc_spec = ToolSpec(
    name="refrig_superheat_subcool_effect",
    description=(
        "Quantify the effect of suction superheat and liquid subcooling on "
        "refrigeration cycle COP and refrigerating effect.\n"
        "\n"
        "Compares the modified cycle (with superheat and subcooling) against "
        "the baseline saturated cycle (superheat=0, subcool=0).\n"
        "\n"
        "Returns COP and refrigerating-effect for both cases, plus absolute "
        "and percentage changes.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_evap_C":    {"type": "number", "description": "Evaporator sat. temp (°C)."},
            "T_cond_C":    {"type": "number", "description": "Condenser sat. temp (°C)."},
            "capacity_W":  {"type": "number", "description": "Refrigerating capacity (W)."},
            "refrigerant": {"type": "string", "enum": _REFRIGERANT_ENUM},
            "superheat_K": {"type": "number", "description": "Suction superheat (K, default 5)."},
            "subcool_K":   {"type": "number", "description": "Liquid subcooling (K, default 3)."},
        },
        "required": ["T_evap_C", "T_cond_C", "capacity_W"],
    },
)


@register(_sh_sc_spec, write=False)
async def run_superheat_subcool_effect(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_evap_C", "T_cond_C", "capacity_W"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("refrigerant", "superheat_K", "subcool_K"):
        if k in a:
            kwargs[k] = a[k]

    result = superheat_subcool_effect(a["T_evap_C"], a["T_cond_C"], a["capacity_W"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: refrig_two_stage_cycle
# ---------------------------------------------------------------------------

_two_stage_spec = ToolSpec(
    name="refrig_two_stage_cycle",
    description=(
        "Two-stage vapor-compression cycle with flash intercooler.\n"
        "\n"
        "Used when the overall pressure ratio exceeds ~10 (typically when the "
        "temperature lift is large). Each stage has its own compressor. The "
        "interstage pressure uses the geometric-mean saturation temperature "
        "by default.\n"
        "\n"
        "Returns per-stage pressure ratios, mass flows, compressor powers, "
        "and overall two-stage COP (higher than single-stage for large lifts).\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_evap_C":       {"type": "number", "description": "Evaporator sat. temp (°C)."},
            "T_cond_C":       {"type": "number", "description": "Condenser sat. temp (°C)."},
            "capacity_W":     {"type": "number", "description": "Total refrigerating capacity (W)."},
            "refrigerant":    {"type": "string", "enum": _REFRIGERANT_ENUM},
            "eta_isentropic": {"type": "number", "description": "Per-stage isentropic efficiency (default 0.75)."},
            "superheat_K":    {"type": "number", "description": "Low-stage suction superheat (K, default 5)."},
            "subcool_K":      {"type": "number", "description": "Condenser liquid subcooling (K, default 3)."},
            "eta_volumetric": {"type": "number", "description": "Per-stage volumetric efficiency (default 0.85)."},
            "T_interstage_C": {"type": "number", "description": "Interstage temperature (°C); geometric mean if omitted."},
        },
        "required": ["T_evap_C", "T_cond_C", "capacity_W"],
    },
)


@register(_two_stage_spec, write=False)
async def run_two_stage_cycle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_evap_C", "T_cond_C", "capacity_W"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("refrigerant", "eta_isentropic", "superheat_K", "subcool_K",
               "eta_volumetric", "T_interstage_C"):
        if k in a:
            kwargs[k] = a[k]

    result = two_stage_cycle(a["T_evap_C"], a["T_cond_C"], a["capacity_W"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: refrig_cascade_cycle
# ---------------------------------------------------------------------------

_cascade_spec = ToolSpec(
    name="refrig_cascade_cycle",
    description=(
        "Two-refrigerant cascade vapor-compression cycle.\n"
        "\n"
        "Two separate refrigerant circuits share a cascade heat exchanger. "
        "Suited for very low temperatures (below −40°C) where a single-stage "
        "cycle has an impractically high pressure ratio.\n"
        "\n"
        "Common cascade pairs:\n"
        "  R744/R134a — deep freeze (CO₂ low circuit)\n"
        "  R717/R134a — industrial ammonia low, HFC high\n"
        "  R290/R134a — propane low circuit\n"
        "\n"
        "Returns per-circuit mass flows, compressor powers, pressure ratios, "
        "cascade duty, and overall COP.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_evap_C":          {"type": "number", "description": "Low-circuit evaporator temperature (°C)."},
            "T_cond_C":          {"type": "number", "description": "High-circuit condenser temperature (°C)."},
            "capacity_W":        {"type": "number", "description": "Total refrigerating capacity (W)."},
            "refrigerant_low":   {"type": "string", "enum": _REFRIGERANT_ENUM, "description": "Low-circuit refrigerant (default R744)."},
            "refrigerant_high":  {"type": "string", "enum": _REFRIGERANT_ENUM, "description": "High-circuit refrigerant (default R134a)."},
            "eta_isentropic":    {"type": "number", "description": "Isentropic efficiency both circuits (default 0.75)."},
            "T_cascade_C":       {"type": "number", "description": "Cascade HX temperature (°C); geometric mean if omitted."},
            "superheat_K":       {"type": "number", "description": "Suction superheat (K, default 5)."},
            "subcool_K":         {"type": "number", "description": "Liquid subcooling (K, default 3)."},
            "cascade_approach_K":{"type": "number", "description": "Temperature approach in cascade HX (K, default 5)."},
        },
        "required": ["T_evap_C", "T_cond_C", "capacity_W"],
    },
)


@register(_cascade_spec, write=False)
async def run_cascade_cycle(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_evap_C", "T_cond_C", "capacity_W"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("refrigerant_low", "refrigerant_high", "eta_isentropic",
               "T_cascade_C", "superheat_K", "subcool_K", "cascade_approach_K"):
        if k in a:
            kwargs[k] = a[k]

    result = cascade_cycle(a["T_evap_C"], a["T_cond_C"], a["capacity_W"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: refrig_defrost_energy
# ---------------------------------------------------------------------------

_defrost_spec = ToolSpec(
    name="refrig_defrost_energy",
    description=(
        "Estimate daily defrost energy for a low-temperature refrigerated coil.\n"
        "\n"
        "Defrost energy is modelled as a fixed fraction of the daily evaporator "
        "heat load (default 5%, typical for hot-gas defrost).\n"
        "\n"
        "Returns daily evaporator energy, total defrost energy, per-cycle "
        "defrost energy, total daily defrost time, and effective operating hours.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q_evap_W": {
                "type": "number",
                "description": "Evaporator capacity (W). Must be > 0.",
            },
            "operating_hours_per_day": {
                "type": "number",
                "description": "Daily operating hours (h). Must be > 0.",
            },
            "defrost_cycles_per_day": {
                "type": "integer",
                "description": "Number of defrost cycles per day (e.g. 4).",
            },
            "defrost_duration_min": {
                "type": "number",
                "description": "Duration of each defrost cycle (minutes). Must be > 0.",
            },
            "defrost_fraction": {
                "type": "number",
                "description": (
                    "Fraction of daily evap duty used for defrost (default 0.05 = 5%). "
                    "Typical hot-gas defrost: 0.03–0.08."
                ),
            },
        },
        "required": [
            "Q_evap_W",
            "operating_hours_per_day",
            "defrost_cycles_per_day",
            "defrost_duration_min",
        ],
    },
)


@register(_defrost_spec, write=False)
async def run_defrost_energy(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q_evap_W", "operating_hours_per_day", "defrost_cycles_per_day", "defrost_duration_min"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "defrost_fraction" in a:
        kwargs["defrost_fraction"] = a["defrost_fraction"]

    result = defrost_energy(
        a["Q_evap_W"],
        a["operating_hours_per_day"],
        a["defrost_cycles_per_day"],
        a["defrost_duration_min"],
        **kwargs,
    )
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: refrig_pressure_ratio_check
# ---------------------------------------------------------------------------

_pr_check_spec = ToolSpec(
    name="refrig_pressure_ratio_check",
    description=(
        "Check pressure ratio and estimate discharge temperature for a "
        "given condensing/evaporating temperature pair.\n"
        "\n"
        "Returns P_evap_Pa, P_cond_Pa, pressure_ratio, discharge_temp_est_C, "
        "and boolean flags flag_high_ratio (>10) and flag_high_discharge (>130°C).\n"
        "\n"
        "Use this to quickly assess whether single-stage or multi-stage "
        "compression is needed before running a full cycle analysis.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "T_evap_C":    {"type": "number", "description": "Evaporator saturation temperature (°C)."},
            "T_cond_C":    {"type": "number", "description": "Condenser saturation temperature (°C)."},
            "refrigerant": {"type": "string", "enum": _REFRIGERANT_ENUM, "description": "Refrigerant (default R134a)."},
            "superheat_K": {"type": "number", "description": "Suction superheat (K, default 5)."},
        },
        "required": ["T_evap_C", "T_cond_C"],
    },
)


@register(_pr_check_spec, write=False)
async def run_pressure_ratio_check(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("T_evap_C", "T_cond_C"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("refrigerant", "superheat_K"):
        if k in a:
            kwargs[k] = a[k]

    result = pressure_ratio_check(a["T_evap_C"], a["T_cond_C"], **kwargs)
    return ok_payload(result) if result.get("ok") else json.dumps(result)
