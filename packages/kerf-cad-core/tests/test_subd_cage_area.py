"""test_subd_cage_area.py
========================
Tests for subd/cage_area.py — SUBD-CAGE-AREA.

Coverage (17 tests across 9 classes):

  TestUnitCubeCage (4 tests):
    1.  Unit-cube cage (6 quads, 8 verts, side=1 mm): total cage area = 6 mm².
    2.  Limit-surface estimate ≈ 5.64 mm² (6 × 0.94).
    3.  All 6 per-face areas are 1.0 mm².
    4.  No degenerate faces.

  TestDegenerateTriangle (3 tests):
    5.  Collinear-point triangle has area ≈ 0.
    6.  Collinear triangle is flagged in degenerate_face_indices.
    7.  CageAreaReport.num_tris = 1.

  TestMixedPyramid (3 tests):
    8.  Square-base pyramid (1 quad base + 4 tri sides): total area is correct.
    9.  num_quads=1, num_tris=4.
    10. per_face_areas has length 5.

  TestPentagonNGon (2 tests):
    11. Regular pentagon (5 edges, area = 5/4 · tan(π/5) · s²): area within 1e-9.
    12. num_ngons=1.

  TestFaceTypeCounts (2 tests):
    13. Mixed cage (1 tri + 2 quads + 1 pentagon): counts are correct.
    14. Total area = sum(per_face_areas).

  TestMinMaxAreas (2 tests):
    15. min_face_area_mm2 and max_face_area_mm2 are correct on non-uniform cage.
    16. Degenerate faces are excluded from min/max.

  TestScaling (1 test):
    17. Scaling all vertex coords by k scales cage area by k².

  TestLimitEstimate (1 test):
    18. estimated_limit_surface_area_mm2 = total_cage_area_mm2 × 0.94 exactly.

  TestImports (1 test):
    19. SubdCage, CageAreaReport, compute_cage_area all importable from
        kerf_cad_core.subd.

  TestHonestCaveat (1 test — bonus, total >= 17):
    20. honest_caveat is a non-empty string mentioning '0.94' or 'empirical'.
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.subd.cage_area import (
    SubdCage,
    CageAreaReport,
    compute_cage_area,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit_cube_cage() -> SubdCage:
    """Unit cube cage: 8 vertices, 6 quad faces, each face area = 1 mm²."""
    verts = [
        (0.0, 0.0, 0.0),  # 0
        (1.0, 0.0, 0.0),  # 1
        (1.0, 1.0, 0.0),  # 2
        (0.0, 1.0, 0.0),  # 3
        (0.0, 0.0, 1.0),  # 4
        (1.0, 0.0, 1.0),  # 5
        (1.0, 1.0, 1.0),  # 6
        (0.0, 1.0, 1.0),  # 7
    ]
    faces = [
        [0, 1, 2, 3],  # bottom (z=0)
        [4, 5, 6, 7],  # top (z=1)
        [0, 1, 5, 4],  # front (y=0)
        [2, 3, 7, 6],  # back (y=1)
        [0, 3, 7, 4],  # left (x=0)
        [1, 2, 6, 5],  # right (x=1)
    ]
    return SubdCage(vertices_xyz_mm=verts, faces=faces)


# ---------------------------------------------------------------------------
# TestUnitCubeCage
# ---------------------------------------------------------------------------

class TestUnitCubeCage:
    """Unit cube: 6 quad faces each with area 1 mm² → total = 6 mm²."""

    def _report(self) -> CageAreaReport:
        return compute_cage_area(_unit_cube_cage())

    def test_total_cage_area(self):
        """Total cage area of unit cube = 6 mm²."""
        r = self._report()
        assert abs(r.total_cage_area_mm2 - 6.0) < 1e-9, (
            f"Expected 6.0 mm², got {r.total_cage_area_mm2}"
        )

    def test_limit_surface_estimate(self):
        """Limit-surface estimate = 6 × 0.94 = 5.64 mm²."""
        r = self._report()
        expected = 6.0 * 0.94
        assert abs(r.estimated_limit_surface_area_mm2 - expected) < 1e-9, (
            f"Expected {expected} mm², got {r.estimated_limit_surface_area_mm2}"
        )

    def test_per_face_areas_all_one(self):
        """Each of the 6 cube faces should have area exactly 1 mm²."""
        r = self._report()
        assert len(r.per_face_areas) == 6
        for i, a in enumerate(r.per_face_areas):
            assert abs(a - 1.0) < 1e-9, f"Face {i} area = {a}, expected 1.0"

    def test_no_degenerate_faces(self):
        """No degenerate faces on unit cube."""
        r = self._report()
        assert r.degenerate_face_indices == [], (
            f"Unexpected degenerate faces: {r.degenerate_face_indices}"
        )


# ---------------------------------------------------------------------------
# TestDegenerateTriangle
# ---------------------------------------------------------------------------

class TestDegenerateTriangle:
    """Triangle with collinear points: area ≈ 0, flagged as degenerate."""

    def _collinear_cage(self) -> SubdCage:
        verts = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
        ]
        faces = [[0, 1, 2]]
        return SubdCage(vertices_xyz_mm=verts, faces=faces)

    def _report(self) -> CageAreaReport:
        return compute_cage_area(self._collinear_cage())

    def test_area_near_zero(self):
        """Collinear triangle area is effectively 0."""
        r = self._report()
        assert r.total_cage_area_mm2 < 1e-9, (
            f"Expected ≈0, got {r.total_cage_area_mm2}"
        )

    def test_flagged_as_degenerate(self):
        """Collinear triangle face index 0 should be in degenerate_face_indices."""
        r = self._report()
        assert 0 in r.degenerate_face_indices, (
            f"Expected face 0 in degenerate list, got {r.degenerate_face_indices}"
        )

    def test_num_tris_is_one(self):
        """num_tris = 1 for a single-triangle cage."""
        r = self._report()
        assert r.num_tris == 1
        assert r.num_quads == 0
        assert r.num_ngons == 0


# ---------------------------------------------------------------------------
# TestMixedPyramid
# ---------------------------------------------------------------------------

class TestMixedPyramid:
    """Square-base pyramid: 1 quad base + 4 triangular sides.

    Base: unit square at z=0 (area = 1).
    Apex: (0.5, 0.5, 1.0).
    Each triangular face: half of 1×1 base → area depends on slant.

    Slant triangle vertices (e.g. front face): (0,0,0), (1,0,0), (0.5,0.5,1).
    Expected area = 0.5 × |cross((1,0,0)-(0,0,0), (0.5,0.5,1)-(0,0,0))|
                  = 0.5 × |(1,0,0) × (0.5,0.5,1)|
                  = 0.5 × |(-0.5, -0.5, 0.5)| (wait, let me recompute)

    cross((1,0,0), (0.5,0.5,1)) = (0·1-0·0.5, 0·0.5-1·1, 1·0.5-0·0.5)
                                 = (0, -1, 0.5)
    |cross| = sqrt(0 + 1 + 0.25) = sqrt(1.25)
    area = 0.5 × sqrt(1.25) ≈ 0.5590

    4 triangular faces + 1 quad base.
    """

    def _pyramid_cage(self) -> SubdCage:
        verts = [
            (0.0, 0.0, 0.0),   # 0 base corner
            (1.0, 0.0, 0.0),   # 1
            (1.0, 1.0, 0.0),   # 2
            (0.0, 1.0, 0.0),   # 3
            (0.5, 0.5, 1.0),   # 4 apex
        ]
        faces = [
            [0, 1, 2, 3],   # base quad
            [0, 1, 4],      # front tri
            [1, 2, 4],      # right tri
            [2, 3, 4],      # back tri
            [3, 0, 4],      # left tri
        ]
        return SubdCage(vertices_xyz_mm=verts, faces=faces)

    def _report(self) -> CageAreaReport:
        return compute_cage_area(self._pyramid_cage())

    def test_total_area_correct(self):
        """Pyramid total area = base 1 + 4 × slant triangles."""
        r = self._report()
        # Base quad area = 1.0
        # Each slant tri: as computed above, area = 0.5 × sqrt(1.25)
        slant_area = 0.5 * math.sqrt(1.25)
        expected = 1.0 + 4 * slant_area
        assert abs(r.total_cage_area_mm2 - expected) < 1e-9, (
            f"Expected {expected}, got {r.total_cage_area_mm2}"
        )

    def test_face_type_counts(self):
        """1 quad + 4 tris."""
        r = self._report()
        assert r.num_quads == 1
        assert r.num_tris == 4
        assert r.num_ngons == 0

    def test_per_face_areas_length(self):
        """per_face_areas has length 5 (1 quad + 4 tris)."""
        r = self._report()
        assert len(r.per_face_areas) == 5


# ---------------------------------------------------------------------------
# TestPentagonNGon
# ---------------------------------------------------------------------------

class TestPentagonNGon:
    """Regular pentagon in the XY plane with unit side length.

    Area = (s² / 4) × sqrt(5(5 + 2√5))  (exact formula, s=1)
         ≈ 1.72048 mm².

    Vertices computed as circle of radius r = 1/(2 sin(π/5)).
    """

    @staticmethod
    def _pentagon_verts():
        s = 1.0  # side length in mm
        r = s / (2 * math.sin(math.pi / 5))
        verts = []
        for k in range(5):
            theta = 2 * math.pi * k / 5 - math.pi / 2  # start at top
            verts.append((r * math.cos(theta), r * math.sin(theta), 0.0))
        return verts

    def _pentagon_cage(self) -> SubdCage:
        verts = self._pentagon_verts()
        faces = [[0, 1, 2, 3, 4]]
        return SubdCage(vertices_xyz_mm=verts, faces=faces)

    def _expected_area(self) -> float:
        s = 1.0
        return (s ** 2) / 4 * math.sqrt(5 * (5 + 2 * math.sqrt(5)))

    def _report(self) -> CageAreaReport:
        return compute_cage_area(self._pentagon_cage())

    def test_area_within_tolerance(self):
        """Pentagon area matches exact formula within 1e-9."""
        r = self._report()
        expected = self._expected_area()
        assert abs(r.total_cage_area_mm2 - expected) < 1e-9, (
            f"Expected {expected}, got {r.total_cage_area_mm2}"
        )

    def test_num_ngons(self):
        """num_ngons=1 for a single pentagon face."""
        r = self._report()
        assert r.num_ngons == 1
        assert r.num_quads == 0
        assert r.num_tris == 0


# ---------------------------------------------------------------------------
# TestFaceTypeCounts
# ---------------------------------------------------------------------------

class TestFaceTypeCounts:
    """Mixed cage: 1 triangle + 2 quads + 1 pentagon."""

    def _mixed_cage(self) -> SubdCage:
        # Vertices for a simple planar mixed cage in XY plane.
        # We'll place each face with distinct vertices.
        # Triangle: (0,0), (1,0), (0.5,1) at z=0
        # Quad 1: (2,0), (3,0), (3,1), (2,1) at z=0
        # Quad 2: (4,0), (5,0), (5,1), (4,1) at z=0
        # Pentagon: (6,0),(7,0),(7.5,0.5),(7,1),(6,1) at z=0
        verts = [
            # tri
            (0.0, 0.0, 0.0),  # 0
            (1.0, 0.0, 0.0),  # 1
            (0.5, 1.0, 0.0),  # 2
            # quad 1
            (2.0, 0.0, 0.0),  # 3
            (3.0, 0.0, 0.0),  # 4
            (3.0, 1.0, 0.0),  # 5
            (2.0, 1.0, 0.0),  # 6
            # quad 2
            (4.0, 0.0, 0.0),  # 7
            (5.0, 0.0, 0.0),  # 8
            (5.0, 1.0, 0.0),  # 9
            (4.0, 1.0, 0.0),  # 10
            # pentagon
            (6.0, 0.0, 0.0),  # 11
            (7.0, 0.0, 0.0),  # 12
            (7.5, 0.5, 0.0),  # 13
            (7.0, 1.0, 0.0),  # 14
            (6.0, 1.0, 0.0),  # 15
        ]
        faces = [
            [0, 1, 2],            # triangle
            [3, 4, 5, 6],         # quad 1
            [7, 8, 9, 10],        # quad 2
            [11, 12, 13, 14, 15], # pentagon
        ]
        return SubdCage(vertices_xyz_mm=verts, faces=faces)

    def _report(self) -> CageAreaReport:
        return compute_cage_area(self._mixed_cage())

    def test_face_type_counts(self):
        """1 tri + 2 quads + 1 ngon."""
        r = self._report()
        assert r.num_tris == 1
        assert r.num_quads == 2
        assert r.num_ngons == 1

    def test_total_is_sum_of_per_face(self):
        """total_cage_area_mm2 == sum(per_face_areas)."""
        r = self._report()
        assert abs(r.total_cage_area_mm2 - sum(r.per_face_areas)) < 1e-12


# ---------------------------------------------------------------------------
# TestMinMaxAreas
# ---------------------------------------------------------------------------

class TestMinMaxAreas:
    """min/max face areas on a cage with faces of varying sizes."""

    def _non_uniform_cage(self) -> SubdCage:
        """Three unit quads and one 2×2 quad in XY plane."""
        verts = [
            # 1×1 quad (area=1)
            (0.0, 0.0, 0.0),  # 0
            (1.0, 0.0, 0.0),  # 1
            (1.0, 1.0, 0.0),  # 2
            (0.0, 1.0, 0.0),  # 3
            # 2×2 quad (area=4)
            (2.0, 0.0, 0.0),  # 4
            (4.0, 0.0, 0.0),  # 5
            (4.0, 2.0, 0.0),  # 6
            (2.0, 2.0, 0.0),  # 7
        ]
        faces = [
            [0, 1, 2, 3],  # 1×1
            [4, 5, 6, 7],  # 2×2
        ]
        return SubdCage(vertices_xyz_mm=verts, faces=faces)

    def _report(self) -> CageAreaReport:
        return compute_cage_area(self._non_uniform_cage())

    def test_min_max_areas(self):
        """min=1.0, max=4.0."""
        r = self._report()
        assert abs(r.min_face_area_mm2 - 1.0) < 1e-9, (
            f"Expected min=1.0, got {r.min_face_area_mm2}"
        )
        assert abs(r.max_face_area_mm2 - 4.0) < 1e-9, (
            f"Expected max=4.0, got {r.max_face_area_mm2}"
        )

    def test_degenerate_excluded_from_minmax(self):
        """When a degenerate face is present, min/max are computed from valid faces only."""
        # Add a collinear triangle to the non-uniform cage.
        cage = self._non_uniform_cage()
        cage.vertices_xyz_mm.append((10.0, 0.0, 0.0))  # 8
        cage.vertices_xyz_mm.append((11.0, 0.0, 0.0))  # 9
        cage.vertices_xyz_mm.append((12.0, 0.0, 0.0))  # 10
        cage.faces.append([8, 9, 10])  # degenerate (collinear)
        r = compute_cage_area(cage)
        # Degenerate triangle must appear in degenerate list.
        assert 2 in r.degenerate_face_indices, (
            f"Expected face 2 degenerate; got {r.degenerate_face_indices}"
        )
        # min and max must still come from non-degenerate faces only.
        assert abs(r.min_face_area_mm2 - 1.0) < 1e-9
        assert abs(r.max_face_area_mm2 - 4.0) < 1e-9


# ---------------------------------------------------------------------------
# TestScaling
# ---------------------------------------------------------------------------

class TestScaling:
    """Scaling vertices by k scales cage area by k²."""

    def test_area_scales_by_k_squared(self):
        """Double all vertex coords → area × 4."""
        cage = _unit_cube_cage()
        cage2 = SubdCage(
            vertices_xyz_mm=[(2*x, 2*y, 2*z) for (x, y, z) in cage.vertices_xyz_mm],
            faces=cage.faces,
        )
        r1 = compute_cage_area(cage)
        r2 = compute_cage_area(cage2)
        assert abs(r2.total_cage_area_mm2 - 4.0 * r1.total_cage_area_mm2) < 1e-9, (
            f"Expected {4.0 * r1.total_cage_area_mm2}, got {r2.total_cage_area_mm2}"
        )


# ---------------------------------------------------------------------------
# TestLimitEstimate
# ---------------------------------------------------------------------------

class TestLimitEstimate:
    """estimated_limit_surface_area_mm2 = total × 0.94 (exact ratio)."""

    def test_limit_ratio_exact(self):
        """For any cage, estimate = cage_area × 0.94."""
        cages = [
            _unit_cube_cage(),
            SubdCage(
                vertices_xyz_mm=[(0,0,0),(3,0,0),(3,3,0),(0,3,0)],
                faces=[[0,1,2,3]],
            ),
        ]
        for cage in cages:
            r = compute_cage_area(cage)
            expected = r.total_cage_area_mm2 * 0.94
            assert abs(r.estimated_limit_surface_area_mm2 - expected) < 1e-12, (
                f"estimated={r.estimated_limit_surface_area_mm2}, expected={expected}"
            )


# ---------------------------------------------------------------------------
# TestImports
# ---------------------------------------------------------------------------

class TestImports:
    """SubdCage, CageAreaReport, compute_cage_area importable from subd package."""

    def test_re_exported_from_subd_package(self):
        """Public names importable from kerf_cad_core.subd."""
        from kerf_cad_core.subd import SubdCage as SC
        from kerf_cad_core.subd import CageAreaReport as CAR
        from kerf_cad_core.subd import compute_cage_area as cca
        assert SC is SubdCage
        assert CAR is CageAreaReport
        assert cca is compute_cage_area


# ---------------------------------------------------------------------------
# TestHonestCaveat
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    """honest_caveat is non-empty and mentions the empirical nature of the estimate."""

    def test_caveat_mentions_empirical_or_ratio(self):
        """honest_caveat should contain '0.94' or 'empirical'."""
        r = compute_cage_area(_unit_cube_cage())
        caveat = r.honest_caveat.lower()
        assert caveat, "honest_caveat must be a non-empty string"
        assert "0.94" in caveat or "empirical" in caveat, (
            f"Expected '0.94' or 'empirical' in caveat, got: {r.honest_caveat[:100]}"
        )


# ---------------------------------------------------------------------------
# Additional edge-case tests (bonus)
# ---------------------------------------------------------------------------

class TestSingleTriangleNonDegenerate:
    """A valid equilateral triangle: area = √3/4 · s²."""

    def test_equilateral_triangle_area(self):
        s = 2.0  # side length mm
        h = s * math.sqrt(3) / 2
        verts = [(0.0, 0.0, 0.0), (s, 0.0, 0.0), (s / 2, h, 0.0)]
        cage = SubdCage(vertices_xyz_mm=verts, faces=[[0, 1, 2]])
        r = compute_cage_area(cage)
        expected = math.sqrt(3) / 4 * s ** 2
        assert abs(r.total_cage_area_mm2 - expected) < 1e-9
        assert r.degenerate_face_indices == []
        assert r.num_tris == 1


class TestZeroVertexFaces:
    """A face with fewer than 3 vertices: area=0, not counted in type stats."""

    def test_undersized_face_ignored(self):
        """Face with 2 vertices contributes 0 area and is counted as degenerate."""
        verts = [(0, 0, 0), (1, 0, 0)]
        cage = SubdCage(vertices_xyz_mm=verts, faces=[[0, 1]])
        r = compute_cage_area(cage)
        assert r.total_cage_area_mm2 == 0.0
        assert 0 in r.degenerate_face_indices


class TestHexagonNGon:
    """Regular hexagon with side s=1: area = 3√3/2 · s²."""

    def test_hexagon_area(self):
        s = 1.0
        verts = []
        for k in range(6):
            theta = 2 * math.pi * k / 6
            verts.append((s * math.cos(theta), s * math.sin(theta), 0.0))
        cage = SubdCage(vertices_xyz_mm=verts, faces=[list(range(6))])
        r = compute_cage_area(cage)
        expected = 3 * math.sqrt(3) / 2 * s ** 2
        assert abs(r.total_cage_area_mm2 - expected) < 1e-9
        assert r.num_ngons == 1
