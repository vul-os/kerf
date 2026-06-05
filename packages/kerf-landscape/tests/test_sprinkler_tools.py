"""
Oracle tests for landscape_layout_sprinkler and landscape_flow_demand LLM tools.

Oracle sources
--------------
* Hunter PGP: radius = 30 ft, GPM = 4.0 (full circle at 45 PSI).
* Rain Bird 5000: radius = 25 ft, GPM = 3.3 (full circle at 35 PSI).
* Square pattern: spacing = 50 % of radius (Hunter IDM p. 34).
* Flow per head = gpm × (arc_deg / 360).
"""

from __future__ import annotations

import json
import asyncio

import pytest

from kerf_landscape._compat import ProjectCtx
from kerf_landscape.tools import (
    run_landscape_layout_sprinkler,
    run_landscape_flow_demand,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CTX = ProjectCtx()


def call(handler, **kwargs) -> dict:
    payload = asyncio.run(handler(CTX, json.dumps(kwargs).encode()))
    return json.loads(payload)


# ---------------------------------------------------------------------------
# landscape_layout_sprinkler
# ---------------------------------------------------------------------------

class TestLayoutSprinklerTool:
    def test_hunter_pgp_square_returns_ok(self):
        result = call(
            run_landscape_layout_sprinkler,
            width_ft=60, length_ft=40,
            sprinkler_kind="Hunter_PGP",
            pattern="square",
        )
        assert result.get("ok") is True, result.get("error")

    def test_positions_list_non_empty(self):
        result = call(
            run_landscape_layout_sprinkler,
            width_ft=60, length_ft=40,
            sprinkler_kind="Hunter_PGP",
        )
        assert isinstance(result["positions"], list)
        assert result["head_count"] > 0

    def test_positions_have_x_y_arc(self):
        result = call(
            run_landscape_layout_sprinkler,
            width_ft=40, length_ft=30,
            sprinkler_kind="Hunter_PGP",
        )
        for p in result["positions"]:
            assert "x" in p and "y" in p and "arc_deg" in p

    def test_sprinkler_meta_returned(self):
        result = call(
            run_landscape_layout_sprinkler,
            width_ft=40, length_ft=30,
            sprinkler_kind="Hunter_PGP",
        )
        sp = result["sprinkler"]
        assert sp["model"] == "Hunter PGP"
        assert sp["radius_ft"] == pytest.approx(30.0)
        assert sp["gpm"] == pytest.approx(4.0)

    def test_rainbird_5000(self):
        result = call(
            run_landscape_layout_sprinkler,
            width_ft=50, length_ft=50,
            sprinkler_kind="RainBird_5000",
            pattern="triangular",
        )
        assert result.get("ok") is True
        assert result["head_count"] > 0

    def test_toro_570z(self):
        result = call(
            run_landscape_layout_sprinkler,
            width_ft=20, length_ft=15,
            sprinkler_kind="Toro_570Z",
        )
        assert result.get("ok") is True

    def test_missing_width_ft_returns_error(self):
        result = call(
            run_landscape_layout_sprinkler,
            length_ft=40,
            sprinkler_kind="Hunter_PGP",
        )
        assert result.get("code") == "BAD_ARGS"

    def test_unknown_sprinkler_returns_error(self):
        result = call(
            run_landscape_layout_sprinkler,
            width_ft=40, length_ft=30,
            sprinkler_kind="Fake_Brand_9000",
        )
        assert result.get("code") == "BAD_ARGS"

    def test_head_count_matches_positions_length(self):
        result = call(
            run_landscape_layout_sprinkler,
            width_ft=60, length_ft=40,
            sprinkler_kind="Hunter_PGP",
        )
        assert result["head_count"] == len(result["positions"])

    def test_arc_degrees_valid(self):
        result = call(
            run_landscape_layout_sprinkler,
            width_ft=60, length_ft=40,
            sprinkler_kind="Hunter_PGP",
            pattern="square",
        )
        for p in result["positions"]:
            assert p["arc_deg"] in (90.0, 180.0, 360.0)


# ---------------------------------------------------------------------------
# landscape_flow_demand
# ---------------------------------------------------------------------------

class TestFlowDemandTool:
    """
    Oracle: 4 Hunter PGP heads @ 360° / 4 zones → 4 GPM / zone (1 head per zone).
    Hunter PGP: 4.0 GPM at full circle.
    """

    def test_four_full_circle_heads_four_zones(self):
        positions = [
            {"x": 7.5,  "y": 7.5,  "arc_deg": 360.0},
            {"x": 22.5, "y": 7.5,  "arc_deg": 360.0},
            {"x": 7.5,  "y": 22.5, "arc_deg": 360.0},
            {"x": 22.5, "y": 22.5, "arc_deg": 360.0},
        ]
        result = call(
            run_landscape_flow_demand,
            positions=positions,
            zone_count=4,
            sprinkler_kind="Hunter_PGP",
        )
        assert result.get("ok") is True
        assert result["zone_count"] == 4
        for zone in result["zones"]:
            assert zone["total_gpm"] == pytest.approx(4.0, rel=1e-6), (
                f"Zone {zone['zone']} GPM should be 4.0; got {zone['total_gpm']}"
            )

    def test_total_flow_sum_two_heads(self):
        positions = [
            {"x": 7.5,  "y": 7.5,  "arc_deg": 360.0},
            {"x": 22.5, "y": 7.5,  "arc_deg": 360.0},
        ]
        result = call(
            run_landscape_flow_demand,
            positions=positions,
            zone_count=2,
            sprinkler_kind="Hunter_PGP",
        )
        # 2 zones × 4 GPM = 8 GPM total
        assert result["total_flow_gpm"] == pytest.approx(8.0, rel=1e-5)

    def test_partial_arc_90deg_quarter_gpm(self):
        """90° arc → 1/4 of full-circle GPM."""
        positions = [{"x": 5.0, "y": 5.0, "arc_deg": 90.0}]
        result = call(
            run_landscape_flow_demand,
            positions=positions,
            zone_count=1,
            sprinkler_kind="Hunter_PGP",
        )
        # 4.0 × (90/360) = 1.0 GPM
        assert result["zones"][0]["total_gpm"] == pytest.approx(1.0, rel=1e-6)

    def test_partial_arc_180deg_half_gpm(self):
        """180° arc → 1/2 of full-circle GPM."""
        positions = [{"x": 5.0, "y": 5.0, "arc_deg": 180.0}]
        result = call(
            run_landscape_flow_demand,
            positions=positions,
            zone_count=1,
            sprinkler_kind="Hunter_PGP",
        )
        # 4.0 × (180/360) = 2.0 GPM
        assert result["zones"][0]["total_gpm"] == pytest.approx(2.0, rel=1e-6)

    def test_missing_positions_returns_error(self):
        result = call(
            run_landscape_flow_demand,
            sprinkler_kind="Hunter_PGP",
        )
        assert result.get("code") == "BAD_ARGS"

    def test_missing_sprinkler_kind_returns_error(self):
        positions = [{"x": 5.0, "y": 5.0, "arc_deg": 360.0}]
        result = call(
            run_landscape_flow_demand,
            positions=positions,
        )
        assert result.get("code") == "BAD_ARGS"

    def test_custom_zone_count_three(self):
        positions = [{"x": i * 10.0, "y": 5.0, "arc_deg": 360.0} for i in range(6)]
        result = call(
            run_landscape_flow_demand,
            positions=positions,
            zone_count=3,
            sprinkler_kind="Hunter_PGP",
        )
        assert result.get("ok") is True
        assert result["zone_count"] == 3
        assert len(result["zones"]) == 3

    def test_rainbird_5000_flow(self):
        positions = [{"x": 5.0, "y": 5.0, "arc_deg": 360.0}]
        result = call(
            run_landscape_flow_demand,
            positions=positions,
            zone_count=1,
            sprinkler_kind="RainBird_5000",
        )
        # RainBird 5000: 3.3 GPM full circle
        assert result.get("ok") is True
        assert result["zones"][0]["total_gpm"] == pytest.approx(3.3, rel=1e-5)
