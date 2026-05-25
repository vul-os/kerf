"""kerf-aero plugin entry-point.

Pure-library plugin today (aerodynamics, propulsion, orbital mechanics).
HTTP routes for aero are mounted by the kerf-api plugin which imports
kerf_aero submodules directly. This plugin only declares its presence so
the loader records `kerf-aero` in the manifest.
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    # Register LLM tools from the aerospace_tools module
    from kerf_aero.llm_tools.aerospace_tools import AEROSPACE_TOOLS
    import asyncio
    import json

    for tool_entry in AEROSPACE_TOOLS:
        fn = tool_entry["fn"]
        tool_name = tool_entry["name"]
        tool_desc = tool_entry["description"]

        # Build a minimal async handler that unpacks args and calls the sync fn
        def _make_handler(sync_fn):
            async def handler(args: dict, _ctx) -> str:
                try:
                    result = sync_fn(**args)
                    return json.dumps(result)
                except (ValueError, TypeError) as exc:
                    return json.dumps({"error": str(exc), "code": "BAD_ARGS"})
                except Exception as exc:
                    return json.dumps({"error": str(exc), "code": "ERROR"})
            return handler

        spec = {
            "name": tool_name,
            "description": tool_desc,
            "input_schema": {"type": "object", "properties": {}},
        }
        ctx.tools.register(tool_name, spec, _make_handler(fn))

    provides = [
        "aero.aerodynamics",
        "aero.propulsion",
        "aero.orbital",
        "aero.orbit_determination",
    ]

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="aero",
            version="0.1.0",
            provides=provides,
            depends=[],
        )
    except ImportError:
        return {
            "name": "aero",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }
