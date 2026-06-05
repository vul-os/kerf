"""
Tests for kerf_cam.onmachine_probing — in-cycle on-machine touch-probe G-code.

Covers:
  - Bore/boss centre-find emits correct probe moves + G31/macro calls
  - WCS-set cycle writes G54 offset from probed datum (G10 L2)
  - Web/pocket width probes two opposing faces
  - Emitted G-code parses as valid blocks (matched cycle calls)
  - Measurement points match nominal geometry
  - Tool-length set cycle emits correct G31 + G10 L11 blocks
  - Both renishaw and fanuc_g31 dialects round-trip

Run:
    pytest packages/kerf-cam/tests/test_onmachine_probing.py -v
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from kerf_cam.onmachine_probing import (
    MeasurementPoint,
    ProbingCycleResult,
    generate_bore_centre_find,
    generate_surface_measure,
    generate_tool_length_set,
    generate_web_pocket_width,
    run_onmachine_probing,
    cam_onmachine_probing_spec,
    run_cam_onmachine_probing,
    WCS_CODES,
    _FanucG31Emitter,
    _RenishawEmitter,
    _fmt,
)


# ---------------------------------------------------------------------------
# Helper: assert a block of G-code is parseable
# ---------------------------------------------------------------------------

def _gcode_blocks(gcode: str) -> list[str]:
    """Return non-empty, non-comment G-code lines."""
    blocks = []
    for line in gcode.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("(") and stripped not in {"%"}:
            # Remove inline comments (...)
            cleaned = re.sub(r"\([^)]*\)", "", stripped).strip()
            if cleaned:
                blocks.append(cleaned)
    return blocks


def _has_word(line: str, word: str) -> bool:
    """True if G-code line contains the G/M/other word (case-insensitive)."""
    return word.upper() in line.upper()


def _g31_code_lines(gcode: str, *, axis: str | None = None) -> list[str]:
    """Return G31 code lines, excluding comment lines (those starting with '(')."""
    lines = []
    for l in gcode.splitlines():
        stripped = l.strip()
        if stripped.startswith("("):
            continue
        if "G31" not in stripped:
            continue
        if axis is not None and f" {axis.upper()}" not in stripped:
            continue
        lines.append(stripped)
    return lines


# ---------------------------------------------------------------------------
# _fmt helper
# ---------------------------------------------------------------------------

def test_fmt_basic():
    assert _fmt(1.0) == "1.0"
    assert _fmt(2.5) == "2.5"
    assert _fmt(10.0, dp=3) == "10.0"
    assert _fmt(0.123456, dp=3) == "0.123"
    assert _fmt(100.0, dp=0) == "100"


# ---------------------------------------------------------------------------
# Surface measure — fanuc_g31
# ---------------------------------------------------------------------------

class TestSurfaceMeasureFanuc:
    def _result(self, axis="Z", travel=-10.0, wcs=1, offset=0.0):
        return generate_surface_measure(
            x=50.0, y=25.0, z_approach=5.0,
            axis=axis, travel=travel,
            probe_feed=300.0,
            retract_mm=2.0,
            safe_z=50.0,
            wcs_number=wcs,
            offset_mm=offset,
            dialect="fanuc_g31",
            result_var=100,
        )

    def test_gcode_contains_G31(self):
        r = self._result()
        assert "G31" in r.gcode

    def test_gcode_contains_G10_L2(self):
        r = self._result()
        # WCS update block
        assert "G10" in r.gcode and "L2" in r.gcode

    def test_wcs_number_g54(self):
        r = self._result(wcs=1)
        # P1 = G54
        assert "P1" in r.gcode

    def test_wcs_number_g55(self):
        r = self._result(wcs=2)
        assert "P2" in r.gcode

    def test_measurement_point_count(self):
        r = self._result()
        assert len(r.measurement_points) == 1

    def test_measurement_point_z_axis(self):
        r = self._result(axis="Z")
        mp = r.measurement_points[0]
        assert mp.direction in ("+Z", "-Z")

    def test_measurement_point_x_y(self):
        r = self._result()
        mp = r.measurement_points[0]
        assert mp.x == 50.0
        assert mp.y == 25.0

    def test_gcode_has_feed(self):
        r = self._result()
        # G31 must carry feed — exclude comment lines (starting with '(')
        g31_lines = [
            l.strip() for l in r.gcode.splitlines()
            if "G31" in l and not l.strip().startswith("(")
        ]
        assert len(g31_lines) >= 1
        for l in g31_lines:
            assert "F" in l, f"G31 line missing F word: {l!r}"

    def test_metric_mode(self):
        r = self._result()
        assert "G21" in r.gcode

    def test_absolute_mode(self):
        r = self._result()
        assert "G90" in r.gcode

    def test_program_delimiters(self):
        r = self._result()
        assert r.gcode.strip().startswith("%")
        assert r.gcode.strip().endswith("%")

    def test_skip_register_in_gcode(self):
        r = self._result(axis="Z")
        # #5063 = Fanuc skip Z register
        assert "#5063" in r.gcode

    def test_x_axis_uses_skip_x_register(self):
        r = self._result(axis="X", travel=-5.0)
        assert "#5061" in r.gcode

    def test_y_axis_uses_skip_y_register(self):
        r = self._result(axis="Y", travel=5.0)
        assert "#5062" in r.gcode

    def test_offset_reflected_in_g10(self):
        r = self._result(offset=1.5)
        # The G10 line must incorporate the offset
        g10_lines = [l for l in r.gcode.splitlines() if "G10" in l and "L2" in l]
        assert len(g10_lines) >= 1
        # offset 1.5 must appear in the expression
        assert "1.5" in g10_lines[0], f"offset not in G10 line: {g10_lines[0]!r}"

    def test_caveat_non_empty(self):
        r = self._result()
        assert len(r.honest_caveat) > 20

    def test_wcs_update_logic_non_empty(self):
        r = self._result()
        assert len(r.wcs_update_logic) > 10


# ---------------------------------------------------------------------------
# Surface measure — renishaw
# ---------------------------------------------------------------------------

class TestSurfaceMeasureRenishaw:
    def _result(self):
        return generate_surface_measure(
            x=0.0, y=0.0, z_approach=5.0,
            axis="Z", travel=-8.0,
            probe_feed=300.0,
            retract_mm=2.0,
            safe_z=50.0,
            wcs_number=1,
            offset_mm=0.0,
            dialect="renishaw",
            result_var=100,
        )

    def test_g65_call_present(self):
        r = self._result()
        assert "G65" in r.gcode

    def test_macro_9811_present(self):
        # O9811 = Renishaw surface measure
        r = self._result()
        assert "P9811" in r.gcode

    def test_protected_move_9810(self):
        r = self._result()
        assert "P9810" in r.gcode

    def test_gcode_parseable_blocks(self):
        r = self._result()
        blocks = _gcode_blocks(r.gcode)
        # Must have several parseable blocks
        assert len(blocks) >= 3


# ---------------------------------------------------------------------------
# Bore centre-find — fanuc_g31
# ---------------------------------------------------------------------------

class TestBoreCentreFindFanuc:
    def _result(self, is_boss=False):
        return generate_bore_centre_find(
            cx=100.0, cy=50.0,
            approach_z=5.0,
            bore_z=-15.0,
            nominal_diameter=30.0,
            probe_feed=300.0,
            retract_mm=2.0,
            safe_z=50.0,
            wcs_number=1,
            dialect="fanuc_g31",
            is_boss=is_boss,
            var_cx=100,
            var_cy=101,
        )

    def test_four_g31_probes(self):
        r = self._result()
        g31_lines = _g31_code_lines(r.gcode)
        assert len(g31_lines) == 4, (
            f"Expected 4 G31 probe moves (±X, ±Y), got {len(g31_lines)}"
        )

    def test_probes_plus_x_and_minus_x(self):
        """+X and -X wall probes must be present."""
        r = self._result()
        g31_x = _g31_code_lines(r.gcode, axis="X")
        assert len(g31_x) == 2, f"Expected 2 X-axis probes, got {len(g31_x)}: {g31_x}"

    def test_probes_plus_y_and_minus_y(self):
        """±Y wall probes must be present."""
        r = self._result()
        g31_y = _g31_code_lines(r.gcode, axis="Y")
        assert len(g31_y) == 2, f"Expected 2 Y-axis probes, got {len(g31_y)}: {g31_y}"

    def test_centre_arithmetic(self):
        """Centre = (hi + lo) / 2 — must appear in G-code."""
        r = self._result()
        # Look for an averaging expression
        assert "+#" in r.gcode and "/2" in r.gcode, (
            "Centre averaging formula [hi+lo]/2 not found in G-code"
        )

    def test_wcs_g10_l2_x_and_y(self):
        """G10 L2 must set both X and Y in G54."""
        r = self._result()
        g10_lines = [l for l in r.gcode.splitlines() if "G10" in l and "L2" in l]
        assert len(g10_lines) >= 2, (
            f"Expected >=2 G10 L2 lines (X and Y), got {len(g10_lines)}: {g10_lines}"
        )
        axes = set()
        for l in g10_lines:
            if " X" in l:
                axes.add("X")
            if " Y" in l:
                axes.add("Y")
        assert "X" in axes, "G10 L2 X line not found"
        assert "Y" in axes, "G10 L2 Y line not found"

    def test_four_measurement_points(self):
        """4 measurement points for ±X and ±Y walls."""
        r = self._result()
        assert len(r.measurement_points) == 4

    def test_measurement_point_labels(self):
        r = self._result()
        labels = {mp.label for mp in r.measurement_points}
        assert "bore_+X" in labels
        assert "bore_-X" in labels
        assert "bore_+Y" in labels
        assert "bore_-Y" in labels

    def test_measurement_points_at_correct_positions(self):
        """±X walls at cx ± nominal_r; ±Y walls at cy ± nominal_r."""
        r = self._result()
        nominal_r = 15.0  # 30 / 2
        for mp in r.measurement_points:
            if "+X" in mp.label:
                assert abs(mp.x - (100.0 + nominal_r)) < 1e-6
                assert abs(mp.y - 50.0) < 1e-6
            elif "-X" in mp.label:
                assert abs(mp.x - (100.0 - nominal_r)) < 1e-6
            elif "+Y" in mp.label:
                assert abs(mp.y - (50.0 + nominal_r)) < 1e-6
            elif "-Y" in mp.label:
                assert abs(mp.y - (50.0 - nominal_r)) < 1e-6

    def test_boss_centre_find(self):
        """Boss centre-find uses same 4-point algorithm."""
        r = self._result(is_boss=True)
        g31_lines = _g31_code_lines(r.gcode)
        assert len(g31_lines) == 4

    def test_safe_z_retract_present(self):
        r = self._result()
        # Safe Z (50.0) must appear at end
        assert "Z50.0" in r.gcode or "Z50" in r.gcode

    def test_bore_z_in_gcode(self):
        r = self._result()
        # bore_z = -15.0 must appear (plunge to probe depth)
        assert "Z-15.0" in r.gcode

    def test_program_delimiters(self):
        r = self._result()
        assert r.gcode.strip().startswith("%")
        assert r.gcode.strip().endswith("%")

    def test_skip_x_register_used(self):
        r = self._result()
        assert "#5061" in r.gcode

    def test_skip_y_register_used(self):
        r = self._result()
        assert "#5062" in r.gcode


# ---------------------------------------------------------------------------
# Bore centre-find — renishaw
# ---------------------------------------------------------------------------

class TestBoreCentreFindRenishaw:
    def _result(self):
        return generate_bore_centre_find(
            cx=0.0, cy=0.0,
            approach_z=5.0,
            bore_z=-10.0,
            nominal_diameter=25.0,
            probe_feed=300.0,
            retract_mm=2.0,
            safe_z=50.0,
            wcs_number=1,
            dialect="renishaw",
            var_cx=100,
            var_cy=101,
        )

    def test_macro_9814_present(self):
        r = self._result()
        assert "P9814" in r.gcode

    def test_g65_call(self):
        r = self._result()
        assert "G65" in r.gcode

    def test_diameter_in_macro_call(self):
        r = self._result()
        # D25.0 or D25 must appear in the O9814 call
        assert "D25" in r.gcode

    def test_four_measurement_points(self):
        r = self._result()
        assert len(r.measurement_points) == 4


# ---------------------------------------------------------------------------
# Web / pocket width — fanuc_g31
# ---------------------------------------------------------------------------

class TestWebPocketWidthFanuc:
    def _result(self, axis="X", width=30.0):
        return generate_web_pocket_width(
            cx=50.0, cy=25.0,
            probe_z=-5.0,
            axis=axis,
            nominal_width=width,
            probe_feed=300.0,
            retract_mm=2.0,
            safe_z=50.0,
            dialect="fanuc_g31",
            var_centre=110,
            var_width=112,
        )

    def test_two_g31_probes_x(self):
        r = self._result(axis="X")
        g31_lines = _g31_code_lines(r.gcode)
        assert len(g31_lines) == 2, (
            f"Web/pocket: expected 2 G31 probes, got {len(g31_lines)}"
        )

    def test_two_g31_probes_y(self):
        r = self._result(axis="Y")
        g31_lines = _g31_code_lines(r.gcode)
        assert len(g31_lines) == 2

    def test_opposing_walls_x(self):
        """X-axis: one probe in +X direction, one in -X."""
        r = self._result(axis="X", width=30.0)
        g31_x = _g31_code_lines(r.gcode, axis="X")
        assert len(g31_x) == 2
        # One must have X > cx=50, one must have X < cx=50
        vals = []
        for l in g31_x:
            m = re.search(r"X([-\d.]+)", l)
            if m:
                vals.append(float(m.group(1)))
        assert len(vals) == 2, f"Could not parse X values from: {g31_x}"
        assert max(vals) > 50.0 and min(vals) < 50.0, (
            f"Expected one probe > cx and one < cx, got {vals}"
        )

    def test_width_averaging_formula(self):
        r = self._result(axis="X")
        # Centre formula hi+lo/2
        assert "+#" in r.gcode and "/2" in r.gcode

    def test_two_measurement_points(self):
        r = self._result()
        assert len(r.measurement_points) == 2

    def test_measurement_point_positions_x(self):
        r = self._result(axis="X", width=30.0)
        half = 15.0
        labels = {mp.label: mp for mp in r.measurement_points}
        assert "wall_+X" in labels
        assert "wall_-X" in labels
        assert abs(labels["wall_+X"].x - (50.0 + half)) < 1e-6
        assert abs(labels["wall_-X"].x - (50.0 - half)) < 1e-6

    def test_probe_z_in_gcode(self):
        r = self._result()
        assert "Z-5.0" in r.gcode or "Z-5" in r.gcode

    def test_program_delimiters(self):
        r = self._result()
        assert r.gcode.strip().startswith("%")
        assert r.gcode.strip().endswith("%")


# ---------------------------------------------------------------------------
# Web / pocket width — renishaw
# ---------------------------------------------------------------------------

class TestWebPocketWidthRenishaw:
    def _result(self):
        return generate_web_pocket_width(
            cx=0.0, cy=0.0,
            probe_z=-5.0,
            axis="Y",
            nominal_width=20.0,
            probe_feed=300.0,
            retract_mm=2.0,
            safe_z=50.0,
            dialect="renishaw",
        )

    def test_macro_9815_present(self):
        r = self._result()
        assert "P9815" in r.gcode

    def test_g65_call(self):
        r = self._result()
        assert "G65" in r.gcode

    def test_two_measurement_points(self):
        r = self._result()
        assert len(r.measurement_points) == 2


# ---------------------------------------------------------------------------
# Tool-length set — fanuc_g31
# ---------------------------------------------------------------------------

class TestToolLengthSetFanuc:
    def _result(self):
        return generate_tool_length_set(
            tool_number=5,
            setter_x=200.0,
            setter_y=-100.0,
            approach_z=20.0,
            setter_z_nominal=5.0,
            probe_feed=200.0,
            retract_mm=2.0,
            safe_z=50.0,
            dialect="fanuc_g31",
            probe_z_var=120,
        )

    def test_g31_present(self):
        r = self._result()
        g31_lines = _g31_code_lines(r.gcode)
        assert len(g31_lines) >= 1

    def test_g10_l11_present(self):
        """Fanuc G10 L11 sets tool-length offset."""
        r = self._result()
        assert "G10" in r.gcode and "L11" in r.gcode

    def test_tool_number_in_g10(self):
        r = self._result()
        g10_lines = [l for l in r.gcode.splitlines() if "G10" in l and "L11" in l]
        assert len(g10_lines) >= 1
        assert "P5" in g10_lines[0], f"Tool number P5 not in G10: {g10_lines[0]!r}"

    def test_one_measurement_point(self):
        r = self._result()
        assert len(r.measurement_points) == 1
        assert r.measurement_points[0].direction == "-Z"

    def test_measurement_point_at_setter_xy(self):
        r = self._result()
        mp = r.measurement_points[0]
        assert abs(mp.x - 200.0) < 1e-6
        assert abs(mp.y - (-100.0)) < 1e-6

    def test_probe_feed_in_g31(self):
        r = self._result()
        g31_lines = _g31_code_lines(r.gcode)
        assert len(g31_lines) >= 1
        assert all("F" in l for l in g31_lines), "G31 missing F word"


# ---------------------------------------------------------------------------
# Tool-length set — renishaw
# ---------------------------------------------------------------------------

class TestToolLengthSetRenishaw:
    def _result(self):
        return generate_tool_length_set(
            tool_number=3,
            setter_x=0.0, setter_y=0.0,
            approach_z=50.0,
            setter_z_nominal=10.0,
            probe_feed=300.0,
            retract_mm=2.0,
            safe_z=50.0,
            dialect="renishaw",
            probe_z_var=120,
        )

    def test_macro_9823_present(self):
        r = self._result()
        assert "P9823" in r.gcode

    def test_g65_call(self):
        r = self._result()
        assert "G65" in r.gcode

    def test_tool_number_in_call(self):
        r = self._result()
        # T3 must appear in the macro call
        assert "T3" in r.gcode


# ---------------------------------------------------------------------------
# run_onmachine_probing dispatcher
# ---------------------------------------------------------------------------

class TestDispatcher:
    def test_bore_centre_find_dispatch(self):
        result = run_onmachine_probing({
            "feature_type": "bore_centre_find",
            "dialect": "fanuc_g31",
            "nominal_geometry": {
                "cx": 10.0, "cy": 20.0,
                "approach_z": 5.0, "bore_z": -12.0,
                "nominal_diameter": 24.0,
                "wcs_number": 1,
            },
            "probe_params": {
                "probe_feed_mm_min": 300.0,
                "retract_mm": 2.0,
                "safe_z_mm": 50.0,
            },
        })
        assert "gcode" in result
        assert "measurement_points" in result
        assert "wcs_update_logic" in result
        assert "honest_caveat" in result
        assert len(result["measurement_points"]) == 4

    def test_web_pocket_dispatch(self):
        result = run_onmachine_probing({
            "feature_type": "web_pocket_width",
            "dialect": "fanuc_g31",
            "nominal_geometry": {
                "cx": 0.0, "cy": 0.0,
                "probe_z": -5.0,
                "axis": "X",
                "nominal_width": 20.0,
            },
        })
        assert len(result["measurement_points"]) == 2

    def test_surface_measure_dispatch(self):
        result = run_onmachine_probing({
            "feature_type": "surface_measure",
            "dialect": "fanuc_g31",
            "nominal_geometry": {
                "x": 0.0, "y": 0.0,
                "z_approach": 5.0,
                "axis": "Z",
                "travel": -8.0,
                "wcs_number": 1,
            },
        })
        assert "G31" in result["gcode"]

    def test_tool_length_set_dispatch(self):
        result = run_onmachine_probing({
            "feature_type": "tool_length_set",
            "dialect": "fanuc_g31",
            "nominal_geometry": {
                "tool_number": 2,
                "setter_x": 300.0,
                "setter_y": -150.0,
                "approach_z": 30.0,
                "setter_z_nominal": 5.0,
            },
        })
        assert "G10" in result["gcode"]

    def test_boss_centre_find_dispatch(self):
        result = run_onmachine_probing({
            "feature_type": "boss_centre_find",
            "dialect": "fanuc_g31",
            "nominal_geometry": {
                "cx": 50.0, "cy": 50.0,
                "approach_z": 5.0, "bore_z": -5.0,
                "nominal_diameter": 40.0,
                "wcs_number": 2,
            },
        })
        assert len(result["measurement_points"]) == 4

    def test_invalid_feature_type_raises(self):
        with pytest.raises(ValueError, match="feature_type must be one of"):
            run_onmachine_probing({
                "feature_type": "invalid_type",
                "nominal_geometry": {},
            })

    def test_invalid_dialect_raises(self):
        with pytest.raises(ValueError, match="dialect must be one of"):
            run_onmachine_probing({
                "feature_type": "surface_measure",
                "dialect": "heidenhain",
                "nominal_geometry": {},
            })


# ---------------------------------------------------------------------------
# LLM tool handler (async)
# ---------------------------------------------------------------------------

class TestLLMHandler:
    def test_spec_name(self):
        assert cam_onmachine_probing_spec.name == "cam_onmachine_probing"

    def test_spec_has_required_feature_type(self):
        required = cam_onmachine_probing_spec.input_schema.get("required", [])
        assert "feature_type" in required

    def test_bore_centre_find_via_handler(self):
        args = json.dumps({
            "feature_type": "bore_centre_find",
            "dialect": "fanuc_g31",
            "nominal_geometry": {
                "cx": 0.0, "cy": 0.0,
                "approach_z": 5.0,
                "bore_z": -10.0,
                "nominal_diameter": 20.0,
                "wcs_number": 1,
            },
        }).encode()

        async def _run():
            return await run_cam_onmachine_probing(None, args)

        raw = asyncio.run(_run())
        result = json.loads(raw)
        assert "gcode" in result
        assert "G31" in result["gcode"]
        assert len(result["measurement_points"]) == 4

    def test_invalid_json_returns_error(self):
        async def _run():
            return await run_cam_onmachine_probing(None, b"not-json")

        raw = asyncio.run(_run())
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_feature_type_via_handler(self):
        args = json.dumps({
            "feature_type": "bogus",
            "nominal_geometry": {},
        }).encode()

        async def _run():
            return await run_cam_onmachine_probing(None, args)

        raw = asyncio.run(_run())
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_wcs_set_surface_via_handler(self):
        """WCS-set cycle writes G54 offset from probed datum."""
        args = json.dumps({
            "feature_type": "surface_measure",
            "dialect": "fanuc_g31",
            "nominal_geometry": {
                "x": 10.0, "y": 10.0,
                "z_approach": 5.0,
                "axis": "Z",
                "travel": -8.0,
                "wcs_number": 1,  # G54
                "offset_mm": 0.0,
            },
            "probe_params": {
                "probe_feed_mm_min": 300.0,
                "retract_mm": 2.0,
                "safe_z_mm": 50.0,
            },
        }).encode()

        async def _run():
            return await run_cam_onmachine_probing(None, args)

        raw = asyncio.run(_run())
        result = json.loads(raw)
        assert "gcode" in result
        gcode = result["gcode"]
        # G54 = P1
        assert "G10" in gcode and "L2" in gcode and "P1" in gcode, (
            "WCS-set cycle should write G10 L2 P1 (G54) to set Z datum"
        )
        # G31 must probe the Z surface
        assert "G31" in gcode

    def test_web_pocket_two_faces_via_handler(self):
        """Web/pocket width probes two opposing faces."""
        args = json.dumps({
            "feature_type": "web_pocket_width",
            "dialect": "fanuc_g31",
            "nominal_geometry": {
                "cx": 50.0, "cy": 0.0,
                "probe_z": -5.0,
                "axis": "X",
                "nominal_width": 30.0,
            },
        }).encode()

        async def _run():
            return await run_cam_onmachine_probing(None, args)

        raw = asyncio.run(_run())
        result = json.loads(raw)
        gcode = result["gcode"]
        g31_lines = _g31_code_lines(gcode, axis="X")
        assert len(g31_lines) == 2, (
            f"Expected 2 G31 X-probes for pocket width, got {len(g31_lines)}"
        )
        # Verify one is above cx=50 and one below
        vals = []
        for l in g31_lines:
            m = re.search(r"X([-\d.]+)", l)
            if m:
                vals.append(float(m.group(1)))
        assert max(vals) > 50.0
        assert min(vals) < 50.0

    def test_renishaw_bore_via_handler(self):
        """Renishaw dialect produces G65 P9814 macro call."""
        args = json.dumps({
            "feature_type": "bore_centre_find",
            "dialect": "renishaw",
            "nominal_geometry": {
                "cx": 0.0, "cy": 0.0,
                "approach_z": 5.0,
                "bore_z": -10.0,
                "nominal_diameter": 30.0,
                "wcs_number": 1,
            },
        }).encode()

        async def _run():
            return await run_cam_onmachine_probing(None, args)

        raw = asyncio.run(_run())
        result = json.loads(raw)
        gcode = result["gcode"]
        assert "G65" in gcode
        assert "P9814" in gcode


# ---------------------------------------------------------------------------
# G-code validity: no unmatched parentheses in comments
# ---------------------------------------------------------------------------

class TestGcodeValidity:
    def _check_parens(self, gcode: str):
        for line in gcode.splitlines():
            opens = line.count("(")
            closes = line.count(")")
            assert opens == closes, (
                f"Unmatched parentheses in G-code line: {line!r}"
            )

    def test_bore_gcode_valid_parens(self):
        r = generate_bore_centre_find(
            cx=0.0, cy=0.0, approach_z=5.0, bore_z=-10.0,
            nominal_diameter=20.0,
            probe_feed=300.0, retract_mm=2.0, safe_z=50.0,
            wcs_number=1, dialect="fanuc_g31",
        )
        self._check_parens(r.gcode)

    def test_surface_gcode_valid_parens(self):
        r = generate_surface_measure(
            x=0.0, y=0.0, z_approach=5.0, axis="Z", travel=-8.0,
            probe_feed=300.0, retract_mm=2.0, safe_z=50.0,
            wcs_number=1, offset_mm=0.0, dialect="fanuc_g31",
        )
        self._check_parens(r.gcode)

    def test_web_gcode_valid_parens(self):
        r = generate_web_pocket_width(
            cx=0.0, cy=0.0, probe_z=-5.0, axis="X",
            nominal_width=20.0,
            probe_feed=300.0, retract_mm=2.0, safe_z=50.0,
            dialect="fanuc_g31",
        )
        self._check_parens(r.gcode)

    def test_renishaw_bore_valid_parens(self):
        r = generate_bore_centre_find(
            cx=0.0, cy=0.0, approach_z=5.0, bore_z=-10.0,
            nominal_diameter=20.0,
            probe_feed=300.0, retract_mm=2.0, safe_z=50.0,
            wcs_number=1, dialect="renishaw",
        )
        self._check_parens(r.gcode)
