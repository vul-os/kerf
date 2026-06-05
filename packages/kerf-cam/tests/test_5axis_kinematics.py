"""
pytest tests for 5-axis machine kinematics models.

Tests:
  - Forward kinematics: (A,B) → (i,j,k) for all three configs
  - Inverse kinematics: (i,j,k) → (A,B) round-trip for all configs
  - RTCP pre-transform (head_table only)
  - Joint-angle unwrap across a sequence
  - Travel-limit enforcement
  - MachineConfig validation
  - MACHINES predefined configs
"""

from __future__ import annotations

import math
import pytest

from kerf_cam.five_axis.kinematics import (
    MachineConfig,
    MACHINES,
    forward_kinematics,
    inverse_kinematics,
    rtcp_transform,
    unwrap_joint_sequence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit(v):
    mag = math.sqrt(sum(c**2 for c in v))
    return tuple(c / mag for c in v)


def _approx_eq(a, b, tol=1e-5):
    return abs(a - b) < tol


# ---------------------------------------------------------------------------
# MachineConfig validation
# ---------------------------------------------------------------------------

def test_machine_config_invalid_kinematic():
    with pytest.raises(ValueError, match="kinematic"):
        MachineConfig(kinematic="unknown_type")


def test_machine_config_defaults():
    cfg = MachineConfig()
    assert cfg.kinematic == "head_table"
    assert cfg.pivot_to_tip_z == 100.0


def test_machines_dict_has_all_types():
    """MACHINES predefined dict has one entry per kinematic type."""
    types = {m.kinematic for m in MACHINES.values()}
    assert "head_table" in types
    assert "table_table" in types
    assert "head_head" in types


# ---------------------------------------------------------------------------
# Forward kinematics — head_table
# ---------------------------------------------------------------------------

_HT = MachineConfig(kinematic="head_table",
                    a_min_deg=-180, a_max_deg=180,
                    b_min_deg=-180, b_max_deg=180)

def test_fk_head_table_zero():
    """A=0, B=0 → tool axis +Z (0,0,1)."""
    i, j, k = forward_kinematics(0.0, 0.0, _HT)
    assert _approx_eq(i, 0.0)
    assert _approx_eq(j, 0.0)
    assert _approx_eq(k, 1.0)


def test_fk_head_table_b15():
    """B=15° (head tilt around Y) → i≈sin15°, k≈cos15°, j≈0."""
    r = math.radians(15.0)
    i, j, k = forward_kinematics(0.0, 15.0, _HT)
    assert _approx_eq(i, math.sin(r), tol=1e-9)
    assert _approx_eq(j, 0.0, tol=1e-9)
    assert _approx_eq(k, math.cos(r), tol=1e-9)


def test_fk_head_table_a30():
    """A=30° (table tilt around X), B=0 → i=0, j=-sin30°, k=cos30°."""
    r = math.radians(30.0)
    i, j, k = forward_kinematics(30.0, 0.0, _HT)
    assert _approx_eq(i, 0.0, tol=1e-9)
    assert _approx_eq(j, -math.sin(r), tol=1e-9)
    assert _approx_eq(k, math.cos(r), tol=1e-9)


def test_fk_head_table_is_unit_vector():
    """FK result must always be a unit vector."""
    for a in range(-60, 61, 15):
        for b in range(-30, 31, 15):
            i, j, k = forward_kinematics(float(a), float(b), _HT)
            mag = math.sqrt(i*i + j*j + k*k)
            assert abs(mag - 1.0) < 1e-9, f"Not unit vector at A={a} B={b}: mag={mag}"


# ---------------------------------------------------------------------------
# Forward kinematics — table_table
# ---------------------------------------------------------------------------

_TT = MachineConfig(kinematic="table_table",
                    a_min_deg=-180, a_max_deg=180,
                    b_min_deg=-360, b_max_deg=360)

def test_fk_table_table_zero():
    """A=0, C=0 → tool axis +Z (workpiece flat on table)."""
    i, j, k = forward_kinematics(0.0, 0.0, _TT)
    assert _approx_eq(k, 1.0, tol=1e-9)


def test_fk_table_table_a30():
    """A=30°, C=0 → k=cos30°, j≈-sin30°*cos0=−sin30°, i≈0."""
    r = math.radians(30.0)
    i, j, k = forward_kinematics(30.0, 0.0, _TT)
    assert _approx_eq(k, math.cos(r), tol=1e-9)
    assert _approx_eq(j, -math.sin(r), tol=1e-9)
    assert _approx_eq(i, 0.0, tol=1e-9)


def test_fk_table_table_is_unit_vector():
    """FK result must always be a unit vector."""
    for a in range(0, 91, 30):
        for c in range(-180, 181, 45):
            i, j, k = forward_kinematics(float(a), float(c), _TT)
            mag = math.sqrt(i*i + j*j + k*k)
            assert abs(mag - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Forward kinematics — head_head
# ---------------------------------------------------------------------------

_HH = MachineConfig(kinematic="head_head",
                    a_min_deg=-180, a_max_deg=180,
                    b_min_deg=-360, b_max_deg=360)

def test_fk_head_head_zero():
    """A=0, C=0 → tool axis +Z."""
    i, j, k = forward_kinematics(0.0, 0.0, _HH)
    assert _approx_eq(k, 1.0, tol=1e-9)


def test_fk_head_head_a30():
    """A=30°, C=0 → k=cos30°."""
    r = math.radians(30.0)
    i, j, k = forward_kinematics(30.0, 0.0, _HH)
    assert _approx_eq(k, math.cos(r), tol=1e-9)


def test_fk_head_head_is_unit_vector():
    for a in range(0, 46, 15):
        for c in range(-180, 181, 45):
            i, j, k = forward_kinematics(float(a), float(c), _HH)
            mag = math.sqrt(i*i + j*j + k*k)
            assert abs(mag - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Inverse kinematics round-trips
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a_in,b_in", [
    (0.0, 0.0),
    (15.0, 20.0),
    (-10.0, 30.0),
    (45.0, -15.0),
    (0.0, 15.0),
    (30.0, 0.0),
])
def test_ik_roundtrip_head_table(a_in, b_in):
    """FK then IK must recover the original (A, B) angles for head_table."""
    i, j, k = forward_kinematics(a_in, b_in, _HT)
    a_out, b_out = inverse_kinematics(i, j, k, _HT)
    assert _approx_eq(a_out, a_in, tol=1e-5), (
        f"head_table IK round-trip failed: in=({a_in}, {b_in}) → FK → IK → ({a_out:.5f}, {b_out:.5f})"
    )
    assert _approx_eq(b_out, b_in, tol=1e-5)


@pytest.mark.parametrize("a_in,c_in", [
    (0.0, 0.0),
    (30.0, 0.0),
    (45.0, 90.0),
    (60.0, -45.0),
    (90.0, 0.0),
])
def test_ik_roundtrip_table_table(a_in, c_in):
    """FK then IK must recover (A, C) for table_table."""
    i, j, k = forward_kinematics(a_in, c_in, _TT)
    a_out, c_out = inverse_kinematics(i, j, k, _TT)
    assert _approx_eq(a_out, a_in, tol=1e-5), (
        f"table_table IK round-trip A: in={a_in} → {a_out:.5f}"
    )
    assert _approx_eq(c_out, c_in, tol=1e-5), (
        f"table_table IK round-trip C: in={c_in} → {c_out:.5f}"
    )


@pytest.mark.parametrize("a_in,c_in", [
    (0.0, 0.0),
    (15.0, 0.0),
    (30.0, 45.0),
    (45.0, -90.0),
])
def test_ik_roundtrip_head_head(a_in, c_in):
    """FK then IK must recover (A, C) for head_head."""
    i, j, k = forward_kinematics(a_in, c_in, _HH)
    a_out, c_out = inverse_kinematics(i, j, k, _HH)
    assert _approx_eq(a_out, a_in, tol=1e-5), (
        f"head_head IK round-trip A: in={a_in} → {a_out:.5f}"
    )
    assert _approx_eq(c_out, c_in, tol=1e-5), (
        f"head_head IK round-trip C: in={c_in} → {c_out:.5f}"
    )


# ---------------------------------------------------------------------------
# Travel limit enforcement
# ---------------------------------------------------------------------------

def test_ik_limit_violation_raises():
    """IK must raise ValueError when computed angle exceeds travel limits."""
    cfg = MachineConfig(kinematic="head_table",
                        a_min_deg=-30.0, a_max_deg=30.0,
                        b_min_deg=-15.0, b_max_deg=15.0)
    # Tool tilted 20° → B = 20° → outside b_max=15°
    r = math.radians(20.0)
    i, j, k = math.sin(r), 0.0, math.cos(r)
    with pytest.raises(ValueError, match="travel"):
        inverse_kinematics(i, j, k, cfg)


def test_ik_within_limits_ok():
    """IK within travel limits must not raise."""
    cfg = MachineConfig(kinematic="head_table",
                        a_min_deg=-60.0, a_max_deg=60.0,
                        b_min_deg=-45.0, b_max_deg=45.0)
    r = math.radians(10.0)
    i, j, k = math.sin(r), 0.0, math.cos(r)
    a, b = inverse_kinematics(i, j, k, cfg)  # must not raise
    assert abs(b - 10.0) < 1e-5


# ---------------------------------------------------------------------------
# RTCP pre-transform (head_table)
# ---------------------------------------------------------------------------

def test_rtcp_zero_position():
    """Tool at (0,0,0) pointing +Z with pivot_to_tip_z=100 → Zm = 100."""
    cfg = MachineConfig(kinematic="head_table", pivot_to_tip_z=100.0, pivot_z_offset=0.0,
                        a_min_deg=-180, a_max_deg=180,
                        b_min_deg=-180, b_max_deg=180)
    xm, ym, zm, a, b = rtcp_transform(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, cfg)
    assert _approx_eq(xm, 0.0)
    assert _approx_eq(ym, 0.0)
    assert _approx_eq(zm, 100.0)   # tcp + L*k = 0 + 100*1 = 100
    assert _approx_eq(a, 0.0)
    assert _approx_eq(b, 0.0)


def test_rtcp_pivot_z_offset():
    """pivot_z_offset shifts Zm."""
    cfg = MachineConfig(kinematic="head_table", pivot_to_tip_z=100.0, pivot_z_offset=50.0,
                        a_min_deg=-180, a_max_deg=180,
                        b_min_deg=-180, b_max_deg=180)
    xm, ym, zm, a, b = rtcp_transform(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, cfg)
    assert _approx_eq(zm, 150.0)   # 100 + 50


def test_rtcp_non_tcp_raises_for_unsupported():
    """rtcp_transform must raise NotImplementedError for table_table/head_head."""
    cfg_tt = MachineConfig(kinematic="table_table",
                           a_min_deg=-180, a_max_deg=180,
                           b_min_deg=-180, b_max_deg=180)
    with pytest.raises(NotImplementedError):
        rtcp_transform(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, cfg_tt)


# ---------------------------------------------------------------------------
# Unwrap joint sequence
# ---------------------------------------------------------------------------

def test_unwrap_empty():
    assert unwrap_joint_sequence([]) == []


def test_unwrap_no_discontinuity():
    pairs = [(10.0, 5.0), (15.0, 8.0), (20.0, 12.0)]
    out = unwrap_joint_sequence(pairs)
    assert len(out) == 3
    assert _approx_eq(out[0][0], 10.0)
    assert _approx_eq(out[2][0], 20.0)


def test_unwrap_removes_360_jump():
    """A jump of 350° (170 → -179) should be unwrapped to 181°."""
    pairs = [(170.0, 0.0), (-179.0, 0.0)]
    out = unwrap_joint_sequence(pairs)
    # The second A should be near 181° (= 170 + 11), not -179°
    assert out[1][0] > 170.0, f"Expected unwrapped A > 170, got {out[1][0]}"
    assert abs(out[1][0] - 181.0) < 0.5, f"Expected ~181°, got {out[1][0]:.2f}"


def test_unwrap_preserves_first():
    pairs = [(45.0, 10.0), (50.0, 12.0)]
    out = unwrap_joint_sequence(pairs)
    assert _approx_eq(out[0][0], 45.0)
    assert _approx_eq(out[0][1], 10.0)


# ---------------------------------------------------------------------------
# FK unit vector normalisation
# ---------------------------------------------------------------------------

def test_fk_output_is_always_unit():
    """Check all three kinematic configs produce unit vectors."""
    for kin, cfg in [("head_table", _HT), ("table_table", _TT), ("head_head", _HH)]:
        for a in range(-60, 61, 20):
            for b in range(-60, 61, 20):
                i, j, k = forward_kinematics(float(a), float(b), cfg)
                mag = math.sqrt(i*i + j*j + k*k)
                assert abs(mag - 1.0) < 1e-9, (
                    f"{kin} A={a} B={b}: magnitude {mag:.10f} ≠ 1"
                )
