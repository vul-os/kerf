"""
LLM tools for the mates/assembly plugin.

Provides: add_mate, delete_mate, list_mates, solve_assembly,
          tolerance_auto_chain
These are registered via ctx.tools.register() in plugin.py.
"""

import json
import uuid

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
    from db.queries import files as file_queries
    _HAS_FILE_QUERIES = True
except ImportError:
    from kerf_mates._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx
    file_queries = None
    _HAS_FILE_QUERIES = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_assembly_file(ctx, fid):
    """Fetch assembly file row; return None if not found or wrong kind."""
    if _HAS_FILE_QUERIES:
        return await file_queries.get_file(ctx.pool, fid)
    # Fallback: direct pool query
    return await ctx.pool.fetchrow(
        "SELECT id, kind, content, name, parent_id FROM files "
        "WHERE id = $1 AND project_id = $2 AND deleted_at IS NULL",
        fid, ctx.project_id,
    )


DIMENSIONAL_MATE_TYPES = {"distance", "angle"}
VALID_FEATURES = {"face", "edge", "vertex", "axis"}

# Classic mate types understood by the geometric constraint solver
CLASSIC_MATE_TYPES = ("coincident", "concentric", "parallel", "perpendicular",
                      "distance", "angle", "tangent")
# Kinematic joint types handled analytically by the joint system
JOINT_MATE_TYPES = ("rigid", "revolute", "slider", "cam", "gear", "pin_slot")
ALL_MATE_TYPES = CLASSIC_MATE_TYPES + JOINT_MATE_TYPES


def validate_mate(mate: dict) -> tuple:
    mate_type = mate.get("type", "")
    if not mate_type:
        return False, "mate type is required"

    if mate_type not in ALL_MATE_TYPES:
        return False, f"invalid mate type: {mate_type}"

    for ref_key in ("a", "b"):
        ref = mate.get(ref_key, {})
        if not ref:
            return False, f"mate {ref_key} is required"
        if not ref.get("component_id"):
            return False, f"mate {ref_key}.component_id is required"
        if ref.get("feature") not in VALID_FEATURES:
            return False, f"mate {ref_key}.feature must be one of: {', '.join(VALID_FEATURES)}"
        if not ref.get("feature_id"):
            return False, f"mate {ref_key}.feature_id is required"

    if mate_type in DIMENSIONAL_MATE_TYPES:
        if "value" not in mate:
            return False, f"mate type '{mate_type}' requires value"
        if not mate.get("unit"):
            return False, f"mate type '{mate_type}' requires unit"

    return True, ""


def generate_mate_id(mate_type: str, existing_ids: set) -> str:
    base = f"{mate_type}-mate"
    if base not in existing_ids:
        return base
    for i in range(1, 1000):
        candidate = f"{base}-{i}"
        if candidate not in existing_ids:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# add_mate
# ---------------------------------------------------------------------------

add_mate_spec = ToolSpec(
    name="add_mate",
    description=(
        "Add a geometric mate constraint to an assembly file. "
        "A mate connects two component entities (face/edge/vertex/axis) "
        "with a constraint type."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly_file_id": {"type": "string"},
            "mate": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["coincident", "concentric", "parallel",
                                 "perpendicular", "distance", "angle", "tangent",
                                 "rigid", "revolute", "slider", "cam", "gear",
                                 "pin_slot"],
                    },
                    "a": {
                        "type": "object",
                        "properties": {
                            "component_id": {"type": "string"},
                            "feature": {"type": "string",
                                        "enum": ["face", "edge", "vertex", "axis"]},
                            "feature_id": {"type": "string"},
                        },
                        "required": ["component_id", "feature", "feature_id"],
                    },
                    "b": {
                        "type": "object",
                        "properties": {
                            "component_id": {"type": "string"},
                            "feature": {"type": "string",
                                        "enum": ["face", "edge", "vertex", "axis"]},
                            "feature_id": {"type": "string"},
                        },
                        "required": ["component_id", "feature", "feature_id"],
                    },
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "tolerance_plus": {"type": "number"},
                    "tolerance_minus": {"type": "number"},
                    "flipped": {"type": "boolean"},
                },
                "required": ["type", "a", "b"],
            },
        },
        "required": ["assembly_file_id", "mate"],
    },
)


@register(add_mate_spec, write=True)
async def run_add_mate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    assembly_file_id = a.get("assembly_file_id", "").strip()
    if not assembly_file_id:
        return err_payload("assembly_file_id is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(assembly_file_id)
    except Exception:
        return err_payload("assembly_file_id must be a uuid", "BAD_ARGS")

    mate = a.get("mate", {})
    valid, err_msg = validate_mate(mate)
    if not valid:
        return err_payload(err_msg, "BAD_MATE")

    row = await _get_assembly_file(ctx, fid)
    if not row:
        return err_payload("assembly file not found", "NOT_FOUND")

    if row["kind"] != "assembly":
        return err_payload(f"file kind '{row['kind']}' is not an assembly", "BAD_KIND")

    content = row["content"] or "{}"
    try:
        doc = json.loads(content)
    except Exception:
        doc = {}

    if not isinstance(doc, dict):
        return err_payload("assembly file content is invalid JSON object", "BAD_FILE")

    existing_ids = {m["id"] for m in doc.get("mates", [])
                   if isinstance(m, dict) and m.get("id")}

    mate_id = mate.get("id", "")
    if not mate_id or mate_id in existing_ids:
        mate_id = generate_mate_id(mate.get("type", "coincident"), existing_ids)

    mate["id"] = mate_id
    doc.setdefault("mates", []).append(mate)

    new_content = json.dumps(doc, separators=(",", ":"))
    await ctx.pool.execute(
        "UPDATE files SET content = $1, updated_at = now() "
        "WHERE id = $2 AND project_id = $3",
        new_content, fid, ctx.project_id,
    )

    return ok_payload({
        "assembly_file_id": assembly_file_id,
        "mate_id": mate_id,
        "type": mate.get("type"),
    })


# ---------------------------------------------------------------------------
# delete_mate
# ---------------------------------------------------------------------------

delete_mate_spec = ToolSpec(
    name="delete_mate",
    description="Remove a geometric mate constraint from an assembly file by its id.",
    input_schema={
        "type": "object",
        "properties": {
            "assembly_file_id": {"type": "string"},
            "mate_id": {"type": "string"},
        },
        "required": ["assembly_file_id", "mate_id"],
    },
)


@register(delete_mate_spec, write=True)
async def run_delete_mate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    assembly_file_id = a.get("assembly_file_id", "").strip()
    mate_id = a.get("mate_id", "").strip()

    if not assembly_file_id or not mate_id:
        return err_payload("assembly_file_id and mate_id are required", "BAD_ARGS")

    try:
        fid = uuid.UUID(assembly_file_id)
    except Exception:
        return err_payload("assembly_file_id must be a uuid", "BAD_ARGS")

    row = await _get_assembly_file(ctx, fid)
    if not row:
        return err_payload("assembly file not found", "NOT_FOUND")

    if row["kind"] != "assembly":
        return err_payload(f"file kind '{row['kind']}' is not an assembly", "BAD_KIND")

    content = row["content"] or "{}"
    try:
        doc = json.loads(content)
    except Exception:
        return err_payload("assembly file content is invalid JSON", "BAD_FILE")

    if not isinstance(doc, dict):
        return err_payload("assembly file content is invalid JSON object", "BAD_FILE")

    mates = doc.get("mates", [])
    found = False
    new_mates = []
    for m in mates:
        if isinstance(m, dict) and m.get("id") == mate_id:
            found = True
        else:
            new_mates.append(m)

    if not found:
        return err_payload(f"mate not found: {mate_id}", "NOT_FOUND")

    doc["mates"] = new_mates
    new_content = json.dumps(doc, separators=(",", ":"))
    await ctx.pool.execute(
        "UPDATE files SET content = $1, updated_at = now() "
        "WHERE id = $2 AND project_id = $3",
        new_content, fid, ctx.project_id,
    )

    return ok_payload({
        "assembly_file_id": assembly_file_id,
        "deleted_mate_id": mate_id,
    })


# ---------------------------------------------------------------------------
# list_mates
# ---------------------------------------------------------------------------

list_mates_spec = ToolSpec(
    name="list_mates",
    description="List all mate constraints in an assembly file.",
    input_schema={
        "type": "object",
        "properties": {"assembly_file_id": {"type": "string"}},
        "required": ["assembly_file_id"],
    },
)


@register(list_mates_spec)
async def run_list_mates(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    assembly_file_id = a.get("assembly_file_id", "").strip()
    if not assembly_file_id:
        return err_payload("assembly_file_id is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(assembly_file_id)
    except Exception:
        return err_payload("assembly_file_id must be a uuid", "BAD_ARGS")

    row = await _get_assembly_file(ctx, fid)
    if not row:
        return err_payload("assembly file not found", "NOT_FOUND")

    if row["kind"] != "assembly":
        return err_payload(f"file kind '{row['kind']}' is not an assembly", "BAD_KIND")

    content = row["content"] or "{}"
    try:
        doc = json.loads(content)
    except Exception:
        return err_payload("assembly file content is invalid JSON", "BAD_FILE")

    if not isinstance(doc, dict):
        return err_payload("assembly file content is invalid JSON object", "BAD_FILE")

    mates = doc.get("mates", [])
    if not isinstance(mates, list):
        mates = []

    return ok_payload({
        "assembly_file_id": assembly_file_id,
        "mates": mates,
        "count": len(mates),
    })


# ---------------------------------------------------------------------------
# solve_assembly
# ---------------------------------------------------------------------------

solve_assembly_spec = ToolSpec(
    name="solve_assembly",
    description=(
        "Solve the geometric constraints of an assembly using the "
        "gradient-descent solver. Computes component positions based on mates "
        "and returns solved transforms along with tolerance stack-up analysis."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly_file_id": {"type": "string"},
            "fixed_component_id": {"type": "string"},
        },
        "required": ["assembly_file_id"],
    },
)


@register(solve_assembly_spec)
async def run_solve_assembly(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    assembly_file_id = a.get("assembly_file_id", "").strip()
    if not assembly_file_id:
        return err_payload("assembly_file_id is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(assembly_file_id)
    except Exception:
        return err_payload("assembly_file_id must be a uuid", "BAD_ARGS")

    fixed_component_id = a.get("fixed_component_id", "").strip() or None

    row = await _get_assembly_file(ctx, fid)
    if not row:
        return err_payload("assembly file not found", "NOT_FOUND")

    if row["kind"] != "assembly":
        return err_payload(f"file kind '{row['kind']}' is not an assembly", "BAD_KIND")

    content = row["content"] or "{}"
    try:
        doc = json.loads(content)
    except Exception:
        return err_payload("assembly file content is invalid JSON", "BAD_FILE")

    if not isinstance(doc, dict):
        return err_payload("assembly file content is invalid JSON object", "BAD_FILE")

    components = doc.get("components", [])
    mates = doc.get("mates", [])

    from kerf_mates.solver import solve_assembly as _solve
    result = _solve(components, mates, fixed_component_id=fixed_component_id)

    return ok_payload({
        "assembly_file_id": assembly_file_id,
        "solved": result["solved"],
        "iterations": result["iterations"],
        "component_transforms": result["component_transforms"],
        "tolerance_stackup": result["tolerance_stackup"],
        "residuals": result["residuals"],
        "error": result["error"],
    })


# ---------------------------------------------------------------------------
# tolerance_auto_chain
# ---------------------------------------------------------------------------

tolerance_auto_chain_spec = ToolSpec(
    name="tolerance_auto_chain",
    description=(
        "Automatically build a 1D tolerance chain by walking the assembly mate "
        "graph between two feature references. Returns a chain list compatible "
        "with tolerance_stack. Distance/angle mates contribute their nominal "
        "value + tolerance; coincident/concentric/parallel/perpendicular/tangent "
        "contribute zero unless they carry a tolerance slot."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly_file_id": {
                "type": "string",
                "description": "UUID of the .assembly file to walk.",
            },
            "start_ref": {
                "type": "object",
                "description": "Start feature reference.",
                "properties": {
                    "component_id": {"type": "string"},
                    "feature_id": {"type": "string"},
                },
                "required": ["component_id", "feature_id"],
            },
            "end_ref": {
                "type": "object",
                "description": "End feature reference.",
                "properties": {
                    "component_id": {"type": "string"},
                    "feature_id": {"type": "string"},
                },
                "required": ["component_id", "feature_id"],
            },
        },
        "required": ["assembly_file_id", "start_ref", "end_ref"],
    },
)


@register(tolerance_auto_chain_spec)
async def run_tolerance_auto_chain(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    assembly_file_id = a.get("assembly_file_id", "").strip()
    start_ref = a.get("start_ref")
    end_ref = a.get("end_ref")

    if not assembly_file_id:
        return err_payload("assembly_file_id is required", "BAD_ARGS")
    if not start_ref or not isinstance(start_ref, dict):
        return err_payload("start_ref is required", "BAD_ARGS")
    if not end_ref or not isinstance(end_ref, dict):
        return err_payload("end_ref is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(assembly_file_id)
    except Exception:
        return err_payload("assembly_file_id must be a uuid", "BAD_ARGS")

    row = await _get_assembly_file(ctx, fid)
    if not row:
        return err_payload("assembly file not found", "NOT_FOUND")
    if row["kind"] != "assembly":
        return err_payload(f"file kind '{row['kind']}' is not an assembly", "BAD_KIND")

    content = row["content"] or "{}"
    try:
        doc = json.loads(content)
    except Exception:
        return err_payload("assembly file content is invalid JSON", "BAD_FILE")
    if not isinstance(doc, dict):
        return err_payload("assembly file content is invalid JSON object", "BAD_FILE")

    from kerf_mates.chain_walk import build_chain_from_assembly

    result = build_chain_from_assembly(doc, start_ref, end_ref)

    if isinstance(result, dict) and "error" in result:
        return err_payload(result["error"], result.get("code", "NO_PATH"))

    return ok_payload({
        "assembly_file_id": assembly_file_id,
        "start_ref": start_ref,
        "end_ref": end_ref,
        "chain": result,
        "chain_length": len(result),
    })


# ---------------------------------------------------------------------------
# add_joint
# ---------------------------------------------------------------------------

add_joint_spec = ToolSpec(
    name="add_joint",
    description=(
        "Add a kinematic joint to an assembly file. "
        "Joints constrain the motion between two bodies with a specified "
        "number of degrees of freedom. Supported types: rigid (0 DOF), "
        "revolute (1 rotational DOF), slider (1 translational DOF), "
        "cam (cam-follower, 1 DOF), gear (gear pair, 1 DOF), "
        "pin_slot (pin-in-slot, 1 DOF)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly_file_id": {"type": "string"},
            "joint": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["rigid", "revolute", "slider", "cam", "gear", "pin_slot"],
                    },
                    "body_a": {"type": "string", "description": "component_id of the first body"},
                    "body_b": {"type": "string", "description": "component_id of the second body"},
                    # revolute / slider
                    "origin": {
                        "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                        "description": "Joint origin in assembly frame [x,y,z] mm",
                    },
                    "axis": {
                        "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                        "description": "Joint axis direction (unit vector)",
                    },
                    "angle_min": {"type": "number", "description": "Revolute lower limit (rad)"},
                    "angle_max": {"type": "number", "description": "Revolute upper limit (rad)"},
                    "limit_min": {"type": "number", "description": "Slider lower limit (mm)"},
                    "limit_max": {"type": "number", "description": "Slider upper limit (mm)"},
                    # cam
                    "cam_origin": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "cam_axis": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "follower_axis": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "cam_radius_mm": {"type": "number"},
                    "eccentricity_mm": {"type": "number"},
                    "follower_min_mm": {"type": "number"},
                    "follower_max_mm": {"type": "number"},
                    # gear
                    "origin_a": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "origin_b": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "axis_a": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "axis_b": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "gear_ratio": {"type": "number", "description": "N_b / N_a"},
                    "internal_mesh": {"type": "boolean", "description": "True = ring gear (same rotation direction)"},
                    "angle_min_a": {"type": "number"},
                    "angle_max_a": {"type": "number"},
                    # pin_slot
                    "slot_origin": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "slot_axis": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "slot_length_min": {"type": "number"},
                    "slot_length_max": {"type": "number"},
                },
                "required": ["type", "body_a", "body_b"],
            },
        },
        "required": ["assembly_file_id", "joint"],
    },
)


@register(add_joint_spec, write=True)
async def run_add_joint(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    assembly_file_id = a.get("assembly_file_id", "").strip()
    if not assembly_file_id:
        return err_payload("assembly_file_id is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(assembly_file_id)
    except Exception:
        return err_payload("assembly_file_id must be a uuid", "BAD_ARGS")

    joint = a.get("joint", {})
    if not joint:
        return err_payload("joint is required", "BAD_ARGS")

    jtype = joint.get("type", "")
    from kerf_mates.joints import JOINT_TYPES
    if jtype not in JOINT_TYPES:
        return err_payload(
            f"invalid joint type: {jtype}; must be one of {sorted(JOINT_TYPES)}",
            "BAD_JOINT",
        )

    if not joint.get("body_a"):
        return err_payload("joint.body_a is required", "BAD_JOINT")
    if not joint.get("body_b"):
        return err_payload("joint.body_b is required", "BAD_JOINT")

    # Validate joint can be constructed
    try:
        from kerf_mates.joints import make_joint
        make_joint({**joint, "id": joint.get("id", "_validate_")})
    except Exception as exc:
        return err_payload(f"invalid joint spec: {exc}", "BAD_JOINT")

    row = await _get_assembly_file(ctx, fid)
    if not row:
        return err_payload("assembly file not found", "NOT_FOUND")
    if row["kind"] != "assembly":
        return err_payload(f"file kind '{row['kind']}' is not an assembly", "BAD_KIND")

    content = row["content"] or "{}"
    try:
        doc = json.loads(content)
    except Exception:
        doc = {}
    if not isinstance(doc, dict):
        return err_payload("assembly file content is invalid JSON object", "BAD_FILE")

    existing_ids = {j["id"] for j in doc.get("joints", [])
                   if isinstance(j, dict) and j.get("id")}

    joint_id = joint.get("id", "")
    if not joint_id or joint_id in existing_ids:
        base = f"{jtype}-joint"
        joint_id = base
        i = 1
        while joint_id in existing_ids:
            joint_id = f"{base}-{i}"
            i += 1

    joint["id"] = joint_id
    doc.setdefault("joints", []).append(joint)

    new_content = json.dumps(doc, separators=(",", ":"))
    await ctx.pool.execute(
        "UPDATE files SET content = $1, updated_at = now() "
        "WHERE id = $2 AND project_id = $3",
        new_content, fid, ctx.project_id,
    )

    return ok_payload({
        "assembly_file_id": assembly_file_id,
        "joint_id": joint_id,
        "type": jtype,
        "dof": make_joint({**joint}).dof,
    })


# ---------------------------------------------------------------------------
# solve_joints
# ---------------------------------------------------------------------------

solve_joints_spec = ToolSpec(
    name="solve_joints",
    description=(
        "Analytically solve the kinematic joints in an assembly for given "
        "drive inputs. Returns the resulting body positions / orientations "
        "for each joint. Drive values: revolute = angle (rad), "
        "slider/pin_slot = displacement (mm), cam = cam angle (rad), "
        "gear = input shaft angle (rad)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly_file_id": {"type": "string"},
            "drives": {
                "type": "object",
                "description": "Mapping of joint_id → drive value",
                "additionalProperties": {"type": "number"},
            },
        },
        "required": ["assembly_file_id"],
    },
)


@register(solve_joints_spec)
async def run_solve_joints(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    assembly_file_id = a.get("assembly_file_id", "").strip()
    if not assembly_file_id:
        return err_payload("assembly_file_id is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(assembly_file_id)
    except Exception:
        return err_payload("assembly_file_id must be a uuid", "BAD_ARGS")

    drives = a.get("drives", {})
    if not isinstance(drives, dict):
        return err_payload("drives must be an object", "BAD_ARGS")

    row = await _get_assembly_file(ctx, fid)
    if not row:
        return err_payload("assembly file not found", "NOT_FOUND")
    if row["kind"] != "assembly":
        return err_payload(f"file kind '{row['kind']}' is not an assembly", "BAD_KIND")

    content = row["content"] or "{}"
    try:
        doc = json.loads(content)
    except Exception:
        return err_payload("assembly file content is invalid JSON", "BAD_FILE")
    if not isinstance(doc, dict):
        return err_payload("assembly file content is invalid JSON object", "BAD_FILE")

    joints = doc.get("joints", [])

    from kerf_mates.joints import solve_joints as _solve_joints
    result = _solve_joints(joints, drives)

    return ok_payload({
        "assembly_file_id": assembly_file_id,
        "results": result["results"],
        "errors": result["errors"],
        "joint_count": len(joints),
    })
