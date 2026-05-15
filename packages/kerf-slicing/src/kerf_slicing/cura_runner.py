"""
CuraEngine subprocess wrapper.

Invokes `CuraEngine slice` as a child process — the subprocess boundary keeps
the hosted service MIT-compatible even though CuraEngine itself is AGPLv3.
See README.md for the full licensing rationale.

CuraEngine 5.x CLI shape (verified against Ultimaker/CuraEngine 5.x docs):

    CuraEngine slice \\
        -j <printer-profile.json>  \\
        -s <key>=<value> ...       \\
        -l <stl-path>              \\
        -o <output.gcode>

The `-s` flag sets per-setting overrides on top of the base profile JSON.
CuraEngine emits progress/info to stderr and G-code to the `-o` file.
It also embeds metadata comments in the G-code:
  ;TIME:<seconds>          — estimated print time in seconds
  ;Filament used: <mm>     — filament used in mm
  ;LAYER_COUNT:<n>         — total number of layers

Surprising nuances:
  - CuraEngine 5.x requires at least one `-j <profile>` argument; it refuses
    to run with `-s` flags alone. We write a minimal "empty" profile JSON
    (just `{ "settings": {} }`) so the overrides can be applied cleanly.
  - The binary may be called `CuraEngine` (capital C) on Linux/macOS or
    `CuraEngine.exe` on Windows. We try `CuraEngine` first, then
    `curaengine` (lowercase), matching common package manager installs.
  - Slice time for a typical 50-triangle STL is ~2 s; for a 1 M-face mesh
    it can reach the 60 s timeout. The timeout is generous but bounded.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple


# ── public exceptions ─────────────────────────────────────────────────────────

class CuraEngineNotInstalledError(RuntimeError):
    """Raised when the CuraEngine binary is not found on PATH."""

class CuraEngineError(RuntimeError):
    """Raised when CuraEngine exits with a non-zero status."""


# ── result type ───────────────────────────────────────────────────────────────

class SliceResult(NamedTuple):
    gcode: str                # full G-code string
    layer_count: int          # parsed from ;LAYER_COUNT: comment
    print_time_s: int | None  # seconds, parsed from ;TIME: comment
    filament_mm: float | None # mm, parsed from ;Filament used: comment
    gcode_bytes: int          # len(gcode.encode())
    warnings: list[str]


# ── capability probe ──────────────────────────────────────────────────────────

def _cura_binary() -> str | None:
    """Return the full path to the first CuraEngine binary found on PATH, or None."""
    for name in ("CuraEngine", "curaengine"):
        found = shutil.which(name)
        if found:
            return found
    return None


# ── settings serialisation ────────────────────────────────────────────────────

# Kerf setting key → CuraEngine setting key mapping.
# CuraEngine 5.x uses snake_case keys that mostly match our API, but a few
# differ (e.g. "perimeters" → "wall_line_count").
_SETTING_MAP: dict[str, str] = {
    "layer_height":        "layer_height",
    "infill_density":      "infill_sparse_density",
    "perimeters":          "wall_line_count",
    "retraction_enabled":  "retraction_enable",
    "print_temperature":   "material_print_temperature",
    "bed_temperature":     "material_bed_temperature",
}


def _build_cura_args(settings: dict) -> list[str]:
    """
    Convert a Kerf settings dict to a list of `-s key=value` CLI fragments.

    Unknown keys are passed through unchanged (allows advanced overrides).
    """
    args: list[str] = []
    for kerf_key, value in settings.items():
        cura_key = _SETTING_MAP.get(kerf_key, kerf_key)
        args += ["-s", f"{cura_key}={value}"]
    return args


# ── minimal base profile ──────────────────────────────────────────────────────

_MINIMAL_PROFILE = json.dumps({"settings": {}})


# ── main entry point ──────────────────────────────────────────────────────────

def run_cura_slice(stl_path: str | Path, settings: dict | None = None) -> SliceResult:
    """
    Slice an STL file with CuraEngine and return the result.

    Parameters
    ----------
    stl_path:
        Absolute path to the input STL file.
    settings:
        Dict of Kerf slicing settings (layer_height, infill_density, …).
        Values are serialised as strings for the `-s key=value` CLI flags.

    Raises
    ------
    CuraEngineNotInstalledError
        When CuraEngine is not on PATH.
    CuraEngineError
        When CuraEngine exits with a non-zero status.
    FileNotFoundError
        When stl_path does not exist.
    """
    stl_path = Path(stl_path)
    if not stl_path.exists():
        raise FileNotFoundError(str(stl_path))

    binary = _cura_binary()
    if binary is None:
        raise CuraEngineNotInstalledError(
            "CuraEngine not found. Install it and ensure it is on PATH. "
            "Ubuntu/Debian: apt-get install cura-engine  "
            "macOS: brew install curaengine"
        )

    settings = settings or {}
    warnings: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        profile_path = Path(tmpdir) / "profile.json"
        profile_path.write_text(_MINIMAL_PROFILE, encoding="utf-8")
        gcode_path = Path(tmpdir) / "output.gcode"

        cmd = [
            binary, "slice",
            "-j", str(profile_path),
            *_build_cura_args(settings),
            "-l", str(stl_path),
            "-o", str(gcode_path),
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            raise CuraEngineError("CuraEngine timed out after 60 s")

        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "")[-800:]
            raise CuraEngineError(
                f"CuraEngine exited {proc.returncode}. stderr: {stderr_tail}"
            )

        if not gcode_path.exists():
            raise CuraEngineError("CuraEngine exited 0 but produced no G-code file")

        gcode = gcode_path.read_text(encoding="utf-8", errors="replace")

    # ── parse metadata from G-code comments ──────────────────────────────────
    layer_count = _parse_layer_count(gcode, warnings)
    print_time_s = _parse_print_time(gcode)
    filament_mm = _parse_filament(gcode)

    return SliceResult(
        gcode=gcode,
        layer_count=layer_count,
        print_time_s=print_time_s,
        filament_mm=filament_mm,
        gcode_bytes=len(gcode.encode()),
        warnings=warnings,
    )


# ── G-code metadata parsers ───────────────────────────────────────────────────

def _parse_layer_count(gcode: str, warnings: list[str]) -> int:
    """Extract ;LAYER_COUNT:<n> from G-code header comments."""
    m = re.search(r"^;LAYER_COUNT:(\d+)", gcode, re.MULTILINE)
    if m:
        return int(m.group(1))
    # Fallback: count ;LAYER: lines
    count = len(re.findall(r"^;LAYER:\d+", gcode, re.MULTILINE))
    if count == 0:
        warnings.append("Could not determine layer count from G-code")
    return count


def _parse_print_time(gcode: str) -> int | None:
    """Extract ;TIME:<seconds> from G-code header (CuraEngine 5.x)."""
    m = re.search(r"^;TIME:(\d+)", gcode, re.MULTILINE)
    if m:
        return int(m.group(1))
    return None


def _parse_filament(gcode: str) -> float | None:
    """Extract 'Filament used: <mm>mm' from G-code header."""
    m = re.search(r"^;Filament used:\s*([\d.]+)", gcode, re.MULTILINE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None
