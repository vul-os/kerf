"""
Tests for SUBD-SYMMETRY-DETECT: detect_symmetry(cage) -> SymmetryReport.

Reference oracles from regular polyhedra:

Cube (centered at origin, side 2):
  8 vertices at (+-1, +-1, +-1).
  Mirror planes: XY (z=0), XZ (y=0), YZ (x=0) -- all score 1.0.
  Rotation about Z-axis: 4-fold (score 1.0).
  Rotation about X-axis: 4-fold (score 1.0).
  Rotation about Y-axis: 4-fold (score 1.0).

Regular tetrahedron (centered at origin, placed on XZ mirror):
  4 vertices; XZ plane scores 1.0 (real symmetry).
  3-fold rotational symmetry about the vertex-to-opposite-face axis.
  Irregular tetrahedron: no axis-aligned mirror planes score 1.0.

Cylinder cage (6 vertices on a circle + 2 caps):
  Rotational symmetry about Z-axis -> best fold 6, continuous flag.

Skewed cage (cube with one vertex displaced in x, y, z unequally):
  All mirror-plane scores < 1.0.
  All rotation axis scores = 0.

Analytical references
---------------------
- Mitra et al. 2006 "Partial and Approximate Symmetry Detection for 3D Geometry"
- Podolak et al. 2006 "A Planar-Reflective Symmetry Transform for 3D Shapes"
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.geom.subd_authoring import SubDCage, create_subd_primitive, _copy_cage
from kerf_cad_core.geom.subd_symmetry import (
    RotationAxis,
    SymmetryPlane,
    SymmetryReport,
    detect_symmetry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cube_cage(side: float = 2.0) -> SubDCage:
    """Unit cube cage centered at origin (side length = side)."""
    return create_subd_primitive("cube", width=side, height=side, depth=side)


def _regular_tetrahedron_cage() -> SubDCage:
    """Regular tetrahedron inscribed in the unit sphere.

    Placed so that two vertices are at y > 0 and two at y < 0, making the
    XZ plane (y=0) a genuine mirror plane.
    """
    a = math.sqrt(8.0 / 9.0)
    b = math.sqrt(2.0 / 9.0)
    c = math.sqrt(2.0 / 3.0)
    verts = [
        [0.0, 0.0, 1.0],
        [a, 0.0, -1.0 / 3.0],
        [-b, c, -1.0 / 3.0],
        [-b, -c, -1.0 / 3.0],
    ]
    faces = [[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]]
    return SubDCage(vertices=verts, faces=faces)


def _irregular_tetrahedron_cage() -> SubDCage:
    """Irregular tetrahedron with no axis-aligned mirror symmetry."""
    verts = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.3, 0.8, 0.0],
        [0.2, 0.3, 1.0],
    ]
    faces = [[0, 1, 2], [0, 1, 3], [1, 2, 3], [2, 0, 3]]
    return SubDCage(vertices=verts, faces=faces)


def _cylinder_cage(n: int = 6, radius: float = 1.0, height: float = 2.0) -> SubDCage:
    """Hexagonal prism cage approximating a cylinder."""
    verts = []
    for i in range(n):
        theta = 2.0 * math.pi * i / n
        x = radius * math.cos(theta)
        y = radius * math.sin(theta)
        verts.append([x, y, -height / 2])
    for i in range(n):
        theta = 2.0 * math.pi * i / n
        x = radius * math.cos(theta)
        y = radius * math.sin(theta)
        verts.append([x, y, height / 2])
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, j + n, i + n])
    faces.append(list(range(n)))
    faces.append(list(range(n, 2 * n)))
    return SubDCage(vertices=verts, faces=faces)


def _skewed_cube_cage(displacement: float = 0.3) -> SubDCage:
    """Cube with vertex 0 displaced by different amounts in x, y, z.

    Unequal per-axis displacements break all axis-aligned and PCA mirror planes
    and all rotational symmetry axes, giving overall_score < 1.0.
    """
    cage = _cube_cage()
    result = _copy_cage(cage)
    result.vertices[0] = [
        result.vertices[0][0] + displacement * 0.333,
        result.vertices[0][1] + displacement * 0.667,
        result.vertices[0][2] + displacement * 1.0,
    ]
    return result


# ---------------------------------------------------------------------------
# 1. Return types
# ---------------------------------------------------------------------------

class TestReturnTypes:
    def test_returns_symmetry_report(self):
        cage = _cube_cage()
        report = detect_symmetry(cage)
        assert isinstance(report, SymmetryReport)

    def test_mirror_planes_list(self):
        cage = _cube_cage()
        report = detect_symmetry(cage)
        assert isinstance(report.mirror_planes, list)
        for p in report.mirror_planes:
            assert isinstance(p, SymmetryPlane)

    def test_rotation_axes_list(self):
        cage = _cube_cage()
        report = detect_symmetry(cage)
        assert isinstance(report.rotation_axes, list)
        for r in report.rotation_axes:
            assert isinstance(r, RotationAxis)

    def test_deviation_per_axis_dict(self):
        cage = _cube_cage()
        report = detect_symmetry(cage)
        assert isinstance(report.deviation_per_axis, dict)

    def test_empty_cage_returns_empty_report(self):
        cage = SubDCage(vertices=[], faces=[])
        report = detect_symmetry(cage)
        assert report.overall_score == 0.0
        assert report.mirror_planes == []
        assert report.rotation_axes == []


# ---------------------------------------------------------------------------
# 2. Cube cage: 3 mirror planes score 1.0
# ---------------------------------------------------------------------------

class TestCubeMirrorPlanes:
    """Cube cage centered at origin -> 3 axis-aligned planes all score 1.0."""

    def setup_method(self):
        self.cage = _cube_cage(side=2.0)
        self.report = detect_symmetry(self.cage, tol=1e-4)

    def test_three_perfect_mirror_planes_exist(self):
        """At least 3 planes with score 1.0 must be detected."""
        perfect = [p for p in self.report.mirror_planes if p.score >= 1.0 - 1e-6]
        assert len(perfect) >= 3, (
            f"Expected >= 3 perfect mirror planes for a cube; found {len(perfect)}: "
            + str([(p.label, p.score) for p in perfect])
        )

    def test_xy_plane_score_1(self):
        """XY plane (z=0 or centroid-z) must score 1.0 for cube."""
        xy_scores = [
            p.score for p in self.report.mirror_planes
            if "XY" in p.label or (
                abs(p.normal[2]) > 0.99 and abs(p.normal[0]) < 0.01
            )
        ]
        assert any(s >= 1.0 - 1e-6 for s in xy_scores), (
            f"Expected XY mirror score >= 1.0 for cube; found scores {xy_scores}"
        )

    def test_xz_plane_score_1(self):
        """XZ plane (y=0 or centroid-y) must score 1.0 for cube."""
        xz_scores = [
            p.score for p in self.report.mirror_planes
            if "XZ" in p.label or (
                abs(p.normal[1]) > 0.99 and abs(p.normal[0]) < 0.01
            )
        ]
        assert any(s >= 1.0 - 1e-6 for s in xz_scores), (
            f"Expected XZ mirror score >= 1.0 for cube; found scores {xz_scores}"
        )

    def test_yz_plane_score_1(self):
        """YZ plane (x=0 or centroid-x) must score 1.0 for cube."""
        yz_scores = [
            p.score for p in self.report.mirror_planes
            if "YZ" in p.label or (
                abs(p.normal[0]) > 0.99 and abs(p.normal[1]) < 0.01
            )
        ]
        assert any(s >= 1.0 - 1e-6 for s in yz_scores), (
            f"Expected YZ mirror score >= 1.0 for cube; found scores {yz_scores}"
        )

    def test_overall_score_1(self):
        assert self.report.overall_score >= 1.0 - 1e-6

    def test_planes_sorted_descending(self):
        scores = [p.score for p in self.report.mirror_planes]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 3. Cube cage: rotational symmetry
# ---------------------------------------------------------------------------

class TestCubeRotation:
    """Cube has 4-fold rotation about each of the 3 face-normal axes."""

    def setup_method(self):
        self.cage = _cube_cage(side=2.0)
        self.report = detect_symmetry(self.cage, tol=1e-4)

    def test_rotation_axes_present(self):
        assert len(self.report.rotation_axes) > 0, "Expected at least one rotation axis"

    def test_best_rotation_score_is_1(self):
        best = max(r.score for r in self.report.rotation_axes)
        assert best >= 1.0 - 1e-6, (
            f"Expected best rotation score >= 1.0 for cube; got {best}"
        )

    def test_4fold_rotation_detected(self):
        """Cube has 4-fold rotation about at least one principal axis."""
        has_4fold = any(r.fold_order == 4 and r.score >= 1.0 - 1e-6
                        for r in self.report.rotation_axes)
        assert has_4fold, (
            "Expected 4-fold rotation with score 1.0 for cube; "
            + str([(r.label, r.fold_order, r.score) for r in self.report.rotation_axes])
        )

    def test_rotation_axes_sorted_descending(self):
        scores = [r.score for r in self.report.rotation_axes]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 4. Tetrahedron: 3-fold rotational symmetry
# ---------------------------------------------------------------------------

class TestTetrahedronSymmetry:
    """Regular tetrahedron: 3-fold rotational symmetry about vertex-to-face axes.

    Note: the canonical regular tetrahedron used here IS symmetric about XZ
    (y=0) -- vertices come in y/(-y) pairs.  XY and YZ are NOT mirrors.
    An irregular tetrahedron is also tested for the no-axis-mirror case.
    """

    def setup_method(self):
        self.cage = _regular_tetrahedron_cage()
        self.report = detect_symmetry(self.cage, tol=1e-3)

    def test_xz_is_valid_mirror(self):
        """Regular tetrahedron placed symmetrically about y=0 plane."""
        xz_score = next(
            (p.score for p in self.report.mirror_planes if p.label == "XZ"),
            0.0,
        )
        assert xz_score >= 1.0 - 1e-6, (
            "Regular tetrahedron in this orientation has XZ mirror symmetry"
        )

    def test_xy_not_perfect(self):
        """XY plane is not a mirror for the regular tetrahedron."""
        xy_score = next(
            (p.score for p in self.report.mirror_planes if p.label == "XY"),
            0.0,
        )
        assert xy_score < 1.0 - 1e-6

    def test_irregular_tetrahedron_no_perfect_axis_mirror(self):
        """Irregular tetrahedron has no axis-aligned mirror plane."""
        cage = _irregular_tetrahedron_cage()
        report = detect_symmetry(cage, tol=1e-3)
        axis_aligned = [
            p for p in report.mirror_planes
            if p.label in ("XY", "XZ", "YZ")
        ]
        perfect = [p for p in axis_aligned if p.score >= 1.0 - 1e-6]
        assert len(perfect) == 0, (
            f"Expected no perfect axis-aligned mirror for irregular tetrahedron; "
            f"found {[(p.label, p.score) for p in perfect]}"
        )

    def test_3fold_rotation_detected(self):
        """Regular tetrahedron has 3-fold rotational symmetry."""
        has_3fold = any(r.fold_order == 3 and r.score >= 0.5
                        for r in self.report.rotation_axes)
        assert has_3fold, (
            "Expected 3-fold rotation (score >= 0.5) for regular tetrahedron; "
            + str([(r.label, r.fold_order, r.score) for r in self.report.rotation_axes])
        )

    def test_rotation_axes_present(self):
        assert len(self.report.rotation_axes) > 0


# ---------------------------------------------------------------------------
# 5. Cylinder cage: continuous symmetry flag
# ---------------------------------------------------------------------------

class TestCylinderContinuousSymmetry:
    """Hexagonal prism approximating a cylinder:
    - Best rotation axis should have continuous=True (two equal transverse PCA eigenvalues).
    - n-fold score should be 1.0 for fold=6 (hexagonal symmetry).
    """

    def setup_method(self):
        self.cage = _cylinder_cage(n=6, radius=1.0, height=2.0)
        self.report = detect_symmetry(self.cage, tol=1e-3)

    def test_rotation_detected(self):
        assert len(self.report.rotation_axes) > 0

    def test_6fold_score_is_1(self):
        """Hexagonal prism: 6-fold rotation about Z-axis scores 1.0."""
        best = max(r.score for r in self.report.rotation_axes)
        assert best >= 1.0 - 1e-6, (
            f"Expected rotation score >= 1.0 for hexagonal prism; got {best}"
        )

    def test_continuous_flag_set(self):
        """Hexagonal prism has two equal transverse PCA eigenvalues -> continuous."""
        any_continuous = any(r.continuous for r in self.report.rotation_axes)
        assert any_continuous, (
            "Expected continuous=True for at least one axis of hexagonal prism "
            "(two equal transverse PCA eigenvalues); "
            + str([(r.label, r.continuous) for r in self.report.rotation_axes])
        )

    def test_mirror_planes_present(self):
        """Hexagonal prism has vertical mirror planes + 1 horizontal."""
        assert len(self.report.mirror_planes) > 0


# ---------------------------------------------------------------------------
# 6. Skewed cage: reduced score
# ---------------------------------------------------------------------------

class TestSkewedCube:
    """Cube with one vertex displaced in x, y, z unequally -> score < 1.0."""

    def setup_method(self):
        self.cage = _skewed_cube_cage(displacement=0.3)
        self.report = detect_symmetry(self.cage, tol=1e-4)

    def test_overall_score_less_than_1(self):
        assert self.report.overall_score < 1.0, (
            f"Expected overall score < 1.0 for skewed cube; got {self.report.overall_score}"
        )

    def test_no_perfect_mirror_plane(self):
        perfect = [p for p in self.report.mirror_planes if p.score >= 1.0 - 1e-6]
        assert len(perfect) == 0, (
            f"Expected no perfect mirror plane for skewed cube; "
            f"found {[(p.label, p.score) for p in perfect]}"
        )

    def test_no_perfect_rotation_axis(self):
        perfect = [r for r in self.report.rotation_axes if r.score >= 1.0 - 1e-6]
        assert len(perfect) == 0, (
            f"Expected no perfect rotation axis for skewed cube; "
            f"found {[(r.label, r.score) for r in perfect]}"
        )

    def test_score_quantifies_deviation(self):
        """overall_score is in (0, 1) -- some vertices still match under reflection."""
        assert 0.0 < self.report.overall_score < 1.0, (
            f"Score should be strictly between 0 and 1 for skewed cube; "
            f"got {self.report.overall_score}"
        )

    def test_deviation_per_axis_populated(self):
        assert len(self.report.deviation_per_axis) > 0
        for label, dev in self.report.deviation_per_axis.items():
            assert dev >= 0.0, f"Deviation for {label} is negative: {dev}"


# ---------------------------------------------------------------------------
# 7. Spherical symmetry (octahedron -- all PCA eigenvalues equal)
# ---------------------------------------------------------------------------

class TestSphericalSymmetry:
    """Regular octahedron inscribed in unit sphere:
    all 6 vertices equidistant from origin.
    PCA eigenvalues should be approximately equal -> spherical=True."""

    def _make_octahedron(self) -> SubDCage:
        verts = [
            [1.0, 0.0, 0.0], [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0], [0.0, -1.0, 0.0],
            [0.0, 0.0, 1.0], [0.0, 0.0, -1.0],
        ]
        faces = [
            [0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4],
            [0, 3, 5], [3, 1, 5], [1, 2, 5], [2, 0, 5],
        ]
        return SubDCage(vertices=verts, faces=faces)

    def test_spherical_flag(self):
        cage = self._make_octahedron()
        report = detect_symmetry(cage, tol=1e-3)
        assert report.spherical, (
            "Expected spherical=True for regular octahedron (equal PCA eigenvalues)"
        )

    def test_spherical_score_is_1(self):
        cage = self._make_octahedron()
        report = detect_symmetry(cage, tol=1e-3)
        assert report.spherical_score >= 1.0 - 1e-6, (
            f"Expected spherical_score=1.0 for octahedron; got {report.spherical_score}"
        )


# ---------------------------------------------------------------------------
# 8. Score threshold filtering
# ---------------------------------------------------------------------------

class TestScoreThreshold:
    def test_threshold_0_includes_all(self):
        cage = _cube_cage()
        report = detect_symmetry(cage, tol=1e-4, score_threshold=0.0)
        n_all = len(report.mirror_planes)
        assert n_all >= 3

    def test_threshold_1_filters_imperfect(self):
        cage = _skewed_cube_cage(0.3)
        report = detect_symmetry(cage, tol=1e-4, score_threshold=1.0)
        assert all(p.score >= 1.0 for p in report.mirror_planes)
        assert all(r.score >= 1.0 for r in report.rotation_axes)

    def test_threshold_reduces_count(self):
        cage = _cube_cage()
        report_low = detect_symmetry(cage, tol=1e-4, score_threshold=0.0)
        report_high = detect_symmetry(cage, tol=1e-4, score_threshold=1.1)
        assert len(report_low.mirror_planes) >= len(report_high.mirror_planes)


# ---------------------------------------------------------------------------
# 9. Robustness
# ---------------------------------------------------------------------------

class TestRobustness:
    def test_single_vertex_cage(self):
        cage = SubDCage(vertices=[[1.0, 2.0, 3.0]], faces=[])
        report = detect_symmetry(cage)
        assert isinstance(report, SymmetryReport)

    def test_two_vertex_cage(self):
        cage = SubDCage(vertices=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], faces=[])
        report = detect_symmetry(cage)
        assert isinstance(report, SymmetryReport)

    def test_collinear_vertices(self):
        """All vertices on a line -- degenerate covariance."""
        verts = [[float(i), 0.0, 0.0] for i in range(5)]
        cage = SubDCage(vertices=verts, faces=[])
        report = detect_symmetry(cage)
        assert isinstance(report, SymmetryReport)

    def test_large_coordinates(self):
        """Scale cube to large coordinates -- should still score 1.0."""
        cage = _cube_cage(side=1000.0)
        report = detect_symmetry(cage, tol=1e-1)
        assert report.overall_score >= 1.0 - 1e-6

    def test_score_in_range(self):
        cage = _skewed_cube_cage(0.3)
        report = detect_symmetry(cage)
        for p in report.mirror_planes:
            assert 0.0 <= p.score <= 1.0 + 1e-9
        for r in report.rotation_axes:
            assert 0.0 <= r.score <= 1.0 + 1e-9
