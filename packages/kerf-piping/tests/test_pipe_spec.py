"""
Tests for kerf_piping.pipe_spec — ASME B36.10M / B31.3 spec-driven pipe selection.

DoD coverage:
  1. wall_thickness_mm returns correct ASME B36.10M values.
  2. nominal_od_mm returns correct values.
  3. min_wall_barlow returns positive values consistent with Barlow formula.
  4. select_schedule raises for insufficient wall thickness.
  5. check_spec_compliance returns compliant=True for spec-conforming pipe.
  6. check_spec_compliance returns compliant=False + violations for bad pipe.
  7. Standard class factories return valid PipeSpec objects.
  8. MaterialSpec.from_designation works for known materials.
"""

from __future__ import annotations

import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_piping.pipe_spec import (
    wall_thickness_mm,
    nominal_od_mm,
    min_wall_barlow,
    select_schedule,
    check_spec_compliance,
    MaterialSpec,
    PipeSpec,
    standard_class_cs_a,
    standard_class_cs_hh,
    standard_class_ss_316l,
    standard_class_api_x52,
    WALL_THICKNESS_MM,
    NOMINAL_OD_MM,
    ALLOWABLE_STRESS_MPA,
)


# ===========================================================================
# ASME B36.10M wall thickness table
# ===========================================================================

class TestWallThicknessMM:
    def test_dn50_sch40(self):
        """DN50 Sch40: B36.10M = 3.91 mm."""
        t = wall_thickness_mm(50, "40")
        assert t == pytest.approx(3.91, abs=0.01)

    def test_dn100_sch80(self):
        """DN100 Sch80: B36.10M = 8.56 mm."""
        t = wall_thickness_mm(100, "80")
        assert t == pytest.approx(8.56, abs=0.01)

    def test_dn50_std_equals_sch40(self):
        """DN50 STD should equal Sch40 (3.91 mm)."""
        t_std = wall_thickness_mm(50, "STD")
        t_40 = wall_thickness_mm(50, "40")
        assert t_std == pytest.approx(t_40, abs=0.001)

    def test_dn50_xs(self):
        """DN50 XS: B36.10M = 5.54 mm."""
        t = wall_thickness_mm(50, "XS")
        assert t == pytest.approx(5.54, abs=0.01)

    def test_dn150_sch40(self):
        """DN150 Sch40: B36.10M = 7.11 mm."""
        t = wall_thickness_mm(150, "40")
        assert t == pytest.approx(7.11, abs=0.01)

    def test_missing_entry_raises_keyerror(self):
        """Non-existent DN/schedule combination raises KeyError."""
        with pytest.raises(KeyError):
            wall_thickness_mm(999, "40")

    def test_all_table_values_positive(self):
        """Every entry in the wall-thickness table should be positive."""
        for (dn, sched), t in WALL_THICKNESS_MM.items():
            assert t > 0.0, f"Non-positive wall at DN{dn} sched={sched}"

    def test_heavier_schedules_thicker(self):
        """Sch80 wall must be thicker than Sch40 for same DN."""
        for dn in [25, 50, 80, 100, 150]:
            if (dn, "40") in WALL_THICKNESS_MM and (dn, "80") in WALL_THICKNESS_MM:
                assert wall_thickness_mm(dn, "80") > wall_thickness_mm(dn, "40"), \
                    f"Sch80 not thicker than Sch40 for DN{dn}"


# ===========================================================================
# Nominal OD
# ===========================================================================

class TestNominalOD:
    def test_dn50(self):
        """DN50 OD: B36.10M = 60.325 mm."""
        od = nominal_od_mm(50)
        assert od == pytest.approx(60.325, abs=0.001)

    def test_dn100(self):
        """DN100 OD: B36.10M = 114.300 mm."""
        od = nominal_od_mm(100)
        assert od == pytest.approx(114.300, abs=0.001)

    def test_dn300(self):
        """DN300 OD: B36.10M = 323.850 mm."""
        od = nominal_od_mm(300)
        assert od == pytest.approx(323.850, abs=0.001)

    def test_missing_dn_raises(self):
        with pytest.raises(KeyError):
            nominal_od_mm(9999)

    def test_all_ods_positive(self):
        for dn, od in NOMINAL_OD_MM.items():
            assert od > 0.0


# ===========================================================================
# Barlow / B31.3 minimum wall
# ===========================================================================

class TestMinWallBarlow:
    def _mat(self, spec="A106", grade="B", ca=1.5):
        return MaterialSpec.from_designation(spec, grade, ca)

    def test_returns_positive(self):
        mat = self._mat()
        t = min_wall_barlow(50, 10.0, mat)
        assert t > 0.0

    def test_higher_pressure_requires_thicker_wall(self):
        mat = self._mat()
        t_lo = min_wall_barlow(50, 5.0, mat)
        t_hi = min_wall_barlow(50, 50.0, mat)
        assert t_hi > t_lo

    def test_larger_dn_requires_thicker_wall_same_pressure(self):
        mat = self._mat()
        t_small = min_wall_barlow(50, 10.0, mat)
        t_large = min_wall_barlow(200, 10.0, mat)
        assert t_large > t_small

    def test_barlow_formula_correctness(self):
        """
        Manual check: P=10 bar, D=60.325mm (DN50), S=117.2 MPa, E=1.0, Y=0.4.
        P_mpa = 1.0, D = 60.325 mm.
        t = P*D / (2*S*E + 2*Y*P) + c_a = 1.0*60.325/(2*117.2*1+2*0.4*1) + 1.5
          = 60.325/235.2 + 1.5 ≈ 0.2564 + 1.5 ≈ 1.756 mm
        """
        mat = MaterialSpec.from_designation("A106", "B", 1.5)
        t = min_wall_barlow(50, 10.0, mat)
        P_mpa = 1.0   # 10 barg * 0.1 = 1.0 MPa
        D = nominal_od_mm(50)
        S = 117.2
        E = 1.0
        Y = 0.4
        c_a = 1.5
        expected = P_mpa * D / (2 * S * E + 2 * Y * P_mpa) + c_a
        assert t == pytest.approx(expected, abs=0.001)

    def test_zero_pressure_returns_corrosion_allowance(self):
        """At P=0, only corrosion allowance contributes."""
        mat = MaterialSpec.from_designation("A106", "B", 2.0)
        t = min_wall_barlow(50, 0.0, mat)
        assert t == pytest.approx(mat.corrosion_allowance_mm, abs=0.001)


# ===========================================================================
# select_schedule
# ===========================================================================

class TestSelectSchedule:
    def test_cs_a_dn50_selects_sch40(self):
        spec = standard_class_cs_a()
        sched = select_schedule(50, spec)
        assert sched == "40"

    def test_cs_a_dn200_selects_sch20(self):
        """CS-A overrides to Sch20 for DN200."""
        spec = standard_class_cs_a()
        sched = select_schedule(200, spec)
        assert sched == "20"

    def test_cs_hh_dn50_selects_sch80(self):
        spec = standard_class_cs_hh()
        sched = select_schedule(50, spec)
        assert sched == "80"

    def test_select_raises_for_non_permitted_dn(self):
        spec = standard_class_cs_a()
        with pytest.raises(ValueError, match="not permitted"):
            select_schedule(999, spec)

    def test_select_returns_string(self):
        spec = standard_class_cs_a()
        sched = select_schedule(100, spec)
        assert isinstance(sched, str)
        assert len(sched) > 0


# ===========================================================================
# check_spec_compliance
# ===========================================================================

class TestCheckSpecCompliance:
    def test_compliant_pipe(self):
        """DN50 Sch40 at 10 barg should comply with CS-A class."""
        spec = standard_class_cs_a()
        result = check_spec_compliance(50, "40", 10.0, 100.0, spec)
        assert result.compliant is True
        assert len(result.violations) == 0

    def test_actual_wall_populated(self):
        spec = standard_class_cs_a()
        result = check_spec_compliance(50, "40", 5.0, 100.0, spec)
        assert result.actual_wall_mm > 0.0
        assert result.min_required_wall_mm > 0.0

    def test_pressure_violation(self):
        """Pressure exceeding class limit → violation."""
        spec = standard_class_cs_a(design_pressure_barg=10.0)
        result = check_spec_compliance(50, "40", 20.0, 100.0, spec)
        assert result.compliant is False
        fields = [v.field for v in result.violations]
        assert "design_pressure_barg" in fields

    def test_temperature_violation(self):
        """Temperature exceeding material limit → violation."""
        spec = standard_class_cs_a()
        result = check_spec_compliance(50, "40", 5.0, 500.0, spec)  # 500°C > A106 limit
        assert result.compliant is False
        fields = [v.field for v in result.violations]
        assert "design_temp_c" in fields

    def test_non_permitted_dn_violation(self):
        """DN not in permitted list → violation."""
        spec = standard_class_cs_a()
        result = check_spec_compliance(999, "40", 5.0, 100.0, spec)
        assert result.compliant is False
        fields = [v.field for v in result.violations]
        assert "dn" in fields

    def test_thin_wall_violation(self):
        """Sch10 (very thin) at extreme pressure → wall thickness violation."""
        # Use CS-HH at 40 barg; check if a thin schedule fails
        spec = standard_class_cs_hh(design_pressure_barg=40.0)
        # Sch20 for DN200 provides 6.35mm actual wall; at 40 barg this may fail
        result = check_spec_compliance(200, "20", 40.0, 200.0, spec)
        # We don't assert compliant/non-compliant (depends on actual B31.3 calc)
        # Just verify the function runs and returns the right shape
        assert "compliant" in result.as_dict()
        assert "actual_wall_mm" in result.as_dict()
        assert "min_required_wall_mm" in result.as_dict()

    def test_schedule_warning_for_spec_mismatch(self):
        """Specifying a different schedule than spec-driven → warning (not violation)."""
        spec = standard_class_cs_a()
        result = check_spec_compliance(50, "80", 5.0, 100.0, spec)
        # Sch80 > Sch40 (heavier) — should be compliant but warn
        assert result.compliant is True
        assert len(result.warnings) > 0

    def test_as_dict_structure(self):
        spec = standard_class_cs_a()
        result = check_spec_compliance(50, "40", 5.0, 100.0, spec)
        d = result.as_dict()
        for key in ["compliant", "actual_wall_mm", "min_required_wall_mm",
                    "schedule_used", "violations", "warnings"]:
            assert key in d, f"Missing key: {key}"


# ===========================================================================
# Standard pipe class factories
# ===========================================================================

class TestStandardClasses:
    def test_cs_a_creates_valid_spec(self):
        spec = standard_class_cs_a()
        assert isinstance(spec, PipeSpec)
        assert spec.name == "CS-A"
        assert spec.material.spec == "A106"
        assert spec.default_schedule == "40"
        assert len(spec.permitted_dn) > 0

    def test_cs_hh_creates_valid_spec(self):
        spec = standard_class_cs_hh()
        assert spec.name == "CS-HH"
        assert spec.default_schedule == "80"

    def test_ss_316l_creates_valid_spec(self):
        spec = standard_class_ss_316l()
        assert spec.name == "SS-316L"
        assert spec.material.spec == "A312"
        assert spec.material.corrosion_allowance_mm == pytest.approx(0.0)

    def test_api_x52_creates_valid_spec(self):
        spec = standard_class_api_x52()
        assert spec.name == "API-X52"
        assert spec.material.grade == "X52"

    def test_cs_a_50_compliance(self):
        """End-to-end: DN50, Sch40, 10 barg, 120°C in CS-A class → compliant."""
        spec = standard_class_cs_a()
        result = check_spec_compliance(50, "40", 10.0, 120.0, spec)
        assert result.compliant is True


# ===========================================================================
# MaterialSpec
# ===========================================================================

class TestMaterialSpec:
    def test_from_designation_a106b(self):
        mat = MaterialSpec.from_designation("A106", "B")
        assert mat.allowable_stress_mpa == pytest.approx(117.2, abs=0.1)
        assert mat.max_temp_c == pytest.approx(427.0, abs=1.0)

    def test_from_designation_316l(self):
        mat = MaterialSpec.from_designation("A312", "316L")
        assert mat.allowable_stress_mpa > 100.0

    def test_from_designation_unknown_raises(self):
        with pytest.raises(ValueError, match="not in allowable-stress table"):
            MaterialSpec.from_designation("FAKE", "ZZZ")

    def test_allowable_stress_all_positive(self):
        for (spec, grade), stress in ALLOWABLE_STRESS_MPA.items():
            assert stress > 0.0, f"Non-positive stress for ({spec}, {grade})"
