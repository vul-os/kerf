"""
LLM tools for the tool database (T7).

Tools:
  create_tool  — create a new .tool file in the project.
  update_tool  — overwrite an existing .tool file by id.
  delete_tool  — soft-delete a .tool file by id.
  list_tools   — list all .tool files in the project.
"""

from __future__ import annotations

import json
import uuid

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_cam.tool_db import parse_tool, validate_tool, list_tools as _list_tools


# ---------------------------------------------------------------------------
# create_tool
# ---------------------------------------------------------------------------

create_tool_spec = ToolSpec(
    name="create_tool",
    description=(
        "Create a new CNC tool definition (.tool file) in the project. "
        "Tools are referenced by id (e.g. 'T1') in CAM jobs. "
        "Returns the created file_id. "
        "type must be one of: ball_end, flat_end, bull_end, chamfer, drill, face_mill, engraver. "
        "ball_end requires ball_radius_mm ≤ diameter_mm/2. "
        "bull_end requires corner_radius_mm. "
        "chamfer and engraver require included_angle_deg."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Tool identifier, e.g. 'T1'"},
            "name": {"type": "string", "description": "Human-readable tool name"},
            "type": {
                "type": "string",
                "enum": ["ball_end", "flat_end", "bull_end", "chamfer", "drill", "face_mill", "engraver"],
            },
            "diameter_mm": {"type": "number", "description": "Cutting diameter in mm"},
            "ball_radius_mm": {"type": "number", "description": "Ball radius (ball_end only)"},
            "corner_radius_mm": {"type": "number", "description": "Corner radius (bull_end only)"},
            "included_angle_deg": {"type": "number", "description": "Included angle in degrees (chamfer/engraver)"},
            "flute_length_mm": {"type": "number"},
            "shank_diameter_mm": {"type": "number"},
            "overall_length_mm": {"type": "number"},
            "flute_count": {"type": "integer"},
            "material": {"type": "string", "description": "Cutter material, e.g. 'carbide'"},
            "spindle_rpm_min": {"type": "number"},
            "spindle_rpm_max": {"type": "number"},
            "feed_rate_mm_min": {"type": "number"},
            "plunge_rate_mm_min": {"type": "number"},
            "notes": {"type": "string"},
        },
        "required": ["id", "name", "type", "diameter_mm"],
    },
)


@register(create_tool_spec, write=True)
async def run_create_tool(ctx: ProjectCtx, args: bytes) -> str:
    try:
        data = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    errors = validate_tool(data)
    if errors:
        return err_payload("; ".join(errors), "VALIDATION_ERROR")

    try:
        tool = parse_tool(data)
    except ValueError as e:
        return err_payload(str(e), "VALIDATION_ERROR")

    tool_json = json.dumps(tool.to_dict(), indent=2)
    file_name = f"{tool.id}.tool"
    file_id = str(uuid.uuid4())

    try:
        await ctx.pool.execute(
            """
            INSERT INTO files (id, project_id, name, kind, created_at, updated_at)
            VALUES ($1, $2, $3, 'tool', now(), now())
            """,
            file_id, ctx.project_id, file_name,
        )
        await ctx.pool.execute(
            """
            INSERT INTO file_revisions (id, file_id, content, created_at)
            VALUES ($1, $2, $3, now())
            """,
            str(uuid.uuid4()), file_id, tool_json,
        )
    except Exception as e:
        return err_payload(f"DB error: {e}", "DB_ERROR")

    return ok_payload({
        "file_id": file_id,
        "tool_id": tool.id,
        "name": tool.name,
        "message": f"Tool {tool.id!r} created as {file_name!r}.",
    })


# ---------------------------------------------------------------------------
# update_tool
# ---------------------------------------------------------------------------

update_tool_spec = ToolSpec(
    name="update_tool",
    description=(
        "Update an existing .tool file in the project by its tool id (e.g. 'T1'). "
        "All fields provided are merged with the existing tool definition. "
        "Returns the updated tool."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tool_id": {"type": "string", "description": "Tool id to update, e.g. 'T1'"},
            "name": {"type": "string"},
            "type": {"type": "string", "enum": ["ball_end", "flat_end", "bull_end", "chamfer", "drill", "face_mill", "engraver"]},
            "diameter_mm": {"type": "number"},
            "ball_radius_mm": {"type": "number"},
            "corner_radius_mm": {"type": "number"},
            "included_angle_deg": {"type": "number"},
            "flute_length_mm": {"type": "number"},
            "shank_diameter_mm": {"type": "number"},
            "overall_length_mm": {"type": "number"},
            "flute_count": {"type": "integer"},
            "material": {"type": "string"},
            "spindle_rpm_min": {"type": "number"},
            "spindle_rpm_max": {"type": "number"},
            "feed_rate_mm_min": {"type": "number"},
            "plunge_rate_mm_min": {"type": "number"},
            "notes": {"type": "string"},
        },
        "required": ["tool_id"],
    },
)


@register(update_tool_spec, write=True)
async def run_update_tool(ctx: ProjectCtx, args: bytes) -> str:
    try:
        data = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    tool_id = data.get("tool_id", "")
    if not tool_id:
        return err_payload("tool_id is required", "BAD_ARGS")

    # Find the existing file.
    row = await ctx.pool.fetchrow(
        """
        SELECT f.id AS file_id, fr.content
        FROM files f
        LEFT JOIN file_revisions fr ON fr.file_id = f.id
        WHERE f.project_id = $1
          AND f.kind = 'tool'
          AND f.deleted_at IS NULL
        ORDER BY fr.created_at DESC
        LIMIT 1
        """,
        ctx.project_id,
    )

    # Search all tool files for the matching id.
    rows = await ctx.pool.fetch(
        """
        SELECT DISTINCT ON (f.id) f.id AS file_id, fr.content
        FROM files f
        LEFT JOIN file_revisions fr ON fr.file_id = f.id
        WHERE f.project_id = $1
          AND f.kind = 'tool'
          AND f.deleted_at IS NULL
        ORDER BY f.id, fr.created_at DESC
        """,
        ctx.project_id,
    )

    target_file_id = None
    existing_data: dict = {}
    for row in rows:
        content = row.get("content") or b""
        if isinstance(content, (bytes, bytearray)):
            content = content.decode("utf-8", errors="replace")
        if not content:
            continue
        try:
            d = json.loads(content)
        except Exception:
            continue
        if str(d.get("id", "")) == str(tool_id):
            target_file_id = row["file_id"]
            existing_data = d
            break

    if target_file_id is None:
        return err_payload(f"Tool {tool_id!r} not found", "NOT_FOUND")

    # Merge incoming fields (exclude tool_id from the update dict).
    update_fields = {k: v for k, v in data.items() if k != "tool_id" and v is not None}
    merged = {**existing_data, **update_fields}
    # Ensure the id is preserved.
    merged["id"] = tool_id

    errors = validate_tool(merged)
    if errors:
        return err_payload("; ".join(errors), "VALIDATION_ERROR")

    try:
        tool = parse_tool(merged)
    except ValueError as e:
        return err_payload(str(e), "VALIDATION_ERROR")

    tool_json = json.dumps(tool.to_dict(), indent=2)
    try:
        await ctx.pool.execute(
            """
            INSERT INTO file_revisions (id, file_id, content, created_at)
            VALUES ($1, $2, $3, now())
            """,
            str(uuid.uuid4()), target_file_id, tool_json,
        )
        await ctx.pool.execute(
            "UPDATE files SET updated_at = now() WHERE id = $1",
            target_file_id,
        )
    except Exception as e:
        return err_payload(f"DB error: {e}", "DB_ERROR")

    return ok_payload({
        "file_id": target_file_id,
        "tool_id": tool.id,
        "tool": tool.to_dict(),
        "message": f"Tool {tool.id!r} updated.",
    })


# ---------------------------------------------------------------------------
# delete_tool
# ---------------------------------------------------------------------------

delete_tool_spec = ToolSpec(
    name="delete_tool",
    description="Soft-delete a .tool file from the project by its tool id.",
    input_schema={
        "type": "object",
        "properties": {
            "tool_id": {"type": "string", "description": "Tool id to delete, e.g. 'T1'"},
        },
        "required": ["tool_id"],
    },
)


@register(delete_tool_spec, write=True)
async def run_delete_tool(ctx: ProjectCtx, args: bytes) -> str:
    try:
        data = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    tool_id = data.get("tool_id", "")
    if not tool_id:
        return err_payload("tool_id is required", "BAD_ARGS")

    rows = await ctx.pool.fetch(
        """
        SELECT DISTINCT ON (f.id) f.id AS file_id, fr.content
        FROM files f
        LEFT JOIN file_revisions fr ON fr.file_id = f.id
        WHERE f.project_id = $1
          AND f.kind = 'tool'
          AND f.deleted_at IS NULL
        ORDER BY f.id, fr.created_at DESC
        """,
        ctx.project_id,
    )

    target_file_id = None
    for row in rows:
        content = row.get("content") or b""
        if isinstance(content, (bytes, bytearray)):
            content = content.decode("utf-8", errors="replace")
        if not content:
            continue
        try:
            d = json.loads(content)
        except Exception:
            continue
        if str(d.get("id", "")) == str(tool_id):
            target_file_id = row["file_id"]
            break

    if target_file_id is None:
        return err_payload(f"Tool {tool_id!r} not found", "NOT_FOUND")

    try:
        await ctx.pool.execute(
            "UPDATE files SET deleted_at = now() WHERE id = $1",
            target_file_id,
        )
    except Exception as e:
        return err_payload(f"DB error: {e}", "DB_ERROR")

    return ok_payload({
        "file_id": target_file_id,
        "tool_id": tool_id,
        "message": f"Tool {tool_id!r} deleted.",
    })


# ---------------------------------------------------------------------------
# list_tools (LLM surface)
# ---------------------------------------------------------------------------

list_tools_llm_spec = ToolSpec(
    name="list_tools",
    description="List all CNC tool definitions (.tool files) in the project.",
    input_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
)


@register(list_tools_llm_spec)
async def run_list_tools(ctx: ProjectCtx, args: bytes) -> str:
    tools = await _list_tools(ctx.pool, ctx.project_id)
    return ok_payload({
        "tools": [t.to_dict() for t in tools],
        "count": len(tools),
    })
