"""
Tests for kerf_cad_core.piping.component_catalogue — AVEVA E3D parity Wave 12B.

Covers:
- ASME B16.5 flange catalogue: size × class coverage (≥ 40 entries)
- ASME B16.9 buttweld fittings: elbows, tees, reducers, caps, crosses
- API 6D valve catalogue
- PipeCatalogue.filter(), .by_type(), .by_size()
- compute_pipe_run_bom() for realistic pipe runs

References: ASME B16.5-2020, ASME B16.9-2018, API Spec 6D-2014.
"""
from __future__ import annotations

import pytest
import math

from kerf_cad_core.piping.component_catalogue import (
    PipeComponent,
    PipeCatalogue,
    asme_b16_5_flange_catalog,
    asme_b16_9_buttweld_fitting_catalog,
    api_6d_valve_catalog,
    compute_pipe_run_bom,
)


# ---------------------------------------------------------------------------
# ASME B16.5 flange catalogue
# ---------------------------------------------------------------------------

def test_asme_b16_5_flange_count_at_least_40():
    """ASME B16.5-2020: 16 NPS × 6 pressure classes = 96 flanges; min 40 required."""
    cat = asme_b16_5_flange_catalog()
    assert len(cat.components) >= 40, f"Expected ≥40 B16.5 flanges, got {len(cat)}"


def test_asme_b16_5_flange_count_exact():
    """Verify we have all 16 sizes × 6 classes = 96 entries."""
    cat = asme_b16_5_flange_catalog()
    assert len(cat.components) == 96


def test_asme_b16_5_flange_types_all_flange():
    """Every B16.5 entry should have component_type == 'flange'."""
    cat = asme_b16_5_flange_catalog()
    for c in cat.components:
        assert c.component_type == "flange"
        assert c.catalog_standard == "ASME B16.5"


def test_asme_b16_5_flange_pressure_classes():
    """All six ASME B16.5 pressure classes must be represented."""
    cat = asme_b16_5_flange_catalog()
    classes = {c.pressure_class_psi for c in cat.components}
    assert classes == {150, 300, 600, 900, 1500, 2500}


def test_asme_b16_5_flange_sizes_covered():
    """Verify standard NPS sizes 0.5 through 24 are all present."""
    expected_nps = {0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0,
                    6.0, 8.0, 10.0, 12.0, 16.0, 20.0, 24.0}
    cat = asme_b16_5_flange_catalog()
    actual_nps = {c.nominal_size_in for c in cat.components}
    assert expected_nps == actual_nps


def test_asme_b16_5_4inch_150lb_weight_reasonable():
    """4\" Class 150 weld-neck flange: expect ~4–5 kg (ASME B16.5-2020 Table 1)."""
    cat = asme_b16_5_flange_catalog()
    matches = [c for c in cat.components
               if abs(c.nominal_size_in - 4.0) < 1e-6 and c.pressure_class_psi == 150]
    assert len(matches) == 1
    wt = matches[0].weight_kg
    assert 3.0 < wt < 6.0, f"4\" 150# flange weight={wt} kg outside expected 3–6 kg range"


def test_asme_b16_5_heavier_with_higher_class():
    """Higher pressure class flanges must weigh more for the same NPS."""
    cat = asme_b16_5_flange_catalog()
    for nps in (4.0, 8.0, 12.0):
        by_nps = {c.pressure_class_psi: c.weight_kg
                  for c in cat.components if abs(c.nominal_size_in - nps) < 1e-6}
        assert by_nps[150] < by_nps[300] < by_nps[600] < by_nps[1500]


def test_asme_b16_5_cost_positive():
    """All flange costs must be strictly positive."""
    cat = asme_b16_5_flange_catalog()
    for c in cat.components:
        assert c.cost_usd > 0.0, f"{c.component_id} has cost={c.cost_usd}"


# ---------------------------------------------------------------------------
# ASME B16.9 butt-weld fitting catalogue
# ---------------------------------------------------------------------------

def test_asme_b16_9_catalog_non_empty():
    cat = asme_b16_9_buttweld_fitting_catalog()
    assert len(cat.components) >= 10


def test_asme_b16_9_has_elbows():
    cat = asme_b16_9_buttweld_fitting_catalog()
    elbows = cat.by_type("elbow")
    assert len(elbows) >= 4, "Expected at least 4 elbow entries"


def test_asme_b16_9_has_tees():
    cat = asme_b16_9_buttweld_fitting_catalog()
    tees = cat.by_type("tee")
    assert len(tees) >= 3


def test_asme_b16_9_has_reducers():
    cat = asme_b16_9_buttweld_fitting_catalog()
    reducers = cat.by_type("reducer")
    assert len(reducers) >= 3


def test_asme_b16_9_catalog_standard():
    cat = asme_b16_9_buttweld_fitting_catalog()
    for c in cat.components:
        assert c.catalog_standard == "ASME B16.9"


# ---------------------------------------------------------------------------
# API 6D valve catalogue
# ---------------------------------------------------------------------------

def test_api_6d_valve_catalog_non_empty():
    cat = api_6d_valve_catalog()
    assert len(cat.components) >= 10


def test_api_6d_all_valves():
    cat = api_6d_valve_catalog()
    for c in cat.components:
        assert c.component_type == "valve"
        assert c.catalog_standard == "API 6D"


# ---------------------------------------------------------------------------
# PipeCatalogue.filter() and helpers
# ---------------------------------------------------------------------------

def test_filter_elbow_4inch_returns_multiple():
    """filter(component_type='elbow', nominal_size_in=4.0) must return ≥2 options."""
    cat = asme_b16_9_buttweld_fitting_catalog()
    results = cat.filter(component_type="elbow", nominal_size_in=4.0)
    assert len(results) >= 2, f"Expected ≥2 4\" elbows, got {len(results)}: {[c.description for c in results]}"


def test_filter_case_insensitive():
    cat = asme_b16_9_buttweld_fitting_catalog()
    r1 = cat.filter(component_type="Elbow")
    r2 = cat.filter(component_type="elbow")
    assert len(r1) == len(r2)


def test_by_type_flanges():
    cat = asme_b16_5_flange_catalog()
    flanges = cat.by_type("flange")
    assert len(flanges) == len(cat.components)


def test_by_size_6inch():
    cat = asme_b16_5_flange_catalog()
    six_inch = cat.by_size(6.0)
    assert len(six_inch) == 6  # 6 pressure classes


def test_filter_class_300():
    cat = asme_b16_5_flange_catalog()
    c300 = cat.filter(component_type="flange", pressure_class_psi=300)
    assert len(c300) == 16  # 16 NPS sizes each with class 300


# ---------------------------------------------------------------------------
# compute_pipe_run_bom
# ---------------------------------------------------------------------------

def test_bom_100m_4inch_sch40_4_elbows_positive():
    """100 m of 4\" SCH40 + 4 elbows → positive weight and cost."""
    b16_9 = asme_b16_9_buttweld_fitting_catalog()
    b16_5 = asme_b16_5_flange_catalog()
    combined = PipeCatalogue(components=b16_9.components + b16_5.components)

    segments = [{
        "from": "T-100",
        "to": "T-200",
        "size_in": 4.0,
        "schedule": "SCH40",
        "length_m": 100.0,
        "material": "A106-B",
        "n_elbows": 4,
        "n_flanges": 2,
    }]
    result = compute_pipe_run_bom(segments, combined)
    assert result["ok"] is True
    assert result["total_weight_kg"] > 0.0, "BOM weight should be positive"
    assert result["total_cost_usd"] > 0.0, "BOM cost should be positive"


def test_bom_pipe_weight_realistic():
    """4\" SCH40 100m pipe weight validation.

    OD = 114.30 mm, t = 6.02 mm (ASME B36.10M), rho = 7850 kg/m³.
    Cross-section area A = π·(r_out² - r_in²) in m².
    Expected weight = A × 100 m × 7850 kg/m³ ≈ 1600 kg for 100 m of 4\" SCH40.
    """
    od_m = 0.11430
    t_m = 0.00602
    r_out = od_m / 2
    r_in = r_out - t_m
    area = math.pi * (r_out**2 - r_in**2)  # m²
    expected_wt = area * 100.0 * 7850.0    # kg
    # 4" SCH40 100m: cross-section area ~0.00205 m² → weight ~1600 kg
    assert 1400.0 < expected_wt < 1800.0

    segments = [{
        "from": "A", "to": "B",
        "size_in": 4.0, "schedule": "SCH40",
        "length_m": 100.0, "material": "A106",
        "n_elbows": 0, "n_flanges": 0,
    }]
    result = compute_pipe_run_bom(segments, PipeCatalogue())
    assert result["ok"] is True
    wt = result["total_weight_kg"]
    assert 1400.0 < wt < 1800.0, f"Expected ~1400–1800 kg for 100m 4\" SCH40, got {wt}"


def test_bom_line_items_non_empty():
    combined = PipeCatalogue(
        components=asme_b16_9_buttweld_fitting_catalog().components
                   + asme_b16_5_flange_catalog().components
    )
    segments = [{"from": "A", "to": "B",
                 "size_in": 4.0, "schedule": "SCH40",
                 "length_m": 50.0, "n_elbows": 2, "n_flanges": 2}]
    result = compute_pipe_run_bom(segments, combined)
    assert len(result["line_items"]) >= 1


def test_bom_multiple_segments():
    combined = PipeCatalogue(
        components=asme_b16_9_buttweld_fitting_catalog().components
    )
    segments = [
        {"from": "A", "to": "B", "size_in": 4.0, "schedule": "SCH40",
         "length_m": 40.0, "n_elbows": 2, "n_flanges": 0},
        {"from": "B", "to": "C", "size_in": 4.0, "schedule": "SCH40",
         "length_m": 60.0, "n_elbows": 2, "n_flanges": 0},
    ]
    result = compute_pipe_run_bom(segments, combined)
    assert result["ok"] is True
    # Should be roughly same as single 100m run
    single = compute_pipe_run_bom(
        [{"from": "A", "to": "C", "size_in": 4.0, "schedule": "SCH40",
          "length_m": 100.0, "n_elbows": 4, "n_flanges": 0}],
        combined
    )
    assert abs(result["total_weight_kg"] - single["total_weight_kg"]) < 1.0
