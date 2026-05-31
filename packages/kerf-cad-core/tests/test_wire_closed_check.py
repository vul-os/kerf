"""Hermetic tests for wire_closed_check.py -- BREP-WIRE-CLOSED-CHECK.

Validated cases:
  1.  Closed unit square (4 edges in XY): closed=True, planar=True,
      normal ≈ (0, 0, 1), max_endpoint_gap=0, max_oop=0.
  2.  Open wire (3 of 4 square edges): closed=False, max_endpoint_gap > 0.
  3.  3-D zig-zag (non-planar): planar=False, max_out_of_plane > tol.
  4.  Equilateral triangle: closed=True, planar=True.
  5.  Single edge (degenerate wire): closed=False (end ≠ start).
  6.  Two-edge line: no wrap-around closure.
  7.  Closed triangle in XZ plane: normal ≈ (0, 1, 0).
  8.  Closed hexagon: closed=True, planar=True.
  9.  Near-closed wire (gap just above tolerance): closed=False.
  10. Near-closed wire (gap just below tolerance): closed=True.
  11. Tolerance sensitivity: same wire, tight vs. loose tolerance.
  12. All edges on Z=5 plane: planar=True, max_oop ≈ 0.
  13. Edge with identical start+end (degenerate point edge): handled.
  14. Collinear points: degenerate SVD → planar=True.
  15. Empty edges list: ValueError raised.
  16. 3-D tetrahedron outline (non-planar): planar=False.
  17. Square with one vertex lifted: non-planar detected.
  18. Large square (10 m sides): closed=True, planar=True.
  19. Report fields contract: all required attributes present and typed.
  20. edge_id field preserved (doesn't affect result).
  21. num_edges field correct.
  22. Re-export from geom/__init__.py works.
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.geom.wire_closed_check import (
    EdgeSegment,
    WireCheckReport,
    check_wire_closed,
)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _square_xy(side: float = 1.0) -> list[EdgeSegment]:
    """Closed unit square in Z=0 plane (CCW)."""
    v = [
        (0.0, 0.0, 0.0),
        (side, 0.0, 0.0),
        (side, side, 0.0),
        (0.0, side, 0.0),
    ]
    return [
        EdgeSegment(start_xyz=v[0], end_xyz=v[1], edge_id="e0"),
        EdgeSegment(start_xyz=v[1], end_xyz=v[2], edge_id="e1"),
        EdgeSegment(start_xyz=v[2], end_xyz=v[3], edge_id="e2"),
        EdgeSegment(start_xyz=v[3], end_xyz=v[0], edge_id="e3"),  # wrap-around
    ]


def _triangle_xy() -> list[EdgeSegment]:
    """Equilateral triangle in Z=0 plane."""
    v = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.5, math.sqrt(3) / 2.0, 0.0),
    ]
    return [
        EdgeSegment(start_xyz=v[0], end_xyz=v[1]),
        EdgeSegment(start_xyz=v[1], end_xyz=v[2]),
        EdgeSegment(start_xyz=v[2], end_xyz=v[0]),
    ]


def _triangle_xz() -> list[EdgeSegment]:
    """Triangle in Y=0 plane (XZ).  Normal should be ≈ (0, 1, 0)."""
    v = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.5, 0.0, 1.0),
    ]
    return [
        EdgeSegment(start_xyz=v[0], end_xyz=v[1]),
        EdgeSegment(start_xyz=v[1], end_xyz=v[2]),
        EdgeSegment(start_xyz=v[2], end_xyz=v[0]),
    ]


def _zigzag_3d() -> list[EdgeSegment]:
    """Non-planar zig-zag 4-edge loop with wrap-around.

    Vertices: A=(0,0,0) B=(1,0,0) C=(1,1,0.5) D=(0,1,0) back to A.
    C is lifted out of the Z=0 plane → non-planar.
    """
    A = (0.0, 0.0, 0.0)
    B = (1.0, 0.0, 0.0)
    C = (1.0, 1.0, 0.5)   # lifted 0.5 mm above XY plane
    D = (0.0, 1.0, 0.0)
    return [
        EdgeSegment(start_xyz=A, end_xyz=B),
        EdgeSegment(start_xyz=B, end_xyz=C),
        EdgeSegment(start_xyz=C, end_xyz=D),
        EdgeSegment(start_xyz=D, end_xyz=A),
    ]


def _hexagon(r: float = 1.0) -> list[EdgeSegment]:
    """Regular hexagon in Z=0 plane, radius r."""
    verts = [
        (r * math.cos(math.pi / 3 * i), r * math.sin(math.pi / 3 * i), 0.0)
        for i in range(6)
    ]
    edges = []
    for i in range(6):
        edges.append(EdgeSegment(
            start_xyz=verts[i],
            end_xyz=verts[(i + 1) % 6],
        ))
    return edges


# ---------------------------------------------------------------------------
# Test 1: Closed square — closed=True, planar=True, normal=(0,0,1)
# ---------------------------------------------------------------------------

def test_closed_square_is_closed_and_planar():
    edges = _square_xy()
    r = check_wire_closed(edges)
    assert r.closed is True
    assert r.planar is True
    assert r.max_endpoint_gap_mm == pytest.approx(0.0, abs=1e-12)
    assert r.num_edges == 4
    # Normal should be (0, 0, ±1)
    assert r.plane_normal_xyz is not None
    nx, ny, nz = r.plane_normal_xyz
    assert abs(nx) < 1e-9
    assert abs(ny) < 1e-9
    assert abs(abs(nz) - 1.0) < 1e-9


def test_closed_square_out_of_plane_zero():
    edges = _square_xy()
    r = check_wire_closed(edges)
    assert r.max_out_of_plane_deviation_mm == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 2: Open wire (3 of 4 square edges) — closed=False
# ---------------------------------------------------------------------------

def test_open_wire_not_closed():
    edges = _square_xy()[:3]  # drop the last edge (no wrap-around)
    r = check_wire_closed(edges)
    assert r.closed is False
    assert r.max_endpoint_gap_mm > 0.0


def test_open_wire_gap_equals_expected_distance():
    side = 2.0
    edges = _square_xy(side)[:3]
    r = check_wire_closed(edges)
    # last.end=(0,side,0), first.start=(0,0,0) → gap = side
    assert r.max_endpoint_gap_mm == pytest.approx(side, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 3: 3-D zig-zag — planar=False, max_oop > tol
# ---------------------------------------------------------------------------

def test_zigzag_non_planar():
    edges = _zigzag_3d()
    r = check_wire_closed(edges, tolerance_mm=1e-6)
    assert r.planar is False
    assert r.max_out_of_plane_deviation_mm > 1e-6


def test_zigzag_is_closed():
    edges = _zigzag_3d()
    r = check_wire_closed(edges)
    assert r.closed is True


# ---------------------------------------------------------------------------
# Test 4: Equilateral triangle — closed=True, planar=True
# ---------------------------------------------------------------------------

def test_triangle_closed_and_planar():
    edges = _triangle_xy()
    r = check_wire_closed(edges)
    assert r.closed is True
    assert r.planar is True
    assert r.num_edges == 3


# ---------------------------------------------------------------------------
# Test 5: Single edge — closed=False (end ≠ start unless degenerate)
# ---------------------------------------------------------------------------

def test_single_edge_not_closed():
    edges = [EdgeSegment(start_xyz=(0.0, 0.0, 0.0), end_xyz=(1.0, 0.0, 0.0))]
    r = check_wire_closed(edges)
    assert r.closed is False
    assert r.max_endpoint_gap_mm == pytest.approx(1.0, rel=1e-9)


def test_single_degenerate_point_edge_is_closed():
    """A 0-length edge whose start == end forms a trivially closed wire."""
    p = (1.0, 2.0, 3.0)
    edges = [EdgeSegment(start_xyz=p, end_xyz=p)]
    r = check_wire_closed(edges)
    assert r.closed is True
    assert r.max_endpoint_gap_mm == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 6: Two-edge open path
# ---------------------------------------------------------------------------

def test_two_edge_open_path():
    e1 = EdgeSegment((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
    e2 = EdgeSegment((1.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    r = check_wire_closed([e1, e2])
    assert r.closed is False
    assert r.max_endpoint_gap_mm == pytest.approx(2.0, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 7: Triangle in XZ plane — normal ≈ (0, ±1, 0)
# ---------------------------------------------------------------------------

def test_triangle_xz_normal():
    edges = _triangle_xz()
    r = check_wire_closed(edges)
    assert r.closed is True
    assert r.planar is True
    assert r.plane_normal_xyz is not None
    nx, ny, nz = r.plane_normal_xyz
    assert abs(abs(ny) - 1.0) < 1e-9
    assert abs(nx) < 1e-9
    assert abs(nz) < 1e-9


# ---------------------------------------------------------------------------
# Test 8: Closed hexagon — closed=True, planar=True
# ---------------------------------------------------------------------------

def test_hexagon_closed_and_planar():
    edges = _hexagon()
    r = check_wire_closed(edges)
    assert r.closed is True
    assert r.planar is True
    assert r.num_edges == 6


# ---------------------------------------------------------------------------
# Test 9: Near-closed wire (gap just above tolerance) → closed=False
# ---------------------------------------------------------------------------

def test_near_closed_wire_above_tolerance():
    tol = 1e-3
    # Last edge ends 2e-3 away from first.start (above tol)
    edges = [
        EdgeSegment((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        EdgeSegment((1.0, 0.0, 0.0), (0.0 + 2e-3, 0.0, 0.0)),  # gap = 2e-3
    ]
    r = check_wire_closed(edges, tolerance_mm=tol)
    assert r.closed is False


# ---------------------------------------------------------------------------
# Test 10: Near-closed wire (gap just below tolerance) → closed=True
# ---------------------------------------------------------------------------

def test_near_closed_wire_below_tolerance():
    tol = 1e-3
    eps = 5e-4  # below tol
    edges = [
        EdgeSegment((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        EdgeSegment((1.0, 0.0, 0.0), (eps, 0.0, 0.0)),  # gap = eps
    ]
    r = check_wire_closed(edges, tolerance_mm=tol)
    assert r.closed is True


# ---------------------------------------------------------------------------
# Test 11: Tolerance sensitivity
# ---------------------------------------------------------------------------

def test_tolerance_sensitivity():
    # Gap = 0.01 mm
    gap = 0.01
    edges = [
        EdgeSegment((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        EdgeSegment((1.0, 0.0, 0.0), (0.0 + gap, 0.0, 0.0)),
    ]
    # With tight tolerance (1e-6): not closed
    r_tight = check_wire_closed(edges, tolerance_mm=1e-6)
    assert r_tight.closed is False
    # With loose tolerance (1.0): closed
    r_loose = check_wire_closed(edges, tolerance_mm=1.0)
    assert r_loose.closed is True


# ---------------------------------------------------------------------------
# Test 12: All edges on Z=5 plane → planar=True, max_oop ≈ 0
# ---------------------------------------------------------------------------

def test_square_at_z5_planar():
    edges = [
        EdgeSegment((0.0, 0.0, 5.0), (1.0, 0.0, 5.0)),
        EdgeSegment((1.0, 0.0, 5.0), (1.0, 1.0, 5.0)),
        EdgeSegment((1.0, 1.0, 5.0), (0.0, 1.0, 5.0)),
        EdgeSegment((0.0, 1.0, 5.0), (0.0, 0.0, 5.0)),
    ]
    r = check_wire_closed(edges)
    assert r.planar is True
    assert r.max_out_of_plane_deviation_mm == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 13: Collinear points → degenerate SVD handled (planar=True)
# ---------------------------------------------------------------------------

def test_collinear_edges_planar_degenerate():
    """3 collinear edges along the X axis — SVD singular; should not crash."""
    edges = [
        EdgeSegment((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        EdgeSegment((1.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        EdgeSegment((2.0, 0.0, 0.0), (0.0, 0.0, 0.0)),  # closed
    ]
    r = check_wire_closed(edges)
    # Should not raise; planarity is trivially true for collinear
    assert r.closed is True
    assert r.planar is True  # degenerate → trivially planar


# ---------------------------------------------------------------------------
# Test 14: Empty edges list → ValueError
# ---------------------------------------------------------------------------

def test_empty_edges_raises():
    with pytest.raises(ValueError, match="edges list must not be empty"):
        check_wire_closed([])


# ---------------------------------------------------------------------------
# Test 15: 3-D tetrahedron outline (non-planar loop)
# ---------------------------------------------------------------------------

def test_tetrahedron_outline_non_planar():
    """Walk three faces of a regular tetrahedron; non-planar."""
    # Vertices of a regular tetrahedron
    A = (0.0, 0.0, 0.0)
    B = (1.0, 0.0, 0.0)
    C = (0.5, math.sqrt(3) / 2.0, 0.0)
    D = (0.5, math.sqrt(3) / 6.0, math.sqrt(2.0 / 3.0))
    # Closed loop: A→B→D→C→A  (visits both planar and raised vertices)
    edges = [
        EdgeSegment(A, B),
        EdgeSegment(B, D),
        EdgeSegment(D, C),
        EdgeSegment(C, A),
    ]
    r = check_wire_closed(edges)
    assert r.closed is True
    assert r.planar is False
    assert r.max_out_of_plane_deviation_mm > 1e-6


# ---------------------------------------------------------------------------
# Test 16: Square with one vertex lifted → non-planar detected
# ---------------------------------------------------------------------------

def test_square_one_vertex_lifted():
    lift = 1.0  # 1 mm above plane
    edges = [
        EdgeSegment((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        EdgeSegment((1.0, 0.0, 0.0), (1.0, 1.0, lift)),  # lifted vertex
        EdgeSegment((1.0, 1.0, lift), (0.0, 1.0, 0.0)),
        EdgeSegment((0.0, 1.0, 0.0), (0.0, 0.0, 0.0)),
    ]
    r = check_wire_closed(edges)
    assert r.closed is True
    assert r.planar is False
    assert r.max_out_of_plane_deviation_mm > 0.1


# ---------------------------------------------------------------------------
# Test 17: Large square (10 000 mm sides) → still closed and planar
# ---------------------------------------------------------------------------

def test_large_square():
    edges = _square_xy(side=10_000.0)
    r = check_wire_closed(edges)
    assert r.closed is True
    assert r.planar is True
    assert r.max_endpoint_gap_mm == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 18: WireCheckReport fields contract
# ---------------------------------------------------------------------------

def test_report_fields_present():
    r = check_wire_closed(_square_xy())
    assert isinstance(r.closed, bool)
    assert isinstance(r.planar, bool)
    assert isinstance(r.max_endpoint_gap_mm, float)
    assert isinstance(r.num_edges, int)
    # plane_normal_xyz is either None or a 3-tuple
    if r.plane_normal_xyz is not None:
        assert len(r.plane_normal_xyz) == 3
        assert all(isinstance(v, float) for v in r.plane_normal_xyz)
    assert isinstance(r.max_out_of_plane_deviation_mm, float)
    assert isinstance(r.honest_caveat, str)
    assert "order-dependent" in r.honest_caveat.lower() or "order" in r.honest_caveat.lower()


# ---------------------------------------------------------------------------
# Test 19: edge_id field preserved (doesn't affect result)
# ---------------------------------------------------------------------------

def test_edge_id_does_not_affect_result():
    edges_with_ids = _square_xy()
    edges_no_ids = [
        EdgeSegment(e.start_xyz, e.end_xyz)  # edge_id="" by default
        for e in edges_with_ids
    ]
    r1 = check_wire_closed(edges_with_ids)
    r2 = check_wire_closed(edges_no_ids)
    assert r1.closed == r2.closed
    assert r1.planar == r2.planar
    assert r1.max_endpoint_gap_mm == pytest.approx(r2.max_endpoint_gap_mm)


# ---------------------------------------------------------------------------
# Test 20: num_edges field correct
# ---------------------------------------------------------------------------

def test_num_edges_matches_input():
    for n in [1, 3, 4, 6, 12]:
        # Use a triangle that fans out to n edges (not all closed)
        edges = [
            EdgeSegment(
                start_xyz=(float(i), 0.0, 0.0),
                end_xyz=(float(i + 1), 0.0, 0.0),
            )
            for i in range(n)
        ]
        r = check_wire_closed(edges)
        assert r.num_edges == n


# ---------------------------------------------------------------------------
# Test 21: Normal direction sign convention (doesn't matter; magnitude=1)
# ---------------------------------------------------------------------------

def test_normal_unit_vector():
    r = check_wire_closed(_square_xy())
    assert r.plane_normal_xyz is not None
    mag = math.sqrt(sum(v ** 2 for v in r.plane_normal_xyz))
    assert mag == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Test 22: Re-export from geom/__init__.py works
# ---------------------------------------------------------------------------

def test_reexport_from_geom_init():
    from kerf_cad_core.geom import EdgeSegment as ES, WireCheckReport as WCR, check_wire_closed as ccw
    edges = [ES(start_xyz=(0.0, 0.0, 0.0), end_xyz=(0.0, 0.0, 0.0))]
    r = ccw(edges)
    assert isinstance(r, WCR)
    assert r.closed is True
