"""
Tests for GK-P17: sheetmetal_features.py

SheetMetalPart / FlatPatternResult / compute_flat_pattern

All tests are hermetic — no DB, no OCCT, no kerf_chat runtime.
Formula reference: Suchy "Handbook of Die Design" §3 + DIN 6935.

  BA   = (π·θ/180)·(r + K·t)
  OSSB = (r + t)·tan(θ/2)
  BD   = 2·OSSB − BA
  flat = Σflange_lengths − ΣBD
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.sheetmetal_features import (
    SheetMetalPart,
    FlatPatternResult,
    compute_flat_pattern,
    _k_factor_from_r_over_t,
    _resolve_material,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _k_expected(r_over_t: float, k_min: float, k_max: float) -> float:
    """Reproduce the interpolation formula for cross-check."""
    if r_over_t < 1.0:
        return k_min
    if r_over_t >= 3.0:
        return k_max
    t = (r_over_t - 1.0) / 2.0
    return k_min + t * (k_max - k_min)


# ===========================================================================
# 1. K-factor interpolation unit tests
# ===========================================================================

def test_k_factor_severe_bend_below_1():
    """r/t = 0.5 → K = k_min (severe bend zone)."""
    k = _k_factor_from_r_over_t(0.5, 0.33, 0.44)
    assert k == pytest.approx(0.33, abs=1e-9)


def test_k_factor_gentle_bend_at_3():
    """r/t = 3.0 → K = k_max (gentle bend zone boundary)."""
    k = _k_factor_from_r_over_t(3.0, 0.33, 0.44)
    assert k == pytest.approx(0.44, abs=1e-9)


def test_k_factor_transition_midpoint():
    """r/t = 2.0 → K = midpoint of (k_min, k_max)."""
    k = _k_factor_from_r_over_t(2.0, 0.33, 0.44)
    expected = 0.33 + 0.5 * (0.44 - 0.33)
    assert k == pytest.approx(expected, abs=1e-9)


def test_k_factor_r_over_t_exactly_1():
    """r/t = 1.0 → K = k_min (start of transition)."""
    k = _k_factor_from_r_over_t(1.0, 0.33, 0.44)
    assert k == pytest.approx(0.33, abs=1e-9)


def test_k_factor_above_3():
    """r/t = 5.0 → K = k_max."""
    k = _k_factor_from_r_over_t(5.0, 0.31, 0.38)
    assert k == pytest.approx(0.38, abs=1e-9)


# ===========================================================================
# 2. Material alias resolution
# ===========================================================================

def test_resolve_material_canonical():
    assert _resolve_material("steel-cold-rolled") == "steel-cold-rolled"


def test_resolve_material_alias_steel():
    assert _resolve_material("steel") == "steel-cold-rolled"


def test_resolve_material_alias_stainless():
    assert _resolve_material("stainless") == "stainless-304"


def test_resolve_material_alias_aluminum():
    assert _resolve_material("aluminum-5052") == "aluminum-5052"


def test_resolve_material_unknown():
    assert _resolve_material("unobtanium") is None


# ===========================================================================
# 3. Single 90° bend — L-bracket 50+50 mm (r=2mm, t=1mm, r/t=2)
# ===========================================================================
# r/t = 2 → K = 0.33 + (2-1)/2 * (0.44-0.33) = 0.33 + 0.5*0.11 = 0.385
# BA = (π/2) * (2 + 0.385*1) = (π/2) * 2.385 ≈ 3.7462 mm
# OSSB = (2+1)*tan(45°) = 3*1 = 3.0 mm
# BD = 2*3 - 3.7462 = 2.2538 mm
# flat = (50+50) - 2.2538 = 97.7462 mm

def test_single_90deg_bend_k_approx_0385():
    """r/t=2 → K ≈ 0.385 (midpoint of mild-steel transition)."""
    part = SheetMetalPart(
        material="steel-cold-rolled",
        thickness_mm=1.0,
        length_mm=52.0,
        width_mm=30.0,
        bend_radius_mm=2.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[50.0, 50.0],
    )
    result = compute_flat_pattern(part)
    # K at r/t=2: 0.33 + 0.5*(0.44-0.33) = 0.385
    assert result.k_factor == pytest.approx(0.385, abs=1e-4)


def test_single_90deg_bend_allowance():
    """BA ≈ (π/2)·(2 + 0.385·1) = (π/2)·2.385."""
    part = SheetMetalPart(
        material="steel-cold-rolled",
        thickness_mm=1.0,
        length_mm=52.0,
        width_mm=30.0,
        bend_radius_mm=2.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[50.0, 50.0],
    )
    result = compute_flat_pattern(part)
    k = 0.385
    expected_ba = (math.pi / 2.0) * (2.0 + k * 1.0)
    assert result.bend_allowances_mm[0] == pytest.approx(expected_ba, rel=1e-4)


def test_single_90deg_bend_num_bends():
    part = SheetMetalPart(
        material="steel-cold-rolled",
        thickness_mm=1.0,
        length_mm=52.0,
        width_mm=30.0,
        bend_radius_mm=2.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[50.0, 50.0],
    )
    result = compute_flat_pattern(part)
    assert result.num_bends == 1


def test_single_90deg_flat_length():
    """flat_length = 100 − BD where BD = 2·OSSB − BA."""
    part = SheetMetalPart(
        material="steel-cold-rolled",
        thickness_mm=1.0,
        length_mm=52.0,
        width_mm=30.0,
        bend_radius_mm=2.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[50.0, 50.0],
    )
    result = compute_flat_pattern(part)
    k = result.k_factor
    ba = (math.pi / 2.0) * (2.0 + k * 1.0)
    ossb = (2.0 + 1.0) * math.tan(math.radians(45.0))
    bd = 2.0 * ossb - ba
    expected_flat = 100.0 - bd
    assert result.flat_length_mm == pytest.approx(expected_flat, rel=1e-4)


def test_flat_width_passthrough():
    part = SheetMetalPart(
        material="steel-cold-rolled",
        thickness_mm=1.0,
        length_mm=52.0,
        width_mm=47.5,
        bend_radius_mm=2.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[50.0, 50.0],
    )
    result = compute_flat_pattern(part)
    assert result.flat_width_mm == pytest.approx(47.5, abs=1e-9)


# ===========================================================================
# 4. 180° hem fold — tight bend (r=0.5mm, t=1mm, r/t=0.5 → K=k_min)
# ===========================================================================
# steel-cold-rolled K_min=0.33, K_max=0.44 → r/t=0.5 < 1 → K=0.33
# BA = π · (0.5 + 0.33·1) = π·0.83 ≈ 2.6077 mm
# OSSB = (0.5+1)·tan(90°) → tan(90°) is undefined/inf → BD is undefined
# Per DIN 6935: at θ=180° use limit: OSSB→∞ but BD = 2·OSSB − BA.
# In practice hem is treated differently; we still compute using the formula.
# The result should not raise (BD may be very large for hem fold).

def test_180deg_hem_fold_no_raise():
    """180° hem fold should compute without raising."""
    part = SheetMetalPart(
        material="steel-cold-rolled",
        thickness_mm=1.0,
        length_mm=10.0,
        width_mm=20.0,
        bend_radius_mm=0.5,
        bend_angle_deg=180.0,
        flange_lengths_mm=[10.0, 5.0],
    )
    # tan(90°) → large but finite float via Python math.tan; result is large
    result = compute_flat_pattern(part)
    assert isinstance(result, FlatPatternResult)
    assert result.num_bends == 1
    # K at r/t=0.5 should be K_min = 0.33 for steel
    assert result.k_factor == pytest.approx(0.33, abs=1e-9)


def test_180deg_hem_severe_k_factor():
    """At r/t < 1 K should stay at k_min regardless of angle."""
    part = SheetMetalPart(
        material="steel-cold-rolled",
        thickness_mm=2.0,
        length_mm=20.0,
        width_mm=10.0,
        bend_radius_mm=1.0,   # r/t = 0.5 → severe
        bend_angle_deg=135.0,
        flange_lengths_mm=[15.0, 10.0],
    )
    result = compute_flat_pattern(part)
    assert result.k_factor == pytest.approx(0.33, abs=1e-9)


# ===========================================================================
# 5. Stainless-304 thicker bend (t=3mm, r=6mm, r/t=2 → K interp)
# ===========================================================================
# stainless-304 K_min=0.31, K_max=0.38
# r/t=2 → K = 0.31 + 0.5*(0.38-0.31) = 0.31 + 0.035 = 0.345

def test_stainless_thick_bend_k_factor():
    part = SheetMetalPart(
        material="stainless-304",
        thickness_mm=3.0,
        length_mm=100.0,
        width_mm=50.0,
        bend_radius_mm=6.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[40.0, 60.0],
    )
    result = compute_flat_pattern(part)
    expected_k = 0.31 + 0.5 * (0.38 - 0.31)
    assert result.k_factor == pytest.approx(expected_k, abs=1e-6)


def test_stainless_k_below_mild_steel():
    """Stainless K-factor should be below mild steel at same r/t."""
    part_ss = SheetMetalPart(
        material="stainless-304",
        thickness_mm=1.0,
        length_mm=50.0,
        width_mm=20.0,
        bend_radius_mm=2.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[25.0, 25.0],
    )
    part_ms = SheetMetalPart(
        material="steel-cold-rolled",
        thickness_mm=1.0,
        length_mm=50.0,
        width_mm=20.0,
        bend_radius_mm=2.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[25.0, 25.0],
    )
    res_ss = compute_flat_pattern(part_ss)
    res_ms = compute_flat_pattern(part_ms)
    assert res_ss.k_factor < res_ms.k_factor


# ===========================================================================
# 6. Multiple bends in series (U-channel: 3 flanges → 2 bends)
# ===========================================================================

def test_u_channel_num_bends():
    """[side, base, side] → 2 bends."""
    part = SheetMetalPart(
        material="aluminum-5052",
        thickness_mm=1.5,
        length_mm=60.0,
        width_mm=40.0,
        bend_radius_mm=3.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[20.0, 40.0, 20.0],
    )
    result = compute_flat_pattern(part)
    assert result.num_bends == 2


def test_u_channel_two_bend_allowances():
    """2 bends → 2 bend-allowance values, identical for uniform geometry."""
    part = SheetMetalPart(
        material="aluminum-5052",
        thickness_mm=1.5,
        length_mm=60.0,
        width_mm=40.0,
        bend_radius_mm=3.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[20.0, 40.0, 20.0],
    )
    result = compute_flat_pattern(part)
    assert len(result.bend_allowances_mm) == 2
    # Both bends are identical (same r, t, angle, material)
    assert result.bend_allowances_mm[0] == pytest.approx(result.bend_allowances_mm[1], abs=1e-9)


def test_u_channel_flat_length_formula():
    """flat = Σflanges − 2·BD (2 bends)."""
    part = SheetMetalPart(
        material="aluminum-5052",
        thickness_mm=1.5,
        length_mm=60.0,
        width_mm=40.0,
        bend_radius_mm=3.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[20.0, 40.0, 20.0],
    )
    result = compute_flat_pattern(part)
    total_flanges = 20.0 + 40.0 + 20.0
    expected_flat = total_flanges - result.total_bend_deduction_mm
    assert result.flat_length_mm == pytest.approx(expected_flat, abs=1e-6)


# ===========================================================================
# 7. Zero bends (single-segment blank — no bends)
# ===========================================================================

def test_zero_bends_single_panel():
    """Single flange = no bend → flat_length == flange_length, BD=0."""
    part = SheetMetalPart(
        material="copper",
        thickness_mm=0.8,
        length_mm=100.0,
        width_mm=50.0,
        bend_radius_mm=1.6,
        bend_angle_deg=90.0,
        flange_lengths_mm=[100.0],
    )
    result = compute_flat_pattern(part)
    assert result.num_bends == 0
    assert result.flat_length_mm == pytest.approx(100.0, abs=1e-6)
    assert result.total_bend_deduction_mm == pytest.approx(0.0, abs=1e-9)
    assert result.bend_allowances_mm == []


# ===========================================================================
# 8. Aluminum-5052 gentle bend (r/t = 4 → K = k_max = 0.50)
# ===========================================================================

def test_aluminum_gentle_bend_k_max():
    """r/t = 4 ≥ 3 → K = 0.50 (aluminum-5052 K_max)."""
    part = SheetMetalPart(
        material="aluminum-5052",
        thickness_mm=2.0,
        length_mm=80.0,
        width_mm=30.0,
        bend_radius_mm=8.0,   # r/t = 4
        bend_angle_deg=90.0,
        flange_lengths_mm=[40.0, 40.0],
    )
    result = compute_flat_pattern(part)
    assert result.k_factor == pytest.approx(0.50, abs=1e-6)


# ===========================================================================
# 9. Copper alias
# ===========================================================================

def test_copper_alias_cu():
    """'cu' alias should resolve to copper K table."""
    part = SheetMetalPart(
        material="cu",
        thickness_mm=1.0,
        length_mm=50.0,
        width_mm=20.0,
        bend_radius_mm=2.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[25.0, 25.0],
    )
    result = compute_flat_pattern(part)
    # copper K_min=0.40, K_max=0.50, r/t=2 → K = 0.40 + 0.5*(0.50-0.40) = 0.45
    assert result.k_factor == pytest.approx(0.45, abs=1e-6)


# ===========================================================================
# 10. Error handling
# ===========================================================================

def test_unknown_material_raises():
    with pytest.raises(ValueError, match="Unknown material"):
        part = SheetMetalPart(
            material="unobtanium",
            thickness_mm=1.0,
            length_mm=50.0,
            width_mm=20.0,
            bend_radius_mm=2.0,
            bend_angle_deg=90.0,
            flange_lengths_mm=[25.0, 25.0],
        )
        compute_flat_pattern(part)


def test_zero_thickness_raises():
    with pytest.raises(ValueError, match="thickness_mm"):
        part = SheetMetalPart(
            material="steel-cold-rolled",
            thickness_mm=0.0,
            length_mm=50.0,
            width_mm=20.0,
            bend_radius_mm=2.0,
            bend_angle_deg=90.0,
            flange_lengths_mm=[25.0, 25.0],
        )
        compute_flat_pattern(part)


def test_negative_bend_radius_raises():
    with pytest.raises(ValueError, match="bend_radius_mm"):
        part = SheetMetalPart(
            material="steel-cold-rolled",
            thickness_mm=1.0,
            length_mm=50.0,
            width_mm=20.0,
            bend_radius_mm=-1.0,
            bend_angle_deg=90.0,
            flange_lengths_mm=[25.0, 25.0],
        )
        compute_flat_pattern(part)


def test_bend_angle_above_180_raises():
    with pytest.raises(ValueError, match="bend_angle_deg"):
        part = SheetMetalPart(
            material="steel-cold-rolled",
            thickness_mm=1.0,
            length_mm=50.0,
            width_mm=20.0,
            bend_radius_mm=2.0,
            bend_angle_deg=181.0,
            flange_lengths_mm=[25.0, 25.0],
        )
        compute_flat_pattern(part)


def test_empty_flanges_raises():
    with pytest.raises(ValueError, match="flange_lengths_mm"):
        part = SheetMetalPart(
            material="steel-cold-rolled",
            thickness_mm=1.0,
            length_mm=50.0,
            width_mm=20.0,
            bend_radius_mm=2.0,
            bend_angle_deg=90.0,
            flange_lengths_mm=[],
        )
        compute_flat_pattern(part)


# ===========================================================================
# 11. FlatPatternResult fields
# ===========================================================================

def test_result_dataclass_fields():
    """Verify all expected fields are present with correct types."""
    part = SheetMetalPart(
        material="steel-cold-rolled",
        thickness_mm=1.0,
        length_mm=52.0,
        width_mm=30.0,
        bend_radius_mm=2.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[50.0, 50.0],
    )
    r = compute_flat_pattern(part)
    assert isinstance(r.flat_length_mm, float)
    assert isinstance(r.flat_width_mm, float)
    assert isinstance(r.bend_allowances_mm, list)
    assert isinstance(r.k_factor, float)
    assert isinstance(r.total_bend_deduction_mm, float)
    assert isinstance(r.num_bends, int)
    assert isinstance(r.honest_caveat, str)
    assert len(r.honest_caveat) > 20


def test_honest_caveat_mentions_key_terms():
    """Caveat must mention spring-back and K-factor."""
    part = SheetMetalPart(
        material="steel-cold-rolled",
        thickness_mm=1.0,
        length_mm=52.0,
        width_mm=30.0,
        bend_radius_mm=2.0,
        bend_angle_deg=90.0,
        flange_lengths_mm=[50.0, 50.0],
    )
    r = compute_flat_pattern(part)
    caveat_lower = r.honest_caveat.lower()
    assert "spring" in caveat_lower
    assert "k-factor" in caveat_lower or "k factor" in caveat_lower


# ===========================================================================
# 12. Re-export from kerf_cad_core.__init__
# ===========================================================================

def test_reexport_from_init():
    """SheetMetalPart, FlatPatternResult, compute_flat_pattern in package root."""
    from kerf_cad_core import (  # noqa: F401
        SheetMetalPart as _SMP,
        FlatPatternResult as _FPR,
        compute_flat_pattern as _CPF,
    )
    assert _SMP is SheetMetalPart
    assert _FPR is FlatPatternResult
    assert _CPF is compute_flat_pattern
