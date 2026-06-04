"""
Tests for kerf_cad_core.packaging.material_yield — sheet yield + material cost.

Covers:
  - A4 sheet (210×297 mm) with 100×100 mm outline at 75 % efficiency → ~4 parts/sheet
  - cost scales linearly with job_quantity
  - waste_pct = 100 - nesting_efficiency_pct
  - sheets_per_job is ceiling of job_quantity / parts_per_sheet
  - material_used_kg is sheets_per_job × sheet_weight_kg
  - estimate_cycles_per_minute formula
  - material_cost_per_part = total_cost / quantity
  - invalid inputs raise ValueError
  - SBS 320 gsm sheet weight calculation
  - YieldReport honest_caveat is non-empty
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.packaging.material_yield import (
    MaterialCostSpec,
    YieldReport,
    compute_material_yield,
    estimate_cycles_per_minute,
    material_cost_per_part,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# A4 sheet: 210 × 297 mm, 320 gsm SBS, $1.60/kg
A4_SBS = MaterialCostSpec(
    material_name="sbs_320gsm",
    cost_per_kg=1.60,
    sheet_size_mm=(210.0, 297.0),
    sheet_weight_gsm=320.0,
)

# Large corrugated press sheet: 1200 × 1000 mm, 5 mm B-flute board, $1.00/kg
CORR_SHEET = MaterialCostSpec(
    material_name="corrugated_B-flute_5mm",
    cost_per_kg=1.00,
    sheet_size_mm=(1200.0, 1000.0),
    sheet_weight_gsm=750.0,  # combined board basis weight
)

# 100 × 100 mm square outline
SQUARE_100 = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]

# 200 × 300 mm box outline
BOX_200_300 = [(0.0, 0.0), (200.0, 0.0), (200.0, 300.0), (0.0, 300.0)]


# ---------------------------------------------------------------------------
# Test 1: A4 sheet with 100×100 mm outline at 75% efficiency → ~4 parts/sheet
# ---------------------------------------------------------------------------

def test_a4_100mm_square_parts_per_sheet():
    """A4 area = 210×297 = 62370 mm²; bbox=10000 mm²; 75% eff → floor(4.68) = 4."""
    report = compute_material_yield(
        box_unfolded_outline=SQUARE_100,
        material=A4_SBS,
        job_quantity=100,
        nesting_efficiency_pct=75.0,
    )
    # 62370 × 0.75 / 10000 = 4.677 → floor = 4
    assert report.parts_per_sheet == 4, f"expected 4, got {report.parts_per_sheet}"


# ---------------------------------------------------------------------------
# Test 2: cost scales linearly with job_quantity (double quantity → ~double cost)
# ---------------------------------------------------------------------------

def test_cost_scales_linearly_with_quantity():
    report_100 = compute_material_yield(
        box_unfolded_outline=SQUARE_100,
        material=A4_SBS,
        job_quantity=100,
        nesting_efficiency_pct=75.0,
    )
    report_200 = compute_material_yield(
        box_unfolded_outline=SQUARE_100,
        material=A4_SBS,
        job_quantity=200,
        nesting_efficiency_pct=75.0,
    )
    # At exactly 100/parts_per_sheet boundary, should double
    ratio = report_200.total_material_cost / report_100.total_material_cost
    assert abs(ratio - 2.0) < 0.1, f"cost ratio {ratio:.3f} should be ~2.0"


# ---------------------------------------------------------------------------
# Test 3: waste_pct == 100 - nesting_efficiency_pct
# ---------------------------------------------------------------------------

def test_waste_pct_is_complement_of_efficiency():
    report = compute_material_yield(
        box_unfolded_outline=SQUARE_100,
        material=A4_SBS,
        job_quantity=50,
        nesting_efficiency_pct=75.0,
    )
    assert abs(report.waste_pct - 25.0) < 1e-9


# ---------------------------------------------------------------------------
# Test 4: sheets_per_job is ceiling(quantity / parts_per_sheet)
# ---------------------------------------------------------------------------

def test_sheets_per_job_is_ceiling():
    report = compute_material_yield(
        box_unfolded_outline=SQUARE_100,
        material=A4_SBS,
        job_quantity=7,
        nesting_efficiency_pct=75.0,
    )
    expected_sheets = math.ceil(7 / report.parts_per_sheet)
    assert report.sheets_per_job == expected_sheets


# ---------------------------------------------------------------------------
# Test 5: material_used_kg = sheets_per_job × sheet_weight_kg
# ---------------------------------------------------------------------------

def test_material_used_kg_calculation():
    report = compute_material_yield(
        box_unfolded_outline=SQUARE_100,
        material=A4_SBS,
        job_quantity=100,
        nesting_efficiency_pct=75.0,
    )
    # A4 area in m²: 0.210 × 0.297 = 0.06237 m²; gsm=320; sheet_wt = 0.06237 × 320/1000 = 0.01996 kg
    sheet_wt = (0.210 * 0.297) * 320.0 / 1000.0
    expected_kg = report.sheets_per_job * sheet_wt
    assert abs(report.material_used_kg - expected_kg) < 1e-6


# ---------------------------------------------------------------------------
# Test 6: estimate_cycles_per_minute formula
# ---------------------------------------------------------------------------

def test_cycles_per_minute():
    cpm = estimate_cycles_per_minute((210.0, 297.0), machine_throughput_sheets_per_hour=7200.0)
    assert abs(cpm - 120.0) < 1e-6


# ---------------------------------------------------------------------------
# Test 7: material_cost_per_part = total_cost / quantity
# ---------------------------------------------------------------------------

def test_cost_per_part():
    qty = 100
    report = compute_material_yield(
        box_unfolded_outline=SQUARE_100,
        material=A4_SBS,
        job_quantity=qty,
        nesting_efficiency_pct=75.0,
    )
    cpp = material_cost_per_part(report, qty)
    assert abs(cpp - report.total_material_cost / qty) < 1e-9


# ---------------------------------------------------------------------------
# Test 8: invalid job_quantity raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_job_quantity_raises():
    with pytest.raises(ValueError, match="job_quantity"):
        compute_material_yield(
            box_unfolded_outline=SQUARE_100,
            material=A4_SBS,
            job_quantity=0,
        )


# ---------------------------------------------------------------------------
# Test 9: invalid nesting_efficiency_pct raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_efficiency_raises():
    with pytest.raises(ValueError, match="nesting_efficiency_pct"):
        compute_material_yield(
            box_unfolded_outline=SQUARE_100,
            material=A4_SBS,
            job_quantity=10,
            nesting_efficiency_pct=110.0,
        )


# ---------------------------------------------------------------------------
# Test 10: YieldReport honest_caveat is non-empty
# ---------------------------------------------------------------------------

def test_yield_report_honest_caveat():
    report = compute_material_yield(
        box_unfolded_outline=SQUARE_100,
        material=A4_SBS,
        job_quantity=50,
    )
    assert report.honest_caveat != ""


# ---------------------------------------------------------------------------
# Test 11: large corrugated sheet with box_200_300 outline → parts_per_sheet > 1
# ---------------------------------------------------------------------------

def test_corrugated_large_sheet_multiple_parts():
    report = compute_material_yield(
        box_unfolded_outline=BOX_200_300,
        material=CORR_SHEET,
        job_quantity=1000,
        nesting_efficiency_pct=70.0,
    )
    # 1200×1000 × 0.70 / (200×300) = 840000 / 60000 = 14
    assert report.parts_per_sheet >= 10


# ---------------------------------------------------------------------------
# Test 12: default estimate_cycles_per_minute (8000 sph → 133.3 spm)
# ---------------------------------------------------------------------------

def test_default_cycles_per_minute():
    cpm = estimate_cycles_per_minute((1200.0, 1000.0))
    assert abs(cpm - 8000.0 / 60.0) < 1e-6
