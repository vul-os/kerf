"""
test_gk104_edge_slide.py
========================
Hermetic oracle tests for GK-104: subd_edge_slide.

Oracle: slide a single edge of a box by t along adjacent faces →
  - the two endpoint vertices move by t * edge_length in the face-tangent direction
  - topology (V count, E count, F count) is identical to the input cage
  - non-endpoint vertices are unaffected

No OCC, no DB, no network.
"""

from __future__ import annotations

import math
from typing import List, Set, Tuple

import pytest

from kerf_cad_core.geom.subd_authoring import (
    SubDCage,
    create_subd_primitive,
    subd_edge_slide,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_unique_edges(cage: SubDCage) -> int:
    seen: Set[Tuple[int, int]] = set()
    for face in cage.faces:
        n = len(face)
        for i in range(n):
            a, b = face[i], face[(i + 1) % n]
            seen.add((min(a, b), max(a, b)))
    return len(seen)


def _vec3_sub(a: List[float], b: List[float]) -> List[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _vec3_len(v: List[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _find_vertical_edge(cage: SubDCage) -> int:
    """Return edge_id of a vertical (z-axis) edge of a 2×2×2 box.

    Vertical edges connect bottom (z=-1) to top (z=+1) with same x,y.
    e.g. edge from [-1,-1,-1] to [-1,-1,+1].  These have only side-face
    adjacency.  For a vertical edge, adjacent faces both have tangents
    pointing in y or x directions, so the slide is purely in x/y.
    """
    edges = cage.cage_edges()
    verts = cage.vertices
    for eid, (a, b) in enumerate(edges):
        va, vb = verts[a], verts[b]
        # Same x, same y, different z
        if (abs(va[0] - vb[0]) < 1e-9 and
                abs(va[1] - vb[1]) < 1e-9 and
                abs(abs(va[2] - vb[2]) - 2.0) < 1e-9):
            return eid
    raise AssertionError("No vertical edge found")


def _find_top_rim_edge(cage: SubDCage) -> int:
    """Return the edge_id of an edge on the top rim (z=+1) of a 2×2×2 box."""
    edges = cage.cage_edges()
    verts = cage.vertices
    for eid, (a, b) in enumerate(edges):
        za = verts[a][2]
        zb = verts[b][2]
        if abs(za - 1.0) < 1e-9 and abs(zb - 1.0) < 1e-9:
            return eid
    raise AssertionError("No top-rim edge found")


# ---------------------------------------------------------------------------
# Test 1: t=0 is identity
# ---------------------------------------------------------------------------

def test_edge_slide_identity():
    cage = create_subd_primitive("cube", width=2, height=2, depth=2)
    eid = _find_top_rim_edge(cage)
    result = subd_edge_slide(cage, eid, t=0.0)

    for orig, slid in zip(cage.vertices, result.vertices):
        assert orig == pytest.approx(slid, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 2: topology (V/E/F) unchanged after slide
# ---------------------------------------------------------------------------

def test_edge_slide_topology_unchanged():
    cage = create_subd_primitive("cube", width=2, height=2, depth=2)
    eid = _find_top_rim_edge(cage)

    V_before = cage.num_vertices
    E_before = _count_unique_edges(cage)
    F_before = cage.num_faces

    for t in [0.5, -0.5, 1.0, -1.0, 0.25]:
        result = subd_edge_slide(cage, eid, t=t)
        assert result.num_vertices == V_before, f"V changed at t={t}"
        assert _count_unique_edges(result) == E_before, f"E changed at t={t}"
        assert result.num_faces == F_before, f"F changed at t={t}"


# ---------------------------------------------------------------------------
# Test 3: displacement is proportional to t (linearity)
# ---------------------------------------------------------------------------

def test_edge_slide_displacement_linear_in_t():
    """Oracle: the displacement vector scales linearly with t.

    slide(t=0.5) should give exactly half the displacement of slide(t=1.0).
    """
    cage = create_subd_primitive("cube", width=2, height=2, depth=2)
    eid = _find_top_rim_edge(cage)
    a, b = cage.cage_edges()[eid]

    half = subd_edge_slide(cage, eid, t=0.5)
    full = subd_edge_slide(cage, eid, t=1.0)

    for vi in (a, b):
        orig = cage.vertices[vi]
        disp_half = _vec3_sub(half.vertices[vi], orig)
        disp_full = _vec3_sub(full.vertices[vi], orig)

        # half displacement should be exactly half full displacement
        for j in range(3):
            assert disp_half[j] == pytest.approx(disp_full[j] * 0.5, abs=1e-9), (
                f"Displacement not linear for v{vi} component {j}: "
                f"half={disp_half[j]}, full/2={disp_full[j] * 0.5}"
            )


# ---------------------------------------------------------------------------
# Test 4: displacement magnitude equals t * edge_length
# ---------------------------------------------------------------------------

def test_edge_slide_displacement_magnitude():
    """Oracle: |disp| = |t| * edge_length for both endpoints."""
    cage = create_subd_primitive("cube", width=2, height=2, depth=2)
    eid = _find_top_rim_edge(cage)
    a, b = cage.cage_edges()[eid]

    # Edge length for any cube edge is 2.0
    edge_len = _vec3_len(_vec3_sub(cage.vertices[b], cage.vertices[a]))
    assert edge_len == pytest.approx(2.0, abs=1e-9)

    for t in [0.5, 0.25, 1.0]:
        result = subd_edge_slide(cage, eid, t=t)
        for vi in (a, b):
            orig = cage.vertices[vi]
            disp = _vec3_sub(result.vertices[vi], orig)
            mag = _vec3_len(disp)
            expected = abs(t) * edge_len
            assert mag == pytest.approx(expected, abs=1e-9), (
                f"t={t} v{vi}: |disp|={mag} expected {expected}"
            )


# ---------------------------------------------------------------------------
# Test 5: vertical edge slides in horizontal plane only (pure tangent test)
# ---------------------------------------------------------------------------

def test_edge_slide_vertical_edge_stays_in_x_range():
    """A vertical (z-axis) edge of the box is flanked by two side faces.

    When slid, the endpoints should move in the horizontal plane (the z
    coordinate of each endpoint does NOT change — the tangent is horizontal).
    """
    cage = create_subd_primitive("cube", width=2, height=2, depth=2)
    eid = _find_vertical_edge(cage)
    a, b = cage.cage_edges()[eid]

    for t in [0.5, 1.0, -0.5]:
        result = subd_edge_slide(cage, eid, t=t)
        for vi in (a, b):
            orig = cage.vertices[vi]
            slid = result.vertices[vi]
            # z must be unchanged — the tangent is in the horizontal plane
            assert slid[2] == pytest.approx(orig[2], abs=1e-9), (
                f"z changed for vertical-edge endpoint v{vi} at t={t}: "
                f"{orig[2]} -> {slid[2]}"
            )


# ---------------------------------------------------------------------------
# Test 6: only the two edge endpoints are displaced; others unaffected
# ---------------------------------------------------------------------------

def test_edge_slide_only_endpoints_move():
    """All vertices except the two edge endpoints should remain unchanged."""
    cage = create_subd_primitive("cube", width=2, height=2, depth=2)
    eid = _find_top_rim_edge(cage)
    a, b = cage.cage_edges()[eid]
    moved = {a, b}

    result = subd_edge_slide(cage, eid, t=0.5)

    for vi, (orig, slid) in enumerate(zip(cage.vertices, result.vertices)):
        if vi in moved:
            continue
        assert orig == pytest.approx(slid, abs=1e-9), (
            f"Unexpected displacement of non-endpoint v{vi}: {orig} -> {slid}"
        )


# ---------------------------------------------------------------------------
# Test 7: t=-1 is symmetric to t=+1 (equal magnitude, opposite direction)
# ---------------------------------------------------------------------------

def test_edge_slide_negative_t_symmetric():
    cage = create_subd_primitive("cube", width=2, height=2, depth=2)
    eid = _find_top_rim_edge(cage)
    a, b = cage.cage_edges()[eid]

    pos = subd_edge_slide(cage, eid, t=1.0)
    neg = subd_edge_slide(cage, eid, t=-1.0)

    for vi in (a, b):
        orig = cage.vertices[vi]
        d_pos = _vec3_sub(pos.vertices[vi], orig)
        d_neg = _vec3_sub(neg.vertices[vi], orig)
        mag_pos = _vec3_len(d_pos)
        mag_neg = _vec3_len(d_neg)
        assert abs(mag_pos - mag_neg) < 1e-9, (
            f"|disp| not symmetric: +t gives {mag_pos}, -t gives {mag_neg}"
        )


# ---------------------------------------------------------------------------
# Test 8: never raises on bad input
# ---------------------------------------------------------------------------

def test_edge_slide_never_raises():
    cage = create_subd_primitive("cube")

    # Out-of-range edge id
    result = subd_edge_slide(cage, 9999, t=0.5)
    assert result.num_vertices == cage.num_vertices

    # Negative edge id
    result = subd_edge_slide(cage, -1, t=0.5)
    assert result.num_vertices == cage.num_vertices

    # t=0 is identity
    result = subd_edge_slide(cage, 0, t=0.0)
    assert result.num_vertices == cage.num_vertices


# ---------------------------------------------------------------------------
# Test 9: export available from geom public facade
# ---------------------------------------------------------------------------

def test_geom_init_exports_edge_slide():
    from kerf_cad_core.geom import subd_edge_slide as fn
    assert callable(fn)
