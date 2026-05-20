"""
bridge_loops.py
===============
GK-74: Bridge two open boundary edge loops with a quad strip.

This module provides a pure-Python, hermetic implementation of the classic
"bridge" operation used in both SubD cage authoring and B-rep topology:

    * Connect two open boundary loops of **equal** vertex count with a
      strip of N quads (one per vertex pair).
    * Auto-match starting vertex by closest-vertex distance.
    * Detect and correct loop orientation twist so the quad strip does not
      self-intersect.

Public API
----------
BridgeResult(dataclass)
    vertices  — list of all [x, y, z] positions (loop_a + loop_b vertices).
    faces     — list of quad faces [[i0, i1, i2, i3], ...], len == N.
    loop_a_indices — int indices into `vertices` for the first loop.
    loop_b_indices — int indices into `vertices` for the second loop.

bridge_loops(loop_a, loop_b) -> BridgeResult
    Connect two open boundary loops.  Each loop is a list of N 3-D points
    (list[list[float]] or compatible sequence).  Returns a BridgeResult
    containing *only* the bridge quad strip — callers integrate into their
    mesh as needed.

Euler formula check (V − E + F = 0 for a quad strip disk topology):
    V = 2N, E = 3N (N bottom + N top + N side), F = N  → 2N − 3N + N = 0. ✓

All errors raise ``ValueError`` with a descriptive message.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple


# ---------------------------------------------------------------------------
# Data type helpers
# ---------------------------------------------------------------------------

Point3 = List[float]


def _vec(a: Point3, b: Point3) -> Point3:
    return [b[0] - a[0], b[1] - a[1], b[2] - a[2]]


def _dist_sq(a: Point3, b: Point3) -> float:
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    return dx * dx + dy * dy + dz * dz


def _centroid(pts: List[Point3]) -> Point3:
    n = len(pts)
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    cz = sum(p[2] for p in pts) / n
    return [cx, cy, cz]


def _loop_normal(pts: List[Point3]) -> Point3:
    """Approximate loop normal via Newell's method (numerically stable polygon normal)."""
    nx = ny = nz = 0.0
    n = len(pts)
    for i in range(n):
        cur = pts[i]
        nxt = pts[(i + 1) % n]
        nx += (cur[1] - nxt[1]) * (cur[2] + nxt[2])
        ny += (cur[2] - nxt[2]) * (cur[0] + nxt[0])
        nz += (cur[0] - nxt[0]) * (cur[1] + nxt[1])
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-12:
        return [0.0, 0.0, 1.0]
    return [nx / length, ny / length, nz / length]


def _dot(a: Point3, b: Point3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class BridgeResult:
    """Output of ``bridge_loops``.

    Attributes
    ----------
    vertices : list of [x, y, z]
        All vertex positions. loop_a comes first (indices 0..N-1), loop_b
        follows (indices N..2N-1).
    faces : list of [i0, i1, i2, i3]
        N quad faces forming the bridge strip.  Each quad is wound
        consistently (outward normal away from the strip interior).
    loop_a_indices : list[int]
        Indices into ``vertices`` for loop_a after rotation to best start.
    loop_b_indices : list[int]
        Indices into ``vertices`` for loop_b after rotation to best start.
    """

    vertices: List[Point3] = field(default_factory=list)
    faces: List[List[int]] = field(default_factory=list)
    loop_a_indices: List[int] = field(default_factory=list)
    loop_b_indices: List[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def _rotate(lst: list, k: int) -> list:
    """Rotate list left by k positions."""
    if not lst:
        return lst
    k = k % len(lst)
    return lst[k:] + lst[:k]


def _find_best_start(loop_a: List[Point3], loop_b: List[Point3]) -> int:
    """Return the index in loop_b closest to loop_a[0]."""
    anchor = loop_a[0]
    best_idx = 0
    best_dsq = _dist_sq(anchor, loop_b[0])
    for i in range(1, len(loop_b)):
        dsq = _dist_sq(anchor, loop_b[i])
        if dsq < best_dsq:
            best_dsq = dsq
            best_idx = i
    return best_idx


def _needs_reverse(loop_a: List[Point3], loop_b: List[Point3]) -> bool:
    """Return True if loop_b should be reversed to avoid a twisted bridge.

    Strategy: project the bridge vector (centroid_a → centroid_b) and check
    that the winding of loop_b matches loop_a when viewed along this axis.
    Specifically, compare normal directions: if both normals point "outward"
    (away from each other) the loops are compatibly wound; if they point in
    the same direction one of them needs to be reversed.
    """
    n_a = _loop_normal(loop_a)
    n_b = _loop_normal(loop_b)
    # For two coaxial open loops that face each other, their normals should be
    # anti-parallel (dot < 0).  If dot > 0 they wind the same way when viewed
    # from outside → reverse loop_b so quads don't twist.
    return _dot(n_a, n_b) > 0.0


def bridge_loops(
    loop_a: Sequence[Sequence[float]],
    loop_b: Sequence[Sequence[float]],
) -> BridgeResult:
    """Connect two open boundary loops with a quad strip.

    Parameters
    ----------
    loop_a, loop_b : sequence of N 3-D points
        Each loop is an ordered sequence of vertices describing one open
        boundary.  The loops must have the **same** vertex count N ≥ 3.

    Returns
    -------
    BridgeResult
        Contains the combined vertex list and N quad faces.

    Raises
    ------
    ValueError
        If the loops are empty, have different vertex counts, or N < 3.

    Notes
    -----
    Euler formula for a quad-strip disk (open manifold patch):
        V = 2N, E = 3N (N bottom + N top + N side), F = N → V − E + F = 0.
    """
    a: List[Point3] = [[float(c) for c in p] for p in loop_a]
    b: List[Point3] = [[float(c) for c in p] for p in loop_b]

    if len(a) == 0 or len(b) == 0:
        raise ValueError("bridge_loops: loops must not be empty")
    if len(a) != len(b):
        raise ValueError(
            f"bridge_loops: loops must have equal vertex count "
            f"(got {len(a)} vs {len(b)})"
        )
    n = len(a)
    if n < 3:
        raise ValueError(
            f"bridge_loops: loops must have at least 3 vertices (got {n})"
        )

    # 1. Auto-match: rotate loop_b so its closest vertex aligns with loop_a[0].
    start_b = _find_best_start(a, b)
    b = _rotate(b, start_b)

    # 2. Twist correction: reverse loop_b if needed.
    if _needs_reverse(a, b):
        b = b[::-1]

    # 3. Build combined vertex list.
    vertices: List[Point3] = a + b
    a_idx = list(range(n))           # 0 .. N-1
    b_idx = list(range(n, 2 * n))    # N .. 2N-1

    # 4. Build quad faces.
    #    Face i: (a[i], a[(i+1)%N], b[(i+1)%N], b[i])
    #    Winding: counter-clockwise when viewed from outside (normal points away).
    faces: List[List[int]] = []
    for i in range(n):
        i_next = (i + 1) % n
        faces.append([
            a_idx[i],
            a_idx[i_next],
            b_idx[i_next],
            b_idx[i],
        ])

    return BridgeResult(
        vertices=vertices,
        faces=faces,
        loop_a_indices=a_idx,
        loop_b_indices=b_idx,
    )
