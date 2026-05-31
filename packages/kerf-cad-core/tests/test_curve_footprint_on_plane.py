"""
test_curve_footprint_on_plane.py
================================
Hermetic analytic-oracle tests for geom/curve_footprint_on_plane.py

Covers:
  1. Helix → XY plane yields a circle (radius matches helix radius)
  2. Already-planar curve → footprint equal to original (within 1e-12)
  3. Vertical line perpendicular to plane → degenerate flag
  4. Skewed plane normal → projection axis is unit-length and correct
  5. Knot vector preserved exactly
  6. Weights preserved exactly for rational curve
  7. Degree preserved
  8. Non-rational footprint (weights=None)
  9. FootprintResult fields populated
 10. max_orig_depth is non-zero for a 3-D curve
 11. Projection formula: random point depth matches formula
 12. 45° tilted plane footprint analytic check
 13. Circle already on XY plane → footprint == original
 14. lift_footprint_to_3d round-trips the 3-D CPs
 15. ValueError for zero-length normal
 16. Multi-turn helix circle radius invariant

All tests: no network, no OCC, no external binaries.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, make_circle_nurbs
from kerf_cad_core.geom.curve_footprint_on_plane import (
    FootprintResult,
    project_curve_to_plane,
    lift_footprint_to_3d,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line_curve(p0, p1) -> NurbsCurve:
    """Degree-1 NURBS line p0→p1."""
    cp = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=cp, knots=knots)


def _helix_nurbs(radius: float, pitch: float, turns: float,
                 n_samples: int = 20) -> NurbsCurve:
    """
    Degree-3 NURBS approximation of a helix:
        x(t) = r cos(2π turns t)
        y(t) = r sin(2π turns t)
        z(t) = pitch * turns * t
    for t in [0, 1].  Interpolated through n_samples points.
    """
    ts = np.linspace(0.0, 1.0, n_samples)
    pts = np.column_stack([
        radius * np.cos(2 * math.pi * turns * ts),
        radius * np.sin(2 * math.pi * turns * ts),
        pitch * turns * ts,
    ])
    # Chord-length parametrisation
    diffs = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    chord_total = diffs.sum()
    params = np.concatenate([[0.0], np.cumsum(diffs) / chord_total])

    degree = 3
    n = n_samples
    # Build clamped uniform knot vector for n CPs, degree d
    inner = max(0, n - degree - 1)
    knots = np.concatenate([
        np.zeros(degree + 1),
        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
        np.ones(degree + 1),
    ])
    return NurbsCurve(degree=degree, control_points=pts, knots=knots)


def _quadratic_curve_3d(z_offset: float = 0.0) -> NurbsCurve:
    """Simple planar degree-2 curve at given z-height."""
    cp = np.array([
        [0.0, 0.0, z_offset],
        [1.0, 2.0, z_offset],
        [2.0, 0.0, z_offset],
    ])
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=2, control_points=cp, knots=knots)


# ---------------------------------------------------------------------------
# Test 1 — Helix → XY plane → circle radius matches helix radius
# ---------------------------------------------------------------------------

def test_helix_to_xy_plane_radius():
    """Projecting a helix onto XY should yield a circle of the helix radius."""
    R = 3.0
    helix = _helix_nurbs(radius=R, pitch=1.0, turns=1.0, n_samples=36)
    result = project_curve_to_plane(
        helix,
        plane_point=[0, 0, 0],
        plane_normal=[0, 0, 1],
    )
    cp2d = result.footprint_curve_2d.control_points
    # All projected CPs should lie at radius ≈ R in UV (XY)
    radii = np.linalg.norm(cp2d, axis=1)
    # Helix CPs are on the circle in XY exactly (no z contribution)
    assert np.allclose(radii, R, atol=1e-12), (
        f"Projected CPs should all have radius={R}; got {radii}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Already-planar curve → footprint equal to original
# ---------------------------------------------------------------------------

def test_already_planar_curve_identity():
    """A curve that lies in the projection plane should project to itself."""
    curve = _quadratic_curve_3d(z_offset=0.0)
    result = project_curve_to_plane(
        curve,
        plane_point=[0, 0, 0],
        plane_normal=[0, 0, 1],
    )
    cp2d = result.footprint_curve_2d.control_points
    # Original XY coords should match UV coords exactly
    expected = curve.control_points[:, :2]
    assert np.allclose(cp2d, expected, atol=1e-12), (
        f"Footprint CPs differ from originals:\n{cp2d}\n!=\n{expected}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Vertical line perpendicular to plane → degenerate / point footprint
# ---------------------------------------------------------------------------

def test_vertical_line_degenerate():
    """A line parallel to the plane normal projects to a single point."""
    vert = _line_curve([1.0, 2.0, 0.0], [1.0, 2.0, 5.0])
    result = project_curve_to_plane(
        vert,
        plane_point=[0, 0, 0],
        plane_normal=[0, 0, 1],
    )
    cp2d = result.footprint_curve_2d.control_points
    # Both CPs should collapse to the same UV point
    spread = np.max(np.linalg.norm(cp2d - cp2d.mean(axis=0), axis=1))
    assert spread < 1e-10, f"Expected degenerate footprint; spread={spread}"
    assert "degenerate" in result.honest_caveat.lower() or "perpendicular" in result.honest_caveat.lower()


# ---------------------------------------------------------------------------
# Test 4 — Skewed plane normal → projection axis is unit-length
# ---------------------------------------------------------------------------

def test_skewed_plane_normal_unit_axis():
    """Result projection_axis must be unit-length for any normal direction."""
    for normal in ([1, 1, 1], [0.1, 0.2, 0.9], [3.7, -2.1, 0.4]):
        curve = _line_curve([0, 0, 0], [1, 1, 0])
        result = project_curve_to_plane(
            curve,
            plane_point=[0, 0, 0],
            plane_normal=normal,
        )
        ax = np.array(result.projection_axis)
        assert abs(np.linalg.norm(ax) - 1.0) < 1e-12, (
            f"projection_axis should be unit for normal={normal}; norm={np.linalg.norm(ax)}"
        )


# ---------------------------------------------------------------------------
# Test 5 — Knot vector preserved exactly
# ---------------------------------------------------------------------------

def test_knot_vector_preserved():
    """Footprint curve must have the exact same knot vector as the input."""
    curve = _quadratic_curve_3d(z_offset=2.0)
    result = project_curve_to_plane(
        curve,
        plane_point=[0, 0, 0],
        plane_normal=[0, 0, 1],
    )
    assert np.array_equal(result.footprint_curve_2d.knots, curve.knots), (
        "Knot vector was modified during projection."
    )


# ---------------------------------------------------------------------------
# Test 6 — Weights preserved for rational curve
# ---------------------------------------------------------------------------

def test_weights_preserved_rational():
    """Rational NURBS weights must survive the projection unchanged."""
    # Build a simple rational quadratic (like a conic arc)
    cp = np.array([[0.0, 0.0, 1.0], [1.0, 1.0, 1.5], [2.0, 0.0, 1.0]])
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    weights = np.array([1.0, math.sqrt(2) / 2, 1.0])
    curve = NurbsCurve(degree=2, control_points=cp, knots=knots, weights=weights)

    result = project_curve_to_plane(
        curve,
        plane_point=[0, 0, 0],
        plane_normal=[0, 0, 1],
    )
    assert np.allclose(result.footprint_curve_2d.weights, weights, atol=1e-15), (
        "Weights were modified during projection."
    )


# ---------------------------------------------------------------------------
# Test 7 — Degree preserved
# ---------------------------------------------------------------------------

def test_degree_preserved():
    """Footprint degree must equal input degree for any degree ≥ 1."""
    for deg in (1, 2, 3):
        n = deg + 3  # enough CPs for the degree
        cp = np.column_stack([
            np.linspace(0, 1, n),
            np.random.default_rng(seed=deg).uniform(-1, 1, n),
            np.random.default_rng(seed=deg + 100).uniform(0, 2, n),
        ])
        inner = max(0, n - deg - 1)
        knots = np.concatenate([
            np.zeros(deg + 1),
            np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
            np.ones(deg + 1),
        ])
        curve = NurbsCurve(degree=deg, control_points=cp, knots=knots)
        result = project_curve_to_plane(
            curve,
            plane_point=[0, 0, 0],
            plane_normal=[0, 0, 1],
        )
        assert result.footprint_curve_2d.degree == deg


# ---------------------------------------------------------------------------
# Test 8 — Non-rational (weights=None) curve → footprint weights=None
# ---------------------------------------------------------------------------

def test_non_rational_weights_none():
    """Non-rational input → footprint should have weights=None."""
    curve = _quadratic_curve_3d(z_offset=1.0)
    assert curve.weights is None
    result = project_curve_to_plane(
        curve,
        plane_point=[0, 0, 0],
        plane_normal=[0, 0, 1],
    )
    assert result.footprint_curve_2d.weights is None


# ---------------------------------------------------------------------------
# Test 9 — FootprintResult fields populated
# ---------------------------------------------------------------------------

def test_footprint_result_fields():
    """FootprintResult must contain all declared fields with correct types."""
    curve = _line_curve([0, 0, 0], [1, 1, 1])
    result = project_curve_to_plane(
        curve,
        plane_point=[0, 0, 0],
        plane_normal=[0, 0, 1],
    )
    assert isinstance(result, FootprintResult)
    assert isinstance(result.footprint_curve_2d, NurbsCurve)
    assert len(result.projection_axis) == 3
    assert isinstance(result.max_orig_depth, float)
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Test 10 — max_orig_depth is non-zero for a 3-D curve with Z variation
# ---------------------------------------------------------------------------

def test_max_orig_depth_nonzero():
    """A curve with Z spread must report max_orig_depth > 0."""
    curve = _line_curve([0, 0, 0], [1, 1, 5])
    result = project_curve_to_plane(
        curve,
        plane_point=[0, 0, 0],
        plane_normal=[0, 0, 1],
    )
    assert result.max_orig_depth > 0.0, "Expected non-zero depth for a 3-D curve."


# ---------------------------------------------------------------------------
# Test 11 — Projection formula: single-point depth check
# ---------------------------------------------------------------------------

def test_projection_formula_depth():
    """
    For a single CP at P, the formula  P' = P - ((P-O)·n̂) n̂  should hold.
    Verify by checking that (P' - O) is perpendicular to n.
    """
    P = np.array([3.0, 4.0, 7.0])
    O = np.array([0.0, 0.0, 0.0])
    n = np.array([0.0, 0.0, 1.0])
    # Project manually
    depth = np.dot(P - O, n)
    P_prime_expected = P - depth * n  # = [3, 4, 0]
    assert np.allclose(P_prime_expected, [3, 4, 0], atol=1e-15)

    # Now via the module
    curve = _line_curve(P, P + np.array([0, 0, 1]))  # second CP is along normal
    result = project_curve_to_plane(curve, plane_point=O, plane_normal=n)
    # First CP should project to (3, 4) in UV == (3, 4) since u=X, v=Y here
    uv0 = result.footprint_curve_2d.control_points[0]
    assert np.allclose(uv0, [3.0, 4.0], atol=1e-12)


# ---------------------------------------------------------------------------
# Test 12 — 45° tilted plane footprint: analytic UV check
# ---------------------------------------------------------------------------

def test_tilted_plane_footprint_analytic():
    """
    Project a point P=(2, 0, 2) onto the plane with normal=(0,0,1) tilted
    so we can verify the UV analytically.

    Use plane_normal = (1, 0, 1)/√2 (a 45° tilt around Y).
    Point P = (4, 0, 0), plane_point O = (0, 0, 0).

    depth = P · n̂ = 4/√2 ≈ 2.828
    P' = P - depth * n̂ = [4, 0, 0] - (4/√2) * [1/√2, 0, 1/√2]
       = [4 - 4/2, 0, 0 - 4/2]
       = [2, 0, -2]

    u_axis (with n̂ = [1,0,1]/√2): candidate = (0,1,0) since |n̂[0]|<0.9 is false here
    Actually |n̂[0]| = 1/√2 ≈ 0.707 < 0.9, so candidate = (1,0,0).
    u_axis_raw = (1,0,0) - (1/√2 * 1/√2) * (1/√2, 0, 1/√2)
               = (1,0,0) - 0.5 * (1/√2, 0, 1/√2)
               = (1 - 0.5/√2, 0, -0.5/√2)

    Let's just verify numerically that the projected CP lies on the plane.
    """
    n_raw = np.array([1.0, 0.0, 1.0])
    n_hat = n_raw / np.linalg.norm(n_raw)
    O = np.array([0.0, 0.0, 0.0])
    P = np.array([4.0, 0.0, 0.0])

    curve = _line_curve(P, P + np.array([0.0, 1.0, 0.0]))
    result = project_curve_to_plane(curve, plane_point=O, plane_normal=n_raw)

    # Reconstruct 3-D foot from UV
    cp_2d = result.footprint_curve_2d.control_points[0]  # [u, v] of first CP

    # Rebuild UV frame the same way the module does
    candidate = np.array([1.0, 0.0, 0.0])
    u_ax = candidate - np.dot(candidate, n_hat) * n_hat
    u_ax /= np.linalg.norm(u_ax)
    v_ax = np.cross(n_hat, u_ax)
    v_ax /= np.linalg.norm(v_ax)

    P_prime_3d = O + cp_2d[0] * u_ax + cp_2d[1] * v_ax

    # P' must lie on the plane: (P' - O) · n̂ == 0
    assert abs(np.dot(P_prime_3d - O, n_hat)) < 1e-12

    # And P' must be the foot of P: (P - P') must be parallel to n̂
    residual = (P - P_prime_3d)
    # residual = depth * n_hat; cross product must be ~0
    cross = np.cross(residual, n_hat)
    assert np.linalg.norm(cross) < 1e-12, (
        f"P - P' should be parallel to n̂; cross={cross}"
    )


# ---------------------------------------------------------------------------
# Test 13 — make_circle_nurbs on XY plane → footprint == original CPs
# ---------------------------------------------------------------------------

def test_circle_already_on_xy_plane():
    """A NURBS circle centred at origin on XY plane → footprint CPs = original XY."""
    circle = make_circle_nurbs(center=np.array([0.0, 0.0, 0.0]), radius=5.0)
    result = project_curve_to_plane(
        circle,
        plane_point=[0, 0, 0],
        plane_normal=[0, 0, 1],
    )
    cp_orig = circle.control_points[:, :2]
    cp_foot = result.footprint_curve_2d.control_points
    assert np.allclose(cp_foot, cp_orig, atol=1e-12), (
        "Circle on XY projected to XY should give identical 2-D CPs."
    )


# ---------------------------------------------------------------------------
# Test 14 — lift_footprint_to_3d round-trips the 3-D control points
# ---------------------------------------------------------------------------

def test_lift_footprint_roundtrip():
    """project → lift should recover the original 3-D control points (within tol)."""
    curve = _quadratic_curve_3d(z_offset=0.0)
    O = [0.0, 0.0, 0.0]
    n = [0.0, 0.0, 1.0]

    result = project_curve_to_plane(curve, plane_point=O, plane_normal=n)
    lifted = lift_footprint_to_3d(result.footprint_curve_2d, plane_point=O, plane_normal=n)

    # The lifted CPs should have z≈0 and XY matching the originals
    assert np.allclose(lifted.control_points[:, :2], curve.control_points[:, :2], atol=1e-12)
    assert np.allclose(lifted.control_points[:, 2], 0.0, atol=1e-12)


# ---------------------------------------------------------------------------
# Test 15 — ValueError for zero-length normal
# ---------------------------------------------------------------------------

def test_zero_normal_raises_value_error():
    """A zero-length plane_normal must raise ValueError."""
    curve = _line_curve([0, 0, 0], [1, 0, 0])
    with pytest.raises(ValueError, match="near-zero magnitude"):
        project_curve_to_plane(curve, plane_point=[0, 0, 0], plane_normal=[0, 0, 0])


# ---------------------------------------------------------------------------
# Test 16 — Multi-turn helix → circle radius invariant to turn count
# ---------------------------------------------------------------------------

def test_helix_multi_turn_radius():
    """Helix radius in XY projection is independent of turn count."""
    R = 2.5
    for turns in (0.5, 1.0, 2.0):
        helix = _helix_nurbs(radius=R, pitch=0.5, turns=turns, n_samples=40)
        result = project_curve_to_plane(
            helix,
            plane_point=[0, 0, 0],
            plane_normal=[0, 0, 1],
        )
        cp2d = result.footprint_curve_2d.control_points
        radii = np.linalg.norm(cp2d, axis=1)
        assert np.allclose(radii, R, atol=1e-12), (
            f"Helix turns={turns}: projected radii should all be {R}; got {radii}"
        )


# ---------------------------------------------------------------------------
# Test 17 — Non-XY projection plane (project onto YZ plane)
# ---------------------------------------------------------------------------

def test_project_onto_yz_plane():
    """Project a curve onto the YZ plane (normal=(1,0,0)); X coords vanish."""
    cp = np.array([
        [3.0, 1.0, 0.0],
        [3.0, 2.0, 1.0],
        [3.0, 3.0, 0.0],
    ])
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    curve = NurbsCurve(degree=2, control_points=cp, knots=knots)

    result = project_curve_to_plane(
        curve,
        plane_point=[0, 0, 0],
        plane_normal=[1, 0, 0],
    )
    # The x=3 contribution is the depth; all projected CP depths should be 3
    assert abs(result.max_orig_depth - 3.0) < 1e-12
    # The 2-D UV footprint should match the YZ coordinates of the CPs
    # u_axis for n̂=(1,0,0): candidate=(0,1,0); u_raw=(0,1,0)-0·(1,0,0)=(0,1,0)
    # v_axis = n̂ × u_axis = (1,0,0)×(0,1,0) = (0,0,1)
    cp2d = result.footprint_curve_2d.control_points
    expected_u = cp[:, 1]   # y-coords
    expected_v = cp[:, 2]   # z-coords
    assert np.allclose(cp2d[:, 0], expected_u, atol=1e-12)
    assert np.allclose(cp2d[:, 1], expected_v, atol=1e-12)
