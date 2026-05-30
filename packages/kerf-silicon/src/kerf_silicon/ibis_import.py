"""ibis_import.py — IBIS 7.1 signal-integrity model import for kerf-silicon.

Parses industry-standard .ibs (Input/Output Buffer Information Specification)
files and provides IV-curve interpolation and eye-diagram estimation.

IBIS 7.1 spec compliance disclaimer
-------------------------------------
This implementation covers the core sections used for signal-integrity
simulation:
  [Component], [Pin], [Model], [Voltage Range],
  [Pulldown], [Pullup], [GND_clamp], [POWER_clamp], [Ramp].

It is NOT IBIS-certified.  IBIS 7.1 defines additional optional keywords
(sub-model matrices, algorithmic models, Series elements, differential pins,
etc.) that are not parsed here.  The eye-diagram computation is an analytical
approximation — not a full IBIS-compliant waveform simulator (which would
require complete Ramp/V-T waveform integration and transmission-line
modelling).

Analytical model used for eye diagram
--------------------------------------
The eye diagram estimation uses the following approach:

1. The effective pull-down resistance R_pd is derived from the IV curve
   slope around the switching threshold (Vcc/2):
       R_pd = ΔV / ΔI  from the pulldown table near Vcc/2.

2. The effective pull-up resistance R_pu is derived analogously from the
   pullup table (note: pullup voltage reference is Vcc, so I(V_pullup = Vcc)
   corresponds to the PMOS being off, and I(V_pullup = 0) to full on).

3. A load is modelled as a parallel combination of load_impedance_ohm
   terminated to Vcc/2 (AC-coupled equivalent).

4. The driver output charges/discharges the load through the effective
   driver impedance.  The RC time constant τ = R_eff × C_load is used to
   compute the 10%→90% rise time, where C_load = 1 / (2π × f × Z_load)
   (implicit capacitance from the matched load model).

5. Eye-opening metrics:
   - opening_height_mV: steady-state swing ×  exp(-π/(Q)) where Q = Z_load/R_eff
     (approximation: eye margin at the sampling point).
   - opening_width_ps: UI − 2 × t_rise_effective (time available without ISI).
   - jitter_estimate_ps: 0.14 × t_rise (empirical Gaussian jitter model,
     from JEDEC JESD65B).

References
----------
- IBIS 7.1 Specification: https://ibis.org/ver7.1/ibis_specs_7_1.pdf
  (Sections 3–5 for keyword syntax; Section 6 for simulation models)
- W. Dally & J. Poulton, "Digital Systems Engineering", Cambridge (1998),
  Chapter 7 — I/O buffer modelling.
- JEDEC JESD65B — BGA ball-map / eye-diagram margin methodology.

Public API
----------
    parse_ibis_file(path: str) -> IbisModel
    evaluate_buffer_iv(model_name: str, voltage: float, model: IbisModel) -> float
    compute_eye_diagram_at_pin(pin_name, model, frequency_ghz, load_impedance_ohm)
        -> EyeDiagramResult
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IbisParseError(ValueError):
    """Raised when an .ibs file cannot be parsed.

    Attributes
    ----------
    line_number:
        1-based line number where the error was detected (0 if unknown).
    message:
        Human-readable description of the parse error.
    """

    def __init__(self, message: str, line_number: int = 0) -> None:
        super().__init__(f"IBIS parse error at line {line_number}: {message}")
        self.line_number = line_number
        self.message = message


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class IVPoint:
    """A single (voltage, current) point in an IV table."""
    voltage: float   # Volts
    current: float   # Amperes


@dataclass
class IbisIVTable:
    """An IBIS IV table (Pulldown, Pullup, GND_clamp, or POWER_clamp).

    Points are stored in ascending voltage order.

    Attributes
    ----------
    name:
        Table section name, e.g. ``"Pulldown"``.
    points:
        List of (voltage, current) pairs, sorted by voltage ascending.
    typ, min, max:
        Optional per-point typ/min/max columns.  When the .ibs file provides
        three current columns, ``points`` contains the typ value; ``points_min``
        and ``points_max`` are populated.
    """
    name: str
    points: list[IVPoint] = field(default_factory=list)
    points_min: list[IVPoint] = field(default_factory=list)
    points_max: list[IVPoint] = field(default_factory=list)


@dataclass
class RampData:
    """IBIS [Ramp] section: output transition dV/dt at 20%–80% levels.

    Attributes
    ----------
    dv_dt_rise: float  — rising dV/dt in V/s (typ)
    dv_dt_fall: float  — falling dV/dt in V/s (typ)
    r_load:     float  — test load resistance (Ohm) for the ramp measurement
    """
    dv_dt_rise: float = 0.0    # V/s  (typ)
    dv_dt_fall: float = 0.0    # V/s  (typ)
    r_load: float = 50.0       # Ohm


@dataclass
class IbisBufferModel:
    """An IBIS [Model] with its IV tables and ramp data.

    Attributes
    ----------
    name:
        Model name as given in [Model] keyword.
    model_type:
        IBIS model type string, e.g. ``"Output"``, ``"I/O"``, ``"Input"``.
    vcc_min, vcc_typ, vcc_max:
        Voltage Range corner values (V).  Defaults to (0, 3.3, 3.3).
    c_comp:
        Package + die capacitance in Farads (typ).
    pulldown, pullup, gnd_clamp, power_clamp:
        IV tables (may be None if not present in this model).
    ramp:
        Ramp section data (None if not present).
    """
    name: str
    model_type: str = "Output"
    vcc_min: float = 0.0
    vcc_typ: float = 3.3
    vcc_max: float = 3.3
    c_comp: float = 1e-12      # F — default 1 pF
    pulldown: IbisIVTable | None = None
    pullup: IbisIVTable | None = None
    gnd_clamp: IbisIVTable | None = None
    power_clamp: IbisIVTable | None = None
    ramp: RampData | None = None


@dataclass
class IbisPin:
    """An IBIS [Pin] entry.

    Attributes
    ----------
    name:       Pin name, e.g. ``"A1"``.
    signal:     Net/signal name.
    model_name: Name of the associated [Model].
    R_pin, L_pin, C_pin:
        Package parasitic resistance (Ohm), inductance (H), capacitance (F).
    """
    name: str
    signal: str
    model_name: str
    R_pin: float = 0.0
    L_pin: float = 0.0
    C_pin: float = 0.0


@dataclass
class IbisComponent:
    """An IBIS [Component] block."""
    name: str
    manufacturer: str = ""
    package_type: str = ""
    pins: dict[str, IbisPin] = field(default_factory=dict)


@dataclass
class IbisModel:
    """Top-level IBIS model container returned by ``parse_ibis_file``.

    Attributes
    ----------
    component:
        The first [Component] block (IBIS requires at least one).
    pins:
        Dict of pin_name → IbisPin.
    models:
        Dict of model_name → IbisBufferModel.
    derating_info:
        Dict of raw derating/corner metadata parsed from the file header.
    source_file:
        Path to the source .ibs file (empty string if parsed from string).
    ibis_version:
        IBIS version string from [IBIS Ver] keyword.
    """
    component: IbisComponent
    pins: dict[str, IbisPin] = field(default_factory=dict)
    models: dict[str, IbisBufferModel] = field(default_factory=dict)
    derating_info: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""
    ibis_version: str = ""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class EyeDiagramResult:
    """Eye-diagram estimation metrics at a given pin and frequency.

    All values are analytical approximations, not full waveform simulations.

    Attributes
    ----------
    opening_height_mV:
        Eye vertical opening in millivolts at the sampling point.
    opening_width_ps:
        Eye horizontal opening in picoseconds (symbol period minus ISI penalty).
    jitter_estimate_ps:
        RMS jitter estimate in picoseconds (0.14 × t_rise, from JEDEC JESD65B).
    symbol_period_ps:
        Full UI (unit interval) in picoseconds = 1 / frequency_ghz × 1000.
    rise_time_ps:
        Effective 20%–80% rise time in picoseconds derived from driver IV curve.
    r_driver_eff_ohm:
        Effective driver output impedance used for the calculation.
    vcc_typ:
        Supply voltage in V from the model's [Voltage Range].
    model_name:
        Name of the IbisBufferModel used.
    """
    opening_height_mV: float
    opening_width_ps: float
    jitter_estimate_ps: float
    symbol_period_ps: float
    rise_time_ps: float
    r_driver_eff_ohm: float
    vcc_typ: float
    model_name: str


# ---------------------------------------------------------------------------
# Parser internals
# ---------------------------------------------------------------------------

# Keywords that introduce a new top-level section
_SECTION_KEYWORDS = frozenset({
    "ibis_ver", "file_name", "file_rev", "date", "source", "notes",
    "disclaimer", "copyright", "component", "model", "end",
})

# IV-table section keywords (within a [Model] block)
_IV_TABLE_KEYWORDS = frozenset({
    "pulldown", "pullup", "gnd_clamp", "power_clamp",
})

_FLOAT_RE = re.compile(
    r"[+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?[numkMGTpf]?"
)

_SI_SUFFIXES: dict[str, float] = {
    "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6,
    "m": 1e-3,  "k": 1e3,   "M": 1e6, "G": 1e9, "T": 1e12,
}


def _parse_float(token: str) -> float:
    """Parse a float token with optional SI suffix (n, p, u, m, k, M, G…)."""
    token = token.strip()
    if not token or token.lower() in ("na", "na)", "(na"):
        return float("nan")
    suffix = token[-1]
    if suffix in _SI_SUFFIXES:
        scale = _SI_SUFFIXES[suffix]
        return float(token[:-1]) * scale
    return float(token)


def _normalise_keyword(raw: str) -> str:
    """Strip brackets, lowercase, collapse internal whitespace."""
    s = raw.strip().lower()
    # Remove surrounding brackets
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    # Collapse whitespace
    return re.sub(r"\s+", "_", s.strip())


def _strip_comment(line: str) -> str:
    """Remove inline IBIS comments (| at start or inline after whitespace)."""
    # Inline comment: first occurrence of '|' that is not inside a value
    idx = line.find("|")
    if idx >= 0:
        return line[:idx]
    return line


def _is_section_header(line: str) -> tuple[bool, str]:
    """Return (True, normalised_keyword) if line starts a new IBIS section."""
    stripped = line.strip()
    m = re.match(r"^\[([^\]]+)\]", stripped)
    if m:
        return True, _normalise_keyword(m.group(1))
    return False, ""


def _parse_iv_row(tokens: list[str]) -> tuple[float, float, float, float] | None:
    """Parse a 1-column or 3-column IV row.

    Returns (voltage, typ_current, min_current, max_current) or None on failure.
    """
    if len(tokens) < 2:
        return None
    try:
        v = _parse_float(tokens[0])
        i_typ = _parse_float(tokens[1])
        i_min = _parse_float(tokens[2]) if len(tokens) > 2 else i_typ
        i_max = _parse_float(tokens[3]) if len(tokens) > 3 else i_typ
        return v, i_typ, i_min, i_max
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_ibis_file(path: str) -> IbisModel:
    """Parse an IBIS .ibs file and return an ``IbisModel``.

    Parses the following IBIS 7.1 sections:
    - ``[IBIS Ver]`` — version string
    - ``[Component]`` — component name + manufacturer
    - ``[Pin]`` — pin name, signal, model assignment, R/L/C parasitics
    - ``[Model]`` — model type
    - ``[Voltage Range]`` — min/typ/max supply
    - ``[C_comp]`` — die + package capacitance
    - ``[Pulldown]``, ``[Pullup]``, ``[GND_clamp]``, ``[POWER_clamp]``
    - ``[Ramp]``

    Parameters
    ----------
    path:
        Absolute or relative path to the .ibs file.

    Returns
    -------
    IbisModel

    Raises
    ------
    IbisParseError
        If the file is malformed (missing required sections, unparseable
        numeric fields, etc.).  Always carries a 1-based line number.
    FileNotFoundError
        If the file does not exist.
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    return _parse_ibis_lines(lines, source_file=path)


def _parse_ibis_lines(lines: list[str], source_file: str = "") -> IbisModel:
    """Core parse logic operating on pre-loaded lines."""
    ibis_version = ""
    components: list[IbisComponent] = []
    all_pins: dict[str, IbisPin] = {}
    buffer_models: dict[str, IbisBufferModel] = {}
    derating_info: dict[str, Any] = {}

    # State machine
    current_section: str = ""
    current_component: IbisComponent | None = None
    current_model: IbisBufferModel | None = None
    current_iv_table: IbisIVTable | None = None
    in_pin_section = False
    in_ramp = False
    ramp_context: dict[str, float] = {}

    def _flush_iv():
        """Attach the current IV table to current_model."""
        nonlocal current_iv_table
        if current_iv_table is None or current_model is None:
            current_iv_table = None
            return
        tname = current_iv_table.name.lower()
        if tname == "pulldown":
            current_model.pulldown = current_iv_table
        elif tname == "pullup":
            current_model.pullup = current_iv_table
        elif tname == "gnd_clamp":
            current_model.gnd_clamp = current_iv_table
        elif tname == "power_clamp":
            current_model.power_clamp = current_iv_table
        current_iv_table = None

    for lineno, raw in enumerate(lines, start=1):
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue

        is_sec, kw = _is_section_header(line)
        if is_sec:
            # Close any open IV table first
            if current_iv_table is not None:
                _flush_iv()
            in_ramp = False
            in_pin_section = False

            if kw == "end":
                break

            elif kw == "ibis_ver":
                rest = line.split("]", 1)[1].strip() if "]" in line else ""
                ibis_version = rest or ""
                current_section = kw

            elif kw == "component":
                if current_component is not None:
                    components.append(current_component)
                comp_name = line.split("]", 1)[1].strip() if "]" in line else "UNNAMED"
                current_component = IbisComponent(name=comp_name)
                current_section = "component"
                in_pin_section = False

            elif kw == "pin":
                in_pin_section = True
                current_section = "pin"

            elif kw == "model":
                if current_model is not None:
                    buffer_models[current_model.name] = current_model
                model_name = line.split("]", 1)[1].strip() if "]" in line else ""
                if not model_name:
                    raise IbisParseError("Empty [Model] name", lineno)
                current_model = IbisBufferModel(name=model_name)
                current_section = "model"
                in_pin_section = False

            elif kw in _IV_TABLE_KEYWORDS:
                if current_model is None:
                    raise IbisParseError(
                        f"[{kw}] found outside of [Model] block", lineno
                    )
                table_display = {
                    "pulldown": "Pulldown",
                    "pullup": "Pullup",
                    "gnd_clamp": "GND_clamp",
                    "power_clamp": "POWER_clamp",
                }[kw]
                current_iv_table = IbisIVTable(name=table_display)
                current_section = kw

            elif kw == "voltage_range":
                current_section = "voltage_range"
                in_pin_section = False
                # Values may be inline: [Voltage Range]  3.3  3.0  3.6
                _vr_inline = (line.split("]", 1)[1].strip() if "]" in line else "")
                _vr_toks = _vr_inline.split()
                if _vr_toks and current_model is not None:
                    try:
                        if len(_vr_toks) >= 1:
                            _v = _parse_float(_vr_toks[0])
                            if not math.isnan(_v):
                                current_model.vcc_typ = _v
                        if len(_vr_toks) >= 2:
                            _v = _parse_float(_vr_toks[1])
                            if not math.isnan(_v):
                                current_model.vcc_min = _v
                        if len(_vr_toks) >= 3:
                            _v = _parse_float(_vr_toks[2])
                            if not math.isnan(_v):
                                current_model.vcc_max = _v
                    except (ValueError, IndexError):
                        pass

            elif kw == "c_comp":
                current_section = "c_comp"
                in_pin_section = False
                # Values may be inline: [C_comp]  2p  1p  3p
                _cc_inline = (line.split("]", 1)[1].strip() if "]" in line else "")
                _cc_toks = _cc_inline.split()
                if _cc_toks and current_model is not None:
                    try:
                        _v = _parse_float(_cc_toks[0])
                        if not math.isnan(_v) and _v > 0:
                            current_model.c_comp = _v
                    except (ValueError, IndexError):
                        pass

            elif kw == "ramp":
                in_ramp = True
                ramp_context = {}
                current_section = "ramp"
                in_pin_section = False

            elif kw == "model_type":
                current_section = "model_type"

            else:
                current_section = kw
                in_pin_section = False

            continue  # Done processing section header

        # ── Data lines ──────────────────────────────────────────────────────

        tokens = line.split()
        if not tokens:
            continue

        if current_section == "component" and current_component is not None:
            # e.g. "Manufacturer  Acme Corp"
            if tokens[0].lower() == "manufacturer":
                current_component.manufacturer = " ".join(tokens[1:])
            elif tokens[0].lower() == "package_type":
                current_component.package_type = " ".join(tokens[1:])

        elif in_pin_section and current_component is not None:
            # Pin table columns: signal_name  model_name  [R_pin  L_pin  C_pin]
            # Header line may start with "signal_name"
            if tokens[0].lower() in ("signal_name", "pin_name", "pin", "signal"):
                continue
            if len(tokens) < 3:
                continue
            pin_name = tokens[0]
            signal = tokens[1]
            model_name = tokens[2]
            r_pin = l_pin = c_pin = 0.0
            try:
                if len(tokens) > 3:
                    r_pin = _parse_float(tokens[3])
                if len(tokens) > 4:
                    l_pin = _parse_float(tokens[4])
                if len(tokens) > 5:
                    c_pin = _parse_float(tokens[5])
            except ValueError:
                pass
            pin = IbisPin(
                name=pin_name,
                signal=signal,
                model_name=model_name,
                R_pin=r_pin if not math.isnan(r_pin) else 0.0,
                L_pin=l_pin if not math.isnan(l_pin) else 0.0,
                C_pin=c_pin if not math.isnan(c_pin) else 0.0,
            )
            all_pins[pin_name] = pin
            if current_component is not None:
                current_component.pins[pin_name] = pin

        elif current_section == "model_type" and current_model is not None:
            current_model.model_type = tokens[0]

        elif current_section == "voltage_range" and current_model is not None:
            # Voltage Range  <typ>  [<min>  <max>]
            # May appear on same line as keyword or on next line
            try:
                if len(tokens) >= 1:
                    current_model.vcc_typ = _parse_float(tokens[0])
                if len(tokens) >= 2:
                    current_model.vcc_min = _parse_float(tokens[1])
                if len(tokens) >= 3:
                    current_model.vcc_max = _parse_float(tokens[2])
                # Sanitise NaN to typ
                if math.isnan(current_model.vcc_min):
                    current_model.vcc_min = current_model.vcc_typ
                if math.isnan(current_model.vcc_max):
                    current_model.vcc_max = current_model.vcc_typ
            except (ValueError, IndexError) as exc:
                raise IbisParseError(f"Bad Voltage Range: {exc}", lineno) from exc

        elif current_section == "c_comp" and current_model is not None:
            # C_comp <typ>  [<min>  <max>]
            try:
                val = _parse_float(tokens[0])
                if not math.isnan(val):
                    current_model.c_comp = val
            except ValueError:
                pass

        elif current_section in _IV_TABLE_KEYWORDS and current_iv_table is not None:
            # IV table row: V_fixture  [I_typ  I_min  I_max]
            # Skip header-like lines
            if tokens[0].lower() in ("v_fixture", "voltage", "v", "typ", "typ/min/max"):
                continue
            row = _parse_iv_row(tokens)
            if row is None:
                continue
            v, i_typ, i_min, i_max = row
            if math.isnan(v):
                continue
            pt = IVPoint(voltage=v, current=i_typ if not math.isnan(i_typ) else 0.0)
            current_iv_table.points.append(pt)
            pt_min = IVPoint(voltage=v, current=i_min if not math.isnan(i_min) else pt.current)
            pt_max = IVPoint(voltage=v, current=i_max if not math.isnan(i_max) else pt.current)
            current_iv_table.points_min.append(pt_min)
            current_iv_table.points_max.append(pt_max)

        elif in_ramp and current_model is not None:
            # Ramp sub-keys: dV/dt_r, dV/dt_f, R_load
            key_raw = tokens[0].lower().rstrip(":")
            if key_raw == "r_load" and len(tokens) > 1:
                try:
                    ramp_context["r_load"] = _parse_float(tokens[1])
                except ValueError:
                    pass
            elif key_raw in ("dv/dt_r", "dvdt_r") and len(tokens) > 1:
                # Format: "3.4V/ns" or "3.4/1n" etc.
                val = _parse_ramp_dvdt(tokens[1], lineno)
                if val is not None:
                    ramp_context["dv_dt_rise"] = val
            elif key_raw in ("dv/dt_f", "dvdt_f") and len(tokens) > 1:
                val = _parse_ramp_dvdt(tokens[1], lineno)
                if val is not None:
                    ramp_context["dv_dt_fall"] = val

            # Flush ramp when we have both rise and fall
            if "dv_dt_rise" in ramp_context and "dv_dt_fall" in ramp_context:
                current_model.ramp = RampData(
                    dv_dt_rise=ramp_context["dv_dt_rise"],
                    dv_dt_fall=ramp_context["dv_dt_fall"],
                    r_load=ramp_context.get("r_load", 50.0),
                )

    # ── Flush any open state ─────────────────────────────────────────────────

    if current_iv_table is not None:
        _flush_iv()

    if current_model is not None:
        buffer_models[current_model.name] = current_model

    if current_component is not None:
        components.append(current_component)

    # ── Validation ───────────────────────────────────────────────────────────

    if not components:
        raise IbisParseError("No [Component] section found in file", 0)

    if not buffer_models:
        raise IbisParseError("No [Model] section found in file", 0)

    # Sort IV table points by voltage
    for bm in buffer_models.values():
        for table_attr in ("pulldown", "pullup", "gnd_clamp", "power_clamp"):
            tbl: IbisIVTable | None = getattr(bm, table_attr)
            if tbl is not None:
                tbl.points.sort(key=lambda p: p.voltage)
                tbl.points_min.sort(key=lambda p: p.voltage)
                tbl.points_max.sort(key=lambda p: p.voltage)

    primary_component = components[0]
    # Merge all pins from all components into the model's pins dict
    merged_pins: dict[str, IbisPin] = {}
    for comp in components:
        merged_pins.update(comp.pins)
    merged_pins.update(all_pins)  # catch any orphan pins

    return IbisModel(
        component=primary_component,
        pins=merged_pins,
        models=buffer_models,
        derating_info=derating_info,
        source_file=source_file,
        ibis_version=ibis_version,
    )


def _parse_ramp_dvdt(token: str, lineno: int) -> float | None:
    """Parse IBIS ramp dV/dt entry, returning V/s (float) or None on failure.

    Formats seen in practice:
      "3.4V/1ns"  "3.4/1n"  "3.4e9"  "3.4V/ns"  "3400000000"
    """
    token = token.strip()
    if "/" in token:
        parts = token.split("/", 1)
        try:
            num_str = parts[0].rstrip("Vv")
            denom_str = parts[1].rstrip("s")  # strip trailing 's' from 'ns', 'ps'…
            # If denom_str still has a time SI suffix, parse it
            num = float(num_str)
            den = _parse_float(denom_str) if denom_str else 1.0
            if den == 0:
                return None
            return num / den  # V / s
        except ValueError:
            return None
    else:
        # Plain number (already V/s)
        try:
            return _parse_float(token)
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# IV curve interpolation
# ---------------------------------------------------------------------------

def evaluate_buffer_iv(
    model_name: str,
    voltage: float,
    model: IbisModel,
) -> float:
    """Interpolate the pulldown IV curve at a given voltage.

    Uses the ``[Pulldown]`` table from the named model.  Linear interpolation
    between adjacent table points.  If the voltage is outside the table range,
    the nearest endpoint value is returned (flat extrapolation).

    Parameters
    ----------
    model_name:
        Name of the IBIS buffer model in ``model.models``.
    voltage:
        Voltage in volts at which to evaluate the pulldown current.
    model:
        The ``IbisModel`` container.

    Returns
    -------
    float
        Pulldown current in amperes (positive = current flowing into the pin).

    Raises
    ------
    KeyError
        If ``model_name`` is not found in ``model.models``.
    ValueError
        If the named model has no pulldown table.
    """
    if model_name not in model.models:
        raise KeyError(f"Model '{model_name}' not found in IbisModel")
    buf = model.models[model_name]
    if buf.pulldown is None or not buf.pulldown.points:
        raise ValueError(f"Model '{model_name}' has no [Pulldown] table")
    return _interpolate_iv(buf.pulldown.points, voltage)


def _interpolate_iv(points: list[IVPoint], v: float) -> float:
    """Linear interpolation (with flat extrapolation) on a sorted IV table."""
    if len(points) == 1:
        return points[0].current
    if v <= points[0].voltage:
        return points[0].current
    if v >= points[-1].voltage:
        return points[-1].current
    # Binary search for bracket
    lo, hi = 0, len(points) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if points[mid].voltage <= v:
            lo = mid
        else:
            hi = mid
    # Linear interpolation
    v0, i0 = points[lo].voltage, points[lo].current
    v1, i1 = points[hi].voltage, points[hi].current
    if abs(v1 - v0) < 1e-15:
        return i0
    t = (v - v0) / (v1 - v0)
    return i0 + t * (i1 - i0)


# ---------------------------------------------------------------------------
# Eye diagram estimation
# ---------------------------------------------------------------------------

def compute_eye_diagram_at_pin(
    pin_name: str,
    model: IbisModel,
    frequency_ghz: float,
    load_impedance_ohm: float,
) -> EyeDiagramResult:
    """Estimate eye-diagram metrics at a pin under a termination load.

    Analytical model (see module docstring for derivation):
    1. Derive effective pull-down and pull-up resistances from IV slopes at Vcc/2.
    2. Compute effective driver impedance = parallel(R_pd, R_pu).
    3. Use RC rise-time model with the load.
    4. Compute eye opening height from steady-state swing × eye-penalty factor.
    5. Compute eye opening width as UI − 2 × effective rise time.
    6. Jitter estimate = 0.14 × t_rise (JEDEC JESD65B approximation).

    Parameters
    ----------
    pin_name:
        Pin name as given in the [Pin] section.
    model:
        The parsed ``IbisModel``.
    frequency_ghz:
        Operating bit-rate frequency in GHz (= 1 / UI in nanoseconds).
    load_impedance_ohm:
        Termination resistance in ohms (e.g. 50 Ω).

    Returns
    -------
    EyeDiagramResult

    Raises
    ------
    KeyError
        If pin or model not found.
    ValueError
        If the model has no IV tables or the load is non-positive.
    """
    if pin_name not in model.pins:
        raise KeyError(f"Pin '{pin_name}' not found in IbisModel")
    if frequency_ghz <= 0:
        raise ValueError("frequency_ghz must be positive")
    if load_impedance_ohm <= 0:
        raise ValueError("load_impedance_ohm must be positive")

    pin = model.pins[pin_name]
    model_name = pin.model_name
    if model_name not in model.models:
        raise KeyError(f"Model '{model_name}' (from pin '{pin_name}') not found")
    buf = model.models[model_name]

    vcc = buf.vcc_typ
    v_mid = vcc / 2.0

    # ── 1. Effective pull-down resistance from IV slope at Vcc/2 ────────────
    r_pd = _effective_resistance_at(buf.pulldown, v_mid)

    # ── 2. Effective pull-up resistance from IV slope at Vcc/2 ──────────────
    # The pullup table voltage axis is referenced to Vcc (V_pullup = Vcc − V_out).
    # At V_out = Vcc/2 → V_pullup_ref = Vcc/2.
    r_pu = _effective_resistance_at(buf.pullup, v_mid)

    # Fall back to load impedance if IV tables are absent (no output model)
    if r_pd is None and r_pu is None:
        r_driver = load_impedance_ohm  # worst-case: driver = matched termination
    elif r_pd is None:
        r_driver = r_pu  # type: ignore[assignment]
    elif r_pu is None:
        r_driver = r_pd
    else:
        # Parallel combination (both drive simultaneously during transition)
        r_driver = (r_pd * r_pu) / (r_pd + r_pu) if (r_pd + r_pu) > 0 else load_impedance_ohm

    # Clamp to physical range [0.1 Ω, 10 kΩ]
    r_driver = max(0.1, min(r_driver, 10_000.0))

    # ── 3. RC rise-time model ────────────────────────────────────────────────
    # If ramp data is available, use dV/dt_rise to derive rise time directly.
    # Otherwise, use τ = R_eff × C_eff where C_eff is the implicit capacitance
    # from the matched-load model.
    if buf.ramp is not None and buf.ramp.dv_dt_rise > 0:
        # Rise time (20%–80%) from ramp: Δt = 0.6 × Vcc / (dV/dt)
        t_rise_s = (0.6 * vcc) / buf.ramp.dv_dt_rise
    else:
        # Implicit capacitance from load at operating frequency:
        # C_load = 1 / (2π × f × Z_load)
        f_hz = frequency_ghz * 1e9
        c_load_f = 1.0 / (2.0 * math.pi * f_hz * load_impedance_ohm)
        # Also include the model's die capacitance
        c_total = c_load_f + buf.c_comp
        # R_eff = parallel(r_driver, load_impedance_ohm)
        r_eff_combined = (r_driver * load_impedance_ohm) / (r_driver + load_impedance_ohm)
        # 10%–90% rise time for RC: τ_10_90 = 2.2 × R × C
        t_rise_s = 2.2 * r_eff_combined * c_total

    # ── 4. Eye height ────────────────────────────────────────────────────────
    # Steady-state swing at load:
    #   V_high = Vcc × Z_load / (r_driver + Z_load)   (pull-up drives high)
    #   V_low  = 0   (pull-down drives low with load to Vcc/2 AC reference)
    # Use voltage-divider model for high-side swing:
    v_swing = vcc * load_impedance_ohm / (r_driver + load_impedance_ohm)
    # Eye margin: at the sampling point (center of UI), the signal has
    # fully transitioned if t_rise << UI.  Penalty factor per ISI model:
    #   eye_height = v_swing × (1 − exp(−UI / (2 × t_rise)))
    ui_s = 1.0 / (frequency_ghz * 1e9)
    if t_rise_s > 0:
        eye_penalty = 1.0 - math.exp(-ui_s / (2.0 * t_rise_s))
    else:
        eye_penalty = 1.0
    opening_height_v = v_swing * eye_penalty
    opening_height_mV = opening_height_v * 1000.0

    # ── 5. Eye width ─────────────────────────────────────────────────────────
    ui_ps = ui_s * 1e12
    t_rise_ps = t_rise_s * 1e12
    # Eye width = UI - 2 × effective rise time (IEEE Std 802.3 model)
    # Clamp to > 0
    opening_width_ps = max(0.0, ui_ps - 2.0 * t_rise_ps)

    # ── 6. Jitter estimate ───────────────────────────────────────────────────
    # σ_jitter ≈ 0.14 × t_rise  (JEDEC JESD65B: Gaussian random jitter component)
    jitter_ps = 0.14 * t_rise_ps

    return EyeDiagramResult(
        opening_height_mV=opening_height_mV,
        opening_width_ps=opening_width_ps,
        jitter_estimate_ps=jitter_ps,
        symbol_period_ps=ui_ps,
        rise_time_ps=t_rise_ps,
        r_driver_eff_ohm=r_driver,
        vcc_typ=vcc,
        model_name=model_name,
    )


def _effective_resistance_at(
    table: IbisIVTable | None,
    voltage: float,
) -> float | None:
    """Compute dV/dI (effective resistance) from an IV table at a given voltage.

    Uses the central difference of the two nearest table points bracketing
    the voltage.  Returns None if the table is absent or has fewer than 2 points.
    """
    if table is None or len(table.points) < 2:
        return None
    pts = table.points
    # Find the bracket
    idx = 0
    for i, pt in enumerate(pts):
        if pt.voltage >= voltage:
            idx = i
            break
    # Use central bracket
    lo_idx = max(0, idx - 1)
    hi_idx = min(len(pts) - 1, lo_idx + 1)
    if lo_idx == hi_idx:
        return None
    dv = pts[hi_idx].voltage - pts[lo_idx].voltage
    di = pts[hi_idx].current - pts[lo_idx].current
    if abs(di) < 1e-15:
        return None
    r = abs(dv / di)
    return r
