"""
kerf_cad_core.simple_parametric.tools — LLM tool wrappers for the
education / maker on-ramp: simple-parametric + cut-list / flat-pack path.

Registers four tools:

  list_maker_templates
      List all built-in parametric starter templates and their parameters.
      No inputs required.

  build_maker_part
      Instantiate a parametric template with user parameters.
      Returns panel list + JSCAD preview code + description.

  compute_maker_cut_list
      Convert a part definition (or raw panel list) into a printable
      cut list + flat-pack sheet layout. Outputs CSV-ready rows.

  export_cut_list_csv
      Format a cut list result as a CSV string for download / printing.

All tools are pure-Python and never raise; errors returned as
{ok: false, errors: [...]}.

Author: imranparuk
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.simple_parametric.templates import build_part, list_templates, PanelDef
from kerf_cad_core.simple_parametric.cut_list import compute_cut_list, cut_list_to_csv


# ---------------------------------------------------------------------------
# T-1: list_maker_templates
# ---------------------------------------------------------------------------

_list_templates_spec = ToolSpec(
    name="list_maker_templates",
    description=(
        "List all built-in parametric starter templates for the education / maker on-ramp. "
        "\n"
        "Returns a list of template descriptors, each with a key, description, and "
        "named numeric parameters (with defaults, min, max, and documentation). "
        "\n"
        "Use this tool first to discover what templates are available, then call "
        "build_maker_part with the chosen template key and your desired parameters."
    ),
    input_schema={"type": "object", "properties": {}, "required": []},
)


@register(_list_templates_spec, write=False)
async def run_list_maker_templates(ctx: ProjectCtx, args: bytes) -> str:
    templates = list_templates()
    return ok_payload({
        "ok": True,
        "templates": templates,
        "count": len(templates),
    })


# ---------------------------------------------------------------------------
# T-2: build_maker_part
# ---------------------------------------------------------------------------

_build_part_spec = ToolSpec(
    name="build_maker_part",
    description=(
        "Build a parametric maker/education starter part from a template. "
        "\n"
        "Inputs: template key (from list_maker_templates) and optional parameter overrides. "
        "Unknown parameter names are silently ignored; values are clamped to min/max. "
        "\n"
        "Returns: resolved parameters, a list of flat panels (name, w, h, thickness, qty), "
        "a self-contained JSCAD preview code string, and a human-readable description. "
        "\n"
        "Supported templates: box, lid_box, enclosure, shelf_bracket, t_slot_frame. "
        "\n"
        "After calling this tool, use compute_maker_cut_list to get a printable cut list "
        "and sheet layout. "
        "\n"
        "Example: template='box', params={'width':300, 'depth':200, 'height':150, 'thickness':9}"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "template": {
                "type": "string",
                "description": (
                    "Template key. One of: box, lid_box, enclosure, shelf_bracket, t_slot_frame. "
                    "Use list_maker_templates to see the full list."
                ),
            },
            "params": {
                "type": "object",
                "description": (
                    "Parameter overrides as a flat object of {param_name: numeric_value}. "
                    "All values in mm (or count for qty parameters). "
                    "Unknown keys are ignored. Missing keys use template defaults."
                ),
                "additionalProperties": {"type": "number"},
            },
        },
        "required": ["template"],
    },
)


@register(_build_part_spec, write=False)
async def run_build_maker_part(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    template = a.get("template")
    if not template or not isinstance(template, str):
        return err_payload("template (string) is required", "BAD_ARGS")

    params = a.get("params") or {}
    if not isinstance(params, dict):
        return err_payload("params must be an object", "BAD_ARGS")

    try:
        part = build_part(template, params)
    except ValueError as exc:
        return err_payload(str(exc), "UNKNOWN_TEMPLATE")
    except Exception as exc:
        return err_payload(f"build_part failed: {exc}", "BUILD_ERROR")

    return ok_payload({
        "ok": True,
        **part.to_dict(),
    })


# ---------------------------------------------------------------------------
# T-3: compute_maker_cut_list
# ---------------------------------------------------------------------------

_cut_list_spec = ToolSpec(
    name="compute_maker_cut_list",
    description=(
        "Convert a simple-parametric part definition (or a raw panel list) into a "
        "cut list and flat-pack sheet layout. "
        "\n"
        "Inputs: panels array (from build_maker_part output), plus optional sheet "
        "dimensions, material name, kerf, and margin. "
        "\n"
        "Algorithm: greedy shelf packing (deterministic, easy to follow). "
        "Panels are sorted tallest-first and placed left-to-right on shelves. "
        "A new shelf is opened when the current shelf is full; a new sheet is "
        "opened when no shelf fits on the current sheet. "
        "\n"
        "Returns: "
        "  pieces[] — rolled-up cut list (unique sizes with quantities and areas). "
        "  sheets_used — number of stock sheets required. "
        "  utilization — fraction of sheet area used (0–1). "
        "  placements[] — per-panel x/y position on each sheet. "
        "  total_area_mm2 — total material area required. "
        "\n"
        "Units: mm throughout. "
        "Call export_cut_list_csv to get a printable CSV string."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "panels": {
                "type": "array",
                "description": (
                    "List of panel objects. Each: "
                    "{name (str), w (mm), h (mm), thickness (mm), qty (int, default 1)}. "
                    "Pass the panels[] array directly from build_maker_part output."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name":      {"type": "string"},
                        "w":         {"type": "number"},
                        "h":         {"type": "number"},
                        "thickness": {"type": "number"},
                        "qty":       {"type": "integer"},
                        "grain_dir": {"type": "string"},
                    },
                    "required": ["name", "w", "h", "thickness"],
                },
            },
            "sheet_w": {
                "type": "number",
                "description": "Stock sheet width (mm). Default 1220 mm (half-sheet).",
            },
            "sheet_h": {
                "type": "number",
                "description": "Stock sheet height (mm). Default 2440 mm (full-sheet 4×8 ft).",
            },
            "material": {
                "type": "string",
                "description": "Material label for the cut list header (e.g. '9mm plywood').",
            },
            "kerf": {
                "type": "number",
                "description": "Saw/laser kerf gap between panels (mm). Default 3 mm.",
            },
            "margin": {
                "type": "number",
                "description": "Border margin inset on each sheet edge (mm). Default 10 mm.",
            },
            "allow_rotate": {
                "type": "boolean",
                "description": "Try rotating panels 90° for better fit. Default true.",
            },
        },
        "required": ["panels"],
    },
)


@register(_cut_list_spec, write=False)
async def run_compute_maker_cut_list(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_panels = a.get("panels")
    if not isinstance(raw_panels, list):
        return err_payload("panels must be an array", "BAD_ARGS")

    try:
        panels: list[PanelDef] = []
        for i, rp in enumerate(raw_panels):
            if not isinstance(rp, dict):
                return err_payload(f"panels[{i}] must be an object", "BAD_ARGS")
            name = str(rp.get("name", f"panel_{i}"))
            try:
                w   = float(rp["w"])
                h   = float(rp["h"])
                t   = float(rp["thickness"])
            except (KeyError, TypeError, ValueError) as exc:
                return err_payload(f"panels[{i}]: {exc}", "BAD_ARGS")
            qty      = int(rp.get("qty", 1))
            grain    = str(rp.get("grain_dir", "any"))
            panels.append(PanelDef(name=name, w=w, h=h, thickness=t, qty=qty, grain_dir=grain))
    except Exception as exc:
        return err_payload(f"panel parse error: {exc}", "BAD_ARGS")

    sheet_w      = float(a.get("sheet_w",   1220.0))
    sheet_h      = float(a.get("sheet_h",   2440.0))
    material     = str(a.get("material",    "plywood"))
    kerf         = float(a.get("kerf",       3.0))
    margin       = float(a.get("margin",    10.0))
    allow_rotate = bool(a.get("allow_rotate", True))

    try:
        result = compute_cut_list(
            panels,
            material=material,
            sheet_w=sheet_w,
            sheet_h=sheet_h,
            kerf=kerf,
            margin=margin,
            allow_rotate=allow_rotate,
        )
    except Exception as exc:
        return err_payload(f"cut list computation failed: {exc}", "COMPUTE_ERROR")

    return ok_payload({
        "ok": True,
        **result.to_dict(),
    })


# ---------------------------------------------------------------------------
# T-4: export_cut_list_csv
# ---------------------------------------------------------------------------

_export_csv_spec = ToolSpec(
    name="export_cut_list_csv",
    description=(
        "Format a cut-list result (from compute_maker_cut_list) as a CSV string "
        "suitable for printing or saving to file. "
        "\n"
        "Columns: Part name, Width (mm), Height (mm), Thickness (mm), Qty, "
        "Area each (mm²), Area total (mm²). "
        "A summary footer shows total qty, total area, sheets required, and utilisation. "
        "\n"
        "Inputs: the full output dict from compute_maker_cut_list."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "cut_list": {
                "type": "object",
                "description": "Full output dict from compute_maker_cut_list.",
            },
        },
        "required": ["cut_list"],
    },
)


@register(_export_csv_spec, write=False)
async def run_export_cut_list_csv(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    cl = a.get("cut_list")
    if not isinstance(cl, dict):
        return err_payload("cut_list must be the output dict from compute_maker_cut_list", "BAD_ARGS")

    # Reconstruct a minimal CutListResult from the dict
    from kerf_cad_core.simple_parametric.cut_list import CutListResult, CutPiece, SheetPlacement

    try:
        pieces = []
        for p in cl.get("pieces", []):
            cp = CutPiece(
                name=str(p.get("name", "")),
                w=float(p.get("w", 0)),
                h=float(p.get("h", 0)),
                thickness=float(p.get("thickness", 0)),
                qty=int(p.get("qty", 1)),
            )
            pieces.append(cp)

        result = CutListResult(
            pieces=pieces,
            sheets_used=int(cl.get("sheets_used", 0)),
            sheet_w=float(cl.get("sheet_w", 1220)),
            sheet_h=float(cl.get("sheet_h", 2440)),
            material=str(cl.get("material", "")),
            kerf_mm=float(cl.get("kerf_mm", 3)),
            margin_mm=float(cl.get("margin_mm", 10)),
            total_area_mm2=float(cl.get("total_area_mm2", 0)),
            total_sheet_area_mm2=float(cl.get("total_sheet_area_mm2", 0)),
            utilization=float(cl.get("utilization", 0)),
            placements=[],  # not needed for CSV
            errors=cl.get("errors", []),
        )
    except Exception as exc:
        return err_payload(f"cut_list parse error: {exc}", "BAD_ARGS")

    try:
        csv_text = cut_list_to_csv(result)
    except Exception as exc:
        return err_payload(f"CSV export failed: {exc}", "EXPORT_ERROR")

    return ok_payload({
        "ok": True,
        "csv": csv_text,
        "line_count": csv_text.count("\n"),
    })
