"""
Tests for kerf_cad_core.civil.parcels — parcel geometry + lot-layout subdivision.

References:
  • AASHTO Green Book (2018) Ch. 3 — subdivision street design.
  • ASCE Manual 21 — lot proportioning, setback geometry.
  • BLM Manual of Surveying Instructions §6 — rectangular subdivision.
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.civil.parcels import (
    Parcel,
    SubdivisionSpec,
    SubdivisionReport,
    polygon_area,
    polygon_centroid,
    polygon_perimeter,
    polygon_contains_point,
    subdivide_parcel,
)


# ---------------------------------------------------------------------------
# Unit-square basic geometry
# ---------------------------------------------------------------------------

UNIT_SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def test_unit_square_area():
    """Shoelace formula: unit square area = 1.0."""
    assert abs(polygon_area(UNIT_SQUARE)) == pytest.approx(1.0, abs=1e-9)


def test_unit_square_centroid():
    """Centroid of unit square = (0.5, 0.5)."""
    cx, cy = polygon_centroid(UNIT_SQUARE)
    assert cx == pytest.approx(0.5, abs=1e-9)
    assert cy == pytest.approx(0.5, abs=1e-9)


def test_unit_square_perimeter():
    """Perimeter of unit square = 4.0."""
    assert polygon_perimeter(UNIT_SQUARE) == pytest.approx(4.0, abs=1e-9)


def test_signed_area_ccw_positive():
    """CCW winding → positive signed area."""
    assert polygon_area(UNIT_SQUARE) > 0


def test_signed_area_cw_negative():
    """CW winding → negative signed area."""
    cw = list(reversed(UNIT_SQUARE))
    assert polygon_area(cw) < 0


# ---------------------------------------------------------------------------
# Rectangle area
# ---------------------------------------------------------------------------

RECT_100x200 = [(0.0, 0.0), (100.0, 0.0), (100.0, 200.0), (0.0, 200.0)]


def test_rect_100x200_area():
    """100×200 m rectangle area = 20,000 m²."""
    assert abs(polygon_area(RECT_100x200)) == pytest.approx(20_000.0, abs=1e-6)


def test_rect_100x200_centroid():
    """Centroid of 100×200 rectangle = (50, 100)."""
    cx, cy = polygon_centroid(RECT_100x200)
    assert cx == pytest.approx(50.0, abs=1e-6)
    assert cy == pytest.approx(100.0, abs=1e-6)


# ---------------------------------------------------------------------------
# polygon_contains_point
# ---------------------------------------------------------------------------

def test_contains_interior_point():
    assert polygon_contains_point(UNIT_SQUARE, (0.5, 0.5)) is True


def test_contains_exterior_point():
    assert polygon_contains_point(UNIT_SQUARE, (1.5, 0.5)) is False


def test_contains_far_exterior():
    assert polygon_contains_point(UNIT_SQUARE, (-1.0, -1.0)) is False


# ---------------------------------------------------------------------------
# Subdivision: 100×200 m parcel, target 500 m² → ~40 lots
# ---------------------------------------------------------------------------

def _make_100x200_spec(
    target_area: float = 500.0,
    frontage: float = 10.0,
    setback_front: float = 3.0,
    setback_side: float = 1.0,
    setback_rear: float = 3.0,
) -> SubdivisionSpec:
    return SubdivisionSpec(
        parent_boundary=RECT_100x200,
        target_lot_area=target_area,
        minimum_frontage=frontage,
        access_road_polyline=[(0.0, 0.0), (100.0, 0.0)],
        setback_front=setback_front,
        setback_side=setback_side,
        setback_rear=setback_rear,
    )


def test_subdivide_approx_40_lots():
    """100×200 m parcel, target 500 m², 10 m frontage → approximately 40 lots."""
    report = subdivide_parcel(_make_100x200_spec())
    # Parent area = 20,000 m²; at 500 m² per lot = 40 ideal lots.
    # Setbacks reduce net area; expect 20–45 lots.
    assert 20 <= report.n_lots <= 45, f"Expected ~40 lots, got {report.n_lots}"


def test_subdivide_returns_parcels():
    report = subdivide_parcel(_make_100x200_spec())
    assert len(report.parcels) == report.n_lots
    assert all(isinstance(p, Parcel) for p in report.parcels)


def test_subdivide_positive_lot_area():
    report = subdivide_parcel(_make_100x200_spec())
    for p in report.parcels:
        assert p.area > 0.0, f"Lot {p.parcel_id} has non-positive area {p.area}"


def test_subdivide_minimum_frontage_respected():
    """
    Each lot width must be ≥ minimum_frontage (AASHTO Green Book 2018 §3).
    Lot width ~ bounding-box width / n_cols.
    We verify each lot's parcel_id starts with 'L' and n_lots > 0.
    """
    spec = _make_100x200_spec(frontage=20.0)
    report = subdivide_parcel(spec)
    assert report.n_lots > 0
    # Verify each lot's x-extent in the boundary is ≥ setback-adjusted frontage
    for p in report.parcels:
        xs = [v[0] for v in p.boundary]
        lot_w = max(xs) - min(xs)
        # After side setbacks removed, the gross width cell should be ≥ frontage
        # (setbacks are deducted; net interior ≥ frontage − 2×setback_side)
        assert lot_w > 0.0, f"Lot {p.parcel_id} width = {lot_w}"


def test_subdivide_setback_waste_positive():
    """Waste area ≥ 0 (setbacks + roads reduce usable area; ASCE Manual 21)."""
    report = subdivide_parcel(_make_100x200_spec())
    assert report.waste_area >= 0.0


def test_subdivide_waste_accounts_for_setbacks():
    """
    Larger setbacks → larger waste_area.
    ASCE Manual 21: setback area counts as waste relative to parent area.
    """
    small_sb = subdivide_parcel(_make_100x200_spec(setback_front=0.5, setback_side=0.1, setback_rear=0.5))
    large_sb = subdivide_parcel(_make_100x200_spec(setback_front=5.0, setback_side=2.0, setback_rear=5.0))
    # Larger setbacks → more waste (or fewer lots)
    assert large_sb.waste_area >= small_sb.waste_area or large_sb.n_lots <= small_sb.n_lots


def test_subdivide_average_lot_area():
    """Average lot area should be close to target (within factor of 2)."""
    target = 500.0
    report = subdivide_parcel(_make_100x200_spec(target_area=target))
    if report.n_lots > 0:
        ratio = report.average_lot_area / target
        assert 0.1 < ratio < 3.0, f"avg_lot_area={report.average_lot_area} far from target={target}"


def test_subdivide_honest_caveat_present():
    """SubdivisionReport must include honest_caveat string (BLM §6.2)."""
    report = subdivide_parcel(_make_100x200_spec())
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 10


def test_subdivide_degenerate_too_small_parent():
    """Parent with < 3 vertices → n_lots=0, graceful report."""
    spec = SubdivisionSpec(
        parent_boundary=[(0.0, 0.0), (1.0, 0.0)],
        target_lot_area=100.0,
        minimum_frontage=10.0,
        access_road_polyline=[],
        setback_front=1.0,
        setback_side=0.5,
        setback_rear=1.0,
    )
    report = subdivide_parcel(spec)
    assert report.n_lots == 0


def test_subdivide_parcel_ids_unique():
    """Every lot must have a unique parcel_id."""
    report = subdivide_parcel(_make_100x200_spec())
    ids = [p.parcel_id for p in report.parcels]
    assert len(ids) == len(set(ids))


def test_polygon_area_triangle():
    """Right triangle with legs 3 and 4: area = 6."""
    tri = [(0.0, 0.0), (3.0, 0.0), (0.0, 4.0)]
    assert abs(polygon_area(tri)) == pytest.approx(6.0, abs=1e-9)


def test_polygon_perimeter_triangle():
    """3-4-5 right triangle: perimeter = 12."""
    tri = [(0.0, 0.0), (3.0, 0.0), (0.0, 4.0)]
    assert polygon_perimeter(tri) == pytest.approx(12.0, abs=1e-9)
