"""
kerf_cad_core.simple_parametric.cut_list — cut-list + flat-pack layout engine.

Two main entry points:

compute_cut_list(panels, *, material, sheet_w, sheet_h, kerf, margin)
    Takes a list of PanelDef (from templates.build_part) and returns:
      - A rolled-up cut list grouped by unique (w × h) panel size.
      - Material area totals and estimated sheet count.
      - Per-panel placement on sheets (flat-pack layout via greedy shelf).

compute_flat_pack_layout(panels, sheet_w, sheet_h, kerf, margin)
    Pure layout engine — returns placement list per sheet.

cut_list_to_csv(cut_list_result)
    Serialise the cut list dict to a CSV string suitable for printing.

Algorithm (flat-pack layout)
----------------------------
Greedy shelf packing (deterministic, no backtracking):
  1. Sort panels descending by height (tallest first).
  2. For each panel: find the shelf with enough horizontal space; else open
     a new shelf (or new sheet when the current sheet is full).
  3. Rotation: if allow_rotate and the panel fits better rotated, rotate it.

The algorithm is intentionally simple (this is the education/maker persona
— the result should be easy to follow, not optimal). Users who need optimal
packing can use nest_parts from kerf_cad_core.nesting.

Units: mm throughout. Deterministic.

Author: imranparuk
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import Optional

from kerf_cad_core.simple_parametric.templates import PanelDef


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CutPiece:
    """One line in the cut list (unique size + qty)."""
    name: str           # panel name (may include index when multiple sizes)
    w: float
    h: float
    thickness: float
    qty: int
    area_each_mm2: float = field(init=False)
    area_total_mm2: float = field(init=False)

    def __post_init__(self) -> None:
        self.area_each_mm2  = round(self.w * self.h, 3)
        self.area_total_mm2 = round(self.w * self.h * self.qty, 3)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "w": round(self.w, 3),
            "h": round(self.h, 3),
            "thickness": round(self.thickness, 3),
            "qty": self.qty,
            "area_each_mm2": self.area_each_mm2,
            "area_total_mm2": self.area_total_mm2,
        }


@dataclass
class SheetPlacement:
    """Position of one panel on a specific sheet."""
    sheet: int      # 1-based
    name: str
    x: float
    y: float
    w: float
    h: float
    rot: int        # 0 or 90


@dataclass
class CutListResult:
    """Full result from compute_cut_list."""
    pieces: list[CutPiece]
    sheets_used: int
    sheet_w: float
    sheet_h: float
    material: str
    kerf_mm: float
    margin_mm: float
    total_area_mm2: float
    total_sheet_area_mm2: float
    utilization: float                  # (0, 1]
    placements: list[SheetPlacement]
    errors: list[str]

    def to_dict(self) -> dict:
        return {
            "pieces": [p.to_dict() for p in self.pieces],
            "sheets_used": self.sheets_used,
            "sheet_w": self.sheet_w,
            "sheet_h": self.sheet_h,
            "material": self.material,
            "kerf_mm": self.kerf_mm,
            "margin_mm": self.margin_mm,
            "total_area_mm2": round(self.total_area_mm2, 3),
            "total_sheet_area_mm2": round(self.total_sheet_area_mm2, 3),
            "utilization": round(self.utilization, 4),
            "placements": [
                {
                    "sheet": p.sheet,
                    "name": p.name,
                    "x": round(p.x, 3),
                    "y": round(p.y, 3),
                    "w": round(p.w, 3),
                    "h": round(p.h, 3),
                    "rot": p.rot,
                }
                for p in self.placements
            ],
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Shelf-packing implementation
# ---------------------------------------------------------------------------

@dataclass
class _Shelf:
    y: float        # bottom edge of shelf
    h: float        # shelf height (= tallest panel placed so far)
    x_next: float   # next available x position on this shelf


@dataclass
class _SheetState:
    number: int     # 1-based sheet number
    shelves: list[_Shelf] = field(default_factory=list)


def _try_place_on_shelf(
    shelf: _Shelf,
    pw: float,
    ph: float,
    usable_w: float,
    usable_h: float,
    margin: float,
    kerf: float,
) -> Optional[tuple[float, float]]:
    """
    Try to place a panel of size (pw × ph) on the given shelf.
    Returns (x, y) of the lower-left corner (including margin) or None.
    """
    x = shelf.x_next
    y = shelf.y
    # Would the panel overflow the shelf height? That means the shelf
    # was opened for a taller panel; this panel fits height-wise (ph <= shelf.h).
    if ph > shelf.h and shelf.h > 0:
        return None
    if x + pw > margin + usable_w:
        return None
    if y + ph > margin + usable_h:
        return None
    return (x, y)


def compute_flat_pack_layout(
    panels: list[PanelDef],
    sheet_w: float,
    sheet_h: float,
    *,
    kerf: float = 0.0,
    margin: float = 0.0,
    allow_rotate: bool = True,
) -> tuple[list[SheetPlacement], int, list[str]]:
    """
    Layout panels onto sheets using a greedy shelf algorithm.

    Returns (placements, sheets_used, errors).

    panels      : list of PanelDef (qty is respected)
    sheet_w/h   : stock sheet outer dimensions (mm)
    kerf        : gap between adjacent panels (mm)
    margin      : border inset on all edges of each sheet (mm)
    allow_rotate: if True, try rotating 90° when the panel fits better

    Errors are returned for panels that cannot fit even on an empty sheet.
    """
    if sheet_w <= 0 or sheet_h <= 0:
        return [], 0, ["sheet dimensions must be > 0"]

    errors: list[str] = []
    placements: list[SheetPlacement] = []

    usable_w = sheet_w - 2 * margin
    usable_h = sheet_h - 2 * margin

    # Expand qty → individual items to place
    items: list[tuple[str, float, float, float]] = []  # (name, w, h, thickness)
    for p in panels:
        # t_slot_frame panels have h==0 (members, not flat panels) — treat as 1D
        is_member = p.h == 0.0
        for _ in range(max(1, p.qty)):
            items.append((p.name, p.w, p.h if not is_member else p.w, p.thickness))

    # Sort descending by height (tallest first → better packing)
    items.sort(key=lambda it: it[2], reverse=True)

    sheets: list[_SheetState] = []

    def _new_sheet() -> _SheetState:
        s = _SheetState(number=len(sheets) + 1)
        # Open the first shelf at the margin boundary
        first_shelf = _Shelf(y=margin, h=0.0, x_next=margin)
        s.shelves.append(first_shelf)
        sheets.append(s)
        return s

    current_sheet = _new_sheet()

    for name, pw, ph, _thick in items:
        # Sanity check: does the panel fit on an empty sheet at all?
        fits_normal  = pw <= usable_w and ph <= usable_h
        fits_rotated = allow_rotate and ph <= usable_w and pw <= usable_h

        if not fits_normal and not fits_rotated:
            errors.append(
                f"Panel '{name}' ({pw:.1f}×{ph:.1f} mm) exceeds usable sheet area "
                f"({usable_w:.1f}×{usable_h:.1f} mm) — skipped."
            )
            continue

        placed = False
        for attempt_sheet in [current_sheet] + [None]:
            if attempt_sheet is None:
                # Open a new sheet
                current_sheet = _new_sheet()
                attempt_sheet = current_sheet

            for rot in ([0, 90] if allow_rotate else [0]):
                apw = pw if rot == 0 else ph
                aph = ph if rot == 0 else pw

                if apw > usable_w or aph > usable_h:
                    continue

                # Try each existing shelf
                for shelf in attempt_sheet.shelves:
                    pos = _try_place_on_shelf(shelf, apw, aph, usable_w, usable_h, margin, kerf)
                    if pos is not None:
                        x, y = pos
                        placements.append(SheetPlacement(
                            sheet=attempt_sheet.number,
                            name=name,
                            x=x, y=y,
                            w=apw, h=aph,
                            rot=rot,
                        ))
                        # Update shelf state
                        shelf.x_next = x + apw + kerf
                        if aph > shelf.h:
                            shelf.h = aph
                        placed = True
                        break

                if placed:
                    break

                # Try opening a new shelf on current sheet
                last_shelf = attempt_sheet.shelves[-1]
                new_shelf_y = last_shelf.y + last_shelf.h + kerf
                if new_shelf_y + aph <= margin + usable_h:
                    new_shelf = _Shelf(y=new_shelf_y, h=0.0, x_next=margin)
                    attempt_sheet.shelves.append(new_shelf)
                    pos = _try_place_on_shelf(new_shelf, apw, aph, usable_w, usable_h, margin, kerf)
                    if pos is not None:
                        x, y = pos
                        placements.append(SheetPlacement(
                            sheet=attempt_sheet.number,
                            name=name,
                            x=x, y=y,
                            w=apw, h=aph,
                            rot=rot,
                        ))
                        new_shelf.x_next = x + apw + kerf
                        new_shelf.h = aph
                        placed = True
                        # Remove the failed partial shelf if it was added and unused
                        break

                if placed:
                    break

            if placed:
                break

        if not placed and not any(
            e.startswith(f"Panel '{name}'") for e in errors
        ):
            errors.append(f"Panel '{name}' could not be placed — unknown layout failure.")

    return placements, len(sheets), errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_cut_list(
    panels: list[PanelDef],
    *,
    material: str = "plywood",
    sheet_w: float = 1220.0,
    sheet_h: float = 2440.0,
    kerf: float = 3.0,
    margin: float = 10.0,
    allow_rotate: bool = True,
) -> CutListResult:
    """
    Compute a cut list and flat-pack layout from a list of PanelDef.

    Parameters
    ----------
    panels      : list of PanelDef from templates.build_part
    material    : human label for the stock material (e.g. "9mm plywood")
    sheet_w     : stock sheet width  (mm), default 1220 (half-sheet 4×8)
    sheet_h     : stock sheet height (mm), default 2440 (full-sheet 4×8)
    kerf        : laser/saw kerf gap between panels (mm), default 3 mm
    margin      : border waste margin on each sheet (mm), default 10 mm
    allow_rotate: try 90° rotation to improve fit (default True)

    Returns
    -------
    CutListResult
    """
    errors: list[str] = []

    # Validate
    if sheet_w <= 0 or sheet_h <= 0:
        return CutListResult(
            pieces=[], sheets_used=0,
            sheet_w=sheet_w, sheet_h=sheet_h,
            material=material, kerf_mm=kerf, margin_mm=margin,
            total_area_mm2=0, total_sheet_area_mm2=0, utilization=0,
            placements=[], errors=["sheet dimensions must be > 0"],
        )

    if kerf < 0 or margin < 0:
        errors.append("kerf and margin must be >= 0; treating as 0.")
        kerf   = max(0.0, kerf)
        margin = max(0.0, margin)

    # Build rolled-up cut list (group by name + size)
    pieces: list[CutPiece] = []
    seen: dict[tuple, CutPiece] = {}
    for p in panels:
        key = (p.name, round(p.w, 3), round(p.h, 3), round(p.thickness, 3))
        if key in seen:
            seen[key].qty += p.qty
            seen[key].area_total_mm2 = round(seen[key].area_each_mm2 * seen[key].qty, 3)
        else:
            cp = CutPiece(
                name=p.name,
                w=p.w, h=p.h,
                thickness=p.thickness,
                qty=p.qty,
            )
            seen[key] = cp
            pieces.append(cp)

    total_area = sum(cp.area_total_mm2 for cp in pieces)

    # Flat-pack layout
    placements, sheets_used, layout_errors = compute_flat_pack_layout(
        panels, sheet_w, sheet_h,
        kerf=kerf, margin=margin, allow_rotate=allow_rotate,
    )
    errors.extend(layout_errors)

    total_sheet_area = sheets_used * sheet_w * sheet_h
    utilization = total_area / total_sheet_area if total_sheet_area > 0 else 0.0

    return CutListResult(
        pieces=pieces,
        sheets_used=sheets_used,
        sheet_w=sheet_w,
        sheet_h=sheet_h,
        material=material,
        kerf_mm=kerf,
        margin_mm=margin,
        total_area_mm2=round(total_area, 3),
        total_sheet_area_mm2=round(total_sheet_area, 3),
        utilization=round(utilization, 4),
        placements=placements,
        errors=errors,
    )


def cut_list_to_csv(result: CutListResult) -> str:
    """
    Serialise a CutListResult to a CSV string.

    Columns: Part name, Width (mm), Height (mm), Thickness (mm), Qty,
             Area each (mm²), Area total (mm²)

    A summary footer line is appended with totals.
    """
    buf = io.StringIO()

    # Header
    buf.write("Part name,Width (mm),Height (mm),Thickness (mm),Qty,Area each (mm²),Area total (mm²)\n")

    for cp in result.pieces:
        buf.write(
            f"{cp.name},{cp.w:.1f},{cp.h:.1f},{cp.thickness:.1f},"
            f"{cp.qty},{cp.area_each_mm2:.0f},{cp.area_total_mm2:.0f}\n"
        )

    buf.write("\n")
    buf.write(
        f"TOTAL,,,,"
        f"{sum(cp.qty for cp in result.pieces)},"
        f",{result.total_area_mm2:.0f}\n"
    )
    buf.write(
        f"Sheets required ({result.material} {result.sheet_w:.0f}×{result.sheet_h:.0f} mm),"
        f"{result.sheets_used},,,,,"
        f"Utilisation: {result.utilization * 100:.1f}%\n"
    )

    return buf.getvalue()
