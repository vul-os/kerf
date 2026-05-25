"""
kerf-plc plugin registration.

Wires the PLC lint route and LLM tools into a Kerf plugin app.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""
    # ── HTTP routes ──────────────────────────────────────────────────────────
    from kerf_plc.routes import router as plc_router
    app.include_router(plc_router, tags=["plc"])

    # ── LLM tools ────────────────────────────────────────────────────────────
    provides = []
    _register_tools(ctx, provides)

    # plc.lint is always declared — the route gracefully degrades when
    # MATIEC isn't installed.
    if "plc.lint" not in provides:
        provides.append("plc.lint")

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "plc",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="plc",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all PLC LLM tools into ctx.tools."""
    try:
        from kerf_plc.tools.run_plc_lint import run_plc_lint_spec, run_plc_lint
        ctx.tools.register("run_plc_lint", run_plc_lint_spec, run_plc_lint)
        provides.append("plc.lint")
    except Exception as exc:
        logger.warning("kerf-plc: failed to load run_plc_lint tool: %s", exc)

    try:
        from kerf_plc.tools.create_ladder_rung import create_ladder_rung_spec, create_ladder_rung
        ctx.tools.register("create_ladder_rung", create_ladder_rung_spec, create_ladder_rung)
        provides.append("plc.ld")
    except Exception as exc:
        logger.warning("kerf-plc: failed to load create_ladder_rung tool: %s", exc)

    # make_ladder_program — synthesise a full LD program from a natural-language spec
    try:
        from kerf_plc.tools.make_ladder_program import make_ladder_program_spec, make_ladder_program_tool
        ctx.tools.register("make_ladder_program", make_ladder_program_spec, make_ladder_program_tool)
        provides.append("plc.make_ladder")
    except Exception as exc:
        logger.warning("kerf-plc: failed to load make_ladder_program tool: %s", exc)

    # convert_st_to_ladder / convert_ladder_to_st — bidirectional ST ↔ LD transpiler
    try:
        from kerf_plc.tools.transpile_plc import (
            convert_st_to_ladder_spec,
            convert_st_to_ladder_tool,
            convert_ladder_to_st_spec,
            convert_ladder_to_st_tool,
        )
        ctx.tools.register("convert_st_to_ladder", convert_st_to_ladder_spec, convert_st_to_ladder_tool)
        ctx.tools.register("convert_ladder_to_st", convert_ladder_to_st_spec, convert_ladder_to_st_tool)
        provides.append("plc.transpile")
    except Exception as exc:
        logger.warning("kerf-plc: failed to load transpile_plc tools: %s", exc)
