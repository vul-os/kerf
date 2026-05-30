"""
kerf_mold.runner_layout_tool — LLM tool wrapper for runner-system layout.

Tool: mold_generate_runner_layout
  Design the cold-runner tree for a multi-cavity injection mold.
  Returns balanced runner segments, diameters (Beaumont 2007 §6.5),
  balance score, pressure-drop coefficient, and advisory warnings.

SCOPE: Cold-runner systems only. Hot runners are NOT modelled.

References:
  Beaumont, J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed., §6.5.
  Menges, G., Michaeli, W., Mohren, P. (2001). *How to Make Injection Molds*, 3rd ed., §6.
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_runner_layout_spec = ToolSpec(
    name="mold_generate_runner_layout",
    description=(
        "Design a cold-runner system (channels carrying molten plastic from "
        "sprue to gates) for a multi-cavity injection mold.  "
        "Generates a balanced runner tree, sizes each runner diameter using "
        "Beaumont (2007) §6.5 (D ≥ W^0.25 + 0.5 mm, max 10 mm), and reports "
        "a balance score (1.0 = naturally balanced; <1.0 = artificial balance "
        "required with graduated diameters).  "
        "COLD RUNNERS ONLY — hot-runner systems are not modelled.  "
        "Ref: Beaumont 2007 §6.5; Menges 2001 §6."
    ),
    input_schema={
        "type": "object",
        "required": ["cavity_positions", "part_weights", "sprue_position"],
        "properties": {
            "cavity_positions": {
                "type": "array",
                "description": (
                    "Centre [x, y] or [x, y, z] in mm of each cavity. "
                    "Length determines number of cavities."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 3,
                },
                "minItems": 1,
            },
            "part_weights": {
                "type": "array",
                "description": "Shot weight per cavity [grams]. Must match len(cavity_positions).",
                "items": {"type": "number", "exclusiveMinimum": 0},
                "minItems": 1,
            },
            "sprue_position": {
                "type": "array",
                "description": "[x, y] or [x, y, z] in mm of the sprue entry point.",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 3,
            },
            "gate_positions": {
                "type": "array",
                "description": (
                    "Optional [x, y, z] in mm of each injection gate.  "
                    "Defaults to cavity_positions when omitted."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 3,
                },
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_generate_runner_layout(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_mold.runner_layout import generate_runner_layout

        # Parse inputs
        cavity_positions = args.get("cavity_positions")
        part_weights = args.get("part_weights")
        sprue_position = args.get("sprue_position")

        if not cavity_positions:
            return err_payload("cavity_positions must be a non-empty list", "BAD_ARGS")
        if not part_weights:
            return err_payload("part_weights must be a non-empty list", "BAD_ARGS")
        if not sprue_position:
            return err_payload("sprue_position is required", "BAD_ARGS")

        # Coerce to floats
        try:
            cavity_positions = [[float(v) for v in p] for p in cavity_positions]
            part_weights = [float(w) for w in part_weights]
            sprue_position = [float(v) for v in sprue_position]
        except (TypeError, ValueError) as exc:
            return err_payload(f"Invalid numeric value: {exc}", "BAD_ARGS")

        gate_positions = args.get("gate_positions")
        if gate_positions is not None:
            try:
                gate_positions = [[float(v) for v in p] for p in gate_positions]
            except (TypeError, ValueError) as exc:
                return err_payload(f"Invalid gate_positions: {exc}", "BAD_ARGS")

        layout = generate_runner_layout(
            cavity_positions=cavity_positions,
            part_weights=part_weights,
            sprue_position=sprue_position,
            gate_positions=gate_positions,
        )

        segments_out = [
            {
                "segment_id": seg.segment_id,
                "start": [round(v, 4) for v in seg.start],
                "end": [round(v, 4) for v in seg.end],
                "diameter_mm": round(seg.diameter_mm, 3),
                "length_mm": round(seg.length_mm, 3),
                "is_main": seg.is_main,
            }
            for seg in layout.runner_segments
        ]

        payload: dict[str, Any] = {
            "ok": True,
            "n_cavities": layout.n_cavities,
            "sprue_position": [round(v, 4) for v in layout.sprue_position],
            "runner_segments": segments_out,
            "diameters": {k: round(v, 3) for k, v in layout.diameters.items()},
            "balance_score": layout.balance_score,
            "naturally_balanced": layout.naturally_balanced,
            "artificial_balance_required": layout.artificial_balance_required,
            "pressure_drop_estimate": layout.pressure_drop_estimate,
            "warnings": layout.warnings,
            "reference": "Beaumont 2007 §6.5; Menges 2001 §6",
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "RUNNER_LAYOUT_ERROR")
