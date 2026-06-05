"""
tests/test_parity_deepening.py — 3Shape parity deepening tests.

Covers:
  - crown_bridge ISO 4049 cement-gap properties + material min thickness
  - implant_plan_v2 Tarnow/Grunder spacing + drill sequence catalogue
  - surgical_guide inspection windows + guide stops
  - denture_v2 Applegate rules + modification count

Wave 11B deepening: 3shape parity.
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


# ===========================================================================
# Crown / Bridge — ISO 4049 cement gap deepening
# ===========================================================================

from kerf_dental.crown_bridge import (
    ToothNumber, MarginLine, CrownDesignSpec, design_crown,
)


def _make_margin(n=16):
    angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.column_stack([5 * np.cos(angles), 5 * np.sin(angles), np.zeros(n)])


def _make_spec(material="zirconia", cement_gap_mm=0.04):
    tooth = ToothNumber.from_universal(19)
    margin = MarginLine(points=_make_margin(), type="chamfer", width_mm=0.8)
    return CrownDesignSpec(
        tooth_number=tooth,
        margin=margin,
        occlusal_clearance_mm=1.5,
        interproximal_contacts=[],
        material=material,
        cement_gap_mm=cement_gap_mm,
    )


class TestISO4049CementGap:
    def test_iso_4049_compliant_at_40um(self):
        """Default 40 µm is within ISO 4049 §6.4 compliant range 20-80 µm."""
        spec = _make_spec()
        assert spec.iso_4049_compliant is True

    def test_iso_4049_non_compliant_at_100um(self):
        """100 µm exceeds ISO 4049 §6.4 upper bound."""
        spec = _make_spec(cement_gap_mm=0.10)
        assert spec.iso_4049_compliant is False

    def test_cement_gap_um_property(self):
        spec = _make_spec(cement_gap_mm=0.04)
        assert spec.cement_gap_um == pytest.approx(40.0, abs=1e-6)

    def test_cement_gap_above_200um_raises(self):
        """cement_gap_mm > 0.2 mm is clinically unacceptable."""
        with pytest.raises(ValueError, match="ISO 4049"):
            _make_spec(cement_gap_mm=0.25)

    def test_material_min_thickness_zirconia(self):
        spec = _make_spec("zirconia")
        assert spec.material_min_thickness_mm == pytest.approx(0.5, abs=1e-6)

    def test_material_min_thickness_lithium_disilicate(self):
        spec = _make_spec("lithium_disilicate")
        assert spec.material_min_thickness_mm == pytest.approx(0.8, abs=1e-6)

    def test_material_min_thickness_pmma(self):
        spec = _make_spec("pmma")
        assert spec.material_min_thickness_mm == pytest.approx(1.5, abs=1e-6)

    def test_crown_wall_ge_material_min_zirconia(self):
        """Crown wall thickness must be >= material minimum (0.5 mm for zirconia)."""
        result = design_crown(_make_spec("zirconia"))
        assert result.wall_thickness_min_mm >= 0.5

    def test_crown_wall_ge_material_min_pmma(self):
        """Crown wall thickness must be >= material minimum (1.5 mm for PMMA)."""
        result = design_crown(_make_spec("pmma"))
        assert result.wall_thickness_min_mm >= 1.5

    def test_margin_fit_zirconia_includes_machining_tol(self):
        """margin_fit_um = cement_gap_um + zirconia_machining_tol/2 = 40+10 = 50."""
        result = design_crown(_make_spec("zirconia", 0.04))
        assert result.margin_fit_um == pytest.approx(50.0, abs=1.0)

    def test_margin_fit_pmma_includes_machining_tol(self):
        """PMMA machining tol = 30 µm → 40 + 15 = 55 µm."""
        result = design_crown(_make_spec("pmma", 0.04))
        assert result.margin_fit_um == pytest.approx(55.0, abs=1.0)


# ===========================================================================
# Implant planning — Tarnow / Grunder + drill sequence
# ===========================================================================

from kerf_dental.implant_plan_v2 import (
    check_tarnow_grunder_spacing,
    get_drill_sequence,
)


class TestTarnowGrunderSpacing:
    """DoD: Tarnow 2000 + Grunder 2005 spacing checks."""

    def test_no_violation_with_generous_spacing(self):
        """Two implants 10 mm apart (surface-to-surface 5.9 mm) → OK."""
        positions = [np.array([0.0, 0.0, 0.0]), np.array([10.0, 0.0, 0.0])]
        diameters = [4.1, 4.1]
        result = check_tarnow_grunder_spacing(positions, diameters)
        assert result["tarnow_ok"] is True
        assert result["min_implant_to_implant_mm"] == pytest.approx(10.0 - 4.1, abs=0.01)

    def test_tarnow_violation_at_5mm_center_to_center(self):
        """Two 4.1 mm implants at 5 mm c-c → surface 0.9 mm < 3 mm → violation."""
        positions = [np.array([0.0, 0.0, 0.0]), np.array([5.0, 0.0, 0.0])]
        diameters = [4.1, 4.1]
        result = check_tarnow_grunder_spacing(positions, diameters)
        assert result["tarnow_ok"] is False
        assert len(result["tarnow_violations"]) == 1
        violation = result["tarnow_violations"][0]
        assert "Tarnow" in violation["rule"]
        assert violation["deficit_mm"] > 0

    def test_grunder_violation_at_2mm_implant_to_tooth(self):
        """Implant at [0,0,0] diam 4.0, tooth at [3,0,0] → surface = 1 mm < 1.5 mm."""
        positions = [np.array([0.0, 0.0, 0.0])]
        diameters = [4.0]
        teeth = [np.array([3.0, 0.0, 0.0])]
        result = check_tarnow_grunder_spacing(positions, diameters, teeth)
        assert result["grunder_ok"] is False
        assert len(result["grunder_violations"]) == 1
        assert "Grunder" in result["grunder_violations"][0]["rule"]

    def test_grunder_ok_at_4mm_implant_to_tooth(self):
        """Implant at [0,0,0] diam 4.0, tooth at [5,0,0] → surface = 3 mm >= 1.5 mm."""
        positions = [np.array([0.0, 0.0, 0.0])]
        diameters = [4.0]
        teeth = [np.array([5.0, 0.0, 0.0])]
        result = check_tarnow_grunder_spacing(positions, diameters, teeth)
        assert result["grunder_ok"] is True

    def test_single_implant_no_tarnow_check(self):
        """Single implant → inter-implant check not applicable."""
        positions = [np.array([0.0, 0.0, 0.0])]
        diameters = [4.1]
        result = check_tarnow_grunder_spacing(positions, diameters)
        assert result["tarnow_ok"] is True
        assert result["min_implant_to_implant_mm"] is None

    def test_disclaimer_present(self):
        result = check_tarnow_grunder_spacing([np.zeros(3)], [4.0])
        assert "disclaimer" in result


class TestDrillSequence:
    """DoD: drill sequences per brand catalogue."""

    def test_straumann_blt_4_1mm_sequence(self):
        """Straumann BLT 4.1 mm → 4-step sequence."""
        seq = get_drill_sequence("Straumann BLT", 4.1)
        assert len(seq) >= 3
        assert all("drill" in s for s in seq)
        diams = [s["diameter_mm"] for s in seq]
        # Sequence should be increasing
        assert diams == sorted(diams)

    def test_nobels_active_4_3mm_sequence(self):
        seq = get_drill_sequence("NobelActive", 4.3)
        assert len(seq) >= 3
        assert any("Countersink" in s["drill"] or "drill" in s["drill"].lower() for s in seq)

    def test_astra_ev_4_0mm_sequence(self):
        seq = get_drill_sequence("Astra EV", 4.0)
        assert len(seq) >= 3

    def test_sequence_has_required_keys(self):
        seq = get_drill_sequence("Straumann BLT", 3.3)
        for step in seq:
            assert "step" in step
            assert "drill" in step
            assert "diameter_mm" in step
            assert "speed_rpm" in step
            assert "torque_ncm" in step

    def test_straumann_blt_step_order(self):
        """Steps should be numbered in increasing order."""
        seq = get_drill_sequence("Straumann BLT", 4.8)
        for i, s in enumerate(seq):
            assert s["step"] == i + 1

    def test_unknown_brand_falls_back_gracefully(self):
        """Unknown brand should return a valid sequence (fallback)."""
        seq = get_drill_sequence("UnknownBrand XYZ", 4.0)
        assert len(seq) >= 1


# ===========================================================================
# Surgical guide — inspection windows + guide stops
# ===========================================================================

from kerf_dental.crown_bridge import ToothNumber
from kerf_dental.implant_plan_v2 import ImplantSpec, ImplantPosition, ImplantPlan
from kerf_dental.surgical_guide import design_surgical_guide, SurgicalGuide


def _dummy_arch(n=20):
    angles = np.linspace(math.pi, 0, n)
    verts = np.column_stack([35 * np.cos(angles), 25 * np.sin(angles), np.zeros(n)])
    tris = np.array([[i, (i+1)%n, (i+2)%n] for i in range(n-2)])
    return verts, tris


def _make_plan(axis=None):
    if axis is None:
        axis = np.array([0.0, 0.0, 1.0])
    tooth = ToothNumber.from_universal(19)
    implant = ImplantSpec(brand="Straumann BLT", diameter_mm=4.1, length_mm=10.0, platform="RC")
    pos = ImplantPosition(
        fixture_tip=np.array([0.0, 0.0, -10.0]),
        platform_position=np.array([0.0, 0.0, 0.0]),
        axis_direction=axis,
        angulation_deg=(0.0, 0.0),
    )
    return ImplantPlan(
        tooth_position=tooth,
        implant=implant,
        position=pos,
        bone_density_HU=1000.0,
        distance_to_nerve_mm=5.0,
        distance_to_sinus_mm=10.0,
        is_prosthetic_driven=True,
        insertion_torque_estimate_n_cm=40.0,
        primary_stability_score=8,
    )


class TestSurgicalGuideDeepened:
    """DoD: inspection windows (fenestrations) + drill depth stops."""

    def test_fenestrations_default_count(self):
        """Default 3 inspection windows per guide."""
        plan = _make_plan()
        guide = design_surgical_guide([plan], _dummy_arch())
        assert len(guide.fenestrations) == 3

    def test_fenestrations_custom_count(self):
        plan = _make_plan()
        guide = design_surgical_guide([plan], _dummy_arch(), n_fenestrations=5)
        assert len(guide.fenestrations) == 5

    def test_fenestration_has_center_and_radius(self):
        plan = _make_plan()
        guide = design_surgical_guide([plan], _dummy_arch())
        for fen in guide.fenestrations:
            assert "center" in fen
            assert "radius_mm" in fen
            assert fen["radius_mm"] > 0.0

    def test_guide_stops_produced(self):
        """Guide stops (depth-stop rings) should be produced per sleeve."""
        plan = _make_plan()
        guide = design_surgical_guide([plan], _dummy_arch())
        assert guide.sleeve_guide_stops is not None
        assert len(guide.sleeve_guide_stops) == 1

    def test_guide_stop_depth_matches_implant_length(self):
        """Guide stop depth = implant length (from plan)."""
        plan = _make_plan()
        guide = design_surgical_guide([plan], _dummy_arch())
        stop = guide.sleeve_guide_stops[0]
        assert stop["depth_mm"] == pytest.approx(plan.implant.length_mm, abs=1e-6)

    def test_guide_stop_ring_diam_larger_than_sleeve(self):
        """Ring diam > sleeve outer diam (stops contact from outside)."""
        plan = _make_plan()
        guide = design_surgical_guide([plan], _dummy_arch())
        stop = guide.sleeve_guide_stops[0]
        sleeve = guide.sleeves[0]
        assert stop["ring_diam_mm"] > sleeve.outer_diameter_mm

    def test_multiple_plans_equal_stops(self):
        """One guide stop per implant plan."""
        plans = [_make_plan() for _ in range(3)]
        guide = design_surgical_guide(plans, _dummy_arch())
        assert len(guide.sleeve_guide_stops) == 3

    def test_honest_caveat_contains_iso(self):
        plan = _make_plan()
        guide = design_surgical_guide([plan], _dummy_arch())
        # honest caveat should reference ISO 10993-5 biocompatibility
        assert "ISO 10993" in guide.honest_caveat or "biocompatibility" in guide.honest_caveat.lower()


# ===========================================================================
# Denture v2 — Applegate rules + modification count
# ===========================================================================

from kerf_dental.crown_bridge import ToothNumber
from kerf_dental.denture_v2 import DentureSpec


class TestKennedyClassificationApplegate:
    """DoD: Kennedy classification with Applegate rules."""

    def test_class_I_bilateral_posterior(self):
        """Bilateral posterior missing = Class I."""
        teeth = [ToothNumber.from_fdi(f) for f in ["36", "37", "46", "47"]]
        spec = DentureSpec(arch="mandibular", type="partial", teeth_to_replace=teeth)
        assert spec.kennedy_class == "Class I"

    def test_class_II_unilateral_posterior(self):
        """Unilateral posterior missing = Class II."""
        teeth = [ToothNumber.from_fdi("36"), ToothNumber.from_fdi("37")]
        spec = DentureSpec(arch="mandibular", type="partial", teeth_to_replace=teeth)
        assert spec.kennedy_class == "Class II"

    def test_class_III_bounded_saddle(self):
        """Missing bounded by teeth = Class III."""
        teeth = [ToothNumber.from_fdi("35"), ToothNumber.from_fdi("34")]
        spec = DentureSpec(arch="mandibular", type="partial", teeth_to_replace=teeth)
        assert spec.kennedy_class == "Class III"

    def test_class_IV_anterior_crosses_midline(self):
        """Anterior crossing midline = Class IV."""
        teeth = [
            ToothNumber.from_fdi("11"),
            ToothNumber.from_fdi("12"),
            ToothNumber.from_fdi("21"),
            ToothNumber.from_fdi("22"),
        ]
        spec = DentureSpec(arch="maxillary", type="partial", teeth_to_replace=teeth)
        assert spec.kennedy_class == "Class IV"

    def test_complete_returns_complete(self):
        teeth = [ToothNumber.from_universal(i) for i in range(17, 25)]
        spec = DentureSpec(arch="mandibular", type="complete", teeth_to_replace=teeth)
        assert spec.kennedy_class == "complete"

    def test_class_IV_no_modifications(self):
        """Applegate Rule 8: Class IV cannot have modifications."""
        teeth = [ToothNumber.from_fdi("11"), ToothNumber.from_fdi("21")]
        spec = DentureSpec(arch="maxillary", type="partial", teeth_to_replace=teeth)
        assert spec.kennedy_class == "Class IV"
        assert spec.applegate_modification_count == 0

    def test_complete_no_modifications(self):
        teeth = [ToothNumber.from_universal(i) for i in range(17, 25)]
        spec = DentureSpec(arch="mandibular", type="complete", teeth_to_replace=teeth)
        assert spec.applegate_modification_count == 0

    def test_class_I_with_additional_gap_has_modification(self):
        """Class I with an extra anterior gap has 1+ modification."""
        teeth = [
            ToothNumber.from_fdi("36"),   # bilateral posterior = Class I
            ToothNumber.from_fdi("46"),
            ToothNumber.from_fdi("33"),   # extra anterior gap = modification
        ]
        spec = DentureSpec(arch="mandibular", type="partial", teeth_to_replace=teeth)
        assert spec.kennedy_class == "Class I"
        # Should have 1 modification (the anterior gap)
        assert spec.applegate_modification_count >= 1
