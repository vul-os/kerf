"""
Tests for kerf_silicon.bridges.yosys_bridge.

Coverage:
  1. subprocess.run is called with the expected argv shape (``yosys -p '...'``).
  2. A successful run parses and returns a SynthResult with status="ok".
  3. Yosys absent → status="pending" with the engine-pending warning.
  4. Non-zero return code → status="error".
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Sample Yosys JSON netlist (half-adder, generic target).
# Produced by: yosys -p "read_verilog ha.v; hierarchy -top half_adder;
#               proc; opt; techmap; opt; write_json ha.json"
# Trimmed to the fields actually used by parse_netlist.
# ---------------------------------------------------------------------------
_HALF_ADDER_JSON: dict = {
    "creator": "Yosys 0.38 (git sha1 abcdef01)",
    "modules": {
        "half_adder": {
            "ports": {
                "a": {"direction": "input",  "bits": [2]},
                "b": {"direction": "input",  "bits": [3]},
                "s": {"direction": "output", "bits": [4]},
                "c": {"direction": "output", "bits": [5]},
            },
            "cells": {
                "$xor$ha.v$1": {
                    "type": "$_XOR_",
                    "parameters": {},
                    "attributes": {"src": "ha.v:6"},
                    "connections": {
                        "A": [2],
                        "B": [3],
                        "Y": [4],
                    },
                },
                "$and$ha.v$2": {
                    "type": "$_AND_",
                    "parameters": {},
                    "attributes": {"src": "ha.v:7"},
                    "connections": {
                        "A": [2],
                        "B": [3],
                        "Y": [5],
                    },
                },
            },
            "netnames": {
                "a": {"bits": [2], "hide_name": 0},
                "b": {"bits": [3], "hide_name": 0},
                "s": {"bits": [4], "hide_name": 0},
                "c": {"bits": [5], "hide_name": 0},
            },
        }
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completed_process(returncode: int = 0,
                             stdout: str = "Yosys 0.38\nDone.",
                             stderr: str = "") -> subprocess.CompletedProcess:
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


# ---------------------------------------------------------------------------
# 1. subprocess.run argv shape
# ---------------------------------------------------------------------------

class TestSubprocessArgv:
    """Yosys must be called as: yosys -p '<script>'"""

    def _run_with_mock(self, monkeypatch, target="generic"):
        from kerf_silicon.bridges import yosys_bridge as yb

        # Ensure yosys looks available.
        monkeypatch.setattr(yb, "_YOSYS_AVAILABLE", True)

        captured: list = []

        def fake_run(args, **kwargs):
            captured.append(args)
            # Write a fake netlist.json into the temp dir so the bridge doesn't
            # complain about a missing file.
            import re
            script = args[2]
            m = re.search(r"write_json\s+(\S+)", script)
            if m:
                Path(m.group(1)).write_text(
                    json.dumps(_HALF_ADDER_JSON), encoding="utf-8"
                )
            return _make_completed_process()

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = yb.synthesize("module half_adder(); endmodule", "half_adder", target)
        return result, captured

    def test_argv_starts_with_yosys_minus_p(self, monkeypatch):
        _, captured = self._run_with_mock(monkeypatch)
        assert captured, "subprocess.run was never called"
        argv = captured[0]
        assert argv[0] == "yosys", f"Expected 'yosys' as first arg, got {argv[0]!r}"
        assert argv[1] == "-p", f"Expected '-p' as second arg, got {argv[1]!r}"

    def test_script_contains_read_verilog(self, monkeypatch):
        _, captured = self._run_with_mock(monkeypatch)
        script = captured[0][2]
        assert "read_verilog" in script

    def test_script_contains_hierarchy_top(self, monkeypatch):
        _, captured = self._run_with_mock(monkeypatch)
        script = captured[0][2]
        assert "hierarchy -top half_adder" in script

    def test_script_contains_write_json(self, monkeypatch):
        _, captured = self._run_with_mock(monkeypatch)
        script = captured[0][2]
        assert "write_json" in script

    def test_script_contains_proc_opt(self, monkeypatch):
        _, captured = self._run_with_mock(monkeypatch)
        script = captured[0][2]
        assert "proc" in script
        assert "opt" in script

    def test_script_contains_techmap_for_generic(self, monkeypatch):
        _, captured = self._run_with_mock(monkeypatch, target="generic")
        script = captured[0][2]
        assert "techmap" in script

    def test_ice40_uses_synth_ice40(self, monkeypatch):
        _, captured = self._run_with_mock(monkeypatch, target="ice40")
        script = captured[0][2]
        assert "synth_ice40" in script

    def test_result_status_ok_on_success(self, monkeypatch):
        result, _ = self._run_with_mock(monkeypatch)
        assert result.status == "ok", f"Expected status='ok', got {result.status!r}"


# ---------------------------------------------------------------------------
# 2. Successful run → SynthResult fields
# ---------------------------------------------------------------------------

class TestSuccessfulRun:
    """When yosys succeeds, SynthResult should be fully populated."""

    def _run_success(self, monkeypatch):
        from kerf_silicon.bridges import yosys_bridge as yb

        monkeypatch.setattr(yb, "_YOSYS_AVAILABLE", True)

        import re

        def fake_run(args, **kwargs):
            script = args[2]
            m = re.search(r"write_json\s+(\S+)", script)
            if m:
                Path(m.group(1)).write_text(
                    json.dumps(_HALF_ADDER_JSON), encoding="utf-8"
                )
            return _make_completed_process(
                stdout="Number of cells:  2\nDone."
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        return yb.synthesize(
            "module half_adder(input a, b, output s, c); endmodule",
            "half_adder",
        )

    def test_status_ok(self, monkeypatch):
        result = self._run_success(monkeypatch)
        assert result.status == "ok"

    def test_netlist_present(self, monkeypatch):
        result = self._run_success(monkeypatch)
        assert result.netlist is not None

    def test_netlist_json_present(self, monkeypatch):
        result = self._run_success(monkeypatch)
        assert result.netlist_json is not None
        assert "modules" in result.netlist_json

    def test_statistics_num_cells(self, monkeypatch):
        result = self._run_success(monkeypatch)
        assert result.statistics.get("num_cells") == 2

    def test_statistics_num_modules(self, monkeypatch):
        result = self._run_success(monkeypatch)
        assert result.statistics.get("num_modules") == 1

    def test_statistics_cell_types(self, monkeypatch):
        result = self._run_success(monkeypatch)
        ct = result.statistics.get("cell_types", {})
        assert "$_XOR_" in ct
        assert "$_AND_" in ct

    def test_netlist_module_count(self, monkeypatch):
        result = self._run_success(monkeypatch)
        assert len(result.netlist.modules) == 1

    def test_netlist_cell_count(self, monkeypatch):
        result = self._run_success(monkeypatch)
        mod = result.netlist.modules[0]
        assert len(mod.cells) == 2

    def test_netlist_port_count(self, monkeypatch):
        result = self._run_success(monkeypatch)
        mod = result.netlist.modules[0]
        assert len(mod.ports) == 4  # a, b, s, c


# ---------------------------------------------------------------------------
# 3. Yosys absent → pending sentinel
# ---------------------------------------------------------------------------

class TestPendingWhenYosysAbsent:
    """With yosys absent the bridge must return status='pending'."""

    def test_pending_status(self, monkeypatch):
        from kerf_silicon.bridges import yosys_bridge as yb

        monkeypatch.setattr(yb, "_YOSYS_AVAILABLE", None)
        monkeypatch.setattr(shutil, "which", lambda _: None)

        result = yb.synthesize("module top(); endmodule", "top")
        assert result.status == "pending"

    def test_pending_warning_message(self, monkeypatch):
        from kerf_silicon.bridges import yosys_bridge as yb

        monkeypatch.setattr(yb, "_YOSYS_AVAILABLE", None)
        monkeypatch.setattr(shutil, "which", lambda _: None)

        result = yb.synthesize("module top(); endmodule", "top")
        assert result.warnings, "Expected at least one warning for pending state"
        assert any("yosys" in w.lower() for w in result.warnings), (
            f"Expected 'yosys' in warning text, got: {result.warnings}"
        )

    def test_pending_no_netlist(self, monkeypatch):
        from kerf_silicon.bridges import yosys_bridge as yb

        monkeypatch.setattr(yb, "_YOSYS_AVAILABLE", None)
        monkeypatch.setattr(shutil, "which", lambda _: None)

        result = yb.synthesize("module top(); endmodule", "top")
        assert result.netlist is None

    def test_cached_sentinel_respected(self, monkeypatch):
        """_YOSYS_AVAILABLE=False (cached) must also return pending."""
        from kerf_silicon.bridges import yosys_bridge as yb

        monkeypatch.setattr(yb, "_YOSYS_AVAILABLE", False)

        result = yb.synthesize("module top(); endmodule", "top")
        assert result.status == "pending"


# ---------------------------------------------------------------------------
# 4. Non-zero exit code → error
# ---------------------------------------------------------------------------

class TestErrorOnNonZeroExit:
    def test_error_status(self, monkeypatch):
        from kerf_silicon.bridges import yosys_bridge as yb

        monkeypatch.setattr(yb, "_YOSYS_AVAILABLE", True)

        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_completed_process(
                returncode=1, stderr="ERROR: syntax error"
            ),
        )

        result = yb.synthesize("bad verilog @@@@", "top")
        assert result.status == "error"

    def test_error_contains_stderr(self, monkeypatch):
        from kerf_silicon.bridges import yosys_bridge as yb

        monkeypatch.setattr(yb, "_YOSYS_AVAILABLE", True)

        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_completed_process(
                returncode=1, stderr="ERROR: syntax error in design.v"
            ),
        )

        result = yb.synthesize("bad verilog @@@@", "top")
        assert result.errors, "Expected error list to be non-empty"
        combined = " ".join(result.errors)
        assert "1" in combined or "error" in combined.lower()


# ---------------------------------------------------------------------------
# 5. Integration smoke test (skipped when yosys absent)
# ---------------------------------------------------------------------------

_needs_yosys = pytest.mark.skipif(
    shutil.which("yosys") is None,
    reason="yosys not installed or not in PATH",
)


@_needs_yosys
def test_real_yosys_half_adder():
    """End-to-end: synthesise a real half-adder and check cell counts."""
    from kerf_silicon.bridges.yosys_bridge import synthesize

    src = """
module half_adder(input a, input b, output s, output c);
  assign s = a ^ b;
  assign c = a & b;
endmodule
"""
    result = synthesize(src, "half_adder", target="generic")
    assert result.status == "ok", f"Synthesis failed: {result.errors}"
    assert result.netlist is not None
    assert len(result.netlist.modules) >= 1
    mod = result.netlist.modules[0]
    assert len(mod.cells) >= 1
    assert result.statistics["num_cells"] >= 1
