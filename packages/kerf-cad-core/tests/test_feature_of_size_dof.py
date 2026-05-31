"""
Tests for kerf_cad_core.gdt.feature_of_size_dof

ASME Y14.5-2018 §4.7 + §7.3 Feature of Size (FOS) DOF enumerator.

Pure-Python, hermetic — no OCC, no DB, no registry required.
"""
from __future__ import annotations

import pytest

from kerf_cad_core.gdt.feature_of_size_dof import (
    FOSSpec,
    FOSDoFReport,
    compute_fos_dof,
)
# Re-export path
from kerf_cad_core.gdt import FOSSpec as FOSSpecAlias, compute_fos_dof as compute_fos_dof_alias


# ---------------------------------------------------------------------------
# FOSSpec construction + validation
# ---------------------------------------------------------------------------

class TestFOSSpecConstruction:
    def test_valid_cylinder_position(self):
        fos = FOSSpec(feature_type="cylinder", tolerance_symbol="position")
        assert fos.feature_type == "cylinder"
        assert fos.tolerance_symbol == "position"

    def test_normalises_case(self):
        fos = FOSSpec(feature_type="CYLINDER", tolerance_symbol="POSITION")
        assert fos.feature_type == "cylinder"
        assert fos.tolerance_symbol == "position"

    def test_normalises_strip_whitespace(self):
        fos = FOSSpec(feature_type="  hole  ", tolerance_symbol="  parallelism  ")
        assert fos.feature_type == "hole"
        assert fos.tolerance_symbol == "parallelism"

    def test_invalid_feature_type_raises(self):
        with pytest.raises(ValueError, match="feature_type"):
            FOSSpec(feature_type="cone", tolerance_symbol="position")

    def test_invalid_tolerance_symbol_raises(self):
        with pytest.raises(ValueError, match="tolerance_symbol"):
            FOSSpec(feature_type="cylinder", tolerance_symbol="flatness")

    def test_to_dict_round_trip(self):
        fos = FOSSpec(feature_type="sphere", tolerance_symbol="position")
        d = fos.to_dict()
        fos2 = FOSSpec.from_dict(d)
        assert fos2.feature_type == "sphere"
        assert fos2.tolerance_symbol == "position"

    def test_width_synonym_valid(self):
        fos = FOSSpec(feature_type="width", tolerance_symbol="perpendicularity")
        assert fos.feature_type == "width"


# ---------------------------------------------------------------------------
# Cylinder / Hole DOF rules (ASME Y14.5-2018 §4.7 + §7.3)
# ---------------------------------------------------------------------------

class TestCylinderDOF:
    def test_cylinder_position_constrains_TX_TY(self):
        """Cylinder + position: axis location constrains 2 radial translations."""
        fos = FOSSpec(feature_type="cylinder", tolerance_symbol="position")
        report = compute_fos_dof(fos)
        assert set(report.dof_constrained) == {"TX", "TY"}
        assert set(report.dof_released) == {"TZ", "RX", "RY", "RZ"}
        assert report.total_constrained == 2

    def test_hole_position_identical_to_cylinder(self):
        """Hole is a cylindrical FOS — same DOF model as cylinder."""
        fos_cyl = FOSSpec(feature_type="cylinder", tolerance_symbol="position")
        fos_hole = FOSSpec(feature_type="hole", tolerance_symbol="position")
        r_cyl = compute_fos_dof(fos_cyl)
        r_hole = compute_fos_dof(fos_hole)
        assert r_cyl.dof_constrained == r_hole.dof_constrained
        assert r_cyl.dof_released == r_hole.dof_released

    def test_cylinder_perpendicularity_constrains_RX_RY(self):
        """Cylinder + perpendicularity: axis tilt constrains 2 rotation DOFs."""
        fos = FOSSpec(feature_type="cylinder", tolerance_symbol="perpendicularity")
        report = compute_fos_dof(fos)
        assert set(report.dof_constrained) == {"RX", "RY"}
        assert set(report.dof_released) == {"TX", "TY", "TZ", "RZ"}
        assert report.total_constrained == 2

    def test_cylinder_parallelism_constrains_RX_RY(self):
        """Parallelism controls axis orientation (identical DOFs to perpendicularity)."""
        fos = FOSSpec(feature_type="cylinder", tolerance_symbol="parallelism")
        report = compute_fos_dof(fos)
        assert set(report.dof_constrained) == {"RX", "RY"}
        assert report.total_constrained == 2

    def test_cylinder_angularity_constrains_RX_RY(self):
        """Angularity controls axis orientation at a specified angle."""
        fos = FOSSpec(feature_type="cylinder", tolerance_symbol="angularity")
        report = compute_fos_dof(fos)
        assert set(report.dof_constrained) == {"RX", "RY"}

    def test_cylinder_runout_constrains_4_dof(self):
        """Runout couples radial location + axis tilt (§7.3.4) → 4 DOFs."""
        fos = FOSSpec(feature_type="cylinder", tolerance_symbol="runout")
        report = compute_fos_dof(fos)
        assert set(report.dof_constrained) == {"TX", "TY", "RX", "RY"}
        assert report.total_constrained == 4

    def test_cylinder_total_runout_same_as_runout(self):
        """Total runout has the same DOF coupling as runout (§7.3.5)."""
        fos = FOSSpec(feature_type="cylinder", tolerance_symbol="total_runout")
        report = compute_fos_dof(fos)
        assert set(report.dof_constrained) == {"TX", "TY", "RX", "RY"}
        assert report.total_constrained == 4


# ---------------------------------------------------------------------------
# Sphere DOF rules (ASME Y14.5-2018 §7.3 — point FOS)
# ---------------------------------------------------------------------------

class TestSphereDOF:
    def test_sphere_position_constrains_TX_TY_TZ(self):
        """Sphere + position: all three translation DOFs constrained (point location)."""
        fos = FOSSpec(feature_type="sphere", tolerance_symbol="position")
        report = compute_fos_dof(fos)
        assert set(report.dof_constrained) == {"TX", "TY", "TZ"}
        assert set(report.dof_released) == {"RX", "RY", "RZ"}
        assert report.total_constrained == 3

    def test_sphere_perpendicularity_no_dofs(self):
        """Orientation tolerances on a sphere constrain nothing (rotationally symmetric)."""
        fos = FOSSpec(feature_type="sphere", tolerance_symbol="perpendicularity")
        report = compute_fos_dof(fos)
        assert report.dof_constrained == []
        assert report.total_constrained == 0
        assert len(report.dof_released) == 6

    def test_sphere_parallelism_no_dofs(self):
        fos = FOSSpec(feature_type="sphere", tolerance_symbol="parallelism")
        report = compute_fos_dof(fos)
        assert report.dof_constrained == []
        assert report.total_constrained == 0

    def test_sphere_runout_no_dofs(self):
        """Runout is not meaningful on a sphere."""
        fos = FOSSpec(feature_type="sphere", tolerance_symbol="runout")
        report = compute_fos_dof(fos)
        assert report.dof_constrained == []
        assert report.total_constrained == 0


# ---------------------------------------------------------------------------
# Slot / Planar pair / Width DOF rules (ASME Y14.5-2018 §7.3 — centre-plane FOS)
# ---------------------------------------------------------------------------

class TestSlotPlanarDOF:
    def test_slot_position_constrains_TX(self):
        """Slot + position: constrains TX (perpendicular to centre-plane)."""
        fos = FOSSpec(feature_type="slot", tolerance_symbol="position")
        report = compute_fos_dof(fos)
        assert set(report.dof_constrained) == {"TX"}
        assert report.total_constrained == 1
        assert "TY" in report.dof_released
        assert "TZ" in report.dof_released

    def test_planar_pair_parallelism_constrains_RX_RY(self):
        """Planar pair + parallelism: constrains RX and RY (wall orientation)."""
        fos = FOSSpec(feature_type="planar_pair", tolerance_symbol="parallelism")
        report = compute_fos_dof(fos)
        assert set(report.dof_constrained) == {"RX", "RY"}
        assert report.total_constrained == 2

    def test_planar_pair_perpendicularity_constrains_RX_RY(self):
        """Planar pair + perpendicularity: same orientation DOFs as parallelism."""
        fos = FOSSpec(feature_type="planar_pair", tolerance_symbol="perpendicularity")
        report = compute_fos_dof(fos)
        assert set(report.dof_constrained) == {"RX", "RY"}

    def test_width_synonym_same_as_slot(self):
        """'width' is a synonym for 'slot' — same DOF results."""
        fos_slot = FOSSpec(feature_type="slot", tolerance_symbol="position")
        fos_width = FOSSpec(feature_type="width", tolerance_symbol="position")
        r_slot = compute_fos_dof(fos_slot)
        r_width = compute_fos_dof(fos_width)
        assert r_slot.dof_constrained == r_width.dof_constrained
        assert r_slot.dof_released == r_width.dof_released

    def test_slot_runout_no_dofs(self):
        """Runout is not a standard callout on slots — returns no constrained DOFs."""
        fos = FOSSpec(feature_type="slot", tolerance_symbol="runout")
        report = compute_fos_dof(fos)
        assert report.dof_constrained == []
        assert report.total_constrained == 0


# ---------------------------------------------------------------------------
# Report structure assertions
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_total_dof_always_6(self):
        """dof_constrained + dof_released must always sum to 6."""
        cases = [
            ("cylinder", "position"),
            ("cylinder", "perpendicularity"),
            ("cylinder", "runout"),
            ("hole", "position"),
            ("sphere", "position"),
            ("sphere", "perpendicularity"),
            ("slot", "position"),
            ("planar_pair", "parallelism"),
        ]
        for ft, ts in cases:
            fos = FOSSpec(feature_type=ft, tolerance_symbol=ts)
            report = compute_fos_dof(fos)
            total = len(report.dof_constrained) + len(report.dof_released)
            assert total == 6, f"Expected 6 total DOF for {ft}+{ts}, got {total}"

    def test_no_overlap_constrained_released(self):
        """No DOF should appear in both constrained and released."""
        cases = [
            ("cylinder", "position"),
            ("cylinder", "total_runout"),
            ("sphere", "position"),
            ("slot", "perpendicularity"),
        ]
        for ft, ts in cases:
            fos = FOSSpec(feature_type=ft, tolerance_symbol=ts)
            report = compute_fos_dof(fos)
            overlap = set(report.dof_constrained) & set(report.dof_released)
            assert overlap == set(), f"Overlap for {ft}+{ts}: {overlap}"

    def test_constrained_list_sorted(self):
        """dof_constrained should be lexicographically sorted."""
        fos = FOSSpec(feature_type="cylinder", tolerance_symbol="runout")
        report = compute_fos_dof(fos)
        assert report.dof_constrained == sorted(report.dof_constrained)

    def test_total_constrained_matches_list_length(self):
        fos = FOSSpec(feature_type="cylinder", tolerance_symbol="position")
        report = compute_fos_dof(fos)
        assert report.total_constrained == len(report.dof_constrained)

    def test_datum_required_count_positive(self):
        """All tolerance symbols should report a positive datum_required_count."""
        from kerf_cad_core.gdt.feature_of_size_dof import _VALID_TOLERANCE_SYMBOLS
        for ts in _VALID_TOLERANCE_SYMBOLS:
            fos = FOSSpec(feature_type="cylinder", tolerance_symbol=ts)
            report = compute_fos_dof(fos)
            assert report.datum_required_count >= 1, f"Unexpected 0 for {ts}"

    def test_code_section_references_Y14_5(self):
        fos = FOSSpec(feature_type="cylinder", tolerance_symbol="position")
        report = compute_fos_dof(fos)
        assert "Y14.5" in report.code_section

    def test_honest_caveat_non_empty(self):
        fos = FOSSpec(feature_type="hole", tolerance_symbol="parallelism")
        report = compute_fos_dof(fos)
        assert len(report.honest_caveat) > 20

    def test_to_dict_all_keys_present(self):
        fos = FOSSpec(feature_type="sphere", tolerance_symbol="position")
        report = compute_fos_dof(fos)
        d = report.to_dict()
        for key in (
            "dof_constrained",
            "dof_released",
            "total_constrained",
            "datum_required_count",
            "code_section",
            "honest_caveat",
        ):
            assert key in d, f"Missing key '{key}' in to_dict() output"


# ---------------------------------------------------------------------------
# compute_fos_dof guard
# ---------------------------------------------------------------------------

class TestComputeFosDofGuard:
    def test_raises_on_non_fosspec(self):
        with pytest.raises(ValueError, match="FOSSpec"):
            compute_fos_dof({"feature_type": "cylinder", "tolerance_symbol": "position"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Re-export from gdt package
# ---------------------------------------------------------------------------

class TestReExport:
    def test_fosspec_importable_from_gdt(self):
        assert FOSSpecAlias is FOSSpec

    def test_compute_importable_from_gdt(self):
        assert compute_fos_dof_alias is compute_fos_dof

    def test_fos_dof_report_importable(self):
        from kerf_cad_core.gdt import FOSDoFReport as FDR
        assert FDR is FOSDoFReport
