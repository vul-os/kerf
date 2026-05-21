"""
Tests for GK-99 — mid_curve / mid_surface.

Oracles
-------
- mid_curve of two parallel lines is centred between them (within tol).
- mid_surface of two parallel planes lies halfway between them (within tol).

All tests are hermetic: no OCC, no database, no network.
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.curve_toolkit import mid_curve
from kerf_cad_core.geom.patch_srf import mid_surface


TOL = 1e-9


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line_curve(p0, p1) -> NurbsCurve:
    """Degree-1 NURBS line from p0 to p1."""
    pts = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=pts, knots=knots)


def _plane_surface(z: float, nu: int = 3, nv: int = 3) -> NurbsSurface:
    """Flat degree-1 NURBS plane at height z over [0,1]x[0,1]."""
    # nu x nv grid of points at height z
    u_vals = np.linspace(0, 1, nu)
    v_vals = np.linspace(0, 1, nv)
    cp = np.zeros((nu, nv, 3))
    for i, u in enumerate(u_vals):
        for j, v in enumerate(v_vals):
            cp[i, j] = [u, v, z]
    # Clamped knots for degree-1
    knots_u = np.array([0.0] * 2 + list(np.linspace(0, 1, nu - 2 + 2))[1:-1] + [1.0] * 2) if nu > 2 else np.array([0.0, 0.0, 1.0, 1.0])
    knots_v = np.array([0.0] * 2 + list(np.linspace(0, 1, nv - 2 + 2))[1:-1] + [1.0] * 2) if nv > 2 else np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                        knots_u=knots_u, knots_v=knots_v)


# ---------------------------------------------------------------------------
# mid_curve tests
# ---------------------------------------------------------------------------

class TestMidCurve:
    def test_parallel_lines_centred_y(self):
        """Mid-curve of two parallel lines offset in Y is at y=0."""
        a = _line_curve([0, -1, 0], [1, -1, 0])
        b = _line_curve([0,  1, 0], [1,  1, 0])
        m = mid_curve(a, b)
        # Sample several points
        for t in np.linspace(m.knots[0], m.knots[-1], 11):
            pt = m.evaluate(float(t))
            assert abs(pt[1]) < TOL, f"y={pt[1]} at t={t}"

    def test_parallel_lines_centred_z(self):
        """Mid-curve of two parallel lines offset in Z is at z=0."""
        a = _line_curve([0, 0, -2], [1, 0, -2])
        b = _line_curve([0, 0,  2], [1, 0,  2])
        m = mid_curve(a, b)
        for t in np.linspace(m.knots[0], m.knots[-1], 11):
            pt = m.evaluate(float(t))
            assert abs(pt[2]) < TOL, f"z={pt[2]} at t={t}"

    def test_mid_curve_endpoints(self):
        """Mid-curve endpoints are the averages of the input endpoints."""
        a = _line_curve([0, 0, 0], [2, 0, 0])
        b = _line_curve([0, 4, 0], [2, 4, 0])
        m = mid_curve(a, b)
        t0 = float(m.knots[m.degree])
        t1 = float(m.knots[-(m.degree + 1)])
        start = m.evaluate(t0)
        end = m.evaluate(t1)
        np.testing.assert_allclose(start, [0, 2, 0], atol=TOL)
        np.testing.assert_allclose(end,   [2, 2, 0], atol=TOL)

    def test_mid_curve_same_curve_is_identity(self):
        """mid_curve of a curve with itself returns the same curve."""
        c = _line_curve([1, 2, 3], [4, 5, 6])
        m = mid_curve(c, c)
        for t in np.linspace(m.knots[0], m.knots[-1], 7):
            np.testing.assert_allclose(m.evaluate(float(t)), c.evaluate(float(t)), atol=TOL)

    def test_mid_curve_returns_nurbs_curve(self):
        a = _line_curve([0, 0, 0], [1, 0, 0])
        b = _line_curve([0, 1, 0], [1, 1, 0])
        m = mid_curve(a, b)
        assert isinstance(m, NurbsCurve)


# ---------------------------------------------------------------------------
# mid_surface tests
# ---------------------------------------------------------------------------

class TestMidSurface:
    def test_parallel_planes_halfway_z(self):
        """Mid-surface of two horizontal planes at z=0 and z=2 is at z=1."""
        a = _plane_surface(0.0)
        b = _plane_surface(2.0)
        m = mid_surface(a, b)
        # Sample interior points
        u0, u1 = float(m.knots_u[0]), float(m.knots_u[-1])
        v0, v1 = float(m.knots_v[0]), float(m.knots_v[-1])
        from kerf_cad_core.geom.nurbs import surface_evaluate
        for u in np.linspace(u0, u1, 5):
            for v in np.linspace(v0, v1, 5):
                pt = surface_evaluate(m, float(u), float(v))
                assert abs(pt[2] - 1.0) < TOL, f"z={pt[2]} at u={u}, v={v}"

    def test_parallel_planes_halfway_y(self):
        """Mid-surface of planes at y=-3 and y=3 is at y=0."""
        def _plane_y(y_offset: float, nu: int = 2, nv: int = 2) -> NurbsSurface:
            cp = np.array([
                [[0, y_offset, 0], [1, y_offset, 0]],
                [[0, y_offset, 1], [1, y_offset, 1]],
            ], dtype=float)
            knots = np.array([0.0, 0.0, 1.0, 1.0])
            return NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                                knots_u=knots, knots_v=knots.copy())

        a = _plane_y(-3.0)
        b = _plane_y(3.0)
        m = mid_surface(a, b)
        from kerf_cad_core.geom.nurbs import surface_evaluate
        for u in np.linspace(0, 1, 5):
            for v in np.linspace(0, 1, 5):
                pt = surface_evaluate(m, float(u), float(v))
                assert abs(pt[1]) < TOL, f"y={pt[1]} at u={u}, v={v}"

    def test_mid_surface_same_surface_is_identity(self):
        """mid_surface of a surface with itself reproduces the original."""
        s = _plane_surface(5.0)
        m = mid_surface(s, s)
        from kerf_cad_core.geom.nurbs import surface_evaluate
        for u in np.linspace(0, 1, 4):
            for v in np.linspace(0, 1, 4):
                pt_m = surface_evaluate(m, float(u), float(v))
                pt_s = surface_evaluate(s, float(u), float(v))
                np.testing.assert_allclose(pt_m, pt_s, atol=TOL)

    def test_mid_surface_returns_nurbs_surface(self):
        a = _plane_surface(0.0)
        b = _plane_surface(1.0)
        m = mid_surface(a, b)
        assert isinstance(m, NurbsSurface)
