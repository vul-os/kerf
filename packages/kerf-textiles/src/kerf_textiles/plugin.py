"""
kerf-textiles plugin entry-point.

Registers:
  - FastAPI router  POST /weave  POST /knit
  - LLM tool        textiles_generate  (via ctx.tools.register)

All generators are pure Python — no optional heavy dependencies.
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""
    from kerf_textiles.routes import router
    app.include_router(router)

    from kerf_textiles.tools import textiles_generate_spec, run_textiles_generate
    ctx.tools.register("textiles_generate", textiles_generate_spec, run_textiles_generate)

    from kerf_textiles.tools import textiles_cloth_drape_spec, run_textiles_cloth_drape
    ctx.tools.register("textiles_cloth_drape", textiles_cloth_drape_spec, run_textiles_cloth_drape)

    from kerf_textiles.tools import textiles_cut_room_spec, run_textiles_cut_room
    ctx.tools.register("textiles_cut_room", textiles_cut_room_spec, run_textiles_cut_room)

    from kerf_textiles.tools import textiles_etextiles_spec, run_textiles_etextiles
    ctx.tools.register("textiles_etextiles", textiles_etextiles_spec, run_textiles_etextiles)

    from kerf_textiles.tools import textiles_sustainability_spec, run_textiles_sustainability
    ctx.tools.register("textiles_sustainability",
                       textiles_sustainability_spec, run_textiles_sustainability)

    from kerf_textiles.tools import textiles_pattern_grade_spec, run_textiles_pattern_grade
    ctx.tools.register("textiles_pattern_grade",
                       textiles_pattern_grade_spec, run_textiles_pattern_grade)

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="textiles",
            version="0.1.0",
            provides=[
                "textiles.weave", "textiles.knit", "textiles.draft", "textiles.drape",
                "textiles.cut_room", "textiles.etextiles", "textiles.sustainability",
                "textiles.pattern_grade",
            ],
            depends=[],
        )
    except ImportError:
        return {
            "name": "textiles",
            "version": "0.1.0",
            "provides": [
                "textiles.weave", "textiles.knit", "textiles.draft", "textiles.drape",
                "textiles.cut_room", "textiles.etextiles", "textiles.sustainability",
                "textiles.pattern_grade",
            ],
            "depends": [],
        }
