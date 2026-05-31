"""
Tests for kerf_cad_core.arch.shear_wall_oop — ACI 318-19 §11.7 RC shear wall OOP check.

All tests are hermetic (no OCC, no DB, no network).
All dimensions in mm, stresses in MPa, forces in kN/m, moments in kNm/m.

Oracle reference (main test case T01):
  t = 200 mm, h = 3000 mm, lw = 5000 mm
  f'c = 30 MPa, fy = 420 MPa, As_each_face = 300 mm²/m
  Pu = 100 kN/m, Mu = 20 kNm/m, k = 0.8, cover = 25 mm, phi = 0.65

  h/t = 15.0 (≤ 30 → OK)
  kh/32t = 0.8×3000/(32×200) = 0.3750
  reduction = 1 − 0.3750² = 0.85938
  A_g = 200 × 1000 = 200 000 mm²/m
  Pn  = 0.55 × 30 × 200 000 × 0.85938 / 1000 = 2835.94 kN/m
  φPn = 0.65 × 2835.94 = 1843.36 kN/m

  bar_area  = 300 × 200 / 1000 = 60 mm²; bar_dia = √(4×60/π) ≈ 8.74 mm
  d         = 200 − 25 − 4.37 ≈ 170.63 mm
  As_total  = 600 mm²/m
  a         = 600 × 420 / (0.85 × 30 × 1000) ≈ 9.882 mm
  Mn_Nmm/m  = 600 × 420 × (170.63 − 4.94) ≈ 41.75 × 10⁶ N·mm/m
  φMn       = 0.65 × 41.75 × 10⁶ / 10⁶ ≈ 27.14 kNm/m

  DCR = 100/1843.36 + 20/27.14 ≈ 0.054 + 0.737 ≈ 0.791 (adequate)

Coverage:
  T01  h/t = 15 → slenderness_ok = True
  T02  Oracle φPn within 0.5% of 1843.36 kN/m
  T03  Oracle φMn within 0.5% of 27.14 kNm/m
  T04  Oracle DCR ≈ 0.791 (< 1.0 → adequate)
  T05  governing_check == "OK" for nominal case
  T06  h = 7000 mm → h/t = 35 > 30 → slenderness_ok = False
  T07  h/t > 30 → governing_check starts with "slenderness"
  T08  High Mu (40 kNm/m) → DCR > 1 → adequate = False
  T09  High Mu → governing_check contains "interaction"
  T10  Both slenderness fail AND high Mu → governing_check = "slenderness+interaction"
  T11  k_factor = 1.0 (cantilever) → lower φPn than k=0.8
  T12  Higher As → higher φMn (monotonic)
  T13  Higher fc → higher φPn (monotonic)
  T14  h/t exactly 30 → slenderness_ok = True (boundary)
  T15  h/t just above 30 (30.001) → slenderness_ok = False (boundary)
  T16  Zero moment (Mu=0) → DCR = Pu/φPn only; adequate depends on Pu
  T17  Zero axial (Pu=0) → DCR = Mu/φMn only
  T18  phi non-default (0.75) → φPn/φMn scale proportionally
  T19  ValueError: wall_thickness_t_mm <= 0
  T20  ValueError: wall_height_h_mm <= 0
  T21  ValueError: wall_length_lw_mm <= 0
  T22  ValueError: fc_MPa <= 0
  T23  ValueError: fy_MPa <= 0
  T24  ValueError: As_each_face_mm2_per_m < 0
  T25  ValueError: axial_load_Pu_kN_per_m < 0
  T26  ValueError: oop_moment_Mu_kNm_per_m < 0
  T27  ValueError: phi out of range (phi > 1)
  T28  Re-export from arch/__init__.py works
  T29  honest_caveat mentions "ACI 318-19"
  T30  honest_caveat mentions "Bresler" (scope limitation disclosure)
  T31  LLM tool (async): valid args → ok, adequate True
  T32  LLM tool (async): missing required field → err BAD_ARGS
  T33  LLM tool (async): negative thickness → err BAD_ARGS
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_cad_core.arch.shear_wall_oop import (
    ShearWallSpec,
    ShearWallOOPReport,
    check_shear_wall_oop,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nominal_spec(**kwargs) -> ShearWallSpec:
    """Return the baseline oracle spec with optional field overrides."""
    base = dict(
        wall_thickness_t_mm=200.0,
        wall_height_h_mm=3000.0,
        wall_length_lw_mm=5000.0,
        fc_MPa=30.0,
        fy_MPa=420.0,
        As_each_face_mm2_per_m=300.0,
        axial_load_Pu_kN_per_m=100.0,
        oop_moment_Mu_kNm_per_m=20.0,
    )
    base.update(kwargs)
    return ShearWallSpec(**base)


# ---------------------------------------------------------------------------
# T01 – T05: Oracle / nominal case
# ---------------------------------------------------------------------------

def test_T01_slenderness_ok():
    """h/t = 15 should pass the ACI §11.5.3 slenderness limit h/t ≤ 30."""
    r = check_shear_wall_oop(_nominal_spec())
    assert r.slenderness_h_over_t == pytest.approx(15.0, abs=0.01)
    assert r.slenderness_ok is True


def test_T02_phi_Pn_oracle():
    """φPn should be within 0.5% of 1843.36 kN/m for the nominal case."""
    r = check_shear_wall_oop(_nominal_spec())
    assert r.phi_Pn_kN_per_m == pytest.approx(1843.36, rel=0.005)


def test_T03_phi_Mn_oracle():
    """φMn should be within 0.5% of 27.14 kNm/m for the nominal case."""
    r = check_shear_wall_oop(_nominal_spec())
    assert r.phi_Mn_kNm_per_m == pytest.approx(27.14, rel=0.005)


def test_T04_dcr_oracle():
    """DCR should be < 1.0 and approximately 0.791 for the nominal case."""
    r = check_shear_wall_oop(_nominal_spec())
    assert r.interaction_dcr == pytest.approx(0.791, rel=0.01)
    assert r.adequate is True


def test_T05_governing_check_ok():
    """governing_check should be 'OK' when all checks pass."""
    r = check_shear_wall_oop(_nominal_spec())
    assert r.governing_check == "OK"


# ---------------------------------------------------------------------------
# T06 – T07: Slenderness failure
# ---------------------------------------------------------------------------

def test_T06_slenderness_fail_h_over_t_35():
    """h = 7000 mm, t = 200 mm → h/t = 35 > 30 → slenderness_ok = False."""
    spec = _nominal_spec(wall_height_h_mm=7000.0)
    r = check_shear_wall_oop(spec)
    assert r.slenderness_h_over_t == pytest.approx(35.0, abs=0.01)
    assert r.slenderness_ok is False
    assert r.adequate is False


def test_T07_slenderness_fail_governing_check():
    """Slenderness-only failure should set governing_check to 'slenderness'."""
    spec = _nominal_spec(wall_height_h_mm=7000.0, oop_moment_Mu_kNm_per_m=1.0)
    r = check_shear_wall_oop(spec)
    assert "slenderness" in r.governing_check


# ---------------------------------------------------------------------------
# T08 – T09: Interaction failure (high Mu)
# ---------------------------------------------------------------------------

def test_T08_high_Mu_dcr_gt_1():
    """Mu = 40 kNm/m should push DCR > 1.0 for the nominal wall."""
    spec = _nominal_spec(oop_moment_Mu_kNm_per_m=40.0)
    r = check_shear_wall_oop(spec)
    assert r.interaction_dcr > 1.0
    assert r.adequate is False


def test_T09_high_Mu_governing_interaction():
    """High Mu with normal h/t should set governing_check = 'interaction'."""
    spec = _nominal_spec(oop_moment_Mu_kNm_per_m=40.0)
    r = check_shear_wall_oop(spec)
    assert r.governing_check == "interaction"


# ---------------------------------------------------------------------------
# T10: Combined slenderness + interaction failure
# ---------------------------------------------------------------------------

def test_T10_combined_slenderness_and_interaction():
    """Both h/t > 30 AND DCR > 1 → governing_check = 'slenderness+interaction'."""
    spec = _nominal_spec(
        wall_height_h_mm=7000.0,
        oop_moment_Mu_kNm_per_m=40.0,
    )
    r = check_shear_wall_oop(spec)
    assert not r.slenderness_ok
    assert r.interaction_dcr > 1.0
    assert r.governing_check == "slenderness+interaction"
    assert r.adequate is False


# ---------------------------------------------------------------------------
# T11: k_factor variation
# ---------------------------------------------------------------------------

def test_T11_cantilever_k1_lower_phi_Pn():
    """k = 1.0 (cantilever) gives larger kh/32t → lower φPn than k = 0.8."""
    r_fixed = check_shear_wall_oop(_nominal_spec(k_factor=0.8))
    r_cant = check_shear_wall_oop(_nominal_spec(k_factor=1.0))
    assert r_cant.phi_Pn_kN_per_m < r_fixed.phi_Pn_kN_per_m


# ---------------------------------------------------------------------------
# T12: Steel variation
# ---------------------------------------------------------------------------

def test_T12_more_steel_higher_phi_Mn():
    """Doubling As_each_face from 300 to 600 mm²/m should increase φMn."""
    r_low = check_shear_wall_oop(_nominal_spec(As_each_face_mm2_per_m=300.0))
    r_high = check_shear_wall_oop(_nominal_spec(As_each_face_mm2_per_m=600.0))
    assert r_high.phi_Mn_kNm_per_m > r_low.phi_Mn_kNm_per_m


# ---------------------------------------------------------------------------
# T13: fc variation
# ---------------------------------------------------------------------------

def test_T13_higher_fc_higher_phi_Pn():
    """Higher f'c should increase φPn (monotonic)."""
    r_low = check_shear_wall_oop(_nominal_spec(fc_MPa=25.0))
    r_high = check_shear_wall_oop(_nominal_spec(fc_MPa=40.0))
    assert r_high.phi_Pn_kN_per_m > r_low.phi_Pn_kN_per_m


# ---------------------------------------------------------------------------
# T14 – T15: Boundary slenderness h/t = 30
# ---------------------------------------------------------------------------

def test_T14_slenderness_exactly_30_ok():
    """h/t exactly 30 should be acceptable (boundary inclusive)."""
    spec = _nominal_spec(wall_height_h_mm=6000.0, wall_thickness_t_mm=200.0)
    r = check_shear_wall_oop(spec)
    assert r.slenderness_h_over_t == pytest.approx(30.0, abs=0.01)
    assert r.slenderness_ok is True


def test_T15_slenderness_just_above_30_fail():
    """h/t just above 30 (t=200, h=6001) should flag slenderness fail."""
    spec = _nominal_spec(wall_height_h_mm=6001.0, wall_thickness_t_mm=200.0)
    r = check_shear_wall_oop(spec)
    assert r.slenderness_h_over_t > 30.0
    assert r.slenderness_ok is False


# ---------------------------------------------------------------------------
# T16 – T17: Zero axial / zero moment
# ---------------------------------------------------------------------------

def test_T16_zero_moment_dcr_axial_only():
    """Zero moment → DCR = Pu/φPn only (no flexure term)."""
    spec = _nominal_spec(oop_moment_Mu_kNm_per_m=0.0)
    r = check_shear_wall_oop(spec)
    expected_dcr = 100.0 / r.phi_Pn_kN_per_m
    assert r.interaction_dcr == pytest.approx(expected_dcr, rel=0.001)


def test_T17_zero_axial_dcr_flexure_only():
    """Zero axial → DCR = Mu/φMn only (no axial term)."""
    spec = _nominal_spec(axial_load_Pu_kN_per_m=0.0)
    r = check_shear_wall_oop(spec)
    expected_dcr = 20.0 / r.phi_Mn_kNm_per_m
    assert r.interaction_dcr == pytest.approx(expected_dcr, rel=0.001)


# ---------------------------------------------------------------------------
# T18: Non-default phi
# ---------------------------------------------------------------------------

def test_T18_phi_075_scales_capacity():
    """phi = 0.75 should give φPn and φMn both 0.75/0.65 times the default."""
    r65 = check_shear_wall_oop(_nominal_spec(), phi=0.65)
    r75 = check_shear_wall_oop(_nominal_spec(), phi=0.75)
    ratio = 0.75 / 0.65
    assert r75.phi_Pn_kN_per_m == pytest.approx(r65.phi_Pn_kN_per_m * ratio, rel=0.001)
    assert r75.phi_Mn_kNm_per_m == pytest.approx(r65.phi_Mn_kNm_per_m * ratio, rel=0.001)


# ---------------------------------------------------------------------------
# T19 – T27: ValueError for invalid inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_kwargs, match",
    [
        ({"wall_thickness_t_mm": 0.0}, "wall_thickness_t_mm"),
        ({"wall_thickness_t_mm": -10.0}, "wall_thickness_t_mm"),
        ({"wall_height_h_mm": 0.0}, "wall_height_h_mm"),
        ({"wall_length_lw_mm": -1.0}, "wall_length_lw_mm"),
        ({"fc_MPa": 0.0}, "fc_MPa"),
        ({"fy_MPa": -420.0}, "fy_MPa"),
        ({"As_each_face_mm2_per_m": -1.0}, "As_each_face_mm2_per_m"),
        ({"axial_load_Pu_kN_per_m": -5.0}, "axial_load_Pu_kN_per_m"),
        ({"oop_moment_Mu_kNm_per_m": -1.0}, "oop_moment_Mu_kNm_per_m"),
    ],
    ids=[
        "T19_t_zero",
        "T20_t_negative",
        "T21_h_zero",
        "T22_lw_negative",
        "T23_fc_zero",
        "T24_fy_negative",
        "T25_As_negative",
        "T26_Pu_negative",
        "T27_Mu_negative",
    ],
)
def test_ValueError_invalid_inputs(bad_kwargs, match):
    """Invalid geometry or material inputs must raise ValueError."""
    spec = _nominal_spec(**bad_kwargs)
    with pytest.raises(ValueError, match=match):
        check_shear_wall_oop(spec)


def test_T27b_phi_out_of_range():
    """phi > 1.0 must raise ValueError."""
    with pytest.raises(ValueError, match="phi"):
        check_shear_wall_oop(_nominal_spec(), phi=1.5)


# ---------------------------------------------------------------------------
# T28: Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

def test_T28_reexport_from_arch_init():
    """ShearWallSpec, ShearWallOOPReport, check_shear_wall_oop all re-exported."""
    from kerf_cad_core.arch import (
        ShearWallSpec as SW,
        ShearWallOOPReport as SWOOP,
        check_shear_wall_oop as chk,
    )
    spec = SW(
        wall_thickness_t_mm=200.0,
        wall_height_h_mm=3000.0,
        wall_length_lw_mm=5000.0,
        fc_MPa=30.0,
        fy_MPa=420.0,
        As_each_face_mm2_per_m=300.0,
        axial_load_Pu_kN_per_m=100.0,
        oop_moment_Mu_kNm_per_m=20.0,
    )
    r = chk(spec)
    assert isinstance(r, SWOOP)
    assert r.slenderness_ok is True


# ---------------------------------------------------------------------------
# T29 – T30: Caveat content
# ---------------------------------------------------------------------------

def test_T29_caveat_mentions_aci():
    """honest_caveat must cite ACI 318-19."""
    r = check_shear_wall_oop(_nominal_spec())
    assert "ACI 318-19" in r.honest_caveat


def test_T30_caveat_mentions_bresler():
    """honest_caveat must disclose the Bresler interaction approximation."""
    r = check_shear_wall_oop(_nominal_spec())
    assert "Bresler" in r.honest_caveat


# ---------------------------------------------------------------------------
# T31 – T33: LLM tool (async handler)
# ---------------------------------------------------------------------------

def _tool_handler():
    """Return the handler only if the tools module can be imported."""
    try:
        import kerf_cad_core.arch.shear_wall_oop_tools as m
        return getattr(m, "run_arch_check_shear_wall_oop", None)
    except ImportError:
        return None


_handler = _tool_handler()


@pytest.mark.skipif(_handler is None, reason="kerf_chat registry not available")
def test_T31_llm_tool_valid_ok():
    """Valid nominal input → no error key, adequate=True, slenderness_ok=True."""
    args = json.dumps(
        {
            "wall_thickness_t_mm": 200.0,
            "wall_height_h_mm": 3000.0,
            "wall_length_lw_mm": 5000.0,
            "fc_MPa": 30.0,
            "fy_MPa": 420.0,
            "As_each_face_mm2_per_m": 300.0,
            "axial_load_Pu_kN_per_m": 100.0,
            "oop_moment_Mu_kNm_per_m": 20.0,
        }
    ).encode()

    result = asyncio.new_event_loop().run_until_complete(_handler(None, args))
    payload = json.loads(result)
    assert "error" not in payload, f"Unexpected error: {payload}"
    assert payload["adequate"] is True
    assert payload["slenderness_ok"] is True


@pytest.mark.skipif(_handler is None, reason="kerf_chat registry not available")
def test_T32_llm_tool_missing_field_err():
    """Missing required field → error key present, code=BAD_ARGS."""
    args = json.dumps({"wall_thickness_t_mm": 200.0}).encode()
    result = asyncio.new_event_loop().run_until_complete(_handler(None, args))
    payload = json.loads(result)
    assert "error" in payload
    assert payload.get("code") == "BAD_ARGS"


@pytest.mark.skipif(_handler is None, reason="kerf_chat registry not available")
def test_T33_llm_tool_invalid_thickness_err():
    """Negative wall thickness → error key present, code=BAD_ARGS."""
    args = json.dumps(
        {
            "wall_thickness_t_mm": -200.0,
            "wall_height_h_mm": 3000.0,
            "wall_length_lw_mm": 5000.0,
            "fc_MPa": 30.0,
            "fy_MPa": 420.0,
            "As_each_face_mm2_per_m": 300.0,
            "axial_load_Pu_kN_per_m": 100.0,
            "oop_moment_Mu_kNm_per_m": 20.0,
        }
    ).encode()
    result = asyncio.new_event_loop().run_until_complete(_handler(None, args))
    payload = json.loads(result)
    assert "error" in payload
    assert payload.get("code") == "BAD_ARGS"
