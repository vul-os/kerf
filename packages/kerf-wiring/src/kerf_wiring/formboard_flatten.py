"""
kerf_wiring.formboard_flatten — 2D manufacturing output for 3D wiring harnesses.

Converts a multi-segment 3D harness graph into a **formboard layout**: a 2D
unfolded representation used on the manufacturing floor to guide wire cutting,
routing over nails/pegs, and connector assembly.

Design notes
------------
* **Topological unfold, not a planar projection** — the formboard preserves
  total wire lengths exactly.  Each 3D segment becomes a segment of the same
  arc-length on the 2D board.  Bend angles from 3D are not preserved; instead
  the longest path from the root is laid horizontally (the "main trunk") and
  every side branch unfolds as a stub at its tap point.

* **Graph model** — the harness is expressed as a graph of segments and branch
  points.  Each segment is a :class:`HarnessSegment` (from ``harness3d.py``)
  tagged with a wire list and connector info at each end.  The graph may be a
  tree (typical) or have junctions; cycles are rejected with
  :class:`FormboardError`.

* **Layout algorithm** (ISO 7200-family industry convention):
  1. Find the "main trunk" = longest simple path from the root connector
     (depth-first, maximise cumulative arc-length).
  2. Place main trunk waypoints along the positive X axis starting at (0, 0).
  3. At each branch-point on the trunk, enumerate remaining branches sorted by
     descending length.  The first branch goes upward (+Y), the next downward
     (−Y), alternating with a 5 mm vertical gap between siblings at the same
     tap.
  4. Recurse for sub-branches using the same alternating rule relative to the
     parent branch direction.

* **No OCCT / external dependency** — pure Python, uses only stdlib.

Terminology
-----------
harness_3d  — dict describing the harness graph (see :func:`formboard_flatten`)
Formboard2D — result dataclass; contains 2D point lists, wire table, annotations

Public API
----------
:func:`formboard_flatten`
:class:`Formboard2D`
:class:`BranchPoint2D`
:class:`Wire2D`
:class:`Annotation`
:exc:`FormboardError`
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FormboardError(Exception):
    """Raised for invalid harness graphs (cycles, disconnected graphs, etc.)."""


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass
class BranchPoint2D:
    """
    A junction / tap point on the 2D formboard.

    Attributes
    ----------
    branch_id   : Unique identifier for this branch point.
    position_mm : 2D position (x, y) in mm on the formboard.
    cumulative_length_mm
                : Cumulative path length from the root connector to this
                  branch point along the main trunk (or branch path).
    label       : Human-readable label (e.g. ``"BP-1"``).
    node_id     : Corresponding node id in the source harness graph.
    """
    branch_id: int
    position_mm: tuple[float, float]
    cumulative_length_mm: float
    label: str
    node_id: str


@dataclass
class Wire2D:
    """
    A single wire or cable on the formboard.

    Attributes
    ----------
    wire_id      : Identifier matching the source harness wire list.
    source_connector
                 : Connector id at the source end.
    dest_connector
                 : Connector id at the destination end.
    gauge_awg    : AWG gauge, or None if specified via diameter_mm.
    diameter_mm  : Conductor diameter in mm.
    length_mm    : Total routed length of this wire (preserved from 3D).
    label        : Display label (defaults to wire_id).
    color        : Optional insulation colour code (e.g. ``"RD"``, ``"BK"``).
    """
    wire_id: str
    source_connector: str
    dest_connector: str
    gauge_awg: int | None
    diameter_mm: float
    length_mm: float
    label: str
    color: str = ""


@dataclass
class Annotation:
    """
    A text annotation on the 2D formboard.

    Used for connector pinouts, branch tap labels, wire number call-outs, etc.

    Attributes
    ----------
    kind     : ``"connector_pinout"`` | ``"branch_tap"`` | ``"wire_label"``.
    ref      : Reference id (connector id, branch point id, wire id).
    position_mm
             : Suggested placement position (x, y) in mm.
    text     : Annotation text content.
    """
    kind: str
    ref: str
    position_mm: tuple[float, float]
    text: str


@dataclass
class Formboard2D:
    """
    2D manufacturing formboard for a 3D wiring harness.

    Attributes
    ----------
    branches     : All branch/junction points on the formboard.
    wires        : Wire table — one entry per logical wire.
    annotations  : Connector pinouts, branch labels, wire call-outs.
    bbox         : Bounding box ``(min_x, min_y, max_x, max_y)`` in mm.
    trunk_path_mm
                 : Ordered list of (x, y) positions along the main trunk.
    total_wire_length_mm
                 : Sum of all wire lengths (board-level stat).
    """
    branches: list[BranchPoint2D]
    wires: list[Wire2D]
    annotations: list[Annotation]
    bbox: tuple[float, float, float, float]
    trunk_path_mm: list[tuple[float, float]]
    total_wire_length_mm: float


# ---------------------------------------------------------------------------
# AWG lookup (mirrors harness3d.py; no circular import needed)
# ---------------------------------------------------------------------------

_AWG_DIAMETER_MM: dict[int, float] = {
    0: 8.252, 1: 7.348, 2: 6.544, 3: 5.827, 4: 5.189, 5: 4.621,
    6: 4.115, 7: 3.665, 8: 3.264, 9: 2.906, 10: 2.588, 11: 2.305,
    12: 2.053, 13: 1.828, 14: 1.628, 15: 1.450, 16: 1.291, 17: 1.150,
    18: 1.024, 19: 0.912, 20: 0.812, 21: 0.723, 22: 0.644, 23: 0.573,
    24: 0.511, 25: 0.455, 26: 0.405, 27: 0.361, 28: 0.321, 29: 0.286,
    30: 0.255, 31: 0.227, 32: 0.202, 33: 0.180, 34: 0.160, 35: 0.143,
    36: 0.127, 37: 0.113, 38: 0.101, 39: 0.090, 40: 0.080,
}
_DEFAULT_AWG = 20


# ---------------------------------------------------------------------------
# Harness graph parsing
# ---------------------------------------------------------------------------

def _parse_harness(harness_3d: dict) -> tuple[
    dict[str, list[str]],   # adjacency: node_id → [neighbour node_id, ...]
    dict[tuple[str, str], dict],  # edge data: (n1, n2) → segment dict
    str,  # root node_id
]:
    """
    Parse the harness_3d dict into an adjacency graph.

    Expected harness_3d keys
    ------------------------
    ``nodes`` (list of dicts)
        Each node must have a ``"id"`` key (str).  Optional: ``"connector"``
        (connector id string), ``"label"``.

    ``segments`` (list of dicts)
        Each segment must have:
          - ``"from"``     : source node id
          - ``"to"``       : destination node id
          - ``"length_mm"`` : arc-length of this segment (float)
          - ``"wires"``    : list of wire dicts (same schema as harness3d)

        Optional per segment:
          - ``"waypoints"`` : list of 3D waypoints (ignored for formboard)

    ``root`` (str, optional)
        Node id of the root connector.  Defaults to the first node.

    ``connectors`` (dict, optional)
        ``{connector_id: {"pins": [...], "label": "..."}}``.
    """
    nodes_raw: list[dict] = harness_3d.get("nodes", [])
    segments_raw: list[dict] = harness_3d.get("segments", [])

    if not nodes_raw:
        raise FormboardError("harness_3d must contain at least one node")
    if not segments_raw:
        raise FormboardError("harness_3d must contain at least one segment")

    node_ids = {n["id"] for n in nodes_raw}
    for n in nodes_raw:
        if "id" not in n:
            raise FormboardError(f"node missing 'id' key: {n!r}")

    adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}
    edge_data: dict[tuple[str, str], dict] = {}

    for seg in segments_raw:
        src = seg.get("from")
        dst = seg.get("to")
        if src is None or dst is None:
            raise FormboardError(
                f"segment missing 'from' or 'to': {seg!r}"
            )
        if src not in node_ids:
            raise FormboardError(
                f"segment 'from' node '{src}' not in nodes list"
            )
        if dst not in node_ids:
            raise FormboardError(
                f"segment 'to' node '{dst}' not in nodes list"
            )
        if "length_mm" not in seg:
            raise FormboardError(
                f"segment {src!r}→{dst!r} missing 'length_mm'"
            )
        length = float(seg["length_mm"])
        if length < 0:
            raise FormboardError(
                f"segment {src!r}→{dst!r} has negative length_mm={length}"
            )

        adjacency[src].append(dst)
        adjacency[dst].append(src)
        key = (min(src, dst), max(src, dst))
        if key in edge_data:
            raise FormboardError(
                f"duplicate segment between '{src}' and '{dst}'"
            )
        edge_data[key] = dict(seg)

    root = harness_3d.get("root", nodes_raw[0]["id"])
    if root not in node_ids:
        raise FormboardError(f"root node '{root}' not in nodes list")

    return adjacency, edge_data, root


def _detect_cycle(
    adjacency: dict[str, list[str]],
    root: str,
) -> None:
    """
    Raise :class:`FormboardError` if the graph contains a cycle.

    Uses iterative DFS.  Disconnected nodes (reachable or not) are tolerated.
    """
    visited: set[str] = set()
    # stack entries: (current_node, parent_node_or_None)
    stack: list[tuple[str, str | None]] = [(root, None)]
    while stack:
        node, parent = stack.pop()
        if node in visited:
            raise FormboardError(
                f"cycle detected in harness graph at node '{node}'; "
                "formboard-flatten requires a tree (no loops)"
            )
        visited.add(node)
        for neighbour in adjacency[node]:
            if neighbour != parent:
                stack.append((neighbour, node))


def _edge_key(a: str, b: str) -> tuple[str, str]:
    return (min(a, b), max(a, b))


def _segment_length(
    edge_data: dict[tuple[str, str], dict],
    a: str,
    b: str,
) -> float:
    return float(edge_data[_edge_key(a, b)]["length_mm"])


# ---------------------------------------------------------------------------
# Main trunk selection (longest path from root)
# ---------------------------------------------------------------------------

def _longest_path_from(
    root: str,
    adjacency: dict[str, list[str]],
    edge_data: dict[tuple[str, str], dict],
    exclude_node: str | None = None,
) -> list[str]:
    """
    Return the ordered list of node ids along the longest simple path from root.

    Parameters
    ----------
    root         : Starting node.
    adjacency    : Adjacency list for the graph.
    edge_data    : Edge data keyed by (min_id, max_id).
    exclude_node : If given, this node is never entered (used to compute subtree
                   paths that must not cross back through the tap node).

    Implemented as iterative DFS keeping cumulative lengths.
    """
    best_length = -1.0
    best_path: list[str] = [root]

    # stack: (current_node, path_so_far, cumulative_length)
    stack: list[tuple[str, list[str], float]] = [(root, [root], 0.0)]
    while stack:
        node, path, cum_len = stack.pop()
        is_leaf = True
        for neighbour in adjacency[node]:
            if neighbour in path:
                continue
            if neighbour == exclude_node:
                continue
            is_leaf = False
            new_len = cum_len + _segment_length(edge_data, node, neighbour)
            stack.append((neighbour, path + [neighbour], new_len))
        if is_leaf and cum_len > best_length:
            best_length = cum_len
            best_path = path

    return best_path


# ---------------------------------------------------------------------------
# 2D layout engine
# ---------------------------------------------------------------------------

_BRANCH_GAP_MM = 5.0   # vertical gap between sibling stubs at the same tap


def _emit_node_bp(
    node_id: str,
    pos: tuple[float, float],
    cum: float,
    all_nodes: dict[str, dict],
    connectors: dict[str, dict],
    branch_points: list[BranchPoint2D],
    annotations: list[Annotation],
    _bp_counter: list[int],
) -> None:
    """Emit a BranchPoint2D and optional connector pinout annotation for node_id."""
    _bp_counter[0] += 1
    bp = BranchPoint2D(
        branch_id=_bp_counter[0],
        position_mm=pos,
        cumulative_length_mm=cum,
        label=f"BP-{_bp_counter[0]}",
        node_id=node_id,
    )
    branch_points.append(bp)

    node_dict = all_nodes.get(node_id, {})
    conn_id = node_dict.get("connector")
    if conn_id:
        conn_info = connectors.get(conn_id, {})
        pins = conn_info.get("pins", [])
        pin_text = ", ".join(str(p) for p in pins) if pins else "—"
        label_str = conn_info.get("label", conn_id)
        annotations.append(Annotation(
            kind="connector_pinout",
            ref=conn_id,
            position_mm=(pos[0], pos[1] + 8.0),
            text=f"{label_str}: [{pin_text}]",
        ))


def _layout_branch(
    parent_node: str,
    branch_root_pos: tuple[float, float],
    direction: tuple[float, float],   # unit vector for this branch
    branch_start_cum: float,
    sub_path: list[str],              # [tap_node, branch_node, ..., tip]
    adjacency: dict[str, list[str]],
    edge_data: dict[tuple[str, str], dict],
    node_positions: dict[str, tuple[float, float]],
    branch_points: list[BranchPoint2D],
    all_nodes: dict[str, dict],
    _bp_counter: list[int],
    visited_edges: set[tuple[str, str]],
    annotations: list[Annotation],
    connectors: dict[str, dict],
    *,
    depth: int = 0,
) -> None:
    """
    Recursively place a branch (sub-path) on the 2D formboard.

    Parameters
    ----------
    parent_node         : The node at which this branch taps off.
    branch_root_pos     : 2D position of the tap point (position of sub_path[0]).
    direction           : Unit vector (dx, dy) for this branch's primary axis.
    branch_start_cum    : Cumulative length at the tap point.
    sub_path            : Ordered list of node ids for this branch, starting with
                          the tap node (sub_path[0]) and extending to the tip.
                          The first edge (sub_path[0]→sub_path[1]) has already
                          been marked in visited_edges by the caller.
    ...
    depth               : Recursion depth (for alternating Y directions).
    """
    # sub_path[0] is the tap node (already positioned by the caller).  We emit
    # a BranchPoint2D for it here so that every branch traversal is self-contained
    # — both the tap AND all subsequent waypoints appear in this branch's portion
    # of the branches list.  This closes the "simple two-node stub" gap where
    # previously only the tip was emitted.
    if not sub_path or len(sub_path) < 2:
        return

    tap_node = sub_path[0]
    _emit_node_bp(
        tap_node, branch_root_pos, branch_start_cum,
        all_nodes, connectors,
        branch_points, annotations, _bp_counter,
    )

    dx, dy = direction
    cum = branch_start_cum
    prev_pos = branch_root_pos
    prev_node = tap_node

    for i in range(1, len(sub_path)):
        curr_node = sub_path[i]
        ek = _edge_key(prev_node, curr_node)

        # The caller pre-marks the first edge; subsequent edges are marked here.
        if i > 1:
            if ek in visited_edges:
                break
            visited_edges.add(ek)

        seg_len = _segment_length(edge_data, prev_node, curr_node)
        cum += seg_len
        curr_pos = (
            prev_pos[0] + dx * seg_len,
            prev_pos[1] + dy * seg_len,
        )
        node_positions[curr_node] = curr_pos

        # Always emit a branch point for every node on a stub/branch path
        _emit_node_bp(
            curr_node, curr_pos, cum,
            all_nodes, connectors,
            branch_points, annotations, _bp_counter,
        )

        prev_pos = curr_pos
        prev_node = curr_node

    # Enumerate side branches from the branch nodes only (sub_path[1:]).
    # sub_path[0] is the tap node, which is already handled by the parent call's
    # _attach_side_branches; including it here would process it twice.
    _attach_side_branches(
        trunk_path=sub_path[1:],
        node_positions=node_positions,
        adjacency=adjacency,
        edge_data=edge_data,
        branch_points=branch_points,
        all_nodes=all_nodes,
        _bp_counter=_bp_counter,
        visited_edges=visited_edges,
        annotations=annotations,
        connectors=connectors,
        parent_direction=direction,
        depth=depth + 1,
    )


def _attach_side_branches(
    trunk_path: list[str],
    node_positions: dict[str, tuple[float, float]],
    adjacency: dict[str, list[str]],
    edge_data: dict[tuple[str, str], dict],
    branch_points: list[BranchPoint2D],
    all_nodes: dict[str, dict],
    _bp_counter: list[int],
    visited_edges: set[tuple[str, str]],
    annotations: list[Annotation],
    connectors: dict[str, dict],
    parent_direction: tuple[float, float],
    depth: int,
) -> None:
    """
    At each node of trunk_path, collect unvisited neighbour edges and lay out
    sub-branches.  Branches alternate above/below the parent axis.
    """
    # Perpendicular directions: rotate parent_direction 90°
    pdx, pdy = parent_direction
    perp_up = (-pdy, pdx)    # rotate +90°
    perp_down = (pdy, -pdx)  # rotate −90°

    for tap_node in trunk_path:
        # Collect unvisited neighbours not already in the visited set
        side_branches: list[tuple[float, str]] = []
        for nb in adjacency[tap_node]:
            ek = _edge_key(tap_node, nb)
            if ek in visited_edges:
                continue
            # Compute subtree length rooted at nb (excluding tap_node)
            subtree_len = _subtree_length(nb, tap_node, adjacency, edge_data)
            side_branches.append((subtree_len, nb))

        # Sort descending by subtree length
        side_branches.sort(key=lambda x: x[0], reverse=True)

        tap_pos = node_positions.get(tap_node)
        if tap_pos is None:
            continue

        cum_at_tap = 0.0
        for bp in branch_points:
            if bp.node_id == tap_node:
                cum_at_tap = bp.cumulative_length_mm
                break

        for idx, (stub_len, nb) in enumerate(side_branches):
            ek = _edge_key(tap_node, nb)
            if ek in visited_edges:
                continue
            # Alternate above / below
            direction = perp_up if idx % 2 == 0 else perp_down
            # Apply gap offset for siblings at the same tap
            offset_factor = (idx // 2) * _BRANCH_GAP_MM
            offset = (direction[0] * offset_factor, direction[1] * offset_factor)
            adjusted_tap = (tap_pos[0] + offset[0], tap_pos[1] + offset[1])

            # Build sub-path using longest-first DFS from nb, excluding tap_node
            # so the path doesn't traverse back through the trunk.
            sub_path = _longest_path_from(nb, adjacency, edge_data, exclude_node=tap_node)
            # sub_path starts at nb; prepend tap_node to form the branch list
            if sub_path[0] != nb:
                sub_path = [nb] + sub_path
            full_branch = [tap_node] + sub_path

            visited_edges.add(ek)
            node_positions[nb] = adjusted_tap

            _layout_branch(
                parent_node=tap_node,
                branch_root_pos=adjusted_tap,
                direction=direction,
                branch_start_cum=cum_at_tap,
                sub_path=full_branch,
                adjacency=adjacency,
                edge_data=edge_data,
                node_positions=node_positions,
                branch_points=branch_points,
                all_nodes=all_nodes,
                _bp_counter=_bp_counter,
                visited_edges=visited_edges,
                annotations=annotations,
                connectors=connectors,
                depth=depth,
            )


def _subtree_length(
    node: str,
    parent: str,
    adjacency: dict[str, list[str]],
    edge_data: dict[tuple[str, str], dict],
) -> float:
    """Return total arc-length of the subtree rooted at node (excluding parent)."""
    total = 0.0
    stack: list[tuple[str, str]] = [(node, parent)]
    while stack:
        cur, par = stack.pop()
        for nb in adjacency[cur]:
            if nb == par:
                continue
            total += _segment_length(edge_data, cur, nb)
            stack.append((nb, cur))
    return total


# ---------------------------------------------------------------------------
# Wire table assembly
# ---------------------------------------------------------------------------

def _build_wire_table(
    harness_3d: dict,
    adjacency: dict[str, list[str]],
    edge_data: dict[tuple[str, str], dict],
    all_nodes: dict[str, dict],
) -> list[Wire2D]:
    """
    Build the wire table from harness_3d["segments"][*]["wires"].

    Each wire entry spans a segment; source/dest connector are the segment's
    from/to nodes' connector ids (or node ids if no connector is specified).
    """
    wires: list[Wire2D] = []
    wire_counter = 0

    for seg in harness_3d.get("segments", []):
        src_node = seg.get("from", "")
        dst_node = seg.get("to", "")
        seg_length = float(seg.get("length_mm", 0.0))

        src_connector = all_nodes.get(src_node, {}).get("connector", src_node)
        dst_connector = all_nodes.get(dst_node, {}).get("connector", dst_node)

        for wire_dict in seg.get("wires", []):
            wire_counter += 1
            wire_id = wire_dict.get("name") or wire_dict.get("id") or f"W{wire_counter:03d}"
            color = wire_dict.get("color", "")
            label = wire_dict.get("label", wire_id)

            gauge_awg: int | None = None
            if "gauge_awg" in wire_dict:
                gauge_awg = int(wire_dict["gauge_awg"])

            if "diameter_mm" in wire_dict:
                diameter_mm = float(wire_dict["diameter_mm"])
            elif gauge_awg is not None and gauge_awg in _AWG_DIAMETER_MM:
                diameter_mm = _AWG_DIAMETER_MM[gauge_awg]
            else:
                gauge_awg = _DEFAULT_AWG
                diameter_mm = _AWG_DIAMETER_MM[_DEFAULT_AWG]

            wires.append(Wire2D(
                wire_id=wire_id,
                source_connector=src_connector,
                dest_connector=dst_connector,
                gauge_awg=gauge_awg,
                diameter_mm=diameter_mm,
                length_mm=seg_length,
                label=label,
                color=color,
            ))

    return wires


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def formboard_flatten(harness_3d: dict[str, Any]) -> Formboard2D:
    """
    Flatten a 3D wiring harness into a 2D manufacturing formboard.

    Parameters
    ----------
    harness_3d :
        Dict describing the harness graph.  Required keys:

        ``nodes`` : list of dicts, each with ``"id"`` (str).
            Optional: ``"connector"`` (str), ``"label"`` (str).
        ``segments`` : list of dicts, each with:
            ``"from"`` (str), ``"to"`` (str), ``"length_mm"`` (float),
            ``"wires"`` (list of wire dicts — same schema as harness3d).
            Optional: ``"waypoints"`` (list of [x,y,z]).
        ``root`` (str, optional) : root node id (default: first node).
        ``connectors`` (dict, optional) :
            ``{connector_id: {"pins": [...], "label": "..."}}``

    Returns
    -------
    Formboard2D
        2D formboard with branch points, wire table, annotations, and bounding
        box.

    Raises
    ------
    FormboardError
        If the harness graph contains a cycle, disconnected segment, missing
        required key, or other structural inconsistency.
    """
    # 1. Parse graph
    adjacency, edge_data, root = _parse_harness(harness_3d)

    # 2. Reject cycles
    _detect_cycle(adjacency, root)

    # 3. Build node lookup
    all_nodes: dict[str, dict] = {
        n["id"]: n for n in harness_3d.get("nodes", [])
    }
    connectors: dict[str, dict] = harness_3d.get("connectors", {})

    # 4. Find main trunk (longest path from root)
    trunk_path = _longest_path_from(root, adjacency, edge_data)

    # 5. Lay out trunk horizontally along +X axis
    node_positions: dict[str, tuple[float, float]] = {}
    branch_points: list[BranchPoint2D] = []
    annotations: list[Annotation] = []
    visited_edges: set[tuple[str, str]] = set()
    _bp_counter = [0]

    # Place root
    node_positions[root] = (0.0, 0.0)

    # Emit root branch-point
    _emit_node_bp(
        root, (0.0, 0.0), 0.0,
        all_nodes, connectors,
        branch_points, annotations, _bp_counter,
    )

    # Walk trunk segments — lay out horizontally along +X
    cum = 0.0
    prev_node = trunk_path[0]
    for i in range(1, len(trunk_path)):
        curr_node = trunk_path[i]
        ek = _edge_key(prev_node, curr_node)
        visited_edges.add(ek)
        seg_len = _segment_length(edge_data, prev_node, curr_node)
        cum += seg_len
        curr_pos = (cum, 0.0)
        node_positions[curr_node] = curr_pos

        _emit_node_bp(
            curr_node, curr_pos, cum,
            all_nodes, connectors,
            branch_points, annotations, _bp_counter,
        )

        prev_node = curr_node

    # 6. Attach side branches
    _attach_side_branches(
        trunk_path=trunk_path,
        node_positions=node_positions,
        adjacency=adjacency,
        edge_data=edge_data,
        branch_points=branch_points,
        all_nodes=all_nodes,
        _bp_counter=_bp_counter,
        visited_edges=visited_edges,
        annotations=annotations,
        connectors=connectors,
        parent_direction=(1.0, 0.0),
        depth=0,
    )

    # 7. Build trunk path
    trunk_path_mm: list[tuple[float, float]] = []
    for nid in trunk_path:
        pos = node_positions.get(nid)
        if pos is not None:
            trunk_path_mm.append(pos)

    # 8. Build wire table
    wires = _build_wire_table(harness_3d, adjacency, edge_data, all_nodes)

    # 9. Add branch-tap annotations
    for bp in branch_points:
        annotations.append(Annotation(
            kind="branch_tap",
            ref=bp.label,
            position_mm=(bp.position_mm[0], bp.position_mm[1] - 6.0),
            text=f"{bp.label} @{bp.cumulative_length_mm:.1f}mm",
        ))

    # 10. Compute bounding box
    all_positions = list(node_positions.values())
    if not all_positions:
        bbox = (0.0, 0.0, 0.0, 0.0)
    else:
        xs = [p[0] for p in all_positions]
        ys = [p[1] for p in all_positions]
        bbox = (min(xs), min(ys), max(xs), max(ys))

    # 11. Total wire length
    total_wire_length_mm = sum(w.length_mm for w in wires)

    return Formboard2D(
        branches=branch_points,
        wires=wires,
        annotations=annotations,
        bbox=bbox,
        trunk_path_mm=trunk_path_mm,
        total_wire_length_mm=total_wire_length_mm,
    )


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def formboard_to_dict(fb: Formboard2D) -> dict:
    """Serialise a Formboard2D to a plain dict suitable for json.dumps."""
    return {
        "branches": [
            {
                "branch_id": bp.branch_id,
                "position_mm": list(bp.position_mm),
                "cumulative_length_mm": bp.cumulative_length_mm,
                "label": bp.label,
                "node_id": bp.node_id,
            }
            for bp in fb.branches
        ],
        "wires": [
            {
                "wire_id": w.wire_id,
                "source_connector": w.source_connector,
                "dest_connector": w.dest_connector,
                "gauge_awg": w.gauge_awg,
                "diameter_mm": w.diameter_mm,
                "length_mm": w.length_mm,
                "label": w.label,
                "color": w.color,
            }
            for w in fb.wires
        ],
        "annotations": [
            {
                "kind": a.kind,
                "ref": a.ref,
                "position_mm": list(a.position_mm),
                "text": a.text,
            }
            for a in fb.annotations
        ],
        "bbox": list(fb.bbox),
        "trunk_path_mm": [list(p) for p in fb.trunk_path_mm],
        "total_wire_length_mm": fb.total_wire_length_mm,
    }
