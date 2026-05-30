"""test_shell_wall_check.py — BREP-SHELL-WALL-CHECK hermetic oracle tests.

Oracle specification:
  1. Uniform 2mm wall + ABS injection moulding → all faces PASS
     (Menges 2001 Table 3.3: ABS t_min=1.5, t_max=4.0).
  2. 0.5mm wall + ABS injection moulding → faces FAIL (thin violation).
  3. 0.5mm wall + FDM 0.4mm nozzle → faces PASS (0.5 > 0.4mm nozzle).
  4. 0.2mm wall + FDM 0.4mm nozzle → faces FAIL (thin violation).
  5. 6mm wall + ABS injection → thick violation (6 > 4mm spec_max).
  6. Menges Table 3.3 oracle: PP t_min=0.8, PC t_min=1.2, LCP t_min=0.5.
  7. Flow-length correction: 100mm flow + ABS → t_min=1.5+0.5=2.0mm.
  8. Sheet-metal aluminium: t=0.5mm → pass; t=0.2mm → thin violation.
  9. SLA process: 0.1mm min; 0.05mm wall → fail; 0.15mm wall → pass.
 10. Unknown material → conservative fallback; all_pass shape-dependent.
 11. ShellWallReport fields: process, material, spec_min_mm, spec_max_mm
     summary, notes, per_face_results populated.

All tests are hermetic (no external files, no server, no GPU).
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.geom.brep import make_box
from kerf_cad_core.geom.solid_features import shell_body
from kerf_cad_core.geom.shell_wall_check import (
    check_shell_walls,
    ShellWallReport,
    FaceWallResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _box_shell(wall_mm: float, side: float = 20.0):
    """Return a hollow box body with uniform *wall_mm* thickness."""
    solid = make_box(origin=(0.0, 0.0, 0.0), size=(side, side, side))
    result = shell_body(solid, wall_mm)
    assert result["ok"], f"shell_body failed: {result.get('reason')}"
    return result["body"]


# ---------------------------------------------------------------------------
# 1. Uniform 2mm wall + ABS injection → PASS
# ---------------------------------------------------------------------------

def test_uniform_2mm_abs_injection_pass():
    body = _box_shell(2.0)
    report = check_shell_walls(body, process="injection_molding", material="ABS",
                                n_samples=500, seed=42)
    assert isinstance(report, ShellWallReport)
    assert report.all_pass, (
        f"Expected PASS for 2mm ABS injection; got: {report.summary}"
    )
    assert report.spec_min_mm == pytest.approx(1.5, abs=0.01)
    assert report.spec_max_mm == pytest.approx(4.0, abs=0.01)
    assert len(report.violations_thin) == 0
    assert len(report.violations_thick) == 0
    assert report.global_min_mm > 1.4  # measured ~2mm


# ---------------------------------------------------------------------------
# 2. 0.5mm wall + ABS injection → FAIL (thin)
# ---------------------------------------------------------------------------

def test_thin_0p5mm_abs_injection_fail():
    body = _box_shell(0.5)
    report = check_shell_walls(body, process="injection_molding", material="ABS",
                                n_samples=500, seed=42)
    assert not report.all_pass, (
        f"Expected FAIL for 0.5mm ABS injection; got: {report.summary}"
    )
    assert len(report.violations_thin) > 0, "Expected thin violations"
    # All violation entries should be THIN
    for v in report.violations_thin:
        assert v.measured_min_mm < report.spec_min_mm


# ---------------------------------------------------------------------------
# 3. 0.5mm wall + FDM 0.4mm nozzle → PASS
# ---------------------------------------------------------------------------

def test_0p5mm_wall_fdm_pass():
    body = _box_shell(0.5)
    report = check_shell_walls(body, process="fdm", material="PLA",
                                n_samples=300, seed=42)
    assert report.spec_min_mm == pytest.approx(0.4, abs=0.01)
    assert report.spec_max_mm is None  # no upper limit for additive
    assert report.all_pass, (
        f"Expected PASS for 0.5mm FDM; got: {report.summary}"
    )


# ---------------------------------------------------------------------------
# 4. 0.2mm wall + FDM 0.4mm nozzle → FAIL (thin)
# ---------------------------------------------------------------------------

def test_0p2mm_wall_fdm_fail():
    body = _box_shell(0.2, side=10.0)
    report = check_shell_walls(body, process="fdm", material="PLA",
                                n_samples=300, seed=42)
    assert not report.all_pass, (
        f"Expected FAIL for 0.2mm FDM; got: {report.summary}"
    )
    assert len(report.violations_thin) > 0


# ---------------------------------------------------------------------------
# 5. 6mm wall + ABS injection → THICK violation
# ---------------------------------------------------------------------------

def test_thick_6mm_abs_injection_fail():
    body = _box_shell(6.0, side=40.0)
    report = check_shell_walls(body, process="injection_molding", material="ABS",
                                n_samples=400, seed=42)
    assert not report.all_pass, (
        f"Expected FAIL for 6mm ABS injection (thick); got: {report.summary}"
    )
    assert len(report.violations_thick) > 0


# ---------------------------------------------------------------------------
# 6. Menges 2001 Table 3.3 oracle — spec limits per material
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("material,expected_tmin,expected_tmax", [
    ("PP",  0.8, 3.8),
    ("PC",  1.2, 4.0),
    ("LCP", 0.5, 3.0),
    ("PVC", 2.0, 5.0),
    ("POM", 0.8, 3.5),
    ("PEEK",1.5, 4.5),
])
def test_menges_table_3_3_oracle(material, expected_tmin, expected_tmax):
    """Oracle: spec limits match Menges 2001 Table 3.3."""
    body = _box_shell(2.0)
    report = check_shell_walls(body, process="injection_molding", material=material,
                                n_samples=200, seed=42)
    assert report.spec_min_mm == pytest.approx(expected_tmin, abs=0.01), (
        f"{material} t_min: expected {expected_tmin}, got {report.spec_min_mm}"
    )
    assert report.spec_max_mm == pytest.approx(expected_tmax, abs=0.01), (
        f"{material} t_max: expected {expected_tmax}, got {report.spec_max_mm}"
    )


# ---------------------------------------------------------------------------
# 7. Flow-length correction: 100mm flow + ABS → t_min raised by 0.5mm
# ---------------------------------------------------------------------------

def test_flow_length_correction_abs():
    """Menges 2001 §3.3: +0.5mm per 100mm flow path."""
    body = _box_shell(2.0)
    report_no_flow = check_shell_walls(
        body, process="injection_molding", material="ABS",
        flow_length_mm=0.0, n_samples=200, seed=42
    )
    report_100mm = check_shell_walls(
        body, process="injection_molding", material="ABS",
        flow_length_mm=100.0, n_samples=200, seed=42
    )
    # Base ABS: 1.5mm; +0.5 for 100mm flow → 2.0mm
    assert report_no_flow.spec_min_mm == pytest.approx(1.5, abs=0.01)
    assert report_100mm.spec_min_mm == pytest.approx(2.0, abs=0.01)
    # 2mm wall exactly at the corrected minimum — may pass or fail but
    # corrected spec must be strictly higher than uncorrected.
    assert report_100mm.spec_min_mm > report_no_flow.spec_min_mm
    # Flow-length note in notes
    note_text = " ".join(report_100mm.notes)
    assert "flow" in note_text.lower() or "correction" in note_text.lower()


# ---------------------------------------------------------------------------
# 8. Sheet metal aluminium: t=0.5mm → pass; t=0.2mm → thin
# ---------------------------------------------------------------------------

def test_sheet_metal_aluminium_pass():
    body = _box_shell(0.5)
    report = check_shell_walls(body, process="sheet_metal", material="aluminium",
                                n_samples=300, seed=42)
    assert report.spec_min_mm == pytest.approx(0.3, abs=0.01)
    assert report.spec_max_mm == pytest.approx(6.0, abs=0.01)
    assert report.all_pass, f"Expected PASS for 0.5mm aluminium sheet metal; got: {report.summary}"


def test_sheet_metal_thin_fail():
    body = _box_shell(0.2, side=10.0)
    report = check_shell_walls(body, process="sheet_metal", material="aluminium",
                                n_samples=300, seed=42)
    assert not report.all_pass, f"Expected FAIL for 0.2mm sheet metal; got: {report.summary}"
    assert len(report.violations_thin) > 0


# ---------------------------------------------------------------------------
# 9. SLA process: spec_min=0.1mm; thin if <0.1mm
# ---------------------------------------------------------------------------

def test_sla_spec_min():
    body = _box_shell(0.5)
    report = check_shell_walls(body, process="sla", material="resin",
                                n_samples=200, seed=42)
    assert report.spec_min_mm == pytest.approx(0.1, abs=0.01)
    assert report.spec_max_mm is None
    assert report.all_pass, f"Expected PASS for 0.5mm SLA; got: {report.summary}"


# ---------------------------------------------------------------------------
# 10. Unknown material falls back to ABS-conservative spec; no crash
# ---------------------------------------------------------------------------

def test_unknown_material_no_crash():
    body = _box_shell(2.0)
    report = check_shell_walls(body, process="injection_molding",
                                material="unobtainium_xk99",
                                n_samples=200, seed=42)
    # Should return a report with some conservative spec_min (≥ 0)
    assert report.spec_min_mm > 0.0
    assert isinstance(report.summary, str)
    assert any("not in" in n or "conservative" in n.lower() for n in report.notes)


# ---------------------------------------------------------------------------
# 11. ShellWallReport structure completeness
# ---------------------------------------------------------------------------

def test_report_structure():
    body = _box_shell(2.0)
    report = check_shell_walls(body, process="injection_molding", material="ABS",
                                n_samples=300, seed=42)
    # All required fields populated
    assert report.process == "injection_molding"
    assert report.material == "ABS"
    assert isinstance(report.per_face_results, list)
    assert len(report.per_face_results) > 0
    assert isinstance(report.summary, str) and len(report.summary) > 0
    assert isinstance(report.notes, list) and len(report.notes) > 0
    assert report.global_min_mm > 0.0
    assert report.global_max_mm >= report.global_min_mm
    # Each FaceWallResult has required fields
    for fr in report.per_face_results:
        assert isinstance(fr, FaceWallResult)
        assert isinstance(fr.face_id, int)
        assert fr.spec_min_mm > 0.0


# ---------------------------------------------------------------------------
# 12. FDM nozzle override: 0.6mm nozzle → 0.5mm wall fails
# ---------------------------------------------------------------------------

def test_fdm_nozzle_override():
    body = _box_shell(0.5)
    report = check_shell_walls(body, process="fdm", material="PLA",
                                nozzle_diameter_mm=0.6,
                                n_samples=300, seed=42)
    assert report.spec_min_mm == pytest.approx(0.6, abs=0.01)
    assert not report.all_pass, "0.5mm wall < 0.6mm nozzle override → FAIL"
    assert len(report.violations_thin) > 0


# ---------------------------------------------------------------------------
# 13. Injection molding + PP: 1mm wall passes (>0.8 min), 0.5mm fails
# ---------------------------------------------------------------------------

def test_pp_injection_1mm_pass():
    body = _box_shell(1.0)
    report = check_shell_walls(body, process="injection_molding", material="PP",
                                n_samples=300, seed=42)
    assert report.spec_min_mm == pytest.approx(0.8, abs=0.01)
    assert report.all_pass, f"Expected 1mm PP to pass (min=0.8mm); got: {report.summary}"


def test_pp_injection_0p5mm_fails():
    body = _box_shell(0.5)
    report = check_shell_walls(body, process="injection_molding", material="PP",
                                n_samples=300, seed=42)
    assert not report.all_pass, f"Expected 0.5mm PP to fail (min=0.8mm); got: {report.summary}"
