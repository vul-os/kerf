"""
markup.py — LLM tools for Kerf markup/redline workflow.

Tools
-----
  bim_add_markup          — add an annotation to a markup session
  bim_export_markup_pdf   — export markup session as PDF overlay
  bim_export_markup_svg   — export markup session as SVG overlay
  bim_import_markup_pdf   — import annotations from an existing PDF
  bim_merge_markups       — merge two or more markup sessions
"""
from __future__ import annotations

import json
import uuid as _uuid

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


# ---------------------------------------------------------------------------
# bim_add_markup
# ---------------------------------------------------------------------------

_add_markup_spec = ToolSpec(
    name="bim_add_markup",
    description=(
        "Add an annotation to a markup review session on a drawing, PDF, or "
        "3D view.  Supported shapes: circle, rectangle, arrow, freehand, "
        "text, highlight, stamp.\n"
        "\n"
        "The session is identified by target_id + target_type.  A layer_name "
        "is required; the layer is created automatically if absent.\n"
        "\n"
        "Returns:\n"
        "  ok            : bool\n"
        "  guid          : str  — UUID4 of the new annotation\n"
        "  layer         : str  — resolved layer name\n"
        "\n"
        "Errors: {ok:false, reason, code}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "description": "ID of the target document or view.",
            },
            "target_type": {
                "type": "string",
                "enum": ["drawing", "pdf", "3d_view"],
                "description": "Type of the annotated target.",
                "default": "drawing",
            },
            "layer_name": {
                "type": "string",
                "description": "Markup layer name (created if absent).",
            },
            "shape": {
                "type": "string",
                "enum": ["circle", "rectangle", "arrow", "freehand", "text", "highlight", "stamp"],
                "description": "Annotation shape type.",
            },
            "xy_mm": {
                "type": "array",
                "description": "Anchor/control points as [[x, y], ...] in mm.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "color_rgb": {
                "type": "array",
                "description": "[R, G, B] stroke colour 0-255.",
                "items": {"type": "integer"},
                "minItems": 3,
                "maxItems": 3,
                "default": [255, 0, 0],
            },
            "thickness_mm": {
                "type": "number",
                "description": "Stroke thickness in mm.",
                "default": 0.5,
            },
            "fill_rgba": {
                "type": ["array", "null"],
                "description": "[R, G, B, A] fill colour (null = transparent).",
                "items": {"type": "integer"},
                "default": None,
            },
            "text_content": {
                "type": "string",
                "description": "Text label for text/stamp shapes.",
                "default": "",
            },
            "author": {
                "type": "string",
                "description": "Reviewer name or ID.",
                "default": "",
            },
            "page_or_view_id": {
                "type": "string",
                "description": "Page number or view ID where the annotation lives.",
                "default": "0",
            },
        },
        "required": ["target_id", "layer_name", "shape", "xy_mm"],
    },
)


async def run_bim_add_markup(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.markup import (
            MarkupAnnotation, MarkupSession, MarkupShape, add_annotation,
        )
        import datetime

        shape_str = params.get("shape", "circle")
        try:
            shape = MarkupShape(shape_str)
        except ValueError:
            return err_payload(f"unknown shape '{shape_str}'", "BAD_ARGS")

        xy_raw = params.get("xy_mm", [])
        xy_mm = [(float(p[0]), float(p[1])) for p in xy_raw]

        color_raw = params.get("color_rgb", [255, 0, 0])
        color_rgb = (int(color_raw[0]), int(color_raw[1]), int(color_raw[2]))

        fill_rgba = None
        fill_raw = params.get("fill_rgba")
        if fill_raw:
            fill_rgba = (int(fill_raw[0]), int(fill_raw[1]),
                         int(fill_raw[2]), int(fill_raw[3]))

        ann = MarkupAnnotation(
            guid=str(_uuid.uuid4()),
            shape=shape,
            xy_mm=xy_mm,
            color_rgb=color_rgb,
            thickness_mm=float(params.get("thickness_mm", 0.5)),
            fill_rgba=fill_rgba,
            text_content=str(params.get("text_content", "")),
            author=str(params.get("author", "")),
            created_at_iso=datetime.datetime.utcnow().isoformat() + "Z",
            page_or_view_id=str(params.get("page_or_view_id", "0")),
        )

        session = MarkupSession(
            target_type=str(params.get("target_type", "drawing")),
            target_id=str(params.get("target_id", "")),
        )
        layer_name = str(params.get("layer_name", "default"))
        add_annotation(session, layer_name, ann)

        return ok_payload({
            "ok": True,
            "guid": ann.guid,
            "layer": layer_name,
        })
    except Exception as exc:
        return err_payload(str(exc), "MARKUP_ADD_ERROR")


# ---------------------------------------------------------------------------
# bim_export_markup_pdf
# ---------------------------------------------------------------------------

_export_pdf_spec = ToolSpec(
    name="bim_export_markup_pdf",
    description=(
        "Export a markup session as a PDF overlay on top of a base PDF "
        "drawing.  The base PDF is unchanged; a new blended PDF is written "
        "to output_path.\n"
        "\n"
        "Returns:\n"
        "  ok          : bool\n"
        "  output_path : str\n"
        "\n"
        "Errors: {ok:false, reason, code}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "session": {
                "type": "object",
                "description": "Serialised MarkupSession dict (from a previous bim_add_markup call).",
            },
            "base_pdf_path": {
                "type": "string",
                "description": "Absolute path to the base PDF.",
            },
            "output_path": {
                "type": "string",
                "description": "Absolute path for the output PDF overlay.",
            },
        },
        "required": ["session", "base_pdf_path", "output_path"],
    },
)


async def run_bim_export_markup_pdf(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.markup import (
            MarkupSession, MarkupLayer, MarkupAnnotation, MarkupShape,
            export_to_pdf_overlay,
        )

        session = _deserialise_session(params["session"])
        result = export_to_pdf_overlay(
            session,
            str(params["base_pdf_path"]),
            str(params["output_path"]),
        )
        return ok_payload({"ok": True, "output_path": result})
    except Exception as exc:
        return err_payload(str(exc), "MARKUP_EXPORT_PDF_ERROR")


# ---------------------------------------------------------------------------
# bim_export_markup_svg
# ---------------------------------------------------------------------------

_export_svg_spec = ToolSpec(
    name="bim_export_markup_svg",
    description=(
        "Export a markup session as a standalone SVG overlay suitable for "
        "embedding in a drawing viewer or printing.\n"
        "\n"
        "Returns:\n"
        "  ok          : bool\n"
        "  output_path : str\n"
        "\n"
        "Errors: {ok:false, reason, code}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "session": {
                "type": "object",
                "description": "Serialised MarkupSession dict.",
            },
            "output_path": {
                "type": "string",
                "description": "Absolute path for the output SVG.",
            },
        },
        "required": ["session", "output_path"],
    },
)


async def run_bim_export_markup_svg(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.markup import export_to_svg_overlay
        session = _deserialise_session(params["session"])
        result = export_to_svg_overlay(session, str(params["output_path"]))
        return ok_payload({"ok": True, "output_path": result})
    except Exception as exc:
        return err_payload(str(exc), "MARKUP_EXPORT_SVG_ERROR")


# ---------------------------------------------------------------------------
# bim_import_markup_pdf
# ---------------------------------------------------------------------------

_import_pdf_spec = ToolSpec(
    name="bim_import_markup_pdf",
    description=(
        "Extract existing annotations embedded in a PDF file and return them "
        "as a MarkupSession.\n"
        "\n"
        "Returns:\n"
        "  ok              : bool\n"
        "  annotation_count: int\n"
        "  session         : object  — serialised MarkupSession\n"
        "\n"
        "Errors: {ok:false, reason, code}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pdf_path": {
                "type": "string",
                "description": "Absolute path to the PDF to read annotations from.",
            },
        },
        "required": ["pdf_path"],
    },
)


async def run_bim_import_markup_pdf(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.markup import import_pdf_annotations
        session = import_pdf_annotations(str(params["pdf_path"]))
        count = sum(len(lyr.annotations) for lyr in session.layers)
        return ok_payload({
            "ok": True,
            "annotation_count": count,
            "session": _serialise_session(session),
        })
    except Exception as exc:
        return err_payload(str(exc), "MARKUP_IMPORT_PDF_ERROR")


# ---------------------------------------------------------------------------
# bim_merge_markups
# ---------------------------------------------------------------------------

_merge_spec = ToolSpec(
    name="bim_merge_markups",
    description=(
        "Merge two or more MarkupSession dicts into a single combined session. "
        "Layers with the same name are concatenated.  Used to combine markups "
        "from multiple reviewers before issuing a combined review PDF.\n"
        "\n"
        "Returns:\n"
        "  ok              : bool\n"
        "  layer_count     : int\n"
        "  annotation_count: int\n"
        "  session         : object  — serialised merged MarkupSession\n"
        "\n"
        "Errors: {ok:false, reason, code}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sessions": {
                "type": "array",
                "description": "List of serialised MarkupSession dicts to merge.",
                "items": {"type": "object"},
                "minItems": 2,
            },
        },
        "required": ["sessions"],
    },
)


async def run_bim_merge_markups(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_bim.markup import merge_sessions
        sessions = [_deserialise_session(s) for s in params["sessions"]]
        merged = merge_sessions(sessions)
        count = sum(len(lyr.annotations) for lyr in merged.layers)
        return ok_payload({
            "ok": True,
            "layer_count": len(merged.layers),
            "annotation_count": count,
            "session": _serialise_session(merged),
        })
    except Exception as exc:
        return err_payload(str(exc), "MARKUP_MERGE_ERROR")


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _serialise_session(session) -> dict:
    from kerf_bim.markup import MarkupSession, MarkupLayer, MarkupAnnotation
    return {
        "target_type": session.target_type,
        "target_id": session.target_id,
        "status": session.status,
        "layers": [
            {
                "name": lyr.name,
                "color_rgb": list(lyr.color_rgb),
                "visible": lyr.visible,
                "annotations": [
                    {
                        "guid": ann.guid,
                        "shape": ann.shape.value if hasattr(ann.shape, "value") else ann.shape,
                        "xy_mm": [list(p) for p in ann.xy_mm],
                        "color_rgb": list(ann.color_rgb),
                        "thickness_mm": ann.thickness_mm,
                        "fill_rgba": list(ann.fill_rgba) if ann.fill_rgba else None,
                        "text_content": ann.text_content,
                        "author": ann.author,
                        "created_at_iso": ann.created_at_iso,
                        "page_or_view_id": ann.page_or_view_id,
                    }
                    for ann in lyr.annotations
                ],
            }
            for lyr in session.layers
        ],
    }


def _deserialise_session(d: dict):
    from kerf_bim.markup import (
        MarkupSession, MarkupLayer, MarkupAnnotation, MarkupShape,
    )
    session = MarkupSession(
        target_type=d.get("target_type", "drawing"),
        target_id=d.get("target_id", ""),
        status=d.get("status", "draft"),
    )
    for lyr_d in d.get("layers", []):
        lyr = MarkupLayer(
            name=lyr_d["name"],
            color_rgb=tuple(lyr_d.get("color_rgb", [255, 0, 0])),
            visible=lyr_d.get("visible", True),
        )
        for ann_d in lyr_d.get("annotations", []):
            fill = ann_d.get("fill_rgba")
            lyr.annotations.append(MarkupAnnotation(
                guid=ann_d.get("guid", str(_uuid.uuid4())),
                shape=MarkupShape(ann_d["shape"]),
                xy_mm=[(p[0], p[1]) for p in ann_d.get("xy_mm", [])],
                color_rgb=tuple(ann_d.get("color_rgb", [255, 0, 0])),
                thickness_mm=float(ann_d.get("thickness_mm", 0.5)),
                fill_rgba=tuple(fill) if fill else None,
                text_content=ann_d.get("text_content", ""),
                author=ann_d.get("author", ""),
                created_at_iso=ann_d.get("created_at_iso", ""),
                page_or_view_id=ann_d.get("page_or_view_id", "0"),
            ))
        session.layers.append(lyr)
    return session


# ---------------------------------------------------------------------------
# TOOLS registry list
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_add_markup",         _add_markup_spec,    run_bim_add_markup),
    ("bim_export_markup_pdf",  _export_pdf_spec,    run_bim_export_markup_pdf),
    ("bim_export_markup_svg",  _export_svg_spec,    run_bim_export_markup_svg),
    ("bim_import_markup_pdf",  _import_pdf_spec,    run_bim_import_markup_pdf),
    ("bim_merge_markups",      _merge_spec,         run_bim_merge_markups),
]
