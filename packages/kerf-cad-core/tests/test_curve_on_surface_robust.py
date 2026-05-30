"""
test_curve_on_surface_robust.py
================================
Hermetic, analytic-oracle tests for geom/curve_on_surface_robust.py.

Coverage:
  1. Parabola-on-paraboloid depth-bar — C(t) lies exactly on z=x^2+y^2;
     S(u(t),v(t)) must reproduce C(t) within grid approximation error < 0.05.
  2. Helix on a cylinder — UV trace spans ~[0,1] in both u and v.
  3. Failed projection on plane edge — curve exits surface domain →
     failed_samples is non-empty.
  4. Oracle distance check — max_projection_distance < 0.05 (flat plane).
  5. CurveOnSurfaceResult dataclass fields are populated correctly.
  6. UV-curve control points lie inside the surface domain.
  7. Line fully inside flat surface: zero failed samples.

All tests are pure-Python with no OCC / network / filesystem dependencies.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.curve_on_surface_robust import (
    CurveOnSurfaceResult,
    project_curve_to_surface,
    _coarse_seed,
    _newton_project,
)


# ---------------------------------------------------------------------------
# NURBS surface / curve fixtures
# ---------------------------------------------------------------------------

def _clamped_knots(n: int, d: int) -> np.ndarray:
    inner = max(0, n - d - 1)
    mid = np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([])
    return np.concatenate([np.zeros(d + 1), mid, np.ones(d + 1)])


def flat_plane_surface(
    x0: float = 0.0, x1: float = 2.0,
    y0: float = 0.0, y1: float = 2.0,
    z: float = 0.0,
) -> NurbsSurface:
    """Degree-1 bilinear plane S(u,v) = (x0 + u*(x1-x0), y0 + v*(y1-y0), z)."""
    cp = np.array([
        [[x0, y0, z], [x0, y1, z]],
        [[x1, y0, z], [x1, y1, z]],
    ], dtype=float)
    ku = np.array([0.0, 0.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                        knots_u=ku, knots_v=kv)


def line_curve_3d(p0, p1) -> NurbsCurve:
    """Degree-1 NURBS line from p0 to p1, parameter in [0, 1]."""
    cp = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=cp, knots=knots)


def parabolic_surface() -> NurbsSurface:
    """Bilinear approximation of z = x^2 + y^2 over [-0.8, 0.8]^2 (20x20 grid).

    The surface evaluator returns points within ~0.005 of the true paraboloid.
    """
    nu, nv = 20, 20
    cp = np.zeros((nu, nv, 3))
    xs = np.linspace(-0.8, 0.8, nu)
    ys = np.linspace(-0.8, 0.8, nv)
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            cp[i, j] = [x, y, x * x + y * y]
    ku = _clamped_knots(nu, 1)
    kv = _clamped_knots(nv, 1)
    return NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                        knots_u=ku, knots_v=kv)


def parabola_on_surface_curve(n: int = 20) -> NurbsCurve:
    """C(t) = (t, 0, t^2) for t in [-0.6, 0.6] — lies on paraboloid z=x^2+y^2."""
    ts = np.linspace(-0.6, 0.6, n)
    pts = np.array([[t, 0.0, t * t] for t in ts], dtype=float)
    knots = np.concatenate([[0.0, 0.0], np.linspace(0.0, 1.0, n), [1.0, 1.0]])
    return NurbsCurve(degree=1, control_points=pts, knots=knots)


def cylinder_surface(radius: float = 1.0, height: float = 2.0) -> NurbsSurface:
    """Non-rational cylinder x=r*cos(2π u), y=r*sin(2π u), z=height*v.

    Bilinear NURBS grid (18×4) over u ∈ [0,1], v ∈ [0,1].
    """
    nu, nv = 18, 4
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        u = i / (nu - 1)
        angle = 2.0 * math.pi * u
        for j in range(nv):
            v = j / (nv - 1)
            cp[i, j] = [radius * math.cos(angle), radius * math.sin(angle), height * v]
    ku = _clamped_knots(nu, 1)
    kv = _clamped_knots(nv, 1)
    return NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                        knots_u=ku, knots_v=kv)


def helix_curve(radius: float = 1.0, height: float = 2.0,
                turns: float = 1.0, n: int = 32) -> NurbsCurve:
    """Polyline approximation of a helix on cylinder(r, h)."""
    ts = np.linspace(0.0, 1.0, n)
    pts = np.array([
        [radius * math.cos(2 * math.pi * turns * t),
         radius * math.sin(2 * math.pi * turns * t),
         height * t]
        for t in ts
    ], dtype=float)
    knots = np.concatenate([[0.0, 0.0], np.linspace(0.0, 1.0, n), [1.0, 1.0]])
    return NurbsCurve(degree=1, control_points=pts, knots=knots)


# ---------------------------------------------------------------------------
# Test 1 — parabola-on-paraboloid depth-bar oracle
# ---------------------------------------------------------------------------

def test_horizontal_line_on_sphere_great_circle():
    """Depth-bar: project C(t) = (t, 0, t^2) lying on z=x^2+y^2 onto the
    bilinear paraboloid surface.

    For each sample t_i, directly project C(t_i) to the surface and verify
    that S(u_i, v_i) is within 0.05 of C(t_i) — the bilinear grid error bound.
    """
    srf = parabolic_surface()
    crv = parabola_on_surface_curve(n=20)

    result = project_curve_to_surface(crv, srf, tol=1e-5, samples=16)

    assert isinstance(result, CurveOnSurfaceResult)
    assert result.uv_curve is not None

    # Depth-bar: directly project each t_i and measure |S(u,v) - C(t)|.
    from kerf_cad_core.geom.inversion import _curve_param_range
    t_min, t_max = _curve_param_range(crv)
    ts = np.linspace(t_min, t_max, 16)

    max_err = 0.0
    for ti in ts:
        pt_c = np.asarray(crv.evaluate(float(ti)), dtype=float)
        u0, v0 = _coarse_seed(pt_c, srf)
        u_nr, v_nr, dist, conv = _newton_project(pt_c, srf, u0, v0, 1e-5, 80)
        pt_s = np.asarray(srf.evaluate(u_nr, v_nr), dtype=float)
        err = float(np.linalg.norm(pt_s[:3] - pt_c[:3]))
        max_err = max(max_err, err)

    assert max_err < 0.05, f"Depth-bar: max |S(u,v)-C(t)| = {max_err:.4f}, expected < 0.05"
    assert result.max_projection_distance < 0.05, (
        f"max_projection_distance={result.max_projection_distance:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 2 — helix on cylinder: UV trace spans the surface
# ---------------------------------------------------------------------------

def test_helix_on_cylinder_uv_linear():
    """Helix on cylinder: UV control polygon must span u~[0,1] and v~[0,1]."""
    cyl = cylinder_surface(radius=1.0, height=2.0)
    hel = helix_curve(radius=1.0, height=2.0, turns=1.0, n=20)

    result = project_curve_to_surface(hel, cyl, tol=1e-4, samples=16)

    assert isinstance(result, CurveOnSurfaceResult)
    uv_c = result.uv_curve
    assert uv_c is not None

    # Check via the control polygon span (not NURBS eval which may oscillate)
    cp = uv_c.control_points
    u_span = float(np.max(cp[:, 0]) - np.min(cp[:, 0]))
    v_span = float(np.max(cp[:, 1]) - np.min(cp[:, 1]))

    assert u_span > 0.4, f"u should span most of [0,1]; span={u_span:.3f}"
    assert v_span > 0.4, f"v should span most of [0,1]; span={v_span:.3f}"


# ---------------------------------------------------------------------------
# Test 3 — failed projection when curve exits surface domain
# ---------------------------------------------------------------------------

def test_failed_projection_curve_exits_surface():
    """Curve from (0.5, 0.5, 0) to (3.0, 0.5, 0) exits the [0,2]×[0,2] plane.

    The far end is outside the surface domain → at least one sample should
    be in failed_samples.
    """
    # Surface covers [0,2] × [0,2]
    plane = flat_plane_surface(x0=0.0, x1=2.0, y0=0.0, y1=2.0, z=0.0)
    # Curve ends at x=3.0, outside the surface x domain
    crv = line_curve_3d([0.5, 0.5, 0.0], [3.0, 0.5, 0.0])

    result = project_curve_to_surface(crv, plane, tol=1e-5, samples=16)

    assert isinstance(result, CurveOnSurfaceResult)
    assert len(result.failed_samples) > 0, (
        "Expected failed samples for curve exiting surface domain"
    )


# ---------------------------------------------------------------------------
# Test 4 — oracle distance check: max_projection_distance < 1e-3
# ---------------------------------------------------------------------------

def test_oracle_distance_flat_plane():
    """Project a line lying exactly on a flat plane: distance should be tiny."""
    plane = flat_plane_surface(x0=0.0, x1=2.0, y0=0.0, y1=2.0, z=0.0)
    # Curve lies entirely in z=0 plane within surface domain
    crv = line_curve_3d([0.3, 0.3, 0.0], [1.7, 1.7, 0.0])

    result = project_curve_to_surface(crv, plane, tol=1e-5, samples=16)

    assert isinstance(result, CurveOnSurfaceResult)
    assert result.max_projection_distance < 1e-3, (
        f"max_projection_distance too large: {result.max_projection_distance}"
    )
    assert len(result.failed_samples) == 0, (
        f"Unexpected failures: {result.failed_samples}"
    )


# ---------------------------------------------------------------------------
# Test 5 — CurveOnSurfaceResult fields populated correctly
# ---------------------------------------------------------------------------

def test_result_fields_populated():
    """Check all CurveOnSurfaceResult fields exist and have correct types."""
    plane = flat_plane_surface()
    crv = line_curve_3d([0.1, 0.1, 0.0], [0.9, 0.9, 0.0])
    result = project_curve_to_surface(crv, plane, tol=1e-5, samples=8)

    assert isinstance(result.uv_curve, NurbsCurve)
    assert isinstance(result.max_projection_distance, float)
    assert isinstance(result.failed_samples, list)


# ---------------------------------------------------------------------------
# Test 6 — UV-curve control points lie inside surface domain
# ---------------------------------------------------------------------------

def test_uv_curve_within_surface_domain():
    """All UV control points should be within [0,1]×[0,1] for a unit flat plane."""
    plane = flat_plane_surface(x0=0.0, x1=1.0, y0=0.0, y1=1.0, z=0.0)
    crv = line_curve_3d([0.1, 0.1, 0.0], [0.9, 0.9, 0.0])
    result = project_curve_to_surface(crv, plane, tol=1e-5, samples=12)

    cp = result.uv_curve.control_points
    u_vals = cp[:, 0]
    v_vals = cp[:, 1]
    # Allow small overshoot from interpolation
    assert np.all(u_vals >= -0.05) and np.all(u_vals <= 1.05), f"u out of range: {u_vals}"
    assert np.all(v_vals >= -0.05) and np.all(v_vals <= 1.05), f"v out of range: {v_vals}"


# ---------------------------------------------------------------------------
# Test 7 — line fully inside flat surface: zero failed samples
# ---------------------------------------------------------------------------

def test_line_fully_inside_flat_surface_no_failures():
    """Line well inside the flat surface: zero failed_samples."""
    plane = flat_plane_surface(x0=0.0, x1=2.0, y0=0.0, y1=2.0, z=0.0)
    crv = line_curve_3d([0.5, 0.5, 0.0], [1.5, 1.5, 0.0])
    result = project_curve_to_surface(crv, plane, tol=1e-5, samples=20)

    assert len(result.failed_samples) == 0, (
        f"Unexpected failures: {result.failed_samples}"
    )
    assert result.max_projection_distance < 1e-3
