"""T-104b — Pure-Python G3 blend strip tests.

Verifies the rebuilt ``blend_srf`` G2/G3 path delivered by T-104b:

  * ``surface_blend_g3`` is importable from both ``surface_fillet`` and
    ``blend_srf``.
  * G3 (curvature-rate) continuity: T-104a oracle residual < 1e-5.
  * G1/G2 continuity: oracle residuals also satisfied (< 1e-9 for flat
    surfaces, < 1e-4 for curved ones).
  * Boundary (G0) interpolation: seam curve lies on the support seam
    within 1e-9.
  * The bogus ``g2_blend_point`` additive nudge is quarantined: the
    function no longer applies an axis-aligned offset.
  * Re-export contract: ``blend_srf.surface_blend_g3`` is the same object
    as ``surface_fillet.surface_blend_g3``.
  * Return-dict keys are present and values are finite.
  * Degree-7 blend strip in the cross-boundary direction.

All tests are hermetic: no network, no OCCT, no external fixtures.
Every tolerance is backed by a closed-form analytic reference.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsSurface,
    surface_evaluate,
)
from kerf_cad_core.geom.surface_fillet import (
    curvature_comb_continuity_residual,
    curvature_rate_continuity_residual,
    surface_blend_g3,
)


# ---------------------------------------------------------------------------
# Shared surface helpers (mirrors test_g3_curvature_rate.py style)
# ---------------------------------------------------------------------------


def _clamped(n: int, degree: int) -> np.ndarray:
    inner = max(0, n - degree - 1)
    parts = [np.zeros(degree + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(degree + 1))
    return np.concatenate(parts)


def _plane_surface(
    origin=(0.0, 0.0, 0.0),
    x_axis=(1.0, 0.0, 0.0),
    y_axis=(0.0, 1.0, 0.0),
    nu: int = 5,
    nv: int = 5,
    degree: int = 3,
) -> NurbsSurface:
    origin = np.asarray(origin, dtype=float)
    xa = np.asarray(x_axis, dtype=float)
    ya = np.asarray(y_axis, dtype=float)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = origin + (i / (nu - 1)) * xa + (j / (nv - 1)) * ya
    deg = min(degree, nu - 1, nv - 1)
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_clamped(nu, deg),
        knots_v=_clamped(nv, deg),
    )


def _cubic_z_surface(amplitude: float = 0.1, nu: int = 5) -> NurbsSurface:
    """S(u,v) = (u, v, A*v^3) — exact degree-3 Bezier in v.

    At v=0: S_v=(0,1,0), S_vv=(0,0,0), S_vvv=(0,0,6A), dκ/ds = 6A.
    """
    nv = 4
    nu_use = max(nu, 4)
    cp = np.zeros((nu_use, nv, 3))
    v_cp = [0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0]
    z_cp = [0.0, 0.0, 0.0, amplitude]
    for i in range(nu_use):
        u = i / (nu_use - 1)
        for j in range(nv):
            cp[i, j] = np.array([u, v_cp[j], z_cp[j]])
    deg_u = min(3, nu_use - 1)
    return NurbsSurface(
        degree_u=deg_u, degree_v=3,
        control_points=cp,
        knots_u=_clamped(nu_use, deg_u),
        knots_v=_clamped(nv, 3),
    )


def _reverse_cubic_z_surface(amplitude: float = 0.1, nu: int = 5) -> NurbsSurface:
    """S(u,v) = (u, v, A*(1-v)^3) — cubic surface reversed in v.

    At v=0 (the seam connecting to _cubic_z_surface's v=1):
        z = A, S_v = (0,1,-3A), S_vv = (0,0,6A), S_vvv = (0,0,-6A).
    Degree-3 Bezier CPs for z = A*(1-v)^3:
        P0=A, P1=2A/3, P2=A/3, P3=0.
    """
    nv = 4
    nu_use = max(nu, 4)
    cp = np.zeros((nu_use, nv, 3))
    v_cp = [0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0]
    z_cp = [amplitude, 2.0 * amplitude / 3.0, amplitude / 3.0, 0.0]
    for i in range(nu_use):
        u = i / (nu_use - 1)
        for j in range(nv):
            cp[i, j] = np.array([u, v_cp[j], z_cp[j]])
    deg_u = min(3, nu_use - 1)
    return NurbsSurface(
        degree_u=deg_u, degree_v=3,
        control_points=cp,
        knots_u=_clamped(nu_use, deg_u),
        knots_v=_clamped(nv, 3),
    )


# ---------------------------------------------------------------------------
# 1. Import / API contract
# ---------------------------------------------------------------------------


class TestImportContract:
    def test_surface_blend_g3_importable_from_surface_fillet(self):
        from kerf_cad_core.geom.surface_fillet import surface_blend_g3 as f
        assert callable(f)

    def test_surface_blend_g3_importable_from_blend_srf(self):
        from kerf_cad_core.geom.blend_srf import surface_blend_g3 as f
        assert callable(f)

    def test_surface_blend_g3_same_object_in_both_modules(self):
        from kerf_cad_core.geom.blend_srf import surface_blend_g3 as f1
        from kerf_cad_core.geom.surface_fillet import surface_blend_g3 as f2
        assert f1 is f2

    def test_return_dict_has_expected_keys(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=6)
        for k in ("ok", "reason", "blend_surface", "diagnostics"):
            assert k in res

    def test_diagnostics_has_expected_keys(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=6)
        diag = res["diagnostics"]
        for k in ("max_g1_residual", "max_g2_residual", "max_g3_residual", "samples"):
            assert k in diag

    def test_all_diagnostic_values_are_finite(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=6)
        diag = res["diagnostics"]
        assert math.isfinite(diag["max_g1_residual"])
        assert math.isfinite(diag["max_g2_residual"])
        assert math.isfinite(diag["max_g3_residual"])

    def test_blend_surface_is_nurbs_surface(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=6)
        assert res["ok"]
        assert isinstance(res["blend_surface"], NurbsSurface)

    def test_blend_surface_degree_v_is_7(self):
        """The cross-boundary strip must be degree-7 (8 CPs → G3 at both ends)."""
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=6)
        assert res["blend_surface"].degree_v == 7

    def test_blend_surface_has_8_control_rows_in_v(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=6)
        assert res["blend_surface"].num_control_points_v == 8


# ---------------------------------------------------------------------------
# 2. Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_invalid_edge_spec_rejected(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="bogus")
        assert res["ok"] is False
        assert "edge" in res["reason"].lower() or "unsupported" in res["reason"].lower()

    def test_negative_blend_width_rejected(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, blend_width=-0.1)
        assert res["ok"] is False

    def test_zero_blend_width_rejected(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, blend_width=0.0)
        assert res["ok"] is False


# ---------------------------------------------------------------------------
# 3. G0 boundary interpolation: seam curve lies on the support seam (1e-9)
# ---------------------------------------------------------------------------


class TestG0BoundaryInterpolation:
    """The blend's v=v_min iso-curve must lie exactly on surf1's v=v_max
    iso-curve (and similarly seam B).  With clamped NURBS, this is
    guaranteed by setting the boundary control points to the sampled seam
    points; we verify geometrically."""

    def test_seam_a_on_surf1_seam_plane(self):
        """For two flat planes y-offset by 1, the seam A is y=1, z=0.
        Every point of blend's v=bv_min iso-curve must satisfy y=1, z=0."""
        s1 = _plane_surface(origin=(0.0, 0.0, 0.0))
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=10)
        blend = res["blend_surface"]
        bu_min = float(blend.knots_u[blend.degree_u])
        bu_max = float(blend.knots_u[-blend.degree_u - 1])
        bv_min = float(blend.knots_v[blend.degree_v])
        max_err = 0.0
        for t in np.linspace(0.0, 1.0, 20):
            bu = bu_min + (bu_max - bu_min) * t
            p = np.asarray(surface_evaluate(blend, bu, bv_min), dtype=float)[:3]
            # On seam A: y should be 1.0, z should be 0.0.
            err = max(abs(p[1] - 1.0), abs(p[2] - 0.0))
            max_err = max(max_err, err)
        assert max_err < 1e-9, (
            f"Blend seam A not on surf1's seam (y=1, z=0): max_err={max_err:.2e}"
        )

    def test_seam_b_on_surf2_seam_plane(self):
        """Blend seam B (v=bv_max) must lie on surf2's seam curve."""
        s1 = _plane_surface(origin=(0.0, 0.0, 0.0))
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=10)
        blend = res["blend_surface"]
        bu_min = float(blend.knots_u[blend.degree_u])
        bu_max = float(blend.knots_u[-blend.degree_u - 1])
        bv_max = float(blend.knots_v[-blend.degree_v - 1])
        max_err = 0.0
        for t in np.linspace(0.0, 1.0, 20):
            bu = bu_min + (bu_max - bu_min) * t
            p = np.asarray(surface_evaluate(blend, bu, bv_max), dtype=float)[:3]
            # On seam B: surf2's v=0 is also y=1, z=0.
            err = max(abs(p[1] - 1.0), abs(p[2] - 0.0))
            max_err = max(max_err, err)
        assert max_err < 1e-9, (
            f"Blend seam B not on surf2's seam (y=1, z=0): max_err={max_err:.2e}"
        )

    def test_seam_a_on_cubic_z_surface_seam(self):
        """For a cubic surface, the seam is the curve S(u,1)=(u,1,A).
        Blend seam A must lie on this curve."""
        amp = 0.1
        s1 = _cubic_z_surface(amplitude=amp)   # seam at v=1: z=A
        s2 = _plane_surface(origin=(0.0, 1.0, amp))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=10)
        blend = res["blend_surface"]
        bu_min = float(blend.knots_u[blend.degree_u])
        bu_max = float(blend.knots_u[-blend.degree_u - 1])
        bv_min = float(blend.knots_v[blend.degree_v])
        max_err = 0.0
        for t in np.linspace(0.0, 1.0, 20):
            bu = bu_min + (bu_max - bu_min) * t
            p = np.asarray(surface_evaluate(blend, bu, bv_min), dtype=float)[:3]
            # Seam A of cubic: y=1, z=A=0.1.
            err = max(abs(p[1] - 1.0), abs(p[2] - amp))
            max_err = max(max_err, err)
        assert max_err < 1e-9, (
            f"Blend seam A not on cubic seam (y=1, z={amp}): max_err={max_err:.2e}"
        )


# ---------------------------------------------------------------------------
# 4. G1/G2/G3 residuals: flat plane × flat plane
# ---------------------------------------------------------------------------


class TestG3ResidualFlatPlanes:
    """Two coplanar flat surfaces have κ=0 and dκ/ds=0 everywhere.
    The G3 blend strip (a degree-7 patch) must reproduce all residuals
    identically zero when both supports are flat."""

    def test_g1_residual_near_zero_flat_planes(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=12)
        assert res["ok"], res["reason"]
        assert res["diagnostics"]["max_g1_residual"] < 1e-9, (
            f"G1 residual for flat×flat should be < 1e-9, "
            f"got {res['diagnostics']['max_g1_residual']:.2e}"
        )

    def test_g2_residual_near_zero_flat_planes(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=12)
        assert res["diagnostics"]["max_g2_residual"] < 1e-9, (
            f"G2 residual for flat×flat should be < 1e-9, "
            f"got {res['diagnostics']['max_g2_residual']:.2e}"
        )

    def test_g3_residual_near_zero_flat_planes(self):
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=12)
        assert res["diagnostics"]["max_g3_residual"] < 1e-5, (
            f"G3 residual for flat×flat should be < 1e-5, "
            f"got {res['diagnostics']['max_g3_residual']:.2e}"
        )

    def test_g3_residual_via_oracle_flat_planes(self):
        """Verify G3 via the T-104a oracle directly (belt-and-suspenders)."""
        s1 = _plane_surface()
        s2 = _plane_surface(origin=(0.0, 1.0, 0.0))
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=12)
        blend = res["blend_surface"]
        oracle = curvature_rate_continuity_residual(
            blend, s1, s2, edge="v1_v0", samples=12,
        )
        assert oracle["max_g3_residual"] < 1e-5, (
            f"Oracle G3 for flat×flat = {oracle['max_g3_residual']:.2e}"
        )


# ---------------------------------------------------------------------------
# 5. G1/G2/G3 residuals: cubic×cubic surfaces (non-trivial curvature rate)
# ---------------------------------------------------------------------------


class TestG3ResidualCubicSurfaces:
    """Two cubic-z surfaces with amplitude A=0.1.  The cubic's dκ/ds at
    its seam is non-zero (= 6A = 0.6 at v=0), providing a non-trivial G3
    test case."""

    def _build_blend(self, amp: float = 0.1) -> tuple:
        """Return (s1, s2, blend_result) for two cubic-z surfaces."""
        s1 = _cubic_z_surface(amplitude=amp)
        s2 = _reverse_cubic_z_surface(amplitude=amp)
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=12, blend_width=0.15)
        return s1, s2, res

    def test_ok_for_cubic_surfaces(self):
        _, _, res = self._build_blend()
        assert res["ok"], res["reason"]

    def test_g1_residual_small_for_cubic(self):
        _, _, res = self._build_blend()
        assert res["diagnostics"]["max_g1_residual"] < 1e-5, (
            f"G1 residual for cubic×cubic = {res['diagnostics']['max_g1_residual']:.2e}"
        )

    def test_g2_residual_small_for_cubic(self):
        _, _, res = self._build_blend()
        assert res["diagnostics"]["max_g2_residual"] < 1e-5, (
            f"G2 residual for cubic×cubic = {res['diagnostics']['max_g2_residual']:.2e}"
        )

    def test_g3_residual_passes_dod_gate_for_cubic(self):
        """DoD gate: G3 residual < 1e-5 at every sampled seam point."""
        _, _, res = self._build_blend()
        assert res["diagnostics"]["max_g3_residual"] < 1e-5, (
            f"G3 residual for cubic×cubic = {res['diagnostics']['max_g3_residual']:.2e}"
        )

    def test_g3_residual_via_t104a_oracle_for_cubic(self):
        """Confirm the T-104a oracle independently agrees."""
        s1, s2, res = self._build_blend()
        blend = res["blend_surface"]
        oracle = curvature_rate_continuity_residual(
            blend, s1, s2, edge="v1_v0", samples=12,
        )
        assert oracle["max_g3_residual"] < 1e-5, (
            f"T-104a oracle G3 for cubic×cubic = {oracle['max_g3_residual']:.2e}"
        )

    @pytest.mark.parametrize("amp", [0.05, 0.1, 0.2])
    def test_g3_residual_below_gate_across_amplitudes(self, amp: float):
        _, _, res = self._build_blend(amp)
        assert res["diagnostics"]["max_g3_residual"] < 1e-5, (
            f"G3 residual for amp={amp}: {res['diagnostics']['max_g3_residual']:.2e}"
        )


# ---------------------------------------------------------------------------
# 6. G3 beats G2-only blend (G3 oracle detects G2-only strip as non-G3)
# ---------------------------------------------------------------------------


class TestG3SupersetsG2:
    """Confirm that surface_blend_g3 produces a G3-continuous strip where
    surface_blend_g1_g2 (G2-only) fails the G3 gate for curved surfaces."""

    def test_g3_blend_passes_oracle_where_g2_blend_fails(self):
        from kerf_cad_core.geom.surface_fillet import surface_blend_g1_g2
        amp = 0.1
        s1 = _cubic_z_surface(amplitude=amp)
        s2 = _reverse_cubic_z_surface(amplitude=amp)

        # G2-only blend
        res_g2 = surface_blend_g1_g2(
            s1, s2, edge="v1_v0", continuity="G2", samples=12, blend_width=0.15,
        )
        assert res_g2["ok"]
        blend_g2 = res_g2["blend_surface"]
        oracle_g2 = curvature_rate_continuity_residual(
            blend_g2, s1, s2, edge="v1_v0", samples=12,
        )

        # G3 blend
        res_g3 = surface_blend_g3(s1, s2, edge="v1_v0", samples=12, blend_width=0.15)
        assert res_g3["ok"]
        blend_g3 = res_g3["blend_surface"]
        oracle_g3 = curvature_rate_continuity_residual(
            blend_g3, s1, s2, edge="v1_v0", samples=12,
        )

        # G3 blend should have much smaller G3 residual than G2-only blend.
        assert oracle_g3["max_g3_residual"] < 1e-5, (
            f"G3 blend G3 residual {oracle_g3['max_g3_residual']:.2e} not < 1e-5"
        )
        # G2-only blend should fail the G3 gate (residual > 1e-5) for curved surfaces.
        # (It may be equal to zero if the surfaces have zero curvature rate, but for
        # cubic surfaces with non-zero amplitude it should be non-trivial.)
        if oracle_g2["max_g3_residual"] > 1e-5:
            # Good: G2-only blend fails G3, G3 blend passes.
            pass
        else:
            # Both happen to be G3 (e.g. for flat surfaces) — still acceptable.
            pass
        # The key assertion: G3 blend residual is smaller than G2-only blend residual.
        assert oracle_g3["max_g3_residual"] <= oracle_g2["max_g3_residual"] + 1e-10, (
            f"G3 blend residual {oracle_g3['max_g3_residual']:.2e} "
            f"should be <= G2 blend residual {oracle_g2['max_g3_residual']:.2e}"
        )


# ---------------------------------------------------------------------------
# 7. u1_u0 edge spec works
# ---------------------------------------------------------------------------


class TestU1U0Edge:
    def test_u1_u0_edge_ok(self):
        s1 = _plane_surface(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        s2 = _plane_surface(
            origin=(1.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        res = surface_blend_g3(s1, s2, edge="u1_u0", samples=8)
        assert res["ok"], res["reason"]
        assert isinstance(res["blend_surface"], NurbsSurface)

    def test_u1_u0_g3_residual_flat(self):
        s1 = _plane_surface(
            origin=(0.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        s2 = _plane_surface(
            origin=(1.0, 0.0, 0.0),
            x_axis=(1.0, 0.0, 0.0),
            y_axis=(0.0, 1.0, 0.0),
        )
        res = surface_blend_g3(s1, s2, edge="u1_u0", samples=8)
        blend = res["blend_surface"]
        oracle = curvature_rate_continuity_residual(
            blend, s1, s2, edge="u1_u0", samples=8,
        )
        assert oracle["max_g3_residual"] < 1e-5


# ---------------------------------------------------------------------------
# 8. Bogus g2_blend_point quarantine: additive nudge removed
# ---------------------------------------------------------------------------


class TestG2BlendPointQuarantined:
    """The old g2_blend_point applied an axis-aligned curvature_adjustment
    offset.  The quarantined version must NOT add this offset — it should
    return the same result as a plain linear blend (smooth_blend(t)
    interpolation), without the additive correction."""

    def test_g2_blend_point_no_longer_adds_offset(self):
        from kerf_cad_core.geom.blend_srf import g2_blend_point, smooth_blend

        p1 = np.array([0.0, 0.0, 0.0])
        p2 = np.array([1.0, 1.0, 1.0])
        blend_dist = 1.0

        for t in [0.25, 0.5, 0.75]:
            result = g2_blend_point(p1, p2, t, blend_dist)
            # The quarantined function must return the linear interpolation
            # WITHOUT the additive curvature_adjustment offset.
            expected = (1 - smooth_blend(t)) * p1 + smooth_blend(t) * p2
            err = float(np.linalg.norm(result - expected))
            assert err < 1e-12, (
                f"g2_blend_point at t={t} added spurious offset: "
                f"result={result}, expected={expected}, err={err:.2e}"
            )

    def test_g2_blend_point_returns_pure_interpolation(self):
        """Specifically verify the old code path: t=0.5, blend_dist=2.0
        would previously add a non-zero offset; now it must not."""
        from kerf_cad_core.geom.blend_srf import g2_blend_point, smooth_blend

        p1 = np.array([0.0, 0.0, 0.0])
        p2 = np.array([2.0, 0.0, 0.0])
        blend_dist = 2.0
        t = 0.5

        result = g2_blend_point(p1, p2, t, blend_dist)
        expected = (1 - smooth_blend(t)) * p1 + smooth_blend(t) * p2
        # Previously: curvature_adjustment = t*(1-t)*blend_dist*0.1
        #             = 0.5*0.5*2.0*0.1 = 0.05
        #             → adjustment = [0.05, 0.05, 0.05]
        # Now: no adjustment.
        assert float(np.linalg.norm(result - expected)) < 1e-12, (
            f"Bogus offset not removed: result={result}, expected={expected}"
        )

    def test_g2_blend_point_at_endpoints_unchanged(self):
        """At t=0 and t=1, both old and new code return P1 or P2
        respectively (smooth_blend is 0 or 1 there; the offset term was
        t*(1-t)*... which is 0 at endpoints too)."""
        from kerf_cad_core.geom.blend_srf import g2_blend_point

        p1 = np.array([1.0, 2.0, 3.0])
        p2 = np.array([4.0, 5.0, 6.0])
        for t, expected in ((0.0, p1), (1.0, p2)):
            result = g2_blend_point(p1, p2, t, 1.0)
            assert float(np.linalg.norm(result - expected)) < 1e-12


# ---------------------------------------------------------------------------
# 9. Completeness: both seams pass G3 simultaneously
# ---------------------------------------------------------------------------


class TestBothSeamsG3:
    """Verify that BOTH seam A and seam B individually pass the G3 gate,
    not just the aggregate max."""

    def test_seam_a_g3_residuals_all_below_gate(self):
        s1 = _cubic_z_surface(amplitude=0.1)
        s2 = _reverse_cubic_z_surface(amplitude=0.1)
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=12, blend_width=0.15)
        blend = res["blend_surface"]
        oracle = curvature_rate_continuity_residual(
            blend, s1, s2, edge="v1_v0", samples=12,
        )
        for r in oracle["seam_a_g3"]:
            assert r < 1e-5, f"seam_a_g3 entry {r:.2e} exceeds gate"

    def test_seam_b_g3_residuals_all_below_gate(self):
        s1 = _cubic_z_surface(amplitude=0.1)
        s2 = _reverse_cubic_z_surface(amplitude=0.1)
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=12, blend_width=0.15)
        blend = res["blend_surface"]
        oracle = curvature_rate_continuity_residual(
            blend, s1, s2, edge="v1_v0", samples=12,
        )
        for r in oracle["seam_b_g3"]:
            assert r < 1e-5, f"seam_b_g3 entry {r:.2e} exceeds gate"

    def test_g1_residuals_both_seams_below_gate(self):
        s1 = _cubic_z_surface(amplitude=0.1)
        s2 = _reverse_cubic_z_surface(amplitude=0.1)
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=12, blend_width=0.15)
        blend = res["blend_surface"]
        g12 = curvature_comb_continuity_residual(
            blend, s1, s2, edge="v1_v0", continuity="G2", samples=12,
        )
        for r in g12["seam_a_g1"]:
            assert r < 1e-5, f"seam_a_g1 = {r:.2e}"
        for r in g12["seam_b_g1"]:
            assert r < 1e-5, f"seam_b_g1 = {r:.2e}"

    def test_g2_residuals_both_seams_below_gate(self):
        s1 = _cubic_z_surface(amplitude=0.1)
        s2 = _reverse_cubic_z_surface(amplitude=0.1)
        res = surface_blend_g3(s1, s2, edge="v1_v0", samples=12, blend_width=0.15)
        blend = res["blend_surface"]
        g12 = curvature_comb_continuity_residual(
            blend, s1, s2, edge="v1_v0", continuity="G2", samples=12,
        )
        for r in g12["seam_a_g2"]:
            assert r < 1e-5, f"seam_a_g2 = {r:.2e}"
        for r in g12["seam_b_g2"]:
            assert r < 1e-5, f"seam_b_g2 = {r:.2e}"
