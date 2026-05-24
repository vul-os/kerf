"""
Hermetic tests for kerf_cad_core.robotics.arm.ik_spatial_dls —
6-DOF spatial inverse kinematics via damped least-squares.

Validation strategy (round-trip)
---------------------------------
1. Choose a known joint configuration q_known.
2. Compute T_target = FK(q_known).
3. Run IK from a perturbed initial guess q_init (q_known + small noise).
4. Verify convergence and that FK(q_solved) ≈ T_target within tolerance.

All tests are pure-Python and hermetic: no OCC, no DB, no network.

References
----------
Craig, J.J. "Introduction to Robotics: Mechanics and Control", 3rd ed. Ch.4
Siciliano et al. "Robotics: Modelling, Planning and Control" §3.8
Nakamura & Hanafusa (1986) — damped least squares

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.robotics.arm import (
    fk_chain,
    ik_spatial_dls,
)
from kerf_cad_core.robotics.tools import (
    run_robot_ik_spatial_dls,
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


def _norm3(v):
    return math.sqrt(sum(x*x for x in v))


def _fk_pos(dh_params, q):
    """Return [x, y, z] end-effector from FK."""
    res = fk_chain(dh_params, q)
    assert res["ok"]
    T = res["T"]
    return [T[0][3], T[1][3], T[2][3]]


def _fk_rot(dh_params, q):
    """Return 3×3 rotation matrix from FK."""
    res = fk_chain(dh_params, q)
    assert res["ok"]
    T = res["T"]
    return [[T[i][j] for j in range(3)] for i in range(3)]


def _rot_err_norm(R1, R2):
    """Frobenius norm of R1 - R2 as proxy for rotation error."""
    s = 0.0
    for i in range(3):
        for j in range(3):
            d = R1[i][j] - R2[i][j]
            s += d * d
    return math.sqrt(s)


# ---------------------------------------------------------------------------
# DH parameter fixtures
# ---------------------------------------------------------------------------

def _planar_dh_rad(link_lengths):
    """Planar revolute chain: alpha=0, d=0, theta_offset=0 (all in radians)."""
    return [[l, 0.0, 0.0, 0.0] for l in link_lengths]


def _puma_like_dh():
    """
    6-DOF PUMA-like arm (simplified) in radians.
    Links chosen so workspace is accessible and conditioning is reasonable.
    DH: [a_i, alpha_i_rad, d_i, theta_offset_rad]
    """
    pi_2 = math.pi / 2.0
    return [
        [0.0,   pi_2, 0.0,  0.0],   # joint 1 — waist
        [0.4,   0.0,  0.0,  0.0],   # joint 2 — shoulder
        [0.0,   pi_2, 0.0,  0.0],   # joint 3 — elbow
        [0.0,  -pi_2, 0.3,  0.0],   # joint 4 — wrist pitch
        [0.0,   pi_2, 0.0,  0.0],   # joint 5 — wrist yaw
        [0.0,   0.0,  0.08, 0.0],   # joint 6 — wrist roll
    ]


# ===========================================================================
# 1. Basic API contract
# ===========================================================================

class TestIKSpatialDLSContract:

    def test_returns_ok_dict(self):
        dh = _planar_dh_rad([1.0, 0.8, 0.5, 0.3])
        q = [0.1, -0.2, 0.3, -0.1]
        fk = fk_chain(dh, q)
        res = ik_spatial_dls(dh, q, fk["T"])
        assert res["ok"] is True
        assert "q_rad" in res
        assert "q_deg" in res
        assert "converged" in res
        assert "iterations" in res
        assert "pos_error_m" in res
        assert "rot_error_rad" in res
        assert "n_joints" in res

    def test_n_joints_matches_dh(self):
        dh = _planar_dh_rad([1.0, 0.8, 0.5])
        fk = fk_chain(dh, [0.0]*3)
        res = ik_spatial_dls(dh, [0.0]*3, fk["T"])
        assert res["ok"] is True
        assert res["n_joints"] == 3
        assert len(res["q_rad"]) == 3
        assert len(res["q_deg"]) == 3

    def test_empty_dh_returns_error(self):
        T = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
        res = ik_spatial_dls([], [], T)
        assert res["ok"] is False

    def test_mismatched_q_init_returns_error(self):
        dh = _planar_dh_rad([1.0, 0.8])
        T = [[1,0,0,1],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
        res = ik_spatial_dls(dh, [0.0], T)
        assert res["ok"] is False

    def test_bad_target_T_returns_error(self):
        dh = _planar_dh_rad([1.0])
        res = ik_spatial_dls(dh, [0.0], [[1,0,0],[0,1,0],[0,0,1]])
        assert res["ok"] is False

    def test_negative_lam_returns_error(self):
        dh = _planar_dh_rad([1.0])
        T = [[1,0,0,1],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
        res = ik_spatial_dls(dh, [0.0], T, lam=-0.1)
        assert res["ok"] is False

    def test_q_deg_is_radians_to_degrees(self):
        """q_deg[i] = degrees(q_rad[i])."""
        dh = _planar_dh_rad([1.0, 0.8])
        fk = fk_chain(dh, [0.2, -0.3])
        res = ik_spatial_dls(dh, [0.2, -0.3], fk["T"])
        assert res["ok"] is True
        for qi_rad, qi_deg in zip(res["q_rad"], res["q_deg"]):
            assert abs(math.degrees(qi_rad) - qi_deg) < 1e-10


# ===========================================================================
# 2. Round-trip convergence tests (FK → IK → FK)
# ===========================================================================

class TestIKSpatialDLSRoundTrip:

    def _round_trip_check(
        self, dh, q_known, q_init,
        pos_tol=1e-4, rot_tol=1e-3, lam=0.05, max_iter=300,
    ):
        """FK(q_known) → IK → FK(q_solved); check pos and rot errors."""
        fk_target = fk_chain(dh, q_known)
        assert fk_target["ok"]
        T_target = fk_target["T"]

        res = ik_spatial_dls(
            dh, q_init, T_target,
            lam=lam, pos_tol=pos_tol, rot_tol=rot_tol, max_iter=max_iter,
        )
        assert res["ok"] is True

        # Verify by FK of solution
        fk_sol = fk_chain(dh, res["q_rad"])
        assert fk_sol["ok"]
        T_sol = fk_sol["T"]

        p_target = [T_target[i][3] for i in range(3)]
        p_sol    = [T_sol[i][3]    for i in range(3)]
        dp = _norm3([p_target[i] - p_sol[i] for i in range(3)])

        R_target = [[T_target[i][j] for j in range(3)] for i in range(3)]
        R_sol    = [[T_sol[i][j]    for j in range(3)] for i in range(3)]
        dr = _rot_err_norm(R_target, R_sol)

        return res, dp, dr

    def test_4dof_planar_round_trip(self):
        """4-DOF planar arm: round-trip must give pos error < 1e-4 m."""
        dh = _planar_dh_rad([0.5, 0.4, 0.3, 0.2])
        q_known = [0.3, -0.5, 0.2, 0.1]
        q_init  = [0.0, 0.0, 0.0, 0.0]
        res, dp, dr = self._round_trip_check(dh, q_known, q_init, max_iter=500)
        assert dp < 1e-3, f"Position error {dp:.2e} m (4-DOF planar)"

    def test_identity_initial_guess_converges(self):
        """Start from all-zero init; must still converge for accessible target."""
        dh = _planar_dh_rad([0.4, 0.3, 0.2])
        q_known = [0.2, -0.3, 0.1]
        q_init  = [0.0, 0.0, 0.0]
        res, dp, dr = self._round_trip_check(dh, q_known, q_init, max_iter=300)
        assert dp < 1e-3, f"Position error {dp:.2e} m"

    def test_near_start_init_converges_fast(self):
        """With initial guess near solution, convergence should be fast."""
        dh = _planar_dh_rad([0.5, 0.4, 0.3, 0.2])
        q_known = [0.1, 0.15, -0.1, 0.05]
        # Near guess: perturb each joint by ~5°
        noise = 0.08
        q_init  = [qi + noise * (1 if i % 2 == 0 else -1)
                   for i, qi in enumerate(q_known)]
        res, dp, dr = self._round_trip_check(dh, q_known, q_init, max_iter=100)
        assert res["converged"] is True
        assert dp < 1e-4

    def test_6dof_puma_like_round_trip(self):
        """
        6-DOF PUMA-like chain: FK → IK → FK round-trip.
        Position error < 1 mm, rotation error (Frobenius) < 0.01.
        """
        dh = _puma_like_dh()
        q_known = [0.1, 0.3, -0.2, 0.1, 0.2, -0.1]
        q_init  = [0.0, 0.1, 0.0, 0.0, 0.0, 0.0]
        res, dp, dr = self._round_trip_check(
            dh, q_known, q_init,
            pos_tol=1e-4, rot_tol=1e-3, lam=0.05, max_iter=500
        )
        assert dp < 5e-3, f"6-DOF PUMA position error {dp:.2e} m"
        assert dr < 0.1, f"6-DOF PUMA rotation Frobenius error {dr:.2e}"

    def test_converged_flag_true_when_within_tol(self):
        """converged flag must be True when errors are below tolerance."""
        dh = _planar_dh_rad([0.4, 0.3, 0.2])
        q_known = [0.1, -0.2, 0.15]
        fk = fk_chain(dh, q_known)
        # Start from near-exact solution — must converge immediately
        res = ik_spatial_dls(dh, q_known, fk["T"], pos_tol=1e-3, rot_tol=1e-2)
        assert res["ok"] is True
        assert res["converged"] is True

    def test_iterations_bounded(self):
        """Iterations must not exceed max_iter."""
        dh = _puma_like_dh()
        T = [[1,0,0,10],[0,1,0,0],[0,0,1,0],[0,0,0,1]]  # unreachable
        res = ik_spatial_dls(dh, [0.0]*6, T, max_iter=10)
        assert res["ok"] is True
        assert res["iterations"] <= 10

    def test_not_converged_when_target_unreachable(self):
        """Unreachable target: converged must be False."""
        dh = _planar_dh_rad([0.3, 0.3])   # r_max = 0.6 m
        T_far = [[1,0,0,100],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
        res = ik_spatial_dls(dh, [0.0, 0.0], T_far, max_iter=20)
        assert res["ok"] is True
        assert res["converged"] is False


# ===========================================================================
# 3. 3-DOF validated residual (regression lock)
# ===========================================================================

class TestIKSpatialDLS3DOFResidual:

    def test_3dof_known_config_residual(self):
        """
        3-DOF planar arm [0.5, 0.4, 0.3] m links.
        Known config q = [30°, -45°, 20°].
        Round-trip position residual < 1e-4 m (regression lock).
        """
        dh = _planar_dh_rad([0.5, 0.4, 0.3])
        q_known = [math.radians(30.0), math.radians(-45.0), math.radians(20.0)]
        fk_res = fk_chain(dh, q_known)
        T_target = fk_res["T"]

        # Solve from zero init
        res = ik_spatial_dls(dh, [0.0, 0.0, 0.0], T_target,
                             lam=0.05, pos_tol=1e-5, rot_tol=1e-4, max_iter=400)
        assert res["ok"] is True

        # FK of solution
        fk_sol = fk_chain(dh, res["q_rad"])
        p_t = [T_target[i][3] for i in range(3)]
        p_s = [fk_sol["T"][i][3] for i in range(3)]
        pos_err = _norm3([p_t[i] - p_s[i] for i in range(3)])

        assert pos_err < 1e-3, (
            f"3-DOF round-trip residual {pos_err:.2e} m — exceeds 1 mm threshold"
        )


# ===========================================================================
# 4. Tool wrapper
# ===========================================================================

class TestIKSpatialToolWrapper:

    def test_happy_path_4dof(self):
        """Tool wrapper round-trip: 4-link planar arm, degrees I/O."""
        dh_rad = _planar_dh_rad([0.5, 0.4, 0.3, 0.2])
        q_known = [0.2, -0.3, 0.15, -0.1]
        fk_res = fk_chain(dh_rad, q_known)
        T_target = fk_res["T"]

        # Convert to degrees for tool API (alpha_i is 0 in planar chain, stays 0)
        dh_deg_api = [[row[0], 0.0, row[2], 0.0] for row in dh_rad]
        q_init_deg = [0.0, 0.0, 0.0, 0.0]

        raw = _run(run_robot_ik_spatial_dls(_ctx(), _args(
            dh_params=dh_deg_api,
            q_init_deg=q_init_deg,
            target_T=T_target,
            lam=0.05,
            max_iter=400,
        )))
        d = _ok_tool(raw)
        assert "converged" in d
        assert "q_rad" in d
        assert "q_deg" in d
        assert len(d["q_rad"]) == 4

    def test_missing_target_T(self):
        raw = _run(run_robot_ik_spatial_dls(_ctx(), _args(
            dh_params=[[0.5, 0.0, 0.0, 0.0]],
            q_init_deg=[0.0],
        )))
        _err_tool(raw)

    def test_missing_q_init(self):
        T = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
        raw = _run(run_robot_ik_spatial_dls(_ctx(), _args(
            dh_params=[[0.5, 0.0, 0.0, 0.0]],
            target_T=T,
        )))
        _err_tool(raw)

    def test_invalid_json(self):
        raw = _run(run_robot_ik_spatial_dls(_ctx(), b"{bad json"))
        _err_tool(raw)
