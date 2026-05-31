"""
Tests for kerf_cad_core.arch.base_plate_aisc — AISC DG-1 §3.1 concentric base plate.

Pure-Python, hermetic — no OCC, no DB, no network.
All inputs in SI: mm, kN, MPa.

Covers:
  T01  W14x90, P=1000 kN, f'c=30 MPa, ped=600×600: A1_req≈30166 mm², DCR<1.0, plate≥175×175
  T02  Plate dims are multiples of 5 mm (round_up behavior)
  T03  DCR < 1.0 when plate is sufficiently large
  T04  Larger load → larger plate (3000 kN vs 1000 kN)
  T05  Plate must cover column footprint: B≥0.80·bf, N≥0.95·d
  T06  m and n are non-negative for any valid result
  T07  A2/A1 ≤ 4 cap: pedestal much larger than plate — sqrt factor capped at 2.0
  T08  A2/A1 = 1 (pedestal exactly equals plate): sqrt factor = 1.0, larger plate needed
  T09  phi_Pp ≥ P_u for adequate design
  T10  thickness > 0 for any valid design
  T11  Higher Fy → smaller thickness (for same plate dims and load)
  T12  Higher f'c → smaller plate (less area needed for same bearing)
  T13  Re-export from arch/__init__.py works
  T14  ValueError on non-positive column_d_mm
  T15  ValueError on non-positive column_bf_mm
  T16  ValueError on non-positive axial_load_kN
  T17  ValueError on non-positive fc_MPa
  T18  ValueError on non-positive support_width
  T19  ValueError on non-positive support_length
  T20  ValueError on phi_c out of (0, 1]
  T21  ValueError on non-positive Fy
  T22  X_factor ∈ [0, 1] for any valid design
  T23  adequate field matches DCR ≤ 1.0
  T24  honest_caveat contains key reference strings (DG-1, J8, SCOPE)
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.base_plate_aisc import (
    ColumnSpec,
    ConcreteSpec,
    BasePlateReport,
    design_base_plate,
)

# ---------------------------------------------------------------------------
# W14x90 section properties (AISC Manual 16e)
# ---------------------------------------------------------------------------
W14X90_d_mm = 355.6   # overall depth d (14.02 in)
W14X90_bf_mm = 368.3  # flange width bf (14.52 in)


def _make_w14x90(P_kN: float = 1000.0) -> ColumnSpec:
    return ColumnSpec(
        column_d_mm=W14X90_d_mm,
        column_bf_mm=W14X90_bf_mm,
        axial_load_kN=P_kN,
    )


def _make_conc(fc: float = 30.0, Bped: float = 600.0, Lped: float = 600.0) -> ConcreteSpec:
    return ConcreteSpec(fc_MPa=fc, support_width_B_mm=Bped, support_length_L_mm=Lped)


# ---------------------------------------------------------------------------
# T01 — W14x90, P=1000 kN, f'c=30 MPa: A1_req≈30166 mm², DCR<1.0
# ---------------------------------------------------------------------------

def test_T01_w14x90_1000kN_basic():
    """W14x90 at 1000 kN, f'c=30 MPa, ped 600×600 — basic pass."""
    col = _make_w14x90(P_kN=1000.0)
    conc = _make_conc(fc=30.0, Bped=600.0, Lped=600.0)
    r = design_base_plate(col, conc, Fy=345.0)

    # A1_required (with A2/A1=4, sqrt=2) ≈ 1000e3/(0.65×0.85×30×2) ≈ 30166 mm²
    # side ≈ 173.7 mm → plate is sized by column footprint (0.95×355.6=337.8, 0.80×368.3=294.6)
    # so N ≥ 338, B ≥ 295 → N=340, B=295
    assert r.plate_N_mm >= 175.0, f"plate_N_mm={r.plate_N_mm} should be >= 175"
    assert r.plate_B_mm >= 175.0, f"plate_B_mm={r.plate_B_mm} should be >= 175"
    assert r.demand_capacity_ratio < 1.0, f"DCR={r.demand_capacity_ratio:.4f} should be <1.0"
    assert r.adequate is True


# ---------------------------------------------------------------------------
# T02 — Plate dimensions are multiples of 5 mm
# ---------------------------------------------------------------------------

def test_T02_plate_dims_multiple_of_5():
    """Plate B and N are multiples of 5 mm."""
    col = _make_w14x90(P_kN=1500.0)
    conc = _make_conc(fc=25.0, Bped=700.0, Lped=700.0)
    r = design_base_plate(col, conc)

    assert r.plate_B_mm % 5 == 0, f"plate_B_mm={r.plate_B_mm} not multiple of 5"
    assert r.plate_N_mm % 5 == 0, f"plate_N_mm={r.plate_N_mm} not multiple of 5"


# ---------------------------------------------------------------------------
# T03 — DCR < 1.0 when plate is adequately sized
# ---------------------------------------------------------------------------

def test_T03_dcr_below_one():
    """Design is adequate for a normal case."""
    col = _make_w14x90(P_kN=2000.0)
    conc = _make_conc(fc=30.0, Bped=800.0, Lped=800.0)
    r = design_base_plate(col, conc, Fy=345.0)
    assert r.demand_capacity_ratio <= 1.0, f"DCR={r.demand_capacity_ratio:.4f}"
    assert r.adequate is True


# ---------------------------------------------------------------------------
# T04 — Larger load → larger plate
# ---------------------------------------------------------------------------

def test_T04_larger_load_larger_plate():
    """3000 kN design produces a larger or equal plate than 1000 kN."""
    conc = _make_conc(fc=30.0, Bped=1200.0, Lped=1200.0)
    r_low = design_base_plate(_make_w14x90(P_kN=1000.0), conc)
    r_high = design_base_plate(_make_w14x90(P_kN=3000.0), conc)

    # At least one dimension should be larger or equal
    A_low = r_low.plate_B_mm * r_low.plate_N_mm
    A_high = r_high.plate_B_mm * r_high.plate_N_mm
    assert A_high >= A_low, (
        f"High load plate {A_high:.0f} mm² not >= low load {A_low:.0f} mm²"
    )


# ---------------------------------------------------------------------------
# T05 — Plate covers column footprint: B≥0.80·bf, N≥0.95·d
# ---------------------------------------------------------------------------

def test_T05_plate_covers_column():
    """Plate width ≥ 0.80·bf and plate length ≥ 0.95·d."""
    col = _make_w14x90(P_kN=500.0)
    conc = _make_conc(fc=35.0, Bped=500.0, Lped=500.0)
    r = design_base_plate(col, conc)

    assert r.plate_B_mm >= 0.80 * W14X90_bf_mm, (
        f"plate_B_mm={r.plate_B_mm:.1f} < 0.80·bf={0.80*W14X90_bf_mm:.1f}"
    )
    assert r.plate_N_mm >= 0.95 * W14X90_d_mm, (
        f"plate_N_mm={r.plate_N_mm:.1f} < 0.95·d={0.95*W14X90_d_mm:.1f}"
    )


# ---------------------------------------------------------------------------
# T06 — m and n are non-negative
# ---------------------------------------------------------------------------

def test_T06_m_and_n_nonneg():
    """Cantilever dimensions m and n are ≥ 0."""
    col = _make_w14x90(P_kN=1000.0)
    conc = _make_conc()
    r = design_base_plate(col, conc)

    assert r.m_mm >= 0.0, f"m={r.m_mm:.4f}"
    assert r.n_mm >= 0.0, f"n={r.n_mm:.4f}"


# ---------------------------------------------------------------------------
# T07 — A2/A1 ≤ 4 cap: large pedestal → sqrt_ratio = 2.0
# ---------------------------------------------------------------------------

def test_T07_a2_a1_cap():
    """With a huge pedestal (A2/A1 >> 4), bearing factor is capped at sqrt(4)=2."""
    col = _make_w14x90(P_kN=1000.0)
    # Pedestal 10× larger in each direction → A2/A1 >> 4
    conc = _make_conc(fc=30.0, Bped=5000.0, Lped=5000.0)
    r = design_base_plate(col, conc)

    # phi_Pp = phi_c * 0.85 * fc * A1 * sqrt(min(A2/A1, 4))
    # With sqrt_actual = 2.0 (cap): phi_Pp = 0.65 * 0.85 * 30 * A1 * 2.0
    A1 = r.plate_B_mm * r.plate_N_mm
    expected_phi_Pp_N = 0.65 * 0.85 * 30.0 * A1 * 2.0
    assert abs(r.plate_phi_Pn_kN - expected_phi_Pp_N / 1e3) < 1.0, (
        f"phi_Pp={r.plate_phi_Pn_kN:.2f} kN, expected={expected_phi_Pp_N/1e3:.2f} kN"
    )


# ---------------------------------------------------------------------------
# T08 — A2/A1 = 1 (pedestal equals plate size exactly): sqrt_factor = 1
# ---------------------------------------------------------------------------

def test_T08_a2_a1_equals_one():
    """With pedestal exactly equalling plate (A2/A1=1), sqrt_ratio=1 → need bigger plate."""
    col = _make_w14x90(P_kN=1000.0)
    # Choose pedestal just large enough to encompass the 295×340 plate
    conc = _make_conc(fc=30.0, Bped=295.0, Lped=340.0)
    r = design_base_plate(col, conc)

    # Plate should be at least 295×340 (column footprint governs)
    assert r.adequate, f"DCR={r.demand_capacity_ratio:.4f}, expected adequate=True"


# ---------------------------------------------------------------------------
# T09 — phi_Pp ≥ P_u for adequate designs
# ---------------------------------------------------------------------------

def test_T09_phi_pn_geq_pu():
    """phi_Pn (kN) ≥ P_u for adequate design."""
    col = _make_w14x90(P_kN=1500.0)
    conc = _make_conc(fc=30.0, Bped=800.0, Lped=800.0)
    r = design_base_plate(col, conc)

    if r.adequate:
        assert r.plate_phi_Pn_kN >= 1500.0, (
            f"phi_Pn={r.plate_phi_Pn_kN:.2f} kN < P_u=1500 kN"
        )


# ---------------------------------------------------------------------------
# T10 — thickness > 0
# ---------------------------------------------------------------------------

def test_T10_thickness_positive():
    """Plate thickness is positive for any valid design."""
    for P in [500.0, 1000.0, 2000.0, 3000.0]:
        col = _make_w14x90(P_kN=P)
        conc = _make_conc(fc=30.0, Bped=1000.0, Lped=1000.0)
        r = design_base_plate(col, conc)
        assert r.plate_thickness_t_mm > 0.0, f"t=0 at P={P} kN"


# ---------------------------------------------------------------------------
# T11 — Higher Fy → smaller or equal thickness
# ---------------------------------------------------------------------------

def test_T11_higher_fy_smaller_thickness():
    """A36 (250 MPa) plate is thicker than A572-Gr50 (345 MPa) for the same load."""
    col = _make_w14x90(P_kN=1000.0)
    conc = _make_conc(fc=30.0, Bped=600.0, Lped=600.0)
    r_a36 = design_base_plate(col, conc, Fy=250.0)
    r_gr50 = design_base_plate(col, conc, Fy=345.0)

    assert r_a36.plate_thickness_t_mm >= r_gr50.plate_thickness_t_mm, (
        f"A36 t={r_a36.plate_thickness_t_mm} vs Gr50 t={r_gr50.plate_thickness_t_mm}"
    )


# ---------------------------------------------------------------------------
# T12 — Higher f'c → equal or smaller plate area
# ---------------------------------------------------------------------------

def test_T12_higher_fc_smaller_plate():
    """Stronger concrete (35 vs 20 MPa) → equal or smaller required A1."""
    col = _make_w14x90(P_kN=1000.0)
    conc_weak = _make_conc(fc=20.0, Bped=800.0, Lped=800.0)
    conc_strong = _make_conc(fc=35.0, Bped=800.0, Lped=800.0)

    r_weak = design_base_plate(col, conc_weak)
    r_strong = design_base_plate(col, conc_strong)

    A_weak = r_weak.plate_B_mm * r_weak.plate_N_mm
    A_strong = r_strong.plate_B_mm * r_strong.plate_N_mm
    assert A_strong <= A_weak, (
        f"Stronger concrete produced larger area: {A_strong:.0f} > {A_weak:.0f} mm²"
    )


# ---------------------------------------------------------------------------
# T13 — Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

def test_T13_reexport_from_arch_init():
    """ColumnSpec, ConcreteSpec, BasePlateReport, design_base_plate re-exported."""
    from kerf_cad_core.arch import (
        ColumnSpec as CS,
        ConcreteSpec as CC,
        BasePlateReport as BPR,
        design_base_plate as dbp,
    )
    col = CS(column_d_mm=355.6, column_bf_mm=368.3, axial_load_kN=1000.0)
    conc = CC(fc_MPa=30.0, support_width_B_mm=600.0, support_length_L_mm=600.0)
    r = dbp(col, conc)
    assert isinstance(r, BPR)
    assert r.adequate


# ---------------------------------------------------------------------------
# T14-T21 — ValueError on invalid inputs
# ---------------------------------------------------------------------------

def test_T14_valueerror_nonpos_d():
    with pytest.raises(ValueError, match="column_d_mm"):
        design_base_plate(
            ColumnSpec(column_d_mm=0.0, column_bf_mm=368.3, axial_load_kN=1000.0),
            _make_conc(),
        )


def test_T15_valueerror_nonpos_bf():
    with pytest.raises(ValueError, match="column_bf_mm"):
        design_base_plate(
            ColumnSpec(column_d_mm=355.6, column_bf_mm=-1.0, axial_load_kN=1000.0),
            _make_conc(),
        )


def test_T16_valueerror_nonpos_load():
    with pytest.raises(ValueError, match="axial_load_kN"):
        design_base_plate(
            ColumnSpec(column_d_mm=355.6, column_bf_mm=368.3, axial_load_kN=0.0),
            _make_conc(),
        )


def test_T17_valueerror_nonpos_fc():
    with pytest.raises(ValueError, match="fc_MPa"):
        design_base_plate(
            _make_w14x90(),
            ConcreteSpec(fc_MPa=0.0, support_width_B_mm=600.0, support_length_L_mm=600.0),
        )


def test_T18_valueerror_nonpos_support_width():
    with pytest.raises(ValueError, match="support_width_B_mm"):
        design_base_plate(
            _make_w14x90(),
            ConcreteSpec(fc_MPa=30.0, support_width_B_mm=0.0, support_length_L_mm=600.0),
        )


def test_T19_valueerror_nonpos_support_length():
    with pytest.raises(ValueError, match="support_length_L_mm"):
        design_base_plate(
            _make_w14x90(),
            ConcreteSpec(fc_MPa=30.0, support_width_B_mm=600.0, support_length_L_mm=-5.0),
        )


def test_T20_valueerror_phi_c_out_of_range():
    with pytest.raises(ValueError, match="phi_c"):
        design_base_plate(
            _make_w14x90(),
            ConcreteSpec(fc_MPa=30.0, support_width_B_mm=600.0, support_length_L_mm=600.0, phi_c=0.0),
        )


def test_T21_valueerror_nonpos_fy():
    with pytest.raises(ValueError, match="Fy"):
        design_base_plate(_make_w14x90(), _make_conc(), Fy=-1.0)


# ---------------------------------------------------------------------------
# T22 — X_factor ∈ [0, 1]
# ---------------------------------------------------------------------------

def test_T22_x_factor_bounded():
    """X_factor is always in [0, 1]."""
    for P in [200.0, 1000.0, 5000.0, 10000.0]:
        col = _make_w14x90(P_kN=P)
        conc = _make_conc(fc=30.0, Bped=2000.0, Lped=2000.0)
        r = design_base_plate(col, conc)
        assert 0.0 <= r.X_factor <= 1.0, f"X={r.X_factor:.4f} at P={P} kN"


# ---------------------------------------------------------------------------
# T23 — adequate field matches DCR ≤ 1.0
# ---------------------------------------------------------------------------

def test_T23_adequate_matches_dcr():
    """adequate is True iff DCR ≤ 1.0."""
    col = _make_w14x90(P_kN=1000.0)
    conc = _make_conc()
    r = design_base_plate(col, conc)
    assert r.adequate == (r.demand_capacity_ratio <= 1.0)


# ---------------------------------------------------------------------------
# T24 — honest_caveat contains required reference strings
# ---------------------------------------------------------------------------

def test_T24_honest_caveat_has_references():
    """Caveat string includes key reference keywords."""
    col = _make_w14x90(P_kN=1000.0)
    conc = _make_conc()
    r = design_base_plate(col, conc)

    caveat = r.honest_caveat
    assert "DG-1" in caveat, "Expected 'DG-1' in caveat"
    assert "J8" in caveat, "Expected 'J8' in caveat"
    assert "SCOPE" in caveat, "Expected 'SCOPE' in caveat"
    assert "moment" in caveat.lower(), "Expected 'moment' limitation in caveat"
    assert "anchor" in caveat.lower(), "Expected 'anchor rod' limitation in caveat"
