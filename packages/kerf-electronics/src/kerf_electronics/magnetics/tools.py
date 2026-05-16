"""
Magnetics design LLM tools.

Provides ten LLM-callable tools:

  magnetics_core_select_ap    — select core by area-product method
  magnetics_core_select_kg    — select core by geometric constant
  magnetics_transformer_turns — primary turns from Faraday's law
  magnetics_inductor_turns    — inductor turns from Ampere's law
  magnetics_gap_length        — air-gap length + AL for energy storage
  magnetics_awg_select        — wire AWG from RMS current + current density
  magnetics_core_loss         — Steinmetz volumetric + total core loss
  magnetics_copper_loss       — DC + Dowell AC winding loss
  magnetics_temperature_rise  — thermal model (surface-area or Rth)
  magnetics_saturation_check  — peak flux density vs Bsat check

All handlers follow the kerf never-raise contract: errors → {"ok": false, "reason": ...}.
Warnings for saturation / over-temp / window-overfill are issued via warnings.warn.

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.magnetics.design import (
    CORE_MATERIALS,
    awg_from_current,
    copper_loss,
    core_select_ap,
    core_select_kg,
    dowell_ac_factor,
    flyback_transformer,
    gap_length,
    inductor_turns,
    leakage_inductance_estimate,
    push_pull_transformer,
    saturation_check,
    skin_depth,
    steinmetz_core_loss,
    temperature_rise,
    total_loss,
    transformer_primary_turns,
    turns_ratio,
    window_utilization,
)

_MATERIAL_KEYS = list(CORE_MATERIALS.keys())

# ═══════════════════════════════════════════════════════════════════════════════
# 1. magnetics_core_select_ap
# ═══════════════════════════════════════════════════════════════════════════════

_CORE_AP_SPEC = ToolSpec(
    name="magnetics_core_select_ap",
    description=(
        "Select a magnetic core using the area-product method.\n\n"
        "Ap = Wa × Ae = power_va / (kt × kw × Bmax × J × fsw)\n\n"
        "Returns the smallest core from the built-in ETD/EE/PQ/toroid catalogue "
        "whose Ap meets the requirement.  Suitable for both transformers (provide "
        "apparent power S) and inductors (provide L × I_pk² × fsw / 2).\n\n"
        "Input: { power_va, freq_hz, bmax_t, j_am2?, kw?, kt? }\n"
        "Returns: { ok, ap_required_cm4, selected_core, candidates }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "power_va": {
                "type": "number",
                "description": "Apparent power handled by the core [VA].",
            },
            "freq_hz": {
                "type": "number",
                "description": "Switching (or line) frequency [Hz].",
            },
            "bmax_t": {
                "type": "number",
                "description": "Peak flux density [T] (use 80-90 % of Bsat for margin).",
            },
            "j_am2": {
                "type": "number",
                "description": "Current density [A/m²] (default 4 MA/m² = 4 A/mm²).",
            },
            "kw": {
                "type": "number",
                "description": "Window utilisation factor (default 0.4 for transformers, 0.6 for inductors).",
            },
            "kt": {
                "type": "number",
                "description": "Topology constant: 1.0 inductor, 0.5 half-bridge, 0.25 push-pull (default 1.0).",
            },
        },
        "required": ["power_va", "freq_hz", "bmax_t"],
    },
)


@register(_CORE_AP_SPEC, write=False)
async def magnetics_core_select_ap(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = core_select_ap(
        power_va=a.get("power_va"),
        freq_hz=a.get("freq_hz"),
        bmax_t=a.get("bmax_t"),
        j_am2=a.get("j_am2", 4.0e6),
        kw=a.get("kw", 0.4),
        kt=a.get("kt", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. magnetics_core_select_kg
# ═══════════════════════════════════════════════════════════════════════════════

_CORE_KG_SPEC = ToolSpec(
    name="magnetics_core_select_kg",
    description=(
        "Select a magnetic core using the geometric constant Kg = Ae² × Wa / MLT.\n\n"
        "Kg method directly accounts for winding resistance targets (McLyman §3.4).\n\n"
        "Input: { power_va, freq_hz, bmax_t, rdc_target_ohm?, j_am2?, kw? }\n"
        "Returns: { ok, kg_required_m5, selected_core, candidates }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "power_va": {"type": "number", "description": "Apparent power [VA]."},
            "freq_hz": {"type": "number", "description": "Frequency [Hz]."},
            "bmax_t": {"type": "number", "description": "Peak flux density [T]."},
            "rdc_target_ohm": {
                "type": "number",
                "description": "Target total DC winding resistance [Ω] (default 0.1 Ω).",
            },
            "j_am2": {"type": "number", "description": "Current density [A/m²] (default 4e6)."},
            "kw": {"type": "number", "description": "Window utilisation (default 0.4)."},
        },
        "required": ["power_va", "freq_hz", "bmax_t"],
    },
)


@register(_CORE_KG_SPEC, write=False)
async def magnetics_core_select_kg(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = core_select_kg(
        power_va=a.get("power_va"),
        freq_hz=a.get("freq_hz"),
        bmax_t=a.get("bmax_t"),
        j_am2=a.get("j_am2", 4.0e6),
        kw=a.get("kw", 0.4),
        rdc_target_ohm=a.get("rdc_target_ohm", 0.1),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. magnetics_transformer_turns
# ═══════════════════════════════════════════════════════════════════════════════

_XFMR_TURNS_SPEC = ToolSpec(
    name="magnetics_transformer_turns",
    description=(
        "Calculate transformer primary turns from Faraday's law.\n\n"
        "Square-wave (switch-mode): Np = V / (4 × f × Bmax × Ae)\n"
        "Sinusoidal (mains):        Np = V / (4.44 × f × Bmax × Ae)\n\n"
        "Input: { v_primary, freq_hz, bmax_t, ae_m2, waveform? }\n"
        "Returns: { ok, Np (integer, ceil), Np_exact, waveform }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "v_primary": {"type": "number", "description": "Primary RMS voltage [V]."},
            "freq_hz": {"type": "number", "description": "Frequency [Hz]."},
            "bmax_t": {"type": "number", "description": "Peak flux density [T]."},
            "ae_m2": {"type": "number", "description": "Effective core cross-section [m²]."},
            "waveform": {
                "type": "string",
                "enum": ["square", "sine"],
                "description": "Waveform: 'square' (switch-mode, default) or 'sine' (mains).",
            },
        },
        "required": ["v_primary", "freq_hz", "bmax_t", "ae_m2"],
    },
)


@register(_XFMR_TURNS_SPEC, write=False)
async def magnetics_transformer_turns(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = transformer_primary_turns(
        v_primary=a.get("v_primary"),
        freq_hz=a.get("freq_hz"),
        bmax_t=a.get("bmax_t"),
        ae_m2=a.get("ae_m2"),
        waveform=a.get("waveform", "square"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. magnetics_inductor_turns
# ═══════════════════════════════════════════════════════════════════════════════

_IND_TURNS_SPEC = ToolSpec(
    name="magnetics_inductor_turns",
    description=(
        "Calculate inductor turns from Ampere's law:\n"
        "  N = L × I_peak / (Bmax × Ae)\n\n"
        "Input: { inductance_h, i_peak_a, bmax_t, ae_m2 }\n"
        "Returns: { ok, N (integer ceil), N_exact }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "inductance_h": {"type": "number", "description": "Required inductance [H]."},
            "i_peak_a": {"type": "number", "description": "Peak current (DC + ripple) [A]."},
            "bmax_t": {"type": "number", "description": "Peak allowable flux density [T]."},
            "ae_m2": {"type": "number", "description": "Effective core cross-section [m²]."},
        },
        "required": ["inductance_h", "i_peak_a", "bmax_t", "ae_m2"],
    },
)


@register(_IND_TURNS_SPEC, write=False)
async def magnetics_inductor_turns(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = inductor_turns(
        inductance_h=a.get("inductance_h"),
        i_peak_a=a.get("i_peak_a"),
        bmax_t=a.get("bmax_t"),
        ae_m2=a.get("ae_m2"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. magnetics_gap_length
# ═══════════════════════════════════════════════════════════════════════════════

_GAP_SPEC = ToolSpec(
    name="magnetics_gap_length",
    description=(
        "Calculate air-gap length and resulting AL for a gapped inductor.\n\n"
        "lg = μ0 × N² × Ae / L  (with fringing correction)\n"
        "AL = μ0 × Ae / (lg_eff + le/μi)\n\n"
        "Input: { inductance_h, n_turns, ae_m2, mu_i? }\n"
        "Returns: { ok, lg_mm, lg_eff_mm, fringing_factor, AL_nH_per_turn2, inductance_check_h }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "inductance_h": {"type": "number", "description": "Target inductance [H]."},
            "n_turns": {"type": "integer", "description": "Number of turns."},
            "ae_m2": {"type": "number", "description": "Effective core cross-section [m²]."},
            "mu_i": {
                "type": "number",
                "description": "Initial core permeability (default 2200 for N87 ferrite).",
            },
        },
        "required": ["inductance_h", "n_turns", "ae_m2"],
    },
)


@register(_GAP_SPEC, write=False)
async def magnetics_gap_length(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    n_turns = a.get("n_turns")
    if n_turns is not None:
        n_turns = int(n_turns)

    result = gap_length(
        inductance_h=a.get("inductance_h"),
        n_turns=n_turns,
        ae_m2=a.get("ae_m2"),
        mu_i=a.get("mu_i", 2200.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. magnetics_awg_select
# ═══════════════════════════════════════════════════════════════════════════════

_AWG_SPEC = ToolSpec(
    name="magnetics_awg_select",
    description=(
        "Select wire AWG from RMS current and current density.\n\n"
        "A_wire = I_rms / J;  returns finest AWG whose area ≥ A_wire.\n\n"
        "Input: { i_rms_a, j_am2? }\n"
        "Returns: { ok, awg, diameter_mm, area_mm2, rdc_ohm_per_m, actual_j_am2 }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "i_rms_a": {"type": "number", "description": "RMS winding current [A]."},
            "j_am2": {
                "type": "number",
                "description": "Current density [A/m²] (default 4 MA/m² = 4 A/mm²).",
            },
        },
        "required": ["i_rms_a"],
    },
)


@register(_AWG_SPEC, write=False)
async def magnetics_awg_select(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = awg_from_current(
        i_rms_a=a.get("i_rms_a"),
        j_am2=a.get("j_am2", 4.0e6),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. magnetics_core_loss
# ═══════════════════════════════════════════════════════════════════════════════

_CORE_LOSS_SPEC = ToolSpec(
    name="magnetics_core_loss",
    description=(
        "Compute Steinmetz core loss for a magnetic component.\n\n"
        "Pv [W/m³] = k × f^α × B_peak^β\n"
        "P_core [W] = Pv × Vc\n\n"
        f"Available materials: {list(CORE_MATERIALS.keys())}\n\n"
        "Input: { freq_hz, b_peak_t, core_volume_m3, material? }\n"
        "Returns: { ok, p_volume_w_m3, p_core_w, saturation_flag, Bsat_t, steinmetz_k/alpha/beta }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "freq_hz": {"type": "number", "description": "Switching frequency [Hz]."},
            "b_peak_t": {
                "type": "number",
                "description": "Peak (one-sided) flux density [T].",
            },
            "core_volume_m3": {
                "type": "number",
                "description": "Effective core volume [m³].",
            },
            "material": {
                "type": "string",
                "enum": _MATERIAL_KEYS,
                "description": "Core material (default 'N87').",
            },
        },
        "required": ["freq_hz", "b_peak_t", "core_volume_m3"],
    },
)


@register(_CORE_LOSS_SPEC, write=False)
async def magnetics_core_loss(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = steinmetz_core_loss(
        freq_hz=a.get("freq_hz"),
        b_peak_t=a.get("b_peak_t"),
        core_volume_m3=a.get("core_volume_m3"),
        material=a.get("material", "N87"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. magnetics_copper_loss
# ═══════════════════════════════════════════════════════════════════════════════

_CU_LOSS_SPEC = ToolSpec(
    name="magnetics_copper_loss",
    description=(
        "Compute winding copper loss (DC + Dowell AC).\n\n"
        "P_total = I_rms² × Rdc × Fr\n\n"
        "Optionally provide Dowell inputs (freq_hz, wire_dia_m, n_layers) to "
        "compute Fr automatically instead of providing it directly.\n\n"
        "Input: { i_rms_dc_a, rdc_ohm, fr? } or { i_rms_dc_a, rdc_ohm, freq_hz, wire_dia_m, n_layers }\n"
        "Returns: { ok, p_dc_w, p_ac_w, p_total_w, rac_ohm }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "i_rms_dc_a": {"type": "number", "description": "Total RMS winding current [A]."},
            "rdc_ohm": {"type": "number", "description": "DC winding resistance [Ω]."},
            "fr": {
                "type": "number",
                "description": "Dowell Fr factor (Rac/Rdc). Supply or let tool compute from freq_hz+wire_dia_m+n_layers.",
            },
            "freq_hz": {"type": "number", "description": "Frequency for Dowell Fr [Hz]."},
            "wire_dia_m": {"type": "number", "description": "Bare wire diameter [m] for Dowell."},
            "n_layers": {"type": "integer", "description": "Winding layers for Dowell."},
        },
        "required": ["i_rms_dc_a", "rdc_ohm"],
    },
)


@register(_CU_LOSS_SPEC, write=False)
async def magnetics_copper_loss(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    fr = a.get("fr", 1.0)
    freq_hz = a.get("freq_hz")
    wire_dia_m = a.get("wire_dia_m")
    n_layers = a.get("n_layers")

    if freq_hz is not None and wire_dia_m is not None and n_layers is not None:
        try:
            n_layers = int(n_layers)
        except (TypeError, ValueError):
            return err_payload("n_layers must be an integer", "BAD_ARGS")
        dowell_res = dowell_ac_factor(
            freq_hz=freq_hz,
            wire_dia_m=wire_dia_m,
            n_layers=n_layers,
        )
        if not dowell_res.get("ok"):
            return err_payload(dowell_res.get("reason", "Dowell error"), "BAD_ARGS")
        fr = dowell_res["Fr"]

    result = copper_loss(
        i_rms_dc_a=a.get("i_rms_dc_a"),
        rdc_ohm=a.get("rdc_ohm"),
        fr=fr,
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. magnetics_temperature_rise
# ═══════════════════════════════════════════════════════════════════════════════

_TEMP_SPEC = ToolSpec(
    name="magnetics_temperature_rise",
    description=(
        "Estimate temperature rise of a magnetic component.\n\n"
        "Surface-area model: ΔT = P / (h × A_surface)  (h=10 W/m²K natural conv.)\n"
        "Thermal-resistance model: ΔT = P × Rth\n\n"
        "Issues a warning when T_ambient + ΔT > T_max.\n\n"
        "Input: { p_total_w, surface_area_m2? OR rth_c_per_w?, t_ambient_c?, t_max_c? }\n"
        "Returns: { ok, delta_t_k, t_total_c, t_margin_k, over_temp }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "p_total_w": {"type": "number", "description": "Total loss [W]."},
            "surface_area_m2": {
                "type": "number",
                "description": "Core+bobbin surface area [m²] (for convection model).",
            },
            "rth_c_per_w": {
                "type": "number",
                "description": "Thermal resistance [°C/W] (alternative to surface_area).",
            },
            "t_ambient_c": {"type": "number", "description": "Ambient temperature [°C] (default 25)."},
            "t_max_c": {"type": "number", "description": "Maximum allowed temperature [°C] (default 100)."},
        },
        "required": ["p_total_w"],
    },
)


@register(_TEMP_SPEC, write=False)
async def magnetics_temperature_rise(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    if a.get("surface_area_m2") is None and a.get("rth_c_per_w") is None:
        return err_payload("Provide either surface_area_m2 or rth_c_per_w", "BAD_ARGS")

    result = temperature_rise(
        p_total_w=a.get("p_total_w"),
        surface_area_m2=a.get("surface_area_m2"),
        rth_c_per_w=a.get("rth_c_per_w"),
        t_ambient_c=a.get("t_ambient_c", 25.0),
        t_max_c=a.get("t_max_c", 100.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. magnetics_saturation_check
# ═══════════════════════════════════════════════════════════════════════════════

_SAT_SPEC = ToolSpec(
    name="magnetics_saturation_check",
    description=(
        "Check peak flux density against core saturation.\n\n"
        "B_peak = μ0 × μi × N × I_peak / le\n\n"
        "Issues a warning when B_peak ≥ Bsat (or within 5 % margin).\n\n"
        f"Available materials (for Bsat): {list(CORE_MATERIALS.keys())}\n\n"
        "Input: { n_turns, i_peak_a, ae_m2, le_m, mu_i, material? or bsat_override_t? }\n"
        "Returns: { ok, b_peak_t, bsat_t, margin_t, saturated }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "n_turns": {"type": "integer", "description": "Number of turns."},
            "i_peak_a": {"type": "number", "description": "Peak current [A]."},
            "ae_m2": {"type": "number", "description": "Effective core cross-section [m²]."},
            "le_m": {"type": "number", "description": "Effective magnetic path length [m]."},
            "mu_i": {"type": "number", "description": "Effective permeability (use 1 for fully gapped)."},
            "material": {
                "type": "string",
                "enum": _MATERIAL_KEYS,
                "description": "Core material for Bsat lookup.",
            },
            "bsat_override_t": {
                "type": "number",
                "description": "Override Bsat [T] if material not in table.",
            },
        },
        "required": ["n_turns", "i_peak_a", "ae_m2", "le_m", "mu_i"],
    },
)


@register(_SAT_SPEC, write=False)
async def magnetics_saturation_check(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    n_turns = a.get("n_turns")
    if n_turns is not None:
        n_turns = int(n_turns)

    result = saturation_check(
        n_turns=n_turns,
        i_peak_a=a.get("i_peak_a"),
        ae_m2=a.get("ae_m2"),
        le_m=a.get("le_m"),
        mu_i=a.get("mu_i"),
        material=a.get("material"),
        bsat_override_t=a.get("bsat_override_t"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_CORE_AP_SPEC.name,    _CORE_AP_SPEC,    magnetics_core_select_ap),
    (_CORE_KG_SPEC.name,    _CORE_KG_SPEC,    magnetics_core_select_kg),
    (_XFMR_TURNS_SPEC.name, _XFMR_TURNS_SPEC, magnetics_transformer_turns),
    (_IND_TURNS_SPEC.name,  _IND_TURNS_SPEC,  magnetics_inductor_turns),
    (_GAP_SPEC.name,        _GAP_SPEC,        magnetics_gap_length),
    (_AWG_SPEC.name,        _AWG_SPEC,        magnetics_awg_select),
    (_CORE_LOSS_SPEC.name,  _CORE_LOSS_SPEC,  magnetics_core_loss),
    (_CU_LOSS_SPEC.name,    _CU_LOSS_SPEC,    magnetics_copper_loss),
    (_TEMP_SPEC.name,       _TEMP_SPEC,       magnetics_temperature_rise),
    (_SAT_SPEC.name,        _SAT_SPEC,        magnetics_saturation_check),
]
