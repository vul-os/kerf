"""ast.py — Liberty timing-library AST dataclasses.

Each node records the source position (line, col) where it was opened
so callers can provide diagnostics that point back into the .lib file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SourcePos:
    """Zero-based line and column of a token or group open-brace."""
    line: int
    col: int

    def __repr__(self) -> str:  # pragma: no cover
        return f"{self.line + 1}:{self.col + 1}"


@dataclass
class LUTable:
    """Lookup-table (e.g. cell_rise, cell_fall, rise_transition).

    ``template`` is the name passed to the group — e.g. ``delay_template``.
    ``values`` is a flat list of floats parsed from the comma/quote-delimited
    ``values(...)`` attribute.
    """
    template: str
    values: list[float]
    pos: Optional[SourcePos] = field(default=None, repr=False)


@dataclass
class TimingArc:
    """One ``timing ()`` group inside a pin."""
    related_pin: Optional[str] = None
    timing_type: Optional[str] = None
    timing_sense: Optional[str] = None
    cell_rise: Optional[LUTable] = None
    cell_fall: Optional[LUTable] = None
    rise_transition: Optional[LUTable] = None
    fall_transition: Optional[LUTable] = None
    pos: Optional[SourcePos] = field(default=None, repr=False)


@dataclass
class Pin:
    """One ``pin (NAME) { ... }`` group inside a cell."""
    name: str
    direction: Optional[str] = None
    capacitance: Optional[float] = None
    max_capacitance: Optional[float] = None
    function: Optional[str] = None
    three_state: Optional[str] = None
    timing_arcs: list[TimingArc] = field(default_factory=list)
    pos: Optional[SourcePos] = field(default=None, repr=False)


@dataclass
class Cell:
    """One ``cell (NAME) { ... }`` group inside a library."""
    name: str
    area: Optional[float] = None
    cell_leakage_power: Optional[float] = None
    pins: list[Pin] = field(default_factory=list)
    pos: Optional[SourcePos] = field(default=None, repr=False)

    # Convenience accessor — timing arcs are nested under pins; expose a flat
    # view for callers that only care about arc-level data.
    @property
    def timing_arcs(self) -> list[TimingArc]:
        arcs: list[TimingArc] = []
        for pin in self.pins:
            arcs.extend(pin.timing_arcs)
        return arcs


@dataclass
class OperatingConditions:
    """``operating_conditions (NAME) { ... }`` group."""
    name: str
    process: Optional[float] = None
    temperature: Optional[float] = None
    voltage: Optional[float] = None
    pos: Optional[SourcePos] = field(default=None, repr=False)


@dataclass
class LUTableTemplate:
    """``lu_table_template (NAME) { ... }`` group."""
    name: str
    variable_1: Optional[str] = None
    variable_2: Optional[str] = None
    index_1: list[float] = field(default_factory=list)
    index_2: list[float] = field(default_factory=list)
    pos: Optional[SourcePos] = field(default=None, repr=False)


@dataclass
class LibertyLibrary:
    """Top-level ``library (NAME) { ... }`` object returned by the parser."""
    name: str
    cells: list[Cell] = field(default_factory=list)
    operating_conditions: list[OperatingConditions] = field(default_factory=list)
    lu_table_templates: list[LUTableTemplate] = field(default_factory=list)
    pos: Optional[SourcePos] = field(default=None, repr=False)
