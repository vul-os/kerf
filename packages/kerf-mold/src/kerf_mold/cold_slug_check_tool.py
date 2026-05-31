"""
kerf_mold.cold_slug_check_tool — LLM tool wrapper for cold-slug well check.

Tool: mold_check_cold_slug_design
  Given a list of runner junctions with their cold-slug well dimensions, verify
  each well against the Beaumont 2007 §6.7 + Menges 2001 §6.5 geometric rules:

    slug well diameter = 1.5 × runner diameter  (±20 % tolerance)
    slug well depth    = 2.0 × runner diameter  (±20 % tolerance)

  Underdimensioned wells fail to capture the cold leading-edge polymer slug and
  allow it to enter the gate, causing flow lines and weak weld lines.  Oversized
  wells waste material and increase cycle time.

References:
  Beaumont J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed.,
    Hanser, §6.7 Cold Slug Wells.
  Menges G., Michaeli W., Mohren P. (2001). *How to Make Injection Molds*,
    3rd ed., Hanser, §6.5 Runner junction design.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.cold_slug_check import (
    RunnerJunctionSpec,
    check_cold_slug_design,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_check_cold_slug_design_spec = ToolSpec(
    name="mold_check_cold_slug_design",
    description=(
        "Verify cold-slug well dimensions at runner junctions in a multi-cavity "
        "injection mold against the Beaumont 2007 §6.7 + Menges 2001 §6.5 "
        "geometric guidelines.\n\n"
        "Rules applied:\n"
        "  slug well diameter = 1.5 × runner diameter  (±20 % tolerance → 1.2×–1.8×)\n"
        "  slug well depth    = 2.0 × runner diameter  (±20 % tolerance → 1.6×–2.4×)\n\n"
        "A cold slug well that is too small allows the cold leading-edge polymer "
        "plug to reach the gate, causing flow lines and weak weld lines.  "
        "An oversized well wastes material and may increase cycle time.\n\n"
        "Input: list of junctions, each with:\n"
        "  junction_id           — label string (e.g. 'J1', 'primary-left')\n"
        "  runner_diameter_mm    — runner diameter at this junction [mm] (> 0)\n"
        "  slug_well_diameter_mm — proposed slug-well diameter [mm] (> 0)\n"
        "  slug_well_depth_mm    — proposed slug-well depth [mm] (> 0)\n"
        "  polymer_grade         — informational resin grade (e.g. 'ABS', 'PP-GF30')\n\n"
        "Returns per-junction results plus overall compliance summary.\n\n"
        "Honest caveat: geometric rule-of-thumb only — actual cold-slug capture "
        "depends on melt temperature, injection speed, and resin freeze-off time. "
        "Confirm by mold trial; use Moldflow / Moldex3D / SigmaSoft for full "
        "melt-front thermal simulation."
    ),
    input_schema={
        "type": "object",
        "required": ["junctions"],
        "properties": {
            "junctions": {
                "type": "array",
                "description": (
                    "List of runner junctions to check.  Each item must include "
                    "junction_id, runner_diameter_mm, slug_well_diameter_mm, "
                    "slug_well_depth_mm, and polymer_grade."
                ),
                "items": {
                    "type": "object",
                    "required": [
                        "junction_id",
                        "runner_diameter_mm",
                        "slug_well_diameter_mm",
                        "slug_well_depth_mm",
                        "polymer_grade",
                    ],
                    "properties": {
                        "junction_id": {
                            "type": "string",
                            "description": "Junction label, e.g. 'J1' or 'primary-left'.",
                        },
                        "runner_diameter_mm": {
                            "type": "number",
                            "description": "Runner diameter at this junction [mm]. Must be > 0.",
                            "exclusiveMinimum": 0,
                        },
                        "slug_well_diameter_mm": {
                            "type": "number",
                            "description": (
                                "Proposed slug-well diameter [mm]. "
                                "Beaumont 2007 §6.7 recommends 1.5 × runner_diameter. "
                                "Must be > 0."
                            ),
                            "exclusiveMinimum": 0,
                        },
                        "slug_well_depth_mm": {
                            "type": "number",
                            "description": (
                                "Proposed slug-well depth [mm]. "
                                "Beaumont 2007 §6.7 recommends 2.0 × runner_diameter. "
                                "Must be > 0."
                            ),
                            "exclusiveMinimum": 0,
                        },
                        "polymer_grade": {
                            "type": "string",
                            "description": (
                                "Informational polymer grade string, "
                                "e.g. 'ABS', 'PP', 'PA66', 'PP-GF30'. "
                                "Not used in the compliance calculation."
                            ),
                        },
                    },
                },
                "minItems": 1,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_check_cold_slug_design(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute cold-slug well check and return a JSON string."""
    try:
        raw_junctions = args.get("junctions")
        if not raw_junctions:
            return err_payload("junctions is required and must not be empty", "BAD_ARGS")

        if not isinstance(raw_junctions, list):
            return err_payload(
                f"junctions must be a list, got {type(raw_junctions).__name__}",
                "BAD_ARGS",
            )

        specs = []
        for idx, item in enumerate(raw_junctions):
            if not isinstance(item, dict):
                return err_payload(
                    f"junctions[{idx}] must be an object, got "
                    f"{type(item).__name__}",
                    "BAD_ARGS",
                )

            junction_id = item.get("junction_id")
            if junction_id is None:
                return err_payload(
                    f"junctions[{idx}].junction_id is required", "BAD_ARGS"
                )

            runner_diameter_mm = item.get("runner_diameter_mm")
            if runner_diameter_mm is None:
                return err_payload(
                    f"junctions[{idx}].runner_diameter_mm is required", "BAD_ARGS"
                )

            slug_well_diameter_mm = item.get("slug_well_diameter_mm")
            if slug_well_diameter_mm is None:
                return err_payload(
                    f"junctions[{idx}].slug_well_diameter_mm is required", "BAD_ARGS"
                )

            slug_well_depth_mm = item.get("slug_well_depth_mm")
            if slug_well_depth_mm is None:
                return err_payload(
                    f"junctions[{idx}].slug_well_depth_mm is required", "BAD_ARGS"
                )

            polymer_grade = item.get("polymer_grade")
            if polymer_grade is None:
                return err_payload(
                    f"junctions[{idx}].polymer_grade is required", "BAD_ARGS"
                )

            # Coerce numeric fields
            try:
                runner_diameter_mm = float(runner_diameter_mm)
            except (TypeError, ValueError):
                return err_payload(
                    f"junctions[{idx}].runner_diameter_mm must be a number, "
                    f"got {runner_diameter_mm!r}",
                    "BAD_ARGS",
                )
            try:
                slug_well_diameter_mm = float(slug_well_diameter_mm)
            except (TypeError, ValueError):
                return err_payload(
                    f"junctions[{idx}].slug_well_diameter_mm must be a number, "
                    f"got {slug_well_diameter_mm!r}",
                    "BAD_ARGS",
                )
            try:
                slug_well_depth_mm = float(slug_well_depth_mm)
            except (TypeError, ValueError):
                return err_payload(
                    f"junctions[{idx}].slug_well_depth_mm must be a number, "
                    f"got {slug_well_depth_mm!r}",
                    "BAD_ARGS",
                )

            specs.append(
                RunnerJunctionSpec(
                    junction_id=str(junction_id),
                    runner_diameter_mm=runner_diameter_mm,
                    slug_well_diameter_mm=slug_well_diameter_mm,
                    slug_well_depth_mm=slug_well_depth_mm,
                    polymer_grade=str(polymer_grade),
                )
            )

        report = check_cold_slug_design(specs)

        payload: dict[str, Any] = {
            "ok": True,
            "total_junctions": report.total_junctions,
            "compliant_count": report.compliant_count,
            "all_compliant": report.compliant_count == report.total_junctions,
            "junction_results": report.junction_results,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., "
                "Hanser 2007, §6.7 Cold Slug Wells; "
                "Menges G., Michaeli W., Mohren P. How to Make Injection Molds, "
                "3rd ed., Hanser 2001, §6.5 Runner junction design."
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "COLD_SLUG_ERROR")
