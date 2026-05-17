"""
Auto-placement essentials — LLM tool wrappers.

Provides five LLM-callable tools that mirror the public API in essentials.py:

  auto_decouple               — place decoupling caps near IC VCC pins
  thermal_via_array           — via grid/staggered array under thermal pad
  mounting_hole_keepout       — circular no-route keep-out around mounting holes
  power_plane_relief          — anti-pad cutout for via through power plane
  bypass_cap_recommendation   — recommend cap value + package per IC type

All handlers follow the kerf never-raise contract:
  Success: {"ok": True, ...}  via ok_payload
  Failure: {"ok": False, "error": ..., "code": ...}  via err_payload
  Never raise.
"""

from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register

from kerf_electronics.autoplace.essentials import (
    auto_decouple,
    bypass_cap_recommendation,
    mounting_hole_keepout,
    power_plane_relief,
    thermal_via_array,
)


# ─── auto_decouple ────────────────────────────────────────────────────────────

_auto_decouple_spec = ToolSpec(
    name="auto_decouple",
    description=(
        "Place one decoupling capacitor per VCC/VDD pin of each IC footprint "
        "on the board. Each cap is positioned at most 2 mm from the VCC pin, "
        "along the vector toward the nearest GND pin of the same IC. Short "
        "VCC→cap and cap→GND trace segments are generated. "
        "Returns the list of placed cap objects and trace segments ready to "
        "merge into the CircuitJSON board."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "board": {
                "description": (
                    "CircuitJSON board element or array. "
                    "Used read-only as context (dimensions, existing traces)."
                ),
                "oneOf": [
                    {"type": "object"},
                    {"type": "array", "items": {"type": "object"}},
                ],
            },
            "ic_footprints": {
                "type": "array",
                "description": (
                    "List of IC component dicts. Each must have 'refdes', "
                    "'x', 'y', and a 'pads' list. Each pad needs 'net_name' "
                    "(or 'pin_name'/'net_id') plus 'x', 'y' offsets relative "
                    "to the component origin."
                ),
                "items": {"type": "object"},
            },
            "cap_value": {
                "type": "string",
                "description": "Capacitor value label (default '100nF').",
            },
            "package": {
                "type": "string",
                "description": "Package code, e.g. '0402', '0201', '0603' (default '0402').",
                "enum": ["0201", "0402", "0603", "0805", "1206"],
            },
        },
        "required": ["ic_footprints"],
    },
)


@register(_auto_decouple_spec)
async def run_auto_decouple(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    ic_footprints = a.get("ic_footprints")
    if not isinstance(ic_footprints, list):
        return err_payload("ic_footprints must be an array", "BAD_ARGS")

    board = a.get("board", {})
    cap_value = str(a.get("cap_value", "100nF"))
    package = str(a.get("package", "0402"))
    if package not in ("0201", "0402", "0603", "0805", "1206"):
        return err_payload(
            "package must be one of 0201, 0402, 0603, 0805, 1206", "BAD_ARGS"
        )

    result = auto_decouple(board, ic_footprints, cap_value=cap_value, package=package)

    return ok_payload({
        "ok": True,
        **result,
        "message": (
            f"Placed {result['cap_count']} decoupling cap(s) "
            f"({cap_value} {package}). "
            + (
                f"{len(result['warnings'])} warning(s)."
                if result["warnings"]
                else "No warnings."
            )
        ),
    })


# ─── thermal_via_array ────────────────────────────────────────────────────────

_thermal_via_array_spec = ToolSpec(
    name="thermal_via_array",
    description=(
        "Place an N×M via array under an IC thermal / exposed pad for PCB "
        "heat-sinking. The array is centred on the pad. Supports 'grid' and "
        "'staggered' lattice patterns. Returns the list of via objects and the "
        "grid dimensions used."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "board": {
                "description": "CircuitJSON board (read-only context).",
                "oneOf": [
                    {"type": "object"},
                    {"type": "array", "items": {"type": "object"}},
                ],
            },
            "pad": {
                "type": "object",
                "description": (
                    "Thermal pad dict with 'x', 'y', 'width', 'height', "
                    "and 'net_name' (or 'net_id')."
                ),
            },
            "via_count": {
                "type": "integer",
                "description": "Target number of vias (actual may be slightly more to fill the grid).",
                "minimum": 1,
            },
            "via_dia": {
                "type": "number",
                "description": "Via outer annular ring diameter (mm).",
            },
            "via_drill": {
                "type": "number",
                "description": "Via drill diameter (mm). Must be < via_dia.",
            },
            "pattern": {
                "type": "string",
                "enum": ["grid", "staggered"],
                "description": "Via arrangement: 'grid' (default) or 'staggered' offset rows.",
            },
        },
        "required": ["pad", "via_count", "via_dia", "via_drill"],
    },
)


@register(_thermal_via_array_spec)
async def run_thermal_via_array(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    pad = a.get("pad")
    if not isinstance(pad, dict):
        return err_payload("pad must be an object", "BAD_ARGS")

    via_count = a.get("via_count")
    if not isinstance(via_count, int) or via_count < 1:
        return err_payload("via_count must be a positive integer", "BAD_ARGS")

    via_dia = a.get("via_dia")
    via_drill = a.get("via_drill")
    if via_dia is None or via_drill is None:
        return err_payload("via_dia and via_drill are required", "BAD_ARGS")

    pattern = str(a.get("pattern", "grid"))
    board = a.get("board", {})

    result = thermal_via_array(
        board, pad,
        via_count=int(via_count),
        via_dia=float(via_dia),
        via_drill=float(via_drill),
        pattern=pattern,
    )

    if "error" in result:
        return err_payload(result["error"], result.get("code", "ERROR"))

    return ok_payload({
        "ok": True,
        **result,
        "message": (
            f"Placed {result['actual_count']} thermal via(s) in a "
            f"{result['rows']}×{result['cols']} {result['pattern']} array "
            f"(pitch {result['pitch_x_mm']:.3f} × {result['pitch_y_mm']:.3f} mm)."
        ),
    })


# ─── mounting_hole_keepout ────────────────────────────────────────────────────

_mounting_hole_keepout_spec = ToolSpec(
    name="mounting_hole_keepout",
    description=(
        "Generate a circular no-route / no-component keep-out zone around a "
        "PCB mounting hole. The keep-out radius equals hole_dia/2 + "
        "keepout_extra_mm (default 2.5 mm). Returns a CircuitJSON-compatible "
        "keepout polygon and the effective radius."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "board": {
                "description": "CircuitJSON board (read-only context).",
                "oneOf": [
                    {"type": "object"},
                    {"type": "array", "items": {"type": "object"}},
                ],
            },
            "hole_position": {
                "type": "object",
                "description": "Dict with 'x' and 'y' keys (mm).",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                },
                "required": ["x", "y"],
            },
            "hole_dia": {
                "type": "number",
                "description": "Mounting hole drill diameter (mm).",
            },
            "keepout_extra_mm": {
                "type": "number",
                "description": (
                    "Additional clearance beyond the hole edge (mm). "
                    "Default 2.5 mm per IPC-7351 guidance."
                ),
            },
        },
        "required": ["hole_position", "hole_dia"],
    },
)


@register(_mounting_hole_keepout_spec)
async def run_mounting_hole_keepout(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    hole_position = a.get("hole_position")
    if not isinstance(hole_position, dict):
        return err_payload("hole_position must be an object with x, y keys", "BAD_ARGS")

    hole_dia = a.get("hole_dia")
    if hole_dia is None:
        return err_payload("hole_dia is required", "BAD_ARGS")

    keepout_extra_mm = float(a.get("keepout_extra_mm", 2.5))
    board = a.get("board", {})

    result = mounting_hole_keepout(
        board,
        hole_position=hole_position,
        hole_dia=float(hole_dia),
        keepout_extra_mm=keepout_extra_mm,
    )

    if "error" in result:
        return err_payload(result["error"], result.get("code", "ERROR"))

    return ok_payload({
        "ok": True,
        **result,
        "message": (
            f"Keep-out zone generated: radius {result['radius_mm']:.3f} mm "
            f"(hole {hole_dia} mm + {keepout_extra_mm} mm clearance)."
        ),
    })


# ─── power_plane_relief ───────────────────────────────────────────────────────

_power_plane_relief_spec = ToolSpec(
    name="power_plane_relief",
    description=(
        "Generate an anti-pad (thermal relief) cutout for a signal or power "
        "via passing through a copper power plane. The anti-pad is a circular "
        "polygon with diameter = via_outer_dia + 2 × anti_pad_mm, placed on "
        "the specified plane layer. Returns a CircuitJSON plane-cutout object."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plane_layer": {
                "type": "string",
                "description": (
                    "Layer name of the power plane, e.g. 'inner_copper_1', "
                    "'inner_copper_2', 'bottom_copper'."
                ),
            },
            "via": {
                "type": "object",
                "description": (
                    "Via dict with 'x', 'y', 'outer_diameter' (mm), "
                    "and 'net_name' (or 'net_id')."
                ),
            },
            "anti_pad_mm": {
                "type": "number",
                "description": (
                    "Clearance from via pad edge to plane edge (mm). "
                    "Typical value: 0.2–0.5 mm."
                ),
            },
        },
        "required": ["plane_layer", "via", "anti_pad_mm"],
    },
)


@register(_power_plane_relief_spec)
async def run_power_plane_relief(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    plane_layer = a.get("plane_layer")
    if not plane_layer or not isinstance(plane_layer, str):
        return err_payload("plane_layer must be a non-empty string", "BAD_ARGS")

    via = a.get("via")
    if not isinstance(via, dict):
        return err_payload("via must be an object", "BAD_ARGS")

    anti_pad_mm = a.get("anti_pad_mm")
    if anti_pad_mm is None:
        return err_payload("anti_pad_mm is required", "BAD_ARGS")

    result = power_plane_relief(
        plane_layer=plane_layer,
        via=via,
        anti_pad_mm=float(anti_pad_mm),
    )

    if "error" in result:
        return err_payload(result["error"], result.get("code", "ERROR"))

    ap = result["anti_pad"]
    return ok_payload({
        "ok": True,
        **result,
        "message": (
            f"Anti-pad cutout generated on '{plane_layer}': "
            f"diameter {ap['anti_pad_dia_mm']:.3f} mm "
            f"({ap['via_od_mm']:.3f} mm via + 2 × {anti_pad_mm} mm clearance)."
        ),
    })


# ─── bypass_cap_recommendation ────────────────────────────────────────────────

_bypass_cap_recommendation_spec = ToolSpec(
    name="bypass_cap_recommendation",
    description=(
        "Recommend bypass / decoupling capacitor values and packages for a "
        "given IC part number. Covers common MCUs (STM32, RP2040, ESP32, "
        "ATmega), FPGAs, op-amps, LDO regulators, logic families, and ADCs. "
        "Unknown parts receive a generic 100 nF + 10 uF recommendation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ic_part": {
                "type": "string",
                "description": (
                    "Part number or descriptive name, e.g. 'STM32F103C8', "
                    "'ATmega328P', 'AMS1117-3.3', '74HC595' (case-insensitive)."
                ),
            },
            "supply_voltage": {
                "type": "number",
                "description": "Supply voltage in volts (optional context).",
            },
        },
        "required": ["ic_part"],
    },
)


@register(_bypass_cap_recommendation_spec)
async def run_bypass_cap_recommendation(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    ic_part = a.get("ic_part")
    if not ic_part or not isinstance(ic_part, str):
        return err_payload("ic_part must be a non-empty string", "BAD_ARGS")

    supply_voltage = a.get("supply_voltage")
    if supply_voltage is not None:
        supply_voltage = float(supply_voltage)

    result = bypass_cap_recommendation(ic_part=ic_part, supply_voltage=supply_voltage)

    if "error" in result:
        return err_payload(result["error"], result.get("code", "ERROR"))

    recs = result["recommendations"]
    summary = "; ".join(f"{r['value']} {r['package']} ({r['notes']})" for r in recs)
    known = result["known_part"]

    return ok_payload({
        "ok": True,
        **result,
        "message": (
            f"{'Known' if known else 'Generic'} recommendations for "
            f"'{result['ic_part']}': {summary}."
        ),
    })


# ─── TOOLS export — consumed by plugin._register_tools ───────────────────────

TOOLS = [
    (_auto_decouple_spec.name,               _auto_decouple_spec,               run_auto_decouple),
    (_thermal_via_array_spec.name,           _thermal_via_array_spec,           run_thermal_via_array),
    (_mounting_hole_keepout_spec.name,       _mounting_hole_keepout_spec,       run_mounting_hole_keepout),
    (_power_plane_relief_spec.name,          _power_plane_relief_spec,          run_power_plane_relief),
    (_bypass_cap_recommendation_spec.name,   _bypass_cap_recommendation_spec,   run_bypass_cap_recommendation),
]
