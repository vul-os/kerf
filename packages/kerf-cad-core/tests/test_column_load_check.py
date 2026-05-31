"""
Tests for kerf_cad_core.arch.column_load_check — AISC 360-22 §E3 steel + ACI 318-19 §22.4 concrete.

All tests are hermetic (no OCC, no DB, no network).
All dimensions in mm and MPa; forces in kN.

Coverage:
  1.  Steel W14x90 — phi_Pn within 2% of AISC 360-22 E3 formula (manual calculation)
  2.  Steel W14x90 — inelastic buckling governs (KL/r < threshold)
  3.  Steel W14x90 — demand < capacity → DCR < 1.0, controls = "OK"
  4.  Steel column at very long KL — elastic Euler governs (KL/r > threshold)
  5.  Steel column KL/r > 200 → slender warning in honest_caveat
  6.  Steel column demand > capacity → DCR > 1.0, controls = "FAIL"
  7.  Concrete 400x400 — phi_Pn within 2% of ACI formula (manual calculation)
  8.  Concrete column — demand > capacity → DCR > 1.0, controls = "FAIL"
  9.  Concrete column rho_g < 0.01 → NOTE in caveat
  10. Concrete column rho_g > 0.08 → NOTE in caveat
  11. Steel — ValueError on non-positive area
  12. Steel — ValueError on non-positive radius of gyration
  13. Steel — ValueError on non-positive length
  14. Concrete — ValueError on Ast >= Ag
  15. Concrete — ValueError on non-positive fc
  16. LLM tool (async): steel → ok payload
  17. LLM tool (async): concrete → ok payload
  18. LLM tool (async): missing P_demand_kN → err payload
  19. LLM tool (async): invalid column_type → err payload
  20. LLM tool (async): missing steel fields → err payload
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.arch.column_load_check import (
    SteelColumnSpec,
    ConcreteColumnSpec,
    ColumnLoadReport,
    check_steel_column,
    check_concrete_column,
)
from kerf_cad_core.arch.column_load_check_tools import run_arch_check_column_load


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine in a fresh event loop."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _tool(args_dict: dict) -> dict:
    """Call the LLM tool wrapper and decode the JSON result."""
    raw = _run(run_arch_check_column_load(None, json.dumps(args_dict).encode()))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Reference values
# ---------------------------------------------------------------------------
# W14x90 — AISC 16th Ed Table 1-1:
#   A = 26.5 in² = 17 097 mm²  (26.5 × 645.16)
#   Iy = 362 in⁴; ry = √(362/26.5) = 3.696 in = 93.9 mm (weak axis governs)
#   Fy = 345 MPa (A572 Gr 50), E = 200 000 MPa, K = 1.0, L = 4 000 mm
#
# Manual AISC E3 calc (in SI):
#   KL/r = 1.0 × 4000 / 93.9 = 42.60
#   threshold = 4.71 × √(200000/345) = 113.4 → inelastic governs
#   Fe = π² × 200000 / 42.60² = 10 876 MPa  (very stiff section)
#   Fcr = 0.658^(345/10876) × 345 = 0.658^0.03172 × 345 ≈ 337.3 MPa
#   φPn = 0.90 × 337.3 × 17097 / 1000 ≈ 5 190 kN   (large W14 is very stocky)
#
# NOTE: The AISC Manual Table 4-1a lists ~4657 kN at KL=13 ft for W14x90 because
# the table is computed with the same formula.  Our SI calculation matches within
# float precision.  The test tolerance is ±2%.

W14X90_A_MM2 = 26.5 * 645.16          # 17 097 mm²
W14X90_RY_MM = math.sqrt(362 / 26.5) * 25.4  # 93.9 mm
W14X90_FY = 345.0   # MPa
W14X90_E  = 200_000.0
W14X90_K  = 1.0
W14X90_L  = 4_000.0  # mm


def _w14x90_expected_phi_Pn_kN() -> float:
    """Compute formula value once for reference assertions."""
    KLr = W14X90_K * W14X90_L / W14X90_RY_MM
    Fe = math.pi**2 * W14X90_E / KLr**2
    Fcr = (0.658 ** (W14X90_FY / Fe)) * W14X90_FY
    return 0.90 * Fcr * W14X90_A_MM2 / 1_000.0


# ACI 318-19 concrete reference (400×400, Ast=800 mm², fc=30, fy=420, φ=0.65)
CONC_AG   = 400.0 * 400.0   # 160 000 mm²
CONC_AST  = 800.0            # 8 cm²
CONC_FC   = 30.0
CONC_FY   = 420.0
CONC_PHI  = 0.65


def _conc_expected_phi_Pn_kN() -> float:
    Ac = CONC_AG - CONC_AST
    Pn_N = 0.80 * (0.85 * CONC_FC * Ac + CONC_FY * CONC_AST)
    return CONC_PHI * Pn_N / 1_000.0


# ---------------------------------------------------------------------------
# Test 1 — W14x90 phi_Pn within 2% of formula
# ---------------------------------------------------------------------------

def test_steel_w14x90_phi_Pn_within_2pct():
    """phi_Pn for W14x90 at KL=4000mm must be within 2% of manual AISC E3 calc."""
    spec = SteelColumnSpec(
        section_label="W14x90",
        A_mm2=W14X90_A_MM2,
        r_min_mm=W14X90_RY_MM,
        Fy_MPa=W14X90_FY,
        K=W14X90_K,
        L_mm=W14X90_L,
        E_MPa=W14X90_E,
    )
    report = check_steel_column(spec, P_service_kN=1000.0)
    expected = _w14x90_expected_phi_Pn_kN()
    assert abs(report.phi_Pn_kN - expected) / expected < 0.02, (
        f"phi_Pn={report.phi_Pn_kN:.2f} kN deviates >2% from expected {expected:.2f} kN"
    )


# ---------------------------------------------------------------------------
# Test 2 — W14x90 inelastic buckling governs
# ---------------------------------------------------------------------------

def test_steel_w14x90_inelastic_governs():
    """W14x90 at KL=4000mm: KL/r << threshold → inelastic mode reported."""
    spec = SteelColumnSpec(
        section_label="W14x90",
        A_mm2=W14X90_A_MM2,
        r_min_mm=W14X90_RY_MM,
        Fy_MPa=W14X90_FY,
        K=W14X90_K,
        L_mm=W14X90_L,
        E_MPa=W14X90_E,
    )
    report = check_steel_column(spec, P_service_kN=1000.0)
    assert "inelastic" in report.governing_mode.lower(), (
        f"Expected inelastic mode, got: {report.governing_mode}"
    )
    assert "E3-2" in report.governing_mode


# ---------------------------------------------------------------------------
# Test 3 — W14x90 demand < capacity → OK
# ---------------------------------------------------------------------------

def test_steel_w14x90_ok_when_demand_below_capacity():
    spec = SteelColumnSpec(
        section_label="W14x90",
        A_mm2=W14X90_A_MM2,
        r_min_mm=W14X90_RY_MM,
        Fy_MPa=W14X90_FY,
        K=W14X90_K,
        L_mm=W14X90_L,
        E_MPa=W14X90_E,
    )
    P_demand = _w14x90_expected_phi_Pn_kN() * 0.8  # 80% of capacity
    report = check_steel_column(spec, P_service_kN=P_demand)
    assert report.controls == "OK"
    assert report.demand_capacity_ratio < 1.0
    assert abs(report.demand_capacity_ratio - 0.80) < 0.005


# ---------------------------------------------------------------------------
# Test 4 — Elastic Euler buckling governs for very slender column
# ---------------------------------------------------------------------------

def test_steel_elastic_euler_governs_long_column():
    """A very long slender column should trigger elastic Euler buckling (E3-3)."""
    # Small r, large L to push KL/r > 4.71√(E/Fy)
    Fy = 250.0
    E = 200_000.0
    threshold = 4.71 * math.sqrt(E / Fy)  # ~133.3
    # Choose KL/r = 160 → L = 160 * r
    r = 20.0  # mm (very slender)
    L = 160.0 * r  # = 3200 mm
    spec = SteelColumnSpec(
        section_label="slender",
        A_mm2=500.0,
        r_min_mm=r,
        Fy_MPa=Fy,
        K=1.0,
        L_mm=L,
        E_MPa=E,
    )
    KLr = 1.0 * L / r
    assert KLr > threshold, "Setup error: KL/r should exceed threshold for this test"
    report = check_steel_column(spec, P_service_kN=10.0)
    assert "elastic" in report.governing_mode.lower(), (
        f"Expected elastic (Euler) mode, got: {report.governing_mode}"
    )
    assert "E3-3" in report.governing_mode


# ---------------------------------------------------------------------------
# Test 5 — KL/r > 200 → slender warning
# ---------------------------------------------------------------------------

def test_steel_slender_column_warning():
    """KL/r > 200 must produce a slenderness warning in honest_caveat."""
    # KL/r = 210
    r = 10.0
    L = 210.0 * r
    spec = SteelColumnSpec(
        section_label="HSS-slender",
        A_mm2=400.0,
        r_min_mm=r,
        Fy_MPa=345.0,
        K=1.0,
        L_mm=L,
        E_MPa=200_000.0,
    )
    report = check_steel_column(spec, P_service_kN=5.0)
    assert "KL/r > 200" in report.honest_caveat, (
        f"Expected slender-column warning; caveat: {report.honest_caveat}"
    )


# ---------------------------------------------------------------------------
# Test 6 — Demand > capacity → FAIL + DCR > 1.0
# ---------------------------------------------------------------------------

def test_steel_fail_when_demand_exceeds_capacity():
    """Demand 1500 kN on a column with capacity 1200 kN must FAIL (DCR > 1.0)."""
    # Construct a column with phi_Pn ≈ 1200 kN: Fcr ≈ 300 MPa, A ≈ 4444 mm²
    # Use: A=4500 mm², r=60 mm, L=3600 mm (KL/r=60), Fy=345 MPa → inelastic
    spec = SteelColumnSpec(
        section_label="small-section",
        A_mm2=4_500.0,
        r_min_mm=60.0,
        Fy_MPa=345.0,
        K=1.0,
        L_mm=3_600.0,
        E_MPa=200_000.0,
    )
    report_cap = check_steel_column(spec, P_service_kN=1.0)
    capacity = report_cap.phi_Pn_kN  # actual formula capacity
    demand = capacity * 1.25  # 25% over capacity

    report = check_steel_column(spec, P_service_kN=demand)
    assert report.controls == "FAIL", f"Expected FAIL, got {report.controls}"
    assert report.demand_capacity_ratio > 1.0, (
        f"Expected DCR > 1.0, got {report.demand_capacity_ratio:.4f}"
    )
    assert abs(report.demand_capacity_ratio - 1.25) < 0.01


# ---------------------------------------------------------------------------
# Test 7 — Concrete 400x400 phi_Pn within 2% of ACI formula
# ---------------------------------------------------------------------------

def test_concrete_400x400_phi_Pn_within_2pct():
    """ACI 318-19 §22.4: 400x400 tied column with Ast=800mm², fc=30, fy=420 MPa."""
    spec = ConcreteColumnSpec(
        A_g_mm2=CONC_AG,
        A_st_mm2=CONC_AST,
        fc_MPa=CONC_FC,
        fy_MPa=CONC_FY,
        phi=CONC_PHI,
    )
    report = check_concrete_column(spec, P_service_kN=1000.0)
    expected = _conc_expected_phi_Pn_kN()
    assert abs(report.phi_Pn_kN - expected) / expected < 0.02, (
        f"phi_Pn={report.phi_Pn_kN:.2f} kN deviates >2% from expected {expected:.2f} kN"
    )


# ---------------------------------------------------------------------------
# Test 8 — Concrete demand > capacity → FAIL + DCR > 1.0
# ---------------------------------------------------------------------------

def test_concrete_fail_when_demand_exceeds_capacity():
    """Concrete column demand 1.5× capacity → FAIL, DCR > 1.0."""
    spec = ConcreteColumnSpec(
        A_g_mm2=CONC_AG,
        A_st_mm2=CONC_AST,
        fc_MPa=CONC_FC,
        fy_MPa=CONC_FY,
        phi=CONC_PHI,
    )
    capacity = _conc_expected_phi_Pn_kN()
    demand = capacity * 1.5

    report = check_concrete_column(spec, P_service_kN=demand)
    assert report.controls == "FAIL"
    assert report.demand_capacity_ratio > 1.0
    assert abs(report.demand_capacity_ratio - 1.5) < 0.01


# ---------------------------------------------------------------------------
# Test 9 — rho_g < 0.01 → NOTE in caveat
# ---------------------------------------------------------------------------

def test_concrete_low_rho_note():
    """ρg < 0.01 (ACI §10.6.1.1 lower bound) triggers a NOTE in honest_caveat."""
    spec = ConcreteColumnSpec(
        A_g_mm2=200_000.0,   # 500×400 mm column
        A_st_mm2=1_000.0,    # ρg = 0.005 < 0.01
        fc_MPa=30.0,
        fy_MPa=420.0,
        phi=0.65,
    )
    report = check_concrete_column(spec, P_service_kN=100.0)
    assert "NOTE" in report.honest_caveat, (
        f"Expected rho_g NOTE in caveat; caveat: {report.honest_caveat}"
    )


# ---------------------------------------------------------------------------
# Test 10 — rho_g > 0.08 → NOTE in caveat
# ---------------------------------------------------------------------------

def test_concrete_high_rho_note():
    """ρg > 0.08 (ACI §10.6.1.1 upper bound) triggers a NOTE in honest_caveat."""
    spec = ConcreteColumnSpec(
        A_g_mm2=50_000.0,    # 250×200 column
        A_st_mm2=5_000.0,    # ρg = 0.10 > 0.08
        fc_MPa=30.0,
        fy_MPa=420.0,
        phi=0.65,
    )
    report = check_concrete_column(spec, P_service_kN=100.0)
    assert "NOTE" in report.honest_caveat, (
        f"Expected rho_g NOTE in caveat; caveat: {report.honest_caveat}"
    )


# ---------------------------------------------------------------------------
# Test 11 — ValueError on non-positive area (steel)
# ---------------------------------------------------------------------------

def test_steel_raises_on_zero_area():
    spec = SteelColumnSpec(
        section_label="bad",
        A_mm2=0.0,
        r_min_mm=50.0,
        Fy_MPa=345.0,
        K=1.0,
        L_mm=3000.0,
    )
    with pytest.raises(ValueError, match="A_mm2"):
        check_steel_column(spec, 100.0)


# ---------------------------------------------------------------------------
# Test 12 — ValueError on non-positive radius of gyration
# ---------------------------------------------------------------------------

def test_steel_raises_on_zero_r():
    spec = SteelColumnSpec(
        section_label="bad",
        A_mm2=5000.0,
        r_min_mm=0.0,
        Fy_MPa=345.0,
        K=1.0,
        L_mm=3000.0,
    )
    with pytest.raises(ValueError, match="r_min_mm"):
        check_steel_column(spec, 100.0)


# ---------------------------------------------------------------------------
# Test 13 — ValueError on non-positive length
# ---------------------------------------------------------------------------

def test_steel_raises_on_zero_length():
    spec = SteelColumnSpec(
        section_label="bad",
        A_mm2=5000.0,
        r_min_mm=50.0,
        Fy_MPa=345.0,
        K=1.0,
        L_mm=0.0,
    )
    with pytest.raises(ValueError, match="L_mm"):
        check_steel_column(spec, 100.0)


# ---------------------------------------------------------------------------
# Test 14 — ValueError on Ast >= Ag (concrete)
# ---------------------------------------------------------------------------

def test_concrete_raises_when_ast_exceeds_ag():
    spec = ConcreteColumnSpec(
        A_g_mm2=5_000.0,
        A_st_mm2=5_000.0,  # equal = invalid
        fc_MPa=30.0,
        fy_MPa=420.0,
    )
    with pytest.raises(ValueError, match="A_st_mm2"):
        check_concrete_column(spec, 100.0)


# ---------------------------------------------------------------------------
# Test 15 — ValueError on non-positive fc (concrete)
# ---------------------------------------------------------------------------

def test_concrete_raises_on_zero_fc():
    spec = ConcreteColumnSpec(
        A_g_mm2=160_000.0,
        A_st_mm2=1_600.0,
        fc_MPa=0.0,
        fy_MPa=420.0,
    )
    with pytest.raises(ValueError, match="fc_MPa"):
        check_concrete_column(spec, 100.0)


# ---------------------------------------------------------------------------
# Test 16 — LLM tool: steel → ok payload
# ---------------------------------------------------------------------------

def test_tool_steel_ok():
    """LLM tool wrapper returns phi_Pn for a valid steel column (ok_payload is the dict itself)."""
    result = _tool({
        "column_type": "steel",
        "P_demand_kN": 1000.0,
        "section_label": "W14x90",
        "A_mm2": W14X90_A_MM2,
        "r_min_mm": W14X90_RY_MM,
        "Fy_MPa": W14X90_FY,
        "K": W14X90_K,
        "L_mm": W14X90_L,
        "E_MPa": W14X90_E,
    })
    # ok_payload(dict) returns the dict directly; no outer {ok: true} wrapper
    assert "error" not in result, f"Unexpected error: {result}"
    assert "phi_Pn_kN" in result, f"Missing phi_Pn_kN in: {result}"
    assert result["phi_Pn_kN"] > 0
    assert result["controls"] == "OK"
    assert "demand_capacity_ratio" in result
    assert result["demand_capacity_ratio"] < 1.0


# ---------------------------------------------------------------------------
# Test 17 — LLM tool: concrete → ok payload
# ---------------------------------------------------------------------------

def test_tool_concrete_ok():
    """LLM tool wrapper returns phi_Pn for a valid concrete column."""
    result = _tool({
        "column_type": "concrete",
        "P_demand_kN": 1000.0,
        "A_g_mm2": CONC_AG,
        "A_st_mm2": CONC_AST,
        "fc_MPa": CONC_FC,
        "fy_MPa": CONC_FY,
        "phi": CONC_PHI,
    })
    assert "error" not in result, f"Unexpected error: {result}"
    assert "phi_Pn_kN" in result, f"Missing phi_Pn_kN in: {result}"
    expected = _conc_expected_phi_Pn_kN()
    assert abs(result["phi_Pn_kN"] - expected) < 1.0  # within 1 kN


# ---------------------------------------------------------------------------
# Test 18 — LLM tool: missing P_demand_kN → err
# ---------------------------------------------------------------------------

def test_tool_missing_demand():
    result = _tool({
        "column_type": "steel",
        "A_mm2": W14X90_A_MM2,
        "r_min_mm": W14X90_RY_MM,
        "Fy_MPa": W14X90_FY,
        "K": W14X90_K,
        "L_mm": W14X90_L,
    })
    # err_payload returns {"error": ..., "code": ...}
    assert "error" in result, f"Expected error response, got: {result}"
    assert "P_demand_kN" in result["error"]


# ---------------------------------------------------------------------------
# Test 19 — LLM tool: invalid column_type → err
# ---------------------------------------------------------------------------

def test_tool_invalid_type():
    result = _tool({
        "column_type": "timber",
        "P_demand_kN": 500.0,
    })
    assert "error" in result, f"Expected error response, got: {result}"
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 20 — LLM tool: missing steel fields → err
# ---------------------------------------------------------------------------

def test_tool_missing_steel_fields():
    result = _tool({
        "column_type": "steel",
        "P_demand_kN": 500.0,
        # A_mm2, r_min_mm, etc. omitted
    })
    assert "error" in result, f"Expected error response, got: {result}"
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Additional tests (tests 21-26 for extra robustness)
# ---------------------------------------------------------------------------

def test_steel_dcr_scales_linearly():
    """DCR should be proportional to P_demand_kN (linear system)."""
    spec = SteelColumnSpec(
        section_label="W14x90",
        A_mm2=W14X90_A_MM2,
        r_min_mm=W14X90_RY_MM,
        Fy_MPa=W14X90_FY,
        K=W14X90_K,
        L_mm=W14X90_L,
        E_MPa=W14X90_E,
    )
    r1 = check_steel_column(spec, P_service_kN=500.0)
    r2 = check_steel_column(spec, P_service_kN=1000.0)
    assert abs(r2.demand_capacity_ratio / r1.demand_capacity_ratio - 2.0) < 1e-6


def test_steel_phi_Pn_fixed_with_k():
    """phi_Pn should decrease as K increases (longer effective length)."""
    spec_pin = SteelColumnSpec("test", 5000.0, 50.0, 345.0, K=1.0, L_mm=3000.0)
    spec_fix = SteelColumnSpec("test", 5000.0, 50.0, 345.0, K=0.5, L_mm=3000.0)
    rep_pin = check_steel_column(spec_pin, 100.0)
    rep_fix = check_steel_column(spec_fix, 100.0)
    assert rep_fix.phi_Pn_kN > rep_pin.phi_Pn_kN, (
        "Fixed-fixed (K=0.5) should have greater capacity than pin-pin (K=1.0)"
    )


def test_concrete_phi_affects_capacity():
    """Spiral (phi=0.75) column should have higher phi_Pn than tied (phi=0.65)."""
    spec_tied = ConcreteColumnSpec(CONC_AG, CONC_AST, CONC_FC, CONC_FY, phi=0.65)
    spec_spiral = ConcreteColumnSpec(CONC_AG, CONC_AST, CONC_FC, CONC_FY, phi=0.75)
    r_tied = check_concrete_column(spec_tied, 1000.0)
    r_spiral = check_concrete_column(spec_spiral, 1000.0)
    assert r_spiral.phi_Pn_kN > r_tied.phi_Pn_kN
    # ratio should be 0.75/0.65
    assert abs(r_spiral.phi_Pn_kN / r_tied.phi_Pn_kN - 0.75 / 0.65) < 0.001


def test_concrete_governing_mode_label():
    """governing_mode should contain ACI reference."""
    spec = ConcreteColumnSpec(CONC_AG, CONC_AST, CONC_FC, CONC_FY)
    report = check_concrete_column(spec, 1000.0)
    assert "ACI" in report.governing_mode
    assert "22.4" in report.governing_mode


def test_steel_governing_mode_contains_kl_r():
    """governing_mode should include the KL/r value."""
    spec = SteelColumnSpec("W14x90", W14X90_A_MM2, W14X90_RY_MM, W14X90_FY, W14X90_K, W14X90_L)
    report = check_steel_column(spec, 1000.0)
    assert "KL/r=" in report.governing_mode


def test_steel_honest_caveat_includes_phi_Pn():
    """honest_caveat should include the computed phi_Pn value."""
    spec = SteelColumnSpec("W14x90", W14X90_A_MM2, W14X90_RY_MM, W14X90_FY, W14X90_K, W14X90_L)
    report = check_steel_column(spec, 1000.0)
    # caveat should contain 'φPn' or 'phi' and a number
    caveat = report.honest_caveat
    assert "φPn" in caveat or "phi" in caveat.lower()
    assert "AISC 360-22" in caveat


def test_concrete_honest_caveat_includes_aci():
    """honest_caveat must reference ACI 318-19 for concrete columns."""
    spec = ConcreteColumnSpec(CONC_AG, CONC_AST, CONC_FC, CONC_FY)
    report = check_concrete_column(spec, 500.0)
    assert "ACI 318-19" in report.honest_caveat
    assert "short column" in report.honest_caveat.lower()
