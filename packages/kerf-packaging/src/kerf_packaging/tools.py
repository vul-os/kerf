"""
kerf_packaging LLM tools — dieline generation, DXF export, fold preview.

Registered via plugin.py at startup.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_packaging._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# packaging_dieline_generate
# ---------------------------------------------------------------------------

packaging_dieline_generate_spec = ToolSpec(
    name="packaging_dieline_generate",
    description=(
        "Generate a parametric ECMA dieline for a folding carton or corrugated box. "
        "Supports ECMA C-02 RSC (regular slotted container), "
        "ECMA A-10 tray (one-piece folder), and ECMA B-03 counter display. "
        "Returns the flat dieline dimensions, panel list, line count, and "
        "a summary suitable for DXF export."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "style": {
                "type": "string",
                "enum": ["C02", "A10", "B03"],
                "description": (
                    "ECMA style: "
                    "C02 = Regular Slotted Container (RSC), "
                    "A10 = one-piece tray, "
                    "B03 = counter display box with tuck front."
                ),
            },
            "length": {
                "type": "number",
                "description": "Internal box length (mm).",
            },
            "width": {
                "type": "number",
                "description": "Internal box width (mm).",
            },
            "depth": {
                "type": "number",
                "description": "Internal box depth / height (mm).",
            },
            "board_t": {
                "type": "number",
                "description": "Board caliper / thickness (mm). Default 0.4 mm.",
            },
            "material": {
                "type": "string",
                "enum": ["sbs", "crb", "flute_b", "flute_c", "flute_bc", "flute_e", "kraft"],
                "description": "Board material. Default 'sbs' (solid bleached sulphate).",
            },
        },
        "required": ["style", "length", "width", "depth"],
    },
)


async def run_packaging_dieline_generate(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_packaging.ecma_generators import ecma_c02_rsc, ecma_a10_tray, ecma_b03_display
        from kerf_packaging.dieline import Material

        style   = str(args["style"]).upper()
        length  = float(args["length"])
        width   = float(args["width"])
        depth   = float(args["depth"])
        board_t = float(args.get("board_t", 0.4))
        mat_str = str(args.get("material", "sbs")).lower()

        try:
            material = Material(mat_str)
        except ValueError:
            material = Material.UNKNOWN

        if style == "C02":
            d = ecma_c02_rsc(length, width, depth, board_t=board_t, material=material)
        elif style == "A10":
            d = ecma_a10_tray(length, width, depth, board_t=board_t, material=material)
        elif style == "B03":
            d = ecma_b03_display(length, width, depth, board_t=board_t, material=material)
        else:
            return err_payload(f"Unknown ECMA style '{style}'", "BAD_ARGS")

        cut_count  = len(d.cut_lines())
        fold_count = len(d.fold_lines())

        payload = {
            "name": d.name,
            "blank_width_mm":  round(d.width,  3),
            "blank_height_mm": round(d.height, 3),
            "panel_count": len(d.panels),
            "panels": [p.name for p in d.panels],
            "cut_line_count":  cut_count,
            "fold_line_count": fold_count,
            "total_line_count": len(d.lines),
            "material": d.material.value,
            "metadata": d.metadata,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "DIELINE_ERROR")


# ---------------------------------------------------------------------------
# packaging_dieline_to_dxf
# ---------------------------------------------------------------------------

packaging_dieline_to_dxf_spec = ToolSpec(
    name="packaging_dieline_to_dxf",
    description=(
        "Generate a parametric ECMA dieline and export it to DXF. "
        "Cut lines on layer 'cut' (red), fold lines on layer 'fold' (cyan), "
        "score lines on 'score' (yellow). Returns DXF text string."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "style": {
                "type": "string",
                "enum": ["C02", "A10", "B03"],
                "description": "ECMA style: C02, A10, or B03.",
            },
            "length": {"type": "number", "description": "Internal box length (mm)."},
            "width":  {"type": "number", "description": "Internal box width (mm)."},
            "depth":  {"type": "number", "description": "Internal box depth (mm)."},
            "board_t": {"type": "number", "description": "Board caliper (mm). Default 0.4."},
            "dxf_version": {
                "type": "string",
                "enum": ["R12", "R2004"],
                "description": "DXF version. Default R2004.",
            },
        },
        "required": ["style", "length", "width", "depth"],
    },
)


async def run_packaging_dieline_to_dxf(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_packaging.ecma_generators import ecma_c02_rsc, ecma_a10_tray, ecma_b03_display
        from kerf_packaging.dieline import Material
        from kerf_imports.dxf_writer import dxf_export_result

        style   = str(args["style"]).upper()
        length  = float(args["length"])
        width   = float(args["width"])
        depth   = float(args["depth"])
        board_t = float(args.get("board_t", 0.4))
        version = str(args.get("dxf_version", "R2004"))

        if style == "C02":
            d = ecma_c02_rsc(length, width, depth, board_t=board_t)
        elif style == "A10":
            d = ecma_a10_tray(length, width, depth, board_t=board_t)
        elif style == "B03":
            d = ecma_b03_display(length, width, depth, board_t=board_t)
        else:
            return err_payload(f"Unknown ECMA style '{style}'", "BAD_ARGS")

        drawing = d.to_drawing_dict()
        result  = dxf_export_result(drawing, version=version)

        if result["ok"]:
            return ok_payload({
                "dxf": result["dxf"],
                "version": version,
                "blank_width_mm":  round(d.width,  3),
                "blank_height_mm": round(d.height, 3),
            })
        return err_payload(result.get("reason") or "DXF export failed", "DXF_ERROR")
    except Exception as exc:
        return err_payload(str(exc), "DXF_ERROR")


# ---------------------------------------------------------------------------
# packaging_fold_preview
# ---------------------------------------------------------------------------

packaging_fold_preview_spec = ToolSpec(
    name="packaging_fold_preview",
    description=(
        "Fold a parametric ECMA dieline into a 3-D carton shape. "
        "Returns the 3-D vertex positions of each panel, the bounding box "
        "of the folded shape, and whether the shape appears closed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "style":  {"type": "string", "enum": ["C02", "A10", "B03"]},
            "length": {"type": "number"},
            "width":  {"type": "number"},
            "depth":  {"type": "number"},
            "fold_angle": {
                "type": "number",
                "description": "Override fold angle in degrees (default 90). 0 = flat.",
            },
        },
        "required": ["style", "length", "width", "depth"],
    },
)


async def run_packaging_fold_preview(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_packaging.ecma_generators import ecma_c02_rsc, ecma_a10_tray, ecma_b03_display
        from kerf_packaging.fold import fold_dieline

        style  = str(args["style"]).upper()
        length = float(args["length"])
        width  = float(args["width"])
        depth  = float(args["depth"])
        angle  = float(args["fold_angle"]) if "fold_angle" in args else None

        if style == "C02":
            d = ecma_c02_rsc(length, width, depth)
        elif style == "A10":
            d = ecma_a10_tray(length, width, depth)
        elif style == "B03":
            d = ecma_b03_display(length, width, depth)
        else:
            return err_payload(f"Unknown ECMA style '{style}'", "BAD_ARGS")

        result = fold_dieline(d, fold_angle_override=angle)

        # Serialize panel corners (round to 3 dp)
        panels_out = {}
        for name, verts in result.panels.items():
            panels_out[name] = [
                [round(v[0], 3), round(v[1], 3), round(v[2], 3)]
                for v in verts
            ]

        bb_min, bb_max = result.bounding_box
        payload = {
            "is_closed": result.is_closed,
            "bounding_box": {
                "min": [round(bb_min[0], 3), round(bb_min[1], 3), round(bb_min[2], 3)],
                "max": [round(bb_max[0], 3), round(bb_max[1], 3), round(bb_max[2], 3)],
            },
            "panel_count": len(panels_out),
            "panels": panels_out,
            "warnings": result.warnings,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "FOLD_ERROR")


# ---------------------------------------------------------------------------
# packaging_bct_estimate
# ---------------------------------------------------------------------------

packaging_bct_estimate_spec = ToolSpec(
    name="packaging_bct_estimate",
    description=(
        "Estimate Box Compression Test (BCT) strength for a Regular Slotted "
        "Container (RSC) using the McKee formula (1963). "
        "Returns BCT in Newtons and kgf, humidity-corrected, plus stacking "
        "analysis if product weight is supplied. "
        "McKee simplified: BCT = k · ECT · √(perimeter × height). "
        "McKee full: BCT = k · ECT · (perimeter/4)^0.492 · height^0.508."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ect_N_per_m": {
                "type": "number",
                "description": (
                    "Edge Crush Test value of the board (N/m). "
                    "Typical: B-flute≈2800, C-flute≈3200, BC-flute≈4500 N/m."
                ),
            },
            "length": {"type": "number", "description": "Internal box length (mm)."},
            "width":  {"type": "number", "description": "Internal box width (mm)."},
            "depth":  {"type": "number", "description": "Box height under compression (mm)."},
            "board_t": {
                "type": "number",
                "description": "Board caliper / thickness (mm). Default 4.5 mm (C-flute).",
            },
            "full_formula": {
                "type": "boolean",
                "description": "Use full McKee formula (α=0.492, β=0.508). Default false.",
            },
            "humidity": {
                "type": "string",
                "enum": ["dry", "normal", "humid", "wet"],
                "description": (
                    "Storage humidity: dry (<50% RH, ×1.00), normal (50–65%, ×0.90), "
                    "humid (65–80%, ×0.75), wet (>80%, ×0.55). Default 'normal'."
                ),
            },
            "load_kg": {
                "type": "number",
                "description": "Product weight per box (kg) for stacking analysis. Optional.",
            },
            "safety_factor": {
                "type": "number",
                "description": "Stacking safety factor (default 3.0). Typical: 2.0–4.0.",
            },
        },
        "required": ["ect_N_per_m", "length", "width", "depth"],
    },
)


async def run_packaging_bct_estimate(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_packaging.bct import bct_mckee, bct_to_dict

        result = bct_mckee(
            ect_N_per_m   = float(args["ect_N_per_m"]),
            length_mm     = float(args["length"]),
            width_mm      = float(args["width"]),
            depth_mm      = float(args["depth"]),
            board_t_mm    = float(args.get("board_t", 4.5)),
            full_formula  = bool(args.get("full_formula", False)),
            humidity      = str(args.get("humidity", "normal")),
            load_kg       = float(args["load_kg"]) if "load_kg" in args else None,
            safety_factor = float(args.get("safety_factor", 3.0)),
        )
        return ok_payload(bct_to_dict(result))
    except Exception as exc:
        return err_payload(str(exc), "BCT_ERROR")
