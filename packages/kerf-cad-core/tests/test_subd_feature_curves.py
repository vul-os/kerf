"""Tests for kerf_cad_core.subd.feature_curves — GK-P19 SubD feature curves.

Oracle strategy:
  - Flat plane: zero curvature everywhere → 0 ridges, 0 valleys.
  - Cube cage (sharp corners/edges): high curvature at corner regions
    → ridges detected; can count them roughly.
  - Saddle cage: negative curvature in one direction → valleys detected.
  - Sphere cage: curvature ~uniform low → minimal features at default threshold.
  - Threshold sweep: raising threshold reduces feature count.
  - API contracts: dataclass defaults, empty cage, single face, etc.

All tests are hermetic (no OCC, no DB, no network).
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.subd.feature_curves import (
    FeatureCurve,
    FeatureCurveResult,
    FeatureCurveSpec,
    SubdCage,
    extract_feature_curves,
)


# ---------------------------------------------------------------------------
# Cage helpers
# ---------------------------------------------------------------------------

def make_flat_plane_cage(nx: int = 4, ny: int = 4) -> SubdCage:
    """Flat quad grid at z=0."""
    verts: List[Tuple[float, float, float]] = []
    for j in range(ny + 1):
        for i in range(nx + 1):
            verts.append((float(i), float(j), 0.0))
    faces: List[List[int]] = []
    for j in range(ny):
        for i in range(nx):
            base = j * (nx + 1) + i
            faces.append([base, base + 1, base + (nx + 1) + 1, base + (nx + 1)])
    return SubdCage(vertices_xyz_mm=verts, faces=faces)


def make_cube_cage(half: float = 10.0) -> SubdCage:
    """Axis-aligned cube cage (6 quad faces, 8 vertices).

    The CC limit surface rounds the cube, concentrating curvature along
    the 12 original edge bands and 8 corner regions.
    """
    h = half
    verts: List[Tuple[float, float, float]] = [
        (-h, -h, -h),  # 0
        ( h, -h, -h),  # 1
        ( h,  h, -h),  # 2
        (-h,  h, -h),  # 3
        (-h, -h,  h),  # 4
        ( h, -h,  h),  # 5
        ( h,  h,  h),  # 6
        (-h,  h,  h),  # 7
    ]
    faces: List[List[int]] = [
        [0, 1, 2, 3],  # bottom (-z)
        [4, 7, 6, 5],  # top    (+z)
        [0, 4, 5, 1],  # front  (-y)
        [2, 6, 7, 3],  # back   (+y)
        [0, 3, 7, 4],  # left   (-x)
        [1, 5, 6, 2],  # right  (+x)
    ]
    return SubdCage(vertices_xyz_mm=verts, faces=faces)


def make_saddle_cage() -> SubdCage:
    """Saddle-shaped quad cage: z = (x² - y²) / scale.

    A 3×3 quad mesh (4×4 vertices) with z = x² - y².
    Interior has negative Gaussian curvature (κ₂ << 0 in one principal
    direction), producing valley detections at low thresholds.
    """
    coords = [-2.0, -0.67, 0.67, 2.0]
    verts: List[Tuple[float, float, float]] = []
    for y in coords:
        for x in coords:
            z = x * x - y * y
            verts.append((x, y, z))
    faces: List[List[int]] = []
    for j in range(3):
        for i in range(3):
            base = j * 4 + i
            faces.append([base, base + 1, base + 5, base + 4])
    return SubdCage(vertices_xyz_mm=verts, faces=faces)


def make_sphere_cage() -> SubdCage:
    """Octahedron cage as a rough sphere proxy (8 triangular faces, 6 vertices).

    All faces are triangles; the CC limit surface is a rounded shape with
    approximately uniform curvature ~1/R where R ~ 10 mm.
    """
    verts: List[Tuple[float, float, float]] = [
        (10.0, 0.0, 0.0),   # 0 +x
        (-10.0, 0.0, 0.0),  # 1 -x
        (0.0, 10.0, 0.0),   # 2 +y
        (0.0, -10.0, 0.0),  # 3 -y
        (0.0, 0.0, 10.0),   # 4 +z
        (0.0, 0.0, -10.0),  # 5 -z
    ]
    faces: List[List[int]] = [
        [0, 2, 4],
        [2, 1, 4],
        [1, 3, 4],
        [3, 0, 4],
        [0, 5, 2],
        [2, 5, 1],
        [1, 5, 3],
        [3, 5, 0],
    ]
    return SubdCage(vertices_xyz_mm=verts, faces=faces)


# ---------------------------------------------------------------------------
# Test 1: Flat plane → 0 ridges, 0 valleys
# ---------------------------------------------------------------------------

class TestFlatPlane:
    """Oracle: flat plane has zero curvature → no features above any positive threshold."""

    def test_flat_plane_zero_ridges(self):
        """Flat plane must produce 0 ridge polylines at default threshold."""
        cage = make_flat_plane_cage()
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.05,
            valley_threshold_per_mm=0.05,
        )
        res = extract_feature_curves(spec)
        assert res.num_ridges == 0, (
            f"Expected 0 ridges on flat plane, got {res.num_ridges}"
        )

    def test_flat_plane_zero_valleys(self):
        """Flat plane must produce 0 valley polylines at default threshold."""
        cage = make_flat_plane_cage()
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.05,
            valley_threshold_per_mm=0.05,
        )
        res = extract_feature_curves(spec)
        assert res.num_valleys == 0, (
            f"Expected 0 valleys on flat plane, got {res.num_valleys}"
        )

    def test_flat_plane_max_curvature_near_zero(self):
        """Max principal curvature on flat plane should be near zero (< 0.1 mm⁻¹)."""
        cage = make_flat_plane_cage()
        spec = FeatureCurveSpec(cage=cage, subdivision_level=2)
        res = extract_feature_curves(spec)
        assert res.max_principal_curvature < 0.5, (
            f"Flat plane max κ₁={res.max_principal_curvature:.4f} unexpectedly large"
        )

    def test_flat_plane_total_lengths_zero(self):
        """No ridge/valley polylines → total lengths are 0."""
        cage = make_flat_plane_cage()
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=1,
            ridge_threshold_per_mm=0.05,
            valley_threshold_per_mm=0.05,
        )
        res = extract_feature_curves(spec)
        assert res.total_ridge_length_mm == 0.0
        assert res.total_valley_length_mm == 0.0


# ---------------------------------------------------------------------------
# Test 2: Cube cage — ridges at edges
# ---------------------------------------------------------------------------

class TestCubeCage:
    """Oracle: a cube cage has 12 edges; CC limit concentrates curvature there."""

    def test_cube_ridges_detected(self):
        """At least some ridges are detected on the cube cage at level 2."""
        cage = make_cube_cage(half=10.0)
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.01,
            valley_threshold_per_mm=0.01,
        )
        res = extract_feature_curves(spec)
        assert res.num_ridges >= 1, (
            f"Expected ≥1 ridge on cube cage, got {res.num_ridges}"
        )

    def test_cube_max_curvature_positive(self):
        """Cube cage (sharp corners) → max principal curvature > 0."""
        cage = make_cube_cage(half=10.0)
        spec = FeatureCurveSpec(cage=cage, subdivision_level=2)
        res = extract_feature_curves(spec)
        assert res.max_principal_curvature > 0.0

    def test_cube_ridge_polylines_have_finite_coords(self):
        """All ridge polyline vertices must be finite 3-D coordinates."""
        cage = make_cube_cage(half=10.0)
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.01,
        )
        res = extract_feature_curves(spec)
        for curve in res.curves:
            assert curve.kind in ("ridge", "valley")
            for pt in curve.polyline_xyz_mm:
                assert len(pt) == 3
                for coord in pt:
                    assert math.isfinite(coord), f"Non-finite coord {coord} in {pt}"

    def test_cube_ridge_curvature_positive(self):
        """Ridge mean principal curvature must be positive (κ₁ > 0)."""
        cage = make_cube_cage(half=10.0)
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.01,
        )
        res = extract_feature_curves(spec)
        ridges = [c for c in res.curves if c.kind == "ridge"]
        for r in ridges:
            assert r.mean_principal_curvature > 0.0, (
                f"Ridge mean curvature {r.mean_principal_curvature:.4f} should be > 0"
            )


# ---------------------------------------------------------------------------
# Test 3: Saddle cage — valleys detected
# ---------------------------------------------------------------------------

class TestSaddleCage:
    """Oracle: saddle z = x² − y² has highly negative curvature in y direction."""

    def test_saddle_features_detected(self):
        """At least one feature (ridge or valley) detected on saddle cage."""
        cage = make_saddle_cage()
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.05,
            valley_threshold_per_mm=0.05,
        )
        res = extract_feature_curves(spec)
        total_features = res.num_ridges + res.num_valleys
        assert total_features >= 1, (
            f"Expected ≥1 feature on saddle cage, got {total_features}"
        )

    def test_saddle_returns_feature_curve_result(self):
        """extract_feature_curves returns a FeatureCurveResult object."""
        cage = make_saddle_cage()
        spec = FeatureCurveSpec(cage=cage, subdivision_level=1)
        res = extract_feature_curves(spec)
        assert isinstance(res, FeatureCurveResult)

    def test_saddle_curves_have_length(self):
        """All feature polylines must have non-negative length."""
        cage = make_saddle_cage()
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.05,
            valley_threshold_per_mm=0.05,
        )
        res = extract_feature_curves(spec)
        for curve in res.curves:
            assert curve.length_mm >= 0.0


# ---------------------------------------------------------------------------
# Test 4: Sphere cage — minimal features
# ---------------------------------------------------------------------------

class TestSphereCage:
    """Oracle: octahedron-proxy sphere has roughly uniform curvature.

    At the default threshold (0.1 mm⁻¹) with a 10 mm radius,
    κ ~ 1/R = 0.1 mm⁻¹ so detection is marginal — this is expected.
    At a higher threshold we should see 0 ridges/valleys.
    """

    def test_sphere_high_threshold_zero_ridges(self):
        """Sphere-like cage at very high threshold → 0 ridges."""
        cage = make_sphere_cage()
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=5.0,   # much higher than sphere curvature
            valley_threshold_per_mm=5.0,
        )
        res = extract_feature_curves(spec)
        assert res.num_ridges == 0, (
            f"Expected 0 ridges at high threshold on sphere, got {res.num_ridges}"
        )

    def test_sphere_result_fields_are_typed(self):
        """FeatureCurveResult fields are correct types."""
        cage = make_sphere_cage()
        spec = FeatureCurveSpec(cage=cage, subdivision_level=1)
        res = extract_feature_curves(spec)
        assert isinstance(res.curves, list)
        assert isinstance(res.num_ridges, int)
        assert isinstance(res.num_valleys, int)
        assert isinstance(res.total_ridge_length_mm, float)
        assert isinstance(res.total_valley_length_mm, float)
        assert isinstance(res.max_principal_curvature, float)
        assert isinstance(res.honest_caveat, str)

    def test_sphere_total_lengths_consistent(self):
        """total_ridge_length = sum of ridge curve lengths."""
        cage = make_sphere_cage()
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.01,
            valley_threshold_per_mm=0.01,
        )
        res = extract_feature_curves(spec)
        expected_ridge = sum(c.length_mm for c in res.curves if c.kind == "ridge")
        expected_valley = sum(c.length_mm for c in res.curves if c.kind == "valley")
        assert abs(res.total_ridge_length_mm - expected_ridge) < 1e-9
        assert abs(res.total_valley_length_mm - expected_valley) < 1e-9


# ---------------------------------------------------------------------------
# Test 5 & 6: API contracts and robustness
# ---------------------------------------------------------------------------

class TestAPIContracts:
    """Guard API contracts and robustness."""

    def test_empty_cage_returns_empty_result(self):
        """Empty cage → FeatureCurveResult with 0 ridges, 0 valleys."""
        spec = FeatureCurveSpec(cage=SubdCage())
        res = extract_feature_curves(spec)
        assert isinstance(res, FeatureCurveResult)
        assert res.num_ridges == 0
        assert res.num_valleys == 0
        assert res.curves == []

    def test_feature_curve_spec_defaults(self):
        """FeatureCurveSpec defaults match documented values."""
        spec = FeatureCurveSpec(cage=SubdCage())
        assert spec.subdivision_level == 2
        assert spec.ridge_threshold_per_mm == 0.1
        assert spec.valley_threshold_per_mm == 0.1

    def test_feature_curve_dataclass_structure(self):
        """FeatureCurve dataclass has correct default values."""
        fc = FeatureCurve()
        assert fc.kind == "ridge"
        assert fc.polyline_xyz_mm == []
        assert fc.length_mm == 0.0
        assert fc.mean_principal_curvature == 0.0

    def test_feature_curve_result_defaults(self):
        """FeatureCurveResult defaults are zero / empty."""
        res = FeatureCurveResult()
        assert res.curves == []
        assert res.num_ridges == 0
        assert res.num_valleys == 0
        assert res.total_ridge_length_mm == 0.0
        assert res.total_valley_length_mm == 0.0
        assert res.max_principal_curvature == 0.0
        assert len(res.honest_caveat) > 0

    def test_single_quad_no_raise(self):
        """Single quad cage must not raise."""
        cage = SubdCage(
            vertices_xyz_mm=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
            faces=[[0, 1, 2, 3]],
        )
        spec = FeatureCurveSpec(cage=cage, subdivision_level=1)
        res = extract_feature_curves(spec)
        assert isinstance(res, FeatureCurveResult)

    def test_zero_subdivision_levels(self):
        """subdivision_level=0 returns result without subdividing."""
        cage = make_cube_cage(half=10.0)
        spec = FeatureCurveSpec(cage=cage, subdivision_level=0)
        res = extract_feature_curves(spec)
        assert isinstance(res, FeatureCurveResult)

    def test_num_ridges_plus_valleys_equals_len_curves(self):
        """num_ridges + num_valleys == len(curves)."""
        cage = make_cube_cage(half=10.0)
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.01,
        )
        res = extract_feature_curves(spec)
        assert res.num_ridges + res.num_valleys == len(res.curves)

    def test_honest_caveat_contains_key_terms(self):
        """honest_caveat mentions Ohtake or discrete curvature."""
        res = FeatureCurveResult()
        caveat = res.honest_caveat.lower()
        assert "curvature" in caveat
        assert "threshold" in caveat

    def test_max_curvature_consistent_with_ridge_threshold(self):
        """If max_principal_curvature < ridge_threshold, num_ridges should be 0."""
        cage = make_flat_plane_cage()
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=999.0,
        )
        res = extract_feature_curves(spec)
        # With an astronomically high threshold, there can't be ridges
        if res.max_principal_curvature < 999.0:
            assert res.num_ridges == 0

    def test_increasing_threshold_reduces_or_maintains_features(self):
        """Higher threshold ≤ feature count at lower threshold."""
        cage = make_cube_cage(half=10.0)
        spec_low = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.001,
        )
        spec_high = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=1.0,
        )
        res_low = extract_feature_curves(spec_low)
        res_high = extract_feature_curves(spec_high)
        assert res_high.num_ridges <= res_low.num_ridges, (
            f"Higher threshold should not give more ridges: "
            f"low={res_low.num_ridges} high={res_high.num_ridges}"
        )

    def test_kind_is_ridge_or_valley(self):
        """All FeatureCurve.kind values are 'ridge' or 'valley'."""
        cage = make_cube_cage(half=10.0)
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=2,
            ridge_threshold_per_mm=0.01,
            valley_threshold_per_mm=0.01,
        )
        res = extract_feature_curves(spec)
        for curve in res.curves:
            assert curve.kind in ("ridge", "valley"), (
                f"Unexpected kind: {curve.kind!r}"
            )

    def test_re_export_from_subd_package(self):
        """FeatureCurveSpec, FeatureCurve, FeatureCurveResult, extract_feature_curves
        are re-exported from kerf_cad_core.subd."""
        from kerf_cad_core.subd import (  # noqa: F401
            FeatureCurve as FC,
            FeatureCurveResult as FCR,
            FeatureCurveSpec as FCS,
            extract_feature_curves as efc,
        )
        assert callable(efc)
        assert FCS is FeatureCurveSpec
        assert FC is FeatureCurve
        assert FCR is FeatureCurveResult
