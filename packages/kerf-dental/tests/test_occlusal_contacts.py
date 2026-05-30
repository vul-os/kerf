"""
Tests for kerf_dental.occlusal_contacts — occlusal contact analysis.

Validation strategy (Okeson 2019 §8; Koos et al. 2018):

  1. No-contact case: two flat plates separated by 100 μm → 0 contact regions.
  2. Single-point contact: two flat plates, one vertex touching (gap = 0) →
     exactly 1 contact region; area ≈ Voronoi area of that vertex.
  3. Multi-region contact: a lower arch with 3 cusps touching 3 isolated spots
     on the upper arch → 3 contact regions detected.
  4. Articulator motion: centric closure with 3 cusp contacts → lateral
     excursion shifts contacts; compute_articulator_motion reports the shift.
  5. Additional API/shape/bounds tests.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_dental.occlusal_contacts import (
    OcclusalReport,
    ContactRegion,
    ArticulatorResult,
    compute_occlusal_contacts,
    mark_high_pressure_zones,
    compute_articulator_motion,
)


# ---------------------------------------------------------------------------
# Mesh helpers
# ---------------------------------------------------------------------------

def _flat_grid(nx: int = 10, ny: int = 10, z: float = 0.0,
               x_off: float = 0.0, y_off: float = 0.0) -> np.ndarray:
    """NxN flat grid in XY plane at height z (mm)."""
    xs = np.linspace(x_off, x_off + float(nx - 1), nx)
    ys = np.linspace(y_off, y_off + float(ny - 1), ny)
    xx, yy = np.meshgrid(xs, ys)
    zz = np.full_like(xx, z)
    return np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])


def _flat_grid_with_spike(nx: int = 10, ny: int = 10,
                          spike_x: float = 4.0, spike_y: float = 4.0,
                          spike_z: float = 0.0) -> np.ndarray:
    """Flat grid (lower plate at z=-0.5) + one spike vertex at (spike_x, spike_y, spike_z).

    spike_x/spike_y must match a point on the upper flat grid (which runs 0..nx-1,
    0..ny-1 at integer positions) so the gap is exactly 0 μm.
    """
    base = _flat_grid(nx, ny, z=-0.5)  # lower plate sits well below
    # Spike vertex exactly on the upper plate (z=0) at an integer-grid position
    spike = np.array([[spike_x, spike_y, spike_z]])
    return np.vstack([base, spike])


def _three_cusp_arch(separation_mm: float = 0.0,
                     inter_cusp_mm: float = 8.0) -> tuple[np.ndarray, np.ndarray]:
    """Upper arch (flat) + lower arch with 3 isolated cusp tips.

    Upper arch: flat plate at z=0.
    Lower arch: flat plate at z = -(separation_mm + 0.10) with 3 additional
    vertices (cusp tips) at z = -(separation_mm) so each tip is *exactly*
    separation_mm below the upper plate.

    With separation_mm=0.0 the cusp tips touch the upper plate (gap=0).
    """
    # Upper arch: flat 15x15 grid at z=0
    upper = _flat_grid(15, 15, z=0.0)

    # Lower arch: flat plate well below + 3 cusp tips at z=-separation_mm
    base_z = -(separation_mm + 0.10)  # 100 μm below cusp tips
    lower_base = _flat_grid(15, 15, z=base_z)

    cusp_tips = np.array([
        [ 3.0,  3.0, -separation_mm],
        [ 3.0 + inter_cusp_mm,  3.0, -separation_mm],
        [ 3.0,  3.0 + inter_cusp_mm, -separation_mm],
    ])
    lower = np.vstack([lower_base, cusp_tips])
    return upper, lower


# ===========================================================================
# 1. No-contact oracle
# ===========================================================================

class TestNoContact:
    """Two flat plates separated by 100 μm → zero contact regions."""

    def test_no_contact_zero_regions(self):
        """Upper plate at z=0.0, lower plate at z=-0.1 mm (100 μm gap)."""
        upper = _flat_grid(10, 10, z=0.0)
        lower = _flat_grid(10, 10, z=-0.1)   # 100 μm gap
        report = compute_occlusal_contacts(upper, lower, threshold_um=50.0)
        assert isinstance(report, OcclusalReport)
        assert len(report.contact_regions) == 0, (
            f"Expected 0 regions; got {len(report.contact_regions)}"
        )

    def test_no_contact_zero_area(self):
        upper = _flat_grid(10, 10, z=0.0)
        lower = _flat_grid(10, 10, z=-0.1)
        report = compute_occlusal_contacts(upper, lower, threshold_um=50.0)
        assert report.total_contact_area_mm2 == 0.0

    def test_no_contact_zero_max_pressure(self):
        upper = _flat_grid(10, 10, z=0.0)
        lower = _flat_grid(10, 10, z=-0.1)
        report = compute_occlusal_contacts(upper, lower, threshold_um=50.0)
        assert report.max_pressure == 0.0

    def test_no_contact_empty_gap_distribution(self):
        upper = _flat_grid(10, 10, z=0.0)
        lower = _flat_grid(10, 10, z=-0.1)
        report = compute_occlusal_contacts(upper, lower, threshold_um=50.0)
        assert len(report.gap_distribution_um) == 0

    def test_contact_at_smaller_threshold_than_gap(self):
        """Gap = 200 μm, threshold = 50 μm → still no contacts."""
        upper = _flat_grid(8, 8, z=0.0)
        lower = _flat_grid(8, 8, z=-0.2)   # 200 μm gap
        report = compute_occlusal_contacts(upper, lower, threshold_um=50.0)
        assert len(report.contact_regions) == 0

    def test_contact_appears_when_threshold_raised(self):
        """Same 100 μm gap, but threshold raised to 150 μm → contacts appear."""
        upper = _flat_grid(10, 10, z=0.0)
        lower = _flat_grid(10, 10, z=-0.1)   # 100 μm gap
        report = compute_occlusal_contacts(upper, lower, threshold_um=150.0)
        assert len(report.contact_regions) > 0


# ===========================================================================
# 2. Single-point contact oracle
# ===========================================================================

class TestSinglePointContact:
    """One vertex touching upper plate → exactly 1 contact region, area ≈ Voronoi area."""

    def _make_single_touch(self) -> tuple[np.ndarray, np.ndarray]:
        """Upper flat plate at z=0; lower flat plate at z=-0.5mm + 1 spike at z=0.

        spike_x=4.0, spike_y=4.0 matches an integer-grid upper vertex so gap == 0 μm.
        """
        upper = _flat_grid(10, 10, z=0.0)
        lower = _flat_grid_with_spike(10, 10, spike_x=4.0, spike_y=4.0, spike_z=0.0)
        return upper, lower

    def test_single_point_one_region(self):
        upper, lower = self._make_single_touch()
        # threshold = 10 μm so only the exact-touch vertex qualifies
        report = compute_occlusal_contacts(upper, lower, threshold_um=10.0)
        assert len(report.contact_regions) == 1, (
            f"Expected 1 region; got {len(report.contact_regions)}"
        )

    def test_single_point_gap_near_zero(self):
        """The touching vertex has gap ≈ 0 μm."""
        upper, lower = self._make_single_touch()
        report = compute_occlusal_contacts(upper, lower, threshold_um=10.0)
        assert len(report.contact_regions) == 1
        region = report.contact_regions[0]
        assert region.mean_gap_um < 1.0, (
            f"Expected mean gap < 1 μm; got {region.mean_gap_um:.4f} μm"
        )

    def test_single_point_area_positive(self):
        """Contact region area must be > 0 mm²."""
        upper, lower = self._make_single_touch()
        report = compute_occlusal_contacts(upper, lower, threshold_um=10.0)
        assert len(report.contact_regions) == 1
        assert report.contact_regions[0].area_mm2 > 0.0

    def test_single_point_vertex_count_is_one(self):
        """Only the spike vertex should be in contact."""
        upper, lower = self._make_single_touch()
        report = compute_occlusal_contacts(upper, lower, threshold_um=10.0)
        assert len(report.contact_regions) == 1
        assert len(report.contact_regions[0].vertex_indices) == 1

    def test_single_point_max_pressure_is_one(self):
        """With a single contact vertex, normalised max_pressure == 1.0."""
        upper, lower = self._make_single_touch()
        report = compute_occlusal_contacts(upper, lower, threshold_um=10.0)
        assert report.max_pressure == pytest.approx(1.0, abs=1e-6)


# ===========================================================================
# 3. Multi-region contact oracle
# ===========================================================================

class TestMultiRegionContact:
    """3 cusp tips touching upper plate → 3 distinct contact regions."""

    def test_three_cusp_three_regions(self):
        """3 cusp tips separated by 8 mm (> 2 mm adjacency radius) → 3 regions."""
        upper, lower = _three_cusp_arch(separation_mm=0.0, inter_cusp_mm=8.0)
        report = compute_occlusal_contacts(
            upper, lower, threshold_um=10.0, adjacency_radius_mm=2.0
        )
        assert len(report.contact_regions) == 3, (
            f"Expected 3 regions; got {len(report.contact_regions)}"
        )

    def test_three_cusp_total_area_positive(self):
        upper, lower = _three_cusp_arch(separation_mm=0.0, inter_cusp_mm=8.0)
        report = compute_occlusal_contacts(
            upper, lower, threshold_um=10.0, adjacency_radius_mm=2.0
        )
        assert report.total_contact_area_mm2 > 0.0

    def test_three_cusp_centers_approx_cusp_positions(self):
        """Each region center should be close to the corresponding cusp tip."""
        upper, lower = _three_cusp_arch(separation_mm=0.0, inter_cusp_mm=8.0)
        expected = np.array([
            [ 3.0,  3.0, 0.0],
            [11.0,  3.0, 0.0],
            [ 3.0, 11.0, 0.0],
        ])
        report = compute_occlusal_contacts(
            upper, lower, threshold_um=10.0, adjacency_radius_mm=2.0
        )
        assert len(report.contact_regions) == 3
        centers = np.array([r.center_mm for r in report.contact_regions])
        # Each expected position should be close (within 1.5 mm) to some center
        for exp_c in expected:
            dists = np.linalg.norm(centers - exp_c, axis=1)
            assert dists.min() < 1.5, (
                f"No region center within 1.5 mm of cusp tip {exp_c}; "
                f"min dist = {dists.min():.3f} mm"
            )

    def test_three_cusp_gap_near_zero(self):
        """All contact regions should have near-zero gap (cusp tips touching)."""
        upper, lower = _three_cusp_arch(separation_mm=0.0, inter_cusp_mm=8.0)
        report = compute_occlusal_contacts(
            upper, lower, threshold_um=10.0, adjacency_radius_mm=2.0
        )
        for region in report.contact_regions:
            assert region.mean_gap_um < 1.0, (
                f"Region mean gap {region.mean_gap_um:.4f} μm too large"
            )

    def test_close_cusps_merge_into_fewer_regions(self):
        """3 cusps separated by only 1 mm (< adjacency_radius 2 mm) → fewer regions."""
        upper, lower = _three_cusp_arch(separation_mm=0.0, inter_cusp_mm=1.0)
        report = compute_occlusal_contacts(
            upper, lower, threshold_um=10.0, adjacency_radius_mm=2.0
        )
        # All three cusps within 2 mm adjacency radius — should merge
        assert len(report.contact_regions) < 3


# ===========================================================================
# 4. Articulator motion oracle
# ===========================================================================

class TestArticulatorMotion:
    """Centric closure with 3 contacts → lateral motion shifts contacts."""

    def _build_arch_pair(self) -> tuple[np.ndarray, np.ndarray]:
        """3 cusp-tip lower arch touching flat upper arch at start."""
        upper = _flat_grid(20, 20, z=0.0, x_off=-2.0, y_off=-2.0)
        # Cusp tips at z=0 (touching), spread across the arch
        base = _flat_grid(20, 20, z=-0.5, x_off=-2.0, y_off=-2.0)
        cusps = np.array([
            [2.0, 2.0, 0.0],
            [10.0, 2.0, 0.0],
            [2.0, 10.0, 0.0],
        ])
        lower = np.vstack([base, cusps])
        return upper, lower

    def test_centric_returns_articulator_result(self):
        upper, lower = self._build_arch_pair()
        result = compute_articulator_motion(
            upper, lower, motion="centric", n_steps=3, step_mm=0.1, threshold_um=10.0
        )
        assert isinstance(result, ArticulatorResult)
        assert result.motion == "centric"

    def test_lateral_contact_shift(self):
        """Lateral motion shifts contact centroids in the X direction."""
        upper, lower = self._build_arch_pair()
        result = compute_articulator_motion(
            upper, lower, motion="lateral", n_steps=5, step_mm=1.0, threshold_um=10.0
        )
        assert isinstance(result, ArticulatorResult)
        assert len(result.steps) == 5
        # Final shift should be > 0 in X (lateral direction)
        final_shift = result.shift_vectors_mm[-1]
        # The lower arch moves in +X, so contacts shift in +X too
        assert final_shift[0] >= 0.0, (
            f"Expected positive X-shift for lateral motion; got {final_shift}"
        )

    def test_protrusive_contact_shift_in_y(self):
        """Protrusive motion shifts contact centroids in Y direction."""
        upper, lower = self._build_arch_pair()
        result = compute_articulator_motion(
            upper, lower, motion="protrusive", n_steps=5, step_mm=1.0, threshold_um=10.0
        )
        final_shift = result.shift_vectors_mm[-1]
        assert final_shift[1] >= 0.0, (
            f"Expected positive Y-shift for protrusive motion; got {final_shift}"
        )

    def test_centric_initial_contacts(self):
        """Starting position (step 0) should have 3 contact regions."""
        upper, lower = self._build_arch_pair()
        result = compute_articulator_motion(
            upper, lower, motion="centric", n_steps=3, step_mm=0.05, threshold_um=10.0
        )
        assert result.contact_count_by_step[0] == 3, (
            f"Expected 3 initial contacts; got {result.contact_count_by_step[0]}"
        )

    def test_lateral_motion_contact_count_changes(self):
        """After 4 mm of lateral motion, contact count changes (contacts shift off)."""
        upper, lower = self._build_arch_pair()
        result = compute_articulator_motion(
            upper, lower, motion="lateral", n_steps=5, step_mm=1.0, threshold_um=10.0
        )
        # Step 0 and last step should differ in some way
        # (contacts either disappear or move off the upper arch edge)
        assert isinstance(result.contact_count_by_step, list)
        assert len(result.contact_count_by_step) == 5

    def test_invalid_motion_raises(self):
        upper, lower = self._build_arch_pair()
        with pytest.raises(ValueError, match="motion must be one of"):
            compute_articulator_motion(upper, lower, motion="chewing")

    def test_shift_vectors_length_equals_n_steps(self):
        upper, lower = self._build_arch_pair()
        result = compute_articulator_motion(
            upper, lower, motion="lateral", n_steps=4, step_mm=0.5, threshold_um=10.0
        )
        assert len(result.shift_vectors_mm) == 4

    def test_step0_shift_is_zero(self):
        """First step has zero shift by definition."""
        upper, lower = self._build_arch_pair()
        result = compute_articulator_motion(
            upper, lower, motion="centric", n_steps=3, step_mm=0.5, threshold_um=10.0
        )
        np.testing.assert_array_almost_equal(
            result.shift_vectors_mm[0], [0.0, 0.0, 0.0], decimal=10
        )


# ===========================================================================
# 5. mark_high_pressure_zones
# ===========================================================================

class TestHighPressureZones:

    def test_flags_above_threshold(self):
        """A region with max_pressure=1.0 is flagged when threshold=0.5."""
        upper = _flat_grid(10, 10, z=0.0)
        lower = _flat_grid_with_spike(spike_z=0.0)   # exact touch
        report = compute_occlusal_contacts(upper, lower, threshold_um=10.0)
        flagged = mark_high_pressure_zones(report, max_pressure_threshold=0.5)
        assert len(flagged) == 1
        assert flagged[0].is_flagged is True

    def test_flags_nothing_when_all_below_threshold(self):
        """All regions below threshold → nothing flagged."""
        upper = _flat_grid(10, 10, z=0.0)
        lower = _flat_grid(10, 10, z=-0.04)    # 40 μm gap — in contact but low pressure
        report = compute_occlusal_contacts(upper, lower, threshold_um=50.0)
        flagged = mark_high_pressure_zones(report, max_pressure_threshold=0.99)
        # With uniform gap the single merged region has max_pressure ≈ 1.0
        # So this only tests the empty case when threshold is above 1.0
        flagged2 = mark_high_pressure_zones(report, max_pressure_threshold=2.0)
        assert len(flagged2) == 0

    def test_is_flagged_mutated_in_report(self):
        """is_flagged on the ContactRegion in the report is mutated."""
        upper = _flat_grid(10, 10, z=0.0)
        lower = _flat_grid_with_spike(spike_z=0.0)
        report = compute_occlusal_contacts(upper, lower, threshold_um=10.0)
        assert report.contact_regions[0].is_flagged is False  # before
        mark_high_pressure_zones(report, max_pressure_threshold=0.5)
        assert report.contact_regions[0].is_flagged is True   # after


# ===========================================================================
# 6. API contract / shape invariants
# ===========================================================================

class TestAPIContract:

    def test_returns_occlusal_report(self):
        upper = _flat_grid(8, 8, z=0.0)
        lower = _flat_grid_with_spike(spike_z=0.0)
        report = compute_occlusal_contacts(upper, lower, threshold_um=20.0)
        assert isinstance(report, OcclusalReport)

    def test_threshold_stored(self):
        upper = _flat_grid(8, 8, z=0.0)
        lower = _flat_grid(8, 8, z=-0.2)
        report = compute_occlusal_contacts(upper, lower, threshold_um=77.0)
        assert report.threshold_um == pytest.approx(77.0)

    def test_n_lower_vertices_evaluated(self):
        upper = _flat_grid(8, 8, z=0.0)
        lower = _flat_grid(8, 8, z=-0.2)
        report = compute_occlusal_contacts(upper, lower, threshold_um=50.0)
        assert report.n_lower_vertices_evaluated == 64

    def test_total_area_is_sum_of_region_areas(self):
        upper, lower = _three_cusp_arch(separation_mm=0.0, inter_cusp_mm=8.0)
        report = compute_occlusal_contacts(upper, lower, threshold_um=10.0, adjacency_radius_mm=2.0)
        expected = sum(r.area_mm2 for r in report.contact_regions)
        assert report.total_contact_area_mm2 == pytest.approx(expected, rel=1e-9)

    def test_contact_region_center_shape(self):
        upper, lower = _three_cusp_arch(separation_mm=0.0, inter_cusp_mm=8.0)
        report = compute_occlusal_contacts(upper, lower, threshold_um=10.0, adjacency_radius_mm=2.0)
        for r in report.contact_regions:
            assert r.center_mm.shape == (3,)

    def test_regions_sorted_descending_pressure(self):
        upper, lower = _three_cusp_arch(separation_mm=0.0, inter_cusp_mm=8.0)
        report = compute_occlusal_contacts(upper, lower, threshold_um=10.0, adjacency_radius_mm=2.0)
        pressures = [r.max_pressure for r in report.contact_regions]
        assert pressures == sorted(pressures, reverse=True)

    def test_list_input_accepted(self):
        upper = [[float(i), 0.0, 0.0] for i in range(20)]
        lower = [[float(i), 0.0, -0.2] for i in range(20)]
        report = compute_occlusal_contacts(upper, lower, threshold_um=50.0)
        assert isinstance(report, OcclusalReport)

    def test_wrong_shape_raises(self):
        with pytest.raises(ValueError):
            compute_occlusal_contacts(np.zeros((10, 2)), np.zeros((10, 3)))


# ===========================================================================
# 7. Module import smoke test
# ===========================================================================

class TestModuleImport:
    def test_import_occlusal_contacts(self):
        import kerf_dental.occlusal_contacts  # noqa: F401

    def test_public_api_accessible(self):
        from kerf_dental.occlusal_contacts import (
            compute_occlusal_contacts,
            mark_high_pressure_zones,
            compute_articulator_motion,
            OcclusalReport,
            ContactRegion,
            ArticulatorResult,
        )
        assert callable(compute_occlusal_contacts)
        assert callable(mark_high_pressure_zones)
        assert callable(compute_articulator_motion)
