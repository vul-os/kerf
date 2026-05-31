"""
kerf_mold.runner_balance_check_tool — LLM tool wrapper for runner balance check.

Tool: mold_check_runner_balance
  Verify whether a multi-cavity runner network is naturally balanced
  (equal hydraulic resistance from sprue to every gate).

References:
  Beaumont, J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed., §6.6.
  Menges, G., Michaeli, W., Mohren, P. (2001). *How to Make Injection Molds*,
    3rd ed., §6.6.4.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.runner_balance_check import RunnerSegment, check_runner_balance


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_runner_balance_check_spec = ToolSpec(
    name="mold_check_runner_balance",
    description=(
        "Verify whether a multi-cavity cold-runner network is *naturally balanced* "
        "(Beaumont 2007 §6.6; Menges 2001 §6.6.4).\n\n"
        "Computes the normalised Hagen-Poiseuille hydraulic resistance "
        "R = L / r⁴  (viscosity μ cancels in ratios) along every path from "
        "the sprue to each cavity gate, then reports the maximum imbalance:\n\n"
        "    max_imbalance_pct = 100 × (R_max − R_min) / R_mean\n\n"
        "A network is *balanced* when max_imbalance_pct < 5 %.\n\n"
        "Inputs:\n"
        "  segments — list of runner segments; each has "
        "  {id, length_mm, diameter_mm, parent_id}. "
        "  Exactly one segment must have parent_id=null (the sprue root).\n"
        "  cavity_gate_ids — list of segment ids that are the final gates "
        "  into each cavity.\n\n"
        "Returns: {ok, cavity_paths[{cavity_id, total_length_mm, "
        "total_resistance, fill_ratio}], max_imbalance_pct, balanced, "
        "honest_caveat, reference}.\n\n"
        "Honest caveat: geometric resistance only — does NOT model "
        "temperature-dependent viscosity, shear-thinning, or shear-heating "
        "asymmetry. Use Moldflow / Moldex3D / SigmaSoft for full rheological "
        "fill simulation."
    ),
    input_schema={
        "type": "object",
        "required": ["segments", "cavity_gate_ids"],
        "properties": {
            "segments": {
                "type": "array",
                "description": (
                    "All runner segments in the network. Each segment: "
                    "{id (str), length_mm (float > 0), diameter_mm (float > 0), "
                    "parent_id (str|null)}. "
                    "Exactly one segment must have parent_id=null (the sprue)."
                ),
                "items": {
                    "type": "object",
                    "required": ["id", "length_mm", "diameter_mm"],
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Unique segment identifier.",
                        },
                        "length_mm": {
                            "type": "number",
                            "description": "Segment length [mm]. Must be > 0.",
                            "exclusiveMinimum": 0,
                        },
                        "diameter_mm": {
                            "type": "number",
                            "description": "Bore diameter [mm]. Must be > 0.",
                            "exclusiveMinimum": 0,
                        },
                        "parent_id": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "null"},
                            ],
                            "description": (
                                "id of the upstream parent segment. "
                                "null for the sprue (root)."
                            ),
                        },
                    },
                },
                "minItems": 1,
            },
            "cavity_gate_ids": {
                "type": "array",
                "description": (
                    "List of segment ids that feed directly into cavities "
                    "(the terminal gate segments). One per cavity."
                ),
                "items": {"type": "string"},
                "minItems": 1,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_check_runner_balance(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute the runner balance check and return a JSON string."""
    try:
        raw_segments = args.get("segments")
        cavity_gate_ids = args.get("cavity_gate_ids")

        if not raw_segments:
            return err_payload("segments must be a non-empty list", "BAD_ARGS")
        if not cavity_gate_ids:
            return err_payload("cavity_gate_ids must be a non-empty list", "BAD_ARGS")
        if not isinstance(raw_segments, list):
            return err_payload("segments must be a list", "BAD_ARGS")
        if not isinstance(cavity_gate_ids, list):
            return err_payload("cavity_gate_ids must be a list", "BAD_ARGS")

        # Parse segments
        segments: list[RunnerSegment] = []
        for i, rs in enumerate(raw_segments):
            try:
                seg = RunnerSegment(
                    id=str(rs["id"]),
                    length_mm=float(rs["length_mm"]),
                    diameter_mm=float(rs["diameter_mm"]),
                    parent_id=rs.get("parent_id"),  # None if absent or null
                )
            except KeyError as exc:
                return err_payload(
                    f"segments[{i}]: missing field {exc}", "BAD_ARGS"
                )
            except (TypeError, ValueError) as exc:
                return err_payload(
                    f"segments[{i}]: invalid value — {exc}", "BAD_ARGS"
                )
            segments.append(seg)

        # Coerce gate ids to strings
        try:
            cavity_gate_ids = [str(g) for g in cavity_gate_ids]
        except Exception as exc:
            return err_payload(f"cavity_gate_ids: {exc}", "BAD_ARGS")

        report = check_runner_balance(
            segments=segments,
            cavity_gate_ids=cavity_gate_ids,
        )

        payload: dict[str, Any] = {
            "ok": True,
            "cavity_paths": report.cavity_paths,
            "max_imbalance_pct": report.max_imbalance_pct,
            "balanced": report.balanced,
            "honest_caveat": report.honest_caveat,
            "reference": "Beaumont 2007 §6.6; Menges 2001 §6.6.4",
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "RUNNER_BALANCE_ERROR")
