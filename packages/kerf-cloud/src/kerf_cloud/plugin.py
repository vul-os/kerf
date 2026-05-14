"""kerf-cloud plugin entry-point.

Cloud-gated: when ctx.cloud_enabled is False, returns an empty manifest and
no routes are mounted.
"""
from __future__ import annotations

from fastapi import FastAPI

from kerf_core.plugin import PluginManifest

PLUGIN_DEPENDS = ["kerf-auth", "kerf-api"]


async def register(app: FastAPI, ctx) -> PluginManifest:
    if not ctx.cloud_enabled:
        ctx.logger.info("kerf-cloud: cloud_enabled=False — plugin dormant")
        return PluginManifest(
            name="kerf-cloud",
            version="0.1.0",
            provides=[],
            depends=["kerf-auth", "kerf-api"],
        )

    from kerf_cloud.routes import router, github_oauth_router
    app.include_router(router, prefix="/api", tags=["cloud"])
    app.include_router(github_oauth_router, prefix="/auth", tags=["github-oauth"])

    ctx.logger.info("kerf-cloud: registered /api/projects/*/git/* and /auth/github/* routes")

    # -------------------------------------------------------------------------
    # Distributor registry — cloud-only (needs encrypted creds + DB)
    # -------------------------------------------------------------------------
    if not ctx.local_mode:
        await _init_distributor_registry(ctx)

    return PluginManifest(
        name="kerf-cloud",
        version="0.1.0",
        provides=["cloud.workshop", "cloud.git", "cloud.distributors"],
        depends=["kerf-auth", "kerf-api"],
    )


async def _init_distributor_registry(ctx) -> None:
    """Create the distributor Registry, reload credentials from DB, wire it
    into kerf-api's module-level getter, and register the background sweep."""
    try:
        from kerf_cloud.distributors.registry import Registry, set_registry
        from kerf_cloud.distributors.sync import start_sweep
        from kerf_api.routes import set_registry as api_set_registry

        # Pass fx=None initially; LCSC will skip CNY→USD conversion until
        # an FX service is wired in later (non-blocking for other distributors).
        reg = Registry(pool=ctx.pool, cfg=ctx.config, fx=None)
        await reg.reload()

        # Publish registry to both locations so both the cloud distributor
        # routes (via registry.get_registry()) and the kerf-api routes
        # (via routes.get_registry()) resolve the same object.
        set_registry(reg)
        api_set_registry(reg)

        # Register the sweep as a background worker so ctx.workers.start_all()
        # picks it up at app startup.
        async def _sweep_factory():
            return start_sweep(ctx.pool, reg)

        ctx.workers.register("distributors.sweep", _sweep_factory)

        ctx.logger.info("kerf-cloud: distributor registry loaded", providers=reg.enabled_names())
    except Exception as exc:  # never crash the whole plugin for distributor init failure
        ctx.logger.warning("kerf-cloud: distributor registry init failed", error=str(exc))
