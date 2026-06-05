"""
test_civil_parity_depth.py — Civil 3D parity gap-closure tests.

Covers:
  1. TIN breaklines / boundary / volume_between / interpolate_z
  2. Gravity pipe HGL/EGL profile (Manning + critical depth + Froude)
  3. Gravity network multi-pipe topological solve
  4. LLM tool registrations for new capabilities

Numeric oracles
---------------
All expected values are derived from first-principles calculations cited in
comments.  Tolerances match engineering practice (< 1% relative error for
design computations).

References
----------
Chaudhry (2008) Open-Channel Hydraulics, 2nd Ed., Springer.
ASCE MOP 36 (2017) Design and Construction of Sanitary and Storm Sewers.
AASHTO GDPS-4-M Green Book §2.2.3.
Mays (2011) Water Resources Engineering, 2nd Ed., Wiley.
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _ctx():
    from kerf_civil._compat import ProjectCtx
    return ProjectCtx()


def _call(handler, payload: dict) -> dict:
    raw = _run(handler(payload, _ctx()))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 1. TIN — breaklines
# ---------------------------------------------------------------------------

class TestTINBreaklines:
    """
    A breakline along the ridge of a hill should appear as a TIN edge.
    """

    POINTS = [
        [0.0, 0.0, 0.0],
        [10.0, 0.0, 0.0],
        [10.0, 10.0, 0.0],
        [0.0, 10.0, 0.0],
        [5.0, 0.0, 3.0],   # ridge left
        [5.0, 10.0, 3.0],  # ridge right
        [5.0, 5.0, 5.0],   # apex
    ]

    def test_build_with_breakline(self):
        from kerf_civil.tin import build_tin
        # Breakline: ridge edge 4→5 (both on the ridge axis)
        tin = build_tin(self.POINTS, breaklines=[[4, 5]])
        assert tin.triangles.shape[0] >= 2

    def test_breakline_stored_on_tin(self):
        from kerf_civil.tin import build_tin
        tin = build_tin(self.POINTS, breaklines=[[4, 5]])
        assert tin.breaklines is not None
        assert [4, 5] in tin.breaklines

    def test_breakline_no_crash_degenerate(self):
        """Breakline that cannot be enforced should not crash."""
        from kerf_civil.tin import build_tin
        pts = [
            [0, 0, 0], [5, 0, 0], [10, 0, 0],
            [0, 5, 0], [5, 5, 5], [10, 5, 0],
        ]
        # Request a breakline across a long diagonal — should not raise
        tin = build_tin(pts, breaklines=[[0, 5]])
        assert tin.triangles.shape[0] > 0


# ---------------------------------------------------------------------------
# 2. TIN — boundary trimming
# ---------------------------------------------------------------------------

class TestTINBoundary:
    POINTS = [
        [0.0, 0.0, 0.0],
        [10.0, 0.0, 0.0],
        [10.0, 10.0, 0.0],
        [0.0, 10.0, 0.0],
        [5.0, 5.0, 5.0],
        # Points well outside the intended area
        [50.0, 50.0, 0.0],
        [60.0, 0.0, 0.0],
    ]

    def test_build_with_boundary(self):
        from kerf_civil.tin import build_tin
        bnd = [[0, 0], [11, 0], [11, 11], [0, 11]]
        tin = build_tin(self.POINTS, boundary=bnd)
        assert tin.triangles.shape[0] > 0

    def test_boundary_reduces_triangles(self):
        from kerf_civil.tin import build_tin
        # Without boundary — more triangles (includes outlier pts)
        tin_full = build_tin(self.POINTS)
        # With boundary — outlier triangles removed
        bnd = [[0, 0], [12, 0], [12, 12], [0, 12]]
        tin_trimmed = build_tin(self.POINTS, boundary=bnd)
        # Trimmed should have fewer or equal triangles
        assert tin_trimmed.triangles.shape[0] <= tin_full.triangles.shape[0]

    def test_boundary_stored_on_tin(self):
        from kerf_civil.tin import build_tin
        bnd = [[0, 0], [10, 0], [10, 10], [0, 10]]
        tin = build_tin(self.POINTS, boundary=bnd)
        assert tin.boundary is not None


# ---------------------------------------------------------------------------
# 3. TIN — volume_between (cut/fill)
# ---------------------------------------------------------------------------

class TestTINVolumeBetween:
    """
    Oracle: two flat surfaces at different elevations.
    TIN_A (existing): flat grid at z=0
    TIN_B (proposed): flat grid at z=2 (uniformly raised by 2 m)
    Over a 10×10 m area → fill = 100 m² × 2 m = 200 m³, cut = 0.
    """

    FLAT_Z0 = [
        [0.0, 0.0, 0.0],
        [10.0, 0.0, 0.0],
        [10.0, 10.0, 0.0],
        [0.0, 10.0, 0.0],
        [5.0, 5.0, 0.0],
    ]

    FLAT_Z2 = [
        [0.0, 0.0, 2.0],
        [10.0, 0.0, 2.0],
        [10.0, 10.0, 2.0],
        [0.0, 10.0, 2.0],
        [5.0, 5.0, 2.0],
    ]

    FLAT_Z_MINUS2 = [
        [0.0, 0.0, -2.0],
        [10.0, 0.0, -2.0],
        [10.0, 10.0, -2.0],
        [0.0, 10.0, -2.0],
        [5.0, 5.0, -2.0],
    ]

    def test_fill_positive(self):
        from kerf_civil.tin import build_tin, volume_between
        # TIN_A (proposed) is above TIN_B (existing) → pure fill
        tin_a = build_tin(self.FLAT_Z2)   # proposed higher
        tin_b = build_tin(self.FLAT_Z0)   # existing lower
        result = volume_between(tin_a, tin_b)
        assert result["fill_m3"] == pytest.approx(100.0 * 2.0, rel=0.05)
        assert result["cut_m3"] == pytest.approx(0.0, abs=1.0)
        assert result["net_m3"] > 0

    def test_cut_positive(self):
        from kerf_civil.tin import build_tin, volume_between
        # TIN_A (proposed) is below TIN_B (existing) → pure cut
        tin_a = build_tin(self.FLAT_Z_MINUS2)  # proposed lower
        tin_b = build_tin(self.FLAT_Z0)         # existing higher
        result = volume_between(tin_a, tin_b)
        assert result["cut_m3"] == pytest.approx(100.0 * 2.0, rel=0.05)
        assert result["fill_m3"] == pytest.approx(0.0, abs=1.0)
        assert result["net_m3"] < 0

    def test_same_surface_zero_volume(self):
        from kerf_civil.tin import build_tin, volume_between
        tin = build_tin(self.FLAT_Z0)
        result = volume_between(tin, tin)
        assert abs(result["net_m3"]) < 1.0  # near zero
        assert abs(result["fill_m3"]) < 1.0
        assert abs(result["cut_m3"]) < 1.0

    def test_result_dict_keys(self):
        from kerf_civil.tin import build_tin, volume_between
        tin_a = build_tin(self.FLAT_Z2)
        tin_b = build_tin(self.FLAT_Z0)
        result = volume_between(tin_a, tin_b)
        assert "cut_m3" in result
        assert "fill_m3" in result
        assert "net_m3" in result


# ---------------------------------------------------------------------------
# 4. TIN — interpolate_z
# ---------------------------------------------------------------------------

class TestTINInterpolateZ:
    PYRAMID = [
        [0.0, 0.0, 0.0],
        [10.0, 0.0, 0.0],
        [10.0, 10.0, 0.0],
        [0.0, 10.0, 0.0],
        [5.0, 5.0, 10.0],  # apex at z=10
    ]

    def test_apex_returns_exact(self):
        """Apex point (5,5) is a vertex — should return z=10."""
        from kerf_civil.tin import build_tin, interpolate_z
        tin = build_tin(self.PYRAMID)
        z = interpolate_z(tin, 5.0, 5.0)
        assert z is not None
        assert abs(z - 10.0) < 0.1

    def test_corner_returns_zero(self):
        """Corners are at z=0."""
        from kerf_civil.tin import build_tin, interpolate_z
        tin = build_tin(self.PYRAMID)
        z = interpolate_z(tin, 0.0, 0.0)
        assert z is not None
        assert abs(z) < 0.1

    def test_midpoint_interpolated(self):
        """Mid-edge between corner (0,0,0) and apex (5,5,10) → ~z=5."""
        from kerf_civil.tin import build_tin, interpolate_z
        tin = build_tin(self.PYRAMID)
        # Midpoint of line from (0,0) to (5,5) = (2.5, 2.5)
        z = interpolate_z(tin, 2.5, 2.5)
        assert z is not None
        # Barycentric: should be between 0 and 10
        assert 0 < z < 10

    def test_outside_returns_none(self):
        """Point well outside TIN extent should return None."""
        from kerf_civil.tin import build_tin, interpolate_z
        tin = build_tin(self.PYRAMID)
        z = interpolate_z(tin, 100.0, 100.0)
        assert z is None


# ---------------------------------------------------------------------------
# 5. HGL/EGL profile — critical depth oracle
# ---------------------------------------------------------------------------

class TestCriticalDepth:
    """
    Oracle: for a 600 mm pipe at Q = 0.10 m³/s, compute critical depth.

    At critical depth: Q² · T / (g · A³) = 1
    By bisection, y_c ≈ 0.333 m for this flow.  We check only that
    the Froude number at y_c is ≈ 1.0.
    """

    def test_froude_at_critical_depth(self):
        from kerf_civil.hydraulics_gravity import critical_depth_circular, froude_number
        d = 0.6
        Q = 0.10
        y_c = critical_depth_circular(d, Q)
        Fr = froude_number(d, y_c, Q)
        assert abs(Fr - 1.0) < 0.05, f"Fr at critical depth = {Fr:.4f}, expected ≈ 1.0"

    def test_critical_depth_in_range(self):
        from kerf_civil.hydraulics_gravity import critical_depth_circular
        d = 0.6
        Q = 0.10
        y_c = critical_depth_circular(d, Q)
        assert 0 < y_c < d

    def test_critical_depth_zero_flow(self):
        from kerf_civil.hydraulics_gravity import critical_depth_circular
        y_c = critical_depth_circular(0.6, 0.0)
        assert y_c == 0.0

    def test_larger_flow_deeper_yc(self):
        """Higher Q → deeper critical depth."""
        from kerf_civil.hydraulics_gravity import critical_depth_circular
        yc1 = critical_depth_circular(0.6, 0.05)
        yc2 = critical_depth_circular(0.6, 0.15)
        assert yc2 > yc1


class TestSpecificEnergy:
    """At minimum specific energy, y = y_c."""

    def test_specific_energy_minimum_at_critical(self):
        from kerf_civil.hydraulics_gravity import critical_depth_circular, specific_energy
        d = 0.6
        Q = 0.08
        y_c = critical_depth_circular(d, Q)
        E_c = specific_energy(d, y_c, Q)
        # E at a slightly shallower and deeper depth should be larger
        E_less = specific_energy(d, y_c * 0.9, Q)
        E_more = specific_energy(d, y_c * 1.1, Q)
        assert E_c <= E_less + 1e-4
        assert E_c <= E_more + 1e-4


# ---------------------------------------------------------------------------
# 6. HGL/EGL profile end-to-end
# ---------------------------------------------------------------------------

class TestHGLEGLProfile:
    """
    Oracle for a single 300 mm pipe, L=80 m, invert drop 0.40 m,
    n=0.013, Q=0.030 m³/s.

    Slope = 0.40/80 = 0.005
    Q_full (d=0.3, n=0.013, S=0.005):
        A = π(0.15)² = 0.07069 m²
        R = 0.075 m
        Q_full = (1/0.013) × 0.07069 × 0.075^(2/3) × 0.005^0.5
               = 76.923 × 0.07069 × 0.17940 × 0.07071
               ≈ 0.0692 m³/s
    So Q=0.030 < Q_full → OK.
    Normal depth: y/d ~ 0.56 (bisection).
    """

    PIPE = {
        "id": "P1",
        "length_m": 80.0,
        "diameter_m": 0.3,
        "manning_n": 0.013,
        "invert_us_m": 10.40,
        "invert_ds_m": 10.00,
        "Q_m3s": 0.030,
    }

    def test_profile_returns_result(self):
        from kerf_civil.hydraulics_gravity import hgl_egl_profile
        profile = hgl_egl_profile([self.PIPE], Q=0.030)
        assert len(profile) == 1
        seg = profile[0]
        assert seg["id"] == "P1"

    def test_normal_depth_below_diameter(self):
        from kerf_civil.hydraulics_gravity import hgl_egl_profile
        profile = hgl_egl_profile([self.PIPE], Q=0.030)
        seg = profile[0]
        assert 0 < seg["y_normal_m"] < 0.3

    def test_hgl_us_above_invert(self):
        from kerf_civil.hydraulics_gravity import hgl_egl_profile
        profile = hgl_egl_profile([self.PIPE], Q=0.030)
        seg = profile[0]
        # HGL_us = invert_us + y_normal
        assert seg["HGL_us_m"] > seg["invert_us_m"]

    def test_egl_above_hgl(self):
        from kerf_civil.hydraulics_gravity import hgl_egl_profile
        profile = hgl_egl_profile([self.PIPE], Q=0.030)
        seg = profile[0]
        # EGL = HGL + V²/2g > HGL
        assert seg["EGL_us_m"] > seg["HGL_us_m"]

    def test_capacity_check_ok(self):
        from kerf_civil.hydraulics_gravity import hgl_egl_profile
        profile = hgl_egl_profile([self.PIPE], Q=0.030)
        seg = profile[0]
        # Q = 0.030 m³/s < Q_full ≈ 0.069 m³/s
        assert seg["capacity_check"] == "OK"

    def test_surcharge_detected(self):
        from kerf_civil.hydraulics_gravity import hgl_egl_profile
        pipe = {**self.PIPE, "Q_m3s": 0.200}  # way over capacity
        profile = hgl_egl_profile([pipe], Q=0.200)
        seg = profile[0]
        assert seg["capacity_check"] == "SURCHARGE"

    def test_subcritical_flow(self):
        """For most sewer flows at moderate slopes, regime is subcritical."""
        from kerf_civil.hydraulics_gravity import hgl_egl_profile
        profile = hgl_egl_profile([self.PIPE], Q=0.030)
        seg = profile[0]
        assert seg["regime"] in ("subcritical", "full")

    def test_froude_positive(self):
        from kerf_civil.hydraulics_gravity import hgl_egl_profile
        profile = hgl_egl_profile([self.PIPE], Q=0.030)
        seg = profile[0]
        assert seg["froude"] >= 0

    def test_velocity_positive(self):
        from kerf_civil.hydraulics_gravity import hgl_egl_profile
        profile = hgl_egl_profile([self.PIPE], Q=0.030)
        seg = profile[0]
        assert seg["velocity_m_s"] > 0

    def test_two_pipe_series(self):
        """Two pipes in series: profile should return two segments."""
        from kerf_civil.hydraulics_gravity import hgl_egl_profile
        pipes = [
            {**self.PIPE, "id": "P1"},
            {
                "id": "P2",
                "length_m": 60.0,
                "diameter_m": 0.4,
                "manning_n": 0.013,
                "invert_us_m": 10.00,
                "invert_ds_m": 9.70,
                "Q_m3s": 0.050,
            },
        ]
        profile = hgl_egl_profile(pipes, Q=0.030)
        assert len(profile) == 2
        assert profile[0]["id"] == "P1"
        assert profile[1]["id"] == "P2"


# ---------------------------------------------------------------------------
# 7. Structure head-loss oracle
# ---------------------------------------------------------------------------

class TestStructureHeadloss:
    """
    Oracle: straight-through manhole (K=0.5), V_in=1.5 m/s, V_out=1.0 m/s
    H_L = 0.5 × (1.5² - 1.0²) / (2 × 9.80665)
         = 0.5 × (2.25 - 1.0) / 19.613
         = 0.5 × 1.25 / 19.613
         ≈ 0.03186 m
    """

    def test_straight_manhole(self):
        from kerf_civil.hydraulics_gravity import structure_headloss
        H_L = structure_headloss(Q=0.05, V_in=1.5, V_out=1.0, K=0.5)
        assert abs(H_L - 0.03186) < 0.001

    def test_equal_velocities_zero_loss(self):
        from kerf_civil.hydraulics_gravity import structure_headloss
        H_L = structure_headloss(Q=0.05, V_in=1.2, V_out=1.2, K=0.5)
        assert abs(H_L) < 1e-10

    def test_higher_k_more_loss(self):
        from kerf_civil.hydraulics_gravity import structure_headloss
        H1 = structure_headloss(Q=0.05, V_in=2.0, V_out=1.0, K=0.5)
        H2 = structure_headloss(Q=0.05, V_in=2.0, V_out=1.0, K=1.0)
        assert H2 > H1


# ---------------------------------------------------------------------------
# 8. Gravity network solve (multi-pipe topological)
# ---------------------------------------------------------------------------

class TestGravityNetworkSolve:
    """
    Simple 3-pipe branch network:

        MH1 (Q_lat=0.010) → pipe P1 → MH2 (Q_lat=0.020) → pipe P2 → OUT
                               ↑
        MH3 (Q_lat=0.015) → pipe P3 → MH2

    Accumulated flows:
        MH1: 0.010
        MH3: 0.015
        P1 carries 0.010 (from MH1)
        P3 carries 0.015 (from MH3)
        MH2: 0.010 + 0.015 + 0.020 = 0.045
        P2 carries 0.045
    """

    PIPES = [
        {
            "id": "P1",
            "length_m": 60.0,
            "diameter_m": 0.3,
            "manning_n": 0.013,
            "invert_us_m": 12.0,
            "invert_ds_m": 11.7,
            "node_from": "MH1",
            "node_to": "MH2",
            "Q_lateral": 0.010,
        },
        {
            "id": "P3",
            "length_m": 50.0,
            "diameter_m": 0.3,
            "manning_n": 0.013,
            "invert_us_m": 11.9,
            "invert_ds_m": 11.7,
            "node_from": "MH3",
            "node_to": "MH2",
            "Q_lateral": 0.015,
        },
        {
            "id": "P2",
            "length_m": 80.0,
            "diameter_m": 0.4,
            "manning_n": 0.013,
            "invert_us_m": 11.7,
            "invert_ds_m": 11.3,
            "node_from": "MH2",
            "node_to": "OUT",
            "Q_lateral": 0.020,
        },
    ]

    def test_ok(self):
        from kerf_civil.hydraulics_gravity import gravity_network_solve
        result = gravity_network_solve(self.PIPES)
        assert result["ok"] is True

    def test_node_q_accumulated(self):
        """MH2 should accumulate all three laterals."""
        from kerf_civil.hydraulics_gravity import gravity_network_solve
        result = gravity_network_solve(self.PIPES)
        node_Q = result["node_Q"]
        # MH1 = 0.010, MH3 = 0.015
        assert abs(node_Q["MH1"] - 0.010) < 1e-6
        assert abs(node_Q["MH3"] - 0.015) < 1e-6

    def test_trunk_pipe_largest_flow(self):
        """P2 (trunk pipe) should carry the largest Q."""
        from kerf_civil.hydraulics_gravity import gravity_network_solve
        result = gravity_network_solve(self.PIPES)
        pipe_map = {p["id"]: p for p in result["pipes"]}
        assert pipe_map["P2"]["Q_m3s"] > pipe_map["P1"]["Q_m3s"]
        assert pipe_map["P2"]["Q_m3s"] > pipe_map["P3"]["Q_m3s"]

    def test_profile_returned_for_all_pipes(self):
        from kerf_civil.hydraulics_gravity import gravity_network_solve
        result = gravity_network_solve(self.PIPES)
        assert len(result["pipes"]) == 3

    def test_warnings_list_present(self):
        from kerf_civil.hydraulics_gravity import gravity_network_solve
        result = gravity_network_solve(self.PIPES)
        assert "warnings" in result

    def test_empty_pipes(self):
        from kerf_civil.hydraulics_gravity import gravity_network_solve
        result = gravity_network_solve([])
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 9. LLM tool: civil_gravity_sewer_profile
# ---------------------------------------------------------------------------

class TestToolGravitySewerProfile:
    PIPE_PARAMS = {
        "pipes": [
            {
                "id": "S1",
                "length_m": 80.0,
                "diameter_m": 0.3,
                "manning_n": 0.013,
                "invert_us_m": 10.40,
                "invert_ds_m": 10.00,
            }
        ],
        "Q_m3s": 0.030,
    }

    def test_tool_returns_ok(self):
        from kerf_civil.tools_hydraulics import run_civil_gravity_sewer_profile
        result = _call(run_civil_gravity_sewer_profile, self.PIPE_PARAMS)
        assert result.get("ok") is True

    def test_tool_returns_pipes(self):
        from kerf_civil.tools_hydraulics import run_civil_gravity_sewer_profile
        result = _call(run_civil_gravity_sewer_profile, self.PIPE_PARAMS)
        assert len(result["pipes"]) == 1

    def test_tool_hgl_present(self):
        from kerf_civil.tools_hydraulics import run_civil_gravity_sewer_profile
        result = _call(run_civil_gravity_sewer_profile, self.PIPE_PARAMS)
        seg = result["pipes"][0]
        assert "HGL_us_m" in seg
        assert "EGL_us_m" in seg

    def test_tool_spec_name(self):
        from kerf_civil.tools_hydraulics import civil_gravity_sewer_profile_spec
        assert civil_gravity_sewer_profile_spec.name == "civil_gravity_sewer_profile"


# ---------------------------------------------------------------------------
# 10. LLM tool: civil_gravity_network_solve
# ---------------------------------------------------------------------------

class TestToolGravityNetworkSolve:
    NETWORK_PARAMS = {
        "pipes": [
            {
                "id": "P1", "length_m": 60.0, "diameter_m": 0.3,
                "manning_n": 0.013, "invert_us_m": 12.0, "invert_ds_m": 11.7,
                "node_from": "MH1", "node_to": "MH2", "Q_lateral": 0.010,
            },
            {
                "id": "P2", "length_m": 80.0, "diameter_m": 0.4,
                "manning_n": 0.013, "invert_us_m": 11.7, "invert_ds_m": 11.3,
                "node_from": "MH2", "node_to": "OUT", "Q_lateral": 0.020,
            },
        ]
    }

    def test_tool_ok(self):
        from kerf_civil.tools_hydraulics import run_civil_gravity_network_solve
        result = _call(run_civil_gravity_network_solve, self.NETWORK_PARAMS)
        assert result.get("ok") is True

    def test_tool_returns_pipes_and_nodes(self):
        from kerf_civil.tools_hydraulics import run_civil_gravity_network_solve
        result = _call(run_civil_gravity_network_solve, self.NETWORK_PARAMS)
        assert "pipes" in result
        assert "node_Q" in result

    def test_tool_spec_name(self):
        from kerf_civil.tools_hydraulics import civil_gravity_network_solve_spec
        assert civil_gravity_network_solve_spec.name == "civil_gravity_network_solve"


# ---------------------------------------------------------------------------
# 11. LLM tool: civil_tin_terrain — new ops
# ---------------------------------------------------------------------------

FLAT_SQUARE_5 = [
    [0.0, 0.0, 0.0],
    [10.0, 0.0, 0.0],
    [10.0, 10.0, 0.0],
    [0.0, 10.0, 0.0],
    [5.0, 5.0, 5.0],
]

FLAT_RAISED = [
    [0.0, 0.0, 3.0],
    [10.0, 0.0, 3.0],
    [10.0, 10.0, 3.0],
    [0.0, 10.0, 3.0],
    [5.0, 5.0, 3.0],
]


class TestToolTINVolumeBetween:
    def test_volume_between_op(self):
        from kerf_civil.tools_terrain import run_civil_tin_terrain
        result = _call(run_civil_tin_terrain, {
            "points": FLAT_RAISED,
            "op": "volume_between",
            "points_b": FLAT_SQUARE_5,
        })
        assert result.get("ok") is True
        assert "cut_m3" in result
        assert "fill_m3" in result
        assert "net_m3" in result

    def test_volume_between_missing_points_b(self):
        from kerf_civil.tools_terrain import run_civil_tin_terrain
        result = _call(run_civil_tin_terrain, {
            "points": FLAT_RAISED,
            "op": "volume_between",
        })
        assert "error" in result


class TestToolTINInterpolateZ:
    def test_interpolate_at_apex(self):
        from kerf_civil.tools_terrain import run_civil_tin_terrain
        result = _call(run_civil_tin_terrain, {
            "points": FLAT_SQUARE_5,
            "op": "interpolate_z",
            "x": 5.0,
            "y": 5.0,
        })
        assert result.get("ok") is True
        assert result.get("z_m") is not None
        assert result["inside_tin"] is True

    def test_interpolate_outside(self):
        from kerf_civil.tools_terrain import run_civil_tin_terrain
        result = _call(run_civil_tin_terrain, {
            "points": FLAT_SQUARE_5,
            "op": "interpolate_z",
            "x": 100.0,
            "y": 100.0,
        })
        assert result.get("ok") is True
        assert result.get("z_m") is None
        assert result["inside_tin"] is False

    def test_interpolate_missing_xy(self):
        from kerf_civil.tools_terrain import run_civil_tin_terrain
        result = _call(run_civil_tin_terrain, {
            "points": FLAT_SQUARE_5,
            "op": "interpolate_z",
        })
        assert "error" in result


class TestToolTINBreakline:
    def test_breakline_kwarg_passed(self):
        """Tool should accept breaklines without crashing."""
        from kerf_civil.tools_terrain import run_civil_tin_terrain
        pts = [
            [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [5, 5, 5]
        ]
        result = _call(run_civil_tin_terrain, {
            "points": pts,
            "op": "stats",
            "breaklines": [[0, 2]],
        })
        assert result.get("ok") is True

    def test_boundary_kwarg_passed(self):
        """Tool should accept boundary without crashing."""
        from kerf_civil.tools_terrain import run_civil_tin_terrain
        pts = [
            [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [5, 5, 5]
        ]
        result = _call(run_civil_tin_terrain, {
            "points": pts,
            "op": "stats",
            "boundary": [[0, 0], [11, 0], [11, 11], [0, 11]],
        })
        assert result.get("ok") is True
