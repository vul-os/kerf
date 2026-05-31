"""
Tests for kerf_cad_core.arch.opening_in_wall
  IBC §2308.4 + ACI 318-19 §11.5.3.1 + TMS 402-22 §8.3 wall opening check.

All tests are hermetic (no OCC, no DB, no network).
All dimensions in metres, stresses in MPa, forces in kN.

Oracle reference (T01 — primary concrete window case):
  wall_height_m = 3.0 m
  wall_thickness_m = 0.200 m  (200 mm)
  opening_width_m = 1.2 m  (window)
  opening_height_m = 1.5 m
  header_above_opening_height_m = 1.0 m
  lintel_depth_m = 0.300 m
  jamb_width_m = 0.400 m
  material = "concrete"
  f_prime_or_fy_MPa = 30.0  (f'c = 30 MPa)
  applied_axial_kN_per_m = 30.0
  applied_lateral_kN_per_m2 = 1.0

  trib_w = 1.2/2 + 0.4/2 + 1.0 = 0.6 + 0.2 + 1.0 = 1.8 m
  P_gravity = 1.2 × 30.0 × 1.8 = 64.8 kN
  P_lateral = 0.5 × 1.0 × (1.2 × 1.5) = 0.5 × 1.8 = 0.9 kN
  total_P = 64.8 + 0.9 = 65.7 kN

  Jamb ACI §11.5.3.1 (k=1.0 pin-pin):
    t = 200 mm, h = 1500 mm (opening height = jamb height)
    Ag = 400 × 200 = 80 000 mm²
    k·h/(32·t) = 1.0×1500/(32×200) = 0.234375
    slend = 1 − 0.234375² = 1 − 0.054932 = 0.945068
    Pn = 0.55 × 30 × 80000 × 0.945068 N = 1 249 290 N = 1249.3 kN
    φ·Pn = 0.65 × 1249.3 = 812.0 kN
    DCR_jamb = 65.7 / 812.0 ≈ 0.0809  → well below 1.0

Coverage (12+ tests):
  T01  Concrete window: 3m wall, 1.2m wide opening, 200mm wall, fc=30MPa
       → jamb DCR < 1, lintel DCR < 1, all_adequate=True
  T02  Tributary width computed correctly for T01 geometry
  T03  Jamb load includes both gravity and lateral components
  T04  Large opening 2.4m wide → higher tributary, higher DCR than T01
  T05  Jamb DCR for 2.4m opening is greater than for 1.2m opening
  T06  Small jamb (0.1m wide) → very low capacity → jamb_dcr > 1 (inadequate)
  T07  Masonry material → TMS 402-22 §8.3 formula used, DCR < 1 for well-sized jamb
  T08  Wood-frame material → simplified bearing check, tool doesn't raise
  T09  Zero lateral load → P_lateral = 0, only gravity contributes
  T10  Zero axial load → P_gravity = 0, only lateral contributes
  T11  governing_check = "jamb_dcr_exceeded" when jamb too small
  T12  governing_check = "OK" for adequate opening
  T13  Re-export from arch/__init__.py works
  T14  honest_caveat contains key references (IBC, ACI, TMS)
  T15  ValueError: wall_height_m <= 0
  T16  ValueError: opening_width_m <= 0
  T17  ValueError: opening_height_m >= wall_height_m
  T18  ValueError: unknown material
  T19  ValueError: f_prime_or_fy_MPa <= 0
  T20  ValueError: applied_axial_kN_per_m < 0
  T21  Increasing jamb_width_m increases jamb capacity
  T22  Increasing opening_width_m increases tributary width
  T23  Masonry large opening (2.4m): higher DCR than 1.2m opening
  T24  all_adequate=False propagates to governing_check when DCR exceeded
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.arch.opening_in_wall import (
    WallOpeningSpec,
    OpeningCheckReport,
    check_opening,
)


# ---------------------------------------------------------------------------
# Helper: build a default valid concrete spec
# ---------------------------------------------------------------------------

def _concrete_spec(**overrides) -> WallOpeningSpec:
    """Return the T01 oracle spec with optional overrides."""
    defaults = dict(
        wall_height_m=3.0,
        wall_thickness_m=0.200,
        opening_width_m=1.2,
        opening_height_m=1.5,
        header_above_opening_height_m=1.0,
        lintel_depth_m=0.300,
        jamb_width_m=0.400,
        material="concrete",
        f_prime_or_fy_MPa=30.0,
        applied_axial_kN_per_m=30.0,
        applied_lateral_kN_per_m2=1.0,
    )
    defaults.update(overrides)
    return WallOpeningSpec(**defaults)


# ---------------------------------------------------------------------------
# T01 — Primary oracle: concrete window 3m wall, 1.2m opening, fc=30MPa
# ---------------------------------------------------------------------------

def test_T01_concrete_window_adequate():
    """T01: Primary oracle — jamb DCR < 1, lintel DCR < 1, all_adequate=True."""
    spec = _concrete_spec()
    report = check_opening(spec)
    assert isinstance(report, OpeningCheckReport)
    assert report.jamb_dcr < 1.0, f"jamb_dcr={report.jamb_dcr:.4f} should be < 1.0"
    assert report.lintel_moment_dcr < 1.0, (
        f"lintel_moment_dcr={report.lintel_moment_dcr:.4f} should be < 1.0"
    )
    assert report.all_adequate is True


# ---------------------------------------------------------------------------
# T02 — Tributary width
# ---------------------------------------------------------------------------

def test_T02_tributary_width():
    """T02: trib_w = opening_width/2 + jamb_width/2 + header_height = 1.8m."""
    spec = _concrete_spec(
        opening_width_m=1.2, jamb_width_m=0.4, header_above_opening_height_m=1.0
    )
    report = check_opening(spec)
    expected_trib = 1.2 / 2.0 + 0.4 / 2.0 + 1.0  # = 1.8
    # total_P includes 1.2 × axial × trib_w + lateral term
    # Re-derive gravity component: 1.2 × 30 × 1.8 = 64.8 kN
    expected_gravity = 1.2 * 30.0 * expected_trib
    expected_lateral = 0.5 * 1.0 * (1.2 * 1.5)
    expected_total = expected_gravity + expected_lateral
    assert abs(report.tributary_load_on_jamb_kN - expected_total) < 0.01, (
        f"tributary_load_on_jamb_kN={report.tributary_load_on_jamb_kN:.4f} "
        f"expected≈{expected_total:.4f}"
    )


# ---------------------------------------------------------------------------
# T03 — Jamb load includes both gravity and lateral components
# ---------------------------------------------------------------------------

def test_T03_load_includes_gravity_and_lateral():
    """T03: Load with lateral > 0 is larger than same case with lateral = 0."""
    spec_with = _concrete_spec(applied_lateral_kN_per_m2=2.0)
    spec_zero = _concrete_spec(applied_lateral_kN_per_m2=0.0)
    r_with = check_opening(spec_with)
    r_zero = check_opening(spec_zero)
    assert r_with.tributary_load_on_jamb_kN > r_zero.tributary_load_on_jamb_kN


# ---------------------------------------------------------------------------
# T04 — Large opening 2.4m wide: higher tributary than 1.2m opening
# ---------------------------------------------------------------------------

def test_T04_large_opening_higher_tributary():
    """T04: 2.4m opening → higher tributary_load_on_jamb than 1.2m opening."""
    spec_small = _concrete_spec(opening_width_m=1.2)
    spec_large = _concrete_spec(opening_width_m=2.4)
    r_small = check_opening(spec_small)
    r_large = check_opening(spec_large)
    assert r_large.tributary_load_on_jamb_kN > r_small.tributary_load_on_jamb_kN


# ---------------------------------------------------------------------------
# T05 — 2.4m wide opening: jamb DCR higher than 1.2m opening
# ---------------------------------------------------------------------------

def test_T05_large_opening_higher_dcr():
    """T05: 2.4m opening → higher jamb_dcr than 1.2m opening (same jamb size)."""
    spec_small = _concrete_spec(opening_width_m=1.2)
    spec_large = _concrete_spec(opening_width_m=2.4)
    r_small = check_opening(spec_small)
    r_large = check_opening(spec_large)
    assert r_large.jamb_dcr > r_small.jamb_dcr


# ---------------------------------------------------------------------------
# T06 — Small jamb: DCR > 1 (inadequate)
# ---------------------------------------------------------------------------

def test_T06_small_jamb_inadequate():
    """T06: Very small jamb (0.05m) with high load → jamb_dcr > 1."""
    # Very small jamb but same axial load → high demand, low capacity
    spec = _concrete_spec(
        jamb_width_m=0.05,
        applied_axial_kN_per_m=100.0,  # very high load
        opening_width_m=2.0,
    )
    report = check_opening(spec)
    assert report.jamb_dcr > 1.0, f"Expected jamb_dcr > 1, got {report.jamb_dcr:.4f}"
    assert report.all_adequate is False


# ---------------------------------------------------------------------------
# T07 — Masonry material: TMS §8.3 formula
# ---------------------------------------------------------------------------

def test_T07_masonry_material():
    """T07: masonry material → uses TMS 402-22 §8.3 formula, returns valid report."""
    spec = WallOpeningSpec(
        wall_height_m=3.0,
        wall_thickness_m=0.200,
        opening_width_m=1.2,
        opening_height_m=1.5,
        header_above_opening_height_m=0.8,
        lintel_depth_m=0.300,
        jamb_width_m=0.400,
        material="masonry",
        f_prime_or_fy_MPa=14.0,  # f'm = 14 MPa (common CMU)
        applied_axial_kN_per_m=20.0,
        applied_lateral_kN_per_m2=0.5,
    )
    report = check_opening(spec)
    assert report.jamb_dcr < 1.0, f"jamb_dcr={report.jamb_dcr:.4f} should be < 1.0"
    assert "masonry" in report.honest_caveat.lower() or "TMS" in report.honest_caveat


# ---------------------------------------------------------------------------
# T08 — Wood-frame material: runs without error
# ---------------------------------------------------------------------------

def test_T08_wood_frame_material():
    """T08: wood_frame material → returns valid report without exception."""
    spec = WallOpeningSpec(
        wall_height_m=2.7,
        wall_thickness_m=0.140,  # 2×6 stud wall ≈ 140mm
        opening_width_m=0.900,
        opening_height_m=2.1,
        header_above_opening_height_m=0.4,
        lintel_depth_m=0.235,   # doubled 2×12 header depth
        jamb_width_m=0.089,     # one stud king+trimmer pair ≈ 89mm
        material="wood_frame",
        f_prime_or_fy_MPa=9.0,  # Fc ≈ 9 MPa for SPF No.2 (NDS proxy)
        applied_axial_kN_per_m=5.0,
        applied_lateral_kN_per_m2=0.5,
    )
    report = check_opening(spec)
    assert isinstance(report, OpeningCheckReport)
    assert report.jamb_axial_capacity_kN > 0.0


# ---------------------------------------------------------------------------
# T09 — Zero lateral load
# ---------------------------------------------------------------------------

def test_T09_zero_lateral_load():
    """T09: zero lateral → P_lateral=0, tributary load is gravity-only."""
    spec = _concrete_spec(applied_lateral_kN_per_m2=0.0)
    report = check_opening(spec)
    # Gravity only: 1.2 × 30.0 × 1.8 = 64.8 kN
    expected = 1.2 * 30.0 * (1.2 / 2.0 + 0.4 / 2.0 + 1.0)
    assert abs(report.tributary_load_on_jamb_kN - expected) < 0.001


# ---------------------------------------------------------------------------
# T10 — Zero axial load
# ---------------------------------------------------------------------------

def test_T10_zero_axial_load():
    """T10: zero axial → P_gravity=0, only lateral contributes."""
    spec = _concrete_spec(applied_axial_kN_per_m=0.0, applied_lateral_kN_per_m2=1.0)
    report = check_opening(spec)
    # Only lateral: 0.5 × 1.0 × (1.2 × 1.5) = 0.9 kN
    expected_lateral = 0.5 * 1.0 * (1.2 * 1.5)
    assert abs(report.tributary_load_on_jamb_kN - expected_lateral) < 0.001


# ---------------------------------------------------------------------------
# T11 — governing_check = "jamb_dcr_exceeded" for inadequate jamb
# ---------------------------------------------------------------------------

def test_T11_governing_check_jamb_exceeded():
    """T11: tiny jamb + high load → governing_check = 'jamb_dcr_exceeded'."""
    spec = _concrete_spec(
        jamb_width_m=0.05,
        applied_axial_kN_per_m=200.0,
        opening_width_m=2.0,
    )
    report = check_opening(spec)
    assert report.governing_check == "jamb_dcr_exceeded"


# ---------------------------------------------------------------------------
# T12 — governing_check = "OK" for well-designed opening
# ---------------------------------------------------------------------------

def test_T12_governing_check_ok():
    """T12: T01 oracle geometry → governing_check = 'OK'."""
    spec = _concrete_spec()
    report = check_opening(spec)
    assert report.governing_check == "OK"


# ---------------------------------------------------------------------------
# T13 — Re-export from arch/__init__.py
# ---------------------------------------------------------------------------

def test_T13_reexport_from_arch_init():
    """T13: WallOpeningSpec, OpeningCheckReport, check_opening all re-exported."""
    from kerf_cad_core.arch import WallOpeningSpec as WOS, OpeningCheckReport as OCR, check_opening as co
    spec = WOS(
        wall_height_m=3.0,
        wall_thickness_m=0.200,
        opening_width_m=1.2,
        opening_height_m=1.5,
        header_above_opening_height_m=0.5,
        lintel_depth_m=0.250,
        jamb_width_m=0.300,
        material="concrete",
        f_prime_or_fy_MPa=25.0,
        applied_axial_kN_per_m=20.0,
        applied_lateral_kN_per_m2=0.0,
    )
    report = co(spec)
    assert isinstance(report, OCR)


# ---------------------------------------------------------------------------
# T14 — honest_caveat contains key references
# ---------------------------------------------------------------------------

def test_T14_honest_caveat_references():
    """T14: honest_caveat must mention IBC §2308.4, ACI 318-19, TMS 402-22."""
    spec = _concrete_spec()
    report = check_opening(spec)
    caveat = report.honest_caveat
    assert "IBC" in caveat, "Should mention IBC §2308.4"
    assert "ACI" in caveat, "Should mention ACI 318-19"
    assert "TMS" in caveat, "Should mention TMS 402-22"


# ---------------------------------------------------------------------------
# T15 — ValueError: wall_height_m <= 0
# ---------------------------------------------------------------------------

def test_T15_error_invalid_wall_height():
    """T15: wall_height_m <= 0 raises ValueError."""
    with pytest.raises(ValueError, match="wall_height_m"):
        check_opening(_concrete_spec(wall_height_m=0.0))


# ---------------------------------------------------------------------------
# T16 — ValueError: opening_width_m <= 0
# ---------------------------------------------------------------------------

def test_T16_error_invalid_opening_width():
    """T16: opening_width_m <= 0 raises ValueError."""
    with pytest.raises(ValueError, match="opening_width_m"):
        check_opening(_concrete_spec(opening_width_m=-0.1))


# ---------------------------------------------------------------------------
# T17 — ValueError: opening_height_m >= wall_height_m
# ---------------------------------------------------------------------------

def test_T17_error_opening_taller_than_wall():
    """T17: opening_height_m >= wall_height_m raises ValueError."""
    with pytest.raises(ValueError, match="opening_height_m"):
        check_opening(_concrete_spec(opening_height_m=3.0, wall_height_m=3.0))


# ---------------------------------------------------------------------------
# T18 — ValueError: unknown material
# ---------------------------------------------------------------------------

def test_T18_error_unknown_material():
    """T18: unknown material raises ValueError."""
    with pytest.raises(ValueError, match="material"):
        check_opening(_concrete_spec(material="steel_frame"))


# ---------------------------------------------------------------------------
# T19 — ValueError: f_prime_or_fy_MPa <= 0
# ---------------------------------------------------------------------------

def test_T19_error_invalid_strength():
    """T19: f_prime_or_fy_MPa <= 0 raises ValueError."""
    with pytest.raises(ValueError, match="f_prime_or_fy_MPa"):
        check_opening(_concrete_spec(f_prime_or_fy_MPa=0.0))


# ---------------------------------------------------------------------------
# T20 — ValueError: applied_axial_kN_per_m < 0
# ---------------------------------------------------------------------------

def test_T20_error_negative_axial():
    """T20: applied_axial_kN_per_m < 0 raises ValueError."""
    with pytest.raises(ValueError, match="applied_axial_kN_per_m"):
        check_opening(_concrete_spec(applied_axial_kN_per_m=-1.0))


# ---------------------------------------------------------------------------
# T21 — Increasing jamb_width increases jamb capacity monotonically
# ---------------------------------------------------------------------------

def test_T21_wider_jamb_higher_capacity():
    """T21: wider jamb_width_m → higher jamb_axial_capacity_kN."""
    caps = []
    for w in [0.2, 0.4, 0.6, 0.8]:
        spec = _concrete_spec(jamb_width_m=w)
        report = check_opening(spec)
        caps.append(report.jamb_axial_capacity_kN)
    # Capacities should be strictly increasing
    for i in range(len(caps) - 1):
        assert caps[i] < caps[i + 1], (
            f"capacity[{i}]={caps[i]:.3f} should be < capacity[{i+1}]={caps[i+1]:.3f}"
        )


# ---------------------------------------------------------------------------
# T22 — Increasing opening_width increases tributary width
# ---------------------------------------------------------------------------

def test_T22_wider_opening_higher_tributary():
    """T22: wider opening_width_m → higher tributary_load_on_jamb_kN."""
    loads = []
    for w in [0.6, 1.0, 1.5, 2.0, 2.4]:
        spec = _concrete_spec(opening_width_m=w)
        report = check_opening(spec)
        loads.append(report.tributary_load_on_jamb_kN)
    for i in range(len(loads) - 1):
        assert loads[i] < loads[i + 1], (
            f"load[{i}]={loads[i]:.3f} should be < load[{i+1}]={loads[i+1]:.3f}"
        )


# ---------------------------------------------------------------------------
# T23 — Masonry large opening: higher DCR than 1.2m
# ---------------------------------------------------------------------------

def test_T23_masonry_large_opening_higher_dcr():
    """T23: masonry wall, 2.4m opening → higher jamb_dcr than 1.2m opening."""
    def masonry_spec(w):
        return WallOpeningSpec(
            wall_height_m=3.0,
            wall_thickness_m=0.200,
            opening_width_m=w,
            opening_height_m=1.5,
            header_above_opening_height_m=0.8,
            lintel_depth_m=0.300,
            jamb_width_m=0.400,
            material="masonry",
            f_prime_or_fy_MPa=14.0,
            applied_axial_kN_per_m=25.0,
            applied_lateral_kN_per_m2=1.0,
        )
    r_small = check_opening(masonry_spec(1.2))
    r_large = check_opening(masonry_spec(2.4))
    assert r_large.jamb_dcr > r_small.jamb_dcr


# ---------------------------------------------------------------------------
# T24 — all_adequate=False propagates to governing_check
# ---------------------------------------------------------------------------

def test_T24_all_adequate_false_when_dcr_exceeded():
    """T24: when jamb_dcr > 1, all_adequate is False and governing_check is set."""
    spec = _concrete_spec(
        jamb_width_m=0.05,
        applied_axial_kN_per_m=200.0,
    )
    report = check_opening(spec)
    assert report.all_adequate is False
    assert report.governing_check != "OK"


# ---------------------------------------------------------------------------
# T25 — Oracle jamb capacity numeric check (T01 concrete window)
# ---------------------------------------------------------------------------

def test_T25_oracle_jamb_capacity_numeric():
    """T25: T01 oracle jamb capacity ≈ 812 kN (ACI §11.5.3.1)."""
    # Jamb: t=200mm, h=1500mm, Ag=400×200=80000mm², k=1.0, fc=30MPa
    # slend = 1 − (1.0×1500/(32×200))² = 1 − 0.234375² = 1 − 0.054932 = 0.945068
    # Pn = 0.55×30×80000×0.945068 N = 1249290 N = 1249.3 kN
    # φPn = 0.65×1249.3 = 812.0 kN
    spec = _concrete_spec()
    report = check_opening(spec)
    expected_cap = 0.65 * 0.55 * 30.0 * (400 * 200) * (1 - (1.0 * 1500 / (32 * 200)) ** 2) / 1000.0
    assert abs(report.jamb_axial_capacity_kN - expected_cap) < 1.0, (
        f"jamb_axial_capacity_kN={report.jamb_axial_capacity_kN:.3f} "
        f"expected≈{expected_cap:.3f}"
    )
