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


# ---------------------------------------------------------------------------
# packaging_prepress_check — ISO 15930-1 / ISO 12647-2 pre-press validation
# ---------------------------------------------------------------------------

packaging_prepress_check_spec = ToolSpec(
    name="packaging_prepress_check",
    description=(
        "Validate a packaging pre-press job against ISO 12647-2 / ISO 15930-1 "
        "structural rules: bleed ≥ 3 mm, safety zone clear, registration marks, "
        "PDF/X-1a structural compliance check, and plate count estimate.\n\n"
        "References: ISO 15930-1:2001 (PDF/X-1a), ISO 12647-2:2013, GRACoL 2013. "
        "Honest: PDF/X-1a check is structural only — commercial preflight "
        "(Enfocus Pitstop, Apago PDF Appraiser) is required before submitting to press."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "trim_box": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x_min, y_min, x_max, y_max] in mm — the intended cut line.",
            },
            "bleed_mm": {
                "type": "number",
                "description": "Bleed extension beyond trim in mm (ISO 12647-2 minimum 3 mm). Default 3.0.",
            },
            "safety_zone_mm": {
                "type": "number",
                "description": "Safety zone inside trim in mm (default 4.0 mm).",
            },
            "registration_marks": {
                "type": "array",
                "description": (
                    "List of registration mark dicts: "
                    "{position: [x, y], kind: 'cross'|'circle'|'corner_bracket', color_layers: [...]}"
                ),
            },
            "spot_colors": {
                "type": "array",
                "description": (
                    "List of spot-colour dicts: "
                    "{layer_id: str, color_name: str, coverage_pct: 0–100, overprint: bool}"
                ),
            },
            "finishing": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Finishing processes: 'varnish_gloss', 'varnish_matte', 'foil_stamp', 'emboss', 'deboss', 'die_cut'.",
            },
            "artwork_bbox": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x_min, y_min, x_max, y_max] of critical artwork in mm.",
            },
        },
        "required": ["trim_box"],
    },
)


async def run_packaging_prepress_check(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_cad_core.packaging.pre_press_tools import _tool_prepress_check
        result = _tool_prepress_check(
            trim_box=args["trim_box"],
            bleed_mm=float(args.get("bleed_mm", 3.0)),
            safety_zone_mm=float(args.get("safety_zone_mm", 4.0)),
            registration_marks=args.get("registration_marks"),
            spot_colors=args.get("spot_colors"),
            finishing=args.get("finishing"),
            artwork_bbox=args.get("artwork_bbox"),
        )
        return ok_payload(result)
    except ImportError:
        return err_payload(
            "kerf_cad_core.packaging.pre_press_tools not available. "
            "Install kerf-cad-core to use pre-press tools.",
            "UNAVAILABLE",
        )
    except Exception as exc:
        return err_payload(str(exc), "PREPRESS_ERROR")


# ---------------------------------------------------------------------------
# packaging_prepress_gen_marks — auto-place registration marks
# ---------------------------------------------------------------------------

packaging_prepress_gen_marks_spec = ToolSpec(
    name="packaging_prepress_gen_marks",
    description=(
        "Auto-place 4 corner registration marks in the slug area outside the trim box, "
        "ready for CMYK press registration (ArtiosCAD / Esko convention).\n\n"
        "Reference: ISO 12647-2:2013 §7.4 — mark placement in bleed/slug area."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "trim_box": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x_min, y_min, x_max, y_max] in mm.",
            },
            "bleed_mm": {"type": "number", "description": "Bleed extension mm (default 3.0)."},
            "kind": {
                "type": "string",
                "enum": ["cross", "circle", "corner_bracket"],
                "description": "Mark geometry. Default 'corner_bracket'.",
            },
            "color_layers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ink separations for marks. Default ['cyan','magenta','yellow','black'].",
            },
            "offset_mm": {"type": "number", "description": "Additional offset from bleed edge (default 5.0 mm)."},
        },
        "required": ["trim_box"],
    },
)


async def run_packaging_prepress_gen_marks(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_cad_core.packaging.pre_press_tools import _tool_prepress_gen_marks
        result = _tool_prepress_gen_marks(
            trim_box=args["trim_box"],
            bleed_mm=float(args.get("bleed_mm", 3.0)),
            kind=str(args.get("kind", "corner_bracket")),
            color_layers=args.get("color_layers"),
            offset_mm=float(args.get("offset_mm", 5.0)),
        )
        return ok_payload(result)
    except ImportError:
        return err_payload("kerf_cad_core.packaging.pre_press_tools not available.", "UNAVAILABLE")
    except Exception as exc:
        return err_payload(str(exc), "GENMARKS_ERROR")


# ---------------------------------------------------------------------------
# packaging_prepress_export_pdf_x1a — minimal ISO 15930-1 PDF/X-1a skeleton
# ---------------------------------------------------------------------------

packaging_prepress_export_pdf_x1a_spec = ToolSpec(
    name="packaging_prepress_export_pdf_x1a",
    description=(
        "Generate a minimal PDF/X-1a:2001 skeleton (ISO 15930-1 §6) for a packaging job.\n\n"
        "Returns structural metadata and PDF size. "
        "Honest: skeleton only — not press-ready without Enfocus Pitstop post-processing. "
        "Spot-colour names and TrimBox/BleedBox are embedded per ISO 15930-1 §6.3/§6.4."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "trim_box": {
                "type": "array",
                "items": {"type": "number"},
                "description": "[x_min, y_min, x_max, y_max] in mm.",
            },
            "bleed_mm": {"type": "number", "description": "Bleed in mm (default 3.0)."},
            "spot_colors": {
                "type": "array",
                "description": "Spot-colour layers: [{layer_id, color_name, coverage_pct, overprint}].",
            },
            "finishing": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Finishing processes.",
            },
            "artwork_svg": {
                "type": "string",
                "description": "SVG artwork (embedded as metadata comment; not rasterised).",
            },
        },
        "required": ["trim_box"],
    },
)


async def run_packaging_prepress_export_pdf_x1a(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_cad_core.packaging.pre_press_tools import _tool_prepress_export_pdf_x1a
        result = _tool_prepress_export_pdf_x1a(
            trim_box=args["trim_box"],
            bleed_mm=float(args.get("bleed_mm", 3.0)),
            spot_colors=args.get("spot_colors"),
            finishing=args.get("finishing"),
            artwork_svg=str(args.get("artwork_svg", "")),
        )
        return ok_payload(result)
    except ImportError:
        return err_payload("kerf_cad_core.packaging.pre_press_tools not available.", "UNAVAILABLE")
    except Exception as exc:
        return err_payload(str(exc), "EXPORT_ERROR")


# ---------------------------------------------------------------------------
# packaging_material_yield — sheet yield + material cost (PMMI handbook)
# ---------------------------------------------------------------------------

packaging_material_yield_spec = ToolSpec(
    name="packaging_material_yield",
    description=(
        "Compute sheet yield (parts/sheet), waste percentage, and total material cost "
        "for a packaging job.\n\n"
        "Algorithm: parts_per_sheet = floor(sheet_area × nesting_efficiency / bbox_area); "
        "total_cost = sheets_per_job × sheet_weight_kg × cost_per_kg.\n\n"
        "Reference: PMMI / FBA Cost of Converting Handbook (2019) §7 'Yield coefficient'. "
        "Honest: uses bounding-box area × efficiency; true NFP nesting gives higher yield "
        "for non-rectangular outlines. Cost excludes ink, plates, die, and converting "
        "labour (add ~40–80%). See PMMI handbook §5."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "box_outline": {
                "type": "array",
                "description": (
                    "Ordered vertices of the unfolded (flat) box blank in mm: "
                    "[[x1,y1], [x2,y2], ...]"
                ),
                "items": {"type": "array", "items": {"type": "number"}},
            },
            "material_name": {
                "type": "string",
                "description": "Substrate identifier: e.g. 'sbs_320gsm', 'corrugated_B-flute_5mm'.",
            },
            "cost_per_kg": {
                "type": "number",
                "description": "Substrate cost per kg (USD). Typical: SBS ≈ 1.60, corrugated ≈ 1.00.",
            },
            "sheet_width_mm": {
                "type": "number",
                "description": "Press sheet width (mm).",
            },
            "sheet_height_mm": {
                "type": "number",
                "description": "Press sheet height (mm).",
            },
            "sheet_weight_gsm": {
                "type": "number",
                "description": "Substrate grammage (g/m²). SBS 320: 320; B-flute combined: ~750.",
            },
            "job_quantity": {
                "type": "integer",
                "description": "Number of finished boxes to produce.",
            },
            "nesting_efficiency_pct": {
                "type": "number",
                "description": "Nesting efficiency as %. PMMI §7.2 reports 70–80% for rectangular blanks. Default 75%.",
            },
            "job_id": {
                "type": "string",
                "description": "Optional job identifier.",
            },
        },
        "required": ["box_outline", "cost_per_kg", "sheet_width_mm", "sheet_height_mm",
                     "sheet_weight_gsm", "job_quantity"],
    },
)


async def run_packaging_material_yield(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_cad_core.packaging.material_yield import (
            MaterialCostSpec, compute_material_yield, material_cost_per_part,
        )

        outline_raw = args.get("box_outline", [])
        if not outline_raw or len(outline_raw) < 2:
            return err_payload("box_outline must have at least 2 vertices", "BAD_ARGS")

        outline: list[tuple[float, float]] = []
        for i, pt in enumerate(outline_raw):
            try:
                outline.append((float(pt[0]), float(pt[1])))
            except (TypeError, IndexError, ValueError) as exc:
                return err_payload(f"box_outline[{i}] invalid: {exc}", "BAD_ARGS")

        material = MaterialCostSpec(
            material_name=str(args.get("material_name", "unknown")),
            cost_per_kg=float(args["cost_per_kg"]),
            sheet_size_mm=(float(args["sheet_width_mm"]), float(args["sheet_height_mm"])),
            sheet_weight_gsm=float(args["sheet_weight_gsm"]),
        )

        job_qty = int(args["job_quantity"])
        efficiency = float(args.get("nesting_efficiency_pct", 75.0))
        job_id = str(args.get("job_id", "job_001"))

        report = compute_material_yield(
            box_unfolded_outline=outline,
            material=material,
            job_quantity=job_qty,
            nesting_efficiency_pct=efficiency,
            job_id=job_id,
        )
        cpp = material_cost_per_part(report, job_qty)

        return ok_payload({
            "job_id": report.job_id,
            "parts_per_sheet": report.parts_per_sheet,
            "sheets_per_job": report.sheets_per_job,
            "material_used_kg": round(report.material_used_kg, 4),
            "waste_pct": round(report.waste_pct, 2),
            "total_material_cost": round(report.total_material_cost, 4),
            "material_cost_per_part": round(cpp, 6),
            "honest_caveat": report.honest_caveat,
        })
    except ImportError:
        return err_payload(
            "kerf_cad_core.packaging.material_yield not available. "
            "Install kerf-cad-core to use material yield tools.",
            "UNAVAILABLE",
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "YIELD_ERROR")
