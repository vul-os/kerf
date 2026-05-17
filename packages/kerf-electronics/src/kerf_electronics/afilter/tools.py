"""
Analog filter design — LLM tools.

Exposes tools to the Kerf agent layer:

  afilter_butterworth_order   — minimum Butterworth order from passband/stopband spec
  afilter_chebyshev_order     — minimum Chebyshev-I order from spec
  afilter_bessel_order        — minimum Bessel order estimate from GD flatness spec
  afilter_butterworth_poles   — normalised LP prototype pole locations
  afilter_chebyshev_poles     — normalised LP prototype pole locations
  afilter_bessel_poles        — normalised LP prototype pole locations
  afilter_butterworth_g       — ladder g-values for Butterworth prototype
  afilter_chebyshev_g         — ladder g-values for Chebyshev-I prototype
  afilter_lp_to_lp            — LP prototype → LP RLC component values
  afilter_lp_to_hp            — LP prototype → HP RLC component values
  afilter_lp_to_bp            — LP prototype → BP RLC component values
  afilter_sallen_key          — Sallen-Key 2nd-order LP op-amp component selection
  afilter_mfb                 — Multiple-Feedback 2nd-order LP op-amp components
  afilter_response            — magnitude (dB), phase, group delay at a frequency

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

from kerf_electronics.afilter.design import (
    bessel_order,
    bessel_poles,
    butterworth_g_values,
    butterworth_order,
    butterworth_poles,
    chebyshev_g_values,
    chebyshev_order,
    chebyshev_poles,
    filter_response,
    lp_to_bp_rlc,
    lp_to_hp_rlc,
    lp_to_lp_rlc,
    multiple_feedback_components,
    sallen_key_components,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. afilter_butterworth_order
# ═══════════════════════════════════════════════════════════════════════════════

_BW_ORDER_SPEC = ToolSpec(
    name="afilter_butterworth_order",
    description=(
        "Compute the minimum Butterworth lowpass filter order that meets a "
        "passband ripple and stopband attenuation specification.\n\n"
        "Formula: n ≥ log(ε_s²/ε_p²) / (2 log(Ωs/Ωp))\n\n"
        "Input: { passband_freq_hz, stopband_freq_hz, passband_ripple_db, stopband_atten_db }\n"
        "Returns: { ok, order, n_exact, fc_hz, omega_c_rads }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "passband_freq_hz": {
                "type": "number",
                "description": "Passband cutoff (−3 dB) frequency [Hz].",
            },
            "stopband_freq_hz": {
                "type": "number",
                "description": "Stopband edge frequency [Hz] (must be > passband_freq_hz).",
            },
            "passband_ripple_db": {
                "type": "number",
                "description": "Maximum in-band ripple [dB] (use 3.0 for Butterworth −3 dB).",
            },
            "stopband_atten_db": {
                "type": "number",
                "description": "Minimum stopband attenuation [dB] (e.g. 40).",
            },
        },
        "required": [
            "passband_freq_hz", "stopband_freq_hz",
            "passband_ripple_db", "stopband_atten_db",
        ],
    },
)


@register(_BW_ORDER_SPEC, write=False)
async def afilter_butterworth_order(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = butterworth_order(
        passband_freq_hz=a.get("passband_freq_hz"),
        stopband_freq_hz=a.get("stopband_freq_hz"),
        passband_ripple_db=a.get("passband_ripple_db"),
        stopband_atten_db=a.get("stopband_atten_db"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. afilter_chebyshev_order
# ═══════════════════════════════════════════════════════════════════════════════

_CHEB_ORDER_SPEC = ToolSpec(
    name="afilter_chebyshev_order",
    description=(
        "Compute the minimum Chebyshev-I lowpass filter order from passband "
        "ripple and stopband attenuation specifications.\n\n"
        "Formula: n ≥ acosh(sqrt(ε_s²/ε_p²)) / acosh(Ωs/Ωp)\n\n"
        "Input: { passband_freq_hz, stopband_freq_hz, passband_ripple_db, stopband_atten_db }\n"
        "Returns: { ok, order, n_exact, epsilon }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "passband_freq_hz": {
                "type": "number",
                "description": "Passband edge frequency [Hz].",
            },
            "stopband_freq_hz": {
                "type": "number",
                "description": "Stopband edge frequency [Hz].",
            },
            "passband_ripple_db": {
                "type": "number",
                "description": "Passband ripple [dB].",
            },
            "stopband_atten_db": {
                "type": "number",
                "description": "Minimum stopband attenuation [dB].",
            },
        },
        "required": [
            "passband_freq_hz", "stopband_freq_hz",
            "passband_ripple_db", "stopband_atten_db",
        ],
    },
)


@register(_CHEB_ORDER_SPEC, write=False)
async def afilter_chebyshev_order(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = chebyshev_order(
        passband_freq_hz=a.get("passband_freq_hz"),
        stopband_freq_hz=a.get("stopband_freq_hz"),
        passband_ripple_db=a.get("passband_ripple_db"),
        stopband_atten_db=a.get("stopband_atten_db"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. afilter_bessel_order
# ═══════════════════════════════════════════════════════════════════════════════

_BESS_ORDER_SPEC = ToolSpec(
    name="afilter_bessel_order",
    description=(
        "Estimate the minimum Bessel/Thomson filter order for a target group-delay "
        "flatness over a normalised bandwidth ratio.\n\n"
        "Bessel filters are maximally flat in group delay.  This tool estimates "
        "the order required so that group delay stays within ±(flatness/2)% of the "
        "DC value up to bandwidth_ratio × ω_n.\n\n"
        "Input: { group_delay_flatness_percent, bandwidth_ratio }\n"
        "Returns: { ok, order, group_delay_flatness_percent, bandwidth_ratio }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "group_delay_flatness_percent": {
                "type": "number",
                "description": "Maximum allowed group-delay deviation [%] (e.g. 5.0).",
            },
            "bandwidth_ratio": {
                "type": "number",
                "description": "Ratio of flat-delay bandwidth to normalised cutoff (> 1).",
            },
        },
        "required": ["group_delay_flatness_percent", "bandwidth_ratio"],
    },
)


@register(_BESS_ORDER_SPEC, write=False)
async def afilter_bessel_order(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = bessel_order(
        group_delay_flatness_percent=a.get("group_delay_flatness_percent"),
        bandwidth_ratio=a.get("bandwidth_ratio"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. afilter_butterworth_poles
# ═══════════════════════════════════════════════════════════════════════════════

_BW_POLES_SPEC = ToolSpec(
    name="afilter_butterworth_poles",
    description=(
        "Return the normalised LP prototype pole locations for a Butterworth filter "
        "of order n (unit cutoff ω_c = 1 rad/s, left half-plane).\n\n"
        "All n poles lie on the unit circle.\n\n"
        "Input: { order }\n"
        "Returns: { ok, order, poles: [{re, im}, ...] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order": {
                "type": "integer",
                "description": "Filter order (1 ≤ n ≤ 20).",
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["order"],
    },
)


@register(_BW_POLES_SPEC, write=False)
async def afilter_butterworth_poles(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    n = a.get("order")
    if not isinstance(n, int):
        try:
            n = int(n)
        except Exception:
            return err_payload("order must be an integer", "BAD_ARGS")

    result = butterworth_poles(n)
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. afilter_chebyshev_poles
# ═══════════════════════════════════════════════════════════════════════════════

_CHEB_POLES_SPEC = ToolSpec(
    name="afilter_chebyshev_poles",
    description=(
        "Return normalised LP prototype pole locations for a Chebyshev-I filter "
        "(passband edge at ω = 1 rad/s).  Poles lie on an ellipse in the LHP.\n\n"
        "Input: { order, passband_ripple_db }\n"
        "Returns: { ok, order, passband_ripple_db, epsilon, alpha, poles: [{re, im}] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order": {
                "type": "integer",
                "description": "Filter order.",
                "minimum": 1,
                "maximum": 20,
            },
            "passband_ripple_db": {
                "type": "number",
                "description": "Passband ripple [dB].",
            },
        },
        "required": ["order", "passband_ripple_db"],
    },
)


@register(_CHEB_POLES_SPEC, write=False)
async def afilter_chebyshev_poles(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    n = a.get("order")
    if not isinstance(n, int):
        try:
            n = int(n)
        except Exception:
            return err_payload("order must be an integer", "BAD_ARGS")

    result = chebyshev_poles(n=n, passband_ripple_db=a.get("passband_ripple_db"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. afilter_bessel_poles
# ═══════════════════════════════════════════════════════════════════════════════

_BESS_POLES_SPEC = ToolSpec(
    name="afilter_bessel_poles",
    description=(
        "Return normalised LP prototype pole locations for a Bessel/Thomson filter "
        "(group delay normalised to 1 s at DC).  Poles are roots of the reverse "
        "Bessel polynomial computed via Durand-Kerner iteration.\n\n"
        "Supports order 1–10.\n\n"
        "Input: { order }\n"
        "Returns: { ok, order, poles: [{re, im}] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order": {
                "type": "integer",
                "description": "Filter order (1 ≤ n ≤ 10).",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["order"],
    },
)


@register(_BESS_POLES_SPEC, write=False)
async def afilter_bessel_poles(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    n = a.get("order")
    if not isinstance(n, int):
        try:
            n = int(n)
        except Exception:
            return err_payload("order must be an integer", "BAD_ARGS")

    result = bessel_poles(n)
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. afilter_butterworth_g
# ═══════════════════════════════════════════════════════════════════════════════

_BW_G_SPEC = ToolSpec(
    name="afilter_butterworth_g",
    description=(
        "Return doubly-terminated Butterworth ladder g-values for a normalised LP "
        "prototype (g_0 = 1, ω_c = 1 rad/s).\n\n"
        "g_k = 2 sin((2k−1)π/(2n))  for k=1…n;  g_{n+1} = 1.\n\n"
        "Input: { order }\n"
        "Returns: { ok, order, g_values (n+2 element list) }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order": {
                "type": "integer",
                "description": "Filter order (1 ≤ n ≤ 20).",
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["order"],
    },
)


@register(_BW_G_SPEC, write=False)
async def afilter_butterworth_g(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    n = a.get("order")
    if not isinstance(n, int):
        try:
            n = int(n)
        except Exception:
            return err_payload("order must be an integer", "BAD_ARGS")

    result = butterworth_g_values(n)
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. afilter_chebyshev_g
# ═══════════════════════════════════════════════════════════════════════════════

_CHEB_G_SPEC = ToolSpec(
    name="afilter_chebyshev_g",
    description=(
        "Return doubly-terminated Chebyshev-I ladder g-values for a normalised LP "
        "prototype (g_0 = 1, passband edge ω_c = 1 rad/s).\n\n"
        "Input: { order, passband_ripple_db }\n"
        "Returns: { ok, order, passband_ripple_db, g_values (n+2 element list) }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order": {
                "type": "integer",
                "description": "Filter order (1 ≤ n ≤ 20).",
                "minimum": 1,
                "maximum": 20,
            },
            "passband_ripple_db": {
                "type": "number",
                "description": "Passband ripple [dB].",
            },
        },
        "required": ["order", "passband_ripple_db"],
    },
)


@register(_CHEB_G_SPEC, write=False)
async def afilter_chebyshev_g(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    n = a.get("order")
    if not isinstance(n, int):
        try:
            n = int(n)
        except Exception:
            return err_payload("order must be an integer", "BAD_ARGS")

    result = chebyshev_g_values(n=n, passband_ripple_db=a.get("passband_ripple_db"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. afilter_lp_to_lp
# ═══════════════════════════════════════════════════════════════════════════════

_LP_LP_SPEC = ToolSpec(
    name="afilter_lp_to_lp",
    description=(
        "Frequency and impedance denormalise a normalised LP ladder prototype to an "
        "LP RLC filter at a target cutoff frequency and impedance.\n\n"
        "Series elements → inductors (L = g_k × Z0 / ω_c).\n"
        "Shunt elements → capacitors (C = g_k / (Z0 × ω_c)).\n\n"
        "Input: { g_values, cutoff_freq_hz, impedance_ohm? }\n"
        "Returns: { ok, r_source, r_load, elements: [{index, type, value}], warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "g_values": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Ladder g-values (n+2 elements: g_0…g_{n+1}).",
            },
            "cutoff_freq_hz": {
                "type": "number",
                "description": "Target −3 dB cutoff frequency [Hz].",
            },
            "impedance_ohm": {
                "type": "number",
                "description": "Reference impedance [Ω] (default 50 Ω).",
            },
        },
        "required": ["g_values", "cutoff_freq_hz"],
    },
)


@register(_LP_LP_SPEC, write=False)
async def afilter_lp_to_lp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = lp_to_lp_rlc(
        g_values=a.get("g_values"),
        cutoff_freq_hz=a.get("cutoff_freq_hz"),
        impedance_ohm=a.get("impedance_ohm", 50.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. afilter_lp_to_hp
# ═══════════════════════════════════════════════════════════════════════════════

_LP_HP_SPEC = ToolSpec(
    name="afilter_lp_to_hp",
    description=(
        "LP prototype → HP RLC filter via the s → ω_c/s frequency inversion.\n\n"
        "LP series L → HP shunt C = 1/(g_k × Z0 × ω_c).\n"
        "LP shunt C → HP series L = Z0 / (g_k × ω_c).\n\n"
        "Input: { g_values, cutoff_freq_hz, impedance_ohm? }\n"
        "Returns: { ok, r_source, r_load, elements: [{index, type, value}], warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "g_values": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Ladder g-values.",
            },
            "cutoff_freq_hz": {
                "type": "number",
                "description": "HP cutoff frequency [Hz].",
            },
            "impedance_ohm": {
                "type": "number",
                "description": "Reference impedance [Ω] (default 50 Ω).",
            },
        },
        "required": ["g_values", "cutoff_freq_hz"],
    },
)


@register(_LP_HP_SPEC, write=False)
async def afilter_lp_to_hp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = lp_to_hp_rlc(
        g_values=a.get("g_values"),
        cutoff_freq_hz=a.get("cutoff_freq_hz"),
        impedance_ohm=a.get("impedance_ohm", 50.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. afilter_lp_to_bp
# ═══════════════════════════════════════════════════════════════════════════════

_LP_BP_SPEC = ToolSpec(
    name="afilter_lp_to_bp",
    description=(
        "LP prototype → BP RLC filter via the LP→BP transformation "
        "s → Q(s/ω_0 + ω_0/s), where Q = ω_0/BW.\n\n"
        "Each prototype element maps to an LC resonant pair centred at ω_0.\n\n"
        "Input: { g_values, center_freq_hz, bandwidth_hz, impedance_ohm? }\n"
        "Returns: { ok, Q, elements: [{index, type, resonator: {L_h, C_f, f0_hz}}], warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "g_values": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Ladder g-values.",
            },
            "center_freq_hz": {
                "type": "number",
                "description": "BP center frequency [Hz].",
            },
            "bandwidth_hz": {
                "type": "number",
                "description": "BP 3dB bandwidth [Hz].",
            },
            "impedance_ohm": {
                "type": "number",
                "description": "Reference impedance [Ω] (default 50 Ω).",
            },
        },
        "required": ["g_values", "center_freq_hz", "bandwidth_hz"],
    },
)


@register(_LP_BP_SPEC, write=False)
async def afilter_lp_to_bp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = lp_to_bp_rlc(
        g_values=a.get("g_values"),
        center_freq_hz=a.get("center_freq_hz"),
        bandwidth_hz=a.get("bandwidth_hz"),
        impedance_ohm=a.get("impedance_ohm", 50.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. afilter_sallen_key
# ═══════════════════════════════════════════════════════════════════════════════

_SK_SPEC = ToolSpec(
    name="afilter_sallen_key",
    description=(
        "Sallen-Key equal-component second-order lowpass op-amp filter design.\n\n"
        "Equal capacitors C1=C2=C, equal resistors R1=R2=R=1/(ω_n×C).\n"
        "Required gain K = 3 − 1/Q.  Non-realizable if Q < 0.5 or Q → ∞.\n\n"
        "Input: { cutoff_freq_hz, Q, gain?, capacitor_f? }\n"
        "Returns: { ok, C1_f, C2_f, R1_ohm, R2_ohm, Rf_ohm, Rg_ohm, "
        "K_required_for_Q, realizable, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cutoff_freq_hz": {
                "type": "number",
                "description": "Pole frequency (natural frequency) [Hz].",
            },
            "Q": {
                "type": "number",
                "description": "Pole Q factor (≥ 0.5 for real equal-component design).",
            },
            "gain": {
                "type": "number",
                "description": "DC gain K (default 1.0 for unity gain).",
            },
            "capacitor_f": {
                "type": "number",
                "description": "Capacitor value [F] (default 10 nF).",
            },
        },
        "required": ["cutoff_freq_hz", "Q"],
    },
)


@register(_SK_SPEC, write=False)
async def afilter_sallen_key(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = sallen_key_components(
        cutoff_freq_hz=a.get("cutoff_freq_hz"),
        Q=a.get("Q"),
        gain=a.get("gain", 1.0),
        capacitor_f=a.get("capacitor_f", None),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. afilter_mfb
# ═══════════════════════════════════════════════════════════════════════════════

_MFB_SPEC = ToolSpec(
    name="afilter_mfb",
    description=(
        "Multiple-Feedback (MFB/Rauch) second-order inverting lowpass op-amp "
        "filter component selection.\n\n"
        "Equal capacitors C1=C2=C.  Realizable when discriminant ≥ 0: "
        "(ω_n/Q)² ≥ 4ω_n²(1+|K|).  "
        "Non-realizable cases return ok=True with realizable=False.\n\n"
        "Input: { cutoff_freq_hz, Q, gain?, capacitor_f? }\n"
        "Returns: { ok, C1_f, C2_f, R1_ohm, R2_ohm, R3_ohm, realizable, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cutoff_freq_hz": {
                "type": "number",
                "description": "Pole frequency [Hz].",
            },
            "Q": {
                "type": "number",
                "description": "Pole Q factor.",
            },
            "gain": {
                "type": "number",
                "description": "Midband gain (negative; default −1.0).",
            },
            "capacitor_f": {
                "type": "number",
                "description": "Capacitor value [F] (default 10 nF).",
            },
        },
        "required": ["cutoff_freq_hz", "Q"],
    },
)


@register(_MFB_SPEC, write=False)
async def afilter_mfb(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = multiple_feedback_components(
        cutoff_freq_hz=a.get("cutoff_freq_hz"),
        Q=a.get("Q"),
        gain=a.get("gain", -1.0),
        capacitor_f=a.get("capacitor_f", None),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. afilter_response
# ═══════════════════════════════════════════════════════════════════════════════

_RESP_SPEC = ToolSpec(
    name="afilter_response",
    description=(
        "Compute magnitude (dB), phase (degrees), and group delay (s) of a filter "
        "defined by its poles and zeros at a given frequency.\n\n"
        "Poles and zeros are specified as {re, im} objects.\n"
        "Group delay is approximated by central difference of phase.\n\n"
        "Input: { poles, zeros?, gain_dc?, freq_hz }\n"
        "Returns: { ok, freq_hz, magnitude_db, phase_deg, group_delay_s, H_re, H_im, H_mag }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "poles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "re": {"type": "number"},
                        "im": {"type": "number"},
                    },
                    "required": ["re", "im"],
                },
                "description": "Pole locations as [{re, im}] objects.",
            },
            "zeros": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "re": {"type": "number"},
                        "im": {"type": "number"},
                    },
                    "required": ["re", "im"],
                },
                "description": "Zero locations as [{re, im}] objects (default empty).",
            },
            "gain_dc": {
                "type": "number",
                "description": "DC gain (default 1.0).",
            },
            "freq_hz": {
                "type": "number",
                "description": "Evaluation frequency [Hz].",
            },
        },
        "required": ["poles", "freq_hz"],
    },
)


@register(_RESP_SPEC, write=False)
async def afilter_response(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = filter_response(
        poles=a.get("poles"),
        zeros=a.get("zeros", []),
        gain_dc=a.get("gain_dc", 1.0),
        freq_hz=a.get("freq_hz"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_BW_ORDER_SPEC.name,   _BW_ORDER_SPEC,   afilter_butterworth_order),
    (_CHEB_ORDER_SPEC.name, _CHEB_ORDER_SPEC, afilter_chebyshev_order),
    (_BESS_ORDER_SPEC.name, _BESS_ORDER_SPEC, afilter_bessel_order),
    (_BW_POLES_SPEC.name,   _BW_POLES_SPEC,   afilter_butterworth_poles),
    (_CHEB_POLES_SPEC.name, _CHEB_POLES_SPEC, afilter_chebyshev_poles),
    (_BESS_POLES_SPEC.name, _BESS_POLES_SPEC, afilter_bessel_poles),
    (_BW_G_SPEC.name,       _BW_G_SPEC,       afilter_butterworth_g),
    (_CHEB_G_SPEC.name,     _CHEB_G_SPEC,     afilter_chebyshev_g),
    (_LP_LP_SPEC.name,      _LP_LP_SPEC,      afilter_lp_to_lp),
    (_LP_HP_SPEC.name,      _LP_HP_SPEC,      afilter_lp_to_hp),
    (_LP_BP_SPEC.name,      _LP_BP_SPEC,      afilter_lp_to_bp),
    (_SK_SPEC.name,         _SK_SPEC,         afilter_sallen_key),
    (_MFB_SPEC.name,        _MFB_SPEC,        afilter_mfb),
    (_RESP_SPEC.name,       _RESP_SPEC,       afilter_response),
]
