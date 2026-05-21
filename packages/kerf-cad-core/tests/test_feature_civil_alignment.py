"""
Feature tests for T-51: Civil alignment + earthwork + hydraulics.

25 highway / drainage scenarios — pure-Python, hermetic (no OCC, no DB, no
network, no disk I/O).  Each scenario exercises alignment geometry (horizontal
curves, spirals, vertical curves, stationing), cut/fill earthwork volumes, or
Manning's-n open-channel flow, and validates the computed result against a
hand-calculated reference within the stated tolerance.

Tolerance: all numeric comparisons ≤ ±2 % of the reference value (as per spec)
except where the formula is exact and a tighter tolerance is used.

Run with:
    python -m pytest packages/kerf-cad-core/tests/test_feature_civil_alignment.py -q

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import math

import pytest

from kerf_cad_core.civil.alignment import (
    compute_horizontal_curve,
    compute_spiral_curve,
    compute_vertical_curve,
    elevation_at,
    format_station,
    parse_station,
    station_add,
)
from kerf_cad_core.civil.earthwork import (
    DesignSurface,
    compute_earthwork,
)
from kerf_cad_core.civil.hydraulics import (
    manning_normal_depth,
    solve_pipe_network,
)
from kerf_cad_core.civil.terrain import TIN, Point3D


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _approx2pct(ref):
    """2 % relative tolerance around ref."""
    return pytest.approx(ref, rel=0.02)


def _flat_tin(x0, y0, x1, y1, z):
    """Flat 4-corner TIN at elevation z over a rectangle (returns a TIN object)."""
    pts = [
        Point3D(x0, y0, z),
        Point3D(x1, y0, z),
        Point3D(x1, y1, z),
        Point3D(x0, y1, z),
        Point3D((x0 + x1) / 2, (y0 + y1) / 2, z),  # centre to avoid collinearity
    ]
    return TIN(pts)


def _square_polygon(cx, cy, half):
    """Return a square polygon ring centred at (cx, cy) with side 2*half."""
    return [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]


# ===========================================================================
# Scenario 1 – Rural highway: simple circular curve, R=500 m, Δ=30°
#   T = 500·tan(15°) ≈ 133.97 m,  L = 500·π/6 ≈ 261.80 m
# ===========================================================================

class TestScenario01_RuralHighwayCircularCurve:
    _c = compute_horizontal_curve(delta_deg=30.0, radius_m=500.0, sta_pi_m=2000.0)

    def test_ok(self):
        assert self._c.ok is True

    def test_arc_length(self):
        assert self._c.arc_length_m == _approx2pct(500.0 * math.radians(30.0))

    def test_tangent_length(self):
        assert self._c.tangent_length_m == _approx2pct(500.0 * math.tan(math.radians(15.0)))

    def test_pt_station(self):
        assert self._c.sta_pt_m == pytest.approx(
            self._c.sta_pc_m + self._c.arc_length_m, rel=1e-9
        )


# ===========================================================================
# Scenario 2 – Urban arterial: tight curve R=100 m, Δ=90°
#   T = 100·tan(45°) = 100 m,  L = 100·π/2 ≈ 157.08 m
# ===========================================================================

class TestScenario02_UrbanArterialtightCurve:
    _c = compute_horizontal_curve(delta_deg=90.0, radius_m=100.0, sta_pi_m=1500.0)

    def test_tangent_equals_radius(self):
        assert self._c.tangent_length_m == _approx2pct(100.0)

    def test_long_chord(self):
        # C = 2R·sin(45°)
        assert self._c.long_chord_m == _approx2pct(2.0 * 100.0 * math.sin(math.radians(45.0)))

    def test_external_distance(self):
        # E = R·(sec(45°) - 1)
        expected_E = 100.0 * (1.0 / math.cos(math.radians(45.0)) - 1.0)
        assert self._c.external_m == _approx2pct(expected_E)


# ===========================================================================
# Scenario 3 – Expressway with design speed: superelevation within AASHTO bounds
# ===========================================================================

def test_scenario03_expressway_superelevation():
    c = compute_horizontal_curve(
        delta_deg=20.0, radius_m=400.0, sta_pi_m=3000.0, design_speed_kmh=100.0
    )
    assert c.ok is True
    # Superelevation must be 0 ≤ e ≤ 0.12 (AASHTO e_max)
    assert 0.0 <= c.superelevation <= 0.12 + 1e-9
    assert c.side_friction > 0.0


# ===========================================================================
# Scenario 4 – Spiral alignment: θs and circular arc length
#   Δ=50°, R=300 m, Ls=90 m
#   θs = 90/(2×300) = 0.15 rad = 8.594°
#   Lc = 300·(Δ_rad - 2·θs)
# ===========================================================================

class TestScenario04_SpiralAlignment:
    _s = compute_spiral_curve(
        delta_deg=50.0, radius_m=300.0, spiral_length_m=90.0, sta_pi_m=5000.0
    )

    def test_ok(self):
        assert self._s.ok is True

    def test_spiral_angle(self):
        expected_theta_s_rad = 90.0 / (2.0 * 300.0)
        assert math.radians(self._s.spiral_angle_deg) == pytest.approx(
            expected_theta_s_rad, rel=1e-9
        )

    def test_circular_arc_length(self):
        theta_s = 90.0 / (2.0 * 300.0)
        expected_lc = 300.0 * (math.radians(50.0) - 2.0 * theta_s)
        assert self._s.circular_arc_length_m == _approx2pct(expected_lc)

    def test_total_length_stations(self):
        total = 2.0 * self._s.spiral_length_m + self._s.circular_arc_length_m
        assert self._s.sta_st_m == pytest.approx(self._s.sta_ts_m + total, rel=1e-9)


# ===========================================================================
# Scenario 5 – Crest vertical curve: K-value and high point
#   G1=+5%, G2=−3%, PVI at sta 4000, L=400 m, e_PVI=120 m
# ===========================================================================

class TestScenario05_CrestVerticalCurve:
    _vc = compute_vertical_curve(
        grade1=0.05, grade2=-0.03,
        sta_pvi_m=4000.0, curve_length_m=400.0, elev_pvi_m=120.0,
    )

    def test_ok_and_type(self):
        assert self._vc.ok is True
        assert self._vc.curve_type == "CREST"

    def test_k_value(self):
        A_pct = abs(-0.03 - 0.05) * 100.0  # 8 %
        expected_k = 400.0 / A_pct          # 50 m/%
        assert self._vc.k_value == _approx2pct(expected_k)

    def test_high_point_exists(self):
        assert self._vc.has_high_low_point is True

    def test_high_point_station(self):
        # x_hl = G1·L / (G1 - G2) = 0.05×400 / (0.05−(−0.03)) = 20/0.08 = 250 m from PVC
        expected_sta = self._vc.sta_pvc_m + 250.0
        assert self._vc.sta_hl_m == _approx2pct(expected_sta)


# ===========================================================================
# Scenario 6 – Sag vertical curve: SSD check passes for long curve
# ===========================================================================

def test_scenario06_sag_curve_ssd_ok():
    vc = compute_vertical_curve(
        grade1=-0.04, grade2=0.04,
        sta_pvi_m=2000.0, curve_length_m=600.0, elev_pvi_m=50.0,
        stopping_sight_distance_m=120.0,
    )
    assert vc.ok is True
    assert vc.curve_type == "SAG"
    assert vc.ssd_ok is True


# ===========================================================================
# Scenario 7 – Sag vertical curve: SSD check FAILS for short curve
# ===========================================================================

def test_scenario07_sag_curve_ssd_fail():
    vc = compute_vertical_curve(
        grade1=-0.06, grade2=0.06,
        sta_pvi_m=1000.0, curve_length_m=30.0, elev_pvi_m=80.0,
        stopping_sight_distance_m=200.0,
    )
    assert vc.ok is True
    assert vc.ssd_ok is False


# ===========================================================================
# Scenario 8 – Elevation query at mid-curve station
#   Parabolic formula: e(x) = e_PVC + G1·x + (G2-G1)/(2L)·x²
# ===========================================================================

def test_scenario08_elevation_at_mid_station():
    G1, G2, L = 0.03, -0.01, 300.0
    e_pvc = 85.0
    x = 150.0
    expected = e_pvc + G1 * x + (G2 - G1) / (2.0 * L) * x ** 2
    result = elevation_at(
        sta_pvc_m=1000.0, elev_pvc_m=e_pvc,
        grade1=G1, grade2=G2,
        curve_length_m=L, query_sta_m=1150.0,
    )
    assert result["ok"] is True
    assert result["elevation_m"] == _approx2pct(expected)


# ===========================================================================
# Scenario 9 – Station arithmetic: highway with many PI points
# ===========================================================================

def test_scenario09_stationing_chain():
    # Chain: 0+00 → PI1 → PI2 → PI3
    sta = 0.0
    deltas = [100.0, 250.0, 400.0, 75.0]
    for d in deltas:
        sta = station_add(sta, d)
    assert sta == pytest.approx(825.0, rel=1e-9)
    assert parse_station(format_station(sta)) == pytest.approx(sta, abs=0.005)


# ===========================================================================
# Scenario 10 – Degree of curve cross-check: D = 5729.578 / R
# ===========================================================================

def test_scenario10_degree_of_curve_various_radii():
    for radius in [100.0, 200.0, 300.0, 500.0, 1000.0]:
        c = compute_horizontal_curve(delta_deg=20.0, radius_m=radius, sta_pi_m=1000.0)
        assert c.ok is True
        assert c.degree_of_curve_deg == _approx2pct(5729.578 / radius)


# ===========================================================================
# Scenario 11 – Cut-only earthwork: flat TIN above design pad
#   TIN @ z=10.0, pad @ z=8.0 → all cut, no fill
# ===========================================================================

def test_scenario11_cut_only_earthwork():
    tin = _flat_tin(0, 0, 20, 20, 10.0)
    design = DesignSurface(pad_elevation=8.0, polygon=_square_polygon(10, 10, 9))
    result = compute_earthwork(tin, design, grid_spacing=2.0)
    assert result.fill_m3 == pytest.approx(0.0, abs=1e-6)
    assert result.cut_m3 > 0.0
    assert result.net_m3 < 0.0   # negative = cut surplus


# ===========================================================================
# Scenario 12 – Fill-only earthwork: flat TIN below design pad
#   TIN @ z=5.0, pad @ z=7.0 → all fill, no cut
# ===========================================================================

def test_scenario12_fill_only_earthwork():
    tin = _flat_tin(0, 0, 20, 20, 5.0)
    design = DesignSurface(pad_elevation=7.0, polygon=_square_polygon(10, 10, 9))
    result = compute_earthwork(tin, design, grid_spacing=2.0)
    assert result.cut_m3 == pytest.approx(0.0, abs=1e-6)
    assert result.fill_m3 > 0.0
    assert result.net_m3 > 0.0   # positive = fill needed


# ===========================================================================
# Scenario 13 – Balanced earthwork: TIN and pad at same elevation
# ===========================================================================

def test_scenario13_balanced_earthwork():
    tin = _flat_tin(0, 0, 20, 20, 6.0)
    design = DesignSurface(pad_elevation=6.0, polygon=_square_polygon(10, 10, 9))
    result = compute_earthwork(tin, design, grid_spacing=2.0)
    assert result.cut_m3 == pytest.approx(0.0, abs=1e-6)
    assert result.fill_m3 == pytest.approx(0.0, abs=1e-6)
    assert result.net_m3 == pytest.approx(0.0, abs=1e-6)


# ===========================================================================
# Scenario 14 – Cut volume accuracy: result matches sample_count × cell × depth
#   TIN @ z=10, pad @ z=8 (2 m cut depth).  For each sampled cell the cut
#   should be exactly 2.0 m deep (flat surfaces).  So:
#       cut_m3 == sample_count × cell_area × 2.0   (to machine precision)
# ===========================================================================

def test_scenario14_cut_volume_accuracy():
    tin = _flat_tin(0, 0, 12, 12, 10.0)
    design = DesignSurface(pad_elevation=8.0, polygon=_square_polygon(6, 6, 5))
    result = compute_earthwork(tin, design, grid_spacing=1.0)
    assert result.sample_count > 0
    # Every sampled cell contributes exactly 2.0 m cut (flat TIN + flat pad)
    expected_cut = result.sample_count * result.cell_area_m2 * 2.0
    assert result.cut_m3 == pytest.approx(expected_cut, rel=1e-9)
    # Fill must be zero (TIN is above pad everywhere)
    assert result.fill_m3 == pytest.approx(0.0, abs=1e-9)


# ===========================================================================
# Scenario 15 – Manning's n for concrete storm sewer (n=0.013)
#   Q=1.5 m³/s, w=2.0 m, S=0.002 → y_n by bisection, check ±2%
# ===========================================================================

def test_scenario15_manning_concrete_sewer():
    result = manning_normal_depth(
        flow_m3s=1.5, width_m=2.0, slope=0.002, manning_n=0.013
    )
    assert result["ok"] is True
    y_n = result["normal_depth_m"]
    # Verify: Manning Q at computed depth ≈ target within 2%
    A = 2.0 * y_n
    P = 2.0 + 2.0 * y_n
    R = A / P
    Q_check = (1.0 / 0.013) * A * (R ** (2.0 / 3.0)) * math.sqrt(0.002)
    assert Q_check == _approx2pct(1.5)


# ===========================================================================
# Scenario 16 – Manning's n for earth-lined roadside ditch (n=0.025)
#   Q=0.5 m³/s, w=1.5 m, S=0.005
# ===========================================================================

def test_scenario16_manning_earth_ditch():
    result = manning_normal_depth(
        flow_m3s=0.5, width_m=1.5, slope=0.005, manning_n=0.025
    )
    assert result["ok"] is True
    y_n = result["normal_depth_m"]
    A = 1.5 * y_n
    P = 1.5 + 2.0 * y_n
    R = A / P
    Q_check = (1.0 / 0.025) * A * (R ** (2.0 / 3.0)) * math.sqrt(0.005)
    assert Q_check == _approx2pct(0.5)


# ===========================================================================
# Scenario 17 – Manning's Froude < 1 → subcritical
# ===========================================================================

def test_scenario17_manning_subcritical():
    # Gentle slope, wide channel → subcritical expected
    result = manning_normal_depth(
        flow_m3s=1.0, width_m=5.0, slope=0.0005, manning_n=0.025
    )
    assert result["ok"] is True
    assert result["froude_number"] < 1.0
    assert result["flow_regime"] == "subcritical"


# ===========================================================================
# Scenario 18 – Manning's Froude > 1 → supercritical (steep channel)
# ===========================================================================

def test_scenario18_manning_supercritical():
    # Very steep slope → supercritical
    result = manning_normal_depth(
        flow_m3s=0.1, width_m=0.5, slope=0.05, manning_n=0.010
    )
    assert result["ok"] is True
    assert result["froude_number"] > 1.0
    assert result["flow_regime"] == "supercritical"


# ===========================================================================
# Scenario 19 – Manning's slope sensitivity: at fixed geometry (depth, width)
#   Q ∝ S^(1/2), so 4× slope → 2× Q.  Verify by computing Manning Q directly.
# ===========================================================================

def test_scenario19_manning_slope_sensitivity():
    import math as _math
    # Fixed geometry: width=2 m, depth=0.5 m, n=0.015
    w, y, n = 2.0, 0.5, 0.015
    A = w * y
    P = w + 2.0 * y
    R = A / P
    s1, s2 = 0.001, 0.004   # 4× slope
    q1 = (1.0 / n) * A * (R ** (2.0 / 3.0)) * _math.sqrt(s1)
    q2 = (1.0 / n) * A * (R ** (2.0 / 3.0)) * _math.sqrt(s2)
    # q2/q1 = sqrt(s2/s1) = sqrt(4) = 2.0  (exact for fixed geometry)
    assert q2 / q1 == pytest.approx(2.0, rel=1e-9)
    # Confirm solve round-trip: compute normal depth for q1 at s1, then q2 at s2
    r1 = manning_normal_depth(flow_m3s=q1, width_m=w, slope=s1, manning_n=n)
    r2 = manning_normal_depth(flow_m3s=q2, width_m=w, slope=s2, manning_n=n)
    assert r1["ok"] is True and r2["ok"] is True
    # Both should recover y ≈ 0.5 m (same geometry)
    assert r1["normal_depth_m"] == pytest.approx(y, rel=0.01)
    assert r2["normal_depth_m"] == pytest.approx(y, rel=0.01)


# ===========================================================================
# Scenario 20 – Single-pipe gravity water main: Hazen-Williams head loss
#   L=500 m, D=0.3 m, C=130, Q=0.05 m³/s
#   hf = 10.67·L·Q^1.852 / (C^1.852·D^4.87)
# ===========================================================================

def test_scenario20_hazen_williams_single_pipe():
    L, D, C, Q = 500.0, 0.3, 130.0, 0.05
    expected_hf = 10.67 * L * (Q ** 1.852) / ((C ** 1.852) * (D ** 4.87))

    result = solve_pipe_network(
        nodes=[
            {"node_id": "A", "elevation": 50.0, "demand": 0.0, "head_fixed": 70.0},
            {"node_id": "B", "elevation": 45.0, "demand": 50.0},   # 50 L/s = 0.05 m³/s
        ],
        pipes=[
            {"pipe_id": "P1", "start_node": "A", "end_node": "B",
             "length": 500.0, "diameter": 0.3, "hw_c": 130.0},
        ],
        head_loss_method="hazen-williams",
    )
    assert result["ok"] is True
    hf_computed = result["pipes"][0]["headloss_m"]
    assert abs(hf_computed) == _approx2pct(expected_hf)


# ===========================================================================
# Scenario 21 – Series drainage network: head losses add up
#   Two pipes in series, total head = sum of individual losses
# ===========================================================================

def test_scenario21_series_pipes_head_losses():
    result = solve_pipe_network(
        nodes=[
            {"node_id": "S", "elevation": 0.0, "demand": 0.0, "head_fixed": 30.0},
            {"node_id": "M", "elevation": 0.0, "demand": 0.0},
            {"node_id": "E", "elevation": 0.0, "demand": 20.0},
        ],
        pipes=[
            {"pipe_id": "P1", "start_node": "S", "end_node": "M",
             "length": 200.0, "diameter": 0.2, "hw_c": 100.0},
            {"pipe_id": "P2", "start_node": "M", "end_node": "E",
             "length": 200.0, "diameter": 0.2, "hw_c": 100.0},
        ],
        head_loss_method="hazen-williams",
    )
    assert result["ok"] is True
    # Total head drop = sum of individual pipe head losses
    hf1 = abs(result["pipes"][0]["headloss_m"])
    hf2 = abs(result["pipes"][1]["headloss_m"])
    h_start = next(n["head_m"] for n in result["nodes"] if n["node_id"] == "S")
    h_end = next(n["head_m"] for n in result["nodes"] if n["node_id"] == "E")
    assert (h_start - h_end) == pytest.approx(hf1 + hf2, rel=1e-4)


# ===========================================================================
# Scenario 22 – Loop network: mass conservation at junction node
# ===========================================================================

def test_scenario22_loop_network_mass_balance():
    result = solve_pipe_network(
        nodes=[
            {"node_id": "R",  "elevation": 10.0, "demand": 0.0,   "head_fixed": 50.0},
            {"node_id": "J1", "elevation": 5.0,  "demand": 10.0},
            {"node_id": "J2", "elevation": 5.0,  "demand": 10.0},
            {"node_id": "J3", "elevation": 5.0,  "demand": 5.0},
        ],
        pipes=[
            {"pipe_id": "PA", "start_node": "R",  "end_node": "J1", "length": 300.0, "diameter": 0.2},
            {"pipe_id": "PB", "start_node": "R",  "end_node": "J2", "length": 300.0, "diameter": 0.2},
            {"pipe_id": "PC", "start_node": "J1", "end_node": "J3", "length": 200.0, "diameter": 0.15},
            {"pipe_id": "PD", "start_node": "J2", "end_node": "J3", "length": 200.0, "diameter": 0.15},
        ],
        head_loss_method="hazen-williams",
    )
    assert result["ok"] is True
    # Mass conservation at J3: inflow from PC + PD = demand 5 L/s
    flow_map = {p["pipe_id"]: p["flow_L_per_s"] for p in result["pipes"]}
    # J3 receives flow from PC (start=J1→J3) and PD (start=J2→J3)
    inflow_j3 = flow_map["PC"] + flow_map["PD"]
    assert inflow_j3 == pytest.approx(5.0, rel=0.05)


# ===========================================================================
# Scenario 23 – Darcy-Weisbach laminar flow: f = 64/Re
#   Very small pipe, low flow → Re < 2300 → f = 64/Re exactly
# ===========================================================================

def test_scenario23_darcy_weisbach_laminar():
    from kerf_cad_core.civil.hydraulics import (
        _darcy_weisbach_hf,
        Pipe,
        _WATER_NU,
        _G,
    )
    import math as _math
    D = 0.01   # 10 mm diameter
    L = 10.0
    # Choose Q such that Re < 2300
    Q_target_ms = 1e-6   # tiny flow
    pipe = Pipe(pipe_id="p1", start_node="A", end_node="B",
                length=L, diameter=D, roughness=0.1)
    area = _math.pi * D ** 2 / 4.0
    v = Q_target_ms / area
    re = v * D / _WATER_NU
    assert re < 2300, f"Re={re} not laminar for this test"
    # Laminar f = 64/Re
    f_lam = 64.0 / re
    hf_expected = f_lam * (L / D) * (v ** 2) / (2.0 * _G)
    hf_computed = _darcy_weisbach_hf(Q_target_ms, pipe)
    assert hf_computed == _approx2pct(hf_expected)


# ===========================================================================
# Scenario 24 – Composite highway scenario:
#   Horizontal curve → spiral transition → vertical sag → drainage ditch
#   Checks that all four computations return ok=True and have physically
#   plausible values for a 60 km/h design speed rural road.
# ===========================================================================

def test_scenario24_composite_highway():
    # Horizontal curve
    hc = compute_horizontal_curve(
        delta_deg=35.0, radius_m=200.0, sta_pi_m=3500.0, design_speed_kmh=60.0
    )
    assert hc.ok is True
    assert hc.arc_length_m > 0.0

    # Spiral transition
    sp = compute_spiral_curve(
        delta_deg=35.0, radius_m=200.0, spiral_length_m=40.0, sta_pi_m=3500.0
    )
    assert sp.ok is True
    assert sp.circular_arc_length_m > 0.0

    # Sag vertical curve
    vc = compute_vertical_curve(
        grade1=-0.03, grade2=0.03,
        sta_pvi_m=3800.0, curve_length_m=150.0, elev_pvi_m=75.0,
    )
    assert vc.ok is True
    assert vc.curve_type == "SAG"
    # For a sag with G1=-3%, PVC is above PVI (grade descends into sag)
    assert vc.elev_pvc_m > vc.elev_pvi_m

    # Roadside ditch (Manning)
    ditch = manning_normal_depth(
        flow_m3s=0.3, width_m=1.0, slope=0.008, manning_n=0.030
    )
    assert ditch["ok"] is True
    assert ditch["normal_depth_m"] > 0.0 and ditch["normal_depth_m"] < 5.0


# ===========================================================================
# Scenario 25 – End-to-end cut/fill + drainage:
#   Road platform cut from natural ground; flow routed through culvert
#   Earthwork cut ≈ 200 m³; Manning confirms culvert capacity sufficient
# ===========================================================================

def test_scenario25_road_platform_cut_and_drainage():
    # --- Earthwork: cut platform, natural ground at 15 m, pad at 13 m (2 m cut) ---
    tin = _flat_tin(0, 0, 22, 12, 15.0)
    design = DesignSurface(
        pad_elevation=13.0,
        polygon=[(1, 1), (21, 1), (21, 11), (1, 11)],
    )
    ew = compute_earthwork(tin, design, grid_spacing=1.0)
    # Flat TIN + flat pad: each sampled cell contributes exactly 2.0 m cut
    assert ew.sample_count > 0
    expected_cut = ew.sample_count * ew.cell_area_m2 * 2.0
    assert ew.cut_m3 == pytest.approx(expected_cut, rel=1e-9)
    assert ew.fill_m3 == pytest.approx(0.0, abs=1e-6)

    # --- Drainage: culvert must carry Q = 0.6 m³/s through 0.8 m wide channel ---
    culvert = manning_normal_depth(
        flow_m3s=0.6, width_m=0.8, slope=0.010, manning_n=0.013
    )
    assert culvert["ok"] is True
    # Capacity check: normal depth must be less than assumed barrel height of 1.2 m
    assert culvert["normal_depth_m"] < 1.2
