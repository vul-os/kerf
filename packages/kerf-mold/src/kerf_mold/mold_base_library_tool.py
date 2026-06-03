"""
kerf_mold.mold_base_library_tool — LLM tool wrapper for standard mold base library.

Tool: mold_select_standard_base
  Select the smallest standard mold base (DME, Hasco, Misumi) accommodating
  the given cavity dimensions.

References:
  Sanford, J. (2017). *Mold Engineering*, 2nd ed., Hanser Publishers, §3–§4.
  DME Mold Components Catalog — CD/CV series §2–§6.

Wave 9C: Cimatron mold base + EDM electrode + wire EDM
"""
from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.mold_base_library import (
    standard_mold_base,
    list_catalog_sizes,
    MoldBaseAssembly,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_select_standard_base_spec = ToolSpec(
    name="mold_select_standard_base",
    description=(
        "Select the smallest standard mold base (DME, Hasco, or Misumi catalog) "
        "accommodating a given injection-mold cavity.\n\n"
        "Returns the complete plate stack-up (TCP / A-plate / B-plate / "
        "BB / BC / EJ-A / EJ-B), leader pins, bushings, return pins, screws, "
        "total mold height, and cavity area.\n\n"
        "Available catalogs:\n"
        "  DME   — CD series (public catalog standard two-plate cold-runner base)\n"
        "  Hasco — Z series (metric, 96–396 mm range)\n"
        "  Misumi — FSWP series (metric, 100–300 mm range)\n\n"
        "Plate roles:\n"
        "  TCP   — Top Clamping Plate\n"
        "  CB-A  — A-plate (fixed cavity half)\n"
        "  CB-B  — B-plate (moving core half)\n"
        "  BB    — Backing / Support Plate\n"
        "  BC    — Bottom Clamping Plate\n"
        "  EJ-A  — Ejector Retainer Plate\n"
        "  EJ-B  — Ejector Plate\n\n"
        "Returns: {ok, catalog, series, plates, leader_pins, bushings, return_pins, "
        "screws, total_height_mm, cavity_area_mm2, plate_width_mm, plate_length_mm, "
        "honest_caveat}.\n\n"
        "HONEST: Sizes are heuristic from public catalog data. "
        "Verify against current vendor catalog before ordering.\n\n"
        "Refs: Sanford 2017 §3; DME Catalog §2–§6."
    ),
    input_schema={
        "type": "object",
        "required": ["cavity_w_mm", "cavity_h_mm", "cavity_depth_mm"],
        "properties": {
            "cavity_w_mm": {
                "type": "number",
                "description": "Cavity block width (X axis) in mm. Must be > 0.",
                "exclusiveMinimum": 0,
            },
            "cavity_h_mm": {
                "type": "number",
                "description": "Cavity block length/height (Y axis) in mm. Must be > 0.",
                "exclusiveMinimum": 0,
            },
            "cavity_depth_mm": {
                "type": "number",
                "description": "Depth of the cavity pocket in mm. Must be > 0.",
                "exclusiveMinimum": 0,
            },
            "catalog": {
                "type": "string",
                "enum": ["DME", "Hasco", "Misumi"],
                "description": "Mold base catalog. Default 'DME'.",
                "default": "DME",
            },
            "series": {
                "type": "string",
                "description": "Series code within catalog (e.g. 'CD' for DME). Default 'CD'.",
                "default": "CD",
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_select_standard_base(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute standard mold base selection and return a JSON string."""
    try:
        cavity_w = args.get("cavity_w_mm")
        cavity_h = args.get("cavity_h_mm")
        cavity_d = args.get("cavity_depth_mm")
        catalog = str(args.get("catalog", "DME"))
        series = str(args.get("series", "CD"))

        if cavity_w is None:
            return err_payload("cavity_w_mm is required", "BAD_ARGS")
        if cavity_h is None:
            return err_payload("cavity_h_mm is required", "BAD_ARGS")
        if cavity_d is None:
            return err_payload("cavity_depth_mm is required", "BAD_ARGS")

        try:
            cavity_w = float(cavity_w)
            cavity_h = float(cavity_h)
            cavity_d = float(cavity_d)
        except (TypeError, ValueError) as exc:
            return err_payload(f"numeric conversion failed: {exc}", "BAD_ARGS")

        assembly: MoldBaseAssembly = standard_mold_base(
            cavity_w_mm=cavity_w,
            cavity_h_mm=cavity_h,
            cavity_depth_mm=cavity_d,
            catalog=catalog,
            series=series,
        )

        plates_out = [
            {
                "role": p.role,
                "thickness_mm": p.thickness_mm,
                "width_mm": p.width_mm,
                "length_mm": p.length_mm,
                "material": p.material,
            }
            for p in assembly.plates
        ]

        return ok_payload({
            "ok": True,
            "catalog": assembly.catalog,
            "series": assembly.series,
            "plates": plates_out,
            "leader_pins": assembly.leader_pins,
            "bushings": assembly.bushings,
            "return_pins": assembly.return_pins,
            "screws": assembly.screws,
            "total_height_mm": assembly.total_height_mm,
            "cavity_area_mm2": assembly.cavity_area_mm2,
            "plate_width_mm": assembly.plate_width_mm,
            "plate_length_mm": assembly.plate_length_mm,
            "honest_caveat": assembly.honest_caveat,
            "reference": (
                "Sanford, J. (2017). Mold Engineering, 2nd ed., Hanser Publishers, §3–§4. "
                "DME Mold Components Catalog CD/CV series §2–§6."
            ),
        })

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "MOLD_BASE_ERROR")
