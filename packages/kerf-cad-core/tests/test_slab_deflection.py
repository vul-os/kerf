"""
Tests for kerf_cad_core.arch.slab_deflection.

Covers:
  1.  Square slab (a=b=5000 mm, h=200 mm, q=5 kPa, E=30000 MPa, ν=0.2, SS):
      δ vs. Timoshenko Table 41 α=0.00406 within 1%.
  2.  a/b=2 simply-supported: α=0.01013, formula match within 1%.
  3.  a/b=1.5 simply-supported: α=0.00772, formula match within 1%.
  4.  Thicker slab reduces deflection proportionally to h³.
  5.  Higher load increases deflection proportionally to q.
  6.  Fixed-fixed slab is stiffer (smaller δ) than simply-supported.
  7.  Fixed-fixed square slab α=0.00126 within 1%.
  8.  Zero load → zero deflection, zero moments.
  9.  Plate stiffness D = E·h³/(12·(1−ν²)) exact match.
  10. One-way strip limit: very large b/a → α approaches 0.01302 (SS).
  11. M_xx and M_yy are non-negative for positive load.
  12. Invalid length_a_mm → ValueError.
  13. Invalid thickness → ValueError.
  14. Invalid poisson → ValueError.
  15. Invalid edge_condition → ValueError.
  16. Negative load → ValueError.
  17. Re-export from arch/__init__.py.
  18. SlabDeflectionReport fields are all finite for valid inputs.
  19. Increasing h by factor 2 → δ decreases by factor 8 (h³ dependence).
  20. Square SS matches Roark 9e Table 11.4 reference value (within 1%).

All dimensions mm, loads kPa, stiffness N·mm, moments N·mm/mm.
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.slab_deflection import (
    SlabSpec,
    LoadSpec,
    SlabDeflectionReport,
    compute_slab_deflection,
)

# Re-export check
from kerf_cad_core.arch import (
    SlabDeflSpec as _SlabSpecFromInit,
    LoadSpec as _LoadSpecFromInit,
    SlabDeflectionReport as _ReportFromInit,
    compute_slab_deflection as _ComputeFromInit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel_err(actual: float, expected: float) -> float:
    """Relative error |actual - expected| / |expected|."""
    if expected == 0.0:
        return 0.0 if actual == 0.0 else float("inf")
    return abs(actual - expected) / abs(expected)


TOL_1PCT = 0.01    # 1% tolerance for Timoshenko oracle checks
TOL_TIGHT = 1e-9   # near-exact tolerance for algebraic identities


# ---------------------------------------------------------------------------
# Reference parameters
# ---------------------------------------------------------------------------

# Square slab 5 m × 5 m, h=200 mm, E=30000 MPa, ν=0.2, q=5 kPa
A_MM   = 5_000.0   # mm
B_MM   = 5_000.0   # mm
H_MM   = 200.0     # mm
E_MPA  = 30_000.0  # MPa
NU     = 0.2
Q_KPA  = 5.0       # kPa

# D = E·h³ / (12·(1−ν²))
_D_REF = E_MPA * (H_MM ** 3) / (12.0 * (1.0 - NU ** 2))

# q in N/mm²
_Q_N_MM2 = Q_KPA * 1.0e-3  # 0.005 N/mm²


# ---------------------------------------------------------------------------
# Test 1: Square slab (a/b = 1) simply-supported, α = 0.00406
# ---------------------------------------------------------------------------

def test_square_ss_timoshenko_alpha():
    """Square slab: δ_max matches Timoshenko Table 41 α=0.00406 within 1%."""
    alpha_ref = 0.00406
    delta_ref_mm = alpha_ref * _Q_N_MM2 * (A_MM ** 4) / _D_REF

    slab = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")
    report = compute_slab_deflection(slab, load)

    assert _rel_err(report.delta_max_mm, delta_ref_mm) < TOL_1PCT, (
        f"δ={report.delta_max_mm:.4f} mm, expected≈{delta_ref_mm:.4f} mm"
    )


# ---------------------------------------------------------------------------
# Test 2: a/b = 2, simply-supported, α = 0.01013
# ---------------------------------------------------------------------------

def test_ab2_ss_timoshenko_alpha():
    """a/b=2 SS: δ_max matches α=0.01013 within 1%."""
    a_mm = 3_000.0
    b_mm = 6_000.0   # b/a = 2.0
    alpha_ref = 0.01013
    D = E_MPA * (H_MM ** 3) / (12.0 * (1.0 - NU ** 2))
    q = Q_KPA * 1.0e-3
    delta_ref_mm = alpha_ref * q * (a_mm ** 4) / D

    slab = SlabSpec(
        length_a_mm=a_mm, width_b_mm=b_mm,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")
    report = compute_slab_deflection(slab, load)

    assert _rel_err(report.delta_max_mm, delta_ref_mm) < TOL_1PCT, (
        f"δ={report.delta_max_mm:.4f} mm, expected≈{delta_ref_mm:.4f} mm"
    )


# ---------------------------------------------------------------------------
# Test 3: a/b = 1.5, simply-supported, α = 0.00772
# ---------------------------------------------------------------------------

def test_ab15_ss_timoshenko_alpha():
    """a/b=1.5 SS: δ_max matches α=0.00772 within 1%."""
    a_mm = 4_000.0
    b_mm = 6_000.0   # b/a = 1.5
    alpha_ref = 0.00772
    D = E_MPA * (H_MM ** 3) / (12.0 * (1.0 - NU ** 2))
    q = Q_KPA * 1.0e-3
    delta_ref_mm = alpha_ref * q * (a_mm ** 4) / D

    slab = SlabSpec(
        length_a_mm=a_mm, width_b_mm=b_mm,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")
    report = compute_slab_deflection(slab, load)

    assert _rel_err(report.delta_max_mm, delta_ref_mm) < TOL_1PCT, (
        f"δ={report.delta_max_mm:.4f} mm, expected≈{delta_ref_mm:.4f} mm"
    )


# ---------------------------------------------------------------------------
# Test 4: Thicker slab → smaller deflection (h³ dependence)
# ---------------------------------------------------------------------------

def test_thickness_h_cubed_dependence():
    """Doubling h → δ decreases by factor ~8 (D scales as h³)."""
    slab1 = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    slab2 = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=H_MM * 2.0, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")

    r1 = compute_slab_deflection(slab1, load)
    r2 = compute_slab_deflection(slab2, load)

    ratio = r1.delta_max_mm / r2.delta_max_mm
    assert abs(ratio - 8.0) < 1e-6, (
        f"Expected δ(h)/δ(2h) ≈ 8, got {ratio:.6f}"
    )


# ---------------------------------------------------------------------------
# Test 5: Higher load → proportionally larger deflection
# ---------------------------------------------------------------------------

def test_load_proportionality():
    """Doubling q → δ doubles (linear elastic)."""
    slab = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load1 = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")
    load2 = LoadSpec(udl_kPa=Q_KPA * 2.0, edge_condition="simply_supported")

    r1 = compute_slab_deflection(slab, load1)
    r2 = compute_slab_deflection(slab, load2)

    ratio = r2.delta_max_mm / r1.delta_max_mm
    assert abs(ratio - 2.0) < 1e-9, (
        f"Expected δ(2q)/δ(q) = 2, got {ratio:.10f}"
    )


# ---------------------------------------------------------------------------
# Test 6: Fixed-fixed stiffer than simply-supported
# ---------------------------------------------------------------------------

def test_fixed_fixed_smaller_deflection_than_ss():
    """Fixed-fixed slab deflects less than simply-supported (same geometry + load)."""
    slab = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load_ss = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")
    load_ff = LoadSpec(udl_kPa=Q_KPA, edge_condition="fixed_fixed")

    r_ss = compute_slab_deflection(slab, load_ss)
    r_ff = compute_slab_deflection(slab, load_ff)

    assert r_ff.delta_max_mm < r_ss.delta_max_mm, (
        f"Fixed-fixed δ={r_ff.delta_max_mm:.4f} should be < SS δ={r_ss.delta_max_mm:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 7: Fixed-fixed square α = 0.00126 within 1%
# ---------------------------------------------------------------------------

def test_fixed_fixed_square_alpha():
    """Fixed-fixed square slab: δ_max matches Timoshenko Table 42 α=0.00126 within 1%."""
    alpha_ref = 0.00126
    delta_ref_mm = alpha_ref * _Q_N_MM2 * (A_MM ** 4) / _D_REF

    slab = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="fixed_fixed")
    report = compute_slab_deflection(slab, load)

    assert _rel_err(report.delta_max_mm, delta_ref_mm) < TOL_1PCT, (
        f"δ_ff={report.delta_max_mm:.4f} mm, expected≈{delta_ref_mm:.4f} mm"
    )


# ---------------------------------------------------------------------------
# Test 8: Zero load → zero deflection and zero moments
# ---------------------------------------------------------------------------

def test_zero_load_zero_deflection():
    """Zero load → δ = 0, M_xx = 0, M_yy = 0."""
    slab = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=0.0, edge_condition="simply_supported")
    report = compute_slab_deflection(slab, load)

    assert report.delta_max_mm == 0.0
    assert report.M_max_xx_Nmm_per_mm == 0.0
    assert report.M_max_yy_Nmm_per_mm == 0.0


# ---------------------------------------------------------------------------
# Test 9: Plate stiffness D exact algebraic identity
# ---------------------------------------------------------------------------

def test_plate_stiffness_D_exact():
    """D = E·h³/(12·(1−ν²)) matches the formula exactly."""
    slab = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")
    report = compute_slab_deflection(slab, load)

    D_expected = E_MPA * (H_MM ** 3) / (12.0 * (1.0 - NU ** 2))
    assert abs(report.plate_stiffness_D - D_expected) < 1e-3, (
        f"D={report.plate_stiffness_D:.6g}, expected={D_expected:.6g}"
    )


# ---------------------------------------------------------------------------
# Test 10: One-way strip limit: very long slab → α → 0.01302
# ---------------------------------------------------------------------------

def test_one_way_strip_limit_ss():
    """Very large b/a → α approaches one-way strip limit 0.01302."""
    a_mm = 1_000.0
    b_mm = 1_000_000.0  # b >> a, virtually a strip

    slab = SlabSpec(
        length_a_mm=a_mm, width_b_mm=b_mm,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")
    report = compute_slab_deflection(slab, load)

    D = E_MPA * (H_MM ** 3) / (12.0 * (1.0 - NU ** 2))
    q = Q_KPA * 1.0e-3
    alpha_computed = report.delta_max_mm * D / (q * a_mm ** 4)
    # α should be close to 5/384 = 0.013021 (one-way SS strip, Roark §8 case 2)
    assert _rel_err(alpha_computed, 0.01302) < 0.01, (
        f"alpha={alpha_computed:.6f} should be ≈0.01302"
    )


# ---------------------------------------------------------------------------
# Test 11: M_xx and M_yy non-negative for positive load
# ---------------------------------------------------------------------------

def test_moments_non_negative():
    """M_xx and M_yy are non-negative for positive UDL."""
    slab = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")
    report = compute_slab_deflection(slab, load)

    assert report.M_max_xx_Nmm_per_mm >= 0.0
    assert report.M_max_yy_Nmm_per_mm >= 0.0


# ---------------------------------------------------------------------------
# Test 12: Invalid length_a_mm → ValueError
# ---------------------------------------------------------------------------

def test_invalid_length_a():
    """Non-positive length_a_mm → ValueError."""
    with pytest.raises(ValueError, match="length_a_mm"):
        compute_slab_deflection(
            SlabSpec(length_a_mm=0.0, width_b_mm=B_MM,
                     thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU),
            LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported"),
        )


# ---------------------------------------------------------------------------
# Test 13: Invalid thickness → ValueError
# ---------------------------------------------------------------------------

def test_invalid_thickness():
    """Non-positive thickness_h_mm → ValueError."""
    with pytest.raises(ValueError, match="thickness_h_mm"):
        compute_slab_deflection(
            SlabSpec(length_a_mm=A_MM, width_b_mm=B_MM,
                     thickness_h_mm=-1.0, E_MPa=E_MPA, poisson=NU),
            LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported"),
        )


# ---------------------------------------------------------------------------
# Test 14: Invalid Poisson's ratio → ValueError
# ---------------------------------------------------------------------------

def test_invalid_poisson():
    """Poisson's ratio = 0.5 → ValueError (incompressible; excluded)."""
    with pytest.raises(ValueError, match="poisson"):
        compute_slab_deflection(
            SlabSpec(length_a_mm=A_MM, width_b_mm=B_MM,
                     thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=0.5),
            LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported"),
        )


# ---------------------------------------------------------------------------
# Test 15: Invalid edge_condition → ValueError
# ---------------------------------------------------------------------------

def test_invalid_edge_condition():
    """Unknown edge_condition → ValueError."""
    with pytest.raises(ValueError, match="edge_condition"):
        compute_slab_deflection(
            SlabSpec(length_a_mm=A_MM, width_b_mm=B_MM,
                     thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU),
            LoadSpec(udl_kPa=Q_KPA, edge_condition="clamped_free"),
        )


# ---------------------------------------------------------------------------
# Test 16: Negative load → ValueError
# ---------------------------------------------------------------------------

def test_negative_load():
    """Negative udl_kPa → ValueError."""
    with pytest.raises(ValueError, match="udl_kPa"):
        compute_slab_deflection(
            SlabSpec(length_a_mm=A_MM, width_b_mm=B_MM,
                     thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU),
            LoadSpec(udl_kPa=-1.0, edge_condition="simply_supported"),
        )


# ---------------------------------------------------------------------------
# Test 17: Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

def test_re_export_from_init():
    """SlabDeflSpec, LoadSpec, SlabDeflectionReport, compute_slab_deflection
    are importable from kerf_cad_core.arch."""
    assert _SlabSpecFromInit is SlabSpec
    assert _LoadSpecFromInit is LoadSpec
    assert _ReportFromInit is SlabDeflectionReport
    assert _ComputeFromInit is compute_slab_deflection


# ---------------------------------------------------------------------------
# Test 18: Report fields are all finite for valid inputs
# ---------------------------------------------------------------------------

def test_report_fields_finite():
    """All SlabDeflectionReport numeric fields are finite for valid inputs."""
    slab = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")
    report = compute_slab_deflection(slab, load)

    assert math.isfinite(report.delta_max_mm)
    assert math.isfinite(report.M_max_xx_Nmm_per_mm)
    assert math.isfinite(report.M_max_yy_Nmm_per_mm)
    assert math.isfinite(report.plate_stiffness_D)
    assert report.plate_stiffness_D > 0.0
    assert report.delta_max_mm > 0.0


# ---------------------------------------------------------------------------
# Test 19: h doubled → δ decreases by exactly factor 8 (h³ scaling)
# ---------------------------------------------------------------------------

def test_thickness_doubling_reduces_deflection_by_8():
    """Increasing h by factor 2 reduces δ by factor 8 (D ∝ h³)."""
    slab_thin = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=150.0, E_MPa=E_MPA, poisson=NU,
    )
    slab_thick = SlabSpec(
        length_a_mm=A_MM, width_b_mm=B_MM,
        thickness_h_mm=300.0, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")

    r_thin = compute_slab_deflection(slab_thin, load)
    r_thick = compute_slab_deflection(slab_thick, load)

    ratio = r_thin.delta_max_mm / r_thick.delta_max_mm
    assert abs(ratio - 8.0) < 1e-6, f"Expected ratio=8, got {ratio:.8f}"


# ---------------------------------------------------------------------------
# Test 20: Explicit numerical oracle — square slab, SS
# δ = α·q·a⁴/D = 0.00406 × 0.005 × 5000⁴ / D
# ---------------------------------------------------------------------------

def test_square_ss_numerical_oracle():
    """Explicit numerical check: square slab 5×5 m, h=200 mm, q=5 kPa, SS."""
    a = 5_000.0   # mm
    h = 200.0     # mm
    E = 30_000.0  # MPa
    nu = 0.2
    q_kpa = 5.0   # kPa

    D = E * h**3 / (12.0 * (1.0 - nu**2))
    q = q_kpa * 1.0e-3  # N/mm²
    alpha = 0.00406
    delta_expected = alpha * q * a**4 / D

    slab = SlabSpec(length_a_mm=a, width_b_mm=a,
                    thickness_h_mm=h, E_MPa=E, poisson=nu)
    load = LoadSpec(udl_kPa=q_kpa, edge_condition="simply_supported")
    report = compute_slab_deflection(slab, load)

    assert _rel_err(report.delta_max_mm, delta_expected) < TOL_1PCT, (
        f"δ={report.delta_max_mm:.4f} mm, ref={delta_expected:.4f} mm"
    )
    # Also check the honest_caveat is a non-empty string
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 50


# ---------------------------------------------------------------------------
# Test 21: Rectangular slab, dimensions reversed — same result (a = shorter)
# ---------------------------------------------------------------------------

def test_dimension_order_independent():
    """length_a_mm and width_b_mm can be swapped — result is identical."""
    slab_ab = SlabSpec(
        length_a_mm=3_000.0, width_b_mm=6_000.0,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    slab_ba = SlabSpec(
        length_a_mm=6_000.0, width_b_mm=3_000.0,
        thickness_h_mm=H_MM, E_MPa=E_MPA, poisson=NU,
    )
    load = LoadSpec(udl_kPa=Q_KPA, edge_condition="simply_supported")

    r_ab = compute_slab_deflection(slab_ab, load)
    r_ba = compute_slab_deflection(slab_ba, load)

    assert abs(r_ab.delta_max_mm - r_ba.delta_max_mm) < 1e-9
    assert abs(r_ab.plate_stiffness_D - r_ba.plate_stiffness_D) < 1e-6
