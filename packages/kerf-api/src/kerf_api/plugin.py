"""kerf-api plugin entry-point.

Registers /api/* routes and LLM tools for file ops, object ops, scaffolding,
revisions, configurations, equations, validation, PCB layers, project layers,
and materials.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from kerf_core.plugin import PluginManifest

logger = logging.getLogger(__name__)

PLUGIN_DEPENDS = ["kerf-auth"]


def _try_include(app: FastAPI, module_path: str, *, prefix: str = "/api", tags: list[str] | None = None) -> bool:
    """Import a routes_* module and include its router; swallow ImportError.

    Several kerf-api sub-routers depend on optional plugin packages that may
    not be present in every persona (e.g. routes_aero_orbit imports kerf_aero).
    Without this wrapper, ONE missing optional dep would cause the entire
    kerf-api plugin's register() to raise — the upstream loader catches that
    as plugin_register_failed and silently 404s every kerf-api route (the
    bug discovered on dev 2026-05-29). Per-router try/except keeps the rest
    of the surface up and logs the gap.
    """
    import importlib
    try:
        mod = importlib.import_module(module_path)
        app.include_router(mod.router, prefix=prefix, tags=tags or [])
        return True
    except Exception as exc:
        logger.warning("kerf-api: skip %s (%s: %s)", module_path, type(exc).__name__, exc)
        return False


async def register(app: FastAPI, ctx) -> PluginManifest:
    # Main API router (always required — if this raises we WANT to fail loud).
    from kerf_api.routes import router
    app.include_router(router, prefix="/api", tags=["api"])

    # All other sub-routers are optional — wrapped so missing deps degrade.
    _try_include(app, "kerf_api.routes_git_diff",        tags=["git-diff"])
    _try_include(app, "kerf_api.routes_atopile",  prefix="",                  tags=["atopile"])
    _try_include(app, "kerf_api.routes_plc_sim",         tags=["plc-sim"])
    _try_include(app, "kerf_api.routes_aero_propulsion", tags=["aero"])
    _try_include(app, "kerf_api.routes_aero_atmosphere", tags=["aero"])
    _try_include(app, "kerf_api.routes_aero_airfoil",    tags=["aero"])
    _try_include(app, "kerf_api.routes_aero_orbit",      tags=["aero"])
    _try_include(app, "kerf_api.routes_silicon_synth",   tags=["silicon"])
    _try_include(app, "kerf_api.routes_silicon",         tags=["silicon"])
    _try_include(app, "kerf_api.routes_composites",      tags=["composites"])
    _try_include(app, "kerf_api.routes_ota",             tags=["ota"])
    # T-408: break-even margin admin endpoint
    _try_include(app, "kerf_api.routes_admin_margin",    tags=["admin"])
    # POST /api/tools/call — frontend dispatch of any registered LLM tool
    # (used by LadderEditor Import/Export and any future UI-wired tool).
    _try_include(app, "kerf_api.routes_tools",           tags=["tools"])
    # GPU worker enrollment + BYO dispatch. routes_workers.py declares short
    # paths (/enroll, /heartbeat, ...) so the prefix MUST include /workers.
    _try_include(app, "kerf_api.routes_workers", prefix="/api/workers", tags=["gpu-workers"])

    _register_tools(ctx)

    ctx.logger.info("kerf-api: registered /api routes and LLM tools")

    return PluginManifest(
        name="kerf-api",
        version="0.1.0",
        provides=["api.rest", "files.crud", "projects.crud"],
        depends=["kerf-auth"],
    )


def _register_tools(ctx) -> None:
    """Register all kerf-api LLM tools into ctx.tools."""

    tool_modules = [
        "kerf_api.tools.file_ops",
        "kerf_api.tools.object_ops",
        "kerf_api.tools.scaffold",
        "kerf_api.tools.revisions",
        "kerf_api.tools.configurations",
        "kerf_api.tools.equations",
        "kerf_api.tools.validation",
        "kerf_api.tools.project_layers",
        "kerf_api.tools.material",
    ]

    import importlib

    for module_path in tool_modules:
        try:
            mod = importlib.import_module(module_path)
            # Each module registers its tools via the @register decorator into
            # the legacy registry when imported.  We also expose them to the
            # plugin tool registry by iterating the module's _compat registry
            # OR by importing the spec/handler pairs directly.
            _register_module_tools(ctx, mod, module_path)
        except Exception as exc:
            logger.warning("kerf-api: failed to load %s: %s", module_path, exc)


def _register_module_tools(ctx, mod, module_path: str) -> None:
    """Register all (spec, handler) pairs from a tool module into ctx.tools."""

    # Build a mapping of handler_fn -> spec from the module's @register calls.
    # Since the tools use the try/except compat shim, on import the @register
    # decorator may have fired into either the legacy tools.registry.Registry
    # list or the kerf_api._compat._registry list.  We walk the module's
    # attributes to find (spec_var, handler_var) pairs by name convention.
    registered = 0
    attrs = dir(mod)
    # Find all *_spec variables that have a `.name` attribute (ToolSpec-like).
    spec_vars = {
        name[:-5]: getattr(mod, name)
        for name in attrs
        if name.endswith("_spec") and hasattr(getattr(mod, name), "name")
    }
    for base_name, spec in spec_vars.items():
        handler_name = f"run_{base_name}"
        handler = getattr(mod, handler_name, None)
        if handler is None:
            logger.warning("kerf-api: %s has spec %s_spec but no run_%s handler",
                           module_path, base_name, base_name)
            continue
        tool_name = spec.name
        try:
            ctx.tools.register(tool_name, spec, handler)
            registered += 1
        except ValueError as exc:
            # Already registered (e.g. duplicate across modules) — skip.
            logger.debug("kerf-api: skipping duplicate tool '%s': %s", tool_name, exc)

    if registered:
        logger.debug("kerf-api: registered %d tool(s) from %s", registered, module_path)
