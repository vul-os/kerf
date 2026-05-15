"""
RF impedance-matching network synthesis — LLM tools.

Exposes eight tools to the Kerf agent layer:

  rfmatch_reflection       — Γ, VSWR, return loss, mismatch loss
  rfmatch_lsection         — L-section matching for complex source/load
  rfmatch_pi               — Pi-network synthesis for target loaded-Q
  rfmatch_t                — T-network synthesis for target loaded-Q
  rfmatch_quarter_wave     — Quarter-wave transformer Z0
  rfmatch_single_stub      — Single-stub matching (shunt/series, short/open)
  rfmatch_microstrip_synth — Microstrip width synthesis (Hammerstad)
  rfmatch_microstrip_anal  — Microstrip analysis: Z0 + εr_eff from geometry

All handlers follow the kerf never-raise contract:
  Success: {"ok": True, ...}  via ok_payload
  Failure: {"ok": False, "error": ..., "code": ...}  via err_payload
  Never raise.

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

from kerf_electronics.rfmatch.match import (
    lsection_match,
    microstrip_analysis,
    microstrip_synthesis,
    pi_network,
    quarter_wave_transformer,
    reflection_coefficient,
    single_stub_match,
    t_network,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. rfmatch_reflection
# ═══════════════════════════════════════════════════════════════════════════════

_REFL_SPEC = ToolSpec(
    name="rfmatch_reflection",
    description=(
        "Compute the complex reflection coefficient Γ = (Z_L − Z0) / (Z_L + Z0) "
        "for a load impedance Z_L relative to a reference impedance Z0.\n\n"
        "Also returns |Γ|, ∠Γ [degrees], VSWR, return loss [dB], and "
        "mismatch loss [dB].\n\n"
        "Input: { z_load_re, z_load_im?, z0? }\n"
        "Returns: { ok, gamma_re, gamma_im, gamma_mag, gamma_phase_deg, "
        "vswr, return_loss_db, mismatch_loss_db }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "z_load_re": {
                "type": "number",
                "description": "Real part of the load impedance [Ω].",
            },
            "z_load_im": {
                "type": "number",
                "description": "Imaginary part of the load impedance [Ω] (default 0).",
            },
            "z0": {
                "type": "number",
                "description": "Reference impedance [Ω] (default 50 Ω).",
            },
        },
        "required": ["z_load_re"],
    },
)


@register(_REFL_SPEC, write=False)
async def rfmatch_reflection(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    zl = complex(a.get("z_load_re", 0.0), a.get("z_load_im", 0.0))
    z0 = a.get("z0", 50.0)

    result = reflection_coefficient(z_load=zl, z0=z0)
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. rfmatch_lsection
# ═══════════════════════════════════════════════════════════════════════════════

_LSEC_SPEC = ToolSpec(
    name="rfmatch_lsection",
    description=(
        "Synthesise an L-section impedance-matching network for complex source "
        "and load impedances at a given frequency.\n\n"
        "Returns both canonical L-section topologies (shunt-source/series-load "
        "and series-source/shunt-load) with component L/C values and loaded-Q.\n"
        "Non-realizable or negative-component solutions are flagged in the "
        "'warnings' field; the function never raises.\n\n"
        "Input: { z_source_re, z_source_im?, z_load_re, z_load_im?, freq_hz }\n"
        "Returns: { ok, Q, solutions: [ { topology, component_type_shunt, "
        "component_value_shunt, component_type_series, component_value_series, "
        "realizable, warnings }, ... ] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "z_source_re": {
                "type": "number",
                "description": "Real part of source impedance [Ω].",
            },
            "z_source_im": {
                "type": "number",
                "description": "Imaginary part of source impedance [Ω] (default 0).",
            },
            "z_load_re": {
                "type": "number",
                "description": "Real part of load impedance [Ω].",
            },
            "z_load_im": {
                "type": "number",
                "description": "Imaginary part of load impedance [Ω] (default 0).",
            },
            "freq_hz": {
                "type": "number",
                "description": "Operating frequency [Hz].",
            },
        },
        "required": ["z_source_re", "z_load_re", "freq_hz"],
    },
)


@register(_LSEC_SPEC, write=False)
async def rfmatch_lsection(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    zs = complex(a.get("z_source_re", 0.0), a.get("z_source_im", 0.0))
    zl = complex(a.get("z_load_re", 0.0), a.get("z_load_im", 0.0))
    freq_hz = a.get("freq_hz")

    result = lsection_match(z_source=zs, z_load=zl, freq_hz=freq_hz)
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. rfmatch_pi
# ═══════════════════════════════════════════════════════════════════════════════

_PI_SPEC = ToolSpec(
    name="rfmatch_pi",
    description=(
        "Synthesise a Pi (π) impedance-matching network for a target loaded-Q.\n\n"
        "A Pi-network provides bandwidth control via the loaded-Q and can match "
        "a wider impedance ratio than a simple L-section.  The loaded-Q must "
        "exceed Q_min = sqrt(R_high/R_low − 1).\n\n"
        "Input: { r_source, r_load, freq_hz, q_loaded }\n"
        "Returns: { ok, r_virtual, X_p1_ohm, X_series_ohm, X_p2_ohm, "
        "component_type_p1/series/p2, component_value_p1/series/p2, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r_source": {
                "type": "number",
                "description": "Source resistance [Ω].",
            },
            "r_load": {
                "type": "number",
                "description": "Load resistance [Ω].",
            },
            "freq_hz": {
                "type": "number",
                "description": "Operating frequency [Hz].",
            },
            "q_loaded": {
                "type": "number",
                "description": "Target loaded-Q (must be > sqrt(R_high/R_low − 1)).",
            },
        },
        "required": ["r_source", "r_load", "freq_hz", "q_loaded"],
    },
)


@register(_PI_SPEC, write=False)
async def rfmatch_pi(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = pi_network(
        r_source=a.get("r_source"),
        r_load=a.get("r_load"),
        freq_hz=a.get("freq_hz"),
        q_loaded=a.get("q_loaded"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. rfmatch_t
# ═══════════════════════════════════════════════════════════════════════════════

_T_SPEC = ToolSpec(
    name="rfmatch_t",
    description=(
        "Synthesise a T-network impedance-matching network for a target loaded-Q.\n\n"
        "A T-network is the dual of a Pi-network: two series arms and one shunt arm.  "
        "The loaded-Q must exceed Q_min = sqrt(R_high/R_low − 1).\n\n"
        "Input: { r_source, r_load, freq_hz, q_loaded }\n"
        "Returns: { ok, r_virtual, X_s1_ohm, X_p_ohm, X_s2_ohm, "
        "component_type_s1/p/s2, component_value_s1/p/s2, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r_source": {
                "type": "number",
                "description": "Source resistance [Ω].",
            },
            "r_load": {
                "type": "number",
                "description": "Load resistance [Ω].",
            },
            "freq_hz": {
                "type": "number",
                "description": "Operating frequency [Hz].",
            },
            "q_loaded": {
                "type": "number",
                "description": "Target loaded-Q (must be > sqrt(R_high/R_low − 1)).",
            },
        },
        "required": ["r_source", "r_load", "freq_hz", "q_loaded"],
    },
)


@register(_T_SPEC, write=False)
async def rfmatch_t(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = t_network(
        r_source=a.get("r_source"),
        r_load=a.get("r_load"),
        freq_hz=a.get("freq_hz"),
        q_loaded=a.get("q_loaded"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. rfmatch_quarter_wave
# ═══════════════════════════════════════════════════════════════════════════════

_QW_SPEC = ToolSpec(
    name="rfmatch_quarter_wave",
    description=(
        "Compute the characteristic impedance Z0 of a quarter-wave transformer "
        "that matches a source resistance R_source to a load resistance R_load.\n\n"
        "Formula: Z0 = sqrt(R_source × R_load)\n\n"
        "Valid for resistive (real) source and load only.  At the design frequency "
        "the transformer is exactly λ/4 long (90° electrical length).\n\n"
        "Input: { r_source, r_load }\n"
        "Returns: { ok, z0_transformer_ohm }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "r_source": {
                "type": "number",
                "description": "Source resistance [Ω].",
            },
            "r_load": {
                "type": "number",
                "description": "Load resistance [Ω].",
            },
        },
        "required": ["r_source", "r_load"],
    },
)


@register(_QW_SPEC, write=False)
async def rfmatch_quarter_wave(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = quarter_wave_transformer(
        r_source=a.get("r_source"),
        r_load=a.get("r_load"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. rfmatch_single_stub
# ═══════════════════════════════════════════════════════════════════════════════

_STUB_SPEC = ToolSpec(
    name="rfmatch_single_stub",
    description=(
        "Single-stub impedance matching: compute the feed-line distance to stub "
        "and stub electrical length for a given load impedance.\n\n"
        "Uses the classical single-stub matching method (Pozar §5.2).  "
        "Returns two solutions (if they exist); each solution includes the "
        "feed-line length d and stub length l as fractions of wavelength and "
        "in degrees.\n\n"
        "Input: { z_load_re, z_load_im?, z0?, stub_type?, termination? }\n"
        "Returns: { ok, solutions: [ { d_wavelength, d_degrees, "
        "stub_length_wavelength, stub_length_degrees, realizable, notes }, ... ] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "z_load_re": {
                "type": "number",
                "description": "Real part of load impedance [Ω].",
            },
            "z_load_im": {
                "type": "number",
                "description": "Imaginary part of load impedance [Ω] (default 0).",
            },
            "z0": {
                "type": "number",
                "description": "System characteristic impedance [Ω] (default 50 Ω).",
            },
            "stub_type": {
                "type": "string",
                "enum": ["shunt", "series"],
                "description": "'shunt' (default) or 'series'.",
            },
            "termination": {
                "type": "string",
                "enum": ["short", "open"],
                "description": "'short' (default) or 'open' stub termination.",
            },
        },
        "required": ["z_load_re"],
    },
)


@register(_STUB_SPEC, write=False)
async def rfmatch_single_stub(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    zl = complex(a.get("z_load_re", 0.0), a.get("z_load_im", 0.0))
    result = single_stub_match(
        z_load=zl,
        z0=a.get("z0", 50.0),
        stub_type=a.get("stub_type", "shunt"),
        termination=a.get("termination", "short"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. rfmatch_microstrip_synth
# ═══════════════════════════════════════════════════════════════════════════════

_MS_SYNTH_SPEC = ToolSpec(
    name="rfmatch_microstrip_synth",
    description=(
        "Microstrip trace width synthesis using the Hammerstad & Jensen (1980) "
        "closed-form equations (Pozar §3.8).\n\n"
        "Given a target characteristic impedance Z0 and substrate parameters, "
        "computes the trace width W/H ratio, effective permittivity εr_eff, "
        "and a self-check impedance.\n\n"
        "Input: { z0_target, er, h?, t? }\n"
        "Returns: { ok, width, width_to_height, er_eff, z0_achieved, "
        "error_percent, regime, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "z0_target": {
                "type": "number",
                "description": "Target characteristic impedance [Ω].",
            },
            "er": {
                "type": "number",
                "description": "Substrate relative permittivity εr.",
            },
            "h": {
                "type": "number",
                "description": "Substrate height (any consistent unit; default 1.0 → result W in same unit).",
            },
            "t": {
                "type": "number",
                "description": "Trace thickness in same unit as h (0 = ideal thin trace; default 0).",
            },
        },
        "required": ["z0_target", "er"],
    },
)


@register(_MS_SYNTH_SPEC, write=False)
async def rfmatch_microstrip_synth(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = microstrip_synthesis(
        z0_target=a.get("z0_target"),
        er=a.get("er"),
        h=a.get("h", 1.0),
        t=a.get("t", 0.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. rfmatch_microstrip_anal
# ═══════════════════════════════════════════════════════════════════════════════

_MS_ANAL_SPEC = ToolSpec(
    name="rfmatch_microstrip_anal",
    description=(
        "Microstrip analysis: compute characteristic impedance Z0 and effective "
        "permittivity εr_eff from physical dimensions (Hammerstad & Jensen).\n\n"
        "Input: { width, h, er, t? }\n"
        "Returns: { ok, width_to_height, er_eff, z0, wavelength_factor }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "width": {
                "type": "number",
                "description": "Trace width [same unit as h].",
            },
            "h": {
                "type": "number",
                "description": "Substrate height [same unit as width].",
            },
            "er": {
                "type": "number",
                "description": "Substrate relative permittivity εr.",
            },
            "t": {
                "type": "number",
                "description": "Trace thickness (0 = ideal thin trace; default 0).",
            },
        },
        "required": ["width", "h", "er"],
    },
)


@register(_MS_ANAL_SPEC, write=False)
async def rfmatch_microstrip_anal(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = microstrip_analysis(
        width=a.get("width"),
        h=a.get("h"),
        er=a.get("er"),
        t=a.get("t", 0.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_REFL_SPEC.name,     _REFL_SPEC,     rfmatch_reflection),
    (_LSEC_SPEC.name,     _LSEC_SPEC,     rfmatch_lsection),
    (_PI_SPEC.name,       _PI_SPEC,       rfmatch_pi),
    (_T_SPEC.name,        _T_SPEC,        rfmatch_t),
    (_QW_SPEC.name,       _QW_SPEC,       rfmatch_quarter_wave),
    (_STUB_SPEC.name,     _STUB_SPEC,     rfmatch_single_stub),
    (_MS_SYNTH_SPEC.name, _MS_SYNTH_SPEC, rfmatch_microstrip_synth),
    (_MS_ANAL_SPEC.name,  _MS_ANAL_SPEC,  rfmatch_microstrip_anal),
]
