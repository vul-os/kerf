"""
facade_ifc.py — LLM tools for IFC 4 façade element parsing.

Registered tools
----------------
bim_parse_facade_ifc           Parse an IFC file and return façade element summary.
bim_facade_thermal_summary     Compute building-envelope thermal summary from a
                                previously-parsed façade model stored in project files.

Notes
-----
IFC 4 subset parser — NOT buildingSMART certified.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx


# ---------------------------------------------------------------------------
# bim_parse_facade_ifc
# ---------------------------------------------------------------------------

_parse_facade_spec = ToolSpec(
    name="bim_parse_facade_ifc",
    description=(
        "Parse an IFC 4 file and extract façade elements (walls, curtain walls, "
        "windows, doors) with thermal (U-value / R-value) and structural properties "
        "(structural_class, fire_rating). Elements are grouped by IfcBuildingStorey. "
        "Returns a summary dict and optionally stores the parsed model as a project file. "
        "NOTE: IFC 4 subset parser — NOT buildingSMART certified."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "UUID of the target Kerf project.",
            },
            "file_blob_id": {
                "type": "string",
                "description": "Blob ID or storage key for the uploaded .ifc file.",
            },
            "store_result": {
                "type": "boolean",
                "description": (
                    "If true (default), store the parsed FacadeModel summary as a "
                    "project file (kind='facade_ifc') and return the file_id."
                ),
            },
        },
        "required": ["project_id", "file_blob_id"],
    },
)


@register(_parse_facade_spec, write=True)
async def bim_parse_facade_ifc(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    project_id = a.get("project_id", "").strip()
    blob_ref = a.get("file_blob_id", "").strip()
    store_result = bool(a.get("store_result", True))

    if not project_id:
        return err_payload("project_id is required", "BAD_ARGS")
    if not blob_ref:
        return err_payload("file_blob_id is required", "BAD_ARGS")

    if ctx.storage is None:
        return err_payload("storage backend not configured", "NO_STORAGE")

    try:
        blob_bytes = await ctx.storage.get(blob_ref)
    except Exception as exc:
        return err_payload(f"failed to fetch blob {blob_ref!r}: {exc}", "STORAGE_ERROR")

    if not blob_bytes:
        return err_payload(f"blob not found: {blob_ref}", "NOT_FOUND")

    # Write to a temp file for ifcopenshell
    try:
        with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as tmp:
            tmp.write(blob_bytes)
            tmp_path = tmp.name
    except Exception as exc:
        return err_payload(f"failed to write temp file: {exc}", "IO_ERROR")

    try:
        from kerf_bim.ifc_facade_parser import parse_facade_from_ifc, extract_facade_thermal_summary
    except ImportError as exc:
        os.unlink(tmp_path)
        return err_payload(f"facade parser unavailable: {exc}", "UNAVAILABLE")

    try:
        facade_model = parse_facade_from_ifc(tmp_path)
    except Exception as exc:
        os.unlink(tmp_path)
        return err_payload(f"IFC facade parse error: {exc}", "PARSE_ERROR")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    thermal_summary = extract_facade_thermal_summary(facade_model)

    result_payload: dict[str, Any] = {
        "walls_count": len(facade_model.walls),
        "curtain_walls_count": len(facade_model.curtain_walls),
        "windows_count": len(facade_model.windows),
        "doors_count": len(facade_model.doors),
        "storeys": list(facade_model.per_storey_index.keys()),
        "thermal_summary": thermal_summary,
        "warnings": facade_model.warnings,
        "disclaimer": "IFC 4 subset parser — NOT buildingSMART certified",
    }

    file_id_str: str | None = None
    if store_result:
        serialised = json.dumps(
            {
                "version": 1,
                "walls": [w.__dict__ for w in facade_model.walls],
                "curtain_walls": [cw.__dict__ for cw in facade_model.curtain_walls],
                "windows": [win.__dict__ for win in facade_model.windows],
                "doors": [d.__dict__ for d in facade_model.doors],
                "per_storey_index": facade_model.per_storey_index,
                "warnings": facade_model.warnings,
            },
            indent=2,
        )
        try:
            new_id = await ctx.pool.fetchval(
                """INSERT INTO files(id, project_id, parent_id, name, kind, content)
                   VALUES ($1, $2, NULL, 'facade_model.json', 'facade_ifc', $3)
                   RETURNING id""",
                uuid.uuid4(),
                ctx.project_id,
                serialised,
            )
            file_id_str = str(new_id)
        except Exception as exc:
            result_payload["store_warning"] = f"failed to store result: {exc}"

    result_payload["file_id"] = file_id_str
    return ok_payload(result_payload)


# ---------------------------------------------------------------------------
# bim_facade_thermal_summary
# ---------------------------------------------------------------------------

_thermal_summary_spec = ToolSpec(
    name="bim_facade_thermal_summary",
    description=(
        "Compute building-envelope thermal summary from a previously-parsed "
        "IFC façade model file (kind='facade_ifc'). "
        "Returns: total_facade_area_m2, total_opening_area_m2, "
        "window_to_wall_ratio, weighted_u_value_W_m2K, "
        "elements_with_u_value, elements_missing_u_value."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "UUID of the Kerf project.",
            },
            "file_id": {
                "type": "string",
                "description": "UUID of the facade_ifc file produced by bim_parse_facade_ifc.",
            },
        },
        "required": ["project_id", "file_id"],
    },
)


@register(_thermal_summary_spec, write=False)
async def bim_facade_thermal_summary(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    project_id = a.get("project_id", "").strip()
    file_id_raw = a.get("file_id", "").strip()

    if not project_id:
        return err_payload("project_id is required", "BAD_ARGS")
    if not file_id_raw:
        return err_payload("file_id is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id_raw)
    except Exception:
        return err_payload("file_id must be a valid UUID", "BAD_ARGS")

    try:
        row = await ctx.pool.fetchrow(
            "SELECT content, kind FROM files "
            "WHERE id = $1 AND project_id = $2 AND deleted_at IS NULL",
            fid,
            ctx.project_id,
        )
    except Exception as exc:
        return err_payload(f"database error: {exc}", "DB_ERROR")

    if row is None:
        return err_payload(f"file {file_id_raw!r} not found", "NOT_FOUND")

    content, kind = row["content"], row["kind"]
    if kind != "facade_ifc":
        return err_payload(
            f"expected kind=facade_ifc, got {kind!r}", "BAD_KIND"
        )

    try:
        data = json.loads(content)
    except Exception as exc:
        return err_payload(f"invalid JSON in stored model: {exc}", "PARSE_ERROR")

    # Reconstruct a minimal FacadeModel for summary computation
    try:
        from kerf_bim.ifc_facade_parser import (
            FacadeModel,
            FacadeWall,
            FacadeCurtainWall,
            FacadeWindow,
            FacadeDoor,
            extract_facade_thermal_summary,
        )
    except ImportError as exc:
        return err_payload(f"facade parser unavailable: {exc}", "UNAVAILABLE")

    try:
        model = FacadeModel(
            walls=[FacadeWall(**w) for w in (data.get("walls") or [])],
            curtain_walls=[FacadeCurtainWall(**cw) for cw in (data.get("curtain_walls") or [])],
            windows=[FacadeWindow(**win) for win in (data.get("windows") or [])],
            doors=[FacadeDoor(**d) for d in (data.get("doors") or [])],
        )
    except Exception as exc:
        return err_payload(f"failed to deserialise stored model: {exc}", "DESERIALISE_ERROR")

    summary = extract_facade_thermal_summary(model)
    return ok_payload(summary)


# ---------------------------------------------------------------------------
# TOOLS registration list (plugin.py pattern)
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_parse_facade_ifc", _parse_facade_spec, bim_parse_facade_ifc),
    ("bim_facade_thermal_summary", _thermal_summary_spec, bim_facade_thermal_summary),
]
