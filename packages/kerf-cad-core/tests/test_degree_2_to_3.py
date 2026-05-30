"""Tests for degree_2_to_3.py — quadratic → cubic NURBS elevation.

Four analytical oracles:
  1. Quadratic line → cubic line: 100 sample points agree within 1e-12.
  2. Quadratic circle → cubic circle: 100 sample points agree within 1e-12;
     circle radius preserved.
  3. Surface elevation: quadratic NURBS surface → cubic surface; 10×10 grid
     within 1e-12.
  4. Body normalization: a body with some degree-2 and some degree-3 faces →
     auto_elevate produces all degree-3.
"""

import importlib.util
import os
import copy

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Import the modules under test directly to avoid triggering the full
# geom/__init__.py dependency chain (some optional modules may be absent).
# ---------------------------------------------------------------------------

_repo_src = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src/kerf_cad_core")
)


def _load_mod(rel_path, name):
    path = os.path.join(_repo_src, rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_nurbs_mod = _load_mod("geom/nurbs.py", "kerf_cad_core.geom.nurbs")
_d2to3_mod = _load_mod("geom/degree_2_to_3.py", "kerf_cad_core.geom.degree_2_to_3")
_brep_mod = _load_mod("geom/brep.py", "kerf_cad_core.geom.brep")

NurbsCurve = _nurbs_mod.NurbsCurve
NurbsSurface = _nurbs_mod.NurbsSurface
make_circle_nurbs = _nurbs_mod.make_circle_nurbs

elevate_quadratic_to_cubic_curve = _d2to3_mod.elevate_quadratic_to_cubic_curve
elevate_quadratic_to_cubic_surface = _d2to3_mod.elevate_quadratic_to_cubic_surface
auto_elevate_to_degree_3 = _d2to3_mod.auto_elevate_to_degree_3

Body = _brep_mod.Body
Solid = _brep_mod.Solid
Shell = _brep_mod.Shell
Face = _brep_mod.Face
Loop = _brep_mod.Loop
Vertex = _brep_mod.Vertex
Edge = _brep_mod.Edge
Coedge = _brep_mod.Coedge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamped_knots(n: int, degree: int) -> np.ndarray:
    """Clamped uniform knot vector for n control points at given degree."""
    inner = max(0, n - degree - 1)
    return np.concatenate([
        np.zeros(degree + 1),
        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
        np.ones(degree + 1),
    ])


def _sample_curve(curve, n: int = 100) -> np.ndarray:
    a = float(curve.knots[curve.degree])
    b = float(curve.knots[-curve.degree - 1])
    us = np.linspace(a, b, n)
    return np.array([curve.evaluate(u) for u in us])


def _sample_surface(surf, nu: int = 10, nv: int = 10) -> np.ndarray:
    au = float(surf.knots_u[surf.degree_u])
    bu = float(surf.knots_u[-surf.degree_u - 1])
    av = float(surf.knots_v[surf.degree_v])
    bv = float(surf.knots_v[-surf.degree_v - 1])
    pts = []
    for u in np.linspace(au, bu, nu):
        for v in np.linspace(av, bv, nv):
            pts.append(surf.evaluate(u, v))
    return np.array(pts)


# ---------------------------------------------------------------------------
# Test 1: Quadratic line → cubic line
# ---------------------------------------------------------------------------

class TestQuadraticLineToCubic:

    def _make_quad_line(self, p0, p2):
        """Quadratic line segment: P0, midpoint, P2 collinear."""
        p1 = 0.5 * (np.asarray(p0) + np.asarray(p2))
        pts = np.array([p0, p1, p2], dtype=float)
        knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        return NurbsCurve(degree=2, control_points=pts, knots=knots)

    def test_degree_is_three_after_elevation(self):
        c2 = self._make_quad_line([0, 0, 0], [4, 2, 0])
        c3 = elevate_quadratic_to_cubic_curve(c2)
        assert c3.degree == 3, f"Expected degree 3, got {c3.degree}"

    def test_quadratic_line_to_cubic_line_100_samples(self):
        """Oracle: 100 sample points agree within 1e-12."""
        c2 = self._make_quad_line([0.0, 0.0, 0.0], [3.0, 1.5, 0.0])
        c3 = elevate_quadratic_to_cubic_curve(c2)

        pts2 = _sample_curve(c2, n=100)
        pts3 = _sample_curve(c3, n=100)

        max_err = float(np.max(np.linalg.norm(pts2 - pts3, axis=1)))
        assert max_err < 1e-12, (
            f"Max point error {max_err:.2e} exceeds 1e-12 for quadratic→cubic line"
        )

    def test_endpoints_exact(self):
        """Elevated curve endpoints must match the original exactly."""
        p0 = np.array([1.5, -2.0, 3.1])
        p2 = np.array([-1.0, 1.0, 0.5])
        c2 = self._make_quad_line(p0, p2)
        c3 = elevate_quadratic_to_cubic_curve(c2)

        a = float(c3.knots[c3.degree])
        b = float(c3.knots[-c3.degree - 1])
        np.testing.assert_allclose(c3.evaluate(a), p0, atol=1e-12)
        np.testing.assert_allclose(c3.evaluate(b), p2, atol=1e-12)

    def test_multi_segment_quad_line(self):
        """Two-segment quadratic B-spline line → elevated cubic line."""
        pts = np.array([
            [0.0, 0.0, 0.0],
            [0.5, 0.0, 0.0],   # midpoint of first half
            [1.0, 0.0, 0.0],   # junction
            [1.5, 0.0, 0.0],   # midpoint of second half
            [2.0, 0.0, 0.0],
        ], dtype=float)
        knots = np.array([0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0])
        c2 = NurbsCurve(degree=2, control_points=pts, knots=knots)
        c3 = elevate_quadratic_to_cubic_curve(c2)

        assert c3.degree == 3
        pts2 = _sample_curve(c2, n=100)
        pts3 = _sample_curve(c3, n=100)
        max_err = float(np.max(np.linalg.norm(pts2 - pts3, axis=1)))
        assert max_err < 1e-12, (
            f"Multi-segment line: max error {max_err:.2e} > 1e-12"
        )

    def test_already_cubic_returns_unchanged(self):
        """Degree-3 input is returned as-is (no-op)."""
        pts = np.array([[0, 0, 0], [1, 1, 0], [2, 0, 0], [3, 1, 0]], dtype=float)
        knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
        c3 = NurbsCurve(degree=3, control_points=pts, knots=knots)
        result = elevate_quadratic_to_cubic_curve(c3)
        assert result is c3  # unchanged object

    def test_degree_1_raises(self):
        """Degree-1 input raises ValueError."""
        pts = np.array([[0, 0, 0], [1, 0, 0]], dtype=float)
        knots = np.array([0.0, 0.0, 1.0, 1.0])
        c1 = NurbsCurve(degree=1, control_points=pts, knots=knots)
        with pytest.raises(ValueError):
            elevate_quadratic_to_cubic_curve(c1)


# ---------------------------------------------------------------------------
# Test 2: Quadratic circle → cubic circle
# ---------------------------------------------------------------------------

class TestQuadraticCircleToCubic:

    def test_degree_is_three(self):
        circle = make_circle_nurbs(center=[0, 0, 0], radius=5.0)
        assert circle.degree == 2
        elevated = elevate_quadratic_to_cubic_curve(circle)
        assert elevated.degree == 3

    def test_circle_100_samples_within_1e12(self):
        """Oracle: elevated cubic evaluates identically at 100 sample points within 1e-12."""
        radius = 7.0
        circle = make_circle_nurbs(center=[1.0, 2.0, 0.0], radius=radius)
        elevated = elevate_quadratic_to_cubic_curve(circle)

        pts2 = _sample_curve(circle, n=100)
        pts3 = _sample_curve(elevated, n=100)

        max_err = float(np.max(np.linalg.norm(pts2 - pts3, axis=1)))
        assert max_err < 1e-12, (
            f"Circle max error {max_err:.2e} > 1e-12 after elevation"
        )

    def test_circle_radius_preserved(self):
        """Sampled points on the elevated circle all lie at the original radius."""
        center = np.array([0.0, 0.0, 0.0])
        radius = 3.5
        circle = make_circle_nurbs(center=center, radius=radius)
        elevated = elevate_quadratic_to_cubic_curve(circle)

        pts = _sample_curve(elevated, n=100)
        distances = np.linalg.norm(pts - center, axis=1)
        max_dev = float(np.max(np.abs(distances - radius)))
        assert max_dev < 1e-10, (
            f"Circle radius not preserved: max deviation {max_dev:.2e}"
        )

    def test_circle_rational_weights_not_all_one(self):
        """Elevated rational circle must retain meaningful (non-uniform) weights."""
        circle = make_circle_nurbs(center=[0, 0, 0], radius=1.0)
        elevated = elevate_quadratic_to_cubic_curve(circle)

        assert elevated.weights is not None, "Weights must be preserved for rational circle"
        # The weights must not all be 1 (the rational structure must survive elevation).
        assert not np.allclose(elevated.weights, 1.0), (
            "Elevated rational circle should retain non-uniform weights"
        )


# ---------------------------------------------------------------------------
# Test 3: Surface elevation
# ---------------------------------------------------------------------------

class TestSurfaceElevation:

    def _make_biquadratic_surface(self) -> NurbsSurface:
        """Degree-(2,2) sinusoidal patch (3×3 control grid)."""
        cp = np.zeros((3, 3, 3), dtype=float)
        for i in range(3):
            for j in range(3):
                cp[i, j] = [float(i), float(j), float(i * j) * 0.1]
        ku = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        kv = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        return NurbsSurface(degree_u=2, degree_v=2, control_points=cp,
                            knots_u=ku, knots_v=kv)

    def test_surface_degree_u_and_v_are_three(self):
        s2 = self._make_biquadratic_surface()
        s3 = elevate_quadratic_to_cubic_surface(s2)
        assert s3.degree_u == 3, f"Expected degree_u=3, got {s3.degree_u}"
        assert s3.degree_v == 3, f"Expected degree_v=3, got {s3.degree_v}"

    def test_surface_10x10_grid_within_1e12(self):
        """Oracle: 10×10 evaluation grid agrees within 1e-12 after elevation."""
        s2 = self._make_biquadratic_surface()
        s3 = elevate_quadratic_to_cubic_surface(s2)

        pts2 = _sample_surface(s2, nu=10, nv=10)
        pts3 = _sample_surface(s3, nu=10, nv=10)

        max_err = float(np.max(np.linalg.norm(pts2 - pts3, axis=1)))
        assert max_err < 1e-12, (
            f"Surface 10×10 grid max error {max_err:.2e} > 1e-12 after elevation"
        )

    def test_surface_with_multi_segment_u(self):
        """Multi-segment quadratic surface (5×3 grid, interior breakpoint in U)."""
        cp = np.zeros((5, 3, 3), dtype=float)
        for i in range(5):
            for j in range(3):
                cp[i, j] = [i * 0.5, j * 0.5, 0.0]
        ku = np.array([0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0])
        kv = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        s2 = NurbsSurface(degree_u=2, degree_v=2, control_points=cp,
                          knots_u=ku, knots_v=kv)
        s3 = elevate_quadratic_to_cubic_surface(s2)

        assert s3.degree_u == 3
        assert s3.degree_v == 3

        pts2 = _sample_surface(s2, nu=10, nv=10)
        pts3 = _sample_surface(s3, nu=10, nv=10)
        max_err = float(np.max(np.linalg.norm(pts2 - pts3, axis=1)))
        assert max_err < 1e-12, (
            f"Multi-segment surface: max error {max_err:.2e} > 1e-12"
        )

    def test_surface_already_degree3_u_only_v_elevated(self):
        """If degree_u is already 3, only degree_v is elevated."""
        cp = np.zeros((4, 3, 3), dtype=float)
        for i in range(4):
            for j in range(3):
                cp[i, j] = [i * 0.5, j * 0.5, 0.0]
        ku = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
        kv = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        # degree_u=3, degree_v=2
        s = NurbsSurface(degree_u=3, degree_v=2, control_points=cp,
                         knots_u=ku, knots_v=kv)
        s_out = elevate_quadratic_to_cubic_surface(s)
        assert s_out.degree_u == 3, "degree_u should remain 3"
        assert s_out.degree_v == 3, "degree_v should be elevated to 3"


# ---------------------------------------------------------------------------
# Test 4: Body normalization
# ---------------------------------------------------------------------------

class TestAutoElevateToDegree3:

    def _make_nurbs_face(self, degree_u: int, degree_v: int) -> Face:
        """Create a Face with a NurbsSurface of given degrees."""
        nu = degree_u + 1  # single Bezier segment in U
        nv = degree_v + 1  # single Bezier segment in V
        cp = np.zeros((nu, nv, 3), dtype=float)
        for i in range(nu):
            for j in range(nv):
                cp[i, j] = [i / max(nu - 1, 1), j / max(nv - 1, 1), 0.0]
        ku = _clamped_knots(nu, degree_u)
        kv = _clamped_knots(nv, degree_v)
        srf = NurbsSurface(degree_u=degree_u, degree_v=degree_v,
                           control_points=cp, knots_u=ku, knots_v=kv)
        return Face(surface=srf)

    def _make_nurbs_edge(self, degree: int) -> Edge:
        """Create an Edge with a NurbsCurve of given degree."""
        n = degree + 1
        pts = np.array([[float(i) / n, 0.0, 0.0] for i in range(n)], dtype=float)
        knots = _clamped_knots(n, degree)
        crv = NurbsCurve(degree=degree, control_points=pts, knots=knots)
        v0 = Vertex(point=np.array([0.0, 0.0, 0.0]))
        v1 = Vertex(point=np.array([1.0, 0.0, 0.0]))
        return Edge(curve=crv, t0=0.0, t1=1.0, v_start=v0, v_end=v1)

    def test_all_degree_2_faces_promoted(self):
        """Body with all degree-2 faces → auto_elevate makes all degree-3."""
        f1 = self._make_nurbs_face(2, 2)
        f2 = self._make_nurbs_face(2, 2)
        shell = Shell(faces=[f1, f2])
        solid = Solid(shells=[shell])
        body = Body(solids=[solid])

        auto_elevate_to_degree_3(body)

        for face in body.all_faces():
            srf = face.surface
            assert srf.degree_u == 3, (
                f"Expected degree_u=3, got {srf.degree_u}"
            )
            assert srf.degree_v == 3, (
                f"Expected degree_v=3, got {srf.degree_v}"
            )

    def test_mixed_degree_body(self):
        """Body with degree-2 and degree-3 faces → auto_elevate makes all degree-3."""
        f_deg2 = self._make_nurbs_face(2, 2)
        f_deg3 = self._make_nurbs_face(3, 3)
        shell = Shell(faces=[f_deg2, f_deg3])
        solid = Solid(shells=[shell])
        body = Body(solids=[solid])

        auto_elevate_to_degree_3(body)

        for face in body.all_faces():
            srf = face.surface
            assert srf.degree_u == 3, (
                f"Mixed body: expected degree_u=3, got {srf.degree_u}"
            )
            assert srf.degree_v == 3, (
                f"Mixed body: expected degree_v=3, got {srf.degree_v}"
            )

    def test_edge_curves_promoted(self):
        """Degree-2 edges in the body are promoted to degree-3."""
        e2 = self._make_nurbs_edge(2)
        e3 = self._make_nurbs_edge(3)

        # Build a minimal topology that uses these edges.
        v0 = Vertex(point=np.array([0.0, 0.0, 0.0]))
        v1 = Vertex(point=np.array([1.0, 0.0, 0.0]))
        # Wire-level body (no solid needed for edge access)
        body = Body()
        # Inject edges via a free shell → face → loop → coedge chain.
        ce2 = Coedge(edge=e2, orientation=True)
        ce3 = Coedge(edge=e3, orientation=True)
        loop = Loop(coedges=[ce2, ce3])
        face = Face(surface=NurbsSurface(
            degree_u=2, degree_v=2,
            control_points=np.zeros((3, 3, 3)),
            knots_u=np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0]),
            knots_v=np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0]),
        ))
        face.loops.append(loop)
        loop.face = face
        shell = Shell(faces=[face])
        body.shells.append(shell)

        auto_elevate_to_degree_3(body)

        for edge in body.all_edges():
            crv = edge.curve
            if isinstance(crv, NurbsCurve):
                assert crv.degree == 3, (
                    f"Edge curve degree should be 3 after normalization, got {crv.degree}"
                )

    def test_returns_same_body_object(self):
        """auto_elevate_to_degree_3 returns the same Body instance (in-place)."""
        f = self._make_nurbs_face(2, 2)
        shell = Shell(faces=[f])
        solid = Solid(shells=[shell])
        body = Body(solids=[solid])

        result = auto_elevate_to_degree_3(body)
        assert result is body

    def test_non_nurbs_surfaces_untouched(self):
        """Faces with non-NurbsSurface geometry are not modified."""
        # Use a plain analytic surface object (not a NurbsSurface)
        class _MockSurface:
            def evaluate(self, u, v):
                return np.array([u, v, 0.0])
            def normal(self, u, v):
                return np.array([0.0, 0.0, 1.0])

        mock_srf = _MockSurface()
        face = Face(surface=mock_srf)
        shell = Shell(faces=[face])
        body = Body(shells=[shell])

        auto_elevate_to_degree_3(body)  # should not raise

        # Surface must still be the original object.
        assert face.surface is mock_srf


# ---------------------------------------------------------------------------
# Test 5: Bezier closed-form formula verification
# ---------------------------------------------------------------------------

class TestBezierFormula:
    """Verify the exact Q1/Q2 formula independently of the full pipeline."""

    def test_single_bezier_segment_formula(self):
        """Verify Q1 = P0/3 + 2/3*P1 and Q2 = 2/3*P1 + P2/3."""
        P0 = np.array([[1.0, 2.0, 3.0]])
        P1 = np.array([[4.0, 5.0, 6.0]])
        P2 = np.array([[7.0, 8.0, 9.0]])
        P = np.vstack([P0, P1, P2])

        from kerf_cad_core.geom.degree_2_to_3 import _elevate_bezier_quad_to_cubic
        Q = _elevate_bezier_quad_to_cubic(P)

        assert Q.shape == (4, 3)
        np.testing.assert_allclose(Q[0], P0[0], atol=1e-15)
        np.testing.assert_allclose(Q[1], P0[0] / 3.0 + (2.0 / 3.0) * P1[0], atol=1e-15)
        np.testing.assert_allclose(Q[2], (2.0 / 3.0) * P1[0] + P2[0] / 3.0, atol=1e-15)
        np.testing.assert_allclose(Q[3], P2[0], atol=1e-15)

    def test_wrong_shape_raises(self):
        """Passing a 4-point (cubic) segment raises ValueError."""
        P = np.zeros((4, 3))
        from kerf_cad_core.geom.degree_2_to_3 import _elevate_bezier_quad_to_cubic
        with pytest.raises(ValueError):
            _elevate_bezier_quad_to_cubic(P)
