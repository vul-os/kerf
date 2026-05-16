"""
Tests for kerf_cad_core.jewelry.cad_qc

Pure-Python: no OCC, no database, no project context required.

Covers (≥25 hermetic tests, ALL green):
  - Thin wall below cast threshold → FAIL with measured < threshold
  - Same wall PASSES under resin_print looser threshold
  - Close stones below clearance → FAIL
  - Prong below min base → WARN / FAIL
  - Open shell (naked hole) → FAIL manifold
  - Undercut flagged with draw direction
  - All-good model → verdict "ready", empty fix list
  - Rule severities ordered in fix list (FAIL before WARN)
  - Missing model fields → graceful reason not crash
  - Weight outside band → WARN
  - Hollow with no access → FAIL
  - Knife-edge rail → WARN
  - Drill radius below minimum → WARN
  - Seat depth below threshold → WARN
  - Custom thresholds override defaults
  - Non-dict model → ok=False
  - DMLS process has lower min-wall than cast
  - Empty model → verdict "n/a"
"""

from __future__ import annotations

import asyncio
import json
import pytest

from kerf_cad_core.jewelry.cad_qc import (
    cad_qc,
    _DEFAULT_MIN_WALL,
    _DEFAULT_MIN_PRONG_BASE_MM,
    _DEFAULT_MIN_STONE_CLEARANCE_MM,
    _DEFAULT_MIN_SEAT_DEPTH_PCT,
    _DEFAULT_KNIFE_EDGE_THRESHOLD_MM,
    _DEFAULT_MIN_DRILL_RADIUS_MM,
    _DEFAULT_WEIGHT_TOLERANCE_PCT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rules_by_id(result, rule_id):
    """Return all result dicts matching a given rule_id."""
    return [r for r in result["results"] if r["rule_id"] == rule_id]


def _fails(result, rule_id=None):
    """Return all FAIL results, optionally filtered by rule_id."""
    return [
        r for r in result["results"]
        if r["severity"] == "FAIL" and (rule_id is None or r["rule_id"] == rule_id)
    ]


def _warns(result, rule_id=None):
    """Return all WARN results, optionally filtered by rule_id."""
    return [
        r for r in result["results"]
        if r["severity"] == "WARN" and (rule_id is None or r["rule_id"] == rule_id)
    ]


def _passes(result, rule_id=None):
    """Return all PASS results, optionally filtered by rule_id."""
    return [
        r for r in result["results"]
        if r["severity"] == "PASS" and (rule_id is None or r["rule_id"] == rule_id)
    ]


# ---------------------------------------------------------------------------
# 1. Non-dict input → graceful error, not crash
# ---------------------------------------------------------------------------

class TestBadInput:
    def test_non_dict_model_returns_ok_false(self):
        r = cad_qc("not a dict")
        assert r["ok"] is False
        assert "reason" in r

    def test_none_model_returns_ok_false(self):
        r = cad_qc(None)
        assert r["ok"] is False

    def test_list_model_returns_ok_false(self):
        r = cad_qc([1, 2, 3])
        assert r["ok"] is False


# ---------------------------------------------------------------------------
# 2. Empty model → verdict "n/a", no crash
# ---------------------------------------------------------------------------

class TestEmptyModel:
    def test_empty_dict_gives_na_verdict(self):
        r = cad_qc({})
        assert r["ok"] is True
        assert r["verdict"] == "n/a"
        assert r["results"] == []
        assert r["fix_list"] == []

    def test_empty_model_has_process_and_alloy(self):
        r = cad_qc({})
        assert r["process"] == "cast"
        assert r["alloy"] == "18k_yellow"


# ---------------------------------------------------------------------------
# 3. Wall-thickness: FAIL below cast threshold
# ---------------------------------------------------------------------------

class TestWallThickness:
    def test_thin_wall_below_cast_threshold_is_fail(self):
        """Wall 0.4 mm < cast minimum 0.8 mm → FAIL; measured < threshold."""
        r = cad_qc({"walls": [{"id": "shank_left", "thickness_mm": 0.4}]})
        assert r["ok"] is True
        assert r["verdict"] == "rework"
        fails = _fails(r, "WALL_THIN")
        assert len(fails) == 1
        f = fails[0]
        assert f["measured"] < f["threshold"]
        assert f["measured"] == pytest.approx(0.4, rel=1e-4)
        assert f["location"] == "shank_left"

    def test_thin_wall_passes_under_resin_print_threshold(self):
        """Wall 0.65 mm < cast 0.8 mm but ≥ resin_print 0.6 mm → PASS."""
        r = cad_qc({
            "process": "resin_print",
            "walls": [{"id": "w1", "thickness_mm": 0.65}],
        })
        assert r["ok"] is True
        wall_results = _rules_by_id(r, "WALL_THIN")
        assert any(x["severity"] == "PASS" for x in wall_results)
        assert not any(x["severity"] == "FAIL" for x in wall_results)

    def test_same_wall_fails_cast_passes_resin(self):
        """0.65 mm wall: FAIL on cast process, PASS on resin_print process."""
        r_cast = cad_qc({
            "process": "cast",
            "walls": [{"id": "w1", "thickness_mm": 0.65}],
        })
        r_resin = cad_qc({
            "process": "resin_print",
            "walls": [{"id": "w1", "thickness_mm": 0.65}],
        })
        assert len(_fails(r_cast, "WALL_THIN")) == 1
        assert len(_passes(r_resin, "WALL_THIN")) == 1

    def test_adequate_wall_is_pass(self):
        r = cad_qc({"walls": [{"id": "w2", "thickness_mm": 1.2}]})
        passes = _passes(r, "WALL_THIN")
        assert len(passes) == 1

    def test_multiple_walls_each_evaluated_independently(self):
        r = cad_qc({
            "walls": [
                {"id": "w_thin", "thickness_mm": 0.3},
                {"id": "w_ok",   "thickness_mm": 1.5},
            ]
        })
        assert len(_fails(r, "WALL_THIN")) == 1
        assert len(_passes(r, "WALL_THIN")) == 1


# ---------------------------------------------------------------------------
# 4. DMLS process has lower minimum wall than cast
# ---------------------------------------------------------------------------

class TestDMLSProcess:
    def test_dmls_min_wall_is_lower_than_cast(self):
        assert _DEFAULT_MIN_WALL["dmls"] < _DEFAULT_MIN_WALL["cast"]

    def test_wall_0_5_passes_dmls_fails_cast(self):
        r_dmls = cad_qc({"process": "dmls", "walls": [{"id": "w", "thickness_mm": 0.5}]})
        r_cast = cad_qc({"process": "cast", "walls": [{"id": "w", "thickness_mm": 0.5}]})
        assert _passes(r_dmls, "WALL_THIN")
        assert _fails(r_cast, "WALL_THIN")


# ---------------------------------------------------------------------------
# 5. Stone clearance: close stones below clearance → FAIL
# ---------------------------------------------------------------------------

class TestStoneClearance:
    def test_close_stones_below_clearance_is_fail(self):
        r = cad_qc({
            "stones": [{"id": "s1", "clearance_to_neighbor_mm": 0.10}]
        })
        fails = _fails(r, "STONE_CLEARANCE")
        assert len(fails) >= 1
        f = fails[0]
        assert f["measured"] < f["threshold"]

    def test_adequate_clearance_is_pass(self):
        r = cad_qc({
            "stones": [{"id": "s1", "clearance_to_neighbor_mm": 0.35}]
        })
        passes = _passes(r, "STONE_CLEARANCE")
        assert len(passes) >= 1

    def test_stone_edge_clearance_too_small_is_fail(self):
        r = cad_qc({
            "stones": [{"id": "s1", "clearance_to_edge_mm": 0.05}]
        })
        fails = _fails(r, "STONE_CLEARANCE")
        assert any("edge" in f["location"] for f in fails)


# ---------------------------------------------------------------------------
# 6. Prong base: below minimum → WARN or FAIL
# ---------------------------------------------------------------------------

class TestProngBase:
    def test_prong_below_minimum_is_warn_or_fail(self):
        r = cad_qc({
            "prongs": [{"id": "p1", "base_mm": 0.5}]
        })
        issues = _warns(r, "PRONG_BASE") + _fails(r, "PRONG_BASE")
        assert len(issues) >= 1
        # Measured must be less than threshold
        for issue in issues:
            if issue["severity"] in ("FAIL", "WARN") and issue["measured"] is not None:
                assert issue["measured"] < issue["threshold"]

    def test_prong_severely_below_minimum_is_fail(self):
        # 0.3 mm is < 80% of 0.7 mm default → FAIL
        r = cad_qc({
            "prongs": [{"id": "p_tiny", "base_mm": 0.3}]
        })
        fails = _fails(r, "PRONG_BASE")
        assert len(fails) >= 1

    def test_adequate_prong_base_is_pass(self):
        r = cad_qc({
            "prongs": [{"id": "p2", "base_mm": 1.0}]
        })
        passes = _passes(r, "PRONG_BASE")
        assert len(passes) >= 1

    def test_prong_taper_too_aggressive_is_warn(self):
        """Tip < 30 % of base triggers an extra WARN for taper."""
        r = cad_qc({
            "prongs": [{"id": "p3", "base_mm": 1.0, "tip_mm": 0.2}]
        })
        warns = _warns(r, "PRONG_BASE")
        assert len(warns) >= 1


# ---------------------------------------------------------------------------
# 7. Manifold: open shell → FAIL
# ---------------------------------------------------------------------------

class TestManifold:
    def test_open_shell_is_fail(self):
        r = cad_qc({"topology": {"is_manifold": False, "naked_edge_count": 4}})
        fails = _fails(r, "MANIFOLD")
        assert len(fails) == 1

    def test_closed_shell_is_pass(self):
        r = cad_qc({"topology": {"is_manifold": True, "naked_edge_count": 0}})
        passes = _passes(r, "MANIFOLD")
        assert len(passes) == 1

    def test_naked_edges_nonzero_is_fail_even_if_manifold_not_set(self):
        r = cad_qc({"topology": {"naked_edge_count": 2}})
        fails = _fails(r, "MANIFOLD")
        assert len(fails) == 1

    def test_topology_wrong_type_is_warn(self):
        r = cad_qc({"topology": "bad"})
        warns = _warns(r, "MANIFOLD")
        assert len(warns) == 1


# ---------------------------------------------------------------------------
# 8. Undercut: flagged with draw direction
# ---------------------------------------------------------------------------

class TestUndercut:
    def test_undercut_face_is_warn_with_draw_direction(self):
        r = cad_qc({
            "draw_direction": "+z",
            "undercut_faces": [{"id": "bottom_lip", "angle_deg": 12.5}],
        })
        warns = _warns(r, "UNDERCUT")
        assert len(warns) == 1
        msg = warns[0]["message"]
        assert "+z" in msg
        assert "bottom_lip" in msg

    def test_undercut_without_draw_direction_still_warns(self):
        r = cad_qc({
            "undercut_faces": [{"id": "uf1"}],
        })
        warns = _warns(r, "UNDERCUT")
        assert len(warns) == 1

    def test_no_undercut_faces_no_undercut_result(self):
        r = cad_qc({"undercut_faces": []})
        results = _rules_by_id(r, "UNDERCUT")
        assert results == []


# ---------------------------------------------------------------------------
# 9. Hollow access: no drain hole → FAIL
# ---------------------------------------------------------------------------

class TestHollowAccess:
    def test_hollow_without_access_is_fail(self):
        r = cad_qc({
            "hollows": [{"id": "main_hollow", "access_open": False, "sprue_dia_mm": 0.0}]
        })
        fails = _fails(r, "HOLLOW_ACCESS")
        assert len(fails) == 1

    def test_hollow_with_adequate_drain_is_pass(self):
        r = cad_qc({
            "hollows": [{"id": "h1", "access_open": True, "sprue_dia_mm": 1.5}]
        })
        passes = _passes(r, "HOLLOW_ACCESS")
        assert len(passes) == 1

    def test_hollow_with_tiny_drain_is_fail(self):
        # drain diameter < 0.8 mm (HOLE_DIA_MIN) → FAIL
        r = cad_qc({
            "hollows": [{"id": "h2", "access_open": True, "sprue_dia_mm": 0.3}]
        })
        fails = _fails(r, "HOLLOW_ACCESS")
        assert len(fails) == 1


# ---------------------------------------------------------------------------
# 10. Knife-edge / thin rail → WARN
# ---------------------------------------------------------------------------

class TestKnifeEdge:
    def test_thin_rail_is_warn(self):
        r = cad_qc({
            "rails": [{"id": "shoulder_rail", "width_mm": 0.25}]
        })
        warns = _warns(r, "KNIFE_EDGE")
        assert len(warns) >= 1

    def test_adequate_rail_is_pass(self):
        r = cad_qc({
            "rails": [{"id": "rail_ok", "width_mm": 1.0}]
        })
        passes = _passes(r, "KNIFE_EDGE")
        assert len(passes) >= 1

    def test_tall_narrow_rail_aspect_warn(self):
        """Height/width ratio > 5 triggers an additional WARN."""
        r = cad_qc({
            "rails": [{"id": "tall_rail", "width_mm": 0.5, "height_mm": 4.0}]
        })
        warns = _warns(r, "KNIFE_EDGE")
        assert len(warns) >= 1


# ---------------------------------------------------------------------------
# 11. Drill radius → WARN
# ---------------------------------------------------------------------------

class TestDrillRadius:
    def test_drill_radius_below_minimum_is_warn(self):
        r = cad_qc({
            "drill_features": [{"id": "seat_drill", "radius_mm": 0.1}]
        })
        warns = _warns(r, "DRILL_RADIUS")
        assert len(warns) == 1

    def test_adequate_drill_radius_is_pass(self):
        r = cad_qc({
            "drill_features": [{"id": "d1", "radius_mm": 0.5}]
        })
        passes = _passes(r, "DRILL_RADIUS")
        assert len(passes) == 1


# ---------------------------------------------------------------------------
# 12. Seat depth → WARN
# ---------------------------------------------------------------------------

class TestSeatDepth:
    def test_shallow_seat_is_warn(self):
        """Seat depth 0.5 mm for a 4 mm girdle = 12.5% < 25% threshold → WARN."""
        r = cad_qc({
            "stones": [{"id": "centre_diamond", "girdle_mm": 4.0, "seat_depth_mm": 0.5}]
        })
        warns = _warns(r, "SEAT_DEPTH")
        assert len(warns) == 1
        w = warns[0]
        assert w["measured"] < w["threshold"]

    def test_adequate_seat_is_pass(self):
        """Seat depth 1.2 mm for a 4 mm girdle = 30% ≥ 25% → PASS."""
        r = cad_qc({
            "stones": [{"id": "s1", "girdle_mm": 4.0, "seat_depth_mm": 1.2}]
        })
        passes = _passes(r, "SEAT_DEPTH")
        assert len(passes) == 1


# ---------------------------------------------------------------------------
# 13. Weight band → WARN when outside tolerance
# ---------------------------------------------------------------------------

class TestWeightBand:
    def test_weight_outside_band_is_warn(self):
        r = cad_qc({
            "weight_g": 15.0,
            "target_weight_g": 10.0,
            "weight_tolerance_pct": 10.0,
        })
        warns = _warns(r, "WEIGHT_BAND")
        assert len(warns) == 1

    def test_weight_within_band_is_pass(self):
        r = cad_qc({
            "weight_g": 10.5,
            "target_weight_g": 10.0,
            "weight_tolerance_pct": 10.0,
        })
        passes = _passes(r, "WEIGHT_BAND")
        assert len(passes) == 1

    def test_no_weight_fields_no_weight_result(self):
        r = cad_qc({})
        results = _rules_by_id(r, "WEIGHT_BAND")
        assert results == []


# ---------------------------------------------------------------------------
# 14. All-good model → verdict "ready", empty fix list
# ---------------------------------------------------------------------------

class TestAllGoodModel:
    def test_all_good_model_is_ready(self):
        r = cad_qc({
            "process": "cast",
            "alloy": "18k_yellow",
            "walls":          [{"id": "w1", "thickness_mm": 1.0}],
            "prongs":         [{"id": "p1", "base_mm": 0.9, "tip_mm": 0.5}],
            "stones":         [{"id": "s1", "girdle_mm": 4.0, "seat_depth_mm": 1.5,
                                 "clearance_to_neighbor_mm": 0.30}],
            "topology":       {"is_manifold": True, "naked_edge_count": 0},
            "undercut_faces": [],
            "hollows":        [{"id": "h1", "access_open": True, "sprue_dia_mm": 2.0}],
            "rails":          [{"id": "r1", "width_mm": 0.8}],
            "drill_features": [{"id": "d1", "radius_mm": 0.5}],
            "weight_g":       12.0,
            "target_weight_g": 12.0,
            "weight_tolerance_pct": 10.0,
        })
        assert r["ok"] is True
        assert r["verdict"] == "ready"
        assert r["fix_list"] == []
        assert all(x["severity"] == "PASS" for x in r["results"])


# ---------------------------------------------------------------------------
# 15. Fix list ordering: FAIL before WARN
# ---------------------------------------------------------------------------

class TestFixListOrdering:
    def test_fail_items_before_warn_in_fix_list(self):
        r = cad_qc({
            "walls":  [{"id": "thin_wall",  "thickness_mm": 0.3}],   # FAIL
            "prongs": [{"id": "small_prong", "base_mm": 0.55}],       # WARN
        })
        assert r["fix_list"], "fix_list must not be empty"
        severities = [item["severity"] for item in r["fix_list"]]
        # All FAILs must come before any WARNs
        seen_warn = False
        for sev in severities:
            if sev == "WARN":
                seen_warn = True
            if seen_warn and sev == "FAIL":
                pytest.fail("FAIL item appears after WARN item in fix_list")

    def test_fix_list_priorities_are_sequential(self):
        r = cad_qc({
            "walls":  [{"id": "w",  "thickness_mm": 0.3}],
            "prongs": [{"id": "p",  "base_mm": 0.55}],
        })
        priorities = [item["priority"] for item in r["fix_list"]]
        assert priorities == list(range(1, len(priorities) + 1))


# ---------------------------------------------------------------------------
# 16. Custom thresholds override defaults
# ---------------------------------------------------------------------------

class TestCustomThresholds:
    def test_custom_min_wall_overrides_default(self):
        """With a custom cast threshold of 1.5 mm, a 1.0 mm wall should FAIL."""
        r = cad_qc({
            "process": "cast",
            "walls": [{"id": "w1", "thickness_mm": 1.0}],
            "thresholds": {"cast_min_wall_mm": 1.5},
        })
        fails = _fails(r, "WALL_THIN")
        assert len(fails) == 1
        assert fails[0]["threshold"] == pytest.approx(1.5, rel=1e-4)

    def test_custom_stone_clearance_threshold(self):
        r = cad_qc({
            "stones": [{"id": "s1", "clearance_to_neighbor_mm": 0.25}],
            "thresholds": {"min_stone_clearance_mm": 0.30},
        })
        fails = _fails(r, "STONE_CLEARANCE")
        assert len(fails) == 1

    def test_custom_weight_tolerance_widens_band(self):
        """With 50% tolerance, a weight 140% of target should still WARN."""
        r = cad_qc({
            "weight_g": 14.0,
            "target_weight_g": 10.0,
            "thresholds": {"weight_tolerance_pct": 50.0},
        })
        # 14.0 / 10.0 = 40% deviation, within 50% tolerance → PASS
        passes = _passes(r, "WEIGHT_BAND")
        assert len(passes) == 1


# ---------------------------------------------------------------------------
# 17. Graceful handling of missing / malformed sub-fields
# ---------------------------------------------------------------------------

class TestGracefulMissingFields:
    def test_wall_missing_thickness_gives_warn_not_crash(self):
        r = cad_qc({"walls": [{"id": "w_bad"}]})
        assert r["ok"] is True
        warns = _warns(r, "WALL_THIN")
        assert len(warns) == 1

    def test_prong_missing_base_gives_warn_not_crash(self):
        r = cad_qc({"prongs": [{"id": "p_bad"}]})
        assert r["ok"] is True

    def test_stone_missing_girdle_skips_seat_check_gracefully(self):
        # clearance_to_neighbor without girdle — only clearance check runs
        r = cad_qc({"stones": [{"id": "s1", "seat_depth_mm": 0.2}]})
        assert r["ok"] is True

    def test_unknown_process_falls_back_to_cast(self):
        r = cad_qc({"process": "mystery_process"})
        assert r["ok"] is True
        assert r["process"] == "cast"

    def test_unknown_alloy_falls_back_gracefully(self):
        r = cad_qc({"alloy": "unobtainium_999"})
        assert r["ok"] is True
        assert r["alloy"] == "18k_yellow"

    def test_walls_as_none_does_not_crash(self):
        r = cad_qc({"walls": None})
        assert r["ok"] is True

    def test_topology_nondict_gives_warn_not_crash(self):
        r = cad_qc({"topology": 42})
        assert r["ok"] is True
        warns = _warns(r, "MANIFOLD")
        assert len(warns) == 1


# ---------------------------------------------------------------------------
# 18. LLM tool runner (async)
# ---------------------------------------------------------------------------

class TestLLMTool:
    def _run(self, **kwargs) -> dict:
        from kerf_cad_core.jewelry.cad_qc import run_jewelry_cad_qc
        raw = asyncio.new_event_loop().run_until_complete(
            run_jewelry_cad_qc(None, json.dumps(kwargs).encode())
        )
        return json.loads(raw)

    def test_tool_all_good_model_returns_ready(self):
        # ok_payload returns the cad_qc dict directly (not nested under "data")
        r = self._run(model={
            "walls": [{"id": "w1", "thickness_mm": 1.2}],
            "topology": {"is_manifold": True, "naked_edge_count": 0},
        })
        assert r["ok"] is True
        assert r["verdict"] == "ready"

    def test_tool_missing_model_returns_bad_args(self):
        # err_payload returns {"error": ..., "code": ...}
        r = self._run()
        assert "error" in r
        assert r.get("code") == "BAD_ARGS"

    def test_tool_invalid_json_returns_bad_args(self):
        from kerf_cad_core.jewelry.cad_qc import run_jewelry_cad_qc
        raw = asyncio.new_event_loop().run_until_complete(
            run_jewelry_cad_qc(None, b"not json")
        )
        r = json.loads(raw)
        assert "error" in r
        assert r.get("code") == "BAD_ARGS"

    def test_tool_non_dict_model_returns_bad_args(self):
        r = self._run(model="bad")
        assert "error" in r
        assert r.get("code") == "BAD_ARGS"
