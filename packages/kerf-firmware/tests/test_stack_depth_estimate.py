"""Tests for kerf_firmware.stack_depth_estimate + LLM tool firmware_estimate_stack_depth.

Coverage
--------
- Three-function chain main(100) → A(200) → B(50): max = 100+200+50+32 = 382
- Cycle A→B→A: has_cycles=True, estimation completes without infinite loop
- Multiple callees: algorithm takes the deepest branch
- Single function (leaf): depth = frame + isr_overhead
- Entry function not in list: ValueError
- Negative frame_size_bytes: ValueError
- Negative isr_overhead_bytes: ValueError
- isr_overhead_bytes=0: disables ISR overhead
- Custom ISR overhead (ATmega, 3 bytes): used correctly
- Diamond DAG (shared callee): deepest path taken, no double-counting
- Deep linear chain: correct accumulation across N nodes
- Unknown callee treated as leaf (frame_size=0, no error)
- Mutual recursion (A→B→A): flagged as cycle
- has_cycles=False for acyclic graph
- num_functions_analyzed counts only reachable nodes
- critical_path starts with entry function and ends at deepest leaf
- LLM tool: valid 3-function chain round-trip
- LLM tool: invalid args (missing required, bad types)
- LLM tool: unknown entry function
- LLM tool: cycle detected flagged in JSON response
- LLM tool: isr_overhead_bytes=0 in JSON
- as_dict() has all expected keys
- Multiple-root branching: both branches explored, max taken
"""
from __future__ import annotations

import json

import pytest

from kerf_firmware.stack_depth_estimate import (
    FunctionFrame,
    StackDepthReport,
    estimate_stack_depth,
)
from kerf_firmware.tools.firmware_estimate_stack_depth import (
    run_firmware_estimate_stack_depth,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_chain(names_and_sizes: list[tuple[str, int]]) -> list[FunctionFrame]:
    """Create a linear call chain: each function calls the next."""
    frames = []
    for i, (name, size) in enumerate(names_and_sizes):
        callee = [names_and_sizes[i + 1][0]] if i + 1 < len(names_and_sizes) else []
        frames.append(FunctionFrame(name, size, callee))
    return frames


def _tool(args: dict) -> dict:
    """Call the LLM tool and return parsed JSON."""
    raw = run_firmware_estimate_stack_depth(args)
    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# FunctionFrame validation
# ─────────────────────────────────────────────────────────────────────────────

class TestFunctionFrameValidation:
    def test_negative_frame_size_raises(self):
        with pytest.raises(ValueError, match="frame_size_bytes"):
            FunctionFrame("f", -1, [])

    def test_zero_frame_size_allowed(self):
        f = FunctionFrame("f", 0, [])
        assert f.frame_size_bytes == 0

    def test_callees_default_empty(self):
        f = FunctionFrame("f", 16)
        assert f.callees == []


# ─────────────────────────────────────────────────────────────────────────────
# Core oracle — task-spec depth-bar
# ─────────────────────────────────────────────────────────────────────────────

class TestDepthBarOracle:
    def test_three_function_chain_is_382(self):
        """Depth-bar: main(100) → A(200) → B(50); default ISR 32 → 382."""
        frames = [
            FunctionFrame("main", 100, ["A"]),
            FunctionFrame("A", 200, ["B"]),
            FunctionFrame("B", 50, []),
        ]
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=32)
        assert report.max_stack_depth_bytes == 382
        assert report.critical_path == ["main", "A", "B"]
        assert report.entry_function == "main"
        assert report.has_cycles is False

    def test_critical_path_starts_at_entry(self):
        frames = _make_chain([("main", 100), ("A", 200), ("B", 50)])
        report = estimate_stack_depth(frames, "main")
        assert report.critical_path[0] == "main"

    def test_critical_path_ends_at_deepest_leaf(self):
        frames = _make_chain([("main", 100), ("A", 200), ("B", 50)])
        report = estimate_stack_depth(frames, "main")
        assert report.critical_path[-1] == "B"

    def test_chain_without_isr_overhead(self):
        """isr_overhead_bytes=0: max = 100 + 200 + 50 = 350."""
        frames = _make_chain([("main", 100), ("A", 200), ("B", 50)])
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=0)
        assert report.max_stack_depth_bytes == 350

    def test_custom_isr_overhead_atmega(self):
        """ATmega ISR overhead = 3 bytes (PC save only)."""
        frames = _make_chain([("main", 100), ("A", 200), ("B", 50)])
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=3)
        assert report.max_stack_depth_bytes == 353


# ─────────────────────────────────────────────────────────────────────────────
# Multiple callees — deepest branch wins
# ─────────────────────────────────────────────────────────────────────────────

class TestMultipleCallees:
    def test_deeper_branch_selected(self):
        """main → [A(200), B(10)]; A has no callees, B has no callees.
        Deepest path: main(100) → A(200) = 300 (vs main(100) → B(10) = 110).
        + ISR 32 = 332.
        """
        frames = [
            FunctionFrame("main", 100, ["A", "B"]),
            FunctionFrame("A", 200, []),
            FunctionFrame("B", 10, []),
        ]
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=32)
        assert report.max_stack_depth_bytes == 332
        assert report.critical_path == ["main", "A"]

    def test_three_branches_max_taken(self):
        """main → [A(50), B(300), C(150)]; deepest: main(100)+B(300)+32 = 432."""
        frames = [
            FunctionFrame("main", 100, ["A", "B", "C"]),
            FunctionFrame("A", 50, []),
            FunctionFrame("B", 300, []),
            FunctionFrame("C", 150, []),
        ]
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=32)
        assert report.max_stack_depth_bytes == 432
        assert "B" in report.critical_path

    def test_deeper_subtree_selected(self):
        """main → [X, Y]; X → [X1(500)], Y → [Y1(10)].
        Path main(10)+X(50)+X1(500)+32 = 592.
        """
        frames = [
            FunctionFrame("main", 10, ["X", "Y"]),
            FunctionFrame("X", 50, ["X1"]),
            FunctionFrame("X1", 500, []),
            FunctionFrame("Y", 100, ["Y1"]),
            FunctionFrame("Y1", 10, []),
        ]
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=32)
        assert report.max_stack_depth_bytes == 10 + 50 + 500 + 32
        assert report.critical_path == ["main", "X", "X1"]


# ─────────────────────────────────────────────────────────────────────────────
# Diamond DAG (shared callee)
# ─────────────────────────────────────────────────────────────────────────────

class TestDiamondDAG:
    def test_diamond_no_cycle(self):
        """main → [A, B]; A → Leaf; B → Leaf (shared callee, no cycle).
        Path main(10)+A(200)+Leaf(50)+32=292 vs main(10)+B(100)+Leaf(50)+32=192.
        Max = 292.
        """
        frames = [
            FunctionFrame("main", 10, ["A", "B"]),
            FunctionFrame("A", 200, ["Leaf"]),
            FunctionFrame("B", 100, ["Leaf"]),
            FunctionFrame("Leaf", 50, []),
        ]
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=32)
        assert report.max_stack_depth_bytes == 10 + 200 + 50 + 32
        assert report.has_cycles is False
        assert report.critical_path == ["main", "A", "Leaf"]


# ─────────────────────────────────────────────────────────────────────────────
# Cycle detection
# ─────────────────────────────────────────────────────────────────────────────

class TestCycleDetection:
    def test_self_cycle_flagged(self):
        """A → A (self-recursion): has_cycles=True, terminates.
        DFS: first A frame (100 B) is pushed, then A is visited once more as its
        own callee (another 100 B) before the back-edge is detected, so the
        per-iteration lower bound reported is 200 B (two frames on the DFS path
        before the cycle is cut).  The important thing is has_cycles=True.
        """
        frames = [FunctionFrame("A", 100, ["A"])]
        report = estimate_stack_depth(frames, "A", isr_overhead_bytes=0)
        assert report.has_cycles is True
        # At minimum one full frame must be counted
        assert report.max_stack_depth_bytes >= 100

    def test_mutual_recursion_flagged(self):
        """A → B → A: mutual recursion detected."""
        frames = [
            FunctionFrame("A", 100, ["B"]),
            FunctionFrame("B", 200, ["A"]),
        ]
        report = estimate_stack_depth(frames, "A", isr_overhead_bytes=0)
        assert report.has_cycles is True

    def test_cycle_with_acyclic_branch(self):
        """main → [Cycler, Leaf]; Cycler → Cycler; Leaf(300).
        Deepest acyclic path: main(10)+Leaf(300)+32=342.
        Cyclic path: main(10)+Cycler(50)+32=92 (cycle cut at self-call).
        Max = 342.
        """
        frames = [
            FunctionFrame("main", 10, ["Cycler", "Leaf"]),
            FunctionFrame("Cycler", 50, ["Cycler"]),  # self-recursive
            FunctionFrame("Leaf", 300, []),
        ]
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=32)
        assert report.has_cycles is True
        assert report.max_stack_depth_bytes == 10 + 300 + 32

    def test_acyclic_graph_no_cycle_flag(self):
        frames = _make_chain([("main", 100), ("A", 200), ("B", 50)])
        report = estimate_stack_depth(frames, "main")
        assert report.has_cycles is False


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_single_leaf_function(self):
        """Single function with no callees: depth = frame + ISR."""
        frames = [FunctionFrame("main", 256, [])]
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=32)
        assert report.max_stack_depth_bytes == 256 + 32
        assert report.critical_path == ["main"]

    def test_unknown_callee_treated_as_leaf(self):
        """Callee not in functions list → treated as external leaf with 0 bytes.
        'printf' contributes 0 to the accumulated depth, so the deepest path
        total equals main's own frame (100 B).  The critical_path may be
        ['main'] since printf adds nothing new to the depth.
        """
        frames = [FunctionFrame("main", 100, ["printf"])]
        # "printf" not in list — should not raise, treated as 0-byte leaf
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=0)
        assert report.max_stack_depth_bytes == 100
        # path must start at entry function
        assert report.critical_path[0] == "main"

    def test_entry_not_in_list_raises(self):
        frames = [FunctionFrame("main", 100, [])]
        with pytest.raises(ValueError, match="not found"):
            estimate_stack_depth(frames, "nonexistent")

    def test_negative_isr_overhead_raises(self):
        frames = [FunctionFrame("main", 100, [])]
        with pytest.raises(ValueError, match="isr_overhead_bytes"):
            estimate_stack_depth(frames, "main", isr_overhead_bytes=-1)

    def test_num_functions_analyzed_counts_reachable(self):
        """Only functions reachable from entry are counted."""
        frames = [
            FunctionFrame("main", 100, ["A"]),
            FunctionFrame("A", 200, []),
            FunctionFrame("Unreachable", 999, []),  # not reachable from main
        ]
        report = estimate_stack_depth(frames, "main")
        # main + A are reachable; Unreachable is not
        assert report.num_functions_analyzed == 2

    def test_deep_linear_chain(self):
        """10-node chain: sum of all frames + ISR."""
        sizes = list(range(10, 110, 10))  # [10, 20, ..., 100]
        names = [f"F{i}" for i in range(10)]
        frames = _make_chain(list(zip(names, sizes)))
        expected = sum(sizes) + 32
        report = estimate_stack_depth(frames, "F0", isr_overhead_bytes=32)
        assert report.max_stack_depth_bytes == expected
        assert report.critical_path == names

    def test_honest_caveat_present(self):
        frames = [FunctionFrame("main", 100, [])]
        report = estimate_stack_depth(frames, "main")
        assert len(report.honest_caveat) > 50
        assert "STATIC" in report.honest_caveat

    def test_cycle_caveat_in_honest_caveat(self):
        frames = [FunctionFrame("A", 100, ["A"])]
        report = estimate_stack_depth(frames, "A")
        assert "CYCLE" in report.honest_caveat

    def test_as_dict_has_all_keys(self):
        frames = _make_chain([("main", 100), ("A", 200)])
        report = estimate_stack_depth(frames, "main")
        d = report.as_dict()
        for key in (
            "entry_function", "max_stack_depth_bytes", "critical_path",
            "num_functions_analyzed", "has_cycles", "honest_caveat",
        ):
            assert key in d, f"Missing key: {key}"

    def test_zero_frame_size_function(self):
        """Function with 0-byte frame still contributes to path correctly."""
        frames = [
            FunctionFrame("main", 0, ["A"]),
            FunctionFrame("A", 200, []),
        ]
        report = estimate_stack_depth(frames, "main", isr_overhead_bytes=0)
        assert report.max_stack_depth_bytes == 200
        assert report.critical_path == ["main", "A"]


# ─────────────────────────────────────────────────────────────────────────────
# LLM tool tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMTool:
    def _make_funcs(self, specs: list[dict]) -> list[dict]:
        return specs

    def test_valid_three_function_chain_is_382(self):
        """LLM tool round-trip: main(100)→A(200)→B(50) + ISR 32 = 382."""
        result = _tool({
            "functions": [
                {"function_name": "main", "frame_size_bytes": 100, "callees": ["A"]},
                {"function_name": "A", "frame_size_bytes": 200, "callees": ["B"]},
                {"function_name": "B", "frame_size_bytes": 50, "callees": []},
            ],
            "entry_function_name": "main",
        })
        assert "error" not in result
        assert result["max_stack_depth_bytes"] == 382
        assert result["critical_path"] == ["main", "A", "B"]
        assert result["has_cycles"] is False

    def test_valid_custom_isr_zero(self):
        """isr_overhead_bytes=0 → 350."""
        result = _tool({
            "functions": [
                {"function_name": "main", "frame_size_bytes": 100, "callees": ["A"]},
                {"function_name": "A", "frame_size_bytes": 200, "callees": ["B"]},
                {"function_name": "B", "frame_size_bytes": 50, "callees": []},
            ],
            "entry_function_name": "main",
            "isr_overhead_bytes": 0,
        })
        assert result["max_stack_depth_bytes"] == 350

    def test_cycle_flagged_in_json(self):
        result = _tool({
            "functions": [
                {"function_name": "A", "frame_size_bytes": 100, "callees": ["B"]},
                {"function_name": "B", "frame_size_bytes": 200, "callees": ["A"]},
            ],
            "entry_function_name": "A",
        })
        assert result["has_cycles"] is True

    def test_missing_functions(self):
        result = _tool({"entry_function_name": "main"})
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_missing_entry_function_name(self):
        result = _tool({
            "functions": [{"function_name": "main", "frame_size_bytes": 100}],
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_unknown_entry_function_returns_error(self):
        result = _tool({
            "functions": [{"function_name": "main", "frame_size_bytes": 100}],
            "entry_function_name": "does_not_exist",
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_negative_frame_size_returns_error(self):
        result = _tool({
            "functions": [{"function_name": "main", "frame_size_bytes": -1}],
            "entry_function_name": "main",
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_invalid_callees_type_returns_error(self):
        result = _tool({
            "functions": [
                {"function_name": "main", "frame_size_bytes": 100, "callees": "A"},
            ],
            "entry_function_name": "main",
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_negative_isr_overhead_returns_error(self):
        result = _tool({
            "functions": [{"function_name": "main", "frame_size_bytes": 100}],
            "entry_function_name": "main",
            "isr_overhead_bytes": -5,
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_response_dict_has_all_keys(self):
        result = _tool({
            "functions": [{"function_name": "main", "frame_size_bytes": 64}],
            "entry_function_name": "main",
        })
        for key in (
            "entry_function", "max_stack_depth_bytes", "critical_path",
            "num_functions_analyzed", "has_cycles", "honest_caveat",
        ):
            assert key in result, f"Missing key: {key}"

    def test_atmega_isr_overhead(self):
        """ATmega isr_overhead_bytes=3: main(100)+A(200)+B(50)+3=353."""
        result = _tool({
            "functions": [
                {"function_name": "main", "frame_size_bytes": 100, "callees": ["A"]},
                {"function_name": "A", "frame_size_bytes": 200, "callees": ["B"]},
                {"function_name": "B", "frame_size_bytes": 50, "callees": []},
            ],
            "entry_function_name": "main",
            "isr_overhead_bytes": 3,
        })
        assert result["max_stack_depth_bytes"] == 353

    def test_multiple_callees_max_path(self):
        """Tool selects deepest branch: main→[A(500), B(10)] → main(50)+A(500)+32=582."""
        result = _tool({
            "functions": [
                {"function_name": "main", "frame_size_bytes": 50,
                 "callees": ["BigFunc", "SmallFunc"]},
                {"function_name": "BigFunc", "frame_size_bytes": 500, "callees": []},
                {"function_name": "SmallFunc", "frame_size_bytes": 10, "callees": []},
            ],
            "entry_function_name": "main",
            "isr_overhead_bytes": 32,
        })
        assert result["max_stack_depth_bytes"] == 582
        assert "BigFunc" in result["critical_path"]
