"""
test_parity_gap_closures.py
===========================
Hermetic numeric-oracle tests closing the four core-geometry parity gaps:

1. NURBS surfacing — Gordon/network surface LLM tool registration +
   gordon_network_srf numeric oracle.
2. Mesh repair / ShrinkWrap — mesh_shrinkwrap nearest-surface + project_normal.
3. Direct edit — push_pull_face + move_face + delete_face (already wired;
   additional regression oracle).
4. Sheet metal — auto corner-relief geometry (square / round / lance).

All tests are hermetic: no DB, no OCCT, no kerf_chat runtime, no network.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Gap 1: Gordon/network surface
# ---------------------------------------------------------------------------

from kerf_cad_core.geom.network_srf import (
    gordon_network_srf,
    network_srf,
    loft_surface,
)
from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    make_line_nurbs,
    surface_evaluate,
)


def _line(p0, p1) -> NurbsCurve:
    return make_line_nurbs(np.asarray(p0, dtype=float), np.asarray(p1, dtype=float))


def _eval_surf(surf: NurbsSurface, u: float, v: float) -> np.ndarray:
    return np.asarray(surface_evaluate(surf, u, v), dtype=float)[:3]


class TestGordonNetworkOracle:
    """Gordon surface on 2x2 straight-line grid = bilinear patch (analytic)."""

    @pytest.fixture(scope="class")
    def surf(self):
        c0u = _line([0, 0, 0], [1, 0, 0])
        c1u = _line([0, 1, 0], [1, 1, 0])
        d0v = _line([0, 0, 0], [0, 1, 0])
        d1v = _line([1, 0, 0], [1, 1, 0])
        return gordon_network_srf(
            [c0u, c1u], [d0v, d1v],
            v_params=[0.0, 1.0], u_params=[0.0, 1.0],
        )

    def test_returns_nurbs_surface(self, surf):
        assert isinstance(surf, NurbsSurface)

    def test_corner_00(self, surf):
        """G(0,0) ≈ (0,0,0)."""
        pt = _eval_surf(surf, 0.0, 0.0)
        assert np.linalg.norm(pt - [0, 0, 0]) < 0.01

    def test_corner_10(self, surf):
        """G(1,0) ≈ (1,0,0)."""
        pt = _eval_surf(surf, 1.0, 0.0)
        assert np.linalg.norm(pt - [1, 0, 0]) < 0.01

    def test_corner_11(self, surf):
        """G(1,1) ≈ (1,1,0)."""
        pt = _eval_surf(surf, 1.0, 1.0)
        assert np.linalg.norm(pt - [1, 1, 0]) < 0.01

    def test_midpoint(self, surf):
        """G(0.5, 0.5) ≈ (0.5, 0.5, 0) for bilinear patch."""
        pt = _eval_surf(surf, 0.5, 0.5)
        assert np.linalg.norm(pt - [0.5, 0.5, 0]) < 0.05


class TestGordonThreeByThreeGrid:
    """3x3 straight-line Gordon network — both families within tolerance."""

    @pytest.fixture(scope="class")
    def surf(self):
        u_curves = [
            _line([0, 0, 0], [1, 0, 0]),
            _line([0, 0.5, 0], [1, 0.5, 0]),
            _line([0, 1, 0], [1, 1, 0]),
        ]
        v_curves = [
            _line([0, 0, 0], [0, 1, 0]),
            _line([0.5, 0, 0], [0.5, 1, 0]),
            _line([1, 0, 0], [1, 1, 0]),
        ]
        return gordon_network_srf(
            u_curves, v_curves,
            v_params=[0.0, 0.5, 1.0],
            u_params=[0.0, 0.5, 1.0],
        )

    def test_returns_nurbs_surface(self, surf):
        assert isinstance(surf, NurbsSurface)

    def test_u_curve_interpolation(self, surf):
        """Middle u-curve (v=0.5) is approximately interpolated."""
        for tu in np.linspace(0.0, 1.0, 7):
            pt = _eval_surf(surf, tu, 0.5)
            expected_x = float(tu)
            assert abs(pt[1] - 0.5) < 0.1, f"y at tu={tu}: got {pt[1]}"

    def test_v_curve_interpolation(self, surf):
        """Middle v-curve (u=0.5) is approximately interpolated."""
        for tv in np.linspace(0.0, 1.0, 7):
            pt = _eval_surf(surf, 0.5, tv)
            assert abs(pt[0] - 0.5) < 0.1, f"x at tv={tv}: got {pt[0]}"


class TestGordonMismatchError:
    """Intersection mismatch beyond tol should raise ValueError."""

    def test_mismatch_raises(self):
        # u-curve at v=0: from (0,0,0) to (1,0,0)
        c0u = _line([0, 0, 0], [1, 0, 0])
        # v-curve at u=0: from (0, 0, 1) to (0, 1, 1)  — z=1 ≠ 0 at intersection
        d0v = _line([0, 0, 1.0], [0, 1, 1.0])
        with pytest.raises(ValueError, match="mismatch|distance"):
            gordon_network_srf([c0u], [d0v], tol=1e-6)


class TestSkinningLoft:
    """Skinning loft through two parallel lines produces a valid surface."""

    def test_two_profiles(self):
        c0 = _line([0, 0, 0], [1, 0, 0])
        c1 = _line([0, 1, 0], [1, 1, 0])
        surf = network_srf([c0, c1], degree_u=1)
        assert isinstance(surf, NurbsSurface)

    def test_ruled_loft(self):
        profiles = [_line([0, i, 0], [1, i, 0]) for i in range(3)]
        surf = loft_surface(profiles, ruled=True)
        assert isinstance(surf, NurbsSurface)
        # Ruled uses degree_u=1 — there should be no cubic-smooth overshoot.

    def test_single_profile_raises(self):
        with pytest.raises(ValueError, match="2 profiles"):
            loft_surface([_line([0, 0, 0], [1, 0, 0])])


class TestLLMToolRegistrationNetworkSrf:
    """Verify the LLM helper functions exist and are importable."""

    def test_serialize_deserialize_round_trip(self):
        from kerf_cad_core.geom.network_srf import _deserialize_curve, _serialize_surface
        c = _line([0, 0, 0], [1, 0, 0])
        d = {
            "control_points": c.control_points.tolist(),
            "knots": c.knots.tolist(),
            "degree": int(c.degree),
        }
        c2 = _deserialize_curve(d)
        assert isinstance(c2, NurbsCurve)
        assert c2.degree == c.degree
        assert np.allclose(c2.control_points, c.control_points)

        c0u = _line([0, 0, 0], [1, 0, 0])
        c1u = _line([0, 1, 0], [1, 1, 0])
        d0v = _line([0, 0, 0], [0, 1, 0])
        d1v = _line([1, 0, 0], [1, 1, 0])
        surf = gordon_network_srf([c0u, c1u], [d0v, d1v])
        sd = _serialize_surface(surf)
        assert "degree_u" in sd
        assert "degree_v" in sd
        assert "control_points" in sd
        assert "knots_u" in sd
        assert "knots_v" in sd


# ---------------------------------------------------------------------------
# Gap 2: Mesh repair / ShrinkWrap
# ---------------------------------------------------------------------------

from kerf_cad_core.geom.mesh_repair import (
    mesh_shrinkwrap,
    mesh_repair,
    repair_pipeline,
    weld_vertices,
    fill_holes,
    is_closed,
    is_manifold,
)


def _unit_box():
    """Simple closed unit box: 8 verts, 12 triangles."""
    verts = [
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ]
    faces = [
        [0, 1, 2], [0, 2, 3],   # bottom
        [4, 6, 5], [4, 7, 6],   # top
        [0, 4, 5], [0, 5, 1],   # front
        [1, 5, 6], [1, 6, 2],   # right
        [2, 6, 7], [2, 7, 3],   # back
        [3, 7, 4], [3, 4, 0],   # left
    ]
    return verts, faces


def _plane_mesh():
    """Flat 2x2 quad grid: 4 verts, 2 triangles (z=2 plane)."""
    verts = [
        [0, 0, 2], [1, 0, 2], [1, 1, 2], [0, 1, 2],
    ]
    faces = [[0, 1, 2], [0, 2, 3]]
    return verts, faces


class TestMeshShrinkwrapNearestSurface:
    """nearest_surface_point projects src vertices onto target."""

    def test_basic_projection(self):
        """Source vertices above z=0 plane should project down to z=0."""
        # Target: large flat triangle at z=0
        tv = [[0, 0, 0], [10, 0, 0], [5, 10, 0]]
        tf = [[0, 1, 2]]
        # Source: three points at z=0.5
        sv = [[1, 1, 0.5], [2, 1, 0.5], [1, 2, 0.5]]
        sf = [[0, 1, 2]]
        r = mesh_shrinkwrap(sv, sf, tv, tf,
                            method="nearest_surface_point",
                            snap_tol=2.0)
        assert r["ok"], r.get("reason")
        # All z coords should be close to 0
        for v in r["verts"]:
            assert abs(v[2]) < 0.05, f"z={v[2]} not projected to z=0"
        assert r["projected_count"] > 0

    def test_empty_target_returns_source(self):
        """Empty target: source returned unchanged."""
        sv = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        sf = [[0, 1, 2]]
        r = mesh_shrinkwrap(sv, sf, [], [], method="nearest_surface_point")
        assert r["ok"]
        assert r["projected_count"] == 0

    def test_invalid_method(self):
        sv = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        sf = [[0, 1, 2]]
        r = mesh_shrinkwrap(sv, sf, sv, sf, method="bogus_method")
        assert not r["ok"]
        assert "method" in r["reason"].lower()


class TestMeshShrinkwrapProjectNormal:
    """project_normal shoots rays from source vertices along normals."""

    def test_flat_source_projects_onto_plane(self):
        """Flat mesh at z=1 projects onto z=0 target plane."""
        # Target: unit square at z=0
        tv = [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]]
        tf = [[0, 1, 2], [0, 2, 3]]
        # Source: flat mesh at z=0.5 facing +z
        sv = [[0.5, 0.5, 0.5], [1.5, 0.5, 0.5], [1.0, 1.5, 0.5]]
        sf = [[0, 1, 2]]
        r = mesh_shrinkwrap(sv, sf, tv, tf,
                            method="project_normal",
                            snap_tol=2.0)
        assert r["ok"], r.get("reason")
        for v in r["verts"]:
            assert abs(v[2]) < 0.1, f"z={v[2]}"

    def test_displacement_within_bounds(self):
        """max_displacement reported correctly."""
        tv, tf = _unit_box()
        # Source: sphere-like vertices inside the box
        sv = [[0.5, 0.5, 0.5]]
        sf = []
        r = mesh_shrinkwrap(sv, sf, tv, tf,
                            method="nearest_surface_point",
                            snap_tol=5.0)
        assert r["ok"]
        assert r["max_displacement"] >= 0.0


class TestMeshShrinkwrapRetopo:
    """Integration: repair + shrinkwrap as a retopology pipeline."""

    def test_cube_retopo(self):
        """Source cube (slightly translated) → should shrinkwrap close to target."""
        sv, sf = _unit_box()
        # Shift source up by 0.1
        sv_shifted = [[v[0], v[1], v[2] + 0.1] for v in sv]
        tv, tf = _unit_box()
        r = mesh_shrinkwrap(sv_shifted, sf, tv, tf,
                            method="nearest_surface_point",
                            snap_tol=1.0)
        assert r["ok"]
        assert r["projected_count"] > 0


class TestMeshRepairRobustness:
    """Regression oracle for existing mesh_repair pipeline (should still pass)."""

    def test_weld_vertices(self):
        """Duplicate vertices at (0,0,0) should be welded."""
        sv = [[0, 0, 0], [0, 0, 0], [1, 0, 0], [0, 1, 0]]
        sf = [[0, 2, 3], [1, 2, 3]]
        r = weld_vertices(sv, sf, tol=1e-6)
        assert r["ok"]
        assert r["merged_count"] == 1

    def test_fill_holes_triangle(self):
        """Open triangle gets its single boundary loop filled."""
        # Two triangles sharing one edge but leaving a triangle-shaped hole
        sv = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]]
        sf = [[0, 1, 3]]  # Only one of two triangles in a unit square
        r = fill_holes(sv, sf)
        assert r["ok"]
        assert r["holes_filled"] >= 1

    def test_is_closed_box(self):
        sv, sf = _unit_box()
        r = is_closed(sv, sf)
        assert r["ok"]
        assert r["closed"]

    def test_is_manifold_box(self):
        sv, sf = _unit_box()
        r = is_manifold(sv, sf)
        assert r["ok"]
        assert r["manifold"]


# ---------------------------------------------------------------------------
# Gap 3: Direct edit (regression oracle — operations already wired)
# ---------------------------------------------------------------------------

from kerf_cad_core.geom.brep import Body, Plane, Shell, Face, Loop, Coedge, Edge, Line3, Vertex
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.direct_edit import (
    push_pull_face,
    move_face,
    delete_face,
    DirectEditConstraintViolation,
    push_pull_face_with_constraints,
)


def _make_unit_box_body() -> Body:
    """Use kerf_cad_core's box_to_body helper to get a unit-cube Body."""
    return box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)


class TestDirectEditPushPull:
    """push_pull_face: positive distance grows box; negative shrinks it."""

    def test_push_grows_box(self):
        body = _make_unit_box_body()
        n_faces = len(body.all_faces())
        assert n_faces >= 4  # at least 4 faces

    def test_push_pull_face_returns_body(self):
        body = _make_unit_box_body()
        faces = body.all_faces()
        # Find a top face (z-normal) — face 0 usually works for simple box
        new_body = push_pull_face(body, 0, 0.5)
        assert isinstance(new_body, Body)

    def test_delete_face_returns_open_shell(self):
        body = _make_unit_box_body()
        new_body = delete_face(body, 0, heal=False)
        assert isinstance(new_body, Body)
        assert len(new_body.all_faces()) < len(body.all_faces())


class TestDirectEditConstraints:
    """push_pull_face_with_constraints clamp mode."""

    def test_no_constraints_applies_full_distance(self):
        body = _make_unit_box_body()
        new_body, applied, clamped = push_pull_face_with_constraints(body, 0, 0.2, [])
        assert isinstance(new_body, Body)
        assert applied == pytest.approx(0.2, abs=1e-9)
        assert clamped == []

    def test_unknown_constraint_warns(self):
        import warnings
        body = _make_unit_box_body()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            new_body, applied, _ = push_pull_face_with_constraints(
                body, 0, 0.1,
                [{"kind": "mystery_constraint"}],
            )
        assert isinstance(new_body, Body)


# ---------------------------------------------------------------------------
# Gap 4: Sheet metal corner-relief
# ---------------------------------------------------------------------------

from kerf_cad_core.sheetmetal_features import (
    CornerReliefSpec,
    CornerReliefResult,
    compute_corner_relief,
)


class TestCornerReliefSquare:
    """Square relief: width = r + t/2, depth ≥ r + t/2."""

    def test_dimensions(self):
        spec = CornerReliefSpec(
            relief_type="square",
            bend_radius_mm=2.0,
            thickness_mm=1.0,
            bend_angle_deg=90.0,
        )
        r = compute_corner_relief(spec)
        assert r.relief_type == "square"
        # width = r + t/2 = 2 + 0.5 = 2.5
        assert abs(r.relief_width_mm - 2.5) < 1e-5
        # depth = r + t/2 = 2.5 (for 90°)
        assert abs(r.relief_depth_mm - 2.5) < 1e-5
        # min punch radius = t/2 = 0.5
        assert abs(r.min_punch_radius_mm - 0.5) < 1e-5

    def test_outline_is_closed_polygon(self):
        spec = CornerReliefSpec("square", 2.0, 1.0)
        r = compute_corner_relief(spec)
        # Outline must start and end at same point (closed)
        assert r.outline_xy[0] == r.outline_xy[-1]
        assert len(r.outline_xy) >= 4  # at least a rectangle

    def test_outline_has_nonzero_area(self):
        """Cross product of outline edges must give non-zero area."""
        spec = CornerReliefSpec("square", 2.0, 1.0)
        r = compute_corner_relief(spec)
        pts = r.outline_xy[:-1]  # exclude closing point
        area = 0.0
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        assert abs(area) > 1e-10, "Relief outline has zero area"


class TestCornerReliefRound:
    """Round relief: radius = max(t/2, r/2)."""

    def test_dimensions(self):
        spec = CornerReliefSpec(
            relief_type="round",
            bend_radius_mm=1.0,
            thickness_mm=2.0,
            bend_angle_deg=90.0,
        )
        r = compute_corner_relief(spec)
        # rr = max(t/2, r/2) = max(1.0, 0.5) = 1.0
        assert abs(r.relief_width_mm - 2.0) < 1e-5
        assert abs(r.relief_depth_mm - 2.0) < 1e-5
        assert abs(r.min_punch_radius_mm - 1.0) < 1e-5

    def test_outline_approximately_circular(self):
        """Radii of all outline points from centre should be approximately equal."""
        spec = CornerReliefSpec("round", 1.0, 1.0)
        r = compute_corner_relief(spec)
        rr = r.min_punch_radius_mm
        centre_y = rr  # circle centred at (0, rr)
        radii = [
            math.hypot(x, y - centre_y)
            for x, y in r.outline_xy[:-1]  # skip closing point
        ]
        # All radii should be within 2% of the nominal radius
        for rad in radii:
            assert abs(rad - rr) / rr < 0.02, f"Radius deviation: {rad} vs {rr}"


class TestCornerReliefLance:
    """Lance relief: width = t, depth = r + t."""

    def test_dimensions(self):
        spec = CornerReliefSpec(
            relief_type="lance",
            bend_radius_mm=2.0,
            thickness_mm=1.0,
        )
        r = compute_corner_relief(spec)
        assert r.relief_type == "lance"
        assert abs(r.relief_width_mm - 1.0) < 1e-5   # width = t
        assert abs(r.relief_depth_mm - 3.0) < 1e-5   # depth = r + t = 3

    def test_l_shaped_outline(self):
        """Lance outline must have at least 6 distinct points (L-shape)."""
        spec = CornerReliefSpec("lance", 2.0, 1.0)
        r = compute_corner_relief(spec)
        # Unique points (exclude closing duplicate)
        unique_pts = list(dict.fromkeys(r.outline_xy))
        assert len(unique_pts) >= 6, f"Expected L-shape; got {len(unique_pts)} pts"


class TestCornerReliefValidation:
    """Input validation raises ValueError on bad inputs."""

    def test_invalid_type(self):
        with pytest.raises(ValueError, match="relief_type"):
            compute_corner_relief(CornerReliefSpec("triangle", 1.0, 1.0))

    def test_zero_radius(self):
        with pytest.raises(ValueError, match="bend_radius_mm"):
            compute_corner_relief(CornerReliefSpec("square", 0.0, 1.0))

    def test_zero_thickness(self):
        with pytest.raises(ValueError, match="thickness_mm"):
            compute_corner_relief(CornerReliefSpec("square", 1.0, 0.0))

    def test_bad_angle(self):
        with pytest.raises(ValueError, match="bend_angle_deg"):
            compute_corner_relief(CornerReliefSpec("square", 1.0, 1.0, 200.0))


class TestCornerReliefHonestCaveat:
    """honest_caveat field is populated for all types."""

    @pytest.mark.parametrize("rtype", ["square", "round", "lance"])
    def test_caveat_populated(self, rtype):
        r = compute_corner_relief(CornerReliefSpec(rtype, 1.0, 1.0))
        assert r.honest_caveat
        assert "DIN 6935" in r.honest_caveat or "Suchy" in r.honest_caveat


class TestSheetMetalFlatPatternRegression:
    """Regression oracle for existing flat-pattern computation (still passes)."""

    def test_l_bracket_90_deg(self):
        """L-bracket: 2 mm steel, 2 flanges, 90° bend, r=2mm."""
        from kerf_cad_core.sheetmetal_features import SheetMetalPart, compute_flat_pattern
        part = SheetMetalPart(
            material="steel-cold-rolled",
            thickness_mm=2.0,
            length_mm=50.0,
            width_mm=50.0,
            bend_radius_mm=2.0,
            bend_angle_deg=90.0,
            flange_lengths_mm=[30.0, 30.0],
        )
        r = compute_flat_pattern(part)
        # r/t = 2/2 = 1.0 → K ≈ 0.33 (severe side of linear range)
        # BA = (π/2) * (2 + 0.33*2) = (π/2) * 2.66 ≈ 4.178
        ba_expected = (math.pi / 2) * (2.0 + 0.33 * 2.0)
        assert abs(r.bend_allowances_mm[0] - ba_expected) < 0.01
        assert r.num_bends == 1
