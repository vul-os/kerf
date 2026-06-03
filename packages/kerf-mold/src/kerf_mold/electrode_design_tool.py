"""
kerf_mold.electrode_design_tool — LLM tool wrapper for EDM electrode design.

Tool: mold_design_edm_electrode
  Design an EDM sinker electrode by offsetting a target cavity face inward by
  spark_gap_mm and estimating process parameters from Hassan-Boothroyd 1989.

References:
  Hassan, A., Boothroyd, G. (1989). *Fundamentals of Machining and Machine
    Tools*, 2nd ed., §14 Table 14.3–14.4.
  Kalpakjian, S., Schmid, S. (2014). §27.
  VDI 3402 (1976).

Wave 9C: Cimatron mold base + EDM electrode + wire EDM
"""
from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.electrode_design import (
    EdmElectrodeSpec,
    EdmElectrodeReport,
    design_edm_electrode,
    FINISH_CLASS_MRR_MM3_PER_MIN,
    ELECTRODE_WEAR_RATIO,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_design_edm_electrode_spec = ToolSpec(
    name="mold_design_edm_electrode",
    description=(
        "Design an EDM sinker electrode for a cavity face: offset the face by "
        "spark_gap_mm, estimate burning time from Hassan-Boothroyd MRR table, "
        "and recommend current/voltage settings for the selected finish class.\n\n"
        "Finish classes (VDI 3402):\n"
        "  F0 — rough    (Ra 10–20 µm, MRR 2000 mm³/min, 30 A / 60 V)\n"
        "  F1 — semi-fin (Ra 5–10 µm,  MRR  400 mm³/min, 15 A / 50 V)\n"
        "  F2 — fine     (Ra 1–5 µm,   MRR   80 mm³/min,  5 A / 45 V) ← typical mold\n"
        "  F3 — super-fine (Ra < 1 µm, MRR   10 mm³/min, 1.5 A / 40 V)\n\n"
        "Electrode materials supported:\n"
        "  graphite_POCO_EDM-3 (wear ratio 0.02) | graphite_standard (0.05)\n"
        "  copper (0.10) | copper_tungsten (0.08)\n\n"
        "Geometry: offset area approximated as (√A − 2·gap)² for convex faces.\n"
        "Burning time: Volume / MRR where Volume = area × assumed_depth (10 mm default).\n\n"
        "Returns: {ok, electrode_geometry, cross_section_area_mm2, cavity_volume_mm3, "
        "estimated_burning_time_min, recommended_current_a, recommended_voltage_v, "
        "electrode_wear_ratio, finish_class, spark_gap_mm, honest_caveat}.\n\n"
        "HONEST: Geometry is planar approximation; real 3-D requires B-rep offset. "
        "Burning time ±50 % depending on machine and flushing conditions.\n\n"
        "Refs: Hassan-Boothroyd 1989 §14; Kalpakjian 2014 §27; VDI 3402."
    ),
    input_schema={
        "type": "object",
        "required": ["cross_section_area_mm2"],
        "properties": {
            "cross_section_area_mm2": {
                "type": "number",
                "description": (
                    "Projected cross-section area of the cavity face / electrode "
                    "projected onto the parting plane (mm²). Must be > 0."
                ),
                "exclusiveMinimum": 0,
            },
            "spark_gap_mm": {
                "type": "number",
                "description": (
                    "One-sided EDM spark gap (mm). Default 0.05 mm (F2 fine finish). "
                    "Typical range: 0.02–0.15 mm (Hassan-Boothroyd 1989 §14.2)."
                ),
                "default": 0.05,
                "minimum": 0,
            },
            "finish_class": {
                "type": "string",
                "enum": ["F0", "F1", "F2", "F3"],
                "description": "VDI 3402 finish class. Default 'F2' (fine, typical mold cavity).",
                "default": "F2",
            },
            "polarity": {
                "type": "string",
                "enum": ["positive", "negative"],
                "description": "Electrode polarity. Default 'positive' (electrode +, workpiece -).",
                "default": "positive",
            },
            "material": {
                "type": "string",
                "enum": [
                    "graphite_POCO_EDM-3",
                    "graphite_standard",
                    "copper",
                    "copper_tungsten",
                ],
                "description": "Electrode material. Default 'graphite_POCO_EDM-3'.",
                "default": "graphite_POCO_EDM-3",
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_design_edm_electrode(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute EDM electrode design and return a JSON string."""
    try:
        area = args.get("cross_section_area_mm2")
        if area is None:
            return err_payload("cross_section_area_mm2 is required", "BAD_ARGS")
        try:
            area = float(area)
        except (TypeError, ValueError) as exc:
            return err_payload(f"cross_section_area_mm2 must be a number: {exc}", "BAD_ARGS")

        spark_gap = float(args.get("spark_gap_mm", 0.05))
        finish_class = str(args.get("finish_class", "F2"))
        polarity = str(args.get("polarity", "positive"))
        material = str(args.get("material", "graphite_POCO_EDM-3"))

        spec = EdmElectrodeSpec(
            target_face_geometry=None,
            spark_gap_mm=spark_gap,
            finish_class=finish_class,
            polarity=polarity,
            material=material,
            cross_section_area_mm2_hint=area,
        )

        report: EdmElectrodeReport = design_edm_electrode(spec)

        return ok_payload({
            "ok": True,
            "electrode_geometry": report.electrode_geometry,
            "cross_section_area_mm2": report.cross_section_area_mm2,
            "cavity_volume_mm3": report.cavity_volume_mm3,
            "estimated_burning_time_min": report.estimated_burning_time_min,
            "recommended_current_a": report.recommended_current_a,
            "recommended_voltage_v": report.recommended_voltage_v,
            "electrode_wear_ratio": report.electrode_wear_ratio,
            "finish_class": report.finish_class,
            "spark_gap_mm": report.spark_gap_mm,
            "honest_caveat": report.honest_caveat,
            "reference": (
                "Hassan, A., Boothroyd, G. (1989). Fundamentals of Machining and Machine Tools, "
                "2nd ed., §14 Table 14.3–14.4. "
                "Kalpakjian, S., Schmid, S. (2014). Manufacturing Engineering and Technology, §27. "
                "VDI 3402 (1976)."
            ),
        })

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "EDM_ELECTRODE_ERROR")
