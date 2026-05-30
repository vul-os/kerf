"""
test_curve_projection.py
========================
Hermetic, analytic-oracle tests for geom/curve_projection.py (GK-P projection):

  project_point_to_curve   — Newton + arc-length fallback
  project_point_to_surface — 2-D Newton
  distance_curve_to_curve  — sampling + Newton refinement

All tests assert closed-form quantities with analytic oracles.
No network, no external binaries, no OCC.

Coverage (4 required + extras):
  1. Point-ON-curve        : P exactly on a NURBS line at t=0.5 → parameter≈0.5, dist≈0.
  2. Point-OFF-curve       : P above a NURBS line in 3D → foot is perpendicular, dist matches.
  3. Point-on-sphere       : P outside a NURBS sphere → project_point_to_surface returns
                             closest point on sphere; dist = |P-centre| - radius.
  4. Distance curve-curve  : two crossing lines → dist≈0; two parallel lines → dist=1.0.
  5. ProjectionResult type : fields populated correctly.
  6. Arc-length fallback   : extreme off-curve point still converges to correct foot.
  7. Quadratic arc         : project onto a parabolic arc; foot verified by perpendicularity.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.curve_projection import (
    ProjectionResult,
    project_point_to_curve,
    project_point_to_surface,
    distance_curve_to_curve,
)


# ---------------------------------------------------------------------------
# NURBS fixtures
# ---------------------------------------------------------------------------

def line_curve(p0, p1) -> NurbsCurve:
    """Degree-1 NURBS line from p0 to p1, parameter in [0, 1]."""
    cp = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=cp, knots=knots)


def quadratic_arc(p0, p1, p2) -> NurbsCurve:
    """Degree-2 (Bézier) arc through three control points."""
    cp = np.array([p0, p1, p2], dtype=float)
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=2, control_points=cp, knots=knots)


def nurbs_sphere(centre, radius) -> NurbsSurface:
    """Exact rational sphere (revolved rational half-circle) centred at ``centre``.

    Uses the standard 9×5 (degree-2 × degree-2) rational representation from
    Piegl & Tiller §8.1.  Every point on the surface satisfies
    |S(u,v) - centre| = radius to ≈ 1e-11 (verified in test_inversion.py).
    """
    c = np.asarray(centre, dtype=float)
    r = float(radius)
    w = math.sqrt(2.0) / 2.0

    # Profile: half-circle from (0,0,+1) through (1,0,0) to (0,0,-1)
    # scaled by radius; rows go south → north.
    prof = np.array([[0, 0, 1], [1, 0, 1], [1, 0, 0],
                     [1, 0, -1], [0, 0, -1]], dtype=float)
    pw = np.array([1.0, w, 1.0, w, 1.0])

    cw = np.array([1.0, w, 1.0, w, 1.0, w, 1.0, w, 1.0])
    cir = np.array([
        [1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0],
        [-1, -1], [0, -1], [1, -1], [1, 0],
    ], dtype=float)

    nu, nv = 9, 5
    cp = np.zeros((nu, nv, 4))
    for i in range(nu):
        for j in range(nv):
            rad = prof[j, 0] * r
            z = prof[j, 2] * r
            W = cw[i] * pw[j]
            x = rad * cir[i, 0] + c[0]
            y = rad * cir[i, 1] + c[1]
            zz = z + c[2]
            cp[i, j, :3] = np.array([x, y, zz]) * W
            cp[i, j, 3] = W

    ku = np.array([0, 0, 0, .25, .25, .5, .5, .75, .75, 1, 1, 1.0])
    kv = np.array([0, 0, 0, .5, .5, 1, 1, 1.0])
    return NurbsSurface(degree_u=2, degree_v=2, control_points=cp,
                        knots_u=ku, knots_v=kv)


def flat_surface_xy(
    x0: float = 0.0, x1: float = 1.0,
    y0: float = 0.0, y1: float = 1.0,
    z: float = 0.0,
    nu: int = 3, nv: int = 3,
) -> NurbsSurface:
    """Flat bilinear surface in z=const plane."""
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [
                x0 + (x1 - x0) * i / (nu - 1),
                y0 + (y1 - y0) * j / (nv - 1),
                z,
            ]
    def _mk(n, d):
        inner = max(0, n - d - 1)
        kn = np.concatenate([
            np.zeros(d + 1),
            np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
            np.ones(d + 1),
        ])
        return kn
    return NurbsSurface(
        degree_u=1, degree_v=1, control_points=cp,
        knots_u=_mk(nu, 1), knots_v=_mk(nv, 1),
    )


# ---------------------------------------------------------------------------
# Test 1 — Point exactly ON the curve at t = 0.5
# ---------------------------------------------------------------------------

def test_project_point_on_curve_recovers_parameter():
    """P on the curve at u=0.5 → parameter≈0.5, distance≈0."""
    curve = line_curve([0.0, 0.0, 0.0], [2.0, 0.0, 0.0])
    # Point at midway along the X-axis line (u=0.5 → x=1.0).
    P = np.array([1.0, 0.0, 0.0])
    res = project_point_to_curve(P, curve, tol=1e-9)

    assert isinstance(res, ProjectionResult), "must return ProjectionResult"
    assert abs(res.parameter - 0.5) < 1e-9, f"parameter={res.parameter}"
    assert res.distance < 1e-9, f"distance={res.distance}"
    foot = np.asarray(res.point_on_curve)
    assert np.linalg.norm(foot - P) < 1e-9


# ---------------------------------------------------------------------------
# Test 2 — Point OFF the curve — perpendicular foot
# ---------------------------------------------------------------------------

def test_project_point_off_curve_perpendicular_foot():
    """P above a line in 3D → foot is the perpendicular; distance matches."""
    # Line along the X-axis from x=0 to x=4.
    curve = line_curve([0.0, 0.0, 0.0], [4.0, 0.0, 0.0])
    # Query point above x=2 in the Y-direction at height 3.
    P = np.array([2.0, 3.0, 0.0])

    # Analytic: foot is (2.0, 0.0, 0.0), distance = 3.0.
    foot_analytic = np.array([2.0, 0.0, 0.0])
    dist_analytic = 3.0

    res = project_point_to_curve(P, curve, tol=1e-9)
    assert res.distance < dist_analytic + 1e-9
    foot = np.asarray(res.point_on_curve)
    assert np.linalg.norm(foot - foot_analytic) < 1e-9, f"foot={foot}"
    assert abs(res.distance - dist_analytic) < 1e-9, f"dist={res.distance}"


# ---------------------------------------------------------------------------
# Test 3 — Point outside a NURBS sphere
# ---------------------------------------------------------------------------

def test_project_point_to_sphere_surface():
    """P outside a rational sphere → foot on the sphere along P-centre; dist = |P-c| - r."""
    centre = np.array([0.0, 0.0, 0.0])
    radius = 1.0
    sphere = nurbs_sphere(centre, radius)

    # Query point along (1, 1, 1) direction at distance 3 from centre.
    direction = np.array([1.0, 1.0, 1.0]) / math.sqrt(3.0)
    P = direction * 3.0

    # Analytic: foot = direction * radius, distance = 3 - 1 = 2.
    foot_analytic = direction * radius
    dist_analytic = 3.0 - radius

    res = project_point_to_surface(P, sphere, tol=1e-6)
    foot = np.asarray(res.point_on_curve)

    # Distance check.
    assert abs(res.distance - dist_analytic) < 1e-4, (
        f"distance={res.distance:.8f}, expected {dist_analytic}")

    # Foot should be near the analytic foot.
    assert np.linalg.norm(foot - foot_analytic) < 1e-3, (
        f"foot={foot}, expected≈{foot_analytic}")

    # Foot should lie on the sphere (|foot - centre| ≈ radius).
    assert abs(float(np.linalg.norm(foot - centre)) - radius) < 1e-3, (
        f"|foot - centre| = {np.linalg.norm(foot - centre):.8f}")


# ---------------------------------------------------------------------------
# Test 4a — distance_curve_to_curve: crossing lines → distance ≈ 0
# ---------------------------------------------------------------------------

def test_distance_crossing_lines_zero():
    """Two lines that cross at (0.5, 0.5, 0) → minimum distance ≈ 0."""
    # Line A: from (0,0,0) to (1,1,0)
    # Line B: from (1,0,0) to (0,1,0)  — they cross at (0.5, 0.5, 0)
    cA = line_curve([0.0, 0.0, 0.0], [1.0, 1.0, 0.0])
    cB = line_curve([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])

    d = distance_curve_to_curve(cA, cB, n_samples=20)
    assert d < 1e-6, f"distance={d}"


# ---------------------------------------------------------------------------
# Test 4b — distance_curve_to_curve: parallel lines → distance = 1.0
# ---------------------------------------------------------------------------

def test_distance_parallel_lines_unit():
    """Two parallel lines at z=0 and z=1 → minimum distance = 1.0."""
    cA = line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    cB = line_curve([0.0, 0.0, 1.0], [1.0, 0.0, 1.0])

    d = distance_curve_to_curve(cA, cB, n_samples=20)
    assert abs(d - 1.0) < 1e-9, f"distance={d}"


# ---------------------------------------------------------------------------
# Test 5 — ProjectionResult fields
# ---------------------------------------------------------------------------

def test_projection_result_fields():
    """ProjectionResult must expose parameter, point_on_curve, distance, converged."""
    curve = line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    res = project_point_to_curve(np.array([0.25, 0.0, 0.0]), curve)

    assert hasattr(res, "parameter")
    assert hasattr(res, "point_on_curve")
    assert hasattr(res, "distance")
    assert hasattr(res, "converged")
    assert isinstance(res.converged, bool)
    assert isinstance(res.distance, float)
    assert res.distance >= 0.0


# ---------------------------------------------------------------------------
# Test 6 — Arc-length fallback on far-off point (robustness)
# ---------------------------------------------------------------------------

def test_arc_length_fallback_far_point():
    """A point very far from the curve still finds the correct foot."""
    # Line from (0,0,0) to (1,0,0); query at (0.7, 1000.0, 0).
    # Foot should be near (0.7, 0, 0), distance ≈ 1000.
    curve = line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    P = np.array([0.7, 1000.0, 0.0])

    res = project_point_to_curve(P, curve, tol=1e-9)
    foot = np.asarray(res.point_on_curve)
    foot_analytic = np.array([0.7, 0.0, 0.0])

    assert np.linalg.norm(foot - foot_analytic) < 1e-9, f"foot={foot}"
    assert abs(res.distance - 1000.0) < 1e-6, f"dist={res.distance}"


# ---------------------------------------------------------------------------
# Test 7 — Quadratic arc: perpendicularity at foot
# ---------------------------------------------------------------------------

def test_project_onto_quadratic_arc_perpendicular():
    """Foot on a quadratic Bézier arc satisfies (C(t) - P) ⊥ C'(t)."""
    # Parabola-like arc: (0,0,0), (1,2,0), (2,0,0)
    arc = quadratic_arc([0.0, 0.0, 0.0], [1.0, 2.0, 0.0], [2.0, 0.0, 0.0])
    # Query point above the midpoint.
    P = np.array([1.0, 3.0, 0.0])

    res = project_point_to_curve(P, arc, tol=1e-9)

    # The residual (C(t) - P) must be perpendicular to the tangent C'(t).
    from kerf_cad_core.geom.inversion import _curve_ders
    derivs = _curve_ders(arc, res.parameter, 1)
    C = derivs[0]
    C1 = derivs[1]
    r = C - P
    dot = abs(float(np.dot(r, C1)))
    c1n = float(np.linalg.norm(C1))
    d = float(np.linalg.norm(r))
    # Normalised cosine should be < tol + numerical noise.
    cosine = dot / (c1n * max(d, 1e-15)) if c1n > 1e-12 else 0.0
    assert cosine < 1e-6, f"perpendicularity cosine={cosine:.3e}"


# ---------------------------------------------------------------------------
# Test 8 — project_point_to_surface on flat surface
# ---------------------------------------------------------------------------

def test_project_to_flat_surface():
    """P above a flat z=0 surface → foot=(Px, Py, 0), dist=|Pz|."""
    surf = flat_surface_xy(0.0, 1.0, 0.0, 1.0, z=0.0)
    P = np.array([0.4, 0.6, 2.5])

    res = project_point_to_surface(P, surf, tol=1e-9)
    foot = np.asarray(res.point_on_curve)
    foot_analytic = np.array([0.4, 0.6, 0.0])

    assert np.linalg.norm(foot - foot_analytic) < 1e-6, f"foot={foot}"
    assert abs(res.distance - 2.5) < 1e-6, f"dist={res.distance}"
    uv = res.parameter
    assert isinstance(uv, tuple) and len(uv) == 2, f"parameter must be (u,v), got {uv}"
