"""
Sensor signal-conditioning LLM tools.

Provides LLM-callable tools:

  sensorcond_bridge_output         — Wheatstone bridge voltage vs strain
  sensorcond_bridge_excitation     — Bridge excitation power and max safe voltage
  sensorcond_strain_to_stress      — Strain-gauge µε → stress (Hooke's law)
  sensorcond_rtd_resistance        — RTD forward model (CVD): temperature → resistance
  sensorcond_rtd_temperature       — RTD inverse model (CVD): resistance → temperature
  sensorcond_rtd_lead_wire         — RTD lead-wire error and correction
  sensorcond_thermocouple          — TC NIST inverse polynomial + CJC
  sensorcond_ina_gain              — Instrumentation-amp gain and error budget
  sensorcond_adc_bits              — Required ADC bits for a target resolution
  sensorcond_enob                  — ENOB from input-referred RMS noise
  sensorcond_antialias_corner      — Anti-alias filter corner frequency
  sensorcond_4_20ma_scale          — 4-20 mA loop engineering-unit scaling
  sensorcond_burden_voltage        — 4-20 mA burden/compliance check
  sensorcond_noise_rss             — Sensor noise budget RSS
  sensorcond_filter_topology       — Sallen-Key vs MFB topology selector

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

from kerf_electronics.sensorcond.condition import (
    antialias_filter_corner,
    adc_required_bits,
    bridge_excitation_power,
    enob_from_noise,
    filter_topology_select,
    instrumentation_amp_gain,
    loop_4_20ma_scaling,
    loop_burden_voltage,
    noise_budget_rss,
    rtd_lead_wire_error,
    rtd_resistance,
    rtd_temperature,
    strain_to_stress,
    thermocouple_temperature,
    wheatstone_bridge_output,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. sensorcond_bridge_output
# ═══════════════════════════════════════════════════════════════════════════════

_BRIDGE_OUTPUT_SPEC = ToolSpec(
    name="sensorcond_bridge_output",
    description=(
        "Compute Wheatstone bridge output voltage for a strain-gauge circuit.\n\n"
        "Supports quarter-bridge (one active arm), half-bridge (two complementary "
        "arms, e.g. bending beam), and full-bridge (four active arms).\n\n"
        "Returns both linearised and exact (nonlinear) output voltages, plus the "
        "nonlinearity error percentage and lead-wire sensitivity loss.\n\n"
        "A warning is issued when ΔR/R > 1% (nonlinearity significant for "
        "quarter/half bridges).\n\n"
        "Input: { excitation_v, gauge_factor, strain_ue, config?, "
        "lead_resistance_ohm?, nominal_resistance_ohm? }\n"
        "Returns: { ok, config, vout_linearised_v, vout_exact_v, "
        "nonlinearity_error_pct, lead_wire_sensitivity_loss_pct, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "excitation_v": {
                "type": "number",
                "description": "Bridge excitation voltage [V].",
            },
            "gauge_factor": {
                "type": "number",
                "description": "Strain-gauge gauge factor (dimensionless, typical 2.0).",
            },
            "strain_ue": {
                "type": "number",
                "description": "Applied strain [µε = microstrain].",
            },
            "config": {
                "type": "string",
                "enum": ["quarter", "half", "full"],
                "description": "Bridge configuration: 'quarter', 'half', or 'full' (default 'quarter').",
            },
            "lead_resistance_ohm": {
                "type": "number",
                "description": "Total lead resistance for the active arm [Ω] (default 0).",
            },
            "nominal_resistance_ohm": {
                "type": "number",
                "description": "Nominal gauge resistance Rg [Ω] (default 350).",
            },
        },
        "required": ["excitation_v", "gauge_factor", "strain_ue"],
    },
)


@register(_BRIDGE_OUTPUT_SPEC, write=False)
async def sensorcond_bridge_output(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = wheatstone_bridge_output(
        excitation_v=a.get("excitation_v"),
        gauge_factor=a.get("gauge_factor"),
        strain_ue=a.get("strain_ue"),
        config=a.get("config", "quarter"),
        lead_resistance_ohm=a.get("lead_resistance_ohm", 0.0),
        nominal_resistance_ohm=a.get("nominal_resistance_ohm", 350.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. sensorcond_bridge_excitation
# ═══════════════════════════════════════════════════════════════════════════════

_BRIDGE_EXCITATION_SPEC = ToolSpec(
    name="sensorcond_bridge_excitation",
    description=(
        "Compute bridge excitation power per arm, total power, and maximum safe "
        "excitation voltage for bonded strain gauges.\n\n"
        "For a balanced bridge (all arms = Rg):\n"
        "  P_arm = Vex² / (4 × Rg)\n"
        "  P_total = Vex² / Rg\n"
        "  Vex_max = sqrt(4 × Rg × 30 mW)   [typical 30 mW self-heating limit]\n\n"
        "A warning is issued when P_arm exceeds 30 mW.\n\n"
        "Input: { excitation_v, nominal_resistance_ohm? }\n"
        "Returns: { ok, i_arm_a, p_arm_w, p_total_w, max_safe_excitation_v }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "excitation_v": {
                "type": "number",
                "description": "Bridge excitation voltage [V].",
            },
            "nominal_resistance_ohm": {
                "type": "number",
                "description": "Nominal gauge resistance Rg [Ω] (default 350).",
            },
        },
        "required": ["excitation_v"],
    },
)


@register(_BRIDGE_EXCITATION_SPEC, write=False)
async def sensorcond_bridge_excitation(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = bridge_excitation_power(
        excitation_v=a.get("excitation_v"),
        nominal_resistance_ohm=a.get("nominal_resistance_ohm", 350.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. sensorcond_strain_to_stress
# ═══════════════════════════════════════════════════════════════════════════════

_STRAIN_STRESS_SPEC = ToolSpec(
    name="sensorcond_strain_to_stress",
    description=(
        "Convert strain-gauge microstrain [µε] to stress [MPa] using Hooke's law.\n\n"
        "  σ = E × ε\n\n"
        "Common Young's moduli: steel ≈ 200 GPa, aluminium ≈ 70 GPa, "
        "titanium ≈ 114 GPa, copper ≈ 128 GPa.\n\n"
        "Input: { strain_ue, youngs_modulus_gpa }\n"
        "Returns: { ok, stress_pa, stress_mpa }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "strain_ue": {
                "type": "number",
                "description": "Strain [µε = microstrain].",
            },
            "youngs_modulus_gpa": {
                "type": "number",
                "description": "Young's modulus [GPa].",
            },
        },
        "required": ["strain_ue", "youngs_modulus_gpa"],
    },
)


@register(_STRAIN_STRESS_SPEC, write=False)
async def sensorcond_strain_to_stress(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = strain_to_stress(
        strain_ue=a.get("strain_ue"),
        youngs_modulus_gpa=a.get("youngs_modulus_gpa"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. sensorcond_rtd_resistance
# ═══════════════════════════════════════════════════════════════════════════════

_RTD_RESISTANCE_SPEC = ToolSpec(
    name="sensorcond_rtd_resistance",
    description=(
        "Callendar-Van Dusen forward model: RTD temperature → resistance.\n\n"
        "IEC 60751:2008:\n"
        "  T ≥ 0 °C: R(T) = R₀ × (1 + A×T + B×T²)\n"
        "  T < 0 °C: R(T) = R₀ × (1 + A×T + B×T² + C×(T−100)×T³)\n\n"
        "Default coefficients for platinum PT100 (IEC 60751):\n"
        "  A = 3.9083e-3 °C⁻¹, B = −5.775e-7 °C⁻², C = −4.183e-12 °C⁻⁴\n\n"
        "Valid range: −200 °C to +850 °C.  A warning is issued outside this range.\n\n"
        "Input: { temperature_c, r0_ohm? }\n"
        "Returns: { ok, temperature_c, resistance_ohm }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "temperature_c": {
                "type": "number",
                "description": "Temperature [°C].",
            },
            "r0_ohm": {
                "type": "number",
                "description": "RTD resistance at 0 °C [Ω] (default 100.0 for PT100).",
            },
        },
        "required": ["temperature_c"],
    },
)


@register(_RTD_RESISTANCE_SPEC, write=False)
async def sensorcond_rtd_resistance(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = rtd_resistance(
        temperature_c=a.get("temperature_c"),
        r0_ohm=a.get("r0_ohm", 100.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. sensorcond_rtd_temperature
# ═══════════════════════════════════════════════════════════════════════════════

_RTD_TEMPERATURE_SPEC = ToolSpec(
    name="sensorcond_rtd_temperature",
    description=(
        "Callendar-Van Dusen inverse model: RTD resistance → temperature.\n\n"
        "For T ≥ 0 °C: closed-form quadratic solution.\n"
        "For T < 0 °C: Newton-Raphson iteration with cubic C term.\n\n"
        "Default coefficients: IEC 60751 PT100 (R₀ = 100 Ω, A = 3.9083e-3).\n\n"
        "Input: { resistance_ohm, r0_ohm? }\n"
        "Returns: { ok, resistance_ohm, r0_ohm, temperature_c }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "resistance_ohm": {
                "type": "number",
                "description": "Measured RTD resistance [Ω].",
            },
            "r0_ohm": {
                "type": "number",
                "description": "RTD resistance at 0 °C [Ω] (default 100.0 for PT100).",
            },
        },
        "required": ["resistance_ohm"],
    },
)


@register(_RTD_TEMPERATURE_SPEC, write=False)
async def sensorcond_rtd_temperature(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = rtd_temperature(
        resistance_ohm=a.get("resistance_ohm"),
        r0_ohm=a.get("r0_ohm", 100.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. sensorcond_rtd_lead_wire
# ═══════════════════════════════════════════════════════════════════════════════

_RTD_LEAD_WIRE_SPEC = ToolSpec(
    name="sensorcond_rtd_lead_wire",
    description=(
        "Compute RTD lead-wire resistance error and corrected resistance.\n\n"
        "2-wire: both leads add to measurement (R_error = 2 × R_lead).\n"
        "3-wire: Kelvin connection cancels lead resistance (ideal: R_error ≈ 0).\n"
        "4-wire: zero lead resistance error.\n\n"
        "Temperature error estimate: ΔT ≈ R_error / (R₀ × α)  "
        "where α ≈ 3.85e-3 °C⁻¹.\n\n"
        "A warning is issued for 2-wire errors > 0.5 °C.\n\n"
        "Input: { measurement_resistance_ohm, lead_resistance_ohm, wiring?, r0_ohm? }\n"
        "Returns: { ok, r_error_ohm, temperature_error_c, corrected_resistance_ohm }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "measurement_resistance_ohm": {
                "type": "number",
                "description": "Raw measured resistance [Ω].",
            },
            "lead_resistance_ohm": {
                "type": "number",
                "description": "Resistance of one lead wire [Ω].",
            },
            "wiring": {
                "type": "string",
                "enum": ["2-wire", "3-wire", "4-wire"],
                "description": "RTD wiring configuration (default '3-wire').",
            },
            "r0_ohm": {
                "type": "number",
                "description": "RTD resistance at 0 °C [Ω] (default 100.0).",
            },
        },
        "required": ["measurement_resistance_ohm", "lead_resistance_ohm"],
    },
)


@register(_RTD_LEAD_WIRE_SPEC, write=False)
async def sensorcond_rtd_lead_wire(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = rtd_lead_wire_error(
        measurement_resistance_ohm=a.get("measurement_resistance_ohm"),
        lead_resistance_ohm=a.get("lead_resistance_ohm"),
        wiring=a.get("wiring", "3-wire"),
        r0_ohm=a.get("r0_ohm", 100.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. sensorcond_thermocouple
# ═══════════════════════════════════════════════════════════════════════════════

_TC_SPEC = ToolSpec(
    name="sensorcond_thermocouple",
    description=(
        "Convert thermocouple EMF [mV] to temperature [°C] using the NIST ITS-90 "
        "inverse polynomial, with cold-junction compensation.\n\n"
        "Supported types: J, K, T, E, N, S, R, B.\n\n"
        "Cold-junction compensation is applied using a linear Seebeck coefficient "
        "approximation around 0 °C.  A warning is issued when the cold-junction "
        "temperature exceeds ±5 °C (linear CJC may introduce ~0.5 °C error).\n\n"
        "Input: { voltage_mv, tc_type, cold_junction_temp_c? }\n"
        "Returns: { ok, tc_type, temperature_c, cjc_voltage_mv, effective_voltage_mv }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "voltage_mv": {
                "type": "number",
                "description": "Measured thermocouple EMF [mV].",
            },
            "tc_type": {
                "type": "string",
                "enum": ["J", "K", "T", "E", "N", "S", "R", "B"],
                "description": "Thermocouple type.",
            },
            "cold_junction_temp_c": {
                "type": "number",
                "description": "Cold-junction (reference) temperature [°C] (default 0).",
            },
        },
        "required": ["voltage_mv", "tc_type"],
    },
)


@register(_TC_SPEC, write=False)
async def sensorcond_thermocouple(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = thermocouple_temperature(
        voltage_mv=a.get("voltage_mv"),
        tc_type=a.get("tc_type"),
        cold_junction_temp_c=a.get("cold_junction_temp_c", 0.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. sensorcond_ina_gain
# ═══════════════════════════════════════════════════════════════════════════════

_INA_GAIN_SPEC = ToolSpec(
    name="sensorcond_ina_gain",
    description=(
        "Compute instrumentation amplifier gain and total input-referred error.\n\n"
        "Three-op-amp INA:  G = 1 + 2 × R_internal / R_gain\n\n"
        "Error sources (all input-referred):\n"
        "  e_offset  = V_os [µV]\n"
        "  e_cmrr    = V_cm / CMRR [µV]\n"
        "  e_drift   = V_os × G × gain_drift_ppm_c × ΔT [µV]\n"
        "  e_total   = RSS(e_offset, e_cmrr, e_drift)\n\n"
        "CMRR-limited warning issued when e_cmrr > e_offset.\n\n"
        "Input: { r_gain_ohm, r_internal_ohm?, gain_error_pct?, offset_voltage_uv?, "
        "cmrr_db?, common_mode_v?, gain_drift_ppm_c?, temperature_delta_c? }\n"
        "Returns: { ok, gain, e_offset_uv, e_cmrr_uv, e_total_rms_uv, cmrr_limited }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r_gain_ohm": {
                "type": "number",
                "description": "External gain-setting resistor [Ω].",
            },
            "r_internal_ohm": {
                "type": "number",
                "description": "Internal resistor pair [Ω] (default 49.4 kΩ for INA128).",
            },
            "gain_error_pct": {
                "type": "number",
                "description": "Initial gain error [%] (default 0.5%).",
            },
            "offset_voltage_uv": {
                "type": "number",
                "description": "Input offset voltage [µV] (default 50 µV).",
            },
            "cmrr_db": {
                "type": "number",
                "description": "CMRR [dB] (default 80 dB).",
            },
            "common_mode_v": {
                "type": "number",
                "description": "Common-mode voltage at inputs [V] (default 0).",
            },
            "gain_drift_ppm_c": {
                "type": "number",
                "description": "Gain temperature coefficient [ppm/°C] (default 10).",
            },
            "temperature_delta_c": {
                "type": "number",
                "description": "Temperature change from calibration [°C] (default 25).",
            },
        },
        "required": ["r_gain_ohm"],
    },
)


@register(_INA_GAIN_SPEC, write=False)
async def sensorcond_ina_gain(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = instrumentation_amp_gain(
        r_gain_ohm=a.get("r_gain_ohm"),
        r_internal_ohm=a.get("r_internal_ohm", 49.4e3),
        gain_error_pct=a.get("gain_error_pct", 0.5),
        offset_voltage_uv=a.get("offset_voltage_uv", 50.0),
        cmrr_db=a.get("cmrr_db", 80.0),
        common_mode_v=a.get("common_mode_v", 0.0),
        gain_drift_ppm_c=a.get("gain_drift_ppm_c", 10.0),
        temperature_delta_c=a.get("temperature_delta_c", 25.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. sensorcond_adc_bits
# ═══════════════════════════════════════════════════════════════════════════════

_ADC_BITS_SPEC = ToolSpec(
    name="sensorcond_adc_bits",
    description=(
        "Compute the minimum ADC bit-width for a target measurement resolution.\n\n"
        "  N_bits ≥ ceil(log2(FSR / target_resolution))\n\n"
        "A warning is issued when ≥ 24 bits are required "
        "(design is typically noise-limited before bitwidth-limited).\n\n"
        "Input: { full_scale_range_v, target_resolution_mv }\n"
        "Returns: { ok, ideal_bits, recommended_bits, lsb_size_mv }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "full_scale_range_v": {
                "type": "number",
                "description": "ADC full-scale input range [V].",
            },
            "target_resolution_mv": {
                "type": "number",
                "description": "Required measurement resolution [mV].",
            },
        },
        "required": ["full_scale_range_v", "target_resolution_mv"],
    },
)


@register(_ADC_BITS_SPEC, write=False)
async def sensorcond_adc_bits(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = adc_required_bits(
        full_scale_range_v=a.get("full_scale_range_v"),
        target_resolution_mv=a.get("target_resolution_mv"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. sensorcond_enob
# ═══════════════════════════════════════════════════════════════════════════════

_ENOB_SPEC = ToolSpec(
    name="sensorcond_enob",
    description=(
        "Compute Effective Number of Bits (ENOB) from input-referred RMS noise.\n\n"
        "  ENOB = log2(FSR / (V_noise_rms × √12))\n\n"
        "Warnings are issued when ENOB < 10 (noise-limited) or > 24 (suspect inputs).\n\n"
        "Input: { noise_rms_uv, full_scale_range_v }\n"
        "Returns: { ok, enob }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "noise_rms_uv": {
                "type": "number",
                "description": "Input-referred RMS noise [µV].",
            },
            "full_scale_range_v": {
                "type": "number",
                "description": "ADC full-scale input range [V].",
            },
        },
        "required": ["noise_rms_uv", "full_scale_range_v"],
    },
)


@register(_ENOB_SPEC, write=False)
async def sensorcond_enob(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = enob_from_noise(
        noise_rms_uv=a.get("noise_rms_uv"),
        full_scale_range_v=a.get("full_scale_range_v"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. sensorcond_antialias_corner
# ═══════════════════════════════════════════════════════════════════════════════

_AAF_CORNER_SPEC = ToolSpec(
    name="sensorcond_antialias_corner",
    description=(
        "Recommend the anti-alias filter −3 dB corner frequency for an ADC.\n\n"
        "Uses Butterworth roll-off approximation:\n"
        "  fc = f_nyq / 10^(A_stop / (20 × N))\n\n"
        "A warning is issued when fc < fs/4 (filter is cutting into the usable band).\n\n"
        "Input: { sample_rate_hz, stopband_attenuation_db?, filter_order? }\n"
        "Returns: { ok, nyquist_hz, filter_corner_hz, bandwidth_ratio }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sample_rate_hz": {
                "type": "number",
                "description": "ADC sample rate [Hz].",
            },
            "stopband_attenuation_db": {
                "type": "number",
                "description": "Required attenuation at Nyquist [dB] (default 40 dB).",
            },
            "filter_order": {
                "type": "integer",
                "description": "Filter order N (default 2).",
            },
        },
        "required": ["sample_rate_hz"],
    },
)


@register(_AAF_CORNER_SPEC, write=False)
async def sensorcond_antialias_corner(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = antialias_filter_corner(
        sample_rate_hz=a.get("sample_rate_hz"),
        stopband_attenuation_db=a.get("stopband_attenuation_db", 40.0),
        filter_order=int(a.get("filter_order", 2)),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. sensorcond_4_20ma_scale
# ═══════════════════════════════════════════════════════════════════════════════

_LOOP_SCALE_SPEC = ToolSpec(
    name="sensorcond_4_20ma_scale",
    description=(
        "Scale a 4-20 mA loop current to engineering units.\n\n"
        "  value = span_low + (I − 4) / 16 × (span_high − span_low)\n\n"
        "A warning is issued when current is outside [3.8, 20.5] mA "
        "(indicates open-circuit or over-range fault).\n\n"
        "Input: { current_ma, span_low, span_high }\n"
        "Returns: { ok, fraction, value }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "current_ma": {
                "type": "number",
                "description": "Loop current [mA].",
            },
            "span_low": {
                "type": "number",
                "description": "Engineering-unit value at 4 mA.",
            },
            "span_high": {
                "type": "number",
                "description": "Engineering-unit value at 20 mA.",
            },
        },
        "required": ["current_ma", "span_low", "span_high"],
    },
)


@register(_LOOP_SCALE_SPEC, write=False)
async def sensorcond_4_20ma_scale(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = loop_4_20ma_scaling(
        current_ma=a.get("current_ma"),
        span_low=a.get("span_low"),
        span_high=a.get("span_high"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. sensorcond_burden_voltage
# ═══════════════════════════════════════════════════════════════════════════════

_BURDEN_SPEC = ToolSpec(
    name="sensorcond_burden_voltage",
    description=(
        "Compute 4-20 mA loop burden voltage and compliance headroom.\n\n"
        "  V_burden = I × R_burden\n"
        "  V_available = V_supply − V_burden\n"
        "  compliance_margin = V_available − V_min_transmitter\n\n"
        "A warning is issued when compliance margin < 1 V.\n\n"
        "Input: { current_ma, burden_resistance_ohm, supply_voltage_v, "
        "transmitter_min_compliance_v? }\n"
        "Returns: { ok, v_burden_v, v_available_v, compliance_margin_v, compliant }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "current_ma": {
                "type": "number",
                "description": "Loop current [mA].",
            },
            "burden_resistance_ohm": {
                "type": "number",
                "description": "Total series burden resistance [Ω].",
            },
            "supply_voltage_v": {
                "type": "number",
                "description": "Loop supply voltage [V].",
            },
            "transmitter_min_compliance_v": {
                "type": "number",
                "description": "Minimum transmitter compliance voltage [V] (default 3 V).",
            },
        },
        "required": ["current_ma", "burden_resistance_ohm", "supply_voltage_v"],
    },
)


@register(_BURDEN_SPEC, write=False)
async def sensorcond_burden_voltage(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = loop_burden_voltage(
        current_ma=a.get("current_ma"),
        burden_resistance_ohm=a.get("burden_resistance_ohm"),
        supply_voltage_v=a.get("supply_voltage_v"),
        transmitter_min_compliance_v=a.get("transmitter_min_compliance_v", 3.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. sensorcond_noise_rss
# ═══════════════════════════════════════════════════════════════════════════════

_NOISE_RSS_SPEC = ToolSpec(
    name="sensorcond_noise_rss",
    description=(
        "Compute root-sum-of-squares (RSS) noise budget from a list of "
        "independent noise sources.\n\n"
        "  V_total_rms = sqrt(V₁² + V₂² + ... + Vₙ²)\n\n"
        "A warning is issued when any single source dominates > 70% of the variance.\n\n"
        "Input: { noise_sources_uv: [n1, n2, ...] }\n"
        "Returns: { ok, total_rms_uv, dominant_source_index, dominant_source_fraction }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "noise_sources_uv": {
                "type": "array",
                "items": {"type": "number"},
                "description": "List of RMS noise amplitudes [µV] from independent sources.",
            },
        },
        "required": ["noise_sources_uv"],
    },
)


@register(_NOISE_RSS_SPEC, write=False)
async def sensorcond_noise_rss(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = noise_budget_rss(
        noise_sources_uv=a.get("noise_sources_uv"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 15. sensorcond_filter_topology
# ═══════════════════════════════════════════════════════════════════════════════

_TOPOLOGY_SPEC = ToolSpec(
    name="sensorcond_filter_topology",
    description=(
        "Recommend Sallen-Key (SK) or Multiple-Feedback (MFB) topology for a "
        "second-order active lowpass anti-alias filter.\n\n"
        "Rules (Horowitz & Hill §6.3 / TI SLOA049):\n"
        "  Sallen-Key preferred: G ≤ 3, Q ≤ 1, single-ended supply, non-inverting.\n"
        "  MFB preferred: G > 3, Q > 1, low-noise priority with high Q.\n\n"
        "Input: { gain, q_factor, supply_single_ended?, low_noise_priority? }\n"
        "Returns: { ok, recommended_topology, reasons, sk_score, mfb_score }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gain": {
                "type": "number",
                "description": "Required filter gain (absolute, ≥ 1).",
            },
            "q_factor": {
                "type": "number",
                "description": (
                    "Required Q factor (0.707 → Butterworth 2nd-order, "
                    "0.577 → Bessel, 1.0 → Chebyshev 3 dB)."
                ),
            },
            "supply_single_ended": {
                "type": "boolean",
                "description": "True if only a single-ended supply is available (default False).",
            },
            "low_noise_priority": {
                "type": "boolean",
                "description": "True if minimising noise is the primary design concern (default False).",
            },
        },
        "required": ["gain", "q_factor"],
    },
)


@register(_TOPOLOGY_SPEC, write=False)
async def sensorcond_filter_topology(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = filter_topology_select(
        gain=a.get("gain"),
        q_factor=a.get("q_factor"),
        supply_single_ended=bool(a.get("supply_single_ended", False)),
        low_noise_priority=bool(a.get("low_noise_priority", False)),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_BRIDGE_OUTPUT_SPEC.name,    _BRIDGE_OUTPUT_SPEC,    sensorcond_bridge_output),
    (_BRIDGE_EXCITATION_SPEC.name, _BRIDGE_EXCITATION_SPEC, sensorcond_bridge_excitation),
    (_STRAIN_STRESS_SPEC.name,    _STRAIN_STRESS_SPEC,    sensorcond_strain_to_stress),
    (_RTD_RESISTANCE_SPEC.name,   _RTD_RESISTANCE_SPEC,   sensorcond_rtd_resistance),
    (_RTD_TEMPERATURE_SPEC.name,  _RTD_TEMPERATURE_SPEC,  sensorcond_rtd_temperature),
    (_RTD_LEAD_WIRE_SPEC.name,    _RTD_LEAD_WIRE_SPEC,    sensorcond_rtd_lead_wire),
    (_TC_SPEC.name,               _TC_SPEC,               sensorcond_thermocouple),
    (_INA_GAIN_SPEC.name,         _INA_GAIN_SPEC,         sensorcond_ina_gain),
    (_ADC_BITS_SPEC.name,         _ADC_BITS_SPEC,         sensorcond_adc_bits),
    (_ENOB_SPEC.name,             _ENOB_SPEC,             sensorcond_enob),
    (_AAF_CORNER_SPEC.name,       _AAF_CORNER_SPEC,       sensorcond_antialias_corner),
    (_LOOP_SCALE_SPEC.name,       _LOOP_SCALE_SPEC,       sensorcond_4_20ma_scale),
    (_BURDEN_SPEC.name,           _BURDEN_SPEC,           sensorcond_burden_voltage),
    (_NOISE_RSS_SPEC.name,        _NOISE_RSS_SPEC,        sensorcond_noise_rss),
    (_TOPOLOGY_SPEC.name,         _TOPOLOGY_SPEC,         sensorcond_filter_topology),
]
