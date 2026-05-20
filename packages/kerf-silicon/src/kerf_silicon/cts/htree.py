"""htree.py — Recursive midpoint-split H-tree topology builder.

Algorithm
---------
Given a set of clock sinks with (x, y) coordinates, an H-tree is built
by recursively partitioning the sink set into two halves at the midpoint
of the bounding box's longer axis.  A buffer is conceptually placed at
each branching (internal) node.

The leaf nodes hold individual clock sinks.  Internal nodes hold the
branching point coordinate plus references to their left and right
sub-trees.

Complexity
----------
* O(n log n) expected (balanced split at each level).
* Depth = ceil(log2(n)) for a power-of-2 sink count.

Terminology
-----------
* **level** — depth from the root (root = level 0).
* **branching level** — level at which an internal node fans out to two
  children.  The number of *branching levels* equals the tree depth minus
  the leaf level (1 for leaves).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ClockSink:
    """One register (D-flip-flop) clock sink placed on the die.

    Attributes
    ----------
    instance_name:
        Unique cell instance identifier (e.g. ``"FF0"``).
    x, y:
        Placement coordinates of the clock pin in microns.
    input_cap_pf:
        Input capacitance of the clock pin in picofarads.
    cell_name:
        The standard-cell type (informational).
    """

    instance_name: str
    x: float
    y: float
    input_cap_pf: float = 0.002
    cell_name: str = ""


@dataclass
class HTreeNode:
    """One node in the H-tree.

    Leaf nodes have ``left is None and right is None`` and a non-None ``sink``.
    Internal (branching) nodes have ``left`` and ``right`` children and
    ``sink is None``.

    Attributes
    ----------
    x, y:
        Coordinates of this node in microns.  For internal nodes this is the
        midpoint of the bounding box; for leaf nodes it is the sink position.
    level:
        Depth from the root (root = 0).
    sink:
        Populated only for leaf nodes.
    left, right:
        Children of an internal node (both None for leaves).
    buffer_instance_name:
        Name assigned to the inserted buffer at this internal node (set by
        :mod:`buffer_sizing`; empty string until assigned).
    """

    x: float
    y: float
    level: int = 0
    sink: Optional[ClockSink] = None
    left: Optional["HTreeNode"] = None
    right: Optional["HTreeNode"] = None
    buffer_instance_name: str = ""

    @property
    def is_leaf(self) -> bool:
        return self.sink is not None

    @property
    def is_internal(self) -> bool:
        return self.sink is None

    def branches(self) -> list["HTreeNode"]:
        """Return all internal (branching) nodes in DFS pre-order."""
        result: list[HTreeNode] = []
        self._collect_branches(result)
        return result

    def _collect_branches(self, acc: list["HTreeNode"]) -> None:
        if self.is_internal:
            acc.append(self)
            if self.left:
                self.left._collect_branches(acc)
            if self.right:
                self.right._collect_branches(acc)

    def leaves(self) -> list["HTreeNode"]:
        """Return all leaf nodes in DFS left-to-right order."""
        result: list[HTreeNode] = []
        self._collect_leaves(result)
        return result

    def _collect_leaves(self, acc: list["HTreeNode"]) -> None:
        if self.is_leaf:
            acc.append(self)
        else:
            if self.left:
                self.left._collect_leaves(acc)
            if self.right:
                self.right._collect_leaves(acc)

    def depth(self) -> int:
        """Maximum depth (number of levels) of this sub-tree."""
        if self.is_leaf:
            return 0
        ld = self.left.depth() if self.left else 0
        rd = self.right.depth() if self.right else 0
        return 1 + max(ld, rd)

    def branching_levels(self) -> int:
        """Number of levels at which branching occurs (i.e. tree depth)."""
        return self.depth()

    def count_buffers(self) -> int:
        """Count internal nodes (= number of buffers to insert)."""
        return len(self.branches())


def _midpoint(sinks: list[ClockSink]) -> tuple[float, float]:
    """Return the centroid of the bounding box of *sinks*."""
    xs = [s.x for s in sinks]
    ys = [s.y for s in sinks]
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


def _bbox_span(sinks: list[ClockSink]) -> tuple[float, float]:
    """Return (x_span, y_span) of the bounding box of *sinks*."""
    xs = [s.x for s in sinks]
    ys = [s.y for s in sinks]
    return max(xs) - min(xs), max(ys) - min(ys)


def _split(sinks: list[ClockSink]) -> tuple[list[ClockSink], list[ClockSink]]:
    """Partition *sinks* into two halves at the midpoint of the longer axis.

    Uses median split on the longer axis so the split is balanced for
    arbitrary (non power-of-2) sink counts.
    """
    x_span, y_span = _bbox_span(sinks)

    if x_span >= y_span:
        # Split along X axis — sort by x, cut at median
        sorted_sinks = sorted(sinks, key=lambda s: s.x)
    else:
        # Split along Y axis — sort by y, cut at median
        sorted_sinks = sorted(sinks, key=lambda s: s.y)

    mid = len(sorted_sinks) // 2
    return sorted_sinks[:mid], sorted_sinks[mid:]


def _build(sinks: list[ClockSink], level: int) -> HTreeNode:
    """Recursively build an H-tree node for *sinks* at *level*."""
    assert len(sinks) >= 1, "Empty sink list passed to _build"

    # Base case — exactly one sink → leaf node.
    if len(sinks) == 1:
        s = sinks[0]
        return HTreeNode(x=s.x, y=s.y, level=level, sink=s)

    # Internal node at the midpoint of the bounding box.
    mx, my = _midpoint(sinks)
    node = HTreeNode(x=mx, y=my, level=level)

    left_sinks, right_sinks = _split(sinks)
    node.left = _build(left_sinks, level + 1)
    node.right = _build(right_sinks, level + 1)

    return node


def build_htree(sinks: list[ClockSink]) -> HTreeNode:
    """Build a balanced H-tree for *sinks*.

    Parameters
    ----------
    sinks:
        At least one :class:`ClockSink`.  Duplicate positions are allowed
        (degenerate tree).

    Returns
    -------
    HTreeNode
        Root of the H-tree.  For a single sink, returns a leaf node
        directly.

    Raises
    ------
    ValueError
        If *sinks* is empty.
    """
    if not sinks:
        raise ValueError("build_htree: sinks list must not be empty")

    return _build(sinks, level=0)
