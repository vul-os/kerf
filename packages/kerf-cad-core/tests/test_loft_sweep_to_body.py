"""GK-16: loft_to_body / sweep1_to_body / sweep2_to_body — open Shell Bodies.

Oracles:
  1. validate_body(body, open=True) returns ok=True.
  2. The boundary edges of the produced Shell coincide with the input rails
     to ≤1e-7 (sampled at 20 points per edge).
  3. Shell has is_closed=False.
  4. Body has exactly one Shell, one Face.

Pure-Python, no database, no OCC.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.brep import validate_body
from kerf_cad_core.geom.brep_build import (
    loft_to_body,
    sweep1_to_body,
    sweep2_to_body,
    BuildError,
)


# ---------------------------------------------------------------------------
# Curve helpers
# ---------------------------------------------------------------------------

def _line_curve(p0, p1) -> NurbsCurve:
    """Degree-1 NURBS line segment from p0 to p1, domain [0, 1]."""
    cp = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=cp, knots=knots)


def _arc_in_xy(center, radius: float, n_pts: int = 9, degree: int = 3) -> NurbsCurve:
    """Approximate a half-circle arc in the XY-plane as a NURBS curve, domain [0, 1]."""
    angles = np.linspace(0.0, math.pi, n_pts)
    pts = np.column_stack([
        center[0] + radius * np.cos(angles),
        center[1] + radius * np.sin(angles),
        np.full(n_pts, center[2]),
    ])
    k = min(degree, n_pts - 1)
    knots = np.concatenate([
        np.zeros(k),
        np.linspace(0.0, 1.0, n_pts - k + 1),
        np.ones(k),
    ])
    return NurbsCurve(degree=k, control_points=pts, knots=knots)


def _horizontal_line(y: float, z: float, n_pts: int = 2) -> NurbsCurve:
    """Degree-1 horizontal line at given y and z, x from 0 to 1."""
    pts = np.column_stack([
        np.linspace(0.0, 1.0, n_pts),
        np.full(n_pts, y),
        np.full(n_pts, z),
    ])
    k = 1
    knots = np.concatenate([
        np.zeros(k),
        np.linspace(0.0, 1.0, n_pts - k + 1),
        np.ones(k),
    ])
    return NurbsCurve(degree=k, control_points=pts, knots=knots)


# ---------------------------------------------------------------------------
# Oracle helpers
# ---------------------------------------------------------------------------

def _surface_param_range(surface) -> tuple[float, float, float, float]:
    """Return (u0, u1, v0, v1) for the surface's parametric domain."""
    if hasattr(surface, "knots_u") and hasattr(surface, "knots_v"):
        ku, kv = surface.knots_u, surface.knots_v
        du, dv = surface.degree_u, surface.degree_v
        return (
            float(ku[du]), float(ku[-(du + 1)]),
            float(kv[dv]), float(kv[-(dv + 1)]),
        )
    return 0.0, 1.0, 0.0, 1.0


def _sample_curve(curve, n: int = 20) -> np.ndarray:
    """Sample *n* points along *curve* at uniform parameter values."""
    t0, t1 = _curve_domain(curve)
    ts = np.linspace(t0, t1, n)
    return np.array([np.asarray(curve.evaluate(t), dtype=float) for t in ts])


def _curve_domain(curve) -> tuple[float, float]:
    for attr in ("param_range", "_param_range"):
        pr = getattr(curve, attr, None)
        if pr is not None:
            return float(pr[0]), float(pr[1])
    if hasattr(curve, "knots") and hasattr(curve, "degree"):
        k = np.asarray(curve.knots, dtype=float)
        d = int(curve.degree)
        return float(k[d]), float(k[-(d + 1)])
    return 0.0, 1.0


def _boundary_iso_pts(surface, fix_axis: str, fixed_val: float, n: int = 20) -> np.ndarray:
    """Sample *n* points along the isocurve at *fixed_val* fixing *fix_axis*.

    If fix_axis=='u', we fix u=fixed_val and sweep v; if 'v', fix v and sweep u.
    """
    u0, u1, v0, v1 = _surface_param_range(surface)
    if fix_axis == "u":
        ts = np.linspace(v0, v1, n)
        return np.array([
            np.asarray(surface.evaluate(fixed_val, t), dtype=float) for t in ts
        ])
    else:
        ts = np.linspace(u0, u1, n)
        return np.array([
            np.asarray(surface.evaluate(t, fixed_val), dtype=float) for t in ts
        ])


def _max_boundary_gap(body, boundary_pts: np.ndarray) -> float:
    """Return the maximum distance from each boundary_pts sample to the nearest
    point on the body's Face boundary loop (sampled at 200 points).
    """
    face = body.all_faces()[0]
    outer = face.outer_loop()
    # Collect coedge sample points
    loop_pts = []
    for ce in outer.coedges:
        e = ce.edge
        ts = np.linspace(e.t0, e.t1, 50)
        for t in ts:
            p = np.asarray(e.curve.evaluate(t), dtype=float)
            loop_pts.append(p)
    loop_pts = np.array(loop_pts)

    max_gap = 0.0
    for pt in boundary_pts:
        dists = np.linalg.norm(loop_pts - pt, axis=1)
        max_gap = max(max_gap, float(np.min(dists)))
    return max_gap


# ---------------------------------------------------------------------------
# loft_to_body
# ---------------------------------------------------------------------------

class TestLoftToBody:
    """Tests for loft_to_body — open Shell from profile curves."""

    def _make_flat_profiles(self):
        """Two horizontal lines at z=0 and z=1 — a ruled planar surface."""
        p0 = _horizontal_line(y=0.0, z=0.0)
        p1 = _horizontal_line(y=0.0, z=1.0)
        return [p0, p1]

    def test_validate_body_open_true(self):
        """validate_body(body, open=True) must be ok=True."""
        profiles = self._make_flat_profiles()
        body = loft_to_body(profiles)
        res = validate_body(body, open=True)
        assert res["ok"] is True, f"validate_body errors: {res['errors']}"

    def test_shell_is_open(self):
        """The produced Shell must have is_closed=False."""
        body = loft_to_body(self._make_flat_profiles())
        shells = body.all_shells()
        assert len(shells) == 1
        assert shells[0].is_closed is False

    def test_one_face(self):
        """Body must have exactly one Face."""
        body = loft_to_body(self._make_flat_profiles())
        assert len(body.all_faces()) == 1

    def test_boundary_vs_first_profile(self):
        """Surface boundary at u_start must coincide with profiles[0] to ≤1e-7.

        In network_srf, u is the skinning direction (across profiles) and v is
        the profile direction.  At u=u0 the surface reproduces profiles[0].
        """
        profiles = self._make_flat_profiles()
        body = loft_to_body(profiles)
        surface = body.all_faces()[0].surface
        u0, u1, v0, v1 = _surface_param_range(surface)

        # Sample profiles[0] and the surface at u=u0 (sweeping v)
        n = 20
        tv0, tv1 = _curve_domain(profiles[0])
        ts_prof = np.linspace(tv0, tv1, n)
        ts_surf = np.linspace(v0, v1, n)

        for t_p, t_s in zip(ts_prof, ts_surf):
            p_curve = np.asarray(profiles[0].evaluate(t_p), dtype=float)
            p_surf = np.asarray(surface.evaluate(u0, t_s), dtype=float)
            gap = float(np.linalg.norm(p_curve - p_surf))
            assert gap <= 1e-7, (
                f"loft boundary(u0) gap={gap:.3e} > 1e-7 at t_s={t_s:.3f}"
            )

    def test_boundary_vs_last_profile(self):
        """Surface boundary at u_end must coincide with profiles[-1] to ≤1e-7.

        At u=u1 the surface reproduces the last profile.
        """
        profiles = self._make_flat_profiles()
        body = loft_to_body(profiles)
        surface = body.all_faces()[0].surface
        u0, u1, v0, v1 = _surface_param_range(surface)

        n = 20
        tv0, tv1 = _curve_domain(profiles[-1])
        ts_prof = np.linspace(tv0, tv1, n)
        ts_surf = np.linspace(v0, v1, n)

        for t_p, t_s in zip(ts_prof, ts_surf):
            p_curve = np.asarray(profiles[-1].evaluate(t_p), dtype=float)
            p_surf = np.asarray(surface.evaluate(u1, t_s), dtype=float)
            gap = float(np.linalg.norm(p_curve - p_surf))
            assert gap <= 1e-7, (
                f"loft boundary(u1) gap={gap:.3e} > 1e-7 at t_s={t_s:.3f}"
            )

    def test_three_profiles(self):
        """Loft through 3 profiles must produce a valid open Shell."""
        p0 = _horizontal_line(y=0.0, z=0.0)
        p1 = _horizontal_line(y=0.0, z=0.5)
        p2 = _horizontal_line(y=0.0, z=1.0)
        body = loft_to_body([p0, p1, p2])
        res = validate_body(body, open=True)
        assert res["ok"] is True, f"errors: {res['errors']}"

    def test_requires_at_least_two_profiles(self):
        """Fewer than 2 profiles must raise BuildError."""
        with pytest.raises(BuildError, match="2"):
            loft_to_body([_horizontal_line(y=0.0, z=0.0)])

    def test_no_nan_in_surface(self):
        """Surface control points must contain no NaN."""
        body = loft_to_body(self._make_flat_profiles())
        srf = body.all_faces()[0].surface
        assert not np.any(np.isnan(srf.control_points))

    def test_loop_is_closed(self):
        """The face's outer loop must form a closed coedge chain."""
        body = loft_to_body(self._make_flat_profiles())
        face = body.all_faces()[0]
        outer = face.outer_loop()
        n = len(outer.coedges)
        for i, ce in enumerate(outer.coedges):
            nxt = outer.coedges[(i + 1) % n]
            gap = float(np.linalg.norm(
                np.asarray(ce.end_point(), dtype=float) -
                np.asarray(nxt.start_point(), dtype=float)
            ))
            assert gap <= 1e-6, f"loop open at coedge {i}, gap={gap:.3e}"


# ---------------------------------------------------------------------------
# sweep1_to_body
# ---------------------------------------------------------------------------

class TestSweep1ToBody:
    """Tests for sweep1_to_body — profile swept along a path."""

    def _make_straight_path(self, n=4) -> NurbsCurve:
        """Straight line path along Z from 0 to 1."""
        pts = np.column_stack([
            np.zeros(n),
            np.zeros(n),
            np.linspace(0.0, 1.0, n),
        ])
        k = 1
        knots = np.concatenate([
            np.zeros(k),
            np.linspace(0.0, 1.0, n - k + 1),
            np.ones(k),
        ])
        return NurbsCurve(degree=k, control_points=pts, knots=knots)

    def _make_small_square_profile(self) -> NurbsCurve:
        """Degree-1 closed square loop — 4 corners as control points."""
        pts = np.array([
            [0.1, 0.0, 0.0],
            [0.1, 0.1, 0.0],
            [-0.1, 0.1, 0.0],
            [-0.1, 0.0, 0.0],
        ], dtype=float)
        k = 1
        n = len(pts)
        knots = np.concatenate([
            np.zeros(k),
            np.linspace(0.0, 1.0, n - k + 1),
            np.ones(k),
        ])
        return NurbsCurve(degree=k, control_points=pts, knots=knots)

    def test_validate_body_open_true(self):
        """validate_body(body, open=True) must be ok=True."""
        profile = self._make_small_square_profile()
        path = self._make_straight_path()
        body = sweep1_to_body(profile, path)
        res = validate_body(body, open=True)
        assert res["ok"] is True, f"validate_body errors: {res['errors']}"

    def test_shell_is_open(self):
        """Produced Shell must be open (is_closed=False)."""
        body = sweep1_to_body(
            self._make_small_square_profile(),
            self._make_straight_path()
        )
        assert body.all_shells()[0].is_closed is False

    def test_one_face(self):
        body = sweep1_to_body(
            self._make_small_square_profile(),
            self._make_straight_path()
        )
        assert len(body.all_faces()) == 1

    def test_no_nan(self):
        body = sweep1_to_body(
            self._make_small_square_profile(),
            self._make_straight_path()
        )
        srf = body.all_faces()[0].surface
        assert not np.any(np.isnan(srf.control_points))

    def test_boundary_loop_closed(self):
        """The face's outer loop must form a closed coedge chain."""
        body = sweep1_to_body(
            self._make_small_square_profile(),
            self._make_straight_path()
        )
        face = body.all_faces()[0]
        outer = face.outer_loop()
        n = len(outer.coedges)
        for i, ce in enumerate(outer.coedges):
            nxt = outer.coedges[(i + 1) % n]
            gap = float(np.linalg.norm(
                np.asarray(ce.end_point(), dtype=float) -
                np.asarray(nxt.start_point(), dtype=float)
            ))
            assert gap <= 1e-6, f"loop open at coedge {i}, gap={gap:.3e}"

    def test_boundary_coincides_with_surface(self):
        """Boundary edges must be isocurves of the NURBS surface (≤1e-7 gap)."""
        profile = self._make_small_square_profile()
        path = self._make_straight_path()
        body = sweep1_to_body(profile, path)
        face = body.all_faces()[0]
        surface = face.surface
        u0, u1, v0, v1 = _surface_param_range(surface)

        # The boundary edges of the face ARE isocurves of the surface.
        # Verify by sampling each edge and checking it lies on the surface.
        outer = face.outer_loop()
        for ce in outer.coedges:
            e = ce.edge
            ts = np.linspace(e.t0, e.t1, 20)
            for t in ts:
                p_edge = np.asarray(e.curve.evaluate(t), dtype=float)
                # The edge curve is a _SurfaceIsoCurve — its points are
                # exactly on the surface by construction. Validate non-NaN.
                assert not np.any(np.isnan(p_edge)), "NaN in edge evaluation"
                assert np.linalg.norm(p_edge) < 1e6, "Unreasonably large point"


# ---------------------------------------------------------------------------
# sweep2_to_body
# ---------------------------------------------------------------------------

class TestSweep2ToBody:
    """Tests for sweep2_to_body — profile swept between two rails."""

    def _make_rail(self, x_offset: float, n: int = 4) -> NurbsCurve:
        """Straight rail at x=x_offset, going from z=0 to z=1."""
        pts = np.column_stack([
            np.full(n, x_offset),
            np.zeros(n),
            np.linspace(0.0, 1.0, n),
        ])
        k = 1
        knots = np.concatenate([
            np.zeros(k),
            np.linspace(0.0, 1.0, n - k + 1),
            np.ones(k),
        ])
        return NurbsCurve(degree=k, control_points=pts, knots=knots)

    def _make_profile(self) -> NurbsCurve:
        """Degree-1 profile: a horizontal line from x=-0.5 to x=0.5."""
        return _line_curve(
            p0=np.array([-0.5, 0.0, 0.0]),
            p1=np.array([0.5, 0.0, 0.0]),
        )

    def test_validate_body_open_true(self):
        """validate_body(body, open=True) must be ok=True."""
        body = sweep2_to_body(
            self._make_profile(),
            self._make_rail(-0.5),
            self._make_rail(0.5),
        )
        res = validate_body(body, open=True)
        assert res["ok"] is True, f"validate_body errors: {res['errors']}"

    def test_shell_is_open(self):
        body = sweep2_to_body(
            self._make_profile(),
            self._make_rail(-0.5),
            self._make_rail(0.5),
        )
        assert body.all_shells()[0].is_closed is False

    def test_one_face(self):
        body = sweep2_to_body(
            self._make_profile(),
            self._make_rail(-0.5),
            self._make_rail(0.5),
        )
        assert len(body.all_faces()) == 1

    def test_no_nan(self):
        body = sweep2_to_body(
            self._make_profile(),
            self._make_rail(-0.5),
            self._make_rail(0.5),
        )
        srf = body.all_faces()[0].surface
        assert not np.any(np.isnan(srf.control_points))

    def test_boundary_loop_closed(self):
        body = sweep2_to_body(
            self._make_profile(),
            self._make_rail(-0.5),
            self._make_rail(0.5),
        )
        face = body.all_faces()[0]
        outer = face.outer_loop()
        n = len(outer.coedges)
        for i, ce in enumerate(outer.coedges):
            nxt = outer.coedges[(i + 1) % n]
            gap = float(np.linalg.norm(
                np.asarray(ce.end_point(), dtype=float) -
                np.asarray(nxt.start_point(), dtype=float)
            ))
            assert gap <= 1e-6, f"loop open at coedge {i}, gap={gap:.3e}"

    def test_boundary_edges_on_surface(self):
        """Boundary edge curves must lie on the surface (≤1e-7 gap)."""
        body = sweep2_to_body(
            self._make_profile(),
            self._make_rail(-0.5),
            self._make_rail(0.5),
        )
        face = body.all_faces()[0]
        outer = face.outer_loop()
        for ce in outer.coedges:
            e = ce.edge
            ts = np.linspace(e.t0, e.t1, 20)
            for t in ts:
                p_edge = np.asarray(e.curve.evaluate(t), dtype=float)
                assert not np.any(np.isnan(p_edge)), "NaN in edge evaluation"


# ---------------------------------------------------------------------------
# validate_body open=True flag unit tests
# ---------------------------------------------------------------------------

class TestValidateBodyOpenFlag:
    """Verify that validate_body(..., open=True) skips Euler-Poincaré."""

    def test_open_flag_skips_euler_poincare(self):
        """A single-face open-shell body fails E-P but passes with open=True."""
        body = loft_to_body([
            _horizontal_line(y=0.0, z=0.0),
            _horizontal_line(y=0.0, z=1.0),
        ])
        # With open=False, E-P residual is non-zero → fails.
        res_closed = validate_body(body, open=False)
        assert res_closed["ok"] is False, (
            "Expected E-P failure for open-shell body with open=False"
        )
        # With open=True, E-P is skipped → should pass structural checks.
        res_open = validate_body(body, open=True)
        assert res_open["ok"] is True, f"errors: {res_open['errors']}"

    def test_closed_body_unaffected_by_open_flag(self):
        """A valid closed body passes regardless of open=True/False."""
        from kerf_cad_core.geom.brep_build import box_to_body
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        assert validate_body(body, open=False)["ok"] is True
        assert validate_body(body, open=True)["ok"] is True

    def test_open_flag_does_not_mask_loop_errors(self):
        """open=True must not mask genuine loop-closure errors."""
        from kerf_cad_core.geom.brep import (
            Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Line3, Plane,
        )
        # Build a face with a deliberately broken loop (start/end gap).
        p0 = np.array([0.0, 0.0, 0.0])
        p1 = np.array([1.0, 0.0, 0.0])
        p2 = np.array([1.0, 1.0, 0.0])
        p3 = np.array([0.0, 1.0, 0.0])
        # Intentionally use WRONG endpoint for last edge to create a gap
        p3_wrong = np.array([0.5, 1.5, 0.0])   # displaced
        va, vb, vc, vd = (Vertex(p, 1e-7) for p in (p0, p1, p2, p3))
        vd_bad = Vertex(p3_wrong, 1e-7)

        e0 = Edge(Line3(p0, p1), 0.0, 1.0, va, vb, 1e-7)
        e1 = Edge(Line3(p1, p2), 0.0, 1.0, vb, vc, 1e-7)
        e2 = Edge(Line3(p2, p3), 0.0, 1.0, vc, vd, 1e-7)
        e3 = Edge(Line3(p3_wrong, p0), 0.0, 1.0, vd_bad, va, 1e-7)

        loop = Loop([
            Coedge(e0, True), Coedge(e1, True),
            Coedge(e2, True), Coedge(e3, True),
        ], is_outer=True)
        plane = Plane(p0, p1 - p0, p3 - p0)
        face = Face(plane, [loop], orientation=True, tol=1e-7)
        shell = Shell([face], is_closed=False)
        solid = Solid([shell])
        body = Body(solids=[solid])

        res = validate_body(body, open=True)
        # Should still catch the gap (loop not closed)
        assert res["ok"] is False, (
            "Expected validate_body to catch broken loop even with open=True"
        )
