"""kerf-pub node-local convenience API — the UI-facing layer over the
four-verb DMTAP-PUB client (:mod:`kerf_pub.client`).

Mounted (like :mod:`kerf_pub.router`, the anonymous §22.5.1 gateway) as an
OSS-node plugin surface, but every endpoint here requires an authenticated
session — this is the local node owner managing THEIR node's identity,
followed feeds, and publishes, not an anonymous protocol endpoint.

Identity and followed feeds are **node-local, not per-account** state: a
single Ed25519 keypair per node (``kerf_pub.identity.Identity``) and one
shared follow list, matching kerf-pub's "accounts shrink to the box" design
(a single-user local install has zero login; a shared team box has local
accounts, but Workshop identity/follows are still a property of the box,
not of any one account on it). ``publish`` is the one project-scoped verb
here and checks workspace membership like any other project route.

Zero-socket invariant: every read here serves from the local
:class:`~kerf_pub.store.PubStore` first; a network call to a followed feed's
``gateway_url`` is only attempted when that follow configured one (see
``GET /api/pub/workshop``).
"""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from kerf_core.db.connection import get_pool_required
from kerf_core.dependencies import require_auth
from kerf_core.storage import get_storage_required

from .client import PubClient
from .errors import PubError, ProfileError
from .identity import Identity, default_key_path
from .objects import (
    ArtifactFormat,
    ArtifactMetadata,
    FMT_ECAD,
    FMT_GLTF,
    FMT_NATIVE,
    FMT_PDF,
    FMT_STEP,
    KIND_ASSEMBLY,
    KIND_DATASET,
    KIND_DOC,
    KIND_DRAWING,
    KIND_PART,
    KIND_PCB,
    KIND_SCHEMATIC,
    PubAnnounce,
    ROLE_CANONICAL,
    Units,
    extract_artifact,
)
from .store import PubStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pub", tags=["pub-local"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    try:
        return base64.urlsafe_b64decode(s + pad)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid base64url")


def _store(request: Request) -> PubStore:
    """Same accessor the gateway router (router.py) uses — one store per app."""
    from .router import _store as _gateway_store
    return _gateway_store(request)


def _now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# GET/POST /api/pub/identity
# ---------------------------------------------------------------------------


@router.get("/identity")
async def get_identity(payload: dict = Depends(require_auth)):
    path = default_key_path()
    if not os.path.exists(path):
        return {"pub": None}
    identity = Identity.load_or_create(path)
    return {"pub": _b64url(identity.pub)}


@router.post("/identity")
async def create_identity(payload: dict = Depends(require_auth)):
    # Idempotent: load_or_create() reuses an existing key rather than erroring.
    identity = Identity.load_or_create()
    return {"pub": _b64url(identity.pub)}


# ---------------------------------------------------------------------------
# GET/POST /api/pub/follows, DELETE /api/pub/follows/{pub}
# ---------------------------------------------------------------------------


class FollowRequest(BaseModel):
    pub: str
    label: str = ""
    gateway_url: str = ""


@router.get("/follows")
async def list_follows(request: Request, payload: dict = Depends(require_auth)):
    store = _store(request)
    follows = await store.list_follows()
    return [
        {
            "pub": _b64url(f["pub"]),
            "label": f["label"],
            "gateway_url": f["gateway_url"],
            "added_ts": f["added_ts"],
        }
        for f in follows
    ]


@router.post("/follows")
async def add_follow(request: Request, body: FollowRequest, payload: dict = Depends(require_auth)):
    pub_bytes = _b64url_decode(body.pub)
    if len(pub_bytes) != 32:
        raise HTTPException(status_code=400, detail="pub must be a 32-byte Ed25519 key (base64url)")

    store = _store(request)
    added_ts = _now_ms()
    await store.put_follow(pub_bytes, body.label, body.gateway_url, added_ts)
    return {
        "pub": _b64url(pub_bytes),
        "label": body.label,
        "gateway_url": body.gateway_url,
        "added_ts": added_ts,
    }


@router.delete("/follows/{pub}")
async def delete_follow(pub: str, request: Request, payload: dict = Depends(require_auth)):
    pub_bytes = _b64url_decode(pub)
    store = _store(request)
    await store.delete_follow(pub_bytes)
    return {"pub": pub, "removed": True}


# ---------------------------------------------------------------------------
# GET /api/pub/workshop
# ---------------------------------------------------------------------------


def _availability_out(avail, now_ms: int) -> dict:
    holders = avail.known_holders
    last_verified = max(holders.values()) if holders else None
    return {
        "status": avail.status(now_ms),
        "holders": len(holders),
        "last_verified": last_verified,
    }


@router.get("/workshop")
async def workshop_feed(request: Request, payload: dict = Depends(require_auth)):
    store = _store(request)
    follows = await store.list_follows()
    now_ms = _now_ms()

    out: list[dict] = []
    for follow in follows:
        gateways = [follow["gateway_url"]] if follow.get("gateway_url") else []
        client = PubClient(store=store, identity=None, gateways=gateways)

        try:
            entries = await client.resolve(follow["pub"])
        except PubError as exc:
            logger.warning("pub-workshop: resolve failed for %s: %s", _b64url(follow["pub"]), exc)
            continue

        for entry in entries:
            raw = await store.get_announce(entry.announce)
            if raw is None and client.online:
                raw = await client._gateway_get(f"announce/{_b64url(entry.announce)}")
            if raw is None:
                continue
            try:
                announce = PubAnnounce.from_cbor(raw)
                announce.verify(expected_id=entry.announce)
            except PubError as exc:
                logger.warning("pub-workshop: invalid announce %s: %s", _b64url(entry.announce), exc)
                continue

            artifact = extract_artifact(announce.meta)
            if artifact is None:
                # Not a CAD/artifact announce (§23) — not a Workshop listing.
                continue

            avail = await store.get_availability(entry.announce)
            out.append({
                "announce_id": _b64url(entry.announce),
                "pub": _b64url(announce.pub),
                "meta": {
                    "name": artifact.name,
                    "description": artifact.description,
                    "artifact_kind": artifact.artifact_kind,
                    "license": artifact.license,
                    "units": {
                        "length_unit": artifact.units.length_unit,
                        "angle_unit": artifact.units.angle_unit,
                        "mass_unit": artifact.units.mass_unit,
                    },
                    "tags": artifact.tags or [],
                },
                "roots": [_b64url(r) for r in announce.roots],
                "ts": announce.ts,
                "supersedes": _b64url(announce.supersedes) if announce.supersedes else None,
                "availability": _availability_out(avail, now_ms),
                "pinned": avail.local_pinned,
            })

    return out


# ---------------------------------------------------------------------------
# POST /api/pub/publish
# ---------------------------------------------------------------------------

_KIND_NAME_TO_INT = {
    "part": KIND_PART, "assembly": KIND_ASSEMBLY, "pcb": KIND_PCB,
    "schematic": KIND_SCHEMATIC, "drawing": KIND_DRAWING,
    "dataset": KIND_DATASET, "doc": KIND_DOC,
}

_EXT_TO_FORMAT = {
    "step": FMT_STEP, "stp": FMT_STEP,
    "gltf": FMT_GLTF, "glb": FMT_GLTF,
    "pdf": FMT_PDF,
    "kicad_pcb": FMT_ECAD, "kicad_sch": FMT_ECAD, "brd": FMT_ECAD, "sch": FMT_ECAD,
}


class PublishMetadata(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    artifact_kind: Optional[str] = None
    license: Optional[str] = None
    units: Optional[dict] = None
    tags: Optional[list[str]] = None


class PublishRequest(BaseModel):
    project_id: str
    metadata: PublishMetadata


async def _project_and_role(pid: str, user_id: str) -> tuple[dict, str]:
    pool = await get_pool_required()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, workspace_id, name FROM projects WHERE id = $1", pid,
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
        member = await conn.fetchrow(
            "SELECT role FROM workspace_members WHERE workspace_id = $1 AND user_id = $2",
            str(row["workspace_id"]), user_id,
        )
        if not member:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
        return dict(row), member["role"]


async def _collect_project_files(project_id: str) -> dict[str, bytes]:
    """path -> bytes for every live file in the project (mirrors the same
    query kerf-api's local git API and the retired hosted-git handler use)."""
    pool = await get_pool_required()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, parent_id, name, kind, content, storage_key "
            "FROM files WHERE project_id = $1 AND deleted_at IS NULL",
            project_id,
        )
    by_id = {r["id"]: r for r in rows}

    def _full_path(row) -> str:
        segs = [row["name"]]
        seen = set()
        cur = row["parent_id"]
        while cur is not None and cur not in seen:
            seen.add(cur)
            parent = by_id.get(cur)
            if parent is None:
                break
            segs.append(parent["name"])
            cur = parent["parent_id"]
        return "/".join(reversed(segs))

    storage = get_storage_required()
    out: dict[str, bytes] = {}
    for r in rows:
        if r["kind"] == "folder":
            continue
        if r["storage_key"]:
            stream, _ct = await storage.get(r["storage_key"])
            try:
                content = stream.read()
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
        else:
            content = (r["content"] or "").encode("utf-8")
        out[_full_path(r)] = content
    return out


def _format_id_for(path: str) -> int:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _EXT_TO_FORMAT.get(ext, FMT_NATIVE)


def _pick_canonical(files: dict[str, bytes]) -> tuple[str, int]:
    """Choose one file as role=canonical-source (§23.3.4 rule): prefer a
    native source file; fall back to STEP only if no native file exists;
    otherwise the first file at all (covers doc/dataset artifacts)."""
    native = [p for p in files if _format_id_for(p) == FMT_NATIVE]
    if native:
        return native[0], FMT_NATIVE
    step = [p for p in files if _format_id_for(p) == FMT_STEP]
    if step:
        return step[0], FMT_STEP
    first = next(iter(files))
    return first, _format_id_for(first)


@router.post("/publish")
async def publish(request: Request, body: PublishRequest, payload: dict = Depends(require_auth)):
    user_id = payload.get("sub")
    project, role = await _project_and_role(body.project_id, user_id)
    if role not in ("owner", "editor", "admin"):
        raise HTTPException(status_code=403, detail="editor or owner role required")

    m = body.metadata
    missing = []
    if not m.name:
        missing.append("metadata.name")
    if not m.description:
        missing.append("metadata.description")
    if not m.artifact_kind:
        missing.append("metadata.artifact_kind")
    if not m.license:
        missing.append("metadata.license")
    length_unit = (m.units or {}).get("length_unit") if m.units else None
    if not length_unit:
        missing.append("metadata.units.length_unit")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"missing required field(s): {', '.join(missing)}",
        )

    kind_raw = m.artifact_kind.strip().lower() if isinstance(m.artifact_kind, str) else m.artifact_kind
    artifact_kind = _KIND_NAME_TO_INT.get(kind_raw, kind_raw if isinstance(kind_raw, int) else None)
    if artifact_kind not in _KIND_NAME_TO_INT.values():
        raise HTTPException(
            status_code=400,
            detail=f"unrecognized metadata.artifact_kind: {m.artifact_kind!r} "
                   f"(expected one of {sorted(_KIND_NAME_TO_INT)})",
        )
    if artifact_kind == KIND_ASSEMBLY:
        # An assembly needs a role=structure ArtifactFormat (§23.6.2, an
        # AssemblyStructure blob enumerating sub-part references) — building
        # that from a project's file tree is future work; publishing a
        # single-part/dataset/doc artifact is fully supported today.
        raise HTTPException(
            status_code=400,
            detail="assembly publish is not yet supported via this endpoint "
                   "(requires an AssemblyStructure sub-part graph)",
        )

    files = await _collect_project_files(body.project_id)
    if not files:
        raise HTTPException(status_code=400, detail="project has no files to publish")

    canonical_path, canonical_format_id = _pick_canonical(files)

    identity = Identity.load_or_create()
    store = _store(request)
    client = PubClient(store=store, identity=identity, gateways=[])

    # Manifests are built for every file inside client.publish(); we need the
    # canonical file's manifest root ahead of time to reference it from
    # ArtifactMetadata.formats — PubManifest.build() is a pure/deterministic
    # function of (bytes, chunk_sz), so recomputing it here and letting
    # client.publish() recompute it again is wasted work, not a correctness
    # risk (both calls produce byte-identical manifests).
    from .objects import PubManifest
    canonical_manifest = PubManifest.build(files[canonical_path])

    try:
        artifact_metadata = ArtifactMetadata(
            name=m.name,
            description=m.description,
            artifact_kind=artifact_kind,
            formats=[ArtifactFormat(
                format_id=canonical_format_id,
                manifest_root=canonical_manifest.id,
                role=ROLE_CANONICAL,
            )],
            units=Units(
                length_unit=m.units["length_unit"],
                angle_unit=m.units.get("angle_unit"),
                mass_unit=m.units.get("mass_unit"),
            ),
            license=m.license,
            tags=m.tags,
        )
        artifact_metadata.validate()
    except ProfileError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.rule}: {exc}")

    try:
        announce_id = await client.publish(files, artifact_metadata)
    except PubError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"announce_id": _b64url(announce_id)}


# ---------------------------------------------------------------------------
# POST/DELETE /api/pub/pin/{announce_id}
# ---------------------------------------------------------------------------


@router.post("/pin/{announce_id}")
async def pin(announce_id: str, request: Request, payload: dict = Depends(require_auth)):
    aid = _b64url_decode(announce_id)
    store = _store(request)
    # Marks local availability state. Actually walking followed gateways to
    # hydrate the manifest + chunk bytes into the local store (the full
    # ADR §6 "pinning fetches the object" behavior) is the P1 swarm-fetch
    # work — out of scope for this node-local convenience wave.
    await store.set_pinned(aid, True)
    return {"announce_id": announce_id, "pinned": True}


@router.delete("/pin/{announce_id}")
async def unpin(announce_id: str, request: Request, payload: dict = Depends(require_auth)):
    aid = _b64url_decode(announce_id)
    store = _store(request)
    await store.set_pinned(aid, False)
    return {"announce_id": announce_id, "pinned": False}
