"""Public-object HTTP endpoint (§22.5.1, the PUB serving profile) — anonymous,
content-addressed reads.

NOTE ON NAMING: DMTAP narrowed "gateway" to mean exactly one thing — the §7
legacy-mail adapter, the sole role needing a reputable IP. This module is the
*other*, unrelated concept §22.5.1 used to also call a "gateway": a plain-HTTP,
no-mesh, no-IP-reputation-needed public-object surface. The spec now calls it
the public-object HTTP endpoint / "PUB server"; this docstring and its
comments follow that terminology. The wire is unchanged.

Exposes the five well-known endpoints EXACTLY as §22.5.1 specifies, serving
ONLY pinned/local objects from the store (§22.6.2). Reads are anonymous; the
four content-addressed endpoints carry immutable-cache headers and a strong
ETag equal to the content address (§22.5.1). Verification is always the
client's job — this PUB server is a convenience, not a trust root.

A missing object is a 404 (the holder does not serve it, ``ERR_PUB_NOT_SERVED``
§22.6.2); a fetcher rotates to another holder.

Also mounts the Wake subscribe/unsubscribe endpoints (:mod:`kerf_pub.wake`,
substrate capability ⑤) at the bottom of this router. Wake is a kerf-local
extension, not part of §22.5.1 itself, but it lives on the SAME anonymous
public-object prefix because it is the same "any node may talk to my node's
public surface about one of my feeds" relationship as the four §22.5.1
endpoints above — a follower node, not this node's own owner, is the caller.
"""

from __future__ import annotations

import base64
import time

from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel

from . import cbor
from .store import InMemoryPubStore, PubStore
from .wake import (
    MAX_SUBSCRIPTIONS_PER_FEED,
    PushSubscription,
    default_wake_config,
    validate_subscription,
    vapid_public_key_b64,
)

CBOR_MEDIA = "application/cbor"
_IMMUTABLE = "public, immutable, max-age=31536000"
_HEAD_CACHE = "no-cache, must-revalidate"

router = APIRouter(prefix="/.well-known/dmtap-pub", tags=["dmtap-pub"])


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    try:
        return base64.urlsafe_b64decode(s + pad)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid base64url")


def _store(request: Request) -> PubStore:
    store = getattr(request.app.state, "pub_store", None)
    if store is None:
        # Never 500 a public read for lack of wiring — serve an empty store.
        store = InMemoryPubStore()
        request.app.state.pub_store = store
    return store


def _immutable(body: bytes, address_b64: str, media: str = CBOR_MEDIA) -> Response:
    return Response(
        content=body,
        media_type=media,
        headers={"Cache-Control": _IMMUTABLE, "ETag": f'"{address_b64}"'},
    )


@router.get("/feed/{pub}/head")
async def feed_head(pub: str, request: Request) -> Response:
    raw = await _store(request).get_feed_head(_b64url_decode(pub))
    if raw is None:
        raise HTTPException(status_code=404, detail="feed head not served")
    return Response(content=raw, media_type=CBOR_MEDIA,
                    headers={"Cache-Control": _HEAD_CACHE})


@router.get("/feed/{pub}/range")
async def feed_range(pub: str, request: Request) -> Response:
    q = request.query_params
    try:
        from_seq = int(q.get("from", "0"))
        to_seq = int(q.get("to", "0"))
    except ValueError:
        raise HTTPException(status_code=400, detail="from/to must be integers")
    if to_seq < from_seq or from_seq < 0:
        raise HTTPException(status_code=400, detail="invalid range")
    rows = await _store(request).get_feed_range(_b64url_decode(pub), from_seq, to_seq)
    entries = [cbor.decode(r) for r in rows]
    return Response(content=cbor.encode(entries), media_type=CBOR_MEDIA,
                    headers={"Cache-Control": "public, max-age=60"})


@router.get("/announce/{aid}")
async def announce(aid: str, request: Request) -> Response:
    raw = await _store(request).get_announce(_b64url_decode(aid))
    if raw is None:
        raise HTTPException(status_code=404, detail="announce not served")
    return _immutable(raw, aid)


@router.get("/manifest/{mid}")
async def manifest(mid: str, request: Request) -> Response:
    raw = await _store(request).get_manifest(_b64url_decode(mid))
    if raw is None:
        raise HTTPException(status_code=404, detail="manifest not served")
    return _immutable(raw, mid)


@router.get("/chunk/{h}")
async def chunk(h: str, request: Request) -> Response:
    data = await _store(request).get_chunk(_b64url_decode(h))
    if data is None:
        raise HTTPException(status_code=404, detail="chunk not served")
    # Raw plaintext bytes (§22.5.1), self-verifying against h.
    return _immutable(data, h, media="application/octet-stream")


# ---------------------------------------------------------------------------
# Wake subscribe / unsubscribe (kerf-local extension, substrate capability ⑤)
# ---------------------------------------------------------------------------
#
# Anonymous by design — a follower on ANOTHER node has no account or session
# here, exactly like the four §22.5.1 reads above. The abuse surface of an
# open "register a URL for me to POST to" endpoint is bounded by: requiring
# https (kerf_pub.wake.validate_subscription — no SSRF to plaintext-http-only
# internal services), capping live subscriptions per feed
# (MAX_SUBSCRIPTIONS_PER_FEED), and the send path itself never carrying
# content (a malicious subscriber can only make this node waste a POST, never
# exfiltrate anything — the payload is a random nonce). Fail-safe off: with no
# VAPID keypair configured, this endpoint refuses every subscription rather
# than accepting one it can never actually use to send a wake.


class SubscribeKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: SubscribeKeys


class UnsubscribeRequest(BaseModel):
    endpoint: str


@router.get("/wake-key")
async def wake_key() -> dict:
    """Anonymous — this node's own VAPID public key (RFC 8292 application
    server key), the piece of state a browser needs before it can call
    `PushManager.subscribe({applicationServerKey})` and then `POST
    .../subscribe` below. Same fail-safe-off posture as that endpoint: 503
    when this node has no VAPID keypair configured, so a caller (the
    Workshop UI's "Notify me" toggle) can tell "not supported here" apart
    from a transient failure and disable itself accordingly."""
    config = default_wake_config()
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="wake is not configured on this node (no VAPID keypair)",
        )
    return {"public_key": vapid_public_key_b64(config)}


@router.post("/feed/{pub}/subscribe")
async def subscribe_feed(pub: str, body: SubscribeRequest, request: Request) -> dict:
    if default_wake_config() is None:
        raise HTTPException(
            status_code=503,
            detail="wake is not configured on this node (no VAPID keypair) — "
                   "the Workshop's pull-only re-crawl still applies",
        )
    pub_bytes = _b64url_decode(pub)
    if len(pub_bytes) != 32:
        raise HTTPException(status_code=400, detail="pub must be a 32-byte Ed25519 key (base64url)")

    sub = PushSubscription(endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth)
    try:
        validate_subscription(sub)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    store = _store(request)
    existing = await store.count_wake_subscriptions(pub_bytes)
    already_subscribed = any(
        s["endpoint"] == sub.endpoint for s in await store.list_wake_subscriptions(pub_bytes)
    )
    if not already_subscribed and existing >= MAX_SUBSCRIPTIONS_PER_FEED:
        raise HTTPException(status_code=429, detail="this feed has reached its wake-subscriber cap")

    await store.put_wake_subscription(
        pub_bytes, sub.endpoint, sub.p256dh, sub.auth, int(time.time() * 1000),
    )
    return {"pub": pub, "subscribed": True}


@router.delete("/feed/{pub}/subscribe")
async def unsubscribe_feed(pub: str, body: UnsubscribeRequest, request: Request) -> dict:
    pub_bytes = _b64url_decode(pub)
    await _store(request).delete_wake_subscription(pub_bytes, body.endpoint)
    return {"pub": pub, "subscribed": False}
