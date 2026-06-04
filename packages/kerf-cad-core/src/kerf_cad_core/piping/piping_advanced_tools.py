"""
kerf_cad_core.piping.piping_advanced_tools — LLM tool wrappers for AVEVA E3D parity.

Registers three LLM tools:
  pipe_component_catalog_query  — query the ASME B16.5/B16.9/API 6D catalogue
  pipe_run_bom                  — compute BOM for a pipe run
  plant_federation_clash        — run cross-discipline clash detection

Wave 12B: AVEVA E3D parity (piping catalog + multi-discipline + concurrent)

References
----------
ASME B16.5-2020 — Pipe Flanges and Flanged Fittings
ASME B16.9-2018 — Factory-Made Wrought Buttwelding Fittings
API Spec 6D-2014 — Pipeline and Piping Valves
BS 1192-4:2014   — COBie federation

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.piping.component_catalogue import (
    asme_b16_5_flange_catalog,
    asme_b16_9_buttweld_fitting_catalog,
    api_6d_valve_catalog,
    compute_pipe_run_bom,
    PipeCatalogue,
)
from kerf_cad_core.piping.multi_discipline_federation import (
    FederatedPlantModel,
    DisciplineSubmodel,
    Discipline,
    detect_stale_submodels,
    make_element,
)


# Merged catalogue (all three standards combined)
def _full_catalogue() -> PipeCatalogue:
    cat = PipeCatalogue()
    cat.components = (
        asme_b16_5_flange_catalog().components
        + asme_b16_9_buttweld_fitting_catalog().components
        + api_6d_valve_catalog().components
    )
    return cat


# ---------------------------------------------------------------------------
# Tool: pipe_component_catalog_query
# ---------------------------------------------------------------------------

_catalog_query_spec = ToolSpec(
    name="pipe_component_catalog_query",
    description=(
        "Query the built-in ASME B16.5 / B16.9 / API 6D pipe component catalogue.\n"
        "\n"
        "Supports filtering by:\n"
        "  component_type   — 'flange' | 'elbow' | 'tee' | 'reducer' | 'valve' | 'cap' | 'cross'\n"
        "  catalog_standard — 'ASME B16.5' | 'ASME B16.9' | 'API 6D'\n"
        "  nominal_size_in  — NPS in inches (float), e.g. 4.0, 6.0, 12.0\n"
        "  pressure_class_psi — 150 | 300 | 600 | 900 | 1500 | 2500\n"
        "  schedule         — 'SCH40' | 'SCH80' | 'SCH160' | 'XXS'\n"
        "\n"
        "Returns: {ok:true, count, components:[{component_id, ...}]}\n"
        "Errors:  {ok:false, reason}\n"
        "\n"
        "References: ASME B16.5-2020, ASME B16.9-2018, API Spec 6D-2014."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "component_type": {
                "type": "string",
                "description": "Filter by type: flange | elbow | tee | reducer | valve | cap | cross",
            },
            "catalog_standard": {
                "type": "string",
                "description": "Filter by standard: 'ASME B16.5' | 'ASME B16.9' | 'API 6D'",
            },
            "nominal_size_in": {
                "type": "number",
                "description": "NPS in inches, e.g. 4.0",
            },
            "pressure_class_psi": {
                "type": "integer",
                "description": "Pressure class: 150 | 300 | 600 | 900 | 1500 | 2500",
            },
            "schedule": {
                "type": "string",
                "description": "Pipe schedule: SCH40 | SCH80 | SCH160 | XXS",
            },
        },
        "required": [],
    },
)


@register(_catalog_query_spec, write=False)
async def run_pipe_component_catalog_query(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    catalogue = _full_catalogue()

    # Build filter kwargs from non-null args
    filter_kwargs: dict = {}
    for key in ("component_type", "catalog_standard", "schedule"):
        if key in a and a[key] is not None:
            filter_kwargs[key] = a[key]
    if "nominal_size_in" in a and a["nominal_size_in"] is not None:
        filter_kwargs["nominal_size_in"] = float(a["nominal_size_in"])
    if "pressure_class_psi" in a and a["pressure_class_psi"] is not None:
        filter_kwargs["pressure_class_psi"] = int(a["pressure_class_psi"])

    if filter_kwargs:
        results = catalogue.filter(**filter_kwargs)
    else:
        results = catalogue.components

    return ok_payload({
        "count": len(results),
        "components": [c.to_dict() for c in results[:100]],  # cap at 100
    })


# ---------------------------------------------------------------------------
# Tool: pipe_run_bom
# ---------------------------------------------------------------------------

_bom_spec = ToolSpec(
    name="pipe_run_bom",
    description=(
        "Compute a bill of materials (BOM) for a piping run.\n"
        "\n"
        "Each pipe_segment must have:\n"
        "  from (str), to (str), size_in (float), schedule (str), length_m (float)\n"
        "  material (str, optional), n_elbows (int, optional), n_flanges (int, optional)\n"
        "\n"
        "Flanges are matched from the ASME B16.5 catalogue; elbows from ASME B16.9.\n"
        "HONEST: budgetary estimate only — production BOM needs vendor quotes.\n"
        "\n"
        "Returns: {ok:true, total_weight_kg, total_cost_usd, line_items}\n"
        "\n"
        "References: ASME B16.5-2020, ASME B16.9-2018, ASME B36.10M-2018."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pipe_segments": {
                "type": "array",
                "description": "List of pipe segment dicts",
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "size_in": {"type": "number"},
                        "schedule": {"type": "string"},
                        "length_m": {"type": "number"},
                        "material": {"type": "string"},
                        "n_elbows": {"type": "integer"},
                        "n_flanges": {"type": "integer"},
                    },
                    "required": ["size_in", "schedule", "length_m"],
                },
            },
        },
        "required": ["pipe_segments"],
    },
)


@register(_bom_spec, write=False)
async def run_pipe_run_bom(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    segments = a.get("pipe_segments")
    if not segments or not isinstance(segments, list):
        return err_payload("pipe_segments is required and must be a list", "BAD_ARGS")

    # Use combined catalogue for fitting lookups
    catalogue = _full_catalogue()

    result = compute_pipe_run_bom(segments, catalogue)
    return ok_payload(result) if result.get("ok") else json.dumps(result)


# ---------------------------------------------------------------------------
# Tool: plant_federation_clash
# ---------------------------------------------------------------------------

_clash_spec = ToolSpec(
    name="plant_federation_clash",
    description=(
        "Run cross-discipline clash detection on a federated plant model.\n"
        "\n"
        "Accepts a list of discipline submodels (each with element bounding boxes).\n"
        "Returns all pairs of elements from different disciplines whose bounding "
        "boxes overlap (AABB intersection).\n"
        "\n"
        "Also performs coordinate system consistency checking per BS 1192-4:2014.\n"
        "\n"
        "Returns: {ok:true, clash_count, clashes:[...], warnings:[...]}\n"
        "\n"
        "References: BS 1192-4:2014, USACE EM 1110-1-1000."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "submodels": {
                "type": "array",
                "description": "List of discipline submodel dicts",
                "items": {
                    "type": "object",
                    "properties": {
                        "discipline": {"type": "string"},
                        "coordinate_system": {"type": "string"},
                        "datum_elevation": {"type": "number"},
                        "elements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "bbox": {"type": "array"},
                                },
                            },
                        },
                    },
                    "required": ["discipline", "elements"],
                },
            },
        },
        "required": ["submodels"],
    },
)


@register(_clash_spec, write=False)
async def run_plant_federation_clash(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    project_id = a.get("project_id", "tool-query")
    raw_submodels = a.get("submodels", [])
    if not isinstance(raw_submodels, list):
        return err_payload("submodels must be a list", "BAD_ARGS")

    submodels = []
    for sm_dict in raw_submodels:
        disc_str = sm_dict.get("discipline", "")
        try:
            disc = Discipline(disc_str)
        except ValueError:
            return err_payload(f"Unknown discipline '{disc_str}'", "BAD_ARGS")

        elements = []
        for e in sm_dict.get("elements", []):
            eid = e.get("id", "?")
            bbox = e.get("bbox")
            if bbox and len(bbox) == 2:
                elements.append({"id": eid, "bbox": (tuple(bbox[0]), tuple(bbox[1]))})

        # Compute overall bbox from elements
        if elements:
            all_mins = [e["bbox"][0] for e in elements]
            all_maxs = [e["bbox"][1] for e in elements]
            overall_min = tuple(min(v[i] for v in all_mins) for i in range(3))
            overall_max = tuple(max(v[i] for v in all_maxs) for i in range(3))
        else:
            overall_min = (0.0, 0.0, 0.0)
            overall_max = (0.0, 0.0, 0.0)

        submodels.append(DisciplineSubmodel(
            discipline=disc,
            file_path="",
            last_modified_iso="",
            element_count=len(elements),
            bbox=(overall_min, overall_max),
            sha256="",
            coordinate_system=sm_dict.get("coordinate_system", "metric-SI"),
            datum_elevation=float(sm_dict.get("datum_elevation", 0.0)),
            elements=elements,
        ))

    model = FederatedPlantModel(
        project_id=project_id,
        submodels=submodels,
    )

    clashes = model.cross_discipline_clashes()
    warnings = model.coordinate_system_consistency()

    return ok_payload({
        "clash_count": len(clashes),
        "clashes": clashes,
        "warnings": warnings,
    })
