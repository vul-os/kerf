"""AST node definitions for the atopile `.ato` language.

Every node is a dataclass.  Source location (line, col) uses 1-based lines and
0-based columns, matching the convention used by most language tools.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class SourceLoc:
    """Source location (1-based line, 0-based column)."""
    line: int
    col: int

    def __repr__(self) -> str:
        return f"{self.line}:{self.col}"


# ---------------------------------------------------------------------------
# Leaf / value nodes
# ---------------------------------------------------------------------------


@dataclass
class Identifier:
    """A simple name token, e.g. `vin`, `Resistor`, `value`."""
    name: str
    loc: SourceLoc


@dataclass
class DottedName:
    """A possibly-dotted reference, e.g. `r1.p1` or `vin`."""
    parts: List[str]
    loc: SourceLoc

    @property
    def name(self) -> str:
        return ".".join(self.parts)


@dataclass
class QuantityLiteral:
    """A numeric literal with an optional unit, e.g. `10kohm`, `100nF`, `3.3V`."""
    value: float
    unit: str          # empty string when unitless
    raw: str           # original source text, e.g. "10kohm"
    loc: SourceLoc


@dataclass
class StringLiteral:
    """A double-quoted string literal, e.g. `"generics/resistors.ato"`."""
    value: str
    loc: SourceLoc


# ---------------------------------------------------------------------------
# Statement nodes
# ---------------------------------------------------------------------------


@dataclass
class ImportStatement:
    """``import <name> from "<path>"``"""
    name: str
    path: str
    loc: SourceLoc


@dataclass
class SignalDecl:
    """``signal <name>``"""
    name: str
    loc: SourceLoc


@dataclass
class PinDecl:
    """``pin <name>``"""
    name: str
    loc: SourceLoc


@dataclass
class ComponentInstance:
    """``<name> = new <type>``"""
    instance_name: str
    type_name: str
    loc: SourceLoc


@dataclass
class Assignment:
    """``<target> = <value>``

    ``value`` is one of :class:`QuantityLiteral`, :class:`StringLiteral`,
    or :class:`Identifier`.
    """
    target: DottedName
    value: object          # QuantityLiteral | StringLiteral | Identifier
    loc: SourceLoc


@dataclass
class Connection:
    """``<left> ~ <right>``"""
    left: DottedName
    right: DottedName
    loc: SourceLoc


@dataclass
class ParameterDecl:
    """``<name>: <type>``  (typed parameter declaration inside a module)"""
    name: str
    type_name: str
    default: Optional[object]   # QuantityLiteral | StringLiteral | None
    loc: SourceLoc


# ---------------------------------------------------------------------------
# Block nodes
# ---------------------------------------------------------------------------


@dataclass
class ModuleBlock:
    """``module <name> [from <base>]: ...``"""
    name: str
    base: Optional[str]
    body: List[object]          # list of statement/block nodes
    loc: SourceLoc


@dataclass
class ComponentBlock:
    """``component <name> [from <base>]: ...``"""
    name: str
    base: Optional[str]
    body: List[object]
    loc: SourceLoc


@dataclass
class InterfaceBlock:
    """``interface <name> [from <base>]: ...``"""
    name: str
    base: Optional[str]
    body: List[object]
    loc: SourceLoc


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


@dataclass
class Module:
    """Root of the AST — represents one `.ato` source file."""
    imports: List[ImportStatement] = field(default_factory=list)
    blocks: List[object] = field(default_factory=list)  # ModuleBlock | ComponentBlock | …
