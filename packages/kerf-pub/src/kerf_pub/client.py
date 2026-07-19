"""The four-verb DMTAP-PUB client: publish / fetch / resolve / submit — plus
pin hydration, the swarm-fetch machinery that makes a Pin durable.

**Zero-socket invariant.** A client constructed with no ``gateways`` NEVER
opens a socket: ``publish`` and ``resolve`` operate on the local store, and
``fetch`` returns bytes assembled from local pins. A network call is attempted
ONLY when at least one gateway is configured AND the object is not local
(§22.5.1 gateway HTTP profile). ``submit`` (compute) is a stub (§22.5, compute
is out of scope for v1). :meth:`PubClient.hydrate_pin` extends the same
invariant to pinning: it raises rather than silently reporting success when
an announce is neither local nor reachable through any configured gateway.

All verification is client-side and total (§22.5.1): every object is
re-addressed and every signature re-checked against the bytes, so a gateway is
a convenience, never a trust root. Chunk bytes fetched through the IPFS
fetch-adapter (:mod:`kerf_pub.ipfs`) go through the exact same
``verify_chunk`` gate as bytes from a kerf gateway (§22.2.2) — see
:meth:`PubClient._fetch_chunk_verified`.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
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
from .ipfs import IPFSGatewayFetcher
from .objects import (
    PubManifest,
    PubAnnounce,
    FeedEntry,
    FeedHead,
    ArtifactMetadata,
    embed_artifact,
)
from .store import PubStore, InMemoryPubStore

# Modest, deterministic concurrency for swarm chunk fetches (§22.5.3): high
# enough to overlap network latency, low enough to keep test runs and gateway
# load predictable — not a tuned production constant.
DEFAULT_HYDRATE_CONCURRENCY = 4


def _now_ms() -> int:
    return int(time.time() * 1000)


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


@dataclasses.dataclass
class HydrationResult:
    """Outcome of :meth:`PubClient.hydrate_pin` (pin durability, §22.5.3).

    ``pinned`` — the announce itself was resolved, verified, and recorded;
    NOT the same as "fully local" (see ``hydrated``).
    ``hydrated`` — every manifest the announce names, and every chunk each
    of those manifests lists, was fetched and self-verified and is now in
    the local store. Only when this is True does availability read
    ``on-node`` (§22.6).
    ``missing_chunks`` — count of chunks that could not be verified from any
    reachable source (local store, configured kerf gateways, then the IPFS
    fetch-adapter if configured). Zero iff ``hydrated`` is True.
    ``error`` — a human-readable summary when ``hydrated`` is False; absent
    on full success.
    """

    pinned: bool
    hydrated: bool
    missing_chunks: int = 0
    error: str | None = None


def check_fork(a: FeedEntry, b: FeedEntry) -> None:
    """Two distinct entries at one seq (equivocation) → CHAIN_BROKEN (§22.4.2)."""
    if a.seq == b.seq and a.id != b.id:
        raise PubError(
            ERR_PUB_FEED_CHAIN_BROKEN,
            f"fork: two entries at seq {a.seq} (a publisher cannot present two histories)",
        )


def check_head_watermark(accepted_seq: int | None, accepted_tip: bytes | None,
                         presented_seq: int, presented_tip: bytes) -> None:
    """Apply the §22.4.2 anti-rollback rule to a presented ``FeedHead``.

    Three outcomes, and the distinction between the last two matters:

    * ``presented_seq < accepted_seq`` — a stale head cannot suppress
      announcements already accepted → ``ERR_PUB_FEED_ROLLBACK`` (0x0907),
      FAIL_CLOSED_BLOCK.
    * ``presented_seq == accepted_seq`` with the SAME tip — an idempotent
      re-fetch of a cacheable head. Equal seq is NOT a rollback; accept.
    * ``presented_seq == accepted_seq`` with a DIFFERENT tip — the author
      presented two histories at one position. That is equivocation, not
      staleness, and is deliberately NOT reported as 0x0907: it is
      ``ERR_PUB_FEED_CHAIN_BROKEN`` (0x0908), HALT_ALERT.
    """
    if accepted_seq is None:
        return
    if presented_seq < accepted_seq:
        raise PubError(
            ERR_PUB_FEED_ROLLBACK,
            f"head seq {presented_seq} < accepted {accepted_seq}",
        )
    if (presented_seq == accepted_seq and accepted_tip is not None
            and presented_tip != accepted_tip):
        raise PubError(
            ERR_PUB_FEED_CHAIN_BROKEN,
            f"fork: two distinct tips at seq {presented_seq} "
            "(a publisher cannot present two histories)",
        )


class PubClient:
    def __init__(self, store: PubStore | None = None, identity=None,
                 gateways: Iterable[str] | None = None,
                 ipfs_gateway_url: str | None = None):
        self.store = store if store is not None else InMemoryPubStore()
        self.identity = identity
        self.gateways = list(gateways) if gateways else []
        # IPFS fetch-adapter (§22.5.3 second chunk source): per-node, absent
        # by default (zero-socket) — see kerf_pub.ipfs for the ADR posture.
        self.ipfs_fetcher = (
            IPFSGatewayFetcher(ipfs_gateway_url) if ipfs_gateway_url else None
        )

    @property
    def online(self) -> bool:
        """True iff at least one kerf gateway (§22.5.1) is configured. Does
        NOT count the IPFS fetch-adapter — IPFS never serves announces or
        manifests (kerf-object formats aren't IPLD, see kerf_pub.ipfs), so it
        can never make announce/manifest resolution "online" on its own."""
        return bool(self.gateways)

    @property
    def chunk_fetch_capable(self) -> bool:
        """True iff there is ANY configured source (kerf gateway or IPFS
        fetch-adapter) that could plausibly serve a missing chunk."""
        return self.online or self.ipfs_fetcher is not None

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
        # The tip we already accepted at that seq, read back from our own pinned
        # entries — so equal-seq equivocation is caught, not silently accepted.
        # No schema column is needed: the watermark seq indexes an entry we hold.
        accepted_tip: bytes | None = None
        if accepted is not None:
            raw = await self.store.get_feed_entry_by_seq(pub_key, accepted)
            if raw is not None:
                accepted_tip = FeedEntry.from_cbor(raw).id
        check_head_watermark(accepted, accepted_tip, head.seq, head.tip)

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

    # ── pin hydration (§22.5.3 swarm fetch — durable Pin) ──────────────────────
    async def hydrate_pin(
        self, announce_id: bytes,
        concurrency: int = DEFAULT_HYDRATE_CONCURRENCY,
    ) -> HydrationResult:
        """Make a Pin durable: resolve ``announce_id`` (local store first,
        else ``self.gateways`` in order), fetch every ``PubManifest`` its
        ``roots`` name, then fetch and self-verify EVERY chunk each manifest
        lists — rotating to the next gateway on a hash mismatch
        (``ERR_PUB_CHUNK_HASH_MISMATCH`` / 0x090A, ROTATE_RETRY, §22.5.3) and
        falling back to the IPFS fetch-adapter (:mod:`kerf_pub.ipfs`) after
        every kerf gateway has failed a given chunk. All verified bytes are
        persisted locally regardless of overall outcome.

        Availability is set ``on-node`` ONLY when hydration is complete
        (``missing_chunks == 0``); a partial result persists what could be
        verified, leaves ``local_pinned`` False, and — if any source
        responded at all — records it as a known holder so status reads
        ``available`` rather than ``unreachable`` (§22.6). This method never
        reports success ("pinned") for bytes it did not actually verify.

        Raises :class:`~kerf_pub.errors.PubError`
        (``ERR_PUB_NOT_SERVED``) ONLY for the pure zero-socket case: the
        announce itself is neither local nor reachable through any
        configured kerf gateway — "pin of a non-local announce" must fail
        loudly, never silently no-op. Once the announce itself is resolved,
        every further shortfall (missing manifest, missing chunk) is
        reported through the returned :class:`HydrationResult`, not a raise.
        """
        announce, announce_holder = await self._resolve_announce_for_hydrate(announce_id)

        missing_chunks = 0
        unreachable_manifest = False
        holder_url = announce_holder
        for root in announce.roots:
            manifest, m_missing, m_holder, m_unreachable = await self._hydrate_one_manifest(
                root, concurrency=concurrency)
            missing_chunks += m_missing
            unreachable_manifest = unreachable_manifest or m_unreachable
            if m_holder:
                holder_url = m_holder

        if missing_chunks == 0 and not unreachable_manifest:
            await self.store.set_pinned(announce_id, True)
            return HydrationResult(pinned=True, hydrated=True, missing_chunks=0)

        # Partial: bytes we *did* verify are already persisted (below), but
        # availability must NOT read on-node (§22.6.2's "serve only what you
        # verified") — leave local_pinned False and, if some source
        # responded, note it as a holder so status is available, not
        # unreachable.
        await self.store.set_pinned(announce_id, False)
        if holder_url:
            await self.store.note_holder(announce_id, holder_url)
        detail = f"{missing_chunks} chunk(s) unverifiable across all configured sources"
        if unreachable_manifest:
            detail += "; one or more referenced manifests were unreachable"
        return HydrationResult(
            pinned=True, hydrated=False, missing_chunks=missing_chunks, error=detail,
        )

    async def _resolve_announce_for_hydrate(
        self, announce_id: bytes,
    ) -> tuple[PubAnnounce, str | None]:
        """Resolve+verify the announce itself; persist it if fetched remotely.
        Zero-socket: raises PubError if it is not local and no kerf gateway
        is configured (never a silent no-op, per hydrate_pin's docstring)."""
        raw = await self.store.get_announce(announce_id)
        holder: str | None = None
        if raw is None:
            if not self.online:
                raise PubError(
                    ERR_PUB_NOT_SERVED,
                    "pin target is not local and no gateway is configured "
                    "(zero-socket invariant: hydration cannot silently no-op)",
                )
            raw, holder = await self._gateway_get_from(f"announce/{_b64url(announce_id)}")
            if raw is None:
                raise PubError(
                    ERR_PUB_NOT_SERVED,
                    "announce not found locally or on any configured gateway",
                )
        announce = PubAnnounce.from_cbor(raw)
        announce.verify(expected_id=announce_id)  # §22.3.3 — fail closed, propagates
        if holder is not None:
            await self.store.put_announce(announce_id, raw)
        return announce, holder

    async def _hydrate_one_manifest(
        self, root: bytes, concurrency: int,
    ) -> tuple[PubManifest | None, int, str | None, bool]:
        """Resolve+verify+persist one referenced ``PubManifest``, then
        hydrate every chunk it lists. Returns
        ``(manifest_or_None, missing_chunk_count, a_responding_holder_url, manifest_unreachable)``.
        A manifest that cannot be resolved/verified at all is reported via
        the ``manifest_unreachable`` flag (its chunk count is unknowable, so
        it is never folded into ``missing_chunk_count``)."""
        raw = await self.store.get_manifest(root)
        holder: str | None = None
        if raw is None and self.online:
            raw, holder = await self._gateway_get_from(f"manifest/{_b64url(root)}")
        if raw is None:
            return None, 0, holder, True
        try:
            manifest = PubManifest.from_cbor(raw)
            manifest.verify()
            if manifest.id != root:
                raise PubError(ERR_PUB_MANIFEST_HASH_MISMATCH, "manifest id != root")
        except PubError:
            return None, 0, holder, True
        if holder is not None:
            await self.store.put_manifest(root, raw)

        missing, chunk_holder = await self._hydrate_chunks(manifest, concurrency=concurrency)
        if chunk_holder:
            holder = chunk_holder
        return manifest, missing, holder, False

    async def _hydrate_chunks(
        self, manifest: PubManifest, concurrency: int,
    ) -> tuple[int, str | None]:
        """Fetch+verify+persist every chunk ``manifest`` lists, with modest
        bounded concurrency (§22.5.3 "swarm parallelism cap"). Returns
        ``(missing_count, a_responding_holder_url_or_None)``."""
        sem = asyncio.Semaphore(max(1, concurrency))
        holders: list[str | None] = [None] * len(manifest.chunks)

        async def _one(i: int, h: bytes) -> bool:
            existing = await self.store.get_chunk(h)
            if existing is not None and verify_chunk(h, existing):
                return True
            async with sem:
                data, url = await self._fetch_chunk_verified(h)
            if data is None:
                return False
            holders[i] = url
            await self.store.put_chunk(h, data)
            return True

        results = await asyncio.gather(
            *(_one(i, h) for i, h in enumerate(manifest.chunks))
        )
        missing = sum(1 for ok in results if not ok)
        holder = next((u for u in holders if u), None)
        return missing, holder

    async def _fetch_chunk_verified(self, h: bytes) -> tuple[bytes | None, str | None]:
        """Try every configured kerf gateway in order, then the IPFS
        fetch-adapter if configured. A gateway serving bytes that fail
        ``verify_chunk`` is ``ERR_PUB_CHUNK_HASH_MISMATCH`` (0x090A) —
        ROTATE_RETRY to the next source, never accepted (§22.5.3)."""
        for base in self.gateways:
            raw = await self._gateway_get_one(base, f"chunk/{_b64url(h)}")
            if raw is None:
                continue
            if verify_chunk(h, raw):
                return raw, base
            # rotate — a mismatched chunk is never accepted, not even locally.
        if self.ipfs_fetcher is not None:
            raw = await self.ipfs_fetcher.fetch_chunk(h)
            if raw is not None and verify_chunk(h, raw):
                return raw, self.ipfs_fetcher.ipfs_gateway_url
        return None, None

    # ── gateway HTTP (only reached when self.online) ───────────────────────────
    async def _gateway_get_one(self, base: str, path: str) -> bytes | None:
        url = f"{base.rstrip('/')}/.well-known/dmtap-pub/{path}"
        try:
            return await asyncio.to_thread(self._http_get, url)
        except Exception:
            return None

    async def _gateway_get(self, path: str) -> bytes | None:
        for base in self.gateways:
            raw = await self._gateway_get_one(base, path)
            if raw is not None:
                return raw
        return None

    async def _gateway_get_from(self, path: str) -> tuple[bytes | None, str | None]:
        """Like :meth:`_gateway_get`, but also returns which gateway served
        it — used by hydration to record a known holder (§22.6)."""
        for base in self.gateways:
            raw = await self._gateway_get_one(base, path)
            if raw is not None:
                return raw, base
        return None, None

    @staticmethod
    def _http_get(url: str) -> bytes | None:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            if resp.status != 200:
                return None
            return resp.read()
