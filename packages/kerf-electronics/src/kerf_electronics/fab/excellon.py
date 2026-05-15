"""
Excellon drill file writer for CircuitJSON boards.

Converts CircuitJSON pad/via hole definitions into an Excellon drill file
with a proper tool table, plated/non-plated sections, and drill hits.

Supported hole sources:
  pcb_via                     → plated through-hole (via diameter)
  pcb_plated_pad              → plated through-hole (pad drill attribute)
  pcb_pad (with drill_size)   → plated through-hole
  pcb_smtpad                  → SMT, no drill

Coordinate units: millimetres, format 3.3 (3 integer + 3 decimal digits).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ─── data structures ─────────────────────────────────────────────────────────

@dataclass(frozen=True, order=True)
class DrillTool:
    diameter_mm: float
    plated: bool


@dataclass
class DrillHit:
    tool: DrillTool
    x: float
    y: float


# ─── coordinate format ────────────────────────────────────────────────────────

def _fmt(mm: float) -> str:
    """Format millimetre value as Excellon 3.3 integer (no decimal point)."""
    return str(int(round(mm * 1_000)))


# ─── CircuitJSON traversal ────────────────────────────────────────────────────

def _collect_hits(circuit_json: list[dict]) -> list[DrillHit]:
    hits: list[DrillHit] = []

    for el in circuit_json:
        t = el.get("type", "")

        # ── vias ────────────────────────────────────────────────────────────
        if t == "pcb_via":
            x = float(el.get("x", 0.0))
            y = float(el.get("y", 0.0))
            diameter = float(
                el.get("hole_diameter",
                el.get("drill_diameter",
                el.get("drill", 0.3)))
            )
            if diameter > 0:
                hits.append(DrillHit(DrillTool(round(diameter, 4), plated=True), x, y))

        # ── plated through-hole pads ─────────────────────────────────────────
        elif t in ("pcb_plated_pad", "pcb_pad"):
            x = float(el.get("x", 0.0))
            y = float(el.get("y", 0.0))
            drill = el.get("hole_diameter", el.get("drill_diameter",
                           el.get("drill", el.get("drill_size", 0.0))))
            diameter = float(drill) if drill is not None else 0.0
            if diameter > 0:
                hits.append(DrillHit(DrillTool(round(diameter, 4), plated=True), x, y))

        # ── pcb_hole (non-plated mounting holes) ─────────────────────────────
        elif t in ("pcb_hole", "pcb_mounting_hole"):
            x = float(el.get("x", 0.0))
            y = float(el.get("y", 0.0))
            diameter = float(el.get("hole_diameter", el.get("diameter", 3.2)))
            if diameter > 0:
                plated = bool(el.get("plated", False))
                hits.append(DrillHit(DrillTool(round(diameter, 4), plated=plated), x, y))

    return hits


def _build_tool_table(hits: list[DrillHit]) -> dict[DrillTool, int]:
    """Assign T-codes to unique tools, sorted by diameter."""
    tools = sorted(set(h.tool for h in hits))
    return {tool: i + 1 for i, tool in enumerate(tools)}


# ─── Excellon generator ───────────────────────────────────────────────────────

def export_excellon(
    circuit_json: list[dict],
    stem: str = "board",
    plated_filename: str | None = None,
    nonplated_filename: str | None = None,
) -> dict[str, str]:
    """Convert CircuitJSON to Excellon drill file(s).

    Returns a dict of {filename: excellon_text}.  Two files are emitted when
    both plated and non-plated holes are present; otherwise only the plated
    file is returned (most boards have no NPTH holes).

    Args:
        circuit_json: Parsed CircuitJSON array.
        stem: Base filename stem.
        plated_filename: Override filename for plated holes (default: stem.DRL).
        nonplated_filename: Override for non-plated (default: stem.NPTH.DRL).
    """
    if not isinstance(circuit_json, list):
        circuit_json = []

    hits = _collect_hits(circuit_json)

    plated_hits = [h for h in hits if h.tool.plated]
    npth_hits = [h for h in hits if not h.tool.plated]

    result: dict[str, str] = {}

    if plated_hits or not npth_hits:
        fname = plated_filename or f"{stem}.DRL"
        result[fname] = _render_excellon(plated_hits, plated=True, stem=stem)

    if npth_hits:
        fname = nonplated_filename or f"{stem}.NPTH.DRL"
        result[fname] = _render_excellon(npth_hits, plated=False, stem=stem)

    return result


def _render_excellon(
    hits: list[DrillHit],
    plated: bool,
    stem: str,
) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tool_table = _build_tool_table(hits)

    lines: list[str] = [
        "M48",
        f"; Kerf Electronics — Excellon Drill File",
        f"; Stem: {stem}",
        f"; Generated: {ts}",
        f"; {'Plated' if plated else 'Non-plated'} holes",
        "FMAT,2",
        "METRIC,TZ",
        ";",
        "; TOOL TABLE",
    ]

    for tool, tcode in sorted(tool_table.items(), key=lambda kv: kv[1]):
        lines.append(f"T{tcode:02d}C{tool.diameter_mm:.4f}")

    lines.append("%")
    lines.append("G90")   # absolute mode
    lines.append("G05")   # drill mode

    # Group hits by tool
    by_tool: dict[int, list[DrillHit]] = {tc: [] for tc in tool_table.values()}
    for h in hits:
        tc = tool_table[h.tool]
        by_tool[tc].append(h)

    for tc in sorted(by_tool.keys()):
        lines.append(f"T{tc:02d}")
        for h in by_tool[tc]:
            lines.append(f"X{_fmt(h.x)}Y{_fmt(h.y)}")

    lines.append("T00")
    lines.append("M30")

    return "\n".join(lines) + "\n"
