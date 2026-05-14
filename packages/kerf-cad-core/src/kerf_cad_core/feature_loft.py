"""
feature_loft — append a ``loft`` feature node to a ``.feature`` JSON file.

Extends the existing ``loft`` op with a ``symmetric: bool`` flag for
mid-plane symmetric thin-walled bodies.  When ``symmetric=True``:

  - Exactly **2** profile sketches are required (>2 is ambiguous — BAD_ARGS).
  - ``closed=True`` is incompatible with ``symmetric=True`` — BAD_ARGS.
  - The OCCT worker (``opLoft``) computes the mid-plane between the two
    sketch planes, mirrors each profile across it, and feeds the sequence
    ``[p1, p2, mirror(p2), mirror(p1)]`` to ``BRepOffsetAPI_ThruSections``.
  - Non-parallel sketch planes produce a BAD_ARGS guard in the worker.

When ``symmetric=False`` (default) the behaviour is **identical** to the
original ``loft`` node — no regression.
"""

from __future__ import annotations

import json
import uuid

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import next_node_id, read_feature_content, append_feature_node

VALID_CONTINUITY = {"C0", "C1", "C2"}


# ── Pure validation helper ────────────────────────────────────────────────────

def validate_loft_args(
    profile_sketch_paths: object,
    ruled: object,
    closed: object,
    symmetric: object,
    continuity: object,
) -> tuple[str | None, str | None]:
    """Validate args; return (error_msg, error_code) or (None, None) on success."""
    if not isinstance(profile_sketch_paths, list):
        return "profile_sketch_paths must be a list", "BAD_ARGS"
    if len(profile_sketch_paths) < 2:
        return "profile_sketch_paths must contain at least 2 sketch paths", "BAD_ARGS"
    for i, p in enumerate(profile_sketch_paths):
        if not isinstance(p, str) or not p.strip():
            return f"profile_sketch_paths[{i}] must be a non-empty string", "BAD_ARGS"
        if not p.endswith(".sketch"):
            return f"profile_sketch_paths[{i}] must end in '.sketch'", "BAD_ARGS"

    if not isinstance(ruled, bool):
        return "ruled must be a boolean", "BAD_ARGS"
    if not isinstance(closed, bool):
        return "closed must be a boolean", "BAD_ARGS"
    if not isinstance(symmetric, bool):
        return "symmetric must be a boolean", "BAD_ARGS"

    if symmetric and len(profile_sketch_paths) != 2:
        return (
            "symmetric mode requires exactly 2 profile sketches; "
            f"got {len(profile_sketch_paths)}",
            "BAD_ARGS",
        )
    if symmetric and closed:
        return "symmetric and closed cannot both be true", "BAD_ARGS"
    if closed and len(profile_sketch_paths) < 3:
        return "closed loft requires at least 3 profiles", "BAD_ARGS"

    cont = (continuity or "C0").upper()
    if cont not in VALID_CONTINUITY:
        return (
            f"continuity must be one of {sorted(VALID_CONTINUITY)}, got '{continuity}'",
            "BAD_ARGS",
        )

    return None, None


def build_loft_node(
    node_id: str,
    profile_sketch_paths: list,
    ruled: bool,
    closed: bool,
    symmetric: bool,
    continuity: str,
    name: str = "",
) -> dict:
    """Return the feature-node dict for a loft operation."""
    node: dict = {
        "id": node_id,
        "op": "loft",
        "profile_sketch_paths": profile_sketch_paths,
        "ruled": ruled,
        "closed": closed,
        "symmetric": symmetric,
        "continuity": continuity.upper(),
    }
    if name:
        node["name"] = name
    return node


# ── LLM tool spec ─────────────────────────────────────────────────────────────

feature_loft_spec = ToolSpec(
    name="feature_loft",
    description=(
        "Append a `loft` node to a `.feature` file. "
        "Loft blends through ≥2 closed profile sketches using "
        "`BRepOffsetAPI_ThruSections`. "
        "\n\n"
        "**`symmetric: true` flag** — mid-plane symmetric loft for thin-walled "
        "bodies (handles, brackets, grips). Requires exactly 2 profiles. "
        "The worker mirrors both profiles across the mid-plane between them and "
        "feeds `[p1, p2, mirror(p2), mirror(p1)]` to ThruSections, producing a "
        "body that is symmetric about the mid-plane. "
        "Both sketch planes must be parallel (non-parallel → BAD_ARGS). "
        "Incompatible with `closed: true`. "
        "\n\n"
        "When `symmetric: false` (default) behaviour is identical to the "
        "existing loft op — no change."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "profile_sketch_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Ordered list of absolute .sketch file paths (≥2, ≥3 if closed). "
                    "When symmetric=true, exactly 2 paths are required."
                ),
            },
            "ruled": {
                "type": "boolean",
                "description": "True = linear (ruled) blends between profiles. Default false.",
            },
            "closed": {
                "type": "boolean",
                "description": (
                    "True = join last profile back to first (requires ≥3 profiles). "
                    "Incompatible with symmetric=true."
                ),
            },
            "symmetric": {
                "type": "boolean",
                "description": (
                    "True = mid-plane symmetric loft (requires exactly 2 profiles, "
                    "parallel sketch planes, closed=false). "
                    "The worker mirrors both profiles across the mid-plane and lofts "
                    "[p1, p2, mirror(p2), mirror(p1)], producing a body symmetric "
                    "about the plane equidistant from both sketches."
                ),
            },
            "continuity": {
                "type": "string",
                "enum": ["C0", "C1", "C2"],
                "description": "Blend continuity. C0=piecewise, C1/C2=NURBS smoothing. Default C0.",
            },
            "name": {
                "type": "string",
                "description": "Optional human-readable label for the feature node.",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id. Auto-generated if omitted.",
            },
        },
        "required": ["file_id", "profile_sketch_paths"],
    },
)


@register(feature_loft_spec, write=True)
async def run_feature_loft(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    # ── required params ──────────────────────────────────────────────────────
    file_id = a.get("file_id", "").strip()
    profile_sketch_paths = a.get("profile_sketch_paths")

    if not file_id:
        return err_payload("file_id is required", "BAD_ARGS")
    if profile_sketch_paths is None:
        return err_payload("profile_sketch_paths is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a valid UUID", "BAD_ARGS")

    # ── optional params with defaults ────────────────────────────────────────
    ruled = a.get("ruled", False)
    closed = a.get("closed", False)
    symmetric = a.get("symmetric", False)
    continuity = a.get("continuity", "C0")
    name = a.get("name", "").strip() or ""
    node_id = a.get("id", "").strip()

    # Coerce to bool in case JSON sends 0/1
    ruled = bool(ruled)
    closed = bool(closed)
    symmetric = bool(symmetric)

    # ── validate ─────────────────────────────────────────────────────────────
    err_msg, err_code = validate_loft_args(
        profile_sketch_paths, ruled, closed, symmetric, continuity
    )
    if err_msg:
        return err_payload(err_msg, err_code)

    # ── read target file ─────────────────────────────────────────────────────
    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "loft")

    # ── build and append node ─────────────────────────────────────────────────
    node = build_loft_node(
        node_id,
        list(profile_sketch_paths),
        ruled,
        closed,
        symmetric,
        continuity,
        name,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid,
        "op": "loft",
        "symmetric": symmetric,
    })
