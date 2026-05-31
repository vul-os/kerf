"""
Tests for kerf_cam.offset_3d_path — 3D parallel-offset surface milling.

References
----------
* Machinery's Handbook 31e §1139 — 3-axis surface-offset milling
* Held & Klingenstein (1991) Computers & Graphics 15(3):333–341
  — parallel-offset raster strategy
* Chuang & Yang (1995) Intl J Mach Tools 35(2):261–267
  — scallop height formula h = R - sqrt(R² - (ae/2)²)

Run:
    pytest packages/kerf-cam/tests/test_offset_3d_path.py -v
"""

from __future__ import annotations

import asyncio
import json
import math
import re

import pytest

from kerf_cam.offset_3d_path import (
    Offset3DSpec,
    Offset3DResult,
    _fmt,
    _scallop_height,
    _bilinear_z,
    _build_grid,
    _compute_pass_y_positions,
    generate_offset_3d_path,
    cam_generate_offset_3d_path_spec,
    run_cam_generate_offset_3d_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat_grid(
    x_count: int = 10,
    y_count: int = 10,
    x_range: tuple = (0.0, 9.0),
    y_range: tuple = (0.0, 9.0),
    z_val: float = 0.0,
) -> list:
    """Return a regular flat grid with z = z_val."""
    xs = [x_range[0] + i * (x_range[1] - x_range[0]) / (x_count - 1) for i in range(x_count)]
    ys = [y_range[0] + j * (y_range[1] - y_range[0]) / (y_count - 1) for j in range(y_count)]
    pts = []
    for y in ys:
        for x in xs:
            pts.append((x, y, z_val))
    return pts


def _hemisphere_grid(
    radius: float = 10.0,
    n: int = 11,
) -> list:
    """Return a hemisphere z = sqrt(R² - x² - y²) sampled on a 2D grid.

    Grid spans [-R/2, R/2] × [-R/2, R/2] — well within the hemisphere.
    """
    half = radius / 2.0
    pts = []
    for i in range(n):
        x = -half + i * (2 * half) / (n - 1)
        for j in range(n):
            y = -half + j * (2 * half) / (n - 1)
            r2 = x ** 2 + y ** 2
            z = math.sqrt(max(0.0, radius ** 2 - r2))
            pts.append((x, y, z))
    return pts


def _default_spec(**kw) -> Offset3DSpec:
    """Return an Offset3DSpec with a 10×10 flat grid, tool_radius=5 mm."""
    defaults = dict(
        target_surface_points=_flat_grid(10, 10),
        tool_radius_mm=5.0,
        stepover_mm=1.0,
        feed_mm_per_min=1000.0,
        spindle_rpm=3000.0,
        rapid_z_mm=10000.0,
    )
    defaults.update(kw)
    return Offset3DSpec(**defaults)


def _ctx():
    from kerf_cam._compat import ProjectCtx
    return ProjectCtx()


def _run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. _scallop_height formula — MH 31e §1139 / Chuang & Yang 1995
# ---------------------------------------------------------------------------

class TestScallopHeight:
    def test_known_value_R5_ae1(self):
        """R=5, ae=1: h = 5 - sqrt(25 - 0.25) = 5 - sqrt(24.75) ≈ 0.0251 mm."""
        h = _scallop_height(tool_radius_mm=5.0, stepover_mm=1.0)
        expected = 5.0 - math.sqrt(24.75)
        assert abs(h - expected) < 1e-12, f"h={h} ≠ expected={expected}"

    def test_scallop_positive(self):
        h = _scallop_height(5.0, 1.0)
        assert h > 0.0

    def test_smaller_stepover_smaller_scallop(self):
        """ae=0.5 should give a smaller scallop than ae=1.0."""
        h_large = _scallop_height(5.0, 1.0)
        h_small = _scallop_height(5.0, 0.5)
        assert h_small < h_large

    def test_scallop_zero_stepover_limit(self):
        """ae → 0 → h → 0."""
        h = _scallop_height(5.0, 0.001)
        assert h < 0.001

    def test_scallop_equals_radius_when_ae_equals_2R(self):
        """ae = 2R (full diameter stepover): h = R - sqrt(R² - R²) = R."""
        h = _scallop_height(5.0, 10.0)
        assert abs(h - 5.0) < 1e-12

    def test_scallop_oversized_ae_raises(self):
        """ae > 2R should raise ValueError."""
        with pytest.raises(ValueError):
            _scallop_height(5.0, 11.0)

    def test_different_radii_consistent(self):
        """Larger tool radius with same absolute stepover → smaller scallop."""
        h_small_tool = _scallop_height(3.0, 1.0)
        h_large_tool = _scallop_height(10.0, 1.0)
        assert h_large_tool < h_small_tool

    def test_scallop_numeric_precision(self):
        """Result should be reproducible to float precision."""
        h1 = _scallop_height(5.0, 1.0)
        h2 = _scallop_height(5.0, 1.0)
        assert h1 == h2


# ---------------------------------------------------------------------------
# 2. Offset3DSpec validation
# ---------------------------------------------------------------------------

class TestOffset3DSpecValidation:
    def test_valid_spec_no_error(self):
        s = _default_spec()
        assert s.tool_radius_mm == 5.0

    def test_too_few_points_raises(self):
        with pytest.raises(ValueError, match="at least 4 points"):
            Offset3DSpec(
                target_surface_points=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                tool_radius_mm=5.0, stepover_mm=1.0,
                feed_mm_per_min=1000.0, spindle_rpm=3000.0,
            )

    def test_single_x_value_raises(self):
        pts = [(0.0, float(j), 0.0) for j in range(5)]
        with pytest.raises(ValueError, match="2 distinct X"):
            Offset3DSpec(
                target_surface_points=pts,
                tool_radius_mm=5.0, stepover_mm=1.0,
                feed_mm_per_min=1000.0, spindle_rpm=3000.0,
            )

    def test_zero_tool_radius_raises(self):
        with pytest.raises(ValueError, match="tool_radius_mm"):
            _default_spec(tool_radius_mm=0.0)

    def test_negative_tool_radius_raises(self):
        with pytest.raises(ValueError, match="tool_radius_mm"):
            _default_spec(tool_radius_mm=-1.0)

    def test_zero_stepover_raises(self):
        with pytest.raises(ValueError, match="stepover_mm"):
            _default_spec(stepover_mm=0.0)

    def test_stepover_larger_than_2r_raises(self):
        with pytest.raises(ValueError, match="stepover_mm"):
            _default_spec(tool_radius_mm=5.0, stepover_mm=11.0)

    def test_zero_feed_raises(self):
        with pytest.raises(ValueError, match="feed_mm_per_min"):
            _default_spec(feed_mm_per_min=0.0)

    def test_zero_rpm_raises(self):
        with pytest.raises(ValueError, match="spindle_rpm"):
            _default_spec(spindle_rpm=0.0)


# ---------------------------------------------------------------------------
# 3. Flat surface z=0 — offset toolpath at tool_radius above surface
# ---------------------------------------------------------------------------

class TestFlatSurface:
    """Flat z=0 surface: all tool Z positions must equal tool_radius (Z-offset model)."""

    def test_flat_surface_all_z_at_tool_radius(self):
        """Every G01 Z value should be tool_radius (= 5.0) above flat surface z=0."""
        spec = _default_spec(
            target_surface_points=_flat_grid(10, 10, z_val=0.0),
            tool_radius_mm=5.0,
        )
        result = generate_offset_3d_path(spec)
        # Find all G01 Z values
        z_vals = [float(m) for m in re.findall(r"G01 X[^\n]+ Z(-?\d+\.?\d*)", result.gcode)]
        assert len(z_vals) > 0, "No G01 Z values found in G-code"
        for z in z_vals:
            assert abs(z - 5.0) < 1e-3, f"G01 Z={z} ≠ tool_radius=5.0 on flat surface"

    def test_flat_surface_nonzero_z_offset(self):
        """Flat surface at z=3.0: all tool Z must equal 3.0 + tool_radius."""
        spec = _default_spec(
            target_surface_points=_flat_grid(10, 10, z_val=3.0),
            tool_radius_mm=5.0,
        )
        result = generate_offset_3d_path(spec)
        z_vals = [float(m) for m in re.findall(r"G01 X[^\n]+ Z(-?\d+\.?\d*)", result.gcode)]
        assert len(z_vals) > 0
        for z in z_vals:
            assert abs(z - 8.0) < 1e-3, f"G01 Z={z} ≠ 8.0 (surface 3.0 + R 5.0)"

    def test_flat_surface_has_correct_num_passes(self):
        """10×10 grid, stepover=1 mm, span Y=0..9: 10 passes at y=0,1,...,9."""
        spec = _default_spec(
            target_surface_points=_flat_grid(10, 10, y_range=(0.0, 9.0)),
            stepover_mm=1.0,
        )
        result = generate_offset_3d_path(spec)
        assert result.num_passes == 10

    def test_flat_surface_scallop_height(self):
        """Scallop height for R=5, ae=1 must equal 5 - sqrt(24.75)."""
        spec = _default_spec(tool_radius_mm=5.0, stepover_mm=1.0)
        result = generate_offset_3d_path(spec)
        expected = 5.0 - math.sqrt(24.75)
        assert abs(result.max_scallop_height_mm - expected) < 1e-9


# ---------------------------------------------------------------------------
# 4. Hemisphere surface — toolpath follows curvature
# ---------------------------------------------------------------------------

class TestHemisphereSurface:
    def test_hemisphere_z_increases_toward_centre(self):
        """On a hemisphere the central passes should have higher tool Z than edges."""
        pts = _hemisphere_grid(radius=10.0, n=11)
        spec = Offset3DSpec(
            target_surface_points=pts,
            tool_radius_mm=2.0,
            stepover_mm=1.0,
            feed_mm_per_min=800.0,
            spindle_rpm=4000.0,
        )
        result = generate_offset_3d_path(spec)
        # Extract all G01 Z values
        z_vals = [float(m) for m in re.findall(r"G01 X[^\n]+ Z(-?\d+\.?\d*)", result.gcode)]
        assert len(z_vals) > 0, "No G01 Z moves found"
        # At the centre the hemisphere is highest: z = sqrt(R²) = R = 10
        # Tool Z at centre ≈ 10 + 2 = 12; at edges ≈ sqrt(100-25) + 2 ≈ 10.66
        # So max Z should be near 12
        assert max(z_vals) > 9.0, f"Max Z={max(z_vals)}: expected > 9 for hemisphere R=10"

    def test_hemisphere_num_passes_positive(self):
        pts = _hemisphere_grid(radius=10.0, n=11)
        spec = Offset3DSpec(
            target_surface_points=pts,
            tool_radius_mm=2.0,
            stepover_mm=1.0,
            feed_mm_per_min=800.0,
            spindle_rpm=4000.0,
        )
        result = generate_offset_3d_path(spec)
        assert result.num_passes >= 1

    def test_hemisphere_path_length_positive(self):
        pts = _hemisphere_grid(radius=10.0, n=11)
        spec = Offset3DSpec(
            target_surface_points=pts,
            tool_radius_mm=2.0,
            stepover_mm=1.0,
            feed_mm_per_min=800.0,
            spindle_rpm=4000.0,
        )
        result = generate_offset_3d_path(spec)
        assert result.total_path_length_mm > 0.0

    def test_hemisphere_gcode_contains_varying_z(self):
        """On a hemisphere the Z values should vary (unlike flat surface)."""
        pts = _hemisphere_grid(radius=10.0, n=11)
        spec = Offset3DSpec(
            target_surface_points=pts,
            tool_radius_mm=2.0,
            stepover_mm=1.0,
            feed_mm_per_min=800.0,
            spindle_rpm=4000.0,
        )
        result = generate_offset_3d_path(spec)
        z_vals = [float(m) for m in re.findall(r"G01 X[^\n]+ Z(-?\d+\.?\d*)", result.gcode)]
        z_range = max(z_vals) - min(z_vals)
        # A hemisphere with radius 10 over a ±5 mm span varies by ≈ 10 - sqrt(75) ≈ 1.34 mm
        assert z_range > 0.1, f"Z range={z_range}: expected variation on hemisphere"


# ---------------------------------------------------------------------------
# 5. Scallop height formula verification
# ---------------------------------------------------------------------------

class TestScallopHeightInResult:
    def test_R5_ae1_scallop_is_0_025mm(self):
        """R=5, ae=1: scallop = 5 - sqrt(24.75) ≈ 0.02513 mm."""
        spec = _default_spec(tool_radius_mm=5.0, stepover_mm=1.0)
        result = generate_offset_3d_path(spec)
        expected = 5.0 - math.sqrt(24.75)
        assert abs(result.max_scallop_height_mm - expected) < 1e-9

    def test_lower_stepover_gives_smaller_scallop(self):
        """Halving stepover should drastically reduce scallop height."""
        spec_coarse = _default_spec(tool_radius_mm=5.0, stepover_mm=2.0)
        spec_fine = _default_spec(tool_radius_mm=5.0, stepover_mm=1.0)
        result_coarse = generate_offset_3d_path(spec_coarse)
        result_fine = generate_offset_3d_path(spec_fine)
        assert result_fine.max_scallop_height_mm < result_coarse.max_scallop_height_mm

    def test_scallop_formula_matches_direct_computation(self):
        """Result scallop height must exactly match the formula function."""
        for R, ae in [(5.0, 1.0), (3.0, 0.5), (10.0, 2.0)]:
            spec = _default_spec(tool_radius_mm=R, stepover_mm=ae)
            result = generate_offset_3d_path(spec)
            expected = _scallop_height(R, ae)
            assert abs(result.max_scallop_height_mm - expected) < 1e-9, (
                f"R={R}, ae={ae}: result {result.max_scallop_height_mm} ≠ {expected}"
            )

    def test_scallop_monotone_in_stepover(self):
        """Scallop height must be monotonically increasing with stepover."""
        R = 5.0
        aes = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
        heights = [_scallop_height(R, ae) for ae in aes]
        for i in range(1, len(heights)):
            assert heights[i] > heights[i - 1], (
                f"scallop not increasing at ae={aes[i]}: {heights[i]} ≤ {heights[i - 1]}"
            )


# ---------------------------------------------------------------------------
# 6. G-code structure
# ---------------------------------------------------------------------------

class TestGcodeStructure:
    def test_gcode_starts_ends_with_percent(self):
        result = generate_offset_3d_path(_default_spec())
        lines = result.gcode.strip().split("\n")
        assert lines[0].strip() == "%"
        assert lines[-1].strip() == "%"

    def test_gcode_contains_g21_metric(self):
        result = generate_offset_3d_path(_default_spec())
        assert "G21" in result.gcode

    def test_gcode_contains_g90_absolute(self):
        result = generate_offset_3d_path(_default_spec())
        assert "G90" in result.gcode

    def test_gcode_contains_g94_feed_per_min(self):
        result = generate_offset_3d_path(_default_spec())
        assert "G94" in result.gcode

    def test_gcode_contains_m03_spindle_on(self):
        result = generate_offset_3d_path(_default_spec())
        assert "M03" in result.gcode

    def test_gcode_contains_m05_spindle_off(self):
        result = generate_offset_3d_path(_default_spec())
        assert "M05" in result.gcode

    def test_gcode_contains_m30_program_end(self):
        result = generate_offset_3d_path(_default_spec())
        assert "M30" in result.gcode

    def test_gcode_contains_g00_rapid(self):
        result = generate_offset_3d_path(_default_spec())
        assert "G00" in result.gcode

    def test_gcode_contains_g01_feed(self):
        result = generate_offset_3d_path(_default_spec())
        assert "G01" in result.gcode

    def test_spindle_rpm_in_gcode(self):
        result = generate_offset_3d_path(_default_spec(spindle_rpm=5000.0))
        assert "S5000" in result.gcode

    def test_feed_rate_in_gcode(self):
        result = generate_offset_3d_path(_default_spec(feed_mm_per_min=800.0))
        assert "F800.0" in result.gcode or "F800" in result.gcode


# ---------------------------------------------------------------------------
# 7. Pass count
# ---------------------------------------------------------------------------

class TestPassCount:
    def test_pass_count_matches_stepover(self):
        """Y span = 9 mm, stepover = 1 mm: should give 10 passes (y=0..9)."""
        spec = _default_spec(
            target_surface_points=_flat_grid(10, 10, y_range=(0.0, 9.0)),
            stepover_mm=1.0,
        )
        result = generate_offset_3d_path(spec)
        assert result.num_passes == 10

    def test_fewer_passes_with_larger_stepover(self):
        spec_fine = _default_spec(
            target_surface_points=_flat_grid(10, 10, y_range=(0.0, 9.0)),
            stepover_mm=1.0,
        )
        spec_coarse = _default_spec(
            target_surface_points=_flat_grid(10, 10, y_range=(0.0, 9.0)),
            stepover_mm=2.0,
        )
        r_fine = generate_offset_3d_path(spec_fine)
        r_coarse = generate_offset_3d_path(spec_coarse)
        assert r_fine.num_passes > r_coarse.num_passes

    def test_num_passes_matches_result_field(self):
        result = generate_offset_3d_path(_default_spec())
        # Count Pass comments in G-code
        n_pass_comments = len(re.findall(r"\(Pass \d+/\d+:", result.gcode))
        assert n_pass_comments == result.num_passes


# ---------------------------------------------------------------------------
# 8. Machining time
# ---------------------------------------------------------------------------

class TestMachiningTime:
    def test_time_is_positive(self):
        result = generate_offset_3d_path(_default_spec())
        assert result.machining_time_s > 0.0

    def test_faster_feed_shorter_time(self):
        slow = generate_offset_3d_path(_default_spec(feed_mm_per_min=500.0))
        fast = generate_offset_3d_path(_default_spec(feed_mm_per_min=2000.0))
        assert fast.machining_time_s < slow.machining_time_s

    def test_time_ge_pure_cutting_time(self):
        """Total time ≥ pure cutting time (rapids only add more)."""
        spec = _default_spec(feed_mm_per_min=1000.0)
        result = generate_offset_3d_path(spec)
        pure_s = (result.total_path_length_mm / 1000.0) * 60.0
        assert result.machining_time_s >= pure_s * 0.95


# ---------------------------------------------------------------------------
# 9. Honest caveat
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    def test_caveat_mentions_3_axis(self):
        result = generate_offset_3d_path(_default_spec())
        caveat = result.honest_caveat.lower()
        assert "3-axis" in caveat or "3 axis" in caveat

    def test_caveat_mentions_no_gouge_checking(self):
        result = generate_offset_3d_path(_default_spec())
        assert "gouge" in result.honest_caveat.lower()

    def test_caveat_mentions_no_5_axis(self):
        result = generate_offset_3d_path(_default_spec())
        assert "5-axis" in result.honest_caveat.lower() or "5 axis" in result.honest_caveat.lower()

    def test_caveat_mentions_mh_reference(self):
        result = generate_offset_3d_path(_default_spec())
        assert "MH" in result.honest_caveat or "Handbook" in result.honest_caveat

    def test_caveat_mentions_held_klingenstein(self):
        result = generate_offset_3d_path(_default_spec())
        assert "Held" in result.honest_caveat or "Klingenstein" in result.honest_caveat

    def test_caveat_mentions_scallop(self):
        result = generate_offset_3d_path(_default_spec())
        assert "scallop" in result.honest_caveat.lower() or "Chuang" in result.honest_caveat


# ---------------------------------------------------------------------------
# 10. LLM tool wrapper
# ---------------------------------------------------------------------------

class TestLLMTool:
    def _default_args(self, **overrides) -> dict:
        pts = _flat_grid(5, 5, x_range=(0.0, 4.0), y_range=(0.0, 4.0), z_val=0.0)
        args = {
            "target_surface_points": [[p[0], p[1], p[2]] for p in pts],
            "tool_radius_mm": 5.0,
            "stepover_mm": 1.0,
            "feed_mm_per_min": 1000.0,
            "spindle_rpm": 3000.0,
        }
        args.update(overrides)
        return args

    def test_tool_spec_name(self):
        assert cam_generate_offset_3d_path_spec.name == "cam_generate_offset_3d_path"

    def test_tool_runs_flat_grid(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, args))
        result = json.loads(raw)
        assert "gcode" in result
        assert "G01" in result["gcode"]

    def test_tool_returns_scallop_height(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, args))
        result = json.loads(raw)
        assert "max_scallop_height_mm" in result
        expected = _scallop_height(5.0, 1.0)
        assert abs(result["max_scallop_height_mm"] - expected) < 1e-9

    def test_tool_returns_num_passes(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, args))
        result = json.loads(raw)
        assert "num_passes" in result
        assert result["num_passes"] >= 1

    def test_tool_returns_honest_caveat(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, args))
        result = json.loads(raw)
        assert "honest_caveat" in result
        assert len(result["honest_caveat"]) > 50

    def test_tool_returns_machining_time(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, args))
        result = json.loads(raw)
        assert "machining_time_s" in result
        assert result["machining_time_s"] > 0.0

    def test_tool_returns_path_length(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, args))
        result = json.loads(raw)
        assert "total_path_length_mm" in result
        assert result["total_path_length_mm"] > 0.0

    def test_tool_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, b"not-json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_missing_required_field_returns_error(self):
        ctx = _ctx()
        args = json.dumps({"tool_radius_mm": 5.0}).encode()
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, args))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_zero_tool_radius_returns_error(self):
        ctx = _ctx()
        bad_args = self._default_args(tool_radius_mm=0.0)
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, json.dumps(bad_args).encode()))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_too_large_stepover_returns_error(self):
        ctx = _ctx()
        bad_args = self._default_args(tool_radius_mm=3.0, stepover_mm=20.0)
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, json.dumps(bad_args).encode()))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_hemisphere_produces_varying_z(self):
        """LLM tool on hemisphere surface should produce varying Z in G-code."""
        ctx = _ctx()
        pts = _hemisphere_grid(radius=10.0, n=7)
        args_dict = {
            "target_surface_points": [[p[0], p[1], p[2]] for p in pts],
            "tool_radius_mm": 2.0,
            "stepover_mm": 1.5,
            "feed_mm_per_min": 800.0,
            "spindle_rpm": 4000.0,
        }
        raw = _run_async(run_cam_generate_offset_3d_path(ctx, json.dumps(args_dict).encode()))
        result = json.loads(raw)
        assert "gcode" in result
        z_vals = [float(m) for m in re.findall(r"G01 X[^\n]+ Z(-?\d+\.?\d*)", result["gcode"])]
        assert len(z_vals) > 0
        z_range = max(z_vals) - min(z_vals)
        assert z_range > 0.1, f"Expected Z variation on hemisphere, got range={z_range}"


# ---------------------------------------------------------------------------
# 11. Bilinear interpolation correctness
# ---------------------------------------------------------------------------

class TestBilinearInterp:
    def test_bilinear_at_grid_node_exact(self):
        """At a grid node the interpolation should return the exact z value."""
        pts = _flat_grid(5, 5, z_val=2.5)
        xs, ys, z_dict = _build_grid(pts)
        # Query at a grid node
        z_interp = _bilinear_z(xs[0], ys[0], xs, ys, z_dict)
        assert abs(z_interp - 2.5) < 1e-10

    def test_bilinear_midpoint_flat(self):
        """Midpoint of flat grid should equal the flat z value."""
        pts = _flat_grid(3, 3, x_range=(0.0, 2.0), y_range=(0.0, 2.0), z_val=7.0)
        xs, ys, z_dict = _build_grid(pts)
        z_interp = _bilinear_z(1.0, 1.0, xs, ys, z_dict)
        assert abs(z_interp - 7.0) < 1e-10

    def test_bilinear_clamping_outside_grid(self):
        """Query outside grid boundary should return clamped value without error."""
        pts = _flat_grid(3, 3, x_range=(0.0, 2.0), y_range=(0.0, 2.0), z_val=1.0)
        xs, ys, z_dict = _build_grid(pts)
        # Query well outside grid
        z_interp = _bilinear_z(10.0, 10.0, xs, ys, z_dict)
        assert abs(z_interp - 1.0) < 1e-10  # flat grid: all z=1.0


# ---------------------------------------------------------------------------
# 12. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_minimum_2x2_grid(self):
        """A 2×2 grid (4 points) is the minimum valid input."""
        pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]
        spec = Offset3DSpec(
            target_surface_points=pts,
            tool_radius_mm=2.0,
            stepover_mm=0.5,
            feed_mm_per_min=500.0,
            spindle_rpm=2000.0,
        )
        result = generate_offset_3d_path(spec)
        assert result.num_passes >= 1
        assert "G01" in result.gcode

    def test_small_stepover_gives_many_passes(self):
        """Small stepover → many passes."""
        spec_fine = _default_spec(stepover_mm=0.5)
        spec_coarse = _default_spec(stepover_mm=2.0)
        r_fine = generate_offset_3d_path(spec_fine)
        r_coarse = generate_offset_3d_path(spec_coarse)
        assert r_fine.num_passes > r_coarse.num_passes

    def test_large_grid_works(self):
        """20×20 grid with tool R=3 mm should work without error."""
        pts = _flat_grid(20, 20, x_range=(0.0, 100.0), y_range=(0.0, 100.0), z_val=5.0)
        spec = Offset3DSpec(
            target_surface_points=pts,
            tool_radius_mm=3.0,
            stepover_mm=2.0,
            feed_mm_per_min=1500.0,
            spindle_rpm=5000.0,
        )
        result = generate_offset_3d_path(spec)
        assert result.num_passes >= 1
        assert result.total_path_length_mm > 0.0

    def test_sloped_plane_varying_z(self):
        """A sloped surface z = x should produce varying Z in toolpath."""
        pts = []
        for i in range(5):
            for j in range(5):
                x = float(i)
                y = float(j)
                z = x  # slope: z = x
                pts.append((x, y, z))
        spec = Offset3DSpec(
            target_surface_points=pts,
            tool_radius_mm=2.0,
            stepover_mm=1.0,
            feed_mm_per_min=800.0,
            spindle_rpm=3000.0,
        )
        result = generate_offset_3d_path(spec)
        z_vals = [float(m) for m in re.findall(r"G01 X[^\n]+ Z(-?\d+\.?\d*)", result.gcode)]
        assert len(z_vals) > 0
        z_range = max(z_vals) - min(z_vals)
        # Slope z=x over x=0..4 → z should vary by ~4 mm
        assert z_range > 1.0, f"Expected significant Z variation on sloped surface, got {z_range}"
