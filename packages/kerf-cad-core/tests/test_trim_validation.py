"""
Tests for kerf_cad_core.geom.trim_validation — T-104e.

Side-selection + validation contract for trim-by-curve geometry.

All tests are hermetic: no OCC, no database, no network.

Coverage:
  1. select_side on a flat (plane-like) NurbsSurface with a UV loop:
       - interior point → "inside"
       - exterior point → "outside"
       - point on loop boundary → AmbiguousPoint
  2. select_side on a cylinder-like NurbsSurface with a UV loop:
       - interior point → "inside"
       - exterior point → "outside"
       - on-loop point → AmbiguousPoint
  3. select_side with analytic Plane surface
  4. select_side with analytic CylinderSurface
  5. validate_body_post_trim on a clean box body → ok, residual ≤ tol
  6. Error paths: bad trim_loop, bad target_point, projection failure
  7. Return dict structure
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.trim_curve import TrimCurve
from kerf_cad_core.geom.trim_validation import (
    AmbiguousPoint,
    select_side,
    validate_body_post_trim,
)


# ---------------------------------------------------------------------------
# Surface factories
# ---------------------------------------------------------------------------

def _make_knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    knots = np.concatenate([
        np.zeros(deg + 1),
        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
        np.ones(deg + 1),
    ])
    return knots


def make_flat_nurbs(
    nu: int = 4,
    nv: int = 4,
    scale: float = 1.0,
) -> NurbsSurface:
    """Flat XY-plane NurbsSurface on [0, scale] × [0, scale]."""
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [i * scale / (nu - 1), j * scale / (nv - 1), 0.0]
    return NurbsSurface(
        degree_u=1,
        degree_v=1,
        control_points=cp,
        knots_u=_make_knots(nu, 1),
        knots_v=_make_knots(nv, 1),
    )


def make_cylinder_nurbs(
    radius: float = 1.0,
    height: float = 2.0,
    n_circ: int = 9,
    n_axial: int = 3,
) -> NurbsSurface:
    """Approximate cylindrical NurbsSurface; u ∈ [0, 1] spans angle, v ∈ [0, 1] spans height."""
    cp = np.zeros((n_circ, n_axial, 3))
    for i in range(n_circ):
        angle = 2.0 * math.pi * i / (n_circ - 1)
        for j in range(n_axial):
            z = height * j / (n_axial - 1)
            cp[i, j] = [radius * math.cos(angle), radius * math.sin(angle), z]
    return NurbsSurface(
        degree_u=2,
        degree_v=1,
        control_points=cp,
        knots_u=_make_knots(n_circ, 2),
        knots_v=_make_knots(n_axial, 1),
    )


def _square_uv_loop(
    u_lo: float, u_hi: float,
    v_lo: float, v_hi: float,
    n: int = 20,
) -> List[Tuple[float, float]]:
    """Rectangular UV-space trim loop."""
    pts: List[Tuple[float, float]] = []
    for k in range(n):
        t = k / n
        if t < 0.25:
            u = u_lo + (u_hi - u_lo) * (t / 0.25)
            pts.append((u, v_lo))
        elif t < 0.5:
            u = u_hi
            v = v_lo + (v_hi - v_lo) * ((t - 0.25) / 0.25)
            pts.append((u, v))
        elif t < 0.75:
            u = u_hi - (u_hi - u_lo) * ((t - 0.5) / 0.25)
            pts.append((u, v_hi))
        else:
            u = u_lo
            v = v_hi - (v_hi - v_lo) * ((t - 0.75) / 0.25)
            pts.append((u, v))
    return pts


# ---------------------------------------------------------------------------
# Group 1: Flat NurbsSurface — select_side
# ---------------------------------------------------------------------------

class TestSelectSideFlatNurbs:
    """Trim loop on a flat NurbsSurface (analytic-matrix case)."""

    def setup_method(self):
        self.surface = make_flat_nurbs(nu=4, nv=4, scale=1.0)
        # Square trim loop in UV occupying the middle 40-60% of the domain
        self.uv_loop = _square_uv_loop(0.35, 0.65, 0.35, 0.65, n=40)
        self.trim_curve = TrimCurve(
            uv_samples=self.uv_loop,
            is_closed=True,
            crosses_boundary=False,
        )

    def test_interior_point_returns_inside(self):
        """A 3D point inside the UV loop → side == 'inside'."""
        # UV (0.5, 0.5) maps to world (0.5, 0.5, 0) on this unit plane
        target = np.array([0.5, 0.5, 0.0])
        result = select_side(self.surface, self.trim_curve, target)
        assert result["side"] == "inside"
        assert result["validated"] is True
        assert result["residual"] < 1e-4

    def test_exterior_point_returns_outside(self):
        """A 3D point outside the UV loop → side == 'outside'."""
        # UV (0.1, 0.1) is well outside the [0.35, 0.65] loop
        target = np.array([0.1, 0.1, 0.0])
        result = select_side(self.surface, self.trim_curve, target)
        assert result["side"] == "outside"
        assert result["validated"] is True

    def test_top_right_exterior_returns_outside(self):
        """Point in top-right corner is outside the central loop."""
        target = np.array([0.9, 0.9, 0.0])
        result = select_side(self.surface, self.trim_curve, target)
        assert result["side"] == "outside"

    def test_return_dict_has_required_keys(self):
        """Return value must have side, validated, residual."""
        target = np.array([0.5, 0.5, 0.0])
        result = select_side(self.surface, self.trim_curve, target)
        assert "side" in result
        assert "validated" in result
        assert "residual" in result

    def test_side_is_string(self):
        """side key must be a string."""
        target = np.array([0.5, 0.5, 0.0])
        result = select_side(self.surface, self.trim_curve, target)
        assert isinstance(result["side"], str)
        assert result["side"] in ("inside", "outside")

    def test_ambiguous_on_loop_raises(self):
        """A point on the UV loop boundary raises AmbiguousPoint."""
        # Place the point exactly on the loop boundary at u=0.5, v=0.35
        # (bottom edge of the square loop) on our unit plane
        target = np.array([0.5, 0.35, 0.0])
        with pytest.raises(AmbiguousPoint) as exc_info:
            select_side(self.surface, self.trim_curve, target)
        err = exc_info.value
        assert hasattr(err, "residual")
        assert hasattr(err, "uv")

    def test_ambiguous_error_message_is_informative(self):
        """AmbiguousPoint message should contain UV coordinates."""
        target = np.array([0.5, 0.35, 0.0])
        with pytest.raises(AmbiguousPoint) as exc_info:
            select_side(self.surface, self.trim_curve, target)
        assert "trim loop" in str(exc_info.value).lower() or "uv" in str(exc_info.value).lower()

    def test_accepts_plain_uv_list(self):
        """trim_loop can be a plain list of (u, v) tuples."""
        target = np.array([0.5, 0.5, 0.0])
        result = select_side(self.surface, self.uv_loop, target)
        assert result["side"] == "inside"

    def test_residual_is_float(self):
        """residual must be a non-negative float."""
        target = np.array([0.5, 0.5, 0.0])
        result = select_side(self.surface, self.trim_curve, target)
        assert isinstance(result["residual"], float)
        assert result["residual"] >= 0.0


# ---------------------------------------------------------------------------
# Group 2: Cylinder-like NurbsSurface — select_side
# ---------------------------------------------------------------------------

class TestSelectSideCylinderNurbs:
    """Trim loop on a cylindrical NurbsSurface."""

    def setup_method(self):
        self.surface = make_cylinder_nurbs(radius=1.0, height=2.0, n_circ=9, n_axial=3)
        # A band trim loop in the middle of the UV domain (u=0.25..0.75, v=0.35..0.65)
        self.uv_loop = _square_uv_loop(0.25, 0.75, 0.35, 0.65, n=40)
        self.trim_curve = TrimCurve(
            uv_samples=self.uv_loop,
            is_closed=True,
            crosses_boundary=False,
        )

    def test_interior_point_returns_inside(self):
        """A 3D point near the cylinder surface, inside the UV band → inside."""
        # u=0.5 → angle = pi (pointing -x), v=0.5 → z = height/2 = 1.0
        # On surface: (-1, 0, 1)
        target = np.array([-0.9, 0.0, 1.0])
        result = select_side(self.surface, self.trim_curve, target)
        assert result["side"] == "inside"
        assert result["validated"] is True

    def test_exterior_point_returns_outside(self):
        """A 3D point near the cylinder surface, outside the UV band → outside."""
        # u~0.1 → angle ≈ 0.2*pi (slight angle from +x), v~0.1 → z ≈ 0.2*height
        # outside the band [0.25, 0.75] in u direction
        # Use angle = 0 (u=0) and z near 0 (v~0)
        target = np.array([1.0, 0.0, 0.2])
        result = select_side(self.surface, self.trim_curve, target)
        assert result["side"] == "outside"

    def test_ambiguous_on_loop_raises(self):
        """A point on the UV loop boundary raises AmbiguousPoint."""
        # u=0.5 → angle = pi, v=0.35 → z = 0.35 * 2.0 = 0.70
        target = np.array([-1.0, 0.0, 0.70])
        with pytest.raises(AmbiguousPoint):
            select_side(self.surface, self.trim_curve, target)

    def test_return_structure(self):
        """Result has required keys."""
        target = np.array([-0.9, 0.0, 1.0])
        result = select_side(self.surface, self.trim_curve, target)
        assert set(result.keys()) >= {"side", "validated", "residual"}
        assert result["validated"] is True


# ---------------------------------------------------------------------------
# Group 3: Analytic Plane surface — select_side
# ---------------------------------------------------------------------------

class TestSelectSideAnalyticPlane:
    """Side-selection on a brep.Plane surface."""

    def _make_plane_and_loop(self):
        from kerf_cad_core.geom.brep import Plane
        # Plane in XY-plane, centred at origin
        plane = Plane(
            origin=np.array([0.0, 0.0, 0.0]),
            x_axis=np.array([1.0, 0.0, 0.0]),
            y_axis=np.array([0.0, 1.0, 0.0]),
        )
        # Square loop in u,v space: u in [-0.3, 0.3], v in [-0.3, 0.3]
        uv_loop = _square_uv_loop(-0.3, 0.3, -0.3, 0.3, n=40)
        return plane, uv_loop

    def test_interior_point_inside(self):
        """Origin is inside the square loop on the XY plane."""
        plane, uv_loop = self._make_plane_and_loop()
        result = select_side(plane, uv_loop, np.array([0.0, 0.0, 0.0]))
        assert result["side"] == "inside"
        assert result["validated"] is True

    def test_exterior_point_outside(self):
        """A point far from the origin is outside the small square loop."""
        plane, uv_loop = self._make_plane_and_loop()
        result = select_side(plane, uv_loop, np.array([1.0, 0.0, 0.0]))
        assert result["side"] == "outside"

    def test_on_loop_raises(self):
        """A point at u=0.0, v=-0.3 (on bottom edge) raises AmbiguousPoint."""
        plane, uv_loop = self._make_plane_and_loop()
        target = np.array([0.0, -0.3, 0.0])
        with pytest.raises(AmbiguousPoint):
            select_side(plane, uv_loop, target)

    def test_residual_near_zero_for_on_surface_point(self):
        """A point on the plane surface should have very small residual."""
        plane, uv_loop = self._make_plane_and_loop()
        result = select_side(plane, uv_loop, np.array([0.0, 0.0, 0.0]))
        assert result["residual"] < 1e-10


# ---------------------------------------------------------------------------
# Group 4: Analytic CylinderSurface — select_side
# ---------------------------------------------------------------------------

class TestSelectSideAnalyticCylinder:
    """Side-selection on a brep.CylinderSurface.

    With axis=(0,0,1): brep._perp gives x_ref=(0,1,0), y=(-1,0,0).
    So evaluate(u, v) = (−sin(u), cos(u), v).
      u=0   → (0, 1, v)  (top of Y-axis)
      u=0.5 → (−sin0.5, cos0.5, v) ≈ (−0.479, 0.878, v)
    Loop covers u in [−0.5, 0.5], v in [0.5, 1.5].
    Interior: u=0, v=1.0 → world (0, 1, 1).
    Exterior: u=2.0, v=1.0 → world (−sin2, cos2, 1) ≈ (−0.909, −0.416, 1).
    On loop: u=−0.5, v=1.0 → world (sin0.5, cos0.5, 1) ≈ (0.479, 0.878, 1).
    """

    def _make_cylinder_and_loop(self, radius: float = 1.0):
        from kerf_cad_core.geom.brep import CylinderSurface
        cyl = CylinderSurface(
            center=np.array([0.0, 0.0, 0.0]),
            axis=np.array([0.0, 0.0, 1.0]),
            radius=radius,
        )
        # UV loop in (angle, height) space: u in [-0.5, 0.5], v in [0.5, 1.5]
        uv_loop = _square_uv_loop(-0.5, 0.5, 0.5, 1.5, n=40)
        return cyl, uv_loop

    def _surface_pt(self, u: float, v: float) -> np.ndarray:
        """Evaluate the cylinder: (−sin u, cos u, v) for radius=1, axis=Z."""
        return np.array([-math.sin(u), math.cos(u), v])

    def test_interior_point_inside(self):
        """A point at u=0, v=1.0 (inside the loop) → side == 'inside'."""
        cyl, uv_loop = self._make_cylinder_and_loop()
        # u=0, v=1.0: inside loop [−0.5,0.5]×[0.5,1.5]
        target = self._surface_pt(0.0, 1.0)  # (0, 1, 1)
        result = select_side(cyl, uv_loop, target)
        assert result["side"] == "inside"
        assert result["validated"] is True

    def test_exterior_point_outside(self):
        """A point at u=2.0, v=1.0 (outside the angular band) → 'outside'."""
        cyl, uv_loop = self._make_cylinder_and_loop()
        # u=2.0 is outside [−0.5, 0.5]
        target = self._surface_pt(2.0, 1.0)
        result = select_side(cyl, uv_loop, target)
        assert result["side"] == "outside"

    def test_on_loop_raises(self):
        """A point at u=−0.5, v=1.0 (left boundary) raises AmbiguousPoint."""
        cyl, uv_loop = self._make_cylinder_and_loop()
        # Exactly on the left boundary of the loop
        target = self._surface_pt(-0.5, 1.0)
        with pytest.raises(AmbiguousPoint):
            select_side(cyl, uv_loop, target)


# ---------------------------------------------------------------------------
# Group 5: validate_body_post_trim
# ---------------------------------------------------------------------------

class TestValidateBodyPostTrim:
    """validate_body_post_trim wraps brep.validate_body and checks residual."""

    def _make_box_body(self):
        from kerf_cad_core.geom.brep_build import box_to_body
        return box_to_body(corner=(0.0, 0.0, 0.0), dx=1.0, dy=1.0, dz=1.0)

    def _make_cylinder_body(self):
        from kerf_cad_core.geom.brep_build import cylinder_to_body
        return cylinder_to_body(
            axis_pt=(0.0, 0.0, 0.0),
            axis_dir=(0.0, 0.0, 1.0),
            radius=0.5,
            height=2.0,
        )

    def test_clean_box_body_passes(self):
        """A freshly built box body should pass post-trim validation."""
        body = self._make_box_body()
        result = validate_body_post_trim(body)
        assert result["ok"] is True
        assert result["errors"] == []

    def test_clean_box_residual_is_small(self):
        """Box body's loop residual should be below tolerance."""
        body = self._make_box_body()
        result = validate_body_post_trim(body, tol=1e-6)
        assert result["residual"] < 1e-6

    def test_clean_cylinder_body_passes(self):
        """A freshly built cylinder body should pass post-trim validation."""
        body = self._make_cylinder_body()
        result = validate_body_post_trim(body)
        assert result["ok"] is True

    def test_clean_cylinder_residual_is_small(self):
        """Cylinder body residual should be below tolerance."""
        body = self._make_cylinder_body()
        result = validate_body_post_trim(body, tol=1e-6)
        assert result["residual"] < 1e-6

    def test_return_dict_has_required_keys(self):
        """Result must have ok, errors, residual."""
        body = self._make_box_body()
        result = validate_body_post_trim(body)
        assert "ok" in result
        assert "errors" in result
        assert "residual" in result

    def test_residual_is_float(self):
        """residual must be a non-negative float."""
        body = self._make_box_body()
        result = validate_body_post_trim(body)
        assert isinstance(result["residual"], float)
        assert result["residual"] >= 0.0

    def test_errors_is_list(self):
        """errors must be a list."""
        body = self._make_box_body()
        result = validate_body_post_trim(body)
        assert isinstance(result["errors"], list)


# ---------------------------------------------------------------------------
# Group 6: Error paths
# ---------------------------------------------------------------------------

class TestErrorPaths:
    """Bad inputs produce informative errors."""

    def _surface(self):
        return make_flat_nurbs()

    def _loop(self):
        return _square_uv_loop(0.3, 0.7, 0.3, 0.7)

    def test_empty_trim_loop_raises(self):
        """trim_loop with < 2 samples raises ValueError."""
        surf = self._surface()
        with pytest.raises(ValueError, match="at least 2"):
            select_side(surf, [], np.array([0.5, 0.5, 0.0]))

    def test_single_sample_loop_raises(self):
        """trim_loop with 1 sample raises ValueError."""
        surf = self._surface()
        with pytest.raises(ValueError, match="at least 2"):
            select_side(surf, [(0.5, 0.5)], np.array([0.5, 0.5, 0.0]))

    def test_short_target_point_raises(self):
        """target_point with < 3 components raises ValueError."""
        surf = self._surface()
        with pytest.raises(ValueError):
            select_side(surf, self._loop(), np.array([0.5, 0.5]))

    def test_0d_target_point_raises(self):
        """Scalar target_point raises ValueError."""
        surf = self._surface()
        with pytest.raises(ValueError):
            select_side(surf, self._loop(), np.array(0.5))


# ---------------------------------------------------------------------------
# Group 7: Return-value contract
# ---------------------------------------------------------------------------

class TestReturnContract:
    """Ensure return dict shape and value contract is consistent."""

    def _surface(self):
        return make_flat_nurbs()

    def _loop(self):
        return _square_uv_loop(0.3, 0.7, 0.3, 0.7)

    @pytest.mark.parametrize("target,expected_side", [
        (np.array([0.5, 0.5, 0.0]), "inside"),
        (np.array([0.1, 0.1, 0.0]), "outside"),
        (np.array([0.9, 0.9, 0.0]), "outside"),
        (np.array([0.5, 0.15, 0.0]), "outside"),
    ])
    def test_side_consistency(self, target, expected_side):
        """Multiple interior/exterior points return the expected side."""
        surf = self._surface()
        loop = self._loop()
        result = select_side(surf, loop, target)
        assert result["side"] == expected_side, (
            f"Point {target} expected {expected_side!r} but got {result['side']!r}"
        )

    def test_validated_is_always_true(self):
        """validated key is always True on success."""
        surf = self._surface()
        loop = self._loop()
        for pt in [
            np.array([0.5, 0.5, 0.0]),
            np.array([0.1, 0.1, 0.0]),
        ]:
            result = select_side(surf, loop, pt)
            assert result["validated"] is True
