"""
cost_estimation.py — LLM tools for 5D cost estimation (Revit parity).

Registered tools
----------------
bim_5d_quantity_takeoff  — extract quantities from BIM elements (area/volume/count)
bim_5d_cost_rollup       — multiply quantities by unit costs, group by phase/trade
bim_5d_cost_summary      — full cost estimate: takeoff + rollup in one call

References
----------
RICS NRM 1:2012 — New Rules of Measurement, Order of Cost Estimating.
ISO 12006-2:2015 — Organisation of information about construction works.
IFC4 ADD2 TC1   — IfcQuantityArea, IfcQuantityVolume, IfcQuantityCount.
"""

from __future__ import annotations

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


# ---------------------------------------------------------------------------
# bim_5d_quantity_takeoff
# ---------------------------------------------------------------------------

_quantity_takeoff_spec = ToolSpec(
    name="bim_5d_quantity_takeoff",
    description=(
        "5D Cost Estimation — Quantity Take-off.\n"
        "\n"
        "Extract measurement quantities (area m², volume m³, count each, "
        "length lm) from a list of BIM element dicts.\n"
        "\n"
        "Each element dict should include:\n"
        "  id (or element_id), category (Wall/Slab/Column/Door/…),\n"
        "  and any of: area, width+height, volume, length, trade, phase.\n"
        "\n"
        "Returns a list of QuantityRecord objects (element_id, category, "
        "quantity, unit, trade, phase).\n"
        "\n"
        "IFC alignment: quantities ≈ IfcElementQuantity (IfcQuantityArea etc)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": "List of BIM element dicts.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":       {"type": "string"},
                        "category": {"type": "string"},
                        "area":     {"type": "number"},
                        "width":    {"type": "number"},
                        "height":   {"type": "number"},
                        "length":   {"type": "number"},
                        "volume":   {"type": "number"},
                        "trade":    {"type": "string"},
                        "phase":    {"type": "string"},
                        "name":     {"type": "string"},
                    },
                },
            },
        },
        "required": ["elements"],
    },
)


async def run_bim_5d_quantity_takeoff(params: dict, ctx) -> str:
    try:
        from kerf_bim.cost_estimation import take_off

        elements = params.get("elements", [])
        if not isinstance(elements, list):
            return err_payload("elements must be an array", "BAD_ARGS")

        records = take_off(elements)
        return ok_payload({
            "ok": True,
            "record_count": len(records),
            "quantities": [
                {
                    "element_id":  r.element_id,
                    "category":    r.category,
                    "quantity":    r.quantity,
                    "unit":        r.unit,
                    "trade":       r.trade,
                    "phase":       r.phase,
                    "description": r.description,
                }
                for r in records
            ],
        })
    except Exception as exc:
        return err_payload(str(exc), "TAKEOFF_ERROR")


# ---------------------------------------------------------------------------
# bim_5d_cost_rollup
# ---------------------------------------------------------------------------

_cost_rollup_spec = ToolSpec(
    name="bim_5d_cost_rollup",
    description=(
        "5D Cost Estimation — Cost Rollup.\n"
        "\n"
        "Multiply pre-computed quantity records by a unit-cost database "
        "(provided or built-in) and return total cost grouped by phase, "
        "trade, and element category. RICS NRM 1:2012 method.\n"
        "\n"
        "unit_costs: optional list of custom rate entries:\n"
        "  [{category, unit, unit_cost, trade?, phase?, currency?, description?}]\n"
        "If omitted, built-in indicative USD rates are used.\n"
        "\n"
        "quantities: list of QuantityRecord dicts (from bim_5d_quantity_takeoff "
        "or manually constructed)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "quantities": {
                "type": "array",
                "description": "List of QuantityRecord dicts.",
                "items": {
                    "type": "object",
                    "properties": {
                        "element_id": {"type": "string"},
                        "category":   {"type": "string"},
                        "quantity":   {"type": "number"},
                        "unit":       {"type": "string"},
                        "trade":      {"type": "string"},
                        "phase":      {"type": "string"},
                    },
                    "required": ["element_id", "category", "quantity", "unit"],
                },
            },
            "unit_costs": {
                "type": "array",
                "description": "Custom unit-cost entries (optional; built-in rates used if omitted).",
                "items": {
                    "type": "object",
                    "properties": {
                        "category":    {"type": "string"},
                        "unit":        {"type": "string"},
                        "unit_cost":   {"type": "number"},
                        "trade":       {"type": "string"},
                        "phase":       {"type": "string"},
                        "currency":    {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["category", "unit", "unit_cost"],
                },
            },
            "currency": {
                "type": "string",
                "description": "Currency for built-in rates (default USD). ISO 4217.",
                "default": "USD",
            },
        },
        "required": ["quantities"],
    },
)


async def run_bim_5d_cost_rollup(params: dict, ctx) -> str:
    try:
        from kerf_bim.cost_estimation import (
            UnitCostDB, UnitCostEntry, QuantityRecord, cost_rollup, default_unit_cost_db,
        )

        raw_quantities = params.get("quantities", [])
        quantities = []
        for q in raw_quantities:
            quantities.append(QuantityRecord(
                element_id=str(q.get("element_id", "")),
                category=str(q.get("category", "Generic")),
                quantity=float(q.get("quantity", 0.0)),
                unit=str(q.get("unit", "each")),
                trade=str(q.get("trade", "")),
                phase=str(q.get("phase", "")),
                description=str(q.get("description", "")),
            ))

        currency = str(params.get("currency", "USD"))
        raw_costs = params.get("unit_costs")
        if raw_costs:
            entries = []
            for c in raw_costs:
                entries.append(UnitCostEntry(
                    category=str(c["category"]),
                    unit=str(c["unit"]),
                    unit_cost=float(c["unit_cost"]),
                    trade=str(c.get("trade", "")),
                    phase=str(c.get("phase", "")),
                    currency=str(c.get("currency", currency)),
                    description=str(c.get("description", "")),
                ))
            db = UnitCostDB(entries=entries)
        else:
            db = default_unit_cost_db(currency=currency)

        rollup = cost_rollup(quantities, db)

        return ok_payload({
            "ok":          True,
            "total_cost":  rollup.total_cost,
            "currency":    rollup.currency,
            "by_phase":    rollup.by_phase,
            "by_trade":    rollup.by_trade,
            "by_category": rollup.by_category,
            "line_count":  len(rollup.line_items),
            "unpriced_count": len(rollup.unpriced),
            "line_items": [
                {
                    "element_id": li.element_id,
                    "category":   li.category,
                    "trade":      li.trade,
                    "phase":      li.phase,
                    "description":li.description,
                    "quantity":   li.quantity,
                    "unit":       li.unit,
                    "unit_cost":  li.unit_cost,
                    "total_cost": li.total_cost,
                    "currency":   li.currency,
                }
                for li in rollup.line_items
            ],
            "unpriced_ids": [q.element_id for q in rollup.unpriced],
        })
    except Exception as exc:
        return err_payload(str(exc), "COST_ROLLUP_ERROR")


# ---------------------------------------------------------------------------
# bim_5d_cost_summary
# ---------------------------------------------------------------------------

_cost_summary_spec = ToolSpec(
    name="bim_5d_cost_summary",
    description=(
        "5D Cost Estimation — Full pipeline: quantity takeoff + cost rollup in "
        "one call. Accepts raw BIM element dicts and optional custom unit costs. "
        "Returns total cost, grouped summaries, and unpriced elements."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "description": "BIM element dicts (same format as bim_5d_quantity_takeoff).",
                "items": {"type": "object"},
            },
            "unit_costs": {
                "type": "array",
                "description": "Custom unit-cost entries (optional).",
                "items": {"type": "object"},
            },
            "currency": {
                "type": "string",
                "default": "USD",
                "description": "ISO 4217 currency code.",
            },
        },
        "required": ["elements"],
    },
)


async def run_bim_5d_cost_summary(params: dict, ctx) -> str:
    try:
        from kerf_bim.cost_estimation import (
            UnitCostDB, UnitCostEntry, take_off, cost_rollup, default_unit_cost_db,
        )

        elements = params.get("elements", [])
        if not isinstance(elements, list):
            return err_payload("elements must be an array", "BAD_ARGS")

        quantities = take_off(elements)
        currency = str(params.get("currency", "USD"))
        raw_costs = params.get("unit_costs")

        if raw_costs:
            entries = [
                UnitCostEntry(
                    category=str(c["category"]),
                    unit=str(c["unit"]),
                    unit_cost=float(c["unit_cost"]),
                    trade=str(c.get("trade", "")),
                    phase=str(c.get("phase", "")),
                    currency=str(c.get("currency", currency)),
                )
                for c in raw_costs
            ]
            db = UnitCostDB(entries=entries)
        else:
            db = default_unit_cost_db(currency=currency)

        rollup = cost_rollup(quantities, db)

        return ok_payload({
            "ok":             True,
            "element_count":  len(elements),
            "quantity_count": len(quantities),
            "total_cost":     rollup.total_cost,
            "currency":       rollup.currency,
            "by_phase":       rollup.by_phase,
            "by_trade":       rollup.by_trade,
            "by_category":    rollup.by_category,
            "line_count":     len(rollup.line_items),
            "unpriced_count": len(rollup.unpriced),
        })
    except Exception as exc:
        return err_payload(str(exc), "COST_SUMMARY_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_5d_quantity_takeoff", _quantity_takeoff_spec, run_bim_5d_quantity_takeoff),
    ("bim_5d_cost_rollup",      _cost_rollup_spec,      run_bim_5d_cost_rollup),
    ("bim_5d_cost_summary",     _cost_summary_spec,     run_bim_5d_cost_summary),
]
