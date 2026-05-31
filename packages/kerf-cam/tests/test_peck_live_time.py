"""
Tests for kerf_cam.peck_live_time — G83 peck-drill cycle live-time analytics.

References
----------
* Machinery's Handbook 31e §1132 — Peck drilling guidelines
* Sandvik CoroPlus drill cycle analytics (2024) — live-time fraction benchmarks
* NIST RS-274/NGC §3.8.4 — G83 canned cycle motion model

Run:
    pytest packages/kerf-cam/tests/test_peck_live_time.py -v
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cam.peck_live_time import (
    PeckCycleParams,
    PeckLiveTimeReport,
    compute_peck_live_time,
    cam_compute_peck_live_time_spec,
    run_cam_compute_peck_live_time,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _params(**kw) -> PeckCycleParams:
    """Build PeckCycleParams with overrideable defaults."""
    defaults = dict(
        depth_mm=10.0,
        peck_depth_mm=2.0,
        retract_z_mm=1.0,
        feed_z_mm_per_min=200.0,
        rapid_z_mm_per_min=20_000.0,
        dwell_per_peck_ms=0.0,
    )
    defaults.update(kw)
    return PeckCycleParams(**defaults)


def _run(coro):
    return asyncio.run(coro)


def _ctx():
    from kerf_cam._compat import ProjectCtx
    return ProjectCtx()


# ---------------------------------------------------------------------------
# 1. PeckCycleParams validation
# ---------------------------------------------------------------------------

class TestPeckCycleParamsValidation:
    def test_valid_params_no_error(self):
        p = _params()
        assert p.depth_mm == 10.0

    def test_zero_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm"):
            _params(depth_mm=0.0)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm"):
            _params(depth_mm=-5.0)

    def test_zero_peck_raises(self):
        with pytest.raises(ValueError, match="peck_depth_mm"):
            _params(peck_depth_mm=0.0)

    def test_zero_feed_raises(self):
        with pytest.raises(ValueError, match="feed_z_mm_per_min"):
            _params(feed_z_mm_per_min=0.0)

    def test_zero_rapid_raises(self):
        with pytest.raises(ValueError, match="rapid_z_mm_per_min"):
            _params(rapid_z_mm_per_min=0.0)

    def test_negative_retract_raises(self):
        with pytest.raises(ValueError, match="retract_z_mm"):
            _params(retract_z_mm=-1.0)

    def test_negative_dwell_raises(self):
        with pytest.raises(ValueError, match="dwell_per_peck_ms"):
            _params(dwell_per_peck_ms=-10.0)

    def test_zero_dwell_accepted(self):
        p = _params(dwell_per_peck_ms=0.0)
        assert p.dwell_per_peck_ms == 0.0

    def test_zero_retract_accepted(self):
        """R-plane exactly at work surface is allowed."""
        p = _params(retract_z_mm=0.0)
        assert p.retract_z_mm == 0.0


# ---------------------------------------------------------------------------
# 2. Baseline: 10 mm depth, 2 mm peck, 1 mm retract, 200 mm/min feed
# ---------------------------------------------------------------------------

class TestBaseline10mmHole:
    """
    10 mm depth / 2 mm peck = 5 pecks.
    Feed 200 mm/min, rapid 20 000 mm/min, retract clearance 1 mm.

    Per-peck feed time:   2 mm / 200 mm·min⁻¹ × 60 s = 0.6 s
    Total cutting time:   5 × 0.6 = 3.0 s

    Rapid down per peck k (0-indexed):  (1 + k×2) mm / 20 000 mm·min⁻¹ × 60 s
      k=0: 1 mm → 0.003 s
      k=1: 3 mm → 0.009 s
      k=2: 5 mm → 0.015 s
      k=3: 7 mm → 0.021 s
      k=4: 9 mm → 0.027 s

    Rapid up per peck k:  (1 + (k+1)×2) mm / 20 000 × 60
      k=0: 3 mm → 0.009 s
      k=1: 5 mm → 0.015 s
      k=2: 7 mm → 0.021 s
      k=3: 9 mm → 0.027 s
      k=4: 11 mm → 0.033 s

    Total retract:  (0.003+0.009 + 0.009+0.015 + 0.015+0.021 + 0.021+0.027 + 0.027+0.033)
                  = 0.18 s
    Total:          3.0 + 0.18 = 3.18 s
    live_frac:      3.0 / 3.18 ≈ 0.9434
    """
    def setup_method(self):
        self.r = compute_peck_live_time(_params(
            depth_mm=10.0,
            peck_depth_mm=2.0,
            retract_z_mm=1.0,
            feed_z_mm_per_min=200.0,
            rapid_z_mm_per_min=20_000.0,
            dwell_per_peck_ms=0.0,
        ))

    def test_num_pecks_is_5(self):
        assert self.r.num_pecks == 5

    def test_cutting_time_is_3_seconds(self):
        assert abs(self.r.cutting_live_time_s - 3.0) < 1e-4

    def test_retract_time_is_0_18_seconds(self):
        assert abs(self.r.retract_time_s - 0.18) < 1e-4

    def test_total_time_is_3_18_seconds(self):
        assert abs(self.r.total_cycle_time_s - 3.18) < 1e-4

    def test_dwell_is_zero(self):
        assert self.r.dwell_time_s == 0.0

    def test_live_fraction_above_half(self):
        """Fast rapid → cutting dominates → live fraction > 0.5."""
        assert self.r.live_time_fraction > 0.5

    def test_live_fraction_approximately_correct(self):
        expected = 3.0 / 3.18
        assert abs(self.r.live_time_fraction - expected) < 1e-4

    def test_adequate_is_true(self):
        """live_frac >> 0.50 threshold → adequate = True."""
        assert self.r.adequate is True

    def test_cutting_time_less_than_total(self):
        assert self.r.cutting_live_time_s < self.r.total_cycle_time_s

    def test_live_greater_than_retract(self):
        """Fast rapid: cutting time should exceed retract time."""
        assert self.r.cutting_live_time_s > self.r.retract_time_s

    def test_times_sum_to_total(self):
        """cutting + retract + dwell should equal total."""
        computed_sum = (
            self.r.cutting_live_time_s
            + self.r.retract_time_s
            + self.r.dwell_time_s
        )
        assert abs(computed_sum - self.r.total_cycle_time_s) < 1e-5

    def test_live_fraction_in_unit_interval(self):
        assert 0.0 < self.r.live_time_fraction <= 1.0


# ---------------------------------------------------------------------------
# 3. Shallow pecks → many pecks, high retract overhead, low live fraction
# ---------------------------------------------------------------------------

class TestShallowPecks:
    """
    10 mm depth, 0.5 mm peck = 20 pecks.
    Each peck is tiny; retract distances grow linearly.
    Expect many pecks and low live fraction.
    """
    def setup_method(self):
        self.r = compute_peck_live_time(_params(
            depth_mm=10.0,
            peck_depth_mm=0.5,
            retract_z_mm=2.0,
            feed_z_mm_per_min=200.0,
            rapid_z_mm_per_min=5_000.0,   # slow rapid → retract overhead high
        ))

    def test_num_pecks_is_20(self):
        assert self.r.num_pecks == 20

    def test_live_fraction_below_baseline(self):
        """Many short pecks with slow rapid → live fraction < baseline (2 mm peck)."""
        baseline = compute_peck_live_time(_params(
            depth_mm=10.0,
            peck_depth_mm=2.0,
            retract_z_mm=2.0,
            feed_z_mm_per_min=200.0,
            rapid_z_mm_per_min=5_000.0,
        ))
        assert self.r.live_time_fraction < baseline.live_time_fraction

    def test_retract_time_significant(self):
        """Retract should be a meaningful portion of total cycle."""
        assert self.r.retract_time_s > 0.1 * self.r.total_cycle_time_s

    def test_adequate_flag_reflects_fraction(self):
        """Adequate flag must correctly reflect threshold comparison."""
        expected_adequate = self.r.live_time_fraction >= self.r.recommended_minimum_live_fraction
        assert self.r.adequate == expected_adequate


# ---------------------------------------------------------------------------
# 4. High rapid rate → higher live fraction
# ---------------------------------------------------------------------------

class TestHighRapidRate:
    """
    Increasing rapid rate should increase live fraction (less retract overhead).
    """
    def test_higher_rapid_increases_live_fraction(self):
        slow = compute_peck_live_time(_params(rapid_z_mm_per_min=1_000.0))
        fast = compute_peck_live_time(_params(rapid_z_mm_per_min=40_000.0))
        assert fast.live_time_fraction > slow.live_time_fraction

    def test_very_fast_rapid_live_fraction_approaches_1(self):
        """With extremely fast rapid, nearly all cycle time is cutting."""
        r = compute_peck_live_time(_params(
            rapid_z_mm_per_min=10_000_000.0,  # near-infinite rapid
        ))
        assert r.live_time_fraction > 0.99

    def test_very_slow_rapid_live_fraction_low(self):
        """With very slow rapid, retract overhead dwarfs cutting time."""
        r = compute_peck_live_time(_params(
            depth_mm=10.0,
            peck_depth_mm=1.0,
            retract_z_mm=5.0,
            feed_z_mm_per_min=100.0,
            rapid_z_mm_per_min=50.0,   # 50 mm/min rapid — absurdly slow
        ))
        assert r.live_time_fraction < 0.30


# ---------------------------------------------------------------------------
# 5. Dwell time accounting
# ---------------------------------------------------------------------------

class TestDwellAccounting:
    def test_dwell_adds_to_total(self):
        no_dwell = compute_peck_live_time(_params(dwell_per_peck_ms=0.0))
        with_dwell = compute_peck_live_time(_params(dwell_per_peck_ms=100.0))
        assert with_dwell.total_cycle_time_s > no_dwell.total_cycle_time_s

    def test_dwell_time_matches_per_peck_x_num_pecks(self):
        """dwell_time_s = dwell_per_peck_ms/1000 × num_pecks."""
        dwell_ms = 50.0
        r = compute_peck_live_time(_params(
            depth_mm=10.0,
            peck_depth_mm=2.0,
            dwell_per_peck_ms=dwell_ms,
        ))
        expected_dwell = (dwell_ms / 1000.0) * r.num_pecks
        assert abs(r.dwell_time_s - expected_dwell) < 1e-9

    def test_dwell_does_not_affect_cutting_time(self):
        """Dwell should not inflate the reported cutting live time."""
        no_dwell = compute_peck_live_time(_params(dwell_per_peck_ms=0.0))
        with_dwell = compute_peck_live_time(_params(dwell_per_peck_ms=500.0))
        assert abs(no_dwell.cutting_live_time_s - with_dwell.cutting_live_time_s) < 1e-9

    def test_dwell_reduces_live_fraction(self):
        """Adding dwell increases total time without increasing cutting time."""
        no_dwell = compute_peck_live_time(_params(dwell_per_peck_ms=0.0))
        with_dwell = compute_peck_live_time(_params(dwell_per_peck_ms=500.0))
        assert with_dwell.live_time_fraction < no_dwell.live_time_fraction


# ---------------------------------------------------------------------------
# 6. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_peck_depth_ge_hole_depth(self):
        """Peck depth >= hole depth → 1 peck, no retract between pecks."""
        r = compute_peck_live_time(_params(depth_mm=5.0, peck_depth_mm=10.0))
        assert r.num_pecks == 1

    def test_single_peck_all_time_is_cutting_plus_one_retract(self):
        """One peck: cutting + one rapid-down + one rapid-up, no intermediate retracts."""
        r = compute_peck_live_time(_params(
            depth_mm=2.0,
            peck_depth_mm=10.0,  # single peck
            retract_z_mm=1.0,
            feed_z_mm_per_min=200.0,
            rapid_z_mm_per_min=20_000.0,
        ))
        assert r.num_pecks == 1
        expected_cut = (2.0 / 200.0) * 60.0   # 0.6 s
        assert abs(r.cutting_live_time_s - expected_cut) < 1e-6

    def test_num_pecks_ceiling(self):
        """depth=10 peck=3 → ceil(10/3)=4 pecks."""
        r = compute_peck_live_time(_params(depth_mm=10.0, peck_depth_mm=3.0))
        assert r.num_pecks == 4

    def test_final_peck_is_partial(self):
        """With partial last peck, cutting time < num_pecks × full_peck_time."""
        # depth=10, peck=3 → 3+3+3+1 mm; last peck is 1 mm not 3 mm
        r = compute_peck_live_time(_params(
            depth_mm=10.0,
            peck_depth_mm=3.0,
            feed_z_mm_per_min=200.0,
        ))
        full_peck_time = (3.0 / 200.0) * 60.0 * 4  # if all pecks were 3 mm
        assert r.cutting_live_time_s < full_peck_time

    def test_times_sum_to_total_always(self):
        """Invariant: cutting + retract + dwell == total, for varied params."""
        test_cases = [
            dict(depth_mm=5.0, peck_depth_mm=1.0, retract_z_mm=2.0,
                 feed_z_mm_per_min=100.0, rapid_z_mm_per_min=10_000.0),
            dict(depth_mm=20.0, peck_depth_mm=5.0, retract_z_mm=0.5,
                 feed_z_mm_per_min=500.0, rapid_z_mm_per_min=30_000.0),
            dict(depth_mm=3.0, peck_depth_mm=3.0, retract_z_mm=1.0,
                 feed_z_mm_per_min=150.0, rapid_z_mm_per_min=15_000.0,
                 dwell_per_peck_ms=200.0),
        ]
        for kw in test_cases:
            r = compute_peck_live_time(_params(**kw))
            s = r.cutting_live_time_s + r.retract_time_s + r.dwell_time_s
            assert abs(s - r.total_cycle_time_s) < 1e-5, (
                f"sum={s:.6f} != total={r.total_cycle_time_s:.6f} for {kw}"
            )


# ---------------------------------------------------------------------------
# 7. Adequate flag and recommended threshold
# ---------------------------------------------------------------------------

class TestAdequateFlag:
    def test_adequate_true_when_fraction_at_or_above_threshold(self):
        r = compute_peck_live_time(_params(
            rapid_z_mm_per_min=50_000.0  # very fast rapid → high live fraction
        ))
        assert r.live_time_fraction >= r.recommended_minimum_live_fraction
        assert r.adequate is True

    def test_adequate_false_when_fraction_below_threshold(self):
        r = compute_peck_live_time(_params(
            depth_mm=10.0,
            peck_depth_mm=0.5,
            retract_z_mm=5.0,
            feed_z_mm_per_min=50.0,
            rapid_z_mm_per_min=50.0,  # very slow rapid
        ))
        if r.live_time_fraction < r.recommended_minimum_live_fraction:
            assert r.adequate is False
        # If somehow fraction is above threshold, just check coherence
        assert r.adequate == (
            r.live_time_fraction >= r.recommended_minimum_live_fraction
        )

    def test_recommended_threshold_is_0_5(self):
        r = compute_peck_live_time(_params())
        assert r.recommended_minimum_live_fraction == 0.50

    def test_honest_caveat_mentions_acceleration(self):
        r = compute_peck_live_time(_params())
        caveat_lower = r.honest_caveat.lower()
        assert "acceleration" in caveat_lower or "ramp" in caveat_lower

    def test_honest_caveat_mentions_rapid(self):
        r = compute_peck_live_time(_params())
        assert "rapid" in r.honest_caveat.lower()


# ---------------------------------------------------------------------------
# 8. LLM tool (async, no DB)
# ---------------------------------------------------------------------------

class TestLLMTool:
    def test_tool_spec_name(self):
        assert cam_compute_peck_live_time_spec.name == "cam_compute_peck_live_time"

    def test_tool_spec_has_description(self):
        assert len(cam_compute_peck_live_time_spec.description) > 20

    def test_tool_basic_call(self):
        ctx = _ctx()
        args = json.dumps({
            "depth_mm": 10.0,
            "peck_depth_mm": 2.0,
            "retract_z_mm": 1.0,
            "feed_z_mm_per_min": 200.0,
        }).encode()
        raw = _run(run_cam_compute_peck_live_time(ctx, args))
        result = json.loads(raw)
        assert "num_pecks" in result
        assert result["num_pecks"] == 5
        assert "cutting_live_time_s" in result
        assert "live_time_fraction" in result
        assert "adequate" in result
        assert "honest_caveat" in result

    def test_tool_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run(run_cam_compute_peck_live_time(ctx, b"not-json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_missing_required_field_returns_error(self):
        ctx = _ctx()
        args = json.dumps({
            "depth_mm": 10.0,
            "peck_depth_mm": 2.0,
            # missing retract_z_mm and feed_z_mm_per_min
        }).encode()
        raw = _run(run_cam_compute_peck_live_time(ctx, args))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_invalid_depth_returns_error(self):
        ctx = _ctx()
        args = json.dumps({
            "depth_mm": -5.0,
            "peck_depth_mm": 2.0,
            "retract_z_mm": 1.0,
            "feed_z_mm_per_min": 200.0,
        }).encode()
        raw = _run(run_cam_compute_peck_live_time(ctx, args))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_returns_adequate_field(self):
        ctx = _ctx()
        args = json.dumps({
            "depth_mm": 10.0,
            "peck_depth_mm": 2.0,
            "retract_z_mm": 1.0,
            "feed_z_mm_per_min": 200.0,
            "rapid_z_mm_per_min": 20_000.0,
        }).encode()
        raw = _run(run_cam_compute_peck_live_time(ctx, args))
        result = json.loads(raw)
        assert isinstance(result["adequate"], bool)

    def test_tool_with_dwell(self):
        ctx = _ctx()
        args = json.dumps({
            "depth_mm": 10.0,
            "peck_depth_mm": 2.0,
            "retract_z_mm": 1.0,
            "feed_z_mm_per_min": 200.0,
            "dwell_per_peck_ms": 100.0,
        }).encode()
        raw = _run(run_cam_compute_peck_live_time(ctx, args))
        result = json.loads(raw)
        assert result["dwell_time_s"] > 0.0

    def test_tool_recommended_threshold_in_response(self):
        ctx = _ctx()
        args = json.dumps({
            "depth_mm": 5.0,
            "peck_depth_mm": 1.0,
            "retract_z_mm": 2.0,
            "feed_z_mm_per_min": 150.0,
        }).encode()
        raw = _run(run_cam_compute_peck_live_time(ctx, args))
        result = json.loads(raw)
        assert "recommended_minimum_live_fraction" in result
        assert result["recommended_minimum_live_fraction"] == 0.50
