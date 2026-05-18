"""VHDL AST dataclasses — IEEE 1076-2008 subset.

All nodes carry a ``line`` attribute (1-based) for error reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

@dataclass
class TypeMark:
    """A type name, possibly with a constraint.

    Examples: ``std_logic``, ``std_logic_vector(7 downto 0)``,
    ``integer range 0 to 255``.
    """

    name: str
    """Base type name, normalised to lower-case."""

    constraint: Optional[str] = None
    """Raw constraint text as it appeared in source, e.g. ``7 downto 0``."""

    line: int = 0


# ---------------------------------------------------------------------------
# Design-unit nodes
# ---------------------------------------------------------------------------

@dataclass
class LibraryClause:
    """``library IEEE;``"""

    names: list[str]
    line: int = 0


@dataclass
class UseClause:
    """``use IEEE.STD_LOGIC_1164.ALL;``"""

    selected_names: list[str]
    line: int = 0


@dataclass
class Port:
    """A single port declaration inside an entity."""

    name: str
    direction: str          # "in" | "out" | "inout" | "buffer"
    type_mark: TypeMark
    default: Optional[str] = None
    line: int = 0


@dataclass
class Generic:
    """A single generic declaration inside an entity."""

    name: str
    type_mark: TypeMark
    default: Optional[str] = None
    line: int = 0


@dataclass
class Entity:
    """``entity Foo is port(…); end entity Foo;``"""

    name: str
    generics: list[Generic] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)
    line: int = 0


# ---------------------------------------------------------------------------
# Architecture internals
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """``signal count : std_logic_vector(7 downto 0) := (others => '0');``"""

    name: str
    type_mark: TypeMark
    default: Optional[str] = None
    line: int = 0


@dataclass
class SignalAssignment:
    """``q <= d;``  or  ``count <= count + 1;``"""

    target: str
    expression: str
    line: int = 0


@dataclass
class VariableAssignment:
    """``v := expr;``"""

    target: str
    expression: str
    line: int = 0


@dataclass
class IfStatement:
    """``if … then … elsif … else … end if;``"""

    condition: str
    then_stmts: list = field(default_factory=list)
    elsif_branches: list[tuple[str, list]] = field(default_factory=list)
    else_stmts: list = field(default_factory=list)
    line: int = 0


@dataclass
class WhenBranch:
    """A single ``when choice => …`` inside a case statement."""

    choices: list[str]
    stmts: list = field(default_factory=list)
    line: int = 0


@dataclass
class CaseStatement:
    """``case state is when … end case;``"""

    expression: str
    branches: list[WhenBranch] = field(default_factory=list)
    line: int = 0


@dataclass
class Process:
    """``process(clk, rst) begin … end process;``"""

    sensitivity_list: list[str]
    declarations: list = field(default_factory=list)
    statements: list = field(default_factory=list)
    label: Optional[str] = None
    line: int = 0


@dataclass
class ComponentDeclaration:
    """``component Foo is port(…); end component;``"""

    name: str
    generics: list[Generic] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)
    line: int = 0


@dataclass
class PortMap:
    """A single ``formal => actual`` or positional entry."""

    formal: Optional[str]
    actual: str
    line: int = 0


@dataclass
class ComponentInstantiation:
    """``label : ComponentName port map(…);``"""

    label: str
    component_name: str
    generic_map: list[PortMap] = field(default_factory=list)
    port_map: list[PortMap] = field(default_factory=list)
    line: int = 0


@dataclass
class GenerateStatement:
    """``label : for i in … generate … end generate;``"""

    label: str
    scheme: str          # raw generate-scheme text
    statements: list = field(default_factory=list)
    line: int = 0


@dataclass
class Architecture:
    """``architecture rtl of Foo is … begin … end architecture rtl;``"""

    name: str
    entity_name: str
    declarations: list = field(default_factory=list)   # Signal / ComponentDeclaration / …
    statements: list = field(default_factory=list)     # Process / ComponentInstantiation / …
    line: int = 0


# ---------------------------------------------------------------------------
# Top-level design file
# ---------------------------------------------------------------------------

@dataclass
class DesignFile:
    """Root node — a complete VHDL source file."""

    library_clauses: list[LibraryClause] = field(default_factory=list)
    use_clauses: list[UseClause] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    architectures: list[Architecture] = field(default_factory=list)
