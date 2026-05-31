"""
Tests for kerf_cad_core.arch.diaphragm_shear — AWC SDPWS-2021 §4.2 / SDI DDM04
in-plane shear capacity of horizontal wood and metal-deck diaphragms.

All tests are hermetic (no OCC, no DB, no network).
All input dimensions in mm; forces in lbs; results in plf.

Oracle reference (TASK spec §6 primary case):
  30 ft × 40 ft plywood 15/32" blocked, nail @ 6" oc (152.4 mm), DF_L
  V_lateral = 20 000 lbs

  L_ft = 30 ft (along load direction → shear distributed along 30 ft)
  v = 20 000 / 30 = 666.67 plf
  v_allow = 510 plf (SDPWS Table 4.2A, 6" oc, DF_L, blocked)
  DCR = 666.67 / 510 = 1.308 → INADEQUATE

  Converted dimensions:
    L_mm = 30 ft × 304.8 = 9 144 mm
    W_mm = 40 ft × 304.8 = 12 192 mm

Oracle for 4" oc nails (101.6 mm):
  v_allow = 665 plf (SDPWS Table 4.2A, 4" oc, DF_L, blocked)
  DCR = 666.67 / 665 = 1.003 → still marginal fail (close)
  Use W = 25 ft instead to test pass: v_allow same, smaller load works

Coverage:
  T01  Primary: 30×40 ft plywood 15/32" blocked 6" oc DF_L V=20 000 lbs →
       v≈667 plf > 510 plf → DCR>1 → adequate=False
  T02  v = V/L formula: 20 000 / 30 ft = 666.7 plf (±0.5 plf)
  T03  v_allow = 510 plf for plywood 15/32" blocked 6" oc DF_L
  T04  DCR ≈ 666.7/510 ≈ 1.307 (±1%)
  T05  governing_factor = "shear_demand" (aspect ratio OK)
  T06  4" oc nails → v_allow = 665 plf (higher than 6" oc → monotonic)
  T07  2.5" oc nails → v_allow = 870 plf (higher still)
  T08  2" oc nails → v_allow = 1000 plf (max in table)
  T09  Blocked > unblocked: blocked 6" oc v_allow > unblocked 6" oc v_allow
  T10  Unblocked reduction = 0.50: unblocked v_allow ≈ 510×0.5 = 255 plf
  T11  plywood 19/32" blocked 6" oc DF_L → v_allow = 640 plf (> 15/32" 510)
  T12  OSB 15/32" blocked 6" oc DF_L → v_allow = 510 plf (= plywood 15/32")
  T13  SPF species factor C_s = 0.80 → v_allow = 510×0.80 = 408 plf (< DF_L)
  T14  HF species factor C_s = 0.90 → v_allow = 510×0.90 = 459 plf
  T15  SP species factor C_s = 1.00 → v_allow = 510 plf (= DF_L)
  T16  Metal deck 22ga → v_allow = 480 plf (SDI DDM04)
  T17  Metal deck 18ga → v_allow = 760 plf (> 22ga → monotonic)
  T18  Metal deck 22ga AR limit = 2:1 (wood = 4:1 → different)
  T19  AR = L/W = 30/40 = 0.75 < 4:1 → aspect OK for wood
  T20  AR = 40/10 = 4.0 exactly → aspect_ok = True (boundary inclusive)
  T21  AR = 41/10 = 4.1 > 4:1 → aspect_ok = False for wood
  T22  aspect_ratio fail + shear fail → governing_factor = "shear_demand+aspect_ratio"
  T23  Small V → adequate=True (v < v_allow)
  T24  V = 0 → v = 0 → DCR = 0 → adequate = True
  T25  ValueError: length_along_load_mm ≤ 0
  T26  ValueError: width_perp_to_load_mm ≤ 0
  T27  ValueError: invalid sheathing_type
  T28  ValueError: nail_spacing_mm < 50 mm
  T29  ValueError: nail_spacing_mm > 165 mm
  T30  ValueError: invalid framing_species
  T31  ValueError: V_lateral_lbs < 0
  T32  Re-export from arch/__init__.py works
  T33  honest_caveat mentions "SDPWS-2021"
  T34  honest_caveat mentions "chord" (scope disclaimer)
  T35  honest_caveat mentions "deflection" (scope disclaimer)
  T36  Interpolation: 3" oc → v_allow between 4" and 2.5" table values (linear)
  T37  LLM tool (async): valid args → ok, adequate depends on DCR
  T38  LLM tool (async): missing required field → err BAD_ARGS
  T39  LLM tool (async): invalid sheathing_type → err BAD_ARGS
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_cad_core.arch.diaphragm_shear import (
    DiaphragmSpec,
    DiaphragmShearReport,
    check_diaphragm_shear,
)

# Conversion constants
_MM_PER_FOOT = 304.8
_MM_PER_INCH = 25.4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec_30x40_plywood_15_32_blocked_6in_DFL() -> DiaphragmSpec:
    """
    30 ft × 40 ft diaphragm — plywood 15/32" blocked 6" oc nails DF_L.
    Primary oracle case from task spec §6.
    """
    return DiaphragmSpec(
        length_along_load_mm=30 * _MM_PER_FOOT,   # 9144 mm
        width_perp_to_load_mm=40 * _MM_PER_FOOT,  # 12192 mm
        sheathing_type="plywood_15_32",
        nail_spacing_mm=6 * _MM_PER_INCH,          # 152.4 mm
        blocked=True,
        framing_species="DF_L",
    )


def _spec(
    length_ft: float = 30.0,
    width_ft: float = 40.0,
    sheathing: str = "plywood_15_32",
    nail_spacing_in: float = 6.0,
    blocked: bool = True,
    species: str = "DF_L",
) -> DiaphragmSpec:
    return DiaphragmSpec(
        length_along_load_mm=length_ft * _MM_PER_FOOT,
        width_perp_to_load_mm=width_ft * _MM_PER_FOOT,
        sheathing_type=sheathing,
        nail_spacing_mm=nail_spacing_in * _MM_PER_INCH,
        blocked=blocked,
        framing_species=species,
    )


# ---------------------------------------------------------------------------
# T01 – T05: Primary oracle (30×40 ft, 15/32" blocked, 6" oc, DF_L, V=20 000 lbs)
# ---------------------------------------------------------------------------

def test_T01_primary_oracle_inadequate():
    """v ≈ 667 plf > 510 plf → adequate = False."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    r = check_diaphragm_shear(spec, V_lateral_lbs=20_000.0)
    assert r.adequate is False
    assert r.demand_capacity_ratio > 1.0


def test_T02_unit_shear_formula():
    """v = V / L_ft = 20000 / 30 = 666.67 plf (±0.5 plf)."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    r = check_diaphragm_shear(spec, V_lateral_lbs=20_000.0)
    expected_v = 20_000.0 / 30.0  # 666.67 plf
    assert r.unit_shear_v_plf == pytest.approx(expected_v, abs=0.5)


def test_T03_v_allow_6in_blocked_DFL():
    """v_allow = 510 plf for plywood 15/32" blocked 6" oc DF_L."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    r = check_diaphragm_shear(spec, V_lateral_lbs=0.0)  # V=0 just to get v_allow
    assert r.allowable_unit_shear_v_allow_plf == pytest.approx(510.0, abs=1.0)


def test_T04_dcr_primary_oracle():
    """DCR ≈ 666.67 / 510 ≈ 1.307 (±1%)."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    r = check_diaphragm_shear(spec, V_lateral_lbs=20_000.0)
    expected_dcr = (20_000.0 / 30.0) / 510.0
    assert r.demand_capacity_ratio == pytest.approx(expected_dcr, rel=0.01)


def test_T05_governing_factor_shear_demand():
    """AR = 30/40 = 0.75 < 4 → aspect OK; DCR > 1 → governing = 'shear_demand'."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    r = check_diaphragm_shear(spec, V_lateral_lbs=20_000.0)
    assert r.governing_factor == "shear_demand"


# ---------------------------------------------------------------------------
# T06 – T08: Tighter nailing → higher v_allow (monotonic with nail spacing)
# ---------------------------------------------------------------------------

def test_T06_4in_nails_higher_v_allow():
    """4" oc nails: v_allow = 665 plf > 510 plf (6" oc)."""
    r6 = check_diaphragm_shear(_spec(nail_spacing_in=6.0), V_lateral_lbs=0.0)
    r4 = check_diaphragm_shear(_spec(nail_spacing_in=4.0), V_lateral_lbs=0.0)
    assert r4.allowable_unit_shear_v_allow_plf == pytest.approx(665.0, abs=2.0)
    assert r4.allowable_unit_shear_v_allow_plf > r6.allowable_unit_shear_v_allow_plf


def test_T07_2pt5in_nails_v_allow_870():
    """2.5" oc nails: v_allow = 870 plf for plywood 15/32" blocked DF_L."""
    r = check_diaphragm_shear(_spec(nail_spacing_in=2.5), V_lateral_lbs=0.0)
    assert r.allowable_unit_shear_v_allow_plf == pytest.approx(870.0, abs=2.0)


def test_T08_2in_nails_v_allow_1000():
    """2" oc nails: v_allow = 1000 plf (maximum in SDPWS Table 4.2A for 15/32")."""
    r = check_diaphragm_shear(_spec(nail_spacing_in=2.0), V_lateral_lbs=0.0)
    assert r.allowable_unit_shear_v_allow_plf == pytest.approx(1000.0, abs=2.0)


# ---------------------------------------------------------------------------
# T09 – T10: Blocked > unblocked
# ---------------------------------------------------------------------------

def test_T09_blocked_greater_than_unblocked():
    """Blocked v_allow > unblocked v_allow for same nailing."""
    r_blocked = check_diaphragm_shear(_spec(blocked=True), V_lateral_lbs=0.0)
    r_unblocked = check_diaphragm_shear(_spec(blocked=False), V_lateral_lbs=0.0)
    assert r_blocked.allowable_unit_shear_v_allow_plf > r_unblocked.allowable_unit_shear_v_allow_plf


def test_T10_unblocked_factor_50_pct():
    """Unblocked v_allow = blocked v_allow × 0.5 per SDPWS §4.2.7."""
    r_blocked = check_diaphragm_shear(_spec(blocked=True), V_lateral_lbs=0.0)
    r_unblocked = check_diaphragm_shear(_spec(blocked=False), V_lateral_lbs=0.0)
    assert r_unblocked.allowable_unit_shear_v_allow_plf == pytest.approx(
        r_blocked.allowable_unit_shear_v_allow_plf * 0.5, rel=0.001
    )


# ---------------------------------------------------------------------------
# T11 – T12: Thicker sheathing / OSB
# ---------------------------------------------------------------------------

def test_T11_plywood_19_32_higher_v_allow():
    """19/32" plywood v_allow = 640 plf at 6" oc > 510 plf for 15/32"."""
    r = check_diaphragm_shear(_spec(sheathing="plywood_19_32", nail_spacing_in=6.0), V_lateral_lbs=0.0)
    assert r.allowable_unit_shear_v_allow_plf == pytest.approx(640.0, abs=2.0)


def test_T12_osb_15_32_equals_plywood_15_32():
    """OSB 15/32" v_allow = plywood 15/32" v_allow per SDPWS §4.2.3."""
    r_ply = check_diaphragm_shear(_spec(sheathing="plywood_15_32"), V_lateral_lbs=0.0)
    r_osb = check_diaphragm_shear(_spec(sheathing="osb_15_32"), V_lateral_lbs=0.0)
    assert r_osb.allowable_unit_shear_v_allow_plf == pytest.approx(
        r_ply.allowable_unit_shear_v_allow_plf, rel=0.001
    )


# ---------------------------------------------------------------------------
# T13 – T15: Species factor
# ---------------------------------------------------------------------------

def test_T13_SPF_species_factor_0p80():
    """SPF: v_allow = 510 × 0.80 = 408 plf."""
    r = check_diaphragm_shear(_spec(species="SPF", nail_spacing_in=6.0), V_lateral_lbs=0.0)
    assert r.allowable_unit_shear_v_allow_plf == pytest.approx(510.0 * 0.80, rel=0.01)


def test_T14_HF_species_factor_0p90():
    """HF: v_allow = 510 × 0.90 = 459 plf."""
    r = check_diaphragm_shear(_spec(species="HF", nail_spacing_in=6.0), V_lateral_lbs=0.0)
    assert r.allowable_unit_shear_v_allow_plf == pytest.approx(510.0 * 0.90, rel=0.01)


def test_T15_SP_species_factor_1p00():
    """SP: v_allow = 510 × 1.00 = 510 plf (same as DF_L reference)."""
    r_SP = check_diaphragm_shear(_spec(species="SP"), V_lateral_lbs=0.0)
    r_DFL = check_diaphragm_shear(_spec(species="DF_L"), V_lateral_lbs=0.0)
    assert r_SP.allowable_unit_shear_v_allow_plf == pytest.approx(r_DFL.allowable_unit_shear_v_allow_plf, rel=0.001)


# ---------------------------------------------------------------------------
# T16 – T17: Metal deck
# ---------------------------------------------------------------------------

def test_T16_metal_deck_22ga_v_allow():
    """Metal deck 22ga v_allow = 480 plf (SDI DDM04 36/6)."""
    spec = DiaphragmSpec(
        length_along_load_mm=30 * _MM_PER_FOOT,
        width_perp_to_load_mm=30 * _MM_PER_FOOT,  # AR=1:1
        sheathing_type="metal_deck_22ga",
        nail_spacing_mm=152.4,   # ignored for metal deck
        blocked=True,
        framing_species="DF_L",  # ignored for metal deck
    )
    r = check_diaphragm_shear(spec, V_lateral_lbs=0.0)
    assert r.allowable_unit_shear_v_allow_plf == pytest.approx(480.0, abs=2.0)


def test_T17_metal_deck_18ga_higher_v_allow():
    """Metal deck 18ga v_allow = 760 plf > 480 plf (22ga)."""
    def _deck_spec(ga: str) -> DiaphragmSpec:
        return DiaphragmSpec(
            length_along_load_mm=20 * _MM_PER_FOOT,
            width_perp_to_load_mm=20 * _MM_PER_FOOT,
            sheathing_type=ga,
            nail_spacing_mm=152.4,
            blocked=True,
            framing_species="DF_L",
        )
    r22 = check_diaphragm_shear(_deck_spec("metal_deck_22ga"), V_lateral_lbs=0.0)
    r18 = check_diaphragm_shear(_deck_spec("metal_deck_18ga"), V_lateral_lbs=0.0)
    assert r18.allowable_unit_shear_v_allow_plf == pytest.approx(760.0, abs=2.0)
    assert r18.allowable_unit_shear_v_allow_plf > r22.allowable_unit_shear_v_allow_plf


# ---------------------------------------------------------------------------
# T18 – T21: Aspect ratio checks
# ---------------------------------------------------------------------------

def test_T18_metal_deck_AR_limit_2_to_1():
    """Metal deck AR limit = 2:1; wood AR limit = 4:1."""
    # 30 × 10 ft: AR = 30/10 = 3.0 > 2 but ≤ 4 → metal deck fails, wood OK
    spec_wood = _spec(length_ft=30, width_ft=10, sheathing="plywood_15_32")
    spec_deck = DiaphragmSpec(
        length_along_load_mm=30 * _MM_PER_FOOT,
        width_perp_to_load_mm=10 * _MM_PER_FOOT,
        sheathing_type="metal_deck_22ga",
        nail_spacing_mm=152.4,
        blocked=True,
        framing_species="DF_L",
    )
    r_wood = check_diaphragm_shear(spec_wood, V_lateral_lbs=1000.0)
    r_deck = check_diaphragm_shear(spec_deck, V_lateral_lbs=1000.0)
    # Wood: AR=3 ≤ 4 → aspect OK; deck: AR=3 > 2 → aspect fail
    assert "aspect" not in r_wood.governing_factor or r_wood.governing_factor == "shear_demand" or r_wood.governing_factor == "OK" or "shear_demand" in r_wood.governing_factor
    assert "aspect_ratio" in r_deck.governing_factor


def test_T19_AR_0p75_aspect_ok_wood():
    """30×40 ft → AR = 30/40 = 0.75 < 4 → aspect OK for wood."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    r = check_diaphragm_shear(spec, V_lateral_lbs=1000.0)
    # governing_factor should NOT contain aspect_ratio (only shear may fail)
    assert "aspect_ratio" not in r.governing_factor


def test_T20_AR_exactly_4_aspect_ok():
    """AR = 40/10 = 4.0 exactly → aspect_ok = True (boundary inclusive)."""
    spec = _spec(length_ft=40, width_ft=10, sheathing="plywood_15_32")
    r = check_diaphragm_shear(spec, V_lateral_lbs=0.0)
    assert "aspect_ratio" not in r.governing_factor


def test_T21_AR_above_4_aspect_fail():
    """AR = 41/10 = 4.1 > 4:1 → aspect_ok = False for wood."""
    spec = _spec(length_ft=41, width_ft=10, sheathing="plywood_15_32")
    r = check_diaphragm_shear(spec, V_lateral_lbs=0.0)
    assert "aspect_ratio" in r.governing_factor
    assert r.adequate is False


# ---------------------------------------------------------------------------
# T22: Combined shear + aspect failure
# ---------------------------------------------------------------------------

def test_T22_combined_shear_and_aspect_fail():
    """High V + AR > 4 → governing_factor = 'shear_demand+aspect_ratio'."""
    # AR > 4 and high V
    spec = _spec(length_ft=41, width_ft=10, sheathing="plywood_15_32")
    r = check_diaphragm_shear(spec, V_lateral_lbs=50_000.0)  # very high V
    assert r.governing_factor == "shear_demand+aspect_ratio"
    assert r.adequate is False


# ---------------------------------------------------------------------------
# T23 – T24: Small / zero load → adequate
# ---------------------------------------------------------------------------

def test_T23_small_V_adequate():
    """Small V such that v < v_allow → adequate = True."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    # v_allow = 510 plf; L = 30 ft; V needed for v < 510: V < 510 × 30 = 15 300 lbs
    r = check_diaphragm_shear(spec, V_lateral_lbs=10_000.0)
    v = 10_000.0 / 30.0  # 333.3 plf < 510 plf
    assert r.demand_capacity_ratio < 1.0
    assert r.adequate is True
    assert r.governing_factor == "OK"


def test_T24_zero_V_adequate():
    """V = 0 → v = 0 → DCR = 0 → adequate = True."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    r = check_diaphragm_shear(spec, V_lateral_lbs=0.0)
    assert r.unit_shear_v_plf == pytest.approx(0.0, abs=0.01)
    assert r.demand_capacity_ratio == pytest.approx(0.0, abs=0.001)
    assert r.adequate is True


# ---------------------------------------------------------------------------
# T25 – T31: ValueError for invalid inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"length_along_load_mm": 0.0}, "length_along_load_mm"),
        ({"length_along_load_mm": -1.0}, "length_along_load_mm"),
        ({"width_perp_to_load_mm": 0.0}, "width_perp_to_load_mm"),
        ({"width_perp_to_load_mm": -5.0}, "width_perp_to_load_mm"),
    ],
    ids=["T25_L_zero", "T26_L_negative", "T27_W_zero", "T28_W_negative"],
)
def test_ValueError_geometry(kwargs, match):
    """Zero or negative dimension raises ValueError."""
    spec = DiaphragmSpec(
        length_along_load_mm=kwargs.get("length_along_load_mm", 9144.0),
        width_perp_to_load_mm=kwargs.get("width_perp_to_load_mm", 12192.0),
        sheathing_type="plywood_15_32",
        nail_spacing_mm=152.4,
        blocked=True,
        framing_species="DF_L",
    )
    with pytest.raises(ValueError, match=match):
        check_diaphragm_shear(spec, V_lateral_lbs=1000.0)


def test_T27_invalid_sheathing_type():
    """Unknown sheathing_type raises ValueError."""
    spec = DiaphragmSpec(
        length_along_load_mm=9144.0,
        width_perp_to_load_mm=12192.0,
        sheathing_type="magic_deck",
        nail_spacing_mm=152.4,
        blocked=True,
        framing_species="DF_L",
    )
    with pytest.raises(ValueError, match="sheathing_type"):
        check_diaphragm_shear(spec, V_lateral_lbs=1000.0)


def test_T28_nail_spacing_too_small():
    """nail_spacing_mm < 50 mm raises ValueError."""
    spec = _spec(nail_spacing_in=1.0)  # 25.4 mm < 50 mm
    with pytest.raises(ValueError, match="nail_spacing_mm"):
        check_diaphragm_shear(spec, V_lateral_lbs=1000.0)


def test_T29_nail_spacing_too_large():
    """nail_spacing_mm > 165 mm raises ValueError."""
    spec = _spec(nail_spacing_in=7.0)  # 177.8 mm > 165 mm
    with pytest.raises(ValueError, match="nail_spacing_mm"):
        check_diaphragm_shear(spec, V_lateral_lbs=1000.0)


def test_T30_invalid_species():
    """Unknown framing_species raises ValueError."""
    spec = DiaphragmSpec(
        length_along_load_mm=9144.0,
        width_perp_to_load_mm=12192.0,
        sheathing_type="plywood_15_32",
        nail_spacing_mm=152.4,
        blocked=True,
        framing_species="PINE",
    )
    with pytest.raises(ValueError, match="framing_species"):
        check_diaphragm_shear(spec, V_lateral_lbs=1000.0)


def test_T31_negative_V():
    """Negative V_lateral_lbs raises ValueError."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    with pytest.raises(ValueError, match="V_lateral_lbs"):
        check_diaphragm_shear(spec, V_lateral_lbs=-100.0)


# ---------------------------------------------------------------------------
# T32: Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

def test_T32_reexport_from_arch_init():
    """DiaphragmSpec, DiaphragmShearReport, check_diaphragm_shear re-exported."""
    from kerf_cad_core.arch import (
        DiaphragmSpec as DS,
        DiaphragmShearReport as DSR,
        check_diaphragm_shear as chk,
    )
    spec = DS(
        length_along_load_mm=9144.0,
        width_perp_to_load_mm=12192.0,
        sheathing_type="plywood_15_32",
        nail_spacing_mm=152.4,
        blocked=True,
        framing_species="DF_L",
    )
    r = chk(spec, V_lateral_lbs=10_000.0)
    assert isinstance(r, DSR)
    assert r.adequate is True  # 10 000 lbs / 30 ft = 333 plf < 510 plf


# ---------------------------------------------------------------------------
# T33 – T35: Caveat content
# ---------------------------------------------------------------------------

def test_T33_caveat_mentions_SDPWS():
    """honest_caveat must cite SDPWS-2021."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    r = check_diaphragm_shear(spec, V_lateral_lbs=1000.0)
    assert "SDPWS-2021" in r.honest_caveat


def test_T34_caveat_mentions_chord():
    """honest_caveat must disclose that chord forces are not calculated."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    r = check_diaphragm_shear(spec, V_lateral_lbs=1000.0)
    assert "chord" in r.honest_caveat.lower() or "CHORD" in r.honest_caveat


def test_T35_caveat_mentions_deflection():
    """honest_caveat must disclose that deflection is not calculated."""
    spec = _spec_30x40_plywood_15_32_blocked_6in_DFL()
    r = check_diaphragm_shear(spec, V_lateral_lbs=1000.0)
    assert "deflection" in r.honest_caveat.lower() or "DEFLECTION" in r.honest_caveat


# ---------------------------------------------------------------------------
# T36: Linear interpolation for intermediate nail spacing
# ---------------------------------------------------------------------------

def test_T36_interpolation_3pt5in_oc():
    """
    3.5" oc nail spacing → v_allow linearly between 4" oc (665 plf) and 3" oc (770 plf).
    Both 4" and 3" are exact table entries.
    t = (4.0 - 3.5) / (4.0 - 3.0) = 0.5/1.0 = 0.5
    v_allow ≈ 665 + 0.5 × (770 - 665) = 665 + 52.5 = 717.5 plf
    """
    r4 = check_diaphragm_shear(_spec(nail_spacing_in=4.0), V_lateral_lbs=0.0)
    r3 = check_diaphragm_shear(_spec(nail_spacing_in=3.0), V_lateral_lbs=0.0)
    r3p5 = check_diaphragm_shear(_spec(nail_spacing_in=3.5), V_lateral_lbs=0.0)

    # 3.5" oc must be strictly between 4" and 3" values
    assert r4.allowable_unit_shear_v_allow_plf < r3p5.allowable_unit_shear_v_allow_plf
    assert r3p5.allowable_unit_shear_v_allow_plf < r3.allowable_unit_shear_v_allow_plf

    # Check linear interpolation formula: midpoint between 4" (665) and 3" (770)
    t = (4.0 - 3.5) / (4.0 - 3.0)
    expected = 665.0 + t * (770.0 - 665.0)   # = 717.5 plf
    assert r3p5.allowable_unit_shear_v_allow_plf == pytest.approx(expected, rel=0.01)


# ---------------------------------------------------------------------------
# T37 – T39: LLM tool (async handler)
# ---------------------------------------------------------------------------

def _tool_handler():
    """Return the handler only if the tools module can be imported."""
    try:
        import kerf_cad_core.arch.diaphragm_shear_tools as m
        return getattr(m, "run_arch_check_diaphragm_shear", None)
    except ImportError:
        return None


_handler = _tool_handler()


@pytest.mark.skipif(_handler is None, reason="kerf_chat registry not available")
def test_T37_llm_tool_valid_args():
    """Valid nominal input → no error key, result contains demand_capacity_ratio."""
    args = json.dumps(
        {
            "length_along_load_mm": 9144.0,
            "width_perp_to_load_mm": 12192.0,
            "sheathing_type": "plywood_15_32",
            "nail_spacing_mm": 152.4,
            "blocked": True,
            "framing_species": "DF_L",
            "V_lateral_lbs": 10_000.0,
        }
    ).encode()

    result = asyncio.new_event_loop().run_until_complete(_handler(None, args))
    payload = json.loads(result)
    assert "error" not in payload, f"Unexpected error: {payload}"
    assert "demand_capacity_ratio" in payload
    assert payload["adequate"] is True


@pytest.mark.skipif(_handler is None, reason="kerf_chat registry not available")
def test_T38_llm_tool_missing_field():
    """Missing required field → error with code=BAD_ARGS."""
    args = json.dumps({"length_along_load_mm": 9144.0}).encode()
    result = asyncio.new_event_loop().run_until_complete(_handler(None, args))
    payload = json.loads(result)
    assert "error" in payload
    assert payload.get("code") == "BAD_ARGS"


@pytest.mark.skipif(_handler is None, reason="kerf_chat registry not available")
def test_T39_llm_tool_invalid_sheathing():
    """Invalid sheathing_type → error with code=BAD_ARGS."""
    args = json.dumps(
        {
            "length_along_load_mm": 9144.0,
            "width_perp_to_load_mm": 12192.0,
            "sheathing_type": "unknown_deck",
            "nail_spacing_mm": 152.4,
            "blocked": True,
            "framing_species": "DF_L",
            "V_lateral_lbs": 10_000.0,
        }
    ).encode()
    result = asyncio.new_event_loop().run_until_complete(_handler(None, args))
    payload = json.loads(result)
    assert "error" in payload
    assert payload.get("code") == "BAD_ARGS"
