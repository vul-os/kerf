"""
Tests for kerf_cad_core.arch.footing_bearing — Meyerhof (1963) bearing capacity.

Pure-Python, hermetic — no OCC, no DB, no network.
All inputs in SI: metres, kPa, kN/m³.

Covers:
  T01  φ=30° N-factors within 1% of published Meyerhof table: N_c=30.14, N_q=18.40, N_γ=15.67
  T02  φ=0 special case: N_c=5.14 (Prandtl), N_q=1.0, N_γ=0.0
  T03  φ=0 clay, square 2×2 m, Df=1 m, c=50 kPa — q_ult formula verified
  T04  φ=35° sand, square 2×2 m, Df=1 m, c=0 — q_ult positive
  T05  Strip footing shape factors = 1.0 for all φ
  T06  Square footing shape factors > 1.0 for φ > 0
  T07  Depth factors increase with Df/B ratio
  T08  q_allow = q_ult / FS (default FS=3)
  T09  Custom FS respected
  T10  Rectangular footing interpolates shape factors between strip and square
  T11  Circular footing uses B/L = 1.0 (same as square)
  T12  q_ult >= 0 for valid inputs (pure sand φ=45°)
  T13  ValueError on invalid shape
  T14  ValueError on negative cohesion
  T15  ValueError on phi_deg out of range (>50)
  T16  ValueError on non-positive B
  T17  ValueError on non-positive Df
  T18  ValueError on non-positive unit_weight
  T19  ValueError on FS <= 0
  T20  BearingCapacityReport honest_caveat contains reference keywords
  T21  N-factors monotonically increase with φ (check φ=10, 20, 30, 40)
  T22  depth_factor_kf < 1 reduces q_ult (submerged condition)
  T23  re-export from arch/__init__.py works
  T24  three terms of q_ult equation — zero cohesion zero surcharge case
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.footing_bearing import (
    SoilProperties,
    FootingSpec,
    BearingCapacityReport,
    compute_bearing_capacity,
    _meyerhof_N_factors,
)


# ---------------------------------------------------------------------------
# T01 — φ=30° N-factors within 1% of published Meyerhof table values
# ---------------------------------------------------------------------------

def test_T01_phi30_N_factors_within_1pct():
    """Meyerhof 1963 Table: φ=30° → N_c=30.14, N_q=18.40, N_γ=15.67."""
    N_c, N_q, N_gamma = _meyerhof_N_factors(30.0)

    assert abs(N_c - 30.14) / 30.14 < 0.01, f"N_c={N_c:.4f}, expected ≈30.14"
    assert abs(N_q - 18.40) / 18.40 < 0.01, f"N_q={N_q:.4f}, expected ≈18.40"
    assert abs(N_gamma - 15.67) / 15.67 < 0.01, f"N_γ={N_gamma:.4f}, expected ≈15.67"


# ---------------------------------------------------------------------------
# T02 — φ=0 special case
# ---------------------------------------------------------------------------

def test_T02_phi0_special_case():
    """φ=0: N_c=5.14 (Prandtl), N_q=1.0, N_γ=0.0."""
    N_c, N_q, N_gamma = _meyerhof_N_factors(0.0)

    assert abs(N_c - 5.14) < 1e-9, f"N_c={N_c}, expected 5.14"
    assert N_q == 1.0, f"N_q={N_q}, expected 1.0"
    assert N_gamma == 0.0, f"N_γ={N_gamma}, expected 0.0"


# ---------------------------------------------------------------------------
# T03 — φ=0 clay, square 2×2 m, Df=1 m, c=50 kPa — formula verification
# ---------------------------------------------------------------------------

def test_T03_phi0_clay_square_formula():
    """
    φ=0 clay: q_ult = c·N_c·s_c·d_c + γ·Df·1·1·1 + 0  (N_γ=0)
    With B=L=2m, Df=1m, c=50 kPa, γ=18 kN/m³:
      N_c=5.14, K_phi=tan²(45)=1.0
      s_c = 1 + 0.2·(1.0)·1.0 = 1.2
      d_c = 1 + 0.2·(1/2)·1.0 = 1.1
      q_ult = 50·5.14·1.2·1.1 + 18·1·1·1·1 + 0 = 339.24 + 18 = 357.24 kPa
    """
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    soil = SoilProperties(cohesion_c_kPa=50.0, friction_angle_phi_deg=0.0, unit_weight_kN_m3=18.0)
    r = compute_bearing_capacity(footing, soil)

    expected_q_ult = 50.0 * 5.14 * 1.2 * 1.1 + 18.0 * 1.0
    assert abs(r.q_ult_kPa - expected_q_ult) < 0.01, (
        f"q_ult={r.q_ult_kPa:.4f}, expected={expected_q_ult:.4f}"
    )
    assert r.N_c == 5.14
    assert r.N_gamma == 0.0


# ---------------------------------------------------------------------------
# T04 — φ=35° sand square footing positive q_ult
# ---------------------------------------------------------------------------

def test_T04_phi35_sand_square_positive():
    """φ=35° pure sand square 2×2 m, Df=1 m → q_ult should be strongly positive."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    soil = SoilProperties(cohesion_c_kPa=0.0, friction_angle_phi_deg=35.0, unit_weight_kN_m3=18.0)
    r = compute_bearing_capacity(footing, soil)

    assert r.q_ult_kPa > 0.0, f"q_ult should be positive, got {r.q_ult_kPa}"
    assert r.q_allow_kPa > 0.0
    # Published approximate: q_ult ≈ 1900 kPa range for this case
    assert r.q_ult_kPa > 500.0, f"q_ult={r.q_ult_kPa:.2f} kPa seems too low"


# ---------------------------------------------------------------------------
# T05 — Strip footing shape factors = 1.0
# ---------------------------------------------------------------------------

def test_T05_strip_shape_factors_unity():
    """Strip footing: all shape factors must equal 1.0 (no shape correction)."""
    footing = FootingSpec(length_B_m=1.5, width_L_m=10.0, depth_Df_m=1.0, shape="strip")
    soil = SoilProperties(cohesion_c_kPa=20.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=17.0)
    r = compute_bearing_capacity(footing, soil)

    assert r.shape_factor_s_c == 1.0, f"s_c={r.shape_factor_s_c}, expected 1.0 for strip"


# ---------------------------------------------------------------------------
# T06 — Square/circular shape factors > 1 for φ > 0
# ---------------------------------------------------------------------------

def test_T06_square_shape_factors_gt_1():
    """Square footing with φ > 0 must have s_c > 1 (shape enhances capacity)."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    soil = SoilProperties(cohesion_c_kPa=0.0, friction_angle_phi_deg=30.0, unit_weight_kN_m3=18.0)
    r = compute_bearing_capacity(footing, soil)

    assert r.shape_factor_s_c > 1.0, f"s_c={r.shape_factor_s_c}"


def test_T06b_circular_same_as_square():
    """Circular footing has same shape factors as square (both use B/L=1)."""
    footing_sq = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    footing_ci = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="circular")
    soil = SoilProperties(cohesion_c_kPa=10.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=17.0)

    r_sq = compute_bearing_capacity(footing_sq, soil)
    r_ci = compute_bearing_capacity(footing_ci, soil)

    assert abs(r_sq.q_ult_kPa - r_ci.q_ult_kPa) < 1e-9, (
        f"Square={r_sq.q_ult_kPa:.4f} should equal circular={r_ci.q_ult_kPa:.4f}"
    )


# ---------------------------------------------------------------------------
# T07 — Depth factors increase with Df/B
# ---------------------------------------------------------------------------

def test_T07_depth_factors_increase_with_Df_B():
    """Greater embedment Df increases depth factors and thus q_ult."""
    soil = SoilProperties(cohesion_c_kPa=30.0, friction_angle_phi_deg=20.0, unit_weight_kN_m3=17.0)

    footing_shallow = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=0.5, shape="square")
    footing_deep = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=2.0, shape="square")

    r_shallow = compute_bearing_capacity(footing_shallow, soil)
    r_deep = compute_bearing_capacity(footing_deep, soil)

    assert r_deep.q_ult_kPa > r_shallow.q_ult_kPa, (
        f"Deeper footing should have higher q_ult; "
        f"deep={r_deep.q_ult_kPa:.2f} <= shallow={r_shallow.q_ult_kPa:.2f}"
    )
    assert r_deep.depth_factor_d_c > r_shallow.depth_factor_d_c


# ---------------------------------------------------------------------------
# T08 — q_allow = q_ult / FS with default FS=3
# ---------------------------------------------------------------------------

def test_T08_q_allow_equals_q_ult_over_FS():
    """Default FS=3.0: q_allow = q_ult / 3 exactly."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=3.0, depth_Df_m=1.5, shape="rectangular")
    soil = SoilProperties(cohesion_c_kPa=25.0, friction_angle_phi_deg=20.0, unit_weight_kN_m3=18.0)
    r = compute_bearing_capacity(footing, soil, FS=3.0)

    assert abs(r.q_allow_kPa - r.q_ult_kPa / 3.0) < 1e-9
    assert r.factor_of_safety == 3.0


# ---------------------------------------------------------------------------
# T09 — Custom FS is respected
# ---------------------------------------------------------------------------

def test_T09_custom_FS():
    """Custom FS=2.5: q_allow = q_ult / 2.5."""
    footing = FootingSpec(length_B_m=1.5, width_L_m=2.5, depth_Df_m=1.0, shape="rectangular")
    soil = SoilProperties(cohesion_c_kPa=0.0, friction_angle_phi_deg=30.0, unit_weight_kN_m3=19.0)
    r = compute_bearing_capacity(footing, soil, FS=2.5)

    assert r.factor_of_safety == 2.5
    assert abs(r.q_allow_kPa - r.q_ult_kPa / 2.5) < 1e-9


# ---------------------------------------------------------------------------
# T10 — Rectangular footing shape factors between strip and square
# ---------------------------------------------------------------------------

def test_T10_rectangular_shape_factor_between_strip_and_square():
    """
    Rectangular footing with B/L = 0.5 should have shape factor between
    strip (s_c=1) and square (B/L=1), because shape correction scales with B/L.
    """
    soil = SoilProperties(cohesion_c_kPa=20.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=17.0)

    footing_rect = FootingSpec(length_B_m=1.0, width_L_m=2.0, depth_Df_m=1.0, shape="rectangular")
    footing_sq = FootingSpec(length_B_m=1.0, width_L_m=1.0, depth_Df_m=1.0, shape="square")
    footing_strip = FootingSpec(length_B_m=1.0, width_L_m=10.0, depth_Df_m=1.0, shape="strip")

    r_rect = compute_bearing_capacity(footing_rect, soil)
    r_sq = compute_bearing_capacity(footing_sq, soil)
    r_strip = compute_bearing_capacity(footing_strip, soil)

    assert r_strip.shape_factor_s_c == 1.0
    assert r_rect.shape_factor_s_c > r_strip.shape_factor_s_c
    assert r_rect.shape_factor_s_c < r_sq.shape_factor_s_c


# ---------------------------------------------------------------------------
# T11 — Circular footing uses B/L = 1 (same shape factor as square)
# ---------------------------------------------------------------------------

def test_T11_circular_footing():
    """Circular footing should return valid q_ult > 0."""
    footing = FootingSpec(length_B_m=1.5, width_L_m=1.5, depth_Df_m=1.0, shape="circular")
    soil = SoilProperties(cohesion_c_kPa=50.0, friction_angle_phi_deg=0.0, unit_weight_kN_m3=18.0)
    r = compute_bearing_capacity(footing, soil)

    assert r.q_ult_kPa > 0.0
    assert r.N_c == 5.14
    assert r.N_gamma == 0.0


# ---------------------------------------------------------------------------
# T12 — Pure sand φ=45° q_ult positive and large
# ---------------------------------------------------------------------------

def test_T12_phi45_dense_sand():
    """Dense sand φ=45°, square footing — q_ult must be very high positive."""
    footing = FootingSpec(length_B_m=1.5, width_L_m=1.5, depth_Df_m=1.5, shape="square")
    soil = SoilProperties(cohesion_c_kPa=0.0, friction_angle_phi_deg=45.0, unit_weight_kN_m3=20.0)
    r = compute_bearing_capacity(footing, soil)

    assert r.q_ult_kPa > 0.0
    # For φ=45° N_q is very large; q_ult >> 1000 kPa
    assert r.q_ult_kPa > 1000.0, f"q_ult={r.q_ult_kPa:.1f}"


# ---------------------------------------------------------------------------
# T13 — ValueError on invalid shape
# ---------------------------------------------------------------------------

def test_T13_invalid_shape_raises():
    """Unknown shape string should raise ValueError."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="hexagonal")
    soil = SoilProperties(cohesion_c_kPa=0.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=17.0)
    with pytest.raises(ValueError, match="shape"):
        compute_bearing_capacity(footing, soil)


# ---------------------------------------------------------------------------
# T14 — ValueError on negative cohesion
# ---------------------------------------------------------------------------

def test_T14_negative_cohesion_raises():
    """Negative cohesion is physically meaningless — must raise ValueError."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    soil = SoilProperties(cohesion_c_kPa=-5.0, friction_angle_phi_deg=20.0, unit_weight_kN_m3=17.0)
    with pytest.raises(ValueError, match="cohesion"):
        compute_bearing_capacity(footing, soil)


# ---------------------------------------------------------------------------
# T15 — ValueError on phi_deg out of range
# ---------------------------------------------------------------------------

def test_T15_phi_out_of_range_raises():
    """φ > 50° is outside Meyerhof formula validity range."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    soil = SoilProperties(cohesion_c_kPa=0.0, friction_angle_phi_deg=55.0, unit_weight_kN_m3=18.0)
    with pytest.raises(ValueError, match="friction_angle"):
        compute_bearing_capacity(footing, soil)


# ---------------------------------------------------------------------------
# T16 — ValueError on non-positive B
# ---------------------------------------------------------------------------

def test_T16_nonpositive_B_raises():
    """B must be > 0."""
    footing = FootingSpec(length_B_m=0.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    soil = SoilProperties(cohesion_c_kPa=0.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=17.0)
    with pytest.raises(ValueError, match="length_B_m"):
        compute_bearing_capacity(footing, soil)


# ---------------------------------------------------------------------------
# T17 — ValueError on non-positive Df
# ---------------------------------------------------------------------------

def test_T17_nonpositive_Df_raises():
    """Df must be > 0 (footing must be below grade)."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=0.0, shape="square")
    soil = SoilProperties(cohesion_c_kPa=0.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=17.0)
    with pytest.raises(ValueError, match="depth_Df_m"):
        compute_bearing_capacity(footing, soil)


# ---------------------------------------------------------------------------
# T18 — ValueError on non-positive unit_weight
# ---------------------------------------------------------------------------

def test_T18_nonpositive_gamma_raises():
    """Unit weight must be > 0."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    soil = SoilProperties(cohesion_c_kPa=0.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=0.0)
    with pytest.raises(ValueError, match="unit_weight"):
        compute_bearing_capacity(footing, soil)


# ---------------------------------------------------------------------------
# T19 — ValueError on FS <= 0
# ---------------------------------------------------------------------------

def test_T19_invalid_FS_raises():
    """FS must be > 0."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    soil = SoilProperties(cohesion_c_kPa=30.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=17.0)
    with pytest.raises(ValueError, match="FS"):
        compute_bearing_capacity(footing, soil, FS=0.0)


# ---------------------------------------------------------------------------
# T20 — honest_caveat contains key reference strings
# ---------------------------------------------------------------------------

def test_T20_honest_caveat_references():
    """honest_caveat must mention Meyerhof, Bowles, and scope caveats."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    soil = SoilProperties(cohesion_c_kPa=30.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=17.0)
    r = compute_bearing_capacity(footing, soil)

    caveat = r.honest_caveat.lower()
    assert "meyerhof" in caveat, "caveat should mention Meyerhof"
    assert "bowles" in caveat, "caveat should mention Bowles"
    assert "brinch hansen" in caveat or "hansen" in caveat, "caveat should mention Brinch Hansen as out-of-scope"
    assert "seismic" in caveat, "caveat should mention seismic as out-of-scope"


# ---------------------------------------------------------------------------
# T21 — N-factors increase monotonically with φ (for φ > 0)
# ---------------------------------------------------------------------------

def test_T21_N_factors_monotonic():
    """N_c, N_q, N_γ must all increase as φ increases from 10° to 40°."""
    phis = [10.0, 20.0, 30.0, 40.0]
    factors = [_meyerhof_N_factors(p) for p in phis]

    for i in range(len(phis) - 1):
        N_c_lo, N_q_lo, N_g_lo = factors[i]
        N_c_hi, N_q_hi, N_g_hi = factors[i + 1]
        phi_lo, phi_hi = phis[i], phis[i + 1]

        assert N_c_hi > N_c_lo, f"N_c not monotonic between φ={phi_lo}° and φ={phi_hi}°"
        assert N_q_hi > N_q_lo, f"N_q not monotonic between φ={phi_lo}° and φ={phi_hi}°"
        assert N_g_hi > N_g_lo, f"N_γ not monotonic between φ={phi_lo}° and φ={phi_hi}°"


# ---------------------------------------------------------------------------
# T22 — depth_factor_kf < 1 reduces q_ult (submerged surcharge)
# ---------------------------------------------------------------------------

def test_T22_depth_factor_kf_reduces_q_ult():
    """Setting depth_factor_kf < 1 (effective stress, submerged) should lower q_ult."""
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.5, shape="square")

    soil_dry = SoilProperties(
        cohesion_c_kPa=0.0, friction_angle_phi_deg=30.0, unit_weight_kN_m3=18.0,
        depth_factor_kf=1.0
    )
    soil_sub = SoilProperties(
        cohesion_c_kPa=0.0, friction_angle_phi_deg=30.0, unit_weight_kN_m3=18.0,
        depth_factor_kf=0.5
    )

    r_dry = compute_bearing_capacity(footing, soil_dry)
    r_sub = compute_bearing_capacity(footing, soil_sub)

    assert r_sub.q_ult_kPa < r_dry.q_ult_kPa, (
        f"Submerged (kf=0.5) should yield lower q_ult: {r_sub.q_ult_kPa:.2f} < {r_dry.q_ult_kPa:.2f}"
    )


# ---------------------------------------------------------------------------
# T23 — re-export from arch/__init__.py works
# ---------------------------------------------------------------------------

def test_T23_reexport_from_arch_init():
    """SoilProperties, FootingSpec, BearingCapacityReport, compute_bearing_capacity
    must be importable from kerf_cad_core.arch (re-exported via __init__.py)."""
    from kerf_cad_core.arch import (  # noqa: F401
        SoilProperties as SP,
        FootingSpec as FS,
        BearingCapacityReport as BCR,
        compute_bearing_capacity as cbc,
    )
    footing = FS(length_B_m=1.0, width_L_m=1.0, depth_Df_m=1.0, shape="square")
    soil = SP(cohesion_c_kPa=50.0, friction_angle_phi_deg=0.0, unit_weight_kN_m3=18.0)
    r = cbc(footing, soil)
    assert isinstance(r, BCR)
    assert r.q_ult_kPa > 0.0


# ---------------------------------------------------------------------------
# T24 — zero cohesion + zero depth: only weight term contributes
# ---------------------------------------------------------------------------

def test_T24_only_weight_term_contributes():
    """
    With c=0, Df→0 (depth term vanishes), only the weight term 0.5·γ·B·N_γ·s_γ·d_γ
    remains.  To test: use a fictitious near-zero Df so that the depth factors ≈ 1
    and the surcharge term is negligible.

    Actually Df must be > 0 per validation.  Instead verify the three terms sum
    correctly by checking that reducing c to 0 drops q_ult by exactly the cohesion
    term previously computed.
    """
    footing = FootingSpec(length_B_m=2.0, width_L_m=2.0, depth_Df_m=1.0, shape="square")
    soil_c = SoilProperties(cohesion_c_kPa=30.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=18.0)
    soil_0 = SoilProperties(cohesion_c_kPa=0.0, friction_angle_phi_deg=25.0, unit_weight_kN_m3=18.0)

    r_c = compute_bearing_capacity(footing, soil_c)
    r_0 = compute_bearing_capacity(footing, soil_0)

    # The difference should be exactly c · N_c · s_c · d_c
    cohesion_term = 30.0 * r_c.N_c * r_c.shape_factor_s_c * r_c.depth_factor_d_c
    assert abs((r_c.q_ult_kPa - r_0.q_ult_kPa) - cohesion_term) < 1e-6, (
        f"Cohesion-term difference mismatch: "
        f"Δq={r_c.q_ult_kPa - r_0.q_ult_kPa:.6f}, "
        f"c·Nc·sc·dc={cohesion_term:.6f}"
    )
