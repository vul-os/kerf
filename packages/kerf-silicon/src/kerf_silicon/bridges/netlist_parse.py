"""
Yosys JSON netlist parser.

Reads the JSON produced by Yosys ``write_json`` and returns a Python AST made
of frozen dataclasses:

    NetlistAST
      .creator  : str
      .modules  : list[Module]

    Module
      .name        : str
      .ports       : list[Port]
      .cells       : list[Cell]
      .connections : list[Connection]   (top-level net assignments)

    Port
      .name      : str
      .direction : "input" | "output" | "inout"
      .bits      : list[int | str]      (bit-vector; str == "0"/"1"/"x"/"z")

    Cell
      .name      : str
      .cell_type : str                  (e.g. "$_AND_", "sky130_fd_sc_hd__and2_1")
      .parameters: dict[str, str]
      .attributes: dict[str, str]
      .connections: dict[str, list[int | str]]  (port-name → bits)

    Connection
      .left  : list[int | str]   (bit-vector)
      .right : list[int | str]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union

# Yosys uses integers for real net IDs and the strings "0"/"1"/"x"/"z" for
# constant / high-impedance drivers.
Bit = Union[int, str]


# ---------------------------------------------------------------------------
# Dataclasses (frozen = hashable, immutable after construction)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Port:
    name: str
    direction: str                        # "input" | "output" | "inout"
    bits: tuple[Bit, ...]                 # bit-vector LSB-first


@dataclass(frozen=True)
class Cell:
    name: str
    cell_type: str
    parameters: dict[str, str]            # NB: not truly frozen, but immutable by convention
    attributes: dict[str, str]
    connections: dict[str, tuple[Bit, ...]]   # port-name → bits


@dataclass(frozen=True)
class Connection:
    left: tuple[Bit, ...]
    right: tuple[Bit, ...]


@dataclass(frozen=True)
class Module:
    name: str
    ports: tuple[Port, ...]
    cells: tuple[Cell, ...]
    connections: tuple[Connection, ...]


@dataclass(frozen=True)
class NetlistAST:
    creator: str
    modules: tuple[Module, ...]


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------

def _parse_bits(raw: Any) -> tuple[Bit, ...]:
    """Normalise a Yosys bit-vector (list of int | str) to a tuple."""
    if not isinstance(raw, list):
        return ()
    result: list[Bit] = []
    for b in raw:
        if isinstance(b, int):
            result.append(b)
        elif isinstance(b, str):
            # Yosys uses "0", "1", "x", "z" for constants / high-Z.
            result.append(b)
        else:
            result.append(str(b))
    return tuple(result)


def _parse_port(name: str, raw: dict[str, Any]) -> Port:
    return Port(
        name=name,
        direction=str(raw.get("direction", "input")),
        bits=_parse_bits(raw.get("bits", [])),
    )


def _parse_cell(name: str, raw: dict[str, Any]) -> Cell:
    raw_conns = raw.get("connections", {})
    connections: dict[str, tuple[Bit, ...]] = {
        port: _parse_bits(bits) for port, bits in raw_conns.items()
    }
    return Cell(
        name=name,
        cell_type=str(raw.get("type", "")),
        parameters=dict(raw.get("parameters", {})),
        attributes=dict(raw.get("attributes", {})),
        connections=connections,
    )


def _parse_module(name: str, raw: dict[str, Any]) -> Module:
    raw_ports = raw.get("ports", {})
    ports = tuple(_parse_port(pname, pdata) for pname, pdata in raw_ports.items())

    raw_cells = raw.get("cells", {})
    cells = tuple(_parse_cell(cname, cdata) for cname, cdata in raw_cells.items())

    # Top-level net connections ("netnames" in Yosys JSON — not the same as
    # the per-cell connections, but useful for net tracing).
    raw_netnames = raw.get("netnames", {})
    connections: list[Connection] = []
    for _net_name, net_data in raw_netnames.items():
        bits = _parse_bits(net_data.get("bits", []))
        if bits:
            # Represent as a self-connection (identity) for uniform handling.
            connections.append(Connection(left=bits, right=bits))

    return Module(
        name=name,
        ports=ports,
        cells=cells,
        connections=tuple(connections),
    )


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def parse_netlist(raw_json: dict[str, Any]) -> NetlistAST:
    """Parse a Yosys ``write_json`` dict into a :class:`NetlistAST`.

    Parameters
    ----------
    raw_json:
        Python dict produced by ``json.loads`` on the Yosys JSON output.

    Returns
    -------
    NetlistAST
        A tree of frozen dataclasses representing the synthesised netlist.
    """
    creator = str(raw_json.get("creator", ""))
    raw_modules = raw_json.get("modules", {})

    modules = tuple(
        _parse_module(mname, mdata) for mname, mdata in raw_modules.items()
    )

    return NetlistAST(creator=creator, modules=modules)
