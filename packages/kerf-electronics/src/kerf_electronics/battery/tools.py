"""
Battery-pack LLM tools.

Exposes four tools to the Kerf agent layer:

  battery_size_pack     — series/parallel cell configuration from target V/Ah
  battery_runtime       — runtime from a load profile (Peukert + DoD)
  battery_charge_time   — charge-time estimate (CC-CV model)
  battery_report        — combined sizing + runtime + charge + thermal report

All handlers follow the kerf never-raise contract:
  - Success: {"ok": True, ...} via ok_payload
  - Failure: {"ok": False, "error": ..., "code": ...} via err_payload
  Never raise.

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

from kerf_electronics.battery.pack import (
    estimate_charge_time,
    estimate_runtime,
    estimate_thermal_rise,
    pack_report,
    size_pack,
)


# ── Shared validation helper ──────────────────────────────────────────────────

def _opt_float(d: dict, key: str) -> float | None:
    """Return float if key present and numeric, else None."""
    v = d.get(key)
    if isinstance(v, (int, float)):
        return float(v)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. battery_size_pack
# ═══════════════════════════════════════════════════════════════════════════════

_SIZE_PACK_SPEC = ToolSpec(
    name="battery_size_pack",
    description=(
        "Size a battery pack from a target voltage and capacity given a single-cell spec. "
        "Computes the minimum series (n_s) and parallel (n_p) cell count, total cells, "
        "actual pack voltage, capacity, energy, and (when cell dimensions are given) "
        "pack mass and volume. "
        "Returns warnings when a cell C-rate check fails or capacity is marginal. "
        "Input shape: { target_voltage_v, target_capacity_ah, cell_voltage_v, "
        "cell_capacity_ah, cell_mass_g?, cell_volume_cm3?, cell_r_int_ohm?, "
        "cell_max_discharge_c? }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_voltage_v": {
                "type": "number",
                "description": "Desired pack nominal voltage (V).",
            },
            "target_capacity_ah": {
                "type": "number",
                "description": "Desired pack capacity (Ah).",
            },
            "cell_voltage_v": {
                "type": "number",
                "description": "Cell nominal voltage (V) — e.g. 3.6 for Li-ion 18650.",
            },
            "cell_capacity_ah": {
                "type": "number",
                "description": "Cell rated capacity (Ah) — e.g. 3.0 for a 3 Ah cell.",
            },
            "cell_mass_g": {
                "type": "number",
                "description": "Single-cell mass (g). Optional; enables pack_mass_g output.",
            },
            "cell_volume_cm3": {
                "type": "number",
                "description": "Single-cell volume (cm³). Optional; enables pack_volume_cm3.",
            },
            "cell_r_int_ohm": {
                "type": "number",
                "description": "Cell internal resistance (Ω). Optional; enables pack_r_int_ohm.",
            },
            "cell_max_discharge_c": {
                "type": "number",
                "description": "Cell max continuous discharge C-rate. Optional; enables C-rate warning.",
            },
        },
        "required": [
            "target_voltage_v", "target_capacity_ah",
            "cell_voltage_v", "cell_capacity_ah",
        ],
    },
)


@register(_SIZE_PACK_SPEC, write=False)
async def battery_size_pack(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = size_pack(
        target_voltage_v=a.get("target_voltage_v"),
        target_capacity_ah=a.get("target_capacity_ah"),
        cell_voltage_v=a.get("cell_voltage_v"),
        cell_capacity_ah=a.get("cell_capacity_ah"),
        cell_mass_g=_opt_float(a, "cell_mass_g"),
        cell_volume_cm3=_opt_float(a, "cell_volume_cm3"),
        cell_r_int_ohm=_opt_float(a, "cell_r_int_ohm"),
        cell_max_discharge_c=_opt_float(a, "cell_max_discharge_c"),
    )
    if not result["ok"]:
        return err_payload(result["reason"], "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. battery_runtime
# ═══════════════════════════════════════════════════════════════════════════════

_RUNTIME_SPEC = ToolSpec(
    name="battery_runtime",
    description=(
        "Estimate battery pack runtime from a multi-step load profile. "
        "Applies Peukert correction (k > 1 reduces effective capacity at high currents) "
        "and respects a depth-of-discharge (DoD) limit. "
        "Returns per-step actual duration, total runtime, energy delivered, and an "
        "'exhausted' flag when the pack is depleted before the profile ends. "
        "Adds a warning when any step exceeds cell_max_discharge_c. "
        "Input shape: { pack_capacity_ah, pack_voltage_v, load_profile, peukert_k?, "
        "dod_limit?, cell_max_discharge_c?, pack_r_int_ohm? } "
        "load_profile items: { power_W, duration_s }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pack_capacity_ah": {
                "type": "number",
                "description": "Rated pack capacity (Ah).",
            },
            "pack_voltage_v": {
                "type": "number",
                "description": "Pack nominal voltage (V).",
            },
            "load_profile": {
                "type": "array",
                "description": "Ordered list of load steps.",
                "items": {
                    "type": "object",
                    "properties": {
                        "power_W": {
                            "type": "number",
                            "description": "Power draw for this step (W).",
                        },
                        "duration_s": {
                            "type": "number",
                            "description": "Requested duration for this step (s).",
                        },
                    },
                    "required": ["power_W", "duration_s"],
                },
            },
            "peukert_k": {
                "type": "number",
                "description": (
                    "Peukert exponent (default 1.1). "
                    "Li-ion: 1.05–1.15; lead-acid: 1.2–1.8. "
                    "Set to 1.0 for ideal cell (no correction)."
                ),
            },
            "dod_limit": {
                "type": "number",
                "description": (
                    "Depth-of-discharge limit (0 < dod_limit <= 1.0; default 0.8). "
                    "Fraction of rated capacity that is usable."
                ),
            },
            "cell_max_discharge_c": {
                "type": "number",
                "description": "Max cell C-rate; triggers a warning when exceeded.",
            },
            "pack_r_int_ohm": {
                "type": "number",
                "description": "Pack internal resistance (Ω); used for voltage-drop report.",
            },
        },
        "required": ["pack_capacity_ah", "pack_voltage_v", "load_profile"],
    },
)


@register(_RUNTIME_SPEC, write=False)
async def battery_runtime(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    # Optional numeric params with defaults
    pk = a.get("peukert_k", 1.1)
    dod = a.get("dod_limit", 0.8)

    result = estimate_runtime(
        pack_capacity_ah=a.get("pack_capacity_ah"),
        pack_voltage_v=a.get("pack_voltage_v"),
        load_profile=a.get("load_profile"),
        peukert_k=pk,
        dod_limit=dod,
        cell_max_discharge_c=_opt_float(a, "cell_max_discharge_c"),
        pack_r_int_ohm=_opt_float(a, "pack_r_int_ohm"),
    )
    if not result["ok"]:
        return err_payload(result["reason"], "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. battery_charge_time
# ═══════════════════════════════════════════════════════════════════════════════

_CHARGE_TIME_SPEC = ToolSpec(
    name="battery_charge_time",
    description=(
        "Estimate battery pack charge time using a simplified CC-CV model. "
        "CC phase charges at charge_c_rate × Q_rated until ~80% SoC; "
        "CV tail adds ~20% of CC time for full top-up. "
        "Returns cc_time_h, cv_tail_h, total_time_h, and total_time_min. "
        "Input shape: { pack_capacity_ah, charge_c_rate?, dod_at_start? }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pack_capacity_ah": {
                "type": "number",
                "description": "Rated pack capacity (Ah).",
            },
            "charge_c_rate": {
                "type": "number",
                "description": (
                    "Charge C-rate (default 0.5 = C/2). "
                    "E.g. 1.0 = 1C charge, 0.5 = C/2."
                ),
            },
            "dod_at_start": {
                "type": "number",
                "description": (
                    "Depth of discharge at start of charging (default 0.8). "
                    "0.8 means the pack is 80% depleted."
                ),
            },
        },
        "required": ["pack_capacity_ah"],
    },
)


@register(_CHARGE_TIME_SPEC, write=False)
async def battery_charge_time(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = estimate_charge_time(
        pack_capacity_ah=a.get("pack_capacity_ah"),
        charge_c_rate=a.get("charge_c_rate", 0.5),
        dod_at_start=a.get("dod_at_start", 0.8),
    )
    if not result["ok"]:
        return err_payload(result["reason"], "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. battery_report
# ═══════════════════════════════════════════════════════════════════════════════

_REPORT_SPEC = ToolSpec(
    name="battery_report",
    description=(
        "Combined battery pack report: sizing + runtime + charge time + thermal rise. "
        "Accepts cell spec and a load profile; computes pack configuration, runtime with "
        "Peukert correction, charge-time (CC-CV), and (when cell_r_int_ohm + cell_mass_g "
        "are given) adiabatic thermal rise. "
        "Warnings are aggregated from all sub-calculations. "
        "Input shape: { target_voltage_v, target_capacity_ah, cell_voltage_v, "
        "cell_capacity_ah, load_profile, peukert_k?, dod_limit?, charge_c_rate?, "
        "cell_mass_g?, cell_volume_cm3?, cell_r_int_ohm?, cell_max_discharge_c? }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_voltage_v": {"type": "number"},
            "target_capacity_ah": {"type": "number"},
            "cell_voltage_v": {"type": "number"},
            "cell_capacity_ah": {"type": "number"},
            "load_profile": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "power_W": {"type": "number"},
                        "duration_s": {"type": "number"},
                    },
                    "required": ["power_W", "duration_s"],
                },
            },
            "peukert_k": {"type": "number"},
            "dod_limit": {"type": "number"},
            "charge_c_rate": {"type": "number"},
            "cell_mass_g": {"type": "number"},
            "cell_volume_cm3": {"type": "number"},
            "cell_r_int_ohm": {"type": "number"},
            "cell_max_discharge_c": {"type": "number"},
        },
        "required": [
            "target_voltage_v", "target_capacity_ah",
            "cell_voltage_v", "cell_capacity_ah",
            "load_profile",
        ],
    },
)


@register(_REPORT_SPEC, write=False)
async def battery_report(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = pack_report(
        target_voltage_v=a.get("target_voltage_v"),
        target_capacity_ah=a.get("target_capacity_ah"),
        cell_voltage_v=a.get("cell_voltage_v"),
        cell_capacity_ah=a.get("cell_capacity_ah"),
        load_profile=a.get("load_profile"),
        peukert_k=a.get("peukert_k", 1.1),
        dod_limit=a.get("dod_limit", 0.8),
        charge_c_rate=a.get("charge_c_rate", 0.5),
        cell_mass_g=_opt_float(a, "cell_mass_g"),
        cell_volume_cm3=_opt_float(a, "cell_volume_cm3"),
        cell_r_int_ohm=_opt_float(a, "cell_r_int_ohm"),
        cell_max_discharge_c=_opt_float(a, "cell_max_discharge_c"),
    )
    if not result["ok"]:
        return err_payload(result["reason"], "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS registry (consumed by plugin._register_tools) ──────────────────────

TOOLS = [
    (_SIZE_PACK_SPEC.name,   _SIZE_PACK_SPEC,   battery_size_pack),
    (_RUNTIME_SPEC.name,     _RUNTIME_SPEC,     battery_runtime),
    (_CHARGE_TIME_SPEC.name, _CHARGE_TIME_SPEC, battery_charge_time),
    (_REPORT_SPEC.name,      _REPORT_SPEC,      battery_report),
]
