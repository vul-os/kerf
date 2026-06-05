"""
kerf_cad_core.piping.plant_coordination_tools — LLM tool wrappers.

Registers two LLM tools for multi-discipline plant coordination:

  plant_model_assemble        — Assemble discipline elements into a federated
                                PlantModel in a shared 3D coordinate space.
  plant_coordination_check    — Run cross-discipline interference / clash
                                detection and return a coordination report.

References
----------
BS 1192-4:2014 — COBie federated model exchange.
USACE EM 1110-1-1000 — Multi-discipline design coordination.
ASME B31.3-2022 §321 — Piping clearance requirements.

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx  # noqa: F401
except ImportError:
    from kerf_cad_core._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_cad_core.piping.plant_coordination import (
    PlantDiscipline,
    PlantModel,
    make_plant_element,
    get_clearance_m,
)


# ---------------------------------------------------------------------------
# Shared element input schema fragment
# ---------------------------------------------------------------------------

_ELEMENT_SCHEMA = {
    "type": "object",
    "description": (
        "A discipline element placed in the shared 3D plant coordinate space."
    ),
    "properties": {
        "element_id": {
            "type": "string",
            "description": "Unique element ID (e.g. 'BEAM-A1-01', 'DN150-PIPE-001').",
        },
        "discipline": {
            "type": "string",
            "enum": [d.value for d in PlantDiscipline],
            "description": "Engineering discipline owning this element.",
        },
        "bbox_min": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 3,
            "maxItems": 3,
            "description": "[x_min, y_min, z_min] lower corner of AABB (metres).",
        },
        "bbox_max": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 3,
            "maxItems": 3,
            "description": "[x_max, y_max, z_max] upper corner of AABB (metres).",
        },
        "label": {
            "type": "string",
            "description": "Human-readable label (e.g. 'W310x97 column', 'DN150 CS steam pipe').",
        },
        "system": {
            "type": "string",
            "description": "Optional zone/system tag (e.g. 'RACK-A', 'PUMP-BAY-1').",
        },
        "material": {"type": "string", "description": "Material descriptor for BOM."},
        "quantity": {"type": "number", "description": "Quantity for BOM (default 1)."},
        "unit": {"type": "string", "description": "BOM unit (default 'ea')."},
        "weight_kg": {"type": "number", "description": "Weight per unit (kg)."},
        "unit_cost": {"type": "number", "description": "Unit cost (USD) for cost roll-up."},
    },
    "required": ["element_id", "discipline", "bbox_min", "bbox_max"],
}


# ---------------------------------------------------------------------------
# Tool: plant_model_assemble
# ---------------------------------------------------------------------------

plant_model_assemble_spec = ToolSpec(
    name="plant_model_assemble",
    description=(
        "Assemble a multi-discipline federated plant model from discipline elements.\n"
        "\n"
        "Each element carries a bounding box (AABB) in the shared 3D plant coordinate "
        "space (metres, right-hand Z-up), a discipline tag (structural/hvac/piping/"
        "civil/equipment/electrical/instrument), and optional BOM metadata.\n"
        "\n"
        "Returns a summary of the assembled model: total elements per discipline, "
        "combined BOM, spatial zone summary, and coordinate-system info.\n"
        "\n"
        "References: BS 1192-4:2014 §4.4 (federated model); USACE EM 1110-1-1000 §5."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Project identifier.",
            },
            "elements": {
                "type": "array",
                "description": "List of discipline elements to include in the plant model.",
                "items": _ELEMENT_SCHEMA,
            },
            "coordinate_system": {
                "type": "string",
                "description": "Coordinate system (default 'metric-SI').",
            },
            "datum_elevation": {
                "type": "number",
                "description": "Project datum Z-elevation offset (metres; default 0.0).",
            },
            "zones": {
                "type": "array",
                "description": "Optional spatial zones (pump bay, pipe rack, etc.).",
                "items": {
                    "type": "object",
                    "properties": {
                        "zone_id": {"type": "string"},
                        "bbox_min": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3,
                        },
                        "bbox_max": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3,
                        },
                    },
                    "required": ["zone_id", "bbox_min", "bbox_max"],
                },
            },
        },
        "required": ["project_id", "elements"],
    },
)


@register(plant_model_assemble_spec, write=False)
async def run_plant_model_assemble(ctx: "ProjectCtx", args: bytes) -> str:
    """Build and summarise a federated plant model."""
    try:
        a = json.loads(args) if args else {}
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    project_id = a.get("project_id", "unnamed-plant")
    raw_elements = a.get("elements", [])
    if not isinstance(raw_elements, list):
        return err_payload("elements must be a list", "BAD_ARGS")

    model = PlantModel(
        project_id=project_id,
        coordinate_system=a.get("coordinate_system", "metric-SI"),
        datum_elevation=float(a.get("datum_elevation", 0.0)),
    )

    # Register zones
    for z in (a.get("zones") or []):
        try:
            model.add_zone(
                z["zone_id"],
                (tuple(z["bbox_min"]), tuple(z["bbox_max"])),
            )
        except (KeyError, TypeError) as exc:
            return err_payload(f"invalid zone spec: {exc}", "BAD_ARGS")

    # Add elements
    errors = []
    for i, raw in enumerate(raw_elements):
        try:
            elem = make_plant_element(
                element_id=raw["element_id"],
                discipline=raw["discipline"],
                x0=raw["bbox_min"][0], y0=raw["bbox_min"][1], z0=raw["bbox_min"][2],
                x1=raw["bbox_max"][0], y1=raw["bbox_max"][1], z1=raw["bbox_max"][2],
                label=raw.get("label", ""),
                system=raw.get("system", ""),
                material=raw.get("material", ""),
                quantity=float(raw.get("quantity", 1.0)),
                unit=raw.get("unit", "ea"),
                weight_kg=float(raw.get("weight_kg", 0.0)),
                unit_cost=float(raw.get("unit_cost", 0.0)),
            )
            model.add_element(elem)
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(f"Element #{i}: {exc}")

    if errors:
        return err_payload(f"Failed to parse elements: {errors}", "BAD_ARGS")

    # Summarise
    bom_summary = model.combined_bom_summary()
    zone_assign = model.assign_zones()

    disciplines_present = sorted(
        {e.discipline.value for e in model.elements}
    )
    per_discipline = {
        d: sum(1 for e in model.elements if e.discipline.value == d)
        for d in disciplines_present
    }

    return ok_payload({
        "project_id": project_id,
        "total_elements": len(model.elements),
        "disciplines_present": disciplines_present,
        "elements_per_discipline": per_discipline,
        "bom_summary": bom_summary,
        "zone_summary": {
            zid: {"element_count": len(ids)}
            for zid, ids in zone_assign.items()
        },
        "coordinate_system": model.coordinate_system,
        "datum_elevation_m": model.datum_elevation,
        "honest_note": (
            "BOM costs are user-supplied estimates; no pricing data is embedded. "
            "Clash detection uses AABB (axis-aligned bounding boxes) — actual "
            "element shapes may allow clearances that AABB reports as violations."
        ),
    })


# ---------------------------------------------------------------------------
# Tool: plant_coordination_check
# ---------------------------------------------------------------------------

plant_coordination_check_spec = ToolSpec(
    name="plant_coordination_check",
    description=(
        "Run multi-discipline plant coordination: cross-discipline interference / "
        "clash detection + clearance checking + BOM rollup + zone summary.\n"
        "\n"
        "Hard clashes: elements from different disciplines whose AABBs physically "
        "overlap (pipe through beam, duct through column, etc.).\n"
        "\n"
        "Soft clashes: AABBs are separated but by less than the required discipline-pair "
        "clearance (e.g. < 25 mm pipe-to-structure, < 50 mm duct-to-pipe) per "
        "ASME B31.3 §321 / SMACNA §5.4 / AISC §B3.9.\n"
        "\n"
        "Returns a CoordinationReport with:\n"
        "  - clash_count (hard + soft) per discipline pair\n"
        "  - each clash: element IDs, disciplines, gap (m), shortfall (m), severity\n"
        "  - combined BOM per discipline\n"
        "  - spatial zone summary\n"
        "\n"
        "HONEST GAP: only AABB interference — no curved/swept-solid geometry. "
        "No concurrent multi-user live update.\n"
        "\n"
        "References: USACE EM 1110-1-1000 §5.3; BS 1192-4:2014 §6.3."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "elements": {
                "type": "array",
                "description": "Discipline elements (same schema as plant_model_assemble).",
                "items": _ELEMENT_SCHEMA,
            },
            "zones": {
                "type": "array",
                "description": "Optional spatial zones.",
                "items": {
                    "type": "object",
                    "properties": {
                        "zone_id": {"type": "string"},
                        "bbox_min": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3,
                        },
                        "bbox_max": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3,
                        },
                    },
                    "required": ["zone_id", "bbox_min", "bbox_max"],
                },
            },
            "check_hard_clashes": {
                "type": "boolean",
                "description": "Check for hard (overlap) clashes (default true).",
            },
            "check_soft_clashes": {
                "type": "boolean",
                "description": "Check for soft (clearance-violation) clashes (default true).",
            },
        },
        "required": ["project_id", "elements"],
    },
)


@register(plant_coordination_check_spec, write=False)
async def run_plant_coordination_check(ctx: "ProjectCtx", args: bytes) -> str:
    """Run multi-discipline coordination check and return a full report."""
    try:
        a = json.loads(args) if args else {}
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    project_id = a.get("project_id", "unnamed-plant")
    raw_elements = a.get("elements", [])
    if not isinstance(raw_elements, list):
        return err_payload("elements must be a list", "BAD_ARGS")

    check_hard = a.get("check_hard_clashes", True)
    check_soft = a.get("check_soft_clashes", True)

    model = PlantModel(project_id=project_id)

    # Register zones
    for z in (a.get("zones") or []):
        try:
            model.add_zone(
                z["zone_id"],
                (tuple(z["bbox_min"]), tuple(z["bbox_max"])),
            )
        except (KeyError, TypeError) as exc:
            return err_payload(f"invalid zone spec: {exc}", "BAD_ARGS")

    # Add elements
    errors = []
    for i, raw in enumerate(raw_elements):
        try:
            elem = make_plant_element(
                element_id=raw["element_id"],
                discipline=raw["discipline"],
                x0=raw["bbox_min"][0], y0=raw["bbox_min"][1], z0=raw["bbox_min"][2],
                x1=raw["bbox_max"][0], y1=raw["bbox_max"][1], z1=raw["bbox_max"][2],
                label=raw.get("label", ""),
                system=raw.get("system", ""),
                material=raw.get("material", ""),
                quantity=float(raw.get("quantity", 1.0)),
                unit=raw.get("unit", "ea"),
                weight_kg=float(raw.get("weight_kg", 0.0)),
                unit_cost=float(raw.get("unit_cost", 0.0)),
            )
            model.add_element(elem)
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(f"Element #{i}: {exc}")

    if errors:
        return err_payload(f"Failed to parse elements: {errors}", "BAD_ARGS")

    report = model.coordination_report()
    result = report.as_dict()
    result["honest_gap"] = (
        "Clash detection uses AABB geometry only — tight curved members may produce "
        "false positives. No real-time concurrent multi-user coordination."
    )
    return ok_payload(result)
