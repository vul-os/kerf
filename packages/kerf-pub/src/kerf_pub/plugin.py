"""kerf-pub plugin entry point — DMTAP-PUB gateway + local pin store.

This is an OSS-node plugin: it mounts the §22.5.1 gateway endpoints
UNCONDITIONALLY (never behind ``cloud_enabled`` / billing). kerf's hosted
gateway is "one gateway among equals" (§23 Appendix A); serving public objects
is core to the decentralized Workshop, not a paid feature.

Entry-point (pyproject.toml):
    [project.entry-points."kerf.plugins"]
    pub = "kerf_pub.plugin:register"
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── kerf_core plugin contract (shared across plugin packages) ─────────────────
try:
    from kerf_core.plugin import PluginContext, PluginManifest  # type: ignore
    _KERF_CORE_AVAILABLE = True
except ImportError:
    _KERF_CORE_AVAILABLE = False

    class PluginManifest:  # type: ignore[no-redef]
        def __init__(self, *, name: str, version: str, provides: list, depends: list):
            self.name = name
            self.version = version
            self.provides = provides
            self.depends = depends

    class PluginContext:  # type: ignore[no-redef]
        pool = None
        cloud_enabled = False
        local_mode = True


async def register(app, ctx) -> "PluginManifest":
    """Mount the DMTAP-PUB gateway router and wire the local pin store.

    Store backend selection:
      * a persistent :class:`~kerf_pub.store.PostgresPubStore` when a DB pool is
        present (hosted gateway);
      * an :class:`~kerf_pub.store.InMemoryPubStore` otherwise (dev / zero-DB).
    """
    from kerf_pub.router import router
    from kerf_pub.router_local import router as local_router
    from kerf_pub.store import InMemoryPubStore, PostgresPubStore

    pool = getattr(ctx, "pool", None)
    if pool is not None:
        store = PostgresPubStore(pool)
        backend = "postgres"
    else:
        store = InMemoryPubStore()
        backend = "in-memory"

    app.state.pub_store = store
    app.include_router(router)
    app.include_router(local_router, prefix="/api")
    logger.info("kerf-pub: DMTAP-PUB gateway + node-local /api/pub/* mounted (store backend=%s)", backend)

    return PluginManifest(
        name="pub",
        version="0.1.0",
        provides=["pub.gateway", "pub.blob-store", "pub.author-feeds", "pub.local-api"],
        depends=["core"],
    )
