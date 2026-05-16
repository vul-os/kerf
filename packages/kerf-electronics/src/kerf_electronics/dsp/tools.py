"""
DSP / digital filter design — LLM tools.

Exposes tools to the Kerf agent layer:

  dsp_fft                       — Radix-2 FFT of a real/complex sequence
  dsp_ifft                      — Radix-2 IFFT
  dsp_spectrum                  — DFT magnitude/phase spectrum + bin frequencies
  dsp_bin_frequency             — Frequency of a single DFT bin
  dsp_fir_lp                    — Windowed-sinc lowpass FIR design
  dsp_fir_hp                    — Windowed-sinc highpass FIR design
  dsp_fir_bp                    — Windowed-sinc bandpass FIR design
  dsp_fir_order                 — FIR tap-count estimate (Kaiser/harris rule)
  dsp_iir_butterworth_lp        — Bilinear-transform Butterworth IIR lowpass
  dsp_iir_butterworth_hp        — Bilinear-transform Butterworth IIR highpass
  dsp_biquad_lp                 — RBJ cookbook lowpass biquad
  dsp_biquad_hp                 — RBJ cookbook highpass biquad
  dsp_biquad_bp                 — RBJ cookbook bandpass biquad
  dsp_biquad_notch              — RBJ cookbook notch biquad
  dsp_biquad_peaking            — RBJ cookbook peaking EQ biquad
  dsp_freq_response             — H(e^jω) magnitude/phase from b/a coefficients
  dsp_group_delay               — Group delay from b/a coefficients
  dsp_nyquist_check             — Sampling/aliasing + Nyquist compliance
  dsp_adc_snr                   — ADC quantisation SNR, ENOB, process gain

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

from kerf_electronics.dsp.filters import (
    fft,
    ifft,
    dft_spectrum,
    bin_frequency,
    windowed_sinc_lp,
    windowed_sinc_hp,
    windowed_sinc_bp,
    fir_order_estimate,
    bilinear_butterworth_lp,
    bilinear_butterworth_hp,
    biquad_lp,
    biquad_hp,
    biquad_bp,
    biquad_notch,
    biquad_peaking,
    freq_response,
    group_delay,
    nyquist_check,
    adc_snr,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. dsp_fft
# ═══════════════════════════════════════════════════════════════════════════════

_FFT_SPEC = ToolSpec(
    name="dsp_fft",
    description=(
        "Compute the radix-2 Cooley-Tukey FFT of a real or complex sequence.\n\n"
        "Input length must be a power of 2.  Use dsp_spectrum for the full "
        "one-sided magnitude/phase spectrum of a real signal.\n\n"
        "Input: { x: [{re, im} | number, ...] }\n"
        "Returns: { ok, N, X: [{re, im}, ...] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "x": {
                "type": "array",
                "items": {},
                "description": (
                    "Input samples: either plain numbers (real) or {re, im} objects. "
                    "Length must be a power of 2."
                ),
            },
        },
        "required": ["x"],
    },
)


@register(_FFT_SPEC, write=False)
async def dsp_fft(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    x_raw = a.get("x")
    if not isinstance(x_raw, list):
        return err_payload("x must be a list", "BAD_ARGS")
    try:
        x = []
        for v in x_raw:
            if isinstance(v, dict):
                x.append(complex(v.get("re", 0), v.get("im", 0)))
            else:
                x.append(complex(float(v)))
    except Exception as exc:
        return err_payload(f"invalid sample in x: {exc}", "BAD_ARGS")
    result = fft(x)
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. dsp_ifft
# ═══════════════════════════════════════════════════════════════════════════════

_IFFT_SPEC = ToolSpec(
    name="dsp_ifft",
    description=(
        "Compute the radix-2 IFFT of a frequency-domain sequence.\n\n"
        "Input length must be a power of 2.\n\n"
        "Input: { X: [{re, im}, ...] }\n"
        "Returns: { ok, N, x: [{re, im}, ...] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "X": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "re": {"type": "number"},
                        "im": {"type": "number"},
                    },
                    "required": ["re", "im"],
                },
                "description": "Frequency-domain samples as [{re, im}] objects.",
            },
        },
        "required": ["X"],
    },
)


@register(_IFFT_SPEC, write=False)
async def dsp_ifft(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = ifft(a.get("X", []))
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. dsp_spectrum
# ═══════════════════════════════════════════════════════════════════════════════

_SPECTRUM_SPEC = ToolSpec(
    name="dsp_spectrum",
    description=(
        "Compute the one-sided DFT magnitude and phase spectrum of a real signal.\n\n"
        "Returns N/2+1 frequency bins with magnitude (linear), magnitude (dB), "
        "phase (rad), and corresponding frequencies.\n\n"
        "Input: { x: [number, ...], fs_hz: number }\n"
        "Returns: { ok, N, fs_hz, freq_hz, magnitude, phase_rad, magnitude_db }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "x": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Real-valued time-domain samples. Length must be power of 2.",
            },
            "fs_hz": {
                "type": "number",
                "description": "Sample rate [Hz].",
            },
        },
        "required": ["x", "fs_hz"],
    },
)


@register(_SPECTRUM_SPEC, write=False)
async def dsp_spectrum(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = dft_spectrum(a.get("x", []), a.get("fs_hz"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. dsp_bin_frequency
# ═══════════════════════════════════════════════════════════════════════════════

_BIN_FREQ_SPEC = ToolSpec(
    name="dsp_bin_frequency",
    description=(
        "Return the frequency of DFT bin k for a length-N transform at sample rate fs.\n\n"
        "freq = k × fs / N\n\n"
        "Input: { k, N, fs_hz }\n"
        "Returns: { ok, freq_hz, bin, N, fs_hz }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "k": {"type": "integer", "description": "Bin index (0 ≤ k < N)."},
            "N": {"type": "integer", "description": "DFT length."},
            "fs_hz": {"type": "number", "description": "Sample rate [Hz]."},
        },
        "required": ["k", "N", "fs_hz"],
    },
)


@register(_BIN_FREQ_SPEC, write=False)
async def dsp_bin_frequency(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = bin_frequency(a.get("k"), a.get("N"), a.get("fs_hz"))
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. dsp_fir_lp
# ═══════════════════════════════════════════════════════════════════════════════

_FIR_LP_SPEC = ToolSpec(
    name="dsp_fir_lp",
    description=(
        "Design a windowed-sinc lowpass FIR filter.\n\n"
        "The ideal sinc impulse response is multiplied by the chosen window to "
        "control stopband attenuation vs. transition bandwidth:\n"
        "  rect:     −21 dB stopband,  narrowest transition\n"
        "  hann:     −44 dB\n"
        "  hamming:  −53 dB\n"
        "  blackman: −74 dB, widest transition\n\n"
        "Input: { N, fc_norm, window? }\n"
        "Returns: { ok, N, fc_norm, window, h: [float, ...] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "N": {
                "type": "integer",
                "description": "Number of taps (use odd N for Type-I symmetric FIR).",
            },
            "fc_norm": {
                "type": "number",
                "description": "Normalised cutoff frequency fc/fs in (0, 0.5).",
            },
            "window": {
                "type": "string",
                "enum": ["rect", "hann", "hamming", "blackman"],
                "description": "Window function (default 'hamming').",
            },
        },
        "required": ["N", "fc_norm"],
    },
)


@register(_FIR_LP_SPEC, write=False)
async def dsp_fir_lp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = windowed_sinc_lp(
        N=a.get("N"),
        fc_norm=a.get("fc_norm"),
        window=a.get("window", "hamming"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. dsp_fir_hp
# ═══════════════════════════════════════════════════════════════════════════════

_FIR_HP_SPEC = ToolSpec(
    name="dsp_fir_hp",
    description=(
        "Design a windowed-sinc highpass FIR filter via spectral inversion.\n\n"
        "h_hp[n] = δ[n − M/2] − h_lp[n]  (requires odd N).\n\n"
        "Input: { N, fc_norm, window? }\n"
        "Returns: { ok, N, fc_norm, window, h: [float, ...] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "N": {
                "type": "integer",
                "description": "Number of taps (must be odd).",
            },
            "fc_norm": {
                "type": "number",
                "description": "Normalised cutoff frequency fc/fs in (0, 0.5).",
            },
            "window": {
                "type": "string",
                "enum": ["rect", "hann", "hamming", "blackman"],
                "description": "Window function (default 'hamming').",
            },
        },
        "required": ["N", "fc_norm"],
    },
)


@register(_FIR_HP_SPEC, write=False)
async def dsp_fir_hp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = windowed_sinc_hp(
        N=a.get("N"),
        fc_norm=a.get("fc_norm"),
        window=a.get("window", "hamming"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. dsp_fir_bp
# ═══════════════════════════════════════════════════════════════════════════════

_FIR_BP_SPEC = ToolSpec(
    name="dsp_fir_bp",
    description=(
        "Design a windowed-sinc bandpass FIR filter.\n\n"
        "Implemented as difference of two LP filters: h_bp = h_lp(fh) − h_lp(fl).\n\n"
        "Input: { N, fl_norm, fh_norm, window? }\n"
        "Returns: { ok, N, fl_norm, fh_norm, window, h: [float, ...] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "N": {
                "type": "integer",
                "description": "Number of taps.",
            },
            "fl_norm": {
                "type": "number",
                "description": "Lower normalised cutoff in (0, 0.5).",
            },
            "fh_norm": {
                "type": "number",
                "description": "Upper normalised cutoff in (0, 0.5), must be > fl_norm.",
            },
            "window": {
                "type": "string",
                "enum": ["rect", "hann", "hamming", "blackman"],
                "description": "Window function (default 'hamming').",
            },
        },
        "required": ["N", "fl_norm", "fh_norm"],
    },
)


@register(_FIR_BP_SPEC, write=False)
async def dsp_fir_bp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = windowed_sinc_bp(
        N=a.get("N"),
        fl_norm=a.get("fl_norm"),
        fh_norm=a.get("fh_norm"),
        window=a.get("window", "hamming"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. dsp_fir_order
# ═══════════════════════════════════════════════════════════════════════════════

_FIR_ORDER_SPEC = ToolSpec(
    name="dsp_fir_order",
    description=(
        "Estimate the minimum FIR tap count (N) for a given window and transition "
        "bandwidth using the fred-harris rule-of-thumb:\n\n"
        "  N ≈ ceil(A / Δf_norm)\n\n"
        "where A = 0.9/3.1/3.3/5.5 for rect/hann/hamming/blackman.\n\n"
        "Input: { transition_bw_norm, window? }\n"
        "Returns: { ok, N_estimate, window, transition_bw_norm }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "transition_bw_norm": {
                "type": "number",
                "description": "Normalised transition bandwidth Δf/fs.",
            },
            "window": {
                "type": "string",
                "enum": ["rect", "hann", "hamming", "blackman"],
                "description": "Window function (default 'hamming').",
            },
        },
        "required": ["transition_bw_norm"],
    },
)


@register(_FIR_ORDER_SPEC, write=False)
async def dsp_fir_order(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = fir_order_estimate(
        transition_bw_norm=a.get("transition_bw_norm"),
        window=a.get("window", "hamming"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. dsp_iir_butterworth_lp
# ═══════════════════════════════════════════════════════════════════════════════

_IIR_BW_LP_SPEC = ToolSpec(
    name="dsp_iir_butterworth_lp",
    description=(
        "Design a digital Butterworth lowpass IIR filter using the bilinear "
        "transform with frequency prewarping.\n\n"
        "Prewarping: ω_a = 2 tan(π f_c / f_s) ensures the digital −3 dB point "
        "is exactly at f_c.\n\n"
        "Input: { order, fc_hz, fs_hz }\n"
        "Returns: { ok, order, fc_hz, fs_hz, fc_norm, fc_prewarped_hz, "
        "b: [float,...], a: [float,...] }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order": {
                "type": "integer",
                "description": "Filter order (1–10).",
                "minimum": 1,
                "maximum": 10,
            },
            "fc_hz": {
                "type": "number",
                "description": "−3 dB cutoff frequency [Hz].",
            },
            "fs_hz": {
                "type": "number",
                "description": "Sample rate [Hz].",
            },
        },
        "required": ["order", "fc_hz", "fs_hz"],
    },
)


@register(_IIR_BW_LP_SPEC, write=False)
async def dsp_iir_butterworth_lp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = bilinear_butterworth_lp(
        order=a.get("order"),
        fc_hz=a.get("fc_hz"),
        fs_hz=a.get("fs_hz"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. dsp_iir_butterworth_hp
# ═══════════════════════════════════════════════════════════════════════════════

_IIR_BW_HP_SPEC = ToolSpec(
    name="dsp_iir_butterworth_hp",
    description=(
        "Design a digital Butterworth highpass IIR filter via bilinear transform.\n\n"
        "Derived from the LP prototype by spectral inversion:\n"
        "  b_hp[k] = b_lp[k] × (−1)^k,  a_hp[k] = a_lp[k] × (−1)^k\n\n"
        "Input: { order, fc_hz, fs_hz }\n"
        "Returns: { ok, order, fc_hz, fs_hz, fc_norm, fc_prewarped_hz, b, a }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order": {
                "type": "integer",
                "description": "Filter order (1–10).",
                "minimum": 1,
                "maximum": 10,
            },
            "fc_hz": {
                "type": "number",
                "description": "−3 dB cutoff frequency [Hz].",
            },
            "fs_hz": {
                "type": "number",
                "description": "Sample rate [Hz].",
            },
        },
        "required": ["order", "fc_hz", "fs_hz"],
    },
)


@register(_IIR_BW_HP_SPEC, write=False)
async def dsp_iir_butterworth_hp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = bilinear_butterworth_hp(
        order=a.get("order"),
        fc_hz=a.get("fc_hz"),
        fs_hz=a.get("fs_hz"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. dsp_biquad_lp
# ═══════════════════════════════════════════════════════════════════════════════

_BIQUAD_LP_SPEC = ToolSpec(
    name="dsp_biquad_lp",
    description=(
        "Compute RBJ Audio EQ Cookbook lowpass biquad coefficients.\n\n"
        "H(z) = (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)\n\n"
        "Input: { fc_hz, fs_hz, Q? }\n"
        "Returns: { ok, b: [b0,b1,b2], a: [1,a1,a2], fc_hz, fs_hz, Q }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fc_hz": {"type": "number", "description": "Cutoff frequency [Hz]."},
            "fs_hz": {"type": "number", "description": "Sample rate [Hz]."},
            "Q": {
                "type": "number",
                "description": "Quality factor Q (default 0.7071 = 1/√2 for Butterworth).",
            },
        },
        "required": ["fc_hz", "fs_hz"],
    },
)


@register(_BIQUAD_LP_SPEC, write=False)
async def dsp_biquad_lp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = biquad_lp(
        fc_hz=a.get("fc_hz"),
        fs_hz=a.get("fs_hz"),
        Q=a.get("Q", 0.7071),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. dsp_biquad_hp
# ═══════════════════════════════════════════════════════════════════════════════

_BIQUAD_HP_SPEC = ToolSpec(
    name="dsp_biquad_hp",
    description=(
        "Compute RBJ Audio EQ Cookbook highpass biquad coefficients.\n\n"
        "Input: { fc_hz, fs_hz, Q? }\n"
        "Returns: { ok, b: [b0,b1,b2], a: [1,a1,a2], fc_hz, fs_hz, Q }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fc_hz": {"type": "number", "description": "Cutoff frequency [Hz]."},
            "fs_hz": {"type": "number", "description": "Sample rate [Hz]."},
            "Q": {"type": "number", "description": "Quality factor Q (default 0.7071)."},
        },
        "required": ["fc_hz", "fs_hz"],
    },
)


@register(_BIQUAD_HP_SPEC, write=False)
async def dsp_biquad_hp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = biquad_hp(
        fc_hz=a.get("fc_hz"),
        fs_hz=a.get("fs_hz"),
        Q=a.get("Q", 0.7071),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. dsp_biquad_bp
# ═══════════════════════════════════════════════════════════════════════════════

_BIQUAD_BP_SPEC = ToolSpec(
    name="dsp_biquad_bp",
    description=(
        "Compute RBJ Audio EQ Cookbook bandpass biquad coefficients (0 dB peak at fc).\n\n"
        "Input: { fc_hz, fs_hz, Q? }\n"
        "Returns: { ok, b: [b0,b1,b2], a: [1,a1,a2], fc_hz, fs_hz, Q }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fc_hz": {"type": "number", "description": "Center frequency [Hz]."},
            "fs_hz": {"type": "number", "description": "Sample rate [Hz]."},
            "Q": {"type": "number", "description": "Quality factor Q (default 1.0)."},
        },
        "required": ["fc_hz", "fs_hz"],
    },
)


@register(_BIQUAD_BP_SPEC, write=False)
async def dsp_biquad_bp(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = biquad_bp(
        fc_hz=a.get("fc_hz"),
        fs_hz=a.get("fs_hz"),
        Q=a.get("Q", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. dsp_biquad_notch
# ═══════════════════════════════════════════════════════════════════════════════

_BIQUAD_NOTCH_SPEC = ToolSpec(
    name="dsp_biquad_notch",
    description=(
        "Compute RBJ Audio EQ Cookbook notch (band-reject) biquad coefficients.\n\n"
        "Input: { fc_hz, fs_hz, Q? }\n"
        "Returns: { ok, b: [b0,b1,b2], a: [1,a1,a2], fc_hz, fs_hz, Q }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fc_hz": {"type": "number", "description": "Notch center frequency [Hz]."},
            "fs_hz": {"type": "number", "description": "Sample rate [Hz]."},
            "Q": {"type": "number", "description": "Quality factor Q (default 1.0)."},
        },
        "required": ["fc_hz", "fs_hz"],
    },
)


@register(_BIQUAD_NOTCH_SPEC, write=False)
async def dsp_biquad_notch(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = biquad_notch(
        fc_hz=a.get("fc_hz"),
        fs_hz=a.get("fs_hz"),
        Q=a.get("Q", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 15. dsp_biquad_peaking
# ═══════════════════════════════════════════════════════════════════════════════

_BIQUAD_PEAKING_SPEC = ToolSpec(
    name="dsp_biquad_peaking",
    description=(
        "Compute RBJ Audio EQ Cookbook peaking EQ biquad coefficients.\n\n"
        "Boosts (+) or cuts (−) gain_db around center frequency fc_hz.\n\n"
        "Input: { fc_hz, fs_hz, Q?, gain_db? }\n"
        "Returns: { ok, b: [b0,b1,b2], a: [1,a1,a2], fc_hz, fs_hz, Q, gain_db }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "fc_hz": {"type": "number", "description": "Center frequency [Hz]."},
            "fs_hz": {"type": "number", "description": "Sample rate [Hz]."},
            "Q": {"type": "number", "description": "Quality factor Q (default 1.0)."},
            "gain_db": {
                "type": "number",
                "description": "Boost/cut amount [dB] (default 6.0 dB).",
            },
        },
        "required": ["fc_hz", "fs_hz"],
    },
)


@register(_BIQUAD_PEAKING_SPEC, write=False)
async def dsp_biquad_peaking(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = biquad_peaking(
        fc_hz=a.get("fc_hz"),
        fs_hz=a.get("fs_hz"),
        Q=a.get("Q", 1.0),
        gain_db=a.get("gain_db", 6.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 16. dsp_freq_response
# ═══════════════════════════════════════════════════════════════════════════════

_FREQ_RESP_SPEC = ToolSpec(
    name="dsp_freq_response",
    description=(
        "Evaluate H(e^{jω}) of a digital filter at a single frequency.\n\n"
        "Accepts any filter specified by its b/a difference-equation coefficients.\n\n"
        "Input: { b: [float,...], a: [float,...], freq_hz, fs_hz }\n"
        "Returns: { ok, freq_hz, fs_hz, magnitude, magnitude_db, phase_rad, H_re, H_im }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Numerator (feedforward) coefficients.",
            },
            "a": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Denominator (feedback) coefficients.",
            },
            "freq_hz": {"type": "number", "description": "Evaluation frequency [Hz]."},
            "fs_hz": {"type": "number", "description": "Sample rate [Hz]."},
        },
        "required": ["b", "a", "freq_hz", "fs_hz"],
    },
)


@register(_FREQ_RESP_SPEC, write=False)
async def dsp_freq_response(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = freq_response(
        b=a.get("b", []),
        a=a.get("a", []),
        freq_hz=a.get("freq_hz"),
        fs_hz=a.get("fs_hz"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 17. dsp_group_delay
# ═══════════════════════════════════════════════════════════════════════════════

_GROUP_DELAY_SPEC = ToolSpec(
    name="dsp_group_delay",
    description=(
        "Compute the group delay of a digital filter at a given frequency.\n\n"
        "Approximated by central-difference of phase: −dφ/dω.\n\n"
        "Input: { b, a, freq_hz, fs_hz, delta_hz? }\n"
        "Returns: { ok, freq_hz, fs_hz, group_delay_samples, group_delay_s }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Numerator coefficients.",
            },
            "a": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Denominator coefficients.",
            },
            "freq_hz": {"type": "number", "description": "Evaluation frequency [Hz]."},
            "fs_hz": {"type": "number", "description": "Sample rate [Hz]."},
            "delta_hz": {
                "type": "number",
                "description": "Finite-difference step [Hz] (default 1.0 Hz).",
            },
        },
        "required": ["b", "a", "freq_hz", "fs_hz"],
    },
)


@register(_GROUP_DELAY_SPEC, write=False)
async def dsp_group_delay(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = group_delay(
        b=a.get("b", []),
        a=a.get("a", []),
        freq_hz=a.get("freq_hz"),
        fs_hz=a.get("fs_hz"),
        delta_hz=a.get("delta_hz", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 18. dsp_nyquist_check
# ═══════════════════════════════════════════════════════════════════════════════

_NYQUIST_SPEC = ToolSpec(
    name="dsp_nyquist_check",
    description=(
        "Check whether a sample rate satisfies the Nyquist criterion for a signal "
        "bandwidth, and report the oversampling ratio.\n\n"
        "Aliasing is flagged via warnings.warn and included in the response when "
        "fs ≤ 2 × signal_bw.\n\n"
        "Input: { signal_bw_hz, fs_hz }\n"
        "Returns: { ok, signal_bw_hz, fs_hz, nyquist_hz, oversampling_ratio, "
        "alias_free, recommended_fs_hz, warnings }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "signal_bw_hz": {
                "type": "number",
                "description": "Highest frequency component in the signal [Hz].",
            },
            "fs_hz": {
                "type": "number",
                "description": "Sample rate [Hz].",
            },
        },
        "required": ["signal_bw_hz", "fs_hz"],
    },
)


@register(_NYQUIST_SPEC, write=False)
async def dsp_nyquist_check(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = nyquist_check(
        signal_bw_hz=a.get("signal_bw_hz"),
        fs_hz=a.get("fs_hz"),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 19. dsp_adc_snr
# ═══════════════════════════════════════════════════════════════════════════════

_ADC_SNR_SPEC = ToolSpec(
    name="dsp_adc_snr",
    description=(
        "Compute theoretical ADC performance metrics: SNR, ENOB, process gain.\n\n"
        "  SNR_ideal = 6.02 × N + 1.76 dB  (N-bit full-scale sine)\n"
        "  Process gain = 10 × log10(OSR) / 2  [3 dB per octave of oversampling]\n"
        "  ENOB = (SNR_total − 1.76) / 6.02\n\n"
        "Input: { bits, osr? }\n"
        "Returns: { ok, bits, osr, snr_ideal_db, process_gain_db, "
        "snr_with_osr_db, enob, dynamic_range_db }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "bits": {
                "type": "integer",
                "description": "ADC resolution [bits] (1–32).",
                "minimum": 1,
                "maximum": 32,
            },
            "osr": {
                "type": "number",
                "description": "Oversampling ratio (≥ 1, default 1).",
            },
        },
        "required": ["bits"],
    },
)


@register(_ADC_SNR_SPEC, write=False)
async def dsp_adc_snr(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    result = adc_snr(
        bits=a.get("bits"),
        osr=a.get("osr", 1.0),
    )
    if not result.get("ok"):
        return err_payload(result.get("reason", "error"), "BAD_ARGS")
    return ok_payload(result)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS export — consumed by plugin._register_tools
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    (_FFT_SPEC.name,           _FFT_SPEC,           dsp_fft),
    (_IFFT_SPEC.name,          _IFFT_SPEC,          dsp_ifft),
    (_SPECTRUM_SPEC.name,      _SPECTRUM_SPEC,      dsp_spectrum),
    (_BIN_FREQ_SPEC.name,      _BIN_FREQ_SPEC,      dsp_bin_frequency),
    (_FIR_LP_SPEC.name,        _FIR_LP_SPEC,        dsp_fir_lp),
    (_FIR_HP_SPEC.name,        _FIR_HP_SPEC,        dsp_fir_hp),
    (_FIR_BP_SPEC.name,        _FIR_BP_SPEC,        dsp_fir_bp),
    (_FIR_ORDER_SPEC.name,     _FIR_ORDER_SPEC,     dsp_fir_order),
    (_IIR_BW_LP_SPEC.name,     _IIR_BW_LP_SPEC,     dsp_iir_butterworth_lp),
    (_IIR_BW_HP_SPEC.name,     _IIR_BW_HP_SPEC,     dsp_iir_butterworth_hp),
    (_BIQUAD_LP_SPEC.name,     _BIQUAD_LP_SPEC,     dsp_biquad_lp),
    (_BIQUAD_HP_SPEC.name,     _BIQUAD_HP_SPEC,     dsp_biquad_hp),
    (_BIQUAD_BP_SPEC.name,     _BIQUAD_BP_SPEC,     dsp_biquad_bp),
    (_BIQUAD_NOTCH_SPEC.name,  _BIQUAD_NOTCH_SPEC,  dsp_biquad_notch),
    (_BIQUAD_PEAKING_SPEC.name, _BIQUAD_PEAKING_SPEC, dsp_biquad_peaking),
    (_FREQ_RESP_SPEC.name,     _FREQ_RESP_SPEC,     dsp_freq_response),
    (_GROUP_DELAY_SPEC.name,   _GROUP_DELAY_SPEC,   dsp_group_delay),
    (_NYQUIST_SPEC.name,       _NYQUIST_SPEC,       dsp_nyquist_check),
    (_ADC_SNR_SPEC.name,       _ADC_SNR_SPEC,       dsp_adc_snr),
]
