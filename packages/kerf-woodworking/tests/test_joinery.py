"""
test_joinery.py — pytest suite for kerf_woodworking.joinery_advanced.

DoD coverage:
  1.  select_joinery for high-load drawer → 'dovetail_half_blind' (or 'mortise_tenon' if load > 5000 N).
  2.  select_joinery for very-high-load structural → 'mortise_tenon'.
  3.  select_joinery for low-load visible → 'dovetail_half_blind'.
  4.  select_joinery for face_frame + low load → 'pocket_screw'.
  5.  select_joinery for medium load + visible → 'dovetail_half_blind'.
  6.  select_joinery for medium load + concealed → 'biscuit_size_20'.
  7.  joinery_machining_operations for dovetail_half_blind returns step list.
  8.  joinery_machining_operations for mortise_tenon returns step list.
  9.  joinery_machining_operations for pocket_screw returns step list.
  10. joinery_machining_operations for biscuit returns step list.
  11. joinery_machining_operations for dowel returns step list.
  12. JoineryConnection can be instantiated with all fields.

References: Stanley (2010); Hoadley (2000); KCMA 2021.
"""

from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_woodworking.joinery_advanced import (
    JoineryConnection,
    JointType,
    select_joinery,
    joinery_machining_operations,
)


# ---------------------------------------------------------------------------
# Test 1–6: select_joinery heuristics
# ---------------------------------------------------------------------------

class TestSelectJoinery:
    # --- Test 1: Drawer with moderate load → dovetail_half_blind ---
    def test_drawer_moderate_load(self):
        """Drawer box at moderate load (500 N) → dovetail_half_blind."""
        jt = select_joinery("drawer_front", "drawer_side", 500.0, "visible")
        assert jt == JointType.DOVETAIL_HALF_BLIND, f"Got {jt}"

    def test_drawer_high_load_dovetail_or_mortise(self):
        """Drawer box at high load (2000 N) → dovetail or mortise."""
        jt = select_joinery("drawer_box", "drawer_side", 2000.0, "visible")
        assert jt in (JointType.DOVETAIL_HALF_BLIND, JointType.MORTISE_TENON), f"Got {jt}"

    # --- Test 2: Very high load structural → mortise_tenon ---
    def test_high_load_structural(self):
        """Structural connection at 6000 N → mortise_tenon."""
        jt = select_joinery("chair_leg", "chair_rail", 6000.0, "structural")
        assert jt == JointType.MORTISE_TENON, f"Got {jt}"

    # --- Test 3: Low load visible → dovetail_half_blind ---
    def test_low_load_visible(self):
        """Low-load visible joint → dovetail_half_blind (decorative)."""
        jt = select_joinery("decorative_shelf", "panel", 50.0, "visible")
        assert jt == JointType.DOVETAIL_HALF_BLIND, f"Got {jt}"

    # --- Test 4: Face frame + low load → pocket_screw ---
    def test_face_frame_low_load(self):
        """Face frame stile to rail at low load → pocket_screw (KCMA standard)."""
        jt = select_joinery("ff_stile", "ff_rail", 100.0, "concealed")
        assert jt == JointType.POCKET_SCREW, f"Got {jt}"

    # --- Test 5: Medium load + visible → dovetail_half_blind ---
    def test_medium_load_visible(self):
        """Medium load + visible → dovetail_half_blind (non-face-frame parts)."""
        jt = select_joinery("shelf_side_panel", "shelf_back_panel", 500.0, "visible")
        assert jt == JointType.DOVETAIL_HALF_BLIND, f"Got {jt}"

    # --- Test 6: Medium load + concealed → biscuit_size_20 ---
    def test_medium_load_concealed(self):
        """Medium load + concealed → biscuit_size_20."""
        jt = select_joinery("panel_a", "panel_b", 500.0, "concealed")
        assert jt == JointType.BISCUIT_SIZE_20, f"Got {jt}"


# ---------------------------------------------------------------------------
# Test 7–11: joinery_machining_operations
# ---------------------------------------------------------------------------

class TestJoineryMachiningOperations:
    def _make_conn(self, joint_type: str, params: dict = None) -> JoineryConnection:
        return JoineryConnection(
            joint_type=joint_type,
            part_a="part_a",
            part_b="part_b",
            location_3d=(0.0, 0.0, 0.0),
            parameters=params or {},
        )

    # --- Test 7: Dovetail half-blind ---
    def test_dovetail_half_blind_ops(self):
        """Dovetail half-blind should return ≥ 3 machining operations."""
        conn = self._make_conn(JointType.DOVETAIL_HALF_BLIND, {
            "tail_count": 4, "tail_angle_deg": 8.0, "board_thickness_mm": 19.0
        })
        ops = joinery_machining_operations(conn)
        assert len(ops) >= 3, f"Expected ≥3 ops, got {len(ops)}"
        # Each op must have required keys
        for op in ops:
            assert "operation" in op
            assert "tool" in op
            assert "description" in op

    # --- Test 8: Mortise-tenon ---
    def test_mortise_tenon_ops(self):
        """Mortise-tenon should return ≥ 4 machining operations."""
        conn = self._make_conn(JointType.MORTISE_TENON, {
            "width_mm": 38.0, "height_mm": 25.0, "depth_mm": 40.0
        })
        ops = joinery_machining_operations(conn)
        assert len(ops) >= 4, f"Expected ≥4 ops for mortise-tenon, got {len(ops)}"
        op_types = [op["operation"] for op in ops]
        assert any("mortise" in ot or "mark" in ot for ot in op_types)
        assert any("tenon" in ot or "saw" in ot for ot in op_types)

    # --- Test 9: Pocket screw ---
    def test_pocket_screw_ops(self):
        """Pocket screw should return ≥ 2 machining operations."""
        conn = self._make_conn(JointType.POCKET_SCREW, {
            "board_thickness_mm": 19.0, "count": 2
        })
        ops = joinery_machining_operations(conn)
        assert len(ops) >= 2
        assert any("pocket" in op["operation"] for op in ops)

    # --- Test 10: Biscuit ---
    def test_biscuit_ops(self):
        """Biscuit joint should return ≥ 2 machining operations."""
        conn = self._make_conn(JointType.BISCUIT_SIZE_20, {"count": 3})
        ops = joinery_machining_operations(conn)
        assert len(ops) >= 2
        assert any("biscuit" in op["tool"] for op in ops)

    # --- Test 11: Dowel ---
    def test_dowel_ops(self):
        """Dowel joint should return ≥ 2 machining operations."""
        conn = self._make_conn(JointType.DOWEL, {
            "diameter_mm": 8.0, "length_mm": 40.0, "count": 3
        })
        ops = joinery_machining_operations(conn)
        assert len(ops) >= 2
        assert any("drill" in op["operation"] or "dowel" in op["operation"] for op in ops)

    # --- Test 12: JoineryConnection instantiation ---
    def test_joinery_connection_instantiation(self):
        """JoineryConnection must instantiate with all required fields."""
        conn = JoineryConnection(
            joint_type=JointType.MORTISE_TENON,
            part_a="stile_left",
            part_b="rail_top",
            location_3d=(100.0, 200.0, 0.0),
            parameters={"width_mm": 38.0, "height_mm": 25.0, "depth_mm": 40.0},
        )
        assert conn.joint_type == JointType.MORTISE_TENON
        assert conn.part_a == "stile_left"
        assert conn.location_3d == (100.0, 200.0, 0.0)
        assert conn.parameters["width_mm"] == 38.0

    def test_loose_tenon_ops(self):
        """Loose tenon (domino) should return ≥ 2 operations."""
        conn = self._make_conn(JointType.LOOSE_TENON, {
            "width_mm": 20.0, "thickness_mm": 10.0, "length_mm": 40.0
        })
        ops = joinery_machining_operations(conn)
        assert len(ops) >= 2
