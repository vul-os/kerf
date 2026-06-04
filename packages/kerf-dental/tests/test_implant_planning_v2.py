"""
Tests for kerf_dental.implant_plan_v2 — Wave 11B: 3shape parity

Tests:
- plan_implant in dense bone (>1000 HU) → stability ≥ 7
- plan_implant with nerve at 1mm → distance flag + warning
- ImplantSpec brand catalogue
- assess_bone_density Misch D1-D4
- _hu_to_torque + _torque_to_stability_score

Wave 11B: dental depth (3shape parity)
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_dental.crown_bridge import ToothNumber
from kerf_dental.implant_plan_v2 import (
    ImplantSpec,
    ImplantPosition,
    ImplantPlan,
    assess_bone_density,
    plan_implant,
    _hu_to_torque,
    _torque_to_stability_score,
    _select_implant_size,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dense_volume(hu: float = 1100.0, shape=(40, 40, 40)) -> np.ndarray:
    return np.full(shape, hu, dtype=float)


def _make_emergence() -> np.ndarray:
    return np.array([0.0, 0.0, 0.0])


# ===========================================================================
# ImplantSpec
# ===========================================================================

class TestImplantSpec:
    def test_straumann_blt(self):
        s = ImplantSpec(brand="Straumann BLT", diameter_mm=4.1, length_mm=10.0, platform="RC")
        assert s.brand == "Straumann BLT"
        assert s.diameter_mm == 4.1

    def test_zero_diameter_raises(self):
        with pytest.raises(ValueError):
            ImplantSpec(brand="Generic", diameter_mm=0.0, length_mm=10.0, platform="RC")

    def test_negative_length_raises(self):
        with pytest.raises(ValueError):
            ImplantSpec(brand="Generic", diameter_mm=4.0, length_mm=-1.0, platform="RC")


# ===========================================================================
# ImplantPosition
# ===========================================================================

class TestImplantPosition:
    def test_axis_normalised(self):
        pos = ImplantPosition(
            fixture_tip=np.array([0.0, 0.0, -10.0]),
            platform_position=np.array([0.0, 0.0, 0.0]),
            axis_direction=np.array([0.0, 0.0, 5.0]),  # non-unit, should be normalised
            angulation_deg=(0.0, 0.0),
        )
        assert abs(np.linalg.norm(pos.axis_direction) - 1.0) < 1e-9


# ===========================================================================
# Bone density helpers
# ===========================================================================

class TestHuToTorque:
    def test_dense_bone_high_torque(self):
        """D1 bone (>1250 HU) should give ~48 Ncm."""
        t = _hu_to_torque(1300.0)
        assert t >= 45.0

    def test_porous_bone_lower_torque(self):
        """D4 bone (150-350 HU) should be lower than D2 bone."""
        t_d4 = _hu_to_torque(200.0)
        t_d2 = _hu_to_torque(1000.0)
        assert t_d4 < t_d2

    def test_sub_threshold_minimal_torque(self):
        t = _hu_to_torque(50.0)
        assert t <= 10.0


class TestTorqueToStabilityScore:
    def test_high_torque_high_score(self):
        score = _torque_to_stability_score(48.0)
        assert score >= 8

    def test_low_torque_low_score(self):
        score = _torque_to_stability_score(5.0)
        assert score <= 5

    def test_score_in_range(self):
        for torque in [5.0, 15.0, 25.0, 35.0, 45.0]:
            score = _torque_to_stability_score(torque)
            assert 1 <= score <= 10


# ===========================================================================
# assess_bone_density
# ===========================================================================

class TestAssessBoneDensity:
    def test_d1_classification(self):
        vol = _dense_volume(1300.0)
        result = assess_bone_density(vol, ((0, 0, 0), (10, 10, 10)))
        assert result["classification"] == "D1"

    def test_d2_classification(self):
        vol = _dense_volume(1000.0)
        result = assess_bone_density(vol, ((0, 0, 0), (5, 5, 5)))
        assert result["classification"] == "D2"

    def test_d3_classification(self):
        vol = _dense_volume(600.0)
        result = assess_bone_density(vol, ((0, 0, 0), (5, 5, 5)))
        assert result["classification"] == "D3"

    def test_d4_sub_threshold(self):
        vol = _dense_volume(80.0)
        result = assess_bone_density(vol, ((0, 0, 0), (5, 5, 5)))
        assert result["classification"] == "D4-"

    def test_returns_mean_hu(self):
        vol = _dense_volume(900.0)
        result = assess_bone_density(vol, ((0, 0, 0), (5, 5, 5)))
        assert result["mean_hu"] == pytest.approx(900.0, abs=1.0)

    def test_returns_description_key(self):
        vol = _dense_volume(1000.0)
        result = assess_bone_density(vol, ((0, 0, 0), (5, 5, 5)))
        assert "description" in result


# ===========================================================================
# plan_implant
# ===========================================================================

class TestPlanImplant:
    """DoD: plan_implant in dense bone → primary_stability_score ≥ 7."""

    def test_dense_bone_stability_at_least_7(self):
        """DoD: plan_implant in dense bone (>1000 HU) → stability ≥ 7."""
        tooth = ToothNumber.from_universal(19)
        vol = _dense_volume(1100.0, shape=(60, 60, 60))
        emergence = _make_emergence()
        plan = plan_implant(tooth, vol, emergence, brand="Straumann BLT",
                            voxel_spacing_mm=(0.4, 0.4, 0.4))
        assert plan.primary_stability_score >= 7, (
            f"Expected stability ≥ 7 in dense bone, got {plan.primary_stability_score}"
        )

    def test_returns_implant_plan_instance(self):
        tooth = ToothNumber.from_universal(19)
        vol = _dense_volume(1000.0)
        plan = plan_implant(tooth, vol, _make_emergence())
        assert isinstance(plan, ImplantPlan)

    def test_is_prosthetic_driven(self):
        tooth = ToothNumber.from_universal(19)
        vol = _dense_volume(1000.0)
        plan = plan_implant(tooth, vol, _make_emergence())
        assert plan.is_prosthetic_driven is True

    def test_insertion_torque_positive(self):
        tooth = ToothNumber.from_universal(19)
        vol = _dense_volume(1000.0)
        plan = plan_implant(tooth, vol, _make_emergence())
        assert plan.insertion_torque_estimate_n_cm > 0.0

    def test_honest_caveat_present(self):
        tooth = ToothNumber.from_universal(19)
        vol = _dense_volume(1000.0)
        plan = plan_implant(tooth, vol, _make_emergence())
        assert "NOT" in plan.honest_caveat.upper() or "EDUCATIONAL" in plan.honest_caveat.upper()

    def test_nerve_at_1mm_distance_recorded(self):
        """DoD: nerve at 1mm → distance_to_nerve_mm ≈ 1mm."""
        tooth = ToothNumber.from_universal(30)  # mandibular
        vol = _dense_volume(1000.0, shape=(60, 60, 60))
        emergence = np.array([0.0, 0.0, 0.0])

        # Nerve 1mm from emergence
        nerve_pts = np.array([[1.0, 0.0, z] for z in np.linspace(0, -10, 20)])
        plan = plan_implant(
            tooth, vol, emergence,
            nerve_polyline=nerve_pts,
            voxel_spacing_mm=(0.4, 0.4, 0.4),
        )
        assert plan.distance_to_nerve_mm < 2.0, (
            f"Expected nerve clearance < 2mm (nerve at 1mm), got {plan.distance_to_nerve_mm:.2f}mm"
        )

    def test_sinus_clearance_recorded(self):
        tooth = ToothNumber.from_universal(14)  # maxillary
        vol = _dense_volume(700.0, shape=(40, 40, 40))
        emergence = np.array([0.0, 0.0, 0.0])
        sinus_pts = np.array([[0.0, 0.0, -5.0], [1.0, 0.0, -5.0]])
        plan = plan_implant(
            tooth, vol, emergence,
            sinus_floor_mesh=(sinus_pts, np.array([[0, 1, 0]])),
        )
        assert plan.distance_to_sinus_mm < 999.0

    def test_implant_brand_straumann(self):
        tooth = ToothNumber.from_universal(19)
        vol = _dense_volume(1000.0)
        plan = plan_implant(tooth, vol, _make_emergence(), brand="Straumann BLT")
        assert plan.implant.brand == "Straumann BLT"

    def test_implant_brand_nobels(self):
        tooth = ToothNumber.from_universal(19)
        vol = _dense_volume(1000.0)
        plan = plan_implant(tooth, vol, _make_emergence(), brand="NobelActive")
        assert plan.implant.brand == "NobelActive"

    def test_implant_dimensions_positive(self):
        tooth = ToothNumber.from_universal(19)
        vol = _dense_volume(1000.0)
        plan = plan_implant(tooth, vol, _make_emergence())
        assert plan.implant.diameter_mm > 0.0
        assert plan.implant.length_mm > 0.0


# ===========================================================================
# _select_implant_size
# ===========================================================================

class TestSelectImplantSize:
    def test_returns_implant_spec(self):
        spec = _select_implant_size(20.0, 12.0, 1000.0, "Straumann BLT")
        assert isinstance(spec, ImplantSpec)

    def test_limited_bone_shorter_implant(self):
        spec_plenty = _select_implant_size(20.0, 12.0, 1000.0)
        spec_limited = _select_implant_size(9.0, 12.0, 1000.0)
        assert spec_limited.length_mm <= spec_plenty.length_mm
