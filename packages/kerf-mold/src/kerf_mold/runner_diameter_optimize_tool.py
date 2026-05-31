"""
kerf_mold.runner_diameter_optimize_tool
=========================================
LLM tool wrapper for the Beaumont §6.5 runner-diameter optimiser.

Registers:
  mold_optimize_runner_diameter — recommend optimal cold-runner diameter D
      for a given part weight W and polymer grade, balancing fill pressure
      against cold-runner waste.

      Formula: D = (W^0.25 × √L) / 3.7  (Beaumont 2007 §6.5)

      Material adjustments: ABS +10%, PC +15%, PP -5%, PA66 ±0%.

Errors returned as {"ok": false, "code": "...", "reason": "..."} — never
raises.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §6.5 (Optimal runner diameter).
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.5 (Runner design).
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.runner_diameter_optimize import (
    RunnerOptimizeSpec,
    optimize_runner_diameter,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_optimize_runner_diameter_spec = ToolSpec(
    name="mold_optimize_runner_diameter",
    description=(
        "Recommend the optimal cold-runner diameter for a single-gate "
        "injection-mold runner segment using the Beaumont (2007) §6.5 "
        "empirical formula:\n\n"
        "    D [mm] = (W^0.25 × √L) / 3.7\n\n"
        "where W = part weight [g] and L = runner length [mm].  "
        "A material-viscosity adjustment is applied per Beaumont §6.5 "
        "+ Menges 2001 §6.5:\n"
        "  ABS  → +10%  (moderate viscosity)\n"
        "  PC   → +15%  (highly viscous; largest runner)\n"
        "  PP   → -5%   (low viscosity; smaller runner)\n"
        "  PA66 → ±0%   (close to ABS baseline)\n"
        "  other → ±0%  (no adjustment)\n\n"
        "Also returns:\n"
        "  - cold_runner_waste_g: cylindrical runner mass at polymer density\n"
        "  - fill_pressure_estimate_MPa: Hagen-Poiseuille proxy "
        "P≈K_mat·L/D^4 (order-of-magnitude only)\n\n"
        "SINGLE RUNNER SEGMENT ONLY — does not optimise filling balance "
        "in multi-cavity molds; use mold_check_runner_balance + "
        "mold_generate_runner_layout for multi-cavity networks.\n\n"
        "Returns: {ok, recommended_diameter_mm, beaumont_diameter_mm, "
        "cold_runner_waste_g, fill_pressure_estimate_MPa, "
        "polymer_specific_adjustment, honest_caveat}.\n\n"
        "Honest caveat: empirical formula only (not a full Hele-Shaw / "
        "Cross-WLF rheological simulation); fill-pressure proxy is "
        "order-of-magnitude; multi-cavity filling balance NOT modelled."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "part_weight_g": {
                "type": "number",
                "description": (
                    "Part (shot) weight in grams.  Must be > 0.  "
                    "Typical injection-molded parts: 5–500 g."
                ),
            },
            "runner_length_mm": {
                "type": "number",
                "description": (
                    "Runner segment length from sprue to cavity gate entry "
                    "[mm].  Must be > 0.  Typical cold runners: 50–300 mm."
                ),
            },
            "polymer_grade": {
                "type": "string",
                "description": (
                    "Polymer grade string (case-insensitive).  Recognised "
                    "grades with material-specific adjustments: "
                    "'ABS' (+10%), 'PC' (+15%), 'PP' (-5%), 'PA66' (±0%).  "
                    "Unknown grades receive ±0% adjustment."
                ),
            },
            "gate_count": {
                "type": "integer",
                "description": (
                    "Number of gates per cavity (default 1).  For multi-gate "
                    "parts, effective per-gate shot weight = "
                    "part_weight_g / gate_count."
                ),
                "minimum": 1,
            },
        },
        "required": ["part_weight_g", "runner_length_mm", "polymer_grade"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_optimize_runner_diameter(
    ctx: "ProjectCtx",
    args: bytes,
) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # --- part_weight_g ---
    raw_w = a.get("part_weight_g")
    if raw_w is None:
        return err_payload("part_weight_g is required", "BAD_ARGS")
    try:
        part_weight_g = float(raw_w)
    except (TypeError, ValueError) as exc:
        return err_payload(f"part_weight_g: {exc}", "BAD_ARGS")

    # --- runner_length_mm ---
    raw_l = a.get("runner_length_mm")
    if raw_l is None:
        return err_payload("runner_length_mm is required", "BAD_ARGS")
    try:
        runner_length_mm = float(raw_l)
    except (TypeError, ValueError) as exc:
        return err_payload(f"runner_length_mm: {exc}", "BAD_ARGS")

    # --- polymer_grade ---
    raw_poly = a.get("polymer_grade")
    if raw_poly is None:
        return err_payload("polymer_grade is required", "BAD_ARGS")
    polymer_grade = str(raw_poly)

    # --- gate_count (optional, default 1) ---
    raw_gc = a.get("gate_count", 1)
    try:
        gate_count = int(raw_gc)
    except (TypeError, ValueError) as exc:
        return err_payload(f"gate_count: {exc}", "BAD_ARGS")

    try:
        spec = RunnerOptimizeSpec(
            part_weight_g=part_weight_g,
            runner_length_mm=runner_length_mm,
            polymer_grade=polymer_grade,
            gate_count=gate_count,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    try:
        report = optimize_runner_diameter(spec)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "OP_FAILED")

    return ok_payload({
        "ok": True,
        "recommended_diameter_mm": report.recommended_diameter_mm,
        "beaumont_diameter_mm": report.beaumont_diameter_mm,
        "cold_runner_waste_g": report.cold_runner_waste_g,
        "fill_pressure_estimate_MPa": report.fill_pressure_estimate_MPa,
        "polymer_specific_adjustment": report.polymer_specific_adjustment,
        "honest_caveat": report.honest_caveat,
    })
