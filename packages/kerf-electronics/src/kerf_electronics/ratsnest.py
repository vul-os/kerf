"""
ratsnest.py — Minimum-spanning-tree ratsnest for PCB nets.

Given a CircuitJSON flat array (list of dicts), groups pads by net and
computes a minimum spanning tree (Prim's algorithm, pure Python) over each
net's pad positions.  The result is a list of "airwire" segments that a
frontend overlay can draw to show unrouted connections.

Public API
----------
compute_ratsnest(circuit_json) -> list[dict]
    Returns a list of edge dicts:
        {
          "net_id": str,
          "from": {"x": float, "y": float, "pad_id": str},
          "to":   {"x": float, "y": float, "pad_id": str},
          "length_mm": float,
        }
    Only edges that do not already have a routed trace covering them are
    included (unrouted-net logic deferred to caller; this module always
    returns the MST regardless of routing state).

compute_net_mst(pads) -> list[dict]
    Lower-level helper: given a list of {"x", "y", "pad_id"} dicts for a
    single net, return the MST edges as
        [{"from": pad, "to": pad, "length_mm": float}, ...]
    using Prim's algorithm.  Total MST length = sum(e["length_mm"]).

Design notes
------------
* Pure Python — no numpy, no scipy.  O(n^2) per net which is fast enough
  for typical PCB pad counts (<200 pads per net in practice).
* Pad types covered: pcb_smtpad, pcb_plated_hole, source_port (with x/y).
  We union them all into a single pad pool keyed by net_id.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _dist(a: Dict, b: Dict) -> float:
    """Euclidean distance between two {x, y} dicts (mm)."""
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


# ---------------------------------------------------------------------------
# MST (Prim's algorithm)
# ---------------------------------------------------------------------------

def compute_net_mst(pads: List[Dict]) -> List[Dict]:
    """Return MST edges for a single net's pad list.

    Parameters
    ----------
    pads : list of {"x": float, "y": float, "pad_id": str}
        At least two pads are required; fewer → empty list returned.

    Returns
    -------
    list of {"from": pad, "to": pad, "length_mm": float}
    """
    n = len(pads)
    if n < 2:
        return []

    # Prim's: track which nodes are in-tree, and the cheapest edge to each
    # out-of-tree node.
    in_tree = [False] * n
    min_dist = [math.inf] * n
    parent = [-1] * n

    # Start from node 0
    min_dist[0] = 0.0

    edges: List[Dict] = []

    for _ in range(n):
        # Pick the out-of-tree node with minimum distance
        u = -1
        best = math.inf
        for i in range(n):
            if not in_tree[i] and min_dist[i] < best:
                best = min_dist[i]
                u = i
        if u == -1:
            break  # disconnected (should not happen)

        in_tree[u] = True

        # Record the edge (skip the seed node)
        if parent[u] != -1:
            edges.append({
                "from": pads[parent[u]],
                "to": pads[u],
                "length_mm": _dist(pads[parent[u]], pads[u]),
            })

        # Update key values of adjacent vertices
        for v in range(n):
            if not in_tree[v]:
                d = _dist(pads[u], pads[v])
                if d < min_dist[v]:
                    min_dist[v] = d
                    parent[v] = u

    return edges


# ---------------------------------------------------------------------------
# Net extraction from CircuitJSON
# ---------------------------------------------------------------------------

_PAD_TYPES = {"pcb_smtpad", "pcb_plated_hole"}


def _extract_pads_by_net(circuit_json: List[Dict]) -> Dict[str, List[Dict]]:
    """Group pad positions by net_id from a flat CircuitJSON array."""
    nets: Dict[str, List[Dict]] = {}
    pad_serial = 0

    for elem in circuit_json:
        etype = elem.get("type", "")
        if etype not in _PAD_TYPES:
            continue
        net_id = elem.get("net_id") or elem.get("net") or elem.get("net_name")
        if not net_id:
            continue
        x = elem.get("x")
        y = elem.get("y")
        if x is None or y is None:
            continue
        pad_id = (
            elem.get("pcb_smtpad_id")
            or elem.get("pcb_plated_hole_id")
            or elem.get("id")
            or f"pad_{pad_serial}"
        )
        pad_serial += 1
        nets.setdefault(net_id, []).append({"x": float(x), "y": float(y), "pad_id": str(pad_id)})

    return nets


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_ratsnest(circuit_json: List[Dict]) -> List[Dict]:
    """Compute MST ratsnest airwires for all nets in *circuit_json*.

    Parameters
    ----------
    circuit_json : list[dict]
        Flat CircuitJSON array (as returned by tscircuit).

    Returns
    -------
    list[dict]  — one entry per MST edge:
        {
          "net_id": str,
          "from": {"x": float, "y": float, "pad_id": str},
          "to":   {"x": float, "y": float, "pad_id": str},
          "length_mm": float,
        }
    """
    if not isinstance(circuit_json, list):
        return []

    pads_by_net = _extract_pads_by_net(circuit_json)
    result: List[Dict] = []

    for net_id, pads in pads_by_net.items():
        mst_edges = compute_net_mst(pads)
        for edge in mst_edges:
            result.append({
                "net_id": net_id,
                "from": edge["from"],
                "to": edge["to"],
                "length_mm": edge["length_mm"],
            })

    return result
