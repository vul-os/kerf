"""
Tests for kerf_cam.profile_roughing — multi-pass 2D profile roughing toolpath.

References
----------
* Machinery's Handbook 31e §1131 — Profile milling
* Sandvik CoroPlus Contour Roughing (2024)
* NIST RS-274/NGC §3.5 — G-code data input format

Run:
    pytest packages/kerf-cam/tests/test_profile_roughing.py -v
"""

from __future__ import annotations

import asyncio
import json
import math
import re

import pytest

from kerf_cam.profile_roughing import (
    ProfileMillSpec,
    ProfileRoughingResult,
    _fmt,
    _polygon_area,
    _polygon_perimeter,
    _offset_polygon,
    _compute_radial_offsets,
    generate_profile_roughing,
    cam_generate_profile_roughing_spec,
    run_cam_generate_profile_roughing,
)


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

def _square_profile(side: float = 100.0) -> list:
    """Return a 100×100 mm square CCW polygon starting at (0,0)."""
    return [
        (0.0, 0.0),
        (side, 0.0),
        (side, side),
        (0.0, side),
    ]


def _spec(**kw) -> ProfileMillSpec:
    """Return a ProfileMillSpec with sensible defaults (100×100 square)."""
    defaults = dict(
        profile_2d=_square_profile(),
        stock_offset_mm=10.0,
        finish_allowance_mm=0.3,
        cutter_diameter_mm=12.0,
        depth_per_pass_mm=5.0,
        total_depth_mm=10.0,
        feed_mm_per_min=800.0,
        spindle_rpm=3000.0,
        rapid_z_mm=10000.0,
        rapid_clearance_mm=5.0,
    )
    defaults.update(kw)
    return ProfileMillSpec(**defaults)


def _run_async(coro):
    return asyncio.run(coro)


def _ctx():
    from kerf_cam._compat import ProjectCtx
    return ProjectCtx()


# ---------------------------------------------------------------------------
# 1. _fmt helper — NIST RS-274/NGC §3.5.1 decimal notation
# ---------------------------------------------------------------------------

class TestFmt:
    def test_integer_has_decimal_point(self):
        assert "." in _fmt(10.0)

    def test_zero_value(self):
        assert _fmt(0.0) == "0.0"

    def test_positive_float(self):
        assert _fmt(12.5) == "12.5"

    def test_negative_float(self):
        assert _fmt(-5.5) == "-5.5"

    def test_trailing_zeros_stripped(self):
        assert _fmt(3.5000) == "3.5"

    def test_integer_becomes_point_zero(self):
        assert _fmt(100.0) == "100.0"


# ---------------------------------------------------------------------------
# 2. ProfileMillSpec validation
# ---------------------------------------------------------------------------

class TestProfileMillSpecValidation:
    def test_valid_spec_no_error(self):
        s = _spec()
        assert s.cutter_diameter_mm == 12.0

    def test_too_few_vertices_raises(self):
        with pytest.raises(ValueError, match="at least 3 vertices"):
            _spec(profile_2d=[(0.0, 0.0), (10.0, 0.0)])

    def test_zero_stock_offset_raises(self):
        with pytest.raises(ValueError, match="stock_offset_mm"):
            _spec(stock_offset_mm=0.0)

    def test_negative_stock_offset_raises(self):
        with pytest.raises(ValueError, match="stock_offset_mm"):
            _spec(stock_offset_mm=-1.0)

    def test_stock_offset_le_finish_raises(self):
        with pytest.raises(ValueError, match="stock_offset_mm.*finish_allowance"):
            _spec(stock_offset_mm=0.3, finish_allowance_mm=0.3)

    def test_negative_finish_allowance_raises(self):
        with pytest.raises(ValueError, match="finish_allowance_mm"):
            _spec(finish_allowance_mm=-0.1)

    def test_zero_cutter_diameter_raises(self):
        with pytest.raises(ValueError, match="cutter_diameter_mm"):
            _spec(cutter_diameter_mm=0.0)

    def test_zero_depth_per_pass_raises(self):
        with pytest.raises(ValueError, match="depth_per_pass_mm"):
            _spec(depth_per_pass_mm=0.0)

    def test_zero_total_depth_raises(self):
        with pytest.raises(ValueError, match="total_depth_mm"):
            _spec(total_depth_mm=0.0)

    def test_zero_feed_raises(self):
        with pytest.raises(ValueError, match="feed_mm_per_min"):
            _spec(feed_mm_per_min=0.0)

    def test_zero_rpm_raises(self):
        with pytest.raises(ValueError, match="spindle_rpm"):
            _spec(spindle_rpm=0.0)


# ---------------------------------------------------------------------------
# 3. _polygon_area — Shoelace formula
# ---------------------------------------------------------------------------

class TestPolygonArea:
    def test_100x100_square_area(self):
        """100×100 mm square CCW → area = 10 000 mm²."""
        pts = _square_profile(100.0)
        area = _polygon_area(pts)
        assert abs(area - 10000.0) < 1e-6

    def test_ccw_positive_area(self):
        """CCW polygon → positive signed area."""
        pts = _square_profile(50.0)
        assert _polygon_area(pts) > 0.0

    def test_cw_negative_area(self):
        """CW polygon → negative signed area."""
        pts = list(reversed(_square_profile(50.0)))
        assert _polygon_area(pts) < 0.0

    def test_unit_square(self):
        pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        assert abs(_polygon_area(pts) - 1.0) < 1e-12


# ---------------------------------------------------------------------------
# 4. _compute_radial_offsets — pass planning
# ---------------------------------------------------------------------------

class TestComputeRadialOffsets:
    def test_100mm_stock_12mm_cutter_03_finish(self):
        """
        stock=10 mm, cutter_radius=6 mm, finish=0.3 mm.
        Passes: 10.0, 4.0 (>0.3); last = 0.3.
        Steps: 10 → 4 → 0.3 = 3 passes.
        """
        spec = _spec(
            stock_offset_mm=10.0,
            finish_allowance_mm=0.3,
            cutter_diameter_mm=12.0,
        )
        offsets = _compute_radial_offsets(spec)
        # First pass at stock
        assert abs(offsets[0] - 10.0) < 1e-9
        # Last pass at finish allowance
        assert abs(offsets[-1] - 0.3) < 1e-9
        # No duplicate of finish (offsets strictly decreasing)
        for i in range(len(offsets) - 1):
            assert offsets[i] > offsets[i + 1]

    def test_last_offset_always_finish_allowance(self):
        """Final radial pass is always exactly at finish_allowance_mm."""
        for finish in [0.0, 0.1, 0.3, 0.5]:
            spec = _spec(finish_allowance_mm=finish, stock_offset_mm=finish + 5.0)
            offsets = _compute_radial_offsets(spec)
            assert abs(offsets[-1] - finish) < 1e-9, (
                f"finish={finish}, last offset={offsets[-1]}"
            )

    def test_zero_finish_allowance_ends_at_zero(self):
        spec = _spec(finish_allowance_mm=0.0, stock_offset_mm=6.0)
        offsets = _compute_radial_offsets(spec)
        assert abs(offsets[-1] - 0.0) < 1e-9

    def test_step_equals_cutter_radius(self):
        """Interior passes are separated by cutter_radius."""
        spec = _spec(stock_offset_mm=20.0, cutter_diameter_mm=12.0,
                     finish_allowance_mm=0.0)
        offsets = _compute_radial_offsets(spec)
        cutter_radius = 6.0
        for i in range(len(offsets) - 2):   # exclude last (finish) jump
            gap = offsets[i] - offsets[i + 1]
            assert abs(gap - cutter_radius) < 1e-9, (
                f"Gap at i={i}: {gap} != {cutter_radius}"
            )


# ---------------------------------------------------------------------------
# 5. generate_profile_roughing — axial and radial pass counts
# ---------------------------------------------------------------------------

class TestAxialRadialCounts:
    def test_2_axial_passes(self):
        """
        100×100 sq, 10mm stock, 0.3mm finish, 12mm cutter, 5mm DOC, 10mm total:
        axial = ceil(10/5) = 2.
        """
        r = generate_profile_roughing(_spec())
        assert r.num_axial_passes == 2

    def test_axial_pass_count_formula(self):
        """num_axial_passes == ceil(total_depth / depth_per_pass)."""
        for total, per_pass, expected in [
            (10.0, 5.0, 2),
            (10.0, 3.0, 4),
            (7.5, 5.0, 2),
            (1.0, 5.0, 1),
            (5.0, 5.0, 1),
        ]:
            r = generate_profile_roughing(
                _spec(total_depth_mm=total, depth_per_pass_mm=per_pass)
            )
            assert r.num_axial_passes == expected, (
                f"total={total}, per_pass={per_pass}: "
                f"got {r.num_axial_passes}, expected {expected}"
            )

    def test_reduce_doc_gives_more_axial_passes(self):
        """Halving depth_per_pass doubles num_axial_passes."""
        r5 = generate_profile_roughing(_spec(depth_per_pass_mm=5.0, total_depth_mm=10.0))
        r2 = generate_profile_roughing(_spec(depth_per_pass_mm=2.0, total_depth_mm=10.0))
        assert r2.num_axial_passes > r5.num_axial_passes

    def test_num_radial_passes_ge_2(self):
        """With stock=10mm > finish=0.3mm, always at least 2 radial passes."""
        r = generate_profile_roughing(_spec())
        assert r.num_radial_passes >= 2

    def test_num_radial_passes_consistent_with_offsets(self):
        """num_radial_passes must match len(_compute_radial_offsets)."""
        spec = _spec()
        offsets = _compute_radial_offsets(spec)
        r = generate_profile_roughing(spec)
        assert r.num_radial_passes == len(offsets)


# ---------------------------------------------------------------------------
# 6. Material removal volume
# ---------------------------------------------------------------------------

class TestMaterialRemoval:
    def test_mrr_positive(self):
        r = generate_profile_roughing(_spec())
        assert r.material_removal_mm3 > 0.0

    def test_mrr_stock_minus_finish(self):
        """
        MRR = (stock_area − finish_area) × total_depth.
        For a 100×100 square:
          stock_poly offset +10 mm → 120×120 = 14 400 mm²
          finish_poly offset +0.3 mm → 100.6×100.6 ≈ 10 120.36 mm²
          MRR ≈ (14400 − 10120.36) × 10 ≈ 42 796 mm³
        (Values approximate due to bisector corner expansion.)
        """
        spec = _spec(
            stock_offset_mm=10.0,
            finish_allowance_mm=0.3,
            total_depth_mm=10.0,
        )
        r = generate_profile_roughing(spec)
        # Manually compute
        from kerf_cam.profile_roughing import _offset_polygon, _polygon_area
        stock_poly = _offset_polygon(spec.profile_2d, spec.stock_offset_mm)
        finish_poly = _offset_polygon(spec.profile_2d, spec.finish_allowance_mm)
        expected = (abs(_polygon_area(stock_poly)) - abs(_polygon_area(finish_poly))) * 10.0
        assert abs(r.material_removal_mm3 - expected) < 1e-3

    def test_larger_stock_offset_more_mrr(self):
        r_small = generate_profile_roughing(_spec(stock_offset_mm=5.0))
        r_large = generate_profile_roughing(_spec(stock_offset_mm=15.0))
        assert r_large.material_removal_mm3 > r_small.material_removal_mm3

    def test_larger_depth_more_mrr(self):
        r_shallow = generate_profile_roughing(_spec(total_depth_mm=5.0))
        r_deep = generate_profile_roughing(_spec(total_depth_mm=20.0))
        assert r_deep.material_removal_mm3 > r_shallow.material_removal_mm3


# ---------------------------------------------------------------------------
# 7. G-code structure validation
# ---------------------------------------------------------------------------

class TestGcodeStructure:
    def _result(self, **kw) -> ProfileRoughingResult:
        return generate_profile_roughing(_spec(**kw))

    def test_gcode_starts_ends_with_percent(self):
        """RS-274/NGC programs delimited by %."""
        r = self._result()
        lines = [l.strip() for l in r.gcode.strip().split("\n")]
        assert lines[0] == "%"
        assert lines[-1] == "%"

    def test_gcode_contains_g21_metric(self):
        assert "G21" in self._result().gcode

    def test_gcode_contains_g90_absolute(self):
        assert "G90" in self._result().gcode

    def test_gcode_contains_g94_feed_per_min(self):
        assert "G94" in self._result().gcode

    def test_gcode_contains_m03_spindle_on(self):
        assert "M03" in self._result().gcode

    def test_gcode_contains_m05_spindle_off(self):
        assert "M05" in self._result().gcode

    def test_gcode_contains_m30_program_end(self):
        assert "M30" in self._result().gcode

    def test_gcode_contains_g00_rapid(self):
        assert "G00" in self._result().gcode

    def test_gcode_contains_g01_feed(self):
        assert "G01" in self._result().gcode

    def test_z_cut_is_negative(self):
        """Cutting Z must be negative (below work surface at Z=0)."""
        r = self._result(total_depth_mm=10.0)
        match = re.search(r"G01 Z(-\d+\.?\d*)", r.gcode)
        assert match, "Expected G01 Z<negative> plunge line in gcode"
        z_val = float(match.group(1))
        assert z_val < 0.0

    def test_spindle_rpm_in_gcode(self):
        r = self._result(spindle_rpm=5000.0)
        assert "S5000" in r.gcode

    def test_feed_rate_in_gcode(self):
        r = self._result(feed_mm_per_min=600.0)
        assert "F600.0" in r.gcode or "F600" in r.gcode


# ---------------------------------------------------------------------------
# 8. Path length
# ---------------------------------------------------------------------------

class TestPathLength:
    def test_path_length_positive(self):
        r = generate_profile_roughing(_spec())
        assert r.total_path_length_mm > 0.0

    def test_more_passes_more_path_length(self):
        """Smaller DOC → more axial passes → more total path length."""
        r5 = generate_profile_roughing(_spec(depth_per_pass_mm=5.0))
        r2 = generate_profile_roughing(_spec(depth_per_pass_mm=2.0))
        assert r2.total_path_length_mm > r5.total_path_length_mm

    def test_path_length_scales_with_axial_passes(self):
        """
        Doubling num_axial_passes should roughly double path length
        (same radial pattern per level).
        """
        r1 = generate_profile_roughing(
            _spec(depth_per_pass_mm=10.0, total_depth_mm=10.0)
        )
        r2 = generate_profile_roughing(
            _spec(depth_per_pass_mm=5.0, total_depth_mm=10.0)
        )
        assert abs(r2.total_path_length_mm / r1.total_path_length_mm - 2.0) < 0.01


# ---------------------------------------------------------------------------
# 9. Machining time
# ---------------------------------------------------------------------------

class TestMachiningTime:
    def test_time_is_positive(self):
        r = generate_profile_roughing(_spec())
        assert r.machining_time_s > 0.0

    def test_faster_feed_gives_shorter_time(self):
        slow = generate_profile_roughing(_spec(feed_mm_per_min=400.0))
        fast = generate_profile_roughing(_spec(feed_mm_per_min=1600.0))
        assert fast.machining_time_s < slow.machining_time_s

    def test_time_ge_pure_cutting_time(self):
        """Total time >= pure cutting time (plunge + rapid only add more)."""
        r = generate_profile_roughing(_spec(feed_mm_per_min=800.0))
        pure_s = (r.total_path_length_mm / 800.0) * 60.0
        assert r.machining_time_s >= pure_s * 0.95


# ---------------------------------------------------------------------------
# 10. Honest caveat
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    def _result(self, **kw) -> ProfileRoughingResult:
        return generate_profile_roughing(_spec(**kw))

    def test_caveat_mentions_2d_profile(self):
        r = self._result()
        caveat_lower = r.honest_caveat.lower()
        assert "2d" in caveat_lower or "profile" in caveat_lower

    def test_caveat_mentions_no_islands(self):
        r = self._result()
        assert "island" in r.honest_caveat.lower()

    def test_caveat_mentions_helical(self):
        r = self._result()
        assert "helical" in r.honest_caveat.lower() or "ramp" in r.honest_caveat.lower()

    def test_caveat_mentions_bisector(self):
        r = self._result()
        assert "bisector" in r.honest_caveat.lower() or "minkowski" in r.honest_caveat.lower()

    def test_caveat_mentions_mh_reference(self):
        r = self._result()
        assert "MH" in r.honest_caveat or "Handbook" in r.honest_caveat

    def test_caveat_mentions_sandvik(self):
        r = self._result()
        assert "Sandvik" in r.honest_caveat


# ---------------------------------------------------------------------------
# 11. Polygon geometry helpers
# ---------------------------------------------------------------------------

class TestPolygonHelpers:
    def test_offset_square_larger(self):
        """Offsetting outward → larger polygon."""
        pts = _square_profile(100.0)
        offset_pts = _offset_polygon(pts, 10.0)
        area_orig = abs(_polygon_area(pts))
        area_offset = abs(_polygon_area(offset_pts))
        assert area_offset > area_orig

    def test_offset_polygon_preserves_vertex_count(self):
        """Offset polygon has same number of vertices as input."""
        pts = _square_profile(100.0)
        offset_pts = _offset_polygon(pts, 5.0)
        assert len(offset_pts) == len(pts)

    def test_polygon_perimeter_100x100_square(self):
        """100×100 square perimeter = 400 mm."""
        pts = _square_profile(100.0)
        assert abs(_polygon_perimeter(pts) - 400.0) < 1e-9

    def test_negative_offset_shrinks_polygon(self):
        """Negative offset (inward) → smaller area."""
        pts = _square_profile(100.0)
        inward_pts = _offset_polygon(pts, -5.0)
        area_orig = abs(_polygon_area(pts))
        area_inward = abs(_polygon_area(inward_pts))
        assert area_inward < area_orig


# ---------------------------------------------------------------------------
# 12. LLM tool wrapper
# ---------------------------------------------------------------------------

class TestLLMTool:
    def _default_args(self, **overrides) -> dict:
        args = {
            "profile_2d": [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]],
            "stock_offset_mm": 10.0,
            "finish_allowance_mm": 0.3,
            "cutter_diameter_mm": 12.0,
            "depth_per_pass_mm": 5.0,
            "total_depth_mm": 10.0,
            "feed_mm_per_min": 800.0,
            "spindle_rpm": 3000.0,
        }
        args.update(overrides)
        return args

    def test_tool_spec_name(self):
        assert cam_generate_profile_roughing_spec.name == "cam_generate_profile_roughing"

    def test_tool_runs_default_spec(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_profile_roughing(ctx, args))
        result = json.loads(raw)
        assert "gcode" in result
        assert "G01" in result["gcode"]

    def test_tool_returns_axial_passes(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_profile_roughing(ctx, args))
        result = json.loads(raw)
        assert result["num_axial_passes"] == 2

    def test_tool_returns_radial_passes(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_profile_roughing(ctx, args))
        result = json.loads(raw)
        assert result["num_radial_passes"] >= 2

    def test_tool_returns_mrr(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_profile_roughing(ctx, args))
        result = json.loads(raw)
        assert "material_removal_mm3" in result
        assert result["material_removal_mm3"] > 0.0

    def test_tool_returns_path_length(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_profile_roughing(ctx, args))
        result = json.loads(raw)
        assert result["total_path_length_mm"] > 0.0

    def test_tool_returns_machining_time(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_profile_roughing(ctx, args))
        result = json.loads(raw)
        assert result["machining_time_s"] > 0.0

    def test_tool_returns_honest_caveat(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_profile_roughing(ctx, args))
        result = json.loads(raw)
        assert "honest_caveat" in result
        assert len(result["honest_caveat"]) > 50

    def test_tool_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run_async(run_cam_generate_profile_roughing(ctx, b"not-json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_missing_required_field_returns_error(self):
        ctx = _ctx()
        incomplete = {"profile_2d": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]}
        raw = _run_async(
            run_cam_generate_profile_roughing(ctx, json.dumps(incomplete).encode())
        )
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_invalid_stock_offset_returns_error(self):
        ctx = _ctx()
        bad = self._default_args(stock_offset_mm=0.0)
        raw = _run_async(
            run_cam_generate_profile_roughing(ctx, json.dumps(bad).encode())
        )
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_custom_depth_per_pass(self):
        """1mm DOC → 10 axial passes for 10mm total depth."""
        ctx = _ctx()
        args = self._default_args(depth_per_pass_mm=1.0, total_depth_mm=10.0)
        raw = _run_async(
            run_cam_generate_profile_roughing(ctx, json.dumps(args).encode())
        )
        result = json.loads(raw)
        assert result["num_axial_passes"] == 10

    def test_tool_triangular_profile(self):
        """Triangle profile with 3 vertices — should work without error."""
        ctx = _ctx()
        args = self._default_args(
            profile_2d=[[0.0, 0.0], [80.0, 0.0], [40.0, 70.0]]
        )
        raw = _run_async(
            run_cam_generate_profile_roughing(ctx, json.dumps(args).encode())
        )
        result = json.loads(raw)
        assert "gcode" in result
        assert result.get("code") is None   # no error code

    def test_tool_zero_finish_allowance(self):
        """finish_allowance=0.0 is valid (cuts right to nominal profile)."""
        ctx = _ctx()
        args = self._default_args(finish_allowance_mm=0.0, stock_offset_mm=5.0)
        raw = _run_async(
            run_cam_generate_profile_roughing(ctx, json.dumps(args).encode())
        )
        result = json.loads(raw)
        assert "gcode" in result
        assert result.get("code") is None
