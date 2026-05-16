"""
Tests for kerf_cad_core.jewelry.stringing

Pure-Python section (always runs):
  - compute_stringing_layout: bead count accuracy, length constraint, style variants
  - knotted vs unknotted same count length comparison
  - princess preset ≈ 45 cm
  - cord_length_needed = finished_length + knot_takeup + tails
  - compute_graduated_schedule: monotone, symmetric, center/end values
  - compute_torsade_spec: multi-strand, clasp upgrade, twist factor > 1
  - _pick_clasp: heavy/multi upgrade rules
  - necklace_preset_mm: all presets defined and in-range
  - invalid inputs: graceful error dicts, never raise
  - LLM tool runners: success paths, required-field errors, preset resolution
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.jewelry.stringing import (
    NECKLACE_PRESETS,
    _SILK_SIZES,
    _WIRE_GAUGES,
    _TAIL_LENGTH_MM,
    _silk_for_hole,
    _wire_gauge_for_hole,
    _pick_clasp,
    _estimate_bead_weight_g,
    _knot_gap_effective,
    compute_stringing_layout,
    compute_graduated_schedule,
    compute_torsade_spec,
    necklace_preset_mm,
    jewelry_stringing_layout_spec,
    jewelry_stringing_graduated_spec,
    jewelry_stringing_torsade_spec,
    run_jewelry_stringing_layout,
    run_jewelry_stringing_graduated,
    run_jewelry_stringing_torsade,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    except ImportError:
        class ProjectCtx:  # type: ignore[no-redef]
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)
    return ProjectCtx(
        pool=None,
        storage=None,
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )


def run_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return json.loads(loop.run_until_complete(coro))
    finally:
        loop.close()


def call_layout(ctx, **kwargs):
    return run_sync(run_jewelry_stringing_layout(ctx, json.dumps(kwargs).encode()))


def call_graduated(ctx, **kwargs):
    return run_sync(run_jewelry_stringing_graduated(ctx, json.dumps(kwargs).encode()))


def call_torsade(ctx, **kwargs):
    return run_sync(run_jewelry_stringing_torsade(ctx, json.dumps(kwargs).encode()))


# ---------------------------------------------------------------------------
# 1. Bead count + length constraint
# ---------------------------------------------------------------------------

class TestBeadCountLengthConstraint:
    """count·(bead_d + gap) + clasp ≈ target ± 1 bead"""

    def _check_length(self, target_mm, bead_d, clasp_mm, style, tol_beads=1):
        r = compute_stringing_layout(
            target_mm, bead_d, clasp_length_mm=clasp_mm, style=style
        )
        assert "error" not in r, r.get("error")
        n = r["bead_count"]
        gap = r["knot_gap_mm"]
        slot = bead_d + gap
        # Actual length with n beads
        actual = n * slot + clasp_mm
        # Length with one fewer or one more bead
        lower = (n - tol_beads) * slot + clasp_mm
        upper = (n + tol_beads) * slot + clasp_mm
        assert lower <= target_mm <= upper, (
            f"target={target_mm}, actual={actual}, n={n}, slot={slot}"
        )

    def test_knotted_princess(self):
        self._check_length(450.0, 7.0, 10.0, "knotted")

    def test_unknotted_princess(self):
        self._check_length(450.0, 7.0, 10.0, "unknotted")

    def test_floating_princess(self):
        self._check_length(450.0, 7.0, 10.0, "floating")

    def test_knotted_opera(self):
        self._check_length(760.0, 8.0, 12.0, "knotted")

    def test_unknotted_choker(self):
        self._check_length(380.0, 5.0, 8.0, "unknotted")

    def test_small_bead_matinee(self):
        self._check_length(560.0, 4.0, 10.0, "knotted")

    def test_large_bead_rope(self):
        self._check_length(1070.0, 12.0, 15.0, "unknotted")


# ---------------------------------------------------------------------------
# 2. Knotted longer than unknotted for same bead count
# ---------------------------------------------------------------------------

class TestKnottedVsUnknotted:
    """Knotted layout has more total thread length than unknotted for same bead diameter."""

    def _knotted_unknotted_lengths(self, bead_d, target_mm):
        rk = compute_stringing_layout(target_mm, bead_d, style="knotted")
        ru = compute_stringing_layout(target_mm, bead_d, style="unknotted")
        return rk, ru

    def test_knotted_needs_more_cord(self):
        rk, ru = self._knotted_unknotted_lengths(7.0, 450.0)
        assert rk["cord_length_needed_mm"] > ru["cord_length_needed_mm"]

    def test_knotted_fewer_or_equal_beads(self):
        # Knots add length per slot, so same target → fewer or equal beads
        rk, ru = self._knotted_unknotted_lengths(7.0, 450.0)
        assert rk["bead_count"] <= ru["bead_count"]

    def test_knotted_has_knot_takeup(self):
        rk, _ = self._knotted_unknotted_lengths(7.0, 450.0)
        assert rk["knot_takeup_mm"] > 0

    def test_unknotted_zero_knot_takeup(self):
        _, ru = self._knotted_unknotted_lengths(7.0, 450.0)
        assert ru["knot_takeup_mm"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 3. Graduated schedule: monotone + symmetric
# ---------------------------------------------------------------------------

class TestGraduatedSchedule:
    def test_odd_bead_count_symmetric(self):
        r = compute_graduated_schedule(10.0, 6.0, bead_count=21)
        assert "error" not in r
        assert r["is_symmetric"] is True

    def test_even_bead_count_symmetric(self):
        r = compute_graduated_schedule(10.0, 6.0, bead_count=20)
        assert "error" not in r
        assert r["is_symmetric"] is True

    def test_monotone(self):
        r = compute_graduated_schedule(10.0, 6.0, bead_count=21)
        assert r["is_monotone"] is True

    def test_center_bead_is_largest(self):
        r = compute_graduated_schedule(10.0, 6.0, bead_count=21)
        sched = r["schedule"]
        mid = len(sched) // 2
        assert sched[mid] == pytest.approx(10.0, abs=0.01)

    def test_end_bead_is_smallest(self):
        r = compute_graduated_schedule(10.0, 6.0, bead_count=21)
        sched = r["schedule"]
        assert sched[0] == pytest.approx(6.0, abs=0.01)
        assert sched[-1] == pytest.approx(6.0, abs=0.01)

    def test_uniform_when_same_diameter(self):
        r = compute_graduated_schedule(8.0, 8.0, bead_count=15)
        assert "error" not in r
        assert all(abs(d - 8.0) < 0.01 for d in r["schedule"])

    def test_schedule_length_matches_bead_count(self):
        for n in [5, 10, 15, 21, 30]:
            r = compute_graduated_schedule(10.0, 6.0, bead_count=n)
            assert len(r["schedule"]) == n, f"n={n}"

    def test_center_gt_end_constraint_enforced(self):
        r = compute_graduated_schedule(5.0, 10.0, bead_count=21)
        assert "error" in r
        assert r["code"] == "BAD_ARGS"

    def test_zero_bead_count_error(self):
        r = compute_graduated_schedule(10.0, 6.0, bead_count=0)
        assert "error" in r

    def test_taper_steps_override(self):
        r = compute_graduated_schedule(10.0, 6.0, bead_count=21, taper_steps=3)
        assert "error" not in r
        assert r["is_symmetric"] is True

    def test_step_size_override(self):
        r = compute_graduated_schedule(10.0, 6.0, bead_count=21, step_size_mm=1.0)
        assert "error" not in r
        assert r["is_symmetric"] is True


# ---------------------------------------------------------------------------
# 4. Princess preset ≈ 45 cm
# ---------------------------------------------------------------------------

class TestNecklacePresets:
    def test_princess_preset_mm(self):
        mm = necklace_preset_mm("princess")
        assert mm is not None
        assert 430 <= mm <= 480, f"princess preset = {mm} mm"

    def test_all_presets_defined(self):
        for name in ("collar", "choker", "princess", "matinee", "opera", "rope"):
            mm = necklace_preset_mm(name)
            assert mm is not None and mm > 0, f"{name} preset missing"

    def test_preset_ordering(self):
        # Each successive preset should be longer
        names = ["collar", "choker", "princess", "matinee", "opera", "rope"]
        lengths = [necklace_preset_mm(n) for n in names]
        for i in range(len(lengths) - 1):
            assert lengths[i] < lengths[i + 1], (
                f"{names[i]} ({lengths[i]}) should be < {names[i+1]} ({lengths[i+1]})"
            )

    def test_unknown_preset_returns_none(self):
        assert necklace_preset_mm("choker_extra_long") is None

    def test_case_insensitive(self):
        assert necklace_preset_mm("PRINCESS") == necklace_preset_mm("princess")


# ---------------------------------------------------------------------------
# 5. Cord length = finished_length + knot_takeup + tails
# ---------------------------------------------------------------------------

class TestCordLength:
    def test_cord_includes_tails(self):
        r = compute_stringing_layout(450.0, 7.0, style="unknotted")
        assert r["cord_length_needed_mm"] >= r["target_length_mm"] + 2 * _TAIL_LENGTH_MM

    def test_knotted_cord_exceeds_unknotted_cord(self):
        rk = compute_stringing_layout(450.0, 7.0, style="knotted")
        ru = compute_stringing_layout(450.0, 7.0, style="unknotted")
        assert rk["cord_length_needed_mm"] > ru["cord_length_needed_mm"]

    def test_knotted_cord_accounts_for_takeup(self):
        r = compute_stringing_layout(450.0, 7.0, style="knotted")
        expected_min = r["target_length_mm"] + r["knot_takeup_mm"] + 2 * _TAIL_LENGTH_MM
        assert r["cord_length_needed_mm"] >= expected_min - 1.0


# ---------------------------------------------------------------------------
# 6. Clasp upgrade: heavy / multi-strand
# ---------------------------------------------------------------------------

class TestClaspPick:
    def test_light_single_gets_lobster(self):
        style = _pick_clasp(1, 5.0)
        assert style == "lobster"

    def test_medium_weight_single_gets_box(self):
        style = _pick_clasp(1, 40.0)
        assert style in ("box", "lobster")

    def test_heavy_single_gets_toggle_or_box(self):
        style = _pick_clasp(1, 100.0)
        assert style in ("toggle", "box")

    def test_multi_strand_upgrades_clasp(self):
        single = _pick_clasp(1, 30.0)
        multi = _pick_clasp(3, 30.0)
        # Multi-strand should use box or toggle
        assert multi in ("box", "toggle")

    def test_very_heavy_gets_toggle(self):
        style = _pick_clasp(1, 200.0)
        assert style in ("toggle", "magnetic")

    def test_compute_layout_clasp_upgrade_heavy(self):
        # Heavy beads (metal, lots of them) should get a heavier clasp
        r = compute_stringing_layout(1070.0, 12.0, style="unknotted", material="metal")
        assert r["clasp_style"] in ("box", "toggle", "magnetic")

    def test_compute_layout_multi_strand_clasp(self):
        r = compute_stringing_layout(450.0, 7.0, style="knotted", strand_count=3)
        assert r["clasp_style"] in ("box", "toggle")


# ---------------------------------------------------------------------------
# 7. Invalid / graceful error handling
# ---------------------------------------------------------------------------

class TestInvalidInputs:
    def test_zero_target_length(self):
        r = compute_stringing_layout(0.0, 7.0)
        assert "error" in r
        assert r["code"] == "BAD_ARGS"

    def test_negative_bead_diameter(self):
        r = compute_stringing_layout(450.0, -1.0)
        assert "error" in r

    def test_clasp_exceeds_target(self):
        r = compute_stringing_layout(50.0, 7.0, clasp_length_mm=100.0)
        assert "error" in r
        assert r["code"] == "BAD_ARGS"

    def test_unknown_style(self):
        r = compute_stringing_layout(450.0, 7.0, style="macrame")
        assert "error" in r

    def test_zero_hole_diameter(self):
        r = compute_stringing_layout(450.0, 7.0, hole_diameter_mm=0.0)
        assert "error" in r

    def test_zero_strand_count(self):
        r = compute_stringing_layout(450.0, 7.0, strand_count=0)
        assert "error" in r

    def test_graduated_center_lt_end_error(self):
        r = compute_graduated_schedule(4.0, 8.0, bead_count=21)
        assert "error" in r

    def test_torsade_single_strand_error(self):
        r = compute_torsade_spec(1, 450.0, 7.0)
        assert "error" in r

    def test_torsade_zero_target_error(self):
        r = compute_torsade_spec(3, 0.0, 7.0)
        assert "error" in r


# ---------------------------------------------------------------------------
# 8. Torsade (multi-strand twist)
# ---------------------------------------------------------------------------

class TestTorsade:
    def test_three_strand_basic(self):
        r = compute_torsade_spec(3, 450.0, 7.0)
        assert "error" not in r, r.get("error")
        assert r["strand_count"] == 3
        assert r["per_strand_bead_count"] > 0

    def test_twist_factor_gt_one(self):
        r = compute_torsade_spec(3, 450.0, 7.0)
        assert r["twist_factor"] > 1.0

    def test_per_strand_target_exceeds_finished(self):
        r = compute_torsade_spec(3, 450.0, 7.0)
        assert r["per_strand_target_mm"] >= 450.0

    def test_total_bead_count_is_strands_times_per_strand(self):
        r = compute_torsade_spec(4, 560.0, 6.0)
        assert r["total_bead_count"] == r["per_strand_bead_count"] * 4

    def test_multi_strand_clasp_not_lobster_for_three_strands(self):
        r = compute_torsade_spec(3, 450.0, 7.0)
        # Torsade code upgrades lobster → box for ≥ 3 strands
        assert r["clasp_style"] in ("box", "toggle")

    def test_custom_twist_period(self):
        r = compute_torsade_spec(3, 450.0, 7.0, twist_period_mm=50.0)
        assert "error" not in r
        assert r["twist_period_mm"] == pytest.approx(50.0)

    def test_unknotted_torsade(self):
        r = compute_torsade_spec(2, 450.0, 7.0, style="unknotted")
        assert "error" not in r
        assert r["style"] == "unknotted"


# ---------------------------------------------------------------------------
# 9. Thread / wire pick helpers
# ---------------------------------------------------------------------------

class TestThreadPick:
    def test_silk_size_fits_hole(self):
        size = _silk_for_hole(1.0)
        assert size in _SILK_SIZES
        # Thread passes doubled: 2 × thread_d ≤ hole_d
        assert 2 * _SILK_SIZES[size] <= 1.0

    def test_larger_hole_picks_larger_silk(self):
        small = _silk_for_hole(0.8)
        large = _silk_for_hole(2.0)
        assert _SILK_SIZES[large] >= _SILK_SIZES[small]

    def test_wire_gauge_fits_hole(self):
        gauge = _wire_gauge_for_hole(1.5)
        assert gauge in _WIRE_GAUGES

    def test_knotted_uses_silk(self):
        r = compute_stringing_layout(450.0, 7.0, style="knotted")
        assert r["thread"]["type"] == "silk"

    def test_unknotted_uses_wire(self):
        r = compute_stringing_layout(450.0, 7.0, style="unknotted")
        assert r["thread"]["type"] == "wire"

    def test_floating_uses_wire(self):
        r = compute_stringing_layout(450.0, 7.0, style="floating")
        assert r["thread"]["type"] == "wire"


# ---------------------------------------------------------------------------
# 10. LLM tool runners
# ---------------------------------------------------------------------------

class TestLLMToolRunners:
    @pytest.fixture
    def ctx(self):
        return make_ctx()

    def test_layout_with_preset_princess(self, ctx):
        r = call_layout(ctx, preset="princess", bead_diameter_mm=7.0)
        assert "error" not in r, r.get("error")
        assert 430 <= r["target_length_mm"] <= 480

    def test_layout_with_explicit_length(self, ctx):
        r = call_layout(ctx, target_length_mm=500.0, bead_diameter_mm=8.0)
        assert "error" not in r, r.get("error")
        assert r["bead_count"] > 0

    def test_layout_missing_bead_diameter(self, ctx):
        r = call_layout(ctx, target_length_mm=450.0)
        assert "error" in r

    def test_layout_missing_length_and_preset(self, ctx):
        r = call_layout(ctx, bead_diameter_mm=7.0)
        assert "error" in r

    def test_layout_bad_preset(self, ctx):
        r = call_layout(ctx, preset="ankle_bracelet", bead_diameter_mm=7.0)
        assert "error" in r

    def test_layout_all_styles(self, ctx):
        for style in ("knotted", "unknotted", "floating"):
            r = call_layout(ctx, target_length_mm=450.0, bead_diameter_mm=7.0, style=style)
            assert "error" not in r, f"style={style}: {r}"

    def test_graduated_tool_success(self, ctx):
        r = call_graduated(
            ctx,
            center_bead_diameter_mm=10.0,
            end_bead_diameter_mm=6.0,
            bead_count=21,
        )
        assert "error" not in r, r.get("error")
        assert r["is_symmetric"] is True

    def test_graduated_missing_fields(self, ctx):
        r = call_graduated(ctx, center_bead_diameter_mm=10.0, end_bead_diameter_mm=6.0)
        assert "error" in r

    def test_torsade_tool_success(self, ctx):
        r = call_torsade(ctx, strand_count=3, target_length_mm=450.0, bead_diameter_mm=7.0)
        assert "error" not in r, r.get("error")
        assert r["strand_count"] == 3

    def test_torsade_missing_fields(self, ctx):
        r = call_torsade(ctx, strand_count=3, target_length_mm=450.0)
        assert "error" in r

    def test_tool_specs_have_names(self):
        assert jewelry_stringing_layout_spec.name == "jewelry_stringing_layout"
        assert jewelry_stringing_graduated_spec.name == "jewelry_stringing_graduated"
        assert jewelry_stringing_torsade_spec.name == "jewelry_stringing_torsade"

    def test_layout_spec_required_fields(self):
        schema = jewelry_stringing_layout_spec.input_schema
        required = schema.get("required", [])
        assert "bead_diameter_mm" in required

    def test_torsade_spec_required_fields(self):
        schema = jewelry_stringing_torsade_spec.input_schema
        required = schema.get("required", [])
        assert "strand_count" in required
        assert "target_length_mm" in required
        assert "bead_diameter_mm" in required
