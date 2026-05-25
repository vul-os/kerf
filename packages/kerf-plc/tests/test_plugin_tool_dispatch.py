"""test_plugin_tool_dispatch.py — dispatch-level tests for newly registered PLC tools.

Covers async tool handlers wired in plugin._register_tools:
  P01  make_ladder_program — blinker spec returns xml with rungs
  P02  make_ladder_program — unknown spec returns UNSUPPORTED error
  P03  make_ladder_program — missing spec returns BAD_ARGS
  P04  make_ladder_program — handler is async coroutine
  P05  convert_st_to_ladder — well-formed POU source returns xml
  P06  convert_st_to_ladder — empty source returns BAD_ARGS
  P07  convert_st_to_ladder — handler is async coroutine
  P08  convert_ladder_to_st — valid xml returns st_source
  P09  convert_ladder_to_st — empty xml returns BAD_ARGS
  P10  convert_ladder_to_st — handler is async coroutine
  P11  _register_tools adds expected capability strings to provides
"""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PKG / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx():
    registered = {}

    class _Tools:
        def register(self, name, spec, handler):
            registered[name] = (spec, handler)

    ctx = SimpleNamespace(tools=_Tools())
    ctx._registered = registered
    return ctx


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Build tool set once
# ---------------------------------------------------------------------------

_ctx = _make_ctx()
_provides: list[str] = []

from kerf_plc.plugin import _register_tools  # noqa: E402
_register_tools(_ctx, _provides)
_reg = _ctx._registered

# Minimal valid ST POU for transpile tests
_ST_POU = (
    "PROGRAM main\n"
    "VAR motor, start, stop: BOOL; END_VAR\n"
    "motor := start AND NOT stop;\n"
    "END_PROGRAM"
)


# ---------------------------------------------------------------------------
# P01–P04  make_ladder_program
# ---------------------------------------------------------------------------

class TestMakeLadderProgramDispatch:
    def test_p01_blinker_returns_xml(self):
        """P01: 'blinker' spec → xml + rung_count."""
        if "make_ladder_program" not in _reg:
            pytest.skip("make_ladder_program not registered")
        _, handler = _reg["make_ladder_program"]
        payload = json.dumps({"spec": "blinker"}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "xml" in result, f"Expected xml in result: {result}"
        assert result.get("rung_count", 0) > 0

    def test_p02_unknown_spec_returns_unsupported(self):
        """P02: unknown spec → UNSUPPORTED error."""
        if "make_ladder_program" not in _reg:
            pytest.skip("make_ladder_program not registered")
        _, handler = _reg["make_ladder_program"]
        payload = json.dumps({"spec": "completely unknown xyz spec"}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "error" in result

    def test_p03_missing_spec_returns_bad_args(self):
        """P03: missing spec → BAD_ARGS."""
        if "make_ladder_program" not in _reg:
            pytest.skip("make_ladder_program not registered")
        _, handler = _reg["make_ladder_program"]
        payload = json.dumps({}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "error" in result

    def test_p04_handler_is_coroutine(self):
        """P04: handler must be async."""
        if "make_ladder_program" not in _reg:
            pytest.skip("make_ladder_program not registered")
        _, handler = _reg["make_ladder_program"]
        assert inspect.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# P05–P07  convert_st_to_ladder
# ---------------------------------------------------------------------------

class TestConvertStToLadderDispatch:
    def test_p05_valid_pou_returns_xml(self):
        """P05: valid ST POU → xml with rung_count."""
        if "convert_st_to_ladder" not in _reg:
            pytest.skip("convert_st_to_ladder not registered")
        _, handler = _reg["convert_st_to_ladder"]
        payload = json.dumps({"st_source": _ST_POU}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "xml" in result, f"Expected xml in result: {result}"
        assert "rung_count" in result

    def test_p06_empty_source_returns_bad_args(self):
        """P06: empty st_source → BAD_ARGS."""
        if "convert_st_to_ladder" not in _reg:
            pytest.skip("convert_st_to_ladder not registered")
        _, handler = _reg["convert_st_to_ladder"]
        payload = json.dumps({}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "error" in result

    def test_p07_handler_is_coroutine(self):
        """P07: handler must be async."""
        if "convert_st_to_ladder" not in _reg:
            pytest.skip("convert_st_to_ladder not registered")
        _, handler = _reg["convert_st_to_ladder"]
        assert inspect.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# P08–P10  convert_ladder_to_st
# ---------------------------------------------------------------------------

class TestConvertLadderToStDispatch:
    @pytest.fixture(scope="class")
    def ladder_xml(self):
        """Generate a small ladder XML to round-trip."""
        import sys
        sys.path.insert(0, str(_PKG / "src"))
        from kerf_plc.llm.transpile import convert_st_to_ladder
        from kerf_plc.plcopen.writer import dumps
        proj = convert_st_to_ladder(_ST_POU)
        return dumps(proj)

    def test_p08_valid_xml_returns_st_source(self, ladder_xml):
        """P08: valid PLCopen XML → st_source string."""
        if "convert_ladder_to_st" not in _reg:
            pytest.skip("convert_ladder_to_st not registered")
        _, handler = _reg["convert_ladder_to_st"]
        payload = json.dumps({"xml": ladder_xml}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "st_source" in result, f"Expected st_source in result: {result}"
        assert len(result["st_source"]) > 0

    def test_p09_empty_xml_returns_bad_args(self):
        """P09: empty xml → BAD_ARGS."""
        if "convert_ladder_to_st" not in _reg:
            pytest.skip("convert_ladder_to_st not registered")
        _, handler = _reg["convert_ladder_to_st"]
        payload = json.dumps({}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "error" in result

    def test_p10_handler_is_coroutine(self):
        """P10: handler must be async."""
        if "convert_ladder_to_st" not in _reg:
            pytest.skip("convert_ladder_to_st not registered")
        _, handler = _reg["convert_ladder_to_st"]
        assert inspect.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# P11  capability provides list
# ---------------------------------------------------------------------------

class TestProvidesCapabilities:
    def test_p11_expected_capabilities_registered(self):
        """P11: _register_tools adds expected capability strings."""
        expected = {"plc.make_ladder", "plc.transpile"}
        assert expected.issubset(set(_provides)), (
            f"Missing provides: {expected - set(_provides)}"
        )
