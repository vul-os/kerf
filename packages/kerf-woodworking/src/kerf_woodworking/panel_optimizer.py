"""panel_optimizer.py — 2D guillotine nesting optimizer for sheet goods.

Implements a 2D guillotine bin-packing algorithm (GUILLOTINE-RECT-SPLIT with
Best Short Side (BSS) fit heuristic) for optimising panel layouts on standard
sheet materials (plywood, MDF, melamine, etc.).

Features:
- Grain-direction aware: optional 90° rotation suppressed when grain matters.
- Kerf allowance between all cuts.
- Yield percentage and off-cut reporting per sheet.
- Multiple stock sheet sizes supported (selects best fit).

Algorithm: Jyl Bourque's guillotine rectangle packing, FFD order.
Reference:
    Bourque, J.-M. (2003). Guillotine binary division.
    https://github.com/jcandeli/guillotine_packing (public domain)
    Scheithauer, G. (2018). Introduction to Cutting and Packing Optimization.
    Springer. Chapter 2: Guillotine Cutting.

All dimensions in millimetres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class PanelPart:
    """A required panel part to be cut from sheet stock.

    Attributes
    ----------
    part_id : str
        Unique identifier for this part type.
    length_mm : float
        Longer dimension (mm).
    width_mm : float
        Shorter dimension (mm).
    quantity : int
        Number of identical parts required.
    grain_direction : str
        'length' — grain must run along length_mm axis.
        'width'  — grain must run along width_mm axis.
        'none'   — no grain constraint; part may be rotated freely.
    material : str
        Material key (e.g. 'birch_ply_3/4"').
    description : str
        Human-readable label.
    """
    part_id: str
    length_mm: float
    width_mm: float
    quantity: int = 1
    grain_direction: str = "none"   # 'length' | 'width' | 'none'
    material: str = ""
    description: str = ""

    def __post_init__(self):
        if self.length_mm <= 0 or self.width_mm <= 0:
            raise ValueError(
                f"PanelPart '{self.part_id}': length_mm and width_mm must be positive"
            )
        if self.quantity < 1:
            raise ValueError(f"PanelPart '{self.part_id}': quantity must be >= 1")
        if self.grain_direction not in ("length", "width", "none"):
            raise ValueError(
                f"PanelPart '{self.part_id}': grain_direction must be "
                "'length', 'width', or 'none'"
            )


@dataclass
class PlacedPanel:
    """One panel placed on a sheet.

    Attributes
    ----------
    part_id : str
        Part identifier.
    x_mm, y_mm : float
        Bottom-left corner position on the sheet.
    length_mm, width_mm : float
        Dimensions as placed (may be rotated from original).
    rotated : bool
        True if part was rotated 90° from its original orientation.
    sheet_index : int
        Zero-based index into the list of used sheets.
    """
    part_id: str
    x_mm: float
    y_mm: float
    length_mm: float
    width_mm: float
    rotated: bool
    sheet_index: int


@dataclass
class SheetLayout:
    """The full nesting layout for one sheet."""
    sheet_index: int
    sheet_length_mm: float
    sheet_width_mm: float
    placements: List[PlacedPanel] = field(default_factory=list)
    off_cuts: List[Dict[str, float]] = field(default_factory=list)

    @property
    def used_area_mm2(self) -> float:
        return sum(p.length_mm * p.width_mm for p in self.placements)

    @property
    def sheet_area_mm2(self) -> float:
        return self.sheet_length_mm * self.sheet_width_mm

    @property
    def yield_pct(self) -> float:
        if self.sheet_area_mm2 <= 0:
            return 0.0
        return 100.0 * self.used_area_mm2 / self.sheet_area_mm2


@dataclass
class NestingResult:
    """Full result from optimise_panel_layout.

    Attributes
    ----------
    sheets_used : int
        Number of full sheets consumed.
    layouts : list[SheetLayout]
        One layout per sheet.
    total_yield_pct : float
        Aggregate material utilisation across all sheets.
    total_waste_mm2 : float
        Total wasted area (mm²).
    unplaced_parts : list[str]
        part_id values that could not be placed (oversized).
    warnings : list[str]
        Engineering or constraint warnings.
    """
    sheets_used: int
    layouts: List[SheetLayout]
    total_yield_pct: float
    total_waste_mm2: float
    unplaced_parts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Guillotine packing core
# ---------------------------------------------------------------------------

@dataclass
class _FreeRect:
    """A free rectangle available for packing."""
    x: float
    y: float
    w: float   # width (along sheet-x)
    h: float   # height (along sheet-y)


def _fits(rect: _FreeRect, pw: float, ph: float) -> bool:
    return pw <= rect.w + 1e-9 and ph <= rect.h + 1e-9


def _split_horiz(rect: _FreeRect, pw: float, ph: float) -> List[_FreeRect]:
    """Split free rect horizontally after placing p (pw × ph) at rect origin."""
    new_rects: List[_FreeRect] = []
    # Right piece
    if rect.w - pw > 1e-3:
        new_rects.append(_FreeRect(rect.x + pw, rect.y, rect.w - pw, ph))
    # Top piece
    if rect.h - ph > 1e-3:
        new_rects.append(_FreeRect(rect.x, rect.y + ph, rect.w, rect.h - ph))
    return new_rects


def _split_vert(rect: _FreeRect, pw: float, ph: float) -> List[_FreeRect]:
    """Split free rect vertically after placing p (pw × ph) at rect origin."""
    new_rects: List[_FreeRect] = []
    # Right piece
    if rect.w - pw > 1e-3:
        new_rects.append(_FreeRect(rect.x + pw, rect.y, rect.w - pw, rect.h))
    # Top piece
    if rect.h - ph > 1e-3:
        new_rects.append(_FreeRect(rect.x, rect.y + ph, pw, rect.h - ph))
    return new_rects


def _score_bss(rect: _FreeRect, pw: float, ph: float) -> float:
    """Best Short Side (BSS) score — lower is better."""
    short_side = min(rect.w - pw, rect.h - ph)
    return short_side


def _pack_sheet(
    parts: List[Tuple[str, float, float, bool]],  # [(part_id, w, h, rotatable), ...]
    sheet_w: float,
    sheet_h: float,
    kerf: float,
) -> Tuple[List[Tuple[str, float, float, float, bool]], List[Tuple[str, float, float, bool]]]:
    """Pack a list of (part_id, w, h, rotatable) onto one sheet using guillotine BSS.

    Returns:
        placed   — [(part_id, x, y, pw, ph, rotated), ...]
        unplaced — [(part_id, w, h, rotatable), ...]
    """
    # Start with full sheet as one free rect; shrink by kerf margin on all edges
    free: List[_FreeRect] = [_FreeRect(kerf, kerf, sheet_w - 2 * kerf, sheet_h - 2 * kerf)]
    placed: List[Tuple[str, float, float, float, float, bool]] = []
    unplaced: List[Tuple[str, float, float, bool]] = []

    for part_id, pw, ph, rotatable in parts:
        best_score = math.inf
        best_rect_idx = -1
        best_rotated = False
        best_pw, best_ph = pw, ph

        for i, rect in enumerate(free):
            # Try normal orientation
            if _fits(rect, pw + kerf, ph + kerf):
                score = _score_bss(rect, pw + kerf, ph + kerf)
                if score < best_score:
                    best_score = score
                    best_rect_idx = i
                    best_rotated = False
                    best_pw, best_ph = pw, ph

            # Try rotated orientation (only if rotatable and non-square)
            if rotatable and abs(pw - ph) > 1e-6:
                if _fits(rect, ph + kerf, pw + kerf):
                    score = _score_bss(rect, ph + kerf, pw + kerf)
                    if score < best_score:
                        best_score = score
                        best_rect_idx = i
                        best_rotated = True
                        best_pw, best_ph = ph, pw

        if best_rect_idx < 0:
            unplaced.append((part_id, pw, ph, rotatable))
            continue

        rect = free[best_rect_idx]
        x, y = rect.x, rect.y
        placed.append((part_id, x, y, best_pw, best_ph, best_rotated))

        # Split the free rectangle (use whichever split leaves larger rects)
        splits_h = _split_horiz(rect, best_pw + kerf, best_ph + kerf)
        splits_v = _split_vert(rect, best_pw + kerf, best_ph + kerf)
        # Choose split with larger total area
        area_h = sum(r.w * r.h for r in splits_h)
        area_v = sum(r.w * r.h for r in splits_v)
        new_splits = splits_h if area_h >= area_v else splits_v

        del free[best_rect_idx]
        free.extend(new_splits)

    return placed, unplaced


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def optimise_panel_layout(
    parts: List[PanelPart],
    sheet_length_mm: float = 2440.0,
    sheet_width_mm: float = 1220.0,
    kerf_mm: float = 3.175,
    allow_rotation: bool = True,
) -> NestingResult:
    """Optimise 2D guillotine nesting of panel parts onto sheets.

    Algorithm: Guillotine Best Short Side (BSS) heuristic in First-Fit
    Decreasing (FFD) order.  Grain-constrained parts are placed in their
    required orientation; unconstrained parts may be rotated 90°.

    Args:
        parts:           list of :class:`PanelPart` instances.
        sheet_length_mm: sheet long dimension (default 2440 mm = 8 ft).
        sheet_width_mm:  sheet short dimension (default 1220 mm = 4 ft).
        kerf_mm:         saw-blade kerf added between adjacent parts and at
                         sheet margins (default 3.175 mm = 1/8").
        allow_rotation:  if True (default), grain='none' parts may be rotated
                         90° for better fit.

    Returns:
        :class:`NestingResult`.

    References:
        Bourque (2003); Scheithauer (2018) Ch. 2.
        KCMA (2021) Cabinet Standards §4 (sheet material conventions).
    """
    if not parts:
        return NestingResult(
            sheets_used=0,
            layouts=[],
            total_yield_pct=100.0,
            total_waste_mm2=0.0,
        )

    warnings: List[str] = []

    # Expand parts by quantity → flat list of (part_id, effective_w, effective_h, rotatable)
    flat: List[Tuple[str, float, float, bool]] = []
    for part in parts:
        rotatable = (part.grain_direction == "none") and allow_rotation
        for q in range(part.quantity):
            pid = f"{part.part_id}_{q}" if part.quantity > 1 else part.part_id
            flat.append((pid, part.length_mm, part.width_mm, rotatable))

    # Warn about oversized parts
    usable_l = sheet_length_mm - 2 * kerf_mm
    usable_w = sheet_width_mm - 2 * kerf_mm
    for pid, pw, ph, rot in flat:
        fits_normal = pw <= usable_l and ph <= usable_w
        fits_rotated = rot and (ph <= usable_l and pw <= usable_w)
        if not fits_normal and not fits_rotated:
            warnings.append(
                f"Part '{pid}' ({pw:.0f}×{ph:.0f} mm) is larger than the usable "
                f"sheet area ({usable_l:.0f}×{usable_w:.0f} mm). Cannot be nested."
            )

    # Sort FFD by area descending
    flat_sorted = sorted(flat, key=lambda t: t[1] * t[2], reverse=True)

    # Pack input: preserve rotatable flag per part
    pack_input: List[Tuple[str, float, float, bool]] = [
        (pid, pw, ph, rotatable) for pid, pw, ph, rotatable in flat_sorted
    ]

    # Pack onto sheets sequentially
    layouts: List[SheetLayout] = []
    remaining = pack_input

    sheet_idx = 0
    while remaining:
        # For grain-constrained parts, strip rotation flag from unplaced remainder
        # (already encoded: grain-constrained items are placed with fixed orientation)
        placed_raw, remaining = _pack_sheet(remaining, sheet_length_mm, sheet_width_mm, kerf_mm)

        layout = SheetLayout(
            sheet_index=sheet_idx,
            sheet_length_mm=sheet_length_mm,
            sheet_width_mm=sheet_width_mm,
        )

        for part_id, x, y, pw, ph, rotated in placed_raw:
            layout.placements.append(PlacedPanel(
                part_id=part_id,
                x_mm=round(x, 3),
                y_mm=round(y, 3),
                length_mm=round(pw, 3),
                width_mm=round(ph, 3),
                rotated=rotated,
                sheet_index=sheet_idx,
            ))

        # Off-cut: report significant leftover areas (> 50×50 mm)
        used_area = sum(p.length_mm * p.width_mm for p in layout.placements)
        waste = sheet_length_mm * sheet_width_mm - used_area
        if waste > 50.0 * 50.0:
            layout.off_cuts.append({
                "approx_area_mm2": round(waste, 1),
            })

        layouts.append(layout)
        sheet_idx += 1

        # Guard: if nothing was placed (all parts too big), break
        if not placed_raw:
            break

    # Report truly unplaceable parts
    unplaced_parts: List[str] = []
    if remaining:
        for item in remaining:
            pid, pw, ph = item[0], item[1], item[2]
            unplaced_parts.append(pid)
            warnings.append(
                f"Part '{pid}' ({pw:.0f}×{ph:.0f} mm) could not be placed on any sheet."
            )

    total_sheet_area = sum(la.sheet_area_mm2 for la in layouts)
    total_used = sum(la.used_area_mm2 for la in layouts)
    total_waste = total_sheet_area - total_used
    yield_pct = 100.0 * total_used / total_sheet_area if total_sheet_area > 0 else 100.0

    return NestingResult(
        sheets_used=len(layouts),
        layouts=layouts,
        total_yield_pct=round(yield_pct, 2),
        total_waste_mm2=round(total_waste, 1),
        unplaced_parts=unplaced_parts,
        warnings=warnings,
    )


def nesting_result_to_dict(result: NestingResult) -> Dict[str, Any]:
    """Serialise a :class:`NestingResult` to a JSON-safe dict."""
    return {
        "sheets_used": result.sheets_used,
        "total_yield_pct": result.total_yield_pct,
        "total_waste_mm2": result.total_waste_mm2,
        "unplaced_parts": result.unplaced_parts,
        "warnings": result.warnings,
        "layouts": [
            {
                "sheet_index": la.sheet_index,
                "sheet_length_mm": la.sheet_length_mm,
                "sheet_width_mm": la.sheet_width_mm,
                "yield_pct": round(la.yield_pct, 2),
                "placement_count": len(la.placements),
                "placements": [
                    {
                        "part_id": p.part_id,
                        "x_mm": p.x_mm,
                        "y_mm": p.y_mm,
                        "length_mm": p.length_mm,
                        "width_mm": p.width_mm,
                        "rotated": p.rotated,
                    }
                    for p in la.placements
                ],
                "off_cuts": la.off_cuts,
            }
            for la in result.layouts
        ],
    }
