"""GK-24..GK-30 — G1/G2 fillet/blend core hermetic test suite.

Covers:

  * Rolling-ball fillet on a box edge: face count, volume oracle,
    cylindrical-fillet curvature.
  * Fillet on a cylinder cap-rim (planar+cylindrical contract).
  * G1 surface-surface blend across coplanar offset planes.
  * G2 surface-surface blend across a sphere-plane junction.
  * Curvature-comb continuity oracle.
  * ``validate_body`` cleanliness on every emitted Body.
  * Monotone radius-volume behaviour.
  * Structured rejection of out-of-range radii.

All tests are hermetic (no network, no OCCT, no external fixtures);
each has an analytic oracle.
"""

from __future__ import annotations

import math
from typing import List, Optional

import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    Body,
    CircleArc3,
    CylinderSurface,
    Edge,
    Line3,
    Plane,
    SphereSurface,
    validate_body,
)
from kerf_cad_core.geom.brep_build import (
    box_to_body,
    cylinder_to_body,
)
from kerf_cad_core.geom.fillet_solid import (
    _CylindricalArcSurface,
    _TorusSegmentSurface,
    edge_supported_contract,
    fillet_solid_edge,
)
from kerf_cad_core.geom.nurbs import (
    NurbsSurface,
    surface_derivatives,
    surface_evaluate,
    surface_normal,
)
from kerf_cad_core.geom.surface_fillet import (
    curvature_comb_continuity_residual,
    surface_blend_g1_g2,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plane_surface(
    origin, x_axis, y_axis, *, nu: int = 4, nv: int = 4,
) -> NurbsSurface:
    """Build a degree-1 NurbsSurface plane patch over a uniform grid."""
    origin = np.asarray(origin, dtype=float)
    x_axis = np.asarray(x_axis, dtype=float)
    y_axis = np.asarray(y_axis, dtype=float)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            u = i / (nu - 1)
            v = j / (nv - 1)
            cp[i, j] = origin + u * x_axis + v * y_axis
    return NurbsSurface(
        degree_u=min(3, nu - 1),
        degree_v=min(3, nv - 1),
        control_points=cp,
        knots_u=_clamped(nu, min(3, nu - 1)),
        knots_v=_clamped(nv, min(3, nv - 1)),
    )


def _clamped(n: int, degree: int) -> np.ndarray:
    inner = max(0, n - degree - 1)
    parts = [np.zeros(degree + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(degree + 1))
    return np.concatenate(parts)


def _make_sphere_surface(
    centre, radius: float, *, nu: int = 9, nv: int = 5,
    u_min: float = 0.0, u_max: float = math.pi / 2.0,
    v_min: float = 0.0, v_max: float = math.pi / 2.0,
) -> NurbsSurface:
    """Build a NurbsSurface sphere patch (non-rational, for tests; we
    don't need exact rational here — only smooth continuity of the
    sampled CP grid)."""
    centre = np.asarray(centre, dtype=float)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        u = u_min + (u_max - u_min) * i / (nu - 1)
        for j in range(nv):
            v = v_min + (v_max - v_min) * j / (nv - 1)
            cp[i, j] = centre + radius * np.array([
                math.cos(v) * math.cos(u),
                math.cos(v) * math.sin(u),
                math.sin(v),
            ])
    deg_u = min(3, nu - 1)
    deg_v = min(3, nv - 1)
    return NurbsSurface(
        degree_u=deg_u,
        degree_v=deg_v,
        control_points=cp,
        knots_u=_clamped(nu, deg_u),
        knots_v=_clamped(nv, deg_v),
    )


def _find_box_edge(body: Body, p0_xyz, p1_xyz, tol: float = 1e-7) -> Edge:
    p0 = np.asarray(p0_xyz, dtype=float)
    p1 = np.asarray(p1_xyz, dtype=float)
    for e in body.all_edges():
        if not isinstance(e.curve, Line3):
            continue
        a = np.asarray(e.curve.p0, dtype=float)
        b = np.asarray(e.curve.p1, dtype=float)
        if (
            (float(np.linalg.norm(a - p0)) < tol
             and float(np.linalg.norm(b - p1)) < tol)
            or (float(np.linalg.norm(a - p1)) < tol
                and float(np.linalg.norm(b - p0)) < tol)
        ):
            return e
    raise AssertionError(f"box edge {p0_xyz} -> {p1_xyz} not found")


def _find_cyl_rim_edge(body: Body) -> Edge:
    for e in body.all_edges():
        if isinstance(e.curve, CircleArc3):
            return e
    raise AssertionError("no cap-rim circular edge found")


# ---------------------------------------------------------------------------
# Test 1..7 — Core box-edge fillet oracle
# ---------------------------------------------------------------------------


class TestBoxEdgeFillet:
    def test_box_edge_fillet_succeeds(self):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        res = fillet_solid_edge(body, edge, 0.1)
        assert res["ok"], res["reason"]
        assert res["body"] is not None

    def test_box_edge_fillet_face_count(self):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        res = fillet_solid_edge(body, edge, 0.1)
        b = res["body"]
        # 4 untouched box faces + 2 trimmed supports + 1 fillet = 7
        assert len(b.all_faces()) == 7

    def test_box_edge_fillet_validate_body_clean(self):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        res = fillet_solid_edge(body, edge, 0.1)
        result = validate_body(res["body"])
        assert result["ok"] is True, result["errors"]

    def test_box_edge_fillet_volume_removed_closed_form(self):
        # Closed form: edge bevel volume = (1 - pi/4) * r^2 * L
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        r = 0.1
        L = 1.0
        res = fillet_solid_edge(body, edge, r)
        expected = (1.0 - math.pi / 4.0) * r * r * L
        assert abs(res["volume_removed"] - expected) < 1e-7

    def test_box_edge_fillet_topology_euler_zero(self):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        res = fillet_solid_edge(body, edge, 0.1)
        b = res["body"]
        c = b.euler_counts()
        # Expected: V=10, E=15, F=7 (genus 0)
        assert c["V"] == 10
        assert c["E"] == 15
        assert c["F"] == 7
        assert c["G"] == 0
        assert b.euler_poincare_residual() == 0

    def test_box_edge_fillet_curvature_is_one_over_r(self):
        """The fillet face on a planar+planar box edge is a portion of a
        cylinder of radius r; its principal curvature must be exactly
        1/r everywhere."""
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        r = 0.1
        res = fillet_solid_edge(body, edge, r)
        ff = res["fillet_face"]
        assert isinstance(ff.surface, _CylindricalArcSurface)
        assert abs(ff.surface.curvature() - 1.0 / r) < 1e-9

    def test_box_edge_fillet_three_face_role(self):
        """Spec says: 1 fillet face + 2 trimmed supports must appear in
        the result."""
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        res = fillet_solid_edge(body, edge, 0.1)
        assert res["fillet_face"] is not None
        assert res["trimmed_face_a"] is not None
        assert res["trimmed_face_b"] is not None
        assert isinstance(res["fillet_face"].surface, _CylindricalArcSurface)
        assert isinstance(res["trimmed_face_a"].surface, Plane)
        assert isinstance(res["trimmed_face_b"].surface, Plane)


# ---------------------------------------------------------------------------
# Test 8..11 — All 12 box edges
# ---------------------------------------------------------------------------


class TestBoxAllTwelveEdges:
    @pytest.mark.parametrize(
        "edge_pts",
        [
            # bottom ring
            ((0, 0, 0), (1, 0, 0)),
            ((1, 0, 0), (1, 1, 0)),
            ((1, 1, 0), (0, 1, 0)),
            ((0, 1, 0), (0, 0, 0)),
            # top ring
            ((0, 0, 1), (1, 0, 1)),
            ((1, 0, 1), (1, 1, 1)),
            ((1, 1, 1), (0, 1, 1)),
            ((0, 1, 1), (0, 0, 1)),
            # vertical pillars
            ((0, 0, 0), (0, 0, 1)),
            ((1, 0, 0), (1, 0, 1)),
            ((1, 1, 0), (1, 1, 1)),
            ((0, 1, 0), (0, 1, 1)),
        ],
    )
    def test_all_box_edges_fillet_clean(self, edge_pts):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, edge_pts[0], edge_pts[1])
        res = fillet_solid_edge(body, edge, 0.1)
        assert res["ok"], res["reason"]
        assert validate_body(res["body"])["ok"] is True


# ---------------------------------------------------------------------------
# Test 12..17 — Monotonicity, radius oracles, structured failure
# ---------------------------------------------------------------------------


class TestRadiusBehaviour:
    def test_larger_radius_removes_more_volume(self):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        v_small = fillet_solid_edge(body, edge, 0.05)["volume_removed"]
        v_mid = fillet_solid_edge(body, edge, 0.1)["volume_removed"]
        v_large = fillet_solid_edge(body, edge, 0.2)["volume_removed"]
        assert v_small < v_mid < v_large

    def test_radius_too_large_rejected_not_crashed(self):
        # Use a thin box (dx=0.3) so r=0.4 exceeds the support
        # perpendicular extent and must be rejected.
        body = box_to_body((0.0, 0.0, 0.0), 0.3, 0.3, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        res = fillet_solid_edge(body, edge, 0.4)
        assert res["ok"] is False
        assert isinstance(res["reason"], str)
        assert "radius" in res["reason"].lower() or "extent" in res["reason"].lower()

    def test_radius_exceeds_edge_length_rejected(self):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        res = fillet_solid_edge(body, edge, 1.5)
        assert res["ok"] is False
        assert "edge length" in res["reason"].lower() or "consume" in res["reason"].lower()

    def test_radius_zero_rejected(self):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        res = fillet_solid_edge(body, edge, 0.0)
        assert res["ok"] is False

    def test_radius_negative_rejected(self):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        res = fillet_solid_edge(body, edge, -0.1)
        assert res["ok"] is False

    def test_volume_removed_scales_with_edge_length(self):
        """Edge of length L=2 should remove 2x as much as L=1 at same r."""
        body_a = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge_a = _find_box_edge(body_a, (0, 0, 0), (0, 0, 1))
        body_b = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 2.0)
        edge_b = _find_box_edge(body_b, (0, 0, 0), (0, 0, 2))
        r = 0.1
        va = fillet_solid_edge(body_a, edge_a, r)["volume_removed"]
        vb = fillet_solid_edge(body_b, edge_b, r)["volume_removed"]
        assert abs(vb - 2 * va) < 1e-9


# ---------------------------------------------------------------------------
# Test 18..21 — Planar+cylindrical (cap rim) fillet
# ---------------------------------------------------------------------------


class TestCylinderCapRimFillet:
    def test_cap_rim_fillet_succeeds(self):
        body = cylinder_to_body((0, 0, 0), (0, 0, 1), 1.0, 2.0)
        rim = _find_cyl_rim_edge(body)
        res = fillet_solid_edge(body, rim, 0.1)
        assert res["ok"], res["reason"]

    def test_cap_rim_fillet_face_count(self):
        body = cylinder_to_body((0, 0, 0), (0, 0, 1), 1.0, 2.0)
        rim = _find_cyl_rim_edge(body)
        res = fillet_solid_edge(body, rim, 0.1)
        # lateral + top cap + trimmed bottom cap + torus = 4
        assert len(res["body"].all_faces()) == 4

    def test_cap_rim_fillet_validate_body_clean(self):
        body = cylinder_to_body((0, 0, 0), (0, 0, 1), 1.0, 2.0)
        rim = _find_cyl_rim_edge(body)
        res = fillet_solid_edge(body, rim, 0.1)
        result = validate_body(res["body"])
        assert result["ok"] is True, result["errors"]

    def test_cap_rim_radius_exceeds_cylinder_radius_rejected(self):
        body = cylinder_to_body((0, 0, 0), (0, 0, 1), 1.0, 2.0)
        rim = _find_cyl_rim_edge(body)
        res = fillet_solid_edge(body, rim, 1.5)
        assert res["ok"] is False
        assert "cylinder radius" in res["reason"].lower() or "fit" in res["reason"].lower()


# ---------------------------------------------------------------------------
# Test 22..27 — G1 and G2 blend continuity
# ---------------------------------------------------------------------------


class TestG1Blend:
    def test_g1_blend_two_coplanar_offset_planes_tangent_residual_small(self):
        """Two coplanar planes offset in v meet G1 (tangent) along seam."""
        s1 = _make_plane_surface(
            origin=(0, 0, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0),
            nu=4, nv=4,
        )
        s2 = _make_plane_surface(
            origin=(0, 1, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0),
            nu=4, nv=4,
        )
        res = surface_blend_g1_g2(
            s1, s2, edge="v1_v0", continuity="G1", samples=12,
        )
        assert res["ok"], res["reason"]
        diag = res["diagnostics"]
        assert diag["max_g1_residual"] < 1e-9

    def test_g1_blend_returns_surface(self):
        s1 = _make_plane_surface(
            origin=(0, 0, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0),
        )
        s2 = _make_plane_surface(
            origin=(0, 1, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0),
        )
        res = surface_blend_g1_g2(s1, s2, edge="v1_v0", continuity="G1")
        assert isinstance(res["blend_surface"], NurbsSurface)

    def test_g1_blend_seam_interpolates_input_points(self):
        """Blend strip's v=0 edge must interpolate surf1's v=v_max
        boundary at the strip's parameter endpoints (clamped knots
        guarantee interpolation only at the corners, not at interior
        sample points)."""
        s1 = _make_plane_surface(
            origin=(0, 0, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0),
        )
        s2 = _make_plane_surface(
            origin=(0, 1, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0),
        )
        res = surface_blend_g1_g2(s1, s2, edge="v1_v0", continuity="G1")
        blend = res["blend_surface"]
        u_min = float(blend.knots_u[blend.degree_u])
        u_max = float(blend.knots_u[-blend.degree_u - 1])
        v_min_b = float(blend.knots_v[blend.degree_v])
        # Corner checks (clamped knots ⇒ exact interpolation).
        for u_corner, u_surf in ((u_min, 0.0), (u_max, 1.0)):
            p_blend = np.asarray(
                surface_evaluate(blend, u_corner, v_min_b), dtype=float,
            )[:3]
            p_s1 = np.asarray(
                surface_evaluate(s1, u_surf, 1.0), dtype=float,
            )[:3]
            assert float(np.linalg.norm(p_blend - p_s1)) < 1e-9

    def test_g1_blend_invalid_continuity_rejected(self):
        s1 = _make_plane_surface((0, 0, 0), (1, 0, 0), (0, 1, 0))
        s2 = _make_plane_surface((0, 1, 0), (1, 0, 0), (0, 1, 0))
        res = surface_blend_g1_g2(
            s1, s2, edge="v1_v0", continuity="NOT_A_CONTINUITY",
        )
        assert res["ok"] is False

    def test_g1_blend_negative_width_rejected(self):
        s1 = _make_plane_surface((0, 0, 0), (1, 0, 0), (0, 1, 0))
        s2 = _make_plane_surface((0, 1, 0), (1, 0, 0), (0, 1, 0))
        res = surface_blend_g1_g2(
            s1, s2, edge="v1_v0", continuity="G1", blend_width=-1.0,
        )
        assert res["ok"] is False

    def test_g1_blend_bad_edge_spec_rejected(self):
        s1 = _make_plane_surface((0, 0, 0), (1, 0, 0), (0, 1, 0))
        s2 = _make_plane_surface((0, 1, 0), (1, 0, 0), (0, 1, 0))
        res = surface_blend_g1_g2(s1, s2, edge="bogus", continuity="G1")
        assert res["ok"] is False


class TestG2BlendSpherePlane:
    def test_g2_blend_sphere_plane_principal_curvature_mismatch_bounded(self):
        """Build a G2 blend between a sphere patch and a tangent plane.
        The tangent plane has curvature 0; the sphere has curvature
        1/r — they cannot both match curvature exactly without a
        radius-zero blend. We test that the *blend's own* curvature
        smoothly interpolates the two extremes (i.e. the curvature
        residual reported by the oracle is bounded).
        """
        sphere = _make_sphere_surface(
            centre=(0, 0, 0), radius=1.0,
            u_min=0.0, u_max=math.pi / 4.0,
            v_min=0.0, v_max=math.pi / 6.0,
        )
        # A tangent plane at the seam (v=pi/6) of the sphere — the
        # sphere's top boundary curve.
        # For our test we just want G2 oracle to *report* the residual.
        plane = _make_plane_surface(
            origin=(0, 0, 1), x_axis=(1, 0, 0), y_axis=(0, 0.5, 0),
            nu=4, nv=4,
        )
        res = surface_blend_g1_g2(
            sphere, plane, edge="v1_v0", continuity="G2", samples=12,
        )
        # The oracle must run and report a numeric residual.
        assert res["ok"], res["reason"]
        diag = res["diagnostics"]
        # G2 residual exists & is finite.
        assert isinstance(diag["max_g2_residual"], float)
        assert math.isfinite(diag["max_g2_residual"])
        # G1 still small (the blend always enforces G1).
        assert diag["max_g1_residual"] < 0.5

    def test_g2_blend_returns_blend_surface(self):
        sphere = _make_sphere_surface(centre=(0, 0, 0), radius=1.0)
        plane = _make_plane_surface(
            origin=(0, 0, 1), x_axis=(1, 0, 0), y_axis=(0, 0.5, 0),
        )
        res = surface_blend_g1_g2(
            sphere, plane, edge="v1_v0", continuity="G2",
        )
        assert isinstance(res["blend_surface"], NurbsSurface)

    def test_g2_blend_diagnostic_keys(self):
        sphere = _make_sphere_surface(centre=(0, 0, 0), radius=1.0)
        plane = _make_plane_surface(
            origin=(0, 0, 1), x_axis=(1, 0, 0), y_axis=(0, 0.5, 0),
        )
        res = surface_blend_g1_g2(
            sphere, plane, edge="v1_v0", continuity="G2",
        )
        diag = res["diagnostics"]
        for k in (
            "max_g1_residual", "max_g2_residual",
            "mean_g1_residual", "mean_g2_residual",
        ):
            assert k in diag


# ---------------------------------------------------------------------------
# Test 28..30 — Curvature comb oracle
# ---------------------------------------------------------------------------


class TestCurvatureCombOracle:
    def test_oracle_returns_dict_with_expected_keys(self):
        s1 = _make_plane_surface((0, 0, 0), (1, 0, 0), (0, 1, 0))
        s2 = _make_plane_surface((0, 1, 0), (1, 0, 0), (0, 1, 0))
        res = surface_blend_g1_g2(s1, s2, continuity="G1")
        blend = res["blend_surface"]
        diag = curvature_comb_continuity_residual(
            blend, s1, s2, edge="v1_v0", continuity="G2", samples=8,
        )
        for k in (
            "max_g1_residual", "max_g2_residual",
            "mean_g1_residual", "mean_g2_residual", "samples",
        ):
            assert k in diag
        assert diag["samples"] == 8

    def test_oracle_reports_zero_g1_for_coplanar_blend(self):
        s1 = _make_plane_surface((0, 0, 0), (1, 0, 0), (0, 1, 0))
        s2 = _make_plane_surface((0, 1, 0), (1, 0, 0), (0, 1, 0))
        res = surface_blend_g1_g2(s1, s2, continuity="G1")
        diag = res["diagnostics"]
        assert diag["max_g1_residual"] < 1e-9

    def test_oracle_g2_for_two_planes_is_zero(self):
        """Two coplanar planes have zero principal curvature; a G2-aware
        blend that linearly interpolates should also have ~zero
        curvature residual at the seam."""
        s1 = _make_plane_surface((0, 0, 0), (1, 0, 0), (0, 1, 0))
        s2 = _make_plane_surface((0, 1, 0), (1, 0, 0), (0, 1, 0))
        res = surface_blend_g1_g2(s1, s2, continuity="G2")
        diag = res["diagnostics"]
        # Both surfaces are planar so cross-boundary curvature is zero;
        # the blend strip is a degree-3 surface with zero curvature on
        # the boundaries.
        assert diag["max_g2_residual"] < 1e-7

    def test_oracle_g1_for_perpendicular_planes_nonzero(self):
        """A blend between two NON-coplanar planes has a tangent
        discontinuity at the seam by default — the oracle must detect
        it."""
        s1 = _make_plane_surface(
            origin=(0, 0, 0), x_axis=(1, 0, 0), y_axis=(0, 1, 0),
        )
        # Perpendicular plane: y_axis rotated 90deg about x.
        s2 = _make_plane_surface(
            origin=(0, 1, 0), x_axis=(1, 0, 0), y_axis=(0, 0, 1),
        )
        # Hand-craft a degenerate "blend" that just linearly interpolates
        # — its tangent at the seam won't match s2's cross-tangent.
        # We build a 4x4 blend whose v=0 row equals s1's v=1 row and
        # v=1 row equals s2's v=0 row; v-tangent is along (0, 0, dz/dv)
        # at v=1 but should be (0, 1, 0) along s2 — so it's MISALIGNED.
        nu = 4
        nv = 4
        cp = np.zeros((nu, nv, 3))
        for i in range(nu):
            u = i / (nu - 1)
            # v=0: surf1 at v=1.
            cp[i, 0] = np.array([u, 1.0, 0.0])
            # v=1: surf2 at v=0.
            cp[i, nv - 1] = np.array([u, 1.0, 0.0])
            # intermediate rows interpolate linearly to a midpoint
            # OFFSET from the seam in a non-tangent direction.
            cp[i, 1] = np.array([u, 1.0 + 0.1, 0.05])
            cp[i, 2] = np.array([u, 1.0 + 0.05, 0.1])
        blend = NurbsSurface(
            degree_u=3, degree_v=3,
            control_points=cp,
            knots_u=_clamped(nu, 3),
            knots_v=_clamped(nv, 3),
        )
        diag = curvature_comb_continuity_residual(
            blend, s1, s2, edge="v1_v0", continuity="G1",
        )
        # The oracle should report a NONZERO residual on at least one
        # seam: blend's cross-tangent does not align with s2's cross-
        # tangent.
        assert diag["max_g1_residual"] > 1e-4


# ---------------------------------------------------------------------------
# Test 31..36 — Edge case handling, contract docstring, error paths
# ---------------------------------------------------------------------------


class TestContractAndErrors:
    def test_contract_doc_string_is_nonempty(self):
        s = edge_supported_contract()
        assert isinstance(s, str)
        assert "planar+planar" in s
        assert "planar+cylindrical" in s

    def test_unsupported_body_returns_structured_failure(self):
        """A body that's not a recognised primitive must fail
        structured, not raise."""
        body_a = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        body_b = box_to_body((10.0, 10.0, 10.0), 1.0, 1.0, 1.0)
        # Try to fillet a body_a edge against body_b — edge isn't part
        # of body_b so we expect failure (the recognition step says
        # "edge incident to 0 faces").
        edge_a = _find_box_edge(body_a, (0, 0, 0), (0, 0, 1))
        res = fillet_solid_edge(body_b, edge_a, 0.1)
        assert res["ok"] is False
        assert "incident" in res["reason"].lower()

    def test_invalid_inputs_rejected(self):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        # Wrong types
        res = fillet_solid_edge("not a body", edge, 0.1)
        assert res["ok"] is False
        res = fillet_solid_edge(body, "not an edge", 0.1)
        assert res["ok"] is False
        res = fillet_solid_edge(body, edge, "0.1")
        assert res["ok"] is False

    def test_no_raise_on_pathological_radius(self):
        body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 1))
        # NaN, Inf radii.
        for bad in (float("nan"), float("inf"), -math.inf):
            res = fillet_solid_edge(body, edge, bad)
            # Either rejected with reason or accepted-then-failed; key
            # is no exception escapes.
            assert isinstance(res, dict)
            assert "ok" in res

    def test_offset_box_filleted_volume_oracle(self):
        """Same volume oracle but on a translated box — must be
        translation-invariant."""
        body = box_to_body((5.0, -3.0, 2.0), 1.0, 1.0, 1.0)
        edge = _find_box_edge(body, (5, -3, 2), (5, -3, 3))
        r = 0.1
        res = fillet_solid_edge(body, edge, r)
        assert res["ok"]
        expected = (1.0 - math.pi / 4.0) * r * r * 1.0
        assert abs(res["volume_removed"] - expected) < 1e-7

    def test_non_unit_box_volume_oracle(self):
        body = box_to_body((0.0, 0.0, 0.0), 2.0, 3.0, 4.0)
        edge = _find_box_edge(body, (0, 0, 0), (0, 0, 4))
        r = 0.2
        res = fillet_solid_edge(body, edge, r)
        assert res["ok"]
        expected = (1.0 - math.pi / 4.0) * r * r * 4.0
        assert abs(res["volume_removed"] - expected) < 1e-7


# ---------------------------------------------------------------------------
# Test 37..40 — Surface wrappers behaviour (defensive: ensure helpers
# remain stable so future blend/sew work can rely on them).
# ---------------------------------------------------------------------------


class TestSurfaceWrappers:
    def test_cylindrical_arc_surface_evaluates_at_endpoints(self):
        s = _CylindricalArcSurface(
            centre=np.array([0.0, 0.0, 0.0]),
            axis=np.array([0.0, 0.0, 1.0]),
            radius=0.5,
            x_ref=np.array([1.0, 0.0, 0.0]),
            u_start=0.0, u_end=math.pi / 2.0,
            v_start=0.0, v_end=1.0,
        )
        # u=0 should give the +x point.
        p = s.evaluate(0.0, 0.0)
        assert abs(p[0] - 0.5) < 1e-12
        # u=1 -> pi/2 -> +y point.
        p = s.evaluate(1.0, 0.0)
        assert abs(p[1] - 0.5) < 1e-12

    def test_cylindrical_arc_surface_normal_is_radial(self):
        s = _CylindricalArcSurface(
            centre=np.array([0.0, 0.0, 0.0]),
            axis=np.array([0.0, 0.0, 1.0]),
            radius=0.5,
            x_ref=np.array([1.0, 0.0, 0.0]),
            u_start=0.0, u_end=math.pi / 2.0,
            v_start=0.0, v_end=1.0,
        )
        n = s.normal(0.0, 0.5)
        assert abs(n[0] - 1.0) < 1e-12
        assert abs(n[1]) < 1e-12
        assert abs(n[2]) < 1e-12

    def test_cylindrical_arc_surface_curvature(self):
        s = _CylindricalArcSurface(
            centre=np.array([0.0, 0.0, 0.0]),
            axis=np.array([0.0, 0.0, 1.0]),
            radius=0.25,
            x_ref=np.array([1.0, 0.0, 0.0]),
            u_start=0.0, u_end=math.pi / 2.0,
            v_start=0.0, v_end=1.0,
        )
        assert abs(s.curvature() - 4.0) < 1e-12

    def test_torus_segment_surface_evaluates_smooth(self):
        s = _TorusSegmentSurface(
            centre=np.array([0.0, 0.0, 0.5]),
            axis=np.array([0.0, 0.0, 1.0]),
            major_radius=1.0,
            minor_radius=0.1,
            u_start=0.0, u_end=2.0 * math.pi,
            v_start=-math.pi / 2.0, v_end=0.0,
            x_ref=np.array([1.0, 0.0, 0.0]),  # explicit so test is deterministic
        )
        # At local (u=0, v=1) -> (cu=0, cv=0): point at major+minor on
        # +x, z = centre.z.
        p = s.evaluate(0.0, 1.0)
        assert abs(p[0] - 1.1) < 1e-12
        assert abs(p[2] - 0.5) < 1e-12
        # At local (u=0, v=0) -> (cu=0, cv=-pi/2): point at radial=major,
        # z = centre.z + minor*sin(-pi/2) = 0.5 - 0.1 = 0.4.
        p = s.evaluate(0.0, 0.0)
        assert abs(p[0] - 1.0) < 1e-12
        assert abs(p[2] - 0.4) < 1e-12

    def test_torus_segment_principal_curvatures_match_analytic(self):
        s = _TorusSegmentSurface(
            centre=np.array([0.0, 0.0, 0.0]),
            axis=np.array([0.0, 0.0, 1.0]),
            major_radius=2.0,
            minor_radius=0.5,
            u_start=0.0, u_end=2.0 * math.pi,
            v_start=0.0, v_end=math.pi / 2.0,
        )
        k_minor, k_major = s.curvature()
        assert abs(k_minor - 2.0) < 1e-12   # 1/0.5
        assert abs(k_major - 0.5) < 1e-12   # 1/2.0
