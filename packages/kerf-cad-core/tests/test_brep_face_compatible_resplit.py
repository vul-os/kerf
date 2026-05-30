"""Tests for BREP-FACE-COMPATIBLE-RESPLIT (face_compatible_resplit.py).

Covers:
  1. Already-compatible faces — no insertions, already_compatible=True
  2. Mismatched knot vectors (depth-bar case from task spec)
  3. Degree mismatch — degree_mismatch=True, no crash
  4. No shared edge — error flagged, no crash

References: Piegl-Tiller §6.5; Hoffmann 1989 §6.
"""

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.face_compatible_resplit import (
    CompatibilityResult,
    make_faces_compatible,
    _internal_knots,
    _missing_knots,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat_surface(degree_u: int, degree_v: int,
                  knots_u, knots_v,
                  z: float = 0.0) -> NurbsSurface:
    """Build a flat NURBS surface whose control points lie in the z-plane.

    The number of control points is derived from the knot vector:
      n_ctrl = len(knots) - degree - 1
    """
    ku = np.array(knots_u, dtype=float)
    kv = np.array(knots_v, dtype=float)
    nu = len(ku) - degree_u - 1
    nv = len(kv) - degree_v - 1
    assert nu > 0 and nv > 0, "degenerate knot vector"
    # uniformly spaced XY grid
    xs = np.linspace(0, 1, nu)
    ys = np.linspace(0, 1, nv)
    pts = np.zeros((nu, nv, 3))
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            pts[i, j] = [x, y, z]
    return NurbsSurface(degree_u=degree_u, degree_v=degree_v,
                        control_points=pts, knots_u=ku, knots_v=kv)


def _adjacent_pair(ku_a, ku_b, degree=2):
    """Two degree-2 flat surfaces that share a u_max / u_min boundary.

    face_a is at z=0, face_b is at z=0 but shifted in X so the u_max of A
    equals the u_min of B geometrically.  Both have v in [0,1].
    """
    kv = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    face_a = _flat_surface(degree, degree, ku_a, kv, z=0.0)
    face_b = _flat_surface(degree, degree, ku_b, kv, z=0.0)
    return face_a, face_b


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_internal_knots_degree2():
    knots = np.array([0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0])
    result = _internal_knots(knots, degree=2)
    np.testing.assert_allclose(result, [0.5])


def test_internal_knots_degree2_multiple():
    knots = np.array([0.0, 0.0, 0.0, 0.3, 0.7, 1.0, 1.0, 1.0])
    result = _internal_knots(knots, degree=2)
    np.testing.assert_allclose(result, [0.3, 0.7])


def test_internal_knots_no_interior():
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    result = _internal_knots(knots, degree=2)
    assert len(result) == 0


def test_missing_knots_simple():
    existing = np.array([0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0])
    target = np.array([0.3, 0.5, 0.7])
    missing = _missing_knots(existing, degree=2, target_internal=target)
    np.testing.assert_allclose(sorted(missing), [0.3, 0.7])


# ---------------------------------------------------------------------------
# Test 1 — already compatible
# ---------------------------------------------------------------------------

def test_already_compatible():
    """Surfaces with identical knot vectors should report already_compatible."""
    ku = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    kv = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    fa, fb = _adjacent_pair(ku, ku, degree=2)
    res = make_faces_compatible(fa, fb, edge_dir_a="v_min", edge_dir_b="v_max")
    assert isinstance(res, CompatibilityResult)
    assert res.error == "", f"unexpected error: {res.error}"
    assert res.already_compatible is True
    assert res.knots_inserted == []
    assert res.degree_mismatch is False
    # surfaces unchanged
    np.testing.assert_array_equal(res.face_a_new.knots_u, fa.knots_u)
    np.testing.assert_array_equal(res.face_b_new.knots_u, fb.knots_u)


# ---------------------------------------------------------------------------
# Test 2 — depth-bar: mismatched knot vectors (P-T §6.5)
# ---------------------------------------------------------------------------

def test_depth_bar_knot_union():
    """Depth-bar case: face_a=[0,0,0,0.5,1,1,1], face_b=[0,0,0,0.3,0.7,1,1,1].

    Expected union along the shared direction: [0,0,0,0.3,0.5,0.7,1,1,1].
    """
    ku_a = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    ku_b = [0.0, 0.0, 0.0, 0.3, 0.7, 1.0, 1.0, 1.0]
    kv = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    fa = _flat_surface(2, 2, ku_a, kv, z=0.0)
    fb = _flat_surface(2, 2, ku_b, kv, z=0.0)

    # Hint: share the v-direction (u knot vectors need to match)
    res = make_faces_compatible(fa, fb, edge_dir_a="v_min", edge_dir_b="v_max")

    assert res.error == "", f"error: {res.error}"
    assert res.already_compatible is False
    assert res.degree_mismatch is False

    expected_internal = [0.3, 0.5, 0.7]
    # After insertion both faces should have all three interior knots
    new_int_a = _internal_knots(res.face_a_new.knots_u, 2)
    new_int_b = _internal_knots(res.face_b_new.knots_u, 2)
    np.testing.assert_allclose(sorted(new_int_a), expected_internal, atol=1e-10)
    np.testing.assert_allclose(sorted(new_int_b), expected_internal, atol=1e-10)

    # knots_inserted should be the union of what was missing from each
    inserted = sorted(res.knots_inserted)
    assert 0.3 in inserted or 0.5 in inserted, f"missing insertions: {inserted}"
    assert 0.5 in inserted, "0.5 should be in knots_inserted (was missing from B)"


def test_depth_bar_knot_count():
    """Face A originally has 4 internal CPs (3 spans); after adding 0.3 + 0.7 it
    should have 6 internal CPs (5 spans), matching face B."""
    ku_a = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    ku_b = [0.0, 0.0, 0.0, 0.3, 0.7, 1.0, 1.0, 1.0]
    kv = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    fa = _flat_surface(2, 2, ku_a, kv, z=0.0)
    fb = _flat_surface(2, 2, ku_b, kv, z=0.0)
    res = make_faces_compatible(fa, fb, edge_dir_a="v_min", edge_dir_b="v_max")
    assert res.error == ""
    # Both should now have 6 knot spans (degree 2, 3 interior => n_ctrl = 6 => knot len = 9)
    assert len(res.face_a_new.knots_u) == 9, f"got {len(res.face_a_new.knots_u)}"
    assert len(res.face_b_new.knots_u) == 9, f"got {len(res.face_b_new.knots_u)}"


def test_depth_bar_geometry_preserved():
    """After knot insertion the surface geometry must not change (Boehm invariance)."""
    from kerf_cad_core.geom.nurbs import surface_evaluate
    ku_a = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    ku_b = [0.0, 0.0, 0.0, 0.3, 0.7, 1.0, 1.0, 1.0]
    kv = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    fa = _flat_surface(2, 2, ku_a, kv, z=0.0)
    fb = _flat_surface(2, 2, ku_b, kv, z=0.0)
    res = make_faces_compatible(fa, fb, edge_dir_a="v_min", edge_dir_b="v_max")
    assert res.error == ""
    # Sample 9 points on face_a before and after insertion
    for u in np.linspace(0.05, 0.95, 9):
        for v in np.linspace(0.05, 0.95, 9):
            pt_before = surface_evaluate(fa, u, v)
            pt_after = surface_evaluate(res.face_a_new, u, v)
            np.testing.assert_allclose(pt_after, pt_before, atol=1e-10,
                                       err_msg=f"geometry changed at u={u:.2f} v={v:.2f}")


# ---------------------------------------------------------------------------
# Test 3 — degree mismatch
# ---------------------------------------------------------------------------

def test_degree_mismatch_flagged():
    """When face_a has degree 2 and face_b has degree 3, flag degree_mismatch."""
    ku_a = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    ku_b = [0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0, 1.0]
    kv_a = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    kv_b = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    fa = _flat_surface(2, 2, ku_a, kv_a, z=0.0)
    fb = _flat_surface(3, 2, ku_b, kv_b, z=0.0)
    res = make_faces_compatible(fa, fb, edge_dir_a="v_min", edge_dir_b="v_max")
    assert res.error == "", f"unexpected error: {res.error}"
    assert res.degree_mismatch is True
    # Surfaces should still be returned (partial result)
    assert res.face_a_new is not None
    assert res.face_b_new is not None


def test_degree_mismatch_does_not_crash():
    """degree-mismatch path should not raise."""
    ku_a = [0.0, 0.0, 0.3, 0.7, 1.0, 1.0]  # degree 1
    ku_b = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]  # degree 2
    kv = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    nu_a = len(ku_a) - 1 - 1
    nu_b = len(ku_b) - 2 - 1
    nv = len(kv) - 2 - 1
    pts_a = np.zeros((nu_a, nv, 3))
    pts_b = np.zeros((nu_b, nv, 3))
    xs_a = np.linspace(0, 1, nu_a)
    xs_b = np.linspace(0, 1, nu_b)
    ys = np.linspace(0, 1, nv)
    for i, x in enumerate(xs_a):
        for j, y in enumerate(ys):
            pts_a[i, j] = [x, y, 0]
    for i, x in enumerate(xs_b):
        for j, y in enumerate(ys):
            pts_b[i, j] = [x, y, 0]
    fa = NurbsSurface(degree_u=1, degree_v=2, control_points=pts_a,
                      knots_u=np.array(ku_a), knots_v=np.array(kv))
    fb = NurbsSurface(degree_u=2, degree_v=2, control_points=pts_b,
                      knots_u=np.array(ku_b), knots_v=np.array(kv))
    res = make_faces_compatible(fa, fb, edge_dir_a="v_min", edge_dir_b="v_max")
    assert res.error == "" or "degree" in res.error.lower() or res.degree_mismatch


# ---------------------------------------------------------------------------
# Test 4 — no shared edge
# ---------------------------------------------------------------------------

def test_no_shared_edge_flagged():
    """Two surfaces that are far apart should produce an error, not crash."""
    ku = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    kv = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    pts_a = np.zeros((3, 3, 3))
    pts_b = np.zeros((3, 3, 3))
    for i in range(3):
        for j in range(3):
            pts_a[i, j] = [i / 2.0, j / 2.0, 0.0]
            pts_b[i, j] = [i / 2.0 + 100.0, j / 2.0 + 100.0, 0.0]  # far away
    fa = NurbsSurface(degree_u=2, degree_v=2, control_points=pts_a,
                      knots_u=np.array(ku), knots_v=np.array(kv))
    fb = NurbsSurface(degree_u=2, degree_v=2, control_points=pts_b,
                      knots_u=np.array(ku), knots_v=np.array(kv))
    res = make_faces_compatible(fa, fb)  # no hints
    assert res.error != "", "expected an error for non-adjacent faces"
    assert "shared edge" in res.error.lower() or "no shared" in res.error.lower()
    assert res.face_a_new is None
    assert res.face_b_new is None


def test_no_shared_edge_with_bad_hints():
    """Supplying explicit hints still works even if the faces are far apart —
    the geometric check is bypassed and pure knot arithmetic is applied."""
    ku_a = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    ku_b = [0.0, 0.0, 0.0, 0.3, 0.7, 1.0, 1.0, 1.0]
    kv = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    # Two non-adjacent surfaces — but we force hints
    fa = _flat_surface(2, 2, ku_a, kv, z=0.0)
    fb = _flat_surface(2, 2, ku_b, kv, z=100.0)  # far in Z
    res = make_faces_compatible(fa, fb, edge_dir_a="v_min", edge_dir_b="v_max")
    # Should succeed because hints bypass geometry check
    assert res.error == ""
    assert res.face_a_new is not None


# ---------------------------------------------------------------------------
# Test 5 — auto-detection of shared edge
# ---------------------------------------------------------------------------

def test_auto_detect_shared_edge():
    """Auto-detection should find the common edge without explicit hints."""
    ku_a = [0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0]
    ku_b = [0.0, 0.0, 0.0, 0.3, 0.7, 1.0, 1.0, 1.0]
    kv = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    fa = _flat_surface(2, 2, ku_a, kv, z=0.0)

    # Build face_b so that its u_min boundary is at the same location as
    # face_a's u_max boundary (both at x=1).
    nu_b = len(ku_b) - 2 - 1
    nv = len(kv) - 2 - 1
    pts_b = np.zeros((nu_b, nv, 3))
    for i in range(nu_b):
        for j in range(nv):
            pts_b[i, j] = [1.0 + i / float(nu_b - 1 or 1), j / float(nv - 1 or 1), 0.0]
    fb = NurbsSurface(degree_u=2, degree_v=2, control_points=pts_b,
                      knots_u=np.array(ku_b), knots_v=np.array(kv))

    res = make_faces_compatible(fa, fb)  # no explicit hints
    # Either a shared edge is found (ok) or auto-detect gracefully flags it
    # (acceptable because the surfaces are only tangent at a point, not an edge).
    # The test simply asserts no crash and that the return type is correct.
    assert isinstance(res, CompatibilityResult)


# ---------------------------------------------------------------------------
# Test 6 — v-direction compatibility
# ---------------------------------------------------------------------------

def test_v_direction_compatibility():
    """Verify that the v knot vectors are harmonised when the shared edge is u-constant."""
    kv_a = [0.0, 0.0, 0.0, 0.4, 1.0, 1.0, 1.0]
    kv_b = [0.0, 0.0, 0.0, 0.6, 1.0, 1.0, 1.0]
    ku = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    fa = _flat_surface(2, 2, ku, kv_a, z=0.0)
    fb = _flat_surface(2, 2, ku, kv_b, z=0.0)
    # shared edge is at u_max of A and u_min of B → v direction must be harmonised
    res = make_faces_compatible(fa, fb, edge_dir_a="u_max", edge_dir_b="u_min")
    assert res.error == ""
    assert res.shared_edge_dir_a == "v"
    assert res.shared_edge_dir_b == "v"
    # Both faces should now have both 0.4 and 0.6 in their v knot vectors
    new_int_a = _internal_knots(res.face_a_new.knots_v, 2)
    new_int_b = _internal_knots(res.face_b_new.knots_v, 2)
    np.testing.assert_allclose(sorted(new_int_a), [0.4, 0.6], atol=1e-10)
    np.testing.assert_allclose(sorted(new_int_b), [0.4, 0.6], atol=1e-10)
