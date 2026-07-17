"""The four-verb DMTAP-PUB client: publish / fetch / resolve / submit.

**Zero-socket invariant.** A client constructed with no ``gateways`` NEVER
opens a socket: ``publish`` and ``resolve`` operate on the local store, and
``fetch`` returns bytes assembled from local pins. A network call is attempted
ONLY when at least one gateway is configured AND the object is not local
(§22.5.1 gateway HTTP profile). ``submit`` (compute) is a stub (§22.5, compute
is out of scope for v1).

All verification is client-side and total (§22.5.1): every object is
re-addressed and every signature re-checked against the bytes, so a gateway is
a convenience, never a trust root.
"""

from __future__ import annotations

import asyncio
import base64
import time
import urllib.request
from typing import Iterable

from .errors import (
    PubError,
    ERR_PUB_FEED_ROLLBACK,
    ERR_PUB_FEED_CHAIN_BROKEN,
    ERR_PUB_FEED_SIG_INVALID,
    ERR_PUB_MANIFEST_HASH_MISMATCH,
    ERR_PUB_CHUNK_HASH_MISMATCH,
    ERR_PUB_NOT_SERVED,
)
from .hashing import verify_chunk
from .objects import (
    PubManifest,
    PubAnnounce,
    FeedEntry,
    FeedHead,
    ArtifactMetadata,
    embed_artifact,
)
from .store import PubStore, InMemoryPubStore


def _now_ms() -> int:
    return int(time.time() * 1000)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def check_fork(a: FeedEntry, b: FeedEntry) -> None:
    """Two distinct entries at one seq (equivocation) → CHAIN_BROKEN (§22.4.2)."""
    if a.seq == b.seq and a.id != b.id:
        raise PubError(
            ERR_PUB_FEED_CHAIN_BROKEN,
            f"fork: two entries at seq {a.seq} (a publisher cannot present two histories)",
        )


class PubClient:
    def __init__(self, store: PubStore | None = None, identity=None,
                 gateways: Iterable[str] | None = None):
        self.store = store if store is not None else InMemoryPubStore()
        self.identity = identity
        self.gateways = list(gateways) if gateways else []

    @property
    def online(self) -> bool:
        return bool(self.gateways)

    # ── verb 1: publish ────────────────────────────────────────────────────────
    async def publish(self, files: dict[str, bytes],
                      artifact_metadata: ArtifactMetadata | None = None) -> bytes:
        """Build manifests over ``files`` (label -> plaintext bytes), sign a
        pub_announce embedding ``artifact_metadata``, append to our own feed, and
        pin everything locally. Returns the ``announce_id`` (§22.7 publish act)."""
        if self.identity is None:
            raise ValueError("publish requires a local identity")
        roots: list[bytes] = []
        for data in files.values():
            manifest = PubManifest.build(data)
            await self.store.put_manifest(manifest.id, manifest.to_cbor())
            plainchunks = PubManifest.split_chunks(data, manifest.chunk_sz)
            for h, chunk in zip(manifest.chunks, plainchunks):
                await self.store.put_chunk(h, chunk)
            roots.append(manifest.id)

        meta: dict = {}
        if artifact_metadata is not None:
            artifact_metadata.validate()  # §23.10 CAD-* profile MUSTs
            meta = embed_artifact(meta, artifact_metadata)

        announce = PubAnnounce(
            pub=self.identity.pub, roots=roots, ts=_now_ms(), meta=meta,
        ).sign(self.identity)
        aid = announce.id
        await self.store.put_announce(aid, announce.to_cbor())
        await self.store.set_pinned(aid, True)
        await self._append_own_feed(aid)
        return aid

    async def _append_own_feed(self, aid: bytes) -> None:
        pub = self.identity.pub
        head_raw = await self.store.get_feed_head(pub)
        if head_raw is None:
            seq, prev = 0, None
        else:
            head = FeedHead.from_cbor(head_raw)
            seq, prev = head.seq + 1, head.tip
        entry = FeedEntry(seq=seq, announce=aid, ts=_now_ms(), prev=prev)
        entry.check_shape()
        await self.store.put_feed_entry(pub, seq, entry.id, entry.to_cbor())
        new_head = FeedHead(pub=pub, seq=seq, tip=entry.id, ts=_now_ms()).sign(self.identity)
        await self.store.put_feed_head(pub, new_head.to_cbor())
        await self.store.set_accepted_seq(pub, seq)

    # ── verb 2: fetch ──────────────────────────────────────────────────────────
    async def fetch(self, content_address: bytes) -> bytes:
        """Fetch and reassemble a public blob by its manifest root, verifying the
        manifest self-address and every chunk against its ``h_i`` (§22.2)."""
        manifest_raw = await self._get_manifest(content_address)
        manifest = PubManifest.from_cbor(manifest_raw)
        manifest.verify()  # DS-tagged Merkle root == id
        if manifest.id != content_address:
            raise PubError(ERR_PUB_MANIFEST_HASH_MISMATCH, "manifest id != fetched address")
        out = bytearray()
        for h in manifest.chunks:
            chunk = await self._get_chunk(h)
            if chunk is None or not verify_chunk(h, chunk):
                # ROTATE_RETRY in the swarm; here (single source) it is fatal.
                raise PubError(ERR_PUB_CHUNK_HASH_MISMATCH, "chunk failed self-verify")
            out += chunk
        return bytes(out)

    async def _get_manifest(self, mid: bytes) -> bytes:
        raw = await self.store.get_manifest(mid)
        if raw is None and self.online:
            raw = await self._gateway_get(f"manifest/{_b64url(mid)}")
        if raw is None:
            raise PubError(ERR_PUB_NOT_SERVED, "manifest not pinned and no gateway served it")
        return raw

    async def _get_chunk(self, h: bytes) -> bytes | None:
        chunk = await self.store.get_chunk(h)
        if chunk is None and self.online:
            chunk = await self._gateway_get(f"chunk/{_b64url(h)}")
        return chunk

    # ── verb 3: resolve ────────────────────────────────────────────────────────
    async def resolve(self, pub_key: bytes) -> list[FeedEntry]:
        """Resolve an author feed: verified head + full chain, with anti-rollback
        (§22.4.2) applied against the local watermark. Returns entries ascending.

        Zero-socket: if no head is known locally and no gateway is configured,
        returns [] (nothing published/pinned here for that author)."""
        head_raw = await self.store.get_feed_head(pub_key)
        if head_raw is None and self.online:
            head_raw = await self._gateway_get(f"feed/{_b64url(pub_key)}/head")
        if head_raw is None:
            return []
        head = FeedHead.from_cbor(head_raw)
        head.verify()
        if head.pub != pub_key:
            raise PubError(ERR_PUB_FEED_SIG_INVALID, "head.pub != requested author")

        accepted = await self.store.get_accepted_seq(pub_key)
        if accepted is not None and head.seq < accepted:
            # A stale head cannot suppress announcements already accepted (§22.4.2).
            raise PubError(
                ERR_PUB_FEED_ROLLBACK,
                f"head seq {head.seq} < accepted {accepted}",
            )

        entries = await self._walk_and_verify(pub_key, head)

        if accepted is None or head.seq > accepted:
            await self.store.set_accepted_seq(pub_key, head.seq)
        return entries

    async def _walk_and_verify(self, pub_key: bytes, head: FeedHead) -> list[FeedEntry]:
        """Walk seq head.seq → 0, checking the prev hash-chain up to the signed
        tip (§22.4.3). Returns entries ascending by seq."""
        by_seq: dict[int, FeedEntry] = {}
        for raw in await self._get_feed_range(pub_key, 0, head.seq):
            e = FeedEntry.from_cbor(raw)
            by_seq[e.seq] = e

        tip = by_seq.get(head.seq)
        if tip is None or tip.id != head.tip:
            raise PubError(ERR_PUB_FEED_CHAIN_BROKEN, "tip entry missing or != head.tip")

        for s in range(head.seq, 0, -1):
            cur = by_seq.get(s)
            prev = by_seq.get(s - 1)
            if cur is None or prev is None:
                raise PubError(ERR_PUB_FEED_CHAIN_BROKEN, f"gap at seq {s}")
            if cur.prev != prev.id:
                raise PubError(
                    ERR_PUB_FEED_CHAIN_BROKEN,
                    f"prev at seq {s} does not resolve to seq {s - 1}",
                )
        return [by_seq[s] for s in range(0, head.seq + 1)]

    async def _get_feed_range(self, pub_key: bytes, from_seq: int,
                              to_seq: int) -> list[bytes]:
        rows = await self.store.get_feed_range(pub_key, from_seq, to_seq)
        if not rows and self.online:
            raw = await self._gateway_get(
                f"feed/{_b64url(pub_key)}/range?from={from_seq}&to={to_seq}")
            # gateway returns a CBOR array of entries; caller re-decodes per entry.
            from . import cbor
            arr = cbor.decode(raw) if raw else []
            rows = [cbor.encode(x) for x in arr]
        return rows

    # ── verb 4: submit (compute — out of scope for v1) ─────────────────────────
    async def submit(self, job) -> None:
        raise NotImplementedError(
            "DMTAP-PUB compute/submit is not part of v1 (public storage + feeds "
            "only); a compute-job profile lands later, layered like §23 on §22."
        )

    # ── gateway HTTP (only reached when self.online) ───────────────────────────
    async def _gateway_get(self, path: str) -> bytes | None:
        for base in self.gateways:
            url = f"{base.rstrip('/')}/.well-known/dmtap-pub/{path}"
            try:
                raw = await asyncio.to_thread(self._http_get, url)
            except Exception:
                continue
            if raw is not None:
                return raw
        return None

    @staticmethod
    def _http_get(url: str) -> bytes | None:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            if resp.status != 200:
                return None
            return resp.read()
