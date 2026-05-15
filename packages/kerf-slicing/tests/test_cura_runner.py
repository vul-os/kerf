"""
tests/test_cura_runner.py — hermetic tests for cura_runner.py.

Strategy:
  - When CuraEngine is not on PATH (CI default), tests assert the graceful-
    degradation path (CuraEngineNotInstalledError).
  - The happy path is exercised via a fake CuraEngine subprocess (a small
    Python script that writes a minimal G-code file to the path given in -o).
  - Settings serialisation is tested without subprocess invocation.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest.mock as mock
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Minimal fake G-code
# ---------------------------------------------------------------------------

FAKE_GCODE = textwrap.dedent("""\
    ;FLAVOR:Marlin
    ;TIME:3742
    ;Filament used: 2.85m
    ;LAYER_COUNT:120
    ;Layer height: 0.2
    G28 ; home all axes
    G1 Z5 F5000 ; lift nozzle
    ;LAYER:0
    G1 X50 Y50 E0.1 F3000
    G1 X60 Y50 E0.2
    ;LAYER:1
    G1 X50 Y50 E0.3
""")

MINIMAL_STL = textwrap.dedent("""\
    solid minimal
    facet normal 0 0 1
      outer loop
        vertex 0 0 0
        vertex 1 0 0
        vertex 0 1 0
      endloop
    endfacet
    endsolid minimal
""")


# ---------------------------------------------------------------------------
# T1 — graceful degradation when CuraEngine is absent
# ---------------------------------------------------------------------------

class TestNoCuraEngine:
    def test_missing_binary_raises_not_installed(self, monkeypatch):
        """When CuraEngine is not on PATH, raises CuraEngineNotInstalledError."""
        monkeypatch.setattr("shutil.which", lambda name: None)
        # Force re-import so the probe runs fresh
        sys.modules.pop("kerf_slicing.cura_runner", None)

        from kerf_slicing.cura_runner import CuraEngineNotInstalledError, run_cura_slice

        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            f.write(MINIMAL_STL.encode())
            stl = f.name
        try:
            with pytest.raises(CuraEngineNotInstalledError):
                run_cura_slice(stl)
        finally:
            os.unlink(stl)

    def test_missing_stl_raises_file_not_found(self, monkeypatch, tmp_path):
        """FileNotFoundError before the binary check when STL is absent."""
        sys.modules.pop("kerf_slicing.cura_runner", None)
        from kerf_slicing.cura_runner import run_cura_slice

        with pytest.raises(FileNotFoundError):
            run_cura_slice(str(tmp_path / "nonexistent.stl"))


# ---------------------------------------------------------------------------
# T2 — settings serialisation
# ---------------------------------------------------------------------------

class TestSettingsSerialisation:
    def setup_method(self):
        sys.modules.pop("kerf_slicing.cura_runner", None)

    def test_known_keys_are_mapped(self):
        from kerf_slicing.cura_runner import _build_cura_args

        args = _build_cura_args({
            "layer_height": 0.2,
            "infill_density": 20,
            "perimeters": 3,
            "retraction_enabled": True,
            "print_temperature": 200,
            "bed_temperature": 60,
        })

        pairs = {args[i + 1]: args[i + 2]
                 for i in range(0, len(args), 3)
                 if args[i] == "-s"}
        # infill_density → infill_sparse_density
        assert "infill_sparse_density=20" in args
        assert "layer_height=0.2" in args
        assert "wall_line_count=3" in args
        assert "retraction_enable=True" in args
        assert "material_print_temperature=200" in args
        assert "material_bed_temperature=60" in args

    def test_unknown_keys_pass_through(self):
        from kerf_slicing.cura_runner import _build_cura_args

        args = _build_cura_args({"my_custom_setting": "42"})
        assert "my_custom_setting=42" in args

    def test_empty_settings_produce_no_s_flags(self):
        from kerf_slicing.cura_runner import _build_cura_args

        assert _build_cura_args({}) == []


# ---------------------------------------------------------------------------
# T3 — G-code metadata parsers
# ---------------------------------------------------------------------------

class TestGcodeMetadataParsers:
    def setup_method(self):
        sys.modules.pop("kerf_slicing.cura_runner", None)

    def test_parse_layer_count_from_comment(self):
        from kerf_slicing.cura_runner import _parse_layer_count

        warnings: list[str] = []
        assert _parse_layer_count(FAKE_GCODE, warnings) == 120
        assert warnings == []

    def test_parse_layer_count_fallback_to_layer_lines(self):
        from kerf_slicing.cura_runner import _parse_layer_count

        gcode = ";LAYER:0\n;LAYER:1\n;LAYER:2\n"
        warnings: list[str] = []
        assert _parse_layer_count(gcode, warnings) == 3

    def test_parse_layer_count_warns_when_missing(self):
        from kerf_slicing.cura_runner import _parse_layer_count

        warnings: list[str] = []
        _parse_layer_count("; no layers here\n", warnings)
        assert len(warnings) == 1
        assert "layer count" in warnings[0].lower()

    def test_parse_print_time(self):
        from kerf_slicing.cura_runner import _parse_print_time

        assert _parse_print_time(FAKE_GCODE) == 3742

    def test_parse_print_time_missing(self):
        from kerf_slicing.cura_runner import _parse_print_time

        assert _parse_print_time("; no time comment\n") is None

    def test_parse_filament(self):
        from kerf_slicing.cura_runner import _parse_filament

        # "2.85m" in the comment — only digits+dot parsed, so None since unit is attached
        # Let's also test a bare-number variant
        from kerf_slicing.cura_runner import _parse_filament
        gcode_bare = ";Filament used: 1234.5\n"
        assert _parse_filament(gcode_bare) == pytest.approx(1234.5)

    def test_parse_filament_missing(self):
        from kerf_slicing.cura_runner import _parse_filament

        assert _parse_filament("; nothing here\n") is None


# ---------------------------------------------------------------------------
# T4 — happy-path with fake CuraEngine subprocess
# ---------------------------------------------------------------------------

class TestFakeCuraEngine:
    """
    Write a small Python-based fake CuraEngine script, make it executable,
    and verify the full run_cura_slice() path processes it correctly.
    """

    @pytest.fixture(autouse=True)
    def fake_cura(self, tmp_path, monkeypatch):
        """Create a fake CuraEngine script that writes minimal G-code."""
        fake_bin = tmp_path / "CuraEngine"
        fake_bin.write_text(
            textwrap.dedent(f"""\
                #!/usr/bin/env python3
                import sys, os

                args = sys.argv[1:]
                # Find -o argument
                try:
                    o_idx = args.index('-o')
                    out_path = args[o_idx + 1]
                except (ValueError, IndexError):
                    sys.exit(1)

                gcode = {FAKE_GCODE!r}
                with open(out_path, 'w') as f:
                    f.write(gcode)
                sys.exit(0)
            """)
        )
        fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC)

        # Patch shutil.which to return our fake binary
        monkeypatch.setattr(
            "shutil.which",
            lambda name: str(fake_bin) if name in ("CuraEngine", "curaengine") else None,
        )
        sys.modules.pop("kerf_slicing.cura_runner", None)

    def _make_stl(self, tmp_path: Path) -> Path:
        stl = tmp_path / "test.stl"
        stl.write_text(MINIMAL_STL)
        return stl

    def test_happy_path_returns_slice_result(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice

        stl = self._make_stl(tmp_path)
        result = run_cura_slice(str(stl), {"layer_height": 0.2, "infill_density": 20})

        assert result.gcode is not None
        assert ";LAYER_COUNT:120" in result.gcode
        assert result.layer_count == 120
        assert result.print_time_s == 3742
        assert result.gcode_bytes > 0

    def test_empty_settings_accepted(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice

        stl = self._make_stl(tmp_path)
        result = run_cura_slice(str(stl))
        assert result.layer_count == 120

    def test_gcode_is_string(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice

        stl = self._make_stl(tmp_path)
        result = run_cura_slice(str(stl))
        assert isinstance(result.gcode, str)

    def test_warnings_list_present(self, tmp_path):
        from kerf_slicing.cura_runner import run_cura_slice

        stl = self._make_stl(tmp_path)
        result = run_cura_slice(str(stl))
        assert isinstance(result.warnings, list)


# ---------------------------------------------------------------------------
# T5 — cura engine error propagation
# ---------------------------------------------------------------------------

class TestCuraEngineErrors:
    @pytest.fixture(autouse=True)
    def fake_cura_failing(self, tmp_path, monkeypatch):
        """Create a fake CuraEngine that exits non-zero."""
        fake_bin = tmp_path / "CuraEngine"
        fake_bin.write_text(
            textwrap.dedent("""\
                #!/usr/bin/env python3
                import sys
                print("ERROR: mesh is broken", file=sys.stderr)
                sys.exit(1)
            """)
        )
        fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setattr(
            "shutil.which",
            lambda name: str(fake_bin) if name in ("CuraEngine", "curaengine") else None,
        )
        sys.modules.pop("kerf_slicing.cura_runner", None)

    def test_nonzero_exit_raises_cura_engine_error(self, tmp_path):
        from kerf_slicing.cura_runner import CuraEngineError, run_cura_slice

        stl = tmp_path / "bad.stl"
        stl.write_text(MINIMAL_STL)
        with pytest.raises(CuraEngineError) as exc_info:
            run_cura_slice(str(stl))
        assert "exited 1" in str(exc_info.value)
