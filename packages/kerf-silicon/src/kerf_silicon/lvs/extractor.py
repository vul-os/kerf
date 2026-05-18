"""extractor.py — layout-to-netlist extraction for LVS.

Traverses a layout's connectivity model: polygons on electrically-connected
layers that touch (or overlap) are merged into a single net via union-find.
Via stacks propagate connectivity across layer pairs.

Public API
----------
extract(layout, tech) -> Netlist
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CellInstance:
    """A device/cell placed in the layout."""
    ref: str          # reference designator, e.g. "M1"
    cell_type: str    # cell master name, e.g. "nmos", "pmos", "res"
    ports: list[str] = field(default_factory=list)  # ordered port names


@dataclass
class Net:
    """A single electrical net in the extracted netlist."""
    name: str
    pin_refs: list[str] = field(default_factory=list)  # "ref/port" strings


@dataclass
class Netlist:
    """Extracted netlist: cells + nets."""
    cells: list[CellInstance] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Union-Find (path-compressed, union-by-rank)
# ---------------------------------------------------------------------------

class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}

    def _make(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x: str) -> str:
        self._make(x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path halving
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def connected(self, a: str, b: str) -> bool:
        return self.find(a) == self.find(b)

    def groups(self) -> dict[str, list[str]]:
        """Return {root: [members]} for all groups with >0 members."""
        out: dict[str, list[str]] = {}
        for x in self._parent:
            r = self.find(x)
            out.setdefault(r, []).append(x)
        return out


# ---------------------------------------------------------------------------
# Layout schema helpers
# ---------------------------------------------------------------------------
#
# Layout dict schema (all keys optional / may be absent):
#
#   {
#     "cells": [                       # placed cell instances
#       {
#         "ref": str,                  # reference designator
#         "type": str,                 # cell master name
#         "ports": [                   # port definitions
#           {"name": str, "net": str}  # net label connecting to this port
#         ]
#       }, ...
#     ],
#     "polygons": [                    # metal/diffusion polygons
#       {
#         "id": str,                   # unique polygon id
#         "layer": str,                # e.g. "M1", "M2", "DIFF", "POLY"
#         "touches": [str, ...]        # ids of polygons this polygon touches
#       }, ...
#     ],
#     "vias": [                        # via connections between layers
#       {
#         "lower_poly": str,           # polygon id on lower layer
#         "upper_poly": str            # polygon id on upper layer
#       }, ...
#     ],
#   }
#
# Tech dict schema:
#   {
#     "connected_layers": [[str, str], ...]  # pairs of layers bridged by vias
#   }
# ---------------------------------------------------------------------------

def extract(layout: dict[str, Any], tech: dict[str, Any] | None = None) -> Netlist:
    """Extract a Netlist from a layout + technology description.

    Parameters
    ----------
    layout:
        Layout description (see schema above).
    tech:
        Technology description with at least a ``connected_layers`` list.
        May be ``None`` if the layout carries all connectivity explicitly.

    Returns
    -------
    Netlist
        Extracted cells and nets.
    """
    if tech is None:
        tech = {}

    uf = _UnionFind()

    # ---- 1. Seed union-find with all polygon ids -------------------------
    for poly in layout.get("polygons", []):
        uf.find(poly["id"])  # _make via find

    # ---- 2. Merge touching polygons on the same (or connected) layer -----
    for poly in layout.get("polygons", []):
        pid = poly["id"]
        for neighbor_id in poly.get("touches", []):
            uf.union(pid, neighbor_id)

    # ---- 3. Merge via stacks --------------------------------------------
    for via in layout.get("vias", []):
        lower = via.get("lower_poly")
        upper = via.get("upper_poly")
        if lower and upper:
            uf.union(lower, upper)

    # ---- 4. Build net-label map from explicit net annotations on polygons
    # (polygons may carry a "net" label used as the canonical net name)
    root_to_netname: dict[str, str] = {}
    for poly in layout.get("polygons", []):
        if "net" in poly:
            root = uf.find(poly["id"])
            root_to_netname.setdefault(root, poly["net"])

    # ---- 5. Walk cells; attach port-to-net bindings ---------------------
    cells: list[CellInstance] = []
    # Maps net_label -> list of "ref/port" pin references
    net_to_pins: dict[str, list[str]] = {}

    for cell_dict in layout.get("cells", []):
        ref = cell_dict["ref"]
        cell_type = cell_dict.get("type", "")
        port_names: list[str] = []

        for port_def in cell_dict.get("ports", []):
            pname = port_def["name"]
            port_names.append(pname)
            net_label = port_def.get("net", f"{ref}_{pname}_floating")
            net_to_pins.setdefault(net_label, []).append(f"{ref}/{pname}")

        cells.append(CellInstance(ref=ref, cell_type=cell_type, ports=port_names))

    # ---- 6. Also expose polygon-derived nets (those with a net label) ---
    # Gather all polygon group roots that haven't been mapped through cell
    # ports yet, and create implicit nets for annotated groups.
    poly_net_labels: set[str] = set(root_to_netname.values())
    for label in poly_net_labels:
        net_to_pins.setdefault(label, [])

    # ---- 7. Assemble Netlist --------------------------------------------
    nets: list[Net] = []
    for net_name, pins in net_to_pins.items():
        nets.append(Net(name=net_name, pin_refs=list(pins)))

    return Netlist(cells=cells, nets=nets)
