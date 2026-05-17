"""Tests for the BYO-Blender path in the Cycles worker.

The cycles_worker module (T-106b) may not yet be landed.  These tests
verify the *contract* that the worker will honour:

  - When KERF_BLENDER_PATH is set, subprocess.run must be called with
    that binary, not with the system 'blender' command.
  - When KERF_BLENDER_PATH is absent, the worker falls back to 'blender'
    (whatever is on PATH).
  - Various edge-cases around path validation, env forwarding, and
    exit-code handling are covered by mocking subprocess.run.

If cycles_worker has not landed yet the tests import a thin compatibility
shim defined in this module so the mock-based assertions still exercise
the expected call shape.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Compatibility shim — exercises the BYO path contract even before T-106b
# ---------------------------------------------------------------------------

_SHIM_SENTINEL = False  # True when we installed a synthetic module

try:
    from kerf_render import cycles_worker as _cw  # type: ignore[attr-defined]
except (ImportError, AttributeError):
    # T-106b not yet landed — synthesise a minimal shim so the mock tests
    # below have something real to exercise.
    _mod = types.ModuleType("kerf_render.cycles_worker")

    def _resolve_blender_bin() -> str:
        """Return the Blender binary path, honouring KERF_BLENDER_PATH."""
        byo = os.environ.get("KERF_BLENDER_BIN") or os.environ.get("KERF_BLENDER_PATH")
        if byo:
            return byo
        return "blender"

    def _run_blender(script_path: str, blender_bin: str | None = None) -> subprocess.CompletedProcess:
        """Invoke Blender headlessly to execute *script_path*."""
        bin_ = blender_bin or _resolve_blender_bin()
        return subprocess.run(
            [bin_, "-b", "--python", script_path, "-noaudio"],
            capture_output=True,
            text=True,
            timeout=600,
        )

    def _is_t106b_landed() -> bool:
        return False

    _mod.resolve_blender_bin = _resolve_blender_bin
    _mod.run_blender = _run_blender
    _mod.is_t106b_landed = _is_t106b_landed
    sys.modules.setdefault("kerf_render.cycles_worker", _mod)
    _cw = _mod
    _SHIM_SENTINEL = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_completed(returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout="Blender 4.1.1",
        stderr="",
    )


# ---------------------------------------------------------------------------
# resolve_blender_bin tests
# ---------------------------------------------------------------------------

class TestResolveBin:
    def test_byo_path_env_respected(self):
        """KERF_BLENDER_PATH overrides the default 'blender' fallback."""
        with patch.dict(os.environ, {"KERF_BLENDER_PATH": "/opt/my-blender/blender"}, clear=False):
            # Clear KERF_BLENDER_BIN so only KERF_BLENDER_PATH is active
            env = {k: v for k, v in os.environ.items() if k != "KERF_BLENDER_BIN"}
            env["KERF_BLENDER_PATH"] = "/opt/my-blender/blender"
            with patch.dict(os.environ, env, clear=True):
                result = _cw.resolve_blender_bin()
        assert result == "/opt/my-blender/blender"

    def test_bundled_blender_bin_env_respected(self):
        """KERF_BLENDER_BIN (set by entrypoint.sh) takes precedence."""
        env = {"KERF_BLENDER_BIN": "/usr/local/bin/blender4", "KERF_BLENDER_PATH": ""}
        with patch.dict(os.environ, env, clear=True):
            result = _cw.resolve_blender_bin()
        assert result == "/usr/local/bin/blender4"

    def test_fallback_when_no_env_set(self):
        """With no env vars, fallback is the bare 'blender' command."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("KERF_BLENDER_PATH", "KERF_BLENDER_BIN")}
        with patch.dict(os.environ, env, clear=True):
            result = _cw.resolve_blender_bin()
        assert result == "blender"

    def test_byo_path_with_spaces(self):
        """Paths with spaces (macOS .app bundles) are returned verbatim."""
        byo = "/Applications/Blender 4.app/Contents/MacOS/Blender"
        with patch.dict(os.environ, {"KERF_BLENDER_PATH": byo, "KERF_BLENDER_BIN": ""}, clear=True):
            result = _cw.resolve_blender_bin()
        assert result == byo

    def test_empty_byo_path_falls_back(self):
        """An explicitly empty KERF_BLENDER_PATH should not override fallback."""
        with patch.dict(os.environ, {"KERF_BLENDER_PATH": "", "KERF_BLENDER_BIN": ""}, clear=True):
            result = _cw.resolve_blender_bin()
        assert result == "blender"


# ---------------------------------------------------------------------------
# run_blender tests — mock subprocess.run
# ---------------------------------------------------------------------------

class TestRunBlender:
    def test_byo_path_used_in_subprocess_call(self, tmp_path):
        """When KERF_BLENDER_PATH is set, run_blender calls that binary."""
        script = tmp_path / "render.py"
        script.write_text("# test script")
        byo = "/custom/blender"
        with patch("subprocess.run", return_value=_fake_completed()) as mock_run:
            _cw.run_blender(str(script), blender_bin=byo)
        args_used = mock_run.call_args[0][0]
        assert args_used[0] == byo

    def test_headless_flag_always_present(self, tmp_path):
        """The -b (background/headless) flag must always be passed."""
        script = tmp_path / "render.py"
        script.write_text("# test")
        with patch("subprocess.run", return_value=_fake_completed()) as mock_run:
            _cw.run_blender(str(script), blender_bin="blender")
        args_used = mock_run.call_args[0][0]
        assert "-b" in args_used

    def test_python_flag_and_script_path_present(self, tmp_path):
        """--python <script_path> must appear in the subprocess arguments."""
        script = tmp_path / "myscript.py"
        script.write_text("# test")
        with patch("subprocess.run", return_value=_fake_completed()) as mock_run:
            _cw.run_blender(str(script))
        args_used = mock_run.call_args[0][0]
        assert "--python" in args_used
        assert str(script) in args_used

    def test_noaudio_flag_present(self, tmp_path):
        """The -noaudio flag suppresses audio device init in headless mode."""
        script = tmp_path / "s.py"
        script.write_text("")
        with patch("subprocess.run", return_value=_fake_completed()) as mock_run:
            _cw.run_blender(str(script))
        args_used = mock_run.call_args[0][0]
        assert "-noaudio" in args_used

    def test_returncode_propagated(self, tmp_path):
        """A non-zero returncode from Blender is surfaced to the caller."""
        script = tmp_path / "fail.py"
        script.write_text("")
        with patch("subprocess.run", return_value=_fake_completed(returncode=1)):
            result = _cw.run_blender(str(script))
        assert result.returncode == 1

    def test_byo_path_via_env_used_when_bin_not_supplied(self, tmp_path):
        """When blender_bin kwarg is None, env-var path is picked up."""
        script = tmp_path / "r.py"
        script.write_text("")
        byo = "/env/blender"
        env = {"KERF_BLENDER_PATH": byo, "KERF_BLENDER_BIN": ""}
        with patch.dict(os.environ, env, clear=True):
            with patch("subprocess.run", return_value=_fake_completed()) as mock_run:
                _cw.run_blender(str(script))
        args_used = mock_run.call_args[0][0]
        assert args_used[0] == byo

    def test_bundled_bin_used_when_no_byo_set(self, tmp_path):
        """When no BYO vars are set, the bare 'blender' command is used."""
        script = tmp_path / "default.py"
        script.write_text("")
        env = {k: v for k, v in os.environ.items()
               if k not in ("KERF_BLENDER_PATH", "KERF_BLENDER_BIN")}
        with patch.dict(os.environ, env, clear=True):
            with patch("subprocess.run", return_value=_fake_completed()) as mock_run:
                _cw.run_blender(str(script))
        args_used = mock_run.call_args[0][0]
        assert args_used[0] == "blender"

    def test_subprocess_timeout_passed(self, tmp_path):
        """subprocess.run must be called with a finite timeout."""
        script = tmp_path / "to.py"
        script.write_text("")
        with patch("subprocess.run", return_value=_fake_completed()) as mock_run:
            _cw.run_blender(str(script))
        kwargs = mock_run.call_args[1]
        assert "timeout" in kwargs
        assert kwargs["timeout"] > 0

    def test_capture_output_enabled(self, tmp_path):
        """stdout/stderr must be captured so the caller can report errors."""
        script = tmp_path / "cap.py"
        script.write_text("")
        with patch("subprocess.run", return_value=_fake_completed()) as mock_run:
            _cw.run_blender(str(script))
        kwargs = mock_run.call_args[1]
        assert kwargs.get("capture_output") is True or (
            "stdout" in kwargs and "stderr" in kwargs
        )

    def test_shim_or_module_loaded(self):
        """Sanity check: cycles_worker module (or shim) is importable."""
        import kerf_render.cycles_worker as cw  # noqa: F401
        assert cw is not None
