"""
kerf_mold.vent_depth_check_tool — LLM tool wrapper for mold vent depth check.

Tool: mold_check_vent_depth
  Given a polymer grade and proposed vent depth, verify that the parting-line
  air-escape gap is within the polymer-specific recommended range per
  Beaumont 2007 §8.3 Table 8.2 + Menges 2001 §6.4 Table 6.7.

  Too shallow → trapped air → short shot / burn marks (diesel effect).
  Too deep    → flash at parting line.

References:
  Beaumont J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed.,
    Hanser, §8.3 + Table 8.2.
  Menges G., Michaeli W., Mohren P. (2001). *How to Make Injection Molds*,
    3rd ed., Hanser, §6.4 + Table 6.7.
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.vent_depth_check import (
    VentSpec,
    check_vent_depth,
    VENT_DEPTH_DB,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_SUPPORTED_POLYMERS = sorted(VENT_DEPTH_DB.keys())

mold_check_vent_depth_spec = ToolSpec(
    name="mold_check_vent_depth",
    description=(
        "Verify that a mold parting-line vent depth (air-escape gap) is correct "
        "for the given polymer melt.\n\n"
        "Too shallow → trapped air → short shot / burn marks (diesel effect).\n"
        "Too deep    → flash at parting line.\n\n"
        "Uses empirical polymer-specific recommended ranges from "
        "Beaumont 2007 §8.3 Table 8.2 + Menges 2001 §6.4 Table 6.7:\n"
        "  ABS   — 0.025–0.038 mm  (amorphous; moderate viscosity)\n"
        "  PC    — 0.013–0.025 mm  (amorphous; low viscosity)\n"
        "  PP    — 0.025–0.050 mm  (semi-crystalline; moderate–high viscosity)\n"
        "  PA66  — 0.013–0.025 mm  (semi-crystalline; low melt viscosity)\n"
        "  POM   — 0.013–0.025 mm  (semi-crystalline; low melt viscosity)\n"
        "  PMMA  — 0.025–0.038 mm  (amorphous; moderate viscosity)\n"
        "  PE    — 0.038–0.075 mm  (semi-crystalline; high melt viscosity)\n\n"
        "Unknown polymers receive a fallback range (0.013–0.038 mm) with a caveat.\n\n"
        "Classification:\n"
        "  'too_shallow' — depth < min (trapped air risk)\n"
        "  'correct'     — depth within [min, max] (compliant)\n"
        "  'too_deep'    — depth > max but ≤ max × 1.25 (probable flash)\n"
        "  'flash_risk'  — depth > max × 1.25 (significant flash risk)\n\n"
        "Inputs:\n"
        "  polymer_grade     — e.g. 'ABS', 'PC', 'PP', 'PA66', 'POM', 'PMMA', 'PE'\n"
        "  proposed_depth_mm — proposed vent depth [mm] (must be > 0)\n"
        "  land_length_mm    — vent land length [mm] (default 1.5; Beaumont §8.3.2 ≥ 0.8)\n"
        "  vent_width_mm     — vent slot width [mm] (default 6.0; context only)\n\n"
        "Returns: {recommended_depth_min_mm, recommended_depth_max_mm, compliant,\n"
        "          depth_class, polymer_notes, honest_caveat}.\n\n"
        "Honest caveat: empirical handbook ranges only. Actual safe depth depends on "
        "resin batch viscosity, melt temp, injection speed, and mold surface finish. "
        "Confirm by mold trial + visual flash inspection."
    ),
    input_schema={
        "type": "object",
        "required": ["polymer_grade", "proposed_depth_mm"],
        "properties": {
            "polymer_grade": {
                "type": "string",
                "description": (
                    "Polymer material grade. Supported: "
                    + ", ".join(f'"{p}"' for p in _SUPPORTED_POLYMERS)
                    + ". Unknown grades receive a fallback range with a caveat."
                ),
            },
            "proposed_depth_mm": {
                "type": "number",
                "description": (
                    "Proposed vent depth (parting-line air-escape gap) [mm]. "
                    "Typical range 0.010–0.100 mm. Must be > 0."
                ),
                "exclusiveMinimum": 0,
            },
            "land_length_mm": {
                "type": "number",
                "description": (
                    "Length of the vent land (flat sealing surface behind the gap) [mm]. "
                    "Beaumont 2007 §8.3.2 recommends ≥ 0.8 mm. Default 1.5 mm. "
                    "Must be ≥ 0."
                ),
                "minimum": 0,
                "default": 1.5,
            },
            "vent_width_mm": {
                "type": "number",
                "description": (
                    "Width of the vent slot [mm]. Default 6.0 mm. "
                    "Provided for context; this tool checks depth only. "
                    "Must be > 0."
                ),
                "exclusiveMinimum": 0,
                "default": 6.0,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_check_vent_depth(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute vent depth check and return a JSON string."""
    try:
        polymer_grade = args.get("polymer_grade")
        proposed_depth_mm = args.get("proposed_depth_mm")
        land_length_mm = args.get("land_length_mm", 1.5)
        vent_width_mm = args.get("vent_width_mm", 6.0)

        # Validate required args
        if polymer_grade is None:
            return err_payload("polymer_grade is required", "BAD_ARGS")
        if proposed_depth_mm is None:
            return err_payload("proposed_depth_mm is required", "BAD_ARGS")

        try:
            proposed_depth_mm = float(proposed_depth_mm)
        except (TypeError, ValueError):
            return err_payload(
                f"proposed_depth_mm must be a number, got {proposed_depth_mm!r}",
                "BAD_ARGS",
            )
        try:
            land_length_mm = float(land_length_mm)
        except (TypeError, ValueError):
            return err_payload(
                f"land_length_mm must be a number, got {land_length_mm!r}",
                "BAD_ARGS",
            )
        try:
            vent_width_mm = float(vent_width_mm)
        except (TypeError, ValueError):
            return err_payload(
                f"vent_width_mm must be a number, got {vent_width_mm!r}",
                "BAD_ARGS",
            )

        vent = VentSpec(
            polymer_grade=str(polymer_grade),
            proposed_depth_mm=proposed_depth_mm,
            land_length_mm=land_length_mm,
            vent_width_mm=vent_width_mm,
        )

        report = check_vent_depth(vent)

        payload: dict[str, Any] = {
            "ok": True,
            "polymer_grade": vent.polymer_grade,
            "proposed_depth_mm": vent.proposed_depth_mm,
            "recommended_depth_min_mm": report.recommended_depth_min_mm,
            "recommended_depth_max_mm": report.recommended_depth_max_mm,
            "compliant": report.compliant,
            "depth_class": report.depth_class,
            "polymer_notes": report.polymer_notes,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., "
                "Hanser 2007, §8.3 + Table 8.2; "
                "Menges G., Michaeli W., Mohren P. How to Make Injection Molds, "
                "3rd ed., Hanser 2001, §6.4 + Table 6.7."
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "VENT_DEPTH_ERROR")
