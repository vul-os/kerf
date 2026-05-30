"""
kerf-gdnt plugin entry-point.

Registers:
  - LLM tools for GD&T symbol lookup, FCF creation, inspection, and reporting
    (via ctx.tools.register)

No heavy optional dependencies — kerf-gdnt is pure Python.
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_gdnt.tools import (
        gdnt_list_symbols_spec, run_gdnt_list_symbols,
        gdnt_create_fcf_spec, run_gdnt_create_fcf,
        gdnt_validate_fcf_spec, run_gdnt_validate_fcf,
        gdnt_inspect_feature_spec, run_gdnt_inspect_feature,
        gdnt_build_report_spec, run_gdnt_build_report,
        gdt_validate_frame_spec, run_gdt_validate_frame,
        gdt_parse_frame_spec, run_gdt_parse_frame,
        gdt_validate_datum_reference_frame_spec,
        run_gdt_validate_datum_reference_frame,
        gdt_validate_composite_tolerance_frame_spec,
        run_gdt_validate_composite_tolerance_frame,
    )

    ctx.tools.register("gdnt_list_symbols", gdnt_list_symbols_spec, run_gdnt_list_symbols)
    ctx.tools.register("gdnt_create_fcf", gdnt_create_fcf_spec, run_gdnt_create_fcf)
    ctx.tools.register("gdnt_validate_fcf", gdnt_validate_fcf_spec, run_gdnt_validate_fcf)
    ctx.tools.register("gdnt_inspect_feature", gdnt_inspect_feature_spec, run_gdnt_inspect_feature)
    ctx.tools.register("gdnt_build_report", gdnt_build_report_spec, run_gdnt_build_report)
    ctx.tools.register("gdt_validate_frame", gdt_validate_frame_spec, run_gdt_validate_frame)
    ctx.tools.register("gdt_parse_frame", gdt_parse_frame_spec, run_gdt_parse_frame)
    ctx.tools.register(
        "gdt_validate_datum_reference_frame",
        gdt_validate_datum_reference_frame_spec,
        run_gdt_validate_datum_reference_frame,
    )
    try:
        ctx.tools.register(
            "gdt_validate_composite_tolerance_frame",
            gdt_validate_composite_tolerance_frame_spec,
            run_gdt_validate_composite_tolerance_frame,
        )
    except Exception:
        pass

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="gdnt",
            version="0.1.0",
            provides=[
                "gdnt.fcf", "gdnt.inspection", "gdnt.homologation",
                "gdnt.drf_validation", "gdnt.composite_tolerance",
            ],
            depends=[],
        )
    except ImportError:
        return {
            "name": "gdnt",
            "version": "0.1.0",
            "provides": [
                "gdnt.fcf", "gdnt.inspection", "gdnt.homologation",
                "gdnt.drf_validation", "gdnt.composite_tolerance",
            ],
            "depends": [],
        }
