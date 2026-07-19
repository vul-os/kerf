"""kerf-cloud plugin entry-point.

Per the 2026-07-17 decentralization ADRs, hosted git serving, GitHub/GitLab
OAuth sync, transactional email, and the centralized Workshop have all been
retired (hosted git -> packages/kerf-api's local git API; Workshop ->
packages/kerf-pub's DMTAP-PUB feeds). What remains here is distributor
sync (Mouser/DigiKey/LCSC/McMaster) — a node feature (self-hosters supply
their own distributor API credentials), plus a handful of unrelated
production-ops features (job traveler, share links, CRDT collab seed, PLM).

Distributor sync mounts unconditionally on every node — there is no
"cloud edition" to gate it behind. Its only real requirement is a DB pool
(distributor credentials live in the ``distributor_credentials`` table,
encrypted at rest); a node with zero distributor credentials configured
simply runs the registry with everything disabled, exactly like a node
with zero GitHub remotes configured still runs its git panel.

The unwired CRDT collab seed (``kerf_cloud.collab`` — ``YMap``/``YArray``/
``YDoc``/``PresenceChannel``, no network layer, never mounted on any router)
was pruned 2026-07-19. Real-time multi-author sync for kerf is planned via the
shared substrate Sync spec (``dmtap/substrate/SYNC.md``) with proper
bindings, not a per-product hand-rolled engine — see docs/architecture.md
future-work.
"""
from __future__ import annotations

from fastapi import FastAPI

from kerf_core.plugin import PluginManifest

PLUGIN_DEPENDS = ["kerf-auth", "kerf-api"]


async def register(app: FastAPI, ctx) -> PluginManifest:
    # -------------------------------------------------------------------------
    # Distributor registry (needs encrypted creds + DB — its only actual
    # requirement). No pool means no distributor_credentials table to read;
    # every other node capability here is unconditional.
    # -------------------------------------------------------------------------
    if ctx.pool is not None:
        await _init_distributor_registry(ctx)
        provides = ["cloud.distributors"]
    else:
        ctx.logger.info("kerf-cloud: no DB pool — distributor registry dormant")
        provides = []

    return PluginManifest(
        name="kerf-cloud",
        version="0.1.0",
        provides=provides,
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
