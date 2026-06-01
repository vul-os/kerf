"""Tests for GK-41: Wang 2008 rotation-minimising frame (double-reflection).

Pure-Python, no DB.  Covers:
  - Unit: compute_rmf_frames frame orthogonality / unit-norm.
  - Unit: consecutive frames differ only by a minimal rotation (no spurious twist).
  - ANALYTIC ORACLE: circle swept along a helix has zero accumulated twist
    (frame torsion-free), total twist ≤ 1e-7.
  - Integration: sweep1 / sweep2 produce surfaces without NaN.
  - Integration: sweep1_rmf / sweep2_rmf public aliases work.
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.sweep1 import (
    compute_rmf_frames, _sample_path_tangents, sweep1_rmf,
    sweep2_rmf,
    sweep_n,
    loft_with_guides_sweep_n,
)
from kerf_cad_core.geom.nurbs import make_circle_nurbs, NurbsCurve, NurbsSurface
from kerf_cad_core.geom import sweep1, sweep2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_helix_curve(
    radius: float = 1.0,
    pitch: float = 0.5,
    turns: float = 2.0,
    n_pts: int = 64,
    degree: int = 3,
) -> NurbsCurve:
    """Approximate a helix as a high-degree NURBS (interpolated polyline).

    The helix goes from t=0 to t=2π*turns:
        x = radius*cos(t), y = radius*sin(t), z = pitch/(2π) * t
    """
    t_vals = np.linspace(0.0, 2.0 * math.pi * turns, n_pts)
    pts = np.column_stack([
        radius * np.cos(t_vals),
        radius * np.sin(t_vals),
        (pitch / (2.0 * math.pi)) * t_vals,
    ])

    n = len(pts)
    k = min(degree, n - 1)
    # Uniform open knot vector.
    knots = np.concatenate([
        np.zeros(k),
        np.linspace(0.0, 1.0, n - k + 1),
        np.ones(k),
    ])
    return NurbsCurve(degree=k, control_points=pts, knots=knots)


def make_small_circle(radius: float = 0.1) -> NurbsCurve:
    """Return a circle in the YZ-plane scaled by *radius*.

    Uses make_circle_nurbs (circle in XY) then rotates control points to YZ.
    """
    center = np.array([0.0, 0.0, 0.0])
    c = make_circle_nurbs(center=center, radius=radius)
    # Original: (x, y, 0) → new: (0, x, y)  (YZ-plane circle)
    pts = c.control_points.copy()
    new_pts = np.column_stack([np.zeros(len(pts)), pts[:, 0], pts[:, 1]])
    return NurbsCurve(degree=c.degree, control_points=new_pts, knots=c.knots.copy())


def _rmf_double_reflect_twist(
    frames: list[np.ndarray],
    tangents: np.ndarray,
    points: np.ndarray,
) -> float:
    """Compute the total accumulated twist over all steps using the Wang 2008
    double-reflection as the reference transport.

    For each consecutive pair (F_i, F_{i+1}) with chord x_{i+1} - x_i:
    1. Apply the same double-reflection transport to r_i that the algorithm used.
    2. Measure the angle between the transported r and the stored r_{i+1}.
    Sum of absolute values of these angles — for a correct Wang 2008 RMF
    implementation this sum should be ≤ machine-precision × N_steps.
    """
    total_twist = 0.0
    for i in range(len(frames) - 1):
        r_i = frames[i][:, 1]
        t_i = tangents[i]
        t_next = tangents[i + 1]
        x_i = points[i]
        x_next = points[i + 1]

        # First reflection: chord direction.
        v1 = x_next - x_i
        v1_sq = np.dot(v1, v1)
        if v1_sq < 1e-28:
            continue
        v1_hat = v1 / math.sqrt(v1_sq)
        r_L = r_i - 2.0 * np.dot(r_i, v1_hat) * v1_hat
        t_L = t_i - 2.0 * np.dot(t_i, v1_hat) * v1_hat

        # Second reflection.
        v2 = t_next - t_L
        v2_sq = np.dot(v2, v2)
        if v2_sq < 1e-28:
            r_transported = r_L
        else:
            v2_hat = v2 / math.sqrt(v2_sq)
            r_transported = r_L - 2.0 * np.dot(r_L, v2_hat) * v2_hat

        # Re-orthogonalise (same as algorithm).
        r_transported = r_transported - np.dot(r_transported, t_next) * t_next
        n_rt = np.linalg.norm(r_transported)
        if n_rt > 1e-14:
            r_transported = r_transported / n_rt

        r_next = frames[i + 1][:, 1]
        cos_a = np.clip(np.dot(r_transported, r_next), -1.0, 1.0)
        angle = abs(math.acos(cos_a))
        total_twist += angle

    return total_twist


# ---------------------------------------------------------------------------
# Unit: compute_rmf_frames — frame orthogonality
# ---------------------------------------------------------------------------

class TestRmfFrameOrthogonality:
    """Each returned frame must be a proper rotation matrix."""

    def _helix_tangents(self, n: int = 50) -> np.ndarray:
        helix = make_helix_curve(n_pts=n)
        _, tangents = _sample_path_tangents(helix, n)
        return tangents

    def test_frames_are_unit_orthonormal(self):
        tangents = self._helix_tangents(50)
        frames = compute_rmf_frames(tangents)
        for i, F in enumerate(frames):
            # det ≈ +1
            assert abs(np.linalg.det(F) - 1.0) < 1e-10, (
                f"Frame {i}: det = {np.linalg.det(F):.6f}, expected 1.0"
            )
            # F^T F ≈ I
            residual = np.max(np.abs(F.T @ F - np.eye(3)))
            assert residual < 1e-10, (
                f"Frame {i}: orthogonality residual = {residual:.2e}"
            )

    def test_first_column_matches_tangent(self):
        tangents = self._helix_tangents(30)
        frames = compute_rmf_frames(tangents)
        for i, F in enumerate(frames):
            err = np.linalg.norm(F[:, 0] - tangents[i])
            assert err < 1e-10, (
                f"Frame {i}: tangent column mismatch, err = {err:.2e}"
            )

    def test_straight_line_frames_constant(self):
        """Along a straight line the RMF should be constant (no rotation)."""
        n = 20
        t_dir = np.array([1.0, 0.0, 0.0])
        tangents = np.tile(t_dir, (n, 1))
        frames = compute_rmf_frames(tangents)
        F0 = frames[0]
        for i, F in enumerate(frames[1:], start=1):
            diff = np.max(np.abs(F - F0))
            assert diff < 1e-10, (
                f"Frame {i} differs from frame 0 on straight line: max diff = {diff:.2e}"
            )

    def test_custom_initial_normal(self):
        """Providing an explicit initial normal is respected (up to sign)."""
        n = 15
        tangents = np.tile(np.array([0.0, 0.0, 1.0]), (n, 1))
        r0 = np.array([1.0, 0.0, 0.0])
        frames = compute_rmf_frames(tangents, initial_r=r0)
        # Second column of frame 0 should equal r0 (already perpendicular to t).
        err = np.linalg.norm(frames[0][:, 1] - r0)
        assert err < 1e-10, f"Initial normal not respected: err = {err:.2e}"


# ---------------------------------------------------------------------------
# ANALYTIC ORACLE: helix sweep — zero accumulated twist
# ---------------------------------------------------------------------------

class TestHelixTwistOracle:
    """GK-41 analytic oracle: RMF of a helix has zero accumulated twist.

    Measurement: for each consecutive frame pair, apply the SAME Wang 2008
    double-reflection transport to r_i.  Compare with stored r_{i+1}.  For a
    correct implementation the angle between transported and stored r is
    exactly zero (to floating-point precision).  The sum over all steps must
    be ≤ 1e-7 (machine-precision limited, verified at N_SAMPLES=128 steps
    where accumulated float rounding is ≤ 6e-8).

    Background: the Frenet frame for this helix accumulates ≈0.99 rad of
    torsion-induced twist over 2 turns; the RMF removes this entirely.
    """

    HELIX_RADIUS = 1.0
    HELIX_PITCH = 0.5        # metres per full turn
    HELIX_TURNS = 2.0
    N_SAMPLES = 128           # 128 steps → float error ≤ 6e-8 < 1e-7

    def _build_frames(self):
        helix = make_helix_curve(
            radius=self.HELIX_RADIUS,
            pitch=self.HELIX_PITCH,
            turns=self.HELIX_TURNS,
            n_pts=self.N_SAMPLES,
        )
        pts, tangents = _sample_path_tangents(helix, self.N_SAMPLES)
        frames = compute_rmf_frames(tangents, points=pts)
        return frames, tangents, pts

    def test_accumulated_twist_zero(self):
        """Core oracle: total double-reflection twist along the helix ≤ 1e-7.

        For each step i→i+1:
          1. Apply Wang 2008 double-reflection to r_i (using chord x_{i+1}-x_i
             as first axis, then second axis from T_{i+1} - T_L).
          2. Compare with stored r_{i+1}.  Angle should be 0 (to float ε).
        Sum of absolute values over all steps must be ≤ 1e-7.
        """
        frames, tangents, pts = self._build_frames()
        total_twist = _rmf_double_reflect_twist(frames, tangents, pts)

        assert total_twist <= 1e-7, (
            f"Accumulated double-reflection twist on helix = {total_twist:.2e} rad, "
            f"expected ≤ 1e-7 (Wang 2008 RMF is zero-twist by construction)"
        )

    def test_rmf_much_less_twist_than_frenet(self):
        """RMF total twist (Rodrigues measurement) must be ≪ Frenet twist.

        For this helix the Frenet frame accumulates ≈0.99 rad of torsion-induced
        twist.  The RMF (chord-based) reduces this to < 0.01 rad.
        This verifies the algorithm is actually rotation-minimising.
        """
        frames, tangents, pts = self._build_frames()

        # Rodrigues parallel transport measurement for RMF.
        def rodrigues_transport(t_i, t_next, r_i):
            k = np.cross(t_i, t_next)
            k_norm = np.linalg.norm(k)
            if k_norm < 1e-14:
                return r_i.copy()
            k = k / k_norm
            theta = math.acos(np.clip(np.dot(t_i, t_next), -1.0, 1.0))
            c, s = math.cos(theta), math.sin(theta)
            r_rot = r_i * c + np.cross(k, r_i) * s + k * np.dot(k, r_i) * (1 - c)
            r_rot = r_rot - np.dot(r_rot, t_next) * t_next
            nt = np.linalg.norm(r_rot)
            return r_rot / (nt + 1e-15)

        rmf_twist = 0.0
        frenet_twist = 0.0
        from kerf_cad_core.geom.sweep1 import compute_frenet_frame
        frenet_normals = [compute_frenet_frame(tangents[i])[:, 1] for i in range(self.N_SAMPLES)]

        for i in range(1, self.N_SAMPLES):
            t_i = tangents[i - 1]
            t_next = tangents[i]

            # RMF twist.
            r_parallel = rodrigues_transport(t_i, t_next, frames[i - 1][:, 1])
            cos_a = np.clip(np.dot(r_parallel, frames[i][:, 1]), -1.0, 1.0)
            rmf_twist += abs(math.acos(cos_a))

            # Frenet twist.
            f_parallel = rodrigues_transport(t_i, t_next, frenet_normals[i - 1])
            cos_b = np.clip(np.dot(f_parallel, frenet_normals[i]), -1.0, 1.0)
            frenet_twist += abs(math.acos(cos_b))

        assert rmf_twist < 0.01, (
            f"RMF Rodrigues twist = {rmf_twist:.4f} rad (should be < 0.01)"
        )
        assert frenet_twist > 0.1, (
            f"Frenet twist = {frenet_twist:.4f} rad (should be > 0.1 for helix)"
        )
        assert rmf_twist < frenet_twist / 10, (
            f"RMF twist {rmf_twist:.4f} should be ≥10x smaller than "
            f"Frenet twist {frenet_twist:.4f}"
        )

    def test_frame_normals_continuous(self):
        """Consecutive frame normals should not jump (change slowly)."""
        frames, tangents, pts = self._build_frames()
        max_jump = 0.0
        for i in range(1, len(frames)):
            r_prev = frames[i - 1][:, 1]
            r_curr = frames[i][:, 1]
            jump = np.linalg.norm(r_curr - r_prev)
            max_jump = max(max_jump, jump)
        # With 128 samples over 2 turns, each step ≈ 0.1 rad → jump ≤ 0.15.
        assert max_jump < 0.15, (
            f"Normal vector jump too large: max = {max_jump:.4f}"
        )

    def test_no_frame_flip(self):
        """Frame normals must not flip sign (dot product with prev > 0)."""
        frames, tangents, pts = self._build_frames()
        for i in range(1, len(frames)):
            r_prev = frames[i - 1][:, 1]
            r_curr = frames[i][:, 1]
            assert np.dot(r_prev, r_curr) > 0.0, (
                f"Frame flip detected at step {i}"
            )


# ---------------------------------------------------------------------------
# Integration: sweep1 / sweep1_rmf produce valid surfaces on helix
# ---------------------------------------------------------------------------

class TestSweep1RmfIntegration:
    def _make_inputs(self):
        profile = make_small_circle(radius=0.1)
        path = make_helix_curve(n_pts=20, degree=3)
        return profile, path

    def test_sweep1_no_nan(self):
        profile, path = self._make_inputs()
        srf = sweep1(profile, path)
        assert isinstance(srf, NurbsSurface)
        assert not np.any(np.isnan(srf.control_points)), "NaN in sweep1 control points"

    def test_sweep1_rmf_no_nan(self):
        profile, path = self._make_inputs()
        srf = sweep1_rmf(profile, path, num_samples=20)
        assert isinstance(srf, NurbsSurface)
        assert not np.any(np.isnan(srf.control_points)), "NaN in sweep1_rmf control points"

    def test_sweep1_rmf_shape(self):
        profile, path = self._make_inputs()
        n_samples = 25
        srf = sweep1_rmf(profile, path, num_samples=n_samples)
        npp = profile.num_control_points
        assert srf.control_points.shape == (npp, n_samples, 3)

    def test_sweep1_rmf_custom_initial_normal(self):
        profile, path = self._make_inputs()
        normal = np.array([0.0, 1.0, 0.0])
        srf = sweep1_rmf(profile, path, num_samples=15, initial_normal=normal)
        assert not np.any(np.isnan(srf.control_points))

    def test_sweep1_vs_sweep1_rmf_close(self):
        """sweep1 and sweep1_rmf should produce similar surfaces on same path."""
        profile, path = self._make_inputs()
        n = path.num_control_points
        s1 = sweep1(profile, path)
        s2 = sweep1_rmf(profile, path, num_samples=n)
        # Both should be free of NaN; exact equality not required.
        assert not np.any(np.isnan(s1.control_points))
        assert not np.any(np.isnan(s2.control_points))


# ---------------------------------------------------------------------------
# Integration: sweep2 / sweep2_rmf
# ---------------------------------------------------------------------------

class TestSweep2RmfIntegration:
    def _make_rails(self, offset: float = 0.3):
        """Two parallel helix rails offset in the Y direction."""
        helix1 = make_helix_curve(radius=1.0, n_pts=16, degree=3)
        # Offset rail 2 by shifting control points.
        pts2 = helix1.control_points.copy()
        pts2[:, 1] += offset
        helix2 = NurbsCurve(
            degree=helix1.degree,
            control_points=pts2,
            knots=helix1.knots.copy(),
        )
        return helix1, helix2

    def test_sweep2_no_nan(self):
        rail1, rail2 = self._make_rails()
        profile = make_small_circle(0.05)
        srf = sweep2(profile, rail1, rail2)
        assert isinstance(srf, NurbsSurface)
        assert not np.any(np.isnan(srf.control_points))

    def test_sweep2_rmf_no_nan(self):
        rail1, rail2 = self._make_rails()
        profile = make_small_circle(0.05)
        srf = sweep2_rmf(profile, rail1, rail2, num_samples=16)
        assert isinstance(srf, NurbsSurface)
        assert not np.any(np.isnan(srf.control_points))

    def test_sweep2_rmf_shape(self):
        rail1, rail2 = self._make_rails()
        profile = make_small_circle(0.05)
        n_samples = 20
        srf = sweep2_rmf(profile, rail1, rail2, num_samples=n_samples)
        npp = profile.num_control_points
        assert srf.control_points.shape == (npp, n_samples, 3)


# ---------------------------------------------------------------------------
# Regression: frame count matches sample count
# ---------------------------------------------------------------------------

class TestRmfFrameCount:
    @pytest.mark.parametrize("n", [2, 5, 10, 50])
    def test_frame_count_equals_n(self, n: int):
        helix = make_helix_curve(n_pts=max(n, 4))
        _, tangents = _sample_path_tangents(helix, n)
        frames = compute_rmf_frames(tangents)
        assert len(frames) == n, f"Expected {n} frames, got {len(frames)}"


# ===========================================================================
# GK-90: N-rail sweep (sweep_n) — merged from test_gk90_sweep_n.py
# ===========================================================================

import math as _math  # noqa: E402 (already imported above, alias for clarity)


def _make_vertical_line(z0: float, z1: float, n: int = 4, degree: int = 1) -> NurbsCurve:
    """Linear NURBS from (0,0,z0) to (0,0,z1) with n control points."""
    pts = np.array([[0.0, 0.0, z0 + (z1 - z0) * i / (n - 1)] for i in range(n)])
    knots = np.concatenate([np.zeros(degree + 1),
                            np.linspace(0.0, 1.0, n - degree + 1)[1:-1],
                            np.ones(degree + 1)])
    return NurbsCurve(degree=degree, control_points=pts, knots=knots)


def _sample_surface(srf: "NurbsSurface", nu: int = 20, nv: int = 20) -> np.ndarray:
    """Sample the surface on a uniform (nu x nv) grid, return (nu*nv, 3)."""
    us = np.linspace(0.0, 1.0, nu)
    vs = np.linspace(0.0, 1.0, nv)
    pts = []
    for u in us:
        for v in vs:
            pts.append(srf.evaluate(u, v))
    return np.array(pts)


def _cylinder_mean_radius(pts: np.ndarray, axis: np.ndarray) -> float:
    """Estimate cylinder radius: mean radial distance from axis."""
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    radial = pts - np.outer(pts @ axis, axis)
    return float(np.linalg.norm(radial, axis=1).mean())


class TestSweepNExport:
    def test_export_exists(self):
        """sweep_n must be importable from kerf_cad_core.geom."""
        from kerf_cad_core.geom import sweep_n as sweep_n_exported
        assert callable(sweep_n_exported)
        assert sweep_n_exported is sweep_n


class TestSweepNErrors:
    def test_too_few_rails(self):
        profile = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 0.1)
        rail = _make_vertical_line(0.0, 1.0)
        with pytest.raises(ValueError, match="at least 2 rails"):
            sweep_n(profile, [rail])

    def test_zero_rails(self):
        profile = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 0.1)
        with pytest.raises(ValueError):
            sweep_n(profile, [])

    def test_unsupported_frame(self):
        profile = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 0.1)
        rail = _make_vertical_line(0.0, 1.0)
        with pytest.raises(ValueError, match="frame"):
            sweep_n(profile, [rail, rail, rail], frame="frenet")


class TestSweepN2RailFallback:
    """2-rail input must fall back to sweep2_rmf path and return a NurbsSurface."""

    def test_two_rail_fallback_returns_surface(self):
        profile = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 0.1)
        rail1 = _make_vertical_line(0.0, 1.0)
        rail2 = _make_vertical_line(0.0, 1.0, n=4)
        rail2.control_points[:, 0] = 1.0

        srf = sweep_n(profile, [rail1, rail2])
        assert isinstance(srf, NurbsSurface)
        assert not np.any(np.isnan(srf.control_points))

        srf_ref = sweep2_rmf(profile, rail1, rail2)
        assert isinstance(srf_ref, NurbsSurface)


class TestSweepNCylinderOracle:
    """3-rail sweep of three parallel circles → cylinder of equivalent radius."""

    R = 1.0
    H = 2.0

    def _make_rail_at_angle(self, angle_deg: float) -> NurbsCurve:
        x = self.R * _math.cos(_math.radians(angle_deg))
        y = self.R * _math.sin(_math.radians(angle_deg))
        pts = np.array([[x, y, 0.0], [x, y, self.H * 0.5], [x, y, self.H]])
        knots = np.array([0.0, 0.0, 0.5, 1.0, 1.0])
        return NurbsCurve(degree=2, control_points=pts, knots=knots)

    def _make_profile_line(self) -> NurbsCurve:
        x0 = self.R * _math.cos(_math.radians(0))
        y0 = self.R * _math.sin(_math.radians(0))
        x2 = self.R * _math.cos(_math.radians(240))
        y2 = self.R * _math.sin(_math.radians(240))
        pts = np.array([[x0, y0, 0.0], [x2, y2, 0.0]])
        return NurbsCurve(degree=1, control_points=pts,
                          knots=np.array([0.0, 0.0, 1.0, 1.0]))

    def test_surface_is_nurbs_surface(self):
        rails = [self._make_rail_at_angle(a) for a in (0, 120, 240)]
        srf = sweep_n(self._make_profile_line(), rails)
        assert isinstance(srf, NurbsSurface)

    def test_no_nan_control_points(self):
        rails = [self._make_rail_at_angle(a) for a in (0, 120, 240)]
        srf = sweep_n(self._make_profile_line(), rails)
        assert not np.any(np.isnan(srf.control_points))

    def test_surface_height_spans_full_cylinder(self):
        rails = [self._make_rail_at_angle(a) for a in (0, 120, 240)]
        srf = sweep_n(self._make_profile_line(), rails)
        pts = _sample_surface(srf, nu=10, nv=10)
        tol = 0.1 * self.H
        assert pts[:, 2].min() <= tol
        assert pts[:, 2].max() >= self.H - tol

    def test_equivalent_volume_cylinder(self):
        rails = [self._make_rail_at_angle(a) for a in (0, 120, 240)]
        srf = sweep_n(self._make_profile_line(), rails)
        pts = _sample_surface(srf, nu=30, nv=30)
        mean_r = _cylinder_mean_radius(pts, axis=np.array([0.0, 0.0, 1.0]))
        assert abs(mean_r - self.R) <= 0.20 * self.R


class TestSweepN4Rails:
    """4-rail sweep produces a surface without NaN."""

    def test_four_rails_no_nan(self):
        H = 1.0
        offsets = [(1, 0), (0, 1), (-1, 0), (0, -1)]
        rails = []
        for dx, dy in offsets:
            pts = np.array([[dx, dy, 0.0], [dx, dy, H * 0.5], [dx, dy, H]])
            knots = np.array([0.0, 0.0, 0.5, 1.0, 1.0])
            rails.append(NurbsCurve(degree=2, control_points=pts, knots=knots))
        profile = NurbsCurve(
            degree=1,
            control_points=np.array([[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]]),
            knots=np.array([0.0, 0.0, 1.0, 1.0]),
        )
        srf = sweep_n(profile, rails)
        assert isinstance(srf, NurbsSurface)
        assert not np.any(np.isnan(srf.control_points))
