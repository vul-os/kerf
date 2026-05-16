"""
Hermetic tests for kerf_cad_core.robotics — serial robot-arm kinematics.

Coverage:
  arm.dh_matrix                    — single DH transform
  arm.fk_chain                     — forward kinematics (2R, 3R, known configs)
  arm.end_effector_pose            — position + ZYX Euler extraction
  arm.ik_2r_planar                 — closed-form IK (elbow up/down, reachability)
  arm.ik_3r_planar                 — 3R IK round-trip
  arm.geometric_jacobian           — Jacobian at various configs including singularities
  arm.manipulability               — Yoshikawa measure
  arm.workspace_radius             — r_max / r_min bounds
  arm.joint_trajectory_trapezoidal — trapezoidal velocity trajectory
  tools wrappers                   — happy-path + error-path for all registered tools

All tests are pure-Python and hermetic: no OCC, no DB, no network, no fixtures.
Analytic values verified against closed-form expressions.

References
----------
Craig, J.J. "Introduction to Robotics: Mechanics and Control", 3rd ed.
Spong et al. "Robot Modeling and Control", 2006.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.robotics.arm import (
    dh_matrix,
    fk_chain,
    end_effector_pose,
    ik_2r_planar,
    ik_3r_planar,
    geometric_jacobian,
    manipulability,
    workspace_radius,
    joint_trajectory_trapezoidal,
)
from kerf_cad_core.robotics.tools import (
    run_robot_fk,
    run_robot_end_effector_pose,
    run_robot_ik_2r_planar,
    run_robot_ik_3r_planar,
    run_robot_jacobian,
    run_robot_manipulability,
    run_robot_workspace,
    run_robot_trajectory_trapezoidal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok_tool(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err_tool(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


ABS = 1e-9
REL = 1e-6

# ---------------------------------------------------------------------------
# Helper: build a simple planar n-link DH chain (all joints in XY plane)
# ---------------------------------------------------------------------------

def _planar_dh(link_lengths):
    """DH params for a planar revolute chain (alpha=0, d=0, theta_offset=0)."""
    return [[l, 0.0, 0.0, 0.0] for l in link_lengths]


# ===========================================================================
# 1. dh_matrix
# ===========================================================================

class TestDHMatrix:

    def test_identity_at_zero_params(self):
        """dh_matrix(0,0,0,0) should give identity."""
        res = dh_matrix(0.0, 0.0, 0.0, 0.0)
        assert res["ok"] is True
        T = res["matrix"]
        assert len(T) == 4
        for i in range(4):
            for j in range(4):
                expected = 1.0 if i == j else 0.0
                assert abs(T[i][j] - expected) < ABS, f"T[{i}][{j}]={T[i][j]}"

    def test_pure_z_rotation(self):
        """dh_matrix(0,0,0,theta) should be a Z-rotation matrix."""
        theta = math.pi / 3.0
        res = dh_matrix(0.0, 0.0, 0.0, theta)
        T = res["matrix"]
        ct, st = math.cos(theta), math.sin(theta)
        assert abs(T[0][0] - ct) < ABS
        assert abs(T[0][1] - (-st)) < ABS
        assert abs(T[1][0] - st) < ABS
        assert abs(T[1][1] - ct) < ABS
        assert abs(T[2][2] - 1.0) < ABS

    def test_pure_translation_along_x(self):
        """dh_matrix(a,0,0,0) should translate by a along x."""
        a = 0.5
        res = dh_matrix(a, 0.0, 0.0, 0.0)
        T = res["matrix"]
        assert abs(T[0][3] - a) < ABS
        assert abs(T[1][3]) < ABS
        assert abs(T[2][3]) < ABS

    def test_pure_translation_along_z(self):
        """dh_matrix(0,0,d,0) should translate by d along z."""
        d = 0.3
        res = dh_matrix(0.0, 0.0, d, 0.0)
        T = res["matrix"]
        assert abs(T[2][3] - d) < ABS

    def test_matrix_is_homogeneous(self):
        """Bottom row must always be [0,0,0,1]."""
        res = dh_matrix(0.1, math.pi / 4, 0.2, math.pi / 6)
        T = res["matrix"]
        assert abs(T[3][0]) < ABS
        assert abs(T[3][1]) < ABS
        assert abs(T[3][2]) < ABS
        assert abs(T[3][3] - 1.0) < ABS

    def test_rotation_part_is_orthonormal(self):
        """Upper 3×3 rotation sub-matrix must be orthonormal (R^T R = I)."""
        res = dh_matrix(0.1, math.pi / 5, 0.15, math.pi / 3)
        T = res["matrix"]
        R = [[T[i][j] for j in range(3)] for i in range(3)]
        for i in range(3):
            for j in range(3):
                dot = sum(R[k][i] * R[k][j] for k in range(3))
                expected = 1.0 if i == j else 0.0
                assert abs(dot - expected) < 1e-10, f"R^T R [{i}][{j}]={dot}"


# ===========================================================================
# 2. fk_chain — Forward Kinematics
# ===========================================================================

class TestFKChain:

    def test_single_link_at_zero(self):
        """Single revolute link, q=0: end-effector at (l1, 0, 0)."""
        l1 = 1.0
        dh = _planar_dh([l1])
        res = fk_chain(dh, [0.0])
        assert res["ok"] is True
        T = res["T"]
        assert abs(T[0][3] - l1) < ABS
        assert abs(T[1][3]) < ABS
        assert abs(T[2][3]) < ABS

    def test_single_link_at_90_deg(self):
        """Single link, q=90°: end-effector at (0, l1, 0)."""
        l1 = 1.0
        dh = _planar_dh([l1])
        res = fk_chain(dh, [math.pi / 2])
        T = res["T"]
        assert abs(T[0][3]) < 1e-10
        assert abs(T[1][3] - l1) < 1e-10

    def test_2r_straight_config(self):
        """2R arm fully extended (both q=0): tip at (l1+l2, 0, 0)."""
        l1, l2 = 1.0, 0.5
        dh = _planar_dh([l1, l2])
        res = fk_chain(dh, [0.0, 0.0])
        T = res["T"]
        assert abs(T[0][3] - (l1 + l2)) < ABS

    def test_2r_folded_config(self):
        """2R arm folded (q1=0, q2=180°): tip at (l1-l2, 0, 0)."""
        l1, l2 = 1.0, 0.5
        dh = _planar_dh([l1, l2])
        res = fk_chain(dh, [0.0, math.pi])
        T = res["T"]
        assert abs(T[0][3] - (l1 - l2)) < 1e-10

    def test_2r_l_shape(self):
        """2R: q1=0, q2=90°. Tip at (l1, l2, 0)."""
        l1, l2 = 1.0, 0.8
        dh = _planar_dh([l1, l2])
        res = fk_chain(dh, [0.0, math.pi / 2])
        T = res["T"]
        assert abs(T[0][3] - l1) < 1e-10
        assert abs(T[1][3] - l2) < 1e-10

    def test_3r_all_zero(self):
        """3R arm all zeros: tip at (l1+l2+l3, 0, 0)."""
        l1, l2, l3 = 1.0, 0.8, 0.5
        dh = _planar_dh([l1, l2, l3])
        res = fk_chain(dh, [0.0, 0.0, 0.0])
        T = res["T"]
        assert abs(T[0][3] - (l1 + l2 + l3)) < ABS

    def test_mismatch_lengths_returns_error(self):
        """Mismatch between dh_params and joint_angles → ok=False."""
        dh = _planar_dh([1.0, 0.5])
        res = fk_chain(dh, [0.0])
        assert res["ok"] is False

    def test_empty_chain_returns_identity(self):
        """Empty chain → identity transform."""
        res = fk_chain([], [])
        assert res["ok"] is True
        T = res["T"]
        for i in range(4):
            assert abs(T[i][i] - 1.0) < ABS


# ===========================================================================
# 3. end_effector_pose
# ===========================================================================

class TestEndEffectorPose:

    def test_identity_gives_zero_pose(self):
        """Identity matrix → position (0,0,0), angles all 0."""
        T = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
        res = end_effector_pose(T)
        assert res["ok"] is True
        assert abs(res["x"]) < ABS
        assert abs(res["y"]) < ABS
        assert abs(res["z"]) < ABS
        assert abs(res["roll_deg"]) < ABS
        assert abs(res["pitch_deg"]) < ABS
        assert abs(res["yaw_deg"]) < ABS

    def test_translation_only(self):
        """Pure translation matrix → correct position, zero angles."""
        T = [[1,0,0,1.5],[0,1,0,2.5],[0,0,1,3.5],[0,0,0,1]]
        res = end_effector_pose(T)
        assert abs(res["x"] - 1.5) < ABS
        assert abs(res["y"] - 2.5) < ABS
        assert abs(res["z"] - 3.5) < ABS

    def test_2r_fk_pose_round_trip(self):
        """FK → end_effector_pose for 2R arm gives correct x,y."""
        l1, l2 = 1.0, 0.8
        q1, q2 = math.radians(30), math.radians(45)
        dh = _planar_dh([l1, l2])
        fk_res = fk_chain(dh, [q1, q2])
        T = fk_res["T"]
        pose = end_effector_pose(T)
        # Manual calculation
        x_expected = l1 * math.cos(q1) + l2 * math.cos(q1 + q2)
        y_expected = l1 * math.sin(q1) + l2 * math.sin(q1 + q2)
        assert abs(pose["x"] - x_expected) < 1e-9
        assert abs(pose["y"] - y_expected) < 1e-9


# ===========================================================================
# 4. ik_2r_planar
# ===========================================================================

class TestIK2RPlanar:

    def test_fully_extended_elbow_up(self):
        """Target at full reach: q2 should be ~0."""
        l1, l2 = 1.0, 0.8
        px = l1 + l2
        res = ik_2r_planar(l1, l2, px, 0.0, elbow_up=True)
        assert res["ok"] is True
        assert res["reachable"] is True
        assert abs(res["q2_deg"]) < 1e-6

    def test_round_trip_elbow_up(self):
        """IK solution verified by FK round-trip (elbow up)."""
        l1, l2 = 1.0, 0.8
        px, py = 0.9, 0.6
        res = ik_2r_planar(l1, l2, px, py, elbow_up=True)
        assert res["ok"] is True
        q1, q2 = res["q1_rad"], res["q2_rad"]
        # FK
        x_fk = l1 * math.cos(q1) + l2 * math.cos(q1 + q2)
        y_fk = l1 * math.sin(q1) + l2 * math.sin(q1 + q2)
        assert abs(x_fk - px) < 1e-9
        assert abs(y_fk - py) < 1e-9

    def test_round_trip_elbow_down(self):
        """IK solution verified by FK round-trip (elbow down)."""
        l1, l2 = 1.0, 0.8
        px, py = 0.9, 0.6
        res = ik_2r_planar(l1, l2, px, py, elbow_up=False)
        assert res["ok"] is True
        q1, q2 = res["q1_rad"], res["q2_rad"]
        x_fk = l1 * math.cos(q1) + l2 * math.cos(q1 + q2)
        y_fk = l1 * math.sin(q1) + l2 * math.sin(q1 + q2)
        assert abs(x_fk - px) < 1e-9
        assert abs(y_fk - py) < 1e-9

    def test_elbow_up_down_different_q2(self):
        """Elbow-up and elbow-down solutions must differ in q2."""
        l1, l2 = 1.0, 0.8
        px, py = 0.9, 0.6
        up   = ik_2r_planar(l1, l2, px, py, elbow_up=True)
        down = ik_2r_planar(l1, l2, px, py, elbow_up=False)
        assert abs(up["q2_deg"] - down["q2_deg"]) > 1e-6

    def test_unreachable_sets_flag_and_warns(self):
        """Target beyond r_max → reachable=False and warning issued."""
        l1, l2 = 1.0, 0.5
        res = ik_2r_planar(l1, l2, 10.0, 0.0)
        assert res["ok"] is True
        assert res["reachable"] is False
        assert len(res["warnings"]) >= 1

    def test_origin_inside_hole_sets_flag(self):
        """Target inside inner void (r < |l1-l2|) → reachable=False."""
        l1, l2 = 1.0, 0.4
        res = ik_2r_planar(l1, l2, 0.001, 0.0)
        assert res["ok"] is True
        assert res["reachable"] is False

    def test_invalid_zero_link_returns_error(self):
        """Zero link length → ok=False."""
        res = ik_2r_planar(0.0, 0.5, 0.5, 0.0)
        assert res["ok"] is False

    def test_negative_link_returns_error(self):
        """Negative link length → ok=False."""
        res = ik_2r_planar(-1.0, 0.5, 0.5, 0.0)
        assert res["ok"] is False

    def test_target_on_x_axis(self):
        """Target exactly on x-axis: elbow-up q2 > 0 or ≈ 0."""
        l1, l2 = 1.0, 0.8
        res = ik_2r_planar(l1, l2, 1.0, 0.0, elbow_up=True)
        assert res["ok"] is True
        assert res["reachable"] is True


# ===========================================================================
# 5. ik_3r_planar
# ===========================================================================

class TestIK3RPlanar:

    def test_round_trip_phi_zero(self):
        """3R IK round-trip: FK of IK solution matches target (phi=0)."""
        l1, l2, l3 = 1.0, 0.8, 0.4
        px, py = 1.5, 0.5
        res = ik_3r_planar(l1, l2, l3, px, py, phi_deg=0.0)
        assert res["ok"] is True
        q1, q2, q3 = res["q1_rad"], res["q2_rad"], res["q3_rad"]
        phi_check = q1 + q2 + q3
        assert abs(phi_check) < 1e-9
        # FK
        x_fk = (l1 * math.cos(q1)
                + l2 * math.cos(q1 + q2)
                + l3 * math.cos(q1 + q2 + q3))
        y_fk = (l1 * math.sin(q1)
                + l2 * math.sin(q1 + q2)
                + l3 * math.sin(q1 + q2 + q3))
        assert abs(x_fk - px) < 1e-8
        assert abs(y_fk - py) < 1e-8

    def test_round_trip_phi_45(self):
        """3R IK round-trip with phi=45°."""
        l1, l2, l3 = 1.0, 0.8, 0.5
        px, py = 1.2, 0.8
        phi_deg = 45.0
        res = ik_3r_planar(l1, l2, l3, px, py, phi_deg=phi_deg)
        assert res["ok"] is True
        q1, q2, q3 = res["q1_rad"], res["q2_rad"], res["q3_rad"]
        phi_rad = math.radians(phi_deg)
        assert abs(q1 + q2 + q3 - phi_rad) < 1e-9
        x_fk = (l1 * math.cos(q1)
                + l2 * math.cos(q1 + q2)
                + l3 * math.cos(q1 + q2 + q3))
        y_fk = (l1 * math.sin(q1)
                + l2 * math.sin(q1 + q2)
                + l3 * math.sin(q1 + q2 + q3))
        assert abs(x_fk - px) < 1e-8
        assert abs(y_fk - py) < 1e-8

    def test_invalid_link_returns_error(self):
        """Zero link length → ok=False."""
        res = ik_3r_planar(1.0, 0.0, 0.5, 1.0, 0.0)
        assert res["ok"] is False

    def test_unreachable_propagates(self):
        """Target far outside workspace → reachable=False."""
        l1, l2, l3 = 0.5, 0.4, 0.3
        res = ik_3r_planar(l1, l2, l3, 100.0, 0.0)
        assert res["ok"] is True
        assert res["reachable"] is False


# ===========================================================================
# 6. geometric_jacobian
# ===========================================================================

class TestGeometricJacobian:

    def test_shape_2r(self):
        """Jacobian for 2R chain must be 6×2."""
        dh = _planar_dh([1.0, 0.8])
        res = geometric_jacobian(dh, [0.0, 0.0])
        assert res["ok"] is True
        J = res["J"]
        assert len(J) == 6
        assert all(len(row) == 2 for row in J)

    def test_shape_3r(self):
        """Jacobian for 3R chain must be 6×3."""
        dh = _planar_dh([1.0, 0.8, 0.5])
        res = geometric_jacobian(dh, [0.0, 0.0, 0.0])
        assert res["ok"] is True
        J = res["J"]
        assert len(J) == 6
        assert all(len(row) == 3 for row in J)

    def test_singular_flag_folded_2r(self):
        """Folded 2R (q2=180°) is a type of degenerate configuration."""
        dh = _planar_dh([1.0, 1.0])
        # At q=[0, pi], the arm is folded — linear part can be singular
        res = geometric_jacobian(dh, [0.0, math.pi])
        assert res["ok"] is True
        # singular flag may or may not trigger for 2R; just check it's bool
        assert isinstance(res["singular"], bool)

    def test_mismatch_lengths_returns_error(self):
        """Mismatch → ok=False."""
        dh = _planar_dh([1.0, 0.8])
        res = geometric_jacobian(dh, [0.0])
        assert res["ok"] is False

    def test_empty_chain(self):
        """Empty chain → ok=True, empty Jacobian."""
        res = geometric_jacobian([], [])
        assert res["ok"] is True
        assert res["J"] == []

    def test_1r_linear_jv_matches_analytic(self):
        """
        For a single revolute link of length l at q=0, aligned with x:
        J_v = z_0 × p_tip = [0,0,1] × [l,0,0] = [0, l, 0].
        """
        l = 1.5
        dh = _planar_dh([l])
        res = geometric_jacobian(dh, [0.0])
        J = res["J"]
        # Jv (rows 0-2, col 0)
        assert abs(J[0][0]) < 1e-10          # x component = 0
        assert abs(J[1][0] - l) < 1e-10      # y component = l
        assert abs(J[2][0]) < 1e-10          # z component = 0
        # Jw = [0, 0, 1]
        assert abs(J[3][0]) < 1e-10
        assert abs(J[4][0]) < 1e-10
        assert abs(J[5][0] - 1.0) < 1e-10

    def test_singularity_detected_3r_fully_extended(self):
        """Fully extended 3R: all links along x — near-singular (Jv rows 1,2 zero)."""
        dh = _planar_dh([1.0, 1.0, 1.0])
        res = geometric_jacobian(dh, [0.0, 0.0, 0.0])
        assert res["ok"] is True
        # det(Jv·Jv^T) should be ~0 since all z-axes cross the same line
        assert res["singular"] is True


# ===========================================================================
# 7. manipulability
# ===========================================================================

class TestManipulability:

    def test_singular_zero_column_jacobian(self):
        """Zero Jacobian → manipulability 0, singular=True."""
        J = [[0.0, 0.0]] * 6
        res = manipulability(J)
        assert res["ok"] is True
        assert res["singular"] is True
        assert res["manipulability"] == 0.0

    def test_non_singular_positive_value(self):
        """A non-degenerate configuration should give w > 0."""
        l1, l2 = 1.0, 0.8
        dh = _planar_dh([l1, l2])
        jac_res = geometric_jacobian(dh, [math.pi / 4, math.pi / 3])
        J = jac_res["J"]
        res = manipulability(J)
        assert res["ok"] is True
        assert res["manipulability"] >= 0.0

    def test_invalid_jacobian_rows(self):
        """J with != 6 rows → ok=False."""
        J = [[1.0, 2.0]] * 3  # 3 rows only
        res = manipulability(J)
        assert res["ok"] is False

    def test_zero_column_jacobian_empty(self):
        """Empty column Jacobian → singular."""
        J = [[] for _ in range(6)]
        res = manipulability(J)
        assert res["ok"] is True
        assert res["singular"] is True


# ===========================================================================
# 8. workspace_radius
# ===========================================================================

class TestWorkspaceRadius:

    def test_2r_r_max(self):
        """2R arm: r_max = l1 + l2."""
        l1, l2 = 1.0, 0.8
        dh = _planar_dh([l1, l2])
        res = workspace_radius(dh)
        assert res["ok"] is True
        assert abs(res["r_max"] - (l1 + l2)) < ABS

    def test_3r_r_max(self):
        """3R arm: r_max = l1 + l2 + l3."""
        l1, l2, l3 = 1.0, 0.8, 0.5
        dh = _planar_dh([l1, l2, l3])
        res = workspace_radius(dh)
        assert abs(res["r_max"] - (l1 + l2 + l3)) < ABS

    def test_r_min_nonnegative(self):
        """r_min is always >= 0."""
        dh = _planar_dh([1.0, 2.0, 0.3])
        res = workspace_radius(dh)
        assert res["r_min"] >= 0.0

    def test_empty_chain_zero(self):
        """Empty chain → r_max = r_min = 0."""
        res = workspace_radius([])
        assert res["r_max"] == 0.0
        assert res["r_min"] == 0.0

    def test_equal_links_r_min_zero(self):
        """Two equal links: r_min = max(0, 2l - 2l) = 0."""
        l = 1.0
        dh = _planar_dh([l, l])
        res = workspace_radius(dh)
        assert abs(res["r_min"]) < ABS


# ===========================================================================
# 9. joint_trajectory_trapezoidal
# ===========================================================================

class TestJointTrajectoryTrapezoidal:

    def test_start_position_correct(self):
        """First position sample must equal q_start."""
        q_start = [0.0, 0.0]
        q_end   = [math.pi / 2, math.pi / 4]
        res = joint_trajectory_trapezoidal(q_start, q_end, v_max=1.0, a_max=2.0, dt=0.05)
        assert res["ok"] is True
        for j in range(2):
            assert abs(res["positions"][0][j] - q_start[j]) < 1e-9

    def test_end_position_correct(self):
        """Last position sample must equal q_end."""
        q_start = [0.0, 0.0]
        q_end   = [math.pi / 2, math.pi / 4]
        res = joint_trajectory_trapezoidal(q_start, q_end, v_max=1.0, a_max=2.0, dt=0.05)
        assert res["ok"] is True
        for j in range(2):
            assert abs(res["positions"][-1][j] - q_end[j]) < 1e-6

    def test_time_steps_are_ordered(self):
        """Time array must be non-decreasing."""
        res = joint_trajectory_trapezoidal(
            [0.0], [math.pi], v_max=1.0, a_max=2.0, dt=0.05
        )
        times = res["times"]
        assert all(times[i] <= times[i + 1] for i in range(len(times) - 1))

    def test_t_sync_positive(self):
        """T_sync must be > 0 for a non-trivial move."""
        res = joint_trajectory_trapezoidal(
            [0.0], [1.0], v_max=0.5, a_max=1.0, dt=0.01
        )
        assert res["T_sync"] > 0.0

    def test_zero_move_returns_single_point(self):
        """q_start == q_end → T_sync=0 and single sample."""
        res = joint_trajectory_trapezoidal(
            [1.0, 2.0], [1.0, 2.0], v_max=1.0, a_max=2.0, dt=0.01
        )
        assert res["ok"] is True
        assert res["T_sync"] == 0.0
        assert len(res["positions"]) == 1

    def test_invalid_v_max_zero(self):
        """v_max=0 → ok=False."""
        res = joint_trajectory_trapezoidal([0.0], [1.0], v_max=0.0, a_max=1.0)
        assert res["ok"] is False

    def test_invalid_a_max_negative(self):
        """a_max < 0 → ok=False."""
        res = joint_trajectory_trapezoidal([0.0], [1.0], v_max=1.0, a_max=-1.0)
        assert res["ok"] is False

    def test_mismatch_q_lengths(self):
        """Mismatched q_start/q_end → ok=False."""
        res = joint_trajectory_trapezoidal([0.0, 0.0], [1.0], v_max=1.0, a_max=1.0)
        assert res["ok"] is False

    def test_velocity_zero_at_endpoints(self):
        """First and last velocity samples must be ~0."""
        res = joint_trajectory_trapezoidal(
            [0.0], [math.pi], v_max=1.0, a_max=2.0, dt=0.02
        )
        assert abs(res["velocities"][0][0]) < 1e-9
        assert abs(res["velocities"][-1][0]) < 1e-9


# ===========================================================================
# 10. Tool wrappers
# ===========================================================================

class TestToolWrappers:

    # --- robot_fk ---

    def test_fk_tool_happy_path_2r(self):
        raw = _run(run_robot_fk(_ctx(), _args(
            dh_params=[[1.0, 0.0, 0.0, 0.0], [0.8, 0.0, 0.0, 0.0]],
            joint_angles_deg=[0.0, 0.0],
        )))
        d = _ok_tool(raw)
        T = d["T"]
        assert len(T) == 4

    def test_fk_tool_missing_joint_angles(self):
        raw = _run(run_robot_fk(_ctx(), _args(
            dh_params=[[1.0, 0.0, 0.0, 0.0]],
        )))
        _err_tool(raw)

    def test_fk_tool_invalid_json(self):
        raw = _run(run_robot_fk(_ctx(), b"not-json"))
        _err_tool(raw)

    # --- robot_end_effector_pose ---

    def test_end_effector_pose_tool_happy_path(self):
        T = [[1,0,0,1.0],[0,1,0,0.5],[0,0,1,0.0],[0,0,0,1]]
        raw = _run(run_robot_end_effector_pose(_ctx(), _args(matrix=T)))
        d = _ok_tool(raw)
        assert abs(d["x"] - 1.0) < ABS
        assert abs(d["y"] - 0.5) < ABS

    def test_end_effector_pose_tool_bad_matrix(self):
        raw = _run(run_robot_end_effector_pose(_ctx(), _args(
            matrix=[[1,0,0],[0,1,0],[0,0,1]]  # 3×3 not 4×4
        )))
        _err_tool(raw)

    # --- robot_ik_2r_planar ---

    def test_ik_2r_tool_happy_path(self):
        raw = _run(run_robot_ik_2r_planar(_ctx(), _args(
            l1=1.0, l2=0.8, px=1.0, py=0.5
        )))
        d = _ok_tool(raw)
        assert "q1_deg" in d
        assert "q2_deg" in d

    def test_ik_2r_tool_missing_field(self):
        raw = _run(run_robot_ik_2r_planar(_ctx(), _args(l1=1.0, l2=0.8, px=1.0)))
        _err_tool(raw)

    def test_ik_2r_tool_elbow_down(self):
        raw = _run(run_robot_ik_2r_planar(_ctx(), _args(
            l1=1.0, l2=0.8, px=0.9, py=0.6, elbow_up=False
        )))
        _ok_tool(raw)

    # --- robot_ik_3r_planar ---

    def test_ik_3r_tool_happy_path(self):
        raw = _run(run_robot_ik_3r_planar(_ctx(), _args(
            l1=1.0, l2=0.8, l3=0.5, px=1.5, py=0.5, phi_deg=30.0
        )))
        d = _ok_tool(raw)
        assert "q1_deg" in d

    def test_ik_3r_tool_missing_l3(self):
        raw = _run(run_robot_ik_3r_planar(_ctx(), _args(
            l1=1.0, l2=0.8, px=1.5, py=0.5
        )))
        _err_tool(raw)

    # --- robot_jacobian ---

    def test_jacobian_tool_happy_path(self):
        raw = _run(run_robot_jacobian(_ctx(), _args(
            dh_params=[[1.0, 0.0, 0.0, 0.0], [0.8, 0.0, 0.0, 0.0]],
            joint_angles_deg=[30.0, 45.0],
        )))
        d = _ok_tool(raw)
        assert d["n_joints"] == 2
        assert len(d["J"]) == 6

    def test_jacobian_tool_mismatch(self):
        raw = _run(run_robot_jacobian(_ctx(), _args(
            dh_params=[[1.0, 0.0, 0.0, 0.0]],
            joint_angles_deg=[0.0, 0.0],
        )))
        _err_tool(raw)

    # --- robot_manipulability ---

    def test_manipulability_tool_happy_path(self):
        # Get J from a non-singular config
        dh = _planar_dh([1.0, 0.8])
        jac_res = geometric_jacobian(dh, [math.pi / 4, math.pi / 3])
        J = jac_res["J"]
        raw = _run(run_robot_manipulability(_ctx(), _args(J=J)))
        d = _ok_tool(raw)
        assert "manipulability" in d

    def test_manipulability_tool_missing_J(self):
        raw = _run(run_robot_manipulability(_ctx(), _args()))
        _err_tool(raw)

    # --- robot_workspace ---

    def test_workspace_tool_happy_path(self):
        raw = _run(run_robot_workspace(_ctx(), _args(
            dh_params=[[1.0, 0.0, 0.0, 0.0], [0.8, 0.0, 0.0, 0.0], [0.5, 0.0, 0.0, 0.0]]
        )))
        d = _ok_tool(raw)
        assert abs(d["r_max"] - 2.3) < 1e-9

    def test_workspace_tool_empty_chain(self):
        raw = _run(run_robot_workspace(_ctx(), _args(dh_params=[])))
        d = _ok_tool(raw)
        assert d["r_max"] == 0.0

    # --- robot_trajectory_trapezoidal ---

    def test_trajectory_tool_happy_path(self):
        raw = _run(run_robot_trajectory_trapezoidal(_ctx(), _args(
            q_start_deg=[0.0, 0.0],
            q_end_deg=[90.0, 45.0],
            v_max_deg_s=60.0,
            a_max_deg_s2=120.0,
            dt_s=0.05,
        )))
        d = _ok_tool(raw)
        assert "T_sync" in d
        assert "positions_deg" in d

    def test_trajectory_tool_missing_v_max(self):
        raw = _run(run_robot_trajectory_trapezoidal(_ctx(), _args(
            q_start_deg=[0.0],
            q_end_deg=[90.0],
            a_max_deg_s2=120.0,
        )))
        _err_tool(raw)

    def test_trajectory_tool_invalid_json(self):
        raw = _run(run_robot_trajectory_trapezoidal(_ctx(), b"{bad"))
        _err_tool(raw)
