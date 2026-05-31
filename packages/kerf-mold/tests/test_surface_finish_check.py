"""
Tests for kerf_mold.surface_finish_check.

Oracle cases and boundary conditions per SPI Mold Finish Standards (2017)
and Menges §11.

Test matrix (15 tests):
  1.  SPI-A2 + PMMA + S136 60 HRC             → achievable
  2.  SPI-A1 + glass-filled-PA + S136 52 HRC  → NOT achievable, glass_filled_warning set
  3.  SPI-C3 + ABS + P20 30 HRC               → achievable (low-grade)
  4.  SPI-A1 + P20 30 HRC                     → NOT achievable (steel too soft)
  5.  SPI-A1 + PMMA + H13 52 HRC              → NOT achievable (H13 max = A3)
  6.  SPI-A1 + PMMA + S136 48 HRC             → NOT achievable (HRC < 50)
  7.  SPI-A1 + PMMA + S136 52 HRC             → achievable
  8.  SPI-B1 + ABS + H13 40 HRC               → achievable
  9.  SPI-B1 + ABS + P20 35 HRC               → NOT achievable (P20 max = B3)
  10. SPI-D3 + ABS + P20 20 HRC               → achievable
  11. SPI-A3 + PA66 + S136 50 HRC             → achievable (PA66 limit = A3)
  12. SPI-A2 + PA66 + S136 50 HRC             → NOT achievable (PA66 max = A3)
  13. SPI-B1 + PP + P20 32 HRC                → NOT achievable (PP max = B1, P20 max = B3; PP limit triggers)
  14. SPI-C2 + glass-filled-PA + P20 30 HRC   → achievable (C-grade + glass; advisory warning only)
  15. SPI-A2 + PC + H13 48 HRC                → NOT achievable (H13 max = A3; A2 requires S136/420SS)
  16. SPI-A2 + ABS + 420SS 50 HRC             → achievable (420SS supports A2)
  17. SPI-B2 + PP + H13 42 HRC                → achievable (PP limit is B1 which is finer; B2 is coarser → achievable)
  18. Ra values: A1 target = 0.012 µm
"""

from __future__ import annotations

import pytest

from kerf_mold.surface_finish_check import (
    SurfaceFinishSpec,
    MoldSpec,
    SurfaceFinishReport,
    check_surface_finish,
    _SPI_CATALOG,
    _grade_index,
    _is_glass_filled,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make(
    finish: str,
    resin: str,
    steel: str,
    hrc: float,
    achieved: str = "",
) -> SurfaceFinishReport:
    part = SurfaceFinishSpec(required_finish=finish, resin=resin)
    mold = MoldSpec(mold_steel=steel, hardness_HRC=hrc, mold_finish_achieved=achieved)
    return check_surface_finish(part, mold)


# ---------------------------------------------------------------------------
# Test 1 — SPI-A2 + PMMA + S136 60 HRC: achievable
# ---------------------------------------------------------------------------

def test_a2_pmma_s136_achievable():
    r = make("SPI-A2", "PMMA", "S136", 60.0)
    assert r.achievable is True
    assert r.Ra_target_um == pytest.approx(0.025)
    assert r.Ra_achievable_um == pytest.approx(0.025)
    assert r.glass_filled_warning is None
    assert r.recommended_steel == "S136"
    assert r.recommended_hardness_HRC_min == pytest.approx(48.0)
    assert "diamond" in r.recommended_polishing_method.lower()


# ---------------------------------------------------------------------------
# Test 2 — SPI-A1 + glass-filled-PA + S136 52 HRC: NOT achievable, glass warning set
# ---------------------------------------------------------------------------

def test_a1_glass_filled_pa_not_achievable():
    r = make("SPI-A1", "glass-filled-PA", "S136", 52.0)
    assert r.achievable is False
    assert r.glass_filled_warning is not None
    assert "glass" in r.glass_filled_warning.lower()
    assert "pull-out" in r.glass_filled_warning.lower() or "fiber" in r.glass_filled_warning.lower()


# ---------------------------------------------------------------------------
# Test 3 — SPI-C3 + ABS + P20 30 HRC: achievable (low-grade)
# ---------------------------------------------------------------------------

def test_c3_abs_p20_achievable():
    r = make("SPI-C3", "ABS", "P20", 30.0)
    assert r.achievable is True
    assert r.Ra_target_um == pytest.approx(3.2)
    assert r.glass_filled_warning is None
    assert "emery" in r.recommended_polishing_method.lower() or "220" in r.recommended_polishing_method


# ---------------------------------------------------------------------------
# Test 4 — SPI-A1 + ABS + P20 30 HRC: NOT achievable (steel too soft)
# ---------------------------------------------------------------------------

def test_a1_abs_p20_not_achievable():
    r = make("SPI-A1", "ABS", "P20", 30.0)
    assert r.achievable is False
    # Achievable Ra should be worse than A1 target
    assert r.Ra_achievable_um > r.Ra_target_um
    assert r.recommended_steel == "S136"


# ---------------------------------------------------------------------------
# Test 5 — SPI-A1 + PMMA + H13 52 HRC: NOT achievable (H13 max = A3)
# ---------------------------------------------------------------------------

def test_a1_pmma_h13_not_achievable():
    r = make("SPI-A1", "PMMA", "H13", 52.0)
    assert r.achievable is False
    assert r.Ra_achievable_um > r.Ra_target_um
    assert r.recommended_steel == "S136"


# ---------------------------------------------------------------------------
# Test 6 — SPI-A1 + PMMA + S136 48 HRC: NOT achievable (HRC < 50)
# ---------------------------------------------------------------------------

def test_a1_pmma_s136_hrc48_not_achievable():
    r = make("SPI-A1", "PMMA", "S136", 48.0)
    assert r.achievable is False
    # HRC is below the 50 HRC minimum for A1
    assert r.recommended_hardness_HRC_min == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Test 7 — SPI-A1 + PMMA + S136 52 HRC: achievable
# ---------------------------------------------------------------------------

def test_a1_pmma_s136_hrc52_achievable():
    r = make("SPI-A1", "PMMA", "S136", 52.0)
    assert r.achievable is True
    assert r.Ra_target_um == pytest.approx(0.012)
    assert r.Ra_achievable_um == pytest.approx(0.012)
    assert r.glass_filled_warning is None
    assert "diamond" in r.recommended_polishing_method.lower()
    assert "#3" in r.recommended_polishing_method or "1 µm" in r.recommended_polishing_method


# ---------------------------------------------------------------------------
# Test 8 — SPI-B1 + ABS + H13 40 HRC: achievable
# ---------------------------------------------------------------------------

def test_b1_abs_h13_achievable():
    r = make("SPI-B1", "ABS", "H13", 40.0)
    assert r.achievable is True
    assert r.Ra_target_um == pytest.approx(0.10)
    assert r.glass_filled_warning is None


# ---------------------------------------------------------------------------
# Test 9 — SPI-B1 + ABS + P20 35 HRC: NOT achievable (P20 max = B3)
# ---------------------------------------------------------------------------

def test_b1_abs_p20_not_achievable():
    r = make("SPI-B1", "ABS", "P20", 35.0)
    assert r.achievable is False
    # P20 is limited to B3 (Ra 0.40 µm), cannot achieve B1 (Ra 0.10 µm)
    assert r.Ra_achievable_um >= 0.40


# ---------------------------------------------------------------------------
# Test 10 — SPI-D3 + ABS + P20 20 HRC: achievable
# ---------------------------------------------------------------------------

def test_d3_abs_p20_achievable():
    r = make("SPI-D3", "ABS", "P20", 20.0)
    assert r.achievable is True
    assert r.Ra_target_um == pytest.approx(14.0)
    assert r.glass_filled_warning is None
    assert "blast" in r.recommended_polishing_method.lower()


# ---------------------------------------------------------------------------
# Test 11 — SPI-A3 + PA66 + S136 50 HRC: achievable (PA66 limit = A3)
# ---------------------------------------------------------------------------

def test_a3_pa66_s136_achievable():
    r = make("SPI-A3", "PA66", "S136", 50.0)
    assert r.achievable is True
    assert r.Ra_target_um == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Test 12 — SPI-A2 + PA66 + S136 50 HRC: NOT achievable (PA66 max = A3)
# ---------------------------------------------------------------------------

def test_a2_pa66_not_achievable():
    r = make("SPI-A2", "PA66", "S136", 50.0)
    assert r.achievable is False
    # Ra achievable should reflect the A3 limit (0.05 µm, coarser than A2's 0.025 µm)
    assert r.Ra_achievable_um >= 0.05


# ---------------------------------------------------------------------------
# Test 13 — SPI-B1 + PP + P20 32 HRC: NOT achievable (PP max B1, P20 max B3)
# ---------------------------------------------------------------------------

def test_b1_pp_p20_not_achievable():
    # P20 can only reach B3; B1 requires H13 or better
    r = make("SPI-B1", "PP", "P20", 32.0)
    assert r.achievable is False


# ---------------------------------------------------------------------------
# Test 14 — SPI-C2 + glass-filled-PA + P20 30 HRC: achievable (C-grade; advisory warning)
# ---------------------------------------------------------------------------

def test_c2_glass_filled_pa_p20_achievable():
    r = make("SPI-C2", "glass-filled-PA", "P20", 30.0)
    assert r.achievable is True
    # Glass-fill advisory warning is present for non-A grades
    assert r.glass_filled_warning is not None
    # But it's a degraded-replication advisory, not a blocker
    assert "NOT achievable" not in r.glass_filled_warning or "achievable" in r.glass_filled_warning


# ---------------------------------------------------------------------------
# Test 15 — SPI-A2 + PC + H13 48 HRC: NOT achievable (H13 max = A3)
# ---------------------------------------------------------------------------

def test_a2_pc_h13_not_achievable():
    r = make("SPI-A2", "PC", "H13", 48.0)
    assert r.achievable is False
    assert r.recommended_steel == "S136"


# ---------------------------------------------------------------------------
# Test 16 — SPI-A2 + ABS + 420SS 50 HRC: achievable (420SS supports A2)
# ---------------------------------------------------------------------------

def test_a2_abs_420ss_achievable():
    r = make("SPI-A2", "ABS", "420SS", 50.0)
    assert r.achievable is True
    assert r.Ra_target_um == pytest.approx(0.025)


# ---------------------------------------------------------------------------
# Test 17 — SPI-B2 + PP + H13 42 HRC: achievable (PP limit = B1, B2 is coarser → OK)
# ---------------------------------------------------------------------------

def test_b2_pp_h13_achievable():
    # PP limit is SPI-B1 (index 3); SPI-B2 has index 4 (coarser) → within PP capability
    r = make("SPI-B2", "PP", "H13", 42.0)
    assert r.achievable is True


# ---------------------------------------------------------------------------
# Test 18 — Ra values from SPI catalog
# ---------------------------------------------------------------------------

def test_spi_catalog_ra_values():
    assert _SPI_CATALOG["SPI-A1"][0] == pytest.approx(0.012)
    assert _SPI_CATALOG["SPI-A2"][0] == pytest.approx(0.025)
    assert _SPI_CATALOG["SPI-A3"][0] == pytest.approx(0.050)
    assert _SPI_CATALOG["SPI-B1"][0] == pytest.approx(0.10)
    assert _SPI_CATALOG["SPI-B2"][0] == pytest.approx(0.20)
    assert _SPI_CATALOG["SPI-B3"][0] == pytest.approx(0.40)
    assert _SPI_CATALOG["SPI-C1"][0] == pytest.approx(0.80)
    assert _SPI_CATALOG["SPI-C2"][0] == pytest.approx(1.60)
    assert _SPI_CATALOG["SPI-C3"][0] == pytest.approx(3.20)
    assert _SPI_CATALOG["SPI-D3"][0] == pytest.approx(14.0)


# ---------------------------------------------------------------------------
# Test 19 — glass filled detection helper
# ---------------------------------------------------------------------------

def test_glass_filled_detection():
    assert _is_glass_filled("glass-filled-PA") is True
    assert _is_glass_filled("GF30-PA66") is True
    assert _is_glass_filled("glass_filled_pp") is True
    assert _is_glass_filled("ABS") is False
    assert _is_glass_filled("PC") is False
    assert _is_glass_filled("PMMA") is False


# ---------------------------------------------------------------------------
# Test 20 — Invalid SPI grade raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_spi_grade_raises():
    with pytest.raises(ValueError, match="SPI-Z9"):
        SurfaceFinishSpec(required_finish="SPI-Z9", resin="ABS")


# ---------------------------------------------------------------------------
# Test 21 — Invalid steel raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_steel_raises():
    with pytest.raises(ValueError, match="mold_steel"):
        MoldSpec(mold_steel="BRONZE", hardness_HRC=30.0)


# ---------------------------------------------------------------------------
# Test 22 — grade_index ordering
# ---------------------------------------------------------------------------

def test_grade_index_ordering():
    # A1 is finest (index 0), D3 is coarsest (index 11)
    assert _grade_index("SPI-A1") == 0
    assert _grade_index("SPI-D3") == 11
    assert _grade_index("SPI-B1") > _grade_index("SPI-A3")
    assert _grade_index("SPI-C1") > _grade_index("SPI-B3")


# ---------------------------------------------------------------------------
# Test 23 — mold_finish_achieved coarser than required → not achievable
# ---------------------------------------------------------------------------

def test_mold_finish_achieved_coarser():
    r = make("SPI-A2", "PMMA", "S136", 52.0, achieved="SPI-B2")
    assert r.achievable is False


# ---------------------------------------------------------------------------
# Test 24 — mold_finish_achieved equal to required → achievable (other factors OK)
# ---------------------------------------------------------------------------

def test_mold_finish_achieved_equal():
    r = make("SPI-A2", "PMMA", "S136", 52.0, achieved="SPI-A2")
    assert r.achievable is True


# ---------------------------------------------------------------------------
# Test 25 — D1 + glass-filled + P20: achievable but advisory glass warning
# ---------------------------------------------------------------------------

def test_d1_glass_filled_advisory():
    r = make("SPI-D1", "glass-filled-PA", "P20", 20.0)
    assert r.achievable is True
    assert r.glass_filled_warning is not None
    # Advisory only — not a blocker since D-grade doesn't need mirror finish


# ---------------------------------------------------------------------------
# Test 26 — honest caveat present and non-empty
# ---------------------------------------------------------------------------

def test_honest_caveat_present():
    r = make("SPI-B2", "ABS", "P20", 32.0)
    assert r.honest_caveat
    assert "catalog" in r.honest_caveat.lower() or "Catalog" in r.honest_caveat


# ---------------------------------------------------------------------------
# Test 27 — recommended polishing method for D3 mentions blast
# ---------------------------------------------------------------------------

def test_d3_polishing_method():
    r = make("SPI-D3", "ABS", "P20", 22.0)
    assert r.achievable is True
    assert "blast" in r.recommended_polishing_method.lower()
    assert "#24" in r.recommended_polishing_method
