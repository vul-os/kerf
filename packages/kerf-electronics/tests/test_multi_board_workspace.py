"""
Tests for multi_board/workspace.py — MultiBoardWorkspace, BoardPlacement,
and InterBoardConnector validation logic.

Covers:
  - Basic workspace construction with 2 boards
  - Board 3D STEP assembly text generation
  - Connector mating validation (happy path and failure modes)
  - Board transform matrix + corner computation
  - Bounding-box overlap detection

References verified against:
  Altium Designer Multi-Board Design User Manual §2–5.
  IPC-2581 Rev B §7.4.1-7.4.2.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_electronics.multi_board.workspace import (
    BoardPlacement,
    InterBoardConnector,
    MultiBoardWorkspace,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


def _make_workspace(
    with_connector: bool = True,
    from_pin_count: int = 4,
    to_pin_count: int = 4,
    pin_mapping: dict[int, int] | None = None,
) -> MultiBoardWorkspace:
    """Build a simple two-board workspace used across most tests."""
    board_a = BoardPlacement(
        board_id="cpu_board",
        file_path="boards/cpu.circuitjson",
        position=(0.0, 0.0, 0.0),
        rotation_xyz_deg=(0.0, 0.0, 0.0),
        board_width_mm=100.0,
        board_height_mm=80.0,
    )
    board_b = BoardPlacement(
        board_id="io_board",
        file_path="boards/io.circuitjson",
        position=(200.0, 0.0, 0.0),
        rotation_xyz_deg=(0.0, 0.0, 0.0),
        board_width_mm=80.0,
        board_height_mm=60.0,
    )

    connectors: list[InterBoardConnector] = []
    if with_connector:
        if pin_mapping is None:
            pin_mapping = {1: 1, 2: 2, 3: 3, 4: 4}
        connectors.append(
            InterBoardConnector(
                name="J1-J2 high-speed link",
                from_board="cpu_board",
                from_designator="J1",
                from_pin_count=from_pin_count,
                to_board="io_board",
                to_designator="J2",
                to_pin_count=to_pin_count,
                pin_mapping=pin_mapping,
            )
        )

    return MultiBoardWorkspace(
        workspace_name="Test Assembly",
        boards=[board_a, board_b],
        connectors=connectors,
    )


# ─── Workspace construction ───────────────────────────────────────────────────


class TestBoardPlacement:
    def test_board_placement_stores_fields(self):
        bp = BoardPlacement(
            board_id="cpu_board",
            file_path="boards/cpu.circuitjson",
            position=(10.0, 20.0, 5.0),
            rotation_xyz_deg=(0.0, 0.0, 45.0),
            board_width_mm=150.0,
            board_height_mm=100.0,
        )
        assert bp.board_id == "cpu_board"
        assert bp.position == (10.0, 20.0, 5.0)
        assert bp.rotation_xyz_deg == (0.0, 0.0, 45.0)
        assert bp.board_width_mm == 150.0
        assert bp.board_height_mm == 100.0

    def test_board_placement_default_dimensions(self):
        bp = BoardPlacement(
            board_id="small",
            file_path="x.json",
            position=(0, 0, 0),
            rotation_xyz_deg=(0, 0, 0),
        )
        assert bp.board_width_mm == 100.0
        assert bp.board_height_mm == 80.0


class TestMultiBoardWorkspaceConstruction:
    def test_two_boards_no_connectors_no_issues(self):
        """Two boards with no declared connectors → validate returns empty list."""
        ws = _make_workspace(with_connector=False)
        issues = ws.validate_connector_mating()
        assert issues == [], f"Expected no issues; got: {issues}"

    def test_workspace_stores_both_boards(self):
        ws = _make_workspace(with_connector=False)
        assert len(ws.boards) == 2
        board_ids = {bp.board_id for bp in ws.boards}
        assert "cpu_board" in board_ids
        assert "io_board" in board_ids

    def test_workspace_name_preserved(self):
        ws = _make_workspace(with_connector=False)
        assert ws.workspace_name == "Test Assembly"


# ─── 3D assembly STEP ─────────────────────────────────────────────────────────


class TestBoard3dAssemblyStep:
    def test_step_contains_both_board_ids(self):
        """board_3d_assembly_step output must reference both board identifiers."""
        ws = _make_workspace(with_connector=True)
        step_text = ws.board_3d_assembly_step()
        assert "cpu_board" in step_text
        assert "io_board" in step_text

    def test_step_has_iso_10303_header(self):
        ws = _make_workspace(with_connector=False)
        step_text = ws.board_3d_assembly_step()
        assert "ISO-10303-21" in step_text
        assert "AP242" in step_text

    def test_export_assembly_step_returns_bytes(self):
        ws = _make_workspace(with_connector=True)
        result = ws.export_assembly_step()
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_step_includes_workspace_name(self):
        ws = _make_workspace(with_connector=False)
        step_text = ws.board_3d_assembly_step()
        assert "Test Assembly" in step_text


# ─── Connector mating validation ──────────────────────────────────────────────


class TestConnectorMatingValidation:
    def test_matching_pin_count_no_issues(self):
        """J1(4-pin) ↔ J2(4-pin) with identity mapping → no issues."""
        ws = _make_workspace(from_pin_count=4, to_pin_count=4)
        issues = ws.validate_connector_mating()
        assert issues == []

    def test_pin_count_mismatch_flagged(self):
        """cpu_board J1 has 10 pins but io_board J2 has only 8 → mismatch issue."""
        ws = _make_workspace(
            from_pin_count=10,
            to_pin_count=8,
            pin_mapping={i: i for i in range(1, 11)},
        )
        issues = ws.validate_connector_mating()
        assert any("mismatch" in iss.lower() for iss in issues), (
            f"Expected pin count mismatch issue; got: {issues}"
        )

    def test_missing_from_board_flagged(self):
        ws = _make_workspace(with_connector=False)
        conn = InterBoardConnector(
            name="orphan connector",
            from_board="nonexistent_board",
            from_designator="J1",
            from_pin_count=4,
            to_board="io_board",
            to_designator="J2",
            to_pin_count=4,
            pin_mapping={1: 1, 2: 2, 3: 3, 4: 4},
        )
        ws.connectors.append(conn)
        issues = ws.validate_connector_mating()
        assert any("nonexistent_board" in iss for iss in issues)

    def test_missing_to_board_flagged(self):
        ws = _make_workspace(with_connector=False)
        conn = InterBoardConnector(
            name="bad connector",
            from_board="cpu_board",
            from_designator="J1",
            from_pin_count=4,
            to_board="ghost_board",
            to_designator="J9",
            to_pin_count=4,
            pin_mapping={1: 1, 2: 2, 3: 3, 4: 4},
        )
        ws.connectors.append(conn)
        issues = ws.validate_connector_mating()
        assert any("ghost_board" in iss for iss in issues)

    def test_self_loop_flagged(self):
        """A connector referencing the same board on both sides is invalid."""
        ws = _make_workspace(with_connector=False)
        conn = InterBoardConnector(
            name="self loop",
            from_board="cpu_board",
            from_designator="J1",
            from_pin_count=4,
            to_board="cpu_board",
            to_designator="J2",
            to_pin_count=4,
            pin_mapping={1: 1, 2: 2, 3: 3, 4: 4},
        )
        ws.connectors.append(conn)
        issues = ws.validate_connector_mating()
        assert any("self-loop" in iss.lower() for iss in issues)

    def test_empty_pin_mapping_flagged(self):
        """A connector with no pin_mapping entries carries no nets → issue."""
        ws = _make_workspace(with_connector=False)
        conn = InterBoardConnector(
            name="empty map connector",
            from_board="cpu_board",
            from_designator="J1",
            from_pin_count=4,
            to_board="io_board",
            to_designator="J2",
            to_pin_count=4,
            pin_mapping={},
        )
        ws.connectors.append(conn)
        issues = ws.validate_connector_mating()
        assert any("empty" in iss.lower() or "pin_mapping" in iss for iss in issues)

    def test_pin_exceeds_count_flagged(self):
        """Mapping references pin 12 but from_pin_count=10 → out-of-range issue."""
        ws = _make_workspace(with_connector=False)
        conn = InterBoardConnector(
            name="overrun connector",
            from_board="cpu_board",
            from_designator="J1",
            from_pin_count=10,
            to_board="io_board",
            to_designator="J2",
            to_pin_count=10,
            pin_mapping={12: 1},
        )
        ws.connectors.append(conn)
        issues = ws.validate_connector_mating()
        assert any("12" in iss for iss in issues), f"Expected pin-12 issue; got: {issues}"


# ─── Board transform matrix and corners ───────────────────────────────────────


class TestBoardTransformMatrix:
    def test_identity_placement_corners(self):
        """Board at origin with zero rotation → corners match local frame."""
        ws = _make_workspace(with_connector=False)
        bp = ws.boards[0]  # cpu_board at (0,0,0), 0 rotation, 100×80
        corners = ws.board_corners_in_workspace(bp)
        assert corners.shape == (4, 3)
        # Lower-left corner should be at workspace (0,0,0)
        np.testing.assert_allclose(corners[0], [0.0, 0.0, 0.0], atol=1e-6)
        # Lower-right corner: (100, 0, 0)
        np.testing.assert_allclose(corners[1], [100.0, 0.0, 0.0], atol=1e-6)

    def test_translation_applied_to_corners(self):
        """Board placed at (200, 50, 0) → corners shifted by that offset."""
        ws = _make_workspace(with_connector=False)
        bp = ws.boards[1]  # io_board at (200, 0, 0)
        corners = ws.board_corners_in_workspace(bp)
        # Lower-left should be at (200, 0, 0)
        np.testing.assert_allclose(corners[0], [200.0, 0.0, 0.0], atol=1e-6)

    def test_rotation_90deg_z_corners(self):
        """90° Z rotation: local X becomes workspace Y."""
        bp = BoardPlacement(
            board_id="rotated",
            file_path="",
            position=(0.0, 0.0, 0.0),
            rotation_xyz_deg=(0.0, 0.0, 90.0),
            board_width_mm=100.0,
            board_height_mm=80.0,
        )
        ws = MultiBoardWorkspace(
            workspace_name="rot_test",
            boards=[bp],
            connectors=[],
        )
        corners = ws.board_corners_in_workspace(bp)
        # Lower-right corner in local (100, 0, 0) → after 90° Z rotation → (0, 100, 0)
        np.testing.assert_allclose(corners[1], [0.0, 100.0, 0.0], atol=1e-5)


# ─── Board overlap detection ──────────────────────────────────────────────────


class TestBoardOverlapDetection:
    def test_separated_boards_no_overlap(self):
        """Two boards at (0,0,0) and (200,0,0) with w=100mm → no overlap."""
        ws = _make_workspace(with_connector=False)
        warnings = ws.check_board_overlaps()
        assert warnings == [], f"Expected no overlap; got: {warnings}"

    def test_overlapping_boards_flagged(self):
        """Board at (0,0,0) and (50,0,0) both 100mm wide → they overlap."""
        board_a = BoardPlacement(
            board_id="cpu_board",
            file_path="a.json",
            position=(0.0, 0.0, 0.0),
            rotation_xyz_deg=(0.0, 0.0, 0.0),
            board_width_mm=100.0,
            board_height_mm=80.0,
        )
        board_b = BoardPlacement(
            board_id="io_board",
            file_path="b.json",
            position=(50.0, 0.0, 0.0),
            rotation_xyz_deg=(0.0, 0.0, 0.0),
            board_width_mm=100.0,
            board_height_mm=80.0,
        )
        ws = MultiBoardWorkspace(
            workspace_name="overlap_test",
            boards=[board_a, board_b],
            connectors=[],
        )
        warnings = ws.check_board_overlaps()
        assert len(warnings) > 0
        assert "cpu_board" in warnings[0] or "io_board" in warnings[0]
