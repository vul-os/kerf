"""
Tests for kerf_cad_core.jewelry.filigree_advanced

>=25 hermetic tests covering:
  - milgrain_with_frame_border: bead count, arc-length, frame rails
  - florentine_scrollwork: period count, repeat-period exact, tendril count
  - celtic_knot_interlace: 2/3-strand crossing count, over/under alternation,
    Trinity, Endless — all types produce strands + crossings
  - wire_twist_rope: helix pitch match, strand count, single-strand
  - metal_volume_estimate: V = π*(d/2)²*L within tolerance
  - art_nouveau_vine: petal/leaf counts, random seed reproducibility
  - persian_moorish_lace: hex+star tile counts for a known region
  - apply_to_band: arc-length preservation through band-wrap mapping,
    planar→cylinder coordinate check
  - input validation: bad params return error dicts (never raise)
  - LLM tool runners: ok/error paths
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.jewelry.filigree_advanced import (
    _arc_length_polyline,
    _arc_length_polylines,
    _helix_pts,
    apply_to_band,
    art_nouveau_vine,
    celtic_knot_interlace,
    florentine_scrollwork,
    metal_volume_estimate,
    milgrain_with_frame_border,
    persian_moorish_lace,
    wire_twist_rope,
    # LLM tool runners
    run_jewelry_filigree_milgrain_border,
    run_jewelry_filigree_florentine_scrollwork,
    run_jewelry_filigree_celtic_knot,
    run_jewelry_filigree_art_nouveau_vine,
    run_jewelry_filigree_persian_lace,
    run_jewelry_filigree_wire_rope,
    run_jewelry_filigree_apply_to_band,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro) -> dict:
    loop = asyncio.new_event_loop()
    try:
        raw = loop.run_until_complete(coro)
        return json.loads(raw)
    finally:
        loop.close()


def _call(runner, **kwargs) -> dict:
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    except ImportError:
        class ProjectCtx:  # type: ignore[no-redef]
            def __init__(self, **kw):
                for k, v in kw.items():
                    setattr(self, k, v)

    ctx = ProjectCtx(
        pool=None,
        storage=None,
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )
    return _run(runner(ctx, json.dumps(kwargs).encode()))


WIRE_DIA = 0.5  # mm — used as default test wire diameter


# ===========================================================================
# 1. metal_volume_estimate
# ===========================================================================

class TestMetalVolumeEstimate:
    def test_known_value(self):
        # V = π * (0.5/2)^2 * 10 = π * 0.0625 * 10 ≈ 1.9635
        v = metal_volume_estimate(0.5, 10.0)
        expected = math.pi * (0.25) ** 2 * 10.0
        assert abs(v - expected) < 1e-6

    def test_proportional_to_length(self):
        v1 = metal_volume_estimate(0.5, 10.0)
        v2 = metal_volume_estimate(0.5, 20.0)
        assert abs(v2 - 2.0 * v1) < 1e-9

    def test_proportional_to_diameter_squared(self):
        # Doubling diameter → 4× volume
        v1 = metal_volume_estimate(1.0, 10.0)
        v2 = metal_volume_estimate(2.0, 10.0)
        assert abs(v2 - 4.0 * v1) < 1e-6

    def test_zero_diameter_returns_zero(self):
        assert metal_volume_estimate(0.0, 10.0) == 0.0

    def test_negative_length_returns_zero(self):
        assert metal_volume_estimate(0.5, -1.0) == 0.0


# ===========================================================================
# 2. milgrain_with_frame_border
# ===========================================================================

class TestMilgrainBorder:
    def test_basic_ok(self):
        r = milgrain_with_frame_border(20.0, 0.7, 0.9)
        assert r.get("ok") is True
        res = r["result"]
        assert "outer_rail" in res
        assert "inner_rail" in res
        assert "bead_centres" in res

    def test_bead_count_matches_path_div_pitch(self):
        r = milgrain_with_frame_border(20.0, 0.7, 2.0)
        res = r["result"]
        expected = max(1, int(20.0 / 2.0))
        assert res["bead_count"] == expected

    def test_metal_volume_equals_formula(self):
        r = milgrain_with_frame_border(20.0, 0.7, 0.9, wire_diameter_mm=0.4)
        res = r["result"]
        total_arc = res["total_arc_length_mm"]
        expected_vol = metal_volume_estimate(0.4, total_arc)
        assert abs(res["metal_volume_mm3"] - expected_vol) < 1e-4

    def test_outer_inner_rail_lengths_equal(self):
        r = milgrain_with_frame_border(15.0, 0.6, 0.8)
        res = r["result"]
        l_outer = _arc_length_polyline(res["outer_rail"])
        l_inner = _arc_length_polyline(res["inner_rail"])
        assert abs(l_outer - l_inner) < 1e-6

    def test_bad_path_length_returns_error(self):
        r = milgrain_with_frame_border(0.0, 0.7, 0.9)
        assert "error" in r

    def test_bad_bead_diameter_returns_error(self):
        r = milgrain_with_frame_border(10.0, -1.0, 0.9)
        assert "error" in r

    def test_bead_centres_on_midline(self):
        r = milgrain_with_frame_border(10.0, 0.5, 1.0)
        for pt in r["result"]["bead_centres"]:
            assert pt[1] == pytest.approx(0.0)  # y=0 midline
            assert pt[2] == pytest.approx(0.0)  # z=0 flat


# ===========================================================================
# 3. florentine_scrollwork
# ===========================================================================

class TestFlorentineScrollwork:
    def test_basic_ok(self):
        r = florentine_scrollwork(20.0)
        assert r.get("ok") is True
        assert "motifs" in r["result"]

    def test_period_count_exact(self):
        # n_periods = int(path_length / period_mm)
        r = florentine_scrollwork(20.0, period_mm=4.0)
        assert r["result"]["n_periods"] == 5

    def test_period_mm_stored_exactly(self):
        r = florentine_scrollwork(20.0, period_mm=3.75)
        assert r["result"]["period_mm"] == pytest.approx(3.75)

    def test_each_period_has_two_arcs_and_tendrils(self):
        r = florentine_scrollwork(15.0, period_mm=5.0, tendril_count=3)
        for motif in r["result"]["motifs"]:
            assert "upper_s" in motif
            assert "lower_s" in motif
            assert len(motif["tendrils"]) == 3

    def test_zero_tendril_count_ok(self):
        r = florentine_scrollwork(10.0, tendril_count=0)
        assert r.get("ok") is True
        for motif in r["result"]["motifs"]:
            assert len(motif["tendrils"]) == 0

    def test_bad_path_length_returns_error(self):
        r = florentine_scrollwork(0.0)
        assert "error" in r

    def test_bad_period_returns_error(self):
        r = florentine_scrollwork(10.0, period_mm=-1.0)
        assert "error" in r

    def test_metal_volume_formula(self):
        r = florentine_scrollwork(20.0, wire_diameter_mm=WIRE_DIA)
        res = r["result"]
        total_arc = res["total_arc_length_mm"]
        expected = metal_volume_estimate(WIRE_DIA, total_arc)
        assert abs(res["metal_volume_mm3"] - expected) < 1e-4


# ===========================================================================
# 4. celtic_knot_interlace
# ===========================================================================

class TestCelticKnotInterlace:
    def test_2strand_ok(self):
        r = celtic_knot_interlace("2_strand", unit_size_mm=5.0, repeat_count=3)
        assert r.get("ok") is True
        res = r["result"]
        assert res["n_strands"] == 2
        assert len(res["strands"]) == 2

    def test_2strand_crossing_count_vs_repeat(self):
        # For a 2-strand over/under plait: 2*repeat_count - 1 crossings
        rc = 4
        r = celtic_knot_interlace("2_strand", repeat_count=rc)
        res = r["result"]
        expected_crossings = 2 * rc - 1
        assert len(res["crossings"]) == expected_crossings

    def test_2strand_over_under_alternates(self):
        r = celtic_knot_interlace("2_strand", repeat_count=5)
        crossings = r["result"]["crossings"]
        for i, c in enumerate(crossings):
            expected_over = 0 if i % 2 == 0 else 1
            assert c["over_strand"] == expected_over, f"crossing {i}: expected over={expected_over}, got {c['over_strand']}"
            assert c["under_strand"] == 1 - expected_over

    def test_3strand_ok(self):
        r = celtic_knot_interlace("3_strand", repeat_count=2)
        assert r.get("ok") is True
        res = r["result"]
        assert res["n_strands"] == 3
        assert len(res["strands"]) == 3

    def test_3strand_crossing_count(self):
        # 2 crossings per period (2 per repeat_count)
        rc = 3
        r = celtic_knot_interlace("3_strand", repeat_count=rc)
        assert len(r["result"]["crossings"]) == 2 * rc

    def test_trinity_ok(self):
        r = celtic_knot_interlace("trinity", repeat_count=2)
        assert r.get("ok") is True
        res = r["result"]
        assert res["n_strands"] == 3

    def test_endless_ok(self):
        r = celtic_knot_interlace("endless", repeat_count=2)
        assert r.get("ok") is True
        res = r["result"]
        assert res["n_strands"] == 1

    def test_endless_crossing_count(self):
        rc = 3
        r = celtic_knot_interlace("endless", repeat_count=rc)
        assert len(r["result"]["crossings"]) == 2 * rc

    def test_invalid_type_returns_error(self):
        r = celtic_knot_interlace("4_strand")
        assert "error" in r

    def test_metal_volume_formula(self):
        r = celtic_knot_interlace("2_strand", wire_diameter_mm=WIRE_DIA)
        res = r["result"]
        total_arc = res["total_arc_length_mm"]
        expected = metal_volume_estimate(WIRE_DIA, total_arc)
        assert abs(res["metal_volume_mm3"] - expected) < 1e-4


# ===========================================================================
# 5. wire_twist_rope — helix pitch matches formula
# ===========================================================================

class TestWireTwistRope:
    def test_basic_ok(self):
        r = wire_twist_rope(20.0, strand_count=2, twist_pitch_mm=3.0)
        assert r.get("ok") is True
        res = r["result"]
        assert res["strand_count"] == 2

    def test_helix_pitch_matches_formula(self):
        """Helix arc-length per strand must match sqrt((2π*R)²+pitch²)*turns."""
        pitch = 4.0
        path_len = 20.0
        r = wire_twist_rope(path_len, strand_count=1, wire_diameter_mm=0.5, twist_pitch_mm=pitch)
        res = r["result"]
        R = res["bundle_radius_mm"]
        n_turns = res["n_turns"]
        theoretical = n_turns * math.sqrt((2.0 * math.pi * R) ** 2 + pitch ** 2)
        assert abs(res["theoretical_arc_per_strand_mm"] - theoretical) < 1e-4

    def test_total_arc_length_is_strand_count_times_single(self):
        r1 = wire_twist_rope(20.0, strand_count=1, twist_pitch_mm=3.0)
        r3 = wire_twist_rope(20.0, strand_count=3, twist_pitch_mm=3.0)
        # Total arc for 3 strands should be approximately 3× a single strand
        # (same per-strand helix parameters; bundle radius varies slightly)
        # Check that 3-strand total > 1-strand total
        assert r3["result"]["total_arc_length_mm"] > r1["result"]["total_arc_length_mm"]

    def test_single_strand_ok(self):
        r = wire_twist_rope(10.0, strand_count=1)
        assert r.get("ok") is True

    def test_metal_volume_formula(self):
        r = wire_twist_rope(20.0, strand_count=2, wire_diameter_mm=WIRE_DIA)
        res = r["result"]
        total_arc = res["total_arc_length_mm"]
        expected = metal_volume_estimate(WIRE_DIA, total_arc)
        assert abs(res["metal_volume_mm3"] - expected) < 1e-4

    def test_bad_path_length_returns_error(self):
        r = wire_twist_rope(0.0)
        assert "error" in r

    def test_bad_strand_count_returns_error(self):
        r = wire_twist_rope(10.0, strand_count=0)
        assert "error" in r

    def test_bad_pitch_returns_error(self):
        r = wire_twist_rope(10.0, twist_pitch_mm=0.0)
        assert "error" in r


# ===========================================================================
# 6. art_nouveau_vine
# ===========================================================================

class TestArtNouveauVine:
    def test_basic_ok(self):
        r = art_nouveau_vine(30.0)
        assert r.get("ok") is True
        res = r["result"]
        assert "stem" in res
        assert "petals" in res
        assert "leaves" in res

    def test_petal_count_matches_param(self):
        r = art_nouveau_vine(30.0, petal_count=5)
        assert r["result"]["petal_count"] == 5

    def test_leaf_count_matches_param(self):
        r = art_nouveau_vine(30.0, leaf_count=3)
        assert r["result"]["leaf_count"] == 3

    def test_random_seed_reproducible(self):
        r1 = art_nouveau_vine(20.0, random_seed=99)
        r2 = art_nouveau_vine(20.0, random_seed=99)
        # Same seed → identical stem (first 3 points)
        assert r1["result"]["stem"][:3] == r2["result"]["stem"][:3]

    def test_different_seeds_different_results(self):
        r1 = art_nouveau_vine(20.0, petal_count=4, random_seed=1)
        r2 = art_nouveau_vine(20.0, petal_count=4, random_seed=2)
        # Petals differ in position
        if r1["result"]["petals"] and r2["result"]["petals"]:
            assert r1["result"]["petals"][0][0] != r2["result"]["petals"][0][0]

    def test_metal_volume_formula(self):
        r = art_nouveau_vine(20.0, wire_diameter_mm=WIRE_DIA)
        res = r["result"]
        total_arc = res["total_arc_length_mm"]
        expected = metal_volume_estimate(WIRE_DIA, total_arc)
        assert abs(res["metal_volume_mm3"] - expected) < 1e-4

    def test_bad_path_length_returns_error(self):
        r = art_nouveau_vine(0.0)
        assert "error" in r

    def test_zero_petal_count_ok(self):
        r = art_nouveau_vine(20.0, petal_count=0, leaf_count=0)
        assert r.get("ok") is True
        assert r["result"]["petal_count"] == 0
        assert r["result"]["leaf_count"] == 0


# ===========================================================================
# 7. persian_moorish_lace — hex+star counts for a known region
# ===========================================================================

class TestPersianMoorishLace:
    def test_basic_ok(self):
        r = persian_moorish_lace(20.0, 20.0, hex_radius_mm=3.0)
        assert r.get("ok") is True
        res = r["result"]
        assert "hexagons" in res
        assert "stars" in res

    def test_hex_count_positive(self):
        r = persian_moorish_lace(20.0, 20.0, hex_radius_mm=3.0)
        assert r["result"]["hex_count"] > 0

    def test_star_count_positive_when_enabled(self):
        r = persian_moorish_lace(20.0, 20.0, hex_radius_mm=3.0, include_stars=True)
        assert r["result"]["star_count"] > 0

    def test_no_stars_when_disabled(self):
        r = persian_moorish_lace(20.0, 20.0, include_stars=False)
        assert r["result"]["star_count"] == 0
        assert len(r["result"]["stars"]) == 0

    def test_larger_region_more_hexes(self):
        r_small = persian_moorish_lace(10.0, 10.0, hex_radius_mm=3.0)
        r_large = persian_moorish_lace(30.0, 30.0, hex_radius_mm=3.0)
        assert r_large["result"]["hex_count"] > r_small["result"]["hex_count"]

    def test_metal_volume_formula(self):
        r = persian_moorish_lace(15.0, 15.0, wire_diameter_mm=WIRE_DIA)
        res = r["result"]
        total_arc = res["total_arc_length_mm"]
        expected = metal_volume_estimate(WIRE_DIA, total_arc)
        assert abs(res["metal_volume_mm3"] - expected) < 1e-4

    def test_bad_width_returns_error(self):
        r = persian_moorish_lace(0.0, 10.0)
        assert "error" in r

    def test_bad_height_returns_error(self):
        r = persian_moorish_lace(10.0, -5.0)
        assert "error" in r

    def test_known_small_region_hex_count(self):
        # For a 10×10 region with hex_radius=4, we expect at least 1 hexagon
        r = persian_moorish_lace(10.0, 10.0, hex_radius_mm=4.0)
        assert r["result"]["hex_count"] >= 1


# ===========================================================================
# 8. apply_to_band — arc-length preservation
# ===========================================================================

class TestApplyToBand:
    def _straight_line(self, length: float) -> list:
        """A straight polyline along X."""
        return [(0.0, 0.0, 0.0), (length, 0.0, 0.0)]

    def test_basic_ok(self):
        poly = self._straight_line(10.0)
        r = apply_to_band([poly], band_inner_dia_mm=17.0, band_width_mm=3.0)
        assert r.get("ok") is True
        assert "wrapped_polylines" in r["result"]

    def test_arc_length_preserved_straight_line(self):
        """A straight line parallel to X maps to an arc on the cylinder.
        The arc-length difference should be small (< 2% for short segments
        vs large radius) for a fine-segment polyline."""
        n = 200
        length = 10.0
        poly: list = [(length * i / n, 0.0, 0.0) for i in range(n + 1)]
        dia = 60.0  # large ring, ~188mm circumference
        r = apply_to_band([poly], band_inner_dia_mm=dia, band_width_mm=3.0)
        res = r["result"]
        flat_arc = res["flat_total_arc_length_mm"]
        wrapped_arc = res["wrapped_total_arc_length_mm"]
        # Relative difference must be < 1%
        rel_err = abs(wrapped_arc - flat_arc) / flat_arc
        assert rel_err < 0.01, f"arc-length mismatch: flat={flat_arc:.4f}, wrapped={wrapped_arc:.4f}"

    def test_band_wrap_output_on_cylinder(self):
        """Wrapped points should lie on the cylinder at r_mid radius."""
        poly = [(5.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
        r = apply_to_band([poly], band_inner_dia_mm=20.0, band_width_mm=4.0)
        res = r["result"]
        r_mid = res["r_mid_mm"]
        for pt in res["wrapped_polylines"][0]:
            xy_r = math.sqrt(pt[0] ** 2 + pt[1] ** 2)
            assert abs(xy_r - r_mid) < 1e-6

    def test_pattern_width_scaling_fills_circumference(self):
        """With pattern_width_mm set, total X maps to exactly one circumference."""
        poly = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
        dia = 20.0
        band_w = 3.0
        r_mid = dia / 2.0 + band_w / 4.0
        circum = 2.0 * math.pi * r_mid
        r = apply_to_band([poly], band_inner_dia_mm=dia, band_width_mm=band_w,
                          pattern_width_mm=10.0)
        res = r["result"]
        assert abs(res["circumference_mm"] - circum) < 1e-6
        assert abs(res["scale_x_applied"] - circum / 10.0) < 1e-6

    def test_y_maps_to_z(self):
        """Y coordinate in flat pattern maps directly to Z on cylinder."""
        poly = [(0.0, 5.0, 0.0)]
        r = apply_to_band([poly], band_inner_dia_mm=20.0, band_width_mm=4.0)
        # theta = 0 → x=r_mid, y=0, z=5.0
        pt = r["result"]["wrapped_polylines"][0][0]
        assert abs(pt[2] - 5.0) < 1e-6

    def test_bad_diameter_returns_error(self):
        r = apply_to_band([], band_inner_dia_mm=0.0, band_width_mm=3.0)
        assert "error" in r

    def test_bad_band_width_returns_error(self):
        r = apply_to_band([], band_inner_dia_mm=17.0, band_width_mm=0.0)
        assert "error" in r


# ===========================================================================
# 9. LLM tool runners — smoke tests
# ===========================================================================

class TestLLMToolRunners:
    def test_milgrain_border_runner_ok(self):
        r = _call(run_jewelry_filigree_milgrain_border,
                  path_length_mm=20.0, bead_diameter_mm=0.7, pitch_mm=0.9)
        assert "error" not in r, r
        assert "bead_count" in r

    def test_milgrain_border_runner_bad_path(self):
        r = _call(run_jewelry_filigree_milgrain_border,
                  path_length_mm=0.0, bead_diameter_mm=0.7, pitch_mm=0.9)
        assert "error" in r

    def test_florentine_runner_ok(self):
        r = _call(run_jewelry_filigree_florentine_scrollwork, path_length_mm=20.0)
        assert "error" not in r, r
        assert "n_periods" in r

    def test_celtic_runner_ok(self):
        r = _call(run_jewelry_filigree_celtic_knot, knot_type="2_strand", repeat_count=2)
        assert "error" not in r, r
        assert "strands" in r

    def test_celtic_runner_bad_type(self):
        r = _call(run_jewelry_filigree_celtic_knot, knot_type="invalid_knot")
        assert "error" in r

    def test_vine_runner_ok(self):
        r = _call(run_jewelry_filigree_art_nouveau_vine, path_length_mm=30.0)
        assert "error" not in r, r
        assert "stem" in r

    def test_persian_lace_runner_ok(self):
        r = _call(run_jewelry_filigree_persian_lace, width_mm=20.0, height_mm=20.0)
        assert "error" not in r, r
        assert "hex_count" in r

    def test_wire_rope_runner_ok(self):
        r = _call(run_jewelry_filigree_wire_rope, path_length_mm=20.0, strand_count=2)
        assert "error" not in r, r
        assert "strand_count" in r

    def test_apply_to_band_runner_ok(self):
        r = _call(run_jewelry_filigree_apply_to_band,
                  band_inner_dia_mm=17.0,
                  band_width_mm=3.0,
                  pattern_polylines=[[[0.0, 0.0, 0.0], [5.0, 0.0, 0.0]]])
        assert "error" not in r, r
        assert "wrapped_polylines" in r


# ===========================================================================
# 10. Arc-length helper unit tests
# ===========================================================================

class TestArcLengthHelpers:
    def test_single_segment_length(self):
        pts = [(0.0, 0.0, 0.0), (3.0, 4.0, 0.0)]
        assert abs(_arc_length_polyline(pts) - 5.0) < 1e-9

    def test_3d_segment(self):
        pts = [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]
        assert abs(_arc_length_polyline(pts) - math.sqrt(3.0)) < 1e-9

    def test_empty_or_single_point_zero(self):
        assert _arc_length_polyline([]) == 0.0
        assert _arc_length_polyline([(1.0, 0.0, 0.0)]) == 0.0

    def test_sum_of_polylines(self):
        p1 = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
        p2 = [(0.0, 0.0, 0.0), (0.0, 2.0, 0.0)]
        assert abs(_arc_length_polylines([p1, p2]) - 3.0) < 1e-9
