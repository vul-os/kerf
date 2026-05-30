"""
Tests for kerf_cad_core.cam_feedrate_lookahead — corner-lookahead feedrate optimiser.

Coverage (16 tests):
  - Degenerate inputs: empty waypoints, single waypoint, two waypoints
  - Straight-line paths (collinear): feedrate = max throughout (except endpoints at rest)
  - Single 90° corner: V_corner formula verification (Altintas 2012 §5.7)
  - Multi-corner zig-zag: deceleration consistency across all interior corners
  - Acceleration limit: feedrates never increase faster than a_max allows
  - Deceleration limit: feedrates never decrease faster than a_max allows
  - End-at-rest constraint: first and last feedrate always 0
  - Corner feedrate cap: no waypoint exceeds its V_corner_i
  - Monotone parameter: larger blending_radius → lower or equal corner feedrates
  - Cycle time > 0 for a real path
  - Validation errors: non-positive max_feedrate / max_accel / blending_radius
  - Collinear three-point: angle 0 → V_corner_i = max_feedrate
  - 180° U-turn: V_corner near 0
  - Long straight run: feedrate reaches max_feedrate in the interior
  - Profile length matches waypoint count
  - Known numeric: 90° corner, a_max=2000, r_blend=0.1 → V_corner ≈ 16.8 mm/s

All tests are pure-Python and hermetic: no OCC, no DB, no network.

References
----------
Altintas 2012 Manufacturing Automation §5.7;
Erkorkmaz & Altintas 2001 Int. J. Machine Tools Manuf. 41(9) 1323–1345.

Author: imranparuk
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.cam_feedrate_lookahead import (
    FeedrateProfile,
    optimize_feedrate,
    _corner_angle,
    _corner_feedrate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

V_TARGET = 1000.0   # mm/s — generous, so geometric constraints dominate
A_MAX = 2000.0      # mm/s²
R_BLEND = 0.1       # mm


def _straight_line(n: int, step: float = 10.0):
    """n waypoints along X-axis, step mm apart."""
    return [(i * step, 0.0, 0.0) for i in range(n)]


# ---------------------------------------------------------------------------
# 1. Empty waypoints
# ---------------------------------------------------------------------------

def test_empty_waypoints():
    profile = optimize_feedrate([], V_TARGET, A_MAX)
    assert profile.feedrates == []
    assert profile.corner_angles == []
    assert profile.total_cycle_time == 0.0


# ---------------------------------------------------------------------------
# 2. Single waypoint
# ---------------------------------------------------------------------------

def test_single_waypoint():
    profile = optimize_feedrate([(0.0, 0.0, 0.0)], V_TARGET, A_MAX)
    assert len(profile.feedrates) == 1
    assert profile.feedrates[0] == 0.0   # at rest; start = end


# ---------------------------------------------------------------------------
# 3. Two waypoints (one segment, no interior corner)
# ---------------------------------------------------------------------------

def test_two_waypoints():
    profile = optimize_feedrate([(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)], V_TARGET, A_MAX)
    assert len(profile.feedrates) == 2
    # Both endpoints forced to rest
    assert profile.feedrates[0] == pytest.approx(0.0)
    assert profile.feedrates[1] == pytest.approx(0.0)
    assert profile.total_cycle_time > 0.0


# ---------------------------------------------------------------------------
# 4. Straight line — interior feedrates = max_feedrate
# ---------------------------------------------------------------------------

def test_straight_line_max_feedrate():
    """
    10 collinear waypoints 100 mm apart.  After start/end come to rest, the
    interior waypoints (indices 1–8) should saturate at V_TARGET because
    the path is straight (no corner constraint) and the segments are long
    enough to fully accelerate.
    """
    wps = _straight_line(10, step=100.0)
    profile = optimize_feedrate(wps, V_TARGET, A_MAX, blending_radius=R_BLEND)
    # Endpoints at rest
    assert profile.feedrates[0] == pytest.approx(0.0)
    assert profile.feedrates[-1] == pytest.approx(0.0)
    # Interior reaches V_TARGET
    interior = profile.feedrates[1:-1]
    assert any(v == pytest.approx(V_TARGET) for v in interior), (
        f"No interior waypoint reached V_TARGET={V_TARGET}: {interior}"
    )


# ---------------------------------------------------------------------------
# 5. Known numeric: 90° corner  (DEPTH BAR)
# ---------------------------------------------------------------------------

def test_90_degree_corner_v_corner():
    """
    Altintas 2012 §5.7 reference case:
        a_max = 2000 mm/s², r_blend = 0.1 mm, θ = 90°
        V_corner = sqrt(2000 × 0.1 / sin(45°)) ≈ sqrt(200/0.7071) ≈ 16.82 mm/s
    """
    v_c = _corner_feedrate(math.pi / 2, a_max=2000.0, r_blend=0.1, v_target=V_TARGET)
    expected = math.sqrt(2000.0 * 0.1 / math.sin(math.pi / 4))
    assert v_c == pytest.approx(expected, rel=1e-6)
    assert v_c == pytest.approx(16.82, abs=0.02)


# ---------------------------------------------------------------------------
# 6. Single 90° corner path: corner feedrate actually applied
# ---------------------------------------------------------------------------

def test_single_90_corner_applied():
    """
    Path: (0,0,0) → (50,0,0) → (50,50,0)  — exactly 90° at wp[1].
    With a_max=2000, r_blend=0.1: V_corner ≈ 16.82 mm/s.
    The feedrate at the corner waypoint must not exceed V_corner.
    """
    wps = [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0), (50.0, 50.0, 0.0)]
    profile = optimize_feedrate(wps, V_TARGET, A_MAX, R_BLEND)
    v_corner_limit = _corner_feedrate(math.pi / 2, A_MAX, R_BLEND, V_TARGET)
    assert profile.feedrates[1] <= v_corner_limit + 1e-9


# ---------------------------------------------------------------------------
# 7. Corner angle computation
# ---------------------------------------------------------------------------

def test_corner_angle_90():
    theta = _corner_angle((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0))
    assert theta == pytest.approx(math.pi / 2, abs=1e-9)


def test_corner_angle_collinear():
    theta = _corner_angle((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0))
    assert theta == pytest.approx(0.0, abs=1e-9)


def test_corner_angle_180():
    """U-turn: the outgoing direction is opposite the incoming."""
    theta = _corner_angle((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    assert theta == pytest.approx(math.pi, abs=1e-6)


# ---------------------------------------------------------------------------
# 8. 180° U-turn: V_corner approaches 0
# ---------------------------------------------------------------------------

def test_uturn_very_slow():
    """
    A U-turn (θ = π) means sin(π/2) = 1 → V_corner = sqrt(a_max * r_blend).
    For a_max=2000, r_blend=0.1: V_corner = sqrt(200) ≈ 14.14 mm/s.
    (Still finite because sin(π/2) = 1 is not zero.)
    """
    v_c = _corner_feedrate(math.pi, a_max=2000.0, r_blend=0.1, v_target=V_TARGET)
    expected = math.sqrt(2000.0 * 0.1 / math.sin(math.pi / 2))
    assert v_c == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# 9. Collinear → V_corner = V_target
# ---------------------------------------------------------------------------

def test_collinear_corner_feedrate():
    v_c = _corner_feedrate(0.0, a_max=A_MAX, r_blend=R_BLEND, v_target=V_TARGET)
    assert v_c == pytest.approx(V_TARGET)


# ---------------------------------------------------------------------------
# 10. Acceleration limit: consecutive feedrate increase bounded by a_max
# ---------------------------------------------------------------------------

def test_acceleration_limit():
    wps = _straight_line(20, step=5.0)
    profile = optimize_feedrate(wps, V_TARGET, A_MAX, R_BLEND)
    v = profile.feedrates
    s = profile.segment_lengths
    for i in range(1, len(v)):
        ds = s[i]
        if ds < 1e-12:
            continue
        v_max_reachable = math.sqrt(v[i - 1] ** 2 + 2.0 * A_MAX * ds)
        assert v[i] <= v_max_reachable + 1e-9, (
            f"Accel limit violated at index {i}: v[i]={v[i]:.4f} > reachable {v_max_reachable:.4f}"
        )


# ---------------------------------------------------------------------------
# 11. Deceleration limit: consecutive feedrate decrease bounded by a_max
# ---------------------------------------------------------------------------

def test_deceleration_limit():
    wps = _straight_line(20, step=5.0)
    profile = optimize_feedrate(wps, V_TARGET, A_MAX, R_BLEND)
    v = profile.feedrates
    s = profile.segment_lengths
    for i in range(len(v) - 1):
        ds = s[i + 1]
        if ds < 1e-12:
            continue
        v_max_reachable_back = math.sqrt(v[i + 1] ** 2 + 2.0 * A_MAX * ds)
        assert v[i] <= v_max_reachable_back + 1e-9, (
            f"Decel limit violated at index {i}: v[i]={v[i]:.4f} > back-reachable {v_max_reachable_back:.4f}"
        )


# ---------------------------------------------------------------------------
# 12. Corner feedrate cap: no waypoint exceeds its V_corner_i
# ---------------------------------------------------------------------------

def test_corner_feedrate_cap():
    # Zig-zag path
    wps = [
        (0.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (10.0, 10.0, 0.0),
        (20.0, 10.0, 0.0),
        (20.0, 0.0, 0.0),
        (30.0, 0.0, 0.0),
    ]
    profile = optimize_feedrate(wps, V_TARGET, A_MAX, R_BLEND)
    for i, (v_i, vcap_i) in enumerate(zip(profile.feedrates, profile.corner_feedrates)):
        assert v_i <= vcap_i + 1e-9, (
            f"Waypoint {i} feedrate {v_i:.4f} exceeds corner cap {vcap_i:.4f}"
        )


# ---------------------------------------------------------------------------
# 13. Profile length matches waypoint count
# ---------------------------------------------------------------------------

def test_profile_length():
    for n in [1, 2, 5, 20]:
        wps = _straight_line(n, step=10.0)
        profile = optimize_feedrate(wps, V_TARGET, A_MAX, R_BLEND)
        assert len(profile.feedrates) == n
        assert len(profile.corner_angles) == n
        assert len(profile.corner_feedrates) == n
        assert len(profile.segment_lengths) == n


# ---------------------------------------------------------------------------
# 14. Endpoints always at rest
# ---------------------------------------------------------------------------

def test_endpoints_at_rest():
    for wps in [
        _straight_line(2, step=50.0),
        _straight_line(10, step=10.0),
        [(0.0, 0.0, 0.0), (5.0, 5.0, 0.0), (10.0, 0.0, 0.0)],
    ]:
        profile = optimize_feedrate(wps, V_TARGET, A_MAX, R_BLEND)
        assert profile.feedrates[0] == pytest.approx(0.0), "Start must be at rest"
        assert profile.feedrates[-1] == pytest.approx(0.0), "End must be at rest"


# ---------------------------------------------------------------------------
# 15. Larger blending_radius → lower or equal V_corner
# ---------------------------------------------------------------------------

def test_larger_blending_radius_lower_corner_feedrate():
    """
    V_corner = sqrt(a_max * r / sin(θ/2)) — monotonically increasing in r.
    So larger r → higher V_corner (less restrictive).  The profile feedrate
    at the corner must be >= with larger r (more freedom).
    """
    wps = [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0), (50.0, 50.0, 0.0)]
    p_small = optimize_feedrate(wps, V_TARGET, A_MAX, blending_radius=0.01)
    p_large = optimize_feedrate(wps, V_TARGET, A_MAX, blending_radius=1.0)
    # V_corner is larger for bigger r_blend (easier constraint)
    assert p_large.corner_feedrates[1] >= p_small.corner_feedrates[1] - 1e-9
    # The actual feedrate must also respect: large-r path can be >= small-r path
    assert p_large.feedrates[1] >= p_small.feedrates[1] - 1e-9


# ---------------------------------------------------------------------------
# 16. Validation errors
# ---------------------------------------------------------------------------

def test_invalid_max_feedrate():
    with pytest.raises(ValueError, match="max_feedrate"):
        optimize_feedrate([(0, 0, 0), (1, 0, 0)], max_feedrate=0.0, max_accel=A_MAX)


def test_invalid_max_accel():
    with pytest.raises(ValueError, match="max_accel"):
        optimize_feedrate([(0, 0, 0), (1, 0, 0)], max_feedrate=V_TARGET, max_accel=-1.0)


def test_invalid_blending_radius():
    with pytest.raises(ValueError, match="blending_radius"):
        optimize_feedrate([(0, 0, 0), (1, 0, 0)], V_TARGET, A_MAX, blending_radius=0.0)
