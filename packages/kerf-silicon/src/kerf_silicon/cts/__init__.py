"""kerf_silicon.cts — Clock-Tree Synthesis (CTS) seed.

Entry point::

    from kerf_silicon.cts import build_clock_tree, ClockTreeResult
    from kerf_silicon.liberty import parse_file

    lib = parse_file("buffers.lib")
    result = build_clock_tree(
        sinks=sinks,           # list of ClockSink
        library=lib,
        skew_bound_ps=50.0,
    )
    print(result.max_skew_ps)
    for buf in result.buffers:
        print(buf.instance_name, buf.x, buf.y, buf.cell_name)

Modules
-------
htree          Recursive midpoint-split H-tree topology builder.
buffer_sizing  Liberty-driven buffer-cell selection per tree segment.
skew_report    Per-sink arrival-time computation + skew report.
"""

from kerf_silicon.cts.htree import (
    ClockSink,
    HTreeNode,
    build_htree,
)
from kerf_silicon.cts.buffer_sizing import (
    BufferInstance,
    size_buffers,
)
from kerf_silicon.cts.skew_report import (
    SinkArrival,
    SkewReport,
    compute_skew,
)

from dataclasses import dataclass, field
from typing import Optional
import pathlib

from kerf_silicon.liberty.ast import LibertyLibrary


@dataclass
class ClockTreeResult:
    """Output of :func:`build_clock_tree`.

    Attributes
    ----------
    tree:
        Root :class:`HTreeNode` of the built H-tree topology.
    buffers:
        Ordered list of inserted :class:`BufferInstance` objects
        (one per branching node).
    skew_report:
        Per-sink arrival times + overall max-skew summary.
    max_skew_ps:
        Convenience shortcut — maximum skew in picoseconds.
    violations:
        List of violation strings (empty = clean; non-empty = check failed).
    """

    tree: HTreeNode
    buffers: list[BufferInstance]
    skew_report: SkewReport
    max_skew_ps: float
    violations: list[str] = field(default_factory=list)


def build_clock_tree(
    sinks: list[ClockSink],
    library: LibertyLibrary,
    skew_bound_ps: float = 50.0,
    *,
    wire_cap_per_um_ff: float = 0.2,
    wire_res_per_um_ohm: float = 0.05,
) -> ClockTreeResult:
    """Build a buffered H-tree clock network for *sinks*.

    Parameters
    ----------
    sinks:
        Clock-sink descriptors (register instances with known placement
        coordinates and input capacitance).
    library:
        Parsed Liberty library containing candidate buffer cells.
        The function looks for cells whose names contain ``clkbuf`` or
        ``buf``; any cell with an output pin that has a ``cell_rise``
        timing arc is eligible.
    skew_bound_ps:
        Target maximum skew between any two sinks, in picoseconds.
        Violations are recorded in :attr:`ClockTreeResult.violations`
        when the skew exceeds this bound.
    wire_cap_per_um_ff:
        Wire capacitance per micron in femtofarads (default 0.2 fF/µm,
        typical for SKY130 M2).
    wire_res_per_um_ohm:
        Wire resistance per micron in ohms (default 0.05 Ω/µm).

    Returns
    -------
    ClockTreeResult
    """
    if len(sinks) < 1:
        raise ValueError("build_clock_tree: need at least 1 sink")

    # 1. Build the H-tree topology (branching nodes + wire segments).
    tree = build_htree(sinks)

    # 2. Size buffers at each branching node using Liberty timing data.
    buffers, violations = size_buffers(
        tree,
        library,
        wire_cap_per_um_ff=wire_cap_per_um_ff,
        wire_res_per_um_ohm=wire_res_per_um_ohm,
    )

    # 3. Compute per-sink arrival times and skew.
    skew_report = compute_skew(
        tree,
        buffers,
        wire_cap_per_um_ff=wire_cap_per_um_ff,
        wire_res_per_um_ohm=wire_res_per_um_ohm,
    )

    max_skew = skew_report.max_skew_ps

    # 4. Check skew bound.
    if max_skew > skew_bound_ps:
        violations.append(
            f"violation: skew {max_skew:.1f} ps exceeds bound {skew_bound_ps:.1f} ps"
        )

    return ClockTreeResult(
        tree=tree,
        buffers=buffers,
        skew_report=skew_report,
        max_skew_ps=max_skew,
        violations=violations,
    )


__all__ = [
    # Top-level API
    "build_clock_tree",
    "ClockTreeResult",
    # H-tree types
    "ClockSink",
    "HTreeNode",
    "build_htree",
    # Buffer types
    "BufferInstance",
    "size_buffers",
    # Skew types
    "SinkArrival",
    "SkewReport",
    "compute_skew",
]
