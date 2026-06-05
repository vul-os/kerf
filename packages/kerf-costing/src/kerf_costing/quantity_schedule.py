"""
kerf_costing.quantity_schedule — BIM material quantity take-off by element type.

Material Quantity Take-off (QTO)
---------------------------------
A quantity schedule aggregates BIM elements by type (Wall, Slab, Column, Beam,
Window, Door, etc.) and reports dimensional quantities (area, volume, length,
count) together with material assignments and direct material cost estimates.

This is the AEC equivalent of a manufacturing BOM cost rollup: instead of
part_number × volume_mm³, we use element_type × area_m² / volume_m³.

Algorithm
---------
For each element in the BIM document:
  1. Classify by ``category`` field (Wall / Slab / Column / Beam / …).
  2. Extract geometry quantities:
       - area_m2    from ``area`` or ``params.area``
       - volume_m3  from ``volume`` or ``params.volume``
       - length_m   from ``length`` or ``params.length``
       - count      always 1 per element line
  3. Look up the element's material in ``material_unit_costs``.
  4. Compute line cost = volume_m3 × density_kg_m3 × price_usd_per_kg.

Cost model
----------
  unit_cost = volume_m3 × density_kg_m3 × price_usd_per_kg

Where ``density_kg_m3`` and ``price_usd_per_kg`` are taken from the caller-
supplied ``material_unit_costs`` map.  Both fields must be provided per
material; see ``MaterialCostSpec``.

Caveats
-------
- Waste / wastage factors are caller-supplied (default 0).
- No overhead, labour, or equipment cost — direct material only.
- Material must be explicitly provided in ``material_unit_costs``; unknown
  materials produce a flagged cost = 0 with a warning.
- Quantities are taken as-is from the BIM document; no IFC unit conversion.
- Area-only elements (doors, windows) contribute zero volume cost unless
  a thickness is provided.
- Multi-layer composite walls / slabs with per-layer materials are not
  decomposed; the composite's top-level ``material`` field is used.

References
----------
- ISO 13370:2017 — Thermal performance of building components
- BCIS Standard Form of Cost Analysis (SFCA) — element cost structure
- Spon's Architects' and Builders' Price Book, 2025 ed. — indicative rates
- ASPE (American Society of Professional Estimators), Section 02: concrete
  quantity take-off
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Input / output types
# ---------------------------------------------------------------------------

@dataclass
class MaterialCostSpec:
    """Material cost specification for quantity schedule costing.

    Parameters
    ----------
    material:
        Material identifier (matched case-insensitively against element
        ``material`` fields).
    density_kg_m3:
        Bulk density of the material in kg/m³.  Used to convert volume → mass.
    price_usd_per_kg:
        Indicative unit price in USD/kg.  2025-H1 baseline; caller should
        update for project-specific procurement prices.
    waste_factor:
        Additional material fraction to account for cutting waste, formwork
        spillage, etc.  Default 0.0 (0 %).  Value of 0.10 = 10 % waste.
    """
    material: str
    density_kg_m3: float
    price_usd_per_kg: float
    waste_factor: float = 0.0

    def __post_init__(self) -> None:
        if self.density_kg_m3 <= 0:
            raise ValueError(
                f"density_kg_m3 must be > 0 for material '{self.material}'"
            )
        if self.price_usd_per_kg < 0:
            raise ValueError(
                f"price_usd_per_kg must be >= 0 for material '{self.material}'"
            )
        if not (0.0 <= self.waste_factor <= 1.0):
            raise ValueError(
                f"waste_factor must be in [0, 1] for material '{self.material}'; "
                f"got {self.waste_factor}"
            )


@dataclass
class ElementLine:
    """One element row in the quantity take-off schedule.

    Parameters
    ----------
    element_id:   Element identifier (GlobalId or kerf internal UUID).
    element_name: Human-readable element name.
    category:     Element type / category (e.g. 'Wall', 'Slab', 'Column').
    material:     Material name (from BIM model).
    area_m2:      Net plan area or surface area in m². None if not applicable.
    volume_m3:    Net solid volume in m³. None if not applicable.
    length_m:     Length in m (relevant for linear elements). None if not applicable.
    count:        Number of instances (always 1 for individual elements).
    gross_mass_kg: Total mass including waste allowance (kg). 0 when no volume/density.
    material_cost_usd: Direct material cost for this element (USD).
    flagged:      True when the element has a cost warning.
    flag_reason:  Human-readable flag description.
    """
    element_id: str
    element_name: str
    category: str
    material: str
    area_m2: float | None
    volume_m3: float | None
    length_m: float | None
    count: int
    gross_mass_kg: float
    material_cost_usd: float
    flagged: bool
    flag_reason: str


@dataclass
class CategorySummary:
    """Aggregated quantities and cost per element category.

    Fields parallel ElementLine but summed across all elements in the category.
    """
    category: str
    element_count: int
    total_area_m2: float
    total_volume_m3: float
    total_gross_mass_kg: float
    total_material_cost_usd: float


@dataclass
class MaterialSummary:
    """Aggregated quantities and cost per material."""
    material: str
    element_count: int
    total_volume_m3: float
    total_gross_mass_kg: float
    total_material_cost_usd: float


@dataclass
class QuantityScheduleReport:
    """Full material quantity take-off report.

    Attributes
    ----------
    ok:                   False when a fatal error prevented execution.
    reason:               Non-empty when ok=False.
    total_material_cost_usd: Sum of all element material costs.
    element_lines:        Per-element detail rows.
    by_category:          Aggregated by element category.
    by_material:          Aggregated by material.
    warnings:             Non-fatal advisory messages.
    """
    ok: bool = True
    reason: str = ""
    total_material_cost_usd: float = 0.0
    element_lines: list[ElementLine] = field(default_factory=list)
    by_category: list[CategorySummary] = field(default_factory=list)
    by_material: list[MaterialSummary] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Quantity extraction helpers
# ---------------------------------------------------------------------------

def _get_nested(obj: dict, *keys: str) -> Any:
    """Get the first non-None value from nested dict keys (dot-notation or flat)."""
    for k in keys:
        parts = k.split(".")
        v = obj
        for p in parts:
            if not isinstance(v, dict):
                v = None
                break
            v = v.get(p)
        if v is not None:
            return v
    return None


def _extract_quantities(element: dict) -> tuple[float | None, float | None, float | None]:
    """Extract (area_m2, volume_m3, length_m) from an element dict."""
    area = _get_nested(element, "area", "params.area", "area_m2", "params.area_m2")
    volume = _get_nested(element, "volume", "params.volume", "volume_m3", "params.volume_m3")
    length = _get_nested(element, "length", "params.length", "length_m", "params.length_m")

    area = float(area) if area is not None else None
    volume = float(volume) if volume is not None else None
    length = float(length) if length is not None else None
    return area, volume, length


# ---------------------------------------------------------------------------
# Cost computation
# ---------------------------------------------------------------------------

def _compute_element_cost(
    volume_m3: float | None,
    material_key: str,
    material_db: dict[str, MaterialCostSpec],
) -> tuple[float, float, bool, str]:
    """Return (gross_mass_kg, cost_usd, flagged, flag_reason) for one element."""
    if volume_m3 is None or volume_m3 <= 0:
        return 0.0, 0.0, False, ""

    spec = material_db.get(material_key.lower() if material_key else "")
    if spec is None:
        return 0.0, 0.0, True, f"unknown material '{material_key}'; cost set to 0"

    gross_volume = volume_m3 * (1.0 + spec.waste_factor)
    gross_mass_kg = gross_volume * spec.density_kg_m3
    cost_usd = gross_mass_kg * spec.price_usd_per_kg
    return round(gross_mass_kg, 6), round(cost_usd, 4), False, ""


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def compute_quantity_schedule(
    elements: list[dict],
    material_unit_costs: list[MaterialCostSpec],
    categories: list[str] | None = None,
) -> QuantityScheduleReport:
    """
    Compute a BIM material quantity take-off schedule.

    Parameters
    ----------
    elements:
        List of BIM element dicts.  Each element should have at minimum:
          ``id`` or ``element_id``,
          ``name``,
          ``category`` (e.g. 'Wall', 'Slab', 'Column', 'Beam', 'Door', 'Window'),
          ``material``,
          optionally ``area``, ``volume``, ``length``.
    material_unit_costs:
        List of :class:`MaterialCostSpec` instances defining density and price
        for each material.  Unrecognised materials produce flagged zero-cost rows.
    categories:
        If provided, filter elements to only these categories.  None = all.

    Returns
    -------
    QuantityScheduleReport
    """
    report = QuantityScheduleReport()

    if not elements:
        report.warnings.append("No elements provided; schedule is empty.")
        return report

    # Build lookup: normalised material name → spec
    material_db: dict[str, MaterialCostSpec] = {}
    for spec in material_unit_costs:
        material_db[spec.material.lower()] = spec

    # Category filter set (lowercase for case-insensitive match)
    cat_filter: set[str] | None = (
        {c.lower() for c in categories} if categories else None
    )

    # Per-category and per-material accumulators
    # cat_key → [count, area_m2, volume_m3, gross_mass_kg, cost_usd]
    _cat_acc: dict[str, list] = {}
    # mat_key → [count, volume_m3, gross_mass_kg, cost_usd]
    _mat_acc: dict[str, list] = {}

    for elem in elements:
        elem_id   = str(_get_nested(elem, "id", "element_id") or "")
        elem_name = str(_get_nested(elem, "name") or elem_id or "unnamed")
        category  = str(_get_nested(elem, "category", "type") or "Unknown")
        material  = str(_get_nested(elem, "material", "params.material") or "Unknown")

        if cat_filter is not None and category.lower() not in cat_filter:
            continue

        area_m2, volume_m3, length_m = _extract_quantities(elem)

        gross_mass_kg, cost_usd, flagged, flag_reason = _compute_element_cost(
            volume_m3, material, material_db
        )

        line = ElementLine(
            element_id=elem_id,
            element_name=elem_name,
            category=category,
            material=material,
            area_m2=area_m2,
            volume_m3=volume_m3,
            length_m=length_m,
            count=1,
            gross_mass_kg=gross_mass_kg,
            material_cost_usd=cost_usd,
            flagged=flagged,
            flag_reason=flag_reason,
        )
        report.element_lines.append(line)

        if flagged and flag_reason:
            report.warnings.append(f"Element '{elem_name}': {flag_reason}")

        report.total_material_cost_usd += cost_usd

        # Accumulate by category
        if category not in _cat_acc:
            _cat_acc[category] = [0, 0.0, 0.0, 0.0, 0.0]
        a = _cat_acc[category]
        a[0] += 1
        a[1] += area_m2 or 0.0
        a[2] += volume_m3 or 0.0
        a[3] += gross_mass_kg
        a[4] += cost_usd

        # Accumulate by material
        mat_key = material
        if mat_key not in _mat_acc:
            _mat_acc[mat_key] = [0, 0.0, 0.0, 0.0]
        b = _mat_acc[mat_key]
        b[0] += 1
        b[1] += volume_m3 or 0.0
        b[2] += gross_mass_kg
        b[3] += cost_usd

    report.total_material_cost_usd = round(report.total_material_cost_usd, 4)

    report.by_category = sorted(
        [
            CategorySummary(
                category=cat,
                element_count=v[0],
                total_area_m2=round(v[1], 4),
                total_volume_m3=round(v[2], 6),
                total_gross_mass_kg=round(v[3], 4),
                total_material_cost_usd=round(v[4], 4),
            )
            for cat, v in _cat_acc.items()
        ],
        key=lambda s: s.total_material_cost_usd,
        reverse=True,
    )

    report.by_material = sorted(
        [
            MaterialSummary(
                material=mat,
                element_count=v[0],
                total_volume_m3=round(v[1], 6),
                total_gross_mass_kg=round(v[2], 4),
                total_material_cost_usd=round(v[3], 4),
            )
            for mat, v in _mat_acc.items()
        ],
        key=lambda s: s.total_material_cost_usd,
        reverse=True,
    )

    if not report.element_lines:
        report.warnings.append(
            "No elements matched the requested categories; schedule is empty."
        )

    return report


def report_to_dict(r: QuantityScheduleReport) -> dict:
    """Serialise QuantityScheduleReport to a JSON-safe dict."""
    return {
        "ok": r.ok,
        "reason": r.reason,
        "total_material_cost_usd": r.total_material_cost_usd,
        "warnings": r.warnings,
        "by_category": [
            {
                "category": s.category,
                "element_count": s.element_count,
                "total_area_m2": s.total_area_m2,
                "total_volume_m3": s.total_volume_m3,
                "total_gross_mass_kg": s.total_gross_mass_kg,
                "total_material_cost_usd": s.total_material_cost_usd,
            }
            for s in r.by_category
        ],
        "by_material": [
            {
                "material": s.material,
                "element_count": s.element_count,
                "total_volume_m3": s.total_volume_m3,
                "total_gross_mass_kg": s.total_gross_mass_kg,
                "total_material_cost_usd": s.total_material_cost_usd,
            }
            for s in r.by_material
        ],
        "element_lines": [
            {
                "element_id": l.element_id,
                "element_name": l.element_name,
                "category": l.category,
                "material": l.material,
                "area_m2": l.area_m2,
                "volume_m3": l.volume_m3,
                "length_m": l.length_m,
                "count": l.count,
                "gross_mass_kg": l.gross_mass_kg,
                "material_cost_usd": l.material_cost_usd,
                "flagged": l.flagged,
                "flag_reason": l.flag_reason,
            }
            for l in r.element_lines
        ],
    }


__all__ = [
    "MaterialCostSpec",
    "ElementLine",
    "CategorySummary",
    "MaterialSummary",
    "QuantityScheduleReport",
    "compute_quantity_schedule",
    "report_to_dict",
]
