"""
instruments.py — virtual oscilloscope, multimeter, and function-generator
helpers that wrap dsp_measures and operate on waveform data returned by the
ngspice bridge.

Public API
----------
    oscilloscope_measure(waveforms, channels, ...)   -> OscopeResult
    multimeter_measure(waveforms, node, mode)        -> MmResult
    function_generator_spec(waveform, freq, amp, offset, duty) -> FgenSpec

All helpers are pure-Python with no external dependencies.

Waveform shape
--------------
A waveform dict from the ngspice bridge has keys:
    "name"  : str   — node expression, e.g. "V(out)", "I(V1)"
    "kind"  : str   — "V" or "I"
    "xUnit" : str   — usually "s"
    "yUnit" : str   — "V" or "A"
    "x"     : list[float]   — time axis (seconds)
    "y"     : list[float]   — sample values

Or a dict {node_name: list[float], "time": list[float]} from
parse_ngspice_output in spice_netlist.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from kerf_electronics.virtual_instruments.dsp_measures import (
    measure_ac_rms,
    measure_dc,
    measure_frequency,
    measure_rms,
    measure_rise_time,
    measure_vpp,
)


# ---------------------------------------------------------------------------
# Oscilloscope
# ---------------------------------------------------------------------------

@dataclass
class ChannelMeasurement:
    """Measurements for one oscilloscope channel."""
    channel: str
    """Node expression, e.g. 'V(out)'."""
    vpp: float
    """Peak-to-peak amplitude (V or A)."""
    v_min: float
    """Minimum sample value."""
    v_max: float
    """Maximum sample value."""
    dc_mean: float
    """DC mean (arithmetic mean)."""
    rms: float
    """Total RMS."""
    ac_rms: float
    """AC RMS (zero-mean component)."""
    frequency_hz: float | None
    """Dominant frequency in Hz, or None if not periodic / insufficient data."""
    period_s: float | None
    """Period in seconds, or None."""
    rise_time_s: float | None
    """10%–90% rise time in seconds, or None if no clear edge found."""
    n_samples: int
    """Number of samples in the trace."""


@dataclass
class OscopeResult:
    """Result from oscilloscope_measure."""
    channels: list[ChannelMeasurement] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    time_start_s: float | None = None
    time_stop_s: float | None = None
    sample_rate_hz: float | None = None


def oscilloscope_measure(
    waveforms: list[dict] | dict,
    channels: list[str],
) -> OscopeResult:
    """Measure oscilloscope parameters on the requested channels.

    Parameters
    ----------
    waveforms:
        Either a list of waveform dicts (from routes_spice.parse_raw_file) or
        a dict mapping node names to sample lists (from parse_ngspice_output).
    channels:
        List of channel names to measure (e.g. ["V(out)", "V(in)"]).
        Each must correspond to a waveform in *waveforms*.

    Returns
    -------
    OscopeResult
    """
    result = OscopeResult()
    wave_map = _build_wave_map(waveforms)

    # Resolve time axis
    t = wave_map.get("time") or wave_map.get("t")
    if isinstance(waveforms, list):
        for w in waveforms:
            if isinstance(w, dict) and w.get("x"):
                t = w["x"]
                break

    if t:
        result.time_start_s = float(t[0]) if t else None
        result.time_stop_s = float(t[-1]) if t else None
        if len(t) >= 2:
            dt = (float(t[-1]) - float(t[0])) / (len(t) - 1)
            result.sample_rate_hz = 1.0 / dt if dt > 0 else None

    for ch in channels:
        y = _find_channel_samples(wave_map, ch, waveforms)
        if y is None:
            result.warnings.append(f"channel '{ch}' not found in waveforms")
            continue
        if len(y) < 2:
            result.warnings.append(f"channel '{ch}' has too few samples ({len(y)})")
            continue

        y_f = [float(v) for v in y]
        t_f = [float(v) for v in t] if t and len(t) == len(y_f) else None

        freq = measure_frequency(t_f, y_f) if t_f else None
        rise = measure_rise_time(t_f, y_f) if t_f else None

        result.channels.append(ChannelMeasurement(
            channel=ch,
            vpp=measure_vpp(y_f),
            v_min=min(y_f),
            v_max=max(y_f),
            dc_mean=measure_dc(y_f),
            rms=measure_rms(y_f),
            ac_rms=measure_ac_rms(y_f),
            frequency_hz=freq,
            period_s=(1.0 / freq) if freq else None,
            rise_time_s=rise,
            n_samples=len(y_f),
        ))

    return result


# ---------------------------------------------------------------------------
# Multimeter
# ---------------------------------------------------------------------------

class MultimeterMode:
    DC_VOLTAGE = "dc_voltage"
    AC_VOLTAGE = "ac_voltage"
    AC_VOLTAGE_RMS = "ac_voltage_rms"
    DC_CURRENT = "dc_current"
    AC_CURRENT_RMS = "ac_current_rms"


@dataclass
class MmResult:
    """Result from multimeter_measure."""
    node: str
    mode: str
    value: float
    unit: str
    n_samples: int
    warning: str | None = None


def multimeter_measure(
    waveforms: list[dict] | dict,
    node: str,
    mode: str = MultimeterMode.DC_VOLTAGE,
) -> MmResult:
    """Read a multimeter value at *node* from simulation waveforms.

    Parameters
    ----------
    waveforms:
        Waveform data from ngspice bridge.
    node:
        Node expression, e.g. ``"V(out)"`` or ``"I(V1)"``.
    mode:
        One of the ``MultimeterMode`` constants.

    Returns
    -------
    MmResult
    """
    wave_map = _build_wave_map(waveforms)
    y = _find_channel_samples(wave_map, node, waveforms)
    if y is None:
        return MmResult(
            node=node, mode=mode, value=math.nan,
            unit="?", n_samples=0,
            warning=f"node '{node}' not found in waveforms",
        )
    y_f = [float(v) for v in y]
    is_current = node.upper().startswith("I(") or "current" in node.lower()
    unit = "A" if is_current else "V"

    if mode == MultimeterMode.DC_VOLTAGE or mode == MultimeterMode.DC_CURRENT:
        value = measure_dc(y_f)
    elif mode == MultimeterMode.AC_VOLTAGE:
        value = measure_vpp(y_f) / 2.0  # peak amplitude (not RMS)
    elif mode in (MultimeterMode.AC_VOLTAGE_RMS, MultimeterMode.AC_CURRENT_RMS):
        value = measure_ac_rms(y_f)
    else:
        value = measure_dc(y_f)

    return MmResult(node=node, mode=mode, value=value, unit=unit, n_samples=len(y_f))


# ---------------------------------------------------------------------------
# Function generator stimulus spec
# ---------------------------------------------------------------------------

@dataclass
class FgenSpec:
    """A function-generator stimulus specification for ngspice transient sim.

    Generates the SPICE source line(s) to drive a transient analysis.
    """
    waveform: str   # "sine" | "square" | "triangle"
    freq_hz: float
    amplitude_v: float
    offset_v: float
    duty_cycle: float   # 0.0–1.0, only used for square wave
    source_name: str    # SPICE source reference, e.g. "V1"
    pos_node: str       # positive terminal node
    neg_node: str       # negative terminal node (usually "0" = GND)

    def to_spice_line(self) -> str:
        """Return the SPICE netlist line for this stimulus source."""
        period_s = 1.0 / self.freq_hz
        if self.waveform == "sine":
            # SIN(offset amplitude freq)
            return (
                f"V{self.source_name} {self.pos_node} {self.neg_node} "
                f"SIN({self.offset_v:.6g} {self.amplitude_v:.6g} {self.freq_hz:.6g})"
            )
        elif self.waveform == "square":
            # PULSE(low high td tr tf pw per) — 50 % duty or custom
            pw = period_s * self.duty_cycle
            tr = period_s * 0.001  # 0.1 % rise time
            tf = tr
            td = 0.0
            low = self.offset_v - self.amplitude_v
            high = self.offset_v + self.amplitude_v
            return (
                f"V{self.source_name} {self.pos_node} {self.neg_node} "
                f"PULSE({low:.6g} {high:.6g} "
                f"{td:.4e} {tr:.4e} {tf:.4e} {pw:.4e} {period_s:.4e})"
            )
        elif self.waveform == "triangle":
            # Approximate triangle with PULSE and slow rise/fall
            half = period_s / 2.0
            low = self.offset_v - self.amplitude_v
            high = self.offset_v + self.amplitude_v
            return (
                f"V{self.source_name} {self.pos_node} {self.neg_node} "
                f"PULSE({low:.6g} {high:.6g} "
                f"0 {half:.4e} {half:.4e} {1e-12:.4e} {period_s:.4e})"
            )
        else:
            raise ValueError(f"Unknown waveform type: '{self.waveform}'. Use 'sine', 'square', or 'triangle'.")

    def to_tran_directive(self, n_cycles: float = 10.0) -> str:
        """Return a .TRAN directive that covers *n_cycles* of this waveform."""
        period_s = 1.0 / self.freq_hz
        tstop = period_s * n_cycles
        tstep = period_s / 100.0
        return f".TRAN {tstep:.4e} {tstop:.4e}"


def function_generator_spec(
    waveform: str,
    freq_hz: float,
    amplitude_v: float,
    offset_v: float = 0.0,
    duty_cycle: float = 0.5,
    source_name: str = "Vstim",
    pos_node: str = "vin",
    neg_node: str = "0",
) -> FgenSpec:
    """Create a function-generator stimulus specification.

    Parameters
    ----------
    waveform:
        One of ``"sine"``, ``"square"``, or ``"triangle"``.
    freq_hz:
        Signal frequency in Hz.
    amplitude_v:
        Amplitude (zero-to-peak) in volts.
    offset_v:
        DC offset in volts (default 0).
    duty_cycle:
        Duty cycle for square waves, 0.0–1.0 (default 0.5 = 50 %).
    source_name:
        SPICE source reference designator suffix (e.g. ``"stim"``
        produces ``Vstim``).
    pos_node:
        Positive terminal node name.
    neg_node:
        Negative terminal node (usually ``"0"`` for ground).

    Returns
    -------
    FgenSpec

    Raises
    ------
    ValueError
        If *waveform* is not one of the supported types, *freq_hz* <= 0,
        *amplitude_v* < 0, or *duty_cycle* outside [0, 1].
    """
    if waveform not in ("sine", "square", "triangle"):
        raise ValueError(f"waveform must be 'sine', 'square', or 'triangle', got '{waveform}'")
    if freq_hz <= 0:
        raise ValueError(f"freq_hz must be positive, got {freq_hz}")
    if amplitude_v < 0:
        raise ValueError(f"amplitude_v must be non-negative, got {amplitude_v}")
    if not (0.0 <= duty_cycle <= 1.0):
        raise ValueError(f"duty_cycle must be in [0, 1], got {duty_cycle}")

    return FgenSpec(
        waveform=waveform,
        freq_hz=freq_hz,
        amplitude_v=amplitude_v,
        offset_v=offset_v,
        duty_cycle=duty_cycle,
        source_name=source_name,
        pos_node=pos_node,
        neg_node=neg_node,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_wave_map(waveforms: list[dict] | dict) -> dict[str, list[float]]:
    """Convert the waveforms payload into a name→samples dict."""
    if isinstance(waveforms, dict):
        return {k: list(v) for k, v in waveforms.items()}
    if isinstance(waveforms, list):
        result: dict[str, list[float]] = {}
        for w in waveforms:
            if not isinstance(w, dict):
                continue
            name = w.get("name", "")
            y = w.get("y")
            if name and isinstance(y, list):
                result[name] = y
            # Also index by lowercase
            if name.lower() != name:
                result[name.lower()] = y or []
        return result
    return {}


def _find_channel_samples(
    wave_map: dict[str, list],
    channel: str,
    waveforms: Any,
) -> list[float] | None:
    """Find samples for *channel* in *wave_map* using various name aliases."""
    # Direct lookup
    if channel in wave_map:
        return wave_map[channel]
    # Case-insensitive lookup
    ch_lower = channel.lower()
    for key in wave_map:
        if key.lower() == ch_lower:
            return wave_map[key]
    # For the list form: also search by waveform name without V()/I() wrapper
    # e.g. "out" matches "V(out)"
    for key in wave_map:
        key_stripped = key.lower().lstrip("vi(").rstrip(")")
        ch_stripped = ch_lower.lstrip("vi(").rstrip(")")
        if key_stripped == ch_stripped:
            return wave_map[key]
    return None
