"""
kerf-systems plugin entry-point.

Registers:
  - LLM tools: systems_run, systems_parse  (via ctx.tools.register)

File kind: 'system' (added to kind check in 0001_core_identity.sql and FILE_KINDS)
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by kerf-core plugin loader at startup."""

    from kerf_systems.tools import (
        systems_run_spec, run_systems_run,
        systems_parse_spec, run_systems_parse,
    )
    ctx.tools.register("systems_run", systems_run_spec, run_systems_run)
    ctx.tools.register("systems_parse", systems_parse_spec, run_systems_parse)

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="systems",
            version="0.1.0",
            provides=["systems.dae", "systems.modelica-parser", "systems.component-library"],
            depends=[],
        )
    except ImportError:
        return {
            "name": "systems",
            "version": "0.1.0",
            "provides": ["systems.dae", "systems.modelica-parser", "systems.component-library"],
            "depends": [],
        }
