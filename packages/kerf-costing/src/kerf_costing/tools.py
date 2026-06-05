"""
kerf_costing.tools — LLM tool wrappers for BIM material quantity take-off.

Registers two tools with the Kerf tool registry:

  bim_quantity_schedule
      Aggregate a BIM element list by category and material, returning
      area / volume / count per element type.  No cost estimation.
      Returns a schedule table suitable for the QuantitySchedulePanel.

  bim_material_cost_rollup
      Full material quantity take-off with cost rollup.  Same as
      bim_quantity_schedule but additionally computes material mass and
      direct material cost per element, aggregated by category and material.

Both tools return {ok: false, reason: ...} on bad input — never raise.

References
----------
BCIS Standard Form of Cost Analysis (SFCA)
ISO 13370:2017 — Thermal performance / building element quantities
Spon's Architects' and Builders' Price Book, 2025 ed.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_costing._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_costing.quantity_schedule import (
    MaterialCostSpec,
    compute_quantity_schedule,
    report_to_dict,
)


# ---------------------------------------------------------------------------
# bim_quantity_schedule
# ---------------------------------------------------------------------------

bim_quantity_schedule_spec = ToolSpec(
    name="bim_quantity_schedule",
    description=(
        "Generate a material quantity take-off (QTO) schedule from a BIM element list.\n"
        "\n"
        "Takes a flat list of BIM elements (each with category, material, and optional "
        "area/volume/length fields) and returns a schedule table grouped by element type "
        "(Wall, Slab, Column, Beam, Window, Door, etc.) with total area, volume, length, "
        "and element count per category.\n"
        "\n"
        "This is the AEC equivalent of a BOM — it answers 'how much of each material type "
        "is in this building?' without requiring cost data.\n"
        "\n"
        "Returns:\n"
        "  by_category    — aggregated rows (category, count, total_area_m2, total_volume_m3)\n"
        "  by_material    — aggregated rows (material, count, total_volume_m3)\n"
        "  element_lines  — per-element detail rows\n"
        "  warnings       — non-fatal issues (missing quantities, unknown categories)\n"
        "\n"
        "HONEST FLAG: quantities are taken from the BIM document as-is; no IFC-unit "
        "conversion is applied.  Composite multi-layer elements are treated as a single "
        "homogeneous material using the top-level material field."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": (
                    "List of BIM elements to schedule.  Each element dict should contain:\n"
                    "  id (string) — element identifier\n"
                    "  name (string) — human-readable element name\n"
                    "  category (string) — element type: 'Wall'/'Slab'/'Column'/'Beam'/"
                    "'Window'/'Door'/'Space'/'Roof'/'Stair'/etc.\n"
                    "  material (string) — primary material name\n"
                    "  area (number, optional) — plan/surface area in m²\n"
                    "  volume (number, optional) — solid volume in m³\n"
                    "  length (number, optional) — length in m (for linear elements)"
                ),
                "items": {"type": "object"},
                "minItems": 1,
            },
            "categories": {
                "type": "array",
                "description": (
                    "Optional list of categories to include.  If omitted, all categories "
                    "are included.  Example: ['Wall', 'Slab', 'Column']."
                ),
                "items": {"type": "string"},
            },
        },
        "required": ["elements"],
    },
)


def run_bim_quantity_schedule(params: dict, ctx: Any) -> str:
    """Generate a BIM material quantity take-off schedule (no cost)."""
    elements = params.get("elements", [])
    if not elements:
        return err_payload("elements is required and must be non-empty", "BAD_ARGS")

    if not isinstance(elements, list):
        return err_payload("elements must be a list", "BAD_ARGS")

    categories = params.get("categories") or None

    try:
        report = compute_quantity_schedule(elements, [], categories)
    except Exception as exc:
        return err_payload(str(exc), "SCHEDULE_ERROR")

    d = report_to_dict(report)
    # For the no-cost variant, strip cost fields from element_lines to keep
    # the output focused.
    for line in d.get("element_lines", []):
        line.pop("gross_mass_kg", None)
        line.pop("material_cost_usd", None)
        line.pop("flagged", None)
        line.pop("flag_reason", None)
    for cat in d.get("by_category", []):
        cat.pop("total_gross_mass_kg", None)
        cat.pop("total_material_cost_usd", None)
    for mat in d.get("by_material", []):
        mat.pop("total_gross_mass_kg", None)
        mat.pop("total_material_cost_usd", None)
    d.pop("total_material_cost_usd", None)

    return ok_payload(d)


# ---------------------------------------------------------------------------
# bim_material_cost_rollup
# ---------------------------------------------------------------------------

bim_material_cost_rollup_spec = ToolSpec(
    name="bim_material_cost_rollup",
    description=(
        "Full BIM material quantity take-off with direct material cost rollup.\n"
        "\n"
        "Extends bim_quantity_schedule with material cost estimation.  Requires "
        "material_unit_costs: a list of {material, density_kg_m3, price_usd_per_kg, "
        "waste_factor?} entries.  Cost model: direct material cost per element = "
        "volume_m3 × (1 + waste_factor) × density_kg_m3 × price_usd_per_kg.\n"
        "\n"
        "Returns:\n"
        "  total_material_cost_usd — sum of all element material costs\n"
        "  by_category             — aggregated by category with total cost\n"
        "  by_material             — aggregated by material with total cost\n"
        "  element_lines           — per-element detail with gross_mass_kg + cost\n"
        "  warnings                — non-fatal issues (unknown materials → flagged)\n"
        "\n"
        "HONEST FLAGS:\n"
        "  - Direct material cost only; no labour, equipment, overhead, or "
        "    preliminaries.\n"
        "  - waste_factor is process-independent (no formwork, lapping, cuts).\n"
        "  - Elements without volume produce zero cost with a warning.\n"
        "  - Prices are 2025-H1 indicative; supply-chain pricing should be used "
        "    for tenders.\n"
        "\n"
        "References: BCIS SFCA; Spon's 2025; ISO 13370:2017."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": (
                    "List of BIM elements.  Each element dict should contain:\n"
                    "  id (string) — element identifier\n"
                    "  name (string) — human-readable element name\n"
                    "  category (string) — element type (Wall/Slab/Column/Beam/etc.)\n"
                    "  material (string) — primary material name\n"
                    "  area (number, optional) — plan/surface area in m²\n"
                    "  volume (number, optional) — solid volume in m³\n"
                    "  length (number, optional) — length in m"
                ),
                "items": {"type": "object"},
                "minItems": 1,
            },
            "material_unit_costs": {
                "type": "array",
                "description": (
                    "Per-material cost specification list.  Each entry:\n"
                    "  material (string, required) — must match element material name\n"
                    "  density_kg_m3 (number, required) — bulk density in kg/m³\n"
                    "  price_usd_per_kg (number, required) — unit price in USD/kg\n"
                    "  waste_factor (number, optional, default 0) — "
                    "fractional waste allowance (0.10 = 10 %)"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "material":          {"type": "string"},
                        "density_kg_m3":     {"type": "number", "exclusiveMinimum": 0},
                        "price_usd_per_kg":  {"type": "number", "minimum": 0},
                        "waste_factor":      {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["material", "density_kg_m3", "price_usd_per_kg"],
                },
                "minItems": 1,
            },
            "categories": {
                "type": "array",
                "description": "Optional list of categories to include.",
                "items": {"type": "string"},
            },
        },
        "required": ["elements", "material_unit_costs"],
    },
)


def run_bim_material_cost_rollup(params: dict, ctx: Any) -> str:
    """Full BIM material quantity take-off with cost rollup."""
    elements = params.get("elements", [])
    if not elements:
        return err_payload("elements is required and must be non-empty", "BAD_ARGS")

    raw_costs = params.get("material_unit_costs", [])
    if not raw_costs:
        return err_payload("material_unit_costs is required and must be non-empty", "BAD_ARGS")

    if not isinstance(elements, list):
        return err_payload("elements must be a list", "BAD_ARGS")
    if not isinstance(raw_costs, list):
        return err_payload("material_unit_costs must be a list", "BAD_ARGS")

    categories = params.get("categories") or None

    # Build MaterialCostSpec list
    specs: list[MaterialCostSpec] = []
    for i, rc in enumerate(raw_costs):
        mat = rc.get("material", "")
        if not mat:
            return err_payload(f"material_unit_costs[{i}].material is required", "BAD_ARGS")
        density = rc.get("density_kg_m3")
        price = rc.get("price_usd_per_kg")
        if density is None or price is None:
            return err_payload(
                f"material_unit_costs[{i}]: density_kg_m3 and price_usd_per_kg required",
                "BAD_ARGS",
            )
        try:
            specs.append(MaterialCostSpec(
                material=mat,
                density_kg_m3=float(density),
                price_usd_per_kg=float(price),
                waste_factor=float(rc.get("waste_factor", 0.0)),
            ))
        except (ValueError, TypeError) as exc:
            return err_payload(
                f"material_unit_costs[{i}]: invalid values — {exc}", "BAD_ARGS"
            )

    try:
        report = compute_quantity_schedule(elements, specs, categories)
    except Exception as exc:
        return err_payload(str(exc), "ROLLUP_ERROR")

    return ok_payload(report_to_dict(report))
