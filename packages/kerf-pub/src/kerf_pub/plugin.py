"""kerf-pub plugin entry point — DMTAP-PUB public-object HTTP endpoint + local
pin store.

This is an OSS-node plugin: it mounts the §22.5.1 public-object endpoints
UNCONDITIONALLY — there is no flag or billing tier gating it. kerf's hosted
PUB server is "one server among equals" (§23 Appendix A); serving public
objects is core to the decentralized Workshop, not a paid feature.

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
        local_mode = True


async def register(app, ctx) -> "PluginManifest":
    """Mount the DMTAP-PUB public-object router and wire the local pin store.

    Store backend selection:
      * a persistent :class:`~kerf_pub.store.PostgresPubStore` when a DB pool is
        present (hosted PUB server);
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
    logger.info("kerf-pub: DMTAP-PUB public-object endpoint + node-local /api/pub/* mounted (store backend=%s)", backend)

    return PluginManifest(
        name="pub",
        version="0.1.0",
        # NOTE: "pub.gateway" keeps its historical spelling — an internal plugin
        # capability token, not the §22.5.1 wire or a public API — left as-is
        # rather than risk an undiscovered external consumer over a rename with
        # no user-visible benefit (see the §0.8 gateway/PUB-server terminology
        # split this module's docstring now follows).
        provides=["pub.gateway", "pub.blob-store", "pub.author-feeds", "pub.local-api"],
        depends=["core"],
    )
