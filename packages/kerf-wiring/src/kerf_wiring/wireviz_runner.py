"""
WireViz YAML → SVG renderer.

WireViz (GPLv3+) is an optional dependency.  If it is not installed this
module still loads; run_wireviz() returns a graceful warning instead of
raising an ImportError so the FastAPI route stays up regardless.

WireViz API surface (v0.4+):
  - wireviz.Harness — main object
    .connectors  dict[name, Connector]
    .cables      dict[name, Cable]
    .add_connector(name, **kwargs)
    .add_cable(name **kwargs)
    .connect(from_connector, from_pin, cable, wire_index, to_connector, to_pin)
    .create_graph() → None  (builds graphviz source internally)
    .svg()          → str   (rendered SVG string)
  - wireviz.parse_file(filename) → Harness  (YAML → Harness)

  As of WireViz 0.4 the canonical entry point for YAML input is
  wireviz.parse_file(path) or the lower-level wireviz.Harness.from_yaml().
  We use a temp-file round-trip because the public API accepts a file path,
  not a string directly.

Surprising nuances discovered during implementation:
  - `Harness.svg()` was added in 0.4; older 0.3.x only writes files via
    `Harness.output(...)`.  We try both.
  - `create_graph()` must be called before svg() / output().
  - Color codes and pin counts are validated at parse time; malformed YAML
    produces a WireVizError (subclass of Exception) with a descriptive msg.
"""
from __future__ import annotations

import io
import tempfile
import textwrap
from pathlib import Path
from typing import NamedTuple


class WireVizResult(NamedTuple):
    svg: str | None
    warnings: list[str]


# ── capability probe ──────────────────────────────────────────────────────────

def _wireviz_available() -> bool:
    try:
        import wireviz  # noqa: F401
        return True
    except ImportError:
        return False


# ── main entry point ──────────────────────────────────────────────────────────

def run_wireviz(source: str) -> WireVizResult:
    """
    Compile a WireViz YAML string to an SVG string.

    Returns WireVizResult(svg, warnings).  `svg` is None when WireViz is not
    installed or compilation fails; `warnings` carries human-readable messages.
    """
    if not source or not source.strip():
        return WireVizResult(svg=None, warnings=["source is empty"])

    if not _wireviz_available():
        return WireVizResult(
            svg=None,
            warnings=["WireViz not installed; run: pip install kerf-wiring[wireviz]"],
        )

    warnings: list[str] = []
    try:
        svg = _compile_yaml(source, warnings)
        return WireVizResult(svg=svg, warnings=warnings)
    except Exception as exc:
        return WireVizResult(svg=None, warnings=[f"WireViz error: {exc}"])


# ── internal compilation ──────────────────────────────────────────────────────

def _compile_yaml(source: str, warnings: list[str]) -> str:
    """
    Write YAML to a temp file, parse via WireViz, return the SVG string.

    Tries the v0.4 API (Harness.svg()) first; falls back to the v0.3
    file-output API if .svg() is not available.
    """
    import wireviz
    from wireviz import Harness  # noqa: F401

    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / "harness.yml"
        yaml_path.write_text(source, encoding="utf-8")

        # parse_file returns a Harness
        harness = wireviz.parse_file(str(yaml_path))
        harness.create_graph()

        # v0.4+: in-memory SVG
        if hasattr(harness, "svg"):
            svg_str = harness.svg()
            if isinstance(svg_str, bytes):
                svg_str = svg_str.decode("utf-8")
            return svg_str

        # v0.3 fallback: write SVG file then read it back
        out_prefix = str(Path(tmpdir) / "harness")
        harness.output(filename=out_prefix, fmt=("svg",), view=False)
        svg_path = Path(out_prefix + ".svg")
        if not svg_path.exists():
            raise RuntimeError(
                "WireViz did not produce an SVG file. "
                "Upgrade to wireviz>=0.4: pip install 'wireviz>=0.4'"
            )
        warnings.append(
            "wireviz<0.4 detected: used file-output fallback. "
            "Upgrade with: pip install 'wireviz>=0.4'"
        )
        return svg_path.read_text(encoding="utf-8")
