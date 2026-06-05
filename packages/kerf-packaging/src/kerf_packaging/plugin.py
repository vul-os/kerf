"""
kerf-packaging plugin registration.

Wires the dieline LLM tools into a Kerf plugin app.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""
    provides: list[str] = []
    _register_tools(ctx, provides)

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "packaging",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="packaging",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all packaging LLM tools into ctx.tools."""
    from kerf_packaging.tools import (
        packaging_dieline_generate_spec,
        run_packaging_dieline_generate,
        packaging_dieline_to_dxf_spec,
        run_packaging_dieline_to_dxf,
        packaging_fold_preview_spec,
        run_packaging_fold_preview,
        packaging_bct_estimate_spec,
        run_packaging_bct_estimate,
        packaging_prepress_check_spec,
        run_packaging_prepress_check,
        packaging_prepress_gen_marks_spec,
        run_packaging_prepress_gen_marks,
        packaging_prepress_export_pdf_x1a_spec,
        run_packaging_prepress_export_pdf_x1a,
        packaging_material_yield_spec,
        run_packaging_material_yield,
    )

    tool_entries = [
        (packaging_dieline_generate_spec, run_packaging_dieline_generate,
         "packaging.dieline-generate"),
        (packaging_dieline_to_dxf_spec, run_packaging_dieline_to_dxf,
         "packaging.dieline-to-dxf"),
        (packaging_fold_preview_spec, run_packaging_fold_preview,
         "packaging.fold-preview"),
        (packaging_bct_estimate_spec, run_packaging_bct_estimate,
         "packaging.bct-estimate"),
        # Pre-press / graphics integration (ISO 15930-1 PDF/X-1a + ISO 12647-2)
        (packaging_prepress_check_spec, run_packaging_prepress_check,
         "packaging.prepress-check"),
        (packaging_prepress_gen_marks_spec, run_packaging_prepress_gen_marks,
         "packaging.prepress-gen-marks"),
        (packaging_prepress_export_pdf_x1a_spec, run_packaging_prepress_export_pdf_x1a,
         "packaging.prepress-export-pdf-x1a"),
        # Material yield + cost estimation (PMMI handbook §7)
        (packaging_material_yield_spec, run_packaging_material_yield,
         "packaging.material-yield"),
    ]

    for spec, handler, capability in tool_entries:
        try:
            if hasattr(ctx, "tools") and hasattr(ctx.tools, "register"):
                ctx.tools.register(spec.name, spec, handler)
            provides.append(capability)
        except Exception as exc:
            logger.warning("kerf-packaging: failed to register %s: %s", spec.name, exc)
