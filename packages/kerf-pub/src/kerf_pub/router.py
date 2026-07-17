"""Gateway HTTP profile (§22.5.1) — anonymous, content-addressed reads.

Exposes the five well-known endpoints EXACTLY as §22.5.1 specifies, serving
ONLY pinned/local objects from the store (§22.6.2). Reads are anonymous; the
four content-addressed endpoints carry immutable-cache headers and a strong
ETag equal to the content address (§22.5.1). Verification is always the
client's job — this gateway is a convenience, not a trust root.

A missing object is a 404 (the holder does not serve it, ``ERR_PUB_NOT_SERVED``
§22.6.2); a fetcher rotates to another holder.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Request, Response, HTTPException

from . import cbor
from .store import InMemoryPubStore, PubStore

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
