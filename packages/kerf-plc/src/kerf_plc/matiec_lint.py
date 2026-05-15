"""
MATIEC subprocess wrapper for IEC 61131-3 Structured Text lint.

`lint_st_source(source: str) -> list[Diagnostic]`

Runs the MATIEC `iec2c` binary against a temporary file, parses its stderr
output into structured diagnostics, and returns them.

MATIEC (GPLv3) is invoked as a **separate subprocess** — no in-process linking.
This subprocess boundary means the hosted service is not GPL-tainted.

Subprocess timeout: configurable via `MATIEC_TIMEOUT` env var; default 5 s.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple


# ── Diagnostic schema ─────────────────────────────────────────────────────────

class Diagnostic(NamedTuple):
    severity: str          # 'error' | 'warning' | 'info'
    message: str
    line: int | None = None
    column: int | None = None
    source: str = "matiec"


# ── MATIEC availability probe ─────────────────────────────────────────────────

def _matiec_binary() -> str | None:
    """Return the path to the MATIEC iec2c binary, or None if not found."""
    return shutil.which("iec2c")


# ── Stderr parser ─────────────────────────────────────────────────────────────

# MATIEC emits lines of the form:
#
#   file.st:12:5: error: message text
#   file.st:12:5: warning: message text
#
# The severity token is 'error', 'warning', or 'note'/'info'.
_DIAG_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<sev>error|warning|note|info):\s*(?P<msg>.+)$",
    re.IGNORECASE,
)

# MATIEC also emits unnamed bare error lines:
#   error: message text
_BARE_DIAG_RE = re.compile(
    r"^(?P<sev>error|warning|note|info):\s*(?P<msg>.+)$",
    re.IGNORECASE,
)


def _parse_stderr(stderr_text: str, src_filename: str) -> list[Diagnostic]:
    """
    Parse MATIEC stderr lines into Diagnostic objects.

    Lines that don't match the expected pattern are silently skipped (MATIEC
    emits spurious banner / info lines that are not diagnostics).
    """
    diagnostics: list[Diagnostic] = []
    for raw_line in stderr_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _DIAG_RE.match(line)
        if m:
            sev = m.group("sev").lower()
            if sev == "note":
                sev = "info"
            diagnostics.append(Diagnostic(
                severity=sev,
                message=m.group("msg").strip(),
                line=int(m.group("line")),
                column=int(m.group("col")),
                source="matiec",
            ))
            continue

        m2 = _BARE_DIAG_RE.match(line)
        if m2:
            sev = m2.group("sev").lower()
            if sev == "note":
                sev = "info"
            diagnostics.append(Diagnostic(
                severity=sev,
                message=m2.group("msg").strip(),
                source="matiec",
            ))

    return diagnostics


# ── Public entry point ────────────────────────────────────────────────────────

def lint_st_source(source: str) -> list[Diagnostic]:
    """
    Lint IEC 61131-3 Structured Text source via the MATIEC `iec2c` binary.

    Returns a list of Diagnostic objects.  When MATIEC is not installed,
    returns a single warning diagnostic rather than raising an exception so
    the FastAPI route always returns a valid response.
    """
    binary = _matiec_binary()
    if binary is None:
        return [Diagnostic(
            severity="warning",
            message=(
                "MATIEC not installed; lint disabled. "
                "Install with: apt install matiec  "
                "or build from https://github.com/thiagoralves/OpenPLC_v3/tree/master/utils/matiec_src"
            ),
            source="matiec",
        )]

    if not source or not source.strip():
        return []

    timeout = float(os.environ.get("MATIEC_TIMEOUT", "5"))

    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = Path(tmpdir) / "input.st"
        src_path.write_text(source, encoding="utf-8")

        try:
            result = subprocess.run(
                [binary, "-I", "/usr/share/matiec/lib", str(src_path)],
                cwd=tmpdir,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return [Diagnostic(
                severity="warning",
                message=f"MATIEC lint timed out after {timeout:.0f}s",
                source="matiec",
            )]
        except OSError as exc:
            return [Diagnostic(
                severity="warning",
                message=f"MATIEC could not be executed: {exc}",
                source="matiec",
            )]

        # MATIEC writes diagnostics to stderr; stdout is generated C code.
        stderr_text = result.stderr
        if isinstance(stderr_text, bytes):
            stderr_text = stderr_text.decode("utf-8", errors="replace")

        return _parse_stderr(stderr_text, str(src_path))
