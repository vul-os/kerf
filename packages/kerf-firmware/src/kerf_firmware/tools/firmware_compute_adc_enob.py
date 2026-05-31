"""LLM tool: firmware_compute_adc_enob — ADC effective-number-of-bits calculator.

Computes ENOB from a SINAD specification or directly-specified ENOB, then
optionally improves via oversampling (TI SBAA221 model: each 4× OSR → +1 bit),
returns effective voltage resolution, and recommends the OSR needed for a
target bit-depth.

References
----------
  Analog Devices MT-003 Rev. B — "Understand SINAD, ENOB, SNR, THD, THD+N,
    and SFDR So You Don't Get Lost in the Noise Floor".
  Texas Instruments SBAA221 — "Oversampling and Decimation to Increase ADC
    Resolution".
  Maxim AN2861 — "Oversampling for ADCs".
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.adc_effective_bits import (
    ADCSpec,
    OversamplingSpec,
    compute_adc_enob,
)


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_compute_adc_enob",
    description=(
        "Compute the Effective Number Of Bits (ENOB) of an MCU ADC channel, "
        "optionally with oversampling improvement, and recommend the oversampling "
        "ratio needed to reach a target resolution.\n\n"
        "ENOB derivation (ADI MT-003 Rev. B):\n"
        "  From SINAD: ENOB = (SINAD_dB − 1.76) / 6.02\n"
        "  From datasheet: use enob_specified directly.\n"
        "  Fallback: ENOB ≈ nominal_bits − 0.5 (rough; supply SINAD or enob_specified "
        "for accuracy).\n\n"
        "Oversampling gain (TI SBAA221):\n"
        "  ENOB_after = ENOB + log2(OSR) / 2\n"
        "  Each 4× OSR adds 1 effective bit (requires OSR independent white-noise "
        "samples, averaged then decimated).\n\n"
        "Depth-bar oracles:\n"
        "  12-bit ADC, SINAD=68 dB, no oversampling:\n"
        "    ENOB = (68 − 1.76) / 6.02 ≈ 11.00 bits.\n"
        "  Same ADC, OSR=16:\n"
        "    gain = log2(16)/2 = 2.0 → ENOB_after ≈ 13.00 bits.\n"
        "  Target 14 bits from 11 ENOB:\n"
        "    OSR = 4^(14−11) = 4^3 = 64.\n\n"
        "HONEST CAVEAT: oversampling gain assumes white (uncorrelated) noise only. "
        "Correlated sources — 50/60 Hz mains hum, PSU ripple, reference noise, "
        "quantisation plateaux — limit real-world improvement. "
        "See ADI MT-003; TI SBAA221; Maxim AN2861."
    ),
    input_schema={
        "type": "object",
        "required": ["nominal_bits", "sampling_rate_Hz", "reference_voltage_V",
                     "signal_full_scale_V"],
        "properties": {
            "nominal_bits": {
                "type": "integer",
                "description": (
                    "Architectural resolution of the ADC (e.g. 12 for STM32F4 "
                    "12-bit ADC). Range: 1–32."
                ),
                "minimum": 1,
                "maximum": 32,
            },
            "sinad_dB": {
                "type": "number",
                "description": (
                    "Signal-to-Noise-And-Distortion ratio in dB from the datasheet "
                    "AC-performance table.  Used to compute ENOB via the ADI MT-003 "
                    "formula.  Typical: 68–74 dB for a 12-bit MCU ADC."
                ),
                "exclusiveMinimum": 0,
            },
            "enob_specified": {
                "type": "number",
                "description": (
                    "Effective Number Of Bits read directly from the datasheet. "
                    "Takes priority over sinad_dB when both are supplied."
                ),
                "exclusiveMinimum": 0,
            },
            "sampling_rate_Hz": {
                "type": "integer",
                "description": (
                    "ADC sampling rate in Hz (informational; e.g. 1_000_000 for "
                    "STM32F4 at 1 Msps)."
                ),
                "minimum": 1,
            },
            "reference_voltage_V": {
                "type": "number",
                "description": (
                    "ADC reference voltage in volts (VREF+). "
                    "Typical: 3.3 V for 3.3 V MCU, 5.0 V for 5 V AVR."
                ),
                "exclusiveMinimum": 0,
            },
            "signal_full_scale_V": {
                "type": "number",
                "description": (
                    "Peak-to-peak voltage swing of the actual input signal in volts. "
                    "Must be ≤ reference_voltage_V. Used to compute the effective "
                    "voltage resolution in µV."
                ),
                "exclusiveMinimum": 0,
            },
            "oversample_ratio": {
                "type": "integer",
                "description": (
                    "Number of raw ADC samples averaged before decimation. "
                    "Powers-of-4 (1, 4, 16, 64, 256, …) yield exactly integer extra "
                    "bits. Default: 1 (no oversampling)."
                ),
                "minimum": 1,
                "default": 1,
            },
            "decimation": {
                "type": "integer",
                "description": (
                    "Decimation factor applied after accumulation (informational only). "
                    "Default: 1."
                ),
                "minimum": 1,
                "default": 1,
            },
            "target_bits": {
                "type": "number",
                "description": (
                    "Desired effective resolution in bits. When provided, the tool "
                    "returns the minimum power-of-4 OSR needed to achieve this from "
                    "the base ENOB. E.g. target_bits=14 with base ENOB=11 → "
                    "recommend OSR=64."
                ),
                "exclusiveMinimum": 0,
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_compute_adc_enob(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute ENOB computation and return a JSON payload."""

    # -- Required fields -------------------------------------------------------
    nominal_bits = args.get("nominal_bits")
    sampling_rate_Hz = args.get("sampling_rate_Hz")
    reference_voltage_V = args.get("reference_voltage_V")
    signal_full_scale_V = args.get("signal_full_scale_V")

    if nominal_bits is None:
        return err_payload("'nominal_bits' is required", "BAD_ARGS")
    if sampling_rate_Hz is None:
        return err_payload("'sampling_rate_Hz' is required", "BAD_ARGS")
    if reference_voltage_V is None:
        return err_payload("'reference_voltage_V' is required", "BAD_ARGS")
    if signal_full_scale_V is None:
        return err_payload("'signal_full_scale_V' is required", "BAD_ARGS")

    try:
        nominal_bits = int(nominal_bits)
        sampling_rate_Hz = int(sampling_rate_Hz)
        reference_voltage_V = float(reference_voltage_V)
        signal_full_scale_V = float(signal_full_scale_V)
    except (TypeError, ValueError) as exc:
        return err_payload(f"Invalid numeric argument: {exc}", "BAD_ARGS")

    # -- Optional fields -------------------------------------------------------
    sinad_dB = args.get("sinad_dB")
    enob_specified = args.get("enob_specified")
    oversample_ratio = args.get("oversample_ratio", 1)
    decimation = args.get("decimation", 1)
    target_bits = args.get("target_bits")

    try:
        if sinad_dB is not None:
            sinad_dB = float(sinad_dB)
        if enob_specified is not None:
            enob_specified = float(enob_specified)
        oversample_ratio = int(oversample_ratio)
        decimation = int(decimation)
        if target_bits is not None:
            target_bits = float(target_bits)
    except (TypeError, ValueError) as exc:
        return err_payload(f"Invalid optional argument: {exc}", "BAD_ARGS")

    # -- Build spec objects ---------------------------------------------------
    try:
        adc = ADCSpec(
            nominal_bits=nominal_bits,
            sampling_rate_Hz=sampling_rate_Hz,
            reference_voltage_V=reference_voltage_V,
            signal_full_scale_V=signal_full_scale_V,
            sinad_dB=sinad_dB,
            enob_specified=enob_specified,
        )
    except ValueError as exc:
        return err_payload(f"Invalid ADC spec: {exc}", "BAD_ARGS")

    try:
        oversampling = OversamplingSpec(
            oversample_ratio=oversample_ratio,
            decimation=decimation,
        )
    except ValueError as exc:
        return err_payload(f"Invalid oversampling spec: {exc}", "BAD_ARGS")

    # -- Compute ---------------------------------------------------------------
    try:
        report = compute_adc_enob(adc, oversampling, target_bits=target_bits)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Computation error: {exc}", "COMPUTE_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_compute_adc_enob_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_compute_adc_enob(a, ctx)
