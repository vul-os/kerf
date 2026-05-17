"""
Thermal / junction-temperature estimator tools.

Provides three LLM-callable tools:

  thermal_junction          — Per-component Tj = Ta + P·(θjc + θcs + θsa)
                              or Tj = Ta + P·θja when no heatsink is fitted.
  thermal_board_report      — Multi-component board rollup: sum dissipations,
                              flag components over their Tj_max limit.
  thermal_heatsink_required — Back-calculate the maximum allowable heatsink
                              θsa to keep Tj ≤ Tj_max.

Thermal resistance network reference:
    Texas Instruments Application Report SLVA462B —
    "Thermal Design by Insight, Not Hindsight"
    (https://www.ti.com/lit/an/slva462b/slva462b.pdf)

Board copper spreading resistance:
    First-order circular spreading approximation; see IPC-2152 Section 4 and
    Delphi Thermal Desktop documentation for background.

All handlers follow the kerf never-raise contract: validation errors are
returned as JSON with {ok: false, reason: str}.

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.thermal.model import (
    ThermalComponent,
    copper_spreading_resistance,
    thermal_board_report,
    thermal_heatsink_required,
    thermal_junction,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. thermal_junction
# ═══════════════════════════════════════════════════════════════════════════════

thermal_junction_spec = ToolSpec(
    name="thermal_junction",
    description=(
        "Compute steady-state junction temperature for a single PCB component.\n\n"
        "With heatsink:  Tj = Ta + P * (θjc + θcs + θsa)\n"
        "Without:        Tj = Ta + P * θja\n\n"
        "Thermal resistances in °C/W; power in W; temperatures in °C.\n\n"
        "Returns {ok, tj_c, r_total, has_heatsink, over_limit, margin_c}.\n"
        "over_limit is True when Tj > tj_max_c (only if tj_max_c is supplied).\n"
        "margin_c = tj_max_c − tj_c (positive = safe).\n\n"
        "Reference: TI SLVA462B 'Thermal Design by Insight, Not Hindsight'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "power_w": {
                "type": "number",
                "description": "Component power dissipation in watts (>= 0).",
            },
            "ambient_c": {
                "type": "number",
                "description": "Ambient (board) temperature in °C.",
            },
            "theta_ja": {
                "type": "number",
                "description": (
                    "Effective junction-to-ambient thermal resistance (°C/W). "
                    "Required when theta_jc + theta_sa are not supplied (no-heatsink model)."
                ),
            },
            "theta_jc": {
                "type": "number",
                "description": (
                    "Junction-to-case thermal resistance (°C/W). "
                    "Required for the heatsink model together with theta_sa."
                ),
            },
            "theta_cs": {
                "type": "number",
                "description": (
                    "Case-to-heatsink interface thermal resistance (°C/W). "
                    "Defaults to 0 (no interface pad or ideal contact)."
                ),
                "default": 0.0,
            },
            "theta_sa": {
                "type": "number",
                "description": (
                    "Heatsink-to-ambient thermal resistance (°C/W). "
                    "Provide together with theta_jc to use the three-element chain. "
                    "Omit for the theta_ja (no-heatsink) model."
                ),
            },
            "tj_max_c": {
                "type": "number",
                "description": (
                    "Maximum rated junction temperature from the component datasheet (°C). "
                    "When supplied, the tool checks Tj against this limit and sets over_limit."
                ),
            },
        },
        "required": ["power_w", "ambient_c"],
    },
)


@register(thermal_junction_spec, write=False)
async def thermal_junction_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    power_w = a.get("power_w")
    ambient_c = a.get("ambient_c")

    if not isinstance(power_w, (int, float)):
        return err_payload("power_w must be a number", "BAD_ARGS")
    if not isinstance(ambient_c, (int, float)):
        return err_payload("ambient_c must be a number", "BAD_ARGS")

    theta_ja = a.get("theta_ja")
    theta_jc = a.get("theta_jc")
    theta_cs = a.get("theta_cs", 0.0)
    theta_sa = a.get("theta_sa")
    tj_max_c = a.get("tj_max_c")

    # Coerce optional numerics
    for name, val in [
        ("theta_ja", theta_ja),
        ("theta_jc", theta_jc),
        ("theta_sa", theta_sa),
        ("tj_max_c", tj_max_c),
    ]:
        if val is not None and not isinstance(val, (int, float)):
            return err_payload(f"{name} must be a number", "BAD_ARGS")

    if not isinstance(theta_cs, (int, float)):
        return err_payload("theta_cs must be a number", "BAD_ARGS")

    result = thermal_junction(
        power_w=float(power_w),
        ambient_c=float(ambient_c),
        theta_ja=float(theta_ja) if theta_ja is not None else None,
        theta_jc=float(theta_jc) if theta_jc is not None else None,
        theta_cs=float(theta_cs),
        theta_sa=float(theta_sa) if theta_sa is not None else None,
        tj_max_c=float(tj_max_c) if tj_max_c is not None else None,
    )

    if not result["ok"]:
        return err_payload(result["reason"], "BAD_ARGS")

    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. thermal_board_report
# ═══════════════════════════════════════════════════════════════════════════════

thermal_board_report_spec = ToolSpec(
    name="thermal_board_report",
    description=(
        "Board-level thermal rollup: compute Tj for every component, sum total "
        "power dissipation, and flag any component whose Tj exceeds its Tj_max.\n\n"
        "Each component entry uses the same thermal network model as thermal_junction:\n"
        "  • Heatsink path:  Tj = Ta + P * (θjc + θcs + θsa)\n"
        "  • No heatsink:    Tj = Ta + P * θja\n\n"
        "Returns {ok, ambient_c, total_power_w, components[], worst_ref, worst_tj_c, "
        "any_over_limit}. Components list mirrors thermal_junction output per entry."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ambient_c": {
                "type": "number",
                "description": "Board ambient temperature in °C.",
            },
            "components": {
                "type": "array",
                "description": (
                    "List of component thermal descriptors. Each item:\n"
                    "  ref       (str)   — component reference, e.g. 'U1'\n"
                    "  power_w   (num)   — dissipated power (W)\n"
                    "  theta_ja  (num?)  — junction-to-ambient (°C/W)\n"
                    "  theta_jc  (num?)  — junction-to-case (°C/W)\n"
                    "  theta_cs  (num?)  — case-to-heatsink interface (°C/W), default 0\n"
                    "  theta_sa  (num?)  — heatsink-to-ambient (°C/W)\n"
                    "  tj_max_c  (num?)  — max rated junction temp (°C)"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "power_w": {"type": "number"},
                        "theta_ja": {"type": "number"},
                        "theta_jc": {"type": "number"},
                        "theta_cs": {"type": "number"},
                        "theta_sa": {"type": "number"},
                        "tj_max_c": {"type": "number"},
                    },
                    "required": ["ref", "power_w"],
                },
            },
        },
        "required": ["ambient_c", "components"],
    },
)


@register(thermal_board_report_spec, write=False)
async def thermal_board_report_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    ambient_c = a.get("ambient_c")
    raw_components = a.get("components")

    if not isinstance(ambient_c, (int, float)):
        return err_payload("ambient_c must be a number", "BAD_ARGS")
    if not isinstance(raw_components, list) or len(raw_components) == 0:
        return err_payload("components must be a non-empty list", "BAD_ARGS")

    components = []
    for i, item in enumerate(raw_components):
        if not isinstance(item, dict):
            return err_payload(f"components[{i}] must be an object", "BAD_ARGS")
        ref = item.get("ref")
        if not isinstance(ref, str) or not ref:
            return err_payload(f"components[{i}].ref must be a non-empty string", "BAD_ARGS")
        power_w = item.get("power_w")
        if not isinstance(power_w, (int, float)):
            return err_payload(f"components[{i}].power_w must be a number", "BAD_ARGS")

        theta_ja = item.get("theta_ja")
        theta_jc = item.get("theta_jc")
        theta_cs = item.get("theta_cs", 0.0)
        theta_sa = item.get("theta_sa")
        tj_max_c = item.get("tj_max_c")

        components.append(ThermalComponent(
            ref=ref,
            power_w=float(power_w),
            theta_ja=float(theta_ja) if theta_ja is not None else None,
            theta_jc=float(theta_jc) if theta_jc is not None else None,
            theta_cs=float(theta_cs) if theta_cs is not None else 0.0,
            theta_sa=float(theta_sa) if theta_sa is not None else None,
            tj_max_c=float(tj_max_c) if tj_max_c is not None else None,
        ))

    result = thermal_board_report(components, ambient_c=float(ambient_c))

    if not result["ok"]:
        return err_payload(result["reason"], "BAD_ARGS")

    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. thermal_heatsink_required
# ═══════════════════════════════════════════════════════════════════════════════

thermal_heatsink_required_spec = ToolSpec(
    name="thermal_heatsink_required",
    description=(
        "Back-calculate the maximum allowable heatsink-to-ambient resistance (θsa) "
        "to keep junction temperature at or below Tj_max.\n\n"
        "Formula: θsa_max = (Tj_max − safety_margin − Ta) / P − θjc − θcs\n\n"
        "Returns {ok, theta_sa_max_c_w, tj_target_c, feasible}.\n"
        "feasible=False means no heatsink can meet the target at the given power/ambient; "
        "the design requires a lower-θjc package, reduced power, or active cooling.\n"
        "When power_w=0, no heatsink is needed (note field is set)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "power_w": {
                "type": "number",
                "description": "Component power dissipation in watts (>= 0).",
            },
            "ambient_c": {
                "type": "number",
                "description": "Ambient temperature in °C.",
            },
            "theta_jc": {
                "type": "number",
                "description": "Junction-to-case thermal resistance (°C/W).",
            },
            "tj_max_c": {
                "type": "number",
                "description": "Maximum rated junction temperature from datasheet (°C).",
            },
            "theta_cs": {
                "type": "number",
                "description": "Case-to-heatsink interface resistance (°C/W). Default 0.",
                "default": 0.0,
            },
            "safety_margin_c": {
                "type": "number",
                "description": (
                    "Safety margin deducted from tj_max_c (°C). "
                    "E.g. 10 means Tj_target = Tj_max − 10 °C. Default 0."
                ),
                "default": 0.0,
            },
        },
        "required": ["power_w", "ambient_c", "theta_jc", "tj_max_c"],
    },
)


@register(thermal_heatsink_required_spec, write=False)
async def thermal_heatsink_required_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    power_w = a.get("power_w")
    ambient_c = a.get("ambient_c")
    theta_jc = a.get("theta_jc")
    tj_max_c = a.get("tj_max_c")
    theta_cs = a.get("theta_cs", 0.0)
    safety_margin_c = a.get("safety_margin_c", 0.0)

    for name, val in [
        ("power_w", power_w),
        ("ambient_c", ambient_c),
        ("theta_jc", theta_jc),
        ("tj_max_c", tj_max_c),
    ]:
        if not isinstance(val, (int, float)):
            return err_payload(f"{name} must be a number", "BAD_ARGS")

    for name, val in [("theta_cs", theta_cs), ("safety_margin_c", safety_margin_c)]:
        if not isinstance(val, (int, float)):
            return err_payload(f"{name} must be a number", "BAD_ARGS")

    result = thermal_heatsink_required(
        power_w=float(power_w),
        ambient_c=float(ambient_c),
        theta_jc=float(theta_jc),
        tj_max_c=float(tj_max_c),
        theta_cs=float(theta_cs),
        safety_margin_c=float(safety_margin_c),
    )

    if not result["ok"]:
        return err_payload(result["reason"], "BAD_ARGS")

    return ok_payload(result)


# ── TOOLS registry (consumed by plugin._register_tools) ──────────────────────

TOOLS = [
    ("thermal_junction", thermal_junction_spec, thermal_junction_tool),
    ("thermal_board_report", thermal_board_report_spec, thermal_board_report_tool),
    ("thermal_heatsink_required", thermal_heatsink_required_spec, thermal_heatsink_required_tool),
]
