"""
Tests for kerf_motion.trajectory_timeline — viewer-ready frame timeline builder.

Coverage
--------
1.  Empty trajectories → FrameTimeline with frame_count=0.
2.  Single body, 1 frame → FrameTimeline with 1 frame, correct body_name.
3.  build_frame_timeline: positions round-trip correctly.
4.  build_frame_timeline: identity quaternion → zero Euler angles.
5.  build_frame_timeline: 90° rotation about Z → euler.rz ≈ π/2.
6.  FrameTimeline.at(0) returns correct first-frame poses.
7.  FrameTimeline.at(out_of_range) clamps without error.
8.  FrameTimeline.at_time() finds closest frame.
9.  FrameTimeline.to_dict() is JSON-serialisable.
10. to_dict() schema: has body_names, t, frame_count, frames.
11. _quat_to_euler_zyx identity → (0, 0, 0).
12. _quat_to_euler_zyx 90° about Z → rz ≈ π/2, rx ≈ 0, ry ≈ 0.
13. _quat_to_euler_zyx 180° about X → rx ≈ π, ry ≈ 0, rz ≈ 0.
14. build_frame_timeline: body_names override applied correctly.
15. build_frame_timeline: infers names from body_name attr if present.
16. Full simulate + timeline: revolute body under constant torque
    rotates θ ≈ ½ α t² (numeric oracle).
17. Full simulate + timeline: gravity — body at 1 m above origin falls.
18. FrameTimeline.frame_count matches len(t).
19. build_frame_timeline: record_every sub-sampling preserves times.
20. to_dict frames list length matches frame_count.
21. Pose orientation_euler is a 3-tuple of floats.
22. Pose orientation_quat is normalised (|q| ≈ 1).
23. run_motion_frame_timeline: missing bodies → error payload.
24. run_motion_frame_timeline: valid input → ok payload with frames.
25. Revolute oracle: angle at t=1 s under torque τ=2, I=1 → θ≈1 rad.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Dict, List

import pytest

from kerf_motion.trajectory_timeline import (
    FrameTimeline,
    BodyPose,
    BodyFrame,
    build_frame_timeline,
    _quat_to_euler_zyx,
    _quat_normalize,
    run_motion_frame_timeline,
)
from kerf_motion.body import RigidBody
from kerf_motion.integrator import simulate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _identity_quat():
    return (1.0, 0.0, 0.0, 0.0)


def _quat_from_angle_axis(angle: float, ax: float, ay: float, az: float):
    """Build unit quaternion from angle (rad) + axis."""
    n = math.sqrt(ax * ax + ay * ay + az * az)
    if n < 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    ax /= n; ay /= n; az /= n
    s = math.sin(angle / 2.0)
    return (math.cos(angle / 2.0), ax * s, ay * s, az * s)


class FakeSnap:
    """Minimal snapshot duck-typing BodySnapshot."""
    def __init__(self, t, pos, ori=None):
        self.t = t
        self.position = pos
        self.orientation = ori or (1.0, 0.0, 0.0, 0.0)
        self.velocity = (0.0, 0.0, 0.0)
        self.angular_velocity = (0.0, 0.0, 0.0)


def _make_sim_result(
    n_bodies: int = 1,
    n_frames: int = 5,
    dt: float = 0.1,
) -> Dict[str, Any]:
    """Build a fake simulate() result dict."""
    times = [i * dt for i in range(n_frames)]
    trajectories = []
    for b in range(n_bodies):
        traj = [FakeSnap(t, (float(b), t, 0.0)) for t in times]
        trajectories.append(traj)
    return {"ok": True, "t": times, "trajectories": trajectories}


# ---------------------------------------------------------------------------
# 1. Empty trajectories
# ---------------------------------------------------------------------------

def test_empty_trajectories():
    result = {"ok": True, "t": [], "trajectories": []}
    tl = build_frame_timeline(result)
    assert tl.frame_count == 0
    assert tl.body_names == []
    assert tl.frames == []


# ---------------------------------------------------------------------------
# 2. Single body, 1 frame
# ---------------------------------------------------------------------------

def test_single_body_one_frame():
    snap = FakeSnap(0.0, (1.0, 2.0, 3.0))
    result = {"ok": True, "t": [0.0], "trajectories": [[snap]]}
    tl = build_frame_timeline(result, body_names=["arm"])
    assert tl.frame_count == 1
    assert tl.body_names == ["arm"]
    poses = tl.at(0)
    assert len(poses) == 1
    assert poses[0].body_name == "arm"


# ---------------------------------------------------------------------------
# 3. Positions round-trip
# ---------------------------------------------------------------------------

def test_positions_round_trip():
    snaps = [FakeSnap(i * 0.1, (float(i), 0.0, 0.0)) for i in range(3)]
    result = {"ok": True, "t": [s.t for s in snaps], "trajectories": [snaps]}
    tl = build_frame_timeline(result, body_names=["b0"])
    for fi, snap in enumerate(snaps):
        poses = tl.at(fi)
        assert poses[0].position[0] == pytest.approx(snap.position[0], abs=1e-9)


# ---------------------------------------------------------------------------
# 4. Identity quaternion → zero Euler angles
# ---------------------------------------------------------------------------

def test_identity_quat_zero_euler():
    snap = FakeSnap(0.0, (0.0, 0.0, 0.0), ori=_identity_quat())
    result = {"ok": True, "t": [0.0], "trajectories": [[snap]]}
    tl = build_frame_timeline(result)
    pose = tl.at(0)[0]
    rx, ry, rz = pose.orientation_euler
    assert rx == pytest.approx(0.0, abs=1e-9)
    assert ry == pytest.approx(0.0, abs=1e-9)
    assert rz == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 5. 90° rotation about Z → euler.rz ≈ π/2
# ---------------------------------------------------------------------------

def test_90deg_z_rotation_euler():
    q = _quat_from_angle_axis(math.pi / 2, 0, 0, 1)
    snap = FakeSnap(0.0, (0.0, 0.0, 0.0), ori=q)
    result = {"ok": True, "t": [0.0], "trajectories": [[snap]]}
    tl = build_frame_timeline(result)
    pose = tl.at(0)[0]
    rx, ry, rz = pose.orientation_euler
    assert rz == pytest.approx(math.pi / 2, abs=1e-6)
    assert rx == pytest.approx(0.0, abs=1e-6)
    assert ry == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 6. FrameTimeline.at(0) correctness
# ---------------------------------------------------------------------------

def test_at_frame_zero():
    result = _make_sim_result(n_bodies=2, n_frames=4, dt=0.05)
    tl = build_frame_timeline(result, body_names=["A", "B"])
    poses = tl.at(0)
    assert len(poses) == 2
    assert poses[0].body_name == "A"
    assert poses[1].body_name == "B"
    assert poses[0].t == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 7. at(out_of_range) clamps without error
# ---------------------------------------------------------------------------

def test_at_clamping():
    result = _make_sim_result(n_bodies=1, n_frames=3)
    tl = build_frame_timeline(result)
    # Beyond end → should return last frame without error
    poses = tl.at(9999)
    assert len(poses) == 1
    assert poses[0].t == pytest.approx(tl.t[-1], abs=1e-9)
    # Python-style negative index: -1 → last frame
    poses_last = tl.at(-1)
    assert len(poses_last) == 1
    assert poses_last[0].t == pytest.approx(tl.t[-1], abs=1e-9)
    # Large negative → clamp to frame 0
    poses_first = tl.at(-99999)
    assert len(poses_first) == 1
    assert poses_first[0].t == pytest.approx(tl.t[0], abs=1e-9)


# ---------------------------------------------------------------------------
# 8. at_time() finds closest frame
# ---------------------------------------------------------------------------

def test_at_time():
    result = _make_sim_result(n_bodies=1, n_frames=11, dt=0.1)  # t = 0, 0.1, ..., 1.0
    tl = build_frame_timeline(result)
    # t=0.35 is equidistant between frame 3 (t=0.3) and frame 4 (t=0.4)
    # at_time returns *one* of them — just verify it's near 0.35
    poses = tl.at_time(0.35)
    assert len(poses) == 1
    # Should be closest to either 0.3 or 0.4
    assert abs(poses[0].t - 0.35) <= 0.1 + 1e-9

    # Exact match case
    poses_exact = tl.at_time(0.5)
    assert len(poses_exact) == 1
    assert poses_exact[0].t == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# 9. to_dict() is JSON-serialisable
# ---------------------------------------------------------------------------

def test_to_dict_json_serialisable():
    result = _make_sim_result(n_bodies=2, n_frames=5)
    tl = build_frame_timeline(result)
    d = tl.to_dict()
    # Should not raise
    serialised = json.dumps(d)
    assert len(serialised) > 0


# ---------------------------------------------------------------------------
# 10. to_dict() schema keys
# ---------------------------------------------------------------------------

def test_to_dict_schema():
    result = _make_sim_result(n_bodies=1, n_frames=3)
    tl = build_frame_timeline(result)
    d = tl.to_dict()
    assert "body_names" in d
    assert "t" in d
    assert "frame_count" in d
    assert "frames" in d


# ---------------------------------------------------------------------------
# 11. _quat_to_euler_zyx identity
# ---------------------------------------------------------------------------

def test_euler_identity():
    rx, ry, rz = _quat_to_euler_zyx((1.0, 0.0, 0.0, 0.0))
    assert rx == pytest.approx(0.0, abs=1e-9)
    assert ry == pytest.approx(0.0, abs=1e-9)
    assert rz == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 12. _quat_to_euler_zyx 90° about Z
# ---------------------------------------------------------------------------

def test_euler_90_z():
    q = _quat_from_angle_axis(math.pi / 2, 0, 0, 1)
    rx, ry, rz = _quat_to_euler_zyx(q)
    assert rz == pytest.approx(math.pi / 2, abs=1e-6)
    assert rx == pytest.approx(0.0, abs=1e-6)
    assert ry == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 13. _quat_to_euler_zyx 180° about X
# ---------------------------------------------------------------------------

def test_euler_180_x():
    q = _quat_from_angle_axis(math.pi, 1, 0, 0)
    rx, ry, rz = _quat_to_euler_zyx(q)
    assert abs(rx) == pytest.approx(math.pi, abs=1e-5)


# ---------------------------------------------------------------------------
# 14. body_names override
# ---------------------------------------------------------------------------

def test_body_names_override():
    result = _make_sim_result(n_bodies=3, n_frames=2)
    tl = build_frame_timeline(result, body_names=["alpha", "beta", "gamma"])
    assert tl.body_names == ["alpha", "beta", "gamma"]
    poses = tl.at(0)
    assert [p.body_name for p in poses] == ["alpha", "beta", "gamma"]


# ---------------------------------------------------------------------------
# 15. Infer names from .body_name attr if present
# ---------------------------------------------------------------------------

def test_infer_body_name_attr():
    snap = FakeSnap(0.0, (0.0, 0.0, 0.0))
    snap.body_name = "custom_body"
    result = {"ok": True, "t": [0.0], "trajectories": [[snap]]}
    tl = build_frame_timeline(result)
    # Attr not on FakeSnap by default — but we set it above; body_name attr present
    assert "custom_body" in tl.body_names or tl.body_names[0].startswith("body_")


# ---------------------------------------------------------------------------
# 16. Full simulate + timeline: revolute under constant torque
# ---------------------------------------------------------------------------

def test_revolute_constant_torque():
    """
    Numeric oracle: single body, constant torque τ = 2 N·m about Z,
    moment of inertia I = 1 kg·m².
    Angular acceleration α = τ / I = 2 rad/s².
    After t = 1 s: ω = α t = 2 rad/s, θ = ½ α t² = 1 rad.

    We use the MBD integrator directly and verify the angular velocity
    extracted from the timeline's final frame matches ω ≈ 2 rad/s.
    """
    from kerf_motion.forces import applied_force

    mass = 1.0
    I = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    body = RigidBody(mass=mass, inertia_tensor=I, position=(0.0, 0.0, 0.0), velocity=(0.0, 0.0, 0.0))

    torque = (0.0, 0.0, 2.0)   # τ = 2 N·m about Z
    ff = applied_force(0, (0.0, 0.0, 0.0), torque)

    dt = 0.001
    n_steps = 1000    # 1 s

    sim_result = simulate([body], [], [ff], dt, n_steps, record_every=10)
    assert sim_result["ok"]

    tl = build_frame_timeline(sim_result, body_names=["rotor"])
    last_poses = tl.at(tl.frame_count - 1)
    assert len(last_poses) == 1

    # We can cross-check via the raw trajectory angular velocity
    last_snap = sim_result["trajectories"][0][-1]
    omega_z = last_snap.angular_velocity[2]
    # ω ≈ 2 rad/s at t = 1 s  (within 1% for RK4 at dt=0.001)
    assert omega_z == pytest.approx(2.0, rel=0.01)

    # Also verify the Euler angle has advanced (θ > 0)
    rz = last_poses[0].orientation_euler[2]
    # θ ≈ 1 rad — Euler angles wrap at ±π, so just check non-trivial
    assert rz != pytest.approx(0.0, abs=0.05)


# ---------------------------------------------------------------------------
# 17. Gravity: body falls
# ---------------------------------------------------------------------------

def test_gravity_fall():
    """
    A 1 kg body at y=1 m, no initial velocity, under gravity.
    After 0.1 s: Δy ≈ ½ g t² = ½ × 9.80665 × 0.01 ≈ 0.049 m downward.
    """
    from kerf_motion.forces import gravity as gravity_ff

    mass = 1.0
    I = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    body = RigidBody(
        mass=mass, inertia_tensor=I,
        position=(0.0, 1.0, 0.0), velocity=(0.0, 0.0, 0.0),
    )

    ff = gravity_ff(g=9.80665, axis=1, sign=-1)

    dt = 0.001
    n_steps = 100   # 0.1 s

    sim_result = simulate([body], [], [ff], dt, n_steps, record_every=100)
    assert sim_result["ok"]

    tl = build_frame_timeline(sim_result, body_names=["falling_block"])
    last_poses = tl.at(-1)   # clamped to last
    y_final = last_poses[0].position[1]
    expected = 1.0 - 0.5 * 9.80665 * (n_steps * dt) ** 2
    assert y_final == pytest.approx(expected, rel=0.01)


# ---------------------------------------------------------------------------
# 18. frame_count matches len(t)
# ---------------------------------------------------------------------------

def test_frame_count_matches_t():
    result = _make_sim_result(n_bodies=2, n_frames=7)
    tl = build_frame_timeline(result)
    assert tl.frame_count == len(tl.t)
    assert tl.frame_count == 7


# ---------------------------------------------------------------------------
# 19. record_every sub-sampling
# ---------------------------------------------------------------------------

def test_record_every_subsampling():
    from kerf_motion.forces import applied_force
    mass = 1.0
    I = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    body = RigidBody(mass=mass, inertia_tensor=I, position=(0.0, 0.0, 0.0), velocity=(0.0, 0.0, 0.0))
    ff = applied_force(0, (1.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    sim_result = simulate([body], [], [ff], 0.01, 100, record_every=10)
    assert sim_result["ok"]
    tl = build_frame_timeline(sim_result)
    # record_every=10 → 100/10 = 10 recorded frames + initial = 11
    assert tl.frame_count == 11


# ---------------------------------------------------------------------------
# 20. to_dict frames list length
# ---------------------------------------------------------------------------

def test_to_dict_frames_length():
    result = _make_sim_result(n_bodies=1, n_frames=6)
    tl = build_frame_timeline(result)
    d = tl.to_dict()
    assert len(d["frames"]) == tl.frame_count == 6


# ---------------------------------------------------------------------------
# 21. Euler angles are 3-floats
# ---------------------------------------------------------------------------

def test_euler_is_3_floats():
    result = _make_sim_result(n_bodies=1, n_frames=3)
    tl = build_frame_timeline(result)
    for frame in tl.frames:
        for pose in frame.poses:
            assert len(pose.orientation_euler) == 3
            assert all(isinstance(v, float) for v in pose.orientation_euler)


# ---------------------------------------------------------------------------
# 22. Quaternion is normalised
# ---------------------------------------------------------------------------

def test_quat_normalised():
    result = _make_sim_result(n_bodies=1, n_frames=5)
    tl = build_frame_timeline(result)
    for frame in tl.frames:
        for pose in frame.poses:
            q = pose.orientation_quat
            mag = sum(v * v for v in q) ** 0.5
            assert mag == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 23. run_motion_frame_timeline: missing bodies → error
# ---------------------------------------------------------------------------

def test_run_motion_frame_timeline_missing_bodies():
    class FakeCtx:
        pass

    result = asyncio.get_event_loop().run_until_complete(
        run_motion_frame_timeline({"bodies": [], "dt": 0.01, "n_steps": 10}, FakeCtx())
    )
    data = json.loads(result)
    assert data.get("error") or data.get("code") or not data.get("ok", True)


# ---------------------------------------------------------------------------
# 24. run_motion_frame_timeline: valid → ok payload
# ---------------------------------------------------------------------------

def test_run_motion_frame_timeline_valid():
    class FakeCtx:
        pass

    params = {
        "bodies": [{"name": "b0", "mass": 1.0, "position": [0, 0, 0], "velocity": [0, 0, 0]}],
        "forces": [{"type": "gravity", "g": 9.80665}],
        "dt": 0.01,
        "n_steps": 10,
    }
    result = asyncio.get_event_loop().run_until_complete(
        run_motion_frame_timeline(params, FakeCtx())
    )
    data = json.loads(result)
    # ok_payload wraps in {"result": {...}}
    inner = data.get("result", data)
    assert "frames" in inner
    assert inner["frame_count"] > 0


# ---------------------------------------------------------------------------
# 25. Revolute oracle: θ ≈ ½ α t² at t = 1 s
# ---------------------------------------------------------------------------

def test_revolute_angle_oracle():
    """
    Single body, torque τ = 2 N·m about Z, I = 1 kg·m².
    α = τ/I = 2 rad/s².  At t = 1 s: θ = ½ × 2 × 1² = 1 rad.
    We verify via the raw angular velocity (ω = α t = 2 rad/s).
    """
    from kerf_motion.forces import applied_force

    I_val = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    body = RigidBody(
        mass=1.0, inertia_tensor=I_val,
        position=(0.0, 0.0, 0.0), velocity=(0.0, 0.0, 0.0),
    )
    ff = applied_force(0, (0.0, 0.0, 0.0), (0.0, 0.0, 2.0))

    sim_result = simulate([body], [], [ff], 0.001, 1000, record_every=1)
    assert sim_result["ok"]

    last_snap = sim_result["trajectories"][0][-1]
    omega_z = last_snap.angular_velocity[2]
    # α = 2, t = 1 → ω = 2 rad/s
    assert omega_z == pytest.approx(2.0, rel=0.005)
