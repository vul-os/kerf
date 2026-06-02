"""
drawing_list.py — Drawing List / Multi-Sheet Manager (ArchiCAD Layout Book equivalent).

Auto-numbers 50-sheet construction document sets per AIA NCS, cross-references
detail markers, validates the full set, and generates an index sheet.

AIA NCS discipline codes used for auto-numbering:
    A  Architectural      A-101, A-102 …
    S  Structural         S-201, S-202 …
    M  Mechanical (MEP)   M-301, M-302 …
    E  Electrical (MEP)   E-401, E-402 …
    P  Plumbing  (MEP)    P-501, P-502 …
    C  Civil              C-601, C-602 …
    I  Interior           I-701, I-702 …
    G  General / Cover    G-001, G-002 …
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


# ── enumerations ──────────────────────────────────────────────────────────────

class SheetSize(str, Enum):
    A0       = "A0"
    A1       = "A1"
    A2       = "A2"
    A3       = "A3"
    A4       = "A4"
    ANSI_A   = "ANSI-A"
    ANSI_B   = "ANSI-B"
    ANSI_C   = "ANSI-C"
    ANSI_D   = "ANSI-D"
    ANSI_E   = "ANSI-E"


# Physical dimensions (width × height) in millimetres (landscape).
_SHEET_DIMS_MM: dict[SheetSize, tuple[int, int]] = {
    SheetSize.A0:    (1189, 841),
    SheetSize.A1:    (841,  594),
    SheetSize.A2:    (594,  420),
    SheetSize.A3:    (420,  297),
    SheetSize.A4:    (297,  210),
    SheetSize.ANSI_A: (279, 216),
    SheetSize.ANSI_B: (432, 279),
    SheetSize.ANSI_C: (559, 432),
    SheetSize.ANSI_D: (864, 559),
    SheetSize.ANSI_E: (1118, 864),
}

DisciplineType = Literal[
    "architectural", "structural", "mep", "civil", "interior", "general"
]

# AIA NCS starting sheet numbers per discipline.
_AIA_SERIES: dict[str, int] = {
    "architectural": 100,
    "structural":    200,
    "mep":           300,
    "civil":         600,
    "interior":      700,
    "general":         0,
}

# AIA NCS letter prefix per discipline.
_AIA_PREFIX: dict[str, str] = {
    "architectural": "A",
    "structural":    "S",
    "mep":           "M",
    "civil":         "C",
    "interior":      "I",
    "general":       "G",
}

# Pattern for a detail marker like "1/A-301" or "3/S-204".
_DETAIL_MARKER_RE = re.compile(r"\b(\d+)/([A-Z]-\d{3})\b")


# ── dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class SheetSpec:
    """Specification for a single sheet in a construction document set."""

    title: str
    discipline: DisciplineType
    sheet_size: SheetSize = SheetSize.A1
    scale: str = "1:100"
    # Viewports: each dict must have at least {"view_ref": str, "origin": [x, y]}
    viewports: list[dict] = field(default_factory=list)
    # Assigned by auto_number_sheets — callers may also set this directly.
    sheet_number: str = ""
    # Revision metadata (optional).
    revision: str = ""
    drawn_by: str = ""
    issue_date: str = ""

    @property
    def dimensions_mm(self) -> tuple[int, int]:
        return _SHEET_DIMS_MM[self.sheet_size]


@dataclass
class DrawingListReport:
    """Summary report for a full construction document drawing list."""

    total_sheets: int
    sheets_by_discipline: dict[str, int]
    # Each row: (sheet_number, title, discipline, sheet_size, scale)
    sheet_summary_table: list[tuple]
    # Each row: (from_sheet_number, to_sheet_number, detail_marker)
    cross_references: list[tuple]
    honest_caveat: str


# ── auto-numbering ─────────────────────────────────────────────────────────────

def auto_number_sheets(
    sheets: list[SheetSpec],
    scheme: str = "aia_standard",
) -> list[SheetSpec]:
    """Assign AIA NCS sheet numbers (A-101, A-102, S-201, …) in-place and return the list.

    Per AIA NCS 2.0:
      - Each discipline has a letter prefix and a starting series number.
      - Sheets are numbered sequentially within a discipline.
      - Existing sheet_number values are overwritten unless scheme=="preserve_existing".
    """
    if scheme not in ("aia_standard", "preserve_existing"):
        raise ValueError(f"Unknown scheme '{scheme}'; expected 'aia_standard' or 'preserve_existing'")

    # Count how many sheets we've assigned per discipline series.
    counters: dict[str, int] = {}

    for sheet in sheets:
        if scheme == "preserve_existing" and sheet.sheet_number:
            continue

        disc = sheet.discipline
        prefix = _AIA_PREFIX.get(disc, "X")
        base   = _AIA_SERIES.get(disc, 0)

        idx = counters.get(disc, 0)
        counters[disc] = idx + 1

        sheet.sheet_number = f"{prefix}-{base + idx + 1:03d}"

    return sheets


# ── validation ────────────────────────────────────────────────────────────────

def validate_drawing_list(sheets: list[SheetSpec]) -> list[str]:
    """Return a (possibly empty) list of human-readable validation error strings.

    Checks performed:
      - Duplicate sheet numbers
      - Sheets missing a title
      - Sheets missing a sheet_number
      - Orphaned cross-references (detail marker points to a sheet that doesn't exist)
      - Viewports missing required keys
    """
    errors: list[str] = []
    seen_numbers: dict[str, int] = {}

    for i, sheet in enumerate(sheets):
        label = sheet.sheet_number or f"sheets[{i}]"

        if not sheet.sheet_number:
            errors.append(f"Sheet {i} '{sheet.title}' has no sheet_number")

        if not sheet.title:
            errors.append(f"Sheet {label} has no title")

        if sheet.sheet_number:
            prev = seen_numbers.get(sheet.sheet_number)
            if prev is not None:
                errors.append(
                    f"Duplicate sheet number {sheet.sheet_number!r} "
                    f"(sheets[{prev}] and sheets[{i}])"
                )
            else:
                seen_numbers[sheet.sheet_number] = i

        for j, vp in enumerate(sheet.viewports):
            if "view_ref" not in vp:
                errors.append(
                    f"Sheet {label} viewport[{j}] missing 'view_ref'"
                )
            if "origin" not in vp:
                errors.append(
                    f"Sheet {label} viewport[{j}] missing 'origin'"
                )

    # Orphaned cross-references detected from viewport view_refs.
    valid_numbers = {s.sheet_number for s in sheets if s.sheet_number}
    for sheet in sheets:
        for vp in sheet.viewports:
            view_ref = vp.get("view_ref", "")
            # view_ref may be "1/A-301" style or plain "A-301".
            for m in _DETAIL_MARKER_RE.finditer(view_ref):
                target = m.group(2)
                if target not in valid_numbers:
                    errors.append(
                        f"Sheet {sheet.sheet_number}: viewport view_ref {view_ref!r} "
                        f"references missing sheet {target!r}"
                    )

    return errors


# ── cross-reference computation ───────────────────────────────────────────────

def compute_cross_references(sheets: list[SheetSpec]) -> list[tuple]:
    """Scan all viewport view_refs for detail markers (e.g. '1/A-301').

    Returns a list of tuples:
        (from_sheet_number, to_sheet_number, detail_marker)

    Only resolved (non-orphaned) cross-references are included.
    """
    valid_numbers = {s.sheet_number for s in sheets if s.sheet_number}
    refs: list[tuple] = []

    for sheet in sheets:
        for vp in sheet.viewports:
            view_ref = vp.get("view_ref", "")
            for m in _DETAIL_MARKER_RE.finditer(view_ref):
                marker   = m.group(0)          # e.g. "1/A-301"
                target   = m.group(2)           # e.g. "A-301"
                if target in valid_numbers:
                    refs.append((sheet.sheet_number, target, marker))

    return refs


# ── index-sheet generator ──────────────────────────────────────────────────────

def generate_drawing_index_sheet(
    sheets: list[SheetSpec],
    output_format: str = "dxf",
) -> str:
    """Generate a drawing-index sheet and return a path to the output file.

    Writes a plain-text representation (tab-separated columns) named
    ``drawing_index.<format>`` in the process's temp directory.  In a
    production deployment this would drive a DXF/PDF renderer; here we emit
    a portable CSV-in-disguise so tests can verify the contents without a
    heavyweight dependency.
    """
    if output_format not in ("dxf", "pdf"):
        raise ValueError(f"Unsupported output_format '{output_format}'; use 'dxf' or 'pdf'")

    import tempfile

    lines: list[str] = [
        "DRAWING INDEX",
        f"Total sheets: {len(sheets)}",
        "",
        "\t".join(["Sheet No.", "Title", "Discipline", "Size", "Scale"]),
    ]

    for sheet in sorted(sheets, key=lambda s: s.sheet_number or ""):
        lines.append(
            "\t".join([
                sheet.sheet_number,
                sheet.title,
                sheet.discipline,
                sheet.sheet_size.value,
                sheet.scale,
            ])
        )

    content = "\n".join(lines) + "\n"
    suffix = f".{output_format}"
    fd, path = tempfile.mkstemp(prefix="drawing_index_", suffix=suffix)
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)

    return path


# ── report ─────────────────────────────────────────────────────────────────────

def compute_drawing_list_report(sheets: list[SheetSpec]) -> DrawingListReport:
    """Compute a full DrawingListReport for the given sheet set."""
    by_disc: dict[str, int] = {}
    summary: list[tuple] = []

    for sheet in sorted(sheets, key=lambda s: s.sheet_number or ""):
        disc = sheet.discipline
        by_disc[disc] = by_disc.get(disc, 0) + 1
        summary.append((
            sheet.sheet_number,
            sheet.title,
            disc,
            sheet.sheet_size.value,
            sheet.scale,
        ))

    xrefs = compute_cross_references(sheets)

    return DrawingListReport(
        total_sheets=len(sheets),
        sheets_by_discipline=by_disc,
        sheet_summary_table=summary,
        cross_references=xrefs,
        honest_caveat=(
            "Cross-references are resolved from viewport view_ref strings that match the "
            "pattern '<detail_number>/<sheet_number>' (e.g. '1/A-301'). "
            "View refs that do not follow this pattern are not tracked. "
            "The index sheet is a plain-text stub; a full DXF/PDF renderer "
            "is required for production construction document output."
        ),
    )
