"""
Thermoelectric (Peltier TEC / Seebeck TEG) LLM tools.

Provides LLM-callable tools for:

  tec_figure_of_merit      — Z and ZT from α, R, K, T_mean
  tec_operating_point      — Qc, Qh, P, COP at given I, Tc, Th
  tec_optimal_current      — I_max_Qc and I_max_COP, COP_max
  tec_delta_t_max          — maximum achievable ΔT (Qc = 0 condition)
  tec_couples_required     — number of couples N for target Qc
  tec_heatsink_coupled     — closed-loop Th solve with heatsink Rθ
  tec_multistage           — cascade TEC for large ΔT
  teg_output               — TEG Voc, matched-load Pm, arbitrary load point
  teg_efficiency           — TEG ηmax vs Carnot, optimal load resistance
  teg_array                — TEG module array (Ns series × Np parallel)
  teg_fill_factor          — module fill factor and effective-Z note

All handlers follow the kerf never-raise contract: errors → {"ok": false, "reason": ...}.
Operating-limit violations are reported via warnings.warn (never raise).

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.thermoelectric.tec import (
    figure_of_merit,
    tec_couples_required,
    tec_delta_t_max,
    tec_heatsink_coupled,
    tec_multistage,
    tec_operating_point,
    tec_optimal_current,
    teg_array,
    teg_efficiency,
    teg_fill_factor,
    teg_output,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. tec_figure_of_merit
# ═══════════════════════════════════════════════════════════════════════════════

_TEC_ZOM_SPEC = ToolSpec(
    name="tec_figure_of_merit",
    description=(
        "Compute the thermoelectric figure of merit Z [1/K] and dimensionless ZT "
        "for a thermoelectric couple.\n\n"
        "Z = α² / (R · K)\n"
        "ZT = Z · T_mean   (requires t_mean)\n\n"
        "where:\n"
        "  α   — Seebeck coefficient [V/K]  (n+p couple pair total)\n"
        "  R   — electrical resistance of the couple [Ω]\n"
        "  K   — thermal conductance of the couple [W/K]\n"
        "  T   — mean absolute temperature [K]\n\n"
        "Input: { alpha, resistance, thermal_conductance, t_mean? }\n"
        "Returns: { ok, Z, ZT, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alpha": {
                "type": "number",
                "description": "Seebeck coefficient [V/K] of the couple (n+p pair total).",
            },
            "resistance": {
                "type": "number",
                "description": "Electrical resistance of the couple [Ω].",
            },
            "thermal_conductance": {
                "type": "number",
                "description": "Thermal conductance of the couple [W/K].",
            },
            "t_mean": {
                "type": "number",
                "description": "Mean absolute temperature [K] (required to compute ZT; optional for Z only).",
            },
        },
        "required": ["alpha", "resistance", "thermal_conductance"],
    },
)


@register(_TEC_ZOM_SPEC, write=False)
async def tec_figure_of_merit_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = figure_of_merit(
        alpha=a.get("alpha"),
        resistance=a.get("resistance"),
        thermal_conductance=a.get("thermal_conductance"),
        t_mean=a.get("t_mean"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. tec_operating_point
# ═══════════════════════════════════════════════════════════════════════════════

_TEC_OP_SPEC = ToolSpec(
    name="tec_operating_point",
    description=(
        "Compute the steady-state operating point of a Peltier TEC module.\n\n"
        "Equations (Goldsmid 2009 §4):\n"
        "  Qc = α·I·Tc − ½·I²·R − K·ΔT\n"
        "  Qh = α·I·Th + ½·I²·R − K·ΔT\n"
        "  P  = Qh − Qc\n"
        "  COP = Qc / P\n\n"
        "A warning is issued when Qc < 0 (module cannot pump heat at this point).\n\n"
        "Input: { alpha, resistance, thermal_conductance, current, tc, th }\n"
        "Returns: { ok, Qc, Qh, P_input, COP, delta_T, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alpha": {"type": "number", "description": "Seebeck coefficient [V/K]."},
            "resistance": {"type": "number", "description": "Module resistance [Ω]."},
            "thermal_conductance": {"type": "number", "description": "Module thermal conductance [W/K]."},
            "current": {"type": "number", "description": "Drive current [A]."},
            "tc": {"type": "number", "description": "Cold-side absolute temperature [K]."},
            "th": {"type": "number", "description": "Hot-side absolute temperature [K]."},
        },
        "required": ["alpha", "resistance", "thermal_conductance", "current", "tc", "th"],
    },
)


@register(_TEC_OP_SPEC, write=False)
async def tec_operating_point_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = tec_operating_point(
        alpha=a.get("alpha"),
        resistance=a.get("resistance"),
        thermal_conductance=a.get("thermal_conductance"),
        current=a.get("current"),
        tc=a.get("tc"),
        th=a.get("th"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. tec_optimal_current
# ═══════════════════════════════════════════════════════════════════════════════

_TEC_OPT_I_SPEC = ToolSpec(
    name="tec_optimal_current",
    description=(
        "Compute optimal drive currents for a Peltier TEC module.\n\n"
        "I_max_Qc  — current maximising cold-side heat pumping:\n"
        "  I_max_Qc = α·Tc / R\n\n"
        "I_max_COP — current maximising coefficient of performance (Ioffe 1957):\n"
        "  I_max_COP = α·ΔT / (R·(√(1+Z·Tmean) − 1))\n"
        "  COP_max   = (Tc/ΔT) · (M − Th/Tc) / (M + 1)\n"
        "  where M = √(1 + Z·Tmean)\n\n"
        "Input: { alpha, resistance, thermal_conductance, tc, th }\n"
        "Returns: { ok, I_max_Qc, Qc_at_I_max_Qc, I_max_COP, COP_max, Z, ZT_mean, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alpha": {"type": "number", "description": "Seebeck coefficient [V/K]."},
            "resistance": {"type": "number", "description": "Module resistance [Ω]."},
            "thermal_conductance": {"type": "number", "description": "Module thermal conductance [W/K]."},
            "tc": {"type": "number", "description": "Cold-side absolute temperature [K]."},
            "th": {"type": "number", "description": "Hot-side absolute temperature [K]."},
        },
        "required": ["alpha", "resistance", "thermal_conductance", "tc", "th"],
    },
)


@register(_TEC_OPT_I_SPEC, write=False)
async def tec_optimal_current_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = tec_optimal_current(
        alpha=a.get("alpha"),
        resistance=a.get("resistance"),
        thermal_conductance=a.get("thermal_conductance"),
        tc=a.get("tc"),
        th=a.get("th"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. tec_delta_t_max
# ═══════════════════════════════════════════════════════════════════════════════

_TEC_DTM_SPEC = ToolSpec(
    name="tec_delta_t_max",
    description=(
        "Compute the maximum achievable temperature difference (ΔT_max) of a "
        "single-stage TEC module at zero heat load.\n\n"
        "ΔT_max = ½ · Z · Tc²    where Z = α² / (R·K)\n"
        "Th_max  = Tc + ΔT_max\n\n"
        "This is the theoretical upper bound for a single-stage module with no "
        "cooling load on the cold side.\n\n"
        "Input: { alpha, resistance, thermal_conductance, tc }\n"
        "Returns: { ok, delta_T_max, Th_max, Z, tc }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alpha": {"type": "number", "description": "Seebeck coefficient [V/K]."},
            "resistance": {"type": "number", "description": "Module resistance [Ω]."},
            "thermal_conductance": {"type": "number", "description": "Module thermal conductance [W/K]."},
            "tc": {"type": "number", "description": "Cold-side absolute temperature [K]."},
        },
        "required": ["alpha", "resistance", "thermal_conductance", "tc"],
    },
)


@register(_TEC_DTM_SPEC, write=False)
async def tec_delta_t_max_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = tec_delta_t_max(
        alpha=a.get("alpha"),
        resistance=a.get("resistance"),
        thermal_conductance=a.get("thermal_conductance"),
        tc=a.get("tc"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. tec_couples_required
# ═══════════════════════════════════════════════════════════════════════════════

_TEC_COUPLES_SPEC = ToolSpec(
    name="tec_couples_required",
    description=(
        "Determine the minimum number of thermoelectric couples N needed to achieve "
        "a target cold-side heat pumping rate Qc_target [W].\n\n"
        "Scales Qc linearly with N:  Qc_total = N · Qc_per_couple.\n"
        "Returns N = ceil(Qc_target / Qc_per_couple).\n"
        "Issues a warning when Qc_per_couple ≤ 0 (impossible at this ΔT/current).\n\n"
        "Input: { alpha_per_couple, resistance_per_couple, "
        "thermal_conductance_per_couple, current, tc, th, Qc_target }\n"
        "Returns: { ok, N, Qc_per_couple, Qc_total, Qh_total, P_total, COP, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alpha_per_couple": {"type": "number", "description": "Seebeck coefficient per couple [V/K]."},
            "resistance_per_couple": {"type": "number", "description": "Resistance per couple [Ω]."},
            "thermal_conductance_per_couple": {"type": "number", "description": "Thermal conductance per couple [W/K]."},
            "current": {"type": "number", "description": "Drive current [A]."},
            "tc": {"type": "number", "description": "Cold-side temperature [K]."},
            "th": {"type": "number", "description": "Hot-side temperature [K]."},
            "Qc_target": {"type": "number", "description": "Required cold-side heat pumping [W]."},
        },
        "required": [
            "alpha_per_couple", "resistance_per_couple", "thermal_conductance_per_couple",
            "current", "tc", "th", "Qc_target",
        ],
    },
)


@register(_TEC_COUPLES_SPEC, write=False)
async def tec_couples_required_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = tec_couples_required(
        alpha_per_couple=a.get("alpha_per_couple"),
        resistance_per_couple=a.get("resistance_per_couple"),
        thermal_conductance_per_couple=a.get("thermal_conductance_per_couple"),
        current=a.get("current"),
        tc=a.get("tc"),
        th=a.get("th"),
        Qc_target=a.get("Qc_target"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. tec_heatsink_coupled
# ═══════════════════════════════════════════════════════════════════════════════

_TEC_HS_SPEC = ToolSpec(
    name="tec_heatsink_coupled",
    description=(
        "Solve for the hot-side temperature Th of a TEC coupled to a heatsink "
        "with thermal resistance Rθ [K/W] to ambient.\n\n"
        "Equilibrium:  Th = T_ambient + Rθ · Qh(Th)\n\n"
        "Solved by fixed-point iteration (up to 200 steps).\n"
        "Issues a warning when the iteration does not converge (heatsink undersized) "
        "or when Qc < 0 (negative heat pumping).\n\n"
        "Input: { alpha, resistance, thermal_conductance, current, tc, t_ambient, rtheta }\n"
        "Returns: { ok, Th, Qc, Qh, P_input, COP, delta_T, converged, iterations, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alpha": {"type": "number", "description": "Seebeck coefficient [V/K]."},
            "resistance": {"type": "number", "description": "Module resistance [Ω]."},
            "thermal_conductance": {"type": "number", "description": "Module thermal conductance [W/K]."},
            "current": {"type": "number", "description": "Drive current [A]."},
            "tc": {"type": "number", "description": "Cold-side (object) temperature [K]."},
            "t_ambient": {"type": "number", "description": "Ambient (heatsink inlet) temperature [K]."},
            "rtheta": {"type": "number", "description": "Heatsink thermal resistance [K/W]."},
        },
        "required": ["alpha", "resistance", "thermal_conductance", "current", "tc", "t_ambient", "rtheta"],
    },
)


@register(_TEC_HS_SPEC, write=False)
async def tec_heatsink_coupled_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = tec_heatsink_coupled(
        alpha=a.get("alpha"),
        resistance=a.get("resistance"),
        thermal_conductance=a.get("thermal_conductance"),
        current=a.get("current"),
        tc=a.get("tc"),
        t_ambient=a.get("t_ambient"),
        rtheta=a.get("rtheta"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. tec_multistage
# ═══════════════════════════════════════════════════════════════════════════════

_TEC_MS_SPEC = ToolSpec(
    name="tec_multistage",
    description=(
        "Design a multistage (cascade) TEC for large ΔT that exceeds a single "
        "module's ΔT_max.\n\n"
        "Each stage is described by its own parameters; the hot side of stage n "
        "feeds the cold side of stage n+1.  ΔT is distributed evenly among stages.\n\n"
        "Input: { stages: [{alpha, resistance, thermal_conductance, current}, ...], "
        "t_cold_target, t_hot_ambient }\n"
        "Returns: { ok, stages_results, total_delta_T, Tc_final, Th_final, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stages": {
                "type": "array",
                "description": "List of stage parameter dicts [{alpha, resistance, thermal_conductance, current}].",
                "items": {
                    "type": "object",
                    "properties": {
                        "alpha": {"type": "number"},
                        "resistance": {"type": "number"},
                        "thermal_conductance": {"type": "number"},
                        "current": {"type": "number"},
                    },
                    "required": ["alpha", "resistance", "thermal_conductance", "current"],
                },
            },
            "t_cold_target": {"type": "number", "description": "Desired cold-side temperature [K]."},
            "t_hot_ambient": {"type": "number", "description": "Hot-side ambient temperature [K]."},
        },
        "required": ["stages", "t_cold_target", "t_hot_ambient"],
    },
)


@register(_TEC_MS_SPEC, write=False)
async def tec_multistage_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = tec_multistage(
        stages=a.get("stages", []),
        t_cold_target=a.get("t_cold_target"),
        t_hot_ambient=a.get("t_hot_ambient"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. teg_output
# ═══════════════════════════════════════════════════════════════════════════════

_TEG_OUT_SPEC = ToolSpec(
    name="teg_output",
    description=(
        "Compute TEG (Seebeck generator) output: open-circuit voltage, "
        "matched-load power, current, voltage, and arbitrary-load operating point.\n\n"
        "Equations (Rowe 1995 §2; Goldsmid 2009 §5):\n"
        "  Voc = α·N·ΔT        — open-circuit voltage\n"
        "  Ri  = N·R            — internal resistance\n"
        "  Im  = Voc / (2·Ri)  — matched-load current  (R_load = Ri)\n"
        "  Pm  = Voc² / (4·Ri) — matched-load power\n\n"
        "Carnot efficiency: ηC = ΔT / Th\n\n"
        "Input: { alpha, resistance, n_couples, tc, th, r_load? }\n"
        "Returns: { ok, Voc, Ri, Im, Vm, Pm, I_load, V_load, P_load, eta_carnot, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alpha": {"type": "number", "description": "Seebeck coefficient per couple [V/K]."},
            "resistance": {"type": "number", "description": "Electrical resistance per couple [Ω]."},
            "n_couples": {"type": "integer", "description": "Number of thermoelectric couples."},
            "tc": {"type": "number", "description": "Cold-side temperature [K]."},
            "th": {"type": "number", "description": "Hot-side temperature [K]."},
            "r_load": {
                "type": "number",
                "description": "Load resistance [Ω]; omit for matched-load (R_load = Ri).",
            },
        },
        "required": ["alpha", "resistance", "n_couples", "tc", "th"],
    },
)


@register(_TEG_OUT_SPEC, write=False)
async def teg_output_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = teg_output(
        alpha=a.get("alpha"),
        resistance=a.get("resistance"),
        n_couples=a.get("n_couples"),
        tc=a.get("tc"),
        th=a.get("th"),
        r_load=a.get("r_load"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. teg_efficiency
# ═══════════════════════════════════════════════════════════════════════════════

_TEG_EFF_SPEC = ToolSpec(
    name="teg_efficiency",
    description=(
        "Compute TEG maximum efficiency and optimal load resistance for the max-η "
        "operating point.\n\n"
        "ηmax = (ΔT/Th) · (M − 1) / (M + Tc/Th)    (Ioffe / Goldsmid)\n"
        "ηC   = ΔT / Th                               (Carnot)\n"
        "M    = √(1 + Z·Tmean)\n"
        "R_opt = R · M   (per couple, for max-η)\n\n"
        "Input: { alpha, resistance, thermal_conductance, tc, th }\n"
        "Returns: { ok, eta_max, eta_carnot, eta_ratio, Z, ZT_mean, M, R_opt_per_couple, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alpha": {"type": "number", "description": "Seebeck coefficient per couple [V/K]."},
            "resistance": {"type": "number", "description": "Resistance per couple [Ω]."},
            "thermal_conductance": {"type": "number", "description": "Thermal conductance per couple [W/K]."},
            "tc": {"type": "number", "description": "Cold-side temperature [K]."},
            "th": {"type": "number", "description": "Hot-side temperature [K]."},
        },
        "required": ["alpha", "resistance", "thermal_conductance", "tc", "th"],
    },
)


@register(_TEG_EFF_SPEC, write=False)
async def teg_efficiency_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = teg_efficiency(
        alpha=a.get("alpha"),
        resistance=a.get("resistance"),
        thermal_conductance=a.get("thermal_conductance"),
        tc=a.get("tc"),
        th=a.get("th"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. teg_array
# ═══════════════════════════════════════════════════════════════════════════════

_TEG_ARRAY_SPEC = ToolSpec(
    name="teg_array",
    description=(
        "Compute output of a TEG module array with Ns modules in series and "
        "Np modules in parallel.\n\n"
        "Series increases voltage; parallel increases current:\n"
        "  Varray = Ns · Voc_module\n"
        "  Iarray = Np · Im_module\n"
        "  Parray = Ns · Np · Pm_module\n\n"
        "Input: { alpha, resistance, n_couples, tc, th, n_series, n_parallel }\n"
        "Returns: { ok, Varray, Iarray, Parray, n_total_modules, Voc_module, Pm_module, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alpha": {"type": "number", "description": "Seebeck coefficient per couple [V/K]."},
            "resistance": {"type": "number", "description": "Resistance per couple [Ω]."},
            "n_couples": {"type": "integer", "description": "Number of couples per module."},
            "tc": {"type": "number", "description": "Cold-side temperature [K]."},
            "th": {"type": "number", "description": "Hot-side temperature [K]."},
            "n_series": {"type": "integer", "description": "Number of modules in series (Ns)."},
            "n_parallel": {"type": "integer", "description": "Number of modules in parallel (Np)."},
        },
        "required": ["alpha", "resistance", "n_couples", "tc", "th", "n_series", "n_parallel"],
    },
)


@register(_TEG_ARRAY_SPEC, write=False)
async def teg_array_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = teg_array(
        alpha=a.get("alpha"),
        resistance=a.get("resistance"),
        n_couples=a.get("n_couples"),
        tc=a.get("tc"),
        th=a.get("th"),
        n_series=a.get("n_series"),
        n_parallel=a.get("n_parallel"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. teg_fill_factor
# ═══════════════════════════════════════════════════════════════════════════════

_TEG_FF_SPEC = ToolSpec(
    name="teg_fill_factor",
    description=(
        "Compute the fill factor of a TEG module.\n\n"
        "FF = (total pellet cross-section area) / (module footprint area)\n\n"
        "A higher FF means more active thermoelectric area and higher effective Z. "
        "Warns if FF > 1 (geometry inputs inconsistent).\n\n"
        "Input: { pellet_area_mm2, pellet_height_mm, n_couples, module_footprint_mm2 }\n"
        "Returns: { ok, fill_factor, total_pellet_area_mm2, n_legs, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pellet_area_mm2": {"type": "number", "description": "Cross-section area of one pellet leg [mm²]."},
            "pellet_height_mm": {"type": "number", "description": "Pellet height (leg length) [mm]."},
            "n_couples": {"type": "integer", "description": "Number of couples (n + p leg pairs)."},
            "module_footprint_mm2": {"type": "number", "description": "Module footprint area [mm²]."},
        },
        "required": ["pellet_area_mm2", "pellet_height_mm", "n_couples", "module_footprint_mm2"],
    },
)


@register(_TEG_FF_SPEC, write=False)
async def teg_fill_factor_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = teg_fill_factor(
        pellet_area_mm2=a.get("pellet_area_mm2"),
        pellet_height_mm=a.get("pellet_height_mm"),
        n_couples=a.get("n_couples"),
        module_footprint_mm2=a.get("module_footprint_mm2"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_TEC_ZOM_SPEC.name,     _TEC_ZOM_SPEC,     tec_figure_of_merit_tool),
    (_TEC_OP_SPEC.name,      _TEC_OP_SPEC,      tec_operating_point_tool),
    (_TEC_OPT_I_SPEC.name,   _TEC_OPT_I_SPEC,   tec_optimal_current_tool),
    (_TEC_DTM_SPEC.name,     _TEC_DTM_SPEC,     tec_delta_t_max_tool),
    (_TEC_COUPLES_SPEC.name, _TEC_COUPLES_SPEC, tec_couples_required_tool),
    (_TEC_HS_SPEC.name,      _TEC_HS_SPEC,      tec_heatsink_coupled_tool),
    (_TEC_MS_SPEC.name,      _TEC_MS_SPEC,      tec_multistage_tool),
    (_TEG_OUT_SPEC.name,     _TEG_OUT_SPEC,     teg_output_tool),
    (_TEG_EFF_SPEC.name,     _TEG_EFF_SPEC,     teg_efficiency_tool),
    (_TEG_ARRAY_SPEC.name,   _TEG_ARRAY_SPEC,   teg_array_tool),
    (_TEG_FF_SPEC.name,      _TEG_FF_SPEC,      teg_fill_factor_tool),
]
