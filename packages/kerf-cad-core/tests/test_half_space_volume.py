"""Tests for BREP half-space volume intersection (BREP-VOLUME-OF-HALF-SPACE-INTERSECTION).

Depth-bar oracles (Mortenson §11.6):
  - Unit cube cut by z=0.5 → volume_above = 0.5, volume_below = 0.5
  - Unit sphere cut at equator z=0 → each half ≈ 4π/6 ≈ 2.0944
  - Cylinder r=1, h=2 cut at x=0 → each half = π ≈ 3.14159
"""

import math
import pytest

from kerf_cad_core.geom.brep import make_box, make_sphere, make_cylinder
from kerf_cad_core.geom.half_space_volume import (
    HalfSpaceVolumeReport,
    compute_half_space_volume,
    volume_above_plane,
    volume_below_plane,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def unit_cube():
    """Unit cube [0,1]³."""
    return make_box(origin=(0, 0, 0), size=(1, 1, 1))


@pytest.fixture
def unit_sphere():
    """Unit sphere centred at origin."""
    return make_sphere(center=(0, 0, 0), radius=1.0)


@pytest.fixture
def unit_cylinder():
    """Cylinder r=1, h=2 centred at origin, axis +z."""
    return make_cylinder(center=(0, 0, 0), axis=(0, 0, 1), radius=1.0, height=2.0)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Unit cube cut at z = 0.5
# ─────────────────────────────────────────────────────────────────────────────

class TestCubeMidCut:
    """Unit cube [0,1]³ cut by z=0.5 → above = below = 0.5 exactly."""

    def test_volume_above(self, unit_cube):
        v = volume_above_plane(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert abs(v - 0.5) < 0.01, f"Expected 0.5, got {v}"

    def test_volume_below(self, unit_cube):
        v = volume_below_plane(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert abs(v - 0.5) < 0.01, f"Expected 0.5, got {v}"

    def test_report_above(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert abs(r.volume_above - 0.5) < 0.01

    def test_report_below(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert abs(r.volume_below - 0.5) < 0.01

    def test_cut_area_is_unit_square(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert abs(r.plane_cut_area - 1.0) < 0.05, f"Expected cut area 1.0, got {r.plane_cut_area}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cube cut below the solid (plane z=-1 → everything above)
# ─────────────────────────────────────────────────────────────────────────────

class TestCubeFullAbove:
    """Plane below solid: volume_above = total volume = 1.0."""

    def test_all_above(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, -1], [0, 0, 1])
        assert abs(r.volume_above - 1.0) < 0.01

    def test_nothing_below(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, -1], [0, 0, 1])
        assert abs(r.volume_below) < 0.01

    def test_no_cut_area(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, -1], [0, 0, 1])
        assert r.plane_cut_area < 0.05, f"Expected ~0 cut area, got {r.plane_cut_area}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cube cut above the solid (plane z=2 → everything below)
# ─────────────────────────────────────────────────────────────────────────────

class TestCubeFullBelow:
    """Plane above solid: volume_below = total volume = 1.0."""

    def test_nothing_above(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 2], [0, 0, 1])
        assert abs(r.volume_above) < 0.01

    def test_all_below(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 2], [0, 0, 1])
        assert abs(r.volume_below - 1.0) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# 4. Unit sphere cut at equator (z=0)
# ─────────────────────────────────────────────────────────────────────────────

class TestSphereEquator:
    """Unit sphere cut at z=0 → each half = 4π/6 ≈ 2.0944."""

    _half = 4.0 * math.pi / 6.0  # ≈ 2.0944

    def test_volume_above(self, unit_sphere):
        v = volume_above_plane(unit_sphere, [0, 0, 0], [0, 0, 1])
        assert abs(v - self._half) < 0.05, f"Expected {self._half:.4f}, got {v:.4f}"

    def test_volume_below(self, unit_sphere):
        v = volume_below_plane(unit_sphere, [0, 0, 0], [0, 0, 1])
        assert abs(v - self._half) < 0.05, f"Expected {self._half:.4f}, got {v:.4f}"

    def test_sum_equals_full_sphere(self, unit_sphere):
        r = compute_half_space_volume(unit_sphere, [0, 0, 0], [0, 0, 1])
        expected_total = 4.0 * math.pi / 3.0  # ≈ 4.1888
        assert abs(r.total - expected_total) < 0.05


# ─────────────────────────────────────────────────────────────────────────────
# 5. Cylinder r=1, h=2 cut at x=0
# ─────────────────────────────────────────────────────────────────────────────

class TestCylinderHalfCut:
    """Cylinder r=1 h=2 cut at x=0 → each half = π ≈ 3.14159."""

    _half = math.pi  # ≈ 3.14159

    def test_volume_above(self, unit_cylinder):
        r = compute_half_space_volume(unit_cylinder, [0, 0, 0], [1, 0, 0])
        assert abs(r.volume_above - self._half) < 0.1, (
            f"Expected π≈{self._half:.5f}, got {r.volume_above:.5f}"
        )

    def test_volume_below(self, unit_cylinder):
        r = compute_half_space_volume(unit_cylinder, [0, 0, 0], [1, 0, 0])
        assert abs(r.volume_below - self._half) < 0.1, (
            f"Expected π≈{self._half:.5f}, got {r.volume_below:.5f}"
        )

    def test_total_volume(self, unit_cylinder):
        r = compute_half_space_volume(unit_cylinder, [0, 0, 0], [1, 0, 0])
        expected = 2.0 * math.pi  # r=1 h=2 → πr²h = 2π
        assert abs(r.total - expected) < 0.1, f"Expected 2π≈{expected:.4f}, got {r.total:.4f}"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Degenerate plane through corner (z=0, passes through bottom face)
# ─────────────────────────────────────────────────────────────────────────────

class TestDegeneratePlaneCorner:
    """Plane through the bottom face of cube (z=0): all above, nothing below."""

    def test_all_above_at_bottom_face(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0], [0, 0, 1])
        # The cube sits on z=0; the bottom face is exactly on the plane.
        # Volume above should be ≈ 1.0 (full cube above or at the plane).
        assert abs(r.volume_above - 1.0) < 0.05, f"Expected ~1.0, got {r.volume_above}"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Sum rule: above + below = total
# ─────────────────────────────────────────────────────────────────────────────

class TestSumRule:
    """above + below should equal total for all shapes and cut positions."""

    def test_cube_mid(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert abs(r.volume_above + r.volume_below - r.total) < 1e-8

    def test_cube_diagonal(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0.5, 0.5, 0.5], [1, 1, 1])
        assert abs(r.volume_above + r.volume_below - r.total) < 1e-6

    def test_sphere_equator(self, unit_sphere):
        r = compute_half_space_volume(unit_sphere, [0, 0, 0], [0, 0, 1])
        assert abs(r.volume_above + r.volume_below - r.total) < 1e-6

    def test_cylinder_x(self, unit_cylinder):
        r = compute_half_space_volume(unit_cylinder, [0, 0, 0], [1, 0, 0])
        assert abs(r.volume_above + r.volume_below - r.total) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# 8. HalfSpaceVolumeReport dataclass structure
# ─────────────────────────────────────────────────────────────────────────────

class TestReportDataclass:
    """Check dataclass fields and types."""

    def test_fields_present(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert isinstance(r, HalfSpaceVolumeReport)
        assert hasattr(r, "volume_above")
        assert hasattr(r, "volume_below")
        assert hasattr(r, "total")
        assert hasattr(r, "plane_cut_area")
        assert hasattr(r, "warnings")

    def test_warnings_is_list(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert isinstance(r.warnings, list)

    def test_volumes_are_floats(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert isinstance(r.volume_above, float)
        assert isinstance(r.volume_below, float)
        assert isinstance(r.total, float)
        assert isinstance(r.plane_cut_area, float)

    def test_total_equals_sum(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert abs(r.volume_above + r.volume_below - r.total) < 1e-8


# ─────────────────────────────────────────────────────────────────────────────
# 9. volume_above_plane / volume_below_plane convenience functions
# ─────────────────────────────────────────────────────────────────────────────

class TestConvenienceFunctions:
    """volume_above_plane and volume_below_plane wrappers."""

    def test_above_returns_float(self, unit_cube):
        v = volume_above_plane(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert isinstance(v, float)

    def test_below_returns_float(self, unit_cube):
        v = volume_below_plane(unit_cube, [0, 0, 0.5], [0, 0, 1])
        assert isinstance(v, float)

    def test_above_matches_report(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0.3], [0, 0, 1])
        v = volume_above_plane(unit_cube, [0, 0, 0.3], [0, 0, 1])
        assert abs(v - r.volume_above) < 1e-8

    def test_below_matches_report(self, unit_cube):
        r = compute_half_space_volume(unit_cube, [0, 0, 0.3], [0, 0, 1])
        v = volume_below_plane(unit_cube, [0, 0, 0.3], [0, 0, 1])
        assert abs(v - r.volume_below) < 1e-8


# ─────────────────────────────────────────────────────────────────────────────
# 10. Zero-normal guard
# ─────────────────────────────────────────────────────────────────────────────

class TestZeroNormalGuard:
    """Zero normal raises ValueError."""

    def test_raises_on_zero_normal(self, unit_cube):
        with pytest.raises(ValueError, match="plane_normal must be non-zero"):
            compute_half_space_volume(unit_cube, [0, 0, 0], [0, 0, 0])
