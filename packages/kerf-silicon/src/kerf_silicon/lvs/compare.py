"""compare.py — LVS netlist comparison engine.

Tier-1 comparison: exact cell-count + port-net match.
No heavy graph-isomorphism; matches are structural/name-based.

Public API
----------
lvs_match(extracted, reference) -> LvsReport
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kerf_silicon.lvs.extractor import Netlist, CellInstance, Net


# ---------------------------------------------------------------------------
# Report data model
# ---------------------------------------------------------------------------

@dataclass
class CellDiff:
    """Describes a mismatch between extracted and reference cell instances."""
    kind: str          # "missing_in_extracted" | "extra_in_extracted" | "port_mismatch"
    ref: str           # cell reference designator
    detail: str = ""


@dataclass
class NetDiff:
    """Describes a mismatch between extracted and reference nets."""
    kind: str          # "missing_in_extracted" | "extra_in_extracted" | "pin_mismatch"
    net_name: str
    detail: str = ""


@dataclass
class LvsReport:
    """Top-level LVS result."""
    matched: bool
    cell_diffs: list[CellDiff] = field(default_factory=list)
    net_diffs: list[NetDiff] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.matched:
            return "LVS CLEAN — layout matches schematic."
        parts = []
        if self.cell_diffs:
            parts.append(f"{len(self.cell_diffs)} cell difference(s)")
        if self.net_diffs:
            parts.append(f"{len(self.net_diffs)} net difference(s)")
        return "LVS FAIL — " + ", ".join(parts) + "."


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def _index_cells(netlist: Netlist) -> dict[str, CellInstance]:
    """Return {ref: CellInstance} map."""
    return {c.ref: c for c in netlist.cells}


def _index_nets(netlist: Netlist) -> dict[str, Net]:
    """Return {name: Net} map."""
    return {n.name: n for n in netlist.nets}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def lvs_match(extracted: Netlist, reference: Netlist) -> LvsReport:
    """Compare an extracted netlist against a reference schematic netlist.

    Tier-1 comparison rules
    -----------------------
    1. Every cell ref in *reference* must appear in *extracted* with the same
       cell_type and the same ordered port list.
    2. Every cell ref in *extracted* must appear in *reference* (no extras).
    3. Every net name in *reference* must appear in *extracted* with an
       identical pin_refs set.
    4. Every net name in *extracted* must appear in *reference* (no extras).

    Returns
    -------
    LvsReport
        ``matched=True`` iff rules 1-4 all pass with zero differences.
    """
    cell_diffs: list[CellDiff] = []
    net_diffs: list[NetDiff] = []

    ext_cells = _index_cells(extracted)
    ref_cells = _index_cells(reference)
    ext_nets = _index_nets(extracted)
    ref_nets = _index_nets(reference)

    # ---- Cell comparison ------------------------------------------------

    # Cells in reference but missing/mismatched in extracted
    for ref_name, ref_cell in ref_cells.items():
        if ref_name not in ext_cells:
            cell_diffs.append(CellDiff(
                kind="missing_in_extracted",
                ref=ref_name,
                detail=f"Expected cell of type '{ref_cell.cell_type}'",
            ))
            continue
        ext_cell = ext_cells[ref_name]
        if ext_cell.cell_type != ref_cell.cell_type:
            cell_diffs.append(CellDiff(
                kind="port_mismatch",
                ref=ref_name,
                detail=(
                    f"Type mismatch: extracted='{ext_cell.cell_type}' "
                    f"vs reference='{ref_cell.cell_type}'"
                ),
            ))
        elif ext_cell.ports != ref_cell.ports:
            cell_diffs.append(CellDiff(
                kind="port_mismatch",
                ref=ref_name,
                detail=(
                    f"Ports differ: extracted={ext_cell.ports!r} "
                    f"vs reference={ref_cell.ports!r}"
                ),
            ))

    # Extra cells in extracted that are not in reference
    for ref_name in ext_cells:
        if ref_name not in ref_cells:
            cell_diffs.append(CellDiff(
                kind="extra_in_extracted",
                ref=ref_name,
                detail="Not present in reference schematic",
            ))

    # ---- Net comparison -------------------------------------------------

    # Nets in reference but missing/mismatched in extracted
    for net_name, ref_net in ref_nets.items():
        if net_name not in ext_nets:
            net_diffs.append(NetDiff(
                kind="missing_in_extracted",
                net_name=net_name,
                detail=f"Expected net '{net_name}' with pins {sorted(ref_net.pin_refs)}",
            ))
            continue
        ext_net = ext_nets[net_name]
        if set(ext_net.pin_refs) != set(ref_net.pin_refs):
            net_diffs.append(NetDiff(
                kind="pin_mismatch",
                net_name=net_name,
                detail=(
                    f"Pin sets differ: extracted={sorted(ext_net.pin_refs)!r} "
                    f"vs reference={sorted(ref_net.pin_refs)!r}"
                ),
            ))

    # Extra nets in extracted not in reference
    for net_name in ext_nets:
        if net_name not in ref_nets:
            net_diffs.append(NetDiff(
                kind="extra_in_extracted",
                net_name=net_name,
                detail="Not present in reference schematic",
            ))

    matched = not cell_diffs and not net_diffs
    return LvsReport(matched=matched, cell_diffs=cell_diffs, net_diffs=net_diffs)
