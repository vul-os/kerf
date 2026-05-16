"""
kerf_cad_core.vacuum.tools — LLM tool wrappers for vacuum-system design.

Registers tools with the Kerf tool registry:

  vacuum_flow_regime          — Knudsen number & flow regime classification
  vacuum_conductance_orifice  — thin circular orifice conductance
  vacuum_conductance_tube     — long circular tube conductance (all regimes)
  vacuum_conductance_series   — 1/C_total = Σ 1/C_i
  vacuum_conductance_parallel — C_total = Σ C_i
  vacuum_effective_speed      — 1/S_eff = 1/S_pump + 1/C
  vacuum_pump_down_time       — two-phase volume + outgassing pump-down model
  vacuum_ultimate_pressure    — P_ult = Q_gas / S_pump
  vacuum_gas_throughput       — Q = S · P
  vacuum_outgassing_rate      — Q_out = q · A
  vacuum_leak_rate_spec       — rate-of-rise leak-rate calculation
  vacuum_rate_of_rise         — predict pressure rise during isolation test
  vacuum_mean_free_path       — λ = k_B·T / (√2·π·d²·P)
  vacuum_monolayer_time       — monolayer formation time on a surface
  vacuum_pump_stage_match     — roughing + high-vac crossover matching

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
O'Hanlon, J.F., "A User's Guide to Vacuum Technology", 3rd ed., Wiley (2003).
Jousten, K. (ed.), "Handbook of Vacuum Technology", Wiley-VCH (2016).

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.vacuum.system import (
    flow_regime,
    conductance_orifice,
    conductance_tube,
    conductance_series,
    conductance_parallel,
    effective_pumping_speed,
    pump_down_time,
    ultimate_pressure,
    gas_throughput,
    outgassing_rate,
    leak_rate_spec,
    rate_of_rise,
    mean_free_path,
    monolayer_time,
    pump_stage_match,
)


# ---------------------------------------------------------------------------
# Tool: vacuum_flow_regime
# ---------------------------------------------------------------------------

_flow_regime_spec = ToolSpec(
    name="vacuum_flow_regime",
    description=(
        "Determine the vacuum flow regime (viscous / transitional / molecular) "
        "from the Knudsen number.\n"
        "\n"
        "Kn = λ / D  where λ = k_B·T / (√2·π·d_mol²·P)\n"
        "\n"
        "Regimes:\n"
        "  Kn < 0.01  → viscous (continuum / hydrodynamic)\n"
        "  0.01–0.5   → transitional (Knudsen)\n"
        "  Kn > 0.5   → molecular (free-molecular)\n"
        "\n"
        "Returns Kn, mean free path, and regime string.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pressure_Pa": {
                "type": "number",
                "description": "Gas pressure (Pa). Must be > 0.",
            },
            "diameter_m": {
                "type": "number",
                "description": "Characteristic geometry diameter (m). Must be > 0.",
            },
            "temperature_K": {
                "type": "number",
                "description": "Gas temperature (K). Default 293.15 (20°C).",
            },
        },
        "required": ["pressure_Pa", "diameter_m"],
    },
)


@register(_flow_regime_spec, write=False)
async def run_flow_regime(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("pressure_Pa") is None:
        return json.dumps({"ok": False, "reason": "pressure_Pa is required"})
    if a.get("diameter_m") is None:
        return json.dumps({"ok": False, "reason": "diameter_m is required"})

    kwargs: dict = {}
    if "temperature_K" in a:
        kwargs["temperature_K"] = a["temperature_K"]

    result = flow_regime(a["pressure_Pa"], a["diameter_m"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_conductance_orifice
# ---------------------------------------------------------------------------

_conductance_orifice_spec = ToolSpec(
    name="vacuum_conductance_orifice",
    description=(
        "Conductance of a thin circular orifice.\n"
        "\n"
        "Molecular regime (Kn > 0.5):  C = A · v_avg / 4\n"
        "Viscous regime (Kn < 0.01):   C = C_mol + viscous pressure increment\n"
        "Transitional:                 interpolated between molecular and viscous\n"
        "\n"
        "Returns C_m3s (m³/s), regime_used, Kn, and area_m2.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "diameter_m": {
                "type": "number",
                "description": "Orifice diameter (m). Must be > 0.",
            },
            "pressure_Pa": {
                "type": "number",
                "description": "Mean pressure at orifice (Pa). Must be > 0.",
            },
            "temperature_K": {
                "type": "number",
                "description": "Temperature (K). Default 293.15.",
            },
            "regime": {
                "type": "string",
                "enum": ["auto", "molecular", "viscous", "transitional"],
                "description": "Force regime or use 'auto' (default).",
            },
        },
        "required": ["diameter_m", "pressure_Pa"],
    },
)


@register(_conductance_orifice_spec, write=False)
async def run_conductance_orifice(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("diameter_m") is None:
        return json.dumps({"ok": False, "reason": "diameter_m is required"})
    if a.get("pressure_Pa") is None:
        return json.dumps({"ok": False, "reason": "pressure_Pa is required"})

    kwargs: dict = {}
    if "temperature_K" in a:
        kwargs["temperature_K"] = a["temperature_K"]
    if "regime" in a:
        kwargs["regime"] = a["regime"]

    result = conductance_orifice(a["diameter_m"], a["pressure_Pa"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_conductance_tube
# ---------------------------------------------------------------------------

_conductance_tube_spec = ToolSpec(
    name="vacuum_conductance_tube",
    description=(
        "Conductance of a long circular tube (L >> D).\n"
        "\n"
        "Molecular: C = (π/12)·v_avg·D³/L           (Knudsen 1909)\n"
        "Viscous:   C = (π·D⁴·P_avg) / (128·η·L)   (Poiseuille)\n"
        "Transitional: interpolated between regimes.\n"
        "\n"
        "Returns C_m3s, C_mol_m3s, C_vis_m3s, Kn, and regime_used.\n"
        "Warns if L/D < 3 (short-tube approximation may be inaccurate).\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "diameter_m": {
                "type": "number",
                "description": "Inner tube diameter (m). Must be > 0.",
            },
            "length_m": {
                "type": "number",
                "description": "Tube length (m). Must be > 0.",
            },
            "pressure_Pa": {
                "type": "number",
                "description": "Mean pressure (Pa). Must be > 0.",
            },
            "temperature_K": {
                "type": "number",
                "description": "Temperature (K). Default 293.15.",
            },
            "regime": {
                "type": "string",
                "enum": ["auto", "molecular", "viscous", "transitional"],
                "description": "Force regime or use 'auto' (default).",
            },
        },
        "required": ["diameter_m", "length_m", "pressure_Pa"],
    },
)


@register(_conductance_tube_spec, write=False)
async def run_conductance_tube(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("diameter_m", "length_m", "pressure_Pa"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "temperature_K" in a:
        kwargs["temperature_K"] = a["temperature_K"]
    if "regime" in a:
        kwargs["regime"] = a["regime"]

    result = conductance_tube(
        a["diameter_m"], a["length_m"], a["pressure_Pa"], **kwargs
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_conductance_series
# ---------------------------------------------------------------------------

_conductance_series_spec = ToolSpec(
    name="vacuum_conductance_series",
    description=(
        "Equivalent conductance of vacuum components in series.\n"
        "\n"
        "1/C_total = Σ (1/C_i)\n"
        "\n"
        "Returns C_total_m3s (m³/s).\n"
        "Warns if any single element creates a severe conductance bottleneck.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "conductances": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "List of individual conductance values (m³/s). "
                    "All must be > 0. At least 1 element."
                ),
            },
        },
        "required": ["conductances"],
    },
)


@register(_conductance_series_spec, write=False)
async def run_conductance_series(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("conductances") is None:
        return json.dumps({"ok": False, "reason": "conductances is required"})

    result = conductance_series(a["conductances"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_conductance_parallel
# ---------------------------------------------------------------------------

_conductance_parallel_spec = ToolSpec(
    name="vacuum_conductance_parallel",
    description=(
        "Equivalent conductance of vacuum components in parallel.\n"
        "\n"
        "C_total = Σ C_i\n"
        "\n"
        "Returns C_total_m3s (m³/s).\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "conductances": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "List of individual conductance values (m³/s). "
                    "All must be > 0. At least 1 element."
                ),
            },
        },
        "required": ["conductances"],
    },
)


@register(_conductance_parallel_spec, write=False)
async def run_conductance_parallel(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("conductances") is None:
        return json.dumps({"ok": False, "reason": "conductances is required"})

    result = conductance_parallel(a["conductances"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_effective_speed
# ---------------------------------------------------------------------------

_effective_speed_spec = ToolSpec(
    name="vacuum_effective_speed",
    description=(
        "Effective pumping speed at the vacuum chamber.\n"
        "\n"
        "1/S_eff = 1/S_pump + 1/C\n"
        "\n"
        "The pump and connecting conductance act in series.  S_eff is always "
        "less than both S_pump and C.\n"
        "\n"
        "Returns S_eff_m3s and S_eff_frac (fraction of pump speed).\n"
        "Warns if S_eff < 50% of S_pump (conductance is the bottleneck).\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "S_pump_m3s": {
                "type": "number",
                "description": "Pump speed at pump inlet (m³/s). Must be > 0.",
            },
            "C_m3s": {
                "type": "number",
                "description": (
                    "Total conductance of connecting plumbing (m³/s). Must be > 0. "
                    "Use vacuum_conductance_series/parallel to combine multiple elements."
                ),
            },
        },
        "required": ["S_pump_m3s", "C_m3s"],
    },
)


@register(_effective_speed_spec, write=False)
async def run_effective_speed(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("S_pump_m3s", "C_m3s"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = effective_pumping_speed(a["S_pump_m3s"], a["C_m3s"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_pump_down_time
# ---------------------------------------------------------------------------

_pump_down_time_spec = ToolSpec(
    name="vacuum_pump_down_time",
    description=(
        "Estimate pump-down time using a two-phase model.\n"
        "\n"
        "Phase 1 (volume-limited):  t₁ = (V/S)·ln(P_start/P_crossover)\n"
        "Phase 2 (outgassing):      t₂ = (V/S)·ln((P_cross−P_ult)/(P_target−P_ult))\n"
        "\n"
        "If P_target ≤ P_ultimate (set by gas load), the target is unreachable "
        "and a warning is issued (t₂ = inf).\n"
        "\n"
        "Returns t_phase1_s, t_phase2_s, t_total_s, P_ult_Pa, P_crossover_Pa.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "volume_m3": {
                "type": "number",
                "description": "Chamber volume (m³). Must be > 0.",
            },
            "S_eff_m3s": {
                "type": "number",
                "description": "Effective pumping speed at chamber (m³/s). Must be > 0.",
            },
            "P_start_Pa": {
                "type": "number",
                "description": "Starting pressure (Pa). Must be > P_target.",
            },
            "P_target_Pa": {
                "type": "number",
                "description": "Target pressure (Pa). Must be > 0.",
            },
            "outgassing_load_Pa_m3s": {
                "type": "number",
                "description": (
                    "Fixed gas load from leaks/permeation (Pa·m³/s). Default 0."
                ),
            },
            "surface_area_m2": {
                "type": "number",
                "description": "Internal surface area with outgassing (m²). Default 0.",
            },
            "outgassing_rate_Pa_m3s_m2": {
                "type": "number",
                "description": (
                    "Specific outgassing rate (Pa·m³/(s·m²)). Default 0. "
                    "Typical: SS unbaked ~1×10⁻⁶, baked ~1×10⁻⁸."
                ),
            },
        },
        "required": ["volume_m3", "S_eff_m3s", "P_start_Pa", "P_target_Pa"],
    },
)


@register(_pump_down_time_spec, write=False)
async def run_pump_down_time(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("volume_m3", "S_eff_m3s", "P_start_Pa", "P_target_Pa"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    for opt in ("outgassing_load_Pa_m3s", "surface_area_m2", "outgassing_rate_Pa_m3s_m2"):
        if opt in a:
            kwargs[opt] = a[opt]

    result = pump_down_time(
        a["volume_m3"], a["S_eff_m3s"], a["P_start_Pa"], a["P_target_Pa"],
        **kwargs,
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_ultimate_pressure
# ---------------------------------------------------------------------------

_ultimate_pressure_spec = ToolSpec(
    name="vacuum_ultimate_pressure",
    description=(
        "Calculate ultimate (base) pressure from gas load and pump speed.\n"
        "\n"
        "P_ult = Q_gas / S_pump\n"
        "\n"
        "At steady state, the pump removes gas at the same rate it enters.\n"
        "\n"
        "Returns P_ult_Pa (Pa).\n"
        "Warns if P_ult > 1×10⁻³ Pa (rough-vacuum range for HV applications).\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q_gas_Pa_m3s": {
                "type": "number",
                "description": (
                    "Total gas load: outgassing + leaks + permeation (Pa·m³/s). "
                    "Must be > 0."
                ),
            },
            "S_pump_m3s": {
                "type": "number",
                "description": "Pumping speed at chamber (m³/s). Must be > 0.",
            },
        },
        "required": ["Q_gas_Pa_m3s", "S_pump_m3s"],
    },
)


@register(_ultimate_pressure_spec, write=False)
async def run_ultimate_pressure(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q_gas_Pa_m3s", "S_pump_m3s"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = ultimate_pressure(a["Q_gas_Pa_m3s"], a["S_pump_m3s"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_gas_throughput
# ---------------------------------------------------------------------------

_gas_throughput_spec = ToolSpec(
    name="vacuum_gas_throughput",
    description=(
        "Calculate gas throughput Q = S · P.\n"
        "\n"
        "Throughput is the amount of gas (in pressure-volume units) flowing "
        "per unit time through a cross-section at pressure P.\n"
        "\n"
        "Returns Q_Pa_m3s (Pa·m³/s).\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "S_m3s": {
                "type": "number",
                "description": "Pumping speed (m³/s). Must be > 0.",
            },
            "P_Pa": {
                "type": "number",
                "description": "Pressure at the measurement point (Pa). Must be > 0.",
            },
        },
        "required": ["S_m3s", "P_Pa"],
    },
)


@register(_gas_throughput_spec, write=False)
async def run_gas_throughput(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("S_m3s", "P_Pa"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = gas_throughput(a["S_m3s"], a["P_Pa"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_outgassing_rate
# ---------------------------------------------------------------------------

_outgassing_rate_spec = ToolSpec(
    name="vacuum_outgassing_rate",
    description=(
        "Calculate total outgassing load from an internal surface.\n"
        "\n"
        "Q_out = q_specific · A\n"
        "\n"
        "Typical specific outgassing rates (Pa·m³/(s·m²)):\n"
        "  Stainless steel, unbaked 1 h : ~1×10⁻⁶\n"
        "  Stainless steel, baked 150°C : ~1×10⁻⁸\n"
        "  Aluminium, unbaked            : ~3×10⁻⁷\n"
        "  Viton O-ring, unbaked         : ~1×10⁻⁵\n"
        "\n"
        "Returns Q_outgassing_Pa_m3s (Pa·m³/s).\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "area_m2": {
                "type": "number",
                "description": "Total internal surface area (m²). Must be > 0.",
            },
            "specific_rate_Pa_m3s_m2": {
                "type": "number",
                "description": (
                    "Specific outgassing rate (Pa·m³/(s·m²)). Must be > 0. "
                    "SS unbaked: ~1e-6; SS baked: ~1e-8."
                ),
            },
        },
        "required": ["area_m2", "specific_rate_Pa_m3s_m2"],
    },
)


@register(_outgassing_rate_spec, write=False)
async def run_outgassing_rate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("area_m2", "specific_rate_Pa_m3s_m2"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = outgassing_rate(a["area_m2"], a["specific_rate_Pa_m3s_m2"])
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_leak_rate_spec
# ---------------------------------------------------------------------------

_leak_rate_spec_spec = ToolSpec(
    name="vacuum_leak_rate_spec",
    description=(
        "Calculate system leak rate from a rate-of-rise (pressure-rise) test.\n"
        "\n"
        "Q_leak = V · (dP/dt)\n"
        "\n"
        "Returns the measured leak rate, helium-equivalent value, and "
        "leak class (ultra_fine / fine / gross / very_gross).\n"
        "Warns if leak rate exceeds the fine-vacuum threshold.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "P_test_Pa": {
                "type": "number",
                "description": "Test pressure at time of test (Pa). Must be > 0.",
            },
            "volume_m3": {
                "type": "number",
                "description": "System volume (m³). Must be > 0.",
            },
            "dp_dt_Pa_s": {
                "type": "number",
                "description": "Measured pressure rise rate (Pa/s). Must be > 0.",
            },
            "test_gas": {
                "type": "string",
                "enum": ["air", "nitrogen", "helium"],
                "description": "Test gas (default 'air').",
            },
        },
        "required": ["P_test_Pa", "volume_m3", "dp_dt_Pa_s"],
    },
)


@register(_leak_rate_spec_spec, write=False)
async def run_leak_rate_spec(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("P_test_Pa", "volume_m3", "dp_dt_Pa_s"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "test_gas" in a:
        kwargs["test_gas"] = a["test_gas"]

    result = leak_rate_spec(a["P_test_Pa"], a["volume_m3"], a["dp_dt_Pa_s"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_rate_of_rise
# ---------------------------------------------------------------------------

_rate_of_rise_spec = ToolSpec(
    name="vacuum_rate_of_rise",
    description=(
        "Predict the pressure rise during an isolated rate-of-rise test.\n"
        "\n"
        "With pump isolated and constant gas load Q:\n"
        "  P(t) = P_initial + (Q/V) · t\n"
        "\n"
        "Returns dP_dt_Pa_s, P_final_Pa, and delta_P_Pa.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "Q_leak_Pa_m3s": {
                "type": "number",
                "description": "Total gas load (leak + outgassing) (Pa·m³/s). Must be > 0.",
            },
            "volume_m3": {
                "type": "number",
                "description": "System volume (m³). Must be > 0.",
            },
            "time_s": {
                "type": "number",
                "description": "Test duration (s). Must be > 0.",
            },
            "P_initial_Pa": {
                "type": "number",
                "description": "Pressure at start of isolation (Pa). Must be > 0.",
            },
        },
        "required": ["Q_leak_Pa_m3s", "volume_m3", "time_s", "P_initial_Pa"],
    },
)


@register(_rate_of_rise_spec, write=False)
async def run_rate_of_rise(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in ("Q_leak_Pa_m3s", "volume_m3", "time_s", "P_initial_Pa"):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    result = rate_of_rise(
        a["Q_leak_Pa_m3s"], a["volume_m3"], a["time_s"], a["P_initial_Pa"]
    )
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_mean_free_path
# ---------------------------------------------------------------------------

_mean_free_path_spec = ToolSpec(
    name="vacuum_mean_free_path",
    description=(
        "Calculate the mean free path of gas molecules.\n"
        "\n"
        "λ = k_B · T / (√2 · π · d_mol² · P)\n"
        "\n"
        "Returns mfp_m (m), v_avg_m_s, and n_density (molecules/m³).\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pressure_Pa": {
                "type": "number",
                "description": "Gas pressure (Pa). Must be > 0.",
            },
            "temperature_K": {
                "type": "number",
                "description": "Temperature (K). Default 293.15.",
            },
        },
        "required": ["pressure_Pa"],
    },
)


@register(_mean_free_path_spec, write=False)
async def run_mean_free_path(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("pressure_Pa") is None:
        return json.dumps({"ok": False, "reason": "pressure_Pa is required"})

    kwargs: dict = {}
    if "temperature_K" in a:
        kwargs["temperature_K"] = a["temperature_K"]

    result = mean_free_path(a["pressure_Pa"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_monolayer_time
# ---------------------------------------------------------------------------

_monolayer_time_spec = ToolSpec(
    name="vacuum_monolayer_time",
    description=(
        "Time to form one monolayer of adsorbate on a clean surface.\n"
        "\n"
        "τ = n_s / (Φ · s)\n"
        "Φ = P / √(2·π·m·k_B·T)  [molecular flux, molecules/(m²·s)]\n"
        "\n"
        "At 1×10⁻⁶ Pa (HV), a monolayer forms in ~1 s (N₂).\n"
        "At 1×10⁻¹⁰ Pa (UHV), monolayer time > 10 h.\n"
        "\n"
        "Returns tau_s and flux_m2s.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pressure_Pa": {
                "type": "number",
                "description": "Gas pressure (Pa). Must be > 0.",
            },
            "temperature_K": {
                "type": "number",
                "description": "Temperature (K). Default 293.15.",
            },
            "sticking_coefficient": {
                "type": "number",
                "description": "Fraction of impinging molecules that adsorb (0–1]. Default 1.0.",
            },
        },
        "required": ["pressure_Pa"],
    },
)


@register(_monolayer_time_spec, write=False)
async def run_monolayer_time(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if a.get("pressure_Pa") is None:
        return json.dumps({"ok": False, "reason": "pressure_Pa is required"})

    kwargs: dict = {}
    if "temperature_K" in a:
        kwargs["temperature_K"] = a["temperature_K"]
    if "sticking_coefficient" in a:
        kwargs["sticking_coefficient"] = a["sticking_coefficient"]

    result = monolayer_time(a["pressure_Pa"], **kwargs)
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: vacuum_pump_stage_match
# ---------------------------------------------------------------------------

_pump_stage_match_spec = ToolSpec(
    name="vacuum_pump_stage_match",
    description=(
        "Match a multi-stage vacuum system: roughing + high-vacuum crossover.\n"
        "\n"
        "Computes:\n"
        "  • Auto-selected crossover pressure (or validates user-supplied)\n"
        "  • Roughing pump-down time (atmospheric → crossover)\n"
        "  • High-vac pump-down time (crossover → HV ultimate)\n"
        "  • Whether the crossover is safely within HV pump spec (< 1 Pa)\n"
        "\n"
        "Warns if the roughing pump cannot reach crossover, or if crossover "
        "pressure exceeds typical HV pump max inlet.\n"
        "Errors: {ok:false, reason} for invalid inputs.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "roughing_speed_m3s": {
                "type": "number",
                "description": "Roughing pump speed (m³/s). Must be > 0.",
            },
            "roughing_base_Pa": {
                "type": "number",
                "description": "Roughing pump ultimate pressure (Pa). Must be > 0. Typically 0.1–10 Pa.",
            },
            "highvac_speed_m3s": {
                "type": "number",
                "description": "High-vacuum pump speed at inlet (m³/s). Must be > 0.",
            },
            "highvac_base_Pa": {
                "type": "number",
                "description": "HV pump ultimate pressure (Pa). Must be > 0. Turbomolecular: ~10⁻⁸–10⁻¹⁰ Pa.",
            },
            "volume_m3": {
                "type": "number",
                "description": "Chamber volume (m³). Must be > 0.",
            },
            "crossover_P_Pa": {
                "type": "number",
                "description": (
                    "Crossover pressure (Pa). If omitted, auto-selected "
                    "(10× roughing base or 1 Pa, whichever is lower)."
                ),
            },
        },
        "required": [
            "roughing_speed_m3s",
            "roughing_base_Pa",
            "highvac_speed_m3s",
            "highvac_base_Pa",
            "volume_m3",
        ],
    },
)


@register(_pump_stage_match_spec, write=False)
async def run_pump_stage_match(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    for field in (
        "roughing_speed_m3s",
        "roughing_base_Pa",
        "highvac_speed_m3s",
        "highvac_base_Pa",
        "volume_m3",
    ):
        if a.get(field) is None:
            return json.dumps({"ok": False, "reason": f"{field} is required"})

    kwargs: dict = {}
    if "crossover_P_Pa" in a:
        kwargs["crossover_P_Pa"] = a["crossover_P_Pa"]

    result = pump_stage_match(
        a["roughing_speed_m3s"],
        a["roughing_base_Pa"],
        a["highvac_speed_m3s"],
        a["highvac_base_Pa"],
        a["volume_m3"],
        **kwargs,
    )
    return ok_payload(result)
