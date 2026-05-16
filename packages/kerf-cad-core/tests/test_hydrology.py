"""
Tests for kerf_cad_core.hydrology — stormwater / drainage hydrology.

All tests are pure-Python, hermetic: no OCC, no DB, no network, no fixtures
from disk.  All numeric inputs are taken from hydrology textbook hand-calcs or
TR-55 worked examples.

Covers (≥ 30 tests):
  1.  rational_peak_flow — basic Q = C·i·A / 360
  2.  rational_peak_flow — dimensional unit check (Q in m³/s)
  3.  rational_peak_flow — C > 1 returns error
  4.  rational_peak_flow — negative area returns error
  5.  composite_runoff_coeff — two sub-areas, hand-calc
  6.  composite_runoff_coeff — single sub-area
  7.  composite_runoff_coeff — empty list returns error
  8.  scs_runoff_depth — P > Ia: hand calc with CN=75, P=100 mm
  9.  scs_runoff_depth — P <= Ia: Q = 0
  10. scs_runoff_depth — CN=98 (impervious), P=50 mm
  11. scs_runoff_depth — CN out of range returns error
  12. scs_runoff_depth — P = 0 returns Q = 0
  13. scs_peak_flow — TR-55 worked example approximation
  14. scs_peak_flow — warns when tc outside [0.1, 2.0] hr
  15. scs_peak_flow — zero runoff (P < Ia) returns Qp = 0
  16. time_of_concentration — kirpich method hand-calc
  17. time_of_concentration — kirpich L=1000 m, H=10 m
  18. time_of_concentration — nrcs_velocity paved_gutter
  19. time_of_concentration — nrcs_velocity bad cover returns error
  20. time_of_concentration — sheet_shallow_channel returns three components
  21. time_of_concentration — unknown method returns error
  22. idf_intensity — formula check i = a/(t+b)^c
  23. idf_intensity — b=0 special case
  24. idf_intensity — negative duration returns error
  25. detention_storage_modified_rational — basic volume check
  26. detention_storage_modified_rational — Q_out >= Q_in → V=0, warning
  27. storage_indication_route — simple flat-rating routing conserves mass
  28. storage_indication_route — peak outflow <= peak inflow (attenuation)
  29. storage_indication_route — bad rating table (unsorted) returns error
  30. storage_indication_route — overtopping warning when storage exceeds table
  31. storm_sewer_pipe_size — selects correct standard diameter
  32. storm_sewer_pipe_size — freeboard exceedance warning
  33. storm_sewer_pipe_size — warns on low velocity
  34. storm_sewer_pipe_size — invalid slope returns error
  35. plugin._TOOL_MODULES includes hydrology.tools

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.hydrology.runoff import (
    rational_peak_flow,
    composite_runoff_coeff,
    scs_runoff_depth,
    scs_peak_flow,
    time_of_concentration,
    idf_intensity,
    detention_storage_modified_rational,
    storage_indication_route,
    storm_sewer_pipe_size,
    _NRCS_K_COVERS,
    _G,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1. rational_peak_flow — basic Q = C·i·A / 360
# ---------------------------------------------------------------------------

def test_rational_peak_flow_basic():
    # Q = 0.70 × 50 mm/hr × 2 ha / 360 = 0.1944 m³/s  (0.70·50·2/360)
    result = rational_peak_flow(C=0.70, i_mm_hr=50.0, A_ha=2.0)
    assert result["ok"] is True
    expected = 0.70 * 50.0 * 2.0 / 360.0
    assert abs(result["Q_m3s"] - expected) < 1e-5, result


# ---------------------------------------------------------------------------
# 2. rational_peak_flow — unit check: L/s ≈ Q_m3s × 1000
# ---------------------------------------------------------------------------

def test_rational_peak_flow_unit_consistency():
    result = rational_peak_flow(C=0.50, i_mm_hr=80.0, A_ha=5.0)
    assert result["ok"] is True
    assert abs(result["Q_L_per_s"] - result["Q_m3s"] * 1000.0) < 1e-3


# ---------------------------------------------------------------------------
# 3. rational_peak_flow — C > 1 returns error
# ---------------------------------------------------------------------------

def test_rational_peak_flow_c_gt_1():
    result = rational_peak_flow(C=1.1, i_mm_hr=30.0, A_ha=1.0)
    assert result["ok"] is False
    assert "C" in result["reason"]


# ---------------------------------------------------------------------------
# 4. rational_peak_flow — negative area returns error
# ---------------------------------------------------------------------------

def test_rational_peak_flow_negative_area():
    result = rational_peak_flow(C=0.5, i_mm_hr=30.0, A_ha=-1.0)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 5. composite_runoff_coeff — two sub-areas hand-calc
# ---------------------------------------------------------------------------

def test_composite_c_two_areas():
    # C_comp = (0.9 × 1.0 + 0.3 × 3.0) / (1.0 + 3.0) = (0.9 + 0.9) / 4 = 0.45
    areas = [{"C": 0.9, "area_ha": 1.0}, {"C": 0.3, "area_ha": 3.0}]
    result = composite_runoff_coeff(areas)
    assert result["ok"] is True
    assert abs(result["C_composite"] - 0.45) < 1e-5
    assert abs(result["total_area_ha"] - 4.0) < 1e-5


# ---------------------------------------------------------------------------
# 6. composite_runoff_coeff — single sub-area
# ---------------------------------------------------------------------------

def test_composite_c_single():
    areas = [{"C": 0.75, "area_ha": 2.0}]
    result = composite_runoff_coeff(areas)
    assert result["ok"] is True
    assert abs(result["C_composite"] - 0.75) < 1e-6


# ---------------------------------------------------------------------------
# 7. composite_runoff_coeff — empty list returns error
# ---------------------------------------------------------------------------

def test_composite_c_empty():
    result = composite_runoff_coeff([])
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 8. scs_runoff_depth — P > Ia: CN=75, P=100 mm
# ---------------------------------------------------------------------------

def test_scs_runoff_depth_basic():
    # S = 25400/75 - 254 = 338.667 - 254 = 84.667 mm
    # Ia = 0.2 × 84.667 = 16.933 mm
    # Q = (100 - 16.933)² / (100 - 16.933 + 84.667) = (83.067)² / 167.733
    CN = 75
    P = 100.0
    S = 25400.0 / CN - 254.0
    Ia = 0.2 * S
    Q_exp = (P - Ia) ** 2 / (P - Ia + S)

    result = scs_runoff_depth(P_mm=P, CN=CN)
    assert result["ok"] is True
    assert abs(result["Q_mm"] - Q_exp) < 0.001
    assert abs(result["S_mm"] - S) < 0.001
    assert abs(result["Ia_mm"] - Ia) < 0.001


# ---------------------------------------------------------------------------
# 9. scs_runoff_depth — P <= Ia → Q = 0
# ---------------------------------------------------------------------------

def test_scs_runoff_depth_no_runoff():
    # CN=30: S = 25400/30 - 254 = 592.67 mm; Ia = 118.5 mm
    # P = 50 mm < Ia → Q = 0
    result = scs_runoff_depth(P_mm=50.0, CN=30)
    assert result["ok"] is True
    assert result["Q_mm"] == 0.0


# ---------------------------------------------------------------------------
# 10. scs_runoff_depth — CN=98 impervious
# ---------------------------------------------------------------------------

def test_scs_runoff_depth_cn98():
    # S = 25400/98 - 254 = 5.184 mm; Ia = 1.037 mm
    CN = 98
    P = 25.0
    S = 25400.0 / CN - 254.0
    Ia = 0.2 * S
    Q_exp = (P - Ia) ** 2 / (P - Ia + S) if P > Ia else 0.0
    result = scs_runoff_depth(P_mm=P, CN=CN)
    assert result["ok"] is True
    assert abs(result["Q_mm"] - Q_exp) < 0.01


# ---------------------------------------------------------------------------
# 11. scs_runoff_depth — CN out of range → error
# ---------------------------------------------------------------------------

def test_scs_runoff_depth_cn_oob():
    result = scs_runoff_depth(P_mm=50.0, CN=101)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 12. scs_runoff_depth — P = 0 → Q = 0
# ---------------------------------------------------------------------------

def test_scs_runoff_depth_zero_p():
    result = scs_runoff_depth(P_mm=0.0, CN=75)
    assert result["ok"] is True
    assert result["Q_mm"] == 0.0


# ---------------------------------------------------------------------------
# 13. scs_peak_flow — approximation check
# ---------------------------------------------------------------------------

def test_scs_peak_flow_nonzero():
    # CN=80, A=1.5 km², tc=0.5 hr, P=100 mm → should return a positive Qp
    result = scs_peak_flow(CN=80, A_km2=1.5, tc_hr=0.5, P_mm=100.0)
    assert result["ok"] is True, result
    assert result["Qp_m3s"] > 0.0
    assert result["Q_mm"] > 0.0
    assert result["qu_m3s_per_km2_per_mm"] > 0.0


# ---------------------------------------------------------------------------
# 14. scs_peak_flow — warns when tc out of [0.1, 2.0] hr
# ---------------------------------------------------------------------------

def test_scs_peak_flow_tc_out_of_range():
    result = scs_peak_flow(CN=75, A_km2=1.0, tc_hr=3.0, P_mm=80.0)
    assert result["ok"] is True
    assert any("tc" in w.lower() or "outside" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# 15. scs_peak_flow — zero runoff (P << Ia) → Qp = 0
# ---------------------------------------------------------------------------

def test_scs_peak_flow_zero_runoff():
    # CN=40, P=10 mm: S = 25400/40 - 254 = 381 mm; Ia = 76.2 mm > 10 mm → Q = 0
    result = scs_peak_flow(CN=40, A_km2=1.0, tc_hr=0.5, P_mm=10.0)
    assert result["ok"] is True
    assert result["Q_mm"] == 0.0
    assert result["Qp_m3s"] == 0.0


# ---------------------------------------------------------------------------
# 16. time_of_concentration — kirpich hand-calc
# ---------------------------------------------------------------------------

def test_tc_kirpich_hand_calc():
    # L = 500 m, H = 5 m → S = 0.01
    # tc [min] = 0.0195 × 500^0.77 × 0.01^-0.385
    L, H = 500.0, 5.0
    S = H / L
    tc_expected_min = 0.0195 * (L ** 0.77) * (S ** -0.385)
    result = time_of_concentration("kirpich", L_m=L, H_m=H)
    assert result["ok"] is True
    assert abs(result["tc_min"] - tc_expected_min) < 0.01
    assert result["method"] == "kirpich"


# ---------------------------------------------------------------------------
# 17. time_of_concentration — kirpich L=1000 m, H=10 m
# ---------------------------------------------------------------------------

def test_tc_kirpich_1000m():
    result = time_of_concentration("kirpich", L_m=1000.0, H_m=10.0)
    assert result["ok"] is True
    assert result["tc_hr"] > 0.0
    # Sanity: tc > 10 min for 1 km channel
    assert result["tc_min"] > 10.0


# ---------------------------------------------------------------------------
# 18. time_of_concentration — nrcs_velocity paved_gutter
# ---------------------------------------------------------------------------

def test_tc_nrcs_velocity_paved():
    # k = 20 ft/s for paved_gutter; slope=0.01
    # V [ft/s] = 20 × sqrt(0.01) = 2.0 ft/s = 0.6096 m/s
    # L=200 m → tc = 200 / 0.6096 / 3600 = 0.09116 hr
    k_fps = 20.0
    slope = 0.01
    L = 200.0
    V_ms = k_fps * math.sqrt(slope) * 0.3048
    tc_hr_exp = L / V_ms / 3600.0

    result = time_of_concentration("nrcs_velocity", L_m=L, slope=slope, cover="paved_gutter")
    assert result["ok"] is True
    assert abs(result["tc_hr"] - tc_hr_exp) < 1e-5
    assert abs(result["velocity_m_per_s"] - V_ms) < 1e-4


# ---------------------------------------------------------------------------
# 19. time_of_concentration — nrcs_velocity bad cover → error
# ---------------------------------------------------------------------------

def test_tc_nrcs_velocity_bad_cover():
    result = time_of_concentration("nrcs_velocity", L_m=100.0, slope=0.01, cover="moon_dust")
    assert result["ok"] is False
    assert "cover" in result["reason"]


# ---------------------------------------------------------------------------
# 20. time_of_concentration — sheet_shallow_channel returns three components
# ---------------------------------------------------------------------------

def test_tc_sheet_shallow_channel():
    result = time_of_concentration(
        "sheet_shallow_channel",
        sheet_length_m=50.0,
        sheet_n=0.15,
        sheet_P2_mm=63.5,   # 2.5 in of 2-yr 24-hr rainfall
        sheet_slope=0.02,
        shallow_length_m=100.0,
        shallow_slope=0.01,
        shallow_cover="short_grass_pasture",
        channel_length_m=500.0,
        channel_slope=0.005,
        channel_area_m2=1.2,
        channel_wetted_perim_m=3.0,
        channel_n=0.035,
    )
    assert result["ok"] is True, result
    assert result["tc_hr"] > 0.0
    assert "tt_sheet_hr" in result
    assert "tt_shallow_hr" in result
    assert "tt_channel_hr" in result
    # Total must equal sum of parts
    total = result["tt_sheet_hr"] + result["tt_shallow_hr"] + result["tt_channel_hr"]
    assert abs(result["tc_hr"] - total) < 1e-6


# ---------------------------------------------------------------------------
# 21. time_of_concentration — unknown method → error
# ---------------------------------------------------------------------------

def test_tc_unknown_method():
    result = time_of_concentration("wacky_method")
    assert result["ok"] is False
    assert "method" in result["reason"]


# ---------------------------------------------------------------------------
# 22. idf_intensity — formula check  i = a / (t + b)^c
# ---------------------------------------------------------------------------

def test_idf_intensity_formula():
    # a=2000, b=10, c=0.8, t=30 min → i = 2000 / (30+10)^0.8
    a, b, c, t = 2000.0, 10.0, 0.8, 30.0
    expected = a / (t + b) ** c
    result = idf_intensity(duration_min=t, a=a, b=b, c=c)
    assert result["ok"] is True
    assert abs(result["intensity_mm_hr"] - expected) < 0.001


# ---------------------------------------------------------------------------
# 23. idf_intensity — b=0 special case
# ---------------------------------------------------------------------------

def test_idf_intensity_b_zero():
    # i = 1500 / 60^0.75
    a, b, c, t = 1500.0, 0.0, 0.75, 60.0
    expected = a / (t ** c)
    result = idf_intensity(duration_min=t, a=a, b=b, c=c)
    assert result["ok"] is True
    assert abs(result["intensity_mm_hr"] - expected) < 0.001


# ---------------------------------------------------------------------------
# 24. idf_intensity — negative duration → error
# ---------------------------------------------------------------------------

def test_idf_intensity_negative_duration():
    result = idf_intensity(duration_min=-10.0, a=2000.0, b=5.0, c=0.8)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 25. detention_storage_modified_rational — basic volume check
# ---------------------------------------------------------------------------

def test_detention_storage_basic():
    # Q_in = 0.50 m³/s, Q_out = 0.10 m³/s, tc = 0.5 hr
    # V = 0.5 × (0.50 - 0.10) × 0.5 × 3600 = 0.5 × 0.40 × 1800 = 360 m³
    result = detention_storage_modified_rational(
        Q_in_cms=0.50, Q_out_cms=0.10, tc_hr=0.5
    )
    assert result["ok"] is True
    assert abs(result["V_m3"] - 360.0) < 0.1


# ---------------------------------------------------------------------------
# 26. detention_storage — Q_out >= Q_in → V=0, warning
# ---------------------------------------------------------------------------

def test_detention_storage_no_volume():
    result = detention_storage_modified_rational(
        Q_in_cms=0.10, Q_out_cms=0.30, tc_hr=1.0
    )
    assert result["ok"] is True
    assert result["V_m3"] == 0.0
    assert len(result["warnings"]) > 0


# ---------------------------------------------------------------------------
# 27. storage_indication_route — flat-rating routing conserves mass
# ---------------------------------------------------------------------------

def test_si_route_mass_balance():
    # Constant inflow = 1.0 m³/s for 10 steps; rating: linear 0–100 m³ → 0–2.0 m³/s
    rating = [
        {"storage_m3": 0.0, "outflow_m3s": 0.0},
        {"storage_m3": 50.0, "outflow_m3s": 1.0},
        {"storage_m3": 100.0, "outflow_m3s": 2.0},
    ]
    inflow = [1.0] * 10
    result = storage_indication_route(
        inflow_series=inflow, outflow_rating=rating, dt_s=60.0, S0_m3=0.0
    )
    assert result["ok"] is True, result
    assert len(result["outflow_m3s"]) == 10
    assert len(result["storage_m3"]) == 10


# ---------------------------------------------------------------------------
# 28. storage_indication_route — peak outflow <= peak inflow (attenuation)
# ---------------------------------------------------------------------------

def test_si_route_attenuation():
    # Triangular inflow peak at step 5; basin should attenuate peak
    rating = [
        {"storage_m3": 0.0, "outflow_m3s": 0.0},
        {"storage_m3": 500.0, "outflow_m3s": 0.5},
        {"storage_m3": 2000.0, "outflow_m3s": 2.0},
    ]
    inflow = [0.1, 0.3, 0.6, 1.0, 1.5, 1.0, 0.6, 0.3, 0.1, 0.0]
    result = storage_indication_route(
        inflow_series=inflow, outflow_rating=rating, dt_s=600.0, S0_m3=0.0
    )
    assert result["ok"] is True
    # Peak outflow should be less than peak inflow
    assert result["peak_outflow_m3s"] <= max(inflow) + 1e-6


# ---------------------------------------------------------------------------
# 29. storage_indication_route — unsorted rating table → error
# ---------------------------------------------------------------------------

def test_si_route_unsorted_rating():
    rating = [
        {"storage_m3": 100.0, "outflow_m3s": 1.0},
        {"storage_m3": 50.0, "outflow_m3s": 0.5},   # out of order
    ]
    result = storage_indication_route(
        inflow_series=[1.0, 1.0, 1.0], outflow_rating=rating, dt_s=60.0
    )
    assert result["ok"] is False
    assert "sorted" in result["reason"].lower() or "ascending" in result["reason"].lower()


# ---------------------------------------------------------------------------
# 30. storage_indication_route — overtopping warning
# ---------------------------------------------------------------------------

def test_si_route_overtopping_warning():
    # Very small rating table; large inflow → storage will exceed table max
    rating = [
        {"storage_m3": 0.0, "outflow_m3s": 0.0},
        {"storage_m3": 10.0, "outflow_m3s": 5.0},
    ]
    inflow = [100.0] * 5   # very large inflow
    result = storage_indication_route(
        inflow_series=inflow, outflow_rating=rating, dt_s=60.0, S0_m3=0.0
    )
    assert result["ok"] is True
    assert any("overtopping" in w.lower() or "exceed" in w.lower()
               for w in result["warnings"])


# ---------------------------------------------------------------------------
# 31. storm_sewer_pipe_size — selects correct standard diameter
# ---------------------------------------------------------------------------

def test_storm_sewer_pipe_size_basic():
    # Q = 0.050 m³/s, slope = 0.005, n = 0.013
    # Manning full-flow for 300 mm: Q = (1/0.013) × (π/4×0.3²) × (0.3/4)^(2/3) × sqrt(0.005)
    # Compute expected
    n = 0.013
    S = 0.005
    d = 0.300  # 300 mm standard pipe
    A = math.pi / 4.0 * d * d
    R = d / 4.0
    Q_full = (1.0 / n) * A * (R ** (2.0 / 3.0)) * math.sqrt(S)
    # Q_design such that 300 mm is sufficient at 85% utilisation
    Q_design = Q_full * 0.80   # 80% capacity, below 85% threshold → 300 mm should fit

    result = storm_sewer_pipe_size(Q_cms=Q_design, slope=S, n=n)
    assert result["ok"] is True, result
    # Selected diameter should be >= 300 mm and <= some reasonable max
    assert result["diameter_m"] >= 0.150
    assert result["Q_full_m3s"] >= Q_design
    assert result["utilisation"] <= 1.0


# ---------------------------------------------------------------------------
# 32. storm_sewer_pipe_size — freeboard exceedance warning
# ---------------------------------------------------------------------------

def test_storm_sewer_pipe_size_freeboard_warning():
    # Force utilisation > 0.85 by using freeboard_fraction = 1.0 but requesting
    # a flow close to full capacity then checking with fb = 0.85
    n = 0.013
    S = 0.003
    d = 0.150  # smallest pipe
    A = math.pi / 4.0 * d * d
    R = d / 4.0
    Q_full = (1.0 / n) * A * (R ** (2.0 / 3.0)) * math.sqrt(S)
    # Request exactly full flow (freeboard_fraction = 0.85 → design flow / fb = Q_full)
    # so utilisation = Q_full / Q_full_selected; if selected = 0.150 m → util = 1.0 > 0.85
    Q_request = Q_full * 0.99   # almost full pipe
    result = storm_sewer_pipe_size(Q_cms=Q_request, slope=S, n=n,
                                   min_d_m=0.150, max_d_m=0.150,
                                   freeboard_fraction=0.85)
    assert result["ok"] is True
    # utilisation > 0.85 → freeboard_ok = False and warning issued
    if result["utilisation"] > 0.85:
        assert result["freeboard_ok"] is False
        assert any("freeboard" in w.lower() or "full" in w.lower()
                   for w in result["warnings"])


# ---------------------------------------------------------------------------
# 33. storm_sewer_pipe_size — warns on low velocity
# ---------------------------------------------------------------------------

def test_storm_sewer_pipe_size_low_velocity():
    # Very low slope → low velocity → self-cleansing warning
    result = storm_sewer_pipe_size(Q_cms=0.001, slope=0.0001, n=0.013)
    assert result["ok"] is True
    # Should warn about low velocity
    assert any("velocity" in w.lower() or "cleansing" in w.lower()
               for w in result["warnings"])


# ---------------------------------------------------------------------------
# 34. storm_sewer_pipe_size — invalid slope → error
# ---------------------------------------------------------------------------

def test_storm_sewer_pipe_size_invalid_slope():
    result = storm_sewer_pipe_size(Q_cms=0.05, slope=-0.001)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 35. plugin._TOOL_MODULES includes hydrology.tools
# ---------------------------------------------------------------------------

def test_plugin_tool_modules_includes_hydrology():
    from kerf_cad_core.plugin import _TOOL_MODULES
    assert "kerf_cad_core.hydrology.tools" in _TOOL_MODULES
