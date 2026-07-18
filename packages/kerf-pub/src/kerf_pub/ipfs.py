"""IPFS gateway fetch-adapter — a SECOND chunk-bytes source behind the fetch
verb, never a source of truth.

ADR posture (kept honest, not just asserted): DMTAP-PUB objects are
self-verifying by construction (§22.2, §22.5.1) — a holder is "a convenience,
never a trust root." IPFS is just one more untrusted holder a kerf-pub node
MAY ask for chunk bytes, addressed via the CID a chunk hash already implies
(:mod:`kerf_pub.cid`). It is consulted strictly AFTER every configured kerf
gateway (§22.5.1 ``/.well-known/dmtap-pub/chunk/{h}``) has failed to serve a
valid chunk, and every byte it returns is re-verified against ``h_i`` before
acceptance (§22.2.2) exactly like a byte from any other holder — a corrupt or
malicious IPFS gateway can waste bandwidth, never poison the store.

**Chunk-bytes only.** ``PubManifest`` / ``PubAnnounce`` / ``FeedEntry`` /
``FeedHead`` are deterministic integer-keyed CBOR (§18.1.2), not IPLD DAG
nodes — there is no IPFS-side representation of a kerf-object to fetch, so
this adapter is never consulted for them. Fetching those remains exclusively
the kerf gateway HTTP profile (§22.5.1) and local mesh (§22.5.2).

**Config.** ``ipfs_gateway_url`` is a per-node setting, absent by default
(zero-socket: a node with no IPFS gateway configured never touches this
module). It follows the same env-var / data-dir convention as
:func:`kerf_pub.identity.default_key_path` — no config file, no DB row,
just an environment variable a node operator sets once:

    KERF_PUB_IPFS_GATEWAY_URL=https://ipfs.io   (or a local go-ipfs daemon,
                                                   e.g. http://127.0.0.1:8080)
"""

from __future__ import annotations

import asyncio
import os
import urllib.request

from .cid import cid_for_chunk

ENV_IPFS_GATEWAY_URL = "KERF_PUB_IPFS_GATEWAY_URL"


def default_ipfs_gateway_url() -> str | None:
    """The per-node IPFS gateway base URL, or ``None`` if unconfigured
    (zero-socket default — no IPFS fetch adapter is built)."""
    url = os.environ.get(ENV_IPFS_GATEWAY_URL, "").strip()
    return url or None


class IPFSGatewayFetcher:
    """Fetches one kerf-pub chunk's bytes from an IPFS HTTP gateway.

    ``GET {ipfs_gateway_url}/ipfs/{cid}`` where ``cid`` is the CIDv1
    (raw codec, base32 multibase) derived from the chunk hash
    (:func:`kerf_pub.cid.cid_for_chunk`). Returns the raw response bytes
    UNVERIFIED — the caller (:class:`kerf_pub.client.PubClient`) MUST run
    :func:`kerf_pub.hashing.verify_chunk` before persisting or using them,
    the same discipline applied to every other holder.
    """

    def __init__(self, ipfs_gateway_url: str):
        if not ipfs_gateway_url:
            raise ValueError("ipfs_gateway_url must be non-empty")
        self.ipfs_gateway_url = ipfs_gateway_url.rstrip("/")

    async def fetch_chunk(self, h: bytes) -> bytes | None:
        cid = cid_for_chunk(h)
        url = f"{self.ipfs_gateway_url}/ipfs/{cid}"
        try:
            return await asyncio.to_thread(self._http_get, url)
        except Exception:
            return None

    @staticmethod
    def _http_get(url: str) -> bytes | None:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            if resp.status != 200:
                return None
            return resp.read()
