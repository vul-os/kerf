"""Hermetic tests for kerf_cad_core.geom.chamfer (GK P1 chamfer).

All tests are self-contained -- no network, no OCCT, no external fixtures.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import validate_body
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.chamfer import (
    ChamferError,
    chamfer_edge,
    chamfer_edge_asymmetric,
    chamfer_edge_variable,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit_box():
    """1×1×1 box at origin."""
    return box_to_body((0, 0, 0), 1, 1, 1)


def _first_edge(body):
    """Return the first edge from the body's edge list."""
    return body.all_edges()[0]


def _pick_edge_by_vertices(body, pt0, pt1, tol=1e-6):
    """Find an edge whose endpoints match pt0 and pt1 (in either order)."""
    p0 = np.asarray(pt0, dtype=float)
    p1 = np.asarray(pt1, dtype=float)
    for e in body.all_edges():
        a = e.v_start.point
        b = e.v_end.point
        if (np.linalg.norm(a - p0) < tol and np.linalg.norm(b - p1) < tol) or \
           (np.linalg.norm(a - p1) < tol and np.linalg.norm(b - p0) < tol):
            return e
    raise AssertionError(f"No edge found between {pt0} and {pt1}")


def _box_volume(body, n=50):
    """Estimate body volume by Monte Carlo signed-divergence integration.

    Uses the divergence theorem on the actual vertex data: sum of
    (x * face_normal_x * face_area) over all faces (planar quad/tri
    approximation via triangulation of each face).
    """
    vol = 0.0
    for face in body.all_faces():
        outer = face.outer_loop()
        if outer is None or len(outer.coedges) < 3:
            continue
        pts = [np.asarray(ce.start_point(), dtype=float) for ce in outer.coedges]
        # Triangulate as a fan from pts[0]
        p0 = pts[0]
        for i in range(1, len(pts) - 1):
            a = pts[i] - p0
            b = pts[i + 1] - p0
            cross = np.cross(a, b)
            # Signed volume contribution: (1/6) * dot(p0, cross)
            vol += float(np.dot(p0, cross))
    return abs(vol) / 6.0


# ---------------------------------------------------------------------------
# 1. Topology counts after constant chamfer on box
# ---------------------------------------------------------------------------


def test_chamfer_topology_counts():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge(body, edge, 0.1)
    c = result.euler_counts()
    assert c["V"] == 10, f"Expected V=10, got {c['V']}"
    assert c["E"] == 15, f"Expected E=15, got {c['E']}"
    assert c["F"] == 7,  f"Expected F=7, got {c['F']}"


def test_chamfer_euler_residual_zero():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge(body, edge, 0.1)
    assert result.euler_poincare_residual() == 0


def test_chamfer_validate_body_clean():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge(body, edge, 0.1)
    vr = validate_body(result)
    assert vr["ok"], f"validate_body errors: {vr['errors']}"


# ---------------------------------------------------------------------------
# 2. Volume removed by symmetric chamfer = ½·w²·L
# ---------------------------------------------------------------------------


def test_symmetric_chamfer_volume_removed():
    """Volume removed = ½·w²·L (right-triangular prism cross-section)."""
    w = 0.1
    L = 1.0  # unit box edge length
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge(body, edge, w)
    vol_before = _box_volume(_unit_box())
    vol_after  = _box_volume(result)
    removed = vol_before - vol_after
    expected = 0.5 * w * w * L
    assert abs(removed - expected) < 1e-9, (
        f"Volume removed {removed:.12f} != expected {expected:.12f}"
    )


def test_symmetric_chamfer_volume_removed_w02():
    """Same test with w=0.2."""
    w = 0.2
    L = 1.0
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge(body, edge, w)
    vol_before = _box_volume(_unit_box())
    vol_after  = _box_volume(result)
    removed = vol_before - vol_after
    expected = 0.5 * w * w * L
    assert abs(removed - expected) < 1e-9, (
        f"Volume removed {removed:.12f} != {expected:.12f}"
    )


def test_symmetric_chamfer_volume_longer_edge():
    """2×1×1 box, chamfer the length-2 top-front edge."""
    w = 0.1
    L = 2.0
    body = box_to_body((0, 0, 0), 2, 1, 1)
    edge = _pick_edge_by_vertices(body, (2, 0, 1), (0, 0, 1))
    result = chamfer_edge(body, edge, w)
    vol_before = _box_volume(box_to_body((0, 0, 0), 2, 1, 1))
    vol_after  = _box_volume(result)
    removed = vol_before - vol_after
    expected = 0.5 * w * w * L
    assert abs(removed - expected) < 1e-9, (
        f"Volume removed {removed:.12f} != {expected:.12f} (L={L})"
    )


# ---------------------------------------------------------------------------
# 3. Asymmetric chamfer volume = ½·w_a·w_b·L
# ---------------------------------------------------------------------------


def test_asymmetric_chamfer_volume_removed():
    """Volume removed = ½·w_a·w_b·L."""
    w_a, w_b = 0.1, 0.2
    L = 1.0
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge_asymmetric(body, edge, w_a, w_b)
    vol_before = _box_volume(_unit_box())
    vol_after  = _box_volume(result)
    removed = vol_before - vol_after
    expected = 0.5 * w_a * w_b * L
    assert abs(removed - expected) < 1e-9, (
        f"Asymmetric volume removed {removed:.12f} != {expected:.12f}"
    )


def test_asymmetric_chamfer_topology_counts():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge_asymmetric(body, edge, 0.1, 0.2)
    c = result.euler_counts()
    assert c["V"] == 10
    assert c["E"] == 15
    assert c["F"] == 7


def test_asymmetric_chamfer_validate_body_clean():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge_asymmetric(body, edge, 0.15, 0.05)
    vr = validate_body(result)
    assert vr["ok"], f"validate_body errors: {vr['errors']}"


def test_asymmetric_chamfer_reversed_order_same_volume():
    """chamfer_edge_asymmetric(w_a, w_b) volume == chamfer_edge_asymmetric(w_b, w_a)."""
    w_a, w_b = 0.1, 0.2
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    r1 = chamfer_edge_asymmetric(body, edge, w_a, w_b)
    r2 = chamfer_edge_asymmetric(body, edge, w_b, w_a)
    vol1 = _box_volume(r1)
    vol2 = _box_volume(r2)
    assert abs(vol1 - vol2) < 1e-9


# ---------------------------------------------------------------------------
# 4. Variable chamfer volume = ¼·w²·L  (ramp 0..w)
# ---------------------------------------------------------------------------


def test_variable_chamfer_volume_removed():
    """Variable chamfer width_start=0, width_end=w: volume = w²·L/6.

    Cross-section at parameter t in [0, 1] is a right isosceles triangle
    with legs w·t on each support face.  Area = ½·(w·t)².  Integrating
    over t from 0 to L gives ½·w²·L²/3 / L = w²·L / 6.
    """
    w = 0.2
    L = 1.0
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge_variable(body, edge, 0.0, w)
    vol_before = _box_volume(_unit_box())
    vol_after  = _box_volume(result)
    removed = vol_before - vol_after
    expected = w * w * L / 6.0
    assert abs(removed - expected) < 1e-7, (
        f"Variable chamfer removed {removed:.12f} != {expected:.12f}"
    )


def test_variable_chamfer_validate_body_clean():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge_variable(body, edge, 0.05, 0.15)
    vr = validate_body(result)
    assert vr["ok"], f"validate_body errors: {vr['errors']}"


def test_variable_chamfer_euler_residual():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge_variable(body, edge, 0.05, 0.15)
    assert result.euler_poincare_residual() == 0


def test_variable_chamfer_constant_equiv_volume():
    """When width_start==width_end, variable chamfer volume == constant chamfer."""
    w = 0.1
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    r_const    = chamfer_edge(body, edge, w)
    r_variable = chamfer_edge_variable(body, edge, w, w)
    assert abs(_box_volume(r_const) - _box_volume(r_variable)) < 1e-9


# ---------------------------------------------------------------------------
# 5. Bevel face planarity (symmetric and asymmetric)
# ---------------------------------------------------------------------------


def _find_bevel_face(body_before, body_after):
    """Find the new bevel face in body_after by process of elimination.

    The bevel face is the one face in body_after whose surface type is
    _RuledSurface (not a Plane).
    """
    from kerf_cad_core.geom.chamfer import _RuledSurface
    for f in body_after.all_faces():
        if isinstance(f.surface, _RuledSurface):
            return f
    raise AssertionError("No bevel face (_RuledSurface) found in result body")


def _face_is_planar(face, n_samples=20, tol=1e-9):
    """Check that sampled points on the bevel face are coplanar."""
    outer = face.outer_loop()
    if outer is None:
        return False
    # Sample the face surface directly
    pts = []
    for u in np.linspace(0, 1, n_samples):
        for v in np.linspace(0, 1, n_samples):
            p = np.asarray(face.surface.evaluate(u, v), dtype=float)
            pts.append(p)
    pts = np.array(pts)
    if len(pts) < 4:
        return True
    # Fit a plane through the first three non-collinear points
    p0 = pts[0]
    for i in range(1, len(pts)):
        v1 = pts[i] - p0
        if np.linalg.norm(v1) > 1e-12:
            break
    for j in range(i + 1, len(pts)):
        v2 = pts[j] - p0
        n = np.cross(v1, v2)
        if np.linalg.norm(n) > 1e-12:
            break
    else:
        return True  # degenerate — trivially planar
    n = n / np.linalg.norm(n)
    # Check all points lie on this plane
    dists = np.abs(np.dot(pts - p0, n))
    return bool(np.all(dists < tol))


def test_bevel_face_is_planar_symmetric():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge(body, edge, 0.1)
    bevel = _find_bevel_face(body, result)
    assert _face_is_planar(bevel, tol=1e-9), "Bevel face should be planar for symmetric chamfer"


def test_bevel_face_is_planar_asymmetric():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge_asymmetric(body, edge, 0.1, 0.2)
    bevel = _find_bevel_face(body, result)
    assert _face_is_planar(bevel, tol=1e-9), "Bevel face should be planar for asymmetric constant chamfer"


def test_bevel_face_normals_uniform():
    """All sampled normals on the bevel face should be identical (planar)."""
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge(body, edge, 0.1)
    bevel = _find_bevel_face(body, result)
    surface = bevel.surface
    normals = []
    for u in np.linspace(0.05, 0.95, 10):
        for v in np.linspace(0.05, 0.95, 10):
            normals.append(np.asarray(surface.normal(u, v), dtype=float))
    normals = np.array(normals)
    # Normalize
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = normals / (norms + 1e-15)
    # All normals should match the first one within 1e-9
    ref = normals[0]
    for n in normals[1:]:
        diff = float(np.linalg.norm(n - ref))
        assert diff < 1e-9, f"Bevel normals deviate: {diff:.3e}"


# ---------------------------------------------------------------------------
# 6. Graceful rejection: width exceeds face extent
# ---------------------------------------------------------------------------


def test_chamfer_too_wide_raises_chamfer_error():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    with pytest.raises(ChamferError) as exc_info:
        chamfer_edge(body, edge, 0.99)  # face is 1.0 wide; 0.99 should fail
    assert exc_info.value.reason == "width exceeds face"


def test_chamfer_zero_width_raises():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    with pytest.raises(ChamferError) as exc_info:
        chamfer_edge(body, edge, 0.0)
    assert exc_info.value.reason == "invalid-width"


def test_chamfer_negative_width_raises():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    with pytest.raises(ChamferError):
        chamfer_edge(body, edge, -0.1)


def test_chamfer_width_exactly_at_max_raises():
    """Width >= face extent should raise, not silently produce garbage."""
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    # The face is 1 unit wide; attempting exactly 1.0 should raise
    with pytest.raises(ChamferError) as exc_info:
        chamfer_edge(body, edge, 1.0)
    assert exc_info.value.reason in ("width exceeds face", "invalid-width")


def test_chamfer_error_carries_reason():
    """ChamferError.reason is a non-empty string."""
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    try:
        chamfer_edge(body, edge, 5.0)
    except ChamferError as e:
        assert isinstance(e.reason, str) and len(e.reason) > 0
        assert isinstance(e.message, str) and len(e.message) > 0
    else:
        pytest.fail("ChamferError not raised for oversized width")


# ---------------------------------------------------------------------------
# 7. Determinism
# ---------------------------------------------------------------------------


def test_chamfer_deterministic_topology():
    """Five independent chamfer calls must yield identical topology counts."""
    results = []
    for _ in range(5):
        body = _unit_box()
        edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
        r = chamfer_edge(body, edge, 0.1)
        results.append(r.euler_counts())
    for c in results[1:]:
        assert c["V"] == results[0]["V"]
        assert c["E"] == results[0]["E"]
        assert c["F"] == results[0]["F"]


def test_chamfer_deterministic_volume():
    """Five independent chamfer calls must yield identical volumes."""
    vols = []
    for _ in range(5):
        body = _unit_box()
        edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
        r = chamfer_edge(body, edge, 0.1)
        vols.append(_box_volume(r))
    for v in vols[1:]:
        assert abs(v - vols[0]) < 1e-12


# ---------------------------------------------------------------------------
# 8. Additional correctness tests
# ---------------------------------------------------------------------------


def test_chamfer_bottom_front_edge():
    """Chamfer a different edge (front-bottom) to verify generality."""
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (0, 0, 0), (1, 0, 0))
    result = chamfer_edge(body, edge, 0.1)
    c = result.euler_counts()
    assert c["V"] == 10
    assert c["E"] == 15
    assert c["F"] == 7
    assert validate_body(result)["ok"]


def test_chamfer_side_vertical_edge():
    """Chamfer a vertical edge of the box."""
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (0, 0, 0), (0, 0, 1))
    result = chamfer_edge(body, edge, 0.1)
    c = result.euler_counts()
    assert c["V"] == 10
    assert c["F"] == 7
    assert validate_body(result)["ok"]


def test_chamfer_does_not_modify_original_body():
    """The original body should remain structurally valid after chamfer."""
    body1 = _unit_box()
    body2 = _unit_box()  # independent copy
    edge1 = _pick_edge_by_vertices(body1, (1, 0, 1), (0, 0, 1))
    _result = chamfer_edge(body1, edge1, 0.1)
    # body2 was not touched; it must still validate
    vr = validate_body(body2)
    # body2 should still have 8 vertices etc (it was never modified)
    c2 = body2.euler_counts()
    assert c2["V"] == 8


def test_symmetric_chamfer_equals_asymmetric_equal_widths():
    """chamfer_edge(w) and chamfer_edge_asymmetric(w, w) should give same volume."""
    w = 0.12
    body_a = _unit_box()
    body_b = _unit_box()
    ea = _pick_edge_by_vertices(body_a, (1, 0, 1), (0, 0, 1))
    eb = _pick_edge_by_vertices(body_b, (1, 0, 1), (0, 0, 1))
    ra = chamfer_edge(body_a, ea, w)
    rb = chamfer_edge_asymmetric(body_b, eb, w, w)
    assert abs(_box_volume(ra) - _box_volume(rb)) < 1e-12


def test_variable_chamfer_zero_start_topology():
    """Variable chamfer with width_start=0 produces a wedge (triangular bevel).

    At the zero-width end the two setback vertices coincide with the original
    corner, so no bevel-boundary edge is created there.  The topology change is:

      -1 corner vertex (v_orig_end replaced by 2 new)  → net +1 vertex
      -1 chamfered edge, +2 setback edges, +1 bevel_at_end → net +2 edges
      +1 bevel face

    Before: V=8 E=12 F=6  →  After: V=9 E=14 F=7.
    Euler: 9 - 14 + 7 - 0 - 2*(1-0) = 0 ✓
    """
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    result = chamfer_edge_variable(body, edge, 0.0, 0.2)
    c = result.euler_counts()
    assert c["V"] == 9, f"Expected V=9 (wedge), got {c['V']}"
    assert c["E"] == 14, f"Expected E=14 (wedge), got {c['E']}"
    assert c["F"] == 7, f"Expected F=7, got {c['F']}"
    assert result.euler_poincare_residual() == 0
    assert validate_body(result)["ok"]


def test_both_variable_widths_zero_raises():
    body = _unit_box()
    edge = _pick_edge_by_vertices(body, (1, 0, 1), (0, 0, 1))
    with pytest.raises(ChamferError):
        chamfer_edge_variable(body, edge, 0.0, 0.0)
