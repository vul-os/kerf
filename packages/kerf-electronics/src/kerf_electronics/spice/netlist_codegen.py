"""netlist_codegen.py — Schematic graph → SPICE netlist generator.

Supports three SPICE dialects:
  'spectre'  — Cadence Spectre syntax
  'ngspice'  — Berkeley ngspice / LTspice .cir syntax
  'hspice'   — Synopsys HSPICE syntax

HONEST DISCLAIMER
-----------------
Generated netlists follow the public documentation for each simulator's
syntax.  They are not validated against any specific foundry PDK process
deck and require integration with device model files (.MODEL / .SUBCKT)
for meaningful simulation.  Cadence Spectre and HSPICE are commercial
tools; generated output follows publicly documented API conventions only.

References:
  Cadence Spectre Circuit Simulator Reference Manual (publicly cited API).
  Synopsys HSPICE Reference Manual (publicly cited API).
  ngspice User Manual (open source, https://ngspice.sourceforge.io/).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Schema dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SchematicNode:
    """A named node (net) in the schematic graph."""

    name: str
    voltage: Optional[str] = None   # 'gnd', 'VDD', or net name label


@dataclass
class SchematicDevice:
    """A two-terminal or multi-terminal device instance.

    kind values  — device-type letter:
      'NMOS'     — N-channel MOSFET (pins: drain, gate, source, body)
      'PMOS'     — P-channel MOSFET (pins: drain, gate, source, body)
      'NPN'      — NPN BJT (pins: collector, base, emitter)
      'PNP'      — PNP BJT
      'R'        — Resistor (pins: +, -)
      'C'        — Capacitor (pins: +, -)
      'L'        — Inductor (pins: +, -)
      'V'        — Voltage source (pins: +, -)
      'I'        — Current source (pins: +, -)
      'D'        — Diode (pins: anode, cathode)
    """

    device_id: str                  # e.g. 'M1', 'R1', 'C3'
    kind: str                       # see above
    pins: List[str]                 # ordered pin-to-node mapping
    parameters: Dict[str, object]   # device parameters {'W': 1e-6, 'L': 100e-9}
    model_name: Optional[str] = None  # optional .MODEL / .SUBCKT reference


@dataclass
class SchematicGraph:
    """Complete schematic graph."""

    nodes: List[SchematicNode]
    devices: List[SchematicDevice]
    title: str = "kerf_netlist"
    vdd_net: str = "VDD"
    gnd_net: str = "0"


# ---------------------------------------------------------------------------
# Engineering value formatter
# ---------------------------------------------------------------------------

def _fmt_eng(value: object, dialect: str) -> str:
    """Format a numeric parameter value in SPICE engineering notation.

    Spectre uses SI prefixes (p, n, u, m, k, M, G).
    ngspice / HSPICE use traditional SPICE suffixes (P, N, U, M, K, MEG, G).
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)

    if v == 0.0:
        return "0"

    abs_v = abs(v)
    sign  = "-" if v < 0 else ""

    if dialect == "spectre":
        prefixes = [
            (1e12,  "T"),
            (1e9,   "G"),
            (1e6,   "M"),
            (1e3,   "K"),
            (1e0,   ""),
            (1e-3,  "m"),
            (1e-6,  "u"),
            (1e-9,  "n"),
            (1e-12, "p"),
            (1e-15, "f"),
        ]
    else:
        # ngspice / HSPICE SPICE suffixes
        prefixes = [
            (1e12,  "T"),
            (1e9,   "G"),
            (1e6,   "MEG"),
            (1e3,   "K"),
            (1e0,   ""),
            (1e-3,  "M"),     # SPICE 'm' = milli (not Mega!)
            (1e-6,  "U"),
            (1e-9,  "N"),
            (1e-12, "P"),
            (1e-15, "F"),
        ]

    for scale, suffix in prefixes:
        if abs_v >= scale * 0.9999:
            scaled = abs_v / scale
            # Avoid over-precision
            s = f"{scaled:.6g}"
            return f"{sign}{s}{suffix}"

    return f"{sign}{abs_v:.6g}"


# ---------------------------------------------------------------------------
# Parameter list formatter
# ---------------------------------------------------------------------------

def _fmt_params(params: Dict[str, object], dialect: str) -> str:
    """Format a parameter dict as a space-separated key=value string."""
    parts = []
    for k, v in params.items():
        parts.append(f"{k}={_fmt_eng(v, dialect)}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Device line formatters per dialect
# ---------------------------------------------------------------------------

def _mosfet_line(dev: SchematicDevice, dialect: str) -> str:
    """Generate a MOSFET instance line.

    Spectre:  M1 (d g s b) nmos W=1u L=100n
    ngspice:  M1 d g s b NMOS W=1u L=100n
    hspice:   M1 D G S B NMOS W=1u L=100n
    """
    d_id = dev.device_id
    kind = dev.kind  # 'NMOS' or 'PMOS'
    model = dev.model_name or kind.lower()

    # Ensure 4 pins (D G S B); pad with '0' if body not specified
    pins = list(dev.pins)
    while len(pins) < 4:
        pins.append("0")

    d, g, s, b = pins[0], pins[1], pins[2], pins[3]
    p_str = _fmt_params(dev.parameters, dialect)

    if dialect == "spectre":
        # Spectre: instance_name (d g s b) model_name W=... L=...
        return f"{d_id} ({d} {g} {s} {b}) {model} {p_str}"
    elif dialect == "hspice":
        D, G, S, B = d.upper(), g.upper(), s.upper(), b.upper()
        return f"{d_id} {D} {G} {S} {B} {kind.upper()} {p_str}"
    else:
        # ngspice
        return f"{d_id} {d} {g} {s} {b} {kind.upper()} {p_str}"


def _bjt_line(dev: SchematicDevice, dialect: str) -> str:
    """Generate a BJT instance line.

    Spectre:  Q1 (c b e) npn
    ngspice:  Q1 c b e NPN
    hspice:   Q1 C B E NPN
    """
    d_id  = dev.device_id
    kind  = dev.kind  # 'NPN' or 'PNP'
    model = dev.model_name or kind.lower()

    pins  = list(dev.pins)
    while len(pins) < 3:
        pins.append("0")

    c, b, e = pins[0], pins[1], pins[2]
    p_str   = _fmt_params(dev.parameters, dialect)

    if dialect == "spectre":
        p_part = f" {p_str}" if p_str else ""
        return f"{d_id} ({c} {b} {e}) {model}{p_part}"
    elif dialect == "hspice":
        return f"{d_id} {c.upper()} {b.upper()} {e.upper()} {kind.upper()}{' ' + p_str if p_str else ''}"
    else:
        return f"{d_id} {c} {b} {e} {kind.upper()}{' ' + p_str if p_str else ''}"


def _two_terminal_line(dev: SchematicDevice, dialect: str) -> str:
    """Generate a two-terminal passive / source instance line.

    Maps R/C/L/V/I/D to each dialect's syntax.

    Spectre:  R1 (a b) resistor r=1K
              C1 (a b) capacitor c=10p
              V1 (+ -) vsource dc=1.0
    ngspice:  R1 a b 1K
              C1 a b 10P
              V1 + - DC 1.0
    hspice:   R1 A B 1K
              C1 A B 10P
              V1 + - DC 1.0
    """
    d_id  = dev.device_id
    kind  = dev.kind
    pins  = list(dev.pins)
    while len(pins) < 2:
        pins.append("0")

    n1, n2 = pins[0], pins[1]

    # Primary value key lookup
    _kind_to_spectre_device = {
        "R": "resistor",
        "C": "capacitor",
        "L": "inductor",
        "V": "vsource",
        "I": "isource",
        "D": "diode",
    }
    _kind_to_value_key = {
        "R": "r",
        "C": "c",
        "L": "l",
        "V": "dc",
        "I": "dc",
        "D": None,
    }

    if dialect == "spectre":
        dev_kw = _kind_to_spectre_device.get(kind, kind.lower())
        val_key = _kind_to_value_key.get(kind)
        params = dict(dev.parameters)
        if val_key and val_key not in params:
            # Try to pull the primary value from 'value' key
            if "value" in params:
                params[val_key] = params.pop("value")
        p_str = _fmt_params(params, dialect)
        model_part = f" {dev.model_name}" if dev.model_name and kind == "D" else ""
        return f"{d_id} ({n1} {n2}){model_part} {dev_kw} {p_str}"

    else:
        # ngspice / HSPICE: <letter><id> <n1> <n2> [model] <value>
        params = dict(dev.parameters)
        value  = params.pop("value", params.pop("r", params.pop("c", params.pop("l",
                 params.pop("dc", None)))))

        if dialect == "hspice":
            n1 = n1.upper()
            n2 = n2.upper()

        if kind in ("V", "I"):
            v_str = _fmt_eng(value, dialect) if value is not None else "0"
            extra  = _fmt_params(params, dialect)
            src_type = "DC"
            line = f"{d_id} {n1} {n2} {src_type} {v_str}"
            if extra:
                line += f" {extra}"
            return line
        elif kind == "D":
            model = dev.model_name or "DMODEL"
            p_str = _fmt_params(params, dialect)
            base  = f"{d_id} {n1} {n2} {model}"
            return f"{base} {p_str}" if p_str else base
        else:
            v_str = _fmt_eng(value, dialect) if value is not None else "0"
            extra = _fmt_params(params, dialect)
            base  = f"{d_id} {n1} {n2} {v_str}"
            return f"{base} {extra}" if extra else base


def _device_line(dev: SchematicDevice, dialect: str) -> str:
    """Dispatch to the appropriate line formatter."""
    if dev.kind in ("NMOS", "PMOS"):
        return _mosfet_line(dev, dialect)
    elif dev.kind in ("NPN", "PNP"):
        return _bjt_line(dev, dialect)
    else:
        return _two_terminal_line(dev, dialect)


# ---------------------------------------------------------------------------
# Netlist header / footer per dialect
# ---------------------------------------------------------------------------

def _header(graph: SchematicGraph, dialect: str) -> List[str]:
    if dialect == "spectre":
        return [
            f"// {graph.title}",
            "// Generated by kerf_electronics.spice.netlist_codegen",
            "// HONEST NOTE: not foundry-PDK accurate; for design exploration only.",
            "simulator lang=spectre",
            "",
        ]
    elif dialect == "hspice":
        return [
            f"* {graph.title}",
            "* Generated by kerf_electronics.spice.netlist_codegen",
            "* HONEST NOTE: not foundry-PDK accurate; for design exploration only.",
            "",
        ]
    else:
        # ngspice
        return [
            f"* {graph.title}",
            "* Generated by kerf_electronics.spice.netlist_codegen",
            "* HONEST NOTE: not foundry-PDK accurate; for design exploration only.",
            "",
        ]


def _footer(graph: SchematicGraph, dialect: str) -> List[str]:
    if dialect == "spectre":
        return ["", "// end of netlist"]
    elif dialect == "hspice":
        return ["", ".END"]
    else:
        return ["", ".end"]


# ---------------------------------------------------------------------------
# Public API: generate_netlist
# ---------------------------------------------------------------------------

def generate_netlist(graph: SchematicGraph, dialect: str = "spectre") -> str:
    """Generate a SPICE netlist from a SchematicGraph.

    Args:
      graph:   Schematic graph with nodes and device instances.
      dialect: One of 'spectre', 'ngspice', 'hspice'.

    Returns:
      Netlist as a multi-line string.

    HONEST NOTE: Not foundry-PDK accurate; requires device .MODEL files for
    simulation.  Follows publicly documented syntax conventions only.

    References:
      Cadence Spectre Circuit Simulator Reference Manual.
      Synopsys HSPICE Reference Manual.
      ngspice User Manual, https://ngspice.sourceforge.io/
    """
    if dialect not in ("spectre", "ngspice", "hspice"):
        raise ValueError(f"Unknown dialect '{dialect}'; choose spectre / ngspice / hspice")

    lines: List[str] = []
    lines.extend(_header(graph, dialect))

    # Supply / power net comments
    if dialect == "spectre":
        lines.append(f"// Supply nets: VDD={graph.vdd_net!r}  GND={graph.gnd_net!r}")
    else:
        lines.append(f"* Supply nets: VDD={graph.vdd_net!r}  GND={graph.gnd_net!r}")
    lines.append("")

    for dev in graph.devices:
        lines.append(_device_line(dev, dialect))

    lines.extend(_footer(graph, dialect))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API: parse_netlist  (round-trip oracle)
# ---------------------------------------------------------------------------

# Regex patterns for each dialect
_RE_MOSFET_SPECTRE = re.compile(
    r'^(\S+)\s+\((\S+)\s+(\S+)\s+(\S+)\s+(\S+)\)\s+(\S+)\s*(.*)',
    re.IGNORECASE,
)
_RE_MOSFET_SPICE = re.compile(
    r'^(M\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*(.*)',
    re.IGNORECASE,
)
_RE_PASSIVE_SPECTRE = re.compile(
    r'^(\S+)\s+\((\S+)\s+(\S+)\)\s+\S+\s*(.*)',
    re.IGNORECASE,
)
_RE_PASSIVE_SPICE = re.compile(
    r'^([RCLVID]\S*)\s+(\S+)\s+(\S+)\s+(.*)',
    re.IGNORECASE,
)


def _parse_params_str(s: str) -> Dict[str, object]:
    """Parse 'key=value key=value ...' into a dict.

    Handles SI/SPICE suffix values (e.g. W=2u, L=100n, r=1K).
    Stores numeric values as float; unrecognised strings as-is.
    Key case is preserved for round-trip fidelity.
    """
    result: Dict[str, object] = {}
    for token in s.strip().split():
        if "=" in token:
            k, v = token.split("=", 1)
            # Try plain float first, then suffix conversion
            try:
                result[k] = float(v)
            except ValueError:
                parsed = _suffix_to_float(v)
                if parsed != 0.0 or v in ("0", "0.0"):
                    result[k] = parsed
                else:
                    result[k] = v  # keep as string (e.g. model name)
    return result


def _suffix_to_float(s: str) -> float:
    """Convert a SPICE/Spectre suffixed value string to float."""
    s = s.strip()
    spice_map = {
        "T": 1e12, "G": 1e9, "MEG": 1e6, "K": 1e3,
        "M": 1e-3, "U": 1e-6, "N": 1e-9, "P": 1e-12, "F": 1e-15,
        # Spectre SI
        "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15,
    }
    for suffix in sorted(spice_map.keys(), key=len, reverse=True):
        if s.upper().endswith(suffix.upper()) and len(s) > len(suffix):
            try:
                return float(s[: -len(suffix)]) * spice_map[suffix]
            except ValueError:
                pass
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_netlist(text: str, dialect: str = "spectre") -> SchematicGraph:
    """Parse a SPICE netlist string into a SchematicGraph.

    Acts as the inverse of generate_netlist for round-trip fidelity oracle.
    Supports the three dialects: 'spectre', 'ngspice', 'hspice'.

    HONEST NOTE: Parser handles the subset of syntax produced by
    generate_netlist; not a general-purpose SPICE parser.

    References:
      Cadence Spectre Circuit Simulator Reference Manual.
      Synopsys HSPICE Reference Manual.
      ngspice User Manual.
    """
    if dialect not in ("spectre", "ngspice", "hspice"):
        raise ValueError(f"Unknown dialect '{dialect}'")

    devices: List[SchematicDevice] = []
    nodes_seen: Dict[str, SchematicNode] = {}
    title = "kerf_netlist"

    def _register_node(name: str) -> None:
        if name not in nodes_seen:
            nodes_seen[name] = SchematicNode(name=name)

    lines = text.splitlines()
    first_comment_seen = False

    for raw in lines:
        line = raw.strip()

        # Skip blanks, comments, directives, metadata
        if not line:
            continue
        if dialect == "spectre":
            if line.startswith("//"):
                # Extract title from first comment line: "// <title>"
                if not first_comment_seen:
                    first_comment_seen = True
                    candidate = line[2:].strip()
                    if candidate and "Generated by" not in candidate and "HONEST" not in candidate:
                        title = candidate
                continue
            if line.startswith("simulator"):
                continue
        else:
            if line.startswith("*"):
                # Extract title from first * comment line
                if not first_comment_seen:
                    first_comment_seen = True
                    candidate = line[1:].strip()
                    if candidate and "Generated by" not in candidate and "HONEST" not in candidate:
                        title = candidate
                continue
            if line.startswith(".") or line.startswith("$"):
                continue

        # ── MOSFET (starts with M) ────────────────────────────────────────
        upper = line.upper()
        first = line.split()[0].upper()

        if first.startswith("M") and len(first) >= 2:
            if dialect == "spectre":
                m = _RE_MOSFET_SPECTRE.match(line)
                if m:
                    dev_id, d, g, s, b, model, rest = m.groups()
                    kind = "NMOS" if "nmos" in model.lower() else "PMOS"
                    pins = [d, g, s, b]
                    params = _parse_params_str(rest)
                    for pin in pins:
                        _register_node(pin)
                    devices.append(SchematicDevice(
                        device_id  = dev_id,
                        kind       = kind,
                        pins       = pins,
                        parameters = params,
                        model_name = model,
                    ))
            else:
                m = _RE_MOSFET_SPICE.match(line)
                if m:
                    dev_id, d, g, s, b, model, rest = m.groups()
                    kind = "NMOS" if "NMOS" in model.upper() else "PMOS"
                    # Preserve pin case as found in the netlist (ngspice keeps
                    # original case; hspice uppercases — both are round-trip safe)
                    pins = [d, g, s, b]
                    params = _parse_params_str(rest)
                    for pin in pins:
                        _register_node(pin)
                    devices.append(SchematicDevice(
                        device_id  = dev_id,
                        kind       = kind,
                        pins       = pins,
                        parameters = params,
                        model_name = model,
                    ))
            continue

        # ── BJT (starts with Q) ───────────────────────────────────────────
        if first.startswith("Q"):
            parts = line.split()
            if len(parts) >= 5:
                dev_id = parts[0]
                c, b_n, e, model = parts[1], parts[2], parts[3], parts[4]
                kind = "NPN" if "NPN" in model.upper() else "PNP"
                pins = [c, b_n, e]
                for pin in pins:
                    _register_node(pin)
                devices.append(SchematicDevice(
                    device_id  = dev_id,
                    kind       = kind,
                    pins       = pins,
                    parameters = {},
                    model_name = model,
                ))
            continue

        # ── Two-terminal passives / sources (R/C/L/V/I/D) ────────────────
        letter = first[0] if first else ""
        if letter in ("R", "C", "L", "V", "I", "D"):
            parts = line.split()
            if len(parts) < 3:
                continue

            if dialect == "spectre":
                m = _RE_PASSIVE_SPECTRE.match(line)
                if m:
                    dev_id, n1, n2, rest = m.groups()
                    # Determine kind from device_id prefix
                    kind_map = {"R": "R", "C": "C", "L": "L", "V": "V", "I": "I", "D": "D"}
                    k = dev_id[0].upper() if dev_id else "R"
                    kind_det = kind_map.get(k, k)
                    params = _parse_params_str(rest)
                    _register_node(n1)
                    _register_node(n2)
                    devices.append(SchematicDevice(
                        device_id  = dev_id,
                        kind       = kind_det,
                        pins       = [n1, n2],
                        parameters = params,
                    ))
            else:
                # ngspice / hspice — preserve pin case for round-trip fidelity
                dev_id = parts[0]
                n1     = parts[1]
                n2     = parts[2]
                _register_node(n1)
                _register_node(n2)

                kind_map = {"R": "R", "C": "C", "L": "L", "V": "V", "I": "I", "D": "D"}
                k = dev_id[0].upper()
                kind_det = kind_map.get(k, k)

                params: Dict[str, object] = {}
                rest_parts = parts[3:]

                # Try to detect key=val tokens vs bare value
                # Preserve key case for round-trip fidelity
                if rest_parts:
                    for token in rest_parts:
                        if "=" in token:
                            kk, vv = token.split("=", 1)
                            try:
                                params[kk] = _suffix_to_float(vv)
                            except Exception:
                                params[kk] = vv
                        elif token.upper() in ("DC", "AC", "PULSE", "SIN"):
                            pass  # source type keyword
                        else:
                            # Bare value — store as 'value'
                            try:
                                params["value"] = _suffix_to_float(token)
                            except Exception:
                                pass

                devices.append(SchematicDevice(
                    device_id  = dev_id,
                    kind       = kind_det,
                    pins       = [n1, n2],
                    parameters = params,
                ))
            continue

    return SchematicGraph(
        nodes   = list(nodes_seen.values()),
        devices = devices,
        title   = title,
    )
