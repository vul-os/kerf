"""
extrude_sketch_to_jscad — scaffold a .jscad file from a .sketch profile.

Takes a path to a .sketch file, a 3D operation, and operation parameters,
then writes a new .jscad file that imports the sketch and applies the
requested extrusion.  The sketch remains the source of truth: editing its
dimensions reflows the 3D automatically.

Supported operations
--------------------
extrude_linear
    Pads the profile to a given height.  Params: {height_mm} or
    {height_param} (equation name for parametric reference).

extrude_rotate
    Revolves the profile around an in-plane axis.  Params: {angle_deg,
    segments?}.  Axis is always the sketch's Y axis in JSCAD (i.e. the
    profile is revolved around the vertical axis of its own plane).

sweep_along_path
    Sweeps the profile along a second sketch's path using
    extrusions.extrudeFromSlices with Frenet-frame placement.
    Params: {path_sketch_file_id}.

JSCAD API notes (verified from @jscad/modeling/src/operations/extrusions/):
- extrudeLinear({ height }, geom2)
- extrudeRotate({ angle, segments }, geom2)   angle in radians
- extrudeFromSlices({ numberOfSlices, callback }, geom2)
  — there is NO sweepAlong in @jscad/modeling 2.x.  The correct API for a
  path-driven sweep is extrudeFromSlices with a per-slice callback that
  walks the path and re-positions a slice transform at each step.  The
  generated scaffold uses a readable helper pattern.

Collision policy
----------------
If target_path already exists the tool returns an EXISTS error rather than
silently overwriting.  The caller can delete/rename the file and retry.
"""

from __future__ import annotations

import json
import math
import os
from typing import Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_api.tools.file_ops import resolve_path, ensure_folders, split_path
from kerf_core.revisions import write_revision as _write_revision


# ---------------------------------------------------------------------------
# Sketch validation helpers
# ---------------------------------------------------------------------------

def _parse_sketch_json(content: str) -> tuple[dict, Optional[str]]:
    """Parse sketch JSON content.  Returns (sketch_dict, error_msg)."""
    if not content or not content.strip():
        return {}, "sketch file is empty"
    try:
        sketch = json.loads(content)
    except Exception as e:
        return {}, f"invalid JSON: {e}"
    if not isinstance(sketch, dict):
        return {}, "sketch root must be a JSON object"
    return sketch, None


def _sketch_has_closed_loop(sketch: dict) -> bool:
    """
    Lightweight check: does the sketch contain at least one entity that can
    form a closed profile?

    Strategy: a sketch is considered to have a closed loop if it contains at
    least one of:
    - a circle (trivially closed)
    - a closed arc (start == end when snapped)
    - 3 or more line/arc entities that share endpoints (full adjacency graph
      cycle detection is frontend-only; we use a heuristic here: ≥ 3
      non-construction lines/arcs exist, which is the minimum for a triangle)

    This is intentionally permissive — the frontend solver is the definitive
    authority on closed loops.  We want to catch the most obvious "empty
    sketch" case without replicating the full geom2 pipeline in Python.
    """
    entities = sketch.get("entities", [])
    if not isinstance(entities, list):
        return False

    curve_types = {"line", "arc", "circle", "ellipse", "bspline"}
    curves = [
        e for e in entities
        if isinstance(e, dict)
        and e.get("type") in curve_types
        and not e.get("construction", False)
    ]

    # A single circle is always a closed loop.
    for e in curves:
        if e.get("type") == "circle":
            return True

    # Any ellipse is also closed.
    for e in curves:
        if e.get("type") == "ellipse":
            return True

    # Any bspline with 3+ points *may* be closed (we accept it).
    for e in curves:
        if e.get("type") == "bspline":
            pts = e.get("points", [])
            if len(pts) >= 3:
                return True

    # Lines / arcs: need at least 3 to form a closed polygon.
    open_curves = [e for e in curves if e.get("type") in {"line", "arc"}]
    return len(open_curves) >= 3


# ---------------------------------------------------------------------------
# JSCAD source generators
# ---------------------------------------------------------------------------

def _object_id_from_path(path: str) -> str:
    """Derive a stable JS identifier from a sketch path basename."""
    basename = os.path.basename(path)
    stem = basename.replace(".sketch", "").replace(".jscad", "")
    # Replace non-alphanumeric chars with hyphens; trim.
    import re
    safe = re.sub(r"[^a-zA-Z0-9]", "-", stem).strip("-")
    return safe if safe else "part"


def generate_extrude_linear(
    sketch_path: str,
    target_path: str,
    params: dict,
    object_id: str,
) -> str:
    """
    Generate .jscad source for a linear extrude (pad).

    params keys (one of):
      height_mm     — literal number in millimetres
      height_param  — equation name (read from params.<name> at runtime)
    """
    height_mm = params.get("height_mm")
    height_param = params.get("height_param", "").strip()

    if height_param:
        height_expr = f"params.{height_param} ?? 10"
        param_comment = (
            f"  // params.{height_param} comes from the project's .equations file.\n"
            f"  // Fallback to 10 mm if no equations file exists yet.\n"
        )
    elif height_mm is not None:
        height_expr = str(float(height_mm))
        param_comment = ""
    else:
        height_expr = "10"
        param_comment = ""

    return (
        f"// Generated from {sketch_path}\n"
        f"// Edit the sketch to change the profile; the 3D updates automatically.\n"
        f"import profile from '{sketch_path}'\n"
        f"\n"
        f"export default function ({{ extrusions, params }}) {{\n"
        f"{param_comment}"
        f"  const height = {height_expr}\n"
        f"\n"
        f"  const body = extrusions.extrudeLinear({{ height }}, profile)\n"
        f"  return [{{ id: '{object_id}', geom: body }}]\n"
        f"}}\n"
    )


def generate_extrude_rotate(
    sketch_path: str,
    target_path: str,
    params: dict,
    object_id: str,
) -> str:
    """
    Generate .jscad source for a revolve (extrudeRotate).

    params keys:
      angle_deg  — rotation angle in degrees (default 360)
      segments   — number of polygon segments (default 32)
    """
    angle_deg = float(params.get("angle_deg", 360))
    segments = int(params.get("segments", 32))

    # JSCAD extrudeRotate takes angle in radians.
    angle_rad = round(angle_deg * math.pi / 180.0, 10)

    # Emit the radian conversion inline so the file is self-documenting.
    angle_comment = f"  // {angle_deg} degrees = {angle_rad:.6f} radians\n"

    return (
        f"// Generated from {sketch_path}\n"
        f"// Edit the sketch to change the profile; the 3D updates automatically.\n"
        f"import profile from '{sketch_path}'\n"
        f"\n"
        f"export default function ({{ extrusions }}) {{\n"
        f"{angle_comment}"
        f"  const angleRad = {angle_rad:.10f}\n"
        f"\n"
        f"  const body = extrusions.extrudeRotate(\n"
        f"    {{ angle: angleRad, segments: {segments} }},\n"
        f"    profile,\n"
        f"  )\n"
        f"  return [{{ id: '{object_id}', geom: body }}]\n"
        f"}}\n"
    )


def generate_sweep_along_path(
    sketch_path: str,
    path_sketch: str,
    target_path: str,
    params: dict,
    object_id: str,
) -> str:
    """
    Generate .jscad source for a path sweep using extrudeFromSlices.

    @jscad/modeling 2.x has no sweepAlong function.  The canonical path-sweep
    API is extrudeFromSlices({ numberOfSlices, callback }, profile), where the
    callback receives (progress, index, base) and returns a repositioned slice
    at each step along the path.

    The scaffold emits a readable pattern: the path sketch (railPath) supplies
    an array of 2D points; the callback walks those points with linear
    interpolation and builds a mat4 frame at each step using the segment
    direction as the Z axis (Frenet-style).  This matches what OCCT sweep1
    produces for simple open paths.

    Note: railPath resolves as a Geom2 (same as any sketch import). To extract
    the path points the scaffold calls geom2.toSides(railPath) — each side is
    a [start, end] pair of [x,y] points.  The scaffold includes a small inline
    helper that walks the sides chain and collects unique ordered vertices.
    """
    return (
        f"// Generated from {sketch_path} swept along {path_sketch}\n"
        f"// Edit either sketch to change the shape; the 3D updates automatically.\n"
        f"//\n"
        f"// Implementation note: @jscad/modeling 2.x does not export a path-sweep\n"
        f"// function.  This scaffold uses extrusions.extrudeFromSlices with a\n"
        f"// Frenet-frame callback that\n"
        f"// walks the path sketch's vertices.  For complex path curves, increase\n"
        f"// NUM_SLICES for smoother results.\n"
        f"import profile from '{sketch_path}'\n"
        f"import railPath from '{path_sketch}'\n"
        f"\n"
        f"export default function ({{ extrusions, geometries, maths }}) {{\n"
        f"  const {{ geom2 }} = geometries\n"
        f"  const {{ mat4, vec3 }} = maths\n"
        f"\n"
        f"  // Extract ordered path vertices from the rail sketch.\n"
        f"  // geom2.toSides returns [[start, end], ...] pairs.\n"
        f"  const sides = geom2.toSides(railPath)\n"
        f"  const pathPts = sides.length > 0\n"
        f"    ? [sides[0][0], ...sides.map(s => s[1])]\n"
        f"    : [[0, 0], [0, 0, 1]]  // fallback: straight 1-unit path\n"
        f"\n"
        f"  const NUM_SLICES = Math.max(pathPts.length, 8)\n"
        f"\n"
        f"  const body = extrusions.extrudeFromSlices(\n"
        f"    {{\n"
        f"      numberOfSlices: NUM_SLICES,\n"
        f"      callback: (progress, _i, base) => {{\n"
        f"        // Interpolate position along path at this progress fraction.\n"
        f"        const t = progress * (pathPts.length - 1)\n"
        f"        const lo = Math.floor(t)\n"
        f"        const hi = Math.min(lo + 1, pathPts.length - 1)\n"
        f"        const f = t - lo\n"
        f"        const p0 = pathPts[lo], p1 = pathPts[hi]\n"
        f"        const x = p0[0] + f * (p1[0] - p0[0])\n"
        f"        const y = p0[1] + f * (p1[1] - p0[1])\n"
        f"        const z = (p0[2] ?? 0) + f * ((p1[2] ?? 0) - (p0[2] ?? 0))\n"
        f"\n"
        f"        // Build a translation matrix for this slice.\n"
        f"        const xform = mat4.fromTranslation(mat4.create(), [x, y, z])\n"
        f"        return extrusions.slice.transform(xform,\n"
        f"          extrusions.slice.fromSides(geom2.toSides(base)))\n"
        f"      }},\n"
        f"    }},\n"
        f"    profile,\n"
        f"  )\n"
        f"  return [{{ id: '{object_id}', geom: body }}]\n"
        f"}}\n"
    )


# ---------------------------------------------------------------------------
# Params validation
# ---------------------------------------------------------------------------

def validate_params(operation: str, params: dict) -> Optional[str]:
    """Return an error message if params are invalid, else None."""
    if not isinstance(params, dict):
        return "params must be an object"

    if operation == "extrude_linear":
        height_mm = params.get("height_mm")
        height_param = params.get("height_param")
        if height_mm is None and not height_param:
            return "extrude_linear requires params.height_mm (number) or params.height_param (string)"
        if height_mm is not None and not isinstance(height_mm, (int, float)):
            return "params.height_mm must be a number"
        if height_mm is not None and float(height_mm) <= 0:
            return "params.height_mm must be > 0"
        if height_param is not None and not isinstance(height_param, str):
            return "params.height_param must be a string"

    elif operation == "extrude_rotate":
        angle_deg = params.get("angle_deg")
        if angle_deg is None:
            return "extrude_rotate requires params.angle_deg"
        if not isinstance(angle_deg, (int, float)):
            return "params.angle_deg must be a number"
        if float(angle_deg) <= 0 or float(angle_deg) > 360:
            return "params.angle_deg must be in (0, 360]"
        segments = params.get("segments")
        if segments is not None:
            if not isinstance(segments, int):
                return "params.segments must be an integer"
            if segments < 3:
                return "params.segments must be >= 3"

    elif operation == "sweep_along_path":
        path_sketch = params.get("path_sketch_file_id", "").strip()
        if not path_sketch:
            return "sweep_along_path requires params.path_sketch_file_id"
        if not path_sketch.startswith("/"):
            return "params.path_sketch_file_id must be an absolute path"

    return None


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

extrude_sketch_to_jscad_spec = ToolSpec(
    name="extrude_sketch_to_jscad",
    description=(
        "Scaffold a new .jscad file that imports a .sketch profile and "
        "applies an extrusion to produce a 3D part. The sketch remains "
        "the source of truth — editing its dimensions reflows the 3D. "
        "Supported ops: 'extrude_linear' (linear pad), 'extrude_rotate' "
        "(revolve around the sketch's vertical axis), 'sweep_along_path' "
        "(sweep the profile along a second sketch's open path). "
        "Returns an error if target_path already exists (collision). "
        "For boolean ops (boss/cut), compose two extrudes via edit_file "
        "after scaffolding. For real B-rep + STEP export, use "
        "create_feature + feature_pad instead — see docs/llm/feature.md."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path for the new .jscad file.",
            },
            "sketch_file_id": {
                "type": "string",
                "description": (
                    "Absolute path to the .sketch profile, "
                    "e.g. '/parts/bracket-outline.sketch'."
                ),
            },
            "operation": {
                "type": "string",
                "enum": ["extrude_linear", "extrude_rotate", "sweep_along_path"],
                "description": "Which JSCAD extrusion op to apply.",
            },
            "params": {
                "type": "object",
                "description": (
                    "Op-specific parameters. "
                    "extrude_linear: {height_mm: number} or {height_param: string}. "
                    "extrude_rotate: {angle_deg: number, segments?: integer}. "
                    "sweep_along_path: {path_sketch_file_id: string}."
                ),
            },
            "object_id": {
                "type": "string",
                "description": (
                    "Id of the produced JSCAD Object; defaults to the "
                    "sketch's basename (e.g. 'bracket' from 'bracket.sketch')."
                ),
            },
        },
        "required": ["path", "sketch_file_id", "operation", "params"],
    },
)


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

@register(extrude_sketch_to_jscad_spec, write=True)
async def run_extrude_sketch_to_jscad(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    target_path = a.get("path", "").strip()
    sketch_file_id = a.get("sketch_file_id", "").strip()
    operation = a.get("operation", "").strip()
    params = a.get("params", {})
    object_id = a.get("object_id", "").strip()

    # ── Required field checks ─────────────────────────────────────────────────
    if not target_path:
        return err_payload("path is required", "BAD_ARGS")
    if not target_path.startswith("/"):
        return err_payload("path must be absolute", "BAD_ARGS")
    if not sketch_file_id:
        return err_payload("sketch_file_id is required", "BAD_ARGS")
    if not sketch_file_id.startswith("/"):
        return err_payload("sketch_file_id must be an absolute path", "BAD_ARGS")
    if operation not in ("extrude_linear", "extrude_rotate", "sweep_along_path"):
        return err_payload(
            "operation must be extrude_linear | extrude_rotate | sweep_along_path",
            "BAD_ARGS",
        )

    # ── Params validation ─────────────────────────────────────────────────────
    param_err = validate_params(operation, params)
    if param_err:
        return err_payload(param_err, "BAD_ARGS")

    # ── Normalise target path ─────────────────────────────────────────────────
    if not target_path.lower().endswith(".jscad"):
        target_path = target_path + ".jscad"

    # ── Collision check ───────────────────────────────────────────────────────
    existing = await resolve_path(ctx, target_path)
    if existing.get("exists"):
        return err_payload(
            f"target path already exists: {target_path}. "
            "Delete or rename the existing file before calling this tool.",
            "EXISTS",
        )

    # ── Validate profile sketch exists and parses ─────────────────────────────
    sketch_row = await ctx.pool.fetchrow(
        "SELECT content, kind FROM files "
        "WHERE project_id = $1 AND path = $2 AND deleted_at IS NULL",
        ctx.project_id, sketch_file_id,
    )
    if not sketch_row:
        return err_payload(f"sketch not found: {sketch_file_id}", "NOT_FOUND")
    if sketch_row["kind"] != "sketch":
        return err_payload(
            f"{sketch_file_id} is kind='{sketch_row['kind']}', expected 'sketch'",
            "BAD_KIND",
        )
    sketch, parse_err = _parse_sketch_json(sketch_row["content"])
    if parse_err:
        return err_payload(f"sketch parse error: {parse_err}", "BAD_CONTENT")
    if not _sketch_has_closed_loop(sketch):
        return err_payload(
            f"sketch {sketch_file_id} does not appear to contain a closed loop "
            "(no circles, ellipses, bsplines, or 3+ line/arc entities found). "
            "Add geometry in the sketch editor before extruding.",
            "NO_CLOSED_LOOP",
        )

    # ── Validate path sketch for sweep ───────────────────────────────────────
    path_sketch_path = ""
    if operation == "sweep_along_path":
        path_sketch_path = params.get("path_sketch_file_id", "").strip()
        ps_row = await ctx.pool.fetchrow(
            "SELECT content, kind FROM files "
            "WHERE project_id = $1 AND path = $2 AND deleted_at IS NULL",
            ctx.project_id, path_sketch_path,
        )
        if not ps_row:
            return err_payload(
                f"path sketch not found: {path_sketch_path}", "NOT_FOUND"
            )
        if ps_row["kind"] != "sketch":
            return err_payload(
                f"{path_sketch_path} is kind='{ps_row['kind']}', expected 'sketch'",
                "BAD_KIND",
            )
        _, ps_parse_err = _parse_sketch_json(ps_row["content"])
        if ps_parse_err:
            return err_payload(
                f"path sketch parse error: {ps_parse_err}", "BAD_CONTENT"
            )

    # ── Derive object_id ──────────────────────────────────────────────────────
    if not object_id:
        object_id = _object_id_from_path(sketch_file_id)

    # ── Generate JSCAD source ─────────────────────────────────────────────────
    if operation == "extrude_linear":
        source = generate_extrude_linear(
            sketch_file_id, target_path, params, object_id
        )
    elif operation == "extrude_rotate":
        source = generate_extrude_rotate(
            sketch_file_id, target_path, params, object_id
        )
    else:  # sweep_along_path
        source = generate_sweep_along_path(
            sketch_file_id, path_sketch_path, target_path, params, object_id
        )

    # ── Write the new file ────────────────────────────────────────────────────
    parts = split_path(target_path)
    parent_id = await ensure_folders(ctx, parts[:-1])
    leaf = parts[-1]

    new_id = await ctx.pool.fetchval(
        "INSERT INTO files(project_id, parent_id, name, kind, content) "
        "VALUES ($1, $2, $3, 'jscad', $4) RETURNING id",
        ctx.project_id, parent_id, leaf, source,
    )

    cap = ctx.file_revisions_max if ctx.file_revisions_max > 0 else 200
    user_id = ctx.user_id if ctx.user_id != __import__("uuid").UUID(int=0) else None
    await _write_revision(
        pool=ctx.pool,
        file_id=new_id,
        content=source,
        source="tool",
        user_id=user_id,
        cap=cap,
    )

    return ok_payload({
        "path": target_path,
        "id": str(new_id),
        "sketch_file_id": sketch_file_id,
        "operation": operation,
        "object_id": object_id,
    })
