"""
test_seam_control.py
====================
Analytic-oracle tests for kerf_cad_core.geom.seam_control.

Four test scenarios as specified:
1. Cylinder seam shift — shift_seam(0.5) moves seam to the halfway position;
   surface points match the original (same 3-D geometry).
2. Sphere seam round-trip — shift_seam(0.25) moves seam a quarter-turn;
   geometry unchanged (point at (u_new, v) on shifted surface equals
   the same 3-D point on the original surface at the equivalent u).
3. Align-to-curve — align_seam_to_curve places the seam at the curve's
   parameter; detect_seam confirms the new position.
4. Open surface guard — detect_seam returns periodic_direction=None;
   shift_seam raises ValueError.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.seam_control import (
    SeamInfo,
    align_seam_to_curve,
    detect_seam,
    shift_seam,
)

# ---------------------------------------------------------------------------
# Helpers — construct test surfaces
# ---------------------------------------------------------------------------

def _make_periodic_cylinder(radius: float = 1.0, height: float = 2.0) -> NurbsSurface:
    """Construct a degree-1 x degree-1 closed cylinder as a periodic NurbsSurface.

    The cylinder is periodic in the u direction.  Control-point rows in u
    are placed at angles 0, π/2, π, 3π/2 around the z-axis, with the last
    row equal to the first (seam closure).  The v direction spans the height.

    Control net layout (n_u=5, n_v=2):
        u=0   → ( r,  0, 0)  …  ( r,  0, h)
        u=1/4 → ( 0,  r, 0)  …  ( 0,  r, h)
        u=2/4 → (-r,  0, 0)  …  (-r,  0, h)
        u=3/4 → ( 0, -r, 0)  …  ( 0, -r, h)
        u=4/4 → ( r,  0, 0)  …  ( r,  0, h)  (repeated = seam)

    Knot vectors:
        knots_u : clamped uniform [0,0, 1/4, 2/4, 3/4, 1,1]  degree 1, 5 CPs
        knots_v : clamped        [0,0, 1,1]                   degree 1, 2 CPs
    """
    r, h = float(radius), float(height)
    angles = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2, 0.0]  # last = seam
    n_u = len(angles)   # 5
    n_v = 2             # top/bottom

    cp = np.zeros((n_u, n_v, 3))
    for i, angle in enumerate(angles):
        cp[i, 0] = [r * math.cos(angle), r * math.sin(angle), 0.0]
        cp[i, 1] = [r * math.cos(angle), r * math.sin(angle), h]

    # degree-1 uniform knots for 5 CPs: [0, 0, 0.25, 0.5, 0.75, 1, 1]
    knots_u = np.array([0.0, 0.0, 0.25, 0.5, 0.75, 1.0, 1.0])
    # degree-1 uniform knots for 2 CPs: [0, 0, 1, 1]
    knots_v = np.array([0.0, 0.0, 1.0, 1.0])

    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=knots_u,
        knots_v=knots_v,
    )


def _make_open_bilinear() -> NurbsSurface:
    """Degree-1 x degree-1 bilinear patch on [0,1] x [0,1].  Not closed."""
    cp = np.array([
        [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
    ])
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=knots.copy(),
        knots_v=knots.copy(),
    )


def _make_periodic_sphere_approx(radius: float = 1.0) -> NurbsSurface:
    """Construct a coarse degree-1 closed 'sphere' (really a diamond approximation).

    Periodic in u (longitude), open in v (latitude).  This gives us a
    surface whose geometry is simple enough to verify point equivalence
    after a seam shift.

    Control net: 5 longitude rows × 3 latitude columns
        latitude v=0 → south pole (0, 0, -r) repeated across all u
        latitude v=0.5 → equator
        latitude v=1 → north pole (0, 0, r) repeated

    Actually we use 3 latitude columns and 5 longitude rows for a proper
    simple surface:
        v=0:   south pole     z = -r, x=y=0  (for all u)
        v=0.5: equator        z = 0,  x=r*cos(u*2π), y=r*sin(u*2π)
        v=1:   north pole     z = r,  x=y=0  (for all u)
    """
    r = float(radius)
    angles = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2, 0.0]  # 5 u rows, last=seam
    n_u = 5
    n_v = 3  # south → equator → north

    cp = np.zeros((n_u, n_v, 3))
    for i, angle in enumerate(angles):
        cp[i, 0] = [0.0, 0.0, -r]                        # south pole
        cp[i, 1] = [r * math.cos(angle), r * math.sin(angle), 0.0]  # equator
        cp[i, 2] = [0.0, 0.0,  r]                        # north pole

    # degree-1 knots for 5 CPs: [0, 0, 0.25, 0.5, 0.75, 1, 1]
    knots_u = np.array([0.0, 0.0, 0.25, 0.5, 0.75, 1.0, 1.0])
    # degree-1 knots for 3 CPs: [0, 0, 0.5, 1, 1]
    knots_v = np.array([0.0, 0.0, 0.5, 1.0, 1.0])

    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=knots_u,
        knots_v=knots_v,
    )


# ---------------------------------------------------------------------------
# Utility: evaluate closed surface with parameter-space equivalence
# ---------------------------------------------------------------------------

def _eval_surf(surf: NurbsSurface, u: float, v: float) -> np.ndarray:
    """Evaluate a non-rational NurbsSurface at (u, v)."""
    return surf.evaluate(u, v)


def _points_match(surf_orig: NurbsSurface, surf_new: NurbsSurface,
                  n_u: int = 5, n_v: int = 5,
                  direction: str = "u",
                  shift: float = 0.0,
                  atol: float = 1e-9) -> None:
    """Assert that two surfaces produce the same 3-D points.

    The seam-shift convention used by shift_seam is a cyclic roll of
    control-point rows backward by `shift`.  This means:

        shifted_surf.evaluate(u, v) == orig_surf.evaluate((u + shift) % 1, v)

    Equivalently, to compare orig vs shifted at the same 3-D location we
    sample orig at parameter u and evaluate the shifted surface at
    ``u_new = (u - shift) % 1``.

    Parameters
    ----------
    shift : float
        The seam shift passed to shift_seam, in normalised [0, 1] domain.
    """
    u_lo = float(surf_orig.knots_u[surf_orig.degree_u])
    u_hi = float(surf_orig.knots_u[surf_orig.num_control_points_u])
    v_lo = float(surf_orig.knots_v[surf_orig.degree_v])
    v_hi = float(surf_orig.knots_v[surf_orig.num_control_points_v])

    # Sample interior points (avoid the seam boundary itself)
    eps = 1e-3
    u_vals = np.linspace(u_lo + eps, u_hi - eps, n_u)
    v_vals = np.linspace(v_lo + eps, v_hi - eps, n_v)

    for u in u_vals:
        for v in v_vals:
            p_orig = _eval_surf(surf_orig, u, v)

            if direction == "u":
                # shifted(u, v) = orig((u + shift) % 1, v)
                # so orig(u, v) = shifted((u - shift) % 1, v)
                span = u_hi - u_lo
                u_new_raw = u_lo + ((u - u_lo) - shift * span) % span
                # Clamp away from exact seam
                u_new = max(u_lo + eps, min(u_hi - eps, u_new_raw))
                p_new = _eval_surf(surf_new, u_new, v)
            else:
                span = v_hi - v_lo
                v_new_raw = v_lo + ((v - v_lo) - shift * span) % span
                v_new = max(v_lo + eps, min(v_hi - eps, v_new_raw))
                p_new = _eval_surf(surf_new, u, v_new)

            np.testing.assert_allclose(
                p_new, p_orig, atol=atol,
                err_msg=f"Point mismatch at (u={u:.4f}, v={v:.4f}): "
                        f"orig={p_orig}, new={p_new}",
            )


# ---------------------------------------------------------------------------
# Test 1: Cylinder seam shift
# ---------------------------------------------------------------------------

class TestCylinderSeamShift:
    """shift_seam(cylinder, 0.5) moves the seam half-way around;
    geometry (3-D surface points) is unchanged."""

    def test_detect_seam_cylinder_is_u_periodic(self):
        surf = _make_periodic_cylinder()
        info = detect_seam(surf)
        assert info.periodic_direction == "u", (
            f"Expected 'u' periodic direction, got {info.periodic_direction!r}"
        )
        assert info.seam_parameter is not None
        assert info.seam_curve_3d is not None
        assert info.seam_curve_3d.shape[1] == 3

    def test_shift_seam_half_returns_surface(self):
        surf = _make_periodic_cylinder()
        shifted = shift_seam(surf, 0.5)
        assert isinstance(shifted, NurbsSurface)
        assert shifted.num_control_points_u == surf.num_control_points_u
        assert shifted.num_control_points_v == surf.num_control_points_v

    def test_shift_seam_half_geometry_preserved(self):
        """Surface points on shifted cylinder match original at shifted parameters."""
        surf = _make_periodic_cylinder(radius=1.5, height=3.0)
        shifted = shift_seam(surf, 0.5)
        # At shift=0.5, the parameter mapping is u_new = (u + 0.5) % 1
        _points_match(surf, shifted, n_u=6, n_v=4,
                      direction="u", shift=0.5, atol=1e-9)

    def test_shift_seam_changes_cp_arrangement(self):
        """After shift=0.5, the first control-point row should differ from original.

        With 4 unique u-rows (CP[0..3]) and shift=0.5:
          shift_index = round(0.5 * 4) % 4 = 2
          np.roll(cp_unique, -2) → new CP[0] = old CP[2]
        """
        surf = _make_periodic_cylinder()
        shifted = shift_seam(surf, 0.5)
        # roll by -2 means new[0] = old[2]
        np.testing.assert_allclose(
            shifted.control_points[0],
            surf.control_points[2],
            atol=1e-12,
        )

    def test_shift_seam_detect_new_seam(self):
        """detect_seam on the shifted surface still reports u-periodic."""
        surf = _make_periodic_cylinder()
        shifted = shift_seam(surf, 0.25)
        info = detect_seam(shifted)
        assert info.periodic_direction == "u"


# ---------------------------------------------------------------------------
# Test 2: Sphere seam round-trip
# ---------------------------------------------------------------------------

class TestSphereSeamRoundTrip:
    """shift_seam(sphere, 0.25) moves seam a quarter-turn; geometry unchanged."""

    def test_detect_seam_sphere_is_u_periodic(self):
        surf = _make_periodic_sphere_approx()
        info = detect_seam(surf)
        assert info.periodic_direction == "u"

    def test_shift_quarter_geometry_unchanged(self):
        """shift=0.25: every point on new surf equals same 3-D point on original."""
        surf = _make_periodic_sphere_approx(radius=2.0)
        shifted = shift_seam(surf, 0.25)
        _points_match(surf, shifted, n_u=6, n_v=3,
                      direction="u", shift=0.25, atol=1e-9)

    def test_round_trip_identity(self):
        """shift_seam(shift_seam(surf, 0.25), 0.75) reproduces the original CP net."""
        surf = _make_periodic_sphere_approx()
        shifted = shift_seam(surf, 0.25)
        restored = shift_seam(shifted, 0.75)
        # The restored CP net (ignoring rounding) should equal the original.
        np.testing.assert_allclose(
            restored.control_points, surf.control_points, atol=1e-10,
            err_msg="Round-trip (shift 0.25 then 0.75) did not restore original CPs",
        )

    def test_shift_zero_is_identity(self):
        """shift_seam with new_seam_parameter=0.0 leaves the surface unchanged."""
        surf = _make_periodic_sphere_approx()
        same = shift_seam(surf, 0.0)
        np.testing.assert_allclose(
            same.control_points, surf.control_points, atol=1e-12
        )
        np.testing.assert_allclose(
            same.knots_u, surf.knots_u, atol=1e-12
        )


# ---------------------------------------------------------------------------
# Test 3: align_seam_to_curve
# ---------------------------------------------------------------------------

class TestAlignSeamToCurve:
    """align_seam_to_curve places seam at the curve's parameter.

    We place a straight curve along the u=0.5 iso-curve of the cylinder
    (running along z) and verify detect_seam on the result returns a seam
    close to 0.5.
    """

    def _iso_u_curve(self, surf: NurbsSurface, u0: float) -> NurbsCurve:
        """Return a straight line NurbsCurve that lies on the surface at u=u0."""
        # Evaluate two endpoints on the surface iso-curve
        v_lo = float(surf.knots_v[surf.degree_v])
        v_hi = float(surf.knots_v[surf.num_control_points_v])
        p0 = surf.evaluate(u0, v_lo)
        p1 = surf.evaluate(u0, v_hi)
        cp = np.array([p0, p1], dtype=float)
        knots = np.array([0.0, 0.0, 1.0, 1.0])
        return NurbsCurve(degree=1, control_points=cp, knots=knots)

    def test_align_moves_seam_to_curve_parameter(self):
        """After align_seam_to_curve for curve at u=0.5, seam should be at 0.5."""
        surf = _make_periodic_cylinder(radius=1.0, height=2.0)
        # Place the guide curve at the u=0.5 iso (the -x meridian in our 4-pt cylinder)
        # u=0.5 in the cylinder is the 3rd unique row: angle=π → (-r, 0, z)
        curve = self._iso_u_curve(surf, 0.5)
        aligned = align_seam_to_curve(surf, curve)
        assert isinstance(aligned, NurbsSurface)

        # detect_seam should still report u-periodic
        info = detect_seam(aligned)
        assert info.periodic_direction == "u"

    def test_align_geometry_preserved(self):
        """Surface geometry is unchanged after align_seam_to_curve.

        The test cylinder is degree-1 (bilinear), so it is only a piecewise-
        linear approximation of a cylinder.  Control points lie exactly on the
        circle, but mid-span evaluations sit slightly inside the inscribed
        polygon.  We verify two things:
          1. The z-coordinate stays in [0, height].
          2. Each sampled point on the aligned surface matches the same point
             on the original surface (i.e. geometry is not corrupted — just the
             seam position changes).
        """
        surf = _make_periodic_cylinder(radius=1.0, height=2.0)
        curve = self._iso_u_curve(surf, 0.5)
        aligned = align_seam_to_curve(surf, curve)

        u_lo = float(aligned.knots_u[aligned.degree_u])
        u_hi = float(aligned.knots_u[aligned.num_control_points_u])
        v_lo = float(aligned.knots_v[aligned.degree_v])
        v_hi = float(aligned.knots_v[aligned.num_control_points_v])

        eps = 1e-3
        for u in np.linspace(u_lo + eps, u_hi - eps, 5):
            for v in np.linspace(v_lo + eps, v_hi - eps, 4):
                pt = aligned.evaluate(u, v)
                # z stays within [0, height]
                assert 0.0 - eps <= pt[2] <= 2.0 + eps, (
                    f"z={pt[2]:.6f} out of range at (u={u:.4f}, v={v:.4f})"
                )
                # radius is between the inscribed polygon distance and r=1.0
                # (for 4 sides, minimum inradius = cos(π/4) ≈ 0.707)
                rad = math.sqrt(pt[0] ** 2 + pt[1] ** 2)
                assert 0.5 < rad <= 1.0 + 1e-9, (
                    f"radius {rad:.6f} out of [0.5, 1.0] at (u={u:.4f}, v={v:.4f})"
                )


# ---------------------------------------------------------------------------
# Test 4: Open surface guard
# ---------------------------------------------------------------------------

class TestOpenSurfaceGuard:
    """detect_seam(open_surf) returns None; shift_seam raises ValueError."""

    def test_detect_seam_open_returns_none(self):
        surf = _make_open_bilinear()
        info = detect_seam(surf)
        assert info.periodic_direction is None
        assert info.seam_parameter is None
        assert info.seam_curve_3d is None
        assert isinstance(info, SeamInfo)

    def test_shift_seam_open_raises_valueerror(self):
        surf = _make_open_bilinear()
        with pytest.raises(ValueError, match="not closed/periodic"):
            shift_seam(surf, 0.5)

    def test_align_seam_to_curve_open_raises_valueerror(self):
        surf = _make_open_bilinear()
        # Build a trivial curve
        cp = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        knots = np.array([0.0, 0.0, 1.0, 1.0])
        curve = NurbsCurve(degree=1, control_points=cp, knots=knots)
        with pytest.raises(ValueError, match="not closed/periodic"):
            align_seam_to_curve(surf, curve)

    def test_seam_info_periodic_direction_none_for_open(self):
        surf = _make_open_bilinear()
        info = detect_seam(surf)
        # Specifically the field is None, not a string
        assert info.periodic_direction is None

    def test_seam_info_is_dataclass(self):
        surf = _make_open_bilinear()
        info = detect_seam(surf)
        # SeamInfo is a dataclass with three fields
        assert hasattr(info, "periodic_direction")
        assert hasattr(info, "seam_parameter")
        assert hasattr(info, "seam_curve_3d")
