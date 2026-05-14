import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


cam_run_spec = ToolSpec(
    name="cam_run",
    description=(
        "Generate a CAM toolpath for a STEP file using OpenCAMlib 2.5D/3D/5-axis operations. "
        "Returns a queued job ID; poll cam_job_status(file_id) for results and G-code download. "
        "For 5-axis constant-tilt finishing use operation='5axis_finish' with drive_face_id + tilt_deg. "
        "For 3+2 indexed use operation='3plus2' with drive_face_id + indexed_op."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "operation": {
                "type": "string",
                "enum": [
                    "face", "contour", "pocket", "drill", "profile",
                    "parallel_3d", "waterline", "lathe",
                    "5axis_finish", "5axis", "3plus2",
                ],
                "description": (
                    "CAM operation type. "
                    "'5axis' is an alias for '5axis_finish'. "
                    "'5axis_finish': constant-tilt surface finishing with A/B rotary moves. "
                    "'3plus2': 3-axis op on a drive-face-aligned rotation."
                ),
            },
            "tool_diameter": {
                "type": "number",
                "description": "Tool diameter in mm (default 3.0)",
            },
            "step_over": {
                "type": "number",
                "description": "Radial step-over in mm (default 0.5)",
            },
            "step_down": {
                "type": "number",
                "description": "Axial depth-of-cut per pass in mm (default 0.5)",
            },
            "feed_rate": {
                "type": "number",
                "description": "Feed rate in mm/min (default 1000.0)",
            },
            "spindle_speed": {
                "type": "number",
                "description": "Spindle speed in RPM (default 10000.0)",
            },
            "coolant": {
                "type": "boolean",
                "description": "Enable flood coolant (default true)",
            },
            "drive_face_id": {
                "type": "integer",
                "description": "Zero-based face index for 5axis_finish / 3plus2 drive surface",
            },
            "tilt_deg": {
                "type": "number",
                "description": "Tool-axis tilt off surface normal in degrees [0–30] for 5axis_finish (default 15)",
            },
            "lead_deg": {
                "type": "number",
                "description": "Lead/lag angle along path direction for 5axis_finish (optional, default 0)",
            },
            "indexed_op": {
                "type": "string",
                "enum": ["face", "pocket", "contour", "parallel_3d", "waterline"],
                "description": "3-axis sub-op for 3plus2 (default 'face')",
            },
            "kinematic_family": {
                "type": "string",
                "enum": ["head_table"],
                "description": "Machine kinematic family (default 'head_table': A-around-X, B-around-Y)",
            },
            "use_tcp": {
                "type": "boolean",
                "description": "Emit G43.4 TCP mode in 5-axis G-code (default false)",
            },
            "post_processor_5x": {
                "type": "string",
                "enum": ["linuxcnc", "fanuc"],
                "description": "Post-processor for 5-axis G-code (default 'linuxcnc')",
            },
        },
        "required": ["file_id", "operation"],
    },
)


@register(cam_run_spec, write=True)
async def run_cam_run(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id = a.get("file_id", "")
    operation = a.get("operation", "")

    if not file_id:
        return err_payload("file_id is required", "BAD_ARGS")
    if not operation:
        return err_payload("operation is required", "BAD_ARGS")

    spec = {
        "operation": operation,
        "tool_diameter": a.get("tool_diameter", 3.0),
        "step_over": a.get("step_over", 0.5),
        "step_down": a.get("step_down", 0.5),
        "feed_rate": a.get("feed_rate", 1000.0),
        "spindle_speed": a.get("spindle_speed", 10000.0),
        "coolant": a.get("coolant", True),
        # 5-axis fields (passed through when present)
        "drive_face_id": a.get("drive_face_id"),
        "tilt_deg": a.get("tilt_deg"),
        "lead_deg": a.get("lead_deg"),
        "indexed_op": a.get("indexed_op"),
        "kinematic_family": a.get("kinematic_family"),
        "use_tcp": a.get("use_tcp"),
        "post_processor_5x": a.get("post_processor_5x"),
    }
    spec_json = json.dumps(spec)

    row = await ctx.pool.fetchrow(
        """INSERT INTO cam_jobs (file_id, project_id, input_spec)
           VALUES ($1, $2, $3)
           ON CONFLICT (file_id) WHERE status IN ('queued', 'running')
           DO UPDATE SET input_spec = $3, status = 'queued', error = NULL,
               started_at = NULL, finished_at = NULL
           RETURNING id""",
        file_id, ctx.project_id, spec_json,
    )

    if not row:
        return err_payload("failed to enqueue CAM job", "ERROR")

    return ok_payload({
        "job_id": str(row["id"]),
        "status": "queued",
        "message": "CAM job enqueued. Poll cam_job_status(file_id) for results.",
    })


cam_job_status_spec = ToolSpec(
    name="cam_job_status",
    description=(
        "Poll the status of a CAM toolpath generation job. "
        "Returns the job status; when complete, includes toolpath stats and output_key for G-code download."
    ),
    input_schema={
        "type": "object",
        "properties": {"file_id": {"type": "string"}},
        "required": ["file_id"],
    },
)


@register(cam_job_status_spec)
async def run_cam_job_status(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    file_id = a.get("file_id", "")
    if not file_id:
        return err_payload("file_id is required", "BAD_ARGS")

    row = await ctx.pool.fetchrow(
        """SELECT status, result_json, output_key, error FROM cam_jobs
           WHERE file_id = $1 AND project_id = $2
           ORDER BY created_at DESC LIMIT 1""",
        file_id, ctx.project_id,
    )

    if not row:
        return err_payload("cam job not found", "NOT_FOUND")

    resp = {"file_id": file_id, "status": row["status"]}
    if row["status"] == "done":
        if row["result_json"]:
            try:
                resp["result"] = json.loads(row["result_json"])
            except Exception:
                pass
        if row["output_key"]:
            resp["output_key"] = row["output_key"]
    elif row["status"] == "error" and row["error"]:
        resp["error"] = row["error"]

    return ok_payload(resp)
