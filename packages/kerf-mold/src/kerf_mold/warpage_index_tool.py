"""
kerf_mold.warpage_index_tool — LLM tool wrapper for warpage-index computation.

Tool: mold_compute_warpage_index
  Given a part shape description (wall thickness uniformity, gate location,
  polymer grade, post-ejection cooling time, mold temperature), compute a
  heuristic warpage index (0–100) and flag high-risk regions.

References:
  Beaumont J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed., §10
    (Warpage Analysis — root-cause diagnostics).
  Menges G., Michaeli W., Mohren P. (2001). *How to Make Injection Molds*,
    3rd ed., §8 (Post-mold shrinkage and warpage).
"""

from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.warpage_index import (
    WarpageSpec,
    compute_warpage_index,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_compute_warpage_index_spec = ToolSpec(
    name="mold_compute_warpage_index",
    description=(
        "Compute a heuristic warpage-risk index (0–100) for an injection-moulded "
        "part, and identify which factor contributes most to the predicted warpage.\n\n"
        "0 = essentially flat (ideal conditions); 100 = severe warpage expected.\n\n"
        "Risk thresholds (Beaumont 2007 §10.1):\n"
        "  0–24   → low    (acceptable; minor tool adjustment may be needed)\n"
        "  25–49  → medium (elevated; design or process change recommended)\n"
        "  50–74  → high   (significant; likely visible warpage in production)\n"
        "  75–100 → severe (near-certain reject; major redesign required)\n\n"
        "Scoring model (Beaumont 2007 §10 + Menges 2001 §8):\n"
        "  Wall-thickness uniformity  → up to 30 pts\n"
        "  Gate location              → up to 25 pts\n"
        "  Polymer grade              → up to 20 pts\n"
        "  Post-ejection cooling time → up to 15 pts\n"
        "  Mold temperature deviation → up to 10 pts\n\n"
        "Wall uniformity (Beaumont 2007 §10.2):\n"
        "  100 % = perfectly uniform; 80 % = ±25 % variation (acceptable);\n"
        "  50 % = thickest wall ≈ 2× thinnest (elevated risk).\n\n"
        "Gate location (Beaumont 2007 §10.3):\n"
        "  'centered' — near-symmetric fill; minimum residual-stress gradient\n"
        "  'edge'     — strong flow directionality; moderate differential\n"
        "  'corner'   — severe fill asymmetry; high residual-stress differential\n"
        "  'unbalanced' — multiple gates with unequal flow lengths; highest risk\n\n"
        "Polymer grade (Menges 2001 §8.3 Table 8.2):\n"
        "  Low-risk amorphous: PC, ABS, PMMA, PS, ABS-PC\n"
        "  Medium-risk semi-cryst.: PP, PA66, PA6, POM, HDPE, PET\n"
        "  High-risk glass-filled/LCP: GF-PA66, GF-PP, GF-PA6, GF-PBT, LCP\n\n"
        "Post-ejection cooling time (Beaumont 2007 §10.5):\n"
        "  ≥ 60 s recommended for semi-cryst./glass-filled grades;\n"
        "  ≥ 30 s for amorphous; < 10 s → high warpage risk on ejection surface.\n\n"
        "Mold temperature (Menges 2001 §8.6):\n"
        "  Each polymer has a recommended range; deviation increases warpage.\n\n"
        "Returns: {warpage_index, risk_level, primary_warp_driver,\n"
        "          mitigation_suggestions, sub_scores, honest_caveat}.\n\n"
        "HONEST CAVEAT: heuristic screening tool only — NOT a FEM simulation. "
        "Real warpage prediction requires Moldflow, Moldex3D, or SigmaSoft. "
        "Orientation-dependent shrinkage tensors, part geometry, packing pressure, "
        "injection speed, hold time, and residual-stress relaxation are NOT modelled. "
        "Accuracy: ±15 index points is typical. Use to flag high-risk designs early; "
        "validate with FEM before production tooling commit."
    ),
    input_schema={
        "type": "object",
        "required": [
            "wall_thickness_uniformity_pct",
            "gate_location",
            "polymer_grade",
            "post_eject_cooling_time_s",
            "mold_temp_C",
        ],
        "properties": {
            "wall_thickness_uniformity_pct": {
                "type": "number",
                "description": (
                    "Wall-thickness uniformity [0–100 %]. "
                    "100 = all walls exactly the same thickness (perfectly uniform). "
                    "50 = the thickest wall is approximately twice the thinnest. "
                    "Rule-of-thumb: keep variation within ±25 % of nominal "
                    "(uniformity_pct ≥ 80 %) to minimise differential cooling "
                    "(Beaumont 2007 §10.2). Must be in [0, 100]."
                ),
                "minimum": 0,
                "maximum": 100,
            },
            "gate_location": {
                "type": "string",
                "description": (
                    "Qualitative gate-location category. One of:\n"
                    "'centered'   — gate at/near geometric centroid of cavity area; "
                    "minimum warpage risk.\n"
                    "'edge'       — gate at one edge (most common side-gated tools).\n"
                    "'corner'     — gate at a corner or extremity; severe fill asymmetry.\n"
                    "'unbalanced' — multiple gates with unequal flow lengths, or highly "
                    "eccentric single gate; highest risk."
                ),
                "enum": ["centered", "edge", "corner", "unbalanced"],
            },
            "polymer_grade": {
                "type": "string",
                "description": (
                    "Polymer material grade. Supported values (case-insensitive):\n"
                    "Amorphous (low risk): PC, ABS, PMMA, PS, ABS-PC\n"
                    "Semi-crystalline (medium risk): PP, PA66, PA6, POM, HDPE, PET\n"
                    "Glass-filled / LCP (high risk): GF-PA66, GF-PP, GF-PA6, GF-PBT, LCP\n"
                    "Unknown grades receive a medium fallback score with a warning caveat."
                ),
            },
            "post_eject_cooling_time_s": {
                "type": "number",
                "description": (
                    "Time [seconds] between part ejection and placement on a flat cool "
                    "surface (or fixture). Longer times allow the part to stabilise "
                    "dimensionally before any constraint force is applied. Must be ≥ 0. "
                    "Typical targets: ≥ 60 s for semi-cryst./glass-filled; "
                    "≥ 30 s for amorphous (Beaumont 2007 §10.5)."
                ),
                "minimum": 0,
            },
            "mold_temp_C": {
                "type": "number",
                "description": (
                    "Mold (coolant) temperature [°C]. Must be ≥ 0. "
                    "Deviating from the polymer-specific recommended range increases "
                    "warpage risk. Typical ranges: PC 70–120 °C, ABS 40–80 °C, "
                    "PP 20–80 °C, PA66 70–120 °C, POM 60–120 °C "
                    "(Menges 2001 §5.4 Table 5.3)."
                ),
                "minimum": 0,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Async handler
# ---------------------------------------------------------------------------

async def run_mold_compute_warpage_index(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute warpage index computation and return a JSON string."""
    try:
        wall_uniformity = args.get("wall_thickness_uniformity_pct")
        gate_location = args.get("gate_location")
        polymer_grade = args.get("polymer_grade")
        cooling_time = args.get("post_eject_cooling_time_s")
        mold_temp = args.get("mold_temp_C")

        # Validate required args
        if wall_uniformity is None:
            return err_payload("wall_thickness_uniformity_pct is required", "BAD_ARGS")
        if gate_location is None:
            return err_payload("gate_location is required", "BAD_ARGS")
        if polymer_grade is None:
            return err_payload("polymer_grade is required", "BAD_ARGS")
        if cooling_time is None:
            return err_payload("post_eject_cooling_time_s is required", "BAD_ARGS")
        if mold_temp is None:
            return err_payload("mold_temp_C is required", "BAD_ARGS")

        try:
            wall_uniformity = float(wall_uniformity)
        except (TypeError, ValueError):
            return err_payload(
                f"wall_thickness_uniformity_pct must be a number, got {wall_uniformity!r}",
                "BAD_ARGS",
            )
        try:
            cooling_time = float(cooling_time)
        except (TypeError, ValueError):
            return err_payload(
                f"post_eject_cooling_time_s must be a number, got {cooling_time!r}",
                "BAD_ARGS",
            )
        try:
            mold_temp = float(mold_temp)
        except (TypeError, ValueError):
            return err_payload(
                f"mold_temp_C must be a number, got {mold_temp!r}",
                "BAD_ARGS",
            )

        spec = WarpageSpec(
            wall_thickness_uniformity_pct=wall_uniformity,
            gate_location=str(gate_location),
            polymer_grade=str(polymer_grade),
            post_eject_cooling_time_s=cooling_time,
            mold_temp_C=mold_temp,
        )

        report = compute_warpage_index(spec)

        payload: dict[str, Any] = {
            "ok": True,
            "warpage_index": report.warpage_index,
            "risk_level": report.risk_level,
            "primary_warp_driver": report.primary_warp_driver,
            "mitigation_suggestions": report.mitigation_suggestions,
            "sub_scores": report.sub_scores,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "Beaumont J.P. Runner and Gating Design Handbook, 2nd ed., "
                "Hanser 2007, §10 (Warpage Analysis); "
                "Menges G., Michaeli W., Mohren P. How to Make Injection Molds, "
                "3rd ed., Hanser 2001, §8 (Post-mold shrinkage and warpage)."
            ),
        }
        return ok_payload(payload)

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "WARPAGE_INDEX_ERROR")
