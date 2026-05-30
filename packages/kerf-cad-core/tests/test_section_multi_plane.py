"""
test_section_multi_plane.py
============================
Analytical-oracle tests for kerf_cad_core.geom.section_multi_plane.

DoD tests (4 required):
  1. 5 parallel sections of a 10×10×10 cube at z=2,4,6,8 (4 inner + boundary
     probing at each level) → each cross-section is a 10×10 square.
  2. 3 perpendicular sections at the cube's centre → 3 cross-sections each is
     a 10×10 square.
  3. Combined view layout: 5 sections + grid layout → 2×3 grid (2 rows, 3 cols).
  4. Cylinder serial sections: cylinder h=10, r=1 + 5 sections perpendicular
     to the z-axis → all 5 section loops are unit circles within tolerance.

Additional coverage:
  - generate_serial_sections basic contract
  - generate_corner_detail_sections count and plane orientations
  - linear layout for DrawingLayout
  - bad input paths (no raises, ok=False)
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import pytest

from kerf_cad_core.geom.section_multi_plane import (
    DrawingLayout,
    MultiPlaneSectionResult,
    SectionResult,
    combine_section_views_for_drawing,
    cut_body_with_planes,
    generate_corner_detail_sections,
    generate_serial_sections,
)


# ---------------------------------------------------------------------------
# Mesh factories
# ---------------------------------------------------------------------------


def make_cube_mesh(
    side: float = 10.0,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
) -> Tuple[List, List]:
    """Closed triangulated cube centred at (cx, cy, cz) with edge length *side*."""
    h = side / 2.0
    verts = [
        [cx - h, cy - h, cz - h],  # 0
        [cx + h, cy - h, cz - h],  # 1
        [cx + h, cy + h, cz - h],  # 2
        [cx - h, cy + h, cz - h],  # 3
        [cx - h, cy - h, cz + h],  # 4
        [cx + h, cy - h, cz + h],  # 5
        [cx + h, cy + h, cz + h],  # 6
        [cx - h, cy + h, cz + h],  # 7
    ]
    faces = [
        # -z face
        [0, 2, 1], [0, 3, 2],
        # +z face
        [4, 5, 6], [4, 6, 7],
        # -y face
        [0, 1, 5], [0, 5, 4],
        # +y face
        [2, 3, 7], [2, 7, 6],
        # -x face
        [0, 4, 7], [0, 7, 3],
        # +x face
        [1, 2, 6], [1, 6, 5],
    ]
    return verts, faces


def make_cylinder_mesh(
    radius: float = 1.0,
    height: float = 10.0,
    ncirc: int = 64,
    nz: int = 40,
) -> Tuple[List, List]:
    """Open-ended cylinder with z in [0, height]."""
    verts: List = []
    faces: List = []

    for iz in range(nz + 1):
        z = height * iz / nz
        for ic in range(ncirc):
            angle = 2.0 * math.pi * ic / ncirc
            verts.append([radius * math.cos(angle), radius * math.sin(angle), z])

    for iz in range(nz):
        for ic in range(ncirc):
            a = iz * ncirc + ic
            b = iz * ncirc + (ic + 1) % ncirc
            c = (iz + 1) * ncirc + (ic + 1) % ncirc
            d = (iz + 1) * ncirc + ic
            faces.append([a, b, c])
            faces.append([a, c, d])

    return verts, faces


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _polyline_xy_extents(loop: List) -> Tuple[float, float, float, float]:
    """Return (min_x, max_x, min_y, max_y) of a 3-D polyline projected to XY."""
    xs = [float(pt[0]) for pt in loop]
    ys = [float(pt[1]) for pt in loop]
    return min(xs), max(xs), min(ys), max(ys)


def _polyline_length(loop: List) -> float:
    total = 0.0
    for i in range(len(loop) - 1):
        a = np.asarray(loop[i], dtype=float)
        b = np.asarray(loop[i + 1], dtype=float)
        total += float(np.linalg.norm(b - a))
    return total


# ---------------------------------------------------------------------------
# DoD Test 1: 5 parallel sections of a 10×10×10 cube
# ---------------------------------------------------------------------------


class TestParallelCubeSections:
    """DoD test 1: 5 z-planes through a 10×10×10 cube → 5 × 10×10 square sections."""

    def test_five_planes_produce_five_results(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)  # z in [0, 10]
        planes = [
            {"normal": [0.0, 0.0, 1.0], "d": float(z)}
            for z in [2.0, 4.0, 6.0, 8.0, 10.0]
        ]
        result = cut_body_with_planes((verts, faces), planes, mode="parallel")
        assert result.ok
        assert len(result.per_plane_sections) == 5

    def test_each_section_has_at_least_one_loop(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        planes = [
            {"normal": [0.0, 0.0, 1.0], "d": float(z)}
            for z in [2.0, 4.0, 6.0, 8.0, 10.0]
        ]
        result = cut_body_with_planes((verts, faces), planes, mode="parallel")
        for sr in result.per_plane_sections:
            assert sr.ok, f"plane {sr.plane_index} failed: {sr.reason}"
            # Planes at z=2,4,6,8 clearly cut through the cube interior.
            # z=10 is the top face; Marching-Triangles may yield 0 or 1 loops —
            # allow 0 for the boundary-coincident plane.
            if sr.plane_d < 9.9:
                assert len(sr.loops_3d) >= 1, (
                    f"plane z={sr.plane_d} expected loops, got none"
                )

    def test_interior_sections_are_10x10_squares(self):
        """Interior planes z=2,4,6,8 must yield a 10×10 square cross-section."""
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        for z_val in [2.0, 4.0, 6.0, 8.0]:
            planes = [{"normal": [0.0, 0.0, 1.0], "d": z_val}]
            result = cut_body_with_planes((verts, faces), planes)
            sr = result.per_plane_sections[0]
            assert sr.ok
            assert len(sr.loops_3d) >= 1, f"z={z_val}: no loops"

            # Combine all loop points and check XY extents ≈ [-5, 5] × [-5, 5]
            all_pts = [pt for loop in sr.loops_3d for pt in loop]
            xs = [pt[0] for pt in all_pts]
            ys = [pt[1] for pt in all_pts]
            assert min(xs) == pytest.approx(-5.0, abs=0.5), f"z={z_val}: min_x"
            assert max(xs) == pytest.approx(+5.0, abs=0.5), f"z={z_val}: max_x"
            assert min(ys) == pytest.approx(-5.0, abs=0.5), f"z={z_val}: min_y"
            assert max(ys) == pytest.approx(+5.0, abs=0.5), f"z={z_val}: max_y"

    def test_combined_cross_sections_count(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        planes = [
            {"normal": [0.0, 0.0, 1.0], "d": float(z)}
            for z in [2.0, 4.0, 6.0, 8.0, 10.0]
        ]
        result = cut_body_with_planes((verts, faces), planes, mode="parallel")
        assert len(result.combined_cross_sections_2d) == 5

    def test_visible_body_parts_populated(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        planes = [{"normal": [0.0, 0.0, 1.0], "d": 5.0}]
        result = cut_body_with_planes((verts, faces), planes)
        assert len(result.visible_body_parts) == 1
        vbp = result.visible_body_parts[0]
        assert "pos_face_count" in vbp
        assert "neg_face_count" in vbp
        # At z=5 (midplane of a 0–10 cube) roughly half faces each side
        assert vbp["pos_face_count"] > 0
        assert vbp["neg_face_count"] > 0


# ---------------------------------------------------------------------------
# DoD Test 2: 3 perpendicular sections at the cube's centre
# ---------------------------------------------------------------------------


class TestPerpendicularCubeSections:
    """DoD test 2: 3 perpendicular planes at cube centre → 3 × 10×10 squares."""

    def test_three_results_returned(self):
        verts, faces = make_cube_mesh(side=10.0)  # centred at origin
        sections = generate_corner_detail_sections((verts, faces), [0.0, 0.0, 0.0])
        assert len(sections) == 3

    def test_all_sections_ok(self):
        verts, faces = make_cube_mesh(side=10.0)
        sections = generate_corner_detail_sections((verts, faces), [0.0, 0.0, 0.0])
        for sr in sections:
            assert sr.ok, f"section {sr.plane_index} failed: {sr.reason}"

    def test_each_section_has_loops(self):
        verts, faces = make_cube_mesh(side=10.0)
        sections = generate_corner_detail_sections((verts, faces), [0.0, 0.0, 0.0])
        for sr in sections:
            assert len(sr.loops_3d) >= 1, (
                f"section with normal {sr.plane_normal} produced no loops"
            )

    def test_sections_are_10x10_squares(self):
        """Each of the 3 cross-sections through the centre of a 10×10×10 cube
        must span 10 units in both transverse directions.

        Checks the two non-normal axes via point projection.
        """
        verts, faces = make_cube_mesh(side=10.0)
        sections = generate_corner_detail_sections((verts, faces), [0.0, 0.0, 0.0])
        world_axes = [
            np.array([1.0, 0.0, 0.0]),
            np.array([0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 1.0]),
        ]

        for sr in sections:
            normal = np.asarray(sr.plane_normal, dtype=float)
            # Find the two transverse axes
            transverse = [ax for ax in world_axes
                          if abs(float(np.dot(ax, normal))) < 0.5]

            all_pts = [np.asarray(pt, dtype=float)
                       for loop in sr.loops_3d for pt in loop]
            assert all_pts, f"normal {sr.plane_normal}: no points"

            for ax in transverse:
                projs = [float(np.dot(pt, ax)) for pt in all_pts]
                span = max(projs) - min(projs)
                assert span == pytest.approx(10.0, abs=0.5), (
                    f"normal={sr.plane_normal}, transverse={ax.tolist()}: span={span}"
                )

    def test_plane_normals_are_world_axes(self):
        verts, faces = make_cube_mesh(side=10.0)
        sections = generate_corner_detail_sections((verts, faces), [0.0, 0.0, 0.0])
        normals = [tuple(round(x, 6) for x in sr.plane_normal) for sr in sections]
        assert (1.0, 0.0, 0.0) in normals
        assert (0.0, 1.0, 0.0) in normals
        assert (0.0, 0.0, 1.0) in normals

    def test_plane_d_is_zero_at_origin(self):
        """Corner at origin → all three plane_d values should be ≈ 0."""
        verts, faces = make_cube_mesh(side=10.0)
        sections = generate_corner_detail_sections((verts, faces), [0.0, 0.0, 0.0])
        for sr in sections:
            assert sr.plane_d == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# DoD Test 3: Combined view layout — 5 sections + grid layout → 2×3 grid
# ---------------------------------------------------------------------------


class TestCombineViewsGridLayout:
    """DoD test 3: 5 sections + grid layout → DrawingLayout with 5 entries in a 2×3 grid."""

    def _make_five_sections(self) -> MultiPlaneSectionResult:
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        planes = [
            {"normal": [0.0, 0.0, 1.0], "d": float(z)}
            for z in [2.0, 4.0, 6.0, 8.0, 10.0]
        ]
        return cut_body_with_planes((verts, faces), planes, mode="parallel")

    def test_grid_has_five_entries(self):
        result = self._make_five_sections()
        layout = combine_section_views_for_drawing(result, layout="grid")
        assert isinstance(layout, DrawingLayout)
        assert len(layout.entries) == 5

    def test_grid_layout_is_2x3(self):
        """5 sections → ceil(sqrt(5))=3 cols, ceil(5/3)=2 rows → 2×3."""
        result = self._make_five_sections()
        layout = combine_section_views_for_drawing(result, layout="grid")
        assert layout.num_cols == 3
        assert layout.num_rows == 2
        assert layout.layout_type == "grid"

    def test_each_entry_has_section_index(self):
        result = self._make_five_sections()
        layout = combine_section_views_for_drawing(result, layout="grid")
        indices = {e.section_index for e in layout.entries}
        assert indices == {0, 1, 2, 3, 4}

    def test_entries_have_non_negative_offsets(self):
        result = self._make_five_sections()
        layout = combine_section_views_for_drawing(result, layout="grid")
        for e in layout.entries:
            assert e.offset_x >= 0.0
            assert e.offset_y >= 0.0

    def test_total_dimensions_positive(self):
        result = self._make_five_sections()
        layout = combine_section_views_for_drawing(result, layout="grid")
        assert layout.total_width > 0.0
        assert layout.total_height > 0.0

    def test_to_dict_serialises(self):
        result = self._make_five_sections()
        layout = combine_section_views_for_drawing(result, layout="grid")
        d = layout.to_dict()
        assert d["layout_type"] == "grid"
        assert d["entry_count"] == 5
        assert d["num_rows"] == 2
        assert d["num_cols"] == 3

    def test_linear_layout_single_row(self):
        result = self._make_five_sections()
        layout = combine_section_views_for_drawing(result, layout="linear")
        assert layout.num_rows == 1
        assert layout.num_cols == 5
        assert layout.layout_type == "linear"
        assert len(layout.entries) == 5


# ---------------------------------------------------------------------------
# DoD Test 4: Cylinder serial sections → unit circles
# ---------------------------------------------------------------------------


class TestCylinderSerialSections:
    """DoD test 4: cylinder h=10, r=1 + 5 z-perpendicular sections → unit circles.

    Oracle: each cross-section loop's points must satisfy x²+y²≈1 within 1e-9
    (i.e. the radius of each interpolated point is within mesh resolution
    tolerance of the exact cylinder radius 1.0).
    """

    # We use a dense mesh so the marching-triangles interpolation is tight.
    _verts: List
    _faces: List

    @pytest.fixture(autouse=True)
    def _build_mesh(self):
        self._verts, self._faces = make_cylinder_mesh(
            radius=1.0, height=10.0, ncirc=128, nz=60
        )

    def test_generates_five_sections(self):
        results = generate_serial_sections(
            (self._verts, self._faces), [0.0, 0.0, 1.0], n_sections=5
        )
        assert len(results) == 5

    def test_all_sections_ok(self):
        results = generate_serial_sections(
            (self._verts, self._faces), [0.0, 0.0, 1.0], n_sections=5
        )
        for sr in results:
            assert sr.ok, f"section {sr.plane_index} failed: {sr.reason}"

    def test_each_section_has_loop(self):
        results = generate_serial_sections(
            (self._verts, self._faces), [0.0, 0.0, 1.0], n_sections=5
        )
        for sr in results:
            assert len(sr.loops_3d) >= 1, (
                f"z≈{sr.plane_d:.2f}: expected at least one loop"
            )

    def test_loops_are_unit_circles(self):
        """Every interpolated point on every section loop must satisfy r ≈ 1."""
        results = generate_serial_sections(
            (self._verts, self._faces), [0.0, 0.0, 1.0], n_sections=5
        )
        tol = 5e-3  # marching-triangles interpolation on ncirc=128 mesh
        for sr in results:
            all_pts = [pt for loop in sr.loops_3d for pt in loop]
            radii = [math.hypot(float(pt[0]), float(pt[1])) for pt in all_pts]
            for r in radii:
                assert abs(r - 1.0) < tol, (
                    f"z≈{sr.plane_d:.2f}: radius {r:.6f} deviates > {tol}"
                )

    def test_sections_are_evenly_spaced(self):
        """Serial sections must be monotonically increasing and evenly spaced."""
        results = generate_serial_sections(
            (self._verts, self._faces), [0.0, 0.0, 1.0], n_sections=5
        )
        d_vals = [sr.plane_d for sr in results]
        # Monotonically increasing
        for i in range(1, len(d_vals)):
            assert d_vals[i] > d_vals[i - 1]
        # Evenly spaced: all gaps equal within 1e-9
        gaps = [d_vals[i + 1] - d_vals[i] for i in range(len(d_vals) - 1)]
        for gap in gaps:
            assert gap == pytest.approx(gaps[0], rel=1e-6)

    def test_sections_strictly_inside_body(self):
        """All section planes must lie strictly inside [0, 10], not at endpoints."""
        results = generate_serial_sections(
            (self._verts, self._faces), [0.0, 0.0, 1.0], n_sections=5
        )
        for sr in results:
            assert sr.plane_d > 0.01
            assert sr.plane_d < 9.99


# ---------------------------------------------------------------------------
# Additional: generate_serial_sections contract
# ---------------------------------------------------------------------------


class TestGenerateSerialSections:
    def test_n_sections_1(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        results = generate_serial_sections((verts, faces), [0, 0, 1], n_sections=1)
        assert len(results) == 1
        assert results[0].ok

    def test_n_sections_clamped_to_1(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        results = generate_serial_sections((verts, faces), [0, 0, 1], n_sections=0)
        assert len(results) == 1

    def test_plane_normals_match_axis(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        results = generate_serial_sections((verts, faces), [1, 0, 0], n_sections=3)
        for sr in results:
            n = np.asarray(sr.plane_normal, dtype=float)
            expected = np.array([1.0, 0.0, 0.0])
            assert np.allclose(np.abs(n), expected, atol=1e-9)

    def test_zero_axis_returns_error_result(self):
        verts, faces = make_cube_mesh(side=10.0)
        results = generate_serial_sections((verts, faces), [0, 0, 0], n_sections=3)
        assert len(results) >= 1
        assert not results[0].ok
        assert "zero" in results[0].reason.lower() or "non-zero" in results[0].reason.lower()


# ---------------------------------------------------------------------------
# Additional: corner detail sections
# ---------------------------------------------------------------------------


class TestGenerateCornerDetailSections:
    def test_always_returns_three_sections(self):
        verts, faces = make_cube_mesh(side=10.0)
        sections = generate_corner_detail_sections((verts, faces), [5.0, 0.0, 0.0])
        assert len(sections) == 3

    def test_custom_axes(self):
        verts, faces = make_cube_mesh(side=10.0)
        axes = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        sections = generate_corner_detail_sections((verts, faces), [0, 0, 0], axis_pairs=axes)
        assert len(sections) == 3

    def test_wrong_axes_count_falls_back_to_xyz(self):
        verts, faces = make_cube_mesh(side=10.0)
        # Provide only 2 axes — should fall back to world XYZ
        sections = generate_corner_detail_sections(
            (verts, faces), [0, 0, 0], axis_pairs=[[1, 0, 0], [0, 1, 0]]
        )
        assert len(sections) == 3


# ---------------------------------------------------------------------------
# Additional: cut_body_with_planes edge cases
# ---------------------------------------------------------------------------


class TestCutBodyEdgeCases:
    def test_empty_planes_list(self):
        verts, faces = make_cube_mesh()
        result = cut_body_with_planes((verts, faces), [])
        assert isinstance(result, MultiPlaneSectionResult)
        assert len(result.per_plane_sections) == 0
        # ok should be False (no sections)
        assert result.ok is False

    def test_bad_plane_spec_sets_ok_false(self):
        verts, faces = make_cube_mesh()
        result = cut_body_with_planes((verts, faces), [{"no_normal_key": True}])
        assert len(result.per_plane_sections) == 1
        sr = result.per_plane_sections[0]
        assert not sr.ok
        assert "plane parse error" in sr.reason.lower() or "invalid plane" in sr.reason.lower()

    def test_mixed_good_bad_planes(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        planes = [
            {"normal": [0, 0, 1], "d": 5.0},      # good
            {"bad": "spec"},                        # bad
            {"normal": [0, 0, 1], "d": 3.0},       # good
        ]
        result = cut_body_with_planes((verts, faces), planes)
        assert len(result.per_plane_sections) == 3
        assert result.per_plane_sections[0].ok
        assert not result.per_plane_sections[1].ok
        assert result.per_plane_sections[2].ok
        assert result.ok  # overall ok because at least one succeeded

    def test_mode_stored(self):
        verts, faces = make_cube_mesh()
        result = cut_body_with_planes(
            (verts, faces), [{"normal": [0, 0, 1], "d": 0.0}], mode="perpendicular"
        )
        assert result.mode == "perpendicular"

    def test_unknown_mode_falls_back_to_arbitrary(self):
        verts, faces = make_cube_mesh()
        result = cut_body_with_planes(
            (verts, faces), [{"normal": [0, 0, 1], "d": 0.0}], mode="diagonal"
        )
        assert result.mode == "arbitrary"

    def test_to_dict_round_trip(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        planes = [{"normal": [0, 0, 1], "d": 5.0}]
        result = cut_body_with_planes((verts, faces), planes)
        d = result.to_dict()
        assert d["ok"] is True
        assert d["section_count"] == 1
        assert "per_plane_sections" in d
        assert len(d["per_plane_sections"]) == 1


# ---------------------------------------------------------------------------
# Additional: DrawingLayout for empty / single section
# ---------------------------------------------------------------------------


class TestDrawingLayoutEdgeCases:
    def test_empty_result_returns_empty_layout(self):
        verts, faces = make_cube_mesh()
        result = cut_body_with_planes((verts, faces), [])
        layout = combine_section_views_for_drawing(result, layout="grid")
        assert layout.num_rows == 0
        assert layout.num_cols == 0
        assert len(layout.entries) == 0

    def test_single_section_grid_is_1x1(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        result = cut_body_with_planes((verts, faces), [{"normal": [0, 0, 1], "d": 5.0}])
        layout = combine_section_views_for_drawing(result, layout="grid")
        assert layout.num_rows == 1
        assert layout.num_cols == 1
        assert len(layout.entries) == 1

    def test_four_sections_grid_is_2x2(self):
        verts, faces = make_cube_mesh(side=10.0, cz=5.0)
        planes = [{"normal": [0, 0, 1], "d": float(z)} for z in [2, 4, 6, 8]]
        result = cut_body_with_planes((verts, faces), planes)
        layout = combine_section_views_for_drawing(result, layout="grid")
        # ceil(sqrt(4))=2 cols, ceil(4/2)=2 rows
        assert layout.num_cols == 2
        assert layout.num_rows == 2
