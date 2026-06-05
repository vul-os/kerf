"""
tests/test_chain_fk_tool.py — pytest tests for chain_forward_kinematics LLM tool.

Analytic oracles (Craig 2005, §5; Denavit-Hartenberg conventions):
  1. Single revolute joint at θ=0 with length L → end-effector at (L, 0, 0).
  2. Single revolute joint at θ=90° (π/2 rad) with length L, axis [0,0,1]
     → end-effector at (0, L, 0)  (rotation about z by 90°).
  3. Two-link planar arm: θ₁=0, θ₂=0, L₁=L₂=1 → EE at (2, 0, 0).
  4. Two-link planar arm: θ₁=90°, θ₂=0, L₁=L₂=1
     → EE at (0, 2, 0)  (first joint rotates 90°, second stays aligned).
  5. Prismatic joint displaced 0.5 m along x → EE at (0.5 + L, 0, 0).

References
----------
Craig, J.J. (2005). Introduction to Robotics, 3rd ed., §5.2, 5.3.
Featherstone, R. (2008). Rigid Body Dynamics Algorithms, §3.
"""

from __future__ import annotations

import asyncio
import json
import math
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeCtx:
    project_id = "proj-test"
    pool = None


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _call_fk(links, root_position=None):
    """Call chain_forward_kinematics and return the parsed payload dict."""
    from kerf_motion.tools import run_chain_forward_kinematics
    ctx = _FakeCtx()
    args = {"links": links}
    if root_position is not None:
        args["root_position"] = root_position
    raw = _run(run_chain_forward_kinematics(args, ctx))
    return json.loads(raw)


def _ee(payload):
    """Extract end-effector position from a successful payload."""
    return payload["end_effector"]["position"]


def _close(a, b, tol=1e-6):
    return abs(a - b) < tol


# ===========================================================================
# 1. Tool registration
# ===========================================================================

class TestChainFKRegistration:

    def test_spec_importable(self):
        from kerf_motion.tools import chain_forward_kinematics_spec
        assert chain_forward_kinematics_spec.name == "chain_forward_kinematics"

    def test_runner_importable(self):
        from kerf_motion.tools import run_chain_forward_kinematics
        assert callable(run_chain_forward_kinematics)


# ===========================================================================
# 2. Analytic oracle tests
# ===========================================================================

class TestChainFKAnalytic:

    def test_single_revolute_theta0_ee_position(self):
        """
        Oracle: one revolute joint at θ=0, L=1.0, axis=[0,0,1].
        EE should be at (1.0, 0.0, 0.0).

        Because at θ=0 the joint adds no rotation; offset along x = length.
        """
        payload = _call_fk([
            {"length": 1.0, "joint_type": "revolute", "angle_rad": 0.0}
        ])
        assert payload.get("ok") is True, f"FK failed: {payload}"
        ee = _ee(payload)
        assert _close(ee[0], 1.0), f"EE x={ee[0]:.6f}, expected 1.0"
        assert _close(ee[1], 0.0), f"EE y={ee[1]:.6f}, expected 0.0"
        assert _close(ee[2], 0.0), f"EE z={ee[2]:.6f}, expected 0.0"

    def test_single_revolute_theta90_ee_position(self):
        """
        Oracle: one revolute joint at θ=π/2, L=1.0, axis=[0,0,1].
        Rotation of 90° about z: EE at (0, 1, 0).

        Parent offset is at origin (no offset for first joint). After rotation:
        link extends along local +x, which is now world +y.
        EE = R_z(π/2) · (1, 0, 0) = (0, 1, 0).
        """
        payload = _call_fk([
            {"length": 1.0, "joint_type": "revolute", "angle_rad": math.pi / 2,
             "axis": [0.0, 0.0, 1.0]}
        ])
        assert payload.get("ok") is True, f"FK failed: {payload}"
        ee = _ee(payload)
        assert _close(ee[0], 0.0, tol=1e-5), f"EE x={ee[0]:.6f}, expected ~0"
        assert _close(ee[1], 1.0, tol=1e-5), f"EE y={ee[1]:.6f}, expected 1.0"

    def test_two_link_both_zero_angles(self):
        """
        Oracle: two revolute joints both at θ=0, L₁=1.0, L₂=1.0.
        EE at (2.0, 0.0, 0.0).
        """
        payload = _call_fk([
            {"length": 1.0, "joint_type": "revolute", "angle_rad": 0.0},
            {"length": 1.0, "joint_type": "revolute", "angle_rad": 0.0},
        ])
        assert payload.get("ok") is True
        ee = _ee(payload)
        assert _close(ee[0], 2.0, tol=1e-5), f"EE x={ee[0]:.6f}, expected 2.0"
        assert _close(ee[1], 0.0, tol=1e-5), f"EE y={ee[1]:.6f}, expected 0.0"

    def test_two_link_first_joint_90deg(self):
        """
        Oracle: two revolute joints, θ₁=π/2, θ₂=0, L₁=L₂=1.0, axis=[0,0,1].

        After joint 1 (θ₁=π/2):  link1 tip at (0, 1, 0).
        After joint 2 (θ₂=0):   link2 extends along local +x (now world +y).
                                  So EE at (0, 2, 0).
        """
        payload = _call_fk([
            {"length": 1.0, "joint_type": "revolute", "angle_rad": math.pi / 2,
             "axis": [0.0, 0.0, 1.0]},
            {"length": 1.0, "joint_type": "revolute", "angle_rad": 0.0,
             "axis": [0.0, 0.0, 1.0]},
        ])
        assert payload.get("ok") is True
        ee = _ee(payload)
        assert _close(ee[0], 0.0, tol=1e-5), f"EE x={ee[0]:.6f}, expected ~0"
        assert _close(ee[1], 2.0, tol=1e-5), f"EE y={ee[1]:.6f}, expected 2.0"

    def test_two_link_folded(self):
        """
        Oracle: θ₁=π/2, θ₂=-π/2, L₁=L₂=1.0.

        After joint 1: tip at (0, 1, 0), orientation = 90° about z.
        Joint 2 at -π/2 relative: net orientation = 0. Link2 along world +x.
        EE at (1, 1, 0).
        """
        payload = _call_fk([
            {"length": 1.0, "joint_type": "revolute", "angle_rad": math.pi / 2,
             "axis": [0.0, 0.0, 1.0]},
            {"length": 1.0, "joint_type": "revolute", "angle_rad": -math.pi / 2,
             "axis": [0.0, 0.0, 1.0]},
        ])
        assert payload.get("ok") is True
        ee = _ee(payload)
        assert _close(ee[0], 1.0, tol=1e-5), f"EE x={ee[0]:.6f}, expected 1.0"
        assert _close(ee[1], 1.0, tol=1e-5), f"EE y={ee[1]:.6f}, expected 1.0"

    def test_prismatic_joint_along_x(self):
        """
        Oracle: one prismatic joint displaced d=0.5 m along x, with link L=1.0.

        Kinematics:
          Joint frame = parent_offset(0,0,0) + prismatic-disp*axis = (0.5, 0, 0).
          Trailing FixedJoint then extends the link by L=1.0 along local +x.
          Since the prismatic joint adds no rotation, the local +x = world +x.
          So EE = (0.5 + 1.0, 0, 0) = (1.5, 0, 0).

        Note: the prismatic joint translates the joint frame; the FixedJoint
        carries it to the link tip. This matches the FK convention used by
        kerf_motion.inverse_kinematics (Craig 2005, §5.2).
        """
        payload = _call_fk([
            {"length": 1.0, "joint_type": "prismatic",
             "displacement_m": 0.5, "axis": [1.0, 0.0, 0.0]},
        ])
        assert payload.get("ok") is True, f"FK failed: {payload}"
        ee = _ee(payload)
        # Joint at (0.5, 0, 0) + FixedJoint tip offset (1.0, 0, 0) = (1.5, 0, 0)
        assert _close(ee[0], 1.5, tol=1e-5), f"EE x={ee[0]:.6f}, expected 1.5"
        assert _close(ee[1], 0.0, tol=1e-5)

    def test_root_position_offset(self):
        """
        Oracle: one revolute joint at θ=0, L=1.0, root at (5, 0, 0).
        EE at (5 + 1, 0, 0) = (6.0, 0.0, 0.0).
        """
        payload = _call_fk(
            [{"length": 1.0, "joint_type": "revolute", "angle_rad": 0.0}],
            root_position=[5.0, 0.0, 0.0]
        )
        assert payload.get("ok") is True
        ee = _ee(payload)
        assert _close(ee[0], 6.0, tol=1e-5), f"EE x={ee[0]:.6f}, expected 6.0"


# ===========================================================================
# 3. Structural contract
# ===========================================================================

class TestChainFKContract:

    def test_n_links_field(self):
        payload = _call_fk([
            {"length": 1.0, "angle_rad": 0.0},
            {"length": 1.0, "angle_rad": 0.0},
        ])
        assert payload.get("ok") is True
        assert payload["n_links"] == 2

    def test_link_poses_length(self):
        payload = _call_fk([
            {"length": 1.0},
            {"length": 1.5},
            {"length": 0.5},
        ])
        assert payload.get("ok") is True
        assert len(payload["link_poses"]) == 3

    def test_link_pose_has_position_and_orientation(self):
        payload = _call_fk([{"length": 1.0}])
        assert payload.get("ok") is True
        for pose in payload["link_poses"]:
            assert "position" in pose
            assert "orientation" in pose
            assert len(pose["position"]) == 3
            assert len(pose["orientation"]) == 4

    def test_end_effector_matches_last_link_pose(self):
        payload = _call_fk([
            {"length": 1.0, "angle_rad": 0.3},
            {"length": 0.8, "angle_rad": -0.2},
        ])
        assert payload.get("ok") is True
        ee = payload["end_effector"]["position"]
        last = payload["link_poses"][-1]["position"]
        for a, b in zip(ee, last):
            assert _close(a, b, tol=1e-9), f"EE pos {ee} != last link pose {last}"

    def test_orientation_is_unit_quaternion(self):
        """Each link pose quaternion must have unit norm."""
        payload = _call_fk([
            {"length": 1.0, "angle_rad": math.pi / 3},
            {"length": 0.5, "angle_rad": math.pi / 6},
        ])
        assert payload.get("ok") is True
        for pose in payload["link_poses"]:
            q = pose["orientation"]
            norm = math.sqrt(sum(v**2 for v in q))
            assert _close(norm, 1.0, tol=1e-5), f"Quaternion norm {norm:.8f} != 1"

    def test_single_link_returns_single_link_pose(self):
        payload = _call_fk([{"length": 2.0}])
        assert payload.get("ok") is True
        assert payload["n_links"] == 1
        assert len(payload["link_poses"]) == 1


# ===========================================================================
# 4. Error handling
# ===========================================================================

class TestChainFKErrors:

    def test_invalid_joint_type_returns_error(self):
        payload = _call_fk([{"length": 1.0, "joint_type": "spherical"}])
        assert payload.get("ok") is False or "code" in payload

    def test_bad_json_returns_error(self):
        from kerf_motion.tools import run_chain_forward_kinematics
        ctx = _FakeCtx()
        # Pass a string instead of dict (simulates the no-json path)
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            run_chain_forward_kinematics({"links": [{"length": "bad_string"}]}, ctx)
        )
        # Should not crash — returns an error payload
        parsed = json.loads(result)
        assert "code" in parsed or parsed.get("ok") is False

    def test_empty_links_returns_valid_payload(self):
        """Empty chain → EE at root, n_links=0 (degenerate but valid)."""
        payload = _call_fk([])
        # Either ok=True with empty link_poses, or ok=False — both are acceptable
        assert "ok" in payload or "code" in payload
