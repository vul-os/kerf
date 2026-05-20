"""
kerf_textiles.export
====================
Export textile structures to standard interchange formats.

Supported outputs
-----------------
- SVG string (vector paths for weave / knit cells)
- WIF (Weaving Information File) — plain-text interchange for weave drafts
- CSV — simple grid dump of a cell matrix
- JSON — generic dict serialisation (uses draft module for Draft objects)

All functions return strings (not files) so they are easily tested
and streamed to response objects.
"""

from __future__ import annotations

import json
from typing import Union

from kerf_textiles.weave import WeaveResult
from kerf_textiles.knit import KnitResult
from kerf_textiles.draft import Draft, draft_to_dict


# ---------------------------------------------------------------------------
# SVG export
# ---------------------------------------------------------------------------

# Colours
_WARP_OVER_COLOUR = "#2c3e50"    # dark — warp thread on top
_WARP_UNDER_COLOUR = "#ecf0f1"   # light — weft thread on top
_LOOP_COLOUR = "#27ae60"         # green
_TUCK_COLOUR = "#e67e22"         # orange
_MISS_COLOUR = "#ecf0f1"         # near-white
_CELL_SIZE = 12                  # px per cell

_KNIT_COLOUR = {
    "loop": _LOOP_COLOUR,
    "tuck": _TUCK_COLOUR,
    "miss": _MISS_COLOUR,
}


def weave_to_svg(result: WeaveResult, cell_px: int = _CELL_SIZE) -> str:
    """Render a WeaveResult to an SVG string showing the repeat tile."""
    matrix = result.cell_matrix
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    width = cols * cell_px
    height = rows * cell_px

    rects: list[str] = []
    for r, row in enumerate(matrix):
        for c, over in enumerate(row):
            colour = _WARP_OVER_COLOUR if over else _WARP_UNDER_COLOUR
            x = c * cell_px
            y = r * cell_px
            rects.append(
                f'  <rect x="{x}" y="{y}" width="{cell_px}" height="{cell_px}" '
                f'fill="{colour}" stroke="#999" stroke-width="0.5"/>'
            )

    inner = "\n".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
        f'{inner}\n'
        f'</svg>'
    )


def knit_to_svg(result: KnitResult, cell_px: int = _CELL_SIZE) -> str:
    """Render a KnitResult to an SVG string showing the repeat tile."""
    matrix = result.cell_matrix
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    width = cols * cell_px
    height = rows * cell_px

    rects: list[str] = []
    for r, row in enumerate(matrix):
        for c, stitch in enumerate(row):
            colour = _KNIT_COLOUR.get(stitch, "#ccc")
            x = c * cell_px
            y = r * cell_px
            rects.append(
                f'  <rect x="{x}" y="{y}" width="{cell_px}" height="{cell_px}" '
                f'fill="{colour}" stroke="#999" stroke-width="0.5"/>'
            )

    inner = "\n".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
        f'{inner}\n'
        f'</svg>'
    )


# ---------------------------------------------------------------------------
# WIF (Weaving Information File) export
# ---------------------------------------------------------------------------

def draft_to_wif(draft: Draft) -> str:
    """
    Serialise a Draft to WIF (Weaving Information File) format.

    WIF is a plain-text, section-based format used by weaving software.
    Sections: [WIF], [CONTENTS], [THREADING], [TREADLING], [TIEUP].
    """
    lines: list[str] = []

    # Header
    lines += [
        "[WIF]",
        "Version=1.1",
        f"Date={draft.name}",
        "Developers=kerf-textiles",
        "Source Program=kerf",
        "",
        "[CONTENTS]",
        "THREADING=true",
        "TREADLING=true",
        "TIEUP=true",
        "",
        "[WEAVING]",
        f"Shafts={draft.n_shafts}",
        f"Treadles={draft.n_treadles}",
        "",
    ]

    # Threading: end_number (1-based) = shaft (1-based)
    lines.append("[THREADING]")
    for i, shaft in enumerate(draft.threading):
        lines.append(f"{i + 1}={shaft + 1}")
    lines.append("")

    # Treadling: pick_number (1-based) = treadle (1-based)
    lines.append("[TREADLING]")
    for j, treadle in enumerate(draft.treadling):
        lines.append(f"{j + 1}={treadle + 1}")
    lines.append("")

    # Tie-up: shaft (1-based) = comma-separated treadles (1-based) where True
    lines.append("[TIEUP]")
    for shaft_idx, row in enumerate(draft.tie_up):
        active = [str(t + 1) for t, v in enumerate(row) if v]
        if active:
            lines.append(f"{shaft_idx + 1}={','.join(active)}")
    lines.append("")

    if draft.notes:
        lines += [f"[NOTES]", draft.notes, ""]

    return "\n".join(lines)


def draft_from_wif(wif_text: str) -> Draft:
    """
    Parse a WIF string back into a Draft object.

    Supports the subset written by draft_to_wif; not a full WIF parser.
    """
    # Parse all sections into raw line lists
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in wif_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].upper()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)

    def parse_str_kv(section: str) -> dict[str, str]:
        """Parse a section as string-key → string-value pairs."""
        out: dict[str, str] = {}
        for line in sections.get(section, []):
            if "=" in line:
                k, _, v = line.partition("=")
                out[k.strip().lower()] = v.strip()
        return out

    def parse_int_kv(section: str) -> dict[int, str]:
        """Parse a section as int-key (1-based) → string-value pairs."""
        out: dict[int, str] = {}
        for line in sections.get(section, []):
            if "=" in line:
                k, _, v = line.partition("=")
                k_str = k.strip()
                if k_str.isdigit():
                    out[int(k_str)] = v.strip()
        return out

    # WEAVING section: string keys (Shafts, Treadles, …)
    weaving = parse_str_kv("WEAVING")
    n_shafts = int(weaving.get("shafts", 0))
    n_treadles = int(weaving.get("treadles", 0))

    # Integer-keyed sections
    threading_kv = parse_int_kv("THREADING")
    treadling_kv = parse_int_kv("TREADLING")
    tieup_kv = parse_int_kv("TIEUP")

    # Reconstruct threading list (1-based end → 0-based shaft)
    n_ends = max(threading_kv.keys(), default=0)
    threading = [int(threading_kv[i + 1]) - 1 for i in range(n_ends)]

    # Reconstruct treadling list (1-based pick → 0-based treadle)
    n_picks = max(treadling_kv.keys(), default=0)
    treadling = [int(treadling_kv[j + 1]) - 1 for j in range(n_picks)]

    # Reconstruct tie_up matrix
    tie_up: list[list[bool]] = [[False] * n_treadles for _ in range(n_shafts)]
    for shaft_1based, treadles_str in tieup_kv.items():
        shaft = shaft_1based - 1
        for t_str in treadles_str.split(","):
            t_str = t_str.strip()
            if t_str and t_str.isdigit():
                treadle = int(t_str) - 1
                if 0 <= shaft < n_shafts and 0 <= treadle < n_treadles:
                    tie_up[shaft][treadle] = True

    # Recover name from WIF header [Date=<name>]
    wif_kv = parse_str_kv("WIF")
    name = wif_kv.get("date", "imported")

    notes = "\n".join(sections.get("NOTES", []))

    return Draft(
        name=name,
        n_shafts=n_shafts,
        n_treadles=n_treadles,
        threading=threading,
        treadling=treadling,
        tie_up=tie_up,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def matrix_to_csv(matrix: list[list]) -> str:
    """Generic 2-D list → CSV string."""
    rows: list[str] = []
    for row in matrix:
        rows.append(",".join("1" if v is True else ("0" if v is False else str(v)) for v in row))
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def weave_to_json(result: WeaveResult) -> str:
    """Serialise a WeaveResult to JSON."""
    data = {
        "name": result.name,
        "repeat_warp": result.repeat_warp,
        "repeat_weft": result.repeat_weft,
        "cell_matrix": result.cell_matrix,
        "float_stats": result.float_stats,
        "analytic_warp_mean_float": result.analytic_warp_mean_float,
        "analytic_weft_mean_float": result.analytic_weft_mean_float,
    }
    return json.dumps(data, indent=2)


def knit_to_json(result: KnitResult) -> str:
    """Serialise a KnitResult to JSON."""
    data = {
        "name": result.name,
        "repeat_needles": result.repeat_needles,
        "repeat_courses": result.repeat_courses,
        "cell_matrix": result.cell_matrix,
        "density_stats": result.density_stats,
    }
    return json.dumps(data, indent=2)
