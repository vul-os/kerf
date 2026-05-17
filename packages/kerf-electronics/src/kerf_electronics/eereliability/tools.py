"""
Electronics reliability prediction tools.

Provides LLM-callable tools:

  eerel_mil217f_parts_count   — MIL-HDBK-217F parts-count (λ = Σ Ni·λg·πQ·πE)
  eerel_mil217f_part_stress   — MIL-HDBK-217F part-stress (πT, πS, πE, πQ, πA)
  eerel_board_fit_mtbf        — Aggregate part-stress → board FIT & MTBF
  eerel_arrhenius_af          — Arrhenius acceleration factor & activation energy
  eerel_coffin_manson         — Thermal-cycling solder-joint fatigue (Coffin-Manson Nf)
  eerel_peck_humidity         — Humidity + temperature acceleration (Peck model)
  eerel_voltage_acceleration  — Voltage acceleration factor (inverse power law)
  eerel_derating_check        — Derating-curve check (voltage/power/temp) per category
  eerel_bathtub               — Bathtub λ(t) hazard rate
  eerel_redundancy_mtbf       — Redundancy MTBF (active/standby with switch reliability)
  eerel_mtbf_confidence       — Chi-square MTBF confidence bound from demo test
  eerel_duty_cycle_fit        — Duty-cycle & power-on-hours adjusted FIT

All handlers follow the kerf never-raise contract: errors → {"ok": false, "reason": ...}.
Over-stress / very-low-MTBF conditions are flagged via warnings.warn (never raise).
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.eereliability.predict import (
    arrhenius_acceleration_factor,
    bathtub_hazard_rate,
    board_fit_and_mtbf,
    coffin_manson_nf,
    derating_check,
    duty_cycle_adjusted_fit,
    mil217f_part_stress,
    mil217f_parts_count,
    mtbf_confidence_bound,
    peck_humidity_acceleration,
    redundancy_mtbf,
    voltage_acceleration,
)

# ── shared part-type enum (kept in one place) ─────────────────────────────────
_PART_TYPES = [
    "resistor", "capacitor", "ic_digital", "ic_linear", "ic_memory",
    "transistor_bjt", "transistor_fet", "diode_signal", "diode_zener",
    "connector", "inductor", "transformer", "crystal", "relay", "switch",
    "solder_joint",
]
_ENV_CODES = [
    "GB", "GF", "GM", "NS", "NU", "AIC", "AIF", "AUC", "AUF",
    "ARW", "SF", "MF", "ML", "CL",
]
_QUALITY_LEVELS = ["S", "B", "B-1", "C", "D", "commercial", "lower"]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. eerel_mil217f_parts_count
# ═══════════════════════════════════════════════════════════════════════════════

_PARTS_COUNT_SPEC = ToolSpec(
    name="eerel_mil217f_parts_count",
    description=(
        "MIL-HDBK-217F parts-count reliability prediction for a PCB.\n\n"
        "Computes: λ_pred = Σ Ni · λg · πQ · πE\n\n"
        "Each entry in `parts` must have `type` and optionally `count` (default 1) "
        "and `quality` (overrides board-level default).\n\n"
        "Returns board FIT and MTBF (hours); warns if MTBF < 1 000 h.\n\n"
        "Note: Telcordia SR-332 Method I/II (black-box, vendor burn-in data) "
        "requires λ_SS and burn-in hours not computable purely analytically.\n\n"
        "Input: { parts, environment?, quality? }\n"
        "Returns: { ok, fit_total, mtbf_hours, part_breakdown, warnings, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "parts": {
                "type": "array",
                "description": (
                    "List of part dicts: {type, count?, quality?}. "
                    f"Valid types: {_PART_TYPES}."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": _PART_TYPES},
                        "count": {"type": "integer", "minimum": 1},
                        "quality": {"type": "string", "enum": _QUALITY_LEVELS},
                    },
                    "required": ["type"],
                },
            },
            "environment": {
                "type": "string",
                "enum": _ENV_CODES,
                "description": "MIL-217F environment code (default GF = Ground Fixed).",
            },
            "quality": {
                "type": "string",
                "enum": _QUALITY_LEVELS,
                "description": "Default board-level quality (default 'commercial').",
            },
        },
        "required": ["parts"],
    },
)


@register(_PARTS_COUNT_SPEC, write=False)
async def eerel_mil217f_parts_count(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = mil217f_parts_count(
        parts=a.get("parts", []),
        environment=a.get("environment", "GF"),
        quality=a.get("quality", "commercial"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. eerel_mil217f_part_stress
# ═══════════════════════════════════════════════════════════════════════════════

_PART_STRESS_SPEC = ToolSpec(
    name="eerel_mil217f_part_stress",
    description=(
        "MIL-HDBK-217F part-stress reliability prediction for a single component.\n\n"
        "Computes: λ_p = λ_b · πT · πS · πE · πQ · πA\n\n"
        "πT = Arrhenius temperature factor (Ea per part type).\n"
        "πS = electrical stress factor (voltage/power ratio raised to exponent).\n"
        "Over-stress-derating violations are flagged in warnings.\n\n"
        "Input: { part_type, tj_c, voltage_stress?, power_stress?, "
        "environment?, quality?, pi_a? }\n"
        "Returns: { ok, fit, pi_t, pi_s, pi_e, pi_q, pi_a, warnings, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_type": {
                "type": "string",
                "enum": _PART_TYPES,
                "description": "Part category.",
            },
            "tj_c": {
                "type": "number",
                "description": "Junction / case temperature [°C].",
            },
            "voltage_stress": {
                "type": "number",
                "description": "Applied/rated voltage ratio (0–1, default 0.5).",
            },
            "power_stress": {
                "type": "number",
                "description": "Applied/rated power ratio (0–1, default 0.5).",
            },
            "environment": {
                "type": "string",
                "enum": _ENV_CODES,
                "description": "Environment code (default GF).",
            },
            "quality": {
                "type": "string",
                "enum": _QUALITY_LEVELS,
                "description": "Quality level (default 'commercial').",
            },
            "pi_a": {
                "type": "number",
                "description": "Application multiplier (default 1.0).",
            },
        },
        "required": ["part_type", "tj_c"],
    },
)


@register(_PART_STRESS_SPEC, write=False)
async def eerel_mil217f_part_stress(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = mil217f_part_stress(
        part_type=a.get("part_type", ""),
        tj_c=a.get("tj_c", 50.0),
        voltage_stress=a.get("voltage_stress", 0.5),
        power_stress=a.get("power_stress", 0.5),
        environment=a.get("environment", "GF"),
        quality=a.get("quality", "commercial"),
        pi_a=a.get("pi_a", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. eerel_board_fit_mtbf
# ═══════════════════════════════════════════════════════════════════════════════

_BOARD_FIT_SPEC = ToolSpec(
    name="eerel_board_fit_mtbf",
    description=(
        "Aggregate MIL-HDBK-217F part-stress predictions across all board "
        "components to produce total board FIT and MTBF.\n\n"
        "Each part may specify: type, count, quality, tj_c, voltage_stress, "
        "power_stress, pi_a.\n\n"
        "Telcordia SR-332 note: Method I/II require vendor-supplied λ_SS and "
        "burn-in hours; use this tool for first-order estimates only.\n\n"
        "Input: { parts, environment? }\n"
        "Returns: { ok, fit_total, mtbf_hours, part_breakdown, warnings, "
        "telcordia_note, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "parts": {
                "type": "array",
                "description": (
                    "List of part dicts: {type, count?, quality?, "
                    "tj_c?, voltage_stress?, power_stress?, pi_a?}."
                ),
                "items": {"type": "object"},
            },
            "environment": {
                "type": "string",
                "enum": _ENV_CODES,
                "description": "Environment code (default GF).",
            },
        },
        "required": ["parts"],
    },
)


@register(_BOARD_FIT_SPEC, write=False)
async def eerel_board_fit_mtbf(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = board_fit_and_mtbf(
        parts=a.get("parts", []),
        environment=a.get("environment", "GF"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. eerel_arrhenius_af
# ═══════════════════════════════════════════════════════════════════════════════

_ARRHENIUS_SPEC = ToolSpec(
    name="eerel_arrhenius_af",
    description=(
        "Compute Arrhenius acceleration factor for ALT/HALT/HASS tests.\n\n"
        "AF = exp(Ea/k × (1/T_use − 1/T_test))\n\n"
        "AF > 1 → test is hotter than use → equivalent use-hours = test_hours × AF.\n"
        "A warning is issued if t_test ≤ t_use (deceleration).\n\n"
        "Input: { t_use_c, t_test_c, ea_ev? }\n"
        "Returns: { ok, acceleration_factor, ea_ev, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "t_use_c": {
                "type": "number",
                "description": "Use-condition temperature [°C].",
            },
            "t_test_c": {
                "type": "number",
                "description": "Accelerated-test temperature [°C].",
            },
            "ea_ev": {
                "type": "number",
                "description": "Activation energy [eV] (default 0.7 eV).",
            },
        },
        "required": ["t_use_c", "t_test_c"],
    },
)


@register(_ARRHENIUS_SPEC, write=False)
async def eerel_arrhenius_af(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = arrhenius_acceleration_factor(
        t_use_c=a.get("t_use_c"),
        t_test_c=a.get("t_test_c"),
        ea_ev=a.get("ea_ev", 0.7),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. eerel_coffin_manson
# ═══════════════════════════════════════════════════════════════════════════════

_COFFIN_MANSON_SPEC = ToolSpec(
    name="eerel_coffin_manson",
    description=(
        "Estimate solder-joint cycles-to-failure using the Coffin-Manson model "
        "(Norris-Landzberg variant, Solomon 1986).\n\n"
        "  Nf = C_f / (ΔT)^m\n\n"
        "Default C_f = 0.005 (eutectic SnPb); use ~0.003 for SAC305 lead-free.\n"
        "Default m = 2.0; SAC305 often uses 2.65.\n"
        "Warns if lifetime < 1 year.\n\n"
        "Input: { delta_t_c, c_f?, m?, f_cyc_per_day? }\n"
        "Returns: { ok, nf_cycles, lifetime_years, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "delta_t_c": {
                "type": "number",
                "description": "Thermal cycle amplitude ΔT [°C] (> 0).",
            },
            "c_f": {
                "type": "number",
                "description": "Fatigue ductility coefficient (default 0.005).",
            },
            "m": {
                "type": "number",
                "description": "Coffin-Manson exponent (default 2.0).",
            },
            "f_cyc_per_day": {
                "type": "number",
                "description": "Cycling frequency [cycles/day] (default 1.0).",
            },
        },
        "required": ["delta_t_c"],
    },
)


@register(_COFFIN_MANSON_SPEC, write=False)
async def eerel_coffin_manson(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = coffin_manson_nf(
        delta_t_c=a.get("delta_t_c"),
        c_f=a.get("c_f", 0.005),
        m=a.get("m", 2.0),
        f_cyc_per_day=a.get("f_cyc_per_day", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. eerel_peck_humidity
# ═══════════════════════════════════════════════════════════════════════════════

_PECK_SPEC = ToolSpec(
    name="eerel_peck_humidity",
    description=(
        "Compute Peck model humidity + temperature acceleration factor.\n\n"
        "AF = (RH_test/RH_use)^n_rh × exp(Ea/k × (1/T_use − 1/T_test))\n\n"
        "Peck (1986): n_rh = 2.7, Ea = 0.9 eV for moisture-driven plastic IC failures.\n\n"
        "Input: { rh_use, rh_test, t_use_c, t_test_c, ea_ev?, n_rh? }\n"
        "Returns: { ok, acceleration_factor, humidity_factor, thermal_factor, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "rh_use": {
                "type": "number",
                "description": "Use relative humidity [%RH] (0–100).",
            },
            "rh_test": {
                "type": "number",
                "description": "Test relative humidity [%RH] (0–100).",
            },
            "t_use_c": {
                "type": "number",
                "description": "Use temperature [°C].",
            },
            "t_test_c": {
                "type": "number",
                "description": "Test temperature [°C].",
            },
            "ea_ev": {
                "type": "number",
                "description": "Activation energy [eV] (default 0.9).",
            },
            "n_rh": {
                "type": "number",
                "description": "Humidity exponent (default 2.7).",
            },
        },
        "required": ["rh_use", "rh_test", "t_use_c", "t_test_c"],
    },
)


@register(_PECK_SPEC, write=False)
async def eerel_peck_humidity(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = peck_humidity_acceleration(
        rh_use=a.get("rh_use"),
        rh_test=a.get("rh_test"),
        t_use_c=a.get("t_use_c"),
        t_test_c=a.get("t_test_c"),
        ea_ev=a.get("ea_ev", 0.9),
        n_rh=a.get("n_rh", 2.7),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. eerel_voltage_acceleration
# ═══════════════════════════════════════════════════════════════════════════════

_VOLT_ACC_SPEC = ToolSpec(
    name="eerel_voltage_acceleration",
    description=(
        "Compute voltage acceleration factor for capacitor dielectric or oxide wear-out.\n\n"
        "AF = (V_test / V_use)^β\n\n"
        "β ≈ 2–5 for ceramic capacitors; β ≈ 3 for electrolytic; β ≈ 2.5 default.\n"
        "Warns if voltage over-stress ratio > 2×.\n\n"
        "Input: { v_use, v_test, beta? }\n"
        "Returns: { ok, acceleration_factor, v_use, v_test, beta, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "v_use": {
                "type": "number",
                "description": "Use voltage [V] (> 0).",
            },
            "v_test": {
                "type": "number",
                "description": "Test (stressed) voltage [V] (> 0).",
            },
            "beta": {
                "type": "number",
                "description": "Voltage exponent β (default 2.5).",
            },
        },
        "required": ["v_use", "v_test"],
    },
)


@register(_VOLT_ACC_SPEC, write=False)
async def eerel_voltage_acceleration(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = voltage_acceleration(
        v_use=a.get("v_use"),
        v_test=a.get("v_test"),
        beta=a.get("beta", 2.5),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. eerel_derating_check
# ═══════════════════════════════════════════════════════════════════════════════

_DERATING_SPEC = ToolSpec(
    name="eerel_derating_check",
    description=(
        "Check applied stress ratios against standard derating curves.\n\n"
        "Returns compliant=True/False and a list of violations. "
        "Violations are also issued as warnings.\n\n"
        "Input: { part_type, voltage_ratio?, power_ratio?, "
        "temperature_ratio?, current_ratio? }\n"
        "Returns: { ok, compliant, violations, limits, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_type": {
                "type": "string",
                "enum": _PART_TYPES,
                "description": "Part category.",
            },
            "voltage_ratio": {
                "type": "number",
                "description": "Applied / rated voltage (0–1).",
            },
            "power_ratio": {
                "type": "number",
                "description": "Applied / rated power (0–1).",
            },
            "temperature_ratio": {
                "type": "number",
                "description": "Applied / rated temperature in consistent units (0–1).",
            },
            "current_ratio": {
                "type": "number",
                "description": "Applied / rated current (0–1).",
            },
        },
        "required": ["part_type"],
    },
)


@register(_DERATING_SPEC, write=False)
async def eerel_derating_check(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = derating_check(
        part_type=a.get("part_type", ""),
        voltage_ratio=a.get("voltage_ratio"),
        power_ratio=a.get("power_ratio"),
        temperature_ratio=a.get("temperature_ratio"),
        current_ratio=a.get("current_ratio"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. eerel_bathtub
# ═══════════════════════════════════════════════════════════════════════════════

_BATHTUB_SPEC = ToolSpec(
    name="eerel_bathtub",
    description=(
        "Compute instantaneous hazard rate λ(t) from a three-region bathtub model.\n\n"
        "Superimposes three Weibull phases:\n"
        "  Infant-mortality (β < 1, decaying rate)\n"
        "  Random failures  (β = 1, constant rate)\n"
        "  Wear-out         (β > 1, increasing rate)\n\n"
        "Input: { t_hours, lambda_early?, lambda_random?, lambda_wearout?, "
        "t_infant?, t_wearout?, beta_early?, beta_wearout? }\n"
        "Returns: { ok, t_hours, lambda_fit, phase, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "t_hours": {
                "type": "number",
                "description": "Operating time [h] (≥ 0).",
            },
            "lambda_early": {
                "type": "number",
                "description": "Infant-mortality scale [FIT] (default 100).",
            },
            "lambda_random": {
                "type": "number",
                "description": "Random failure rate [FIT] (default 10).",
            },
            "lambda_wearout": {
                "type": "number",
                "description": "Wear-out scale [FIT] (default 1).",
            },
            "t_infant": {
                "type": "number",
                "description": "Infant-mortality characteristic life [h] (default 168).",
            },
            "t_wearout": {
                "type": "number",
                "description": "Wear-out characteristic life [h] (default 87600).",
            },
            "beta_early": {
                "type": "number",
                "description": "Weibull shape for infant mortality (< 1, default 0.5).",
            },
            "beta_wearout": {
                "type": "number",
                "description": "Weibull shape for wear-out (> 1, default 4.0).",
            },
        },
        "required": ["t_hours"],
    },
)


@register(_BATHTUB_SPEC, write=False)
async def eerel_bathtub(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = bathtub_hazard_rate(
        t_hours=a.get("t_hours"),
        lambda_early=a.get("lambda_early", 100.0),
        lambda_random=a.get("lambda_random", 10.0),
        lambda_wearout=a.get("lambda_wearout", 1.0),
        t_infant=a.get("t_infant", 168.0),
        t_wearout=a.get("t_wearout", 87600.0),
        beta_early=a.get("beta_early", 0.5),
        beta_wearout=a.get("beta_wearout", 4.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. eerel_redundancy_mtbf
# ═══════════════════════════════════════════════════════════════════════════════

_REDUNDANCY_SPEC = ToolSpec(
    name="eerel_redundancy_mtbf",
    description=(
        "Compute system MTBF for active (parallel) or standby redundancy.\n\n"
        "Active parallel n units:\n"
        "  MTBF_sys = MTBF_unit × Σ(k=1..n) 1/k\n\n"
        "Standby (cold) with switch reliability Rs:\n"
        "  MTBF_sys ≈ MTBF_unit × n × Rs\n\n"
        "Input: { fit_per_unit, n_active?, redundancy_type?, switch_reliability? }\n"
        "Returns: { ok, mtbf_unit_hours, mtbf_system_hours, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fit_per_unit": {
                "type": "number",
                "description": "Failure rate of each unit [FIT] (> 0).",
            },
            "n_active": {
                "type": "integer",
                "minimum": 1,
                "description": "Number of units (default 2).",
            },
            "redundancy_type": {
                "type": "string",
                "enum": ["active", "standby"],
                "description": "'active' (parallel) or 'standby' (cold) (default 'active').",
            },
            "switch_reliability": {
                "type": "number",
                "description": "Switchover reliability (0–1, standby only, default 0.99).",
            },
        },
        "required": ["fit_per_unit"],
    },
)


@register(_REDUNDANCY_SPEC, write=False)
async def eerel_redundancy_mtbf(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = redundancy_mtbf(
        fit_per_unit=a.get("fit_per_unit"),
        n_active=a.get("n_active", 2),
        redundancy_type=a.get("redundancy_type", "active"),
        switch_reliability=a.get("switch_reliability", 0.99),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. eerel_mtbf_confidence
# ═══════════════════════════════════════════════════════════════════════════════

_MTBF_CONF_SPEC = ToolSpec(
    name="eerel_mtbf_confidence",
    description=(
        "Compute one-sided MTBF confidence bound from time-terminated "
        "demonstration test data (MIL-HDBK-781A, Annex A).\n\n"
        "  Lower bound: MTBF_lower = 2T / χ²(2f+2, α)\n"
        "  Upper bound: MTBF_upper = 2T / χ²(2f, 1−α)\n\n"
        "Chi-square is approximated via Wilson-Hilferty normal approximation.\n"
        "Warns when demonstrated MTBF is below 1 000 h.\n\n"
        "Input: { total_hours, n_failures, confidence?, bound? }\n"
        "Returns: { ok, mtbf_bound_hours, confidence, bound, chi2, df, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "total_hours": {
                "type": "number",
                "description": "Accumulated test time [h] (> 0).",
            },
            "n_failures": {
                "type": "integer",
                "minimum": 0,
                "description": "Observed failure count (≥ 0).",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence level (0–1, default 0.90).",
            },
            "bound": {
                "type": "string",
                "enum": ["lower", "upper"],
                "description": "'lower' or 'upper' (default 'lower').",
            },
        },
        "required": ["total_hours", "n_failures"],
    },
)


@register(_MTBF_CONF_SPEC, write=False)
async def eerel_mtbf_confidence(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = mtbf_confidence_bound(
        total_hours=a.get("total_hours"),
        n_failures=a.get("n_failures"),
        confidence=a.get("confidence", 0.90),
        bound=a.get("bound", "lower"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. eerel_duty_cycle_fit
# ═══════════════════════════════════════════════════════════════════════════════

_DUTY_CYCLE_SPEC = ToolSpec(
    name="eerel_duty_cycle_fit",
    description=(
        "Adjust FIT and MTBF for duty cycle (power-on-hours vs calendar time).\n\n"
        "  λ_calendar = λ_rated × duty_cycle\n"
        "  MTBF_calendar = 1e9 / λ_calendar\n\n"
        "Use this when MIL-217F gives a rated (100 % duty) FIT but the device "
        "is powered for only a fraction of calendar time.\n\n"
        "Input: { fit_rated, duty_cycle, calendar_hours_per_year? }\n"
        "Returns: { ok, fit_adjusted, mtbf_calendar_hours, mtbf_calendar_years, "
        "power_on_hours_per_year, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fit_rated": {
                "type": "number",
                "description": "Nominal (100 % duty) FIT (> 0).",
            },
            "duty_cycle": {
                "type": "number",
                "description": "Fraction of calendar time powered (0–1).",
            },
            "calendar_hours_per_year": {
                "type": "number",
                "description": "Calendar hours per year (default 8760).",
            },
        },
        "required": ["fit_rated", "duty_cycle"],
    },
)


@register(_DUTY_CYCLE_SPEC, write=False)
async def eerel_duty_cycle_fit(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = duty_cycle_adjusted_fit(
        fit_rated=a.get("fit_rated"),
        duty_cycle=a.get("duty_cycle"),
        calendar_hours_per_year=a.get("calendar_hours_per_year", 8760.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_PARTS_COUNT_SPEC.name,  _PARTS_COUNT_SPEC,  eerel_mil217f_parts_count),
    (_PART_STRESS_SPEC.name,  _PART_STRESS_SPEC,  eerel_mil217f_part_stress),
    (_BOARD_FIT_SPEC.name,    _BOARD_FIT_SPEC,    eerel_board_fit_mtbf),
    (_ARRHENIUS_SPEC.name,    _ARRHENIUS_SPEC,    eerel_arrhenius_af),
    (_COFFIN_MANSON_SPEC.name, _COFFIN_MANSON_SPEC, eerel_coffin_manson),
    (_PECK_SPEC.name,         _PECK_SPEC,         eerel_peck_humidity),
    (_VOLT_ACC_SPEC.name,     _VOLT_ACC_SPEC,     eerel_voltage_acceleration),
    (_DERATING_SPEC.name,     _DERATING_SPEC,     eerel_derating_check),
    (_BATHTUB_SPEC.name,      _BATHTUB_SPEC,      eerel_bathtub),
    (_REDUNDANCY_SPEC.name,   _REDUNDANCY_SPEC,   eerel_redundancy_mtbf),
    (_MTBF_CONF_SPEC.name,    _MTBF_CONF_SPEC,    eerel_mtbf_confidence),
    (_DUTY_CYCLE_SPEC.name,   _DUTY_CYCLE_SPEC,   eerel_duty_cycle_fit),
]
