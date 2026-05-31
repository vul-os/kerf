"""
kerf_mold.gate_vestige_check_tool — LLM tool wrapper for gate vestige check.

Tool: mold_check_gate_vestige
  Estimate the gate vestige (gate-mark protrusion) for a given gate type
  and dimension, then check compliance against a cosmetic class requirement.

References:
  Beaumont J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed., §7.6.
  Menges G., Michaeli W., Mohren P. (2001). *How to Make Injection Molds*,
    3rd ed., §6.6.
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.gate_vestige_check import GateSpec, check_gate_vestige


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_check_gate_vestige_spec = ToolSpec(
    name="mold_check_gate_vestige",
    description=(
        "Estimate the gate *vestige* (protrusion / gate-mark scar) left on a "
        "molded part after degating, and check whether it meets a cosmetic "
        "class requirement (Beaumont 2007 §7.6 + Table 7.4; Menges 2001 §6.6).\n\n"
        "Vestige rules per gate type (Beaumont 2007 Table 7.4):\n"
        "  • edge / fan  : vestige ≈ gate_thickness (worst-case knife trim)\n"
        "  • tunnel      : vestige ≈ 0.10 mm (range 0.05–0.15; sub-surface break)\n"
        "  • submarine   : vestige ≈ 0.05 mm (angled sub-surface break)\n"
        "  • hot_tip     : vestige ≈ 0.20 mm (range 0.10–0.30; thermal pip)\n"
        "  • pin_point   : vestige ≈ 0.10 mm (small circular gate pip)\n"
        "  • film        : vestige ≈ 0.50 mm (trimmed tab scar)\n\n"
        "Cosmetic classes:\n"
        "  A1 = flush (0 mm) | A2 ≤ 0.1 mm | A3 ≤ 0.3 mm | B ≤ 1.0 mm | C = any\n\n"
        "Inputs:\n"
        "  gate_type        — \"edge\"|\"tunnel\"|\"submarine\"|\"hot_tip\"|"
        "\"pin_point\"|\"fan\"|\"film\"\n"
        "  gate_thickness_mm — gate land thickness [mm] (> 0)\n"
        "  gate_width_mm    — gate width [mm] (> 0; mainly relevant for fan/film)\n"
        "  polymer_grade    — e.g. \"ABS\", \"PC\", \"PP\" (informational; "
        "recorded in caveat)\n"
        "  required_class   — cosmetic class to check against "
        "(\"A1\"|\"A2\"|\"A3\"|\"B\"|\"C\"); default \"A2\"\n\n"
        "Returns: {estimated_vestige_mm, cosmetic_class_required, "
        "cosmetic_class_achieved, compliant, removal_method, "
        "honest_caveat, reference}.\n\n"
        "Honest caveat: empirical estimates only. Actual vestige depends on "
        "degating tool sharpness, melt temperature, mold temperature, gate land "
        "length, and resin ductility. Confirm by molding trial for A1/A2 surfaces."
    ),
    input_schema={
        "type": "object",
        "required": ["gate_type", "gate_thickness_mm", "gate_width_mm", "polymer_grade"],
        "properties": {
            "gate_type": {
                "type": "string",
                "description": (
                    "Gate geometry type. One of: \"edge\", \"tunnel\", "
                    "\"submarine\", \"hot_tip\", \"pin_point\", \"fan\", \"film\"."
                ),
                "enum": ["edge", "tunnel", "submarine", "hot_tip", "pin_point", "fan", "film"],
            },
            "gate_thickness_mm": {
                "type": "number",
                "description": "Gate land thickness [mm]. Must be > 0.",
                "exclusiveMinimum": 0,
            },
            "gate_width_mm": {
                "type": "number",
                "description": "Gate width [mm]. Must be > 0.",
                "exclusiveMinimum": 0,
            },
            "polymer_grade": {
                "type": "string",
                "description": (
                    "Polymer/material grade. Informational — e.g. \"ABS\", "
                    "\"PC\", \"PP\", \"POM\". Recorded in caveat; does not "
                    "change the numeric vestige estimate."
                ),
            },
            "required_class": {
                "type": "string",
                "description": (
                    "Required cosmetic class for the part surface at the gate. "
                    "\"A1\" = flush; \"A2\" ≤ 0.1 mm; \"A3\" ≤ 0.3 mm; "
                    "\"B\" ≤ 1.0 mm; \"C\" = any visible vestige OK. "
                    "Default: \"A2\"."
                ),
                "enum": ["A1", "A2", "A3", "B", "C"],
                "default": "A2",
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_check_gate_vestige(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute gate vestige check and return a JSON string."""
    try:
        gate_type = args.get("gate_type")
        gate_thickness_mm = args.get("gate_thickness_mm")
        gate_width_mm = args.get("gate_width_mm")
        polymer_grade = args.get("polymer_grade")
        required_class = args.get("required_class", "A2")

        # Validate required args
        if gate_type is None:
            return err_payload("gate_type is required", "BAD_ARGS")
        if gate_thickness_mm is None:
            return err_payload("gate_thickness_mm is required", "BAD_ARGS")
        if gate_width_mm is None:
            return err_payload("gate_width_mm is required", "BAD_ARGS")
        if polymer_grade is None:
            return err_payload("polymer_grade is required", "BAD_ARGS")

        try:
            gate_thickness_mm = float(gate_thickness_mm)
        except (TypeError, ValueError):
            return err_payload(
                f"gate_thickness_mm must be a number, got {gate_thickness_mm!r}",
                "BAD_ARGS",
            )

        try:
            gate_width_mm = float(gate_width_mm)
        except (TypeError, ValueError):
            return err_payload(
                f"gate_width_mm must be a number, got {gate_width_mm!r}",
                "BAD_ARGS",
            )

        gate = GateSpec(
            gate_type=str(gate_type),
            gate_thickness_mm=gate_thickness_mm,
            gate_width_mm=gate_width_mm,
            polymer_grade=str(polymer_grade),
        )

        report = check_gate_vestige(gate, required_class=str(required_class))

        payload: dict[str, Any] = {
            "ok": True,
            "estimated_vestige_mm": report.estimated_vestige_mm,
            "cosmetic_class_required": report.cosmetic_class_required,
            "cosmetic_class_achieved": report.cosmetic_class_achieved,
            "compliant": report.compliant,
            "removal_method": report.removal_method,
            "honest_caveat": report.honest_caveat,
            "reference": "Beaumont 2007 §7.6 + Table 7.4; Menges 2001 §6.6",
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "GATE_VESTIGE_ERROR")
