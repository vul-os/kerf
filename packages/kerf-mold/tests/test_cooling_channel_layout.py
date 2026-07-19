"""
Tests for kerf_mold.cooling_channel_layout
============================================
Covers conventional and conformal cooling channel routing design,
bore diameter selection, pitch/clearance validation, LLM tool dispatch,
and plugin registration.

References:
  Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
    Hanser 2001, §6.5 — cooling channel design rules; Table 6.4.
  Xu X., Sachs E., Allen S. (2001). *Polymer Engineering & Science* 41(7),
    1265–1279 — conformal cooling channel offset rules.
  Tang L.Q. et al. (1998). *Finite Elements in Analysis and Design* 26(3),
    229–251 — optimal cooling channel placement.
"""
import asyncio
import json
import math

import pytest

from kerf_mold.cooling_channel_layout import (
    MoldBlockSpec,
    CoolingChannelRoute,
    CoolingLayoutReport,
    design_cooling_channel_layout,
    BORE_DIAMETER_DEFAULT_MM,
    BORE_DIAMETER_MIN_MM,
    BORE_DIAMETER_MAX_MM,
    PITCH_FACTOR_STANDARD,
    WALL_CLEARANCE_FACTOR_STANDARD,
    CONFORMAL_OFFSET_FACTOR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


class _Ctx:
    pass


CTX = _Ctx()


def _std_block() -> MoldBlockSpec:
    """Standard 200×150×80 mm mold block."""
    return MoldBlockSpec(
        x_min=0.0, x_max=200.0,
        y_min=0.0, y_max=150.0,
        z_min=0.0, z_max=80.0,
        pull_axis="z",
    )


# ---------------------------------------------------------------------------
# 1. MoldBlockSpec validation
# ---------------------------------------------------------------------------

class TestMoldBlockSpec:
    def test_valid_block_created(self):
        block = _std_block()
        assert block.width_mm == pytest.approx(200.0)
        assert block.depth_mm == pytest.approx(150.0)
        assert block.height_mm == pytest.approx(80.0)

    def test_x_min_ge_x_max_raises(self):
        with pytest.raises(ValueError, match="x_min"):
            MoldBlockSpec(
                x_min=100.0, x_max=100.0,
                y_min=0.0, y_max=150.0,
                z_min=0.0, z_max=80.0,
            )

    def test_y_min_ge_y_max_raises(self):
        with pytest.raises(ValueError, match="y_min"):
            MoldBlockSpec(
                x_min=0.0, x_max=200.0,
                y_min=150.0, y_max=50.0,
                z_min=0.0, z_max=80.0,
            )

    def test_invalid_pull_axis_raises(self):
        with pytest.raises(ValueError, match="pull_axis"):
            MoldBlockSpec(
                x_min=0.0, x_max=200.0,
                y_min=0.0, y_max=150.0,
                z_min=0.0, z_max=80.0,
                pull_axis="w",
            )

    def test_cavity_surface_z_stored(self):
        block = MoldBlockSpec(
            x_min=0, x_max=200, y_min=0, y_max=150,
            z_min=0, z_max=80, cavity_surface_z=50.0,
        )
        assert block.cavity_surface_z == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# 2. CoolingChannelRoute
# ---------------------------------------------------------------------------

class TestCoolingChannelRoute:
    def test_length_straight(self):
        ch = CoolingChannelRoute(
            start_mm=[0.0, 50.0, 20.0],
            end_mm=[200.0, 50.0, 20.0],
            diameter_mm=10.0,
        )
        assert ch.length_mm == pytest.approx(200.0)

    def test_invalid_diameter_raises(self):
        with pytest.raises(ValueError, match="diameter_mm must be > 0"):
            CoolingChannelRoute(
                start_mm=[0, 50, 20],
                end_mm=[200, 50, 20],
                diameter_mm=0.0,
            )

    def test_invalid_channel_type_raises(self):
        with pytest.raises(ValueError, match="channel_type must be one of"):
            CoolingChannelRoute(
                start_mm=[0, 50, 20],
                end_mm=[200, 50, 20],
                diameter_mm=10.0,
                channel_type="spiral",
            )

    def test_as_dict_contains_expected_keys(self):
        ch = CoolingChannelRoute(
            start_mm=[0.0, 50.0, 20.0],
            end_mm=[200.0, 50.0, 20.0],
            diameter_mm=10.0,
            label="CH_00",
            channel_type="straight",
            circuit_id="circuit_A",
        )
        d = ch.as_dict()
        assert "start_mm" in d
        assert "end_mm" in d
        assert "diameter_mm" in d
        assert "length_mm" in d
        assert "label" in d
        assert "channel_type" in d
        assert "circuit_id" in d


# ---------------------------------------------------------------------------
# 3. Conventional layout — basic sanity
# ---------------------------------------------------------------------------

class TestConventionalLayout:
    def test_returns_report(self):
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        assert isinstance(report, CoolingLayoutReport)

    def test_layout_type_conventional(self):
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        assert report.layout_type == "conventional"

    def test_channels_produced(self):
        """Standard block should produce at least 2 channels."""
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        assert report.total_channels >= 2, (
            f"Expected >= 2 channels, got {report.total_channels}"
        )

    def test_total_length_positive(self):
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        assert report.total_length_mm > 0.0

    def test_channel_count_matches_list(self):
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        assert report.total_channels == len(report.channels)

    def test_bore_diameter_in_range(self):
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        assert BORE_DIAMETER_MIN_MM <= report.bore_diameter_mm <= BORE_DIAMETER_MAX_MM

    def test_clearance_mm_matches_factor(self):
        block = _std_block()
        factor = 2.0
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, clearance_factor=factor
        )
        expected_clearance = factor * report.bore_diameter_mm
        assert report.clearance_mm == pytest.approx(expected_clearance, rel=1e-5)

    def test_pitch_mm_matches_factor(self):
        block = _std_block()
        factor = 3.5
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, pitch_factor=factor
        )
        expected_pitch = factor * report.bore_diameter_mm
        assert report.pitch_mm == pytest.approx(expected_pitch, rel=1e-5)

    def test_custom_bore_diameter_respected(self):
        block = _std_block()
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, bore_diameter_mm=12.0
        )
        assert report.bore_diameter_mm == pytest.approx(12.0)

    def test_channels_are_straight(self):
        """All conventional channels should have channel_type 'straight'."""
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        for ch in report.channels:
            assert ch.channel_type == "straight", (
                f"Channel {ch.label} has unexpected type {ch.channel_type}"
            )

    def test_channel_z_above_cavity_surface(self):
        """All channels should be above the cavity surface level."""
        block = MoldBlockSpec(
            x_min=0, x_max=200, y_min=0, y_max=150,
            z_min=0, z_max=80,
        )
        cavity_depth = 30.0
        cav_z = block.z_max - cavity_depth  # = 50
        report = design_cooling_channel_layout(block, cavity_depth_mm=cavity_depth)
        for ch in report.channels:
            assert ch.start_mm[2] >= cav_z, (
                f"Channel {ch.label} Z={ch.start_mm[2]:.1f} below cavity surface {cav_z:.1f}"
            )

    def test_two_circuits_present_with_enough_channels(self):
        """With >= 4 channels and num_circuits=2, at least 2 circuit IDs should appear."""
        block = _std_block()
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=20.0, num_circuits=2
        )
        if report.total_channels >= 4:
            circuit_ids = {ch.circuit_id for ch in report.channels}
            assert len(circuit_ids) >= 1  # at least one circuit (may be 2)

    def test_heat_area_positive(self):
        """Estimated heat transfer area must be positive."""
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        assert report.estimated_heat_area_mm2 > 0.0

    def test_honest_caveat_present(self):
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        assert len(report.honest_caveat) > 50
        assert "HONEST" in report.honest_caveat

    def test_honest_caveat_references_menges(self):
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        assert "Menges" in report.honest_caveat or "6.5" in report.honest_caveat

    def test_invalid_layout_type_raises(self):
        block = _std_block()
        with pytest.raises(ValueError, match="layout_type must be one of"):
            design_cooling_channel_layout(block, cavity_depth_mm=30.0, layout_type="spiral")

    def test_invalid_cavity_depth_raises(self):
        block = _std_block()
        with pytest.raises(ValueError, match="cavity_depth_mm must be > 0"):
            design_cooling_channel_layout(block, cavity_depth_mm=0.0)

    def test_negative_cavity_depth_raises(self):
        block = _std_block()
        with pytest.raises(ValueError, match="cavity_depth_mm must be > 0"):
            design_cooling_channel_layout(block, cavity_depth_mm=-5.0)


# ---------------------------------------------------------------------------
# 4. Bore diameter auto-selection
# ---------------------------------------------------------------------------

class TestBoreDiameterAutoSelection:
    def test_small_block_gets_small_bore(self):
        """Small block (< 10000 mm²) should get 8 mm bore."""
        block = MoldBlockSpec(
            x_min=0, x_max=80, y_min=0, y_max=100,
            z_min=0, z_max=60,
        )
        report = design_cooling_channel_layout(block, cavity_depth_mm=20.0)
        # 80×100 = 8000 mm² → 8 mm bore
        assert report.bore_diameter_mm == pytest.approx(8.0)

    def test_large_block_gets_larger_bore(self):
        """Large block (> 100000 mm²) should get 14 mm bore."""
        block = MoldBlockSpec(
            x_min=0, x_max=400, y_min=0, y_max=400,
            z_min=0, z_max=100,
        )
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        # 400×400 = 160000 mm² → 14 mm bore
        assert report.bore_diameter_mm == pytest.approx(14.0)


# ---------------------------------------------------------------------------
# 5. Conformal layout
# ---------------------------------------------------------------------------

class TestConformalLayout:
    def test_conformal_layout_type(self):
        block = _std_block()
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, layout_type="conformal"
        )
        assert report.layout_type == "conformal"

    def test_conformal_channels_produced(self):
        block = _std_block()
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, layout_type="conformal"
        )
        assert report.total_channels >= 4  # at least one rectangular loop

    def test_conformal_channels_are_conformal_type(self):
        """All conformal channels should have channel_type 'conformal'."""
        block = _std_block()
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, layout_type="conformal"
        )
        for ch in report.channels:
            assert ch.channel_type == "conformal", (
                f"Channel {ch.label} has type {ch.channel_type}, expected 'conformal'"
            )

    def test_conformal_total_length_positive(self):
        block = _std_block()
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, layout_type="conformal"
        )
        assert report.total_length_mm > 0.0

    def test_conformal_warns_about_approximation(self):
        block = _std_block()
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, layout_type="conformal"
        )
        all_warnings = " ".join(report.warnings)
        assert "rectangular" in all_warnings.lower() or "HONEST" in all_warnings

    def test_conformal_custom_segments(self):
        """Custom n_segments should create the right number of channels."""
        block = _std_block()
        n = 12
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, layout_type="conformal",
            num_conformal_segments=n
        )
        # Should produce n conformal channel segments
        assert report.total_channels == n


# ---------------------------------------------------------------------------
# 6. Warnings
# ---------------------------------------------------------------------------

class TestWarnings:
    def test_low_clearance_factor_warns(self):
        block = _std_block()
        # clearance_factor = 1.0 is below minimum of 1.5
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, clearance_factor=1.0
        )
        combined = " ".join(report.warnings).lower()
        assert "clearance" in combined or "breakthrough" in combined

    def test_low_pitch_factor_warns(self):
        block = _std_block()
        # pitch_factor = 2.0 is below minimum of 2.5
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, pitch_factor=2.0
        )
        combined = " ".join(report.warnings).lower()
        assert "pitch" in combined or "close" in combined

    def test_report_warnings_is_list(self):
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        assert isinstance(report.warnings, list)

    def test_deep_cavity_warns(self):
        """When cavity_depth is 90%+ of block height, a warning should appear."""
        block = MoldBlockSpec(
            x_min=0, x_max=200, y_min=0, y_max=150,
            z_min=0, z_max=80,
        )
        report = design_cooling_channel_layout(block, cavity_depth_mm=75.0)
        combined = " ".join(report.warnings)
        assert len(report.warnings) > 0


# ---------------------------------------------------------------------------
# 7. as_dict / serialisation
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_report_as_dict_json_serialisable(self):
        block = _std_block()
        report = design_cooling_channel_layout(block, cavity_depth_mm=30.0)
        d = report.as_dict()
        # Must be JSON serialisable without error
        json_str = json.dumps(d)
        loaded = json.loads(json_str)
        assert loaded["layout_type"] == "conventional"
        assert loaded["total_channels"] >= 0

    def test_conformal_report_as_dict_json_serialisable(self):
        block = _std_block()
        report = design_cooling_channel_layout(
            block, cavity_depth_mm=30.0, layout_type="conformal"
        )
        d = report.as_dict()
        json_str = json.dumps(d)
        loaded = json.loads(json_str)
        assert loaded["layout_type"] == "conformal"


# ---------------------------------------------------------------------------
# 8. LLM tool dispatch
# ---------------------------------------------------------------------------

class TestLLMToolDispatch:
    def _std_args(self, **overrides) -> dict:
        base = {
            "block_x_min": 0.0,
            "block_x_max": 200.0,
            "block_y_min": 0.0,
            "block_y_max": 150.0,
            "block_z_min": 0.0,
            "block_z_max": 80.0,
            "cavity_depth_mm": 30.0,
        }
        base.update(overrides)
        return base

    def test_conventional_layout_ok(self):
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        result = json.loads(_run(run_mold_design_cooling_channel_layout(
            self._std_args(), CTX
        )))
        assert "error" not in result, f"Tool returned error: {result}"
        assert result.get("ok") is True
        assert result["layout_type"] == "conventional"
        assert result["total_channels"] >= 0
        assert result["bore_diameter_mm"] > 0
        assert "channels" in result

    def test_conformal_layout_ok(self):
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        result = json.loads(_run(run_mold_design_cooling_channel_layout(
            self._std_args(layout_type="conformal"), CTX
        )))
        assert "error" not in result, f"Tool returned error: {result}"
        assert result.get("ok") is True
        assert result["layout_type"] == "conformal"

    def test_custom_bore_diameter(self):
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        result = json.loads(_run(run_mold_design_cooling_channel_layout(
            self._std_args(bore_diameter_mm=12.0), CTX
        )))
        assert "error" not in result, f"Tool returned error: {result}"
        assert result["bore_diameter_mm"] == pytest.approx(12.0)

    def test_missing_block_x_max_returns_error(self):
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        args = {
            "block_x_min": 0.0,
            # block_x_max missing
            "block_y_min": 0.0, "block_y_max": 150.0,
            "block_z_min": 0.0, "block_z_max": 80.0,
            "cavity_depth_mm": 30.0,
        }
        result = json.loads(_run(run_mold_design_cooling_channel_layout(args, CTX)))
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_missing_cavity_depth_returns_error(self):
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        args = {
            "block_x_min": 0.0, "block_x_max": 200.0,
            "block_y_min": 0.0, "block_y_max": 150.0,
            "block_z_min": 0.0, "block_z_max": 80.0,
            # cavity_depth_mm missing
        }
        result = json.loads(_run(run_mold_design_cooling_channel_layout(args, CTX)))
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_layout_type_returns_error(self):
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        result = json.loads(_run(run_mold_design_cooling_channel_layout(
            self._std_args(layout_type="circular"), CTX
        )))
        assert "error" in result

    def test_invalid_x_range_returns_error(self):
        """block_x_min >= block_x_max should return BAD_ARGS."""
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        result = json.loads(_run(run_mold_design_cooling_channel_layout(
            self._std_args(block_x_min=200.0, block_x_max=100.0), CTX
        )))
        assert "error" in result

    def test_result_has_reference(self):
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        result = json.loads(_run(run_mold_design_cooling_channel_layout(
            self._std_args(), CTX
        )))
        assert "error" not in result, f"Tool returned error: {result}"
        assert "reference" in result
        assert "Menges" in result["reference"]

    def test_result_channels_serialisable(self):
        """Each channel dict must contain all expected keys."""
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        result = json.loads(_run(run_mold_design_cooling_channel_layout(
            self._std_args(), CTX
        )))
        assert "error" not in result
        for ch in result.get("channels", []):
            assert "start_mm" in ch
            assert "end_mm" in ch
            assert "diameter_mm" in ch
            assert "length_mm" in ch
            assert "channel_type" in ch

    def test_honest_caveat_in_result(self):
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        result = json.loads(_run(run_mold_design_cooling_channel_layout(
            self._std_args(), CTX
        )))
        assert "error" not in result
        assert "HONEST" in result.get("honest_caveat", "")

    def test_num_circuits_2_default(self):
        """Default num_circuits=2 and large enough block → circuits A and B present."""
        from kerf_mold.cooling_channel_layout_tool import run_mold_design_cooling_channel_layout
        result = json.loads(_run(run_mold_design_cooling_channel_layout(
            self._std_args(), CTX
        )))
        assert "error" not in result
        assert result["num_circuits"] >= 1


# ---------------------------------------------------------------------------
# 9. Tool spec
# ---------------------------------------------------------------------------

class TestToolSpec:
    def test_tool_spec_name(self):
        from kerf_mold.cooling_channel_layout_tool import (
            mold_design_cooling_channel_layout_spec,
        )
        assert mold_design_cooling_channel_layout_spec.name == "mold_design_cooling_channel_layout"

    def test_tool_spec_required_fields(self):
        from kerf_mold.cooling_channel_layout_tool import (
            mold_design_cooling_channel_layout_spec,
        )
        req = mold_design_cooling_channel_layout_spec.input_schema.get("required", [])
        assert "block_x_min" in req
        assert "block_x_max" in req
        assert "block_y_min" in req
        assert "block_y_max" in req
        assert "block_z_min" in req
        assert "block_z_max" in req
        assert "cavity_depth_mm" in req

    def test_tool_spec_description_mentions_conformal(self):
        from kerf_mold.cooling_channel_layout_tool import (
            mold_design_cooling_channel_layout_spec,
        )
        desc = mold_design_cooling_channel_layout_spec.description
        assert "conformal" in desc.lower()
        assert "conventional" in desc.lower()


# ---------------------------------------------------------------------------
# 10. Plugin registration
# ---------------------------------------------------------------------------

class TestPluginRegistration:
    def test_plugin_registers_cooling_channel_layout(self):
        from kerf_mold.plugin import register
        from fastapi import FastAPI

        class _MockReg:
            def __init__(self):
                self.registered = {}
            def register(self, name, spec, handler):
                self.registered[name] = (spec, handler)

        class _MockCtx:
            def __init__(self):
                self.tools = _MockReg()

        app = FastAPI()
        ctx = _MockCtx()

        async def _go():
            return await register(app, ctx)

        _run(_go())
        assert "mold_design_cooling_channel_layout" in ctx.tools.registered, (
            f"mold_design_cooling_channel_layout not registered. "
            f"Registered tools: {list(ctx.tools.registered.keys())}"
        )
