"""
feature_boss_with_draft — FreeCAD-parity shortcut: pad + draft in one node.

Appends a ``boss_with_draft`` feature node to a ``.feature`` JSON file.
The OCCT worker (``opBossWithDraft``) evaluates the node at render time:

1. Extrude the sketch profile via ``BRepPrimAPI_MakePrism``.
2. Walk all side faces (``walkSideFaces`` helper).
3. Apply per-face taper via ``BRepOffsetAPI_DraftAngle`` with the sketch
   plane as the neutral plane.
"""

from __future__ import annotations

import json
import uuid

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import next_node_id, read_feature_content, append_feature_node

DRAFT_ANGLE_MIN = -30.0
DRAFT_ANGLE_MAX = 30.0
VALID_DIRECTIONS = {"up", "down", "symmetric"}
VALID_DRAFT_DIRECTIONS = {"outward", "inward"}


# ── Pure validation helper ────────────────────────────────────────────────────

def validate_boss_with_draft_args(
    sketch_path: str,
    height: object,
    direction: str,
    draft_angle_deg: object,
    draft_direction: str,
) -> tuple[str | None, str | None]:
    """Validate args; return (error_msg, error_code) or (None, None) on success."""
    if not sketch_path or not isinstance(sketch_path, str) or not sketch_path.strip():
        return "sketch_path is required and must be a non-empty string", "BAD_ARGS"
    if not sketch_path.endswith(".sketch"):
        return "sketch_path must end in '.sketch'", "BAD_ARGS"
    if not isinstance(height, (int, float)):
        return "height must be a number", "BAD_ARGS"
    if height <= 0:
        return "height must be > 0", "BAD_ARGS"
    if direction not in VALID_DIRECTIONS:
        return (
            f"direction must be one of {sorted(VALID_DIRECTIONS)}, got '{direction}'",
            "BAD_ARGS",
        )
    if not isinstance(draft_angle_deg, (int, float)):
        return "draft_angle_deg must be a number", "BAD_ARGS"
    if draft_angle_deg < DRAFT_ANGLE_MIN or draft_angle_deg > DRAFT_ANGLE_MAX:
        return (
            f"draft_angle_deg must be in [{DRAFT_ANGLE_MIN}, {DRAFT_ANGLE_MAX}], "
            f"got {draft_angle_deg}",
            "BAD_ARGS",
        )
    if draft_direction not in VALID_DRAFT_DIRECTIONS:
        return (
            f"draft_direction must be 'outward' or 'inward', got '{draft_direction}'",
            "BAD_ARGS",
        )
    return None, None


def build_boss_with_draft_node(
    node_id: str,
    sketch_path: str,
    height: float,
    direction: str,
    draft_angle_deg: float,
    draft_direction: str,
    name: str = "",
) -> dict:
    """Return the feature-node dict for a boss_with_draft operation."""
    node: dict = {
        "id": node_id,
        "op": "boss_with_draft",
        "sketch_path": sketch_path,
        "height": float(height),
        "direction": direction,
        "draft_angle_deg": float(draft_angle_deg),
        "draft_direction": draft_direction,
    }
    if name:
        node["name"] = name
    return node


# ── LLM tool spec ─────────────────────────────────────────────────────────────

feature_boss_with_draft_spec = ToolSpec(
    name="feature_boss_with_draft",
    description=(
        "Append a `boss_with_draft` node to a `.feature` file. "
        "FreeCAD-parity shortcut: extrudes a sketch profile (like `pad`) "
        "AND applies a draft taper to all side faces in a single step. "
        "Eliminates the separate pad + face-picking + feature_draft workflow. "
        "The neutral plane for the draft is always the sketch plane. "
        "`draft_angle_deg` is clamped to [-30, 30]; positive values produce "
        "outward taper (wider at the base), negative inward (narrower at the base) "
        "when `draft_direction` is 'outward'. "
        "Use `draft_angle_deg=0` for a plain pad without taper (a warning hint "
        "is emitted but the node is valid). "
        "OCCT path: BRepPrimAPI_MakePrism → walkSideFaces → BRepOffsetAPI_DraftAngle."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "sketch_path": {
                "type": "string",
                "description": (
                    "Absolute path of the closed-profile .sketch file "
                    "(e.g. '/profile.sketch')."
                ),
            },
            "height": {
                "type": "number",
                "description": "Extrusion height in mm. Must be > 0.",
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down", "symmetric"],
                "description": (
                    "'up' = extrude along +Z (default), "
                    "'down' = along -Z, "
                    "'symmetric' = centred on the sketch plane."
                ),
            },
            "draft_angle_deg": {
                "type": "number",
                "description": (
                    "Draft taper angle in degrees. "
                    "Must be in [-30, 30]. "
                    "0 = no taper (degenerates to a plain pad; allowed but emits a hint). "
                    "Positive = combined with draft_direction to widen away from sketch plane."
                ),
            },
            "draft_direction": {
                "type": "string",
                "enum": ["outward", "inward"],
                "description": (
                    "'outward' = side faces widen away from the sketch plane (default). "
                    "'inward' = side faces narrow toward the sketch plane."
                ),
            },
            "name": {
                "type": "string",
                "description": "Optional human-readable label for the feature node.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id (e.g. 'boss-1'). Auto-generated if omitted.",
            },
        },
        "required": ["file_id", "sketch_path", "height", "draft_angle_deg"],
    },
)


@register(feature_boss_with_draft_spec, write=True)
async def run_feature_boss_with_draft(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    # ── required params ──────────────────────────────────────────────────────
    file_id = a.get("file_id", "").strip()
    sketch_path = a.get("sketch_path", "").strip()
    height = a.get("height")
    draft_angle_deg = a.get("draft_angle_deg")

    if not file_id:
        return err_payload("file_id is required", "BAD_ARGS")
    if height is None:
        return err_payload("height is required", "BAD_ARGS")
    if draft_angle_deg is None:
        return err_payload("draft_angle_deg is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a valid UUID", "BAD_ARGS")

    # ── optional params with defaults ────────────────────────────────────────
    direction = a.get("direction", "up")
    draft_direction = a.get("draft_direction", "outward")
    name = a.get("name", "").strip() or ""
    node_id = a.get("id", "").strip()

    # ── validate ─────────────────────────────────────────────────────────────
    err_msg, err_code = validate_boss_with_draft_args(
        sketch_path, height, direction, draft_angle_deg, draft_direction
    )
    if err_msg:
        return err_payload(err_msg, err_code)

    # ── read target file ─────────────────────────────────────────────────────
    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "boss_with_draft")

    # ── build and append node ─────────────────────────────────────────────────
    node = build_boss_with_draft_node(
        node_id, sketch_path, height, direction,
        draft_angle_deg, draft_direction, name,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    result: dict = {
        "file_id": file_id,
        "id": nid,
        "op": "boss_with_draft",
    }
    if draft_angle_deg == 0:
        result["hint"] = (
            "draft_angle_deg is 0 — the result is equivalent to a plain pad. "
            "Set a non-zero angle to get the taper effect."
        )
    return ok_payload(result)
