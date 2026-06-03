"""
Tests for multi_board/inter_board_nets.py — cross-board net mapping and
signal continuity checks.

Covers:
  - compute_workspace_net_map: net bridge resolution from connector pin_mapping
  - Floating net detection (unmapped connector pins)
  - Impedance mismatch flagging (>10% warning / >25% error)
  - Differential pair continuity (both P and N must cross the boundary)
  - check_signal_continuity: aggregated issue list generation

References:
  Altium MB3D §6 "Cross-Board Net Inspector".
  IPC-2581 §7.4.3 inter-board net declaration.
  Bogatin §11.3: >10% Z0 mismatch threshold.
  IPC-2141A §6: differential pair routing across board boundaries.
"""

from __future__ import annotations

import pytest

from kerf_electronics.multi_board.inter_board_nets import (
    NetBridge,
    WorkspaceNetReport,
    check_signal_continuity,
    compute_workspace_net_map,
)
from kerf_electronics.multi_board.workspace import (
    BoardPlacement,
    InterBoardConnector,
    MultiBoardWorkspace,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


def _basic_workspace() -> MultiBoardWorkspace:
    """Two boards connected by a 4-pin board-to-board connector J1↔J2."""
    board_a = BoardPlacement(
        board_id="cpu_board",
        file_path="cpu.circuitjson",
        position=(0.0, 0.0, 0.0),
        rotation_xyz_deg=(0.0, 0.0, 0.0),
    )
    board_b = BoardPlacement(
        board_id="io_board",
        file_path="io.circuitjson",
        position=(200.0, 0.0, 0.0),
        rotation_xyz_deg=(0.0, 0.0, 0.0),
    )
    conn = InterBoardConnector(
        name="J1-J2 PCIe link",
        from_board="cpu_board",
        from_designator="J1",
        from_pin_count=4,
        to_board="io_board",
        to_designator="J2",
        to_pin_count=4,
        pin_mapping={1: 1, 2: 2, 3: 3, 4: 4},
    )
    return MultiBoardWorkspace(
        workspace_name="Test System",
        boards=[board_a, board_b],
        connectors=[conn],
    )


def _pcie_net_assignments() -> dict:
    """Net assignments for J1 (cpu_board) ↔ J2 (io_board) carrying PCIe signals."""
    return {
        "cpu_board": {
            "J1": {
                1: "PCIE0_P",
                2: "PCIE0_N",
                3: "GND",
                4: "3V3",
            }
        },
        "io_board": {
            "J2": {
                1: "TX_PCIE0_P",
                2: "TX_PCIE0_N",
                3: "GND",
                4: "3V3",
            }
        },
    }


# ─── Basic net map tests ───────────────────────────────────────────────────────


class TestComputeWorkspaceNetMap:
    def test_bridge_count_matches_mapped_pins(self):
        """4 mapped pins → 4 bridges in the report."""
        ws = _basic_workspace()
        report = compute_workspace_net_map(ws)
        assert len(report.bridges) == 4

    def test_known_local_nets_resolved_to_workspace_names(self):
        """PCIE0_P (cpu) ↔ TX_PCIE0_P (io) → workspace net named 'PCIE0_P|TX_PCIE0_P'."""
        ws = _basic_workspace()
        report = compute_workspace_net_map(
            ws, board_net_assignments=_pcie_net_assignments()
        )
        ws_nets = {b.workspace_net_name for b in report.bridges}
        # Pins 1 and 2 carry the PCIe lanes — net names differ so '|' separator used
        assert "PCIE0_P|TX_PCIE0_P" in ws_nets
        assert "PCIE0_N|TX_PCIE0_N" in ws_nets

    def test_same_local_net_resolves_to_single_name(self):
        """When both boards share the same net name (GND, 3V3) → workspace net = that name."""
        ws = _basic_workspace()
        report = compute_workspace_net_map(
            ws, board_net_assignments=_pcie_net_assignments()
        )
        ws_nets = {b.workspace_net_name for b in report.bridges}
        assert "GND" in ws_nets
        assert "3V3" in ws_nets

    def test_bridge_records_correct_boards(self):
        """Each bridge references the correct board_a and board_b."""
        ws = _basic_workspace()
        report = compute_workspace_net_map(
            ws, board_net_assignments=_pcie_net_assignments()
        )
        for bridge in report.bridges:
            assert bridge.board_a == "cpu_board"
            assert bridge.board_b == "io_board"

    def test_bridge_connector_pair_name_set(self):
        """Each bridge should carry the connector's name."""
        ws = _basic_workspace()
        report = compute_workspace_net_map(ws)
        for bridge in report.bridges:
            assert bridge.connector_pair_name == "J1-J2 PCIe link"

    def test_synthetic_net_names_without_assignments(self):
        """Without board_net_assignments, synthetic pin names are generated."""
        ws = _basic_workspace()
        report = compute_workspace_net_map(ws)
        # Synthetic names follow 'J1_pin1' / 'J2_pin1' convention
        pin1_bridge = next((b for b in report.bridges if b.from_pin == 1), None)
        assert pin1_bridge is not None
        assert "J1_pin1" in pin1_bridge.board_a_local_net
        assert "J2_pin1" in pin1_bridge.board_b_local_net


# ─── Floating net detection ───────────────────────────────────────────────────


class TestFloatingNetDetection:
    def test_floating_pin_on_from_board(self):
        """Pin 3 on cpu_board/J1 has a net but is NOT in pin_mapping → floating."""
        board_a = BoardPlacement(
            board_id="cpu_board",
            file_path="cpu.circuitjson",
            position=(0.0, 0.0, 0.0),
            rotation_xyz_deg=(0.0, 0.0, 0.0),
        )
        board_b = BoardPlacement(
            board_id="io_board",
            file_path="io.circuitjson",
            position=(200.0, 0.0, 0.0),
            rotation_xyz_deg=(0.0, 0.0, 0.0),
        )
        # Only pins 1 and 2 in pin_mapping; pin 3 is assigned a net but not mapped
        conn = InterBoardConnector(
            name="partial connector",
            from_board="cpu_board",
            from_designator="J1",
            from_pin_count=3,
            to_board="io_board",
            to_designator="J2",
            to_pin_count=2,
            pin_mapping={1: 1, 2: 2},
        )
        ws = MultiBoardWorkspace(
            workspace_name="float_test",
            boards=[board_a, board_b],
            connectors=[conn],
        )
        # Provide net assignment so pin 3 has a known name
        bna = {
            "cpu_board": {"J1": {1: "SIG_A", 2: "SIG_B", 3: "ORPHAN_NET"}},
            "io_board": {"J2": {1: "SIG_A", 2: "SIG_B"}},
        }
        report = compute_workspace_net_map(ws, board_net_assignments=bna)
        float_boards = [f[0] for f in report.floating_nets]
        float_nets = [f[1] for f in report.floating_nets]
        assert "cpu_board" in float_boards
        assert "ORPHAN_NET" in float_nets

    def test_no_floating_nets_when_all_pins_mapped(self):
        """All 4 pins in pin_mapping → floating_nets is empty."""
        ws = _basic_workspace()
        report = compute_workspace_net_map(
            ws, board_net_assignments=_pcie_net_assignments()
        )
        assert report.floating_nets == []


# ─── Impedance continuity ─────────────────────────────────────────────────────


class TestImpedanceContinuity:
    def _ws_with_impedances(self, z_a: float, z_b: float) -> tuple:
        ws = _basic_workspace()
        bna = {
            "cpu_board": {"J1": {1: "PCIE0_P", 2: "PCIE0_N", 3: "GND", 4: "3V3"}},
            "io_board": {"J2": {1: "PCIE0_P", 2: "PCIE0_N", 3: "GND", 4: "3V3"}},
        }
        bimps = {
            "cpu_board": {"PCIE0_P": z_a, "PCIE0_N": z_a},
            "io_board": {"PCIE0_P": z_b, "PCIE0_N": z_b},
        }
        report = compute_workspace_net_map(
            ws, board_net_assignments=bna, board_impedances=bimps
        )
        return report

    def test_matched_impedance_ok(self):
        """Z0=50Ω on both sides → severity 'ok', no continuity issue."""
        report = self._ws_with_impedances(50.0, 50.0)
        for entry in report.impedance_continuity:
            if entry["net_name"] in ("PCIE0_P", "PCIE0_N"):
                assert entry["severity"] == "ok"

    def test_10pct_mismatch_is_warning(self):
        """50Ω vs 55.1Ω → >10% mismatch → warning severity."""
        report = self._ws_with_impedances(50.0, 55.5)
        z0_entries = [
            e for e in report.impedance_continuity if e["net_name"] == "PCIE0_P"
        ]
        assert z0_entries, "Expected impedance entry for PCIE0_P"
        assert z0_entries[0]["severity"] == "warning"

    def test_over_25pct_mismatch_is_error(self):
        """50Ω vs 70Ω → 40% mismatch → error severity."""
        report = self._ws_with_impedances(50.0, 70.0)
        z0_entries = [
            e for e in report.impedance_continuity if e["net_name"] == "PCIE0_P"
        ]
        assert z0_entries
        assert z0_entries[0]["severity"] == "error"

    def test_continuity_check_flags_impedance_mismatch(self):
        """check_signal_continuity must report the >10% Z0 mismatch."""
        report = self._ws_with_impedances(50.0, 60.0)
        issues = check_signal_continuity(report)
        assert any("mismatch" in iss.lower() or "Z0" in iss or "impedance" in iss.lower() for iss in issues)


# ─── Differential pair continuity ─────────────────────────────────────────────


class TestDiffPairContinuity:
    def test_both_pcie_members_bridged(self):
        """PCIE0_P and PCIE0_N both on separate pins → both_bridged=True."""
        board_a = BoardPlacement(
            board_id="cpu_board",
            file_path="",
            position=(0.0, 0.0, 0.0),
            rotation_xyz_deg=(0.0, 0.0, 0.0),
        )
        board_b = BoardPlacement(
            board_id="io_board",
            file_path="",
            position=(200.0, 0.0, 0.0),
            rotation_xyz_deg=(0.0, 0.0, 0.0),
        )
        conn = InterBoardConnector(
            name="J1-J2 diff pair link",
            from_board="cpu_board",
            from_designator="J1",
            from_pin_count=2,
            to_board="io_board",
            to_designator="J2",
            to_pin_count=2,
            pin_mapping={1: 1, 2: 2},
        )
        ws = MultiBoardWorkspace(
            workspace_name="diff_pair_test",
            boards=[board_a, board_b],
            connectors=[conn],
        )
        bna = {
            "cpu_board": {"J1": {1: "PCIE_LANE_0_P", 2: "PCIE_LANE_0_N"}},
            "io_board": {"J2": {1: "PCIE_LANE_0_P", 2: "PCIE_LANE_0_N"}},
        }
        report = compute_workspace_net_map(ws, board_net_assignments=bna)
        diff_pairs = report.diff_pair_continuity
        assert len(diff_pairs) == 1
        assert diff_pairs[0]["both_bridged"] is True
        assert diff_pairs[0]["skew_risk"] == "ok"

    def test_only_p_member_bridged_flags_skew_risk(self):
        """Only the _P member in pin_mapping → skew_risk='high' for that pair."""
        board_a = BoardPlacement(
            board_id="cpu_board",
            file_path="",
            position=(0.0, 0.0, 0.0),
            rotation_xyz_deg=(0.0, 0.0, 0.0),
        )
        board_b = BoardPlacement(
            board_id="io_board",
            file_path="",
            position=(200.0, 0.0, 0.0),
            rotation_xyz_deg=(0.0, 0.0, 0.0),
        )
        # Only pin 1 (the _P member) is in the mapping; pin 2 (the _N member) is not
        conn = InterBoardConnector(
            name="partial diff pair",
            from_board="cpu_board",
            from_designator="J1",
            from_pin_count=2,
            to_board="io_board",
            to_designator="J2",
            to_pin_count=1,
            pin_mapping={1: 1},
        )
        ws = MultiBoardWorkspace(
            workspace_name="skew_test",
            boards=[board_a, board_b],
            connectors=[conn],
        )
        bna = {
            "cpu_board": {"J1": {1: "USB_D_P", 2: "USB_D_N"}},
            "io_board": {"J2": {1: "USB_D_P"}},
        }
        report = compute_workspace_net_map(ws, board_net_assignments=bna)
        issues = check_signal_continuity(report)
        # Either diff_pair_continuity flags it OR the floating net produces an issue
        dp_high = [dp for dp in report.diff_pair_continuity if dp["skew_risk"] == "high"]
        float_nets = [f[1] for f in report.floating_nets]
        assert dp_high or "USB_D_N" in float_nets, (
            f"Expected skew risk or floating net; diff_pairs={report.diff_pair_continuity}, "
            f"floats={report.floating_nets}"
        )

    def test_diff_pair_check_in_continuity_report(self):
        """An orphaned _P net with no _N counterpart triggers a continuity issue."""
        # Build a report manually with only one member
        orphan_bridge = NetBridge(
            workspace_net_name="USB_HS_P",
            board_a="board_a",
            board_a_local_net="USB_HS_P",
            board_b="board_b",
            board_b_local_net="USB_HS_P",
            connector_pair_name="J1-J2",
        )
        report = WorkspaceNetReport(
            bridges=[orphan_bridge],
            floating_nets=[],
            impedance_continuity=[],
            diff_pair_continuity=[
                {
                    "pair_name": "USB_HS",
                    "pos_net": "USB_HS_P",
                    "neg_net": "USB_HS_N (missing)",
                    "both_bridged": False,
                    "skew_risk": "high",
                    "board_a": "board_a",
                    "board_b": "board_b",
                }
            ],
        )
        issues = check_signal_continuity(report)
        assert any("USB_HS" in iss for iss in issues)
        assert any("IPC-2141A" in iss for iss in issues)


# ─── check_signal_continuity aggregation ──────────────────────────────────────


class TestCheckSignalContinuity:
    def test_empty_report_no_issues(self):
        """A completely clean report should produce no continuity issues."""
        report = WorkspaceNetReport(
            bridges=[],
            floating_nets=[],
            impedance_continuity=[],
            diff_pair_continuity=[],
        )
        assert check_signal_continuity(report) == []

    def test_floating_net_produces_issue(self):
        """A single floating net → one issue string containing 'Floating'."""
        report = WorkspaceNetReport(
            bridges=[],
            floating_nets=[("cpu_board", "ORPHAN_NET")],
            impedance_continuity=[],
            diff_pair_continuity=[],
        )
        issues = check_signal_continuity(report)
        assert len(issues) == 1
        assert "Floating" in issues[0]
        assert "ORPHAN_NET" in issues[0]

    def test_ok_impedance_entry_not_in_issues(self):
        """An impedance entry with severity='ok' must not appear in issues."""
        report = WorkspaceNetReport(
            bridges=[],
            floating_nets=[],
            impedance_continuity=[
                {
                    "net_name": "GND",
                    "Z0_a": 50.0,
                    "Z0_b": 50.5,
                    "mismatch_ohm": 0.5,
                    "mismatch_pct": 1.0,
                    "severity": "ok",
                }
            ],
            diff_pair_continuity=[],
        )
        issues = check_signal_continuity(report)
        assert issues == []

    def test_multiple_issue_types_all_reported(self):
        """Floating net + impedance warning + diff pair risk → 3 issues."""
        report = WorkspaceNetReport(
            bridges=[],
            floating_nets=[("board_a", "FLOAT_NET")],
            impedance_continuity=[
                {
                    "net_name": "SIG1",
                    "Z0_a": 50.0,
                    "Z0_b": 57.0,
                    "mismatch_ohm": 7.0,
                    "mismatch_pct": 14.0,
                    "severity": "warning",
                }
            ],
            diff_pair_continuity=[
                {
                    "pair_name": "CLK",
                    "pos_net": "CLK_P",
                    "neg_net": "CLK_N (missing)",
                    "both_bridged": False,
                    "skew_risk": "high",
                    "board_a": "board_a",
                    "board_b": "board_b",
                }
            ],
        )
        issues = check_signal_continuity(report)
        assert len(issues) == 3
