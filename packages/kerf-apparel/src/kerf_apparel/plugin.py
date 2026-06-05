"""
kerf-apparel plugin entry-point.

Registers:
  - LLM tools:  apparel_grade_bodice, apparel_add_seam, apparel_make_marker,
                apparel_generate_block, apparel_flatten_pattern,
                apparel_apply_grading, apparel_grade_check,
                garment_avatar_body_form

No heavy optional dependencies are required; the plugin always loads.
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_apparel.tools import (
        grade_bodice_spec, run_grade_bodice,
        add_seam_spec, run_add_seam,
        make_marker_spec, run_make_marker,
        generate_block_spec, run_generate_block,
        flatten_pattern_spec, run_flatten_pattern,
        apply_grading_spec, run_apply_grading,
        grade_check_spec, run_grade_check,
        avatar_body_form_spec, run_avatar_body_form,
    )
    ctx.tools.register("apparel_grade_bodice", grade_bodice_spec, run_grade_bodice)
    ctx.tools.register("apparel_add_seam", add_seam_spec, run_add_seam)
    ctx.tools.register("apparel_make_marker", make_marker_spec, run_make_marker)
    ctx.tools.register("apparel_generate_block", generate_block_spec, run_generate_block)
    ctx.tools.register("apparel_flatten_pattern", flatten_pattern_spec, run_flatten_pattern)
    ctx.tools.register("apparel_apply_grading", apply_grading_spec, run_apply_grading)
    ctx.tools.register("apparel_grade_check", grade_check_spec, run_grade_check)
    ctx.tools.register("garment_avatar_body_form", avatar_body_form_spec, run_avatar_body_form)

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="apparel",
            version="0.1.0",
            provides=[
                "apparel.blocks", "apparel.seam", "apparel.grading",
                "apparel.marker", "apparel.generate_block",
                "apparel.pattern_flatten",
                "apparel.apply_grading", "apparel.grade_check",
                "apparel.avatar_body_form",
            ],
            depends=[],
        )
    except ImportError:
        return {
            "name": "apparel",
            "version": "0.1.0",
            "provides": [
                "apparel.blocks", "apparel.seam", "apparel.grading",
                "apparel.marker", "apparel.generate_block",
                "apparel.pattern_flatten",
                "apparel.apply_grading", "apparel.grade_check",
                "apparel.avatar_body_form",
            ],
            "depends": [],
        }
