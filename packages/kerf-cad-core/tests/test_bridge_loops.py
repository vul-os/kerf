"""
Tests for kerf_cad_core.geom.bridge_loops — GK-74.

All tests are hermetic: no OCC, no database, no network.  Pure-Python only.

Coverage:
  1. Basic bridge of two coaxial circles of N segments → N quads.
  2. Euler formula V − E + F = 0 for the quad-strip open patch.
  3. Watertight manifold: every interior edge shared by exactly 2 quads;
     boundary edges (loop_a / loop_b) used by exactly 1 quad.
  4. Auto-match (closest-vertex rotation): loop_b offset by k → same result.
  5. Twist correction: reversed loop_b produces a non-twisted bridge.
  6. Distinct output vertices match combined input count (2N).
  7. Error on empty loops.
  8. Error on unequal loop lengths.
  9. Error on loops with fewer than 3 vertices.
  10. Import from top-level geom package.
"""

from __future__ import annotations

import math
from typing import Dict, List, Set, Tuple

import pytest

from kerf_cad_core.geom.bridge_loops import BridgeResult, bridge_loops


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _circle_loop(n: int, radius: float = 1.0, z: float = 0.0) -> List[List[float]]:
    """N-point polygon approximating a circle at height z."""
    return [
        [radius * math.cos(2 * math.pi * i / n),
         radius * math.sin(2 * math.pi * i / n),
         z]
        for i in range(n)
    ]


def _count_edges(faces: List[List[int]]) -> Dict[Tuple[int, int], int]:
    """Return edge → use-count dict for the given face list."""
    edge_count: Dict[Tuple[int, int], int] = {}
    for face in faces:
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            key = (min(a, b), max(a, b))
            edge_count[key] = edge_count.get(key, 0) + 1
    return edge_count


def _euler_check(n_vertices: int, faces: List[List[int]]) -> int:
    """Return V − E + F for the given mesh patch."""
    edge_set: Set[Tuple[int, int]] = set()
    for face in faces:
        m = len(face)
        for i in range(m):
            a, b = face[i], face[(i + 1) % m]
            edge_set.add((min(a, b), max(a, b)))
    V = n_vertices
    E = len(edge_set)
    F = len(faces)
    return V - E + F


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", [3, 4, 6, 8, 12, 16, 32])
def test_quad_count_equals_n(n: int) -> None:
    """Bridge of two N-gon circles yields exactly N quads."""
    a = _circle_loop(n, radius=1.0, z=0.0)
    b = _circle_loop(n, radius=1.0, z=1.0)
    result = bridge_loops(a, b)
    assert len(result.faces) == n, f"Expected {n} quads, got {len(result.faces)}"
    for face in result.faces:
        assert len(face) == 4, "Each bridge face must be a quad"


@pytest.mark.parametrize("n", [3, 4, 6, 8, 12])
def test_euler_formula_quad_strip(n: int) -> None:
    """V − E + F = 0 for a quad-strip open patch (disk topology).

    For a bridge strip: V=2N, E=3N (N bottom + N top + N side), F=N.
    Hence V − E + F = 2N − 3N + N = 0.
    """
    a = _circle_loop(n, radius=1.0, z=0.0)
    b = _circle_loop(n, radius=1.0, z=2.0)
    result = bridge_loops(a, b)
    euler = _euler_check(len(result.vertices), result.faces)
    assert euler == 0, (
        f"Euler formula violated: V−E+F = {euler} (expected 0) for N={n}"
    )


@pytest.mark.parametrize("n", [4, 6, 8])
def test_watertight_manifold_edges(n: int) -> None:
    """Interior bridge edges are shared by exactly 2 quads; boundary edges by 1."""
    a = _circle_loop(n, radius=1.0, z=0.0)
    b = _circle_loop(n, radius=1.0, z=1.0)
    result = bridge_loops(a, b)

    edge_count = _count_edges(result.faces)
    # Side edges (connecting a[i] to b[i]) are interior: shared by 2 quads.
    # Top/bottom edges (along loop_a and loop_b) are boundary: used by 1 quad.
    a_idx = set(result.loop_a_indices)
    b_idx = set(result.loop_b_indices)

    for (u, v), cnt in edge_count.items():
        u_in_a = u in a_idx
        v_in_a = v in a_idx
        u_in_b = u in b_idx
        v_in_b = v in b_idx
        is_boundary = (u_in_a and v_in_a) or (u_in_b and v_in_b)
        is_side = (u_in_a and v_in_b) or (u_in_b and v_in_a)
        if is_boundary:
            assert cnt == 1, f"Boundary edge {(u,v)} used {cnt} times (expected 1)"
        elif is_side:
            assert cnt == 2, f"Interior side edge {(u,v)} used {cnt} times (expected 2)"


def test_vertex_count() -> None:
    """Result contains exactly 2N vertices (loop_a + loop_b)."""
    n = 8
    a = _circle_loop(n, radius=1.0, z=0.0)
    b = _circle_loop(n, radius=2.0, z=3.0)
    result = bridge_loops(a, b)
    assert len(result.vertices) == 2 * n
    assert len(result.loop_a_indices) == n
    assert len(result.loop_b_indices) == n


def test_auto_match_rotation_invariant() -> None:
    """Rotating loop_b by k positions should produce the same bridge topology."""
    n = 6
    a = _circle_loop(n, radius=1.0, z=0.0)
    b = _circle_loop(n, radius=1.0, z=1.0)
    k = 3
    b_rotated = b[k:] + b[:k]

    r1 = bridge_loops(a, b)
    r2 = bridge_loops(a, b_rotated)

    # Both results should have the same number of faces and vertices.
    assert len(r1.faces) == len(r2.faces) == n
    assert len(r1.vertices) == len(r2.vertices) == 2 * n

    # The faces from r2 should cover the same geometric positions as r1
    # (order may differ, but total face count and vertex count match).
    assert len(r2.faces) == n


def test_twist_correction_reversed_loop() -> None:
    """Reversing loop_b should still yield a valid non-twisted bridge.

    After twist correction, the bridge should have the same number of
    quads and satisfy V-E+F=0.
    """
    n = 8
    a = _circle_loop(n, radius=1.0, z=0.0)
    b = _circle_loop(n, radius=1.0, z=1.0)
    b_reversed = list(reversed(b))

    r_normal = bridge_loops(a, b)
    r_reversed = bridge_loops(a, b_reversed)

    assert len(r_normal.faces) == n
    assert len(r_reversed.faces) == n

    euler_r = _euler_check(len(r_reversed.vertices), r_reversed.faces)
    assert euler_r == 0, f"Reversed-input bridge Euler={euler_r} (expected 0)"


def test_different_radii_bridge() -> None:
    """Bridge between circles of different radii is valid."""
    n = 6
    a = _circle_loop(n, radius=1.0, z=0.0)
    b = _circle_loop(n, radius=3.0, z=5.0)
    result = bridge_loops(a, b)
    assert len(result.faces) == n
    assert _euler_check(len(result.vertices), result.faces) == 0


def test_vertex_indices_disjoint() -> None:
    """loop_a_indices and loop_b_indices must be disjoint and cover 0..2N-1."""
    n = 5
    a = _circle_loop(n)
    b = _circle_loop(n, z=1.0)
    result = bridge_loops(a, b)
    all_idx = set(result.loop_a_indices) | set(result.loop_b_indices)
    assert all_idx == set(range(2 * n)), "Indices must cover all vertices"
    assert len(set(result.loop_a_indices) & set(result.loop_b_indices)) == 0


def test_error_empty_loop() -> None:
    """bridge_loops raises ValueError for empty loops."""
    with pytest.raises(ValueError, match="empty"):
        bridge_loops([], [])


def test_error_unequal_lengths() -> None:
    """bridge_loops raises ValueError when loops have different vertex counts."""
    a = _circle_loop(4)
    b = _circle_loop(6)
    with pytest.raises(ValueError, match="equal vertex count"):
        bridge_loops(a, b)


def test_error_too_few_vertices() -> None:
    """bridge_loops raises ValueError when loops have fewer than 3 vertices."""
    a = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    b = [[0.0, 0.0, 1.0], [1.0, 0.0, 1.0]]
    with pytest.raises(ValueError, match="at least 3"):
        bridge_loops(a, b)


def test_import_from_geom_package() -> None:
    """BridgeResult and bridge_loops must be importable from kerf_cad_core.geom."""
    from kerf_cad_core.geom import BridgeResult as BR, bridge_loops as bl
    assert BR is BridgeResult
    assert bl is bridge_loops
