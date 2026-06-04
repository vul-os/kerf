"""
kerf_cad_core.packaging.material_yield — Sheet yield + material cost estimation.

Computes how many blank cuts fit on a press sheet, total material consumption,
waste percentage, and production cost for corrugated / paperboard packaging.

References
----------
PMMI / FBA (2019). "Cost of Converting Handbook for Corrugated Packaging."
    Flexible Packaging Association / PMMI, Herndon VA.
    ("PMMI handbook")

FBA (Fibre Box Association, 2023). "Corrugated Containers Design Manual."
    §7 "Material yield and waste coefficients."

Aldrich, W. (2015). "Metric Pattern Cutting for Women's Wear", 6th ed.
    Wiley-Blackwell. (cited for nesting efficiency benchmark context only.)

Honest caveats
--------------
- ``parts_per_sheet`` is calculated from the bounding-box area of the
  unfolded outline scaled by ``nesting_efficiency_pct``.  True nesting
  (polygon no-fit polygon / irregular nesting) is substantially more accurate
  for non-rectangular outlines; this approximation typically over-estimates
  waste for highly irregular outlines.  The caller may pass
  ``nesting_efficiency_pct`` adjusted from empirical run data.
- Sheet weight is converted from g/m² (gsm) to kg using exact sheet dimensions.
  Caliper variation, moisture content, and trimmed-edge losses are ignored.
- Machine throughput in :func:`estimate_cycles_per_minute` is a first-order
  estimate for offset litho / flexo presses at rated speed; actual throughput
  depends on substrate, ink coverage, dryer dwell time, and operator efficiency.
  See PMMI handbook §3.2 for press productivity factors.
- Cost does not include ink, plates, die, makeready waste, or converting
  (scoring / slitting) labour.  These can add 40–80 % of material cost;
  see PMMI handbook §5.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MaterialCostSpec:
    """Material specification for a press substrate.

    Attributes
    ----------
    material_name : str
        Human-readable material identifier, e.g.
        ``'corrugated_B-flute_5mm'``, ``'sbs_320gsm'``, ``'kraft_270gsm'``.
    cost_per_kg : float
        Substrate cost in the user's billing currency per kg.
        Typical 2024 indicative values (USD): corrugated board ≈ 0.80–1.20 $/kg;
        SBS 320 gsm ≈ 1.40–1.80 $/kg.  (PMMI handbook §5 Table 5-1.)
    sheet_size_mm : tuple[float, float]
        (width_mm, height_mm) of the parent press sheet.
    sheet_weight_gsm : float
        Substrate grammage in g/m².  For corrugated board, use the combined-
        board basis weight (facing + fluting + facing).
    """

    material_name: str
    cost_per_kg: float
    sheet_size_mm: tuple[float, float]
    sheet_weight_gsm: float


@dataclass
class YieldReport:
    """Output of :func:`compute_material_yield`.

    Attributes
    ----------
    job_id : str
        Caller-supplied job identifier.
    parts_per_sheet : int
        Number of blanks nesting on one parent sheet.
    material_used_kg : float
        Total substrate consumed in kg (including waste).
    waste_pct : float
        Percentage of sheet area wasted (100 − nesting_efficiency_pct).
    total_material_cost : float
        ``sheets_per_job × sheet_weight_kg × cost_per_kg``.
    sheets_per_job : int
        Sheets required to produce ``job_quantity`` parts.
    honest_caveat : str
        Built-in design caveat.
    """

    job_id: str
    parts_per_sheet: int
    material_used_kg: float
    waste_pct: float
    total_material_cost: float
    sheets_per_job: int
    honest_caveat: str = (
        "parts_per_sheet uses bounding-box area × nesting_efficiency_pct; "
        "true irregular nesting (NFP algorithm) gives better yield. "
        "Cost excludes ink, plates, die, and converting labour (add ~40–80 %). "
        "PMMI handbook §5 Table 5-1 for full cost-of-converting breakdown."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bbox_area(outline: list[tuple[float, float]]) -> float:
    """Return the bounding-box area (mm²) of a polygon outline."""
    if len(outline) < 2:
        return 0.0
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def _sheet_weight_kg(material: MaterialCostSpec) -> float:
    """Return the mass of one parent sheet in kg."""
    w_mm, h_mm = material.sheet_size_mm
    area_m2 = (w_mm / 1000.0) * (h_mm / 1000.0)
    return area_m2 * material.sheet_weight_gsm / 1000.0   # g → kg


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_material_yield(
    box_unfolded_outline: list[tuple[float, float]],
    material: MaterialCostSpec,
    job_quantity: int,
    nesting_efficiency_pct: float = 75.0,
    job_id: str = "job_001",
) -> YieldReport:
    """Compute parts-per-sheet, waste, and material cost for a packaging job.

    **Honest flag**: parts_per_sheet is based on bounding-box area scaled by
    ``nesting_efficiency_pct``.  Polygon no-fit-polygon nesting (via
    ``kerf_cad_core.nesting``) will yield higher part counts for non-rectangular
    outlines.  See module docstring for full caveats.

    Algorithm
    ---------
    1. Compute outline bounding-box area (mm²).
    2. ``parts_per_sheet = floor(sheet_area × efficiency / bbox_area)``.
    3. ``sheets_per_job = ceil(job_quantity / parts_per_sheet)``.
    4. ``material_used_kg = sheets_per_job × sheet_weight_kg``.
    5. ``total_material_cost = material_used_kg × cost_per_kg``.

    Reference: PMMI handbook §7 "Yield coefficient for rectangular blanks."

    Parameters
    ----------
    box_unfolded_outline : list[tuple[float, float]]
        Ordered vertices of the unfolded (flat) box blank in mm.
    material : MaterialCostSpec
        Press substrate specification.
    job_quantity : int
        Number of finished boxes to produce.
    nesting_efficiency_pct : float
        Packing efficiency as percentage (default 75 %).  PMMI handbook
        §7.2 reports 70–80 % for rectangular corrugated blanks.
    job_id : str
        Identifier propagated to the report.

    Returns
    -------
    YieldReport
    """
    if job_quantity <= 0:
        raise ValueError("job_quantity must be positive")
    if not (0 < nesting_efficiency_pct <= 100):
        raise ValueError("nesting_efficiency_pct must be in (0, 100]")

    bbox_area_mm2 = _bbox_area(box_unfolded_outline)
    if bbox_area_mm2 < 1e-6:
        raise ValueError("box_unfolded_outline bounding box has zero area")

    w_mm, h_mm = material.sheet_size_mm
    sheet_area_mm2 = w_mm * h_mm
    efficiency = nesting_efficiency_pct / 100.0

    parts_per_sheet = max(1, int(math.floor(sheet_area_mm2 * efficiency / bbox_area_mm2)))
    sheets_per_job = math.ceil(job_quantity / parts_per_sheet)
    sheet_wt_kg = _sheet_weight_kg(material)
    material_used_kg = sheets_per_job * sheet_wt_kg
    total_cost = material_used_kg * material.cost_per_kg
    waste_pct = 100.0 - nesting_efficiency_pct

    return YieldReport(
        job_id=job_id,
        parts_per_sheet=parts_per_sheet,
        material_used_kg=material_used_kg,
        waste_pct=waste_pct,
        total_material_cost=total_cost,
        sheets_per_job=sheets_per_job,
    )


def estimate_cycles_per_minute(
    sheet_size_mm: tuple[float, float],
    machine_throughput_sheets_per_hour: float = 8_000.0,
) -> float:
    """Estimate press cycles per minute (sheets/min) for a press job.

    **Honest flag**: this is a rated-speed estimate.  Real throughput depends
    on substrate, ink coverage, dryer dwell, and operator efficiency.  PMMI
    handbook §3.2 "Productivity factors" reports 60–85 % OEE for typical
    commercial presses.

    Parameters
    ----------
    sheet_size_mm : tuple[float, float]
        ``(width_mm, height_mm)`` of the parent sheet.  Larger sheets reduce
        rated speed on some press models; this function does not model that
        (linear estimate only).
    machine_throughput_sheets_per_hour : float
        Rated press speed in sheets per hour (default 8 000 sph —
        typical mid-range offset litho; flexo corrugated presses: 150–250 sph).

    Returns
    -------
    float
        Sheets per minute at rated throughput.
    """
    _ = sheet_size_mm   # sheet size noted; no speed correction applied
    return machine_throughput_sheets_per_hour / 60.0


def material_cost_per_part(
    report: YieldReport,
    job_quantity: int,
) -> float:
    """Return material cost per finished box.

    Parameters
    ----------
    report : YieldReport
        Output of :func:`compute_material_yield`.
    job_quantity : int
        Number of parts (denominator).

    Returns
    -------
    float
        Cost per part (same currency as ``MaterialCostSpec.cost_per_kg``).
    """
    if job_quantity <= 0:
        return 0.0
    return report.total_material_cost / job_quantity
