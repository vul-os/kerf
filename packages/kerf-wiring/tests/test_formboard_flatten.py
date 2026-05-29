"""
tests/test_formboard_flatten.py — unit tests for formboard_flatten (T-37).

DoD:
- Trivial 3-wire trunk → flatten → 3 wires + total length matches 3D path length.
- Branched harness (trunk + 2 stubs) → branch points + correct stub lengths.
- Cycle in harness graph → raises FormboardError.
- LLM tool wrapper (wiring_formboard_flatten) round-trip.

All tests are hermetic (no DB, no network, no optional deps).
"""
from __future__ import annotations

import json
import math

import pytest

from kerf_wiring.formboard_flatten import (
    BranchPoint2D,
    Formboard2D,
    FormboardError,
    Wire2D,
    formboard_flatten,
    formboard_to_dict,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _simple_trunk_harness():
    """
    3-node linear harness:  A --200mm-- B --300mm-- C
    Three wires on the A→B segment, zero on B→C (tests the wires are counted
    per segment).
    """
    return {
        "nodes": [
            {"id": "A", "connector": "X1"},
            {"id": "B"},
            {"id": "C", "connector": "X2"},
        ],
        "segments": [
            {
                "from": "A", "to": "B", "length_mm": 200.0,
                "wires": [
                    {"name": "W1", "gauge_awg": 20, "color": "RD"},
                    {"name": "W2", "gauge_awg": 20, "color": "BK"},
                    {"name": "W3", "gauge_awg": 14, "color": "YE"},
                ],
            },
            {
                "from": "B", "to": "C", "length_mm": 300.0,
                "wires": [],
            },
        ],
        "root": "A",
    }


def _branched_harness():
    """
    Trunk:  A --100mm-- B --150mm-- C
    Stub 1: B --80mm-- D
    Stub 2: B --60mm-- E

    Longest path: A→B→C (total 250mm).
    """
    return {
        "nodes": [
            {"id": "A", "connector": "X1"},
            {"id": "B"},
            {"id": "C", "connector": "X2"},
            {"id": "D", "connector": "X3"},
            {"id": "E", "connector": "X4"},
        ],
        "segments": [
            {
                "from": "A", "to": "B", "length_mm": 100.0,
                "wires": [{"name": "WA", "gauge_awg": 20}],
            },
            {
                "from": "B", "to": "C", "length_mm": 150.0,
                "wires": [{"name": "WB", "gauge_awg": 20}],
            },
            {
                "from": "B", "to": "D", "length_mm": 80.0,
                "wires": [{"name": "WC", "gauge_awg": 20}],
            },
            {
                "from": "B", "to": "E", "length_mm": 60.0,
                "wires": [{"name": "WD", "gauge_awg": 20}],
            },
        ],
        "root": "A",
    }


def _cycle_harness():
    """
    Triangle A -- B -- C -- A (cycle).
    """
    return {
        "nodes": [
            {"id": "A"},
            {"id": "B"},
            {"id": "C"},
        ],
        "segments": [
            {"from": "A", "to": "B", "length_mm": 100.0, "wires": []},
            {"from": "B", "to": "C", "length_mm": 100.0, "wires": []},
            {"from": "C", "to": "A", "length_mm": 100.0, "wires": []},
        ],
        "root": "A",
    }


# ---------------------------------------------------------------------------
# Test: trivial 3-wire trunk harness
# ---------------------------------------------------------------------------

class TestSimpleTrunkHarness:
    """T-37 DoD: trivial trunk → 3 wires, total length matches 3D path."""

    def test_returns_formboard2d(self):
        fb = formboard_flatten(_simple_trunk_harness())
        assert isinstance(fb, Formboard2D)

    def test_three_wires_on_first_segment(self):
        """The first segment has 3 wires; second has 0."""
        fb = formboard_flatten(_simple_trunk_harness())
        assert len(fb.wires) == 3

    def test_wire_names(self):
        fb = formboard_flatten(_simple_trunk_harness())
        wire_ids = {w.wire_id for w in fb.wires}
        assert wire_ids == {"W1", "W2", "W3"}

    def test_wire_length_matches_segment(self):
        """All 3 wires are on the 200 mm segment."""
        fb = formboard_flatten(_simple_trunk_harness())
        for w in fb.wires:
            assert pytest.approx(w.length_mm, rel=1e-9) == 200.0

    def test_total_wire_length(self):
        """Total wire length = 3 wires × 200 mm = 600 mm."""
        fb = formboard_flatten(_simple_trunk_harness())
        assert pytest.approx(fb.total_wire_length_mm, rel=1e-9) == 600.0

    def test_trunk_path_has_correct_x_extent(self):
        """
        Trunk A→B→C: A at x=0, B at x=200, C at x=500.
        bbox max_x should be 500 mm.
        """
        fb = formboard_flatten(_simple_trunk_harness())
        min_x, min_y, max_x, max_y = fb.bbox
        assert pytest.approx(max_x, rel=1e-6) == 500.0
        assert pytest.approx(min_x, abs=1e-6) == 0.0

    def test_trunk_path_is_horizontal(self):
        """All trunk Y-coordinates are 0 (horizontal layout)."""
        fb = formboard_flatten(_simple_trunk_harness())
        for x, y in fb.trunk_path_mm:
            assert pytest.approx(y, abs=1e-9) == 0.0

    def test_trunk_path_length(self):
        """Trunk path should have 3 points (A, B, C)."""
        fb = formboard_flatten(_simple_trunk_harness())
        assert len(fb.trunk_path_mm) == 3

    def test_trunk_path_x_positions(self):
        """Trunk X positions: [0, 200, 500]."""
        fb = formboard_flatten(_simple_trunk_harness())
        xs = [p[0] for p in fb.trunk_path_mm]
        assert pytest.approx(xs[0], abs=1e-9) == 0.0
        assert pytest.approx(xs[1], abs=1e-9) == 200.0
        assert pytest.approx(xs[2], abs=1e-9) == 500.0

    def test_branch_points_count(self):
        """3 nodes → 3 branch points."""
        fb = formboard_flatten(_simple_trunk_harness())
        assert len(fb.branches) == 3

    def test_connector_annotations_present(self):
        """Nodes A and C have connectors → connector_pinout annotations."""
        fb = formboard_flatten(_simple_trunk_harness())
        pinout_refs = {a.ref for a in fb.annotations if a.kind == "connector_pinout"}
        assert "X1" in pinout_refs
        assert "X2" in pinout_refs

    def test_branch_tap_annotations_present(self):
        """All branch points generate branch_tap annotations."""
        fb = formboard_flatten(_simple_trunk_harness())
        tap_refs = {a.ref for a in fb.annotations if a.kind == "branch_tap"}
        assert len(tap_refs) == 3

    def test_bbox_is_non_degenerate(self):
        fb = formboard_flatten(_simple_trunk_harness())
        min_x, min_y, max_x, max_y = fb.bbox
        assert max_x > min_x


# ---------------------------------------------------------------------------
# Test: branched harness (T-37 DoD: branch points + stub lengths)
# ---------------------------------------------------------------------------

class TestBranchedHarness:
    """T-37 DoD: branched harness → branch points + correct stub lengths."""

    def test_returns_formboard2d(self):
        fb = formboard_flatten(_branched_harness())
        assert isinstance(fb, Formboard2D)

    def test_four_wires(self):
        """WA on A→B, WB on B→C, WC on B→D, WD on B→E."""
        fb = formboard_flatten(_branched_harness())
        assert len(fb.wires) == 4

    def test_wire_lengths_match_segments(self):
        """Wire lengths must match the segment lengths from the harness."""
        fb = formboard_flatten(_branched_harness())
        length_by_id = {w.wire_id: w.length_mm for w in fb.wires}
        assert pytest.approx(length_by_id["WA"], rel=1e-9) == 100.0
        assert pytest.approx(length_by_id["WB"], rel=1e-9) == 150.0
        assert pytest.approx(length_by_id["WC"], rel=1e-9) == 80.0
        assert pytest.approx(length_by_id["WD"], rel=1e-9) == 60.0

    def test_branch_points_include_tap(self):
        """Node B (the tap point) must appear in branches."""
        fb = formboard_flatten(_branched_harness())
        node_ids = {bp.node_id for bp in fb.branches}
        assert "B" in node_ids

    def test_all_nodes_have_branch_points(self):
        """Every node in the harness should appear in branch_points."""
        fb = formboard_flatten(_branched_harness())
        node_ids = {bp.node_id for bp in fb.branches}
        assert {"A", "B", "C", "D", "E"}.issubset(node_ids)

    def test_trunk_is_longest_path(self):
        """
        Longest path from A is A→B→C (250 mm).
        Trunk path must span nodes A, B, C.
        """
        fb = formboard_flatten(_branched_harness())
        # Trunk X positions: A=0, B=100, C=250
        assert pytest.approx(fb.trunk_path_mm[0][0], abs=1e-9) == 0.0
        assert pytest.approx(fb.trunk_path_mm[1][0], abs=1e-9) == 100.0
        assert pytest.approx(fb.trunk_path_mm[2][0], abs=1e-9) == 250.0

    def test_stubs_are_perpendicular(self):
        """
        Stub nodes D and E should be at X == 100 (tap X position),
        and non-zero Y.
        """
        fb = formboard_flatten(_branched_harness())
        pos_by_node = {bp.node_id: bp.position_mm for bp in fb.branches}
        # D and E stubs branch off at B (x=100)
        dx = pos_by_node["D"][0]
        dy = pos_by_node["D"][1]
        ex = pos_by_node["E"][0]
        ey = pos_by_node["E"][1]

        # X positions should stay at tap X = 100 for perpendicular stubs
        assert pytest.approx(dx, abs=1e-9) == 100.0
        assert pytest.approx(ex, abs=1e-9) == 100.0

        # Y should be non-zero (one above, one below)
        assert abs(dy) > 1e-9, "D stub should have non-zero Y"
        assert abs(ey) > 1e-9, "E stub should have non-zero Y"
        # They should be on opposite sides
        assert dy * ey < 0, "D and E stubs should be on opposite Y sides"

    def test_stub_lengths_preserved(self):
        """
        Distance from tap node B to stub tip D must equal 80 mm,
        and B to E must equal 60 mm.
        """
        fb = formboard_flatten(_branched_harness())
        pos_by_node = {bp.node_id: bp.position_mm for bp in fb.branches}
        bx, by = pos_by_node["B"]
        dx, dy = pos_by_node["D"]
        ex, ey = pos_by_node["E"]

        dist_D = math.sqrt((dx - bx) ** 2 + (dy - by) ** 2)
        dist_E = math.sqrt((ex - bx) ** 2 + (ey - by) ** 2)

        assert pytest.approx(dist_D, rel=1e-6) == 80.0
        assert pytest.approx(dist_E, rel=1e-6) == 60.0

    def test_total_wire_length(self):
        """Total: 100 + 150 + 80 + 60 = 390 mm."""
        fb = formboard_flatten(_branched_harness())
        assert pytest.approx(fb.total_wire_length_mm, rel=1e-9) == 390.0

    def test_bbox_includes_stubs(self):
        """Bounding box must include Y extent from stubs."""
        fb = formboard_flatten(_branched_harness())
        min_x, min_y, max_x, max_y = fb.bbox
        # Max_y or abs(min_y) must be at least 60 mm (shorter stub)
        y_extent = max_y - min_y
        assert y_extent > 10.0, "bbox Y extent should include stub heights"


# ---------------------------------------------------------------------------
# Test: cycle detection
# ---------------------------------------------------------------------------

class TestCycleDetection:
    """T-37 DoD: cycle in harness graph raises FormboardError."""

    def test_cycle_raises_formboard_error(self):
        with pytest.raises(FormboardError, match="cycle"):
            formboard_flatten(_cycle_harness())

    def test_error_message_mentions_node(self):
        """Error message should indicate which node triggered the cycle."""
        try:
            formboard_flatten(_cycle_harness())
        except FormboardError as exc:
            assert "cycle" in str(exc).lower()
        else:
            pytest.fail("FormboardError not raised")

    def test_two_path_graph_is_fine(self):
        """A→B and A→C (star) should NOT be a cycle."""
        h = {
            "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "segments": [
                {"from": "A", "to": "B", "length_mm": 50.0, "wires": []},
                {"from": "A", "to": "C", "length_mm": 75.0, "wires": []},
            ],
            "root": "A",
        }
        fb = formboard_flatten(h)  # Must not raise
        assert isinstance(fb, Formboard2D)


# ---------------------------------------------------------------------------
# Test: validation errors
# ---------------------------------------------------------------------------

class TestValidation:

    def test_missing_nodes_raises(self):
        with pytest.raises(FormboardError, match="node"):
            formboard_flatten({"nodes": [], "segments": [{"from": "A", "to": "B", "length_mm": 1}]})

    def test_missing_segments_raises(self):
        with pytest.raises(FormboardError):
            formboard_flatten({"nodes": [{"id": "A"}], "segments": []})

    def test_segment_unknown_from_node_raises(self):
        h = {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "segments": [{"from": "X", "to": "B", "length_mm": 10.0, "wires": []}],
        }
        with pytest.raises(FormboardError, match="'X'"):
            formboard_flatten(h)

    def test_segment_unknown_to_node_raises(self):
        h = {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "segments": [{"from": "A", "to": "Y", "length_mm": 10.0, "wires": []}],
        }
        with pytest.raises(FormboardError, match="'Y'"):
            formboard_flatten(h)

    def test_duplicate_segment_raises(self):
        h = {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "segments": [
                {"from": "A", "to": "B", "length_mm": 10.0, "wires": []},
                {"from": "A", "to": "B", "length_mm": 20.0, "wires": []},
            ],
        }
        with pytest.raises(FormboardError, match="duplicate"):
            formboard_flatten(h)

    def test_negative_length_raises(self):
        h = {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "segments": [{"from": "A", "to": "B", "length_mm": -5.0, "wires": []}],
        }
        with pytest.raises(FormboardError, match="negative"):
            formboard_flatten(h)

    def test_unknown_root_raises(self):
        h = {
            "nodes": [{"id": "A"}, {"id": "B"}],
            "segments": [{"from": "A", "to": "B", "length_mm": 10.0, "wires": []}],
            "root": "Z",
        }
        with pytest.raises(FormboardError, match="root"):
            formboard_flatten(h)


# ---------------------------------------------------------------------------
# Test: serialisation
# ---------------------------------------------------------------------------

class TestFormboardToDict:

    def test_json_serialisable(self):
        fb = formboard_flatten(_branched_harness())
        d = formboard_to_dict(fb)
        json.dumps(d)  # Must not raise

    def test_keys_present(self):
        fb = formboard_flatten(_branched_harness())
        d = formboard_to_dict(fb)
        assert set(d.keys()) == {
            "branches", "wires", "annotations", "bbox",
            "trunk_path_mm", "total_wire_length_mm",
        }

    def test_bbox_is_list_of_4(self):
        fb = formboard_flatten(_branched_harness())
        d = formboard_to_dict(fb)
        assert isinstance(d["bbox"], list)
        assert len(d["bbox"]) == 4

    def test_total_wire_length_matches(self):
        fb = formboard_flatten(_branched_harness())
        d = formboard_to_dict(fb)
        assert pytest.approx(d["total_wire_length_mm"]) == fb.total_wire_length_mm


# ---------------------------------------------------------------------------
# Test: LLM tool wrapper
# ---------------------------------------------------------------------------

class TestWiringFormboardFlattenTool:
    """End-to-end tests for the LLM-facing tool wrapper."""

    def _call(self, args: dict) -> dict:
        import asyncio
        from kerf_wiring.tools.wiring_formboard_flatten import wiring_formboard_flatten
        from kerf_wiring._compat import ProjectCtx
        ctx = ProjectCtx()
        loop = asyncio.new_event_loop()
        try:
            raw = loop.run_until_complete(
                wiring_formboard_flatten(ctx, json.dumps(args).encode())
            )
        finally:
            loop.close()
        return json.loads(raw)

    def test_basic_trunk(self):
        result = self._call({
            "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "segments": [
                {"from": "A", "to": "B", "length_mm": 100.0,
                 "wires": [{"name": "W1", "gauge_awg": 20}]},
                {"from": "B", "to": "C", "length_mm": 200.0,
                 "wires": [{"name": "W2", "gauge_awg": 20}]},
            ],
        })
        assert "wires" in result
        assert len(result["wires"]) == 2
        assert "branches" in result
        assert "bbox" in result

    def test_total_length_correct(self):
        """2 wires × 300mm total path → total_wire_length_mm = 300 (one wire per segment)."""
        result = self._call({
            "nodes": [{"id": "A"}, {"id": "B"}],
            "segments": [
                {"from": "A", "to": "B", "length_mm": 300.0,
                 "wires": [{"name": "X", "gauge_awg": 20}]},
            ],
        })
        assert pytest.approx(result["total_wire_length_mm"]) == 300.0

    def test_cycle_returns_error(self):
        result = self._call({
            "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "segments": [
                {"from": "A", "to": "B", "length_mm": 10.0, "wires": []},
                {"from": "B", "to": "C", "length_mm": 10.0, "wires": []},
                {"from": "C", "to": "A", "length_mm": 10.0, "wires": []},
            ],
        })
        assert result.get("code") == "FORMBOARD_ERROR"

    def test_missing_nodes_returns_error(self):
        result = self._call({
            "segments": [{"from": "A", "to": "B", "length_mm": 10.0, "wires": []}],
        })
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_json_returns_error(self):
        import asyncio
        from kerf_wiring.tools.wiring_formboard_flatten import wiring_formboard_flatten
        from kerf_wiring._compat import ProjectCtx
        ctx = ProjectCtx()
        loop = asyncio.new_event_loop()
        try:
            raw = loop.run_until_complete(
                wiring_formboard_flatten(ctx, b"not json {{")
            )
        finally:
            loop.close()
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_connector_annotations_in_result(self):
        """connectors dict should produce connector_pinout annotations."""
        result = self._call({
            "nodes": [
                {"id": "A", "connector": "X1"},
                {"id": "B", "connector": "X2"},
            ],
            "segments": [
                {"from": "A", "to": "B", "length_mm": 50.0, "wires": []},
            ],
            "connectors": {
                "X1": {"pins": ["1", "2"], "label": "ECU"},
                "X2": {"pins": ["A", "B", "C"], "label": "Sensor"},
            },
        })
        assert "annotations" in result
        pinout_anns = [a for a in result["annotations"] if a["kind"] == "connector_pinout"]
        pinout_refs = {a["ref"] for a in pinout_anns}
        assert "X1" in pinout_refs
        assert "X2" in pinout_refs

    def test_trunk_path_is_horizontal(self):
        """All trunk Y positions must be 0.0."""
        result = self._call({
            "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "segments": [
                {"from": "A", "to": "B", "length_mm": 100.0, "wires": []},
                {"from": "B", "to": "C", "length_mm": 200.0, "wires": []},
            ],
        })
        for x, y in result["trunk_path_mm"]:
            assert pytest.approx(y, abs=1e-9) == 0.0
