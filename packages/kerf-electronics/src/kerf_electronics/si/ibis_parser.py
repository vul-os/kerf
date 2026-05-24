"""
IBIS (I/O Buffer Information Specification) file parser.

Targets IBIS versions 3.x / 4.x / 5.x — the keyword/subkeyword grammar.
Parses the essential sections required for SI simulation:

  [Component]         component metadata, package R/L/C
  [Pin]               pin-to-signal-to-model mapping
  [Model]             model type, polarity, C_comp (typ/min/max)
  [Pulldown]          I-V table (Voltage, I_typ, I_min, I_max)
  [Pullup]            I-V table (same columns)
  [Ramp]              dV/dt rise / fall (typ/min/max)
  [Rising Waveform]   optional time-domain waveform table
  [Falling Waveform]  optional time-domain waveform table

Unknown keywords are tolerated and reported via warnings.
Malformed structure (missing required sections, bad numeric data) raises
IBISParseError.

IBIS spec reference: IBIS 5.1 (jedec.org/document/jesd8-18a / ibis.org spec).

Author: imranparuk
"""

from __future__ import annotations

import math
import re
import warnings
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ── Types ──────────────────────────────────────────────────────────────────────

# A single row in an IV or waveform table: (V_or_T, typ, min, max)
# Values may be None when the column is 'NA' in the IBIS file.
TableRow = Tuple[float, Optional[float], Optional[float], Optional[float]]


class IBISParseError(ValueError):
    """Raised when the IBIS file has an unrecoverable structural problem."""


@dataclass
class TypMinMax:
    """A three-corner numeric value (typ / min / max).  None = not specified."""
    typ: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None

    def __bool__(self) -> bool:
        return self.typ is not None


@dataclass
class IBISRamp:
    """dV/dt rise and fall corners from [Ramp]."""
    dv_dt_rise: TypMinMax = field(default_factory=TypMinMax)
    dv_dt_fall: TypMinMax = field(default_factory=TypMinMax)
    r_load: Optional[float] = None  # measurement load resistance, ohms


@dataclass
class IBISWaveform:
    """One [Rising Waveform] or [Falling Waveform] table."""
    direction: str = "rising"       # 'rising' | 'falling'
    r_fixture: Optional[float] = None
    v_fixture: Optional[float] = None
    v_fixture_min: Optional[float] = None
    v_fixture_max: Optional[float] = None
    table: List[TableRow] = field(default_factory=list)  # (time_s, V_typ, V_min, V_max)


@dataclass
class IBISModel:
    """Contents of one [Model] block."""
    name: str = ""
    model_type: str = ""           # Output, Input, I/O, 3-state, …
    polarity: str = ""             # Non-Inverting | Inverting
    c_comp: TypMinMax = field(default_factory=TypMinMax)
    pulldown: List[TableRow] = field(default_factory=list)   # (V, I_typ, I_min, I_max)
    pullup: List[TableRow] = field(default_factory=list)     # same
    ramp: Optional[IBISRamp] = None
    rising_waveforms: List[IBISWaveform] = field(default_factory=list)
    falling_waveforms: List[IBISWaveform] = field(default_factory=list)


@dataclass
class IBISPin:
    """One row in the [Pin] section."""
    pin_name: str = ""
    signal_name: str = ""
    model_name: str = ""
    r_pin: Optional[float] = None  # package pin resistance, ohms
    l_pin: Optional[float] = None  # package pin inductance, H
    c_pin: Optional[float] = None  # package pin capacitance, F


@dataclass
class IBISComponent:
    """Contents of one [Component] block."""
    name: str = ""
    manufacturer: str = ""
    package_r: TypMinMax = field(default_factory=TypMinMax)
    package_l: TypMinMax = field(default_factory=TypMinMax)
    package_c: TypMinMax = field(default_factory=TypMinMax)
    pins: List[IBISPin] = field(default_factory=list)


@dataclass
class IBISDeck:
    """Top-level parsed IBIS deck."""
    ibis_ver: str = ""
    file_name: str = ""
    file_rev: str = ""
    components: List[IBISComponent] = field(default_factory=list)
    models: List[IBISModel] = field(default_factory=list)
    unknown_keywords: List[str] = field(default_factory=list)

    # Convenience lookup
    def model(self, name: str) -> Optional[IBISModel]:
        """Return model by name (case-insensitive), or None."""
        nl = name.lower()
        for m in self.models:
            if m.name.lower() == nl:
                return m
        return None

    def component(self, name: str) -> Optional[IBISComponent]:
        """Return component by name (case-insensitive), or None."""
        nl = name.lower()
        for c in self.components:
            if c.name.lower() == nl:
                return c
        return None


# ── Internal helpers ────────────────────────────────────────────────────────────

# SI suffix table used in IBIS files (from IBIS spec §3).
_SI_SUFFIXES: dict[str, float] = {
    "T": 1e12, "G": 1e9, "M": 1e6,
    "k": 1e3, "m": 1e-3, "u": 1e-6,
    "n": 1e-9, "p": 1e-12, "f": 1e-15,
}

_SI_RE = re.compile(
    r"^\s*([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)\s*"
    r"([TGMkmunpf])?\s*$"
)


def _parse_si(token: str) -> Optional[float]:
    """Parse an IBIS numeric token with optional SI suffix.  Returns None for 'NA'."""
    s = token.strip()
    if s.upper() in ("NA", ""):
        return None
    m = _SI_RE.match(s)
    if m:
        mantissa = float(m.group(1))
        suffix = m.group(2)
        scale = _SI_SUFFIXES.get(suffix, 1.0) if suffix else 1.0
        return mantissa * scale
    # Fallback: try plain float
    try:
        return float(s)
    except ValueError:
        raise IBISParseError(f"Cannot parse numeric token: {s!r}")


def _parse_tmm(tokens: List[str]) -> TypMinMax:
    """Parse a typ/min/max triple from a list of string tokens."""
    while len(tokens) < 3:
        tokens.append("NA")
    return TypMinMax(
        typ=_parse_si(tokens[0]),
        min=_parse_si(tokens[1]),
        max=_parse_si(tokens[2]),
    )


def _split_value_line(line: str) -> List[str]:
    """Split a data line on whitespace/commas (IBIS allows either)."""
    return re.split(r"[\s,]+", line.strip())


def _keyword_name(line: str) -> Optional[str]:
    """If *line* is a keyword line [Keyword], return 'Keyword', else None."""
    m = re.match(r"^\s*\[([^\]]+)\]\s*", line)
    if m:
        return m.group(1).strip()
    return None


# ── Parser state machine ────────────────────────────────────────────────────────

_KNOWN_KEYWORDS = {
    "IBIS Ver", "File Name", "File Rev", "Date", "Source", "Notes",
    "Disclaimer", "Copyright",
    "Component", "Manufacturer", "Package", "Pin", "Diff Pin",
    "Package Model", "Begin Package Model", "End Package Model",
    "End",
    "Model", "Model Spec",
    "Pulldown", "Pullup",
    "GND Clamp", "POWER Clamp",
    "Ramp",
    "Rising Waveform", "Falling Waveform",
    "Model Selector",
    "External Circuit", "Circuit Call",
    "Test Data", "Test Load",
    "Submodel",
    "Begin Board Description", "End Board Description",
    "Comment Char",
}


class _Parser:
    """Line-by-line stateful IBIS parser."""

    def __init__(self, lines: List[str]):
        self.lines = lines
        self.pos = 0
        self.deck = IBISDeck()
        self._comment_char = "|"

    # ── Iteration helpers ───────────────────────────────────────────────────

    def _peek(self) -> Optional[str]:
        while self.pos < len(self.lines):
            raw = self.lines[self.pos]
            # Strip inline comment
            line = raw.split(self._comment_char)[0].rstrip()
            if line.strip():
                return line
            self.pos += 1
        return None

    def _advance(self) -> Optional[str]:
        line = self._peek()
        if line is not None:
            self.pos += 1
        return line

    def _is_keyword(self) -> bool:
        line = self._peek()
        return line is not None and bool(_keyword_name(line))

    # ── Top-level parse ──────────────────────────────────────────────────────

    def parse(self) -> IBISDeck:
        while True:
            line = self._peek()
            if line is None:
                break
            kw = _keyword_name(line)
            if kw is None:
                # Non-keyword line at top level (rare, treat as noise)
                self._advance()
                continue
            self._advance()  # consume the keyword line
            self._dispatch(kw, line)
        return self.deck

    def _dispatch(self, kw: str, kw_line: str):
        kw_lower = kw.lower()
        if kw_lower == "ibis ver":
            self.deck.ibis_ver = kw_line.split("]", 1)[-1].strip()
        elif kw_lower == "file name":
            self.deck.file_name = kw_line.split("]", 1)[-1].strip()
        elif kw_lower == "file rev":
            self.deck.file_rev = kw_line.split("]", 1)[-1].strip()
        elif kw_lower == "component":
            self._parse_component(kw_line)
        elif kw_lower == "model":
            self._parse_model(kw_line)
        elif kw_lower in ("end",):
            pass  # [End] — normal EOF marker
        elif kw_lower in ("comment char",):
            rest = kw_line.split("]", 1)[-1].strip()
            if rest:
                self._comment_char = rest[0]
        else:
            # Tolerate unknown keywords
            if kw not in self.deck.unknown_keywords:
                self.deck.unknown_keywords.append(kw)
                if kw not in _KNOWN_KEYWORDS:
                    warnings.warn(f"IBIS: unknown keyword [{kw}] — skipping", stacklevel=3)
            self._skip_until_next_keyword()

    # ── [Component] ─────────────────────────────────────────────────────────

    def _parse_component(self, kw_line: str):
        comp = IBISComponent()
        comp.name = kw_line.split("]", 1)[-1].strip()
        while not self._is_keyword():
            line = self._advance()
            if line is None:
                break
        # Now parse sub-keywords until next top-level [keyword]
        while True:
            line = self._peek()
            if line is None:
                break
            kw = _keyword_name(line)
            if kw is None:
                self._advance()
                continue
            kw_lower = kw.lower()
            # Sub-keywords that belong to [Component]
            if kw_lower == "manufacturer":
                self._advance()
                comp.manufacturer = line.split("]", 1)[-1].strip()
            elif kw_lower == "package":
                self._advance()
                self._parse_package(comp)
            elif kw_lower == "pin":
                self._advance()
                self._parse_pins(comp)
            elif kw_lower in ("diff pin", "package model",
                              "begin package model", "end package model",
                              "model selector"):
                self._advance()
                self._skip_until_next_keyword()
            else:
                # Start of a new top-level keyword → stop
                break
        self.deck.components.append(comp)

    def _parse_package(self, comp: IBISComponent):
        """Parse R_pkg, L_pkg, C_pkg lines inside [Package]."""
        while not self._is_keyword():
            line = self._advance()
            if line is None:
                break
            parts = _split_value_line(line)
            if not parts:
                continue
            key = parts[0].lower()
            vals = parts[1:]
            if key == "r_pkg":
                comp.package_r = _parse_tmm(vals)
            elif key == "l_pkg":
                comp.package_l = _parse_tmm(vals)
            elif key == "c_pkg":
                comp.package_c = _parse_tmm(vals)

    def _parse_pins(self, comp: IBISComponent):
        """Parse tabular pin rows until the next keyword."""
        # Skip the header row (contains column names)
        header_skipped = False
        while not self._is_keyword():
            line = self._advance()
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            parts = _split_value_line(line)
            if not parts:
                continue
            # Skip comment-style or header lines
            if parts[0].lower() in ("pin_name", "signal_name", "model_name"):
                header_skipped = True
                continue
            if not header_skipped and parts[0].lower() == "pin":
                # Sometimes the column header IS on the [Pin] keyword line; already consumed
                continue
            # Data row: pin_name signal_name model_name [R_pin L_pin C_pin]
            if len(parts) < 3:
                continue
            pin = IBISPin(
                pin_name=parts[0],
                signal_name=parts[1],
                model_name=parts[2],
            )
            if len(parts) > 3:
                try:
                    pin.r_pin = _parse_si(parts[3])
                except IBISParseError:
                    pass
            if len(parts) > 4:
                try:
                    pin.l_pin = _parse_si(parts[4])
                except IBISParseError:
                    pass
            if len(parts) > 5:
                try:
                    pin.c_pin = _parse_si(parts[5])
                except IBISParseError:
                    pass
            comp.pins.append(pin)

    # ── [Model] ─────────────────────────────────────────────────────────────

    def _parse_model(self, kw_line: str):
        model = IBISModel()
        model.name = kw_line.split("]", 1)[-1].strip()

        # First few lines before any sub-keyword may carry Model_type / Polarity / C_comp
        while not self._is_keyword():
            line = self._advance()
            if line is None:
                break
            parts = _split_value_line(line)
            if not parts:
                continue
            key = parts[0].lower().replace("_", "").replace("-", "")
            if key == "modeltype":
                model.model_type = parts[1] if len(parts) > 1 else ""
            elif key == "polarity":
                model.polarity = parts[1] if len(parts) > 1 else ""
            elif key == "ccomp":
                model.c_comp = _parse_tmm(parts[1:])
            elif key == "vinl":
                pass  # ignore optional thresholds
            elif key == "vinh":
                pass

        # Sub-keyword dispatch inside [Model]
        while True:
            line = self._peek()
            if line is None:
                break
            kw = _keyword_name(line)
            if kw is None:
                self._advance()
                continue
            kw_lower = kw.lower().replace(" ", "")
            if kw_lower == "pulldown":
                self._advance()
                model.pulldown = self._parse_iv_table()
            elif kw_lower == "pullup":
                self._advance()
                model.pullup = self._parse_iv_table()
            elif kw_lower in ("gndclamp", "powerclamp"):
                self._advance()
                self._skip_until_next_keyword()
            elif kw_lower == "ramp":
                self._advance()
                model.ramp = self._parse_ramp()
            elif kw_lower == "risingwaveform":
                self._advance()
                model.rising_waveforms.append(self._parse_waveform("rising"))
            elif kw_lower == "fallingwaveform":
                self._advance()
                model.falling_waveforms.append(self._parse_waveform("falling"))
            elif kw_lower == "modelspec":
                self._advance()
                self._skip_until_next_keyword()
            else:
                # Top-level keyword — stop processing this model
                break

        self.deck.models.append(model)

    def _parse_iv_table(self) -> List[TableRow]:
        """Parse V / I_typ / I_min / I_max rows until next keyword."""
        rows: List[TableRow] = []
        while not self._is_keyword():
            line = self._advance()
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            parts = _split_value_line(line)
            if len(parts) < 1:
                continue
            # Skip column-header lines
            if parts[0].lower() in ("voltage", "v"):
                continue
            if len(parts) < 2:
                continue
            try:
                v = _parse_si(parts[0])
                i_typ = _parse_si(parts[1]) if len(parts) > 1 else None
                i_min = _parse_si(parts[2]) if len(parts) > 2 else None
                i_max = _parse_si(parts[3]) if len(parts) > 3 else None
                if v is not None:
                    rows.append((v, i_typ, i_min, i_max))
            except IBISParseError:
                continue
        return rows

    def _parse_ramp(self) -> IBISRamp:
        ramp = IBISRamp()
        while not self._is_keyword():
            line = self._advance()
            if line is None:
                break
            parts = _split_value_line(line)
            if not parts:
                continue
            key = parts[0].lower()
            if key in ("dv/dt_r", "dv/dt_rise"):
                # Values look like: 1.2/1e-9  typ/min/max or three separate tokens
                ramp.dv_dt_rise = _parse_ramp_tmm(parts[1:])
            elif key in ("dv/dt_f", "dv/dt_fall"):
                ramp.dv_dt_fall = _parse_ramp_tmm(parts[1:])
            elif key == "r_load":
                if len(parts) > 1:
                    ramp.r_load = _parse_si(parts[1])
        return ramp

    def _parse_waveform(self, direction: str) -> IBISWaveform:
        wf = IBISWaveform(direction=direction)
        # Header scalars before the table
        while not self._is_keyword():
            line = self._advance()
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            parts = _split_value_line(line)
            if not parts:
                continue
            key = parts[0].lower()
            if key == "r_fixture":
                wf.r_fixture = _parse_si(parts[1]) if len(parts) > 1 else None
            elif key == "v_fixture":
                wf.v_fixture = _parse_si(parts[1]) if len(parts) > 1 else None
            elif key == "v_fixture_min":
                wf.v_fixture_min = _parse_si(parts[1]) if len(parts) > 1 else None
            elif key == "v_fixture_max":
                wf.v_fixture_max = _parse_si(parts[1]) if len(parts) > 1 else None
            elif key in ("time", "t"):
                # Column header — now we're in the table
                continue
            else:
                # Try to parse as a table row: time typ min max
                try:
                    t = _parse_si(parts[0])
                    v_typ = _parse_si(parts[1]) if len(parts) > 1 else None
                    v_min = _parse_si(parts[2]) if len(parts) > 2 else None
                    v_max = _parse_si(parts[3]) if len(parts) > 3 else None
                    if t is not None:
                        wf.table.append((t, v_typ, v_min, v_max))
                except IBISParseError:
                    pass
        return wf

    # ── Utility ─────────────────────────────────────────────────────────────

    def _skip_until_next_keyword(self):
        """Consume lines until the next [Keyword] line (not including it)."""
        while not self._is_keyword():
            if self._advance() is None:
                break


def _parse_ramp_tmm(tokens: List[str]) -> TypMinMax:
    """
    Ramp dV/dt can appear as:
      ``1.2V/1ns   0.9V/1.1ns   1.5V/0.9ns``   (fraction form per corner)
      ``1.2e9   0.9e9   1.5e9``                  (already in V/s)
    Returns TypMinMax in V/s.
    """
    results = []
    for tok in tokens[:3]:
        tok = tok.strip()
        if not tok or tok.upper() == "NA":
            results.append(None)
            continue
        if "/" in tok:
            # "dV/dt" fraction — e.g. "1.2V/1ns"  →  strip units
            # Numerator: strip trailing voltage/current unit letter (V, v, A, a)
            # Denominator: strip trailing time unit 's' only (keep SI prefix: n, p, u…)
            parts = tok.split("/")
            try:
                num_str = re.sub(r"[VvAa]+$", "", parts[0])
                den_str = re.sub(r"[sS]+$", "", parts[1])
                num = _parse_si(num_str)
                den = _parse_si(den_str)
                if num is not None and den and den != 0:
                    results.append(num / den)
                else:
                    results.append(None)
            except IBISParseError:
                results.append(None)
        else:
            try:
                results.append(_parse_si(tok))
            except IBISParseError:
                results.append(None)
    while len(results) < 3:
        results.append(None)
    return TypMinMax(typ=results[0], min=results[1], max=results[2])


# ── Public API ──────────────────────────────────────────────────────────────────

def parse_ibis(text: str) -> IBISDeck:
    """
    Parse an IBIS file from *text* and return an :class:`IBISDeck`.

    Parameters
    ----------
    text : str
        Full contents of the IBIS (.ibs) file.

    Returns
    -------
    IBISDeck
        Populated data model with components, models, IV tables, ramp, etc.

    Raises
    ------
    IBISParseError
        On unrecoverable structural errors (e.g. completely empty input).

    Warns
    -----
    UserWarning
        For unrecognised keywords — parsing continues.
    """
    lines = text.splitlines()
    if not lines:
        raise IBISParseError("IBIS text is empty")
    parser = _Parser(lines)
    deck = parser.parse()
    return deck


def ibis_deck_to_dict(deck: IBISDeck) -> dict:
    """
    Serialise an :class:`IBISDeck` to a plain-Python dict (JSON-safe).

    IV table rows are stored as lists ``[V, I_typ, I_min, I_max]`` with
    ``None`` for NA values.  TypMinMax triples become ``[typ, min, max]``.
    """
    def _tmm(v: TypMinMax) -> list:
        return [v.typ, v.min, v.max]

    def _rows(table: List[TableRow]) -> list:
        return [[r[0], r[1], r[2], r[3]] for r in table]

    def _wf(w: IBISWaveform) -> dict:
        return {
            "direction": w.direction,
            "r_fixture": w.r_fixture,
            "v_fixture": w.v_fixture,
            "table": _rows(w.table),
        }

    def _model(m: IBISModel) -> dict:
        return {
            "name": m.name,
            "model_type": m.model_type,
            "polarity": m.polarity,
            "c_comp": _tmm(m.c_comp),
            "pulldown": _rows(m.pulldown),
            "pullup": _rows(m.pullup),
            "ramp": {
                "dv_dt_rise": _tmm(m.ramp.dv_dt_rise) if m.ramp else [None, None, None],
                "dv_dt_fall": _tmm(m.ramp.dv_dt_fall) if m.ramp else [None, None, None],
                "r_load": m.ramp.r_load if m.ramp else None,
            } if m.ramp else None,
            "rising_waveforms": [_wf(w) for w in m.rising_waveforms],
            "falling_waveforms": [_wf(w) for w in m.falling_waveforms],
        }

    def _pin(p: IBISPin) -> dict:
        return {
            "pin_name": p.pin_name,
            "signal_name": p.signal_name,
            "model_name": p.model_name,
            "r_pin": p.r_pin,
            "l_pin": p.l_pin,
            "c_pin": p.c_pin,
        }

    def _comp(c: IBISComponent) -> dict:
        return {
            "name": c.name,
            "manufacturer": c.manufacturer,
            "package_r": _tmm(c.package_r),
            "package_l": _tmm(c.package_l),
            "package_c": _tmm(c.package_c),
            "pins": [_pin(p) for p in c.pins],
        }

    return {
        "ibis_ver": deck.ibis_ver,
        "file_name": deck.file_name,
        "file_rev": deck.file_rev,
        "components": [_comp(c) for c in deck.components],
        "models": [_model(m) for m in deck.models],
        "unknown_keywords": deck.unknown_keywords,
    }
