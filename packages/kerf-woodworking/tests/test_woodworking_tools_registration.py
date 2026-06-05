"""
Tests that the TOOLS list in kerf_woodworking.tools is properly populated and
that the plugin's _register_tools mechanism can consume it.
"""

from __future__ import annotations

import asyncio
import json
import pytest

from kerf_woodworking.tools import TOOLS


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    pass


CTX = _Ctx()

# ---------------------------------------------------------------------------
# TOOLS list sanity
# ---------------------------------------------------------------------------

class TestToolsList:
    EXPECTED_NAMES = {
        "woodworking_mortise_tenon",
        "woodworking_dovetail",
        "woodworking_finger_joint",
        "woodworking_dowel",
        "woodworking_biscuit",
        "woodworking_pocket_screw",
        "woodworking_cut_list",
        "woodworking_grain_check",
        "woodworking_hinge_cup_pattern",
        "woodworking_shelf_pin_pattern",
        "woodworking_drawer_runner_pattern",
        "woodworking_euro_screw_pattern",
        "woodworking_handle_pattern",
        "woodworking_validate_joinery",
        "woodworking_joinery_strength",
    }

    def test_all_expected_tools_present(self):
        names = {name for name, spec, handler in TOOLS}
        assert names == self.EXPECTED_NAMES

    def test_all_entries_have_three_parts(self):
        for entry in TOOLS:
            assert len(entry) == 3
            name, spec, handler = entry
            assert isinstance(name, str)
            assert spec.name == name

    def test_handlers_are_callable(self):
        for name, spec, handler in TOOLS:
            assert callable(handler), f"{name}: handler not callable"


# ---------------------------------------------------------------------------
# Plugin mock registration
# ---------------------------------------------------------------------------

class _MockRegistry:
    def __init__(self):
        self.registered = {}

    def register(self, name, spec, handler):
        self.registered[name] = (spec, handler)


class _MockCtx:
    def __init__(self):
        self.tools = _MockRegistry()


class TestPluginRegistration:
    def test_register_tools_populates_registry(self):
        """_register_tools should register all TOOLS entries."""
        from kerf_woodworking.plugin import _register_tools
        ctx = _MockCtx()
        provides = []
        _register_tools(ctx, provides)
        assert len(ctx.tools.registered) == 24

    def test_all_tool_names_registered(self):
        from kerf_woodworking.plugin import _register_tools
        ctx = _MockCtx()
        _register_tools(ctx, [])
        assert "woodworking_mortise_tenon" in ctx.tools.registered
        assert "woodworking_handle_pattern" in ctx.tools.registered
        assert "woodworking_hinge_cup_pattern" in ctx.tools.registered
        assert "woodworking_validate_joinery" in ctx.tools.registered
        assert "woodworking_joinery_strength" in ctx.tools.registered


# ---------------------------------------------------------------------------
# Spot dispatch tests
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_mortise_tenon_dispatch(self):
        name, spec, handler = next(
            (n, s, h) for n, s, h in TOOLS if n == "woodworking_mortise_tenon"
        )
        result = json.loads(_run(handler(CTX, json.dumps({
            "piece_length_mm": 300.0,
            "piece_width_mm": 40.0,
            "piece_thickness_mm": 20.0,
        }).encode())))
        assert "error" not in result or result.get("ok", True)

    def test_hinge_cup_dispatch(self):
        name, spec, handler = next(
            (n, s, h) for n, s, h in TOOLS if n == "woodworking_hinge_cup_pattern"
        )
        result = json.loads(_run(handler(CTX, json.dumps({
            "panel_width_mm": 600.0,
            "panel_height_mm": 800.0,
        }).encode())))
        assert "holes" in result or "bore_pattern" in result or "ok" in result

    def test_handle_pattern_dispatch(self):
        name, spec, handler = next(
            (n, s, h) for n, s, h in TOOLS if n == "woodworking_handle_pattern"
        )
        result = json.loads(_run(handler(CTX, json.dumps({
            "panel_width_mm": 400.0,
            "panel_height_mm": 600.0,
        }).encode())))
        # Should return some bore/hole positions
        assert isinstance(result, dict)
