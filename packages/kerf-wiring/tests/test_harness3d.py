"""
tests/test_harness3d.py — unit tests for the 3D harness route-through-DMU primitive.

DoD (T-36): a bundle routes along a 3-point path with correct diameter;
            length computed; pytest green.

All tests are hermetic (no DB, no network, no optional deps required).
"""
from __future__ import annotations

import json
import math

import pytest

from kerf_wiring.harness3d import (
    HarnessSegment,
    WireSpec,
    _AWG_DIAMETER_MM,
    _PACKING_EFFICIENCY,
    _SLACK_FACTOR,
    harness_segment,
    segment_to_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expected_bundle_diam(
    wires: list[dict],
    packing: float = _PACKING_EFFICIENCY,
    slack: float = _SLACK_FACTOR,
) -> float:
    """Reference implementation of the bundle-diameter formula."""
    total_area = 0.0
    for w in wires:
        if "diameter_mm" in w:
            d = float(w["diameter_mm"])
        elif "gauge_awg" in w:
            d = _AWG_DIAMETER_MM[int(w["gauge_awg"])]
        else:
            d = _AWG_DIAMETER_MM[20]
        count = int(w.get("count", 1))
        r = d / 2.0
        total_area += count * math.pi * r * r
    bundle_area = total_area / packing
    bundle_radius = math.sqrt(bundle_area / math.pi)
    return 2.0 * bundle_radius * slack


def _seg_len(a, b) -> float:
    return math.sqrt(sum((bi - ai) ** 2 for ai, bi in zip(a, b)))


# ---------------------------------------------------------------------------
# harness_segment — basic 3-point path
# ---------------------------------------------------------------------------

class TestHarnessSegment3Point:
    """T-36 DoD: bundle routes along a 3-point path with correct diameter; length computed."""

    WAYPOINTS = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 200.0, 0.0)]
    WIRE_LIST = [
        {"name": "pwr", "gauge_awg": 14},
        {"name": "sig", "gauge_awg": 20},
        {"name": "sig", "gauge_awg": 20},
    ]

    def test_returns_harness_segment(self):
        seg = harness_segment(self.WAYPOINTS, self.WIRE_LIST)
        assert isinstance(seg, HarnessSegment)

    def test_waypoints_preserved(self):
        seg = harness_segment(self.WAYPOINTS, self.WIRE_LIST)
        assert seg.waypoints == [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 200.0, 0.0)]

    def test_length_correct(self):
        """Total length must equal sum of segment Euclidean distances."""
        seg = harness_segment(self.WAYPOINTS, self.WIRE_LIST)
        expected = (
            _seg_len((0, 0, 0), (100, 0, 0)) +   # 100 mm
            _seg_len((100, 0, 0), (100, 200, 0))  # 200 mm
        )
        assert pytest.approx(seg.length_mm, rel=1e-9) == expected
        assert pytest.approx(seg.length_mm, rel=1e-9) == 300.0

    def test_segment_lengths_list(self):
        seg = harness_segment(self.WAYPOINTS, self.WIRE_LIST)
        assert len(seg.segment_lengths_mm) == 2
        assert pytest.approx(seg.segment_lengths_mm[0], rel=1e-9) == 100.0
        assert pytest.approx(seg.segment_lengths_mm[1], rel=1e-9) == 200.0

    def test_bundle_diameter_formula(self):
        """Bundle diameter must match the packing + slack formula."""
        seg = harness_segment(self.WAYPOINTS, self.WIRE_LIST)
        expected = _expected_bundle_diam(self.WIRE_LIST)
        assert pytest.approx(seg.bundle_diameter_mm, rel=1e-9) == expected

    def test_bundle_diameter_positive(self):
        seg = harness_segment(self.WAYPOINTS, self.WIRE_LIST)
        assert seg.bundle_diameter_mm > 0.0

    def test_bundle_diameter_larger_than_largest_wire(self):
        """Bundle must be at least as wide as the thickest individual wire."""
        seg = harness_segment(self.WAYPOINTS, self.WIRE_LIST)
        max_wire_diam = max(_AWG_DIAMETER_MM[14], _AWG_DIAMETER_MM[20])
        assert seg.bundle_diameter_mm > max_wire_diam

    def test_wire_count(self):
        seg = harness_segment(self.WAYPOINTS, self.WIRE_LIST)
        assert len(seg.wires) == 3


# ---------------------------------------------------------------------------
# Diameter model — explicit diameter_mm
# ---------------------------------------------------------------------------

class TestDiameterModel:
    WP = [(0, 0, 0), (50, 0, 0)]

    def test_explicit_diameter_mm(self):
        """diameter_mm key overrides gauge_awg."""
        wires = [{"name": "fat", "diameter_mm": 4.0}]
        seg = harness_segment(self.WP, wires)
        expected = _expected_bundle_diam(wires)
        assert pytest.approx(seg.bundle_diameter_mm, rel=1e-6) == expected

    def test_gauge_awg_lookup(self):
        """AWG 20 → 0.812 mm per table."""
        wires = [{"gauge_awg": 20}]
        seg = harness_segment(self.WP, wires)
        assert pytest.approx(seg.wires[0].diameter_mm, rel=1e-9) == 0.812

    def test_default_awg20_when_no_spec(self):
        """Wire with no diameter or gauge defaults to AWG 20."""
        wires = [{"name": "mystery"}]
        seg = harness_segment(self.WP, wires)
        assert pytest.approx(seg.wires[0].diameter_mm, rel=1e-9) == 0.812

    def test_count_multiplies_area(self):
        """count=3 wires should have larger bundle than count=1."""
        single = harness_segment(self.WP, [{"diameter_mm": 1.0}])
        triple = harness_segment(self.WP, [{"diameter_mm": 1.0, "count": 3}])
        assert triple.bundle_diameter_mm > single.bundle_diameter_mm

    def test_count_area_exact(self):
        """3× count on a single wire equals 3 separate entries with same wire."""
        wires_count = [{"diameter_mm": 1.0, "count": 3}]
        wires_explicit = [
            {"diameter_mm": 1.0},
            {"diameter_mm": 1.0},
            {"diameter_mm": 1.0},
        ]
        seg_c = harness_segment(self.WP, wires_count)
        seg_e = harness_segment(self.WP, wires_explicit)
        assert pytest.approx(seg_c.bundle_diameter_mm, rel=1e-9) == seg_e.bundle_diameter_mm

    def test_diameter_mm_overrides_gauge_awg(self):
        """When both present, diameter_mm wins."""
        wires = [{"gauge_awg": 10, "diameter_mm": 1.0}]
        seg = harness_segment(self.WP, wires)
        assert pytest.approx(seg.wires[0].diameter_mm, rel=1e-9) == 1.0

    def test_more_wires_bigger_bundle(self):
        """Adding wires always increases bundle diameter."""
        w1 = [{"diameter_mm": 1.0}]
        w2 = [{"diameter_mm": 1.0}, {"diameter_mm": 1.0}]
        s1 = harness_segment(self.WP, w1)
        s2 = harness_segment(self.WP, w2)
        assert s2.bundle_diameter_mm > s1.bundle_diameter_mm

    def test_slack_factor_applied(self):
        """bundle_diam should be slack_factor × geometric diam."""
        wires = [{"diameter_mm": 2.0}]
        seg_default = harness_segment(self.WP, wires)
        seg_no_slack = harness_segment(self.WP, wires, slack_factor=1.0)
        assert pytest.approx(
            seg_default.bundle_diameter_mm / seg_no_slack.bundle_diameter_mm,
            rel=1e-9,
        ) == _SLACK_FACTOR


# ---------------------------------------------------------------------------
# Path geometry — various configurations
# ---------------------------------------------------------------------------

class TestPathGeometry:
    WIRE_LIST = [{"gauge_awg": 20}]

    def test_two_point_path(self):
        seg = harness_segment([(0, 0, 0), (10, 0, 0)], self.WIRE_LIST)
        assert pytest.approx(seg.length_mm, rel=1e-9) == 10.0
        assert len(seg.segment_lengths_mm) == 1

    def test_3d_diagonal(self):
        """(0,0,0)→(3,4,0) = 5 mm; (3,4,0)→(3,4,12) = 12 mm → total 17 mm."""
        seg = harness_segment(
            [(0, 0, 0), (3, 4, 0), (3, 4, 12)],
            self.WIRE_LIST,
        )
        assert pytest.approx(seg.length_mm, rel=1e-9) == 17.0
        assert pytest.approx(seg.segment_lengths_mm[0], rel=1e-9) == 5.0
        assert pytest.approx(seg.segment_lengths_mm[1], rel=1e-9) == 12.0

    def test_four_waypoints(self):
        pts = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (10, 10, 10)]
        seg = harness_segment(pts, self.WIRE_LIST)
        assert len(seg.segment_lengths_mm) == 3
        assert pytest.approx(seg.length_mm, rel=1e-9) == 30.0

    def test_floating_point_waypoints(self):
        seg = harness_segment([(0.5, 1.5, 2.5), (3.5, 5.5, 6.5)], self.WIRE_LIST)
        expected = math.sqrt((3.0) ** 2 + (4.0) ** 2 + (4.0) ** 2)
        assert pytest.approx(seg.length_mm, rel=1e-9) == expected

    def test_colinear_waypoints(self):
        """Waypoints on a line — sum of individual segments."""
        seg = harness_segment([(0, 0, 0), (10, 0, 0), (20, 0, 0)], self.WIRE_LIST)
        assert pytest.approx(seg.length_mm, rel=1e-9) == 20.0

    def test_waypoints_as_lists(self):
        """Accepts lists as well as tuples."""
        seg = harness_segment([[0, 0, 0], [100, 0, 0]], self.WIRE_LIST)
        assert pytest.approx(seg.length_mm, rel=1e-9) == 100.0

    def test_waypoints_normalised_to_tuples(self):
        """Returned waypoints are always tuples."""
        seg = harness_segment([[0, 0, 0], [1, 0, 0]], self.WIRE_LIST)
        for pt in seg.waypoints:
            assert isinstance(pt, tuple)


# ---------------------------------------------------------------------------
# Validation — error cases
# ---------------------------------------------------------------------------

class TestValidation:
    WP = [(0, 0, 0), (10, 0, 0)]
    WL = [{"gauge_awg": 20}]

    def test_too_few_waypoints_raises(self):
        with pytest.raises(ValueError, match="at least 2 waypoints"):
            harness_segment([(0, 0, 0)], self.WL)

    def test_empty_waypoints_raises(self):
        with pytest.raises(ValueError, match="at least 2 waypoints"):
            harness_segment([], self.WL)

    def test_wrong_dimension_waypoint_raises(self):
        with pytest.raises(ValueError, match="3 coordinates"):
            harness_segment([(0, 0), (1, 0)], self.WL)

    def test_empty_wire_list_raises(self):
        with pytest.raises(ValueError, match="at least one wire"):
            harness_segment(self.WP, [])

    def test_zero_diameter_raises(self):
        with pytest.raises(ValueError, match="diameter_mm must be > 0"):
            harness_segment(self.WP, [{"diameter_mm": 0.0}])

    def test_negative_diameter_raises(self):
        with pytest.raises(ValueError, match="diameter_mm must be > 0"):
            harness_segment(self.WP, [{"diameter_mm": -1.0}])

    def test_invalid_awg_raises(self):
        with pytest.raises(ValueError, match="AWG 99"):
            harness_segment(self.WP, [{"gauge_awg": 99}])

    def test_zero_count_raises(self):
        with pytest.raises(ValueError, match="count must be ≥ 1"):
            harness_segment(self.WP, [{"diameter_mm": 1.0, "count": 0}])

    def test_bad_packing_efficiency_raises(self):
        with pytest.raises(ValueError, match="packing_efficiency"):
            harness_segment(self.WP, self.WL, packing_efficiency=0.0)

    def test_bad_slack_factor_raises(self):
        with pytest.raises(ValueError, match="slack_factor"):
            harness_segment(self.WP, self.WL, slack_factor=0.5)


# ---------------------------------------------------------------------------
# segment_to_dict
# ---------------------------------------------------------------------------

class TestSegmentToDict:
    WP = [(0, 0, 0), (100, 0, 0), (100, 200, 0)]
    WL = [{"name": "pwr", "gauge_awg": 14}, {"name": "gnd", "gauge_awg": 20}]

    def test_json_serialisable(self):
        seg = harness_segment(self.WP, self.WL)
        d = segment_to_dict(seg)
        # Must not raise
        json.dumps(d)

    def test_keys_present(self):
        seg = harness_segment(self.WP, self.WL)
        d = segment_to_dict(seg)
        assert set(d.keys()) == {
            "waypoints", "wires", "bundle_diameter_mm",
            "length_mm", "segment_lengths_mm",
        }

    def test_waypoints_are_lists(self):
        seg = harness_segment(self.WP, self.WL)
        d = segment_to_dict(seg)
        for pt in d["waypoints"]:
            assert isinstance(pt, list)
            assert len(pt) == 3

    def test_values_match_segment(self):
        seg = harness_segment(self.WP, self.WL)
        d = segment_to_dict(seg)
        assert pytest.approx(d["bundle_diameter_mm"]) == seg.bundle_diameter_mm
        assert pytest.approx(d["length_mm"]) == seg.length_mm
        assert d["segment_lengths_mm"] == seg.segment_lengths_mm


# ---------------------------------------------------------------------------
# LLM tool: route_harness_3d
# ---------------------------------------------------------------------------

class TestRouteHarness3dTool:
    """End-to-end tests for the LLM-facing tool wrapper."""

    def _call(self, args: dict) -> dict:
        import asyncio
        from kerf_wiring.tools.route_harness_3d import route_harness_3d
        from kerf_wiring._compat import ProjectCtx
        ctx = ProjectCtx()
        raw = asyncio.get_event_loop().run_until_complete(
            route_harness_3d(ctx, json.dumps(args).encode())
        )
        return json.loads(raw)

    def test_basic_3point_path(self):
        result = self._call({
            "waypoints": [[0, 0, 0], [100, 0, 0], [100, 200, 0]],
            "wire_list": [{"gauge_awg": 20}, {"gauge_awg": 14}],
        })
        assert "bundle_diameter_mm" in result
        assert "length_mm" in result
        assert pytest.approx(result["length_mm"]) == 300.0
        assert result["bundle_diameter_mm"] > 0

    def test_returns_correct_segment_lengths(self):
        result = self._call({
            "waypoints": [[0, 0, 0], [10, 0, 0], [10, 0, 20]],
            "wire_list": [{"diameter_mm": 1.0}],
        })
        assert pytest.approx(result["segment_lengths_mm"][0]) == 10.0
        assert pytest.approx(result["segment_lengths_mm"][1]) == 20.0

    def test_bad_args_returns_err(self):
        result = self._call({"waypoints": [[0, 0, 0]], "wire_list": [{"gauge_awg": 20}]})
        assert result.get("code") == "BAD_ARGS"

    def test_empty_wire_list_returns_err(self):
        result = self._call({"waypoints": [[0, 0, 0], [1, 0, 0]], "wire_list": []})
        assert result.get("code") == "BAD_ARGS"

    def test_missing_waypoints_returns_err(self):
        result = self._call({"wire_list": [{"gauge_awg": 20}]})
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_json_returns_err(self):
        import asyncio
        from kerf_wiring.tools.route_harness_3d import route_harness_3d
        from kerf_wiring._compat import ProjectCtx
        ctx = ProjectCtx()
        raw = asyncio.get_event_loop().run_until_complete(
            route_harness_3d(ctx, b"not json")
        )
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_explicit_diameter_mm_in_tool(self):
        result = self._call({
            "waypoints": [[0, 0, 0], [50, 0, 0]],
            "wire_list": [{"name": "power", "diameter_mm": 3.0, "count": 2}],
        })
        assert "bundle_diameter_mm" in result
        # Verify against reference formula
        expected = _expected_bundle_diam([{"diameter_mm": 3.0, "count": 2}])
        assert pytest.approx(result["bundle_diameter_mm"], rel=1e-6) == expected
