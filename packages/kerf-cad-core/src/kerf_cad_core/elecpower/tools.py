"""
kerf_cad_core.elecpower.tools — LLM tool wrappers for NEC power distribution.

Registers tools with the Kerf tool registry:

  elecpower_demand_load          — NEC Art. 220 demand-load calculation
  elecpower_conductor_ampacity   — NEC 310.16 derated conductor ampacity
  elecpower_conductor_size       — Select conductor size for a load
  elecpower_voltage_drop         — Voltage drop 1φ/3φ with upsize recommendation
  elecpower_conduit_fill         — NEC Ch.9 conduit fill percentage
  elecpower_ocpd_size            — Overcurrent device sizing per NEC 240.4
  elecpower_motor_branch         — Motor branch circuit per NEC Art. 430
  elecpower_transformer_feeder   — Transformer & feeder sizing per NEC 450
  elecpower_short_circuit        — Point-to-point short-circuit analysis
  elecpower_pf_correction        — Power-factor correction kVAR / capacitor sizing
  elecpower_grounding_conductor  — GEC (250.66) and EGC (250.122) sizing
  elecpower_panel_schedule       — Panel/feeder schedule rollup
  elecpower_generator_size       — Generator / UPS sizing

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
NFPA 70 (NEC) 2023

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.elecpower.distribution import (
    demand_load,
    conductor_ampacity,
    conductor_size_for_load,
    voltage_drop,
    conduit_fill,
    overcurrent_device_size,
    motor_branch_circuit,
    transformer_feeder_size,
    short_circuit_analysis,
    power_factor_correction,
    grounding_conductor_size,
    panel_schedule_rollup,
    generator_ups_size,
)


# ---------------------------------------------------------------------------
# Tool: elecpower_demand_load
# ---------------------------------------------------------------------------

_demand_load_spec = ToolSpec(
    name="elecpower_demand_load",
    description=(
        "Calculate feeder/service demand load per NEC Art. 220.\n"
        "\n"
        "Applies NEC 215.2/220.14 continuous-load 125% factor and, for dwelling "
        "occupancies, NEC Table 220.42 general-lighting demand factors.\n"
        "\n"
        "Returns demand_va, continuous_va, noncontinuous_demand_va.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "loads": {
                "type": "array",
                "description": (
                    "List of load objects. Each: {name: str, va: float, "
                    "continuous: bool (optional, default false)}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "va": {"type": "number"},
                        "continuous": {"type": "boolean"},
                    },
                    "required": ["va"],
                },
            },
            "occupancy": {
                "type": "string",
                "enum": ["dwelling", "commercial", "industrial"],
                "description": "Building occupancy type (default 'commercial').",
            },
            "continuous_factor": {
                "type": "number",
                "description": "Multiplier for continuous loads (default 1.25).",
            },
        },
        "required": ["loads"],
    },
)


@register(_demand_load_spec, write=False)
async def run_demand_load(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    loads = a.get("loads")
    if loads is None:
        return json.dumps({"ok": False, "reason": "loads is required"})

    kwargs: dict = {}
    if "occupancy" in a:
        kwargs["occupancy"] = a["occupancy"]
    if "continuous_factor" in a:
        kwargs["continuous_factor"] = a["continuous_factor"]

    result = demand_load(loads, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_conductor_ampacity
# ---------------------------------------------------------------------------

_conductor_ampacity_spec = ToolSpec(
    name="elecpower_conductor_ampacity",
    description=(
        "Return derated conductor ampacity per NEC 310.16.\n"
        "\n"
        "Applies ambient-temperature correction (NEC 310.15(B)(2)(a)) and "
        "bundling adjustment (NEC 310.15(B)(3)(a)) to the 75°C table ampacity.\n"
        "\n"
        "Returns base_ampacity_A, ambient_correction, bundling_factor, derated_ampacity_A.\n"
        "\n"
        "Errors: {ok:false, reason} for unknown size or invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "size": {
                "type": "string",
                "description": (
                    "Conductor size: AWG '14','12','10','8','6','4','3','2','1' "
                    "or kcmil '1/0','2/0','3/0','4/0','250','300','350','400',"
                    "'500','600','700','750','1000'."
                ),
            },
            "material": {
                "type": "string",
                "enum": ["cu", "al"],
                "description": "Conductor material: 'cu' (copper, default) or 'al' (aluminum).",
            },
            "ambient_c": {
                "type": "number",
                "description": "Ambient temperature (°C). Default 30°C.",
            },
            "num_ccc": {
                "type": "integer",
                "description": "Number of current-carrying conductors in raceway. Default 3.",
            },
        },
        "required": ["size"],
    },
)


@register(_conductor_ampacity_spec, write=False)
async def run_conductor_ampacity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    size = a.get("size")
    if size is None:
        return json.dumps({"ok": False, "reason": "size is required"})

    kwargs: dict = {}
    if "material" in a:
        kwargs["material"] = a["material"]
    if "ambient_c" in a:
        kwargs["ambient_c"] = a["ambient_c"]
    if "num_ccc" in a:
        kwargs["num_ccc"] = a["num_ccc"]

    result = conductor_ampacity(size, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_conductor_size
# ---------------------------------------------------------------------------

_conductor_size_spec = ToolSpec(
    name="elecpower_conductor_size",
    description=(
        "Select minimum conductor size to carry a given load per NEC 310.16.\n"
        "\n"
        "Accounts for ambient derating, bundling derating, and applies 125% "
        "continuous-load factor when continuous=true (NEC 215.2).\n"
        "\n"
        "Returns size, required_A, derated_ampacity_A.\n"
        "\n"
        "Errors: {ok:false, reason} if no standard size is adequate. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "load_A": {
                "type": "number",
                "description": "Load current (A). Must be > 0.",
            },
            "material": {
                "type": "string",
                "enum": ["cu", "al"],
                "description": "Conductor material (default 'cu').",
            },
            "ambient_c": {
                "type": "number",
                "description": "Ambient temperature (°C, default 30).",
            },
            "num_ccc": {
                "type": "integer",
                "description": "Number of current-carrying conductors (default 3).",
            },
            "continuous": {
                "type": "boolean",
                "description": "True if load is continuous (125% factor). Default false.",
            },
        },
        "required": ["load_A"],
    },
)


@register(_conductor_size_spec, write=False)
async def run_conductor_size(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    load_A = a.get("load_A")
    if load_A is None:
        return json.dumps({"ok": False, "reason": "load_A is required"})

    kwargs: dict = {}
    for k in ("material", "ambient_c", "num_ccc", "continuous"):
        if k in a:
            kwargs[k] = a[k]

    result = conductor_size_for_load(load_A, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_voltage_drop
# ---------------------------------------------------------------------------

_voltage_drop_spec = ToolSpec(
    name="elecpower_voltage_drop",
    description=(
        "Calculate voltage drop for a conductor run and flag if it exceeds limit.\n"
        "\n"
        "Formulas (NEC Ch.9 Table 9 resistance):\n"
        "  1φ: VD = 2 × I × R × L / 1000\n"
        "  3φ: VD = √3 × I × R × L / 1000\n"
        "\n"
        "NEC recommends ≤3% on branch circuits (210.19 Informational Note) and "
        "≤5% combined feeder + branch. Exceeding vd_limit_pct triggers a warning "
        "and suggests an upsized conductor.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "load_A": {
                "type": "number",
                "description": "Load current (A). Must be > 0.",
            },
            "length_ft": {
                "type": "number",
                "description": "One-way conductor length (ft). Must be > 0.",
            },
            "size": {
                "type": "string",
                "description": "Conductor size string (e.g. '12', '4/0', '250').",
            },
            "voltage": {
                "type": "number",
                "description": "System voltage (V). Must be > 0.",
            },
            "phases": {
                "type": "integer",
                "enum": [1, 3],
                "description": "1 (single-phase, default) or 3 (three-phase).",
            },
            "material": {
                "type": "string",
                "enum": ["cu", "al"],
                "description": "Conductor material (default 'cu').",
            },
            "pf": {
                "type": "number",
                "description": "Power factor 0–1 (default 1.0).",
            },
            "vd_limit_pct": {
                "type": "number",
                "description": "Voltage-drop limit % for warning flag (default 3.0).",
            },
        },
        "required": ["load_A", "length_ft", "size", "voltage"],
    },
)


@register(_voltage_drop_spec, write=False)
async def run_voltage_drop(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("load_A", "length_ft", "size", "voltage"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("phases", "material", "pf", "vd_limit_pct"):
        if k in a:
            kwargs[k] = a[k]

    result = voltage_drop(a["load_A"], a["length_ft"], a["size"], a["voltage"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_conduit_fill
# ---------------------------------------------------------------------------

_conduit_fill_spec = ToolSpec(
    name="elecpower_conduit_fill",
    description=(
        "Calculate conduit fill percentage per NEC Chapter 9.\n"
        "\n"
        "NEC Ch.9 Table 1 limits: 53% for 1 conductor, 31% for 2, 40% for 3+.\n"
        "\n"
        "Returns fill_pct, max_fill_pct, fill_ok. Warns if over limit.\n"
        "\n"
        "Errors: {ok:false, reason} for unknown sizes or conduit. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "conductors": {
                "type": "array",
                "description": (
                    "List of conductor objects: "
                    "{size: str, material: str (optional, default 'cu'), "
                    "count: int (optional, default 1)}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "size": {"type": "string"},
                        "material": {"type": "string"},
                        "count": {"type": "integer"},
                    },
                    "required": ["size"],
                },
            },
            "conduit_trade_size_in": {
                "type": "number",
                "description": (
                    "Conduit trade size in inches: 0.5, 0.75, 1.0, 1.25, 1.5, "
                    "2.0, 2.5, 3.0, 3.5, 4.0."
                ),
            },
            "conduit_type": {
                "type": "string",
                "enum": ["EMT", "RMC", "IMC", "PVC40", "PVC80"],
                "description": "Conduit type (default 'EMT').",
            },
        },
        "required": ["conductors", "conduit_trade_size_in"],
    },
)


@register(_conduit_fill_spec, write=False)
async def run_conduit_fill(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    conductors = a.get("conductors")
    conduit_size = a.get("conduit_trade_size_in")
    if conductors is None:
        return json.dumps({"ok": False, "reason": "conductors is required"})
    if conduit_size is None:
        return json.dumps({"ok": False, "reason": "conduit_trade_size_in is required"})

    kwargs: dict = {}
    if "conduit_type" in a:
        kwargs["conduit_type"] = a["conduit_type"]

    result = conduit_fill(conductors, conduit_size, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_ocpd_size
# ---------------------------------------------------------------------------

_ocpd_size_spec = ToolSpec(
    name="elecpower_ocpd_size",
    description=(
        "Size overcurrent protection device per NEC 240.4.\n"
        "\n"
        "Selects the next standard OCPD size (NEC 240.6(A)) at or above the "
        "derated conductor ampacity. Flags undersized conductor if load_A exceeds "
        "derated ampacity.\n"
        "\n"
        "Returns ocpd_A, conductor_ampacity_A, undersized_conductor.\n"
        "\n"
        "Errors: {ok:false, reason} for unknown conductor size. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "conductor_size": {
                "type": "string",
                "description": "Conductor size string.",
            },
            "material": {
                "type": "string",
                "enum": ["cu", "al"],
                "description": "Conductor material (default 'cu').",
            },
            "load_A": {
                "type": "number",
                "description": "Optional load current (A) to check against OCPD.",
            },
            "continuous": {
                "type": "boolean",
                "description": "True if load is continuous (125% check). Default false.",
            },
            "ambient_c": {
                "type": "number",
                "description": "Ambient temperature (°C, default 30).",
            },
            "num_ccc": {
                "type": "integer",
                "description": "Number of current-carrying conductors (default 3).",
            },
        },
        "required": ["conductor_size"],
    },
)


@register(_ocpd_size_spec, write=False)
async def run_ocpd_size(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    conductor_size = a.get("conductor_size")
    if conductor_size is None:
        return json.dumps({"ok": False, "reason": "conductor_size is required"})

    kwargs: dict = {}
    for k in ("material", "load_A", "continuous", "ambient_c", "num_ccc"):
        if k in a:
            kwargs[k] = a[k]

    result = overcurrent_device_size(conductor_size, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_motor_branch
# ---------------------------------------------------------------------------

_motor_branch_spec = ToolSpec(
    name="elecpower_motor_branch",
    description=(
        "Size motor branch circuit per NEC Art. 430.\n"
        "\n"
        "  Conductor:  ≥ 125% FLC (NEC 430.22).\n"
        "  OCPD:       ≤ table % FLC — inverse-time breaker 250%, "
        "dual-element fuse 175%, instantaneous 800% (NEC 430.52 Table).\n"
        "  Overload:   ≤ 125% FLC for SF ≥ 1.15, else 115% (NEC 430.32).\n"
        "\n"
        "Uses NEC 430.248 (1φ) and 430.250 (3φ at 460V scaled to actual voltage) "
        "FLC tables.\n"
        "\n"
        "Returns flc_A, conductor_size, ocpd_A, overload_A.\n"
        "\n"
        "Errors: {ok:false, reason} if HP not in NEC table. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "hp": {
                "type": "number",
                "description": "Motor horsepower. Must be in NEC 430.248/430.250 table.",
            },
            "voltage": {
                "type": "number",
                "description": "System voltage (V).",
            },
            "phases": {
                "type": "integer",
                "enum": [1, 3],
                "description": "1 (single-phase) or 3 (three-phase, default).",
            },
            "service_factor": {
                "type": "number",
                "description": "Motor nameplate SF (default 1.15).",
            },
            "ocpd_type": {
                "type": "string",
                "enum": ["inverse_time_breaker", "dual_element_fuse", "instantaneous"],
                "description": "OCPD type (default 'inverse_time_breaker').",
            },
        },
        "required": ["hp", "voltage"],
    },
)


@register(_motor_branch_spec, write=False)
async def run_motor_branch(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    hp = a.get("hp")
    voltage = a.get("voltage")
    if hp is None:
        return json.dumps({"ok": False, "reason": "hp is required"})
    if voltage is None:
        return json.dumps({"ok": False, "reason": "voltage is required"})

    kwargs: dict = {}
    for k in ("phases", "service_factor", "ocpd_type"):
        if k in a:
            kwargs[k] = a[k]

    result = motor_branch_circuit(hp, voltage, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_transformer_feeder
# ---------------------------------------------------------------------------

_transformer_feeder_spec = ToolSpec(
    name="elecpower_transformer_feeder",
    description=(
        "Size transformer primary/secondary feeders and overcurrent devices "
        "per NEC Art. 450 and 215.\n"
        "\n"
        "Computes primary and secondary FLA, selects conductor sizes, sizes "
        "primary OCPD ≤ 125% FLA (NEC 450.3(B)), and estimates maximum "
        "secondary short-circuit current from transformer %Z.\n"
        "\n"
        "Returns primary/secondary FLA, conductor sizes, OCPD ratings, "
        "and max_secondary_sca_A.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "kva": {
                "type": "number",
                "description": "Transformer kVA rating. Must be > 0.",
            },
            "primary_voltage": {
                "type": "number",
                "description": "Primary voltage (V).",
            },
            "secondary_voltage": {
                "type": "number",
                "description": "Secondary voltage (V).",
            },
            "phases": {
                "type": "integer",
                "enum": [1, 3],
                "description": "1 or 3 (default 3).",
            },
            "impedance_pct": {
                "type": "number",
                "description": "Transformer %Z (default 5.75%).",
            },
        },
        "required": ["kva", "primary_voltage", "secondary_voltage"],
    },
)


@register(_transformer_feeder_spec, write=False)
async def run_transformer_feeder(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("kva", "primary_voltage", "secondary_voltage"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("phases", "impedance_pct"):
        if k in a:
            kwargs[k] = a[k]

    result = transformer_feeder_size(
        a["kva"], a["primary_voltage"], a["secondary_voltage"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_short_circuit
# ---------------------------------------------------------------------------

_short_circuit_spec = ToolSpec(
    name="elecpower_short_circuit",
    description=(
        "Point-to-point short-circuit analysis using infinite-bus method "
        "(NEC / IEEE 141 Red Book).\n"
        "\n"
        "Steps:\n"
        "  1. Transformer secondary bolted fault current from %Z.\n"
        "  2. Cable impedance reduces available fault current.\n"
        "  3. Required AIC = calculated fault current rounded up to next kA.\n"
        "\n"
        "Returns isc_transformer_A, isc_at_point_A, z_transformer_ohms, "
        "z_cable_ohms, required_aic_A. Warns if AIC is very high.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "transformer_kva": {
                "type": "number",
                "description": "Transformer kVA.",
            },
            "transformer_primary_V": {
                "type": "number",
                "description": "Primary voltage (V, stored for reference).",
            },
            "transformer_secondary_V": {
                "type": "number",
                "description": "Secondary line-to-line voltage (V).",
            },
            "transformer_z_pct": {
                "type": "number",
                "description": "Transformer %Z (default 5.75).",
            },
            "phases": {
                "type": "integer",
                "enum": [1, 3],
                "description": "1 or 3 (default 3).",
            },
            "cable_length_ft": {
                "type": "number",
                "description": "One-way cable length from transformer to fault point (ft, default 0).",
            },
            "cable_size": {
                "type": "string",
                "description": "Phase conductor size (default '4/0').",
            },
            "cable_material": {
                "type": "string",
                "enum": ["cu", "al"],
                "description": "Cable material (default 'cu').",
            },
            "point_name": {
                "type": "string",
                "description": "Label for the fault point (default 'distribution board').",
            },
        },
        "required": ["transformer_kva", "transformer_primary_V", "transformer_secondary_V"],
    },
)


@register(_short_circuit_spec, write=False)
async def run_short_circuit(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("transformer_kva", "transformer_primary_V", "transformer_secondary_V"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("transformer_z_pct", "phases", "cable_length_ft", "cable_size",
               "cable_material", "point_name"):
        if k in a:
            kwargs[k] = a[k]

    result = short_circuit_analysis(
        a["transformer_kva"],
        a["transformer_primary_V"],
        a["transformer_secondary_V"],
        **kwargs,
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_pf_correction
# ---------------------------------------------------------------------------

_pf_correction_spec = ToolSpec(
    name="elecpower_pf_correction",
    description=(
        "Calculate capacitor kVAR required for power-factor correction.\n"
        "\n"
        "  Q_correction = P × (tan θ₁ − tan θ₂)\n"
        "  Capacitance C = Q / (2πf × V_phase²) per phase\n"
        "\n"
        "Returns kvar_required, kvar_bank_size (rounded to 5 kVAR), "
        "capacitance_uF_per_phase, current/target kVA and kVAR.\n"
        "\n"
        "Errors: {ok:false, reason} if target_pf ≤ current_pf. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "load_kw": {
                "type": "number",
                "description": "Real power load (kW). Must be > 0.",
            },
            "current_pf": {
                "type": "number",
                "description": "Existing power factor (0 < pf ≤ 1).",
            },
            "target_pf": {
                "type": "number",
                "description": "Target power factor (must be > current_pf, ≤ 1).",
            },
            "voltage": {
                "type": "number",
                "description": "System voltage (V, line-to-line for 3φ).",
            },
            "phases": {
                "type": "integer",
                "enum": [1, 3],
                "description": "1 or 3 (default 3).",
            },
            "frequency_hz": {
                "type": "number",
                "description": "System frequency Hz (default 60).",
            },
        },
        "required": ["load_kw", "current_pf", "target_pf", "voltage"],
    },
)


@register(_pf_correction_spec, write=False)
async def run_pf_correction(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("load_kw", "current_pf", "target_pf", "voltage"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for k in ("phases", "frequency_hz"):
        if k in a:
            kwargs[k] = a[k]

    result = power_factor_correction(
        a["load_kw"], a["current_pf"], a["target_pf"], a["voltage"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_grounding_conductor
# ---------------------------------------------------------------------------

_grounding_conductor_spec = ToolSpec(
    name="elecpower_grounding_conductor",
    description=(
        "Size grounding conductors per NEC 250.\n"
        "\n"
        "  GEC (grounding-electrode conductor): NEC 250.66, based on "
        "service-entrance conductor size.\n"
        "  EGC (equipment-grounding conductor): NEC 250.122, based on "
        "OCPD rating.\n"
        "\n"
        "Returns size, material, nec_reference.\n"
        "\n"
        "Errors: {ok:false, reason} for missing inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "service_conductor_size": {
                "type": "string",
                "description": (
                    "Service-entrance conductor size (used for GEC). "
                    "Also provide for EGC as reference (ocpd_rating_A governs EGC)."
                ),
            },
            "ocpd_rating_A": {
                "type": "number",
                "description": "OCPD rating (A) — required for EGC sizing.",
            },
            "conductor_type": {
                "type": "string",
                "enum": ["gec", "egc"],
                "description": "'gec' (default) or 'egc'.",
            },
            "material": {
                "type": "string",
                "enum": ["cu", "al"],
                "description": "Conductor material (default 'cu').",
            },
        },
        "required": ["service_conductor_size"],
    },
)


@register(_grounding_conductor_spec, write=False)
async def run_grounding_conductor(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    se_size = a.get("service_conductor_size")
    if se_size is None:
        return json.dumps({"ok": False, "reason": "service_conductor_size is required"})

    kwargs: dict = {}
    for k in ("ocpd_rating_A", "conductor_type", "material"):
        if k in a:
            kwargs[k] = a[k]

    result = grounding_conductor_size(se_size, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_panel_schedule
# ---------------------------------------------------------------------------

_panel_schedule_spec = ToolSpec(
    name="elecpower_panel_schedule",
    description=(
        "Compile panel/feeder load schedule and size main breaker and feeder "
        "conductors per NEC Art. 220.\n"
        "\n"
        "Rolls up circuit VA totals, applies demand factors (optional), computes "
        "feeder amps, sizes main breaker, and selects feeder conductor.\n"
        "\n"
        "Returns total_connected_va, demand_va, total_amps, main_breaker_A, "
        "feeder_conductor_size.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuits": {
                "type": "array",
                "description": (
                    "List of circuit objects: {name: str, va: float, "
                    "continuous: bool (optional), poles: int (optional)}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "va": {"type": "number"},
                        "continuous": {"type": "boolean"},
                        "poles": {"type": "integer"},
                    },
                    "required": ["va"],
                },
            },
            "voltage": {
                "type": "number",
                "description": "Panel voltage (V, default 120).",
            },
            "phases": {
                "type": "integer",
                "enum": [1, 3],
                "description": "1 or 3 (default 1).",
            },
            "include_demand": {
                "type": "boolean",
                "description": "Apply NEC 220 demand factors (default true).",
            },
            "occupancy": {
                "type": "string",
                "enum": ["dwelling", "commercial", "industrial"],
                "description": "Occupancy type for demand factors (default 'commercial').",
            },
        },
        "required": ["circuits"],
    },
)


@register(_panel_schedule_spec, write=False)
async def run_panel_schedule(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    circuits = a.get("circuits")
    if circuits is None:
        return json.dumps({"ok": False, "reason": "circuits is required"})

    kwargs: dict = {}
    for k in ("voltage", "phases", "include_demand", "occupancy"):
        if k in a:
            kwargs[k] = a[k]

    result = panel_schedule_rollup(circuits, **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: elecpower_generator_size
# ---------------------------------------------------------------------------

_generator_size_spec = ToolSpec(
    name="elecpower_generator_size",
    description=(
        "Size a standby generator or UPS for a given load list.\n"
        "\n"
        "Applies demand factor, power factor, motor starting surge (6× LRC "
        "estimate for largest motor), and spare capacity percentage to recommend "
        "a standard generator kVA size.\n"
        "\n"
        "Returns total_running_kw, running_kva, largest_motor_starting_kva, "
        "recommended_gen_kva, standard_gen_size_kva.\n"
        "\n"
        "Errors: {ok:false, reason} for invalid inputs. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "loads": {
                "type": "array",
                "description": (
                    "List of load objects: {name: str, kw: float, "
                    "pf: float (optional), motor_hp: float (optional), "
                    "continuous: bool (optional)}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "kw": {"type": "number"},
                        "pf": {"type": "number"},
                        "motor_hp": {"type": "number"},
                        "continuous": {"type": "boolean"},
                    },
                    "required": ["kw"],
                },
            },
            "demand_factor": {
                "type": "number",
                "description": "Demand factor applied to running kW (default 0.8).",
            },
            "power_factor": {
                "type": "number",
                "description": "Generator power factor rating (default 0.8).",
            },
            "include_spare_pct": {
                "type": "number",
                "description": "Spare capacity % added to recommendation (default 20).",
            },
        },
        "required": ["loads"],
    },
)


@register(_generator_size_spec, write=False)
async def run_generator_size(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    loads = a.get("loads")
    if loads is None:
        return json.dumps({"ok": False, "reason": "loads is required"})

    kwargs: dict = {}
    for k in ("demand_factor", "power_factor", "include_spare_pct"):
        if k in a:
            kwargs[k] = a[k]

    result = generator_ups_size(loads, **kwargs)
    return ok_payload(result)
