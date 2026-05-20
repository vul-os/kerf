"""GK-20: validate_body opt-in self-intersection check.

Tests that:
  * The flag defaults to False (no behaviour change for existing callers).
  * All standard primitives (box, cylinder, sphere, tetra, torus) pass
    ``check_self_intersection=True``.
  * A hand-crafted self-intersecting shell is detected when the flag is on.
  * The return shape is always ``{"ok": bool, "errors": list}``.
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    Coedge,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    Body,
    Vertex,
    make_box,
    make_cylinder,
    make_sphere,
    make_tetra,
    make_torus,
    validate_body,
)


# ---------------------------------------------------------------------------
# Helpers: build a self-intersecting body
# ---------------------------------------------------------------------------

def _make_self_intersecting_body() -> Body:
    """Build a two-face open shell whose faces geometrically cross each other.

    The two faces are completely non-adjacent (share no edges or vertices)
    so the structural checks all pass for the open shell.  Their planes
    mutually straddle each other's sample points, triggering the SI check.

    Face A: a flat square in the XY-plane (z = 0), spanning x=[0,2], y=[0,2].
    Face B: a flat square in the XZ-plane (y = 1), spanning x=[0,2], z=[-1,3].

    Face B's centroid is at (1, 1, 1) which has z=1>0, so it is *above* face
    A's plane.  Face A's centroid is at (1, 1, 0) which has y=1=y_B's plane,
    meaning Face A straddles Face B's plane because half of Face A is on each
    side (y goes from 0 to 2 while Face B's plane is y=1).

    Actually to make straddling clear for both: let Face B's plane be y=1, and
    Face A has vertices at y=0 and y=2, so Face A's points straddle y=1.
    Face B has vertices at z=-1 and z=3, so Face B's points straddle z=0
    (Face A's plane z=0).  Both straddle → intersection.

    Uses separate vertices/edges so Euler-Poincaré holds for an open shell:
    V=8, E=8, F=2, L=2, H=0, S=1, G=0 → 8-8+2-0-2(1-0)=0 ✓
    """
    # Face A vertices: square in z=0 plane, y from 0 to 2
    a0 = np.array([0.0, 0.0, 0.0])
    a1 = np.array([2.0, 0.0, 0.0])
    a2 = np.array([2.0, 2.0, 0.0])
    a3 = np.array([0.0, 2.0, 0.0])

    va0, va1, va2, va3 = (Vertex(p, 1e-7) for p in (a0, a1, a2, a3))

    ea0 = Edge(Line3(a0, a1), 0.0, 1.0, va0, va1, 1e-7)
    ea1 = Edge(Line3(a1, a2), 0.0, 1.0, va1, va2, 1e-7)
    ea2 = Edge(Line3(a2, a3), 0.0, 1.0, va2, va3, 1e-7)
    ea3 = Edge(Line3(a3, a0), 0.0, 1.0, va3, va0, 1e-7)

    plane_a = Plane(a0, a1 - a0, a3 - a0)
    loop_a  = Loop([
        Coedge(ea0, True), Coedge(ea1, True),
        Coedge(ea2, True), Coedge(ea3, True),
    ], is_outer=True)
    face_a = Face(plane_a, [loop_a], orientation=True, tol=1e-7)

    # Face B vertices: square in y=1 plane, z from -1 to 3 (straddles z=0)
    b0 = np.array([0.0, 1.0, -1.0])
    b1 = np.array([2.0, 1.0, -1.0])
    b2 = np.array([2.0, 1.0,  3.0])
    b3 = np.array([0.0, 1.0,  3.0])

    vb0, vb1, vb2, vb3 = (Vertex(p, 1e-7) for p in (b0, b1, b2, b3))

    eb0 = Edge(Line3(b0, b1), 0.0, 1.0, vb0, vb1, 1e-7)
    eb1 = Edge(Line3(b1, b2), 0.0, 1.0, vb1, vb2, 1e-7)
    eb2 = Edge(Line3(b2, b3), 0.0, 1.0, vb2, vb3, 1e-7)
    eb3 = Edge(Line3(b3, b0), 0.0, 1.0, vb3, vb0, 1e-7)

    plane_b = Plane(b0, b1 - b0, b3 - b0)
    loop_b  = Loop([
        Coedge(eb0, True), Coedge(eb1, True),
        Coedge(eb2, True), Coedge(eb3, True),
    ], is_outer=True)
    face_b = Face(plane_b, [loop_b], orientation=True, tol=1e-7)

    shell = Shell([face_a, face_b], is_closed=False)
    solid = Solid([shell])
    return Body(solids=[solid])


# ---------------------------------------------------------------------------
# Tests: flag defaults to False
# ---------------------------------------------------------------------------

def test_validate_body_default_flag_is_false():
    """Default call must not raise and must not run SI check."""
    body = make_box()
    res = validate_body(body)
    assert set(res.keys()) == {"ok", "errors"}
    assert res["ok"] is True


def test_validate_body_explicit_false_unchanged():
    """Explicit False is identical to omitting the flag."""
    body = make_box()
    res_default = validate_body(body)
    res_explicit = validate_body(body, check_self_intersection=False)
    assert res_default == res_explicit


# ---------------------------------------------------------------------------
# Tests: all standard primitives stay clean with flag on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body_factory,name", [
    (make_box,      "box"),
    (make_cylinder, "cylinder"),
    (make_sphere,   "sphere"),
    (make_tetra,    "tetra"),
    (make_torus,    "torus"),
])
def test_validate_body_primitive_ok_with_si_flag(body_factory, name):
    body = body_factory()
    res = validate_body(body, check_self_intersection=True)
    assert res["ok"] is True, (
        f"{name}: unexpected errors with SI check: {res['errors']}"
    )


# ---------------------------------------------------------------------------
# Tests: self-intersecting shell is detected
# ---------------------------------------------------------------------------

def test_self_intersecting_body_detected_when_flag_on():
    """A known self-intersecting shell must produce at least one error."""
    body = _make_self_intersecting_body()
    res = validate_body(body, check_self_intersection=True)
    assert res["ok"] is False
    assert any("self-intersection" in e for e in res["errors"]), res["errors"]


def test_self_intersecting_body_clean_when_flag_off():
    """The same shell must pass structural checks (flag off = no SI check)."""
    body = _make_self_intersecting_body()
    res = validate_body(body, check_self_intersection=False)
    # structural checks (Euler, loop, manifold) pass for this open shell
    assert res["ok"] is True, res["errors"]


# ---------------------------------------------------------------------------
# Tests: return shape contract is preserved
# ---------------------------------------------------------------------------

def test_return_shape_flag_on():
    body = make_box()
    res = validate_body(body, check_self_intersection=True)
    assert isinstance(res, dict)
    assert set(res.keys()) == {"ok", "errors"}
    assert isinstance(res["ok"], bool)
    assert isinstance(res["errors"], list)


def test_return_shape_si_body_flag_on():
    body = _make_self_intersecting_body()
    res = validate_body(body, check_self_intersection=True)
    assert isinstance(res, dict)
    assert set(res.keys()) == {"ok", "errors"}
    assert isinstance(res["ok"], bool)
    assert isinstance(res["errors"], list)


# ---------------------------------------------------------------------------
# Tests: two-box scenario (same-shell edge-edge and face-face)
# ---------------------------------------------------------------------------

def _make_crossing_edge_body() -> Body:
    """Two non-adjacent edges that cross, in a valid open two-face shell.

    Face A: triangle (0,0,0)-(1,1,0)-(0,2,0)  — diagonal goes (0,0,0)->(1,1,0)
    Face B: triangle (1,0,0)-(0,1,0)-(1,2,0)  — diagonal goes (1,0,0)->(0,1,0)

    The two diagonals cross at (0.5, 0.5, 0).  The faces share no edges or
    vertices, so they are non-adjacent.

    Topology: V=6, E=6, F=2, L=2, H=0, S=1 (open) →
    6-6+2-0-2(1-0) = 0 ✓
    """
    # Face A vertices
    pa0 = np.array([0.0, 0.0, 0.0])
    pa1 = np.array([1.0, 1.0, 0.0])
    pa2 = np.array([0.0, 2.0, 0.0])
    va0, va1, va2 = Vertex(pa0, 1e-7), Vertex(pa1, 1e-7), Vertex(pa2, 1e-7)
    ea0 = Edge(Line3(pa0, pa1), 0.0, 1.0, va0, va1, 1e-7)  # the crossing diagonal
    ea1 = Edge(Line3(pa1, pa2), 0.0, 1.0, va1, va2, 1e-7)
    ea2 = Edge(Line3(pa2, pa0), 0.0, 1.0, va2, va0, 1e-7)
    plane_a = Plane(pa0, pa1 - pa0, pa2 - pa0)
    loop_a = Loop([Coedge(ea0, True), Coedge(ea1, True), Coedge(ea2, True)],
                  is_outer=True)
    face_a = Face(plane_a, [loop_a], orientation=True, tol=1e-7)

    # Face B vertices
    pb0 = np.array([1.0, 0.0, 0.0])
    pb1 = np.array([0.0, 1.0, 0.0])
    pb2 = np.array([1.0, 2.0, 0.0])
    vb0, vb1, vb2 = Vertex(pb0, 1e-7), Vertex(pb1, 1e-7), Vertex(pb2, 1e-7)
    eb0 = Edge(Line3(pb0, pb1), 0.0, 1.0, vb0, vb1, 1e-7)  # the crossing diagonal
    eb1 = Edge(Line3(pb1, pb2), 0.0, 1.0, vb1, vb2, 1e-7)
    eb2 = Edge(Line3(pb2, pb0), 0.0, 1.0, vb2, vb0, 1e-7)
    plane_b = Plane(pb0, pb1 - pb0, pb2 - pb0)
    loop_b = Loop([Coedge(eb0, True), Coedge(eb1, True), Coedge(eb2, True)],
                  is_outer=True)
    face_b = Face(plane_b, [loop_b], orientation=True, tol=1e-7)

    shell = Shell([face_a, face_b], is_closed=False)
    return Body(solids=[Solid([shell])])


def test_crossing_edges_detected():
    body = _make_crossing_edge_body()
    res = validate_body(body, check_self_intersection=True)
    assert res["ok"] is False
    assert any("self-intersection" in e for e in res["errors"]), res["errors"]


def test_crossing_edges_clean_when_flag_off():
    """Structural checks pass for the crossing-edge body (flag off)."""
    body = _make_crossing_edge_body()
    res = validate_body(body, check_self_intersection=False)
    assert res["ok"] is True, res["errors"]
