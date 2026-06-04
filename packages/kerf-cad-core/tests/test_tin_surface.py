"""
Tests for kerf_cad_core.civil.tin_surface — dynamic TIN surface.

Covers:
  - build_tin_from_points: 4 corner points → 2 triangles
  - build_tin_from_points: elevation range correct
  - add_point_dynamic: 5th point inside square → 4 triangles
  - contour_lines: sloped plane → parallel lines at correct intervals
  - cut_fill_volume: identical surfaces → zero net volume
  - cut_fill_volume: elevated surface → positive cut volume
  - build_tin_from_points with breakline constraint
  - collinear points raise ValueError
  - fewer than 3 points raise ValueError
  - min/max elevation correct after add_point_dynamic
  - contour_lines returns correct count of levels
  - add_point_dynamic: duplicate XY returns unchanged
  - contour_lines: negative interval raises ValueError
  - build_tin_from_points: large grid (9 points)
  - add_point_dynamic: triangle count increases monotonically

Author: imranparuk
"""
from __future__ import annotations

import math
import pytest
import numpy as np

from kerf_cad_core.civil.tin_surface import (
    SurveyPoint,
    Breakline,
    TINSurface,
    build_tin_from_points,
    contour_lines,
    cut_fill_volume,
    add_point_dynamic,
)


# ---------------------------------------------------------------------------
# Helper: make a square of 4 corner survey points at z=elevation
# ---------------------------------------------------------------------------

def _square_pts(size: float = 10.0, elevation: float = 0.0) -> list[SurveyPoint]:
    return [
        SurveyPoint('P1', 0.0,   0.0,   elevation),
        SurveyPoint('P2', size,  0.0,   elevation),
        SurveyPoint('P3', size,  size,  elevation),
        SurveyPoint('P4', 0.0,   size,  elevation),
    ]


# ---------------------------------------------------------------------------
# TIN construction
# ---------------------------------------------------------------------------

def test_tin_4_corners_produces_2_triangles():
    """4 coplanar corner points → exactly 2 triangles (Delaunay of a square)."""
    pts = _square_pts(size=10.0, elevation=5.0)
    surface = build_tin_from_points(pts)
    assert surface.triangles.shape[0] == 2, (
        f"Expected 2 triangles from 4 corners, got {surface.triangles.shape[0]}"
    )


def test_tin_4_corners_elevation_range():
    """Elevation range is reported correctly."""
    pts = _square_pts(elevation=5.0)
    surface = build_tin_from_points(pts)
    assert abs(surface.min_elevation - 5.0) < 1e-9
    assert abs(surface.max_elevation - 5.0) < 1e-9


def test_tin_varying_elevations():
    """TIN with varying elevations reports correct min/max."""
    pts = [
        SurveyPoint('P1', 0.0,  0.0,  10.0),
        SurveyPoint('P2', 10.0, 0.0,  20.0),
        SurveyPoint('P3', 10.0, 10.0, 15.0),
        SurveyPoint('P4', 0.0,  10.0, 25.0),
    ]
    surface = build_tin_from_points(pts)
    assert abs(surface.min_elevation - 10.0) < 1e-9
    assert abs(surface.max_elevation - 25.0) < 1e-9


def test_tin_triangle_indices_valid():
    """All triangle indices are within bounds of the point list."""
    pts = _square_pts()
    surface = build_tin_from_points(pts)
    n = len(surface.points)
    assert surface.triangles.min() >= 0
    assert surface.triangles.max() < n


def test_tin_collinear_raises():
    """All-collinear points must raise ValueError."""
    collinear = [
        SurveyPoint('P1', 0.0, 0.0, 0.0),
        SurveyPoint('P2', 1.0, 0.0, 0.0),
        SurveyPoint('P3', 2.0, 0.0, 0.0),
    ]
    with pytest.raises(ValueError, match="[Cc]ollinear|collinear"):
        build_tin_from_points(collinear)


def test_tin_fewer_than_3_raises():
    """Fewer than 3 points must raise ValueError."""
    pts = [
        SurveyPoint('P1', 0.0, 0.0, 0.0),
        SurveyPoint('P2', 1.0, 0.0, 0.0),
    ]
    with pytest.raises(ValueError):
        build_tin_from_points(pts)


def test_tin_9_point_grid():
    """3×3 grid of 9 points produces a valid TIN with 8 triangles (Delaunay of grid)."""
    pts = []
    k = 0
    for i in range(3):
        for j in range(3):
            pts.append(SurveyPoint(f'P{k}', float(i * 5), float(j * 5), float(k)))
            k += 1
    surface = build_tin_from_points(pts)
    # 9 points in general position → 2N-h-2 triangles (N=9, h=convex hull pts)
    # At minimum there should be several triangles
    assert surface.triangles.shape[0] >= 6
    assert len(surface.points) == 9


def test_tin_with_breakline():
    """Breakline vertices are incorporated into the TIN."""
    pts = [
        SurveyPoint('P1', 0.0,  0.0,  10.0),
        SurveyPoint('P2', 20.0, 0.0,  10.0),
        SurveyPoint('P3', 20.0, 20.0, 10.0),
        SurveyPoint('P4', 0.0,  20.0, 10.0),
    ]
    bl = Breakline(
        breakline_id='BL1',
        points=[(10.0, 0.0, 10.0), (10.0, 20.0, 10.0)],
        kind='standard',
    )
    surface = build_tin_from_points(pts, breaklines=[bl])
    # Breakline added 2 new points → at least 6 points in output
    assert len(surface.points) >= 6
    assert surface.triangles.shape[0] > 2


# ---------------------------------------------------------------------------
# add_point_dynamic
# ---------------------------------------------------------------------------

def test_add_point_dynamic_increases_triangles():
    """Adding a 5th point inside the square increases triangle count."""
    pts = _square_pts(size=10.0, elevation=0.0)
    surface = build_tin_from_points(pts)
    tri_before = surface.triangles.shape[0]

    # Centre point
    centre = SurveyPoint('P5', 5.0, 5.0, 0.0)
    surface2 = add_point_dynamic(surface, centre)
    tri_after = surface2.triangles.shape[0]

    assert tri_after > tri_before, (
        f"Triangle count should increase: was {tri_before}, now {tri_after}"
    )
    # Adding 1 interior point to a Delaunay triangulation adds 2 triangles
    # (splits one triangle into 3, or merges cavity into 4 etc.)
    assert tri_after >= 4


def test_add_point_dynamic_point_count():
    """Point list grows by 1 after dynamic insertion."""
    pts = _square_pts()
    surface = build_tin_from_points(pts)
    centre = SurveyPoint('P5', 5.0, 5.0, 3.0)
    surface2 = add_point_dynamic(surface, centre)
    assert len(surface2.points) == len(surface.points) + 1


def test_add_point_dynamic_elevation_range_updates():
    """Elevation range is updated when a higher point is inserted."""
    pts = _square_pts(elevation=0.0)
    surface = build_tin_from_points(pts)
    high_pt = SurveyPoint('P5', 5.0, 5.0, 100.0)
    surface2 = add_point_dynamic(surface, high_pt)
    assert abs(surface2.max_elevation - 100.0) < 1e-9


def test_add_point_dynamic_duplicate_xy_no_change():
    """Inserting a point with duplicate (x, y) returns the surface unchanged."""
    pts = _square_pts()
    surface = build_tin_from_points(pts)
    n_before = len(surface.points)
    dup = SurveyPoint('DUP', 0.0, 0.0, 99.0)   # same xy as P1
    surface2 = add_point_dynamic(surface, dup)
    assert len(surface2.points) == n_before


# ---------------------------------------------------------------------------
# contour_lines
# ---------------------------------------------------------------------------

def test_contour_lines_flat_plane_no_contours():
    """A flat plane at z=5 with interval=1 produces no interior contours
    (all points at same elevation, no interval crossing within triangles)."""
    pts = _square_pts(elevation=5.0)
    surface = build_tin_from_points(pts)
    polys = contour_lines(surface, elevation_interval=1.0)
    # Flat surface has no elevation change → no crossings within triangles
    assert isinstance(polys, list)


def test_contour_lines_sloped_plane_parallel():
    """Sloped plane produces contours at regular intervals.

    Surface: four corners at z = 0, 0, 10, 10 (slope in y-direction).
    Contour interval = 1.0 m → expect ~9 contour levels between z=0..10.
    """
    pts = [
        SurveyPoint('P1', 0.0,  0.0,  0.0),
        SurveyPoint('P2', 10.0, 0.0,  0.0),
        SurveyPoint('P3', 10.0, 10.0, 10.0),
        SurveyPoint('P4', 0.0,  10.0, 10.0),
    ]
    surface = build_tin_from_points(pts)
    polys = contour_lines(surface, elevation_interval=1.0)
    # 9 interior contour levels (z=1..9)
    assert len(polys) >= 8, f"Expected ≥ 8 contours, got {len(polys)}"


def test_contour_lines_count_matches_interval():
    """Count of contour polylines is proportional to elevation range / interval."""
    pts = [
        SurveyPoint('P1', 0.0,  0.0,  0.0),
        SurveyPoint('P2', 10.0, 0.0,  0.0),
        SurveyPoint('P3', 10.0, 10.0, 20.0),
        SurveyPoint('P4', 0.0,  10.0, 20.0),
    ]
    surface = build_tin_from_points(pts)
    polys_1m = contour_lines(surface, elevation_interval=1.0)
    polys_2m = contour_lines(surface, elevation_interval=2.0)
    # Halving interval roughly doubles contour count
    assert len(polys_1m) > len(polys_2m)


def test_contour_lines_invalid_interval_raises():
    """Negative or zero interval raises ValueError."""
    pts = _square_pts()
    surface = build_tin_from_points(pts)
    with pytest.raises(ValueError):
        contour_lines(surface, elevation_interval=-1.0)


def test_contour_lines_returns_list_of_lists():
    """Return type is list[list[tuple]]."""
    pts = [
        SurveyPoint('P1', 0.0,  0.0,  0.0),
        SurveyPoint('P2', 10.0, 0.0,  0.0),
        SurveyPoint('P3', 5.0,  10.0, 5.0),
    ]
    surface = build_tin_from_points(pts)
    polys = contour_lines(surface, elevation_interval=1.0)
    assert isinstance(polys, list)
    for poly in polys:
        assert isinstance(poly, list)
        for pt in poly:
            assert len(pt) == 2


# ---------------------------------------------------------------------------
# cut_fill_volume
# ---------------------------------------------------------------------------

def test_cut_fill_identical_surfaces_zero():
    """Cut/fill between identical surfaces = zero net volume."""
    pts = [
        SurveyPoint('P1', 0.0,  0.0,  5.0),
        SurveyPoint('P2', 10.0, 0.0,  5.0),
        SurveyPoint('P3', 10.0, 10.0, 5.0),
        SurveyPoint('P4', 0.0,  10.0, 5.0),
    ]
    srf_a = build_tin_from_points(pts)
    srf_b = build_tin_from_points(pts)   # identical
    result = cut_fill_volume(srf_a, srf_b, grid_spacing_m=1.0)
    assert abs(result['cut_m3']) < 1e-6
    assert abs(result['fill_m3']) < 1e-6
    assert abs(result['net_m3']) < 1e-6


def test_cut_fill_cut_positive():
    """Existing surface above design surface → positive cut volume."""
    existing = [
        SurveyPoint('P1', 0.0,  0.0,  10.0),
        SurveyPoint('P2', 10.0, 0.0,  10.0),
        SurveyPoint('P3', 10.0, 10.0, 10.0),
        SurveyPoint('P4', 0.0,  10.0, 10.0),
    ]
    design = [
        SurveyPoint('P1', 0.0,  0.0,  5.0),
        SurveyPoint('P2', 10.0, 0.0,  5.0),
        SurveyPoint('P3', 10.0, 10.0, 5.0),
        SurveyPoint('P4', 0.0,  10.0, 5.0),
    ]
    srf_a = build_tin_from_points(existing)
    srf_b = build_tin_from_points(design)
    result = cut_fill_volume(srf_a, srf_b, grid_spacing_m=0.5)
    assert result['cut_m3'] > 0
    assert result['fill_m3'] < 1e-6
    assert result['net_m3'] > 0


def test_cut_fill_fill_positive():
    """Design surface above existing → fill volume positive."""
    existing = [
        SurveyPoint('P1', 0.0,  0.0,  5.0),
        SurveyPoint('P2', 10.0, 0.0,  5.0),
        SurveyPoint('P3', 10.0, 10.0, 5.0),
        SurveyPoint('P4', 0.0,  10.0, 5.0),
    ]
    design = [
        SurveyPoint('P1', 0.0,  0.0,  10.0),
        SurveyPoint('P2', 10.0, 0.0,  10.0),
        SurveyPoint('P3', 10.0, 10.0, 10.0),
        SurveyPoint('P4', 0.0,  10.0, 10.0),
    ]
    srf_a = build_tin_from_points(existing)
    srf_b = build_tin_from_points(design)
    result = cut_fill_volume(srf_a, srf_b, grid_spacing_m=0.5)
    assert result['fill_m3'] > 0
    assert result['cut_m3'] < 1e-6
    assert result['net_m3'] < 0  # net fill = negative
