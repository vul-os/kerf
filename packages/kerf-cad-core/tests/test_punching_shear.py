"""
Tests for kerf_cad_core.arch.punching_shear — ACI 318-19 §22.6 two-way shear.

All tests are hermetic (no OCC, no DB, no network).
All dimensions in mm, stresses in MPa, forces in kN.

Oracle reference case (task spec):
  300 mm² square column, 200 mm slab, d = 160 mm, f'c = 30 MPa:
    b_0 = 4·(300+160) = 1840 mm
    vc_basic = 0.33·√30 ≈ 1.8075 MPa
    φ·vc·b_0·d = 0.75·1.8075·1840·160 / 1000 ≈ 399.1 kN

Coverage:
  T01  Square col: b_0 = 4·(c+d) exactly
  T02  vc_basic = 0.33·√f'c for square (β_c=1 → vc_b > vc_a)
  T03  φ·Vn oracle ≈ 399.1 kN (within 0.1%)
  T04  DCR for V=300 kN < 1.0 → adequate=True
  T05  DCR for V=500 kN > 1.0 → adequate=False
  T06  DCR for V=900 kN > 1.0 → adequate=False, DCR ≈ 2.255
  T07  Rectangular col β_c=3 > 2 → governing_eqn = "aspect-ratio"
  T08  Rectangular b_0 = 2·(c1+d) + 2·(c2+d) exactly
  T09  Circular col: b_0 = π·(c+d)
  T10  Lightweight λ=0.75 reduces φ·Vn proportionally
  T11  f'c increase → higher φ·Vn (monotonic in f'c)
  T12  Edge column alpha_s=30: vc_c lower than interior → φ·Vn decreases
  T13  Corner column alpha_s=20: governs for large column (vc_c < vc_a)
  T14  Non-default phi=0.65 → φ·Vn scales with phi
  T15  ValueError: invalid column_shape
  T16  ValueError: column_size_mm <= 0
  T17  ValueError: slab_thickness_mm <= 0
  T18  ValueError: fc_MPa <= 0
  T19  ValueError: effective_depth_d_mm <= 0
  T20  ValueError: effective_depth_d_mm >= slab_thickness_mm
  T21  ValueError: rectangular missing column_width_b_mm
  T22  ValueError: column_width_b_mm < column_size_mm
  T23  ValueError: V_applied_kN < 0
  T24  ValueError: phi out of range
  T25  ValueError: invalid alpha_s
  T26  governing_eqn "perimeter" for interior square with d/b0 extreme
  T27  Re-export from arch/__init__.py
  T28  LLM tool (async): valid square → ok, adequate
  T29  LLM tool (async): missing required field → err BAD_ARGS
  T30  LLM tool (async): invalid column_shape → err BAD_ARGS
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_cad_core.arch.punching_shear import (
    ColumnSlabSpec,
    PunchingShearReport,
    check_punching_shear,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sq300(fc: float = 30.0, d: float = 160.0, h: float = 200.0) -> ColumnSlabSpec:
    """Standard oracle: 300 mm square col, 200 mm slab, d=160 mm."""
    return ColumnSlabSpec(
        column_size_mm=300.0,
        slab_thickness_mm=h,
        fc_MPa=fc,
        effective_depth_d_mm=d,
        column_shape="square",
    )


# ---------------------------------------------------------------------------
# T01 — Square column b_0 = 4·(c+d) exactly
# ---------------------------------------------------------------------------

def test_T01_square_b0_exact():
    """b_0 for a 300mm square col + d=160mm must equal 4·(300+160) = 1840mm."""
    spec = _sq300()
    r = check_punching_shear(spec, V_applied_kN=0.0)
    assert r.b_0_mm == pytest.approx(1840.0, abs=1e-9), (
        f"b_0 = {r.b_0_mm}, expected 1840"
    )


# ---------------------------------------------------------------------------
# T02 — vc_basic = 0.33·√f'c; for square β_c=1 → vc_aspect > vc_basic
# ---------------------------------------------------------------------------

def test_T02_vc_basic_formula_and_basic_governs():
    """vc_basic = 0.33·√30 ≈ 1.8075 MPa; β_c=1 → aspect eq > basic → basic governs."""
    spec = _sq300()
    r = check_punching_shear(spec, V_applied_kN=0.0)

    expected_vc_basic = 0.33 * math.sqrt(30.0)
    assert r.vc_basic_MPa == pytest.approx(expected_vc_basic, rel=1e-9)

    # For square: β_c=1 → vc_b = 0.17·3·√f'c = 0.51·√f'c > 0.33·√f'c
    assert r.vc_aspect_MPa > r.vc_basic_MPa

    # For this geometry vc_c > vc_a too (interior, d/b0 = 160/1840 ≈ 0.087)
    # vc_c = 0.083·(40·160/1840+2)·√30 ≈ 0.083·5.478·5.477 ≈ 2.49 MPa
    assert r.vc_perimeter_MPa > r.vc_basic_MPa

    # governing must be "basic"
    assert r.governing_eqn == "basic"
    assert r.vc_governing_MPa == pytest.approx(expected_vc_basic, rel=1e-9)


# ---------------------------------------------------------------------------
# T03 — φ·Vn oracle ≈ 399.1 kN
# ---------------------------------------------------------------------------

def test_T03_phi_Vn_oracle():
    """φ·Vn = 0.75·vc·b0·d = 0.75·1.8075·1840·160/1000 ≈ 399.09 kN."""
    spec = _sq300()
    r = check_punching_shear(spec, V_applied_kN=0.0)

    vc = 0.33 * math.sqrt(30.0)
    expected = 0.75 * vc * 1840.0 * 160.0 / 1_000.0
    assert r.phi_vc_kN == pytest.approx(expected, rel=1e-4), (
        f"φ·Vn = {r.phi_vc_kN:.3f} kN, expected {expected:.3f} kN"
    )


# ---------------------------------------------------------------------------
# T04 — V=300 kN → DCR < 1.0, adequate=True
# ---------------------------------------------------------------------------

def test_T04_V300_adequate():
    """V=300 kN on 1840mm perimeter → DCR ≈ 0.752 < 1.0."""
    r = check_punching_shear(_sq300(), V_applied_kN=300.0)
    assert r.adequate is True
    assert r.demand_capacity_ratio < 1.0
    # DCR ≈ 300 / 399.09 ≈ 0.7517
    assert r.demand_capacity_ratio == pytest.approx(300.0 / r.phi_vc_kN, rel=1e-9)


# ---------------------------------------------------------------------------
# T05 — V=500 kN → DCR > 1.0, adequate=False
# ---------------------------------------------------------------------------

def test_T05_V500_inadequate():
    """V=500 kN → DCR ≈ 1.253 > 1.0 → inadequate."""
    r = check_punching_shear(_sq300(), V_applied_kN=500.0)
    assert r.adequate is False
    assert r.demand_capacity_ratio > 1.0
    assert r.demand_capacity_ratio == pytest.approx(500.0 / r.phi_vc_kN, rel=1e-9)


# ---------------------------------------------------------------------------
# T06 — V=900 kN → DCR ≈ 2.255
# ---------------------------------------------------------------------------

def test_T06_V900_DCR():
    """V=900 kN → DCR ≈ 2.255 > 1.0 → inadequate."""
    r = check_punching_shear(_sq300(), V_applied_kN=900.0)
    assert r.adequate is False
    assert r.demand_capacity_ratio == pytest.approx(900.0 / r.phi_vc_kN, rel=1e-9)
    # Numerically: ≈ 900/399.09 ≈ 2.255
    assert r.demand_capacity_ratio == pytest.approx(2.255, rel=0.005)


# ---------------------------------------------------------------------------
# T07 — Rectangular col β_c = 3 > 2 → governing_eqn = "aspect-ratio"
# ---------------------------------------------------------------------------

def test_T07_rectangular_aspect_ratio_governs():
    """Rectangular col c1=200mm, c2=600mm → β_c=3 → vc_aspect < vc_basic."""
    spec = ColumnSlabSpec(
        column_size_mm=200.0,        # short side c1
        slab_thickness_mm=200.0,
        fc_MPa=30.0,
        effective_depth_d_mm=160.0,
        column_shape="rectangular",
        column_width_b_mm=600.0,     # long side c2
    )
    r = check_punching_shear(spec, V_applied_kN=0.0)

    assert r.governing_eqn == "aspect-ratio", (
        f"Expected 'aspect-ratio', got '{r.governing_eqn}'"
    )
    # vc_aspect = 0.17·(1+2/3)·√30 = 0.17·(5/3)·√30 ≈ 1.5519 MPa
    beta_c = 3.0
    expected_vc_b = 0.17 * (1.0 + 2.0 / beta_c) * math.sqrt(30.0)
    assert r.vc_aspect_MPa == pytest.approx(expected_vc_b, rel=1e-9)
    assert r.vc_governing_MPa == pytest.approx(expected_vc_b, rel=1e-9)


# ---------------------------------------------------------------------------
# T08 — Rectangular b_0 = 2·(c1+d) + 2·(c2+d)
# ---------------------------------------------------------------------------

def test_T08_rectangular_b0_formula():
    """b_0 for rect col c1=200, c2=600, d=160 = 2·360 + 2·760 = 2240 mm."""
    spec = ColumnSlabSpec(
        column_size_mm=200.0,
        slab_thickness_mm=200.0,
        fc_MPa=30.0,
        effective_depth_d_mm=160.0,
        column_shape="rectangular",
        column_width_b_mm=600.0,
    )
    r = check_punching_shear(spec, V_applied_kN=0.0)
    expected_b0 = 2.0 * (200.0 + 160.0) + 2.0 * (600.0 + 160.0)
    assert r.b_0_mm == pytest.approx(expected_b0, abs=1e-9)


# ---------------------------------------------------------------------------
# T09 — Circular column: b_0 = π·(c+d)
# ---------------------------------------------------------------------------

def test_T09_circular_b0():
    """Circular col c=300mm, d=160mm → b_0 = π·460 ≈ 1445.13 mm."""
    spec = ColumnSlabSpec(
        column_size_mm=300.0,
        slab_thickness_mm=200.0,
        fc_MPa=30.0,
        effective_depth_d_mm=160.0,
        column_shape="circular",
    )
    r = check_punching_shear(spec, V_applied_kN=0.0)
    expected_b0 = math.pi * (300.0 + 160.0)
    assert r.b_0_mm == pytest.approx(expected_b0, rel=1e-9)
    # φ·Vn_circ < φ·Vn_sq because b0 < 1840
    r_sq = check_punching_shear(_sq300(), V_applied_kN=0.0)
    assert r.phi_vc_kN < r_sq.phi_vc_kN


# ---------------------------------------------------------------------------
# T10 — Lightweight λ=0.75 reduces φ·Vn proportionally
# ---------------------------------------------------------------------------

def test_T10_lightweight_factor():
    """λ=0.75 → φ·Vn_lw = 0.75 · φ·Vn_nw."""
    spec_nw = _sq300()
    spec_lw = ColumnSlabSpec(
        column_size_mm=300.0,
        slab_thickness_mm=200.0,
        fc_MPa=30.0,
        effective_depth_d_mm=160.0,
        column_shape="square",
        lambda_factor=0.75,
    )
    r_nw = check_punching_shear(spec_nw, V_applied_kN=0.0)
    r_lw = check_punching_shear(spec_lw, V_applied_kN=0.0)

    assert r_lw.phi_vc_kN == pytest.approx(0.75 * r_nw.phi_vc_kN, rel=1e-9)
    # vc_basic_lw / vc_basic_nw = 0.75
    assert r_lw.vc_basic_MPa == pytest.approx(0.75 * r_nw.vc_basic_MPa, rel=1e-9)


# ---------------------------------------------------------------------------
# T11 — f'c increase → higher φ·Vn (monotonic)
# ---------------------------------------------------------------------------

def test_T11_fc_monotonic():
    """Higher f'c → higher φ·Vn (both governed by basic vc)."""
    r25 = check_punching_shear(_sq300(fc=25.0), V_applied_kN=0.0)
    r30 = check_punching_shear(_sq300(fc=30.0), V_applied_kN=0.0)
    r40 = check_punching_shear(_sq300(fc=40.0), V_applied_kN=0.0)
    assert r25.phi_vc_kN < r30.phi_vc_kN < r40.phi_vc_kN


# ---------------------------------------------------------------------------
# T12 — Edge column alpha_s=30: vc_c lower; φ·Vn < interior for same geometry
# ---------------------------------------------------------------------------

def test_T12_edge_column_lower_capacity():
    """alpha_s=30 (edge) → vc_c lower than interior → φ·Vn ≤ interior."""
    spec_int = ColumnSlabSpec(
        column_size_mm=300.0, slab_thickness_mm=200.0, fc_MPa=30.0,
        effective_depth_d_mm=160.0, column_shape="square", alpha_s=40,
    )
    spec_edge = ColumnSlabSpec(
        column_size_mm=300.0, slab_thickness_mm=200.0, fc_MPa=30.0,
        effective_depth_d_mm=160.0, column_shape="square", alpha_s=30,
    )
    r_int = check_punching_shear(spec_int, V_applied_kN=0.0)
    r_edge = check_punching_shear(spec_edge, V_applied_kN=0.0)

    # vc_c_edge < vc_c_interior; but basic still governs for both here
    assert r_edge.vc_perimeter_MPa < r_int.vc_perimeter_MPa
    # Both cases: basic governs for this geometry
    assert r_edge.governing_eqn == "basic"


# ---------------------------------------------------------------------------
# T13 — Corner alpha_s=20 on large column: vc_perimeter governs
# ---------------------------------------------------------------------------

def test_T13_corner_perimeter_governs():
    """alpha_s=20 with a very large column (d/b0 tiny) → vc_c < vc_a."""
    # Large column: c=800mm, d=160mm → b0=4·960=3840mm; d/b0=160/3840≈0.042
    # vc_c = 0.083·(20·0.042+2)·√30 = 0.083·2.833·5.477 ≈ 1.288 MPa < vc_a=1.808
    spec = ColumnSlabSpec(
        column_size_mm=800.0, slab_thickness_mm=1000.0, fc_MPa=30.0,
        effective_depth_d_mm=160.0, column_shape="square", alpha_s=20,
    )
    r = check_punching_shear(spec, V_applied_kN=0.0)
    assert r.governing_eqn == "perimeter", (
        f"Expected 'perimeter', got '{r.governing_eqn}'"
    )
    assert r.vc_governing_MPa < r.vc_basic_MPa


# ---------------------------------------------------------------------------
# T14 — Non-default phi=0.65 scales φ·Vn linearly
# ---------------------------------------------------------------------------

def test_T14_phi_scaling():
    """φ·Vn(phi=0.65) / φ·Vn(phi=0.75) = 0.65/0.75."""
    spec = _sq300()
    r75 = check_punching_shear(spec, V_applied_kN=0.0, phi=0.75)
    r65 = check_punching_shear(spec, V_applied_kN=0.0, phi=0.65)
    assert r65.phi_vc_kN == pytest.approx(r75.phi_vc_kN * (0.65 / 0.75), rel=1e-9)


# ---------------------------------------------------------------------------
# T15 — ValueError: invalid column_shape
# ---------------------------------------------------------------------------

def test_T15_invalid_shape():
    with pytest.raises(ValueError, match="column_shape"):
        check_punching_shear(
            ColumnSlabSpec(
                column_size_mm=300.0, slab_thickness_mm=200.0, fc_MPa=30.0,
                effective_depth_d_mm=160.0, column_shape="oval",
            ),
            V_applied_kN=100.0,
        )


# ---------------------------------------------------------------------------
# T16 — ValueError: column_size_mm <= 0
# ---------------------------------------------------------------------------

def test_T16_invalid_column_size():
    with pytest.raises(ValueError, match="column_size_mm"):
        check_punching_shear(
            ColumnSlabSpec(
                column_size_mm=0.0, slab_thickness_mm=200.0, fc_MPa=30.0,
                effective_depth_d_mm=160.0, column_shape="square",
            ),
            V_applied_kN=100.0,
        )


# ---------------------------------------------------------------------------
# T17 — ValueError: slab_thickness_mm <= 0
# ---------------------------------------------------------------------------

def test_T17_invalid_slab_thickness():
    with pytest.raises(ValueError, match="slab_thickness_mm"):
        check_punching_shear(
            ColumnSlabSpec(
                column_size_mm=300.0, slab_thickness_mm=0.0, fc_MPa=30.0,
                effective_depth_d_mm=160.0, column_shape="square",
            ),
            V_applied_kN=100.0,
        )


# ---------------------------------------------------------------------------
# T18 — ValueError: fc_MPa <= 0
# ---------------------------------------------------------------------------

def test_T18_invalid_fc():
    with pytest.raises(ValueError, match="fc_MPa"):
        check_punching_shear(
            ColumnSlabSpec(
                column_size_mm=300.0, slab_thickness_mm=200.0, fc_MPa=-1.0,
                effective_depth_d_mm=160.0, column_shape="square",
            ),
            V_applied_kN=100.0,
        )


# ---------------------------------------------------------------------------
# T19 — ValueError: effective_depth_d_mm <= 0
# ---------------------------------------------------------------------------

def test_T19_invalid_d_zero():
    with pytest.raises(ValueError, match="effective_depth_d_mm"):
        check_punching_shear(
            ColumnSlabSpec(
                column_size_mm=300.0, slab_thickness_mm=200.0, fc_MPa=30.0,
                effective_depth_d_mm=0.0, column_shape="square",
            ),
            V_applied_kN=100.0,
        )


# ---------------------------------------------------------------------------
# T20 — ValueError: effective_depth_d_mm >= slab_thickness_mm
# ---------------------------------------------------------------------------

def test_T20_d_exceeds_slab():
    with pytest.raises(ValueError, match="effective_depth_d_mm"):
        check_punching_shear(
            ColumnSlabSpec(
                column_size_mm=300.0, slab_thickness_mm=200.0, fc_MPa=30.0,
                effective_depth_d_mm=200.0, column_shape="square",
            ),
            V_applied_kN=100.0,
        )


# ---------------------------------------------------------------------------
# T21 — ValueError: rectangular column missing column_width_b_mm
# ---------------------------------------------------------------------------

def test_T21_rectangular_missing_width():
    with pytest.raises(ValueError, match="column_width_b_mm"):
        check_punching_shear(
            ColumnSlabSpec(
                column_size_mm=300.0, slab_thickness_mm=250.0, fc_MPa=30.0,
                effective_depth_d_mm=200.0, column_shape="rectangular",
                column_width_b_mm=None,
            ),
            V_applied_kN=100.0,
        )


# ---------------------------------------------------------------------------
# T22 — ValueError: column_width_b_mm < column_size_mm
# ---------------------------------------------------------------------------

def test_T22_width_less_than_size():
    with pytest.raises(ValueError, match="column_width_b_mm"):
        check_punching_shear(
            ColumnSlabSpec(
                column_size_mm=500.0, slab_thickness_mm=250.0, fc_MPa=30.0,
                effective_depth_d_mm=200.0, column_shape="rectangular",
                column_width_b_mm=300.0,  # 300 < 500 → invalid
            ),
            V_applied_kN=100.0,
        )


# ---------------------------------------------------------------------------
# T23 — ValueError: V_applied_kN < 0
# ---------------------------------------------------------------------------

def test_T23_negative_applied_shear():
    with pytest.raises(ValueError, match="V_applied_kN"):
        check_punching_shear(_sq300(), V_applied_kN=-10.0)


# ---------------------------------------------------------------------------
# T24 — ValueError: phi out of range
# ---------------------------------------------------------------------------

def test_T24_phi_out_of_range():
    with pytest.raises(ValueError, match="phi"):
        check_punching_shear(_sq300(), V_applied_kN=100.0, phi=1.5)


# ---------------------------------------------------------------------------
# T25 — ValueError: invalid alpha_s
# ---------------------------------------------------------------------------

def test_T25_invalid_alpha_s():
    with pytest.raises(ValueError, match="alpha_s"):
        check_punching_shear(
            ColumnSlabSpec(
                column_size_mm=300.0, slab_thickness_mm=200.0, fc_MPa=30.0,
                effective_depth_d_mm=160.0, column_shape="square", alpha_s=50,
            ),
            V_applied_kN=100.0,
        )


# ---------------------------------------------------------------------------
# T26 — Perimeter equation governs for interior col with large d/b0
# ---------------------------------------------------------------------------

def test_T26_perimeter_governs_small_col():
    """Very small col (c=50mm) → b0 small → d/b0 large → vc_c large (doesn't govern),
    but very small col with large d/b0 → vc_c is actually LARGE.
    Instead: check that for a typical interior column the three equations give
    the correct relative ordering when β_c=1."""
    # For square col c=50mm, d=160mm, b0=4·210=840mm
    # vc_c = 0.083·(40·160/840+2)·√30 = 0.083·9.619·5.477 ≈ 4.37 MPa
    # vc_b = 0.51·√30 ≈ 2.793 MPa
    # vc_a = 0.33·√30 ≈ 1.808 MPa → basic still governs
    spec = ColumnSlabSpec(
        column_size_mm=50.0, slab_thickness_mm=200.0, fc_MPa=30.0,
        effective_depth_d_mm=160.0, column_shape="square",
    )
    r = check_punching_shear(spec, V_applied_kN=0.0)
    assert r.governing_eqn == "basic"
    assert r.vc_basic_MPa < r.vc_perimeter_MPa  # vc_c > vc_a for small col

    # For a corner column (alpha_s=20) with large col, perimeter governs
    spec2 = ColumnSlabSpec(
        column_size_mm=800.0, slab_thickness_mm=1000.0, fc_MPa=30.0,
        effective_depth_d_mm=160.0, column_shape="square", alpha_s=20,
    )
    r2 = check_punching_shear(spec2, V_applied_kN=0.0)
    assert r2.governing_eqn == "perimeter"


# ---------------------------------------------------------------------------
# T27 — Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

def test_T27_reexport():
    """ColumnSlabSpec, PunchingShearReport, check_punching_shear are re-exported."""
    from kerf_cad_core.arch import (
        ColumnSlabSpec as _CS,
        PunchingShearReport as _PSR,
        check_punching_shear as _check,
    )
    assert _CS is ColumnSlabSpec
    assert _PSR is PunchingShearReport
    assert _check is check_punching_shear

    # Quick smoke test through the re-export path
    spec = _CS(
        column_size_mm=300.0, slab_thickness_mm=200.0, fc_MPa=30.0,
        effective_depth_d_mm=160.0, column_shape="square",
    )
    r = _check(spec, V_applied_kN=200.0)
    assert isinstance(r, _PSR)
    assert r.adequate is True


# ---------------------------------------------------------------------------
# T28 — LLM tool async: valid square → ok, adequate
# ---------------------------------------------------------------------------

def test_T28_tool_valid_square():
    """LLM tool returns success (no error key) for a valid square column under moderate load."""
    from kerf_cad_core.arch.punching_shear_tools import (
        run_arch_check_punching_shear,
    )

    payload = json.dumps({
        "column_size_mm": 300.0,
        "slab_thickness_mm": 200.0,
        "fc_MPa": 30.0,
        "effective_depth_d_mm": 160.0,
        "column_shape": "square",
        "V_applied_kN": 300.0,
    }).encode()

    result_str = asyncio.new_event_loop().run_until_complete(
        run_arch_check_punching_shear(None, payload)
    )
    result = json.loads(result_str)
    assert "error" not in result, f"Unexpected error: {result}"
    assert result["adequate"] is True
    assert result["governing_eqn"] == "basic"
    assert result["b_0_mm"] == pytest.approx(1840.0, abs=0.01)


# ---------------------------------------------------------------------------
# T29 — LLM tool async: missing required field → err BAD_ARGS
# ---------------------------------------------------------------------------

def test_T29_tool_missing_field():
    """Missing V_applied_kN → BAD_ARGS error."""
    from kerf_cad_core.arch.punching_shear_tools import (
        run_arch_check_punching_shear,
    )

    payload = json.dumps({
        "column_size_mm": 300.0,
        "slab_thickness_mm": 200.0,
        "fc_MPa": 30.0,
        "effective_depth_d_mm": 160.0,
        "column_shape": "square",
        # V_applied_kN omitted
    }).encode()

    result_str = asyncio.new_event_loop().run_until_complete(
        run_arch_check_punching_shear(None, payload)
    )
    result = json.loads(result_str)
    assert "error" in result, f"Expected error response, got: {result}"
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# T30 — LLM tool async: invalid column_shape → err BAD_ARGS
# ---------------------------------------------------------------------------

def test_T30_tool_invalid_shape():
    """Invalid column_shape → BAD_ARGS error."""
    from kerf_cad_core.arch.punching_shear_tools import (
        run_arch_check_punching_shear,
    )

    payload = json.dumps({
        "column_size_mm": 300.0,
        "slab_thickness_mm": 200.0,
        "fc_MPa": 30.0,
        "effective_depth_d_mm": 160.0,
        "column_shape": "pentagon",
        "V_applied_kN": 200.0,
    }).encode()

    result_str = asyncio.new_event_loop().run_until_complete(
        run_arch_check_punching_shear(None, payload)
    )
    result = json.loads(result_str)
    assert "error" in result, f"Expected error response, got: {result}"
    assert result.get("code") == "BAD_ARGS"
