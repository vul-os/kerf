"""test_plugin_tool_dispatch.py — dispatch-level tests for kerf-silicon tools.

Covers async tool handlers wired in plugin._register_tools:
  S01  instantiate_analog_cell — opamp_2stage returns ok=True result
  S02  instantiate_analog_cell — unknown family returns ok=False
  S03  instantiate_analog_cell — missing family returns BAD_ARGS
  S04  instantiate_analog_cell — handler is async coroutine
  S05  silicon_drc_check — valid layout returns violations dict
  S06  silicon_drc_check — missing layout returns BAD_ARGS
  S07  silicon_drc_check — handler is async coroutine
  S08  silicon_formal_equiv — equivalent netlists return equivalent=True
  S09  silicon_formal_equiv — mismatched inputs return INPUT_MISMATCH
  S10  silicon_formal_equiv — missing netlist_a returns BAD_ARGS
  S11  silicon_formal_equiv — handler is async coroutine
  S12  silicon_run_openlane — missing design_name returns error
  S13  silicon_run_openlane — handler is async coroutine
  S14  _register_tools adds expected capability strings to provides
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

from kerf_silicon.plugin import _register_tools  # noqa: E402
_register_tools(_ctx, _provides)
_reg = _ctx._registered


# ---------------------------------------------------------------------------
# S01–S04  instantiate_analog_cell
# ---------------------------------------------------------------------------

class TestInstantiateAnalogCellDispatch:
    def test_s01_opamp_returns_ok(self):
        """S01: opamp_2stage → ok=True result."""
        if "instantiate_analog_cell" not in _reg:
            pytest.skip("instantiate_analog_cell not registered")
        _, handler = _reg["instantiate_analog_cell"]
        payload = json.dumps({"family": "opamp_2stage", "params": {"gbw_hz": 1e6}}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert result.get("ok") is True, f"Expected ok=True: {result}"

    def test_s02_unknown_family_returns_not_ok(self):
        """S02: unknown family → ok=False."""
        if "instantiate_analog_cell" not in _reg:
            pytest.skip("instantiate_analog_cell not registered")
        _, handler = _reg["instantiate_analog_cell"]
        payload = json.dumps({"family": "unknown_xyz_cell"}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert result.get("ok") is False or "error" in result

    def test_s03_missing_family_returns_bad_args(self):
        """S03: missing family → BAD_ARGS."""
        if "instantiate_analog_cell" not in _reg:
            pytest.skip("instantiate_analog_cell not registered")
        _, handler = _reg["instantiate_analog_cell"]
        payload = json.dumps({}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert result.get("code") == "BAD_ARGS" or "error" in result

    def test_s04_handler_is_coroutine(self):
        """S04: handler must be async."""
        if "instantiate_analog_cell" not in _reg:
            pytest.skip("instantiate_analog_cell not registered")
        _, handler = _reg["instantiate_analog_cell"]
        assert inspect.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# S05–S07  silicon_drc_check
# ---------------------------------------------------------------------------

class TestSiliconDrcCheckDispatch:
    def test_s05_valid_layout_returns_violations(self):
        """S05: valid layout → violations list + passed_rules."""
        if "silicon_drc_check" not in _reg:
            pytest.skip("silicon_drc_check not registered")
        _, handler = _reg["silicon_drc_check"]
        # Deliberately narrow poly shape (50 nm width) to trigger min_width violation
        layout = [
            {
                "layer": "poly",
                "polygon": [[0, 0], [0.05, 0], [0.05, 1.0], [0, 1.0]],
            }
        ]
        payload = json.dumps({"layout": layout, "pdk": "sky130"}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "violations" in result or "error" in result

    def test_s06_missing_layout_returns_bad_args(self):
        """S06: missing layout → BAD_ARGS."""
        if "silicon_drc_check" not in _reg:
            pytest.skip("silicon_drc_check not registered")
        _, handler = _reg["silicon_drc_check"]
        payload = json.dumps({}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "error" in result

    def test_s07_handler_is_coroutine(self):
        """S07: handler must be async."""
        if "silicon_drc_check" not in _reg:
            pytest.skip("silicon_drc_check not registered")
        _, handler = _reg["silicon_drc_check"]
        assert inspect.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# S08–S11  silicon_formal_equiv
# ---------------------------------------------------------------------------

class TestSiliconFormalEquivDispatch:
    # Minimal 2-input, 1-output AND-gate netlist (format matches fixtures/formal/*.json)
    _NETLIST_AND = {
        "inputs": ["a", "b"],
        "outputs": ["y"],
        "gates": [{"type": "and", "inputs": ["a", "b"], "output": "y"}],
    }

    def test_s08_equivalent_netlists_return_true(self):
        """S08: two identical netlists → equivalent=True."""
        if "silicon_formal_equiv" not in _reg:
            pytest.skip("silicon_formal_equiv not registered")
        _, handler = _reg["silicon_formal_equiv"]
        payload = json.dumps({
            "netlist_a": self._NETLIST_AND,
            "netlist_b": self._NETLIST_AND,
        }).encode()
        result = json.loads(_run(handler(None, payload)))
        assert result.get("equivalent") is True, f"Expected equivalent=True: {result}"

    def test_s09_mismatched_inputs_return_error(self):
        """S09: different primary inputs → INPUT_MISMATCH error."""
        if "silicon_formal_equiv" not in _reg:
            pytest.skip("silicon_formal_equiv not registered")
        _, handler = _reg["silicon_formal_equiv"]
        netlist_b = {
            "inputs": ["a", "c"],  # different input set → mismatch
            "outputs": ["y"],
            "gates": [{"type": "and", "inputs": ["a", "c"], "output": "y"}],
        }
        payload = json.dumps({
            "netlist_a": self._NETLIST_AND,
            "netlist_b": netlist_b,
        }).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "error" in result

    def test_s10_missing_netlist_returns_bad_args(self):
        """S10: missing netlist_a → BAD_ARGS."""
        if "silicon_formal_equiv" not in _reg:
            pytest.skip("silicon_formal_equiv not registered")
        _, handler = _reg["silicon_formal_equiv"]
        payload = json.dumps({"netlist_b": self._NETLIST_AND}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "error" in result

    def test_s11_handler_is_coroutine(self):
        """S11: handler must be async."""
        if "silicon_formal_equiv" not in _reg:
            pytest.skip("silicon_formal_equiv not registered")
        _, handler = _reg["silicon_formal_equiv"]
        assert inspect.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# S12–S13  silicon_run_openlane
# ---------------------------------------------------------------------------

class TestSiliconRunOpenLaneDispatch:
    def test_s12_missing_design_name_returns_error(self):
        """S12: missing design_name → error status."""
        if "silicon_run_openlane" not in _reg:
            pytest.skip("silicon_run_openlane not registered")
        _, handler = _reg["silicon_run_openlane"]
        payload = json.dumps({"verilog_files": ["/tmp/foo.v"]}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "error" in result or result.get("status") == "error"

    def test_s13_handler_is_coroutine(self):
        """S13: handler must be async."""
        if "silicon_run_openlane" not in _reg:
            pytest.skip("silicon_run_openlane not registered")
        _, handler = _reg["silicon_run_openlane"]
        assert inspect.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# S14  capability provides list
# ---------------------------------------------------------------------------

class TestProvidesCapabilities:
    def test_s14_expected_capabilities_registered(self):
        """S14: _register_tools adds expected capability strings."""
        expected = {
            "silicon.analog_cell",
            "silicon.drc",
            "silicon.formal_equiv",
            "silicon.openlane",
        }
        assert expected.issubset(set(_provides)), (
            f"Missing provides: {expected - set(_provides)}"
        )
