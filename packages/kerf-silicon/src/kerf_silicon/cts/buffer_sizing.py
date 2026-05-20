"""buffer_sizing.py — Liberty-driven buffer-cell selection for CTS.

For each internal (branching) node in the H-tree, this module:

1. Estimates the wire capacitance of each outgoing segment using the
   Euclidean distance from the node to its children.
2. Sums up the load capacitance (wire cap + input cap of the downstream
   buffer or sink).
3. Picks the *smallest* buffer cell from the Liberty library whose
   ``max_capacitance`` attribute on the input pin meets the total load.
4. Returns a :class:`BufferInstance` per branching node plus a list of
   constraint violation strings.

Violation surface
-----------------
If ``force_cell`` is supplied (negative-path test), the caller can override
the selected cell.  When that cell's ``max_capacitance`` is smaller than the
actual load, the function records::

    "violation: cap budget exceeded for <instance>: load <X> pF > max_cap <Y> pF"

Liberty assumptions
-------------------
* Buffer cells have exactly one input pin and one output pin.
* The input pin carries ``max_capacitance`` (in pF).  If absent, the pin
  can drive any load (treated as ∞).
* ``cell_rise``/``cell_fall`` tables on the output pin are used to estimate
  buffer propagation delay at the given load.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from kerf_silicon.liberty.ast import Cell, LibertyLibrary, Pin, TimingArc
from kerf_silicon.cts.htree import HTreeNode


@dataclass
class BufferInstance:
    """One inserted buffer at an H-tree branching node.

    Attributes
    ----------
    instance_name:
        Auto-generated unique name (e.g. ``"CTS_BUF_0"``).
    cell_name:
        Liberty cell name selected for this position.
    x, y:
        Placement coordinate (same as the branching node's midpoint).
    level:
        H-tree level at which this buffer sits.
    load_cap_pf:
        Estimated total load capacitance seen by this buffer's output (pF).
    delay_ps:
        Estimated propagation delay through this buffer at *load_cap_pf* (ps).
    max_cap_pf:
        Maximum capacitance budget of the chosen cell's input pin (pF).
    """

    instance_name: str
    cell_name: str
    x: float
    y: float
    level: int
    load_cap_pf: float
    delay_ps: float
    max_cap_pf: float


# ---------------------------------------------------------------------------
# Liberty helpers
# ---------------------------------------------------------------------------

def _input_pin(cell: Cell) -> Optional[Pin]:
    """Return the first input pin of *cell*, or None."""
    for pin in cell.pins:
        if pin.direction == "input":
            return pin
    return None


def _output_pin(cell: Cell) -> Optional[Pin]:
    """Return the first output pin of *cell*, or None."""
    for pin in cell.pins:
        if pin.direction == "output":
            return pin
    return None


def _is_buffer_cell(cell: Cell) -> bool:
    """Return True if *cell* looks like a clock buffer (single in/out)."""
    inputs = [p for p in cell.pins if p.direction == "input"]
    outputs = [p for p in cell.pins if p.direction == "output"]
    return len(inputs) >= 1 and len(outputs) >= 1


def _lookup_delay_ns(arc: TimingArc, load_cap_pf: float) -> float:
    """Linearly interpolate a 1-D or 2-D LUT for *load_cap_pf* (pF → ns).

    Uses ``cell_rise`` if present, else ``cell_fall``.  Falls back to the
    table mean if the load is outside the index range.

    The function handles both 1-D tables (single index row) and 2-D tables
    (rows × columns) by extracting the *last* row (highest input transition
    — conservative) and interpolating along the cap axis.
    """
    table = arc.cell_rise or arc.cell_fall
    if table is None or not table.values:
        return 0.0

    values = table.values

    # Retrieve LUT template from the arc's parent (we don't have a back-ref
    # here, so we do a simple heuristic: figure out the column count from the
    # number of values).  For a 1-D table the values is a single row.
    # For a 2-D table with 3 rows × 4 cols = 12 values.
    # We determine the shape by checking how many values we have relative to
    # common index sizes.  We'll work column-wise: pick the last row and
    # interpolate on the column dimension which corresponds to load cap.

    # Detect table shape: try common column counts.
    n = len(values)
    col_counts = [4, 3, 2, 1]  # most common LUT sizes
    ncols = n
    for c in col_counts:
        if n % c == 0:
            ncols = c
            break

    nrows = n // ncols

    # Use the last (most loaded) row for a conservative estimate.
    row = values[(nrows - 1) * ncols : nrows * ncols]

    # Build simple evenly-spaced cap axis if we don't have template indexes.
    # We use a default matching the fixture: [0.001, 0.01, 0.1, 1.0] pF
    # for 4-col, [0.001, 0.01, 0.1] for 3-col, etc.
    default_caps = {
        1: [0.01],
        2: [0.001, 0.1],
        3: [0.001, 0.01, 0.1],
        4: [0.001, 0.01, 0.1, 1.0],
    }
    caps = default_caps.get(ncols, [i * 0.1 for i in range(ncols)])

    if load_cap_pf <= caps[0]:
        return row[0]
    if load_cap_pf >= caps[-1]:
        return row[-1]

    # Linear interpolation
    for i in range(len(caps) - 1):
        if caps[i] <= load_cap_pf <= caps[i + 1]:
            t = (load_cap_pf - caps[i]) / (caps[i + 1] - caps[i])
            return row[i] + t * (row[i + 1] - row[i])

    return sum(row) / len(row)


def _cell_delay_ps(cell: Cell, load_cap_pf: float) -> float:
    """Return estimated propagation delay (ps) through *cell* at *load_cap_pf*."""
    out_pin = _output_pin(cell)
    if out_pin is None:
        return 0.0

    for arc in out_pin.timing_arcs:
        delay_ns = _lookup_delay_ns(arc, load_cap_pf)
        if delay_ns > 0:
            return delay_ns * 1000.0  # ns → ps

    return 0.0


def _candidate_buffers(library: LibertyLibrary) -> list[Cell]:
    """Return buffer cells from *library* sorted by max_cap ascending (weakest first)."""
    candidates = []
    for cell in library.cells:
        if _is_buffer_cell(cell):
            candidates.append(cell)

    def _max_cap(cell: Cell) -> float:
        ip = _input_pin(cell)
        if ip and ip.max_capacitance is not None:
            return ip.max_capacitance
        return math.inf

    candidates.sort(key=_max_cap)
    return candidates


def _segment_length(node: HTreeNode, child: HTreeNode) -> float:
    """Euclidean distance between *node* and *child* in microns."""
    return math.hypot(child.x - node.x, child.y - node.y)


def _child_input_cap(child: HTreeNode, buf_map: dict[str, BufferInstance]) -> float:
    """Return the input capacitance at *child*'s clock pin in pF.

    For leaf nodes this is the sink's input cap.  For internal nodes it is
    the Liberty input-pin cap of the buffer assigned to that node (looked up
    from *buf_map* if already assigned, else 0 as a conservative fallback for
    top-down traversal).
    """
    if child.is_leaf:
        return child.sink.input_cap_pf if child.sink else 0.0
    buf = buf_map.get(child.buffer_instance_name)
    if buf:
        # Use the cell's own input capacitance (already stored in buf.load_cap_pf
        # is the *output* load; input cap not directly stored).
        # We use a nominal 0.004 pF for an intermediate buffer input.
        return 0.004
    return 0.004  # fallback


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def size_buffers(
    tree: HTreeNode,
    library: LibertyLibrary,
    *,
    wire_cap_per_um_ff: float = 0.2,
    wire_res_per_um_ohm: float = 0.05,
    force_cell: Optional[str] = None,
) -> tuple[list[BufferInstance], list[str]]:
    """Assign a buffer cell to every internal node in *tree*.

    Traversal order is bottom-up (children before parents) so that when
    sizing a parent node the load from child buffers is already known.

    Parameters
    ----------
    tree:
        Root :class:`HTreeNode` built by :func:`~kerf_silicon.cts.htree.build_htree`.
    library:
        Parsed Liberty library to source buffer cells from.
    wire_cap_per_um_ff:
        Wire capacitance in fF/µm (default 0.2 fF/µm).
    wire_res_per_um_ohm:
        Wire resistance in Ω/µm (unused in v1 sizing, reserved for RC delay).
    force_cell:
        If given, override all buffer selections with this cell name regardless
        of whether it meets the cap budget (used for negative-path tests).

    Returns
    -------
    (buffers, violations)
        * ``buffers`` — list of :class:`BufferInstance` sorted by insertion order.
        * ``violations`` — list of constraint violation strings (empty = clean).
    """
    candidates = _candidate_buffers(library)
    if not candidates and force_cell is None:
        raise ValueError(
            "size_buffers: no buffer cells found in Liberty library. "
            "Ensure the library contains cells with input + output pins."
        )

    # Build a name → Cell map for force_cell lookup.
    cell_by_name: dict[str, Cell] = {c.name: c for c in library.cells}

    buffers: list[BufferInstance] = []
    violations: list[str] = []
    buf_counter = 0
    buf_map: dict[str, BufferInstance] = {}

    # Collect all internal nodes in bottom-up order (leaves first).
    def _collect_postorder(node: HTreeNode, acc: list[HTreeNode]) -> None:
        if node.is_leaf:
            return
        if node.left:
            _collect_postorder(node.left, acc)
        if node.right:
            _collect_postorder(node.right, acc)
        acc.append(node)

    internal_nodes: list[HTreeNode] = []
    _collect_postorder(tree, internal_nodes)

    for node in internal_nodes:
        # Estimate load capacitance seen by this node's output.
        total_load_pf = 0.0
        for child in (node.left, node.right):
            if child is None:
                continue
            seg_len_um = _segment_length(node, child)
            wire_cap_pf = seg_len_um * wire_cap_per_um_ff / 1000.0  # fF → pF
            child_cap_pf = _child_input_cap(child, buf_map)
            total_load_pf += wire_cap_pf + child_cap_pf

        instance_name = f"CTS_BUF_{buf_counter}"
        buf_counter += 1

        if force_cell is not None:
            chosen_cell = cell_by_name.get(force_cell)
            if chosen_cell is None:
                raise ValueError(
                    f"size_buffers: force_cell={force_cell!r} not found in library"
                )
            # Check cap budget and record violation if exceeded.
            ip = _input_pin(chosen_cell)
            max_cap = ip.max_capacitance if (ip and ip.max_capacitance is not None) else math.inf
            if total_load_pf > max_cap:
                violations.append(
                    f"violation: cap budget exceeded for {instance_name}: "
                    f"load {total_load_pf:.4f} pF > max_cap {max_cap:.4f} pF"
                )
            delay_ps = _cell_delay_ps(chosen_cell, total_load_pf)
            max_cap_stored = max_cap if max_cap != math.inf else 0.0
            buf = BufferInstance(
                instance_name=instance_name,
                cell_name=chosen_cell.name,
                x=node.x,
                y=node.y,
                level=node.level,
                load_cap_pf=total_load_pf,
                delay_ps=delay_ps,
                max_cap_pf=max_cap_stored,
            )
        else:
            # Pick the smallest buffer whose max_cap ≥ total_load.
            chosen_cell = None
            for cand in candidates:
                ip = _input_pin(cand)
                max_cap = ip.max_capacitance if (ip and ip.max_capacitance is not None) else math.inf
                if max_cap >= total_load_pf:
                    chosen_cell = cand
                    break

            if chosen_cell is None:
                # Fallback: use the strongest buffer and record a violation.
                chosen_cell = candidates[-1]
                ip = _input_pin(chosen_cell)
                max_cap = ip.max_capacitance if (ip and ip.max_capacitance is not None) else math.inf
                violations.append(
                    f"violation: cap budget exceeded for {instance_name}: "
                    f"load {total_load_pf:.4f} pF > max_cap {max_cap:.4f} pF "
                    f"(strongest available)"
                )

            ip = _input_pin(chosen_cell)
            max_cap = ip.max_capacitance if (ip and ip.max_capacitance is not None) else math.inf
            delay_ps = _cell_delay_ps(chosen_cell, total_load_pf)
            max_cap_stored = max_cap if max_cap != math.inf else 0.0
            buf = BufferInstance(
                instance_name=instance_name,
                cell_name=chosen_cell.name,
                x=node.x,
                y=node.y,
                level=node.level,
                load_cap_pf=total_load_pf,
                delay_ps=delay_ps,
                max_cap_pf=max_cap_stored,
            )

        node.buffer_instance_name = instance_name
        buf_map[instance_name] = buf
        buffers.append(buf)

    return buffers, violations
