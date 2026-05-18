"""
tests/test_analyze.py — pytest suite for kerf_plc.llm.analyze (T-225b-3).

Covers static analysis:
  - find_self_latching    — motor := motor OR start pattern
  - find_unused_variables — declared but not used
  - find_double_coil_writes — two rungs writing to the same coil
  - find_dangling_inputs  — VAR_INPUT never referenced
  - find_race_conditions  — bidirectional read/write dependency

Dynamic analysis:
  - simulate_ladder       — blinker oracle: ≥9 rising edges in 5000 ms (±1 of 10)
  - count_edges           — utility: rising / falling / both
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from kerf_plc.llm.analyze import (
    count_edges,
    find_dangling_inputs,
    find_double_coil_writes,
    find_race_conditions,
    find_self_latching,
    find_unused_variables,
    simulate_ladder,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ===========================================================================
# Helpers
# ===========================================================================

def _prog(variables: dict[str, Any], pous: list[dict], **kwargs) -> dict[str, Any]:
    p: dict[str, Any] = {"variables": variables, "pous": pous}
    p.update(kwargs)
    return p


def _ld_pou(rungs: list[dict]) -> dict:
    return {"kind": "LD", "rungs": rungs}


def _st_pou(statements: list[dict]) -> dict:
    return {"kind": "ST", "statements": statements}


def _contact(var: str, negate: bool = False) -> dict:
    return {"type": "contact", "var": var, "negate": negate}


def _rung(elements: list[dict], coil: str | None = None) -> dict:
    r: dict = {"elements": elements}
    if coil:
        r["coil"] = coil
    return r


# ===========================================================================
# find_self_latching
# ===========================================================================

class TestFindSelfLatching:
    """Oracle: motor := motor OR start  →  (motor, rung_index) in results."""

    def _make_motor_latch(self) -> dict[str, Any]:
        """Minimal LD program modelling `motor := motor OR start`."""
        return _prog(
            variables={"motor": False, "start": False},
            pous=[
                _ld_pou([
                    _rung(
                        elements=[
                            _contact("motor"),   # existing state (latch leg)
                            _contact("start"),   # momentary push
                        ],
                        coil="motor",
                    )
                ])
            ],
        )

    def test_detects_self_latch(self):
        prog = self._make_motor_latch()
        results = find_self_latching(prog)
        assert len(results) >= 1
        vars_found = [v for v, _ri in results]
        assert "motor" in vars_found

    def test_returns_correct_rung_index(self):
        prog = self._make_motor_latch()
        results = find_self_latching(prog)
        # The latch rung is the first (and only) rung → flat index 0
        assert any(ri == 0 for _v, ri in results)

    def test_no_false_positive_without_self_read(self):
        """A simple coil with no self-read is not flagged."""
        prog = _prog(
            variables={"x": False, "y": False},
            pous=[
                _ld_pou([
                    _rung(elements=[_contact("x")], coil="y")
                ])
            ],
        )
        results = find_self_latching(prog)
        assert results == []

    def test_second_rung_index_correct(self):
        """Self-latch on the second rung of a program → flat_index == 1."""
        prog = _prog(
            variables={"a": False, "b": False},
            pous=[
                _ld_pou([
                    _rung(elements=[_contact("a")], coil="a_out"),
                    _rung(elements=[_contact("b"), _contact("a_out")], coil="b"),
                ])
            ],
        )
        results = find_self_latching(prog)
        assert ("b", 1) in results

    def test_empty_program_returns_empty(self):
        prog = _prog(variables={}, pous=[])
        assert find_self_latching(prog) == []


# ===========================================================================
# find_unused_variables
# ===========================================================================

class TestFindUnusedVariables:
    """Oracle: declared-but-never-used variable appears in results."""

    def test_unused_declared_var_detected(self):
        prog = _prog(
            variables={"used_var": False, "ghost": False},
            pous=[
                _ld_pou([
                    _rung(elements=[_contact("used_var")], coil="output")
                ])
            ],
        )
        unused = find_unused_variables(prog)
        assert "ghost" in unused

    def test_used_var_not_in_results(self):
        prog = _prog(
            variables={"x": False},
            pous=[
                _ld_pou([_rung(elements=[_contact("x")], coil="y")])
            ],
        )
        unused = find_unused_variables(prog)
        assert "x" not in unused

    def test_only_declared_vars_are_checked(self):
        """Variables that appear in rungs but not declared are not flagged."""
        prog = _prog(
            variables={"declared": False},
            pous=[
                _ld_pou([
                    _rung(elements=[_contact("undeclared_contact")], coil="declared")
                ])
            ],
        )
        unused = find_unused_variables(prog)
        # declared is written (coil), so it IS used
        assert "declared" not in unused
        # undeclared_contact was never declared → not in scope
        assert "undeclared_contact" not in unused

    def test_all_vars_used_returns_empty(self):
        prog = _prog(
            variables={"a": False, "b": False},
            pous=[
                _ld_pou([_rung(elements=[_contact("a")], coil="b")])
            ],
        )
        unused = find_unused_variables(prog)
        assert unused == []

    def test_st_assignment_counts_as_use(self):
        prog = _prog(
            variables={"x": False, "y": False},
            pous=[
                _st_pou([{"lhs": "x", "rhs": {"type": "var", "name": "y"}}])
            ],
        )
        unused = find_unused_variables(prog)
        assert "x" not in unused
        assert "y" not in unused

    def test_multiple_unused(self):
        prog = _prog(
            variables={"a": False, "b": False, "c": False},
            pous=[],
        )
        unused = find_unused_variables(prog)
        assert set(unused) == {"a", "b", "c"}

    def test_empty_program_with_vars_returns_all(self):
        prog = _prog(variables={"lonely": False}, pous=[])
        unused = find_unused_variables(prog)
        assert "lonely" in unused


# ===========================================================================
# find_double_coil_writes
# ===========================================================================

class TestFindDoubleCoilWrites:
    """Oracle: two rungs both driving the same coil variable → flagged."""

    def test_two_rungs_same_coil(self):
        prog = _prog(
            variables={"motor": False, "start": False, "stop": False},
            pous=[
                _ld_pou([
                    _rung(elements=[_contact("start")], coil="motor"),
                    _rung(elements=[_contact("stop")], coil="motor"),
                ])
            ],
        )
        doubles = find_double_coil_writes(prog)
        assert "motor" in doubles

    def test_single_coil_not_flagged(self):
        prog = _prog(
            variables={"x": False, "y": False},
            pous=[
                _ld_pou([
                    _rung(elements=[_contact("x")], coil="y")
                ])
            ],
        )
        doubles = find_double_coil_writes(prog)
        assert doubles == []

    def test_st_double_write(self):
        """Two ST assignments to the same LHS count as a double-write."""
        prog = _prog(
            variables={"flag": False},
            pous=[
                _st_pou([
                    {"lhs": "flag", "rhs": {"type": "literal", "value": True}},
                    {"lhs": "flag", "rhs": {"type": "literal", "value": False}},
                ])
            ],
        )
        doubles = find_double_coil_writes(prog)
        assert "flag" in doubles

    def test_ld_and_st_mixed_write(self):
        """LD coil + ST assignment to same variable counts as double-write."""
        prog = _prog(
            variables={"out": False, "cond": False},
            pous=[
                _ld_pou([_rung(elements=[_contact("cond")], coil="out")]),
                _st_pou([{"lhs": "out", "rhs": {"type": "literal", "value": True}}]),
            ],
        )
        doubles = find_double_coil_writes(prog)
        assert "out" in doubles

    def test_different_coils_not_flagged(self):
        prog = _prog(
            variables={"a": False, "b": False, "x": False},
            pous=[
                _ld_pou([
                    _rung(elements=[_contact("x")], coil="a"),
                    _rung(elements=[_contact("x")], coil="b"),
                ])
            ],
        )
        doubles = find_double_coil_writes(prog)
        assert doubles == []


# ===========================================================================
# find_dangling_inputs
# ===========================================================================

class TestFindDanglingInputs:
    def test_unused_var_input_detected(self):
        prog = _prog(
            variables={"sensor": False, "output": False},
            pous=[
                _ld_pou([_rung(elements=[_contact("output")], coil="output")])
            ],
            var_inputs=["sensor"],
        )
        dangling = find_dangling_inputs(prog)
        assert "sensor" in dangling

    def test_used_var_input_not_flagged(self):
        prog = _prog(
            variables={"sensor": False},
            pous=[
                _ld_pou([_rung(elements=[_contact("sensor")], coil="out")])
            ],
            var_inputs=["sensor"],
        )
        dangling = find_dangling_inputs(prog)
        assert "sensor" not in dangling

    def test_no_var_inputs_key_returns_empty(self):
        prog = _prog(variables={"x": False}, pous=[])
        assert find_dangling_inputs(prog) == []


# ===========================================================================
# find_race_conditions
# ===========================================================================

class TestFindRaceConditions:
    def test_bidirectional_dependency_detected(self):
        """Rung 0 writes A and reads B; rung 1 writes B and reads A → race."""
        prog = _prog(
            variables={"A": False, "B": False},
            pous=[
                _ld_pou([
                    _rung(elements=[_contact("B")], coil="A"),
                    _rung(elements=[_contact("A")], coil="B"),
                ])
            ],
        )
        races = find_race_conditions(prog)
        assert len(races) >= 1
        pair = (min("A", "B"), max("A", "B"))
        assert pair in races

    def test_independent_rungs_no_race(self):
        prog = _prog(
            variables={"x": False, "y": False, "a": False, "b": False},
            pous=[
                _ld_pou([
                    _rung(elements=[_contact("x")], coil="y"),
                    _rung(elements=[_contact("a")], coil="b"),
                ])
            ],
        )
        races = find_race_conditions(prog)
        assert races == []

    def test_result_pairs_are_lexicographic(self):
        """Each result pair has pair[0] < pair[1] lexicographically."""
        prog = _prog(
            variables={"Z": False, "A": False},
            pous=[
                _ld_pou([
                    _rung(elements=[_contact("A")], coil="Z"),
                    _rung(elements=[_contact("Z")], coil="A"),
                ])
            ],
        )
        races = find_race_conditions(prog)
        for a, b in races:
            assert a <= b


# ===========================================================================
# simulate_ladder — blinker oracle
# ===========================================================================

class TestSimulateLadder:
    """Oracle: blinker 500ms × 5000ms → ≥9 rising edges on blink_out (±1 of 10)."""

    @pytest.fixture()
    def blinker_program(self) -> dict[str, Any]:
        return json.loads((FIXTURES / "sim_blinker.json").read_text())

    def test_blinker_returns_required_keys(self, blinker_program):
        result = simulate_ladder(
            blinker_program,
            inputs_provider=lambda t: {"enable": True},
            duration_ms=100,
            tick_ms=1,
        )
        assert "trace" in result
        assert "final_state" in result
        assert "output_pulses" in result

    def test_blinker_trace_length(self, blinker_program):
        result = simulate_ladder(
            blinker_program,
            inputs_provider=lambda t: {"enable": True},
            duration_ms=200,
            tick_ms=1,
        )
        assert len(result["trace"]) == 200

    def test_blinker_rising_edges_oracle(self, blinker_program):
        """Core oracle: 5000 ms / 500 ms = 10 pulses; tolerance ±1 → ≥9 edges."""
        result = simulate_ladder(
            blinker_program,
            inputs_provider=lambda t: {"enable": True},
            duration_ms=5000,
            tick_ms=1,
        )
        rising = count_edges(result["trace"], "blink_out", edge="rising")
        assert rising >= 9, f"Expected ≥9 rising edges on blink_out, got {rising}"
        assert rising <= 11, f"Expected ≤11 rising edges on blink_out, got {rising}"

    def test_blinker_output_pulses_covers_blink_out(self, blinker_program):
        """output_pulses counts edges across all vars; must be > 0."""
        result = simulate_ladder(
            blinker_program,
            inputs_provider=lambda t: {"enable": True},
            duration_ms=1000,
            tick_ms=1,
        )
        assert result["output_pulses"] > 0

    def test_final_state_is_last_snapshot(self, blinker_program):
        result = simulate_ladder(
            blinker_program,
            inputs_provider=lambda t: {"enable": True},
            duration_ms=10,
            tick_ms=1,
        )
        assert result["final_state"] == result["trace"][-1]

    def test_disabled_blinker_produces_no_edges(self, blinker_program):
        """With enable=False, the TON never starts and blink_out stays False."""
        result = simulate_ladder(
            blinker_program,
            inputs_provider=lambda t: {"enable": False},
            duration_ms=2000,
            tick_ms=1,
        )
        rising = count_edges(result["trace"], "blink_out", edge="rising")
        assert rising == 0


# ===========================================================================
# count_edges utility
# ===========================================================================

class TestCountEdges:
    def _make_trace(self, pattern: list[bool], var: str = "x") -> list[dict]:
        return [{var: v} for v in pattern]

    def test_rising_edges(self):
        trace = self._make_trace([False, True, True, False, True])
        assert count_edges(trace, "x", "rising") == 2

    def test_falling_edges(self):
        trace = self._make_trace([True, True, False, True, False])
        assert count_edges(trace, "x", "falling") == 2

    def test_both_edges(self):
        trace = self._make_trace([False, True, False, True])
        assert count_edges(trace, "x", "both") == 3  # F→T, T→F, F→T

    def test_empty_trace_returns_zero(self):
        assert count_edges([], "x") == 0

    def test_single_element_trace_returns_zero(self):
        assert count_edges([{"x": True}], "x") == 0

    def test_no_edges_returns_zero(self):
        trace = self._make_trace([True, True, True])
        assert count_edges(trace, "x", "rising") == 0

    def test_invalid_edge_raises(self):
        with pytest.raises(ValueError, match="edge must be"):
            count_edges([{"x": True}], "x", "sideways")

    def test_missing_variable_treated_as_false(self):
        """A key absent from snapshots is treated as False."""
        trace = [{"other": True}, {"x": True}, {"x": False}]
        assert count_edges(trace, "x", "rising") == 1

    def test_count_on_blinker_sim(self):
        """Integration: count_edges matches manual count on a 100-step trace."""
        import json as _json
        prog = _json.loads((FIXTURES / "sim_blinker.json").read_text())
        result = simulate_ladder(
            prog,
            inputs_provider=lambda t: {"enable": True},
            duration_ms=1000,
            tick_ms=1,
        )
        rising = count_edges(result["trace"], "blink_out", "rising")
        # 1000 ms / 500 ms = ~2 pulses, with up to ±1 tolerance
        assert 1 <= rising <= 3
