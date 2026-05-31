"""
Tests for kerf_cad_core.arch.slab_on_grade — ACI 360R-10 + Westergaard (1948)
slab-on-grade thickness check under concentrated interior loads.

All tests are hermetic (no OCC, no DB, no network).
Units: mm, MPa, kN throughout.

Oracle reference (from task spec):
  slab_thickness_mm=150, fc=25 MPa, k=27.2 MPa/m, P=50 kN, contact=80 mm
  l ≈ 706 mm
  E = 4700·√25 = 23500 MPa
  k_N_mm3 = 27.2/1000 = 0.0272 N/mm³
  l = (23500·150³/(12·(1−0.15²)·0.0272))^0.25
  MR = 0.62·√25 = 3.10 MPa
  σ_max = 3·50000·1.15/(2·π·150²) · (log10(706/80)+0.5)
  DCR = σ_max/MR < 1.0  →  adequate
  Heavy load 200 kN  →  DCR > 1.0  →  inadequate
  Joint spacing 30·0.15 = 4.5 m

Coverage:
  T01  l oracle ≈ 706 mm (within 1 mm)
  T02  MR = 0.62·√f'c exactly
  T03  σ_max formula — components match manual calculation
  T04  50 kN load: DCR < 1, adequate=True
  T05  200 kN load: DCR > 1, adequate=False
  T06  Joint spacing = 30·h/1000 m exactly (h=150mm → 4.5 m)
  T07  Joint spacing = 30·h/1000 for h=200mm → 6.0 m
  T08  Monotonic: higher P → higher DCR
  T09  Monotonic: higher h → lower l AND lower σ_max (thicker slab is better)
  T10  Monotonic: higher k → lower l (softer subgrade → larger l, NOT lower)
  T11  Monotonic: higher fc → higher MR → lower DCR
  T12  ValueError: slab_thickness_mm <= 0
  T13  ValueError: fc_MPa <= 0
  T14  ValueError: subgrade_modulus_k_MPa_per_m <= 0
  T15  ValueError: point_load_kN <= 0
  T16  ValueError: contact_radius_mm <= 0
  T17  ValueError: slab_long_dimension_m <= 0
  T18  Re-export from arch/__init__.py
  T19  LLM tool (async): valid input → ok, adequate, l ≈ 706
  T20  LLM tool (async): missing required field → err BAD_ARGS
  T21  LLM tool (async): invalid fc → err BAD_ARGS
  T22  l formula: doubling h raises l by 2^(3/4) ≈ 1.6818
  T23  l formula: quadrupling E raises l by 4^(1/4) = √2
  T24  σ_max proportional to P (linearity)
  T25  DCR field consistent with σ_max / MR
  T26  recommended_joint_spacing_m = 30·h/1000 independent of slab_long_dimension_m
  T27  honest_caveat non-empty and mentions 'interior'
  T28  P=100 kN: DCR ≈ 2× the 50kN DCR (linearity)
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_cad_core.arch.slab_on_grade import (
    SlabOnGradeSpec,
    SlabOnGradeReport,
    check_slab_on_grade,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NU = 0.15  # Westergaard Poisson's ratio


def _oracle_spec(
    h: float = 150.0,
    fc: float = 25.0,
    k: float = 27.2,
    P: float = 50.0,
    b: float = 80.0,
    L: float = 6.0,
) -> SlabOnGradeSpec:
    """Oracle: 150mm slab, fc=25MPa, k=27.2MPa/m, P=50kN, b=80mm, L=6m."""
    return SlabOnGradeSpec(
        slab_thickness_mm=h,
        fc_MPa=fc,
        subgrade_modulus_k_MPa_per_m=k,
        point_load_kN=P,
        contact_radius_mm=b,
        slab_long_dimension_m=L,
    )


def _expected_l(h: float, fc: float, k_MPa_per_m: float) -> float:
    """Compute expected Westergaard l."""
    E = 4700.0 * math.sqrt(fc)
    k_N_mm3 = k_MPa_per_m / 1000.0
    return (E * h ** 3 / (12.0 * (1.0 - _NU ** 2) * k_N_mm3)) ** 0.25


def _expected_sigma(P_kN: float, h: float, l: float, b: float) -> float:
    """Compute expected max bending stress using PCA log10+0.5 formula."""
    P_N = P_kN * 1000.0
    return 3.0 * P_N * (1.0 + _NU) / (2.0 * math.pi * h ** 2) * (
        math.log10(l / b) + 0.5
    )


# ---------------------------------------------------------------------------
# T01 — l oracle ≈ 706 mm
# ---------------------------------------------------------------------------

def test_T01_l_oracle():
    """Radius of relative stiffness l ≈ 706 mm (within 1 mm of task oracle)."""
    r = check_slab_on_grade(_oracle_spec())
    assert r.radius_of_relative_stiffness_l_mm == pytest.approx(706.0, abs=1.0), (
        f"l = {r.radius_of_relative_stiffness_l_mm:.2f} mm, expected ≈ 706 mm"
    )


# ---------------------------------------------------------------------------
# T02 — MR = 0.62·√f'c exactly
# ---------------------------------------------------------------------------

def test_T02_MR_formula():
    """MR = 0.62·√25 = 3.10 MPa exactly."""
    r = check_slab_on_grade(_oracle_spec())
    expected_MR = 0.62 * math.sqrt(25.0)
    assert r.modulus_of_rupture_MR_MPa == pytest.approx(expected_MR, rel=1e-9)
    assert r.modulus_of_rupture_MR_MPa == pytest.approx(3.10, abs=1e-4)


# ---------------------------------------------------------------------------
# T03 — σ_max formula matches manual calculation
# ---------------------------------------------------------------------------

def test_T03_sigma_max_formula():
    """σ_max matches 3P(1+ν)/(2πh²)·(log10(l/b)+0.5) to 7 significant figures."""
    spec = _oracle_spec()
    r = check_slab_on_grade(spec)
    l = r.radius_of_relative_stiffness_l_mm
    expected_sigma = _expected_sigma(50.0, 150.0, l, 80.0)
    assert r.max_bending_stress_MPa == pytest.approx(expected_sigma, rel=1e-7)


# ---------------------------------------------------------------------------
# T04 — 50 kN → DCR < 1, adequate=True
# ---------------------------------------------------------------------------

def test_T04_50kN_adequate():
    """P=50 kN on 150mm slab with k=27.2 MPa/m → DCR < 1 → adequate."""
    r = check_slab_on_grade(_oracle_spec(P=50.0))
    assert r.adequate is True
    assert r.dcr < 1.0
    assert r.dcr == pytest.approx(r.max_bending_stress_MPa / r.modulus_of_rupture_MR_MPa, rel=1e-9)


# ---------------------------------------------------------------------------
# T05 — 200 kN → DCR > 1, adequate=False
# ---------------------------------------------------------------------------

def test_T05_200kN_inadequate():
    """P=200 kN → DCR > 1 → inadequate (slab too thin)."""
    r = check_slab_on_grade(_oracle_spec(P=200.0))
    assert r.adequate is False
    assert r.dcr > 1.0


# ---------------------------------------------------------------------------
# T06 — Joint spacing = 30·h/1000 m (h=150mm → 4.5 m)
# ---------------------------------------------------------------------------

def test_T06_joint_spacing_150mm():
    """30·h rule: 30·150/1000 = 4.5 m."""
    r = check_slab_on_grade(_oracle_spec(h=150.0))
    assert r.recommended_joint_spacing_m == pytest.approx(4.5, rel=1e-9)


# ---------------------------------------------------------------------------
# T07 — Joint spacing for h=200mm = 6.0 m
# ---------------------------------------------------------------------------

def test_T07_joint_spacing_200mm():
    """30·200/1000 = 6.0 m."""
    r = check_slab_on_grade(_oracle_spec(h=200.0))
    assert r.recommended_joint_spacing_m == pytest.approx(6.0, rel=1e-9)


# ---------------------------------------------------------------------------
# T08 — Higher P → higher DCR (monotonic)
# ---------------------------------------------------------------------------

def test_T08_load_monotonic():
    """DCR increases linearly with P."""
    r50 = check_slab_on_grade(_oracle_spec(P=50.0))
    r100 = check_slab_on_grade(_oracle_spec(P=100.0))
    r200 = check_slab_on_grade(_oracle_spec(P=200.0))
    assert r50.dcr < r100.dcr < r200.dcr


# ---------------------------------------------------------------------------
# T09 — Thicker slab: higher h → lower σ_max (better capacity)
# ---------------------------------------------------------------------------

def test_T09_thickness_monotonic():
    """Thicker slab → lower σ_max (larger l, lower stress coefficient)."""
    r150 = check_slab_on_grade(_oracle_spec(h=150.0))
    r200 = check_slab_on_grade(_oracle_spec(h=200.0))
    r250 = check_slab_on_grade(_oracle_spec(h=250.0))
    # Both MR and l increase, but the net effect is lower DCR for thicker slabs
    assert r150.dcr > r200.dcr > r250.dcr


# ---------------------------------------------------------------------------
# T10 — Higher k (stiffer subgrade) → LOWER l
# ---------------------------------------------------------------------------

def test_T10_k_effect_on_l():
    """Stiffer subgrade (higher k) → smaller l (shorter relative stiffness radius)."""
    r_soft = check_slab_on_grade(_oracle_spec(k=14.0))   # very soft
    r_med = check_slab_on_grade(_oracle_spec(k=27.2))    # medium
    r_stiff = check_slab_on_grade(_oracle_spec(k=55.0))  # stiff
    assert r_soft.radius_of_relative_stiffness_l_mm > r_med.radius_of_relative_stiffness_l_mm > r_stiff.radius_of_relative_stiffness_l_mm


# ---------------------------------------------------------------------------
# T11 — Higher f'c → higher MR → lower DCR
# ---------------------------------------------------------------------------

def test_T11_fc_monotonic():
    """Higher f'c → higher MR → lower DCR (monotonic)."""
    r25 = check_slab_on_grade(_oracle_spec(fc=25.0))
    r32 = check_slab_on_grade(_oracle_spec(fc=32.0))
    r40 = check_slab_on_grade(_oracle_spec(fc=40.0))
    assert r25.modulus_of_rupture_MR_MPa < r32.modulus_of_rupture_MR_MPa < r40.modulus_of_rupture_MR_MPa
    assert r25.dcr > r32.dcr > r40.dcr


# ---------------------------------------------------------------------------
# T12–T17 — ValueError on invalid inputs
# ---------------------------------------------------------------------------

def test_T12_invalid_thickness():
    with pytest.raises(ValueError, match="slab_thickness_mm"):
        check_slab_on_grade(_oracle_spec(h=0.0))


def test_T13_invalid_fc():
    with pytest.raises(ValueError, match="fc_MPa"):
        check_slab_on_grade(_oracle_spec(fc=-5.0))


def test_T14_invalid_k():
    with pytest.raises(ValueError, match="subgrade_modulus_k_MPa_per_m"):
        check_slab_on_grade(_oracle_spec(k=0.0))


def test_T15_invalid_load():
    with pytest.raises(ValueError, match="point_load_kN"):
        check_slab_on_grade(_oracle_spec(P=0.0))


def test_T16_invalid_contact_radius():
    with pytest.raises(ValueError, match="contact_radius_mm"):
        check_slab_on_grade(_oracle_spec(b=0.0))


def test_T17_invalid_long_dimension():
    with pytest.raises(ValueError, match="slab_long_dimension_m"):
        check_slab_on_grade(_oracle_spec(L=0.0))


# ---------------------------------------------------------------------------
# T18 — Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

def test_T18_reexport():
    """SlabOnGradeSpec, SlabOnGradeReport, check_slab_on_grade re-exported from arch."""
    from kerf_cad_core.arch import (
        SlabOnGradeSpec as _S,
        SlabOnGradeReport as _R,
        check_slab_on_grade as _check,
    )
    assert _S is SlabOnGradeSpec
    assert _R is SlabOnGradeReport
    assert _check is check_slab_on_grade

    spec = _S(
        slab_thickness_mm=150.0,
        fc_MPa=25.0,
        subgrade_modulus_k_MPa_per_m=27.2,
        point_load_kN=50.0,
        contact_radius_mm=80.0,
        slab_long_dimension_m=6.0,
    )
    r = _check(spec)
    assert isinstance(r, _R)
    assert r.adequate is True


# ---------------------------------------------------------------------------
# T19 — LLM tool (async): valid input → ok, adequate, l ≈ 706
# ---------------------------------------------------------------------------

def test_T19_tool_valid():
    """LLM tool returns ok payload for the oracle case."""
    from kerf_cad_core.arch.slab_on_grade_tools import run_arch_check_slab_on_grade

    payload = json.dumps({
        "slab_thickness_mm": 150.0,
        "fc_MPa": 25.0,
        "subgrade_modulus_k_MPa_per_m": 27.2,
        "point_load_kN": 50.0,
        "contact_radius_mm": 80.0,
        "slab_long_dimension_m": 6.0,
    }).encode()

    result_str = asyncio.new_event_loop().run_until_complete(
        run_arch_check_slab_on_grade(None, payload)
    )
    result = json.loads(result_str)
    assert "error" not in result, f"Unexpected error: {result}"
    assert result["adequate"] is True
    assert result["radius_of_relative_stiffness_l_mm"] == pytest.approx(706.0, abs=1.0)
    assert result["recommended_joint_spacing_m"] == pytest.approx(4.5, rel=1e-4)


# ---------------------------------------------------------------------------
# T20 — LLM tool (async): missing field → BAD_ARGS
# ---------------------------------------------------------------------------

def test_T20_tool_missing_field():
    """Missing fc_MPa → BAD_ARGS."""
    from kerf_cad_core.arch.slab_on_grade_tools import run_arch_check_slab_on_grade

    payload = json.dumps({
        "slab_thickness_mm": 150.0,
        # fc_MPa omitted
        "subgrade_modulus_k_MPa_per_m": 27.2,
        "point_load_kN": 50.0,
        "contact_radius_mm": 80.0,
        "slab_long_dimension_m": 6.0,
    }).encode()

    result_str = asyncio.new_event_loop().run_until_complete(
        run_arch_check_slab_on_grade(None, payload)
    )
    result = json.loads(result_str)
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# T21 — LLM tool (async): invalid fc → BAD_ARGS
# ---------------------------------------------------------------------------

def test_T21_tool_invalid_fc():
    """fc_MPa=-1 → BAD_ARGS (ValueError)."""
    from kerf_cad_core.arch.slab_on_grade_tools import run_arch_check_slab_on_grade

    payload = json.dumps({
        "slab_thickness_mm": 150.0,
        "fc_MPa": -1.0,
        "subgrade_modulus_k_MPa_per_m": 27.2,
        "point_load_kN": 50.0,
        "contact_radius_mm": 80.0,
        "slab_long_dimension_m": 6.0,
    }).encode()

    result_str = asyncio.new_event_loop().run_until_complete(
        run_arch_check_slab_on_grade(None, payload)
    )
    result = json.loads(result_str)
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# T22 — l formula: doubling h → l increases by 2^(3/4)
# ---------------------------------------------------------------------------

def test_T22_l_scales_with_h():
    """l ∝ h^(3/4): doubling h multiplies l by 2^(3/4) ≈ 1.6818."""
    r1 = check_slab_on_grade(_oracle_spec(h=100.0))
    r2 = check_slab_on_grade(_oracle_spec(h=200.0))
    expected_ratio = 2.0 ** (3.0 / 4.0)
    assert r2.radius_of_relative_stiffness_l_mm / r1.radius_of_relative_stiffness_l_mm == pytest.approx(
        expected_ratio, rel=1e-6
    )


# ---------------------------------------------------------------------------
# T23 — l formula: quadrupling E raises l by √2
# ---------------------------------------------------------------------------

def test_T23_l_scales_with_E():
    """l ∝ E^(1/4): quadrupling E (4×fc) → l × 4^(1/4) = √2 ≈ 1.4142.
    Note: E = 4700·√fc, so 4×E requires 16×fc."""
    # fc_base → fc_4x s.t. E_4x = 4·E_base: E = 4700√fc → 4700√fc_4x = 4·4700√fc_base
    # → fc_4x = 16·fc_base
    fc_base = 25.0
    fc_4x = fc_base * 16.0  # gives E_4x = 4·E_base
    r_base = check_slab_on_grade(_oracle_spec(fc=fc_base))
    r_4x = check_slab_on_grade(_oracle_spec(fc=fc_4x))
    expected_ratio = 4.0 ** 0.25  # = √2
    actual_ratio = (
        r_4x.radius_of_relative_stiffness_l_mm
        / r_base.radius_of_relative_stiffness_l_mm
    )
    assert actual_ratio == pytest.approx(expected_ratio, rel=1e-5)


# ---------------------------------------------------------------------------
# T24 — σ_max proportional to P (linearity)
# ---------------------------------------------------------------------------

def test_T24_sigma_proportional_to_P():
    """σ_max is linear in P: doubling P doubles σ_max."""
    r50 = check_slab_on_grade(_oracle_spec(P=50.0))
    r100 = check_slab_on_grade(_oracle_spec(P=100.0))
    assert r100.max_bending_stress_MPa == pytest.approx(
        2.0 * r50.max_bending_stress_MPa, rel=1e-9
    )


# ---------------------------------------------------------------------------
# T25 — DCR = σ_max / MR exactly
# ---------------------------------------------------------------------------

def test_T25_dcr_consistent():
    """DCR field = σ_max / MR to machine precision."""
    for P in [50.0, 100.0, 200.0]:
        r = check_slab_on_grade(_oracle_spec(P=P))
        assert r.dcr == pytest.approx(
            r.max_bending_stress_MPa / r.modulus_of_rupture_MR_MPa, rel=1e-9
        ), f"P={P}: DCR={r.dcr} ≠ σ/MR"


# ---------------------------------------------------------------------------
# T26 — joint spacing independent of slab_long_dimension_m
# ---------------------------------------------------------------------------

def test_T26_joint_spacing_independent_of_L():
    """recommended_joint_spacing_m = 30·h/1000 regardless of slab_long_dimension_m."""
    r6 = check_slab_on_grade(_oracle_spec(L=6.0))
    r3 = check_slab_on_grade(_oracle_spec(L=3.0))
    r12 = check_slab_on_grade(_oracle_spec(L=12.0))
    expected = 30.0 * 150.0 / 1000.0  # 4.5 m
    for r in [r6, r3, r12]:
        assert r.recommended_joint_spacing_m == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# T27 — honest_caveat non-empty and mentions 'interior'
# ---------------------------------------------------------------------------

def test_T27_honest_caveat_content():
    """honest_caveat is non-empty and explicitly states interior-load scope."""
    r = check_slab_on_grade(_oracle_spec())
    assert len(r.honest_caveat) > 100, "honest_caveat too short"
    assert "interior" in r.honest_caveat.lower()
    assert "edge" in r.honest_caveat.lower()
    assert "curling" in r.honest_caveat.lower()


# ---------------------------------------------------------------------------
# T28 — P=100 kN: DCR ≈ 2× the 50 kN DCR
# ---------------------------------------------------------------------------

def test_T28_double_load_double_DCR():
    """Linear model: P=100kN → DCR = 2× the DCR at P=50kN."""
    r50 = check_slab_on_grade(_oracle_spec(P=50.0))
    r100 = check_slab_on_grade(_oracle_spec(P=100.0))
    assert r100.dcr == pytest.approx(2.0 * r50.dcr, rel=1e-9)
