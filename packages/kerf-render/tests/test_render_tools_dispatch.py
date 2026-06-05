"""
test_render_tools_dispatch.py — hermetic TOOLS-list wiring test for kerf-render.

Verifies that kerf_render.tools exposes a TOOLS list with all 5 render tools,
and that the plugin loader's `hasattr(mod, "TOOLS")` check now succeeds.
"""
from __future__ import annotations

import pytest


def test_tools_list_present():
    from kerf_render import tools as m
    assert hasattr(m, "TOOLS"), "kerf_render.tools must expose a TOOLS list"
    assert len(m.TOOLS) == 5, f"expected 5 render tools, got {len(m.TOOLS)}"


def test_tools_list_names():
    from kerf_render import tools as m
    names = {t[0] for t in m.TOOLS}
    expected = {
        "create_render",
        "set_render_camera",
        "add_render_light",
        "set_render_material_override",
        "run_render",
    }
    assert names == expected, f"tool name mismatch: {names} != {expected}"


def test_tools_list_entries_shape():
    from kerf_render import tools as m
    for entry in m.TOOLS:
        name, spec, handler = entry
        assert isinstance(name, str) and name
        assert hasattr(spec, "name") and spec.name == name
        assert callable(handler)


def test_pathtrace_tool_module_registered_in_plugin():
    """The CPU path tracer's TOOLS module must be wired into the plugin's
    _TOOL_MODULES list so its tool actually gets registered."""
    from kerf_render import plugin
    assert "kerf_render.pathtrace_tools" in plugin._TOOL_MODULES


def test_pathtrace_tools_list():
    from kerf_render import pathtrace_tools as m
    assert hasattr(m, "TOOLS")
    names = {t[0] for t in m.TOOLS}
    assert "pathtrace_render_scene" in names
    for name, spec, handler in m.TOOLS:
        assert spec.name == name
        assert callable(handler)
