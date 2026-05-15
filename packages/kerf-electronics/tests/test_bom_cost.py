"""
Tests for BOM cost rollup, DFM report, and sourcing risk tools.

Covers (≥30 hermetic tests):
  - Extended cost arithmetic
  - Price-break selection at quantity thresholds
  - NRE amortisation per board
  - DNP exclusion from cost (line-level flag + dnp_list argument)
  - IPC class 2 vs class 3 annular-ring thresholds
  - Each DFM rule fires on a crafted failing case and passes on a clean case
  - Sourcing-risk flags: single-source, no-price, long-lead
  - Empty BOM → friendly error (not exception)
  - Tool-level LLM JSON roundtrip (bom_cost_rollup, bom_dfm_report, bom_sourcing_risk)

All tests are hermetic (no network, no filesystem side-effects).

Author: imranparuk
"""

from __future__ import annotations

import json
import unittest

# Trigger @register decorators
import kerf_electronics.tools.bom_cost  # noqa: F401

from kerf_electronics.tools.bom_cost import (
    _select_price,
    _compute_cost_rollup,
)
from kerf_electronics.dfm.rules import (
    run_dfm_checks,
    score_dfm,
    DFMFinding,
    _check_annular_ring,
    _check_min_trace_space,
    _check_drill_to_copper,
    _check_silkscreen_over_pad,
    _check_acid_traps,
    _check_slivers,
    _check_courtyard_overlap,
    _check_smallest_passive,
    _IPC_THRESHOLDS,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _call(tool_name: str, args: dict) -> dict:
    """Call a registered tool by name and parse the JSON response."""
    from kerf_chat.tools.registry import Registry
    for tool in Registry:
        if tool.spec.name == tool_name:
            raw = await tool.run(None, json.dumps(args).encode())
            return json.loads(raw)
    raise KeyError(f"tool {tool_name!r} not found in Registry")


def _run(coro):
    """Run an async coroutine synchronously."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

SIMPLE_BOM = [
    {"refdes": "R1,R2", "qty": 2, "unit_price": 0.10},
    {"refdes": "U1",    "qty": 1, "unit_price": 2.50},
]

PRICE_BREAK_LINE = {
    "refdes": "C1",
    "qty": 1,
    "price_breaks": [
        {"min_qty": 1,    "unit_price": 0.50},
        {"min_qty": 100,  "unit_price": 0.30},
        {"min_qty": 1000, "unit_price": 0.15},
    ],
}

THREE_COMPONENT_CIRCUIT = [
    {"type": "pcb_board", "width": 100.0, "height": 80.0},
    {"type": "source_component", "source_component_id": "sc_r1",
     "name": "R1", "value": "10k", "footprint": "R_0402"},
    {"type": "source_component", "source_component_id": "sc_u1",
     "name": "U1", "value": "ATmega328P", "footprint": "TQFP-32"},
    {"type": "pcb_component", "source_component_id": "sc_r1",
     "x": 10.0, "y": 10.0},
    {"type": "pcb_component", "source_component_id": "sc_u1",
     "x": 50.0, "y": 40.0},
]


# ─── 1. Price-break selection ─────────────────────────────────────────────────

class TestSelectPrice(unittest.TestCase):

    def test_flat_price_no_breaks(self):
        self.assertAlmostEqual(_select_price(0.10, [], 1), 0.10)

    def test_price_break_selects_tier_100(self):
        breaks = [
            {"min_qty": 1,   "unit_price": 0.50},
            {"min_qty": 100, "unit_price": 0.30},
        ]
        self.assertAlmostEqual(_select_price(None, breaks, 100), 0.30)

    def test_price_break_below_threshold_stays_tier1(self):
        breaks = [
            {"min_qty": 1,   "unit_price": 0.50},
            {"min_qty": 100, "unit_price": 0.30},
        ]
        # qty=99 → still at tier-1 price
        self.assertAlmostEqual(_select_price(None, breaks, 99), 0.50)

    def test_price_break_selects_highest_applicable_tier(self):
        breaks = [
            {"min_qty": 1,    "unit_price": 0.50},
            {"min_qty": 100,  "unit_price": 0.30},
            {"min_qty": 1000, "unit_price": 0.15},
        ]
        # qty=500 → second tier
        self.assertAlmostEqual(_select_price(None, breaks, 500), 0.30)
        # qty=1000 → third tier
        self.assertAlmostEqual(_select_price(None, breaks, 1000), 0.15)

    def test_no_price_returns_none(self):
        self.assertIsNone(_select_price(None, [], 10))

    def test_flat_price_preferred_when_no_breaks_apply(self):
        breaks = [{"min_qty": 100, "unit_price": 0.30}]
        # qty=5 → no break applies; falls back to flat
        self.assertAlmostEqual(_select_price(0.50, breaks, 5), 0.50)


# ─── 2. Cost rollup arithmetic ────────────────────────────────────────────────

class TestCostRollup(unittest.TestCase):

    def test_simple_extended_cost(self):
        result = _compute_cost_rollup(SIMPLE_BOM, board_qty=1, assembly_qty=1,
                                      nre_usd=0.0, dnp_list=[])
        # R1+R2: 2 qty × 0.10 = 0.20; U1: 1 × 2.50 = 2.50 → 2.70
        self.assertAlmostEqual(result["subtotal_parts_usd"], 2.70, places=4)

    def test_extended_cost_scales_with_assembly_qty(self):
        result = _compute_cost_rollup(SIMPLE_BOM, board_qty=100, assembly_qty=100,
                                      nre_usd=0.0, dnp_list=[])
        # Per board: 2*0.10 + 2.50 = 2.70; × 100 = 270.0
        self.assertAlmostEqual(result["subtotal_parts_usd"], 270.0, places=2)

    def test_nre_added_to_total(self):
        result = _compute_cost_rollup(SIMPLE_BOM, board_qty=1, assembly_qty=1,
                                      nre_usd=50.0, dnp_list=[])
        self.assertAlmostEqual(result["total_usd"], 2.70 + 50.0, places=2)

    def test_nre_amortised_per_board(self):
        result = _compute_cost_rollup(SIMPLE_BOM, board_qty=10, assembly_qty=10,
                                      nre_usd=100.0, dnp_list=[])
        # parts total: 2.70 × 10 = 27.0 + NRE 100.0 = 127.0; per board = 12.7
        self.assertAlmostEqual(result["per_board_usd"], 12.70, places=2)

    def test_dnp_flag_on_line_excludes_from_cost(self):
        bom = [
            {"refdes": "R1", "qty": 1, "unit_price": 0.10},
            {"refdes": "R2", "qty": 1, "unit_price": 0.10, "dnp": True},
        ]
        result = _compute_cost_rollup(bom, board_qty=1, assembly_qty=1,
                                      nre_usd=0.0, dnp_list=[])
        # Only R1 contributes
        self.assertAlmostEqual(result["subtotal_parts_usd"], 0.10, places=4)
        self.assertIn("R2", result["dnp_lines"])

    def test_dnp_list_arg_excludes_from_cost(self):
        bom = [
            {"refdes": "R1", "qty": 1, "unit_price": 0.10},
            {"refdes": "R2", "qty": 1, "unit_price": 0.10},
        ]
        result = _compute_cost_rollup(bom, board_qty=1, assembly_qty=1,
                                      nre_usd=0.0, dnp_list=["R2"])
        self.assertAlmostEqual(result["subtotal_parts_usd"], 0.10, places=4)
        self.assertIn("R2", result["dnp_lines"])

    def test_missing_price_line_reported(self):
        bom = [
            {"refdes": "R1", "qty": 1, "unit_price": 0.10},
            {"refdes": "U1", "qty": 1},  # no price
        ]
        result = _compute_cost_rollup(bom, board_qty=1, assembly_qty=1,
                                      nre_usd=0.0, dnp_list=[])
        self.assertIn("U1", result["missing_price_lines"])

    def test_price_break_selected_at_assembly_qty(self):
        bom = [PRICE_BREAK_LINE]
        result = _compute_cost_rollup(bom, board_qty=100, assembly_qty=100,
                                      nre_usd=0.0, dnp_list=[])
        # At qty=100×1=100 → tier 0.30
        self.assertAlmostEqual(result["subtotal_parts_usd"], 100 * 0.30, places=2)

    def test_price_break_tier1_below_threshold(self):
        bom = [PRICE_BREAK_LINE]
        result = _compute_cost_rollup(bom, board_qty=10, assembly_qty=10,
                                      nre_usd=0.0, dnp_list=[])
        # At qty=10×1=10 < 100 → tier 0.50
        self.assertAlmostEqual(result["subtotal_parts_usd"], 10 * 0.50, places=2)

    def test_per_board_zero_assembly_qty_safe(self):
        # assembly_qty=0 would be rejected upstream; but rollup itself handles it gracefully
        result = _compute_cost_rollup(SIMPLE_BOM, board_qty=0, assembly_qty=0,
                                      nre_usd=0.0, dnp_list=[])
        # subtotal is 0 (no boards), per_board is 0.0
        self.assertEqual(result["per_board_usd"], 0.0)


# ─── 3. Tool-level tests (JSON roundtrip) ─────────────────────────────────────

class TestBomCostRollupTool(unittest.TestCase):

    def test_basic_rollup_ok(self):
        resp = _run(_call("bom_cost_rollup", {
            "bom_lines": SIMPLE_BOM,
            "board_qty": 1,
            "assembly_qty": 1,
        }))
        self.assertTrue(resp.get("ok"))
        self.assertAlmostEqual(resp["subtotal_parts_usd"], 2.70, places=2)

    def test_empty_bom_returns_error(self):
        resp = _run(_call("bom_cost_rollup", {"bom_lines": []}))
        self.assertIn("error", resp)
        self.assertEqual(resp["code"], "EMPTY_BOM")

    def test_invalid_bom_lines_type(self):
        resp = _run(_call("bom_cost_rollup", {"bom_lines": "not_a_list"}))
        self.assertIn("error", resp)
        self.assertEqual(resp["code"], "BAD_ARGS")

    def test_nre_field_in_output(self):
        resp = _run(_call("bom_cost_rollup", {
            "bom_lines": SIMPLE_BOM,
            "board_qty": 1,
            "assembly_qty": 1,
            "nre_usd": 50.0,
        }))
        self.assertTrue(resp.get("ok"))
        self.assertAlmostEqual(resp["nre_usd"], 50.0, places=2)

    def test_dnp_list_in_tool_call(self):
        bom = [
            {"refdes": "R1", "qty": 1, "unit_price": 0.10},
            {"refdes": "R2", "qty": 1, "unit_price": 0.10},
        ]
        resp = _run(_call("bom_cost_rollup", {
            "bom_lines": bom,
            "board_qty": 1,
            "assembly_qty": 1,
            "dnp_list": ["R2"],
        }))
        self.assertTrue(resp.get("ok"))
        self.assertIn("R2", resp["dnp_lines"])
        self.assertAlmostEqual(resp["subtotal_parts_usd"], 0.10, places=4)


# ─── 4. DFM rules — individual rule tests ─────────────────────────────────────

class TestAnnularRing(unittest.TestCase):

    def _t(self, cls):
        return _IPC_THRESHOLDS[cls]

    def test_via_annular_ring_fail_class2(self):
        """Via with ring < 0.050 mm fails class 2."""
        via = {"type": "pcb_via", "x": 10.0, "y": 10.0,
               "outer_diameter": 0.4, "hole_diameter": 0.36}  # ring = 0.020 mm
        findings = _check_annular_ring([via], [], self._t(2))
        self.assertTrue(any(f.rule == "annular_ring_via" for f in findings))

    def test_via_annular_ring_pass_class2(self):
        """Via with ring = 0.10 mm passes class 2."""
        via = {"type": "pcb_via", "x": 10.0, "y": 10.0,
               "outer_diameter": 0.6, "hole_diameter": 0.3}  # ring = 0.150 mm
        findings = _check_annular_ring([via], [], self._t(2))
        self.assertFalse(any(f.rule == "annular_ring_via" for f in findings))

    def test_via_annular_ring_fail_class3_stricter(self):
        """Ring of 0.060 mm passes class 2 (min 0.050) but fails class 3 (min 0.075)."""
        via = {"type": "pcb_via", "x": 10.0, "y": 10.0,
               "outer_diameter": 0.42, "hole_diameter": 0.30}  # ring = 0.060 mm
        finds_cls2 = _check_annular_ring([via], [], self._t(2))
        finds_cls3 = _check_annular_ring([via], [], self._t(3))
        self.assertFalse(any(f.rule == "annular_ring_via" for f in finds_cls2))
        self.assertTrue(any(f.rule == "annular_ring_via" for f in finds_cls3))

    def test_pth_pad_annular_ring_fail(self):
        """PTH pad with tiny ring fails."""
        pad = {"type": "pcb_plated_hole", "x": 5.0, "y": 5.0,
               "width": 1.2, "hole_diameter": 1.18}  # ring = 0.010 mm
        findings = _check_annular_ring([], [pad], self._t(2))
        self.assertTrue(any(f.rule == "annular_ring_pth" for f in findings))


class TestTraceSpace(unittest.TestCase):

    def _t(self, cls):
        return _IPC_THRESHOLDS[cls]

    def test_thin_trace_fails(self):
        trace = {"type": "pcb_trace", "route_thickness_mm": 0.05,
                 "route": [{"x": 0, "y": 0}, {"x": 10, "y": 0}]}
        findings = _check_min_trace_space([trace], self._t(2))
        self.assertTrue(any(f.rule == "min_trace_width" for f in findings))

    def test_nominal_trace_passes(self):
        trace = {"type": "pcb_trace", "route_thickness_mm": 0.20,
                 "route": [{"x": 0, "y": 0}, {"x": 10, "y": 0}]}
        findings = _check_min_trace_space([trace], self._t(2))
        self.assertFalse(any(f.rule == "min_trace_width" for f in findings))

    def test_close_traces_flag_space(self):
        t1 = {"type": "pcb_trace", "route_thickness_mm": 0.15,
              "route": [{"x": 0, "y": 0}, {"x": 5, "y": 0}]}
        # second trace starts 0.05 mm from end of first (gap < 0.10 mm min_space)
        t2 = {"type": "pcb_trace", "route_thickness_mm": 0.15,
              "route": [{"x": 0.10, "y": 0}, {"x": 5.10, "y": 0}]}
        findings = _check_min_trace_space([t1, t2], self._t(2))
        self.assertTrue(any(f.rule == "min_trace_space" for f in findings))


class TestDrillToCopper(unittest.TestCase):

    def _t(self, cls):
        return _IPC_THRESHOLDS[cls]

    def test_drill_to_copper_fail(self):
        v1 = {"type": "pcb_via", "x": 0.0, "y": 0.0,
               "hole_diameter": 0.3, "outer_diameter": 0.6}
        v2 = {"type": "pcb_via", "x": 0.4, "y": 0.0,
               "hole_diameter": 0.3, "outer_diameter": 0.6}
        # drill edge of v1 to copper edge of v2: 0.4 - 0.15 - 0.30 = -0.05 → fail
        findings = _check_drill_to_copper([v1, v2], [], self._t(2))
        self.assertTrue(any(f.rule == "drill_to_copper" for f in findings))

    def test_drill_to_copper_pass(self):
        v1 = {"type": "pcb_via", "x": 0.0, "y": 0.0,
               "hole_diameter": 0.3, "outer_diameter": 0.6}
        v2 = {"type": "pcb_via", "x": 2.0, "y": 0.0,
               "hole_diameter": 0.3, "outer_diameter": 0.6}
        findings = _check_drill_to_copper([v1, v2], [], self._t(2))
        self.assertFalse(any(f.rule == "drill_to_copper" for f in findings))


class TestSilkscreenOverPad(unittest.TestCase):

    def _t(self, cls):
        return _IPC_THRESHOLDS[cls]

    def test_silk_on_pad_flagged(self):
        silk = {"type": "pcb_silkscreen_text", "x": 10.0, "y": 10.0}
        pad = {"type": "pcb_smtpad", "x": 10.0, "y": 10.0, "width": 2.0}
        findings = _check_silkscreen_over_pad([silk], [pad], self._t(2))
        self.assertTrue(any(f.rule == "silkscreen_over_pad" for f in findings))

    def test_silk_off_pad_clean(self):
        silk = {"type": "pcb_silkscreen_text", "x": 0.0, "y": 0.0}
        pad = {"type": "pcb_smtpad", "x": 50.0, "y": 50.0, "width": 2.0}
        findings = _check_silkscreen_over_pad([silk], [pad], self._t(2))
        self.assertFalse(any(f.rule == "silkscreen_over_pad" for f in findings))


class TestAcidTraps(unittest.TestCase):

    def test_acute_corner_flagged(self):
        # Trace that turns 30° — an acid trap
        trace = {
            "type": "pcb_trace",
            "route": [
                {"x": 0.0, "y": 0.0},
                {"x": 5.0, "y": 0.0},
                {"x": 5.5, "y": 0.1},  # ~11° turn — acute enough
            ]
        }
        findings = _check_acid_traps([trace])
        self.assertTrue(any(f.rule == "acid_trap" for f in findings))

    def test_right_angle_not_flagged(self):
        # 90° corner is NOT an acid trap
        trace = {
            "type": "pcb_trace",
            "route": [
                {"x": 0.0, "y": 0.0},
                {"x": 5.0, "y": 0.0},
                {"x": 5.0, "y": 5.0},
            ]
        }
        findings = _check_acid_traps([trace])
        self.assertFalse(any(f.rule == "acid_trap" for f in findings))


class TestSlivers(unittest.TestCase):

    def _t(self, cls):
        return _IPC_THRESHOLDS[cls]

    def test_sliver_flagged(self):
        trace = {
            "type": "pcb_trace",
            "route_thickness_mm": 0.05,  # thin
            "route": [{"x": 0.0, "y": 0.0}, {"x": 0.08, "y": 0.0}],  # short
        }
        findings = _check_slivers([trace], self._t(2))
        self.assertTrue(any(f.rule == "copper_sliver" for f in findings))

    def test_normal_trace_not_sliver(self):
        trace = {
            "type": "pcb_trace",
            "route_thickness_mm": 0.25,
            "route": [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
        }
        findings = _check_slivers([trace], self._t(2))
        self.assertFalse(any(f.rule == "copper_sliver" for f in findings))


class TestCourtyardOverlap(unittest.TestCase):

    def _t(self, cls):
        return _IPC_THRESHOLDS[cls]

    def test_overlapping_courtyards_flagged(self):
        comps = [
            {"type": "pcb_component", "source_component_id": "sc_a",
             "x": 0.0, "y": 0.0, "courtyard_width": 3.0, "courtyard_height": 3.0},
            {"type": "pcb_component", "source_component_id": "sc_b",
             "x": 2.0, "y": 0.0, "courtyard_width": 3.0, "courtyard_height": 3.0},
        ]
        findings = _check_courtyard_overlap(comps, self._t(2))
        self.assertTrue(any(f.rule == "courtyard_overlap" for f in findings))

    def test_well_spaced_courtyards_clean(self):
        comps = [
            {"type": "pcb_component", "source_component_id": "sc_a",
             "x": 0.0, "y": 0.0, "courtyard_width": 2.0, "courtyard_height": 2.0},
            {"type": "pcb_component", "source_component_id": "sc_b",
             "x": 20.0, "y": 0.0, "courtyard_width": 2.0, "courtyard_height": 2.0},
        ]
        findings = _check_courtyard_overlap(comps, self._t(2))
        self.assertFalse(any(f.rule == "courtyard_overlap" for f in findings))


class TestSmallestPassive(unittest.TestCase):

    def _t(self, cls):
        return _IPC_THRESHOLDS[cls]

    def test_0201_fails_class2(self):
        src = [{"type": "source_component", "source_component_id": "sc1",
                "name": "R1", "footprint": "R_0201"}]
        pbc = [{"type": "pcb_component", "source_component_id": "sc1"}]
        findings = _check_smallest_passive(src, pbc, self._t(2))
        self.assertTrue(any(f.rule == "smallest_passive" for f in findings))

    def test_0402_passes_class2(self):
        src = [{"type": "source_component", "source_component_id": "sc1",
                "name": "R1", "footprint": "R_0402"}]
        pbc = [{"type": "pcb_component", "source_component_id": "sc1"}]
        findings = _check_smallest_passive(src, pbc, self._t(2))
        self.assertFalse(any(f.rule == "smallest_passive" for f in findings))

    def test_0402_fails_class3(self):
        src = [{"type": "source_component", "source_component_id": "sc1",
                "name": "R1", "footprint": "R_0402"}]
        pbc = [{"type": "pcb_component", "source_component_id": "sc1"}]
        findings = _check_smallest_passive(src, pbc, self._t(3))
        self.assertTrue(any(f.rule == "smallest_passive" for f in findings))

    def test_0603_passes_class3(self):
        src = [{"type": "source_component", "source_component_id": "sc1",
                "name": "R1", "footprint": "R_0603"}]
        pbc = [{"type": "pcb_component", "source_component_id": "sc1"}]
        findings = _check_smallest_passive(src, pbc, self._t(3))
        self.assertFalse(any(f.rule == "smallest_passive" for f in findings))


# ─── 5. DFM score ─────────────────────────────────────────────────────────────

class TestScoreDfm(unittest.TestCase):

    def test_no_findings_scores_100(self):
        self.assertEqual(score_dfm([]), 100)

    def test_one_fail_deducts_15(self):
        findings = [DFMFinding(rule="x", severity="fail", message="")]
        self.assertEqual(score_dfm(findings), 85)

    def test_one_warn_deducts_5(self):
        findings = [DFMFinding(rule="x", severity="warn", message="")]
        self.assertEqual(score_dfm(findings), 95)

    def test_score_clamps_to_zero(self):
        findings = [DFMFinding(rule="x", severity="fail", message="")] * 10
        self.assertEqual(score_dfm(findings), 0)

    def test_info_findings_no_penalty(self):
        findings = [DFMFinding(rule="input", severity="info", message="")]
        self.assertEqual(score_dfm(findings), 100)


# ─── 6. DFM report tool (JSON roundtrip) ─────────────────────────────────────

class TestBomDfmReportTool(unittest.TestCase):

    def test_clean_board_scores_100(self):
        resp = _run(_call("bom_dfm_report", {"circuit_json": THREE_COMPONENT_CIRCUIT}))
        self.assertTrue(resp.get("ok"))
        self.assertEqual(resp["score"], 100)
        self.assertEqual(resp["fail_count"], 0)

    def test_empty_circuit_returns_ok_with_info(self):
        resp = _run(_call("bom_dfm_report", {"circuit_json": []}))
        self.assertTrue(resp.get("ok"))
        self.assertEqual(resp["info_count"], 1)

    def test_invalid_board_class(self):
        resp = _run(_call("bom_dfm_report", {
            "circuit_json": THREE_COMPONENT_CIRCUIT,
            "board_class": 9,
        }))
        self.assertIn("error", resp)

    def test_class2_vs_class3_annular_ring_differ(self):
        """Board with via ring=0.060 mm: passes class 2, fails class 3."""
        circuit = [
            {"type": "pcb_board", "width": 50.0, "height": 50.0},
            {"type": "pcb_via", "x": 10.0, "y": 10.0,
             "outer_diameter": 0.42, "hole_diameter": 0.30},  # ring = 0.060
        ]
        resp2 = _run(_call("bom_dfm_report", {"circuit_json": circuit, "board_class": 2}))
        resp3 = _run(_call("bom_dfm_report", {"circuit_json": circuit, "board_class": 3}))
        self.assertEqual(resp2["fail_count"], 0)
        self.assertGreater(resp3["fail_count"], 0)


# ─── 7. Sourcing risk tool ────────────────────────────────────────────────────

class TestBomSourcingRiskTool(unittest.TestCase):

    def test_single_source_flagged(self):
        bom = [
            {"refdes": "U1", "qty": 1, "unit_price": 5.0,
             "mpn": "ABC-123", "num_sources": 1}
        ]
        resp = _run(_call("bom_sourcing_risk", {"bom_lines": bom}))
        self.assertTrue(resp.get("ok"))
        self.assertTrue(any(r["risk"] == "single_source" for r in resp["risks"]))

    def test_multi_source_not_flagged(self):
        bom = [
            {"refdes": "R1", "qty": 1, "unit_price": 0.10, "num_sources": 3}
        ]
        resp = _run(_call("bom_sourcing_risk", {"bom_lines": bom}))
        self.assertTrue(resp.get("ok"))
        self.assertFalse(any(r["risk"] == "single_source" for r in resp["risks"]))

    def test_no_price_flagged(self):
        bom = [{"refdes": "R5", "qty": 1}]
        resp = _run(_call("bom_sourcing_risk", {"bom_lines": bom}))
        self.assertTrue(resp.get("ok"))
        self.assertTrue(any(r["risk"] == "no_price" for r in resp["risks"]))

    def test_price_breaks_sufficient_for_price(self):
        bom = [{"refdes": "C1", "qty": 1,
                "price_breaks": [{"min_qty": 1, "unit_price": 0.50}]}]
        resp = _run(_call("bom_sourcing_risk", {"bom_lines": bom}))
        self.assertFalse(any(r["risk"] == "no_price" for r in resp["risks"]))

    def test_long_lead_flagged(self):
        bom = [{"refdes": "U2", "qty": 1, "unit_price": 10.0,
                "lead_time_weeks": 52}]
        resp = _run(_call("bom_sourcing_risk", {"bom_lines": bom}))
        self.assertTrue(any(r["risk"] == "long_lead" for r in resp["risks"]))

    def test_short_lead_not_flagged(self):
        bom = [{"refdes": "U2", "qty": 1, "unit_price": 10.0,
                "lead_time_weeks": 4}]
        resp = _run(_call("bom_sourcing_risk", {"bom_lines": bom}))
        self.assertFalse(any(r["risk"] == "long_lead" for r in resp["risks"]))

    def test_dnp_parts_skipped(self):
        bom = [{"refdes": "R99", "qty": 1, "dnp": True, "num_sources": 1}]
        resp = _run(_call("bom_sourcing_risk", {"bom_lines": bom}))
        self.assertTrue(resp.get("ok"))
        self.assertEqual(resp["risk_count"], 0)

    def test_empty_bom_returns_error(self):
        resp = _run(_call("bom_sourcing_risk", {"bom_lines": []}))
        self.assertIn("error", resp)
        self.assertEqual(resp["code"], "EMPTY_BOM")

    def test_custom_long_lead_threshold(self):
        bom = [{"refdes": "U3", "qty": 1, "unit_price": 5.0, "lead_time_weeks": 20}]
        resp_default = _run(_call("bom_sourcing_risk", {"bom_lines": bom}))
        resp_strict = _run(_call("bom_sourcing_risk", {
            "bom_lines": bom, "long_lead_weeks": 12
        }))
        # Default (16 wks) flags 20 wks; stricter (12 wks) also flags
        self.assertTrue(any(r["risk"] == "long_lead" for r in resp_default["risks"]))
        self.assertTrue(any(r["risk"] == "long_lead" for r in resp_strict["risks"]))


if __name__ == "__main__":
    unittest.main()
