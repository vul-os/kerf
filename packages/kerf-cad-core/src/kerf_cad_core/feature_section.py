"""
feature_section — append a ``section`` feature node to a ``.feature`` JSON file.

Intersects a solid body with a plane using OCCT's ``BRepAlgoAPI_Section`` and
returns the resulting intersection edges as a 2D outline compound.

The result is **not** a solid — it is a ``TopoDS_Compound`` of edges.  The
worker stores it as a ``.section`` file kind so it can be dimensioned,
exported to DXF, or chained into ``feature_pad`` later.

Schema of the emitted feature node
-----------------------------------
::

    {
      "id": "section-1",
      "op": "section",
      "target_solid_ref": "pad-1",
      "plane": {
        "point":  [0.0, 0.0, 0.0],
        "normal": [0.0, 0.0, 1.0]
      }
    }
"""

from __future__ import annotations

import json
import uuid

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import next_node_id, read_feature_content, append_feature_node


# ── Pure validation helpers ───────────────────────────────────────────────────

def _is_xyz(v: object) -> bool:
    """Return True if *v* is a list/tuple of exactly 3 numbers."""
    if not isinstance(v, (list, tuple)):
        return False
    if len(v) != 3:
        return False
    return all(isinstance(x, (int, float)) for x in v)


def validate_section_args(
    target_solid_ref: object,
    plane: object,
) -> tuple[str | None, str | None]:
    """Validate args; return (error_msg, error_code) or (None, None) on success."""
    if not isinstance(target_solid_ref, str) or not target_solid_ref.strip():
        return "target_solid_ref must be a non-empty string (node id of the target solid)", "BAD_ARGS"

    if not isinstance(plane, dict):
        return "plane must be an object with 'point' and 'normal' keys", "BAD_ARGS"

    point  = plane.get("point")
    normal = plane.get("normal")

    if point is None:
        return "plane.point is required — provide [x, y, z]", "BAD_ARGS"
    if not _is_xyz(point):
        return "plane.point must be a list of exactly 3 numbers [x, y, z]", "BAD_ARGS"

    if normal is None:
        return "plane.normal is required — provide [x, y, z]", "BAD_ARGS"
    if not _is_xyz(normal):
        return "plane.normal must be a list of exactly 3 numbers [x, y, z]", "BAD_ARGS"

    nx, ny, nz = normal
    mag_sq = nx * nx + ny * ny + nz * nz
    if mag_sq < 1e-20:
        return "plane.normal must not be a zero vector", "BAD_ARGS"

    return None, None


def build_section_node(
    node_id: str,
    target_solid_ref: str,
    plane_point: list,
    plane_normal: list,
    name: str = "",
) -> dict:
    """Return the feature-node dict for a section operation."""
    node: dict = {
        "id": node_id,
        "op": "section",
        "target_solid_ref": target_solid_ref,
        "plane": {
            "point":  list(plane_point),
            "normal": list(plane_normal),
        },
    }
    if name:
        node["name"] = name
    return node


# ── LLM tool spec ─────────────────────────────────────────────────────────────

feature_section_spec = ToolSpec(
    name="feature_section",
    description=(
        "Append a `section` node to a `.feature` file.  "
        "Intersects a solid body with a plane using `BRepAlgoAPI_Section` "
        "(OCCT) and returns the resulting edge compound (a 2D cross-section "
        "outline).  "
        "\n\n"
        "The result is **not** a solid — it is a compound of edges.  "
        "It is saved as a `.section` file kind so it can be dimensioned, "
        "exported to DXF, or chained into `feature_pad`. "
        "\n\n"
        "**Plane definition**: supply a point on the plane (`plane.point`) and "
        "the outward normal (`plane.normal`).  Common shortcuts: "
        "`normal: [0,0,1]` → XY plane, `normal: [0,1,0]` → XZ plane, "
        "`normal: [1,0,0]` → YZ plane.  "
        "\n\n"
        "Requires `BRepAlgoAPI_Section` to be present in the OCCT WASM build "
        "(C1 probe reports OK/MISSING at worker boot).  If MISSING the worker "
        "will error with a clear message; no fallback is available for this op."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_solid_ref": {
                "type": "string",
                "description": (
                    "Node id of the solid to slice (must already exist in the "
                    "feature tree, e.g. 'pad-1')."
                ),
            },
            "plane": {
                "type": "object",
                "description": "The cutting plane, defined by a point and a normal vector.",
                "properties": {
                    "point": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                        "description": "A point on the cutting plane [x, y, z] in mm.",
                    },
                    "normal": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                        "description": (
                            "Normal vector of the cutting plane [x, y, z]. "
                            "Does not need to be unit-length; the worker normalises it."
                        ),
                    },
                },
                "required": ["point", "normal"],
            },
            "name": {
                "type": "string",
                "description": "Optional human-readable label for the feature node.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id (e.g. 'section-1'). Auto-generated if omitted.",
            },
        },
        "required": ["file_id", "target_solid_ref", "plane"],
    },
)


@register(feature_section_spec, write=True)
async def run_feature_section(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    # ── required params ──────────────────────────────────────────────────────
    file_id          = a.get("file_id", "").strip()
    target_solid_ref = a.get("target_solid_ref", "")
    plane            = a.get("plane")

    if not file_id:
        return err_payload("file_id is required", "BAD_ARGS")
    if not target_solid_ref:
        return err_payload("target_solid_ref is required", "BAD_ARGS")
    if plane is None:
        return err_payload("plane is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a valid UUID", "BAD_ARGS")

    # ── optional params ──────────────────────────────────────────────────────
    name    = a.get("name", "").strip() or ""
    node_id = a.get("id",   "").strip()

    # ── validate ─────────────────────────────────────────────────────────────
    err_msg, err_code = validate_section_args(target_solid_ref, plane)
    if err_msg:
        return err_payload(err_msg, err_code)

    plane_point  = list(plane["point"])
    plane_normal = list(plane["normal"])

    # ── read target file ─────────────────────────────────────────────────────
    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "section")

    # ── build and append node ─────────────────────────────────────────────────
    node = build_section_node(
        node_id,
        target_solid_ref,
        plane_point,
        plane_normal,
        name,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id":          file_id,
        "id":               nid,
        "op":               "section",
        "target_solid_ref": target_solid_ref,
        "plane":            node["plane"],
    })
