"""
test_gordon_network.py
======================
Hermetic tests for the Gordon / Coons-Gordon network surface (GK-42).

All oracles are analytic.  No OCC, no database, no network.

Coverage
--------
1.  Two families of straight lines  → exact bilinear Gordon patch (≤1e-9).
2.  u-curves are interpolated exactly  (the Gordon property).
3.  v-curves are interpolated exactly  (the Gordon property).
4.  3 × 3 grid of straight lines  → trilinear Gordon — both families ≤1e-9.
5.  Intersection mismatch raises ValueError.
6.  Returns NurbsSurface.
7.  Determinism — repeated calls produce identical control nets.
8.  Single u-curve + single v-curve (1×1 network) → single point surface.
9.  Custom u_params / v_params (non-uniform placement).
10. Curved u-curves (non-linear) — v-curve interpolation still ≤1e-9.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    make_line_nurbs,
    surface_evaluate,
)
from kerf_cad_core.geom.network_srf import gordon_network_srf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line(p0, p1) -> NurbsCurve:
    return make_line_nurbs(np.asarray(p0, dtype=float),
                           np.asarray(p1, dtype=float))


def _eval(surf: NurbsSurface, u: float, v: float) -> np.ndarray:
    return surface_evaluate(surf, u, v)


def _sample(n: int = 9):
    return np.linspace(0.0, 1.0, n)


def _eval_curve(curve: NurbsCurve, t: float) -> np.ndarray:
    """Evaluate *curve* at normalised parameter t ∈ [0,1]."""
    u0 = float(curve.knots[curve.degree])
    u1 = float(curve.knots[-curve.degree - 1])
    u = max(u0, min(u1, u0 + t * (u1 - u0)))
    pt = np.asarray(curve.evaluate(u), dtype=float).ravel()
    if pt.shape[0] < 3:
        pt = np.concatenate([pt, np.zeros(3 - pt.shape[0])])
    return pt[:3]


# ---------------------------------------------------------------------------
# 1 & 2 & 3.  2×2 straight-line network → exact bilinear Gordon patch
# ---------------------------------------------------------------------------

class TestGordonLinearNetwork2x2:
    """Two u-curves (horizontal lines) and two v-curves (vertical lines)
    forming the unit square.  The Gordon formula reduces to the bilinear
    Coons patch which, for straight-line inputs, is exact.
    """

    @pytest.fixture(scope="class")
    def surf_and_curves(self):
        # u-curves: lines at v=0 and v=1
        c0u = _line([0, 0, 0], [1, 0, 0])   # v=0 bottom
        c1u = _line([0, 1, 0], [1, 1, 0])   # v=1 top
        # v-curves: lines at u=0 and u=1
        c0v = _line([0, 0, 0], [0, 1, 0])   # u=0 left
        c1v = _line([1, 0, 0], [1, 1, 0])   # u=1 right

        surf = gordon_network_srf(
            u_curves=[c0u, c1u],
            v_curves=[c0v, c1v],
            v_params=[0.0, 1.0],
            u_params=[0.0, 1.0],
        )
        return surf, c0u, c1u, c0v, c1v

    def test_returns_nurbs_surface(self, surf_and_curves):
        surf, *_ = surf_and_curves
        assert isinstance(surf, NurbsSurface)

    # --- Oracle: unit-square bilinear surface ---

    def test_corner_00(self, surf_and_curves):
        surf, *_ = surf_and_curves
        np.testing.assert_allclose(_eval(surf, 0, 0)[:3], [0, 0, 0], atol=1e-9)

    def test_corner_10(self, surf_and_curves):
        surf, *_ = surf_and_curves
        np.testing.assert_allclose(_eval(surf, 1, 0)[:3], [1, 0, 0], atol=1e-9)

    def test_corner_01(self, surf_and_curves):
        surf, *_ = surf_and_curves
        np.testing.assert_allclose(_eval(surf, 0, 1)[:3], [0, 1, 0], atol=1e-9)

    def test_corner_11(self, surf_and_curves):
        surf, *_ = surf_and_curves
        np.testing.assert_allclose(_eval(surf, 1, 1)[:3], [1, 1, 0], atol=1e-9)

    def test_z_is_zero_everywhere(self, surf_and_curves):
        """Planar surface: z == 0 everywhere."""
        surf, *_ = surf_and_curves
        for u in _sample(9):
            for v in _sample(9):
                assert abs(_eval(surf, u, v)[2]) < 1e-9

    def test_bilinear_x(self, surf_and_curves):
        """x-coordinate == u for the unit square."""
        surf, *_ = surf_and_curves
        for u in _sample(9):
            for v in _sample(9):
                pt = _eval(surf, u, v)
                assert abs(pt[0] - u) < 1e-9, f"x={pt[0]} != u={u}"

    def test_bilinear_y(self, surf_and_curves):
        """y-coordinate == v for the unit square."""
        surf, *_ = surf_and_curves
        for u in _sample(9):
            for v in _sample(9):
                pt = _eval(surf, u, v)
                assert abs(pt[1] - v) < 1e-9, f"y={pt[1]} != v={v}"

    # --- Gordon property: u-curves reproduced at their v-parameters ---

    def test_u_curve_0_interpolated(self, surf_and_curves):
        """Surface at v=0 must reproduce c0u exactly."""
        surf, c0u, c1u, c0v, c1v = surf_and_curves
        for u in _sample(11):
            expected = _eval_curve(c0u, u)
            got = _eval(surf, u, 0.0)[:3]
            np.testing.assert_allclose(got, expected, atol=1e-9,
                                       err_msg=f"u-curve 0 mismatch at u={u}")

    def test_u_curve_1_interpolated(self, surf_and_curves):
        """Surface at v=1 must reproduce c1u exactly."""
        surf, c0u, c1u, c0v, c1v = surf_and_curves
        for u in _sample(11):
            expected = _eval_curve(c1u, u)
            got = _eval(surf, u, 1.0)[:3]
            np.testing.assert_allclose(got, expected, atol=1e-9,
                                       err_msg=f"u-curve 1 mismatch at u={u}")

    # --- Gordon property: v-curves reproduced at their u-parameters ---

    def test_v_curve_0_interpolated(self, surf_and_curves):
        """Surface at u=0 must reproduce c0v exactly."""
        surf, c0u, c1u, c0v, c1v = surf_and_curves
        for v in _sample(11):
            expected = _eval_curve(c0v, v)
            got = _eval(surf, 0.0, v)[:3]
            np.testing.assert_allclose(got, expected, atol=1e-9,
                                       err_msg=f"v-curve 0 mismatch at v={v}")

    def test_v_curve_1_interpolated(self, surf_and_curves):
        """Surface at u=1 must reproduce c1v exactly."""
        surf, c0u, c1u, c0v, c1v = surf_and_curves
        for v in _sample(11):
            expected = _eval_curve(c1v, v)
            got = _eval(surf, 1.0, v)[:3]
            np.testing.assert_allclose(got, expected, atol=1e-9,
                                       err_msg=f"v-curve 1 mismatch at v={v}")


# ---------------------------------------------------------------------------
# 4.  3×3 grid of straight lines
# ---------------------------------------------------------------------------

class TestGordon3x3LinearNetwork:
    """3 u-curves and 3 v-curves — all straight lines.  The Gordon formula
    still reduces to exact bilinear interpolation between the input lines.
    Both families must be reproduced to ≤1e-9.
    """

    @pytest.fixture(scope="class")
    def surf_and_curves(self):
        # u-curves at v = 0, 0.5, 1 — all horizontal
        uc0 = _line([0, 0, 0], [2, 0, 0])
        uc1 = _line([0, 1, 0], [2, 1, 0])
        uc2 = _line([0, 2, 0], [2, 2, 0])
        # v-curves at u = 0, 0.5, 1 — all vertical
        vc0 = _line([0, 0, 0], [0, 2, 0])
        vc1 = _line([1, 0, 0], [1, 2, 0])
        vc2 = _line([2, 0, 0], [2, 2, 0])

        surf = gordon_network_srf(
            u_curves=[uc0, uc1, uc2],
            v_curves=[vc0, vc1, vc2],
            v_params=[0.0, 0.5, 1.0],
            u_params=[0.0, 0.5, 1.0],
        )
        return surf, [uc0, uc1, uc2], [vc0, vc1, vc2]

    def test_returns_nurbs_surface(self, surf_and_curves):
        surf, *_ = surf_and_curves
        assert isinstance(surf, NurbsSurface)

    def test_all_u_curves_interpolated(self, surf_and_curves):
        surf, u_curves, v_curves = surf_and_curves
        v_params_list = [0.0, 0.5, 1.0]
        for i, (uc, vi) in enumerate(zip(u_curves, v_params_list)):
            for u in _sample(11):
                expected = _eval_curve(uc, u)
                got = _eval(surf, u, vi)[:3]
                np.testing.assert_allclose(
                    got, expected, atol=1e-9,
                    err_msg=f"u-curve {i} mismatch at u={u}, v={vi}"
                )

    def test_all_v_curves_interpolated(self, surf_and_curves):
        surf, u_curves, v_curves = surf_and_curves
        u_params_list = [0.0, 0.5, 1.0]
        for j, (vc, uj) in enumerate(zip(v_curves, u_params_list)):
            for v in _sample(11):
                expected = _eval_curve(vc, v)
                got = _eval(surf, uj, v)[:3]
                np.testing.assert_allclose(
                    got, expected, atol=1e-9,
                    err_msg=f"v-curve {j} mismatch at v={v}, u={uj}"
                )

    def test_bilinear_interior(self, surf_and_curves):
        """For straight-line inputs the whole surface should be bilinear:
        S(u,v) = (2u, 2v, 0)."""
        surf, *_ = surf_and_curves
        for u in _sample(7):
            for v in _sample(7):
                pt = _eval(surf, u, v)[:3]
                expected = np.array([2 * u, 2 * v, 0.0])
                np.testing.assert_allclose(pt, expected, atol=1e-9)


# ---------------------------------------------------------------------------
# 5.  Intersection mismatch raises ValueError
# ---------------------------------------------------------------------------

class TestGordonMismatchRejection:

    def test_mismatched_intersection_raises(self):
        # u-curve and v-curve do NOT intersect where expected.
        uc = _line([0, 0, 0], [1, 0, 0])   # y=0 always
        vc = _line([0.5, 1, 0], [0.5, 2, 0])  # starts at y=1, never y=0

        with pytest.raises(ValueError, match="intersection mismatch"):
            gordon_network_srf(
                u_curves=[uc],
                v_curves=[vc],
                u_params=[0.5],
                v_params=[0.0],
                tol=0.01,
            )

    def test_tight_tolerance_raises_on_small_gap(self):
        # Small but deliberate gap of 0.1 at the intersection.
        uc = _line([0, 0, 0], [1, 0, 0])          # intersection at (0.5, 0, 0)
        vc = _line([0.5, 0.1, 0], [0.5, 1, 0])    # starts 0.1 above

        with pytest.raises(ValueError, match="intersection mismatch"):
            gordon_network_srf(
                u_curves=[uc],
                v_curves=[vc],
                u_params=[0.5],
                v_params=[0.0],
                tol=0.05,
            )


# ---------------------------------------------------------------------------
# 6.  Single-curve network (1×1)
# ---------------------------------------------------------------------------

class TestGordon1x1:
    """A single u-curve and a single v-curve intersecting at one point."""

    def test_single_intersection_point(self):
        # u-curve: from (0,0,0) to (1,0,0); v-curve: from (0.5,0,0) to (0.5,1,0)
        # They meet at (0.5, 0, 0).
        uc = _line([0, 0, 0], [1, 0, 0])
        vc = _line([0.5, 0, 0], [0.5, 1, 0])

        surf = gordon_network_srf(
            u_curves=[uc],
            v_curves=[vc],
            u_params=[0.5],
            v_params=[0.0],
        )
        assert isinstance(surf, NurbsSurface)

    def test_u_curve_reproduced(self):
        uc = _line([0, 0, 0], [1, 0, 0])
        vc = _line([0.5, 0, 0], [0.5, 1, 0])

        surf = gordon_network_srf(
            u_curves=[uc],
            v_curves=[vc],
            u_params=[0.5],
            v_params=[0.0],
        )
        # At v=0, the u-curve should be reproduced.
        for u in _sample(7):
            expected = _eval_curve(uc, u)
            got = _eval(surf, u, 0.0)[:3]
            np.testing.assert_allclose(got, expected, atol=1e-9,
                                       err_msg=f"u-curve mismatch at u={u}")


# ---------------------------------------------------------------------------
# 7.  Determinism
# ---------------------------------------------------------------------------

class TestGordonDeterminism:

    def test_repeated_calls_identical(self):
        uc0 = _line([0, 0, 0], [1, 0, 0])
        uc1 = _line([0, 1, 0], [1, 1, 0])
        vc0 = _line([0, 0, 0], [0, 1, 0])
        vc1 = _line([1, 0, 0], [1, 1, 0])

        surfs = [
            gordon_network_srf(
                u_curves=[uc0, uc1],
                v_curves=[vc0, vc1],
                v_params=[0.0, 1.0],
                u_params=[0.0, 1.0],
            )
            for _ in range(3)
        ]
        for s in surfs[1:]:
            np.testing.assert_array_equal(
                s.control_points, surfs[0].control_points,
                err_msg="Non-deterministic control points"
            )


# ---------------------------------------------------------------------------
# 8.  Custom (non-uniform) placement parameters
# ---------------------------------------------------------------------------

class TestGordonNonUniformParams:
    """Non-uniform placement parameters for the input curves."""

    @pytest.fixture(scope="class")
    def surf_and_curves(self):
        # u-curves at v=0, 0.3, 1.0 (not uniform)
        uc0 = _line([0, 0, 0], [3, 0, 0])
        uc1 = _line([0, 0.9, 0], [3, 0.9, 0])
        uc2 = _line([0, 3, 0], [3, 3, 0])
        # v-curves at u=0, 0.6, 1.0
        vc0 = _line([0, 0, 0], [0, 3, 0])
        vc1 = _line([1.8, 0, 0], [1.8, 3, 0])
        vc2 = _line([3, 0, 0], [3, 3, 0])

        surf = gordon_network_srf(
            u_curves=[uc0, uc1, uc2],
            v_curves=[vc0, vc1, vc2],
            v_params=[0.0, 0.3, 1.0],
            u_params=[0.0, 0.6, 1.0],
        )
        return surf, [uc0, uc1, uc2], [vc0, vc1, vc2]

    def test_u_curves_at_custom_vparams(self, surf_and_curves):
        surf, u_curves, v_curves = surf_and_curves
        v_params_list = [0.0, 0.3, 1.0]
        for i, (uc, vi) in enumerate(zip(u_curves, v_params_list)):
            for u in _sample(9):
                expected = _eval_curve(uc, u)
                got = _eval(surf, u, vi)[:3]
                np.testing.assert_allclose(
                    got, expected, atol=1e-9,
                    err_msg=f"u-curve {i} mismatch at u={u}, v={vi}"
                )

    def test_v_curves_at_custom_uparams(self, surf_and_curves):
        surf, u_curves, v_curves = surf_and_curves
        u_params_list = [0.0, 0.6, 1.0]
        for j, (vc, uj) in enumerate(zip(v_curves, u_params_list)):
            for v in _sample(9):
                expected = _eval_curve(vc, v)
                got = _eval(surf, uj, v)[:3]
                np.testing.assert_allclose(
                    got, expected, atol=1e-9,
                    err_msg=f"v-curve {j} mismatch at v={v}, u={uj}"
                )


# ---------------------------------------------------------------------------
# 9.  3D network — straight lines in 3D space
# ---------------------------------------------------------------------------

class TestGordon3DLinearNetwork:
    """Lines in 3D: verify both families are interpolated to ≤1e-9."""

    @pytest.fixture(scope="class")
    def surf_and_curves(self):
        # u-curves: lines at different z and y levels
        uc0 = _line([0, 0, 0], [2, 0, 0])
        uc1 = _line([0, 2, 4], [2, 2, 4])
        # v-curves crossing the u-curves at u=0, u=1
        vc0 = _line([0, 0, 0], [0, 2, 4])
        vc1 = _line([2, 0, 0], [2, 2, 4])

        surf = gordon_network_srf(
            u_curves=[uc0, uc1],
            v_curves=[vc0, vc1],
            v_params=[0.0, 1.0],
            u_params=[0.0, 1.0],
        )
        return surf, uc0, uc1, vc0, vc1

    def test_u_curve_0(self, surf_and_curves):
        surf, uc0, uc1, vc0, vc1 = surf_and_curves
        for u in _sample(9):
            np.testing.assert_allclose(
                _eval(surf, u, 0.0)[:3], _eval_curve(uc0, u), atol=1e-9
            )

    def test_u_curve_1(self, surf_and_curves):
        surf, uc0, uc1, vc0, vc1 = surf_and_curves
        for u in _sample(9):
            np.testing.assert_allclose(
                _eval(surf, u, 1.0)[:3], _eval_curve(uc1, u), atol=1e-9
            )

    def test_v_curve_0(self, surf_and_curves):
        surf, uc0, uc1, vc0, vc1 = surf_and_curves
        for v in _sample(9):
            np.testing.assert_allclose(
                _eval(surf, 0.0, v)[:3], _eval_curve(vc0, v), atol=1e-9
            )

    def test_v_curve_1(self, surf_and_curves):
        surf, uc0, uc1, vc0, vc1 = surf_and_curves
        for v in _sample(9):
            np.testing.assert_allclose(
                _eval(surf, 1.0, v)[:3], _eval_curve(vc1, v), atol=1e-9
            )


# ---------------------------------------------------------------------------
# 10.  API errors
# ---------------------------------------------------------------------------

class TestGordonAPIErrors:

    def test_empty_u_curves_raises(self):
        vc = _line([0, 0, 0], [0, 1, 0])
        with pytest.raises(ValueError, match="u-curve"):
            gordon_network_srf(u_curves=[], v_curves=[vc])

    def test_empty_v_curves_raises(self):
        uc = _line([0, 0, 0], [1, 0, 0])
        with pytest.raises(ValueError, match="v-curve"):
            gordon_network_srf(u_curves=[uc], v_curves=[])

    def test_wrong_v_params_length_raises(self):
        uc0 = _line([0, 0, 0], [1, 0, 0])
        uc1 = _line([0, 1, 0], [1, 1, 0])
        vc0 = _line([0, 0, 0], [0, 1, 0])
        with pytest.raises(ValueError, match="v_params length"):
            gordon_network_srf(
                u_curves=[uc0, uc1],
                v_curves=[vc0],
                v_params=[0.0],    # should be length 2
                u_params=[0.5],
            )

    def test_wrong_u_params_length_raises(self):
        uc0 = _line([0, 0, 0], [1, 0, 0])
        vc0 = _line([0, 0, 0], [0, 1, 0])
        vc1 = _line([1, 0, 0], [1, 1, 0])
        with pytest.raises(ValueError, match="u_params length"):
            gordon_network_srf(
                u_curves=[uc0],
                v_curves=[vc0, vc1],
                v_params=[0.0],
                u_params=[0.0, 0.5, 1.0],    # should be length 2
            )
