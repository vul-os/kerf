"""
PCB trace current-capacity & copper-thermal design — LLM tools.

Provides LLM-callable tools:

  tracecurrent_ipc2152        — IPC-2152 steady-state current capacity for a trace
                                (internal vs external, copper-weight, board-k and
                                thickness correction, plane proximity factor)
  tracecurrent_required_width — bisection solver: trace width for a target I / ΔT
  tracecurrent_resistance     — trace DC resistance, I²R power, voltage drop
                                (with temperature coefficient of resistivity)
  tracecurrent_via_capacity   — via barrel current capacity (IPC-2152 model)
  tracecurrent_via_count      — minimum vias required for a given current
  tracecurrent_thermal_via    — thermal-via array Rθ and ΔT (IPC-7093)
  tracecurrent_plane_rs       — copper-plane sheet resistance, current density,
                                Onderdonk fusing margin (cross-check reference)
  tracecurrent_pour_area      — polygon-pour heatsink area for a target Rθ
  tracecurrent_busbar         — copper busbar width and resistance sizing

All handlers follow the kerf never-raise contract: errors → {"ok": false, "reason": ...}.
Over-temperature / undersized-trace / via-overcurrent conditions are reported via
warnings.warn (never raised).

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register

from kerf_electronics.tracecurrent.ampacity import (
    ipc2152_trace_current,
    required_trace_width,
    trace_resistance,
    via_current_capacity,
    required_via_count,
    thermal_via_array,
    plane_sheet_resistance,
    polygon_pour_heatsink_area,
    busbar_sizing,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. tracecurrent_ipc2152
# ═══════════════════════════════════════════════════════════════════════════════

_IPC2152_SPEC = ToolSpec(
    name="tracecurrent_ipc2152",
    description=(
        "IPC-2152 (2009) steady-state current capacity for a PCB trace.\n\n"
        "Model: I [A] = k_0 × ΔT^0.44 × A_mil²^0.725 with correction factors:\n"
        "  • Copper-weight correction: cf_cw = (oz / 1.0)^0.045\n"
        "  • Board k and thickness correction: cf_th = (k_pcb/0.25)^0.10 × (t/1.6)^0.05\n"
        "  • Plane proximity correction: cf_pl = 1 + 0.15×exp(−H_plane/0.3)\n\n"
        "Baseline coefficients (IPC-2152 Table 6-1):\n"
        "  External: k_0 = 0.048  |  Internal: k_0 = 0.024\n\n"
        "Warnings issued (never raised) when capacity is extremely low.\n\n"
        "Input: { width_mm, copper_oz?, delta_t_c?, layer?, k_pcb?, t_pcb_mm?, h_plane_mm? }\n"
        "Returns: { ok, current_a, cross_section_mil2, cf_copper_weight, cf_board, cf_plane, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "width_mm": {
                "type": "number",
                "description": "Trace width [mm].",
            },
            "copper_oz": {
                "type": "number",
                "description": "Copper weight [oz/ft²] (default 1.0).",
            },
            "delta_t_c": {
                "type": "number",
                "description": "Allowable temperature rise above ambient [°C] (default 10).",
            },
            "layer": {
                "type": "string",
                "enum": ["external", "internal"],
                "description": "Layer type: 'external' (outer) or 'internal' (inner, default 'external').",
            },
            "k_pcb": {
                "type": "number",
                "description": "Board base-material thermal conductivity [W/(m·K)] (FR-4 default 0.25).",
            },
            "t_pcb_mm": {
                "type": "number",
                "description": "Board thickness [mm] (default 1.6).",
            },
            "h_plane_mm": {
                "type": "number",
                "description": "Distance to nearest adjacent copper plane [mm]. Omit if no nearby plane.",
            },
        },
        "required": ["width_mm"],
    },
)


@register(_IPC2152_SPEC, write=False)
async def tracecurrent_ipc2152(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = ipc2152_trace_current(
        width_mm=a.get("width_mm"),
        copper_oz=a.get("copper_oz", 1.0),
        delta_t_c=a.get("delta_t_c", 10.0),
        layer=a.get("layer", "external"),
        k_pcb=a.get("k_pcb", 0.25),
        t_pcb_mm=a.get("t_pcb_mm", 1.6),
        h_plane_mm=a.get("h_plane_mm"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. tracecurrent_required_width
# ═══════════════════════════════════════════════════════════════════════════════

_REQ_WIDTH_SPEC = ToolSpec(
    name="tracecurrent_required_width",
    description=(
        "Bisection solver: PCB trace width [mm] required to carry current_a [A] "
        "with temperature rise ≤ delta_t_c [°C] (IPC-2152 model).\n\n"
        "Searches width range [0.001, 100] mm with 80 bisection iterations "
        "(precision < 0.001 mm).\n\n"
        "A warning is issued when the required width exceeds 20 mm.\n\n"
        "Input: { current_a, copper_oz?, delta_t_c?, layer?, k_pcb?, t_pcb_mm?, h_plane_mm? }\n"
        "Returns: { ok, width_mm, current_a, delta_t_c, cross_section_mil2, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "current_a": {
                "type": "number",
                "description": "Required trace current [A].",
            },
            "copper_oz": {
                "type": "number",
                "description": "Copper weight [oz/ft²] (default 1.0).",
            },
            "delta_t_c": {
                "type": "number",
                "description": "Allowable temperature rise [°C] (default 10).",
            },
            "layer": {
                "type": "string",
                "enum": ["external", "internal"],
                "description": "'external' or 'internal' (default 'external').",
            },
            "k_pcb": {
                "type": "number",
                "description": "Board thermal conductivity [W/(m·K)] (default 0.25).",
            },
            "t_pcb_mm": {
                "type": "number",
                "description": "Board thickness [mm] (default 1.6).",
            },
            "h_plane_mm": {
                "type": "number",
                "description": "Distance to adjacent copper plane [mm] (optional).",
            },
        },
        "required": ["current_a"],
    },
)


@register(_REQ_WIDTH_SPEC, write=False)
async def tracecurrent_required_width(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = required_trace_width(
        current_a=a.get("current_a"),
        copper_oz=a.get("copper_oz", 1.0),
        delta_t_c=a.get("delta_t_c", 10.0),
        layer=a.get("layer", "external"),
        k_pcb=a.get("k_pcb", 0.25),
        t_pcb_mm=a.get("t_pcb_mm", 1.6),
        h_plane_mm=a.get("h_plane_mm"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. tracecurrent_resistance
# ═══════════════════════════════════════════════════════════════════════════════

_RESISTANCE_SPEC = ToolSpec(
    name="tracecurrent_resistance",
    description=(
        "PCB trace DC resistance [Ω], I²R power loss [W], and voltage drop [V].\n\n"
        "Model: R = ρ_Cu(T) × L / A\n"
        "  ρ_Cu(T) = 1.724e-8 × (1 + 3.93e-3 × (T − 20))  [Ω·m]  (IEC 60228)\n"
        "  A = width × thickness  (copper weight → thickness via 1 oz = 34.8 µm)\n\n"
        "Also returns sheet resistance Rs = ρ / t_Cu [Ω/□].\n\n"
        "A warning is issued when voltage drop > 10% of a nominal 3.3 V rail.\n\n"
        "Input: { width_mm, length_mm, copper_oz?, current_a?, temp_c? }\n"
        "Returns: { ok, resistance_ohm, power_w, voltage_drop_v, sheet_resistance_ohm_sq, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "width_mm": {
                "type": "number",
                "description": "Trace width [mm].",
            },
            "length_mm": {
                "type": "number",
                "description": "Trace length [mm].",
            },
            "copper_oz": {
                "type": "number",
                "description": "Copper weight [oz/ft²] (default 1.0 oz = 34.8 µm).",
            },
            "current_a": {
                "type": "number",
                "description": "Trace current [A] for I²R / V_drop calculation (default 1.0).",
            },
            "temp_c": {
                "type": "number",
                "description": "Operating temperature [°C] (default 25.0).",
            },
        },
        "required": ["width_mm", "length_mm"],
    },
)


@register(_RESISTANCE_SPEC, write=False)
async def tracecurrent_resistance(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = trace_resistance(
        width_mm=a.get("width_mm"),
        length_mm=a.get("length_mm"),
        copper_oz=a.get("copper_oz", 1.0),
        current_a=a.get("current_a", 1.0),
        temp_c=a.get("temp_c", 25.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. tracecurrent_via_capacity
# ═══════════════════════════════════════════════════════════════════════════════

_VIA_CAP_SPEC = ToolSpec(
    name="tracecurrent_via_capacity",
    description=(
        "IPC-2152 current capacity of a plated through-hole via barrel.\n\n"
        "Model: the barrel annulus is treated as a trace of effective width = π×drill_mm "
        "and thickness = plating_mm (same IPC-2152 curve as a trace).\n\n"
        "A warning is issued when plating < IPC-6012 Class 2 minimum (18 µm).\n\n"
        "Input: { drill_mm, plating_mm?, delta_t_c?, layer? }\n"
        "Returns: { ok, current_a, barrel_area_mil2, drill_mm, plating_mm, delta_t_c, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "drill_mm": {
                "type": "number",
                "description": "Via drill (finished bore) diameter [mm].",
            },
            "plating_mm": {
                "type": "number",
                "description": "Copper plating thickness [mm] (default 0.025 mm = 25 µm).",
            },
            "delta_t_c": {
                "type": "number",
                "description": "Allowable temperature rise [°C] (default 10).",
            },
            "layer": {
                "type": "string",
                "enum": ["external", "internal"],
                "description": "'external' or 'internal' (default 'internal').",
            },
        },
        "required": ["drill_mm"],
    },
)


@register(_VIA_CAP_SPEC, write=False)
async def tracecurrent_via_capacity(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = via_current_capacity(
        drill_mm=a.get("drill_mm"),
        plating_mm=a.get("plating_mm", 0.025),
        delta_t_c=a.get("delta_t_c", 10.0),
        layer=a.get("layer", "internal"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. tracecurrent_via_count
# ═══════════════════════════════════════════════════════════════════════════════

_VIA_COUNT_SPEC = ToolSpec(
    name="tracecurrent_via_count",
    description=(
        "Minimum number of parallel vias required to carry a given total current.\n\n"
        "Each via capacity is computed from the IPC-2152 barrel model.\n"
        "n_vias = ceil(total_current_a / current_per_via_a).\n\n"
        "A warning is issued when more than 20 vias are required.\n\n"
        "Input: { total_current_a, drill_mm, plating_mm?, delta_t_c?, layer? }\n"
        "Returns: { ok, n_vias, current_per_via_a, total_current_a, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "total_current_a": {
                "type": "number",
                "description": "Total current to be carried [A].",
            },
            "drill_mm": {
                "type": "number",
                "description": "Via drill diameter [mm].",
            },
            "plating_mm": {
                "type": "number",
                "description": "Copper plating thickness [mm] (default 0.025 mm).",
            },
            "delta_t_c": {
                "type": "number",
                "description": "Allowable temperature rise [°C] (default 10).",
            },
            "layer": {
                "type": "string",
                "enum": ["external", "internal"],
                "description": "'external' or 'internal' (default 'internal').",
            },
        },
        "required": ["total_current_a", "drill_mm"],
    },
)


@register(_VIA_COUNT_SPEC, write=False)
async def tracecurrent_via_count(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = required_via_count(
        total_current_a=a.get("total_current_a"),
        drill_mm=a.get("drill_mm"),
        plating_mm=a.get("plating_mm", 0.025),
        delta_t_c=a.get("delta_t_c", 10.0),
        layer=a.get("layer", "internal"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. tracecurrent_thermal_via
# ═══════════════════════════════════════════════════════════════════════════════

_THERMAL_VIA_SPEC = ToolSpec(
    name="tracecurrent_thermal_via",
    description=(
        "Thermal resistance and ΔT of a thermal-via array under a component pad "
        "(IPC-7093 parallel-barrel model).\n\n"
        "Model:\n"
        "  Each via: Rθ_each = t_pcb / (A_barrel × k_Cu)\n"
        "  Array:    Rθ_array = Rθ_each / n_vias\n"
        "  Spreading: Rθ_spread ≈ 1 / (4 × k_pcb × side_m)\n"
        "  Total:    Rθ_total = Rθ_array + Rθ_spread\n"
        "  ΔT = power_w × Rθ_total\n\n"
        "A warning is issued when ΔT > 15 K.\n\n"
        "Input: { n_vias, drill_mm, plating_mm?, t_pcb_mm?, k_pcb?, "
        "array_side_mm?, power_w? }\n"
        "Returns: { ok, rth_via_each_k_per_w, rth_array_k_per_w, rth_spread_k_per_w, "
        "rth_total_k_per_w, delta_t_k, n_vias, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n_vias": {
                "type": "integer",
                "description": "Number of thermal vias in the array.",
            },
            "drill_mm": {
                "type": "number",
                "description": "Via drill diameter [mm].",
            },
            "plating_mm": {
                "type": "number",
                "description": "Copper plating thickness [mm] (default 0.025 mm).",
            },
            "t_pcb_mm": {
                "type": "number",
                "description": "Board thickness [mm] (default 1.6).",
            },
            "k_pcb": {
                "type": "number",
                "description": "Board thermal conductivity [W/(m·K)] (default 0.25).",
            },
            "array_side_mm": {
                "type": "number",
                "description": "Side length of the square via-array footprint [mm] (default 3.0).",
            },
            "power_w": {
                "type": "number",
                "description": "Dissipated power through the via array [W] (default 1.0).",
            },
        },
        "required": ["n_vias", "drill_mm"],
    },
)


@register(_THERMAL_VIA_SPEC, write=False)
async def tracecurrent_thermal_via(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = thermal_via_array(
        n_vias=a.get("n_vias"),
        drill_mm=a.get("drill_mm"),
        plating_mm=a.get("plating_mm", 0.025),
        t_pcb_mm=a.get("t_pcb_mm", 1.6),
        k_pcb=a.get("k_pcb", 0.25),
        array_side_mm=a.get("array_side_mm", 3.0),
        power_w=a.get("power_w", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. tracecurrent_plane_rs
# ═══════════════════════════════════════════════════════════════════════════════

_PLANE_RS_SPEC = ToolSpec(
    name="tracecurrent_plane_rs",
    description=(
        "Copper-plane sheet resistance [Ω/□], optional current density, and "
        "Onderdonk fusing margin (cross-check reference).\n\n"
        "Rs = ρ_Cu(T) / t_Cu   [Ω/□]  (t_Cu from copper weight)\n\n"
        "When current_a and plane_width_mm are provided:\n"
        "  J [A/mm²] = I / (W × t)\n"
        "  Onderdonk fusing time [s] = (A_mil² / I²) × (log10((T_fuse−T_amb)/234+1) / 0.0297)\n"
        "  Note: Onderdonk is a cross-check reference only.  Use protection.protect "
        "for accurate fuse sizing.\n\n"
        "A warning is issued when Onderdonk predicts fusing in < 0.1 s.\n\n"
        "Input: { copper_oz?, temp_c?, current_a?, plane_width_mm?, ambient_c? }\n"
        "Returns: { ok, sheet_resistance_ohm_sq, thickness_mm, "
        "[current_density_a_mm2, onderdonk_fuse_time_s, fusing_margin_ok], warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "copper_oz": {
                "type": "number",
                "description": "Copper weight [oz/ft²] (default 1.0).",
            },
            "temp_c": {
                "type": "number",
                "description": "Operating temperature [°C] (default 25.0).",
            },
            "current_a": {
                "type": "number",
                "description": "Current [A] (optional; enables density and Onderdonk check).",
            },
            "plane_width_mm": {
                "type": "number",
                "description": "Plane (conductor) width [mm] (required when current_a is given).",
            },
            "ambient_c": {
                "type": "number",
                "description": "Ambient temperature [°C] for Onderdonk calculation (default 25.0).",
            },
        },
        "required": [],
    },
)


@register(_PLANE_RS_SPEC, write=False)
async def tracecurrent_plane_rs(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = plane_sheet_resistance(
        copper_oz=a.get("copper_oz", 1.0),
        temp_c=a.get("temp_c", 25.0),
        current_a=a.get("current_a"),
        plane_width_mm=a.get("plane_width_mm"),
        ambient_c=a.get("ambient_c", 25.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. tracecurrent_pour_area
# ═══════════════════════════════════════════════════════════════════════════════

_POUR_AREA_SPEC = ToolSpec(
    name="tracecurrent_pour_area",
    description=(
        "Required copper-pour (polygon heatsink) area [mm² / cm²] for a target "
        "PCB thermal resistance.\n\n"
        "Model (1-D conduction through substrate):\n"
        "  Rθ_plane = t_pcb / (A_pour × k_pcb)\n"
        "  → A_pour = t_pcb / (Rθ_target × k_pcb)\n\n"
        "This is a conservative (lower-bound) estimate; copper spreading in the "
        "plane reduces the actual Rθ further.\n\n"
        "A warning is issued when the required area exceeds 100 cm².\n\n"
        "Input: { rth_target_k_per_w, t_pcb_mm?, k_pcb? }\n"
        "Returns: { ok, area_mm2, area_cm2, side_mm, rth_target_k_per_w, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "rth_target_k_per_w": {
                "type": "number",
                "description": "Target thermal resistance [K/W] (or [°C/W], same unit).",
            },
            "t_pcb_mm": {
                "type": "number",
                "description": "Board thickness [mm] (default 1.6).",
            },
            "k_pcb": {
                "type": "number",
                "description": "Base-material thermal conductivity [W/(m·K)] (default 0.25).",
            },
        },
        "required": ["rth_target_k_per_w"],
    },
)


@register(_POUR_AREA_SPEC, write=False)
async def tracecurrent_pour_area(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = polygon_pour_heatsink_area(
        rth_target_k_per_w=a.get("rth_target_k_per_w"),
        t_pcb_mm=a.get("t_pcb_mm", 1.6),
        k_pcb=a.get("k_pcb", 0.25),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. tracecurrent_busbar
# ═══════════════════════════════════════════════════════════════════════════════

_BUSBAR_SPEC = ToolSpec(
    name="tracecurrent_busbar",
    description=(
        "Copper busbar width and resistance for a given current and current density.\n\n"
        "Width: W = I / (J_max × T)\n"
        "Resistance: R = ρ_Cu(T) × L / (W × T)\n\n"
        "Typical J_max values:\n"
        "  PCB busbars (short runs, forced air): 5–10 A/mm²\n"
        "  PCB busbars (long runs, natural conv): 3–5 A/mm²\n"
        "  Copper busbars in switchgear: 1.5–3 A/mm²\n\n"
        "Input: { current_a, thickness_mm?, j_max_a_mm2?, length_mm?, temp_c? }\n"
        "Returns: { ok, width_mm, cross_section_mm2, resistance_ohm, power_w, "
        "voltage_drop_v, current_density_a_mm2, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "current_a": {
                "type": "number",
                "description": "Busbar current [A].",
            },
            "thickness_mm": {
                "type": "number",
                "description": "Busbar thickness [mm] (default 2.0).",
            },
            "j_max_a_mm2": {
                "type": "number",
                "description": "Maximum allowable current density [A/mm²] (default 3.0).",
            },
            "length_mm": {
                "type": "number",
                "description": "Busbar length [mm] (default 100).",
            },
            "temp_c": {
                "type": "number",
                "description": "Operating temperature [°C] (default 25.0).",
            },
        },
        "required": ["current_a"],
    },
)


@register(_BUSBAR_SPEC, write=False)
async def tracecurrent_busbar(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = busbar_sizing(
        current_a=a.get("current_a"),
        thickness_mm=a.get("thickness_mm", 2.0),
        j_max_a_mm2=a.get("j_max_a_mm2", 3.0),
        length_mm=a.get("length_mm", 100.0),
        temp_c=a.get("temp_c", 25.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_IPC2152_SPEC.name,    _IPC2152_SPEC,    tracecurrent_ipc2152),
    (_REQ_WIDTH_SPEC.name,  _REQ_WIDTH_SPEC,  tracecurrent_required_width),
    (_RESISTANCE_SPEC.name, _RESISTANCE_SPEC, tracecurrent_resistance),
    (_VIA_CAP_SPEC.name,    _VIA_CAP_SPEC,    tracecurrent_via_capacity),
    (_VIA_COUNT_SPEC.name,  _VIA_COUNT_SPEC,  tracecurrent_via_count),
    (_THERMAL_VIA_SPEC.name, _THERMAL_VIA_SPEC, tracecurrent_thermal_via),
    (_PLANE_RS_SPEC.name,   _PLANE_RS_SPEC,   tracecurrent_plane_rs),
    (_POUR_AREA_SPEC.name,  _POUR_AREA_SPEC,  tracecurrent_pour_area),
    (_BUSBAR_SPEC.name,     _BUSBAR_SPEC,     tracecurrent_busbar),
]
