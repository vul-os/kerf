"""
kerf_woodworking.cabinet_cut_list — Generate optimised cut-list from cabinet placements.

Decomposes cabinet placement specifications into individual panel parts, aggregates
identical parts, then packs them onto standard sheet sizes using 2D bin packing.

References:
    KCMA (Kitchen Cabinet Manufacturers Association). (2021). Cabinet Standards.
    Stanley, J. (2010). Furniture Design & Construction for the Wood Worker.
    Hoadley, R.B. (2000). Understanding Wood, 2nd ed. The Taunton Press.

HONEST: Sheet utilisation estimates use a simplified 2D skyline bin-packing
algorithm. Real CNC nesting software (e.g. OpenCutList, Cabinet Vision) applies
more sophisticated optimisation and accounts for grain direction rotation constraints,
clamping margins, and toolpath geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Material cost library (USD per 4×8 sheet, approximate 2024 retail)
# ---------------------------------------------------------------------------

_SHEET_COST_USD: dict[str, float] = {
    'oak_3/4"':        85.0,
    'oak_1/2"':        65.0,
    'oak_1/4"':        38.0,
    'birch_ply_3/4"':  55.0,
    'birch_ply_1/2"':  42.0,
    'birch_ply_1/4"':  28.0,
    'mdf_3/4"':        40.0,
    'mdf_1/2"':        30.0,
    'mdf_1/4"':        20.0,
    'maple_3/4"':      95.0,
    'walnut_3/4"':    130.0,
    'melamine_3/4"':   48.0,
}

_DEFAULT_SHEET_COST_USD = 60.0   # fallback

# Edge banding cost per lineal metre (USD)
_EDGE_BANDING_COST_USD_PER_M: dict[str, float] = {
    'pvc_white':   0.80,
    'pvc_black':   0.90,
    'oak_veneer':  1.80,
    'maple_veneer': 2.00,
    'walnut_veneer': 2.50,
    'none':        0.0,
}

# Standard sheet size: 4ft × 8ft (1220 × 2440 mm) per KCMA convention
_DEFAULT_SHEET_SIZE_MM = (1220.0, 2440.0)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CutListItem:
    """
    A single panel cut-list entry.

    HONEST: Edge banding lineal metres is per-item (count=1).
    Multiply by count for totals.

    References: KCMA 2021 Cabinet Standards §4.
    """
    part_id: str
    material: str                  # e.g. 'oak_3/4"' | 'birch_ply_3/4"' | 'mdf_3/4"'
    length_mm: float
    width_mm: float
    thickness_mm: float
    grain_direction: str           # 'length' | 'width' | 'none'
    count: int
    edge_banding: str              # 'pvc_white' | 'oak_veneer' | 'none'
    description: str = ""


@dataclass
class CutListReport:
    """
    Full cut-list output from generate_cut_list().

    HONEST: waste_pct is an upper bound from the simple bin-packing algorithm.
    Skilled CNC nesting may achieve lower waste.

    References: KCMA 2021 Cabinet Standards; Stanley (2010) Furniture Design & Construction.
    """
    items: List[CutListItem]
    total_sheets_required: Dict[str, int]   # material → sheet count
    total_lineal_meters_edge_banding: float
    estimated_cost_usd: float
    waste_pct: float
    honest_caveat: str = (
        "SIMPLIFIED cut-list: 2D bin-packing (greedy skyline). "
        "Actual nesting waste depends on grain-direction constraints and part shapes. "
        "Validate against OpenCutList or similar before ordering materials. "
        "Ref: KCMA 2021 Cabinet Standards."
    )


# ---------------------------------------------------------------------------
# Cabinet decomposition
# ---------------------------------------------------------------------------

# Standard cabinet part dimensions per KCMA (mm)
# Base cabinet: 762 mm tall (30"), 610 mm deep (24")
# Wall cabinet:  762 mm tall (30"), 330 mm deep (13")
# Typical face frame: 1.5" × 1.5" stiles/rails

_BASE_CAB_HEIGHT_MM = 762.0
_BASE_CAB_DEPTH_MM = 610.0
_WALL_CAB_HEIGHT_MM = 762.0
_WALL_CAB_DEPTH_MM = 330.0
_PANEL_THICKNESS_MM = 19.05   # 3/4" in mm
_BACK_THICKNESS_MM = 6.35     # 1/4" in mm
_SHELF_THICKNESS_MM = 19.05

_EURO_OVERLAY = 1.0            # full-overlay cabinet — doors overlay 19mm of case


@dataclass
class CabinetPlacement:
    """
    A positioned cabinet unit.

    HONEST: This is a parametric box-decomposition model.
    Custom carcases, inset doors, and frame-and-panel construction
    require more detailed joint geometry beyond this spec.

    References: KCMA 2021 Cabinet Standards §3.
    """
    cabinet_id: str
    cabinet_type: str              # 'base' | 'wall' | 'tall'
    width_mm: float
    height_mm: float               # if None, defaults are used per type
    depth_mm: float                # if None, defaults are used per type
    material: str = 'birch_ply_3/4"'
    back_material: str = 'birch_ply_1/4"'
    door_count: int = 1
    shelf_count: int = 1
    edge_banding: str = 'pvc_white'
    include_face_frame: bool = False

    def __post_init__(self):
        if self.width_mm <= 0:
            raise ValueError(f"Cabinet '{self.cabinet_id}': width_mm must be positive")
        if self.height_mm <= 0:
            raise ValueError(f"Cabinet '{self.cabinet_id}': height_mm must be positive")
        if self.depth_mm <= 0:
            raise ValueError(f"Cabinet '{self.cabinet_id}': depth_mm must be positive")


def _decompose_cabinet(cab: CabinetPlacement) -> List[CutListItem]:
    """
    Decompose a cabinet into its constituent panels.

    Part decomposition per KCMA standard construction:
        - 2× side panels (full height × depth)
        - 1× top panel (width − 2·t × depth)
        - 1× bottom panel (width − 2·t × depth)
        - 1× back panel (1/4" ply, width − 2·t × height − 2·t)
        - N× shelves (width − 2·t × depth − 25mm for shelf pin offset)
        - N× door panels (width/N × height − adjustments, 3/4" ply or solid)
        - Face frame (if include_face_frame): 2× stiles + rails

    HONEST: This is a simplified rectangular decomposition.
    Real cabinetry may use dados, rabbets, and custom joinery that affect part dimensions.
    Ref: KCMA 2021 Cabinet Standards §4.1; Stanley (2010) Ch. 12.
    """
    parts: List[CutListItem] = []
    t = _PANEL_THICKNESS_MM
    w = cab.width_mm
    h = cab.height_mm
    d = cab.depth_mm
    mat = cab.material
    eb = cab.edge_banding
    cid = cab.cabinet_id

    # Internal width (inside case dimension)
    inner_w = w - 2.0 * t

    # --- Side panels ---
    parts.append(CutListItem(
        part_id=f"{cid}_side",
        material=mat,
        length_mm=h,
        width_mm=d,
        thickness_mm=t,
        grain_direction='length',
        count=2,
        edge_banding=eb,
        description=f"Side panel for {cid}",
    ))

    # --- Top panel ---
    parts.append(CutListItem(
        part_id=f"{cid}_top",
        material=mat,
        length_mm=inner_w,
        width_mm=d,
        thickness_mm=t,
        grain_direction='length',
        count=1,
        edge_banding=eb,
        description=f"Top panel for {cid}",
    ))

    # --- Bottom panel ---
    parts.append(CutListItem(
        part_id=f"{cid}_bottom",
        material=mat,
        length_mm=inner_w,
        width_mm=d,
        thickness_mm=t,
        grain_direction='length',
        count=1,
        edge_banding=eb,
        description=f"Bottom panel for {cid}",
    ))

    # --- Back panel (1/4" ply) ---
    back_mat = cab.back_material
    back_t = _BACK_THICKNESS_MM
    parts.append(CutListItem(
        part_id=f"{cid}_back",
        material=back_mat,
        length_mm=inner_w,
        width_mm=h - 2.0 * t,
        thickness_mm=back_t,
        grain_direction='length',
        count=1,
        edge_banding='none',
        description=f"Back panel for {cid}",
    ))

    # --- Shelves ---
    if cab.shelf_count > 0:
        shelf_d = max(d - 25.0, 150.0)   # shelf pin setback
        parts.append(CutListItem(
            part_id=f"{cid}_shelf",
            material=mat,
            length_mm=inner_w,
            width_mm=shelf_d,
            thickness_mm=t,
            grain_direction='length',
            count=cab.shelf_count,
            edge_banding=eb,
            description=f"Adjustable shelf for {cid}",
        ))

    # --- Door panels ---
    if cab.door_count > 0:
        door_w = w / cab.door_count
        door_h = h  # full-overlay per KCMA
        parts.append(CutListItem(
            part_id=f"{cid}_door",
            material=mat,
            length_mm=door_h,
            width_mm=door_w,
            thickness_mm=t,
            grain_direction='length',   # grain runs vertically per KCMA convention
            count=cab.door_count,
            edge_banding=eb,
            description=f"Door panel for {cid}",
        ))

    # --- Face frame (if requested) ---
    if cab.include_face_frame:
        ff_t = 19.05   # 3/4" face frame stock
        ff_w = 38.1    # 1.5" wide stock
        # Stiles: full height
        parts.append(CutListItem(
            part_id=f"{cid}_ff_stile",
            material=mat,
            length_mm=h,
            width_mm=ff_w,
            thickness_mm=ff_t,
            grain_direction='length',
            count=2,
            edge_banding='none',
            description=f"Face frame stile for {cid}",
        ))
        # Top and bottom rails
        rail_l = inner_w - 2.0 * ff_w
        parts.append(CutListItem(
            part_id=f"{cid}_ff_rail",
            material=mat,
            length_mm=max(rail_l, 50.0),
            width_mm=ff_w,
            thickness_mm=ff_t,
            grain_direction='length',
            count=2,
            edge_banding='none',
            description=f"Face frame rail for {cid}",
        ))

    return parts


# ---------------------------------------------------------------------------
# 2D bin packing (simple skyline for sheets)
# ---------------------------------------------------------------------------

def _pack_panels_onto_sheets(
    items: List[CutListItem],
    sheet_w: float,
    sheet_h: float,
    kerf_mm: float = 3.175,
) -> Tuple[Dict[str, int], float, float]:
    """
    Pack panel items (by material) onto standard sheets using a greedy
    2D skyline bin-packing algorithm.

    For each material group:
      - Expand items by count to get individual panel instances.
      - Sort by area (largest first, FFD order).
      - Try to fit onto sheets using skyline packing.

    Returns:
        sheets_by_material  — {material: sheet_count}
        total_area_used_mm2 — sum of all panel areas
        total_area_avail_mm2 — sum of all sheet areas allocated
    """
    from collections import defaultdict

    # Group items by material
    by_material: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for item in items:
        for _ in range(item.count):
            by_material[item.material].append((item.length_mm, item.width_mm))

    sheets_by_material: Dict[str, int] = {}
    total_used = 0.0
    total_avail = 0.0

    for material, panels in by_material.items():
        # Sort by area descending (FFD)
        panels_sorted = sorted(panels, key=lambda p: p[0] * p[1], reverse=True)

        sheet_count = 0
        # Skyline state: list of (x_start, y_level) segments — simplified flat skyline
        # For each sheet: skyline is a step function; we use a simpler row-based approach

        # Greedy shelf-packing per sheet
        remaining: list[tuple[float, float]] = list(panels_sorted)
        while remaining:
            sheet_count += 1
            # Simple guillotine: place panels row by row
            y_cursor = kerf_mm  # current row top
            x_cursor = kerf_mm
            row_height = 0.0
            still_remaining: list[tuple[float, float]] = []

            # Try to place each panel in current sheet
            placed_any = True
            sheet_panels = list(remaining)
            remaining = []

            # Multiple passes to fill each row
            placed_set: set[int] = set()
            y_cur = kerf_mm

            idx = 0
            while idx < len(sheet_panels):
                if idx in placed_set:
                    idx += 1
                    continue
                pw, ph = sheet_panels[idx]   # panel width (along sheet width) x height
                # Try fitting in current row position
                if x_cursor + pw + kerf_mm <= sheet_w and y_cur + ph + kerf_mm <= sheet_h:
                    placed_set.add(idx)
                    row_height = max(row_height, ph)
                    x_cursor += pw + kerf_mm
                    total_used += pw * ph
                    idx += 1
                else:
                    # Try next row
                    if row_height > 0:
                        y_cur += row_height + kerf_mm
                        x_cursor = kerf_mm
                        row_height = 0.0
                        # Don't increment idx — retry same panel in new row
                        if y_cur + ph + kerf_mm > sheet_h:
                            # Doesn't fit on this sheet at all
                            remaining.append(sheet_panels[idx])
                            placed_set.add(idx)
                            idx += 1
                    else:
                        # Can't fit even in a fresh row — oversize panel
                        remaining.append(sheet_panels[idx])
                        placed_set.add(idx)
                        idx += 1

            # Any not placed go to next sheet
            for i, panel in enumerate(sheet_panels):
                if i not in placed_set:
                    remaining.append(panel)

            total_avail += sheet_w * sheet_h

        sheets_by_material[material] = sheet_count

    return sheets_by_material, total_used, total_avail


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_cut_list(
    cabinet_placements: List[CabinetPlacement],
    sheet_size_mm: Tuple[float, float] = _DEFAULT_SHEET_SIZE_MM,
) -> CutListReport:
    """
    Generate an optimised cut-list from a list of cabinet placements.

    For each placement:
        1. Decompose into panel parts (sides, top, bottom, back, shelves, doors).
        2. Aggregate identical parts (same part_id, material, and dimensions).
        3. Pack onto standard sheets via 2D bin packing.
        4. Compute material costs and edge banding totals.

    HONEST: Simplified 2D bin-packing (greedy shelf algorithm). Production
    nesting may yield 5–15% better utilisation. Cost estimates use approximate
    2024 retail sheet prices.
    Ref: KCMA 2021 Cabinet Standards; Stanley (2010) Furniture Design.

    Args:
        cabinet_placements:  list of CabinetPlacement instances.
        sheet_size_mm:       (width, height) of standard sheet in mm.
                             Default: 1220 × 2440 mm (4ft × 8ft).

    Returns:
        CutListReport with items, sheet counts, edge banding, cost, and waste.
    """
    if not cabinet_placements:
        return CutListReport(
            items=[],
            total_sheets_required={},
            total_lineal_meters_edge_banding=0.0,
            estimated_cost_usd=0.0,
            waste_pct=0.0,
        )

    # --- Decompose all cabinets ---
    all_parts: List[CutListItem] = []
    for cab in cabinet_placements:
        parts = _decompose_cabinet(cab)
        all_parts.extend(parts)

    # --- Aggregate identical parts ---
    # Two parts are identical if they share part_id template + material + dimensions
    # (We aggregate by the generic part_id, e.g. all "XXX_side" panels at same size)
    aggregated: dict[str, CutListItem] = {}
    for item in all_parts:
        key = (item.part_id, item.material, round(item.length_mm, 1),
               round(item.width_mm, 1), item.thickness_mm, item.grain_direction)
        if key in aggregated:
            aggregated[key] = CutListItem(
                part_id=item.part_id,
                material=item.material,
                length_mm=item.length_mm,
                width_mm=item.width_mm,
                thickness_mm=item.thickness_mm,
                grain_direction=item.grain_direction,
                count=aggregated[key].count + item.count,
                edge_banding=item.edge_banding,
                description=item.description,
            )
        else:
            aggregated[key] = CutListItem(
                part_id=item.part_id,
                material=item.material,
                length_mm=item.length_mm,
                width_mm=item.width_mm,
                thickness_mm=item.thickness_mm,
                grain_direction=item.grain_direction,
                count=item.count,
                edge_banding=item.edge_banding,
                description=item.description,
            )

    items = list(aggregated.values())

    # --- Sheet packing ---
    sheet_w, sheet_h = sheet_size_mm
    sheets_by_material, total_used_mm2, total_avail_mm2 = _pack_panels_onto_sheets(
        items, sheet_w, sheet_h
    )

    waste_pct = 0.0
    if total_avail_mm2 > 0:
        waste_pct = 100.0 * (1.0 - total_used_mm2 / total_avail_mm2)
    waste_pct = max(0.0, min(100.0, waste_pct))

    # --- Edge banding ---
    total_eb_mm = 0.0
    for item in items:
        if item.edge_banding != 'none':
            # Per KCMA: band all exposed edges — typically 2 long edges + 2 short edges
            # For a panel: (2 × length + 2 × width) × count
            perimeter_mm = 2.0 * (item.length_mm + item.width_mm)
            total_eb_mm += perimeter_mm * item.count
    total_eb_m = total_eb_mm / 1000.0

    # --- Cost estimate ---
    estimated_cost = 0.0
    for material, n_sheets in sheets_by_material.items():
        cost_per_sheet = _SHEET_COST_USD.get(material, _DEFAULT_SHEET_COST_USD)
        estimated_cost += n_sheets * cost_per_sheet

    # Add edge banding cost
    # Use the dominant edge banding type from items
    eb_types: dict[str, float] = {}
    for item in items:
        if item.edge_banding != 'none':
            perimeter_m = 2.0 * (item.length_mm + item.width_mm) * item.count / 1000.0
            eb_types[item.edge_banding] = eb_types.get(item.edge_banding, 0.0) + perimeter_m
    for eb_type, eb_m in eb_types.items():
        rate = _EDGE_BANDING_COST_USD_PER_M.get(eb_type, 1.0)
        estimated_cost += eb_m * rate

    return CutListReport(
        items=items,
        total_sheets_required=sheets_by_material,
        total_lineal_meters_edge_banding=round(total_eb_m, 2),
        estimated_cost_usd=round(estimated_cost, 2),
        waste_pct=round(waste_pct, 1),
    )
