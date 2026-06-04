"""
kerf-dental plugin entry-point.

Registers:
  - LLM tools: dental_crown_design, dental_surgical_guide, dental_dicom_ingest,
    dental_denture_design, dental_stl_export, dental_register_scans,
    dental_deviation_map, dental_implant_metrics, dental_recommend_implant
"""

from __future__ import annotations

from fastapi import FastAPI

# Check for optional pydicom
_PYDICOM_AVAILABLE = False
try:
    import pydicom  # noqa: F401
    _PYDICOM_AVAILABLE = True
except ImportError:
    pass


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_dental.tools import (
        dental_crown_design_spec, run_dental_crown_design,
        dental_surgical_guide_spec, run_dental_surgical_guide,
        dental_dicom_ingest_spec, run_dental_dicom_ingest,
        dental_denture_design_spec, run_dental_denture_design,
        dental_stl_export_spec, run_dental_stl_export,
        dental_register_scans_spec, run_dental_register_scans,
        dental_deviation_map_spec, run_dental_deviation_map,
        dental_implant_metrics_spec, run_dental_implant_metrics,
        dental_recommend_implant_spec, run_dental_recommend_implant,
        # Wave 11B: dental depth (3shape parity)
        dental_crown_bridge_design_spec, run_dental_crown_bridge_design,
        dental_implant_plan_v2_spec, run_dental_implant_plan_v2,
        dental_lab_case_report_spec, run_dental_lab_case_report,
    )
    ctx.tools.register("dental_crown_design", dental_crown_design_spec, run_dental_crown_design)
    ctx.tools.register("dental_surgical_guide", dental_surgical_guide_spec, run_dental_surgical_guide)
    ctx.tools.register("dental_dicom_ingest", dental_dicom_ingest_spec, run_dental_dicom_ingest)
    ctx.tools.register("dental_denture_design", dental_denture_design_spec, run_dental_denture_design)
    ctx.tools.register("dental_stl_export", dental_stl_export_spec, run_dental_stl_export)
    ctx.tools.register("dental_register_scans", dental_register_scans_spec, run_dental_register_scans)
    ctx.tools.register("dental_deviation_map", dental_deviation_map_spec, run_dental_deviation_map)
    ctx.tools.register("dental_implant_metrics", dental_implant_metrics_spec, run_dental_implant_metrics)
    ctx.tools.register("dental_recommend_implant", dental_recommend_implant_spec, run_dental_recommend_implant)
    # Wave 11B: dental depth (3shape parity)
    ctx.tools.register("dental_crown_bridge_design", dental_crown_bridge_design_spec, run_dental_crown_bridge_design)
    ctx.tools.register("dental_implant_plan_v2", dental_implant_plan_v2_spec, run_dental_implant_plan_v2)
    ctx.tools.register("dental_lab_case_report", dental_lab_case_report_spec, run_dental_lab_case_report)

    provides = ["dental.crown", "dental.guide", "dental.denture", "dental.stl",
                "dental.registration", "dental.deviation", "dental.implant_planning",
                # Wave 11B
                "dental.crown_bridge", "dental.implant_plan_v2", "dental.surgical_guide",
                "dental.denture_v2", "dental.intraoral_scan", "dental.lab_workflow",
                "dental.ai_automation"]
    if _PYDICOM_AVAILABLE:
        provides.append("dental.dicom")

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="dental",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "dental",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
