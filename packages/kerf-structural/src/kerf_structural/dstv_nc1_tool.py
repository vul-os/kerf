"""
LLM tool: steel_export_dstv_nc1

Generates a DSTV NC1 (.nc1) steel-fabrication NC file for a single steel
member (profile + length + hole list + cope/notch list) and returns the
file content as a string.

Standard reference
------------------
DSTV NC — Datenaustausch für numerisch gesteuerte Maschinen, Deutscher
Stahlbau-Verband (DSTV), §3 File Structure.
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_structural._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

dstv_nc1_spec = ToolSpec(
    name="steel_export_dstv_nc1",
    description=(
        "Generate a DSTV NC1 (.nc1) steel-fabrication file for a single steel "
        "member.  NC1 is the industry-standard CNC interchange format used by "
        "Tekla Structures, Advance Steel, SDS/2 and CNC drilling / coping "
        "machines.  Returns the NC1 file content as a string ready to write "
        "to disk with a .nc1 extension.\n\n"
        "Standard: DSTV NC (Deutscher Stahlbau-Verband NC data exchange), "
        "DIN 18800-7.  Blocks: ST (header) → BO (holes) → AK (outer contours) "
        "→ IK (inner contours) → SI (part marks) → EN."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "order_no": {
                "type": "string",
                "description": "Order / job number (max 20 chars).",
            },
            "drawing_no": {
                "type": "string",
                "description": "Drawing number (max 20 chars).",
            },
            "pos_no": {
                "type": "string",
                "description": "Part / position number (max 20 chars).",
            },
            "quantity": {
                "type": "integer",
                "description": "Number of identical pieces (default 1).",
            },
            "profile": {
                "type": "string",
                "description": (
                    "DSTV profile designation, e.g. 'I HEB 200', 'I IPE 300', "
                    "'U UPN 200', 'L L100x100x10', 'RO 139.7x8', 'FL 200x20'."
                ),
            },
            "material": {
                "type": "string",
                "description": "Steel grade, e.g. 'S355JR', 'S275JR', 'A572-50' (max 8 chars).",
            },
            "length_mm": {
                "type": "number",
                "description": "Cut length of the member (mm).",
            },
            "flange_width_mm": {
                "type": "number",
                "description": "Profile flange width (mm).  0 for round sections.",
            },
            "flange_thickness_mm": {
                "type": "number",
                "description": "Flange thickness (mm).  Wall thickness for hollow sections.",
            },
            "web_height_mm": {
                "type": "number",
                "description": (
                    "Total profile height (mm) for I/H sections; outer diameter "
                    "for hollow / round sections."
                ),
            },
            "web_thickness_mm": {
                "type": "number",
                "description": "Web thickness (mm).  Wall thickness for hollow sections.",
            },
            "saw_length_mm": {
                "type": "number",
                "description": (
                    "Saw-cut length (mm) when different from length_mm (skewed cuts). "
                    "Defaults to length_mm."
                ),
            },
            "holes": {
                "type": "array",
                "description": (
                    "List of holes (BO block).  Each hole is an object with keys: "
                    "face ('o'=top, 'u'=bottom, 'v'=front web, 'h'=back web, "
                    "'a'=start end, 'e'=finish end), x_mm (longitudinal from start), "
                    "y_mm (transverse from centreline), diameter_mm.  "
                    "Optional: slot_length_mm (omit or 0 for round holes)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "face":            {"type": "string"},
                        "x_mm":           {"type": "number"},
                        "y_mm":           {"type": "number"},
                        "diameter_mm":    {"type": "number"},
                        "slot_length_mm": {"type": "number"},
                    },
                    "required": ["face", "x_mm", "y_mm", "diameter_mm"],
                },
            },
            "outer_contours": {
                "type": "array",
                "description": (
                    "Outer contour polygons (AK block) for copes, notches, and "
                    "non-rectangular ends.  Each contour has 'face' and 'points' "
                    "(list of {x_mm, y_mm[, arc_bulge]})."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "face":   {"type": "string"},
                        "points": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x_mm":      {"type": "number"},
                                    "y_mm":      {"type": "number"},
                                    "arc_bulge": {"type": "number"},
                                },
                                "required": ["x_mm", "y_mm"],
                            },
                        },
                    },
                    "required": ["face", "points"],
                },
            },
            "inner_contours": {
                "type": "array",
                "description": (
                    "Inner contour polygons (IK block) for web cut-outs or "
                    "internal copes.  Same structure as outer_contours."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "face":   {"type": "string"},
                        "points": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x_mm":      {"type": "number"},
                                    "y_mm":      {"type": "number"},
                                    "arc_bulge": {"type": "number"},
                                },
                                "required": ["x_mm", "y_mm"],
                            },
                        },
                    },
                    "required": ["face", "points"],
                },
            },
            "stamps": {
                "type": "array",
                "description": (
                    "Part mark stamps (SI block).  Each stamp has: "
                    "face, x_mm, y_mm, text, size_mm (default 10)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "face":    {"type": "string"},
                        "x_mm":   {"type": "number"},
                        "y_mm":   {"type": "number"},
                        "text":   {"type": "string"},
                        "size_mm": {"type": "number"},
                    },
                    "required": ["face", "x_mm", "y_mm", "text"],
                },
            },
        },
        "required": [
            "order_no", "drawing_no", "pos_no", "profile", "material",
            "length_mm", "web_height_mm",
        ],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register(dstv_nc1_spec, write=False)
async def run_dstv_nc1(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    try:
        from kerf_structural.dstv_nc1 import (
            NC1Member, NC1Hole, NC1ContourPoint, NC1Contour, NC1Stamp, write_nc1
        )

        # Build holes list
        holes = []
        for raw_hole in a.get("holes", []):
            holes.append(NC1Hole(
                face=str(raw_hole["face"]),
                x_mm=float(raw_hole["x_mm"]),
                y_mm=float(raw_hole["y_mm"]),
                diameter_mm=float(raw_hole["diameter_mm"]),
                slot_length_mm=float(raw_hole.get("slot_length_mm", 0.0)),
            ))

        # Build outer contours
        outer_contours = []
        for raw_c in a.get("outer_contours", []):
            pts = [
                NC1ContourPoint(
                    x_mm=float(p["x_mm"]),
                    y_mm=float(p["y_mm"]),
                    arc_bulge=float(p.get("arc_bulge", 0.0)),
                )
                for p in raw_c["points"]
            ]
            outer_contours.append(NC1Contour(face=str(raw_c["face"]), points=pts))

        # Build inner contours
        inner_contours = []
        for raw_c in a.get("inner_contours", []):
            pts = [
                NC1ContourPoint(
                    x_mm=float(p["x_mm"]),
                    y_mm=float(p["y_mm"]),
                    arc_bulge=float(p.get("arc_bulge", 0.0)),
                )
                for p in raw_c["points"]
            ]
            inner_contours.append(NC1Contour(face=str(raw_c["face"]), points=pts))

        # Build stamps
        stamps = []
        for raw_s in a.get("stamps", []):
            stamps.append(NC1Stamp(
                face=str(raw_s["face"]),
                x_mm=float(raw_s["x_mm"]),
                y_mm=float(raw_s["y_mm"]),
                text=str(raw_s["text"]),
                size_mm=float(raw_s.get("size_mm", 10.0)),
            ))

        member = NC1Member(
            order_no=str(a.get("order_no", "")),
            drawing_no=str(a.get("drawing_no", "")),
            pos_no=str(a.get("pos_no", "")),
            quantity=int(a.get("quantity", 1)),
            profile=str(a["profile"]),
            material=str(a.get("material", "")),
            length_mm=float(a["length_mm"]),
            flange_width_mm=float(a.get("flange_width_mm", 0.0)),
            flange_thickness_mm=float(a.get("flange_thickness_mm", 0.0)),
            web_height_mm=float(a["web_height_mm"]),
            web_thickness_mm=float(a.get("web_thickness_mm", 0.0)),
            holes=holes,
            outer_contours=outer_contours,
            inner_contours=inner_contours,
            stamps=stamps,
            saw_length_mm=float(a["saw_length_mm"]) if "saw_length_mm" in a else None,
        )

        nc1_text = write_nc1(member)

    except (ValueError, KeyError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    return ok_payload({
        "ok": True,
        "nc1_text": nc1_text,
        "member_summary": {
            "profile": member.profile,
            "material": member.material,
            "length_mm": member.length_mm,
            "hole_count": len(member.holes),
            "outer_contour_count": len(member.outer_contours),
            "inner_contour_count": len(member.inner_contours),
        },
        "note": (
            "Save the nc1_text content to a file with .nc1 extension.  "
            "Format: DSTV NC (Deutscher Stahlbau-Verband), DIN 18800-7."
        ),
    })
