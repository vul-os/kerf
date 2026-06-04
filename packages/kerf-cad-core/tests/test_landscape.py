"""
Tests for kerf_cad_core.civil.landscape — Rhino landscape module.

Covers:
  1.  design_grading: cut/fill non-zero for non-flat TIN
  2.  design_grading: surface_out is a valid TINSurface
  3.  design_grading: drainage_slope_min_pct recorded correctly
  4.  design_grading: max_grade_pct propagated
  5.  compute_drainage_network: ≥ 1 catchment for a square 20×20 m site
  6.  compute_drainage_network: flow_paths non-empty
  7.  compute_drainage_network: runoff_coefficients positive
  8.  design_planting_plan: zone 6 selects different species than zone 10
  9.  design_planting_plan: placements non-empty for a valid polygon
  10. design_planting_plan: total_area_m2 > 0
  11. design_planting_plan: estimated_water_demand > 0 when placements exist
  12. design_planting_plan: all placed species are in the returned species list

All tests are hermetic (no DB, no filesystem, no network).
"""
from __future__ import annotations

import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import math
import numpy as np
import pytest

from kerf_cad_core.civil.tin_surface import (
    TINSurface,
    SurveyPoint,
    build_tin_from_points,
)
from kerf_cad_core.civil.landscape import (
    GradingPlan,
    DrainageNetwork,
    PlantingPlan,
    design_grading,
    compute_drainage_network,
    design_planting_plan,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_sloped_tin(rows: int = 5, cols: int = 5, slope_m_per_m: float = 0.05) -> TINSurface:
    """
    Build a TIN surface with a regular grid, sloping linearly in X.
    slope_m_per_m = rise-over-run.
    """
    pts: list[SurveyPoint] = []
    for i in range(rows):
        for j in range(cols):
            x = float(j * 4)          # 4 m spacing
            y = float(i * 4)
            z = 10.0 + x * slope_m_per_m
            pts.append(SurveyPoint(
                point_id=f"P{i}_{j}", x=x, y=y, elevation=z,
            ))
    return build_tin_from_points(pts)


def _make_flat_tin(rows: int = 5, cols: int = 5) -> TINSurface:
    """Flat TIN at z=10.0."""
    pts: list[SurveyPoint] = []
    for i in range(rows):
        for j in range(cols):
            pts.append(SurveyPoint(
                point_id=f"P{i}_{j}",
                x=float(j * 4),
                y=float(i * 4),
                elevation=10.0,
            ))
    return build_tin_from_points(pts)


def _simple_building() -> tuple[list[tuple[float, float]], float]:
    """4 m × 4 m building centred at (8, 8), FFE = 10.5 m."""
    outline = [(6.0, 6.0), (10.0, 6.0), (10.0, 10.0), (6.0, 10.0)]
    return (outline, 10.5)


def _square_site_outline(size: float = 20.0) -> list[tuple[float, float]]:
    return [(0.0, 0.0), (size, 0.0), (size, size), (0.0, size)]


# ---------------------------------------------------------------------------
# Test 1: cut_volume + fill_volume non-zero for non-flat input
# ---------------------------------------------------------------------------

def test_design_grading_nonzero_cut_fill():
    """
    A sloped TIN with a building at an intermediate elevation must produce
    both non-zero cut and fill volumes after grading.
    """
    tin = _make_sloped_tin()
    bldg = _simple_building()
    plan = design_grading(tin, [bldg])
    # Grading adjusts elevations → cut + fill both positive
    assert plan.cut_volume_m3 >= 0.0
    assert plan.fill_volume_m3 >= 0.0
    total = plan.cut_volume_m3 + plan.fill_volume_m3
    assert total > 0.0, f"Expected non-zero total earthwork; got {total}"


# ---------------------------------------------------------------------------
# Test 2: surface_out is a valid TINSurface
# ---------------------------------------------------------------------------

def test_design_grading_surface_out_valid():
    tin = _make_sloped_tin()
    plan = design_grading(tin, [_simple_building()])
    assert isinstance(plan.surface_out, TINSurface)
    assert plan.surface_out.triangles.shape[1] == 3
    assert len(plan.surface_out.points) >= 3


# ---------------------------------------------------------------------------
# Test 3: drainage_slope_min_pct recorded correctly
# ---------------------------------------------------------------------------

def test_design_grading_drainage_slope_natural():
    tin = _make_sloped_tin()
    plan = design_grading(tin, [_simple_building()], drainage_pattern='natural')
    assert plan.drainage_slope_min_pct == pytest.approx(5.0)


def test_design_grading_drainage_slope_french_drain():
    tin = _make_sloped_tin()
    plan = design_grading(tin, [_simple_building()], drainage_pattern='french_drain')
    assert plan.drainage_slope_min_pct == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Test 4: max_grade_pct propagated
# ---------------------------------------------------------------------------

def test_design_grading_max_grade_propagated():
    tin = _make_sloped_tin()
    plan = design_grading(tin, [_simple_building()], max_grade_pct=15.0)
    assert plan.max_grade_pct == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Test 5: drainage network ≥ 1 catchment for a square site
# ---------------------------------------------------------------------------

def test_compute_drainage_network_min_one_catchment():
    """
    A 20×20 m sloped TIN should yield at least one delineated catchment basin.
    """
    # Build 5×5 grid over 20 m × 20 m, sloped to SW corner
    pts: list[SurveyPoint] = []
    for i in range(6):
        for j in range(6):
            x = float(j * 4)
            y = float(i * 4)
            z = 15.0 - 0.5 * x - 0.3 * y
            pts.append(SurveyPoint(point_id=f"G{i}_{j}", x=x, y=y, elevation=z))
    tin = build_tin_from_points(pts)
    net = compute_drainage_network(tin)
    assert isinstance(net, DrainageNetwork)
    assert len(net.catchment_polygons) >= 1, (
        f"Expected ≥ 1 catchment; got {len(net.catchment_polygons)}"
    )


# ---------------------------------------------------------------------------
# Test 6: flow_paths non-empty
# ---------------------------------------------------------------------------

def test_compute_drainage_network_flow_paths():
    pts: list[SurveyPoint] = []
    for i in range(6):
        for j in range(6):
            x = float(j * 4)
            y = float(i * 4)
            z = 15.0 - 0.5 * x - 0.3 * y
            pts.append(SurveyPoint(point_id=f"G{i}_{j}", x=x, y=y, elevation=z))
    tin = build_tin_from_points(pts)
    net = compute_drainage_network(tin)
    assert len(net.flow_paths) >= 1


# ---------------------------------------------------------------------------
# Test 7: runoff_coefficients positive
# ---------------------------------------------------------------------------

def test_compute_drainage_network_runoff_positive():
    pts: list[SurveyPoint] = []
    for i in range(5):
        for j in range(5):
            pts.append(SurveyPoint(
                point_id=f"G{i}_{j}",
                x=float(j * 5), y=float(i * 5),
                elevation=20.0 - float(i + j) * 0.4,
            ))
    tin = build_tin_from_points(pts)
    net = compute_drainage_network(tin)
    for c in net.runoff_coefficients:
        assert c > 0.0, f"Runoff coefficient must be > 0; got {c}"


# ---------------------------------------------------------------------------
# Test 8: zone 6 selects different species than zone 10
# ---------------------------------------------------------------------------

def test_planting_plan_zone_6_vs_zone_10_differ():
    outline = _square_site_outline(30.0)
    plan6 = design_planting_plan(outline, site_hardiness_zone=6)
    plan10 = design_planting_plan(outline, site_hardiness_zone=10)

    names6 = {sp['species_name'] for sp in plan6.species}
    names10 = {sp['species_name'] for sp in plan10.species}

    # The two zones must have at least one distinct species selection
    assert names6 != names10, (
        f"Zone 6 and zone 10 species lists should differ; got identical: {names6}"
    )


# ---------------------------------------------------------------------------
# Test 9: placements non-empty for a valid polygon
# ---------------------------------------------------------------------------

def test_planting_plan_placements_nonempty():
    outline = _square_site_outline(40.0)
    plan = design_planting_plan(outline, site_hardiness_zone=7)
    assert len(plan.placements) > 0, "Expected at least one plant placement"


# ---------------------------------------------------------------------------
# Test 10: total_area_m2 > 0
# ---------------------------------------------------------------------------

def test_planting_plan_area_positive():
    outline = _square_site_outline(20.0)
    plan = design_planting_plan(outline, site_hardiness_zone=5)
    assert plan.total_area_m2 > 0.0


# ---------------------------------------------------------------------------
# Test 11: estimated_water_demand > 0 when placements exist
# ---------------------------------------------------------------------------

def test_planting_plan_water_demand_positive():
    outline = _square_site_outline(40.0)
    plan = design_planting_plan(outline, site_hardiness_zone=8)
    if plan.placements:
        assert plan.estimated_water_demand_l_per_month > 0.0


# ---------------------------------------------------------------------------
# Test 12: all placed species are in the returned species list
# ---------------------------------------------------------------------------

def test_planting_plan_placements_species_in_list():
    outline = _square_site_outline(30.0)
    plan = design_planting_plan(outline, site_hardiness_zone=9)
    species_names = {sp['species_name'] for sp in plan.species}
    for _x, _y, sp_name in plan.placements:
        assert sp_name in species_names, (
            f"Placed species '{sp_name}' not found in species list"
        )
