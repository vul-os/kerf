"""
probe.py — interactive probe model for on-wire voltage/current overlays.

Given ngspice simulation waveforms and a list of node names, ``probe_nodes``
returns per-node V (and per-branch I) from the last transient or
operating-point result, formatted for on-wire schematic overlay display.

Public API
----------
    probe_nodes(waveforms, nodes, at_time=None) -> ProbeResult
        Return instantaneous or steady-state values at the named nodes.

    ProbeResult
    NodeProbe
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from kerf_electronics.virtual_instruments.dsp_measures import measure_dc, measure_rms
from kerf_electronics.virtual_instruments.instruments import (
    _build_wave_map,
    _find_channel_samples,
)


@dataclass
class NodeProbe:
    """Probe reading at a single node or branch."""
    node: str
    """Node expression, e.g. 'V(out)' or 'I(R1)'."""
    kind: str
    """'V' for voltage, 'I' for current."""
    value_v_or_a: float
    """Instantaneous or mean value (V or A), depending on *probe_mode*."""
    unit: str
    """'V' or 'A'."""
    dc_mean: float
    """Arithmetic mean across all time steps."""
    rms: float
    """Total RMS across all time steps."""
    n_samples: int
    """Number of time-step samples available."""
    at_time_s: float | None = None
    """The time at which *value_v_or_a* was sampled (None = mean/DC)."""
    not_found: bool = False
    """True when the node was not present in the simulation output."""


@dataclass
class ProbeResult:
    """Result from probe_nodes."""
    probes: list[NodeProbe] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def probe_nodes(
    waveforms: list[dict] | dict,
    nodes: list[str],
    at_time: float | None = None,
) -> ProbeResult:
    """Probe per-node voltage and per-branch current.

    Parameters
    ----------
    waveforms:
        Waveform data from the ngspice bridge — either the list-of-dicts
        format from ``routes_spice.parse_raw_file`` or the dict format from
        ``parse_ngspice_output``.
    nodes:
        List of SPICE node expressions to probe.  Voltage nodes should be
        expressed as ``"V(nodename)"`` or just ``"nodename"``.  Current
        branches as ``"I(Vname)"`` or ``"I(R1)"``.
    at_time:
        If given (in seconds), return the sample value nearest to *at_time*.
        Otherwise return the DC mean across all samples.

    Returns
    -------
    ProbeResult
    """
    result = ProbeResult()
    wave_map = _build_wave_map(waveforms)

    # Build a time axis from the list form (if available)
    t: list[float] | None = None
    if isinstance(waveforms, list):
        for w in waveforms:
            if isinstance(w, dict) and w.get("x"):
                t = [float(v) for v in w["x"]]
                break
    elif isinstance(waveforms, dict):
        raw_t = waveforms.get("time") or waveforms.get("t")
        if raw_t:
            t = [float(v) for v in raw_t]

    for node in nodes:
        y_raw = _find_channel_samples(wave_map, node, waveforms)

        if y_raw is None:
            result.probes.append(NodeProbe(
                node=node,
                kind="V" if not node.upper().startswith("I(") else "I",
                value_v_or_a=math.nan,
                unit="?",
                dc_mean=math.nan,
                rms=math.nan,
                n_samples=0,
                not_found=True,
            ))
            result.warnings.append(f"node '{node}' not found in simulation output")
            continue

        y = [float(v) for v in y_raw]
        is_current = node.upper().startswith("I(") or "current" in node.lower()
        kind = "I" if is_current else "V"
        unit = "A" if is_current else "V"

        dc = measure_dc(y)
        rms = measure_rms(y)

        # Instantaneous value at at_time (nearest sample)
        if at_time is not None and t is not None and len(t) == len(y):
            idx = _nearest_index(t, at_time)
            inst_val = y[idx]
            at_t = t[idx]
        else:
            inst_val = dc
            at_t = None

        result.probes.append(NodeProbe(
            node=node,
            kind=kind,
            value_v_or_a=inst_val,
            unit=unit,
            dc_mean=dc,
            rms=rms,
            n_samples=len(y),
            at_time_s=at_t,
        ))

    return result


def _nearest_index(t: list[float], target: float) -> int:
    """Return the index of the element in *t* closest to *target*."""
    if not t:
        return 0
    best_i = 0
    best_d = abs(t[0] - target)
    for i, v in enumerate(t[1:], 1):
        d = abs(v - target)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def format_probe_overlay(probe: NodeProbe) -> dict[str, Any]:
    """Return a JSON-serialisable dict for schematic on-wire overlay display.

    The dict shape is what the React probe-overlay component expects:
    {
        "node":      str,
        "kind":      "V" | "I",
        "value":     float,
        "unit":      "V" | "A",
        "dc":        float,
        "rms":       float,
        "label":     str,       -- human-readable label for on-wire display
        "not_found": bool,
    }
    """
    if probe.not_found or math.isnan(probe.value_v_or_a):
        label = f"{probe.node}: ??"
    else:
        label = _fmt_value(probe.value_v_or_a, probe.unit)

    return {
        "node": probe.node,
        "kind": probe.kind,
        "value": probe.value_v_or_a if not math.isnan(probe.value_v_or_a) else None,
        "unit": probe.unit,
        "dc": probe.dc_mean if not math.isnan(probe.dc_mean) else None,
        "rms": probe.rms if not math.isnan(probe.rms) else None,
        "label": label,
        "not_found": probe.not_found,
    }


def _fmt_value(v: float, unit: str) -> str:
    """Format a scalar with SI prefix for overlay display."""
    a = abs(v)
    if a == 0.0:
        return f"0 {unit}"
    if a >= 1.0:
        return f"{v:.4g} {unit}"
    if a >= 1e-3:
        return f"{v * 1e3:.4g} m{unit}"
    if a >= 1e-6:
        return f"{v * 1e6:.4g} µ{unit}"
    return f"{v * 1e9:.4g} n{unit}"
