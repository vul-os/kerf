"""
Crystal oscillator & PLL design — LLM tools.

Exposes tools to the Kerf agent layer:

  osc_crystal_load_caps        — crystal load capacitance & external cap selection
  osc_pierce_neg_resistance    — Pierce-oscillator negative resistance & gm margin
  osc_drive_level              — drive-level estimate for crystal
  osc_frequency_pulling        — frequency pulling/trim from CL error (ppm)
  osc_ppm_budget               — ppm error budget (tolerance + temp + aging + load)
  osc_rc_frequency             — RC oscillator frequency
  osc_lc_frequency             — LC oscillator frequency (Colpitts/Clapp/Hartley)
  osc_ring_frequency           — ring oscillator frequency
  pll_divider_n                — PLL: divider N from fout/fref
  pll_loop_filter              — type-II 2nd/3rd-order loop filter components
  pll_lock_time                — PLL lock time estimate
  pll_phase_noise_to_jitter    — phase noise → RMS jitter conversion

All handlers follow the kerf never-raise contract:
  Success: {"ok": True, ...}  via ok_payload
  Failure: {"ok": False, "error": ..., "code": ...}  via err_payload
  Never raise.

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.oscillator.design import (
    crystal_load_caps,
    pierce_negative_resistance,
    drive_level_estimate,
    frequency_pulling,
    ppm_error_budget,
    rc_oscillator_frequency,
    lc_oscillator_frequency,
    ring_oscillator_frequency,
    pll_divider_n,
    pll_type2_loop_filter,
    pll_lock_time,
    phase_noise_to_jitter,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. osc_crystal_load_caps
# ═══════════════════════════════════════════════════════════════════════════════

_XTAL_LOAD_CAPS_SPEC = ToolSpec(
    name="osc_crystal_load_caps",
    description=(
        "Calculate crystal load capacitance (CL) and recommend external capacitor "
        "values for a Pierce or parallel-resonance oscillator.\n\n"
        "Effective CL seen by the crystal:\n"
        "  CL = (C1_ext × C2_ext) / (C1_ext + C2_ext) + Cstray\n\n"
        "Symmetric external caps for target CL:\n"
        "  C_ext = 2 × (CL_target − Cstray)\n\n"
        "Input: { cl_target_f, cstray_f?, c1_ext_f?, c2_ext_f? }\n"
        "Returns: { ok, cl_target_pf, c_ext_symmetric_pf, cl_actual_pf?, cl_error_ppm? }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cl_target_f": {
                "type": "number",
                "description": "Target crystal load capacitance [F], e.g. 12e-12 for 12 pF.",
            },
            "cstray_f": {
                "type": "number",
                "description": "PCB stray capacitance per node [F] (default 3e-12 = 3 pF).",
            },
            "c1_ext_f": {
                "type": "number",
                "description": "First external load capacitor [F] (optional, for verification).",
            },
            "c2_ext_f": {
                "type": "number",
                "description": "Second external load capacitor [F] (optional, for verification).",
            },
        },
        "required": ["cl_target_f"],
    },
)


@register(_XTAL_LOAD_CAPS_SPEC, write=False)
async def osc_crystal_load_caps(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = crystal_load_caps(
        cl_target_f=a.get("cl_target_f"),
        cstray_f=a.get("cstray_f", 3e-12),
        c1_ext_f=a.get("c1_ext_f"),
        c2_ext_f=a.get("c2_ext_f"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. osc_pierce_neg_resistance
# ═══════════════════════════════════════════════════════════════════════════════

_PIERCE_NEG_RES_SPEC = ToolSpec(
    name="osc_pierce_neg_resistance",
    description=(
        "Compute Pierce oscillator negative resistance and gm margin.\n\n"
        "Model (Rohde & Kuhn 2005; Vittoz 1988):\n"
        "  |−Rn| = gm / (ω² × C1 × C2)\n\n"
        "Oscillation starts when |−Rn| ≥ safety_factor × ESR (typically 3–5×).\n"
        "gm_margin = |−Rn| / ESR — must be ≥ safety_factor.\n\n"
        "Input: { freq_hz, gm_s, c1_f, c2_f, esr_ohm, safety_factor? }\n"
        "Returns: { ok, neg_resistance_ohm, gm_margin, sufficient_gm, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {
                "type": "number",
                "description": "Crystal nominal frequency [Hz].",
            },
            "gm_s": {
                "type": "number",
                "description": "Inverting amplifier transconductance [S] (A/V).",
            },
            "c1_f": {
                "type": "number",
                "description": "Load capacitor on input side [F].",
            },
            "c2_f": {
                "type": "number",
                "description": "Load capacitor on output side [F].",
            },
            "esr_ohm": {
                "type": "number",
                "description": "Crystal equivalent series resistance [Ω].",
            },
            "safety_factor": {
                "type": "number",
                "description": "Negative-resistance safety margin (default 3).",
            },
        },
        "required": ["freq_hz", "gm_s", "c1_f", "c2_f", "esr_ohm"],
    },
)


@register(_PIERCE_NEG_RES_SPEC, write=False)
async def osc_pierce_neg_resistance(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = pierce_negative_resistance(
        freq_hz=a.get("freq_hz"),
        gm_s=a.get("gm_s"),
        c1_f=a.get("c1_f"),
        c2_f=a.get("c2_f"),
        esr_ohm=a.get("esr_ohm"),
        safety_factor=a.get("safety_factor", 3.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. osc_drive_level
# ═══════════════════════════════════════════════════════════════════════════════

_DRIVE_LEVEL_SPEC = ToolSpec(
    name="osc_drive_level",
    description=(
        "Estimate power dissipated in the crystal (drive level) in a Pierce oscillator.\n\n"
        "Simplified model (Baba & Yoon 2003 / Frerking 1978):\n"
        "  I_rms ≈ ω × CL × V_rms   (current through load cap)\n"
        "  P_xtal = I_rms² × ESR\n\n"
        "Over-drive damages the crystal. Typical max drive level: 10–100 μW.\n\n"
        "Input: { freq_hz, esr_ohm, c_load_f, v_osc_v, max_drive_level_uw? }\n"
        "Returns: { ok, drive_level_uw, over_drive, i_rms_a, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {
                "type": "number",
                "description": "Oscillation frequency [Hz].",
            },
            "esr_ohm": {
                "type": "number",
                "description": "Crystal equivalent series resistance [Ω].",
            },
            "c_load_f": {
                "type": "number",
                "description": "Crystal load capacitance [F].",
            },
            "v_osc_v": {
                "type": "number",
                "description": "Oscillation voltage peak amplitude [V].",
            },
            "max_drive_level_uw": {
                "type": "number",
                "description": "Maximum crystal drive level [μW] (default 100 μW).",
            },
        },
        "required": ["freq_hz", "esr_ohm", "c_load_f", "v_osc_v"],
    },
)


@register(_DRIVE_LEVEL_SPEC, write=False)
async def osc_drive_level(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = drive_level_estimate(
        freq_hz=a.get("freq_hz"),
        esr_ohm=a.get("esr_ohm"),
        c_load_f=a.get("c_load_f"),
        v_osc_v=a.get("v_osc_v"),
        max_drive_level_uw=a.get("max_drive_level_uw", 100.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. osc_frequency_pulling
# ═══════════════════════════════════════════════════════════════════════════════

_FREQ_PULLING_SPEC = ToolSpec(
    name="osc_frequency_pulling",
    description=(
        "Compute crystal oscillator frequency pulling due to load capacitance "
        "deviation from the nominal CL specification.\n\n"
        "First-order approximation (IEC 60444-5):\n"
        "  Δf/f ≈ (Cm × ΔCL) / (2 × (C0 + CL_nom)²)   [ppm × 1e6]\n\n"
        "Exact model also computed:\n"
        "  Δf/f = (Cm/2) × [1/(C0+CL_act) − 1/(C0+CL_nom)]\n\n"
        "Input: { freq_hz, cm_f, c0_f, cl_nominal_f, cl_actual_f }\n"
        "Returns: { ok, delta_f_ppm, delta_f_ppm_exact, delta_f_hz, delta_f_hz_exact }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {
                "type": "number",
                "description": "Crystal nominal frequency [Hz].",
            },
            "cm_f": {
                "type": "number",
                "description": "Motional (series) capacitance Cm [F], e.g. 10e-15 (10 fF).",
            },
            "c0_f": {
                "type": "number",
                "description": "Shunt (parallel) capacitance C0 [F], e.g. 3e-12 (3 pF).",
            },
            "cl_nominal_f": {
                "type": "number",
                "description": "Crystal nominal load capacitance [F] (from crystal datasheet).",
            },
            "cl_actual_f": {
                "type": "number",
                "description": "Actual PCB load capacitance [F].",
            },
        },
        "required": ["freq_hz", "cm_f", "c0_f", "cl_nominal_f", "cl_actual_f"],
    },
)


@register(_FREQ_PULLING_SPEC, write=False)
async def osc_frequency_pulling(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = frequency_pulling(
        freq_hz=a.get("freq_hz"),
        cm_f=a.get("cm_f"),
        c0_f=a.get("c0_f"),
        cl_nominal_f=a.get("cl_nominal_f"),
        cl_actual_f=a.get("cl_actual_f"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. osc_ppm_budget
# ═══════════════════════════════════════════════════════════════════════════════

_PPM_BUDGET_SPEC = ToolSpec(
    name="osc_ppm_budget",
    description=(
        "Compute crystal oscillator frequency accuracy error budget using "
        "root-sum-of-squares (RSS) combination of independent error sources.\n\n"
        "  total_ppm = sqrt(initial² + temp² + aging² + load²)\n\n"
        "Each term is the worst-case ±magnitude in ppm (provide absolute values).\n\n"
        "Input: { initial_tolerance_ppm, temp_ppm, aging_ppm, load_ppm, "
        "budget_limit_ppm? }\n"
        "Returns: { ok, total_ppm, within_budget?, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "initial_tolerance_ppm": {
                "type": "number",
                "description": "Initial frequency tolerance at calibration [ppm].",
            },
            "temp_ppm": {
                "type": "number",
                "description": "Temperature coefficient contribution [ppm] over operating range.",
            },
            "aging_ppm": {
                "type": "number",
                "description": "Aging contribution over product lifetime [ppm/year × years].",
            },
            "load_ppm": {
                "type": "number",
                "description": "Load-pulling and supply voltage contribution [ppm].",
            },
            "budget_limit_ppm": {
                "type": "number",
                "description": "System frequency budget limit [ppm] (optional).",
            },
        },
        "required": ["initial_tolerance_ppm", "temp_ppm", "aging_ppm", "load_ppm"],
    },
)


@register(_PPM_BUDGET_SPEC, write=False)
async def osc_ppm_budget(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = ppm_error_budget(
        initial_tolerance_ppm=a.get("initial_tolerance_ppm"),
        temp_ppm=a.get("temp_ppm"),
        aging_ppm=a.get("aging_ppm"),
        load_ppm=a.get("load_ppm"),
        budget_limit_ppm=a.get("budget_limit_ppm"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. osc_rc_frequency
# ═══════════════════════════════════════════════════════════════════════════════

_RC_FREQ_SPEC = ToolSpec(
    name="osc_rc_frequency",
    description=(
        "Compute RC oscillator frequency.\n\n"
        "Ideal: f = 1 / (2π × R × C)\n\n"
        "For CMOS Schmitt-trigger oscillator: f ≈ 1 / (2.2 × R × C)\n"
        "  → set rc_factor = 2.2/(2π) ≈ 0.3502\n\n"
        "Input: { r_ohm, c_f, rc_factor? }\n"
        "Returns: { ok, freq_hz, period_s, tau_s }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r_ohm": {
                "type": "number",
                "description": "Resistance [Ω].",
            },
            "c_f": {
                "type": "number",
                "description": "Capacitance [F].",
            },
            "rc_factor": {
                "type": "number",
                "description": (
                    "Multiplier on R×C (default 1.0 → ideal 1/(2πRC)). "
                    "Use 2.2/(2π) ≈ 0.3502 for CMOS Schmitt variant."
                ),
            },
        },
        "required": ["r_ohm", "c_f"],
    },
)


@register(_RC_FREQ_SPEC, write=False)
async def osc_rc_frequency(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = rc_oscillator_frequency(
        r_ohm=a.get("r_ohm"),
        c_f=a.get("c_f"),
        rc_factor=a.get("rc_factor", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. osc_lc_frequency
# ═══════════════════════════════════════════════════════════════════════════════

_LC_FREQ_SPEC = ToolSpec(
    name="osc_lc_frequency",
    description=(
        "Compute LC oscillator resonant frequency (Colpitts, Clapp, Hartley, etc.).\n\n"
        "  f = 1 / (2π × sqrt(L × C))\n\n"
        "For Colpitts: C_eff = C1×C2/(C1+C2).\n"
        "For Clapp: C_eff includes series tuning cap.\n\n"
        "Input: { l_h, c_f }\n"
        "Returns: { ok, freq_hz, omega_rad_s, period_s }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "l_h": {
                "type": "number",
                "description": "Inductance [H], e.g. 100e-9 for 100 nH.",
            },
            "c_f": {
                "type": "number",
                "description": "Effective tank capacitance [F], e.g. 10e-12 for 10 pF.",
            },
        },
        "required": ["l_h", "c_f"],
    },
)


@register(_LC_FREQ_SPEC, write=False)
async def osc_lc_frequency(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = lc_oscillator_frequency(
        l_h=a.get("l_h"),
        c_f=a.get("c_f"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. osc_ring_frequency
# ═══════════════════════════════════════════════════════════════════════════════

_RING_FREQ_SPEC = ToolSpec(
    name="osc_ring_frequency",
    description=(
        "Compute ring oscillator fundamental frequency.\n\n"
        "  f = 1 / (2 × N × τ_pd)\n\n"
        "N = number of inverting stages (must be odd for oscillation: 3, 5, 7, ...)\n"
        "τ_pd = propagation delay per stage [s]\n\n"
        "Input: { n_stages, tau_pd_s }\n"
        "Returns: { ok, freq_hz, period_s, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n_stages": {
                "type": "integer",
                "description": "Number of inverter stages (odd integer ≥ 3).",
                "minimum": 3,
            },
            "tau_pd_s": {
                "type": "number",
                "description": "Propagation delay per stage [s], e.g. 50e-12 for 50 ps.",
            },
        },
        "required": ["n_stages", "tau_pd_s"],
    },
)


@register(_RING_FREQ_SPEC, write=False)
async def osc_ring_frequency(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = ring_oscillator_frequency(
        n_stages=a.get("n_stages"),
        tau_pd_s=a.get("tau_pd_s"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. pll_divider_n
# ═══════════════════════════════════════════════════════════════════════════════

_PLL_DIV_N_SPEC = ToolSpec(
    name="pll_divider_n",
    description=(
        "Compute PLL feedback divider N from desired output and reference frequencies.\n\n"
        "Integer-N: N = round(f_out / f_ref); actual f_out = N × f_ref\n"
        "Fractional-N: N = f_out / f_ref (exact float)\n\n"
        "Input: { f_out_hz, f_ref_hz, integer_n? }\n"
        "Returns: { ok, N_exact, N_used, f_out_actual_hz, freq_error_ppm, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "f_out_hz": {
                "type": "number",
                "description": "Desired VCO output frequency [Hz].",
            },
            "f_ref_hz": {
                "type": "number",
                "description": "PFD reference frequency [Hz].",
            },
            "integer_n": {
                "type": "boolean",
                "description": "True for integer-N PLL (default), False for fractional-N.",
            },
        },
        "required": ["f_out_hz", "f_ref_hz"],
    },
)


@register(_PLL_DIV_N_SPEC, write=False)
async def pll_divider_n_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = pll_divider_n(
        f_out_hz=a.get("f_out_hz"),
        f_ref_hz=a.get("f_ref_hz"),
        integer_n=a.get("integer_n", True),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. pll_loop_filter
# ═══════════════════════════════════════════════════════════════════════════════

_PLL_LOOP_FILTER_SPEC = ToolSpec(
    name="pll_loop_filter",
    description=(
        "Design a type-II charge-pump PLL loop filter (2nd or 3rd order).\n\n"
        "Model (Banerjee 'PLL Performance, Simulation, and Design' 5e, 2006):\n"
        "  C1 = Icp × Kvco / (2π × N × ωn²)\n"
        "  R  = 2ζ / (ωn × C1)\n"
        "  C2 = C1 / 10   [reference spur suppression]\n\n"
        "ζ from phase margin φm (Banerjee approximation):\n"
        "  ζ = tan(φm)/2 + sqrt(tan²(φm)/4 + 1)/2\n\n"
        "Stability: phase margin < 45° → UNSTABLE.\n\n"
        "Input: { f_loop_bw_hz, phase_margin_deg, icp_a, kvco_hz_per_v, "
        "n_divider, order? }\n"
        "Returns: { ok, R_ohm, C1_f, C2_f, zeta, omega_n_rad_s, stable, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "f_loop_bw_hz": {
                "type": "number",
                "description": "Loop bandwidth [Hz].",
            },
            "phase_margin_deg": {
                "type": "number",
                "description": "Desired phase margin [degrees] (45–70° typical).",
            },
            "icp_a": {
                "type": "number",
                "description": "Charge pump current [A], e.g. 1e-3 (1 mA).",
            },
            "kvco_hz_per_v": {
                "type": "number",
                "description": "VCO gain [Hz/V], e.g. 50e6 (50 MHz/V).",
            },
            "n_divider": {
                "type": "number",
                "description": "Feedback divider ratio N.",
            },
            "order": {
                "type": "integer",
                "enum": [2, 3],
                "description": "Loop filter order: 2 (default) or 3.",
            },
        },
        "required": [
            "f_loop_bw_hz", "phase_margin_deg", "icp_a",
            "kvco_hz_per_v", "n_divider",
        ],
    },
)


@register(_PLL_LOOP_FILTER_SPEC, write=False)
async def pll_loop_filter(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = pll_type2_loop_filter(
        f_loop_bw_hz=a.get("f_loop_bw_hz"),
        phase_margin_deg=a.get("phase_margin_deg"),
        icp_a=a.get("icp_a"),
        kvco_hz_per_v=a.get("kvco_hz_per_v"),
        n_divider=a.get("n_divider"),
        order=a.get("order", 2),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. pll_lock_time
# ═══════════════════════════════════════════════════════════════════════════════

_PLL_LOCK_TIME_SPEC = ToolSpec(
    name="pll_lock_time",
    description=(
        "Estimate PLL acquisition lock time for a frequency step.\n\n"
        "Model (Banerjee 2006 §3.8 / Gardner 2005):\n"
        "  t_lock ≈ −ln(ε_freq / f_step) / (ζ × ωn)\n\n"
        "Valid for type-II 2nd-order PLL in the linear range (no cycle-slip).\n\n"
        "Input: { f_loop_bw_hz, zeta, f_step_hz, epsilon_hz? }\n"
        "Returns: { ok, t_lock_s, t_lock_us }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "f_loop_bw_hz": {
                "type": "number",
                "description": "Loop bandwidth [Hz].",
            },
            "zeta": {
                "type": "number",
                "description": "Damping ratio (from loop filter design).",
            },
            "f_step_hz": {
                "type": "number",
                "description": "Frequency step size [Hz].",
            },
            "epsilon_hz": {
                "type": "number",
                "description": "Frequency accuracy at lock [Hz] (default 1.0 Hz).",
            },
        },
        "required": ["f_loop_bw_hz", "zeta", "f_step_hz"],
    },
)


@register(_PLL_LOCK_TIME_SPEC, write=False)
async def pll_lock_time_tool(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = pll_lock_time(
        f_loop_bw_hz=a.get("f_loop_bw_hz"),
        zeta=a.get("zeta"),
        f_step_hz=a.get("f_step_hz"),
        epsilon_hz=a.get("epsilon_hz", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. pll_phase_noise_to_jitter
# ═══════════════════════════════════════════════════════════════════════════════

_PN_JITTER_SPEC = ToolSpec(
    name="pll_phase_noise_to_jitter",
    description=(
        "Convert single-sideband phase noise to integrated RMS jitter.\n\n"
        "Approximation for flat phase-noise floor L(f) [dBc/Hz] over bandwidth BW:\n"
        "  L_lin = 10^(L_dBc/10)\n"
        "  σ_phase [rad] = sqrt(2 × L_lin × BW)\n"
        "  σ_jitter [s]  = σ_phase / (2π × f_osc)\n\n"
        "Reference spurs are NOT included (see ref_spur_note in response).\n\n"
        "Input: { f_osc_hz, phase_noise_dbc_hz, integration_bw_hz }\n"
        "Returns: { ok, sigma_jitter_s, sigma_jitter_ps, sigma_jitter_fs, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "f_osc_hz": {
                "type": "number",
                "description": "Oscillator frequency [Hz].",
            },
            "phase_noise_dbc_hz": {
                "type": "number",
                "description": (
                    "Phase noise spectral density [dBc/Hz] (typically negative, "
                    "e.g. −130 for a good 100 MHz TCXO)."
                ),
            },
            "integration_bw_hz": {
                "type": "number",
                "description": "One-sided integration bandwidth [Hz].",
            },
        },
        "required": ["f_osc_hz", "phase_noise_dbc_hz", "integration_bw_hz"],
    },
)


@register(_PN_JITTER_SPEC, write=False)
async def pll_phase_noise_to_jitter(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = phase_noise_to_jitter(
        f_osc_hz=a.get("f_osc_hz"),
        phase_noise_dbc_hz=a.get("phase_noise_dbc_hz"),
        integration_bw_hz=a.get("integration_bw_hz"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_XTAL_LOAD_CAPS_SPEC.name,   _XTAL_LOAD_CAPS_SPEC,   osc_crystal_load_caps),
    (_PIERCE_NEG_RES_SPEC.name,   _PIERCE_NEG_RES_SPEC,   osc_pierce_neg_resistance),
    (_DRIVE_LEVEL_SPEC.name,      _DRIVE_LEVEL_SPEC,      osc_drive_level),
    (_FREQ_PULLING_SPEC.name,     _FREQ_PULLING_SPEC,     osc_frequency_pulling),
    (_PPM_BUDGET_SPEC.name,       _PPM_BUDGET_SPEC,       osc_ppm_budget),
    (_RC_FREQ_SPEC.name,          _RC_FREQ_SPEC,          osc_rc_frequency),
    (_LC_FREQ_SPEC.name,          _LC_FREQ_SPEC,          osc_lc_frequency),
    (_RING_FREQ_SPEC.name,        _RING_FREQ_SPEC,        osc_ring_frequency),
    (_PLL_DIV_N_SPEC.name,        _PLL_DIV_N_SPEC,        pll_divider_n_tool),
    (_PLL_LOOP_FILTER_SPEC.name,  _PLL_LOOP_FILTER_SPEC,  pll_loop_filter),
    (_PLL_LOCK_TIME_SPEC.name,    _PLL_LOCK_TIME_SPEC,    pll_lock_time_tool),
    (_PN_JITTER_SPEC.name,        _PN_JITTER_SPEC,        pll_phase_noise_to_jitter),
]
