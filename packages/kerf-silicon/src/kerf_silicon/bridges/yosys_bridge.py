"""
Yosys synthesis subprocess bridge.

Public API
----------
synthesize(verilog_source, top_module, target) -> SynthResult

Writes a temp .v file + a Yosys script, shells out to ``yosys``, then parses
the JSON netlist produced by ``write_json``.

If ``yosys`` is not on PATH the function returns immediately with
``status="pending"`` (same sentinel pattern as kerf_fem.calculix_utils).

Targets
-------
generic : technology-independent (default gates: AND/OR/NOT/DFF)
sky130  : SkyWater SKY130 standard-cell library
ice40   : Lattice iCE40 FPGA (uses yosys synth_ice40)
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from kerf_silicon.bridges.netlist_parse import parse_netlist, NetlistAST

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability sentinel (mirrors kerf_fem.calculix_utils pattern)
# ---------------------------------------------------------------------------

_YOSYS_AVAILABLE: Optional[bool] = None

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

_VERILOG_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_module_name(name: str) -> str:
    """Validate *name* is a legal Verilog simple identifier.

    Returns the name unchanged on success.
    Raises ``ValueError`` with a descriptive message on failure.

    This is the primary injection-prevention guard: the module name is
    interpolated directly into the Yosys synthesis script, and Yosys supports
    a ``shell`` command — so an un-validated name is an RCE vector.
    """
    if not isinstance(name, str) or not _VERILOG_IDENT_RE.match(name):
        raise ValueError(
            f"Invalid top-level module name {name!r}: must match "
            r"^[A-Za-z_][A-Za-z0-9_]*$ (Verilog simple identifier)."
        )
    return name


def _yosys_available() -> bool:
    global _YOSYS_AVAILABLE
    if _YOSYS_AVAILABLE is None:
        _YOSYS_AVAILABLE = shutil.which("yosys") is not None
    return _YOSYS_AVAILABLE


ENGINE_PENDING_WARNING = (
    "Engine pending — Yosys not installed or not in PATH. "
    "Install via: brew install yosys  (macOS) or  apt install yosys  (Debian/Ubuntu)."
)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

Target = Literal["generic", "sky130", "ice40"]


@dataclass
class SynthResult:
    """Result of a Yosys synthesis run."""

    status: str  # "ok" | "pending" | "error"
    netlist: Optional[NetlistAST] = None
    netlist_json: Optional[dict[str, Any]] = None
    statistics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


# ---------------------------------------------------------------------------
# Yosys script builder
# ---------------------------------------------------------------------------

def _build_yosys_script(verilog_path: str, top_module: str, netlist_path: str,
                         target: Target) -> str:
    """Return a Yosys synthesis script as a single string.

    The script is passed via ``yosys -p '...'`` so each command is separated
    by semicolons.
    """
    steps: list[str] = [
        f"read_verilog {verilog_path}",
        f"hierarchy -top {top_module}",
        "proc",
        "opt",
    ]

    if target == "sky130":
        # Use the SKY130 technology mapping — requires PDK in YOSYS_DATDIR.
        # Fall back to generic techmap if PDK is not installed; the gate counts
        # will differ but the connectivity is valid.
        steps += [
            "techmap",
            "opt",
            "dfflibmap -liberty $YOSYS_DATDIR/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib || techmap",
        ]
    elif target == "ice40":
        # iCE40 synthesis — uses the synth_ice40 pass which handles ABC internally.
        steps = [
            f"read_verilog {verilog_path}",
            f"hierarchy -top {top_module}",
            "synth_ice40",
        ]
    else:
        # Generic: technology-independent standard-cell mapping.
        steps += [
            "techmap",
            "opt",
        ]

    steps.append(f"write_json {netlist_path}")
    return "; ".join(steps)


# ---------------------------------------------------------------------------
# Statistics extraction
# ---------------------------------------------------------------------------

def _extract_statistics(stdout: str, netlist_json: dict[str, Any]) -> dict[str, Any]:
    """Parse high-level cell counts from the JSON netlist."""
    stats: dict[str, Any] = {}

    modules = netlist_json.get("modules", {})
    total_cells = 0
    cell_counts: dict[str, int] = {}

    for mod_data in modules.values():
        for cell_data in mod_data.get("cells", {}).values():
            cell_type = cell_data.get("type", "unknown")
            cell_counts[cell_type] = cell_counts.get(cell_type, 0) + 1
            total_cells += 1

    stats["num_modules"] = len(modules)
    stats["num_cells"] = total_cells
    stats["cell_types"] = cell_counts

    # Try to extract area / gate-count lines from yosys stdout.
    for line in stdout.splitlines():
        line_lower = line.lower()
        if "number of cells" in line_lower:
            parts = line.strip().split()
            for i, p in enumerate(parts):
                if p.isdigit():
                    stats["reported_cell_count"] = int(p)
                    break
        elif "chip area" in line_lower or "total cell area" in line_lower:
            parts = line.strip().split()
            for p in reversed(parts):
                try:
                    stats["estimated_area"] = float(p)
                    break
                except ValueError:
                    pass

    return stats


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def synthesize(
    verilog_source: str,
    top_module: str,
    target: Target = "generic",
) -> SynthResult:
    """Synthesise *verilog_source* to a gate-level netlist via Yosys.

    Parameters
    ----------
    verilog_source:
        Raw Verilog (or SystemVerilog) source text.
    top_module:
        Name of the top-level module to elaborate.
    target:
        Technology target: ``"generic"`` | ``"sky130"`` | ``"ice40"``.

    Returns
    -------
    SynthResult
        ``status="pending"`` when Yosys is absent.
        ``status="ok"``      on success.
        ``status="error"``   when Yosys exits non-zero.
    """
    validate_module_name(top_module)

    if not _yosys_available():
        return SynthResult(
            status="pending",
            warnings=[ENGINE_PENDING_WARNING],
        )

    with tempfile.TemporaryDirectory(prefix="kerf_yosys_") as tmp:
        tmpdir = Path(tmp)
        verilog_path = tmpdir / "design.v"
        netlist_path = tmpdir / "netlist.json"

        verilog_path.write_text(verilog_source, encoding="utf-8")

        script = _build_yosys_script(
            str(verilog_path), top_module, str(netlist_path), target
        )

        try:
            proc = subprocess.run(
                ["yosys", "-p", script],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return SynthResult(
                status="error",
                errors=["Yosys timed out after 120 s"],
            )
        except OSError as exc:
            return SynthResult(
                status="error",
                errors=[f"Failed to launch yosys: {exc}"],
            )

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""

        if proc.returncode != 0:
            logger.warning("Yosys failed (rc=%d): %s", proc.returncode, stderr[:500])
            return SynthResult(
                status="error",
                errors=[f"Yosys exited with code {proc.returncode}", stderr[:2000]],
                stdout=stdout,
                stderr=stderr,
            )

        if not netlist_path.exists():
            return SynthResult(
                status="error",
                errors=["Yosys did not produce a netlist JSON file"],
                stdout=stdout,
                stderr=stderr,
            )

        try:
            netlist_json = json.loads(netlist_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return SynthResult(
                status="error",
                errors=[f"Failed to parse Yosys JSON netlist: {exc}"],
                stdout=stdout,
                stderr=stderr,
            )

        netlist_ast = parse_netlist(netlist_json)
        statistics = _extract_statistics(stdout, netlist_json)

        return SynthResult(
            status="ok",
            netlist=netlist_ast,
            netlist_json=netlist_json,
            statistics=statistics,
            stdout=stdout,
            stderr=stderr,
        )
