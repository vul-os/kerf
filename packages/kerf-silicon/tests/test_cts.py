"""test_cts.py — pytest suite for kerf_silicon.cts (Clock-Tree Synthesis seed).

Run with:
    python -m pytest packages/kerf-silicon/tests/test_cts.py -v

Definition of Done (T-252):
  * counter4 placed fixture (4 register sinks) → H-tree with exactly 2
    branching levels + 3 buffers.
  * Reported max-skew ≤ 50 ps.
  * Forcing an undersized buffer surfaces "violation: cap budget exceeded"
    (negative test).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from kerf_silicon.liberty import parse_file
from kerf_silicon.cts import (
    ClockSink,
    ClockTreeResult,
    build_clock_tree,
    build_htree,
)
from kerf_silicon.cts.buffer_sizing import size_buffers
from kerf_silicon.cts.skew_report import compute_skew

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CTS_FIXTURES = FIXTURES / "cts"
NETLIST_JSON = CTS_FIXTURES / "counter4_placed.netlist.json"
BUFFERS_LIB = CTS_FIXTURES / "cts_buffers.lib"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_sinks() -> list[ClockSink]:
    """Load the 4 register sinks from the counter4 placed fixture."""
    data = json.loads(NETLIST_JSON.read_text())
    sinks = []
    for inst in data["instances"]:
        if inst.get("type") == "register":
            sinks.append(
                ClockSink(
                    instance_name=inst["instance"],
                    x=inst["x"] + inst["width"] / 2.0,  # centre of cell
                    y=inst["y"] + inst["height"] / 2.0,
                    input_cap_pf=inst.get("input_cap_pf", 0.002),
                    cell_name=inst["cell"],
                )
            )
    return sinks


# ---------------------------------------------------------------------------
# H-tree topology tests
# ---------------------------------------------------------------------------

class TestHTreeTopology:
    """Unit tests for the pure H-tree builder."""

    def test_single_sink_is_leaf(self):
        sinks = [ClockSink("FF0", 10.0, 10.0)]
        root = build_htree(sinks)
        assert root.is_leaf
        assert root.sink is not None
        assert root.sink.instance_name == "FF0"

    def test_two_sinks_produce_one_branching_level(self):
        sinks = [ClockSink("FF0", 0.0, 0.0), ClockSink("FF1", 100.0, 0.0)]
        root = build_htree(sinks)
        assert root.is_internal
        assert root.branching_levels() == 1
        assert root.count_buffers() == 1

    def test_four_sinks_produce_two_branching_levels(self):
        """Counter4 H-tree: 4 sinks → 2 branching levels + 3 buffers."""
        sinks = _load_sinks()
        assert len(sinks) == 4
        root = build_htree(sinks)
        assert root.branching_levels() == 2, (
            f"Expected 2 branching levels, got {root.branching_levels()}"
        )
        assert root.count_buffers() == 3, (
            f"Expected 3 internal nodes (buffers), got {root.count_buffers()}"
        )

    def test_four_sinks_four_leaves(self):
        sinks = _load_sinks()
        root = build_htree(sinks)
        leaves = root.leaves()
        assert len(leaves) == 4
        sink_names = {lf.sink.instance_name for lf in leaves}
        assert sink_names == {"FF0", "FF1", "FF2", "FF3"}

    def test_empty_sinks_raises(self):
        with pytest.raises(ValueError, match="empty"):
            build_htree([])

    def test_midpoint_placement(self):
        """Root of a symmetric 4-sink tree should be at the bounding-box centre."""
        sinks = [
            ClockSink("FF0", 0.0, 0.0),
            ClockSink("FF1", 100.0, 0.0),
            ClockSink("FF2", 0.0, 100.0),
            ClockSink("FF3", 100.0, 100.0),
        ]
        root = build_htree(sinks)
        assert abs(root.x - 50.0) < 1e-6, f"Expected root.x=50, got {root.x}"
        assert abs(root.y - 50.0) < 1e-6, f"Expected root.y=50, got {root.y}"


# ---------------------------------------------------------------------------
# Buffer sizing tests
# ---------------------------------------------------------------------------

class TestBufferSizing:
    """Tests for Liberty-driven buffer sizing."""

    @pytest.fixture(scope="class")
    def lib(self):
        return parse_file(BUFFERS_LIB)

    def test_buffer_count_matches_branching_nodes(self, lib):
        sinks = _load_sinks()
        root = build_htree(sinks)
        buffers, violations = size_buffers(root, lib)
        assert len(buffers) == 3, f"Expected 3 buffers, got {len(buffers)}"

    def test_no_violations_for_adequate_cells(self, lib):
        sinks = _load_sinks()
        root = build_htree(sinks)
        _, violations = size_buffers(root, lib)
        assert violations == [], f"Unexpected violations: {violations}"

    def test_buffer_cells_are_from_library(self, lib):
        sinks = _load_sinks()
        root = build_htree(sinks)
        buffers, _ = size_buffers(root, lib)
        cell_names = {c.name for c in lib.cells}
        for buf in buffers:
            assert buf.cell_name in cell_names, (
                f"Buffer cell {buf.cell_name!r} not in library"
            )

    def test_buffer_positions_match_tree_nodes(self, lib):
        """Each buffer should sit at its branching node's (x, y)."""
        sinks = _load_sinks()
        root = build_htree(sinks)
        branches = root.branches()
        buffers, _ = size_buffers(root, lib)

        branch_coords = {(round(b.x, 3), round(b.y, 3)) for b in branches}
        buf_coords = {(round(b.x, 3), round(b.y, 3)) for b in buffers}
        assert buf_coords == branch_coords, (
            f"Buffer positions {buf_coords} do not match branch coords {branch_coords}"
        )

    def test_negative_undersized_buffer_violation(self, lib):
        """Forcing CLKBUF_1 (max_cap 0.05 pF) on a large load must surface a violation."""
        sinks = [
            ClockSink("FF0", 0.0, 0.0, input_cap_pf=0.050),
            ClockSink("FF1", 1000.0, 0.0, input_cap_pf=0.050),
        ]
        root = build_htree(sinks)
        # With 1000 µm wire and 2× 0.05 pF sink caps the load greatly exceeds
        # clkbuf_1's 0.05 pF max.
        _, violations = size_buffers(root, lib, force_cell="sky130_fd_sc_hd__clkbuf_1")
        assert len(violations) >= 1, "Expected at least one cap-budget violation"
        assert any("cap budget exceeded" in v for v in violations), (
            f"Expected 'cap budget exceeded' in violations, got: {violations}"
        )

    def test_force_cell_unknown_raises(self, lib):
        sinks = _load_sinks()
        root = build_htree(sinks)
        with pytest.raises(ValueError, match="not found in library"):
            size_buffers(root, lib, force_cell="nonexistent_cell_xyz")


# ---------------------------------------------------------------------------
# Skew report tests
# ---------------------------------------------------------------------------

class TestSkewReport:
    """Tests for per-sink arrival time and skew computation."""

    @pytest.fixture(scope="class")
    def lib(self):
        return parse_file(BUFFERS_LIB)

    def test_arrivals_count_matches_sink_count(self, lib):
        sinks = _load_sinks()
        root = build_htree(sinks)
        buffers, _ = size_buffers(root, lib)
        report = compute_skew(root, buffers)
        assert len(report.arrivals) == 4

    def test_all_arrivals_positive(self, lib):
        sinks = _load_sinks()
        root = build_htree(sinks)
        buffers, _ = size_buffers(root, lib)
        report = compute_skew(root, buffers)
        for arr in report.arrivals:
            assert arr.arrival_ps >= 0.0, (
                f"Negative arrival for {arr.sink.instance_name}: {arr.arrival_ps}"
            )

    def test_early_and_late_sinks_populated(self, lib):
        sinks = _load_sinks()
        root = build_htree(sinks)
        buffers, _ = size_buffers(root, lib)
        report = compute_skew(root, buffers)
        assert report.early_sink is not None
        assert report.late_sink is not None

    def test_max_skew_is_consistent(self, lib):
        """max_skew_ps should equal late - early arrival."""
        sinks = _load_sinks()
        root = build_htree(sinks)
        buffers, _ = size_buffers(root, lib)
        report = compute_skew(root, buffers)
        late = max(a.arrival_ps for a in report.arrivals)
        early = min(a.arrival_ps for a in report.arrivals)
        assert abs(report.max_skew_ps - (late - early)) < 1e-9

    def test_path_starts_and_ends_at_correct_coords(self, lib):
        sinks = _load_sinks()
        root = build_htree(sinks)
        buffers, _ = size_buffers(root, lib)
        report = compute_skew(root, buffers)
        for arr in report.arrivals:
            # Path should end at the sink's coordinate
            assert len(arr.path) > 0
            last = arr.path[-1]
            assert abs(last[0] - arr.sink.x) < 1e-6
            assert abs(last[1] - arr.sink.y) < 1e-6


# ---------------------------------------------------------------------------
# End-to-end integration: build_clock_tree oracle
# ---------------------------------------------------------------------------

class TestBuildClockTree:
    """Integration tests using the full build_clock_tree() API."""

    @pytest.fixture(scope="class")
    def lib(self):
        return parse_file(BUFFERS_LIB)

    @pytest.fixture(scope="class")
    def result(self, lib):
        return build_clock_tree(_load_sinks(), lib, skew_bound_ps=50.0)

    def test_returns_clock_tree_result(self, result):
        assert isinstance(result, ClockTreeResult)

    def test_exactly_two_branching_levels(self, result):
        """DoD: H-tree has exactly 2 branching levels."""
        assert result.tree.branching_levels() == 2, (
            f"Expected 2 branching levels, got {result.tree.branching_levels()}"
        )

    def test_exactly_three_buffers(self, result):
        """DoD: exactly 3 buffers inserted."""
        assert len(result.buffers) == 3, (
            f"Expected 3 buffers, got {len(result.buffers)}"
        )

    def test_max_skew_within_bound(self, result):
        """DoD: max-skew ≤ 50 ps."""
        assert result.max_skew_ps <= 50.0, (
            f"Max skew {result.max_skew_ps:.2f} ps exceeds 50 ps bound"
        )

    def test_no_violations_in_clean_run(self, result):
        """No constraint violations for the well-sized counter4 fixture."""
        assert result.violations == [], (
            f"Unexpected violations: {result.violations}"
        )

    def test_skew_report_populated(self, result):
        assert len(result.skew_report.arrivals) == 4
        assert result.skew_report.max_skew_ps == result.max_skew_ps

    def test_negative_undersized_triggers_violation(self, lib):
        """DoD negative test: undersized buffer → 'violation: cap budget exceeded'."""
        from kerf_silicon.cts.buffer_sizing import size_buffers

        # Use sinks with large spacing to guarantee high wire cap load.
        sinks = [
            ClockSink("FF0", 0.0, 0.0, input_cap_pf=0.050),
            ClockSink("FF1", 2000.0, 0.0, input_cap_pf=0.050),
        ]
        root = build_htree(sinks)
        _, violations = size_buffers(root, lib, force_cell="sky130_fd_sc_hd__clkbuf_1")
        assert any("cap budget exceeded" in v for v in violations), (
            f"Expected cap-budget violation, got: {violations}"
        )

    def test_skew_bound_violation_when_skew_too_high(self, lib):
        """build_clock_tree should record a skew violation when bound < actual skew."""
        # Use an asymmetric layout so the H-tree produces non-zero skew.
        # Two sinks at very different distances from the midpoint produce
        # measurably different wire delays.
        sinks = [
            ClockSink("FF_NEAR", 0.0, 0.0, input_cap_pf=0.002),
            ClockSink("FF_FAR",  0.0, 1000.0, input_cap_pf=0.002),
            ClockSink("FF_X",   10.0, 0.0, input_cap_pf=0.002),
        ]
        result_loose = build_clock_tree(sinks, lib, skew_bound_ps=50.0)
        # Record what the actual skew is.
        actual_skew = result_loose.max_skew_ps

        # Now tighten the bound to 0 to guarantee a violation.
        result = build_clock_tree(sinks, lib, skew_bound_ps=0.0)
        skew_violations = [v for v in result.violations if "skew" in v]
        if actual_skew > 0.0:
            assert len(skew_violations) >= 1, (
                f"Expected skew violation with 0 ps bound (actual {actual_skew:.2f} ps), "
                f"got: {result.violations}"
            )
        else:
            # Perfectly symmetric tree — bound of 0 is met, no violation expected.
            assert result.violations == []
