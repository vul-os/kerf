"""
kerf_cad_core.drawings.tools — Wave 8 LLM tool for B-rep HLR drawings.

Wave 8 module
-------------
  kerf_cad_core.drawings.brep_hlr

Tool registered
---------------
  brep_to_2d_hlr — Project a B-rep body into standard orthographic views
    with hidden-line removal (HLR), returning SVG path data.

References
----------
Appel, A. (1967). "The Notion of Quantitative Invisibility and the Machine
    Rendering of Solids." Proc. ACM 22nd National Conference, pp. 387–393.
Markosian et al. (1997). "Real-Time Nonphotorealistic Rendering." SIGGRAPH 97, §3.
Hertzmann, A. (1999). "Introduction to 3D Non-Photorealistic Rendering." NPAR 1999.
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.drawings.brep_hlr import make_standard_views, ProjectionView
from kerf_cad_core.geom.brep import (
    Body, Face, Plane, Line3, CircleArc3,
    make_box,
)


# ---------------------------------------------------------------------------
# Tool: brep_to_2d_hlr
# ---------------------------------------------------------------------------

_brep_to_2d_hlr_spec = ToolSpec(
    name="brep_to_2d_hlr",
    description=(
        "Project a B-rep box solid into standard orthographic views "
        "(front, top, right, isometric) with hidden-line removal (HLR).\n"
        "\n"
        "Algorithm:\n"
        "  1. Tessellate each B-rep face into triangles.\n"
        "  2. For each edge, determine QI (quantitative invisibility) via\n"
        "     depth-sorted triangle occlusion checks (Appel 1967).\n"
        "  3. Classify visible vs hidden edges per view.\n"
        "  4. Return SVG path strings for each view + 2D bbox.\n"
        "\n"
        "v1 scope: box primitives only (make_box). Pass size=[w, h, d] and\n"
        "optionally origin=[x, y, z].\n"
        "\n"
        "Returns per view (front/top/right/isometric):\n"
        "  svg_path_visible — SVG path string for visible edges\n"
        "  svg_path_hidden  — SVG path string for hidden edges (dashed)\n"
        "  bbox_2d          — [xmin, ymin, xmax, ymax] in drawing space\n"
        "  n_visible_edges  — count of visible edge segments\n"
        "  n_hidden_edges   — count of hidden edge segments\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "size": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Box [width, height, depth] in mm. Default [100, 80, 60].",
            },
            "origin": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Box origin [x, y, z] in mm. Default [0, 0, 0].",
            },
            "views": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Which views to return: any subset of "
                    "['front', 'top', 'right', 'isometric']. "
                    "Default: all four."
                ),
            },
        },
        "required": [],
    },
)


@register(_brep_to_2d_hlr_spec, write=False)
async def run_brep_to_2d_hlr(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    size = a.get("size", [100.0, 80.0, 60.0])
    origin = a.get("origin", [0.0, 0.0, 0.0])
    requested_views = a.get("views", ["front", "top", "right", "isometric"])

    _valid_views = {"front", "top", "right", "isometric"}
    for v in requested_views:
        if v not in _valid_views:
            return err_payload(
                f"Unknown view '{v}'. Valid: {sorted(_valid_views)}", "BAD_ARGS"
            )

    try:
        size_tup = tuple(float(x) for x in size)
        origin_tup = tuple(float(x) for x in origin)
        if len(size_tup) != 3:
            return err_payload("size must have 3 elements [w, h, d]", "BAD_ARGS")
        body = make_box(size=size_tup, origin=origin_tup)
    except Exception as exc:
        return err_payload(f"failed to create box body: {exc}", "BAD_ARGS")

    try:
        all_views = make_standard_views(body)
    except Exception as exc:
        return err_payload(f"HLR projection error: {exc}", "EVAL_ERROR")

    result: dict = {}
    for view_name in requested_views:
        if view_name not in all_views:
            result[view_name] = {"ok": False, "reason": "view not available"}
            continue
        hlr = all_views[view_name]
        result[view_name] = {
            "svg_path_visible": hlr.svg_path_visible,
            "svg_path_hidden": hlr.svg_path_hidden,
            "bbox": list(hlr.bbox),
            "n_visible_edges": len(hlr.visible_edges),
            "n_hidden_edges": len(hlr.hidden_edges),
        }

    return ok_payload({
        "views": result,
        "size": list(size_tup),
        "origin": list(origin_tup),
        "views_generated": list(requested_views),
    })


__all__ = ["run_brep_to_2d_hlr"]
