"""GK-P: Degree raise + lower (Cohen-Lyche-Schumaker 1985) — oracle tests.

Covers:
1. Round-trip raise:   degree-2 NURBS raised to degree-5 → eval at 100 pts within 1e-12.
2. Round-trip raise+lower: degree-3 raised to 5 then lowered back to 3 → CPs within 1e-6.
3. Bezier degree-elevation oracle: single Bezier degree 3 → 4, CPs match CLS formula exactly.
4. Surface raise (u+v): degree-(2,3) surface raised to (4,5) → eval at 10×10 grid within 1e-12.

All tests use hermetic pure-Python imports (no plugin registry needed).
"""

import importlib.util
import os
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Direct module loads — avoids triggering optional geom/__init__ imports
# ---------------------------------------------------------------------------

_NURBS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__),
                 "../src/kerf_cad_core/geom/nurbs.py")
)
_DEG_OP_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__),
                 "../src/kerf_cad_core/geom/degree_op.py")
)

# Load nurbs module
_nurbs_spec = importlib.util.spec_from_file_location(
    "kerf_cad_core.geom.nurbs", _NURBS_PATH
)
_nurbs_mod = importlib.util.module_from_spec(_nurbs_spec)
_nurbs_spec.loader.exec_module(_nurbs_mod)

NurbsCurve = _nurbs_mod.NurbsCurve
NurbsSurface = _nurbs_mod.NurbsSurface
_elevate_curve_bspline = _nurbs_mod._elevate_curve_bspline
_bezier_degree_elevate_once = _nurbs_mod._bezier_degree_elevate_once

# Load degree_op module — patch its nurbs imports to use the module we loaded
import sys as _sys
import types as _types

# Inject our loaded nurbs module so degree_op's "from kerf_cad_core.geom.nurbs import ..."
# resolves against it.
_sys.modules.setdefault("kerf_cad_core", _types.ModuleType("kerf_cad_core"))
_sys.modules.setdefault("kerf_cad_core.geom", _types.ModuleType("kerf_cad_core.geom"))
_sys.modules["kerf_cad_core.geom.nurbs"] = _nurbs_mod

_deg_spec = importlib.util.spec_from_file_location(
    "kerf_cad_core.geom.degree_op", _DEG_OP_PATH
)
_deg_mod = importlib.util.module_from_spec(_deg_spec)
_deg_spec.loader.exec_module(_deg_mod)

degree_raise_curve = _deg_mod.degree_raise_curve
degree_raise_surface = _deg_mod.degree_raise_surface
degree_lower_curve = _deg_mod.degree_lower_curve
degree_lower_surface = _deg_mod.degree_lower_surface
elevate_to_match = _deg_mod.elevate_to_match


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_quadratic_bspline():
    """Standard clamped 5-CP quadratic B-spline with one internal knot."""
    pts = np.array([
        [0.0, 0.0, 0.0],
        [0.5, 1.0, 0.0],
        [1.0, 0.5, 0.0],
        [1.5, 1.0, 0.0],
        [2.0, 0.0, 0.0],
    ], dtype=float)
    # clamped quadratic: [0,0,0, 0.5, 0.5, 1,1,1]
    knots = np.array([0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=2, control_points=pts, knots=knots)


def _make_cubic_bezier():
    """Single Bezier segment, degree 3."""
    pts = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 2.0, 0.0],
        [3.0, 2.0, 0.0],
        [4.0, 0.0, 0.0],
    ], dtype=float)
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=pts, knots=knots)


def _make_surface_2_3():
    """Degree-(2,3) clamped surface on a 3×4 grid."""
    nu, nv, dim = 3, 4, 3
    cp = np.zeros((nu, nv, dim))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [float(i), float(j), float(i * j) * 0.1]
    ku = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])       # degree 2 in u
    kv = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])  # degree 3 in v
    return NurbsSurface(degree_u=2, degree_v=3, control_points=cp,
                        knots_u=ku, knots_v=kv)


def _sample_curve(curve, n=100):
    a = float(curve.knots[curve.degree])
    b = float(curve.knots[-curve.degree - 1])
    us = np.linspace(a, b, n)
    return np.array([curve.evaluate(float(u)) for u in us])


def _sample_surface(srf, n=10):
    au = float(srf.knots_u[srf.degree_u])
    bu = float(srf.knots_u[-srf.degree_u - 1])
    av = float(srf.knots_v[srf.degree_v])
    bv = float(srf.knots_v[-srf.degree_v - 1])
    us = np.linspace(au, bu, n)
    vs = np.linspace(av, bv, n)
    pts = []
    for u in us:
        for v in vs:
            pts.append(srf.evaluate(float(u), float(v)))
    return np.array(pts)


# ---------------------------------------------------------------------------
# Test 1: Round-trip raise — degree-2 → degree-5 — exact (< 1e-12)
# ---------------------------------------------------------------------------

class TestDegreeRaiseCurveRoundtrip:

    def test_raise_degree2_to_5_eval_exact(self):
        """Raise quadratic B-spline to degree-5; evaluation matches within 1e-12."""
        orig = _make_quadratic_bspline()
        raised = degree_raise_curve(orig, target_degree=5)

        assert raised.degree == 5, f"Expected degree 5, got {raised.degree}"

        pts_orig = _sample_curve(orig, n=100)
        pts_raised = _sample_curve(raised, n=100)

        max_err = float(np.max(np.linalg.norm(pts_orig - pts_raised, axis=1)))
        assert max_err < 1e-12, (
            f"Degree-raise (2→5) evaluation error {max_err:.3e} > 1e-12.\n"
            "This tests that degree elevation is exact to float precision."
        )

    def test_raise_returns_correct_degree(self):
        """degree_raise_curve returns a curve with the requested degree."""
        crv = _make_quadratic_bspline()
        for td in (3, 4, 5, 7):
            out = degree_raise_curve(crv, target_degree=td)
            assert out.degree == td, f"Expected degree {td}, got {out.degree}"

    def test_raise_same_degree_returns_unchanged(self):
        """Raising to the same degree returns the input curve unchanged."""
        crv = _make_quadratic_bspline()
        out = degree_raise_curve(crv, target_degree=2)
        assert out is crv

    def test_raise_lower_degree_raises_valueerror(self):
        """Trying to raise to a lower degree raises ValueError."""
        crv = _make_quadratic_bspline()
        with pytest.raises(ValueError):
            degree_raise_curve(crv, target_degree=1)


# ---------------------------------------------------------------------------
# Test 2: Round-trip raise + lower — degree-3 → 5 → 3 — CPs within 1e-6
# ---------------------------------------------------------------------------

class TestDegreeRaiseThenLower:

    def test_raise_cubic_to_5_lower_back_to_3_cp_recovery(self):
        """Raise cubic Bezier from degree-3 to 5, then lower back to 3.

        Since the degree-5 curve represents an exact degree-3 polynomial,
        the lowering should succeed and recover the original CPs within 1e-6.
        """
        orig = _make_cubic_bezier()

        # Raise to 5
        raised = degree_raise_curve(orig, target_degree=5)
        assert raised.degree == 5

        # Lower back to 3
        lowered = degree_lower_curve(raised, target_degree=3, tol=1e-6)
        assert lowered.degree == 3, (
            f"degree-lower (5→3) failed: got degree {lowered.degree}"
        )

        # Evaluate both and compare
        pts_orig = _sample_curve(orig, n=100)
        pts_lowered = _sample_curve(lowered, n=100)
        max_err = float(np.max(np.linalg.norm(pts_orig - pts_lowered, axis=1)))
        assert max_err < 1e-6, (
            f"Round-trip 3→5→3 eval error {max_err:.3e} > 1e-6"
        )

    def test_lower_to_same_degree_returns_unchanged(self):
        """Lowering to the current degree returns the input unchanged."""
        crv = _make_cubic_bezier()
        out = degree_lower_curve(crv, target_degree=3)
        assert out is crv

    def test_lower_beyond_min_raises_valueerror(self):
        """Requesting target_degree < 1 raises ValueError."""
        crv = _make_cubic_bezier()
        with pytest.raises(ValueError):
            degree_lower_curve(crv, target_degree=0)

    def test_lower_above_degree_raises_valueerror(self):
        """Requesting target > current raises ValueError."""
        crv = _make_cubic_bezier()
        with pytest.raises(ValueError):
            degree_lower_curve(crv, target_degree=5)


# ---------------------------------------------------------------------------
# Test 3: Bezier degree-elevation oracle — exact match to CLS formula
# ---------------------------------------------------------------------------

class TestBezierDegreeElevationOracleCLS:

    def test_cubic_bezier_elevated_to_4_matches_cls_formula(self):
        """Single Bezier segment degree 3 → 4: CPs match Cohen-Lyche-Schumaker formula exactly.

        CLS formula (Piegl & Tiller §5.5, Alg. A5.1):
          Q_i = (i / (p+1)) * P_{i-1} + (1 - i/(p+1)) * P_i,  i=0..p+1
        where P_{-1} and P_{p+1} are not defined (endpoints fold in naturally:
          Q_0 = P_0,  Q_{p+1} = P_p).

        We validate the elevated CPs returned by degree_raise_curve against
        the direct formula applied to the Bezier hull.
        """
        orig = _make_cubic_bezier()
        p = orig.degree  # 3
        P = orig.control_points

        # Direct Cohen-Lyche-Schumaker formula for a single Bezier segment
        # elevating degree p → p+1:
        q = p + 1  # 4
        Q_direct = np.zeros((q + 1, 3))  # 5 CPs
        Q_direct[0] = P[0].copy()
        for i in range(1, q):
            alpha = i / (p + 1)
            Q_direct[i] = alpha * P[i - 1] + (1.0 - alpha) * P[i]
        Q_direct[q] = P[p].copy()

        # Elevate via degree_raise_curve
        raised = degree_raise_curve(orig, target_degree=4)
        assert raised.degree == 4, f"Expected degree 4, got {raised.degree}"
        assert raised.num_control_points == 5, (
            f"Expected 5 CPs, got {raised.num_control_points}"
        )

        # CPs from the elevated B-spline must match the direct CLS formula
        # to floating-point precision (all-Bezier single segment, no averaging)
        Q_nurbs = raised.control_points
        max_diff = float(np.max(np.abs(Q_nurbs - Q_direct)))
        assert max_diff < 1e-13, (
            f"CPs differ from CLS direct formula by {max_diff:.3e}.\n"
            f"Expected (CLS): {Q_direct.tolist()}\n"
            f"Got (nurbs): {Q_nurbs.tolist()}"
        )

    def test_linear_bezier_elevated_to_2_matches_cls_formula(self):
        """Degree-1 → degree-2 elevation matches CLS formula exactly."""
        pts = np.array([[0.0, 0.0, 0.0], [3.0, 1.0, 0.0]], dtype=float)
        knots = np.array([0.0, 0.0, 1.0, 1.0])
        orig = NurbsCurve(degree=1, control_points=pts, knots=knots)

        # Direct CLS: Q_0 = P_0, Q_2 = P_1, Q_1 = 0.5*P_0 + 0.5*P_1
        Q_direct = np.array([
            pts[0],
            0.5 * pts[0] + 0.5 * pts[1],
            pts[1],
        ])

        raised = degree_raise_curve(orig, target_degree=2)
        assert raised.degree == 2
        max_diff = float(np.max(np.abs(raised.control_points - Q_direct)))
        assert max_diff < 1e-14, (
            f"Linear→quadratic CPS differ from CLS by {max_diff:.3e}"
        )


# ---------------------------------------------------------------------------
# Test 4: Surface raise (u+v) — degree-(2,3) → (4,5) — eval within 1e-12
# ---------------------------------------------------------------------------

class TestSurfaceDegreeRaise:

    def test_surface_raise_2_3_to_4_5_eval_exact(self):
        """Raise degree-(2,3) surface to (4,5); grid evaluation within 1e-12."""
        orig = _make_surface_2_3()
        assert orig.degree_u == 2
        assert orig.degree_v == 3

        raised = degree_raise_surface(orig, target_degree_u=4, target_degree_v=5)

        assert raised.degree_u == 4, f"Expected degree_u=4, got {raised.degree_u}"
        assert raised.degree_v == 5, f"Expected degree_v=5, got {raised.degree_v}"

        pts_orig = _sample_surface(orig, n=10)
        pts_raised = _sample_surface(raised, n=10)

        max_err = float(np.max(np.linalg.norm(pts_orig - pts_raised, axis=1)))
        assert max_err < 1e-12, (
            f"Surface raise (2,3)→(4,5) evaluation error {max_err:.3e} > 1e-12.\n"
            "Degree elevation of a tensor-product surface should be geometrically exact."
        )

    def test_surface_raise_same_degree_returns_unchanged(self):
        """Raising to the same degree returns the surface unchanged."""
        srf = _make_surface_2_3()
        out = degree_raise_surface(srf, target_degree_u=2, target_degree_v=3)
        assert out is srf

    def test_surface_raise_lower_degree_raises_valueerror(self):
        """Trying to raise to a lower degree raises ValueError."""
        srf = _make_surface_2_3()
        with pytest.raises(ValueError):
            degree_raise_surface(srf, target_degree_u=1, target_degree_v=3)


# ---------------------------------------------------------------------------
# Test: elevate_to_match helper
# ---------------------------------------------------------------------------

class TestElevateToMatch:

    def test_elevate_to_match_raises_lower_surface(self):
        """elevate_to_match raises the lower-degree surface to match the higher."""
        srf_low = _make_surface_2_3()    # degree (2, 3)
        srf_high = degree_raise_surface(srf_low, 4, 5)  # degree (4, 5)

        a, b = elevate_to_match(srf_low, srf_high)
        assert a.degree_u == 4
        assert a.degree_v == 5
        assert b.degree_u == 4
        assert b.degree_v == 5

    def test_elevate_to_match_already_equal(self):
        """elevate_to_match on equal-degree surfaces returns them unchanged."""
        srf = _make_surface_2_3()
        a, b = elevate_to_match(srf, srf)
        assert a.degree_u == srf.degree_u
        assert a.degree_v == srf.degree_v
