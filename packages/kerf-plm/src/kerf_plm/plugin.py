"""
kerf-plm plugin entry-point.

Registers:
  - LLM tool  plm_configure  (via ctx.tools.register)
"""

from __future__ import annotations

from fastapi import FastAPI


async def register(app: FastAPI, ctx):
    """Plugin entry-point — called by the kerf-core plugin loader at startup."""

    from kerf_plm.tools import plm_configure_spec, run_plm_configure
    ctx.tools.register("plm_configure", plm_configure_spec, run_plm_configure)

    from kerf_plm.tools import plm_change_management_spec, plm_change_management as _plm_cm

    async def _run_plm_change_management(ctx, args: bytes) -> str:
        import json as _json
        try:
            a = _json.loads(args)
        except Exception as e:
            from kerf_plm._compat import err_payload
            return err_payload(f"invalid args: {e}", "BAD_ARGS")
        result = _plm_cm(**a)
        import json as _json2
        return _json2.dumps(result)

    ctx.tools.register("plm_change_management", plm_change_management_spec, _run_plm_change_management)

    try:
        from kerf_core.plugin import PluginManifest
        return PluginManifest(
            name="plm",
            version="0.1.0",
            provides=["plm.configurator", "plm.effectivity-bom", "plm.change-management"],
            depends=[],
        )
    except ImportError:
        return {
            "name": "plm",
            "version": "0.1.0",
            "provides": ["plm.configurator", "plm.effectivity-bom", "plm.change-management"],
            "depends": [],
        }
