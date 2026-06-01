"""
feature_loft_with_rails — GK-P-D: loft with multiple guide rails.

Appends a ``loft_with_rails`` feature node to a ``.feature`` JSON file.

This is the multi-rail extension of ``feature_loft``.  Where ``feature_loft``
accepts zero or one guide spine, ``feature_loft_with_rails`` explicitly
requires at least one rail and supports an arbitrary number of rail curves
(e.g. sheer + chine(s) + keel for hull surfaces).

The pure-Python kernel path delegates to
``kerf_cad_core.geom.loft_rails.loft_with_rails`` which uses a Gordon-surface
construction (Piegl & Tiller §10.4) to ensure every intermediate profile
section rides on all supplied guide rails.

Gordon surface overview
-----------------------
  G(u, v) = Σ_i L_i(v)·p_i(u)  +  Σ_j M_j(u)·r_j(v)
           − Σ_i Σ_j L_i(v)·M_j(u)·P_ij

where p_i are the profiles, r_j are the rails, and P_ij are their (snapped)
intersection points.  The surface interpolates both curve families exactly.

Tangent continuity
------------------
Set ``tangent_mode: "perpendicular"`` (default) to constrain the surface
tangent perpendicular to each rail tangent (G1 continuity condition at
rails).  Set ``tangent_mode: "normal"`` and supply per-rail normals via
``normal_field`` for explicit normal direction control (G2-style advanced
use).
"""

from __future__ import annotations

import json
import uuid

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx
from kerf_cad_core.surfacing import next_node_id, read_feature_content, append_feature_node

VALID_TANGENT_MODES = {"perpendicular", "normal"}


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def validate_loft_with_rails_args(
    profile_sketch_paths: object,
    rail_sketch_paths: object,
    ruled: object,
    closed: object,
    tangent_mode: object,
) -> tuple[str | None, str | None]:
    """Validate args; return (error_msg, error_code) or (None, None) on success."""
    # profiles
    if not isinstance(profile_sketch_paths, list):
        return "profile_sketch_paths must be a list", "BAD_ARGS"
    if len(profile_sketch_paths) < 2:
        return "profile_sketch_paths must contain at least 2 sketch paths", "BAD_ARGS"
    for i, p in enumerate(profile_sketch_paths):
        if not isinstance(p, str) or not p.strip():
            return f"profile_sketch_paths[{i}] must be a non-empty string", "BAD_ARGS"
        if not p.endswith(".sketch"):
            return f"profile_sketch_paths[{i}] must end in '.sketch'", "BAD_ARGS"

    # rails
    if not isinstance(rail_sketch_paths, list):
        return "rail_sketch_paths must be a list", "BAD_ARGS"
    if len(rail_sketch_paths) < 1:
        return "rail_sketch_paths must contain at least 1 rail sketch path", "BAD_ARGS"
    for i, p in enumerate(rail_sketch_paths):
        if not isinstance(p, str) or not p.strip():
            return f"rail_sketch_paths[{i}] must be a non-empty string", "BAD_ARGS"
        if not p.endswith(".sketch"):
            return f"rail_sketch_paths[{i}] must end in '.sketch'", "BAD_ARGS"

    if not isinstance(ruled, bool):
        return "ruled must be a boolean", "BAD_ARGS"
    if not isinstance(closed, bool):
        return "closed must be a boolean", "BAD_ARGS"

    mode = (tangent_mode or "perpendicular").lower()
    if mode not in VALID_TANGENT_MODES:
        return (
            f"tangent_mode must be one of {sorted(VALID_TANGENT_MODES)}, "
            f"got '{tangent_mode}'",
            "BAD_ARGS",
        )

    return None, None


# ---------------------------------------------------------------------------
# Node builder
# ---------------------------------------------------------------------------

def build_loft_with_rails_node(
    node_id: str,
    profile_sketch_paths: list,
    rail_sketch_paths: list,
    ruled: bool,
    closed: bool,
    tangent_mode: str,
    name: str = "",
) -> dict:
    """Return the feature-node dict for a loft_with_rails operation."""
    node: dict = {
        "id": node_id,
        "op": "loft_with_rails",
        "profile_sketch_paths": list(profile_sketch_paths),
        "rail_sketch_paths": list(rail_sketch_paths),
        "ruled": ruled,
        "closed": closed,
        "tangent_mode": tangent_mode.lower(),
    }
    if name:
        node["name"] = name
    return node


# ---------------------------------------------------------------------------
# LLM ToolSpec
# ---------------------------------------------------------------------------

feature_loft_with_rails_spec = ToolSpec(
    name="feature_loft_with_rails",
    description=(
        "Append a `loft_with_rails` node to a `.feature` file.  "
        "Loft a set of profile cross-sections constrained to ride along "
        "**one or more guide rail curves simultaneously** using a "
        "Gordon-surface construction (Piegl & Tiller §10.4).  "
        "\n\n"
        "**When to use over `feature_loft`:**  "
        "Use this tool whenever you need intermediate profile sections to "
        "precisely follow specific 3-D curves — e.g. hull surfaces with "
        "sheer + chine + keel rails, wing skin with spanwise guide curves, "
        "or ergonomic grips with fingertip-contour rails.  "
        "`feature_loft` supports at most one guide spine; this tool supports "
        "an arbitrary number of simultaneous rail curves.  "
        "\n\n"
        "**Gordon surface:**  "
        "The kernel builds ``G(u,v) = Σ L_i(v)·p_i(u) + Σ M_j(u)·r_j(v) "
        "− Σ L_i(v)·M_j(u)·P_ij`` where p_i are the profiles, r_j are the "
        "rails, and P_ij are their snapped intersection points.  Both curve "
        "families are interpolated within the grid sampling precision.  "
        "\n\n"
        "**Rail ordering:**  Rails should be supplied in a spatially "
        "consistent order (e.g. port → centre → starboard for a hull).  "
        "u-parameters are evenly spaced across all rails.  "
        "\n\n"
        "**Tangent continuity:**  "
        "``tangent_mode: 'perpendicular'`` (default) constrains the surface "
        "tangent perpendicular to the rail tangent at each rail (G1-like "
        "behaviour at rail curves).  ``'normal'`` uses explicit per-rail "
        "normal vectors from the feature data for advanced surface shaping.  "
        "\n\n"
        "**OCCT path:**  The OCCT worker routes profiles through "
        "``BRepOffsetAPI_ThruSections`` and passes rails through the guide "
        "spine overload; the pure-Python kernel uses the Gordon formula.  "
        "\n\n"
        "Not compatible with `symmetric: true` (use `feature_loft` for "
        "symmetric thin-walled bodies)."
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
                    "Ordered list of absolute .sketch file paths for the "
                    "cross-section profiles (≥2).  "
                    "Profiles are the u-family curves of the Gordon surface."
                ),
            },
            "rail_sketch_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Ordered list of absolute .sketch file paths for the "
                    "guide rails (≥1, typically 2–4 for hull-style work).  "
                    "Rails are the v-family curves of the Gordon surface.  "
                    "Supply in consistent spatial order (e.g. port to "
                    "starboard).  Rails need not mathematically intersect "
                    "the profiles; the kernel snaps anchor points."
                ),
            },
            "ruled": {
                "type": "boolean",
                "description": (
                    "True = linear (ruled) blending between profiles. "
                    "When guide rails are present the Gordon surface always "
                    "interpolates the rails exactly; 'ruled' only affects "
                    "how the intermediate profile blending is computed. "
                    "Default false."
                ),
            },
            "closed": {
                "type": "boolean",
                "description": (
                    "True = join last profile back to first (closed periodic "
                    "loft; first and last profiles should be coincident). "
                    "Default false."
                ),
            },
            "tangent_mode": {
                "type": "string",
                "enum": ["perpendicular", "normal"],
                "description": (
                    "Tangent continuity mode at rail curves.  "
                    "'perpendicular' (default) = surface tangent "
                    "perpendicular to rail tangent (G1-like).  "
                    "'normal' = explicit per-rail normal direction."
                ),
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
        "required": ["file_id", "profile_sketch_paths", "rail_sketch_paths"],
    },
)


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

@register(feature_loft_with_rails_spec, write=True)
async def run_feature_loft_with_rails(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    # Required params
    file_id = a.get("file_id", "").strip()
    profile_sketch_paths = a.get("profile_sketch_paths")
    rail_sketch_paths = a.get("rail_sketch_paths")

    if not file_id:
        return err_payload("file_id is required", "BAD_ARGS")
    if profile_sketch_paths is None:
        return err_payload("profile_sketch_paths is required", "BAD_ARGS")
    if rail_sketch_paths is None:
        return err_payload("rail_sketch_paths is required", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a valid UUID", "BAD_ARGS")

    # Optional params with defaults
    ruled = bool(a.get("ruled", False))
    closed = bool(a.get("closed", False))
    tangent_mode = a.get("tangent_mode", "perpendicular")
    name = a.get("name", "").strip() or ""
    node_id = a.get("id", "").strip()

    # Validate
    err_msg, err_code = validate_loft_with_rails_args(
        profile_sketch_paths, rail_sketch_paths, ruled, closed, tangent_mode,
    )
    if err_msg:
        return err_payload(err_msg, err_code)

    # Read target file
    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "loft_with_rails")

    # Build and append node
    node = build_loft_with_rails_node(
        node_id,
        list(profile_sketch_paths),
        list(rail_sketch_paths),
        ruled,
        closed,
        tangent_mode or "perpendicular",
        name,
    )

    _, nid, err = append_feature_node(ctx, fid, node)
    if err:
        return err_payload(err, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid,
        "op": "loft_with_rails",
        "num_profiles": len(profile_sketch_paths),
        "num_rails": len(rail_sketch_paths),
        "tangent_mode": tangent_mode or "perpendicular",
    })
