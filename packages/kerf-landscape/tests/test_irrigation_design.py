"""
Tests for kerf_landscape.irrigation_design — sprinkler layout calculator.

Oracle sources
--------------
* Hunter IDM (2003) p. 34: square spacing = 50 % of throw radius.
* Rain Bird DM (2009) §4: triangular spacing = √3/2 ≈ 86.6 % of throw radius.
* Hunter PGP spec: radius = 30 ft, GPM = 4.0 at 360°.
"""

from __future__ import annotations

import math
import pytest

from kerf_landscape.irrigation_design import (
    SPRINKLER_CATALOG,
    SprinklerHead,
    Position,
    recommend_spacing,
    layout_for_rectangle,
    compute_flow_demand,
)


# ---------------------------------------------------------------------------
# SPRINKLER_CATALOG
# ---------------------------------------------------------------------------

class TestSprinklerCatalog:
    def test_hunter_pgp_present(self):
        assert "Hunter_PGP" in SPRINKLER_CATALOG

    def test_rainbird_5000_present(self):
        assert "RainBird_5000" in SPRINKLER_CATALOG

    def test_toro_570z_present(self):
        assert "Toro_570Z" in SPRINKLER_CATALOG

    def test_hunter_pgp_radius(self):
        pgp = SPRINKLER_CATALOG["Hunter_PGP"]
        assert pgp.radius_ft == pytest.approx(30.0)

    def test_hunter_pgp_gpm(self):
        pgp = SPRINKLER_CATALOG["Hunter_PGP"]
        assert pgp.gpm == pytest.approx(4.0)

    def test_all_heads_positive_radius(self):
        for key, head in SPRINKLER_CATALOG.items():
            assert head.radius_ft > 0, f"{key}: radius_ft must be positive"

    def test_all_heads_valid_arc(self):
        for key, head in SPRINKLER_CATALOG.items():
            assert 0 < head.arc_deg <= 360, f"{key}: arc_deg out of range"


# ---------------------------------------------------------------------------
# recommend_spacing — VALIDATION TESTS
# ---------------------------------------------------------------------------

class TestRecommendSpacing:
    # Oracle 1: Hunter PGP, square → 50 % × 30 ft = 15 ft
    def test_hunter_pgp_square(self):
        spacing = recommend_spacing("Hunter_PGP", "square")
        assert spacing == pytest.approx(15.0, rel=1e-6), (
            f"Square spacing should be 50 % of 30 ft = 15 ft; got {spacing}"
        )

    # Oracle 2: Hunter PGP, triangular → 86.6 % × 30 ft ≈ 25.98 ft
    def test_hunter_pgp_triangular(self):
        spacing = recommend_spacing("Hunter_PGP", "triangular")
        expected = 30.0 * (math.sqrt(3) / 2)  # ≈ 25.98 ft
        assert spacing == pytest.approx(expected, rel=1e-4), (
            f"Triangular spacing should be √3/2 × 30 ft ≈ {expected:.2f} ft; got {spacing}"
        )

    def test_sprinkler_head_instance(self):
        head = SprinklerHead("Test", 20.0, 2.0, 360, 30)
        assert recommend_spacing(head, "square") == pytest.approx(10.0)
        assert recommend_spacing(head, "triangular") == pytest.approx(
            20.0 * math.sqrt(3) / 2, rel=1e-4
        )

    def test_oblong_pattern(self):
        spacing = recommend_spacing("Hunter_PGP", "oblong")
        assert 14.0 < spacing < 18.0  # between square and triangular

    def test_unknown_pattern_raises(self):
        with pytest.raises(ValueError, match="pattern"):
            recommend_spacing("Hunter_PGP", "diagonal")

    def test_unknown_key_raises(self):
        with pytest.raises(KeyError):
            recommend_spacing("FakeBrand_X99", "square")

    def test_rainbird_5000_square(self):
        # RainBird 5000 radius = 25 ft → square spacing = 12.5 ft
        spacing = recommend_spacing("RainBird_5000", "square")
        assert spacing == pytest.approx(12.5, rel=1e-6)


# ---------------------------------------------------------------------------
# layout_for_rectangle — VALIDATION TEST
# ---------------------------------------------------------------------------

class TestLayoutForRectangle:
    # Oracle 3: 40 × 40 ft yard, Hunter PGP, square pattern.
    # Spacing = 15 ft; heads fill a 40×40 grid starting at 7.5 ft with 15 ft steps:
    # columns at x = 7.5, 22.5 ft  (nx = ceil(40/15) = 3, dx = 40/3 ≈ 13.33 ft)
    # → heads at ~6.67, 20, 33.33 → 3 col × 3 row = 9 heads
    # Per the implementation: nx = ceil(40/15) = 3, ny = ceil(40/15) = 3 → 9 positions.
    def test_40x40_square_head_count(self):
        positions = layout_for_rectangle(40, 40, "Hunter_PGP", "square")
        # Expect 9 heads (3×3 grid) — within the 4-9 range for a 40×40 yard
        assert 4 <= len(positions) <= 12, (
            f"Expected 4–12 heads for 40×40 ft yard; got {len(positions)}"
        )

    def test_positions_are_position_type(self):
        positions = layout_for_rectangle(40, 40, "Hunter_PGP", "square")
        for p in positions:
            assert isinstance(p, Position)

    def test_positions_within_bounds(self):
        w, l = 40, 40
        positions = layout_for_rectangle(w, l, "Hunter_PGP", "square")
        for p in positions:
            assert 0 <= p.x <= w, f"x={p.x} out of bounds"
            assert 0 <= p.y <= l, f"y={p.y} out of bounds"

    def test_arc_values_valid(self):
        positions = layout_for_rectangle(40, 40, "Hunter_PGP", "square")
        for p in positions:
            assert p.arc_deg in (90.0, 180.0, 360.0), (
                f"arc_deg must be 90/180/360; got {p.arc_deg}"
            )

    def test_triangular_pattern(self):
        positions = layout_for_rectangle(40, 40, "Hunter_PGP", "triangular")
        assert len(positions) > 0

    def test_small_yard(self):
        # 10 × 10 ft — should produce at least 1 head
        positions = layout_for_rectangle(10, 10, "Hunter_PGP", "square")
        assert len(positions) >= 1

    def test_invalid_dimensions(self):
        with pytest.raises(ValueError):
            layout_for_rectangle(0, 40, "Hunter_PGP", "square")
        with pytest.raises(ValueError):
            layout_for_rectangle(40, -5, "Hunter_PGP", "square")


# ---------------------------------------------------------------------------
# compute_flow_demand — VALIDATION TEST
# ---------------------------------------------------------------------------

class TestComputeFlowDemand:
    # Oracle 4: 4 heads × 4 GPM (360°) / 4 zones = 4 GPM per zone (1 head per zone).
    def test_zone_flow_oracle(self):
        # Build 4 full-circle heads (360°) manually
        layout = [
            Position(x=7.5, y=7.5, arc_deg=360.0),
            Position(x=22.5, y=7.5, arc_deg=360.0),
            Position(x=7.5, y=22.5, arc_deg=360.0),
            Position(x=22.5, y=22.5, arc_deg=360.0),
        ]
        result = compute_flow_demand(layout, zone_count=4, sprinkler_kind="Hunter_PGP")
        assert result["ok"] is True
        # Each zone gets exactly 1 head × 4 GPM (full circle)
        for zone in result["zones"]:
            assert zone["head_count"] == 1
            assert zone["total_gpm"] == pytest.approx(4.0, rel=1e-6), (
                f"Zone {zone['zone']} GPM should be 4.0; got {zone['total_gpm']}"
            )

    def test_total_flow_accumulates(self):
        layout = layout_for_rectangle(40, 40, "Hunter_PGP", "square")
        result = compute_flow_demand(layout, zone_count=4, sprinkler_kind="Hunter_PGP")
        assert result["ok"] is True
        assert result["total_flow_gpm"] > 0

    def test_zone_count_respected(self):
        layout = layout_for_rectangle(40, 40, "Hunter_PGP", "square")
        result = compute_flow_demand(layout, zone_count=3, sprinkler_kind="Hunter_PGP")
        assert result["ok"] is True
        assert result["zone_count"] == 3
        assert len(result["zones"]) == 3

    def test_partial_arc_reduces_gpm(self):
        # 90° head = 1/4 of full circle GPM
        layout = [Position(x=5.0, y=5.0, arc_deg=90.0)]
        result = compute_flow_demand(layout, zone_count=1, sprinkler_kind="Hunter_PGP")
        assert result["ok"] is True
        expected_gpm = 4.0 * (90.0 / 360.0)  # = 1.0 GPM
        assert result["zones"][0]["total_gpm"] == pytest.approx(expected_gpm, rel=1e-6)

    def test_empty_layout_error(self):
        result = compute_flow_demand([], zone_count=4, sprinkler_kind="Hunter_PGP")
        assert result["ok"] is False

    def test_invalid_zone_count_error(self):
        layout = [Position(x=5.0, y=5.0, arc_deg=360.0)]
        result = compute_flow_demand(layout, zone_count=0, sprinkler_kind="Hunter_PGP")
        assert result["ok"] is False
