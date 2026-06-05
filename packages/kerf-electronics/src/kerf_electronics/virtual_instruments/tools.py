"""
tools.py — LLM-callable tools for the virtual instrument bench.

Registered tools
----------------
    eda_virtual_instrument   — oscilloscope / multimeter / function-gen
    eda_probe_nodes          — per-node V and per-branch I overlay
"""

from __future__ import annotations

import json
import math
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register

# ---------------------------------------------------------------------------
# Tool: eda_virtual_instrument
# ---------------------------------------------------------------------------

_EDA_VIRTUAL_INSTRUMENT_SPEC = ToolSpec(
    name="eda_virtual_instrument",
    description=(
        "Virtual instrument bench — oscilloscope, multimeter, and function "
        "generator — operating on SPICE simulation waveforms. "
        "\n\n"
        "Oscilloscope: multi-channel time-domain trace with V/div, time/div, "
        "trigger level, and cursor measurements (Vpp, frequency, rise-time, "
        "RMS, DC). "
        "\n\n"
        "Multimeter: DC voltage, AC voltage (peak), AC RMS voltage, DC current, "
        "or AC RMS current readout at a chosen node. "
        "\n\n"
        "Function generator: produce a stimulus spec (sine/square/triangle, "
        "freq/amp/offset/duty) that drives a transient sim — returns SPICE "
        "source line and .TRAN directive."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "instrument": {
                "type": "string",
                "enum": ["oscilloscope", "multimeter", "function_generator"],
                "description": "Which virtual instrument to use.",
            },
            "waveforms": {
                "type": "array",
                "description": (
                    "Array of waveform objects from a SPICE simulation result. "
                    "Each object must have: name (str), kind ('V'|'I'), "
                    "x (list of floats, time in seconds), y (list of floats, values). "
                    "Required for oscilloscope and multimeter; omit for function_generator."
                ),
                "items": {"type": "object"},
            },
            # Oscilloscope params
            "channels": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Oscilloscope: list of channel node expressions to measure, "
                    "e.g. ['V(out)', 'V(in)']."
                ),
            },
            # Multimeter params
            "node": {
                "type": "string",
                "description": (
                    "Multimeter: node expression to measure, e.g. 'V(out)' or 'I(V1)'."
                ),
            },
            "mode": {
                "type": "string",
                "enum": [
                    "dc_voltage", "ac_voltage", "ac_voltage_rms",
                    "dc_current", "ac_current_rms",
                ],
                "description": (
                    "Multimeter mode. "
                    "dc_voltage: arithmetic mean. "
                    "ac_voltage: peak amplitude (Vpp/2). "
                    "ac_voltage_rms / ac_current_rms: RMS of AC component. "
                    "dc_current: arithmetic mean of current trace."
                ),
            },
            # Function generator params
            "waveform": {
                "type": "string",
                "enum": ["sine", "square", "triangle"],
                "description": "Function generator waveform type.",
            },
            "freq_hz": {
                "type": "number",
                "description": "Function generator frequency in Hz.",
            },
            "amplitude_v": {
                "type": "number",
                "description": "Function generator amplitude (zero-to-peak) in volts.",
            },
            "offset_v": {
                "type": "number",
                "description": "Function generator DC offset in volts (default 0).",
            },
            "duty_cycle": {
                "type": "number",
                "description": "Duty cycle for square wave, 0.0–1.0 (default 0.5).",
            },
            "source_name": {
                "type": "string",
                "description": "SPICE source reference designator (default 'stim').",
            },
            "pos_node": {
                "type": "string",
                "description": "Positive terminal node name (default 'vin').",
            },
            "neg_node": {
                "type": "string",
                "description": "Negative terminal node name (default '0' = GND).",
            },
        },
        "required": ["instrument"],
    },
)


@register(_EDA_VIRTUAL_INSTRUMENT_SPEC, write=False)
async def eda_virtual_instrument(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    instrument = a.get("instrument", "")
    if instrument not in ("oscilloscope", "multimeter", "function_generator"):
        return err_payload(
            "instrument must be 'oscilloscope', 'multimeter', or 'function_generator'",
            "BAD_ARGS",
        )

    # ── Oscilloscope ──────────────────────────────────────────────────────────
    if instrument == "oscilloscope":
        waveforms = a.get("waveforms")
        channels = a.get("channels")
        if not waveforms:
            return err_payload("waveforms is required for oscilloscope", "BAD_ARGS")
        if not channels or not isinstance(channels, list):
            return err_payload("channels (list of node expressions) is required for oscilloscope", "BAD_ARGS")

        from kerf_electronics.virtual_instruments.instruments import oscilloscope_measure
        result = oscilloscope_measure(waveforms, channels)

        def _ch_dict(ch):
            return {
                "channel": ch.channel,
                "vpp": ch.vpp,
                "v_min": ch.v_min,
                "v_max": ch.v_max,
                "dc_mean": ch.dc_mean,
                "rms": ch.rms,
                "ac_rms": ch.ac_rms,
                "frequency_hz": ch.frequency_hz,
                "period_s": ch.period_s,
                "rise_time_s": ch.rise_time_s,
                "n_samples": ch.n_samples,
            }

        return ok_payload({
            "instrument": "oscilloscope",
            "channels": [_ch_dict(ch) for ch in result.channels],
            "time_start_s": result.time_start_s,
            "time_stop_s": result.time_stop_s,
            "sample_rate_hz": result.sample_rate_hz,
            "warnings": result.warnings,
        })

    # ── Multimeter ────────────────────────────────────────────────────────────
    if instrument == "multimeter":
        waveforms = a.get("waveforms")
        node = a.get("node", "")
        mode = a.get("mode", "dc_voltage")
        if not waveforms:
            return err_payload("waveforms is required for multimeter", "BAD_ARGS")
        if not node:
            return err_payload("node is required for multimeter", "BAD_ARGS")

        from kerf_electronics.virtual_instruments.instruments import multimeter_measure
        r = multimeter_measure(waveforms, node, mode)

        return ok_payload({
            "instrument": "multimeter",
            "node": r.node,
            "mode": r.mode,
            "value": r.value if not math.isnan(r.value) else None,
            "unit": r.unit,
            "n_samples": r.n_samples,
            "warning": r.warning,
        })

    # ── Function generator ────────────────────────────────────────────────────
    if instrument == "function_generator":
        waveform = a.get("waveform", "")
        freq_hz = a.get("freq_hz")
        amplitude_v = a.get("amplitude_v")

        if not waveform:
            return err_payload("waveform is required for function_generator", "BAD_ARGS")
        if freq_hz is None:
            return err_payload("freq_hz is required for function_generator", "BAD_ARGS")
        if amplitude_v is None:
            return err_payload("amplitude_v is required for function_generator", "BAD_ARGS")

        try:
            from kerf_electronics.virtual_instruments.instruments import function_generator_spec
            spec = function_generator_spec(
                waveform=str(waveform),
                freq_hz=float(freq_hz),
                amplitude_v=float(amplitude_v),
                offset_v=float(a.get("offset_v", 0.0)),
                duty_cycle=float(a.get("duty_cycle", 0.5)),
                source_name=str(a.get("source_name", "stim")),
                pos_node=str(a.get("pos_node", "vin")),
                neg_node=str(a.get("neg_node", "0")),
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "instrument": "function_generator",
            "waveform": spec.waveform,
            "freq_hz": spec.freq_hz,
            "amplitude_v": spec.amplitude_v,
            "offset_v": spec.offset_v,
            "duty_cycle": spec.duty_cycle,
            "source_name": spec.source_name,
            "pos_node": spec.pos_node,
            "neg_node": spec.neg_node,
            "spice_line": spec.to_spice_line(),
            "tran_directive": spec.to_tran_directive(),
        })

    return err_payload("unreachable", "INTERNAL")


# ---------------------------------------------------------------------------
# Tool: eda_probe_nodes
# ---------------------------------------------------------------------------

_EDA_PROBE_NODES_SPEC = ToolSpec(
    name="eda_probe_nodes",
    description=(
        "Interactive probe — given simulation waveforms and a list of node "
        "names (or branch current expressions), return per-node V and per-branch I "
        "from the last transient or operating-point result, formatted for on-wire "
        "schematic overlay display. "
        "\n\n"
        "Each returned probe object contains: node name, kind (V/I), instantaneous "
        "value at the requested time (or DC mean), unit, DC mean, RMS across all "
        "samples, a formatted label for overlay, and a 'not_found' flag. "
        "\n\n"
        "Use at_time to read a specific simulation time-step (e.g. 0.01 for 10 ms)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "waveforms": {
                "type": "array",
                "description": (
                    "Array of waveform objects from a SPICE simulation result. "
                    "Each object must have: name (str), x (list[float], time s), "
                    "y (list[float], values V or A)."
                ),
                "items": {"type": "object"},
            },
            "nodes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of node/branch expressions to probe. "
                    "Voltage nodes: 'V(out)', 'V(vdd)', or just 'out'. "
                    "Current branches: 'I(V1)', 'I(R1)'."
                ),
            },
            "at_time": {
                "type": "number",
                "description": (
                    "Time in seconds at which to read instantaneous values. "
                    "Omit or set to null to return the DC mean instead."
                ),
            },
        },
        "required": ["waveforms", "nodes"],
    },
)


@register(_EDA_PROBE_NODES_SPEC, write=False)
async def eda_probe_nodes(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    waveforms = a.get("waveforms")
    nodes = a.get("nodes")
    at_time = a.get("at_time")

    if not waveforms:
        return err_payload("waveforms is required", "BAD_ARGS")
    if not nodes or not isinstance(nodes, list):
        return err_payload("nodes must be a non-empty list of strings", "BAD_ARGS")

    try:
        from kerf_electronics.virtual_instruments.probe import probe_nodes, format_probe_overlay
        result = probe_nodes(waveforms, nodes, at_time=at_time)
    except Exception as exc:
        return err_payload(f"probe error: {exc}", "ERROR")

    overlays = [format_probe_overlay(p) for p in result.probes]

    return ok_payload({
        "probes": overlays,
        "warnings": result.warnings,
        "at_time": at_time,
    })


# ---------------------------------------------------------------------------
# TOOLS list for plugin registration (mirrors pattern used elsewhere)
# ---------------------------------------------------------------------------

TOOLS = [
    ("eda_virtual_instrument", _EDA_VIRTUAL_INSTRUMENT_SPEC, eda_virtual_instrument),
    ("eda_probe_nodes", _EDA_PROBE_NODES_SPEC, eda_probe_nodes),
]
