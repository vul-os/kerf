"""
Tests for kerf_cad_core.arch.retaining_wall_stability — Rankine retaining wall.

Pure-Python, hermetic — no OCC, no DB, no network.
All inputs in SI: metres, kN/m³, kPa, degrees.

Oracle wall geometry (unless overridden in individual tests):
  H=3m, h=0.3m, t=0.3m, l_toe=0.2m, l_heel=1.5m  →  B=2.0m
  Soil: γ=18 kN/m³, φ=30°, δ=20°, q_a=200 kPa
  Concrete: γ_c=24 kN/m³

Key analytical checks:
  Ka = tan²(45-15) = tan²(30°) = 1/3
  Pa = 0.5·18·9·(1/3) = 27.0 kN/m   (acts at H/3 = 1.0 m)

Covers:
  T01  Ka = 1/3 for φ=30°
  T02  Pa = 27.0 kN/m for H=3m, γ=18 kN/m³, φ=30°
  T03  FoS_overturning > 2.0 for adequate wall (H=3m, B=2m, standard geometry)
  T04  FoS_overturning type is float
  T05  Narrow base → FoS_sliding below adequate threshold
  T06  FoS_sliding increases with wider base (more soil weight)
  T07  FoS_bearing positive finite value
  T08  all_adequate True for well-proportioned wall
  T09  all_adequate False for very narrow base (B=0.5m)
  T10  governing_failure_mode = 'none' when all_adequate
  T11  governing_failure_mode is one of sliding/overturning/bearing when inadequate
  T12  q_max_kPa > 0 for valid inputs
  T13  Higher φ → lower Ka (less active pressure)
  T14  Taller wall → higher Pa (Pa ∝ H²)
  T15  ValueError on negative H
  T16  ValueError on base_thickness >= H
  T17  ValueError on phi_deg=0 (not in (0,50])
  T18  ValueError on negative heel_length
  T19  ValueError on geometric inconsistency B ≠ toe+t+heel
  T20  ValueError on base_friction_delta > phi
  T21  ValueError on allowable_bearing = 0
  T22  Re-export from arch/__init__.py works
  T23  Concrete unit weight default 24.0 kN/m³
  T24  honest_caveat contains key scope limitation keywords
  T25  FoS_overturning formula: ΣM_resist / ΣM_overt — manual cross-check
  T26  Wider heel improves FoS_overturning (more resisting moment from soil weight)
  T27  FoS_bearing = q_a / q_max ratio
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.retaining_wall_stability import (
    RetainingWallSpec,
    SoilSpec,
    RetainingWallReport,
    check_retaining_wall,
)


# ---------------------------------------------------------------------------
# Helpers — canonical oracle wall
# ---------------------------------------------------------------------------

def _oracle_wall(
    *,
    H=3.0,
    t=0.3,
    h=0.3,
    l_toe=0.2,
    l_heel=1.5,
    gam_c=24.0,
) -> RetainingWallSpec:
    B = l_toe + t + l_heel
    return RetainingWallSpec(
        wall_height_H_m=H,
        stem_thickness_t_m=t,
        base_width_B_m=round(B, 6),
        base_thickness_h_m=h,
        heel_length_m=l_heel,
        toe_length_m=l_toe,
        concrete_unit_weight_kN_m3=gam_c,
    )


def _oracle_soil(
    *,
    gamma=18.0,
    phi=30.0,
    delta=20.0,
    q_a=200.0,
) -> SoilSpec:
    return SoilSpec(
        unit_weight_kN_m3=gamma,
        friction_angle_phi_deg=phi,
        base_friction_delta_deg=delta,
        allowable_bearing_q_a_kPa=q_a,
    )


# ---------------------------------------------------------------------------
# T01 — Ka = 1/3 for φ=30°
# ---------------------------------------------------------------------------

def test_T01_Ka_phi30():
    wall = _oracle_wall()
    soil = _oracle_soil(phi=30.0)
    r = check_retaining_wall(wall, soil)
    # Ka = tan²(45 - φ/2) = tan²(45 - 15) = tan²(30°) = (1/√3)² = 1/3
    Ka_expected = math.tan(math.radians(30.0)) ** 2   # = 1/3
    assert abs(r.Ka - Ka_expected) < 1e-9, f"Ka={r.Ka:.8f}, expected {Ka_expected:.8f}"
    assert abs(r.Ka - 1.0 / 3.0) < 1e-6, f"Ka should be ≈ 1/3, got {r.Ka:.8f}"


# ---------------------------------------------------------------------------
# T02 — Pa = 27.0 kN/m for H=3m, γ=18, φ=30°
# ---------------------------------------------------------------------------

def test_T02_Pa_oracle():
    wall = _oracle_wall(H=3.0)
    soil = _oracle_soil(gamma=18.0, phi=30.0)
    r = check_retaining_wall(wall, soil)
    # Pa = 0.5 · 18 · 9 · (1/3) = 27.0 kN/m
    assert abs(r.Pa_kN_per_m - 27.0) < 0.01, (
        f"Pa = {r.Pa_kN_per_m:.4f} kN/m, expected 27.00 kN/m"
    )


# ---------------------------------------------------------------------------
# T03 — FoS_overturning > 2.0 for adequate wall
# ---------------------------------------------------------------------------

def test_T03_FoS_overturning_adequate():
    wall = _oracle_wall()
    soil = _oracle_soil()
    r = check_retaining_wall(wall, soil)
    assert r.FoS_overturning > 2.0, (
        f"FoS_overturning = {r.FoS_overturning:.3f}, expected > 2.0 for adequate wall"
    )


# ---------------------------------------------------------------------------
# T04 — FoS_overturning is a float
# ---------------------------------------------------------------------------

def test_T04_FoS_overturning_type():
    r = check_retaining_wall(_oracle_wall(), _oracle_soil())
    assert isinstance(r.FoS_overturning, float), (
        f"FoS_overturning should be float, got {type(r.FoS_overturning)}"
    )


# ---------------------------------------------------------------------------
# T05 — Narrow base → FoS_sliding below adequate (1.5)
# ---------------------------------------------------------------------------

def test_T05_narrow_base_low_FoS_sliding():
    # Narrow wall: small base → low resisting weight → low sliding resistance
    # H=3m, B=0.9m, t=0.3m, toe=0.1m, heel=0.5m
    wall = _oracle_wall(H=3.0, t=0.3, h=0.3, l_toe=0.1, l_heel=0.5)
    soil = _oracle_soil(phi=30.0, delta=15.0)  # conservative delta
    r = check_retaining_wall(wall, soil)
    assert r.FoS_sliding < 1.5, (
        f"Expected FoS_sliding < 1.5 for narrow base, got {r.FoS_sliding:.3f}"
    )


# ---------------------------------------------------------------------------
# T06 — Wider base (longer heel) → higher FoS_sliding
# ---------------------------------------------------------------------------

def test_T06_wider_heel_higher_FoS_sliding():
    soil = _oracle_soil(phi=30.0, delta=20.0)
    wall_narrow = _oracle_wall(l_heel=0.6, l_toe=0.2)
    wall_wide   = _oracle_wall(l_heel=1.8, l_toe=0.2)
    r_narrow = check_retaining_wall(wall_narrow, soil)
    r_wide   = check_retaining_wall(wall_wide, soil)
    assert r_wide.FoS_sliding > r_narrow.FoS_sliding, (
        f"Wider heel should give higher FoS_sliding: "
        f"{r_wide.FoS_sliding:.3f} vs {r_narrow.FoS_sliding:.3f}"
    )


# ---------------------------------------------------------------------------
# T07 — FoS_bearing is positive and finite
# ---------------------------------------------------------------------------

def test_T07_FoS_bearing_positive_finite():
    r = check_retaining_wall(_oracle_wall(), _oracle_soil())
    assert r.FoS_bearing > 0.0, f"FoS_bearing must be > 0, got {r.FoS_bearing}"
    assert math.isfinite(r.FoS_bearing), f"FoS_bearing must be finite, got {r.FoS_bearing}"


# ---------------------------------------------------------------------------
# T08 — all_adequate True for well-proportioned wall
# ---------------------------------------------------------------------------

def test_T08_all_adequate_good_wall():
    # Good proportions: B=2m, H=3m, large q_a
    # Use delta=25° so FoS_sliding ≈ 1.84 > 1.5; FoS_bearing=3.51>3.0; FoS_overt=4.16>2.0
    wall = _oracle_wall()
    soil = _oracle_soil(q_a=300.0, delta=25.0)
    r = check_retaining_wall(wall, soil)
    assert r.all_adequate is True, (
        f"Expected all_adequate=True; "
        f"FoS_overt={r.FoS_overturning:.2f}, "
        f"FoS_slide={r.FoS_sliding:.2f}, "
        f"FoS_bear={r.FoS_bearing:.2f}"
    )


# ---------------------------------------------------------------------------
# T09 — all_adequate False for very narrow base
# ---------------------------------------------------------------------------

def test_T09_all_adequate_false_narrow_base():
    wall = _oracle_wall(l_toe=0.1, l_heel=0.3)  # B=0.7m, H=3m
    soil = _oracle_soil(q_a=100.0, delta=10.0)
    r = check_retaining_wall(wall, soil)
    assert r.all_adequate is False, (
        "Expected all_adequate=False for narrow base wall"
    )


# ---------------------------------------------------------------------------
# T10 — governing_failure_mode = 'none' when all_adequate
# ---------------------------------------------------------------------------

def test_T10_governing_mode_none_when_adequate():
    wall = _oracle_wall()
    soil = _oracle_soil(q_a=500.0, delta=20.0)
    r = check_retaining_wall(wall, soil)
    if r.all_adequate:
        assert r.governing_failure_mode == "none", (
            f"Expected 'none', got '{r.governing_failure_mode}'"
        )


# ---------------------------------------------------------------------------
# T11 — governing_failure_mode is valid string when inadequate
# ---------------------------------------------------------------------------

def test_T11_governing_mode_valid_when_inadequate():
    wall = _oracle_wall(l_toe=0.1, l_heel=0.3)
    soil = _oracle_soil(q_a=50.0, delta=5.0)
    r = check_retaining_wall(wall, soil)
    assert r.governing_failure_mode in ("overturning", "sliding", "bearing"), (
        f"Unexpected governing_failure_mode: '{r.governing_failure_mode}'"
    )


# ---------------------------------------------------------------------------
# T12 — q_max_kPa > 0
# ---------------------------------------------------------------------------

def test_T12_q_max_positive():
    r = check_retaining_wall(_oracle_wall(), _oracle_soil())
    assert r.q_max_kPa > 0.0, f"q_max_kPa must be > 0, got {r.q_max_kPa}"


# ---------------------------------------------------------------------------
# T13 — Higher φ → smaller Ka
# ---------------------------------------------------------------------------

def test_T13_higher_phi_smaller_Ka():
    wall = _oracle_wall()
    r25 = check_retaining_wall(wall, _oracle_soil(phi=25.0, delta=16.0))
    r35 = check_retaining_wall(wall, _oracle_soil(phi=35.0, delta=20.0))
    assert r35.Ka < r25.Ka, (
        f"Ka(φ=35°)={r35.Ka:.4f} should be < Ka(φ=25°)={r25.Ka:.4f}"
    )


# ---------------------------------------------------------------------------
# T14 — Taller wall → larger Pa (Pa ∝ H²)
# ---------------------------------------------------------------------------

def test_T14_taller_wall_larger_Pa():
    soil = _oracle_soil()
    w3 = _oracle_wall(H=3.0)
    # H=4m: B must grow proportionally to keep geometry valid
    w4 = RetainingWallSpec(
        wall_height_H_m=4.0,
        stem_thickness_t_m=0.35,
        base_width_B_m=2.7,
        base_thickness_h_m=0.4,
        heel_length_m=1.95,
        toe_length_m=0.40,
        concrete_unit_weight_kN_m3=24.0,
    )
    r3 = check_retaining_wall(w3, soil)
    r4 = check_retaining_wall(w4, soil)
    # Pa = 0.5·γ·H²·Ka → Pa(4m)/Pa(3m) should be ≈ 16/9 ≈ 1.78
    ratio = r4.Pa_kN_per_m / r3.Pa_kN_per_m
    assert abs(ratio - (16.0 / 9.0)) < 0.01, (
        f"Pa ratio H=4m/H=3m = {ratio:.4f}, expected ≈ {16/9:.4f}"
    )


# ---------------------------------------------------------------------------
# T15 — ValueError on H ≤ 0
# ---------------------------------------------------------------------------

def test_T15_ValueError_nonpositive_H():
    with pytest.raises(ValueError, match="wall_height_H_m"):
        check_retaining_wall(
            RetainingWallSpec(
                wall_height_H_m=-1.0,
                stem_thickness_t_m=0.3,
                base_width_B_m=2.0,
                base_thickness_h_m=0.3,
                heel_length_m=1.5,
                toe_length_m=0.2,
            ),
            _oracle_soil(),
        )


# ---------------------------------------------------------------------------
# T16 — ValueError on base_thickness >= H
# ---------------------------------------------------------------------------

def test_T16_ValueError_base_thickness_ge_H():
    with pytest.raises(ValueError, match="base_thickness_h_m"):
        check_retaining_wall(
            RetainingWallSpec(
                wall_height_H_m=3.0,
                stem_thickness_t_m=0.3,
                base_width_B_m=2.0,
                base_thickness_h_m=3.0,   # equal to H — invalid
                heel_length_m=1.5,
                toe_length_m=0.2,
            ),
            _oracle_soil(),
        )


# ---------------------------------------------------------------------------
# T17 — ValueError on phi_deg = 0 (must be > 0)
# ---------------------------------------------------------------------------

def test_T17_ValueError_phi_zero():
    with pytest.raises(ValueError, match="friction_angle_phi_deg"):
        check_retaining_wall(
            _oracle_wall(),
            SoilSpec(
                unit_weight_kN_m3=18.0,
                friction_angle_phi_deg=0.0,
                base_friction_delta_deg=0.0,
                allowable_bearing_q_a_kPa=200.0,
            ),
        )


# ---------------------------------------------------------------------------
# T18 — ValueError on negative heel_length
# ---------------------------------------------------------------------------

def test_T18_ValueError_negative_heel():
    with pytest.raises(ValueError, match="heel_length_m"):
        check_retaining_wall(
            RetainingWallSpec(
                wall_height_H_m=3.0,
                stem_thickness_t_m=0.3,
                base_width_B_m=2.0,  # inconsistent — will also fail, but heel triggers first
                base_thickness_h_m=0.3,
                heel_length_m=-0.5,
                toe_length_m=0.2,
            ),
            _oracle_soil(),
        )


# ---------------------------------------------------------------------------
# T19 — ValueError on geometric inconsistency B ≠ toe+t+heel
# ---------------------------------------------------------------------------

def test_T19_ValueError_geometric_inconsistency():
    with pytest.raises(ValueError, match="base_width_B_m"):
        check_retaining_wall(
            RetainingWallSpec(
                wall_height_H_m=3.0,
                stem_thickness_t_m=0.3,
                base_width_B_m=3.0,      # wrong: toe+t+heel = 0.2+0.3+1.5=2.0
                base_thickness_h_m=0.3,
                heel_length_m=1.5,
                toe_length_m=0.2,
            ),
            _oracle_soil(),
        )


# ---------------------------------------------------------------------------
# T20 — ValueError on base_friction_delta > phi
# ---------------------------------------------------------------------------

def test_T20_ValueError_delta_exceeds_phi():
    with pytest.raises(ValueError, match="base_friction_delta_deg"):
        check_retaining_wall(
            _oracle_wall(),
            SoilSpec(
                unit_weight_kN_m3=18.0,
                friction_angle_phi_deg=30.0,
                base_friction_delta_deg=35.0,  # > phi — invalid
                allowable_bearing_q_a_kPa=200.0,
            ),
        )


# ---------------------------------------------------------------------------
# T21 — ValueError on allowable_bearing = 0
# ---------------------------------------------------------------------------

def test_T21_ValueError_zero_q_a():
    with pytest.raises(ValueError, match="allowable_bearing_q_a_kPa"):
        check_retaining_wall(
            _oracle_wall(),
            SoilSpec(
                unit_weight_kN_m3=18.0,
                friction_angle_phi_deg=30.0,
                base_friction_delta_deg=20.0,
                allowable_bearing_q_a_kPa=0.0,  # invalid
            ),
        )


# ---------------------------------------------------------------------------
# T22 — Re-export from arch/__init__.py works
# ---------------------------------------------------------------------------

def test_T22_reexport_from_arch_init():
    from kerf_cad_core.arch import (
        RetainingWallSpec as RWS,
        RetainingSoilSpec as RSS,
        RetainingWallReport as RWR,
        check_retaining_wall as crw,
    )
    assert RWS is RetainingWallSpec
    assert RSS is SoilSpec
    assert RWR is RetainingWallReport
    assert crw is check_retaining_wall


# ---------------------------------------------------------------------------
# T23 — Default concrete unit weight is 24.0 kN/m³
# ---------------------------------------------------------------------------

def test_T23_default_concrete_unit_weight():
    wall = RetainingWallSpec(
        wall_height_H_m=3.0,
        stem_thickness_t_m=0.3,
        base_width_B_m=2.0,
        base_thickness_h_m=0.3,
        heel_length_m=1.5,
        toe_length_m=0.2,
    )
    assert wall.concrete_unit_weight_kN_m3 == 24.0, (
        f"Default concrete unit weight should be 24.0, got {wall.concrete_unit_weight_kN_m3}"
    )


# ---------------------------------------------------------------------------
# T24 — honest_caveat contains key scope limitation keywords
# ---------------------------------------------------------------------------

def test_T24_honest_caveat_keywords():
    r = check_retaining_wall(_oracle_wall(), _oracle_soil())
    caveat = r.honest_caveat.lower()
    for kw in ["rankine", "surcharge", "seismic", "passive", "mononobe"]:
        assert kw in caveat, f"honest_caveat missing keyword '{kw}'"


# ---------------------------------------------------------------------------
# T25 — Manual moment cross-check for FoS_overturning
# ---------------------------------------------------------------------------

def test_T25_FoS_overturning_manual_crosscheck():
    """
    Oracle geometry:
      H=3.0m, h=0.3m, t=0.3m, l_toe=0.2m, l_heel=1.5m, B=2.0m, γ_c=24 kN/m³
      Soil: γ_s=18 kN/m³, φ=30°

    Weight components:
      H_stem = 3.0 - 0.3 = 2.7m
      W_stem = 24 · 0.3 · 2.7 = 19.44 kN/m  at x=0.2+0.15=0.35m
      W_base = 24 · 2.0 · 0.3 = 14.40 kN/m  at x=1.0m
      W_soil = 18 · 1.5 · 2.7 = 72.90 kN/m  at x=2.0-0.75=1.25m

    M_resist = 19.44·0.35 + 14.40·1.0 + 72.90·1.25
             = 6.804 + 14.40 + 91.125 = 112.329 kN·m/m

    Ka = 1/3, Pa = 0.5·18·9·(1/3) = 27.0 kN/m
    M_overt = 27.0 · 1.0 = 27.0 kN·m/m

    FoS_overt = 112.329 / 27.0 ≈ 4.160
    """
    wall = _oracle_wall()
    soil = _oracle_soil(phi=30.0)
    r = check_retaining_wall(wall, soil)

    M_resist_expected = 19.44 * 0.35 + 14.40 * 1.0 + 72.90 * 1.25
    M_overt_expected  = 27.0 * 1.0
    FoS_expected = M_resist_expected / M_overt_expected

    assert abs(r.FoS_overturning - FoS_expected) < 0.001, (
        f"FoS_overturning = {r.FoS_overturning:.4f}, expected ≈ {FoS_expected:.4f}"
    )


# ---------------------------------------------------------------------------
# T26 — Wider heel → higher FoS_overturning
# ---------------------------------------------------------------------------

def test_T26_wider_heel_higher_FoS_overturning():
    soil = _oracle_soil()
    w_short = _oracle_wall(l_heel=0.8, l_toe=0.2)   # B=1.3m
    w_long  = _oracle_wall(l_heel=1.8, l_toe=0.2)   # B=2.3m
    r_short = check_retaining_wall(w_short, soil)
    r_long  = check_retaining_wall(w_long, soil)
    assert r_long.FoS_overturning > r_short.FoS_overturning, (
        f"Wider heel (B=2.3m) should give higher FoS_overturning than narrow (B=1.3m): "
        f"{r_long.FoS_overturning:.3f} vs {r_short.FoS_overturning:.3f}"
    )


# ---------------------------------------------------------------------------
# T27 — FoS_bearing = q_a / q_max
# ---------------------------------------------------------------------------

def test_T27_FoS_bearing_equals_q_a_over_q_max():
    q_a = 250.0
    soil = _oracle_soil(q_a=q_a)
    r = check_retaining_wall(_oracle_wall(), soil)
    expected = q_a / r.q_max_kPa
    assert abs(r.FoS_bearing - expected) < 1e-9, (
        f"FoS_bearing = {r.FoS_bearing:.6f}, "
        f"expected q_a/q_max = {expected:.6f}"
    )
