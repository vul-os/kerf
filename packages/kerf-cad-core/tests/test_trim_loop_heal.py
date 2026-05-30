"""Tests for geom/trim_loop_heal.py — four analytic-oracle validations.

Oracle contract (from the GK-P spec):
  1. T-junction merge  : two near-coincident vertices → merged; tjunctions_merged=1
  2. Dead-loop removal : inner loop with 2 vertices → removed; deadloops_removed=1
  3. Orientation flip  : CW outer with area=-2.0 → reversed; signed area=+2.0
  4. Self-intersection : figure-8 outer → self_intersections >= 1; loop unchanged
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.trim_loop_heal import (
    HealedTrimLoops,
    TrimmedFace,
    _signed_area,
    heal_trim_loops,
)

UV = Tuple[float, float]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _rect_loop(x0: float, y0: float, x1: float, y1: float) -> List[UV]:
    """Return a CCW rectangular UV loop."""
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# ---------------------------------------------------------------------------
# Oracle 1: T-junction merge
# ---------------------------------------------------------------------------


def test_tjunction_merge_snaps_near_vertex():
    """Two vertices within tol are merged; stat reports tjunctions_merged >= 1."""
    tol = 1e-6
    # Outer square with one vertex displaced by 1e-7 (inside tol)
    outer: List[UV] = [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
    ]
    # Inner loop that nearly shares a vertex with outer at (0.5, 0.3)
    # One vertex at (0.5 + 1e-7, 0.3) — should be merged to (0.5, 0.3) representative
    inner: List[UV] = [
        (0.5 + 1e-7, 0.3),
        (0.7, 0.3),
        (0.7, 0.5),
        (0.5, 0.5),
    ]
    # Inject the "true" partner in the outer — not actually needed for the merge
    # test since the merge operates across all loops.  We instead use two
    # close vertices in the inner loop itself.
    inner_with_dup: List[UV] = [
        (0.5 + 1e-7, 0.3),  # close to (0.5, 0.3)
        (0.5, 0.3),          # the "true" position
        (0.7, 0.5),
        (0.5, 0.5),
    ]
    face = TrimmedFace(outer=outer, inners=[inner_with_dup])
    result = heal_trim_loops(face, tol=tol)

    assert isinstance(result, HealedTrimLoops)
    assert result.stats["tjunctions_merged"] >= 1, (
        f"expected >= 1 T-junction merge, got {result.stats['tjunctions_merged']}"
    )

    # The two close inner vertices should now be at the same position
    # (within tol of each other after merging)
    merged_inner = result.inners[0] if result.inners else []
    # Find the two vertices that were originally close
    positions_near_05_03 = [
        (u, v) for (u, v) in merged_inner
        if math.hypot(u - 0.5, v - 0.3) < 1e-3
    ]
    # After merge, they should be coincident within tol
    if len(positions_near_05_03) >= 2:
        u0, v0 = positions_near_05_03[0]
        u1, v1 = positions_near_05_03[1]
        assert math.hypot(u0 - u1, v0 - v1) < tol * 2, (
            f"merged vertices should coincide within tol; "
            f"distance = {math.hypot(u0 - u1, v0 - v1)}"
        )


def test_tjunction_merge_two_vertices_cross_loops():
    """Vertex at (0.5+1e-7, 0.3) in inner and (0.5, 0.3) in outer → merged; stat=1."""
    tol = 1e-6
    # Outer has a vertex at exactly (0.5, 0.3)
    outer: List[UV] = [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.5, 0.3),   # ← exact vertex
        (0.0, 1.0),
    ]
    # Inner has a vertex at (0.5 + 1e-7, 0.3) — within tol of outer's vertex
    inner: List[UV] = [
        (0.5 + 1e-7, 0.3),   # ← near-coincident with outer vertex
        (0.7, 0.3),
        (0.7, 0.5),
        (0.5, 0.5),
    ]
    face = TrimmedFace(outer=outer, inners=[inner])
    result = heal_trim_loops(face, tol=tol)

    assert result.stats["tjunctions_merged"] >= 1, (
        f"expected >= 1 T-junction merge across loops; "
        f"got {result.stats['tjunctions_merged']}"
    )

    # At least one vertex in the merged inner loop should now be near (0.5, 0.3)
    # (the representative of the merged cluster).
    merged_inner = result.inners[0]
    near_05_03 = [
        (u, v) for (u, v) in merged_inner
        if math.hypot(u - 0.5, v - 0.3) < 1e-5
    ]
    assert len(near_05_03) >= 1, (
        f"expected at least one merged inner vertex near (0.5, 0.3); "
        f"loop = {merged_inner}"
    )


# ---------------------------------------------------------------------------
# Oracle 2: Dead-loop removal
# ---------------------------------------------------------------------------


def test_dead_loop_removal_degenerate_edge():
    """Inner loop with 2 vertices (degenerate) → removed; deadloops_removed=1."""
    outer = _rect_loop(0.0, 0.0, 2.0, 2.0)
    # A "loop" with only 2 unique vertices is degenerate (an edge, not a polygon)
    degenerate_inner: List[UV] = [(0.5, 0.5), (0.8, 0.8)]
    face = TrimmedFace(outer=outer, inners=[degenerate_inner])

    result = heal_trim_loops(face, tol=1e-6)

    assert result.stats["deadloops_removed"] == 1, (
        f"expected deadloops_removed=1; got {result.stats['deadloops_removed']}"
    )
    assert len(result.inners) == 0, (
        f"expected 0 surviving inner loops; got {len(result.inners)}"
    )
    # Outer loop should be intact
    assert len(result.outer) == 4, "outer loop should remain unchanged"


def test_dead_loop_removal_zero_area():
    """Inner loop with area < tol² → removed; deadloops_removed=1."""
    tol = 1e-6
    outer = _rect_loop(0.0, 0.0, 2.0, 2.0)
    # Tiny triangle with area much less than tol²
    tiny: List[UV] = [(0.5, 0.5), (0.5 + 1e-10, 0.5), (0.5, 0.5 + 1e-10)]
    face = TrimmedFace(outer=outer, inners=[tiny])
    result = heal_trim_loops(face, tol=tol)

    assert result.stats["deadloops_removed"] >= 1, (
        f"expected tiny-area inner loop removed; got {result.stats}"
    )
    assert len(result.inners) == 0, (
        "tiny-area inner loop should have been removed"
    )


def test_dead_loop_removal_outer_unchanged():
    """Outer loop is not affected by inner dead-loop removal."""
    outer = _rect_loop(0.0, 0.0, 3.0, 3.0)
    valid_inner: List[UV] = [(0.5, 0.5), (1.0, 0.5), (1.0, 1.0), (0.5, 1.0)]
    degenerate_inner: List[UV] = [(1.5, 1.5), (1.8, 1.5)]

    face = TrimmedFace(outer=outer, inners=[valid_inner, degenerate_inner])
    result = heal_trim_loops(face, tol=1e-6)

    assert result.stats["deadloops_removed"] == 1
    assert len(result.inners) == 1, "valid inner should survive"
    # Outer must still have 4 vertices
    assert len(result.outer) == 4


# ---------------------------------------------------------------------------
# Oracle 3: Orientation flip
# ---------------------------------------------------------------------------


def test_orientation_fix_cw_outer_becomes_ccw():
    """CW outer with signed area = -2.0 → reversed → signed area = +2.0;
    orientations_fixed=1."""
    # Unit square (CCW) has area = 1.  We scale to get area = ±2.
    # CW square: vertices in clock-wise order
    cw_outer: List[UV] = [
        (0.0, 0.0),
        (0.0, 2.0),   # CW: go up first
        (1.0, 2.0),
        (1.0, 0.0),
    ]
    # Verify it is indeed CW
    area_before = _signed_area(cw_outer)
    assert area_before < 0.0, f"test setup: expected CW (negative area), got {area_before}"

    face = TrimmedFace(outer=cw_outer, inners=[])
    result = heal_trim_loops(face, tol=1e-6)

    area_after = _signed_area(result.outer)
    assert area_after > 0.0, (
        f"after orientation fix, outer should be CCW (positive area); "
        f"got area={area_after}"
    )
    assert abs(area_after - abs(area_before)) < 1e-10, (
        f"area magnitude should be preserved; before={abs(area_before)}, after={area_after}"
    )
    assert result.stats["orientations_fixed"] == 1, (
        f"expected orientations_fixed=1; got {result.stats['orientations_fixed']}"
    )


def test_orientation_fix_ccw_inner_becomes_cw():
    """CCW inner loop → reversed → CW; orientations_fixed=1."""
    outer = _rect_loop(0.0, 0.0, 4.0, 4.0)
    # CCW inner: should be made CW
    ccw_inner: List[UV] = [
        (1.0, 1.0),
        (2.0, 1.0),
        (2.0, 2.0),
        (1.0, 2.0),
    ]
    # Verify it is CCW
    assert _signed_area(ccw_inner) > 0.0

    face = TrimmedFace(outer=outer, inners=[ccw_inner])
    result = heal_trim_loops(face, tol=1e-6)

    assert _signed_area(result.inners[0]) < 0.0, (
        "inner loop should be CW (negative area) after orientation fix"
    )
    assert result.stats["orientations_fixed"] == 1, (
        f"expected orientations_fixed=1; got {result.stats['orientations_fixed']}"
    )


def test_orientation_fix_already_correct_unchanged():
    """Correctly-oriented loops → orientations_fixed=0."""
    outer = _rect_loop(0.0, 0.0, 4.0, 4.0)   # CCW
    # Explicitly CW inner
    cw_inner: List[UV] = [
        (1.0, 1.0),
        (1.0, 2.0),   # CW: go up first
        (2.0, 2.0),
        (2.0, 1.0),
    ]
    assert _signed_area(cw_inner) < 0.0, "test setup: inner must be CW"

    face = TrimmedFace(outer=outer, inners=[cw_inner])
    result = heal_trim_loops(face, tol=1e-6)

    assert result.stats["orientations_fixed"] == 0, (
        f"no orientation fix needed; got {result.stats['orientations_fixed']}"
    )


# ---------------------------------------------------------------------------
# Oracle 4: Self-intersection detection
# ---------------------------------------------------------------------------


def test_self_intersection_figure8_detected():
    """A figure-8 outer loop → self_intersections >= 1; loop returned unchanged."""
    # Figure-8 in UV space: two loops crossing at origin
    # Vertices: (0,0) → (1,1) → (1,-1) → (-1,1) → (-1,-1) → back to (0,0)
    # This creates a crossing at (0, 0).
    figure8: List[UV] = [
        (0.0, 0.0),
        (1.0, 1.0),
        (-1.0, -1.0),   # crosses first segment on return path
        (-1.0, 1.0),
        (1.0, -1.0),
    ]

    face = TrimmedFace(outer=figure8, inners=[])
    result = heal_trim_loops(face, tol=1e-6)

    assert result.stats["self_intersections"] >= 1, (
        f"expected >= 1 self-intersection in figure-8 loop; "
        f"got {result.stats['self_intersections']}"
    )

    # The outer loop should be returned as-is (no auto-fix)
    # Length must match
    assert len(result.outer) == len(figure8), (
        "self-intersecting loop should be returned unchanged (same vertex count)"
    )


def test_self_intersection_clean_loop_zero():
    """A clean convex loop reports self_intersections=0."""
    outer = _rect_loop(0.0, 0.0, 1.0, 1.0)
    face = TrimmedFace(outer=outer, inners=[])
    result = heal_trim_loops(face, tol=1e-6)

    assert result.stats["self_intersections"] == 0, (
        f"clean convex loop should have 0 self-intersections; "
        f"got {result.stats['self_intersections']}"
    )


# ---------------------------------------------------------------------------
# Combined / stats completeness
# ---------------------------------------------------------------------------


def test_stats_keys_always_present():
    """HealedTrimLoops.stats always contains all four keys."""
    outer = _rect_loop(0.0, 0.0, 1.0, 1.0)
    face = TrimmedFace(outer=outer, inners=[])
    result = heal_trim_loops(face, tol=1e-6)

    for key in ("tjunctions_merged", "deadloops_removed",
                "orientations_fixed", "self_intersections"):
        assert key in result.stats, f"missing key: {key}"
        assert isinstance(result.stats[key], int), (
            f"stat '{key}' should be int, got {type(result.stats[key])}"
        )
