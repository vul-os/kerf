"""
kerf_mold.vent_slot_layout_tool — LLM tool wrapper for vent slot layout.

Tool: mold_generate_vent_slot_layout
  Given a cavity volume, parting-line perimeter, polymer grade, and injection
  speed, propose the number of vent slots, their width, and centre-to-centre
  spacing sufficient for the air-displacement volume.

  Based on Beaumont 2007 §8.5 (Vent Slot Count and Width) + Menges 2001 §6.4.

References:
  Beaumont J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed.,
    Hanser, §8.5 Vent Slot Count and Width.
  Menges G., Michaeli W., Mohren P. (2001). *How to Make Injection Molds*,
    3rd ed., Hanser, §6.4 Vent Slot Design.
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.vent_slot_layout import (
    MoldVolumeSpec,
    POLYMER_VENT_DEPTH_RANGE,
    generate_vent_slot_layout,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_SUPPORTED_POLYMERS = sorted(POLYMER_VENT_DEPTH_RANGE.keys())

mold_generate_vent_slot_layout_spec = ToolSpec(
    name="mold_generate_vent_slot_layout",
    description=(
        "Propose a vent slot layout (count, width, spacing) for an injection-mold "
        "cavity sufficient for the air-displacement volume during filling.\n\n"
        "Uses Beaumont 2007 §8.5 (Vent Slot Count and Width) + Menges 2001 §6.4:\n"
        "  • Total vent area ≥ 0.5 % of projected cavity area (baseline).\n"
        "  • Injection speeds above 50 cm³/s scale the required area proportionally.\n"
        "  • Standard vent slot width = 6 mm (Beaumont §8.5 + Menges §6.4).\n"
        "  • Polymer-specific vent depth midpoint used for per-slot area sizing.\n"
        "  • Minimum 4 slots (one per quadrant, Beaumont §8.5).\n"
        "  • Minimum 10 mm steel bridge between slots (Menges §6.4 sealing surface).\n\n"
        "Inputs:\n"
        "  cavity_volume_cm3         — total cavity volume [cm³]\n"
        "  parting_line_perimeter_mm — parting-line perimeter available for vents [mm]\n"
        "  polymer_grade             — e.g. 'ABS', 'PC', 'PP', 'PA66', 'POM', 'PMMA', 'PE'\n"
        "  injection_speed_cm3_s     — volumetric injection speed [cm³/s]\n\n"
        "Returns:\n"
        "  num_vent_slots, vent_slot_width_mm (always 6 mm), vent_slot_spacing_mm,\n"
        "  total_vent_width_mm, air_displacement_rate_cm3_s, adequate, honest_caveat.\n\n"
        "Honest caveat: heuristic rule based on production experience "
        "(Beaumont 2007 §8.5). Wall thickness assumed 3 mm for area estimation. "
        "Uniform spacing only — use mold_optimize_vent_placement to locate vents "
        "at last-to-fill regions. Confirm by Moldflow / Moldex3D / SigmaSoft + "
        "mold-trial visual inspection."
    ),
    input_schema={
        "type": "object",
        "required": [
            "cavity_volume_cm3",
            "parting_line_perimeter_mm",
            "polymer_grade",
            "injection_speed_cm3_s",
        ],
        "properties": {
            "cavity_volume_cm3": {
                "type": "number",
                "description": (
                    "Total injection cavity volume [cm³]. Must be > 0. "
                    "Example: 50.0 for a 50 cm³ cavity."
                ),
                "exclusiveMinimum": 0,
            },
            "parting_line_perimeter_mm": {
                "type": "number",
                "description": (
                    "Total length of the parting-line perimeter available for vent "
                    "slots [mm]. Must be > 0. "
                    "Example: 200.0 for a 200 mm perimeter."
                ),
                "exclusiveMinimum": 0,
            },
            "polymer_grade": {
                "type": "string",
                "description": (
                    "Polymer material grade. Supported: "
                    + ", ".join(f'"{p}"' for p in _SUPPORTED_POLYMERS)
                    + ". Unknown grades use a fallback vent depth range with a caveat."
                ),
            },
            "injection_speed_cm3_s": {
                "type": "number",
                "description": (
                    "Volumetric injection speed [cm³/s]. Must be > 0. "
                    "Beaumont §8.5: speeds > 50 cm³/s require proportionally more "
                    "total vent area. Example: 50.0 for a moderate-speed fill."
                ),
                "exclusiveMinimum": 0,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_generate_vent_slot_layout(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute vent slot layout calculation and return a JSON string."""
    try:
        cavity_volume_cm3 = args.get("cavity_volume_cm3")
        parting_line_perimeter_mm = args.get("parting_line_perimeter_mm")
        polymer_grade = args.get("polymer_grade")
        injection_speed_cm3_s = args.get("injection_speed_cm3_s")

        # Validate required args
        if cavity_volume_cm3 is None:
            return err_payload("cavity_volume_cm3 is required", "BAD_ARGS")
        if parting_line_perimeter_mm is None:
            return err_payload("parting_line_perimeter_mm is required", "BAD_ARGS")
        if polymer_grade is None:
            return err_payload("polymer_grade is required", "BAD_ARGS")
        if injection_speed_cm3_s is None:
            return err_payload("injection_speed_cm3_s is required", "BAD_ARGS")

        try:
            cavity_volume_cm3 = float(cavity_volume_cm3)
        except (TypeError, ValueError):
            return err_payload(
                f"cavity_volume_cm3 must be a number, got {cavity_volume_cm3!r}",
                "BAD_ARGS",
            )
        try:
            parting_line_perimeter_mm = float(parting_line_perimeter_mm)
        except (TypeError, ValueError):
            return err_payload(
                f"parting_line_perimeter_mm must be a number, "
                f"got {parting_line_perimeter_mm!r}",
                "BAD_ARGS",
            )
        try:
            injection_speed_cm3_s = float(injection_speed_cm3_s)
        except (TypeError, ValueError):
            return err_payload(
                f"injection_speed_cm3_s must be a number, "
                f"got {injection_speed_cm3_s!r}",
                "BAD_ARGS",
            )

        spec = MoldVolumeSpec(
            cavity_volume_cm3=cavity_volume_cm3,
            parting_line_perimeter_mm=parting_line_perimeter_mm,
            polymer_grade=str(polymer_grade),
            injection_speed_cm3_s=injection_speed_cm3_s,
        )

        report = generate_vent_slot_layout(spec)

        payload: dict[str, Any] = {
            "ok": True,
            "polymer_grade": spec.polymer_grade,
            "cavity_volume_cm3": spec.cavity_volume_cm3,
            "parting_line_perimeter_mm": spec.parting_line_perimeter_mm,
            "injection_speed_cm3_s": spec.injection_speed_cm3_s,
            "num_vent_slots": report.num_vent_slots,
            "vent_slot_width_mm": report.vent_slot_width_mm,
            "vent_slot_spacing_mm": report.vent_slot_spacing_mm,
            "total_vent_width_mm": report.total_vent_width_mm,
            "air_displacement_rate_cm3_s": report.air_displacement_rate_cm3_s,
            "adequate": report.adequate,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., "
                "Hanser 2007, §8.5 Vent Slot Count and Width; "
                "Menges G., Michaeli W., Mohren P. How to Make Injection Molds, "
                "3rd ed., Hanser 2001, §6.4 Vent Slot Design."
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "VENT_SLOT_LAYOUT_ERROR")
