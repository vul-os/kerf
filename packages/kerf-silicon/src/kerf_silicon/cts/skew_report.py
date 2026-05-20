"""skew_report.py — Per-sink arrival time computation and skew report.

Model
-----
Clock propagation delay from the root to each sink is the sum of:

  1. **Buffer delay** at each internal node on the path (ps), as estimated by
     :mod:`buffer_sizing` using Liberty ``cell_rise``/``cell_fall`` tables.
  2. **Wire delay** on each segment from a branching node to the next node
     (ps), modelled as:

         t_wire = 0.5 · R · C   (Elmore delay, lumped RC)

     where R = resistance of the segment (Ω) and C = capacitance of the
     segment (pF), with wire parameters from
     :func:`~kerf_silicon.cts.buffer_sizing.size_buffers`.

Clock skew is the difference between the earliest and latest arrival times
across all sinks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from kerf_silicon.cts.htree import HTreeNode, ClockSink
from kerf_silicon.cts.buffer_sizing import BufferInstance


@dataclass
class SinkArrival:
    """Arrival time at one clock sink.

    Attributes
    ----------
    sink:
        The :class:`~kerf_silicon.cts.htree.ClockSink` this record belongs to.
    arrival_ps:
        Total propagation time from the clock root to this sink's clock pin,
        in picoseconds.
    path:
        Sequence of node x,y coordinates traversed (root → sink), for
        diagnostics.
    """

    sink: ClockSink
    arrival_ps: float
    path: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class SkewReport:
    """Skew summary across all sinks.

    Attributes
    ----------
    arrivals:
        Per-sink :class:`SinkArrival` records.
    max_skew_ps:
        Maximum difference between any two arrival times (ps).
    early_sink:
        Sink with the smallest arrival time.
    late_sink:
        Sink with the largest arrival time.
    """

    arrivals: list[SinkArrival]
    max_skew_ps: float
    early_sink: Optional[ClockSink] = None
    late_sink: Optional[ClockSink] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _seg_wire_delay_ps(
    node: HTreeNode,
    child: HTreeNode,
    wire_cap_per_um_ff: float,
    wire_res_per_um_ohm: float,
) -> float:
    """Elmore delay (ps) for the wire from *node* to *child*."""
    seg_len = math.hypot(child.x - node.x, child.y - node.y)
    wire_cap_pf = seg_len * wire_cap_per_um_ff / 1000.0  # fF → pF
    wire_res_ohm = seg_len * wire_res_per_um_ohm
    # Elmore: t = 0.5 * R * C  (in ps; R in Ω, C in pF → ps = Ω·pF × 1e-3 × 1e12 × 0.5)
    # Ω × pF = 1e-12 s = 1 ps, so t_ps = 0.5 * R_ohm * C_pf * 1000 (to stay in ps with fF units)
    # Actually: R[Ω] * C[pF] gives [Ω·pF] = [s·1e-12] → multiply by 1e12 to get ps:
    # t_ps = 0.5 * R_ohm * C_pf (already gives ps when C is in pF and R in Ω, since Ω·pF = ps)
    elmore_ps = 0.5 * wire_res_ohm * wire_cap_pf
    return elmore_ps


def _traverse(
    node: HTreeNode,
    cumulative_ps: float,
    path: list[tuple[float, float]],
    buf_map: dict[str, BufferInstance],
    wire_cap_per_um_ff: float,
    wire_res_per_um_ohm: float,
    arrivals: list[SinkArrival],
) -> None:
    """DFS traversal accumulating arrival times."""
    current_path = path + [(node.x, node.y)]

    if node.is_leaf:
        assert node.sink is not None
        arrivals.append(
            SinkArrival(
                sink=node.sink,
                arrival_ps=cumulative_ps,
                path=current_path,
            )
        )
        return

    # Add buffer delay at this internal node.
    buf_delay_ps = 0.0
    if node.buffer_instance_name:
        buf = buf_map.get(node.buffer_instance_name)
        if buf:
            buf_delay_ps = buf.delay_ps

    for child in (node.left, node.right):
        if child is None:
            continue
        # Wire delay on this segment.
        wire_ps = _seg_wire_delay_ps(
            node, child, wire_cap_per_um_ff, wire_res_per_um_ohm
        )
        _traverse(
            child,
            cumulative_ps + buf_delay_ps + wire_ps,
            current_path,
            buf_map,
            wire_cap_per_um_ff,
            wire_res_per_um_ohm,
            arrivals,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_skew(
    tree: HTreeNode,
    buffers: list[BufferInstance],
    *,
    wire_cap_per_um_ff: float = 0.2,
    wire_res_per_um_ohm: float = 0.05,
) -> SkewReport:
    """Compute per-sink arrival times and overall clock skew.

    Parameters
    ----------
    tree:
        Root :class:`HTreeNode` (buffers must already be assigned by
        :func:`~kerf_silicon.cts.buffer_sizing.size_buffers`).
    buffers:
        List of :class:`BufferInstance` returned by ``size_buffers``.
    wire_cap_per_um_ff:
        Wire capacitance in fF/µm.
    wire_res_per_um_ohm:
        Wire resistance in Ω/µm.

    Returns
    -------
    SkewReport
    """
    buf_map: dict[str, BufferInstance] = {b.instance_name: b for b in buffers}
    arrivals: list[SinkArrival] = []
    _traverse(tree, 0.0, [], buf_map, wire_cap_per_um_ff, wire_res_per_um_ohm, arrivals)

    if not arrivals:
        return SkewReport(arrivals=[], max_skew_ps=0.0)

    min_arr = min(arrivals, key=lambda a: a.arrival_ps)
    max_arr = max(arrivals, key=lambda a: a.arrival_ps)
    skew = max_arr.arrival_ps - min_arr.arrival_ps

    return SkewReport(
        arrivals=arrivals,
        max_skew_ps=skew,
        early_sink=min_arr.sink,
        late_sink=max_arr.sink,
    )
