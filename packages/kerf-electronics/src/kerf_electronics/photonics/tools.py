"""
Optoelectronics LLM tools — @register wrappers for photonics/devices.py.

Provides twelve LLM-callable tools:

  photonics_wavelength_to_energy  — wavelength ↔ photon energy
  photonics_led_liv               — LED/laser L-I-V, WPE, EQE, thermal droop
  photonics_laser_threshold       — laser P-I above/below threshold
  photonics_photodiode_responsivity — responsivity from QE and λ
  photonics_photodiode_photocurrent — photocurrent from optical power
  photonics_photodiode_noise      — shot/dark/Johnson noise, SNR, NEP, D*
  photonics_photodiode_bandwidth  — RC and transit-time bandwidth
  photonics_tia_design            — TIA gain, noise, Cf, stability
  photonics_optocoupler           — CTR, current-transfer, speed vs Rload
  photonics_fiber_coupling        — mode/NA mismatch coupling efficiency
  photonics_solar_cell_iv         — single-diode model, Voc/Isc/FF/η
  photonics_tof_lidar             — ToF/LiDAR range, P_rx, SNR

All handlers follow the kerf never-raise contract:
  errors → {"ok": false, "reason": ...}
  never raise.

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.photonics.devices import (
    fiber_coupling_efficiency,
    laser_threshold,
    led_liv,
    optocoupler,
    photodiode_bandwidth,
    photodiode_noise,
    photodiode_photocurrent,
    photodiode_responsivity,
    solar_cell_iv,
    tia_design,
    tof_lidar,
    wavelength_to_photon_energy,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. photonics_wavelength_to_energy
# ═══════════════════════════════════════════════════════════════════════════════

_WL_TO_E_SPEC = ToolSpec(
    name="photonics_wavelength_to_energy",
    description=(
        "Convert optical wavelength to photon energy.\n\n"
        "E_photon [J] = h·c/λ;  E_photon [eV] = E_J / q\n\n"
        "Input: { wavelength_m }\n"
        "Returns: { ok, wavelength_nm, freq_hz, photon_energy_j, photon_energy_ev }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wavelength_m": {
                "type": "number",
                "description": "Optical wavelength [m] (e.g. 1550e-9 for 1550 nm).",
            },
        },
        "required": ["wavelength_m"],
    },
)


@register(_WL_TO_E_SPEC, write=False)
async def photonics_wavelength_to_energy(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = wavelength_to_photon_energy(wavelength_m=a.get("wavelength_m"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. photonics_led_liv
# ═══════════════════════════════════════════════════════════════════════════════

_LED_LIV_SPEC = ToolSpec(
    name="photonics_led_liv",
    description=(
        "LED / laser-diode L-I-V model.\n\n"
        "Computes optical output power, junction voltage, wall-plug efficiency (WPE), "
        "external quantum efficiency (EQE), wavelength↔photon energy, and thermal "
        "efficiency droop + wavelength shift.\n\n"
        "P_opt = slope_eff × (I − I_th)  [W]\n"
        "WPE = P_opt / (Vj × I)\n"
        "EQE = slope_eff × q / (h·f)  (if not provided)\n\n"
        "Warns when below threshold.  Never raises.\n\n"
        "Input: { current_a, wavelength_m, slope_efficiency_w_per_a, "
        "threshold_current_a?, vf_v?, series_resistance_ohm?, eqe?, "
        "thermal_droop_per_k?, wavelength_shift_nm_per_k?, delta_temp_k? }\n"
        "Returns: { ok, p_opt_w, vj_v, wpe, eqe, photon_energy_ev, "
        "below_threshold, warnings, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "current_a": {"type": "number", "description": "Drive current [A]."},
            "wavelength_m": {"type": "number", "description": "Nominal emission wavelength [m]."},
            "slope_efficiency_w_per_a": {
                "type": "number",
                "description": "Slope efficiency dP/dI [W/A].",
            },
            "threshold_current_a": {
                "type": "number",
                "description": "Threshold current [A] (0 for LED, >0 for laser diode). Default 0.",
            },
            "vf_v": {
                "type": "number",
                "description": "Forward voltage at operating current [V]. Default 2.0.",
            },
            "series_resistance_ohm": {
                "type": "number",
                "description": "Series resistance [Ω]. Default 0.",
            },
            "eqe": {
                "type": "number",
                "description": "External quantum efficiency ∈ (0,1] (if known; otherwise derived).",
            },
            "thermal_droop_per_k": {
                "type": "number",
                "description": "Relative efficiency droop per Kelvin [1/K]. Default 0.",
            },
            "wavelength_shift_nm_per_k": {
                "type": "number",
                "description": "Wavelength red-shift per Kelvin [nm/K]. Default 0.",
            },
            "delta_temp_k": {
                "type": "number",
                "description": "Junction temperature rise above reference [K]. Default 0.",
            },
        },
        "required": ["current_a", "wavelength_m", "slope_efficiency_w_per_a"],
    },
)


@register(_LED_LIV_SPEC, write=False)
async def photonics_led_liv(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = led_liv(
        current_a=a.get("current_a"),
        wavelength_m=a.get("wavelength_m"),
        slope_efficiency_w_per_a=a.get("slope_efficiency_w_per_a"),
        threshold_current_a=a.get("threshold_current_a", 0.0),
        vf_v=a.get("vf_v", 2.0),
        series_resistance_ohm=a.get("series_resistance_ohm", 0.0),
        eqe=a.get("eqe"),
        thermal_droop_per_k=a.get("thermal_droop_per_k", 0.0),
        wavelength_shift_nm_per_k=a.get("wavelength_shift_nm_per_k", 0.0),
        delta_temp_k=a.get("delta_temp_k", 0.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. photonics_laser_threshold
# ═══════════════════════════════════════════════════════════════════════════════

_LASER_TH_SPEC = ToolSpec(
    name="photonics_laser_threshold",
    description=(
        "Laser P-I relation above/below threshold.\n\n"
        "P_opt [W] = slope_eff × (I − I_th)  for I > I_th, else 0.\n"
        "Warns when below threshold.\n\n"
        "Input: { current_a, threshold_current_a, slope_efficiency_w_per_a }\n"
        "Returns: { ok, p_opt_w, above_threshold, overdrive_a }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "current_a": {"type": "number", "description": "Drive current [A]."},
            "threshold_current_a": {
                "type": "number",
                "description": "Threshold current I_th [A].",
            },
            "slope_efficiency_w_per_a": {
                "type": "number",
                "description": "Slope efficiency dP/dI [W/A] above threshold.",
            },
        },
        "required": ["current_a", "threshold_current_a", "slope_efficiency_w_per_a"],
    },
)


@register(_LASER_TH_SPEC, write=False)
async def photonics_laser_threshold(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = laser_threshold(
        current_a=a.get("current_a"),
        threshold_current_a=a.get("threshold_current_a"),
        slope_efficiency_w_per_a=a.get("slope_efficiency_w_per_a"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. photonics_photodiode_responsivity
# ═══════════════════════════════════════════════════════════════════════════════

_PD_RESP_SPEC = ToolSpec(
    name="photonics_photodiode_responsivity",
    description=(
        "Photodiode responsivity R [A/W] from external quantum efficiency and λ.\n\n"
        "R = EQE × q × λ / (h × c)\n\n"
        "At 1550 nm with QE=0.8: R ≈ 1.0 A/W.\n\n"
        "Input: { wavelength_m, quantum_efficiency? }\n"
        "Returns: { ok, responsivity_a_per_w, photon_energy_ev }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wavelength_m": {"type": "number", "description": "Wavelength [m]."},
            "quantum_efficiency": {
                "type": "number",
                "description": "External QE ∈ (0,1] (default 0.8).",
            },
        },
        "required": ["wavelength_m"],
    },
)


@register(_PD_RESP_SPEC, write=False)
async def photonics_photodiode_responsivity(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = photodiode_responsivity(
        wavelength_m=a.get("wavelength_m"),
        quantum_efficiency=a.get("quantum_efficiency", 0.8),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. photonics_photodiode_photocurrent
# ═══════════════════════════════════════════════════════════════════════════════

_PD_IPC_SPEC = ToolSpec(
    name="photonics_photodiode_photocurrent",
    description=(
        "Photocurrent from incident optical power and responsivity.\n\n"
        "I_ph [A] = R [A/W] × P_opt [W]\n\n"
        "Input: { optical_power_w, responsivity_a_per_w }\n"
        "Returns: { ok, photocurrent_a }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "optical_power_w": {"type": "number", "description": "Incident optical power [W]."},
            "responsivity_a_per_w": {
                "type": "number",
                "description": "Photodiode responsivity [A/W].",
            },
        },
        "required": ["optical_power_w", "responsivity_a_per_w"],
    },
)


@register(_PD_IPC_SPEC, write=False)
async def photonics_photodiode_photocurrent(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = photodiode_photocurrent(
        optical_power_w=a.get("optical_power_w"),
        responsivity_a_per_w=a.get("responsivity_a_per_w"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. photonics_photodiode_noise
# ═══════════════════════════════════════════════════════════════════════════════

_PD_NOISE_SPEC = ToolSpec(
    name="photonics_photodiode_noise",
    description=(
        "Photodiode noise analysis: shot, dark-current, thermal (Johnson) noise, "
        "SNR, NEP, and D*.\n\n"
        "i_shot = sqrt(2·q·I_ph·B)\n"
        "i_dark_shot = sqrt(2·q·I_dark·B)\n"
        "i_thermal = sqrt(4·k·T·B/R_L)\n"
        "i_noise = sqrt(i_shot² + i_dark_shot² + i_thermal²)\n"
        "SNR [dB] = 20·log10(I_ph/i_noise)\n"
        "NEP [W/√Hz] = i_noise / (R × √B)\n"
        "D* [cm·√Hz/W] for 1 mm² detector.\n\n"
        "Warns if SNR < snr_min_db.  Never raises.\n\n"
        "Input: { optical_power_w, responsivity_a_per_w, dark_current_a, "
        "bandwidth_hz, load_resistance_ohm, temp_k?, snr_min_db? }\n"
        "Returns: { ok, i_noise_rms_a, snr_db, nep_w_per_root_hz, "
        "d_star_cm_root_hz_per_w, snr_ok, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "optical_power_w": {"type": "number", "description": "Incident optical power [W]."},
            "responsivity_a_per_w": {"type": "number", "description": "Responsivity [A/W]."},
            "dark_current_a": {"type": "number", "description": "Dark current [A]."},
            "bandwidth_hz": {"type": "number", "description": "Noise bandwidth [Hz]."},
            "load_resistance_ohm": {
                "type": "number",
                "description": "Load/feedback resistance [Ω].",
            },
            "temp_k": {
                "type": "number",
                "description": "Temperature [K] (default 290 K).",
            },
            "snr_min_db": {
                "type": "number",
                "description": "Minimum acceptable SNR [dB]; warns if below (default 0).",
            },
        },
        "required": [
            "optical_power_w",
            "responsivity_a_per_w",
            "dark_current_a",
            "bandwidth_hz",
            "load_resistance_ohm",
        ],
    },
)


@register(_PD_NOISE_SPEC, write=False)
async def photonics_photodiode_noise(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = photodiode_noise(
        optical_power_w=a.get("optical_power_w"),
        responsivity_a_per_w=a.get("responsivity_a_per_w"),
        dark_current_a=a.get("dark_current_a"),
        bandwidth_hz=a.get("bandwidth_hz"),
        load_resistance_ohm=a.get("load_resistance_ohm"),
        temp_k=a.get("temp_k", 290.0),
        snr_min_db=a.get("snr_min_db", 0.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. photonics_photodiode_bandwidth
# ═══════════════════════════════════════════════════════════════════════════════

_PD_BW_SPEC = ToolSpec(
    name="photonics_photodiode_bandwidth",
    description=(
        "Photodiode -3 dB bandwidth from RC time constant and transit time.\n\n"
        "f_RC = 1/(2π·C_j·R_L)\n"
        "f_transit = 0.45/τ_tr\n"
        "f_3dB = 1/sqrt(1/f_RC² + 1/f_tr²)  (quadrature addition)\n\n"
        "Input: { junction_capacitance_f, load_resistance_ohm, transit_time_s? }\n"
        "Returns: { ok, f_rc_hz, f_transit_hz?, f_3db_hz, rc_limited, transit_limited }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "junction_capacitance_f": {
                "type": "number",
                "description": "Junction/total input capacitance [F].",
            },
            "load_resistance_ohm": {
                "type": "number",
                "description": "Load or feedback resistance [Ω].",
            },
            "transit_time_s": {
                "type": "number",
                "description": "Carrier transit time [s] (optional).",
            },
        },
        "required": ["junction_capacitance_f", "load_resistance_ohm"],
    },
)


@register(_PD_BW_SPEC, write=False)
async def photonics_photodiode_bandwidth(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = photodiode_bandwidth(
        junction_capacitance_f=a.get("junction_capacitance_f"),
        load_resistance_ohm=a.get("load_resistance_ohm"),
        transit_time_s=a.get("transit_time_s"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. photonics_tia_design
# ═══════════════════════════════════════════════════════════════════════════════

_TIA_SPEC = ToolSpec(
    name="photonics_tia_design",
    description=(
        "Transimpedance amplifier (TIA) design: gain, input-referred noise, "
        "feedback capacitor for stability, and bandwidth.\n\n"
        "Noise contributions:\n"
        "  i_Rf  = sqrt(4·k·T·B/Rf)          [Johnson noise of Rf]\n"
        "  i_en  ≈ en × 2π × Cd × sqrt(B³/3) [en integrated over f²·Cd² spectrum]\n"
        "  i_in  = in × sqrt(B)               [op-amp current noise]\n"
        "  i_total = sqrt(i_Rf² + i_en² + i_in²)\n\n"
        "Feedback capacitor for stability:\n"
        "  Cf = sqrt(Cd / (2π·GBW·Rf)) × pm_factor\n\n"
        "Warns if TIA unstable or large BW mismatch.\n\n"
        "Input: { feedback_resistance_ohm, diode_capacitance_f, "
        "opamp_voltage_noise_v_per_root_hz, opamp_current_noise_a_per_root_hz, "
        "bandwidth_hz, temp_k?, phase_margin_deg? }\n"
        "Returns: { ok, transimpedance_gain_ohm, i_total_noise_rms_a, "
        "cf_stability_f, f_3db_hz, tia_stable, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "feedback_resistance_ohm": {
                "type": "number",
                "description": "Feedback resistor Rf [Ω].",
            },
            "diode_capacitance_f": {
                "type": "number",
                "description": "Total input capacitance Cd [F].",
            },
            "opamp_voltage_noise_v_per_root_hz": {
                "type": "number",
                "description": "Op-amp voltage noise en [V/√Hz].",
            },
            "opamp_current_noise_a_per_root_hz": {
                "type": "number",
                "description": "Op-amp current noise in [A/√Hz].",
            },
            "bandwidth_hz": {
                "type": "number",
                "description": "Target signal bandwidth [Hz].",
            },
            "temp_k": {
                "type": "number",
                "description": "Temperature [K] (default 290 K).",
            },
            "phase_margin_deg": {
                "type": "number",
                "description": "Target phase margin [°] (default 60°).",
            },
        },
        "required": [
            "feedback_resistance_ohm",
            "diode_capacitance_f",
            "opamp_voltage_noise_v_per_root_hz",
            "opamp_current_noise_a_per_root_hz",
            "bandwidth_hz",
        ],
    },
)


@register(_TIA_SPEC, write=False)
async def photonics_tia_design(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = tia_design(
        feedback_resistance_ohm=a.get("feedback_resistance_ohm"),
        diode_capacitance_f=a.get("diode_capacitance_f"),
        opamp_voltage_noise_v_per_root_hz=a.get("opamp_voltage_noise_v_per_root_hz"),
        opamp_current_noise_a_per_root_hz=a.get("opamp_current_noise_a_per_root_hz"),
        bandwidth_hz=a.get("bandwidth_hz"),
        temp_k=a.get("temp_k", 290.0),
        phase_margin_deg=a.get("phase_margin_deg", 60.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. photonics_optocoupler
# ═══════════════════════════════════════════════════════════════════════════════

_OPTO_SPEC = ToolSpec(
    name="photonics_optocoupler",
    description=(
        "Optocoupler: CTR (current-transfer ratio), output current, voltage, "
        "propagation delay, and speed vs load resistance.\n\n"
        "I_out = (CTR/100) × I_F\n"
        "V_out = min(Vcc, I_out × R_load)\n"
        "Bandwidth scales as 1/R_load (from reference 1 kΩ).\n\n"
        "Input: { if_ma, ctr_percent, vcc_v, rload_ohm, "
        "bandwidth_hz?, propagation_delay_ns? }\n"
        "Returns: { ok, i_out_a, v_out_v, saturated, "
        "bandwidth_hz_at_rload (if bandwidth_hz given), ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "if_ma": {"type": "number", "description": "LED forward current [mA]."},
            "ctr_percent": {
                "type": "number",
                "description": "Current transfer ratio CTR [%].",
            },
            "vcc_v": {
                "type": "number",
                "description": "Collector supply voltage [V].",
            },
            "rload_ohm": {
                "type": "number",
                "description": "Collector load resistance [Ω].",
            },
            "bandwidth_hz": {
                "type": "number",
                "description": "Datasheet bandwidth at 1 kΩ reference [Hz] (optional).",
            },
            "propagation_delay_ns": {
                "type": "number",
                "description": "Typical propagation delay [ns] (default 0).",
            },
        },
        "required": ["if_ma", "ctr_percent", "vcc_v", "rload_ohm"],
    },
)


@register(_OPTO_SPEC, write=False)
async def photonics_optocoupler(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = optocoupler(
        if_ma=a.get("if_ma"),
        ctr_percent=a.get("ctr_percent"),
        vcc_v=a.get("vcc_v"),
        rload_ohm=a.get("rload_ohm"),
        bandwidth_hz=a.get("bandwidth_hz"),
        propagation_delay_ns=a.get("propagation_delay_ns", 0.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. photonics_fiber_coupling
# ═══════════════════════════════════════════════════════════════════════════════

_FIBER_COUP_SPEC = ToolSpec(
    name="photonics_fiber_coupling",
    description=(
        "Fiber coupling efficiency from mode-field and NA mismatch.\n\n"
        "Mode overlap (Gaussian): η_mode = (2·ws·wf/(ws²+wf²))²\n"
        "NA mismatch: η_NA = (fiber_NA/source_NA)² when source_NA > fiber_NA, else 1\n"
        "Total: η = η_mode × η_NA\n"
        "Coupling loss [dB] = −10·log10(η)\n\n"
        "Input: { source_na, fiber_na, source_mode_diameter_m, fiber_mode_diameter_m }\n"
        "Returns: { ok, coupling_efficiency, coupling_loss_db, "
        "mode_overlap_efficiency, na_efficiency }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "source_na": {"type": "number", "description": "Source numerical aperture."},
            "fiber_na": {"type": "number", "description": "Fiber numerical aperture."},
            "source_mode_diameter_m": {
                "type": "number",
                "description": "Source mode-field diameter [m].",
            },
            "fiber_mode_diameter_m": {
                "type": "number",
                "description": "Fiber mode-field diameter [m].",
            },
        },
        "required": [
            "source_na", "fiber_na",
            "source_mode_diameter_m", "fiber_mode_diameter_m",
        ],
    },
)


@register(_FIBER_COUP_SPEC, write=False)
async def photonics_fiber_coupling(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = fiber_coupling_efficiency(
        source_na=a.get("source_na"),
        fiber_na=a.get("fiber_na"),
        source_mode_diameter_m=a.get("source_mode_diameter_m"),
        fiber_mode_diameter_m=a.get("fiber_mode_diameter_m"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. photonics_solar_cell_iv
# ═══════════════════════════════════════════════════════════════════════════════

_SOLAR_SPEC = ToolSpec(
    name="photonics_solar_cell_iv",
    description=(
        "Solar cell I-V characteristics: single-diode model with series and shunt "
        "resistance.\n\n"
        "I = Isc − I0×(exp((V+I·Rs)/(n·Vt))−1) − (V+I·Rs)/Rsh\n"
        "Vt = k·T/q\n"
        "FF ≈ (v_oc_norm − ln(v_oc_norm + 0.72)) / (v_oc_norm + 1)  [Green 1982]\n"
        "Efficiency η = Pmpp / (irradiance × area)\n\n"
        "Warns if efficiency exceeds physical limits.  Never raises.\n\n"
        "Input: { isc_a, voc_v, ideality_factor?, series_resistance_ohm?, "
        "shunt_resistance_ohm?, temp_k?, irradiance_w_per_m2?, cell_area_m2? }\n"
        "Returns: { ok, ff, pmpp_w, vmpp_v, impp_a, efficiency, vt_v, i0_a }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "isc_a": {"type": "number", "description": "Short-circuit current [A]."},
            "voc_v": {"type": "number", "description": "Open-circuit voltage [V]."},
            "ideality_factor": {
                "type": "number",
                "description": "Diode ideality factor n (default 1.0).",
            },
            "series_resistance_ohm": {
                "type": "number",
                "description": "Series resistance Rs [Ω] (default 0).",
            },
            "shunt_resistance_ohm": {
                "type": "number",
                "description": "Shunt resistance Rsh [Ω] (default 1 MΩ).",
            },
            "temp_k": {
                "type": "number",
                "description": "Cell temperature [K] (default 300 K).",
            },
            "irradiance_w_per_m2": {
                "type": "number",
                "description": "Incident irradiance [W/m²] (default 1000 = 1-sun).",
            },
            "cell_area_m2": {
                "type": "number",
                "description": "Cell area [m²] (default 1 cm² = 1e-4 m²).",
            },
        },
        "required": ["isc_a", "voc_v"],
    },
)


@register(_SOLAR_SPEC, write=False)
async def photonics_solar_cell_iv(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = solar_cell_iv(
        isc_a=a.get("isc_a"),
        voc_v=a.get("voc_v"),
        ideality_factor=a.get("ideality_factor", 1.0),
        series_resistance_ohm=a.get("series_resistance_ohm", 0.0),
        shunt_resistance_ohm=a.get("shunt_resistance_ohm", 1e6),
        temp_k=a.get("temp_k", 300.0),
        irradiance_w_per_m2=a.get("irradiance_w_per_m2", 1000.0),
        cell_area_m2=a.get("cell_area_m2", 1e-4),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. photonics_tof_lidar
# ═══════════════════════════════════════════════════════════════════════════════

_TOF_SPEC = ToolSpec(
    name="photonics_tof_lidar",
    description=(
        "Time-of-Flight (ToF) / LiDAR: received power, photocurrent, SNR, "
        "and maximum range.\n\n"
        "Lidar equation (Lambertian target):\n"
        "  P_rx = P_tx × ρ × A_rx / (π·R²) × T_atm²\n"
        "  T_atm = 10^(−α·R/(10×1000))  [one-way]\n\n"
        "Range limit: R_max ≈ R × (SNR/SNR_min)^0.25 (thermal-noise limited)\n"
        "ToF: d = c·Δt/2\n\n"
        "Warns if SNR < snr_min_db.  Never raises.\n\n"
        "Input: { peak_power_w, target_reflectivity, target_distance_m, "
        "aperture_diameter_m, receiver_responsivity_a_per_w, dark_current_a, "
        "bandwidth_hz, load_resistance_ohm, beam_divergence_rad?, "
        "atmospheric_loss_db_per_km?, temp_k?, snr_min_db? }\n"
        "Returns: { ok, p_rx_w, snr_db, snr_ok, range_limit_m, tof_s }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "peak_power_w": {"type": "number", "description": "Transmit peak power [W]."},
            "target_reflectivity": {
                "type": "number",
                "description": "Target reflectivity ρ ∈ (0, 1].",
            },
            "target_distance_m": {
                "type": "number",
                "description": "Target distance [m].",
            },
            "aperture_diameter_m": {
                "type": "number",
                "description": "Receiver aperture diameter [m].",
            },
            "receiver_responsivity_a_per_w": {
                "type": "number",
                "description": "Receiver responsivity [A/W].",
            },
            "dark_current_a": {
                "type": "number",
                "description": "Dark current [A].",
            },
            "bandwidth_hz": {
                "type": "number",
                "description": "Receiver bandwidth [Hz].",
            },
            "load_resistance_ohm": {
                "type": "number",
                "description": "Load resistance [Ω].",
            },
            "beam_divergence_rad": {
                "type": "number",
                "description": "Beam half-angle divergence [rad] (default 1 mrad).",
            },
            "atmospheric_loss_db_per_km": {
                "type": "number",
                "description": "One-way atmospheric loss [dB/km] (default 0).",
            },
            "temp_k": {
                "type": "number",
                "description": "Temperature [K] (default 290 K).",
            },
            "snr_min_db": {
                "type": "number",
                "description": "Minimum required SNR [dB] (default 10 dB).",
            },
        },
        "required": [
            "peak_power_w", "target_reflectivity", "target_distance_m",
            "aperture_diameter_m", "receiver_responsivity_a_per_w",
            "dark_current_a", "bandwidth_hz", "load_resistance_ohm",
        ],
    },
)


@register(_TOF_SPEC, write=False)
async def photonics_tof_lidar(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = tof_lidar(
        peak_power_w=a.get("peak_power_w"),
        target_reflectivity=a.get("target_reflectivity"),
        target_distance_m=a.get("target_distance_m"),
        aperture_diameter_m=a.get("aperture_diameter_m"),
        receiver_responsivity_a_per_w=a.get("receiver_responsivity_a_per_w"),
        dark_current_a=a.get("dark_current_a"),
        bandwidth_hz=a.get("bandwidth_hz"),
        load_resistance_ohm=a.get("load_resistance_ohm"),
        beam_divergence_rad=a.get("beam_divergence_rad", 1e-3),
        atmospheric_loss_db_per_km=a.get("atmospheric_loss_db_per_km", 0.0),
        temp_k=a.get("temp_k", 290.0),
        snr_min_db=a.get("snr_min_db", 10.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_WL_TO_E_SPEC.name,      _WL_TO_E_SPEC,      photonics_wavelength_to_energy),
    (_LED_LIV_SPEC.name,      _LED_LIV_SPEC,      photonics_led_liv),
    (_LASER_TH_SPEC.name,     _LASER_TH_SPEC,     photonics_laser_threshold),
    (_PD_RESP_SPEC.name,      _PD_RESP_SPEC,      photonics_photodiode_responsivity),
    (_PD_IPC_SPEC.name,       _PD_IPC_SPEC,       photonics_photodiode_photocurrent),
    (_PD_NOISE_SPEC.name,     _PD_NOISE_SPEC,     photonics_photodiode_noise),
    (_PD_BW_SPEC.name,        _PD_BW_SPEC,        photonics_photodiode_bandwidth),
    (_TIA_SPEC.name,          _TIA_SPEC,          photonics_tia_design),
    (_OPTO_SPEC.name,         _OPTO_SPEC,         photonics_optocoupler),
    (_FIBER_COUP_SPEC.name,   _FIBER_COUP_SPEC,   photonics_fiber_coupling),
    (_SOLAR_SPEC.name,        _SOLAR_SPEC,        photonics_solar_cell_iv),
    (_TOF_SPEC.name,          _TOF_SPEC,          photonics_tof_lidar),
]
