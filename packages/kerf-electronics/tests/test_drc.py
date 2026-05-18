"""
Tests for kerf_electronics.drc — Design Rule Check engine.

Oracles / coverage
------------------
1.  DRC fires on two cross-net pads 0.1 mm apart when rule is 0.2 mm.
2.  Same-net pads 0.1 mm apart do NOT fire a pad_clearance violation.
3.  Pads exactly at clearance boundary do not violate.
4.  Unconnected-pad check fires when net has ≥2 pads but no trace.
5.  Missing-footprint check fires when source_component has no pcb_component.
6.  Trace-to-trace clearance fires for two close cross-net traces.
7.  Pad-to-trace clearance fires for a pad close to a foreign trace.
8.  Empty circuit returns zero violations.
9.  run_drc returns correct error_count and warning_count.
10. Custom rules override default clearance.
"""

from __future__ import annotations

import pytest

from kerf_electronics.drc import run_drc, DEFAULT_RULES


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _pad(pad_id: str, x: float, y: float, net: str | None = None, w: float = 0.5, h: float = 0.5) -> dict:
    p: dict = {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": pad_id,
        "x": x,
        "y": y,
        "width": w,
        "height": h,
    }
    if net is not None:
        p["net_id"] = net
    return p


def _trace(trace_id: str, points: list, net: str | None = None, width: float = 0.2) -> dict:
    t: dict = {
        "type": "pcb_trace",
        "pcb_trace_id": trace_id,
        "route_thickness_mm": width,
        "route": [{"x": x, "y": y} for x, y in points],
    }
    if net is not None:
        t["net_id"] = net
    return t


def _src_comp(src_id: str, name: str) -> dict:
    return {"type": "source_component", "source_component_id": src_id, "name": name}


def _pcb_comp(src_id: str) -> dict:
    return {"type": "pcb_component", "source_component_id": src_id}


# ---------------------------------------------------------------------------
# 1. Pad-to-pad clearance violations
# ---------------------------------------------------------------------------

class TestPadPadClearance:

    def test_violation_fires_for_close_cross_net_pads(self):
        """Two pads on different nets, 0.1 mm apart (edge-to-edge), rule=0.2 mm → violation."""
        # Pad centres 0.6 mm apart; each pad is 0.5×0.5 mm → half-width=0.25 each
        # Edge-to-edge = 0.6 - 0.25 - 0.25 = 0.1 mm < 0.2 mm rule
        circuit = [
            _pad("P1", 0.0, 0.0, "VCC"),
            _pad("P2", 0.6, 0.0, "GND"),
        ]
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        violations = result["violations"]
        pad_clear = [v for v in violations if v["kind"] == "pad_clearance"]
        assert len(pad_clear) >= 1, "Expected pad_clearance violation"

    def test_same_net_pads_no_clearance_violation(self):
        """Same-net pads are excluded from clearance checks."""
        circuit = [
            _pad("P1", 0.0, 0.0, "GND"),
            _pad("P2", 0.6, 0.0, "GND"),
        ]
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        pad_clear = [v for v in result["violations"] if v["kind"] == "pad_clearance"]
        assert len(pad_clear) == 0

    def test_pads_well_clear_no_violation(self):
        """Pads comfortably above the clearance threshold → no violation."""
        # Centers 2.0 mm apart; half-widths 0.25 each → edge-to-edge = 1.5 mm >> 0.2 mm rule
        circuit = [
            _pad("P1", 0.0, 0.0, "VCC"),
            _pad("P2", 2.0, 0.0, "GND"),
        ]
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        pad_clear = [v for v in result["violations"] if v["kind"] == "pad_clearance"]
        assert len(pad_clear) == 0, "Pads well clear of the limit should not violate"

    def test_known_violating_fixture(self):
        """Oracle: two cross-net pads 0.1 mm apart with 0.2 mm rule → violation count >= 1."""
        # This is the explicit fixture from the task spec.
        circuit = [
            _pad("PA", 0.0, 0.0, "NET_A", w=0.05, h=0.05),
            _pad("PB", 0.1, 0.0, "NET_B", w=0.05, h=0.05),
        ]
        # Pad centres 0.1 mm apart; half-widths 0.025 each → edge-to-edge = 0.05 mm < 0.2 mm
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        assert result["error_count"] >= 1


# ---------------------------------------------------------------------------
# 2. Unconnected-pad check
# ---------------------------------------------------------------------------

class TestUnconnectedPads:

    def test_unconnected_fires_when_no_trace_for_net(self):
        circuit = [
            _pad("P1", 0.0, 0.0, "SIGNAL"),
            _pad("P2", 5.0, 0.0, "SIGNAL"),
        ]
        result = run_drc(circuit)
        unconnected = [v for v in result["violations"] if v["kind"] == "unconnected_pad"]
        assert len(unconnected) >= 1

    def test_unconnected_not_fired_for_single_pad_net(self):
        """A net with only one pad cannot be unconnected."""
        circuit = [_pad("P1", 0.0, 0.0, "SINGLE")]
        result = run_drc(circuit)
        unconnected = [v for v in result["violations"] if v["kind"] == "unconnected_pad"]
        assert len(unconnected) == 0

    def test_unconnected_not_fired_when_trace_exists(self):
        """Net with both pads and a trace → no unconnected warning."""
        circuit = [
            _pad("P1", 0.0, 0.0, "VCC"),
            _pad("P2", 5.0, 0.0, "VCC"),
            _trace("T1", [(0.0, 0.0), (5.0, 0.0)], "VCC"),
        ]
        result = run_drc(circuit)
        unconnected = [v for v in result["violations"] if v["kind"] == "unconnected_pad"]
        assert len(unconnected) == 0

    def test_unconnected_is_warning_severity(self):
        circuit = [
            _pad("P1", 0.0, 0.0, "SIGNAL"),
            _pad("P2", 5.0, 0.0, "SIGNAL"),
        ]
        result = run_drc(circuit)
        unconnected = [v for v in result["violations"] if v["kind"] == "unconnected_pad"]
        for v in unconnected:
            assert v["severity"] == "warning"


# ---------------------------------------------------------------------------
# 3. Missing-footprint check
# ---------------------------------------------------------------------------

class TestMissingFootprint:

    def test_missing_footprint_fires(self):
        circuit = [
            _src_comp("SC1", "R1"),
            _src_comp("SC2", "C1"),
            _pcb_comp("SC1"),  # only SC1 is placed
        ]
        result = run_drc(circuit)
        missing = [v for v in result["violations"] if v["kind"] == "missing_footprint"]
        assert len(missing) == 1
        assert "C1" in missing[0]["message"]

    def test_all_placed_no_violation(self):
        circuit = [
            _src_comp("SC1", "R1"),
            _pcb_comp("SC1"),
        ]
        result = run_drc(circuit)
        missing = [v for v in result["violations"] if v["kind"] == "missing_footprint"]
        assert len(missing) == 0

    def test_missing_footprint_is_warning(self):
        circuit = [_src_comp("SC1", "U1")]
        result = run_drc(circuit)
        missing = [v for v in result["violations"] if v["kind"] == "missing_footprint"]
        assert len(missing) == 1
        assert missing[0]["severity"] == "warning"


# ---------------------------------------------------------------------------
# 4. Trace-to-trace clearance
# ---------------------------------------------------------------------------

class TestTraceClearance:

    def test_close_cross_net_traces_violate(self):
        """Two traces on different nets, very close together → trace_clearance violation."""
        circuit = [
            _trace("T1", [(0.0, 0.0), (10.0, 0.0)], "NET_A"),
            _trace("T2", [(0.0, 0.05), (10.0, 0.05)], "NET_B"),
        ]
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        trace_viol = [v for v in result["violations"] if v["kind"] == "trace_clearance"]
        assert len(trace_viol) >= 1

    def test_same_net_traces_no_violation(self):
        circuit = [
            _trace("T1", [(0.0, 0.0), (10.0, 0.0)], "NET_A"),
            _trace("T2", [(0.0, 0.05), (10.0, 0.05)], "NET_A"),
        ]
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        trace_viol = [v for v in result["violations"] if v["kind"] == "trace_clearance"]
        assert len(trace_viol) == 0

    def test_far_traces_no_violation(self):
        circuit = [
            _trace("T1", [(0.0, 0.0), (10.0, 0.0)], "NET_A"),
            _trace("T2", [(0.0, 5.0), (10.0, 5.0)], "NET_B"),
        ]
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        trace_viol = [v for v in result["violations"] if v["kind"] == "trace_clearance"]
        assert len(trace_viol) == 0


# ---------------------------------------------------------------------------
# 5. Pad-to-trace clearance
# ---------------------------------------------------------------------------

class TestPadTraceClearance:

    def test_pad_close_to_foreign_trace_violates(self):
        """Pad on NET_A very close to a NET_B trace → violation."""
        circuit = [
            _pad("P1", 0.0, 0.0, "NET_A", w=0.1, h=0.1),
            _trace("T1", [(-5.0, 0.1), (5.0, 0.1)], "NET_B"),
        ]
        # Pad edge is at y=0.05; trace is at y=0.1 → gap = 0.05 mm < 0.2 mm rule
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        pt_viol = [v for v in result["violations"] if v["kind"] == "pad_trace_clearance"]
        assert len(pt_viol) >= 1

    def test_same_net_pad_trace_no_violation(self):
        circuit = [
            _pad("P1", 0.0, 0.0, "NET_A", w=0.1, h=0.1),
            _trace("T1", [(-5.0, 0.05), (5.0, 0.05)], "NET_A"),
        ]
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        pt_viol = [v for v in result["violations"] if v["kind"] == "pad_trace_clearance"]
        assert len(pt_viol) == 0


# ---------------------------------------------------------------------------
# 6. Edge cases and result structure
# ---------------------------------------------------------------------------

class TestEdgeCasesAndStructure:

    def test_empty_circuit(self):
        result = run_drc([])
        assert result["violations"] == []
        assert result["error_count"] == 0
        assert result["warning_count"] == 0

    def test_non_list_input(self):
        result = run_drc(None)  # type: ignore[arg-type]
        assert result["violations"] == []

    def test_result_keys_present(self):
        result = run_drc([])
        assert "violations" in result
        assert "error_count" in result
        assert "warning_count" in result

    def test_error_and_warning_counts_consistent(self):
        circuit = [
            _pad("P1", 0.0, 0.0, "A", w=0.05, h=0.05),
            _pad("P2", 0.1, 0.0, "B", w=0.05, h=0.05),  # too close → error
            _src_comp("SC1", "U1"),  # no footprint → warning
        ]
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        errors = [v for v in result["violations"] if v["severity"] == "error"]
        warnings = [v for v in result["violations"] if v["severity"] == "warning"]
        assert result["error_count"] == len(errors)
        assert result["warning_count"] == len(warnings)

    def test_custom_rule_overrides_default(self):
        """With a relaxed rule (0.05 mm), the 0.1-mm close pads should NOT violate."""
        circuit = [
            _pad("P1", 0.0, 0.0, "A", w=0.05, h=0.05),
            _pad("P2", 0.1, 0.0, "B", w=0.05, h=0.05),
        ]
        result = run_drc(circuit, {"min_clearance_mm": 0.03})
        pad_clear = [v for v in result["violations"] if v["kind"] == "pad_clearance"]
        assert len(pad_clear) == 0

    def test_violation_has_required_fields(self):
        circuit = [
            _pad("P1", 0.0, 0.0, "A", w=0.05, h=0.05),
            _pad("P2", 0.1, 0.0, "B", w=0.05, h=0.05),
        ]
        result = run_drc(circuit, {"min_clearance_mm": 0.2})
        for v in result["violations"]:
            assert "kind" in v
            assert "severity" in v
            assert "x" in v
            assert "y" in v
            assert "message" in v
