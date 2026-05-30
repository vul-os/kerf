"""
Tests for kerf_dental.implant_planning — T-implant-planning

Verifies the four DoD oracles:
  1. Bone density classification: HU > 1250 → D1; HU 850-1250 → D2; etc.
  2. Nerve clearance violation: trajectory within 1 mm → flagged; ≥ 2 mm → OK.
  3. Sizing recommendation: tooth 16 → ≈ 4.0 × 10 mm (posterior maxillary).
  4. Axial deviation: trajectory at 15° from prosthetic axis → flagged > 10°.

References: Misch 2014 Contemporary Implant Dentistry §22; EAO Clinical Guidelines.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# sys.path bootstrap
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------

from kerf_dental.implant_planning import (
    BoneDensity,
    ImplantPlan,
    ImplantMetrics,
    classify_bone_density,
    compute_implant_metrics,
    recommend_implant_dimensions,
    generate_surgical_guide_geometry,
    _fdi_to_region,
    _sample_hu_along_trajectory,
    _min_distance_point_to_curve,
)


# ---------------------------------------------------------------------------
# Helper: build a synthetic CBCT volume filled with uniform HU
# ---------------------------------------------------------------------------

def _uniform_volume(hu: float, shape: tuple[int, int, int] = (50, 50, 50)) -> np.ndarray:
    """Return a volume uniformly filled with *hu* HU."""
    return np.full(shape, hu, dtype=float)


def _make_plan(
    entry=(0.0, 0.0, 0.0),
    exit_=(0.0, 0.0, 10.0),
    tooth="16",
    prosthetic_axis=None,
) -> ImplantPlan:
    return ImplantPlan(
        entry_point=entry,
        exit_point=exit_,
        diameter_mm=4.0,
        length_mm=10.0,
        tooth_position=tooth,
        prosthetic_axis=prosthetic_axis,
    )


# ===========================================================================
# DoD Oracle 1 — Bone density classification (Misch 2014 §22)
# ===========================================================================

class TestBoneDensityClassification:
    """
    HU thresholds: D1 > 1250, D2 850-1250, D3 350-849, D4 150-349, D4- < 150.
    Source: Misch CE (2014) Contemporary Implant Dentistry §22 Table 22-1.
    """

    def test_d1_above_1250(self):
        """HU > 1250 must classify as D1 (densest cortical bone)."""
        assert classify_bone_density(1300.0) == BoneDensity.D1

    def test_d1_at_boundary_1251(self):
        assert classify_bone_density(1251.0) == BoneDensity.D1

    def test_d2_at_1250(self):
        """HU = 1250 is D2 (D1 is strictly > 1250)."""
        assert classify_bone_density(1250.0) == BoneDensity.D2

    def test_d2_in_range(self):
        """HU 850-1250 → D2."""
        assert classify_bone_density(1000.0) == BoneDensity.D2

    def test_d2_at_850(self):
        assert classify_bone_density(850.0) == BoneDensity.D2

    def test_d3_just_below_850(self):
        assert classify_bone_density(849.0) == BoneDensity.D3

    def test_d3_in_range(self):
        """HU 350-849 → D3."""
        assert classify_bone_density(600.0) == BoneDensity.D3

    def test_d3_at_350(self):
        assert classify_bone_density(350.0) == BoneDensity.D3

    def test_d4_in_range(self):
        """HU 150-349 → D4."""
        assert classify_bone_density(250.0) == BoneDensity.D4

    def test_d4_at_150(self):
        assert classify_bone_density(150.0) == BoneDensity.D4

    def test_d4_sub_below_150(self):
        """HU < 150 → D4- (sub-threshold)."""
        result = classify_bone_density(100.0)
        assert result == "D4-"

    def test_d4_sub_zero(self):
        result = classify_bone_density(0.0)
        assert result == "D4-"

    def test_negative_hu_sub_threshold(self):
        """Negative HU (air) → D4-."""
        assert classify_bone_density(-100.0) == "D4-"

    # ----- Integration with compute_implant_metrics -----

    def test_compute_metrics_d1_volume(self):
        """Uniform D1 volume (1300 HU) → classification D1 in metrics."""
        vol = _uniform_volume(1300.0)
        plan = _make_plan()
        metrics = compute_implant_metrics(plan, vol, voxel_spacing_mm=(0.2, 0.2, 0.2))
        assert metrics.bone_density_classification == BoneDensity.D1

    def test_compute_metrics_d2_volume(self):
        """Uniform D2 volume (1000 HU) → classification D2."""
        vol = _uniform_volume(1000.0)
        plan = _make_plan()
        metrics = compute_implant_metrics(plan, vol, voxel_spacing_mm=(0.2, 0.2, 0.2))
        assert metrics.bone_density_classification == BoneDensity.D2

    def test_compute_metrics_d3_volume(self):
        """Uniform D3 volume (600 HU) → classification D3."""
        vol = _uniform_volume(600.0)
        plan = _make_plan()
        metrics = compute_implant_metrics(plan, vol, voxel_spacing_mm=(0.2, 0.2, 0.2))
        assert metrics.bone_density_classification == BoneDensity.D3

    def test_compute_metrics_sub_threshold_flagged(self):
        """D4- volume → violation present in recommended_violations."""
        vol = _uniform_volume(80.0)
        plan = _make_plan()
        metrics = compute_implant_metrics(plan, vol, voxel_spacing_mm=(0.2, 0.2, 0.2))
        assert metrics.bone_density_classification == "D4-"
        assert any("sub-threshold" in v.lower() or "150" in v
                   for v in metrics.recommended_violations)

    def test_mean_hu_matches_uniform_volume(self):
        """mean_hu should equal the uniform fill value for in-bounds samples.

        Uses a large volume (80×80×80 at 0.5mm) so the 10mm trajectory stays
        well within bounds and all 50 samples hit the fill value.
        """
        fill = 750.0
        # 80 voxels × 0.5mm = 40mm cube; trajectory (0..10mm) fully in-bounds
        vol = _uniform_volume(fill, shape=(80, 80, 80))
        plan = _make_plan()
        metrics = compute_implant_metrics(plan, vol, voxel_spacing_mm=(0.5, 0.5, 0.5))
        assert metrics.mean_hu == pytest.approx(fill, abs=1.0)


# ===========================================================================
# DoD Oracle 2 — Nerve clearance violation
# ===========================================================================

class TestNerveClearance:
    """
    EAO: mandibular nerve clearance must be ≥ 2 mm.
    Trajectory within 1 mm → flagged; ≥ 2 mm → OK.
    """

    _VOL = _uniform_volume(1000.0)  # D2 bone, neutral
    _SPACING = (0.2, 0.2, 0.2)

    def _nerve_at_distance(self, dist_mm: float) -> np.ndarray:
        """
        Build a nerve curve parallel to the trajectory (along z-axis from z=0..10),
        offset by *dist_mm* in the x-direction.
        """
        zs = np.linspace(0.0, 10.0, 20)
        pts = np.column_stack([
            np.full(20, dist_mm),
            np.zeros(20),
            zs,
        ])
        return pts

    def test_nerve_within_1mm_flagged(self):
        """Trajectory passing within 1 mm of nerve → violation flagged (DoD)."""
        plan = _make_plan()
        nerve = self._nerve_at_distance(0.8)
        metrics = compute_implant_metrics(
            plan, self._VOL,
            voxel_spacing_mm=self._SPACING,
            mandibular_nerve_curve=nerve,
        )
        assert metrics.nerve_clearance_mm is not None
        assert metrics.nerve_clearance_mm < 2.0
        assert any("nerve" in v.lower() for v in metrics.recommended_violations)

    def test_nerve_at_1mm_flagged(self):
        """Nerve at exactly 1.0 mm → still flagged (< 2 mm threshold)."""
        plan = _make_plan()
        nerve = self._nerve_at_distance(1.0)
        metrics = compute_implant_metrics(
            plan, self._VOL,
            voxel_spacing_mm=self._SPACING,
            mandibular_nerve_curve=nerve,
        )
        assert any("nerve" in v.lower() for v in metrics.recommended_violations)

    def test_nerve_at_2mm_ok(self):
        """Nerve at exactly 2.0 mm → no violation (DoD: ≥ 2 mm is OK)."""
        plan = _make_plan()
        nerve = self._nerve_at_distance(2.0)
        metrics = compute_implant_metrics(
            plan, self._VOL,
            voxel_spacing_mm=self._SPACING,
            mandibular_nerve_curve=nerve,
        )
        nerve_violations = [v for v in metrics.recommended_violations if "nerve" in v.lower()]
        assert len(nerve_violations) == 0, (
            f"Expected no nerve violation at 2.0 mm clearance but got: {nerve_violations}"
        )

    def test_nerve_at_5mm_ok(self):
        """Nerve at 5.0 mm → no violation."""
        plan = _make_plan()
        nerve = self._nerve_at_distance(5.0)
        metrics = compute_implant_metrics(
            plan, self._VOL,
            voxel_spacing_mm=self._SPACING,
            mandibular_nerve_curve=nerve,
        )
        nerve_violations = [v for v in metrics.recommended_violations if "nerve" in v.lower()]
        assert len(nerve_violations) == 0

    def test_nerve_clearance_value_accurate(self):
        """nerve_clearance_mm should be close to the configured offset."""
        plan = _make_plan()
        nerve = self._nerve_at_distance(3.0)
        metrics = compute_implant_metrics(
            plan, self._VOL,
            voxel_spacing_mm=self._SPACING,
            mandibular_nerve_curve=nerve,
        )
        # The minimum distance from the z-axis segment to a parallel line offset
        # by 3.0 mm in x should be approximately 3.0 mm.
        assert metrics.nerve_clearance_mm == pytest.approx(3.0, abs=0.05)

    def test_no_nerve_provided_none(self):
        """Without nerve curve, nerve_clearance_mm is None."""
        plan = _make_plan()
        metrics = compute_implant_metrics(plan, self._VOL, voxel_spacing_mm=self._SPACING)
        assert metrics.nerve_clearance_mm is None


# ===========================================================================
# DoD Oracle 3 — Sizing recommendation: tooth 16 → ≈ 4.0 × 10 mm
# ===========================================================================

class TestRecommendImplantDimensions:
    """
    Misch §22 Table 22-2: posterior maxillary (tooth 16 = upper right first molar)
    → diameter 4.0 mm, length 10.0 mm in D2 bone.
    """

    def test_tooth_16_baseline_diameter(self):
        """Tooth 16 (upper right first molar) → diameter ≈ 4.0 mm (DoD)."""
        plan = recommend_implant_dimensions("16", bone_quality=BoneDensity.D2)
        assert plan.diameter_mm == pytest.approx(4.0, abs=0.01)

    def test_tooth_16_baseline_length(self):
        """Tooth 16 → length ≈ 10.0 mm in D2 bone (DoD)."""
        plan = recommend_implant_dimensions("16", bone_quality=BoneDensity.D2)
        assert plan.length_mm == pytest.approx(10.0, abs=0.01)

    def test_tooth_16_returns_implant_plan(self):
        """Return type is ImplantPlan."""
        plan = recommend_implant_dimensions("16")
        assert isinstance(plan, ImplantPlan)

    def test_tooth_16_tooth_position_set(self):
        """tooth_position attribute carries the FDI code."""
        plan = recommend_implant_dimensions("16")
        assert plan.tooth_position == "16"

    def test_tooth_11_anterior_maxillary(self):
        """Tooth 11 (upper right central incisor) → anterior maxillary: 3.5 × 11 mm."""
        plan = recommend_implant_dimensions("11", bone_quality=BoneDensity.D2)
        assert plan.diameter_mm == pytest.approx(3.5, abs=0.01)
        assert plan.length_mm == pytest.approx(11.0, abs=0.01)

    def test_tooth_36_posterior_mandibular(self):
        """Tooth 36 (lower left first molar) → posterior mandibular: 4.5 × 10 mm."""
        plan = recommend_implant_dimensions("36", bone_quality=BoneDensity.D2)
        assert plan.diameter_mm == pytest.approx(4.5, abs=0.01)
        assert plan.length_mm == pytest.approx(10.0, abs=0.01)

    def test_d3_bone_wider_longer(self):
        """D3 bone → wider + longer implant than D2 (Misch §22 Table 22-3)."""
        p_d2 = recommend_implant_dimensions("16", bone_quality=BoneDensity.D2)
        p_d3 = recommend_implant_dimensions("16", bone_quality=BoneDensity.D3)
        assert p_d3.diameter_mm >= p_d2.diameter_mm
        assert p_d3.length_mm >= p_d2.length_mm

    def test_sinus_present_reduces_length_in_posterior_maxilla(self):
        """sinus_present=True → shorter implant in posterior maxilla."""
        p_no_sinus = recommend_implant_dimensions("16", sinus_present=False)
        p_sinus = recommend_implant_dimensions("16", sinus_present=True)
        assert p_sinus.length_mm < p_no_sinus.length_mm

    def test_sinus_minimum_8mm(self):
        """Even with sinus, length must be ≥ 8 mm (minimum for osseointegration)."""
        plan = recommend_implant_dimensions("17", bone_quality=BoneDensity.D4, sinus_present=True)
        assert plan.length_mm >= 8.0

    def test_trajectory_matches_length(self):
        """Computed trajectory length should match recommended length_mm."""
        plan = recommend_implant_dimensions("16")
        traj_len = plan.trajectory_length_mm
        # The exit_point is computed from entry + axis * length_mm
        assert traj_len == pytest.approx(plan.length_mm, abs=0.01)

    def test_fdi_region_upper_right_molar(self):
        assert _fdi_to_region("16") == "posterior_maxillary"

    def test_fdi_region_lower_left_incisor(self):
        assert _fdi_to_region("31") == "anterior_mandibular"

    def test_fdi_region_upper_left_premolar(self):
        assert _fdi_to_region("24") == "premolar_maxillary"

    def test_fdi_region_lower_right_premolar(self):
        assert _fdi_to_region("45") == "premolar_mandibular"


# ===========================================================================
# DoD Oracle 4 — Axial deviation: 15° → flagged > 10° EAO limit
# ===========================================================================

class TestAxialDeviation:
    """
    EAO guideline: axial deviation from prosthetic axis ≤ 10°.
    Trajectory at 15° from prosthetic axis → violation flagged.
    Trajectory at ≤ 10° → no violation.
    """

    _VOL = _uniform_volume(1000.0)
    _SPACING = (0.2, 0.2, 0.2)

    def _plan_at_angle(self, angle_deg: float) -> ImplantPlan:
        """
        Build a plan whose trajectory is *angle_deg* from the prosthetic axis (0,0,1).
        The trajectory is tilted in the xz-plane.
        """
        rad = math.radians(angle_deg)
        # Trajectory direction: (sin(angle), 0, cos(angle))
        tx = math.sin(rad)
        tz = math.cos(rad)
        exit_pt = (tx * 10.0, 0.0, tz * 10.0)
        return ImplantPlan(
            entry_point=(0.0, 0.0, 0.0),
            exit_point=exit_pt,
            diameter_mm=4.0,
            length_mm=10.0,
            tooth_position="16",
            prosthetic_axis=(0.0, 0.0, 1.0),  # occlusal axis
        )

    def test_15deg_deviation_flagged(self):
        """Trajectory at 15° → axial deviation violation (DoD)."""
        plan = self._plan_at_angle(15.0)
        metrics = compute_implant_metrics(plan, self._VOL, voxel_spacing_mm=self._SPACING)
        assert metrics.axial_deviation_deg == pytest.approx(15.0, abs=0.1)
        axial_violations = [v for v in metrics.recommended_violations if "axial" in v.lower()]
        assert len(axial_violations) >= 1, (
            f"Expected axial violation at 15° but got: {metrics.recommended_violations}"
        )

    def test_9deg_deviation_ok(self):
        """Trajectory at 9° → no axial violation (within 10° EAO limit)."""
        plan = self._plan_at_angle(9.0)
        metrics = compute_implant_metrics(plan, self._VOL, voxel_spacing_mm=self._SPACING)
        axial_violations = [v for v in metrics.recommended_violations if "axial" in v.lower()]
        assert len(axial_violations) == 0, (
            f"Unexpected axial violation at 9°: {axial_violations}"
        )

    def test_10deg_deviation_ok(self):
        """Trajectory at exactly 10° → no violation (≤ 10° is the EAO limit)."""
        plan = self._plan_at_angle(10.0)
        metrics = compute_implant_metrics(plan, self._VOL, voxel_spacing_mm=self._SPACING)
        axial_violations = [v for v in metrics.recommended_violations if "axial" in v.lower()]
        assert len(axial_violations) == 0, (
            f"10° is within EAO limit; unexpected violation: {axial_violations}"
        )

    def test_0deg_deviation_no_violation(self):
        """Perfect axial alignment → no deviation violation."""
        plan = self._plan_at_angle(0.0)
        metrics = compute_implant_metrics(plan, self._VOL, voxel_spacing_mm=self._SPACING)
        axial_violations = [v for v in metrics.recommended_violations if "axial" in v.lower()]
        assert len(axial_violations) == 0

    def test_deviation_value_accurate(self):
        """axial_deviation_deg attribute matches the constructed angle."""
        for angle in [0.0, 5.0, 10.0, 15.0, 20.0]:
            plan = self._plan_at_angle(angle)
            metrics = compute_implant_metrics(plan, self._VOL, voxel_spacing_mm=self._SPACING)
            assert metrics.axial_deviation_deg == pytest.approx(angle, abs=0.1), (
                f"Expected {angle}° but got {metrics.axial_deviation_deg:.2f}°"
            )

    def test_no_prosthetic_axis_zero_deviation(self):
        """Without a prosthetic axis, axial_deviation_deg should be 0.0."""
        plan = _make_plan(prosthetic_axis=None)
        metrics = compute_implant_metrics(plan, self._VOL, voxel_spacing_mm=self._SPACING)
        assert metrics.axial_deviation_deg == pytest.approx(0.0, abs=1e-9)


# ===========================================================================
# ImplantPlan data model
# ===========================================================================

class TestImplantPlan:
    def test_basic_construction(self):
        plan = ImplantPlan(
            entry_point=(0.0, 0.0, 0.0),
            exit_point=(0.0, 0.0, 10.0),
        )
        assert plan.diameter_mm == pytest.approx(4.0)
        assert plan.length_mm == pytest.approx(10.0)

    def test_trajectory_vector_unit(self):
        """trajectory_vector must be a unit vector."""
        plan = _make_plan()
        v = plan.trajectory_vector
        assert abs(np.linalg.norm(v) - 1.0) < 1e-12

    def test_trajectory_length(self):
        plan = _make_plan(exit_=(3.0, 4.0, 0.0))
        assert plan.trajectory_length_mm == pytest.approx(5.0, abs=1e-9)

    def test_coincident_points_raises(self):
        with pytest.raises(ValueError, match="distinct"):
            ImplantPlan(
                entry_point=(1.0, 2.0, 3.0),
                exit_point=(1.0, 2.0, 3.0),
            )

    def test_zero_diameter_raises(self):
        with pytest.raises(ValueError):
            ImplantPlan(
                entry_point=(0.0, 0.0, 0.0),
                exit_point=(0.0, 0.0, 10.0),
                diameter_mm=0.0,
            )

    def test_negative_length_raises(self):
        with pytest.raises(ValueError):
            ImplantPlan(
                entry_point=(0.0, 0.0, 0.0),
                exit_point=(0.0, 0.0, 10.0),
                length_mm=-1.0,
            )


# ===========================================================================
# Surgical guide geometry
# ===========================================================================

class TestGenerateSurgicalGuideGeometry:
    def test_returns_dict_with_required_keys(self):
        plan = _make_plan()
        result = generate_surgical_guide_geometry(plan)
        for key in ("vertices", "faces", "outer_radius_mm", "inner_radius_mm", "axis", "entry"):
            assert key in result

    def test_vertices_and_faces_non_empty(self):
        plan = _make_plan()
        result = generate_surgical_guide_geometry(plan)
        assert len(result["vertices"]) > 0
        assert len(result["faces"]) > 0

    def test_outer_radius_greater_than_inner(self):
        plan = _make_plan()
        result = generate_surgical_guide_geometry(plan)
        assert result["outer_radius_mm"] > result["inner_radius_mm"]

    def test_inner_radius_matches_plan(self):
        plan = _make_plan()  # diameter 4.0 → inner_r = 2.0
        result = generate_surgical_guide_geometry(plan)
        assert result["inner_radius_mm"] == pytest.approx(2.0, abs=1e-9)

    def test_axis_is_unit_vector(self):
        plan = _make_plan()
        result = generate_surgical_guide_geometry(plan)
        ax = np.array(result["axis"])
        assert abs(np.linalg.norm(ax) - 1.0) < 1e-12

    def test_face_indices_valid(self):
        """All face vertex indices must be within the vertex list."""
        plan = _make_plan()
        result = generate_surgical_guide_geometry(plan)
        n_verts = len(result["vertices"])
        for face in result["faces"]:
            for idx in face:
                assert 0 <= idx < n_verts

    def test_n_triangles_field(self):
        plan = _make_plan()
        result = generate_surgical_guide_geometry(plan)
        assert result["n_triangles"] == len(result["faces"])


# ===========================================================================
# HU sampling utility
# ===========================================================================

class TestSampleHuAlongTrajectory:
    def test_uniform_volume_returns_fill_value(self):
        vol = _uniform_volume(700.0, shape=(30, 30, 30))
        entry = np.array([1.0, 1.0, 1.0])
        exit_ = np.array([5.0, 5.0, 5.0])
        samples = _sample_hu_along_trajectory(entry, exit_, vol, voxel_spacing_mm=(0.5, 0.5, 0.5))
        # All in-bounds samples should be 700.0
        assert np.mean(samples) == pytest.approx(700.0, abs=1.0)

    def test_returns_correct_number_of_samples(self):
        vol = _uniform_volume(500.0, shape=(30, 30, 30))
        entry = np.array([0.0, 0.0, 0.0])
        exit_ = np.array([5.0, 5.0, 5.0])
        samples = _sample_hu_along_trajectory(
            entry, exit_, vol, voxel_spacing_mm=(0.5, 0.5, 0.5), n_samples=40
        )
        assert len(samples) == 40


# ===========================================================================
# Distance utility
# ===========================================================================

class TestMinDistancePointToCurve:
    def test_point_on_segment(self):
        """Point on the segment itself → distance = 0."""
        entry = np.array([0.0, 0.0, 0.0])
        exit_ = np.array([10.0, 0.0, 0.0])
        pts = np.array([[5.0, 0.0, 0.0]])
        assert _min_distance_point_to_curve(entry, exit_, pts) == pytest.approx(0.0, abs=1e-9)

    def test_perpendicular_offset(self):
        """Point perpendicular to segment at midpoint → distance = offset."""
        entry = np.array([0.0, 0.0, 0.0])
        exit_ = np.array([10.0, 0.0, 0.0])
        pts = np.array([[5.0, 3.0, 0.0]])
        assert _min_distance_point_to_curve(entry, exit_, pts) == pytest.approx(3.0, abs=1e-9)

    def test_clamping_past_end(self):
        """Point beyond exit end → clamped to exit, distance = ||pt - exit||."""
        entry = np.array([0.0, 0.0, 0.0])
        exit_ = np.array([1.0, 0.0, 0.0])
        pts = np.array([[3.0, 0.0, 0.0]])
        assert _min_distance_point_to_curve(entry, exit_, pts) == pytest.approx(2.0, abs=1e-9)


# ===========================================================================
# ImplantMetrics model
# ===========================================================================

class TestImplantMetrics:
    def test_no_violations_empty_list(self):
        vol = _uniform_volume(1000.0)
        plan = _make_plan()
        metrics = compute_implant_metrics(plan, vol, voxel_spacing_mm=(0.2, 0.2, 0.2))
        # D2 bone, no nerve/sinus, no prosthetic axis → no violations
        assert isinstance(metrics.recommended_violations, list)
        assert len(metrics.recommended_violations) == 0

    def test_n_samples_reported(self):
        vol = _uniform_volume(500.0)
        plan = _make_plan()
        metrics = compute_implant_metrics(
            plan, vol, voxel_spacing_mm=(0.2, 0.2, 0.2), n_samples=25
        )
        assert metrics.n_samples == 25

    def test_cortical_thickness_non_negative(self):
        vol = _uniform_volume(900.0)
        plan = _make_plan()
        metrics = compute_implant_metrics(plan, vol, voxel_spacing_mm=(0.2, 0.2, 0.2))
        assert metrics.cortical_thickness_entry_mm >= 0.0
