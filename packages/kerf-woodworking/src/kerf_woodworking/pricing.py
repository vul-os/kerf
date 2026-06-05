"""pricing.py — Material, hardware, and labour cost rollup for woodworking projects.

Provides a parametric cost estimator for cabinet and furniture projects:

    estimate_project_cost(...)  — full rollup: material + hardware + labour
    material_cost(...)          — sheet goods + solid lumber cost
    hardware_cost(...)          — hinges, drawer slides, knobs, shelf pins, etc.
    labour_cost(...)            — labour hours × rate for each phase

References:
    KCMA (2021). Cabinet Standards §8: Cost estimation conventions.
    Kitchen & Bath Business (2024). Cabinet pricing benchmarks.
    Woodworkers Guild of America (2024). Shop rate guide.
    RS Means (2024). Architectural Woodwork cost data.

HONEST: All prices are approximate 2024 US retail / wholesale values.
Regional variation ±30% is typical. Validate against local supplier quotes
before using in binding estimates.

All monetary values are in USD unless noted.
All dimensions are in millimetres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Sheet material price database (USD per 4×8 ft sheet, approximate 2024 retail)
# ---------------------------------------------------------------------------

SHEET_COST_USD: Dict[str, float] = {
    # Hardwood plywood (home centre / cabinet dealer)
    'oak_3/4"':            85.0,
    'oak_1/2"':            65.0,
    'oak_1/4"':            38.0,
    'white_oak_3/4"':      95.0,
    'maple_3/4"':          90.0,
    'maple_1/2"':          70.0,
    'walnut_3/4"':        145.0,
    'cherry_3/4"':        110.0,
    # Construction/shop plywood
    'birch_ply_3/4"':      55.0,
    'birch_ply_1/2"':      42.0,
    'birch_ply_1/4"':      28.0,
    'pine_ply_3/4"':       48.0,
    'pine_ply_1/2"':       36.0,
    # MDF / particleboard
    'mdf_3/4"':            40.0,
    'mdf_1/2"':            30.0,
    'mdf_1/4"':            20.0,
    'particleboard_3/4"':  22.0,
    # Melamine / thermofoil
    'melamine_3/4"':       48.0,
    'melamine_1/2"':       38.0,
    'thermoplastic_3/4"':  60.0,
    # Solid core
    'mdo_3/4"':            65.0,
}

_DEFAULT_SHEET_COST_USD = 60.0   # fallback

# Sheet dimensions: standard 4 ft × 8 ft (1220 × 2440 mm)
_SHEET_AREA_MM2 = 1220.0 * 2440.0

# Edge banding (USD per lineal metre, approximate 2024)
EDGE_BANDING_COST_USD_PER_M: Dict[str, float] = {
    'pvc_white':       0.85,
    'pvc_black':       0.95,
    'pvc_wood_grain':  1.10,
    'oak_veneer':      1.90,
    'maple_veneer':    2.10,
    'walnut_veneer':   2.60,
    'cherry_veneer':   2.40,
    'abs_white':       0.90,
    'none':            0.0,
}

# Solid hardwood lumber (USD per board-foot, rough sawn 2024 retail)
SOLID_LUMBER_COST_USD_PER_BF: Dict[str, float] = {
    'oak_red':    8.5,
    'oak_white':  9.0,
    'maple':      7.5,
    'cherry':    12.0,
    'walnut':    18.0,
    'pine':       4.0,
    'poplar':     5.0,
    'ash':        8.0,
    'mahogany':  14.0,
}


# ---------------------------------------------------------------------------
# Hardware price database (USD per unit, approximate 2024)
# ---------------------------------------------------------------------------

HARDWARE_UNIT_COST_USD: Dict[str, float] = {
    # Hinges (per hinge)
    'hinge_blum_clip_top':        6.50,
    'hinge_blum_inserta':         7.25,
    'hinge_grass_tiomos':         5.90,
    'hinge_salice_213':           5.50,
    'hinge_concealed_generic':    3.50,
    # Drawer slides (per pair)
    'drawer_slide_blum_movento':  35.0,
    'drawer_slide_blum_tandem':   42.0,
    'drawer_slide_king_slide':    18.0,
    'drawer_slide_grass_nova':    28.0,
    'drawer_slide_sidemount_22in': 14.0,
    'drawer_slide_generic':       10.0,
    # Shelf pins (per pack of 4)
    'shelf_pins_5mm_x4':          1.50,
    # Knobs and pulls (per unit)
    'knob_round_30mm':            2.50,
    'knob_bar_96mm':              4.50,
    'knob_bar_128mm':             5.00,
    'knob_bar_160mm':             5.50,
    'pull_cup_bin':               3.00,
    'pull_bar_96mm':              6.00,
    'pull_bar_128mm':             6.50,
    'pull_bar_160mm':             7.00,
    # Fasteners (per pack of 100)
    'pocket_screws_25mm_x100':    8.00,
    'pocket_screws_32mm_x100':    8.50,
    'euro_screws_7x50_x100':     12.00,
    'wood_screws_4x25_x100':      6.00,
    'confirmat_7x50_x100':       11.00,
    # Cam locks / RTA (per unit)
    'cam_lock_15mm':              0.85,
    'dowel_8x40_each':            0.15,
    # Lazy susan bearing (each)
    'lazy_susan_12in':           12.00,
    'lazy_susan_18in':           18.00,
    # Soft-close dampers (per pair)
    'soft_close_door_pair':       4.00,
    # Toe kick (per metre)
    'toe_kick_pvc_per_m':         3.50,
}

_DEFAULT_HARDWARE_COST_USD = 5.0   # fallback per unit


# ---------------------------------------------------------------------------
# Labour phase definitions (hours per cabinet unit, typical)
# ---------------------------------------------------------------------------

# Base hours per cabinet type, per phase (rough estimates for small shop)
# Reference: Kitchen & Bath Business (2024); Woodworkers Guild of America (2024)
_LABOUR_BASE_HOURS: Dict[str, Dict[str, float]] = {
    "base": {
        "material_prep":  0.5,   # dimension, joint prep
        "assembly":       1.0,   # pocket screw / dado assembly
        "hanging_doors":  0.3,   # 2 doors, hinge install
        "drawer_install": 0.4,   # 1 drawer, runner + face
        "finishing":      0.5,   # sanding + one coat
        "install":        0.5,   # site installation
    },
    "wall": {
        "material_prep":  0.4,
        "assembly":       0.8,
        "hanging_doors":  0.3,
        "drawer_install": 0.0,   # wall cabs typically no drawers
        "finishing":      0.4,
        "install":        0.4,
    },
    "tall": {
        "material_prep":  0.7,
        "assembly":       1.5,
        "hanging_doors":  0.5,
        "drawer_install": 0.6,
        "finishing":      0.7,
        "install":        0.7,
    },
}

_DEFAULT_LABOUR_HOURS = _LABOUR_BASE_HOURS["base"]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class MaterialLineItem:
    """One line in the material cost breakdown."""
    description: str
    material_key: str
    quantity: float       # sheets or board-feet
    unit: str             # 'sheet' | 'bf' | 'm' (edge banding)
    unit_cost_usd: float
    total_cost_usd: float


@dataclass
class HardwareLineItem:
    """One line in the hardware cost breakdown."""
    description: str
    hardware_key: str
    quantity: int
    unit_cost_usd: float
    total_cost_usd: float


@dataclass
class LabourLineItem:
    """One line in the labour cost breakdown."""
    phase: str
    hours: float
    rate_usd_per_hr: float
    total_cost_usd: float


@dataclass
class CostEstimate:
    """Full cost rollup for a woodworking project.

    HONEST: Estimates based on 2024 US retail pricing and typical small-shop
    labour rates. Regional variation ±30%. Validate against local suppliers.
    Ref: KCMA 2021 §8; RS Means (2024).
    """
    material_lines: List[MaterialLineItem] = field(default_factory=list)
    hardware_lines: List[HardwareLineItem] = field(default_factory=list)
    labour_lines: List[LabourLineItem] = field(default_factory=list)
    subtotal_material_usd: float = 0.0
    subtotal_hardware_usd: float = 0.0
    subtotal_labour_usd: float = 0.0
    overhead_pct: float = 15.0    # overhead and profit percentage
    overhead_usd: float = 0.0
    total_usd: float = 0.0
    honest_caveat: str = (
        "ESTIMATE: 2024 US approximate retail/wholesale pricing. "
        "Regional variation ±30%. Validate against local supplier quotes. "
        "Ref: KCMA 2021 §8; RS Means (2024); Woodworkers Guild (2024)."
    )


# ---------------------------------------------------------------------------
# Sub-estimators
# ---------------------------------------------------------------------------

def material_cost(
    sheet_items: List[Dict[str, Any]],
    edge_banding_items: Optional[List[Dict[str, Any]]] = None,
    solid_lumber_items: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[MaterialLineItem], float]:
    """Compute material cost from sheet goods, edge banding, and solid lumber.

    Args:
        sheet_items: list of dicts:
            {material: str, sheets: float}
        edge_banding_items: list of dicts:
            {banding_type: str, lineal_m: float}
        solid_lumber_items: list of dicts:
            {species: str, board_feet: float}

    Returns:
        (lines: list[MaterialLineItem], total_usd: float)
    """
    lines: List[MaterialLineItem] = []
    total = 0.0

    for item in sheet_items:
        mat = item.get("material", "")
        n = float(item.get("sheets", 1))
        unit_cost = SHEET_COST_USD.get(mat, _DEFAULT_SHEET_COST_USD)
        line_total = n * unit_cost
        lines.append(MaterialLineItem(
            description=f"Sheet: {mat}",
            material_key=mat,
            quantity=n,
            unit="sheet",
            unit_cost_usd=unit_cost,
            total_cost_usd=round(line_total, 2),
        ))
        total += line_total

    for item in (edge_banding_items or []):
        bt = item.get("banding_type", "pvc_white")
        metres = float(item.get("lineal_m", 0.0))
        unit_cost = EDGE_BANDING_COST_USD_PER_M.get(bt, 1.0)
        line_total = metres * unit_cost
        lines.append(MaterialLineItem(
            description=f"Edge banding: {bt}",
            material_key=bt,
            quantity=metres,
            unit="m",
            unit_cost_usd=unit_cost,
            total_cost_usd=round(line_total, 2),
        ))
        total += line_total

    for item in (solid_lumber_items or []):
        species = item.get("species", "oak_red")
        bf = float(item.get("board_feet", 0.0))
        unit_cost = SOLID_LUMBER_COST_USD_PER_BF.get(species, 8.0)
        line_total = bf * unit_cost
        lines.append(MaterialLineItem(
            description=f"Solid lumber: {species}",
            material_key=species,
            quantity=bf,
            unit="bf",
            unit_cost_usd=unit_cost,
            total_cost_usd=round(line_total, 2),
        ))
        total += line_total

    return lines, round(total, 2)


def hardware_cost(
    hardware_items: List[Dict[str, Any]],
) -> Tuple[List[HardwareLineItem], float]:
    """Compute hardware cost.

    Args:
        hardware_items: list of dicts:
            {hardware_key: str, quantity: int, description: str (optional)}

    Returns:
        (lines: list[HardwareLineItem], total_usd: float)
    """
    lines: List[HardwareLineItem] = []
    total = 0.0
    for item in hardware_items:
        key = item.get("hardware_key", "")
        qty = int(item.get("quantity", 1))
        unit_cost = HARDWARE_UNIT_COST_USD.get(key, _DEFAULT_HARDWARE_COST_USD)
        desc = item.get("description") or key.replace("_", " ").title()
        line_total = qty * unit_cost
        lines.append(HardwareLineItem(
            description=desc,
            hardware_key=key,
            quantity=qty,
            unit_cost_usd=unit_cost,
            total_cost_usd=round(line_total, 2),
        ))
        total += line_total
    return lines, round(total, 2)


def labour_cost(
    cabinet_counts: Dict[str, int],
    rate_usd_per_hr: float = 75.0,
    multipliers: Optional[Dict[str, float]] = None,
) -> Tuple[List[LabourLineItem], float]:
    """Compute labour cost from cabinet counts and shop rate.

    Args:
        cabinet_counts: {cabinet_type: count}, e.g. {'base': 5, 'wall': 4}.
        rate_usd_per_hr: hourly shop rate (USD). Default $75/hr (small shop 2024).
        multipliers: optional phase multipliers, e.g. {'finishing': 1.5} for
                     painted finish vs. clear coat.

    Returns:
        (lines: list[LabourLineItem], total_usd: float)

    Reference: Woodworkers Guild of America (2024) shop-rate benchmarks.
    """
    mults = multipliers or {}
    phase_totals: Dict[str, float] = {}

    for cab_type, count in cabinet_counts.items():
        base_hours = _LABOUR_BASE_HOURS.get(cab_type, _DEFAULT_LABOUR_HOURS)
        for phase, hrs_per_unit in base_hours.items():
            mult = mults.get(phase, 1.0)
            phase_totals[phase] = phase_totals.get(phase, 0.0) + hrs_per_unit * count * mult

    lines: List[LabourLineItem] = []
    total = 0.0
    for phase, hrs in sorted(phase_totals.items()):
        line_cost = hrs * rate_usd_per_hr
        lines.append(LabourLineItem(
            phase=phase,
            hours=round(hrs, 2),
            rate_usd_per_hr=rate_usd_per_hr,
            total_cost_usd=round(line_cost, 2),
        ))
        total += line_cost

    return lines, round(total, 2)


# ---------------------------------------------------------------------------
# Full project estimator
# ---------------------------------------------------------------------------

def estimate_project_cost(
    sheet_items: Optional[List[Dict[str, Any]]] = None,
    edge_banding_items: Optional[List[Dict[str, Any]]] = None,
    solid_lumber_items: Optional[List[Dict[str, Any]]] = None,
    hardware_items: Optional[List[Dict[str, Any]]] = None,
    cabinet_counts: Optional[Dict[str, int]] = None,
    labour_rate_usd_per_hr: float = 75.0,
    labour_multipliers: Optional[Dict[str, float]] = None,
    overhead_pct: float = 15.0,
) -> CostEstimate:
    """Full material + hardware + labour cost rollup.

    Args:
        sheet_items:           list of {material, sheets}.
        edge_banding_items:    list of {banding_type, lineal_m}.
        solid_lumber_items:    list of {species, board_feet}.
        hardware_items:        list of {hardware_key, quantity, description?}.
        cabinet_counts:        {cabinet_type: count} for labour estimate.
        labour_rate_usd_per_hr: shop hourly rate (default $75/hr).
        labour_multipliers:    phase multipliers for labour hours.
        overhead_pct:          overhead + profit as % of direct costs (default 15%).

    Returns:
        :class:`CostEstimate`.

    HONEST: All prices approximate 2024 US values. Ref: KCMA 2021 §8.
    """
    mat_lines, mat_total = material_cost(
        sheet_items or [],
        edge_banding_items,
        solid_lumber_items,
    )

    hw_lines, hw_total = hardware_cost(hardware_items or [])

    lab_lines, lab_total = labour_cost(
        cabinet_counts or {},
        rate_usd_per_hr=labour_rate_usd_per_hr,
        multipliers=labour_multipliers,
    )

    direct_total = mat_total + hw_total + lab_total
    overhead = direct_total * overhead_pct / 100.0
    grand_total = direct_total + overhead

    return CostEstimate(
        material_lines=mat_lines,
        hardware_lines=hw_lines,
        labour_lines=lab_lines,
        subtotal_material_usd=mat_total,
        subtotal_hardware_usd=hw_total,
        subtotal_labour_usd=lab_total,
        overhead_pct=overhead_pct,
        overhead_usd=round(overhead, 2),
        total_usd=round(grand_total, 2),
    )


def cost_estimate_to_dict(estimate: CostEstimate) -> Dict[str, Any]:
    """Serialise a :class:`CostEstimate` to a JSON-safe dict."""
    return {
        "subtotal_material_usd": estimate.subtotal_material_usd,
        "subtotal_hardware_usd": estimate.subtotal_hardware_usd,
        "subtotal_labour_usd": estimate.subtotal_labour_usd,
        "overhead_pct": estimate.overhead_pct,
        "overhead_usd": estimate.overhead_usd,
        "total_usd": estimate.total_usd,
        "honest_caveat": estimate.honest_caveat,
        "material_lines": [
            {
                "description": l.description,
                "quantity": l.quantity,
                "unit": l.unit,
                "unit_cost_usd": l.unit_cost_usd,
                "total_cost_usd": l.total_cost_usd,
            }
            for l in estimate.material_lines
        ],
        "hardware_lines": [
            {
                "description": l.description,
                "quantity": l.quantity,
                "unit_cost_usd": l.unit_cost_usd,
                "total_cost_usd": l.total_cost_usd,
            }
            for l in estimate.hardware_lines
        ],
        "labour_lines": [
            {
                "phase": l.phase,
                "hours": l.hours,
                "rate_usd_per_hr": l.rate_usd_per_hr,
                "total_cost_usd": l.total_cost_usd,
            }
            for l in estimate.labour_lines
        ],
    }
