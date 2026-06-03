"""Tests for kerf_cad_core.animation.keyframe — FCurve / AnimClip system.

Covers ≥9 assertions across linear, step, bezier interpolation, cyclic
wrapping, array-valued keyframes, and AnimClip evaluation.
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.animation.keyframe import Keyframe, FCurve, AnimClip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_linear_fcurve(points: list[tuple[float, float]]) -> FCurve:
    """Create a linear FCurve from (t, value) pairs."""
    keys = [Keyframe(t=t, value=v, interpolation="linear") for t, v in points]
    return FCurve(keyframes=keys)


def make_step_fcurve(points: list[tuple[float, float]]) -> FCurve:
    keys = [Keyframe(t=t, value=v, interpolation="step") for t, v in points]
    return FCurve(keyframes=keys)


# ---------------------------------------------------------------------------
# Test: linear interpolation
# ---------------------------------------------------------------------------

def test_linear_midpoint():
    """Linear interp between (0,0) and (1,10) at t=0.5 → 5.0."""
    fc = make_linear_fcurve([(0.0, 0.0), (1.0, 10.0)])
    assert abs(fc.evaluate(0.5) - 5.0) < 1e-9


def test_linear_quarter():
    """Linear interp at t=0.25 → 2.5."""
    fc = make_linear_fcurve([(0.0, 0.0), (1.0, 10.0)])
    assert abs(fc.evaluate(0.25) - 2.5) < 1e-9


def test_linear_clamp_before():
    """Evaluation before first key returns first value."""
    fc = make_linear_fcurve([(1.0, 5.0), (2.0, 10.0)])
    assert abs(fc.evaluate(0.0) - 5.0) < 1e-9


def test_linear_clamp_after():
    """Evaluation after last key returns last value."""
    fc = make_linear_fcurve([(0.0, 0.0), (1.0, 10.0)])
    assert abs(fc.evaluate(2.0) - 10.0) < 1e-9


def test_linear_exact_key():
    """Evaluation at exact key time returns exact value."""
    fc = make_linear_fcurve([(0.0, 3.0), (1.0, 7.0)])
    assert abs(fc.evaluate(0.0) - 3.0) < 1e-9
    assert abs(fc.evaluate(1.0) - 7.0) < 1e-9


def test_linear_multi_segment():
    """Multi-segment linear curve selects correct segment."""
    fc = make_linear_fcurve([(0.0, 0.0), (1.0, 10.0), (2.0, 5.0)])
    # Second segment descends from 10→5; at t=1.5 → 7.5
    assert abs(fc.evaluate(1.5) - 7.5) < 1e-9


# ---------------------------------------------------------------------------
# Test: step interpolation
# ---------------------------------------------------------------------------

def test_step_holds_value():
    """Step interp returns the previous keyframe value (no interpolation)."""
    fc = make_step_fcurve([(0.0, 1.0), (1.0, 5.0), (2.0, 9.0)])
    # At t=0.99 we are still in segment [0→1], so value = key0.value = 1.0
    assert abs(fc.evaluate(0.99) - 1.0) < 1e-9


def test_step_at_boundary():
    """Step interp at the start of the second key returns first segment value."""
    fc = make_step_fcurve([(0.0, 0.0), (1.0, 100.0)])
    # t = 0.9999 still in first segment
    assert abs(fc.evaluate(0.9999) - 0.0) < 1e-9


def test_step_second_segment():
    """Step interp past key1 returns key1 value."""
    fc = make_step_fcurve([(0.0, 0.0), (1.0, 100.0), (2.0, 200.0)])
    # t=1.5 is in segment [1→2] → value = key1.value = 100.0
    assert abs(fc.evaluate(1.5) - 100.0) < 1e-9


# ---------------------------------------------------------------------------
# Test: bezier interpolation
# ---------------------------------------------------------------------------

def test_bezier_linear_tangents_midpoint():
    """Bezier with flat tangents approaches linear interp at midpoint."""
    # Zero tangents → cubic Bezier degenerates toward linear
    k0 = Keyframe(t=0.0, value=0.0, interpolation="bezier",
                  tangent_out=(0.333, 0.0), tangent_in=None)
    k1 = Keyframe(t=1.0, value=10.0, interpolation="bezier",
                  tangent_in=(-0.333, 0.0), tangent_out=None)
    fc = FCurve(keyframes=[k0, k1])
    # With symmetric zero-slope tangents the curve is symmetric; midpoint ≈ 5
    val = fc.evaluate(0.5)
    assert abs(val - 5.0) < 0.5  # bezier with these tangents is close to linear


def test_bezier_known_control_points():
    """Bezier interp matches known cubic bezier for simple case.

    Control points: P0=(0,0), P1=(0.33,0), P2=(0.67,10), P3=(1,10)
    At t=0.5, the x-parameter u≈0.5 → B_y(0.5) ≈ 5 (symmetric curve).
    """
    k0 = Keyframe(t=0.0, value=0.0, interpolation="bezier",
                  tangent_out=(0.33, 0.0))
    k1 = Keyframe(t=1.0, value=10.0, interpolation="bezier",
                  tangent_in=(-0.33, 0.0))
    fc = FCurve(keyframes=[k0, k1])
    val = fc.evaluate(0.5)
    # Symmetric bezier → passes through midpoint
    assert abs(val - 5.0) < 0.5


def test_bezier_overshoot_with_steep_tangents():
    """Steep positive tangent out from k0 lifts the curve above a straight line.

    Control points:
        P0=(0,0), tangent_out=(0.3, 6)  → handle P1=(0.3, 6)
        P3=(1,5), tangent_in=(-0.3, 0)  → handle P2=(0.7, 5)
    The steep upward departure from k0 causes the curve to overshoot above 5
    before t1.  At t=0.3 the bezier value should be well above linear(0.3)=1.5.
    """
    k0 = Keyframe(t=0.0, value=0.0, interpolation="bezier",
                  tangent_out=(0.3, 6.0))
    k1 = Keyframe(t=1.0, value=5.0, interpolation="bezier",
                  tangent_in=(-0.3, 0.0))
    fc = FCurve(keyframes=[k0, k1])
    val = fc.evaluate(0.3)
    # Linear value at 0.3 would be 1.5; the steep tangent should push well above
    assert val > 2.5, f"Expected bezier to overshoot linear at t=0.3; got {val:.3f}"


# ---------------------------------------------------------------------------
# Test: cyclic FCurve
# ---------------------------------------------------------------------------

def test_cyclic_wrap():
    """Cyclic FCurve wraps t past duration back to start."""
    fc = make_linear_fcurve([(0.0, 0.0), (1.0, 10.0)])
    fc.cyclic = True
    # t=1.5 should wrap to t=0.5 → value ≈ 5.0
    val = fc.evaluate(1.5)
    assert abs(val - 5.0) < 1e-6


def test_cyclic_exact_period():
    """Cyclic at exactly t = period wraps to t_start → returns first key value.

    With cyclic wrapping, fmod(t - t_start, span) at t == t_end gives 0.0,
    so t wraps back to t_start and the first key value is returned.
    """
    fc = make_linear_fcurve([(0.0, 3.0), (2.0, 7.0)])
    fc.cyclic = True
    # t=2.0 → fmod(2-0, 2) = 0.0 → wraps to t=0.0 → value = 3.0
    val = fc.evaluate(2.0)
    assert abs(val - 3.0) < 1e-9


def test_cyclic_multiple_periods():
    """Cyclic FCurve handles t >> duration."""
    fc = make_linear_fcurve([(0.0, 0.0), (1.0, 10.0)])
    fc.cyclic = True
    # t=3.25 → wraps to t=0.25 → value ≈ 2.5
    val = fc.evaluate(3.25)
    assert abs(val - 2.5) < 1e-5


# ---------------------------------------------------------------------------
# Test: array-valued keyframes
# ---------------------------------------------------------------------------

def test_linear_array_value():
    """Linear interp works for vector-valued keyframes."""
    k0 = Keyframe(t=0.0, value=np.array([0.0, 0.0, 0.0]), interpolation="linear")
    k1 = Keyframe(t=1.0, value=np.array([10.0, 20.0, 30.0]), interpolation="linear")
    fc = FCurve(keyframes=[k0, k1])
    val = fc.evaluate(0.5)
    expected = np.array([5.0, 10.0, 15.0])
    assert np.allclose(val, expected, atol=1e-9)


def test_single_key_returns_value():
    """Single-keyframe FCurve always returns that value."""
    fc = FCurve(keyframes=[Keyframe(t=0.5, value=42.0)])
    assert fc.evaluate(0.0) == 42.0
    assert fc.evaluate(1.0) == 42.0


# ---------------------------------------------------------------------------
# Test: AnimClip
# ---------------------------------------------------------------------------

def test_animclip_evaluate_all_channels():
    """AnimClip.evaluate returns dict for all channels."""
    fc1 = make_linear_fcurve([(0.0, 0.0), (1.0, 10.0)])
    fc2 = make_linear_fcurve([(0.0, 5.0), (1.0, 15.0)])
    clip = AnimClip(name="test", duration=1.0, fcurves={"rx": fc1, "ry": fc2})
    result = clip.evaluate(0.5)
    assert set(result.keys()) == {"rx", "ry"}
    assert abs(result["rx"] - 5.0) < 1e-9
    assert abs(result["ry"] - 10.0) < 1e-9


def test_animclip_empty_channels():
    """AnimClip with no channels returns empty dict."""
    clip = AnimClip(name="empty", duration=1.0, fcurves={})
    assert clip.evaluate(0.5) == {}


def test_animclip_single_channel():
    """AnimClip with one channel returns that channel."""
    fc = make_linear_fcurve([(0.0, 100.0), (2.0, 200.0)])
    clip = AnimClip(name="pos", duration=2.0, fcurves={"tx": fc})
    result = clip.evaluate(1.0)
    assert abs(result["tx"] - 150.0) < 1e-9
