"""
Audio electronics & loudspeaker design LLM tools.

Provides LLM-callable tools (registered via kerf_chat.tools.registry):

  audio_amp_class_a      — class-A power amplifier analysis
  audio_amp_class_b      — class-B push-pull amplifier analysis
  audio_amp_class_ab     — class-AB amplifier efficiency bounds
  audio_amp_class_d      — class-D switching amplifier + LC filter sizing
  audio_heatsink_rth     — heatsink thermal resistance for amplifier devices
  audio_sealed_box       — Thiele-Small sealed enclosure alignment
  audio_vented_box       — Thiele-Small vented (bass-reflex) enclosure alignment
  audio_driver_spl       — driver SPL sensitivity and max SPL
  audio_crossover        — passive crossover component values (1st–4th order BW/LR)
  audio_zobel            — Zobel (impedance compensation) RC network
  audio_lpad             — L-pad attenuator for loudspeaker level matching
  audio_damping_factor   — amplifier damping factor vs cable + driver Re
  audio_spl_add          — incoherent SPL addition
  audio_spl_distance     — SPL at new distance (inverse-square law)
  audio_db_voltage       — voltage ratio to dB conversion
  audio_db_power         — power ratio to dB conversion
  audio_a_weighting      — A-weighting correction at a frequency
  audio_impedance_bridge — line-level impedance bridging analysis

All handlers follow the kerf never-raise contract:
  errors → {"ok": false, "reason": ...}
  clipping / chuffing / over-excursion → warnings.warn

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.audio.design import (
    amp_class_a,
    amp_class_ab,
    amp_class_b,
    amp_class_d,
    a_weighting,
    damping_factor,
    db_power,
    db_voltage,
    driver_spl,
    heatsink_rth,
    impedance_bridging,
    lpad_attenuator,
    passive_crossover,
    sealed_box,
    spl_add,
    spl_distance,
    vented_box,
    zobel_network,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. audio_amp_class_a
# ═══════════════════════════════════════════════════════════════════════════════

_AMP_A_SPEC = ToolSpec(
    name="audio_amp_class_a",
    description=(
        "Class-A power amplifier analysis.\n\n"
        "Computes quiescent current, maximum output power, supply power, "
        "device dissipation (worst-case at zero signal), and theoretical "
        "efficiency (max 25%) for a single-ended class-A stage.\n\n"
        "Model: Self 'Audio Power Amplifier Design Handbook' (5th ed.) §2.2.\n\n"
        "Input: { vcc, rl, iq_factor? }\n"
        "Returns: { ok, iq_a, pout_max_w, psupply_w, pdiss_max_w, "
        "efficiency_max_pct, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vcc": {"type": "number", "description": "Supply voltage [V] (single-rail peak)."},
            "rl": {"type": "number", "description": "Load resistance [Ω]."},
            "iq_factor": {
                "type": "number",
                "description": "Quiescent current multiplier ≥ 1.0 (default 1.0 = minimum).",
            },
        },
        "required": ["vcc", "rl"],
    },
)


@register(_AMP_A_SPEC, write=False)
async def audio_amp_class_a(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = amp_class_a(
        vcc=a.get("vcc"),
        rl=a.get("rl"),
        iq_factor=a.get("iq_factor", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. audio_amp_class_b
# ═══════════════════════════════════════════════════════════════════════════════

_AMP_B_SPEC = ToolSpec(
    name="audio_amp_class_b",
    description=(
        "Class-B push-pull amplifier analysis.\n\n"
        "Computes maximum output power, supply power at full output, "
        "worst-case per-device dissipation (at Vpk = Vcc/π), and "
        "theoretical efficiency η_max = π/4 ≈ 78.54%.\n\n"
        "Model: Self §3.2 / Leach 'Introduction to Electroacoustics' §5.3.\n\n"
        "Input: { vcc, rl }\n"
        "Returns: { ok, pout_max_w, pdiss_per_device_max_w, efficiency_max_pct, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vcc": {"type": "number", "description": "Single-rail supply voltage [V]."},
            "rl": {"type": "number", "description": "Load resistance [Ω]."},
        },
        "required": ["vcc", "rl"],
    },
)


@register(_AMP_B_SPEC, write=False)
async def audio_amp_class_b(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = amp_class_b(vcc=a.get("vcc"), rl=a.get("rl"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. audio_amp_class_ab
# ═══════════════════════════════════════════════════════════════════════════════

_AMP_AB_SPEC = ToolSpec(
    name="audio_amp_class_ab",
    description=(
        "Class-AB amplifier efficiency bounds and output power estimate.\n\n"
        "Returns lower bound (class-A, 25%), upper bound (class-B, 78.54%), "
        "and a typical practical estimate (~60% of class-B bound).\n\n"
        "Input: { vcc, rl, vq? }\n"
        "Returns: { ok, pout_max_w, efficiency_lower_pct, efficiency_upper_pct, "
        "efficiency_estimate_pct, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vcc": {"type": "number", "description": "Supply voltage [V]."},
            "rl": {"type": "number", "description": "Load resistance [Ω]."},
            "vq": {
                "type": "number",
                "description": "Quiescent bias voltage [V] (default 0.65 V).",
            },
        },
        "required": ["vcc", "rl"],
    },
)


@register(_AMP_AB_SPEC, write=False)
async def audio_amp_class_ab(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = amp_class_ab(
        vcc=a.get("vcc"),
        rl=a.get("rl"),
        vq=a.get("vq", 0.65),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. audio_amp_class_d
# ═══════════════════════════════════════════════════════════════════════════════

_AMP_D_SPEC = ToolSpec(
    name="audio_amp_class_d",
    description=(
        "Class-D switching amplifier analysis and LC reconstruction filter sizing.\n\n"
        "Computes maximum output power, ideal efficiency (100%), dead-time switching "
        "loss, estimated practical efficiency, and 2nd-order Butterworth LC output "
        "filter component values (fb = fsw / 10).\n\n"
        "Input: { vcc, rl, fsw_hz, dead_time_ns?, lc_order? }\n"
        "Returns: { ok, pout_max_w, efficiency_ideal_pct, dead_time_loss_pct, "
        "efficiency_est_pct, filter_L_H, filter_C_F, filter_fb_hz, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vcc": {"type": "number", "description": "Supply voltage [V]."},
            "rl": {"type": "number", "description": "Load resistance [Ω]."},
            "fsw_hz": {"type": "number", "description": "Switching frequency [Hz]."},
            "dead_time_ns": {
                "type": "number",
                "description": "Half-bridge dead time [ns] (default 50 ns).",
            },
            "lc_order": {
                "type": "integer",
                "description": "LC filter order (currently only 2 supported).",
            },
        },
        "required": ["vcc", "rl", "fsw_hz"],
    },
)


@register(_AMP_D_SPEC, write=False)
async def audio_amp_class_d(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = amp_class_d(
        vcc=a.get("vcc"),
        rl=a.get("rl"),
        fsw_hz=a.get("fsw_hz"),
        dead_time_ns=a.get("dead_time_ns", 50.0),
        lc_order=a.get("lc_order", 2),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. audio_heatsink_rth
# ═══════════════════════════════════════════════════════════════════════════════

_HEATSINK_SPEC = ToolSpec(
    name="audio_heatsink_rth",
    description=(
        "Required heatsink thermal resistance (Rth_sa) for an amplifier power device.\n\n"
        "Model: Tj = Ta + Pdiss × (Rth_jc + Rth_cs + Rth_sa).\n"
        "Solves for Rth_sa given Tj_max, Ta, Rth_jc, Rth_cs, Pdiss.\n"
        "A warning is issued if Rth_sa < 0 (package alone cannot meet budget).\n\n"
        "Input: { pdiss_w, tj_max_c, ta_c, rth_jc, rth_cs? }\n"
        "Returns: { ok, rth_sa_required_c_per_w, tj_actual_c, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pdiss_w": {"type": "number", "description": "Device power dissipation [W]."},
            "tj_max_c": {"type": "number", "description": "Maximum junction temperature [°C]."},
            "ta_c": {"type": "number", "description": "Ambient temperature [°C]."},
            "rth_jc": {
                "type": "number",
                "description": "Junction-to-case thermal resistance [°C/W].",
            },
            "rth_cs": {
                "type": "number",
                "description": "Case-to-heatsink resistance [°C/W] (default 0.5).",
            },
        },
        "required": ["pdiss_w", "tj_max_c", "ta_c", "rth_jc"],
    },
)


@register(_HEATSINK_SPEC, write=False)
async def audio_heatsink_rth(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = heatsink_rth(
        pdiss_w=a.get("pdiss_w"),
        tj_max_c=a.get("tj_max_c"),
        ta_c=a.get("ta_c"),
        rth_jc=a.get("rth_jc"),
        rth_cs=a.get("rth_cs", 0.5),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. audio_sealed_box
# ═══════════════════════════════════════════════════════════════════════════════

_SEALED_SPEC = ToolSpec(
    name="audio_sealed_box",
    description=(
        "Thiele-Small sealed loudspeaker enclosure alignment.\n\n"
        "Calculates required box volume (Vb) for a target system Q (Qtc), "
        "system resonance fc, and −3 dB frequency f3.\n\n"
        "Common Qtc values: 0.5 (max flat group delay), 0.707 (Butterworth), "
        "1.0 (slight bass boost).\n\n"
        "Input: { vas_l, qts, fs_hz, qtc? }\n"
        "Returns: { ok, vb_l, fc_hz, f3_hz, alpha, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vas_l": {
                "type": "number",
                "description": "Equivalent compliance volume [litres].",
            },
            "qts": {"type": "number", "description": "Total driver Q at fs."},
            "fs_hz": {"type": "number", "description": "Driver free-air resonance [Hz]."},
            "qtc": {
                "type": "number",
                "description": "Target system Q (default 0.707 Butterworth).",
            },
        },
        "required": ["vas_l", "qts", "fs_hz"],
    },
)


@register(_SEALED_SPEC, write=False)
async def audio_sealed_box(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = sealed_box(
        vas_l=a.get("vas_l"),
        qts=a.get("qts"),
        fs_hz=a.get("fs_hz"),
        qtc=a.get("qtc", 0.707),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. audio_vented_box
# ═══════════════════════════════════════════════════════════════════════════════

_VENTED_SPEC = ToolSpec(
    name="audio_vented_box",
    description=(
        "Thiele-Small vented (bass-reflex) loudspeaker enclosure design.\n\n"
        "Supports QB3 and SBB4 alignments (Small 1973). Calculates box volume "
        "(Vb), port tuning frequency (fb), port length and air velocity.\n"
        "Issues a warning when port velocity exceeds 17 m/s (chuffing risk).\n\n"
        "Input: { vas_l, qts, fs_hz, re_ohm, sd_cm2, alignment?, port_diameter_mm? }\n"
        "Returns: { ok, vb_l, fb_hz, port_length_mm, port_velocity_mps, "
        "chuffing_warning, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vas_l": {"type": "number", "description": "Compliance volume [litres]."},
            "qts": {"type": "number", "description": "Total driver Q."},
            "fs_hz": {"type": "number", "description": "Driver resonance [Hz]."},
            "re_ohm": {"type": "number", "description": "Voice coil DC resistance [Ω]."},
            "sd_cm2": {"type": "number", "description": "Effective piston area [cm²]."},
            "alignment": {
                "type": "string",
                "enum": ["QB3", "SBB4"],
                "description": "Vented box alignment (default 'QB3').",
            },
            "port_diameter_mm": {
                "type": "number",
                "description": "Port tube diameter [mm] (default 50 mm).",
            },
        },
        "required": ["vas_l", "qts", "fs_hz", "re_ohm", "sd_cm2"],
    },
)


@register(_VENTED_SPEC, write=False)
async def audio_vented_box(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = vented_box(
        vas_l=a.get("vas_l"),
        qts=a.get("qts"),
        fs_hz=a.get("fs_hz"),
        re_ohm=a.get("re_ohm"),
        sd_cm2=a.get("sd_cm2"),
        alignment=a.get("alignment", "QB3"),
        port_diameter_mm=a.get("port_diameter_mm", 50.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. audio_driver_spl
# ═══════════════════════════════════════════════════════════════════════════════

_DRIVER_SPL_SPEC = ToolSpec(
    name="audio_driver_spl",
    description=(
        "Driver SPL at rated power and maximum excursion-limited SPL.\n\n"
        "SPL(P, d) = sensitivity + 10×log10(P) − 20×log10(d).\n"
        "Excursion-limited SPL (at 100 Hz, 1 m) uses piston far-field model.\n\n"
        "Input: { sensitivity_db_1w_1m, power_w, xmax_mm, sd_cm2, re_ohm, "
        "distance_m? }\n"
        "Returns: { ok, spl_at_rated_power_db, spl_excursion_limited_100hz_db, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sensitivity_db_1w_1m": {
                "type": "number",
                "description": "Driver sensitivity [dB SPL @ 1 W, 1 m].",
            },
            "power_w": {"type": "number", "description": "Rated input power [W]."},
            "xmax_mm": {"type": "number", "description": "Peak linear excursion [mm]."},
            "sd_cm2": {"type": "number", "description": "Effective piston area [cm²]."},
            "re_ohm": {"type": "number", "description": "Voice coil DC resistance [Ω]."},
            "distance_m": {
                "type": "number",
                "description": "Listening distance [m] (default 1.0 m).",
            },
        },
        "required": ["sensitivity_db_1w_1m", "power_w", "xmax_mm", "sd_cm2", "re_ohm"],
    },
)


@register(_DRIVER_SPL_SPEC, write=False)
async def audio_driver_spl(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = driver_spl(
        sensitivity_db_1w_1m=a.get("sensitivity_db_1w_1m"),
        power_w=a.get("power_w"),
        xmax_mm=a.get("xmax_mm"),
        sd_cm2=a.get("sd_cm2"),
        re_ohm=a.get("re_ohm"),
        distance_m=a.get("distance_m", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. audio_crossover
# ═══════════════════════════════════════════════════════════════════════════════

_XOVER_SPEC = ToolSpec(
    name="audio_crossover",
    description=(
        "Passive crossover component values for a resistive loudspeaker load.\n\n"
        "Supports Butterworth (1st–4th order) and Linkwitz-Riley (2nd, 4th order) "
        "topologies.\n"
        "Returns a list of series inductors (L) and shunt capacitors (C) in order.\n\n"
        "Input: { fc_hz, z_load, order?, topology? }\n"
        "Returns: { ok, components[], ... }\n"
        "Each component: { stage, type ('L'/'C'), value_H/value_mH or value_F/value_uF }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fc_hz": {"type": "number", "description": "Crossover frequency [Hz]."},
            "z_load": {
                "type": "number",
                "description": "Nominal load impedance [Ω] (assumed resistive).",
            },
            "order": {
                "type": "integer",
                "description": "Filter order: 1–4 (Butterworth) or 2, 4 (Linkwitz-Riley). Default 2.",
            },
            "topology": {
                "type": "string",
                "enum": ["butterworth", "linkwitz-riley"],
                "description": "Filter topology (default 'butterworth').",
            },
        },
        "required": ["fc_hz", "z_load"],
    },
)


@register(_XOVER_SPEC, write=False)
async def audio_crossover(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = passive_crossover(
        fc_hz=a.get("fc_hz"),
        z_load=a.get("z_load"),
        order=a.get("order", 2),
        topology=a.get("topology", "butterworth"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. audio_zobel
# ═══════════════════════════════════════════════════════════════════════════════

_ZOBEL_SPEC = ToolSpec(
    name="audio_zobel",
    description=(
        "Zobel (impedance compensation) RC network for a loudspeaker driver.\n\n"
        "Flattens the rising voice-coil inductance by placing Rz + Cz in series "
        "(shunted across driver terminals):\n"
        "  Rz = Re,  Cz = Le / Re²\n\n"
        "Input: { re_ohm, le_mh }\n"
        "Returns: { ok, rz_ohm, cz_uF, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "re_ohm": {"type": "number", "description": "Voice coil DC resistance [Ω]."},
            "le_mh": {"type": "number", "description": "Voice coil inductance [mH]."},
        },
        "required": ["re_ohm", "le_mh"],
    },
)


@register(_ZOBEL_SPEC, write=False)
async def audio_zobel(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = zobel_network(re_ohm=a.get("re_ohm"), le_mh=a.get("le_mh"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. audio_lpad
# ═══════════════════════════════════════════════════════════════════════════════

_LPAD_SPEC = ToolSpec(
    name="audio_lpad",
    description=(
        "L-pad attenuator resistor values for loudspeaker level matching.\n\n"
        "Computes series resistor Rs and shunt resistor Rp to attenuate the "
        "signal by the specified amount while maintaining nominal load impedance.\n\n"
        "Input: { attenuation_db, z_source, z_load }\n"
        "Returns: { ok, rs_ohm, rp_ohm, actual_attenuation_db, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "attenuation_db": {
                "type": "number",
                "description": "Desired attenuation [dB] (positive = reduce level).",
            },
            "z_source": {"type": "number", "description": "Source impedance [Ω]."},
            "z_load": {"type": "number", "description": "Load impedance [Ω]."},
        },
        "required": ["attenuation_db", "z_source", "z_load"],
    },
)


@register(_LPAD_SPEC, write=False)
async def audio_lpad(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = lpad_attenuator(
        attenuation_db=a.get("attenuation_db"),
        z_source=a.get("z_source"),
        z_load=a.get("z_load"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. audio_damping_factor
# ═══════════════════════════════════════════════════════════════════════════════

_DF_SPEC = ToolSpec(
    name="audio_damping_factor",
    description=(
        "Amplifier damping factor considering output impedance and cable resistance.\n\n"
        "  DF = Re / (Zout + R_cable)\n\n"
        "Issues a warning when DF < 10 (impaired cone control).\n\n"
        "Input: { amp_zout_ohm, re_ohm, cable_r_ohm? }\n"
        "Returns: { ok, damping_factor, quality_note, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "amp_zout_ohm": {
                "type": "number",
                "description": "Amplifier output impedance [Ω].",
            },
            "re_ohm": {
                "type": "number",
                "description": "Driver DC voice coil resistance [Ω].",
            },
            "cable_r_ohm": {
                "type": "number",
                "description": "Cable resistance (round trip) [Ω] (default 0.1 Ω).",
            },
        },
        "required": ["amp_zout_ohm", "re_ohm"],
    },
)


@register(_DF_SPEC, write=False)
async def audio_damping_factor(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = damping_factor(
        amp_zout_ohm=a.get("amp_zout_ohm"),
        re_ohm=a.get("re_ohm"),
        cable_r_ohm=a.get("cable_r_ohm", 0.1),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. audio_spl_add
# ═══════════════════════════════════════════════════════════════════════════════

_SPL_ADD_SPEC = ToolSpec(
    name="audio_spl_add",
    description=(
        "Add multiple incoherent SPL sources.\n\n"
        "  SPL_total = 10 × log10(Σ 10^(SPLi / 10))\n\n"
        "Input: { spl_values_db: [val1, val2, ...] }\n"
        "Returns: { ok, spl_total_db, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "spl_values_db": {
                "type": "array",
                "items": {"type": "number"},
                "description": "List of SPL values [dB] to add (at least 2).",
                "minItems": 2,
            },
        },
        "required": ["spl_values_db"],
    },
)


@register(_SPL_ADD_SPEC, write=False)
async def audio_spl_add(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    vals = a.get("spl_values_db")
    if not isinstance(vals, list) or len(vals) < 2:
        return err_payload("spl_values_db must be a list with at least 2 values", "BAD_ARGS")
    result = spl_add(*vals)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. audio_spl_distance
# ═══════════════════════════════════════════════════════════════════════════════

_SPL_DIST_SPEC = ToolSpec(
    name="audio_spl_distance",
    description=(
        "SPL at a new distance (inverse-square law, free-field point source).\n\n"
        "  SPL(d) = SPL(d_ref) − 20 × log10(d / d_ref)\n\n"
        "Input: { spl_ref_db, d_ref_m, d_target_m }\n"
        "Returns: { ok, spl_target_db, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "spl_ref_db": {"type": "number", "description": "Reference SPL [dB]."},
            "d_ref_m": {"type": "number", "description": "Reference distance [m]."},
            "d_target_m": {"type": "number", "description": "Target distance [m]."},
        },
        "required": ["spl_ref_db", "d_ref_m", "d_target_m"],
    },
)


@register(_SPL_DIST_SPEC, write=False)
async def audio_spl_distance(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = spl_distance(
        spl_ref_db=a.get("spl_ref_db"),
        d_ref_m=a.get("d_ref_m"),
        d_target_m=a.get("d_target_m"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 15. audio_db_voltage
# ═══════════════════════════════════════════════════════════════════════════════

_DB_V_SPEC = ToolSpec(
    name="audio_db_voltage",
    description=(
        "Convert a voltage ratio to dB: 20 × log10(V_out / V_in).\n\n"
        "Input: { v_ratio }\n"
        "Returns: { ok, db, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "v_ratio": {
                "type": "number",
                "description": "Voltage ratio V_out / V_in (must be > 0).",
            },
        },
        "required": ["v_ratio"],
    },
)


@register(_DB_V_SPEC, write=False)
async def audio_db_voltage(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = db_voltage(v_ratio=a.get("v_ratio"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 16. audio_db_power
# ═══════════════════════════════════════════════════════════════════════════════

_DB_P_SPEC = ToolSpec(
    name="audio_db_power",
    description=(
        "Convert a power ratio to dB: 10 × log10(P_out / P_in).\n\n"
        "Input: { p_ratio }\n"
        "Returns: { ok, db, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "p_ratio": {
                "type": "number",
                "description": "Power ratio P_out / P_in (must be > 0).",
            },
        },
        "required": ["p_ratio"],
    },
)


@register(_DB_P_SPEC, write=False)
async def audio_db_power(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = db_power(p_ratio=a.get("p_ratio"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 17. audio_a_weighting
# ═══════════════════════════════════════════════════════════════════════════════

_AWEIGHT_SPEC = ToolSpec(
    name="audio_a_weighting",
    description=(
        "A-weighting correction in dB at a given frequency (IEC 61672-1).\n\n"
        "Normalised to 0 dB at 1 kHz. Returns negative values below ~1 kHz "
        "and above ~4 kHz.\n\n"
        "Input: { freq_hz }\n"
        "Returns: { ok, a_weighting_db, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {
                "type": "number",
                "description": "Frequency [Hz] (must be > 0).",
            },
        },
        "required": ["freq_hz"],
    },
)


@register(_AWEIGHT_SPEC, write=False)
async def audio_a_weighting(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = a_weighting(freq_hz=a.get("freq_hz"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 18. audio_impedance_bridge
# ═══════════════════════════════════════════════════════════════════════════════

_IMP_BRIDGE_SPEC = ToolSpec(
    name="audio_impedance_bridge",
    description=(
        "Line-level impedance bridging analysis.\n\n"
        "Checks whether Z_load / Z_source ≥ 10 (audio bridging condition) "
        "and returns voltage transfer factor and power transfer ratio.\n"
        "Issues a warning when bridging condition is not met.\n\n"
        "Input: { z_source, z_load }\n"
        "Returns: { ok, ratio, av_db, power_transfer_db, bridging_ok, ... }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "z_source": {
                "type": "number",
                "description": "Source (output) impedance [Ω].",
            },
            "z_load": {
                "type": "number",
                "description": "Load (input) impedance [Ω].",
            },
        },
        "required": ["z_source", "z_load"],
    },
)


@register(_IMP_BRIDGE_SPEC, write=False)
async def audio_impedance_bridge(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = impedance_bridging(z_source=a.get("z_source"), z_load=a.get("z_load"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_AMP_A_SPEC.name,       _AMP_A_SPEC,       audio_amp_class_a),
    (_AMP_B_SPEC.name,       _AMP_B_SPEC,       audio_amp_class_b),
    (_AMP_AB_SPEC.name,      _AMP_AB_SPEC,      audio_amp_class_ab),
    (_AMP_D_SPEC.name,       _AMP_D_SPEC,       audio_amp_class_d),
    (_HEATSINK_SPEC.name,    _HEATSINK_SPEC,    audio_heatsink_rth),
    (_SEALED_SPEC.name,      _SEALED_SPEC,      audio_sealed_box),
    (_VENTED_SPEC.name,      _VENTED_SPEC,      audio_vented_box),
    (_DRIVER_SPL_SPEC.name,  _DRIVER_SPL_SPEC,  audio_driver_spl),
    (_XOVER_SPEC.name,       _XOVER_SPEC,       audio_crossover),
    (_ZOBEL_SPEC.name,       _ZOBEL_SPEC,       audio_zobel),
    (_LPAD_SPEC.name,        _LPAD_SPEC,        audio_lpad),
    (_DF_SPEC.name,          _DF_SPEC,          audio_damping_factor),
    (_SPL_ADD_SPEC.name,     _SPL_ADD_SPEC,     audio_spl_add),
    (_SPL_DIST_SPEC.name,    _SPL_DIST_SPEC,    audio_spl_distance),
    (_DB_V_SPEC.name,        _DB_V_SPEC,        audio_db_voltage),
    (_DB_P_SPEC.name,        _DB_P_SPEC,        audio_db_power),
    (_AWEIGHT_SPEC.name,     _AWEIGHT_SPEC,     audio_a_weighting),
    (_IMP_BRIDGE_SPEC.name,  _IMP_BRIDGE_SPEC,  audio_impedance_bridge),
]
