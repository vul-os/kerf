"""
Tests for kerf_mold.tunnel_gate_design
========================================
Covers gate diameter rule, high-viscosity correction, break-off force,
shear-rate check, freeze time, angle recommendation, validation errors,
and polymer database entries.

References:
  Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., Hanser 2007,
    §7.4 (Tunnel / Submarine Gates).
  Menges G., Michaeli W., Mohren P. How to Make Injection Molds, 3rd ed.,
    Hanser 2001, §6.6.5 + Table 6.3 + §7.3.3.
"""

import math

import pytest

from kerf_mold.tunnel_gate_design import (
    TunnelGateReport,
    TunnelGateSpec,
    _D_GATE_MIN_MM,
    _D_GATE_UPPER_FRACTION,
    _HIGH_VISCOSITY_POLYMERS,
    _SHEAR_RATE_LIMIT_PER_S,
    _SHEAR_STRENGTH_MPA,
    _THERMAL_DIFFUSIVITY_M2_S,
    design_tunnel_gate,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal valid spec
# ---------------------------------------------------------------------------

def _spec(
    part_weight_g: float = 30.0,
    wall_thickness_mm: float = 2.0,
    polymer_grade: str = "ABS",
    melt_temp_C: float = 240.0,
    gate_angle_deg: float = 30.0,
    gate_length_mm: float = 1.5,
) -> TunnelGateSpec:
    return TunnelGateSpec(
        part_weight_g=part_weight_g,
        wall_thickness_at_gate_mm=wall_thickness_mm,
        polymer_grade=polymer_grade,
        melt_temp_C=melt_temp_C,
        gate_angle_deg=gate_angle_deg,
        gate_length_mm=gate_length_mm,
    )


# ===========================================================================
# 1. ABS 30 g, wall 2 mm → D = 1.0 mm (Beaumont §7.4: 0.5 × 2.0 = 1.0)
# ===========================================================================

def test_abs_30g_wall2mm_diameter():
    """ABS, 2mm wall → Beaumont rule gives 0.5×2=1.0 mm exactly."""
    spec = _spec(polymer_grade="ABS", wall_thickness_mm=2.0)
    report = design_tunnel_gate(spec)
    assert report.gate_diameter_mm == pytest.approx(1.0, abs=1e-6), (
        f"Expected D=1.0 mm for ABS 2mm wall, got {report.gate_diameter_mm}"
    )


def test_abs_returns_tunnel_gate_report():
    spec = _spec()
    report = design_tunnel_gate(spec)
    assert isinstance(report, TunnelGateReport)


# ===========================================================================
# 2. PC (high-viscosity) → larger D than ABS for same wall thickness
# ===========================================================================

def test_pc_diameter_larger_than_abs_same_wall():
    """PC has +10% viscosity correction → D_PC > D_ABS for same wall."""
    spec_abs = _spec(polymer_grade="ABS", wall_thickness_mm=3.0)
    spec_pc = _spec(polymer_grade="PC", wall_thickness_mm=3.0)
    report_abs = design_tunnel_gate(spec_abs)
    report_pc = design_tunnel_gate(spec_pc)
    assert report_pc.gate_diameter_mm > report_abs.gate_diameter_mm, (
        f"Expected D_PC > D_ABS; got D_PC={report_pc.gate_diameter_mm} "
        f"D_ABS={report_abs.gate_diameter_mm}"
    )


def test_pc_diameter_equals_1p1_times_abs_diameter_before_cap():
    """For wall=3mm: D_ABS=1.5 mm, D_PC=1.5×1.10=1.65 mm (both below 2/3×3=2.0 cap)."""
    spec_abs = _spec(polymer_grade="ABS", wall_thickness_mm=3.0)
    spec_pc = _spec(polymer_grade="PC", wall_thickness_mm=3.0)
    d_abs = design_tunnel_gate(spec_abs).gate_diameter_mm
    d_pc = design_tunnel_gate(spec_pc).gate_diameter_mm
    assert d_pc == pytest.approx(d_abs * 1.10, abs=1e-5)


# ===========================================================================
# 3. Shear rate exceeds 50 000/s → flag shear_within_limit = False
# ===========================================================================

def test_shear_rate_flagged_for_heavy_part_thin_gate():
    """
    A very heavy part (100 g) through a tiny gate (0.8 mm, machining floor)
    will produce very high shear rate → shear_within_limit = False.
    """
    # wall=1.0mm → D_initial=0.5mm → clamped to 0.8mm (floor)
    spec = _spec(
        part_weight_g=100.0,
        wall_thickness_mm=1.0,
        polymer_grade="ABS",
        melt_temp_C=240.0,
    )
    report = design_tunnel_gate(spec)
    # Gate is at minimum 0.8 mm; high flow → high shear rate
    assert not report.shear_within_limit, (
        f"Expected shear flag; got shear_rate={report.shear_rate_at_gate_per_s} s⁻¹"
    )
    assert report.shear_rate_at_gate_per_s > _SHEAR_RATE_LIMIT_PER_S


def test_shear_rate_ok_for_small_light_part():
    """1 g part, 4 mm wall → large gate, low shear rate → within limit."""
    spec = _spec(
        part_weight_g=1.0,
        wall_thickness_mm=4.0,
        polymer_grade="PP",
        melt_temp_C=230.0,
    )
    report = design_tunnel_gate(spec)
    assert report.shear_within_limit is True
    assert report.shear_rate_at_gate_per_s <= _SHEAR_RATE_LIMIT_PER_S


# ===========================================================================
# 4. Recommended angle 30°–45° per Menges §6.6.5
# ===========================================================================

def test_recommended_angle_in_range_for_abs():
    """ABS (low-viscosity) → recommended angle = 30°."""
    report = design_tunnel_gate(_spec(polymer_grade="ABS", gate_angle_deg=30.0))
    assert 30.0 <= report.recommended_angle_deg <= 45.0


def test_recommended_angle_45_for_high_viscosity():
    """PC (high-viscosity) → recommended angle = 45°."""
    report = design_tunnel_gate(_spec(polymer_grade="PC", gate_angle_deg=30.0))
    assert report.recommended_angle_deg == pytest.approx(45.0)


def test_user_angle_in_range_abs_still_recommends_30():
    """ABS always recommends 30° regardless of user angle within range."""
    spec = _spec(gate_angle_deg=40.0, polymer_grade="ABS")
    report = design_tunnel_gate(spec)
    assert report.recommended_angle_deg == pytest.approx(30.0)


def test_recommended_angle_always_polymer_based():
    """Recommended angle always reflects polymer guidance, not user input."""
    spec = _spec(gate_angle_deg=60.0, polymer_grade="ABS")
    report = design_tunnel_gate(spec)
    assert 30.0 <= report.recommended_angle_deg <= 45.0


# ===========================================================================
# 5. Lower bound: gate diameter never below 0.8 mm
# ===========================================================================

def test_gate_diameter_not_below_machining_floor():
    """Very thin wall (0.5 mm) → D_initial=0.25 < 0.8 → clamped to 0.8 mm."""
    spec = _spec(wall_thickness_mm=0.5, polymer_grade="PP")
    report = design_tunnel_gate(spec)
    assert report.gate_diameter_mm >= _D_GATE_MIN_MM


# ===========================================================================
# 6. Upper cap: gate diameter not above 2/3 × wall_thickness
# ===========================================================================

def test_gate_diameter_does_not_exceed_upper_cap_for_pc():
    """
    PC, wall=1.2mm → D_initial=0.6, ×1.10=0.66, cap=2/3×1.2=0.80.
    0.66 < 0.80 so cap not triggered, but general test: D ≤ 2/3×wall.
    For larger wall: wall=3mm → D_initial=1.5, ×1.10=1.65; cap=2.0; D=1.65.
    """
    for wall in [1.2, 2.0, 3.0, 5.0]:
        spec = _spec(wall_thickness_mm=wall, polymer_grade="PC")
        report = design_tunnel_gate(spec)
        cap = _D_GATE_UPPER_FRACTION * wall
        assert report.gate_diameter_mm <= cap + 1e-9, (
            f"D={report.gate_diameter_mm:.4f} exceeds cap={cap:.4f} for wall={wall}"
        )


# ===========================================================================
# 7. Break-off force is positive and proportional to shear strength × D²
# ===========================================================================

def test_break_off_force_positive():
    spec = _spec()
    report = design_tunnel_gate(spec)
    assert report.gate_break_off_force_N > 0.0


def test_break_off_force_higher_for_pc_than_abs():
    """PC has higher shear strength AND higher D → larger break force."""
    spec_abs = _spec(polymer_grade="ABS", wall_thickness_mm=3.0)
    spec_pc = _spec(polymer_grade="PC", wall_thickness_mm=3.0)
    f_abs = design_tunnel_gate(spec_abs).gate_break_off_force_N
    f_pc = design_tunnel_gate(spec_pc).gate_break_off_force_N
    assert f_pc > f_abs, f"Expected F_break_PC > F_break_ABS; got {f_pc:.2f} vs {f_abs:.2f}"


def test_break_off_force_formula_oracle():
    """
    Oracle: ABS, wall=2mm → D_gate=1.0mm=0.001m
    A = π/4 × (0.001)² = 7.854e-7 m²
    F = 30 MPa × 7.854e-7 = 23.56 N
    """
    spec = _spec(polymer_grade="ABS", wall_thickness_mm=2.0)
    report = design_tunnel_gate(spec)
    d_m = 1.0e-3
    expected_N = 30.0e6 * (math.pi / 4.0 * d_m ** 2)
    assert report.gate_break_off_force_N == pytest.approx(expected_N, rel=1e-4)


# ===========================================================================
# 8. Gate freeze time is positive and finite
# ===========================================================================

def test_gate_freeze_time_positive():
    spec = _spec()
    report = design_tunnel_gate(spec)
    assert report.gate_freeze_time_s > 0.0
    assert math.isfinite(report.gate_freeze_time_s)


def test_gate_freeze_time_shorter_for_larger_diffusivity():
    """PC (α=1.5e-7) freezes faster than PP (α=0.95e-7) at same D."""
    # Use same wall to ensure same gate diameter baseline
    spec_pc = _spec(polymer_grade="PC", wall_thickness_mm=2.0, melt_temp_C=300.0)
    spec_pp = _spec(polymer_grade="PP", wall_thickness_mm=2.0, melt_temp_C=230.0)
    t_pc = design_tunnel_gate(spec_pc).gate_freeze_time_s
    t_pp = design_tunnel_gate(spec_pp).gate_freeze_time_s
    # PC has 1.10 correction → slightly larger D, but α is 58% larger → much faster
    # The thermal term dominates: t ∝ D²/α; PC α=1.5e-7, D_pc=1.1×D_pp
    # t_pc/t_pp = (1.1²) × (0.95/1.5) = 1.21 × 0.633 = 0.766 → t_pc < t_pp
    assert t_pc < t_pp, (
        f"Expected t_PC < t_PP due to higher diffusivity; "
        f"t_PC={t_pc:.4f}s, t_PP={t_pp:.4f}s"
    )


# ===========================================================================
# 9. Shear rate calculation is non-zero for valid inputs
# ===========================================================================

def test_shear_rate_nonzero():
    spec = _spec(part_weight_g=10.0, wall_thickness_mm=2.0)
    report = design_tunnel_gate(spec)
    assert report.shear_rate_at_gate_per_s > 0.0


def test_shear_rate_increases_with_part_weight():
    """Heavier part → higher Q (same fill time) → higher shear rate through same gate."""
    spec_light = _spec(part_weight_g=1.0, wall_thickness_mm=2.0, polymer_grade="ABS")
    spec_heavy = _spec(part_weight_g=100.0, wall_thickness_mm=2.0, polymer_grade="ABS")
    r_light = design_tunnel_gate(spec_light).shear_rate_at_gate_per_s
    r_heavy = design_tunnel_gate(spec_heavy).shear_rate_at_gate_per_s
    assert r_heavy > r_light, (
        f"Expected higher shear for heavier part; "
        f"r_light={r_light:.1f}, r_heavy={r_heavy:.1f}"
    )


# ===========================================================================
# 10. Honest caveat is non-empty and contains key terms
# ===========================================================================

def test_honest_caveat_non_empty():
    spec = _spec()
    report = design_tunnel_gate(spec)
    assert report.honest_caveat, "honest_caveat should not be empty"


def test_honest_caveat_mentions_beaumont():
    spec = _spec(polymer_grade="PC")
    report = design_tunnel_gate(spec)
    assert "Beaumont" in report.honest_caveat


def test_honest_caveat_mentions_moldflow():
    spec = _spec()
    report = design_tunnel_gate(spec)
    assert "Moldflow" in report.honest_caveat


def test_honest_caveat_mentions_polymer():
    spec = _spec(polymer_grade="ABS")
    report = design_tunnel_gate(spec)
    assert "ABS" in report.honest_caveat


# ===========================================================================
# 11. Validation errors
# ===========================================================================

def test_zero_part_weight_raises():
    with pytest.raises(ValueError, match="part_weight_g must be > 0"):
        TunnelGateSpec(
            part_weight_g=0.0,
            wall_thickness_at_gate_mm=2.0,
            polymer_grade="ABS",
            melt_temp_C=240.0,
        )


def test_negative_wall_thickness_raises():
    with pytest.raises(ValueError, match="wall_thickness_at_gate_mm must be > 0"):
        TunnelGateSpec(
            part_weight_g=10.0,
            wall_thickness_at_gate_mm=-1.0,
            polymer_grade="ABS",
            melt_temp_C=240.0,
        )


def test_zero_melt_temp_raises():
    with pytest.raises(ValueError, match="melt_temp_C must be > 0"):
        TunnelGateSpec(
            part_weight_g=10.0,
            wall_thickness_at_gate_mm=2.0,
            polymer_grade="ABS",
            melt_temp_C=0.0,
        )


def test_zero_gate_length_raises():
    with pytest.raises(ValueError, match="gate_length_mm must be > 0"):
        TunnelGateSpec(
            part_weight_g=10.0,
            wall_thickness_at_gate_mm=2.0,
            polymer_grade="ABS",
            melt_temp_C=240.0,
            gate_length_mm=0.0,
        )


def test_invalid_gate_angle_raises():
    with pytest.raises(ValueError, match="gate_angle_deg must be in"):
        TunnelGateSpec(
            part_weight_g=10.0,
            wall_thickness_at_gate_mm=2.0,
            polymer_grade="ABS",
            melt_temp_C=240.0,
            gate_angle_deg=0.0,
        )


# ===========================================================================
# 12. Unknown polymer falls back gracefully (no exception)
# ===========================================================================

def test_unknown_polymer_grade_no_exception():
    """Unrecognised polymer uses ABS-baseline properties; no crash."""
    spec = _spec(polymer_grade="MYSTERY_RESIN")
    report = design_tunnel_gate(spec)
    assert isinstance(report, TunnelGateReport)
    assert report.gate_diameter_mm > 0.0
    assert report.gate_break_off_force_N > 0.0


# ===========================================================================
# 13. High-viscosity polymer set contains expected members
# ===========================================================================

def test_high_viscosity_set_includes_pc_pa66_pmma():
    for grade in ["PC", "PA66", "PMMA", "POM", "PEI", "PPO"]:
        assert grade in _HIGH_VISCOSITY_POLYMERS, (
            f"{grade} should be in _HIGH_VISCOSITY_POLYMERS"
        )


def test_abs_not_in_high_viscosity_set():
    assert "ABS" not in _HIGH_VISCOSITY_POLYMERS


# ===========================================================================
# 14. Shear rate limit constant is 50 000 s⁻¹
# ===========================================================================

def test_shear_rate_limit_is_50000():
    assert _SHEAR_RATE_LIMIT_PER_S == pytest.approx(50_000.0)


# ===========================================================================
# 15. Freeze time formula oracle — ABS, D=1mm, T_melt=240, T_mold=40, T_eject=80
# ===========================================================================

def test_freeze_time_oracle_abs_1mm():
    """
    Oracle: ABS, wall=2mm → D_gate=1.0 mm = 0.001 m
    α = 1.0e-7 m²/s; T_melt=240, T_mold=40, T_eject=80
    log_arg = (8/π²) × (240−40)/(80−40) = 0.8106 × 5.0 = 4.053
    t_f = (0.001² / (π² × 1.0e-7)) × ln(4.053)
        = (1e-6 / 9.8696e-7) × 1.400
        = 1.013 × 1.400
        ≈ 1.418 s
    """
    spec = _spec(
        polymer_grade="ABS",
        wall_thickness_mm=2.0,
        melt_temp_C=240.0,
    )
    report = design_tunnel_gate(spec)
    d_m = 1.0e-3
    alpha = 1.0e-7
    T_melt, T_mold, T_eject = 240.0, 40.0, 80.0
    log_arg = (8.0 / math.pi ** 2) * (T_melt - T_mold) / (T_eject - T_mold)
    expected_s = (d_m ** 2 / (math.pi ** 2 * alpha)) * math.log(log_arg)
    assert report.gate_freeze_time_s == pytest.approx(expected_s, rel=1e-4)


# ===========================================================================
# 16. PP shear strength and diffusivity correct per Menges database
# ===========================================================================

def test_pp_shear_strength_database():
    assert _SHEAR_STRENGTH_MPA.get("PP") == pytest.approx(22.0)


def test_pp_thermal_diffusivity_database():
    assert _THERMAL_DIFFUSIVITY_M2_S.get("PP") == pytest.approx(0.95e-7)
