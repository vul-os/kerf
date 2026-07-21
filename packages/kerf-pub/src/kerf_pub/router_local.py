"""kerf-pub node-local convenience API — the UI-facing layer over the
four-verb DMTAP-PUB client (:mod:`kerf_pub.client`).

Mounted (like :mod:`kerf_pub.router`, the anonymous §22.5.1 public-object HTTP
endpoint — the "PUB server" profile, distinct from the §7 legacy-mail
gateway role) as an OSS-node plugin surface, but every endpoint here requires
an authenticated session — this is the local node owner managing THEIR
node's identity, followed feeds, and publishes, not an anonymous protocol
endpoint.

Identity and followed feeds are **node-local, not per-account** state: a
single Ed25519 keypair per node (``kerf_pub.identity.Identity``) and one
shared follow list, matching kerf-pub's "accounts shrink to the box" design
(a single-user local install has zero login; a shared team box has local
accounts, but Workshop identity/follows are still a property of the box,
not of any one account on it). ``publish`` is the one project-scoped verb
here and checks workspace membership like any other project route.

Zero-socket invariant: every read here serves from the local
:class:`~kerf_pub.store.PubStore` first; a network call to a followed feed's
``gateway_url`` (its followed PUB server) is only attempted when that follow
configured one (see ``GET /api/pub/workshop``). Pin hydration
(``POST /api/pub/pin/{id}``, ``POST /api/pub/pin/{id}/hydrate``) extends the
same invariant: with no PUB server configured anywhere, pinning a non-local
announce fails with a clear 400 rather than a silent no-op
(:func:`_do_hydrate`, :meth:`kerf_pub.client.PubClient.hydrate_pin`).
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

from .assembly import (
    UnresolvedChildRef,
    build_assembly_children,
    list_own_assembly_candidates,
    walk_bom,
)
from .client import PubClient, HydrationResult
from .errors import PubError, ProfileError
from .identity import Identity, default_key_path
from .ipfs import default_ipfs_gateway_url
from .wake import PushSubscription, default_wake_config, notify_subscribers
from .objects import (
    ArtifactFormat,
    ArtifactMetadata,
    AssemblyStructure,
    FMT_ASSEMBLY_STRUCTURE,
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
    PubManifest,
    ROLE_CANONICAL,
    ROLE_DERIVED,
    ROLE_STRUCTURE,
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
    """Same accessor the public-object router (router.py) uses — one store per app."""
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


async def _resolve_follow_listings(store: PubStore, follow: dict, now_ms: int) -> list[dict]:
    """Resolve one followed feed (verified head + chain walk, §22.4) into
    Workshop listing dicts. Shared by the full re-crawl (``GET /workshop``,
    every follow) and the single-feed refresh (``POST /follows/{pub}/refresh``
    — the targeted pull a Wake ping's receiver triggers instead of waiting for
    the next full re-crawl, :mod:`kerf_pub.wake`)."""
    gateways = [follow["gateway_url"]] if follow.get("gateway_url") else []
    client = PubClient(store=store, identity=None, gateways=gateways)

    try:
        entries = await client.resolve(follow["pub"])
    except PubError as exc:
        logger.warning("pub-workshop: resolve failed for %s: %s", _b64url(follow["pub"]), exc)
        return []

    out: list[dict] = []
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


@router.get("/workshop")
async def workshop_feed(request: Request, payload: dict = Depends(require_auth)):
    store = _store(request)
    follows = await store.list_follows()
    now_ms = _now_ms()

    out: list[dict] = []
    for follow in follows:
        out.extend(await _resolve_follow_listings(store, follow, now_ms))
    return out


# ---------------------------------------------------------------------------
# POST /api/pub/follows/{pub}/refresh
# ---------------------------------------------------------------------------
#
# A targeted re-crawl of exactly ONE followed feed — the "light up without
# re-crawl polling" half of Wake (:mod:`kerf_pub.wake`, substrate capability
# ⑤): a browser Service Worker that receives a content-free WakePing for this
# feed calls this instead of waiting for the next full ``GET /workshop`` pass
# over every follow. Pull remains authoritative either way (DMTAP: "push is a
# latency optimization, not delivery") — this endpoint does the exact same
# verified resolve+chain-walk as ``GET /workshop``, just scoped to one `pub`.


@router.post("/follows/{pub}/refresh")
async def refresh_follow(pub: str, request: Request, payload: dict = Depends(require_auth)):
    pub_bytes = _b64url_decode(pub)
    store = _store(request)
    follows = await store.list_follows()
    follow = next((f for f in follows if f["pub"] == pub_bytes), None)
    if follow is None:
        raise HTTPException(status_code=404, detail="not following this feed")
    return await _resolve_follow_listings(store, follow, _now_ms())


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


class AssemblyChildIn(BaseModel):
    """One entry of a ``POST /api/pub/publish`` assembly ``children`` array
    (§23.6.2). ``pin`` children carry ``manifest_root``; ``track`` children
    carry ``announce_id`` — both base64url, both validated against the local
    store / followed PUB servers before the announce is signed."""

    ref_kind: str  # "pin" | "track"
    announce_id: Optional[str] = None
    manifest_root: Optional[str] = None
    quantity: int = 1


class PublishRequest(BaseModel):
    project_id: str
    metadata: PublishMetadata
    children: Optional[list[AssemblyChildIn]] = None


async def _notify_wake_subscribers(store: PubStore, pub: bytes) -> None:
    """Best-effort Wake fan-out (:mod:`kerf_pub.wake`, substrate capability
    ⑤) after a new revision lands on OUR OWN feed. Fail-safe off (a no-op
    when this node has no VAPID keypair configured) and never raises — a dead
    push endpoint or a misconfigured node must never fail the publish that
    triggered it; the Workshop's pull-only re-crawl remains authoritative
    regardless of whether any wake was sent."""
    config = default_wake_config()
    if config is None:
        return
    try:
        rows = await store.list_wake_subscriptions(pub)
        subs = [PushSubscription(endpoint=r["endpoint"], p256dh=r["p256dh"], auth=r["auth"]) for r in rows]
        await notify_subscribers(subs, config)
    except Exception:
        logger.warning("kerf-pub: wake fan-out failed after publish", exc_info=True)


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
    identity = Identity.load_or_create()
    store = _store(request)
    follows = await store.list_follows()
    gateways = [f["gateway_url"] for f in follows if f.get("gateway_url")]
    client = PubClient(store=store, identity=identity, gateways=gateways)

    if artifact_kind == KIND_ASSEMBLY:
        try:
            children = await build_assembly_children(
                store, client, [c.model_dump() for c in (body.children or [])],
            )
        except UnresolvedChildRef as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # The AssemblyStructure blob (§23.6.2) is itself just an ordinary
        # public blob — published like any other project file, referenced
        # from formats with role=structure, format_id=6 (§23.3.4 CAD-3).
        structure = AssemblyStructure(children=children)
        struct_bytes = structure.to_cbor()
        struct_manifest = PubManifest.build(struct_bytes)

        files = await _collect_project_files(body.project_id)
        publish_files: dict[str, bytes] = {"__assembly_structure__.cbor": struct_bytes}
        formats = [ArtifactFormat(
            format_id=FMT_ASSEMBLY_STRUCTURE, manifest_root=struct_manifest.id, role=ROLE_STRUCTURE,
        )]

        # A native assembly-authoring file, if the project has one, MAY
        # additionally carry role=canonical (§23.3.4); everything else the
        # project holds (STEP/glTF/PDF exports) rides in as a derived
        # rendition of that native file, or of the structure blob itself
        # when there is no native file to derive from.
        native_path = next((p for p in files if _format_id_for(p) == FMT_NATIVE), None)
        native_root = None
        if native_path is not None:
            native_manifest = PubManifest.build(files[native_path])
            native_root = native_manifest.id
            formats.append(ArtifactFormat(
                format_id=FMT_NATIVE, manifest_root=native_root, role=ROLE_CANONICAL,
            ))
        for path, data in files.items():
            publish_files[path] = data
            if path == native_path:
                continue
            fmt_manifest = PubManifest.build(data)
            formats.append(ArtifactFormat(
                format_id=_format_id_for(path),
                manifest_root=fmt_manifest.id,
                role=ROLE_DERIVED,
                derived_from_format=native_root if native_root is not None else struct_manifest.id,
            ))

        try:
            artifact_metadata = ArtifactMetadata(
                name=m.name,
                description=m.description,
                artifact_kind=KIND_ASSEMBLY,
                formats=formats,
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
            announce_id = await client.publish(publish_files, artifact_metadata)
        except PubError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        await _notify_wake_subscribers(store, identity.pub)
        return {"announce_id": _b64url(announce_id)}

    files = await _collect_project_files(body.project_id)
    if not files:
        raise HTTPException(status_code=400, detail="project has no files to publish")

    canonical_path, canonical_format_id = _pick_canonical(files)

    # Manifests are built for every file inside client.publish(); we need the
    # canonical file's manifest root ahead of time to reference it from
    # ArtifactMetadata.formats — PubManifest.build() is a pure/deterministic
    # function of (bytes, chunk_sz), so recomputing it here and letting
    # client.publish() recompute it again is wasted work, not a correctness
    # risk (both calls produce byte-identical manifests).
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

    await _notify_wake_subscribers(store, identity.pub)
    return {"announce_id": _b64url(announce_id)}


# ---------------------------------------------------------------------------
# GET /api/pub/bom/{announce_id}
# ---------------------------------------------------------------------------


@router.get("/bom/{announce_id}")
async def bom(announce_id: str, request: Request, payload: dict = Depends(require_auth)):
    """§23.6.3 BOM walk from an assembly-kind announce: resolves pin/track
    children (recursing into sub-assemblies), dedups leaf quantities by
    resolved content address, and surfaces any cycle rather than recursing
    forever or silently dropping the offending subtree (CAD-10)."""
    aid = _b64url_decode(announce_id)
    store = _store(request)
    follows = await store.list_follows()
    gateways = [f["gateway_url"] for f in follows if f.get("gateway_url")]
    client = PubClient(store=store, identity=None, gateways=gateways)

    try:
        result = await walk_bom(store, aid, client)
    except PubError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ProfileError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.rule}: {exc}")

    return {
        "announce_id": announce_id,
        "parts": [
            {
                "ref": _b64url(p.ref),
                "ref_kind": p.ref_kind,
                "resolved_announce": _b64url(p.resolved_announce) if p.resolved_announce else None,
                "quantity_total": p.quantity_total,
            }
            for p in result.parts
        ],
        "cycles": [
            {
                "ref": _b64url(c.ref),
                "ref_kind": c.ref_kind,
                "path": [_b64url(x) for x in c.path],
            }
            for c in result.cycles
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/pub/assembly-candidates/{project_id}
# ---------------------------------------------------------------------------


@router.get("/assembly-candidates/{project_id}")
async def assembly_candidates(project_id: str, request: Request, payload: dict = Depends(require_auth)):
    """Best-effort list of the node owner's OWN published announces, for a UI
    child-picker when composing an assembly's `children` array. Requires
    project membership (any role) purely as the standard project-route auth
    gate; the candidates themselves come from the node-local feed, not the
    project (§23.7 — workshop identity/follows are node-local, not per-project)."""
    user_id = payload.get("sub")
    await _project_and_role(project_id, user_id)

    store = _store(request)
    identity = Identity.load_or_create()
    candidates = await list_own_assembly_candidates(store, identity)
    return [
        {"announce_id": _b64url(c["announce_id"]), "name": c["name"], "kind": c["kind"]}
        for c in candidates
    ]


# ---------------------------------------------------------------------------
# POST/DELETE /api/pub/pin/{announce_id}, POST /api/pub/pin/{announce_id}/hydrate
# ---------------------------------------------------------------------------
#
# Pinning is durable, not a flag flip: POST /pin walks the swarm — the
# followed author's own PUB server first, then every other followed PUB
# server (deduped), then the per-node IPFS fetch-adapter for chunk bytes if
# configured (kerf_pub.ipfs) — fetching and self-verifying every manifest and
# chunk the announce names before it reports success (kerf_pub.client.
# PubClient.hydrate_pin, §22.5.3). POST /pin/{id}/hydrate re-runs the exact
# same walk to retry a pin that came back incomplete.


async def _ordered_gateways_for(store: PubStore, announce_id: bytes) -> list[str]:
    """PUB server URLs to try, in order: the followed author's OWN
    ``gateway_url`` first (learned from a locally-known copy of the
    announce, if any), then every other follow's non-empty ``gateway_url``,
    deduplicated by URL. When the announce isn't locally known yet, the
    author can't be identified without fetching it first, so every followed
    PUB server is offered in follow order — hydrate_pin() still finds and
    verifies the announce through whichever one happens to serve it."""
    follows = await store.list_follows()
    ordered: list[str] = []

    def _add(url: str | None) -> None:
        if url and url not in ordered:
            ordered.append(url)

    primary_pub: bytes | None = None
    local_raw = await store.get_announce(announce_id)
    if local_raw is not None:
        try:
            primary_pub = PubAnnounce.from_cbor(local_raw).pub
        except PubError:
            primary_pub = None

    if primary_pub is not None:
        for f in follows:
            if f["pub"] == primary_pub:
                _add(f.get("gateway_url"))

    for f in follows:
        _add(f.get("gateway_url"))

    return ordered


async def _do_hydrate(store: PubStore, aid: bytes) -> HydrationResult:
    gateways = await _ordered_gateways_for(store, aid)
    client = PubClient(
        store=store, identity=None, gateways=gateways,
        ipfs_gateway_url=default_ipfs_gateway_url(),
    )
    try:
        return await client.hydrate_pin(aid)
    except PubError as exc:
        # Zero-socket / not-found: a clear 400, never a silent 200 (§22.5.1's
        # "pin cannot silently no-op" requirement).
        raise HTTPException(status_code=400, detail=str(exc))


def _hydration_response(announce_id: str, result: HydrationResult) -> dict:
    out: dict = {
        "announce_id": announce_id,
        "pinned": result.pinned,
        "hydrated": result.hydrated,
        "missing_chunks": result.missing_chunks,
    }
    if result.error:
        out["error"] = result.error
    return out


@router.post("/pin/{announce_id}")
async def pin(announce_id: str, request: Request, payload: dict = Depends(require_auth)):
    aid = _b64url_decode(announce_id)
    store = _store(request)
    result = await _do_hydrate(store, aid)
    return _hydration_response(announce_id, result)


@router.post("/pin/{announce_id}/hydrate")
async def hydrate_pin(announce_id: str, request: Request, payload: dict = Depends(require_auth)):
    """Retry hydration of a pin that previously came back incomplete
    (``hydrated: false``) — identical walk to ``POST /pin/{id}``, exposed
    separately so a client can distinguish "pin this" from "try again"."""
    aid = _b64url_decode(announce_id)
    store = _store(request)
    result = await _do_hydrate(store, aid)
    return _hydration_response(announce_id, result)


@router.delete("/pin/{announce_id}")
async def unpin(announce_id: str, request: Request, payload: dict = Depends(require_auth)):
    aid = _b64url_decode(announce_id)
    store = _store(request)
    await store.set_pinned(aid, False)
    return {"announce_id": announce_id, "pinned": False}
