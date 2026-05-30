"""GK-82 ext — LLM tool: brep_imprint_body.

Projects all edges of a tool body onto a target body's faces, splitting
the target faces along each projected curve and tagging the new edges with
imprint provenance (source_body_id + source_edge_id).

This module registers ``brep_imprint_body`` in the kerf tool registry so
the chat agent can invoke it.  The tool operates entirely on in-memory
B-rep ``Body`` objects serialised as JSON feature-tree node references.

Since the pure-Python B-rep layer does not have a persistent file store,
this tool accepts JSON-serialised body descriptions for hermetic testing
and returns a structured imprint report.  In production the caller passes
``target_body_json`` / ``tool_body_json`` obtained from the feature DAG.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional registry import (graceful stub when kerf_chat not installed)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    _HAS_REGISTRY = True
except ImportError:
    _HAS_REGISTRY = False

    class ToolSpec:  # type: ignore[no-redef]
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def err_payload(msg: str, code: str = "ERROR") -> str:
        return json.dumps({"ok": False, "reason": msg, "code": code})

    def ok_payload(data: dict) -> str:
        return json.dumps({"ok": True, **data})

    def register(spec, write: bool = False):  # type: ignore[misc]
        def decorator(fn):
            return fn
        return decorator

try:
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
except ImportError:
    class ProjectCtx:  # type: ignore[no-redef]
        pass


# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

brep_imprint_body_spec = ToolSpec(
    name="brep_imprint_body",
    description=(
        "Project all edges of a *tool* B-rep body onto the faces of a "
        "*target* B-rep body, splitting target faces along each projected "
        "curve and tagging every new edge with imprint provenance "
        "(source_body_id + source_edge_id). "
        "\n\n"
        "Use this to transfer geometry from one body onto another — e.g. "
        "project a mating-surface footprint onto a base plate, or imprint "
        "a flange outline onto a shell. "
        "\n\n"
        "``mode='intersect'`` (default) only imprints where the tool edge "
        "plausibly intersects or lies on the target face (proximity filter). "
        "``mode='all'`` projects every tool edge onto every face — useful "
        "for design-intent transfer regardless of geometric overlap. "
        "\n\n"
        "Returns a report with the number of successful imprints and a "
        "mapping of new-edge ids to their source body/edge ids."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_body_json": {
                "type": "string",
                "description": (
                    "JSON-serialised description of the target body.  "
                    "Currently accepts a box spec: "
                    "{\"type\": \"box\", \"origin\": [x,y,z], \"size\": [sx,sy,sz]} "
                    "or {\"type\": \"sphere\", \"center\": [x,y,z], \"radius\": r}."
                ),
            },
            "tool_body_json": {
                "type": "string",
                "description": (
                    "JSON-serialised description of the tool body (same schema as "
                    "target_body_json)."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["intersect", "all"],
                "description": (
                    "Imprint mode: 'intersect' (default) only imprints where tool "
                    "edges are geometrically near a target face; 'all' projects "
                    "regardless of proximity."
                ),
                "default": "intersect",
            },
        },
        "required": ["target_body_json", "tool_body_json"],
    },
)


# ---------------------------------------------------------------------------
# Body builder helper (JSON spec → Body)
# ---------------------------------------------------------------------------

def _body_from_spec(spec: dict):
    """Build a B-rep Body from a minimal JSON spec dict."""
    from kerf_cad_core.geom.brep import make_box, make_sphere

    kind = spec.get("type", "box")
    if kind == "box":
        origin = tuple(float(v) for v in spec.get("origin", [0, 0, 0]))
        size = tuple(float(v) for v in spec.get("size", [1, 1, 1]))
        return make_box(origin=origin, size=size)
    if kind == "sphere":
        import numpy as np
        center = np.array([float(v) for v in spec.get("center", [0, 0, 0])])
        radius = float(spec.get("radius", 1.0))
        return make_sphere(center=center, radius=radius)
    raise ValueError(f"Unknown body type {kind!r}; expected 'box' or 'sphere'")


# ---------------------------------------------------------------------------
# LLM handler
# ---------------------------------------------------------------------------

@register(brep_imprint_body_spec, write=False)
async def run_brep_imprint_body(ctx: "ProjectCtx", args: bytes) -> str:
    """Handle ``brep_imprint_body`` tool calls from the chat agent."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid JSON args: {exc}", "BAD_ARGS")

    # Parse mode
    mode = str(a.get("mode", "intersect"))
    if mode not in ("intersect", "all"):
        return err_payload(
            f"mode must be 'intersect' or 'all', got {mode!r}", "BAD_ARGS"
        )

    # Parse target body
    raw_target = a.get("target_body_json", "")
    if not raw_target:
        return err_payload("target_body_json is required", "BAD_ARGS")
    try:
        target_spec = json.loads(raw_target)
        target = _body_from_spec(target_spec)
    except Exception as exc:
        return err_payload(f"could not build target body: {exc}", "BAD_ARGS")

    # Parse tool body
    raw_tool = a.get("tool_body_json", "")
    if not raw_tool:
        return err_payload("tool_body_json is required", "BAD_ARGS")
    try:
        tool_spec = json.loads(raw_tool)
        tool = _body_from_spec(tool_spec)
    except Exception as exc:
        return err_payload(f"could not build tool body: {exc}", "BAD_ARGS")

    # Run imprint
    try:
        from kerf_cad_core.geom.imprint import imprint_body
        result = imprint_body(target, tool, mode=mode)
    except Exception as exc:
        return err_payload(f"imprint_body failed: {exc}", "ERROR")

    # Serialise edge_tags
    tags_out = {
        str(eid): {
            "source_body_id": tag.source_body_id,
            "source_edge_id": tag.source_edge_id,
        }
        for eid, tag in result.edge_tags.items()
    }

    return ok_payload({
        "n_imprinted": result.n_imprinted,
        "n_new_edges": len(result.edge_tags),
        "n_target_faces_after": len(result.body.all_faces()),
        "edge_tags": tags_out,
        "tool_body_id": tool.id,
    })
