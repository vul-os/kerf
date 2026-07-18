"""§23.6 assembly support: publish-time child-ref resolution and the BOM walk.

Kept as its own module (rather than folded into :mod:`kerf_pub.router_local`
or :mod:`kerf_pub.objects`) so the publish-handler surface stays a thin
HTTP-shape adapter and the recursive DAG-walk logic — the part with real
edge cases (cycles, dedup, forward supersedes-resolution) — has its own
seam, independently testable without a FastAPI app.

Three things live here:

1. :func:`build_assembly_children` — turns the raw ``children`` array of a
   ``POST /api/pub/publish`` request into validated :class:`~kerf_pub.objects.AssemblyChild`
   entries, failing closed (naming the bad ref) when a pin's manifest or a
   track's announce isn't resolvable locally or via a followed gateway.
2. :func:`walk_bom` — the §23.6.3 BOM walk: resolves every child (pin
   directly, track via forward supersedes-resolution to the live head),
   recurses into sub-assemblies, dedups leaf quantities by content address,
   and rejects cycles per-subtree rather than recursing forever.
3. :func:`list_own_assembly_candidates` — a convenience read over the local
   node's own feed, for a UI child-picker (no cross-package coupling).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

from .client import PubClient
from .errors import PubError, ProfileError, ERR_PUB_NOT_SERVED
from .identity import Identity
from .objects import (
    AssemblyChild,
    AssemblyStructure,
    KIND_ASSEMBLY,
    PubAnnounce,
    FeedEntry,
    FeedHead,
    REF_PIN,
    REF_TRACK,
    ROLE_STRUCTURE,
    extract_artifact,
)
from .store import PubStore

_KIND_INT_TO_NAME = {
    1: "part", 2: "assembly", 3: "pcb", 4: "schematic",
    5: "drawing", 6: "dataset", 7: "doc",
}


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


class UnresolvedChildRef(ValueError):
    """A publish-time assembly child ref that could not be validated (§23.6.1):
    a ``pin`` manifest_root or ``track`` announce_id absent from the local
    store and not served by any followed gateway. Carries every offending
    child's description so the 400 names them all, not just the first."""


# ═══════════════════════════════════════════════════════════════════════════
# publish-time: build + validate AssemblyChild list from a request payload
# ═══════════════════════════════════════════════════════════════════════════

async def _manifest_exists(store: PubStore, client: PubClient, ref: bytes) -> bool:
    if await store.get_manifest(ref) is not None:
        return True
    if client.online:
        raw = await client._gateway_get(f"manifest/{_b64url(ref)}")
        if raw is not None:
            await store.put_manifest(ref, raw)
            return True
    return False


async def _announce_exists(store: PubStore, client: PubClient, ref: bytes) -> bool:
    if await store.get_announce(ref) is not None:
        return True
    if client.online:
        raw = await client._gateway_get(f"announce/{_b64url(ref)}")
        if raw is not None:
            await store.put_announce(ref, raw)
            return True
    return False


async def build_assembly_children(
    store: PubStore,
    client: PubClient,
    children: list[dict],
) -> list[AssemblyChild]:
    """Validate + build the §23.6.2 children list from a publish request's raw
    ``children`` array: ``[{ref_kind: "pin"|"track", manifest_root?, announce_id?,
    quantity}]``. ``pin`` children carry a base64url ``manifest_root``; ``track``
    children a base64url ``announce_id``. Every ref MUST resolve — locally, or
    via a followed gateway — or the whole publish fails closed with every
    unresolvable ref named (§23.6, no silent partial assembly)."""
    if not children:
        raise UnresolvedChildRef("assembly publish requires a non-empty children array")

    out: list[AssemblyChild] = []
    problems: list[str] = []
    for i, c in enumerate(children):
        ref_kind_raw = c.get("ref_kind")
        try:
            quantity = int(c.get("quantity", 1))
        except (TypeError, ValueError):
            problems.append(f"children[{i}]: quantity must be an integer")
            continue

        if ref_kind_raw == "pin":
            root_b64 = c.get("manifest_root")
            if not root_b64:
                problems.append(f"children[{i}]: pin child requires manifest_root")
                continue
            try:
                ref = _b64url_decode(root_b64)
            except Exception:
                problems.append(f"children[{i}]: manifest_root is not valid base64url")
                continue
            if not await _manifest_exists(store, client, ref):
                problems.append(
                    f"children[{i}]: manifest_root {root_b64} not found locally or via followed gateways"
                )
                continue
            ref_kind = REF_PIN
        elif ref_kind_raw == "track":
            aid_b64 = c.get("announce_id")
            if not aid_b64:
                problems.append(f"children[{i}]: track child requires announce_id")
                continue
            try:
                ref = _b64url_decode(aid_b64)
            except Exception:
                problems.append(f"children[{i}]: announce_id is not valid base64url")
                continue
            if not await _announce_exists(store, client, ref):
                problems.append(
                    f"children[{i}]: announce_id {aid_b64} not found locally or via followed gateways"
                )
                continue
            ref_kind = REF_TRACK
        else:
            problems.append(f"children[{i}]: ref_kind must be 'pin' or 'track', got {ref_kind_raw!r}")
            continue

        if quantity < 1:
            problems.append(f"children[{i}]: quantity must be >= 1")
            continue

        out.append(AssemblyChild(ref_kind=ref_kind, ref=ref, quantity=quantity))

    if problems:
        raise UnresolvedChildRef("; ".join(problems))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# §23.6.3 BOM walk
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BomPart:
    """One leaf (non-assembly) entry in a resolved BOM."""

    ref: bytes                     # as published on the AssemblyChild (manifest_root or announce_id)
    ref_kind: str                  # "pin" | "track"
    resolved_announce: bytes | None  # for track leaves, the supersedes-head announce id
    quantity_total: int


@dataclass
class BomCycle:
    """A rejected subtree: `ref` re-encountered an identity already on `path`."""

    ref: bytes
    ref_kind: str
    path: list[bytes] = field(default_factory=list)


@dataclass
class BomResult:
    parts: list[BomPart]
    cycles: list[BomCycle]


async def resolve_track_head(store: PubStore, announce_id: bytes) -> bytes:
    """Resolve a ``track`` ref to the current head of its supersedes chain
    (§23.5, §23.6.1): fetch the referenced announce to learn its author, walk
    that author's feed to build the supersedes ``predecessor -> successor``
    map, and follow it forward from ``announce_id`` to the newest descendant.

    Local-store only (no gateway fallback here — the caller's PubClient
    already hydrated whatever a gateway could serve when validating refs at
    publish time; a BOM walk over an already-published structure works from
    what this node has pinned/followed)."""
    raw = await store.get_announce(announce_id)
    if raw is None:
        raise PubError(ERR_PUB_NOT_SERVED, f"track ref announce not served: {_b64url(announce_id)}")
    ann = PubAnnounce.from_cbor(raw)
    ann.verify(expected_id=announce_id)

    head_raw = await store.get_feed_head(ann.pub)
    if head_raw is None:
        return announce_id  # no known feed for this author beyond the ref itself
    head = FeedHead.from_cbor(head_raw)
    head.verify()

    successor_of: dict[bytes, bytes] = {}
    for raw_e in await store.get_feed_range(ann.pub, 0, head.seq):
        entry = FeedEntry.from_cbor(raw_e)
        a_raw = await store.get_announce(entry.announce)
        if a_raw is None:
            continue
        a = PubAnnounce.from_cbor(a_raw)
        if a.supersedes is not None:
            successor_of[a.supersedes] = entry.announce

    cur = announce_id
    seen = {cur}
    while cur in successor_of:
        nxt = successor_of[cur]
        if nxt in seen:
            break  # malformed supersedes cycle in the raw feed itself — stop, don't loop forever
        seen.add(nxt)
        cur = nxt
    return cur


def _try_decode_structure(raw: bytes) -> AssemblyStructure | None:
    """A resolved address (pin manifest, or a track leaf's canonical bytes)
    is a sub-assembly iff its bytes decode as a well-formed AssemblyStructure
    (§23.6.2) — the only structural signal available once a `pin` ref has
    been stripped of its announce/metadata context."""
    try:
        return AssemblyStructure.from_cbor(raw)
    except Exception:
        return None


async def _load_assembly_structure_for_announce(
    store: PubStore, client: PubClient, announce_id: bytes,
):
    """Return (ArtifactMetadata | None, AssemblyStructure | None) for an
    announce: structure is non-None only when the announce is assembly-kind
    and carries a role=structure format entry."""
    raw = await store.get_announce(announce_id)
    if raw is None:
        raise PubError(ERR_PUB_NOT_SERVED, f"announce not served: {_b64url(announce_id)}")
    ann = PubAnnounce.from_cbor(raw)
    ann.verify(expected_id=announce_id)
    artifact = extract_artifact(ann.meta)
    if artifact is None or artifact.artifact_kind != KIND_ASSEMBLY:
        return artifact, None
    struct_fmt = next((f for f in artifact.formats if f.role == ROLE_STRUCTURE), None)
    if struct_fmt is None:
        return artifact, None
    raw_struct = await client.fetch(struct_fmt.manifest_root)
    return artifact, AssemblyStructure.from_cbor(raw_struct)


async def walk_bom(
    store: PubStore, root_announce_id: bytes, client: PubClient | None = None,
) -> BomResult:
    """§23.6.3 BOM walk rooted at an assembly-kind announce.

    - pin children resolve directly to their manifest bytes;
    - track children resolve to the current supersedes-head (§23.5) of the
      referenced announce;
    - a resolved address that itself decodes as an ``AssemblyStructure`` is
      recursed into; everything else is a BOM leaf;
    - quantities multiply along the path and accumulate per distinct resolved
      content address (dedup, §23.6.3);
    - re-encountering an identity already on the CURRENT DFS path is a fatal
      cycle for that subtree only — recorded in ``cycles``, walk continues
      with sibling children (CAD-10, no infinite recursion, nothing silently
      dropped).
    """
    if client is None:
        client = PubClient(store=store)

    root_artifact, root_structure = await _load_assembly_structure_for_announce(
        store, client, root_announce_id,
    )
    if root_artifact is None or root_artifact.artifact_kind != KIND_ASSEMBLY or root_structure is None:
        raise ProfileError(
            "CAD-3", "BOM walk root must be an assembly-kind artifact with a structure entry",
        )

    parts: dict[bytes, BomPart] = {}
    cycles: list[BomCycle] = []

    async def recurse(
        structure: AssemblyStructure, path: frozenset[bytes], path_list: list[bytes], multiplier: int,
    ) -> None:
        for child in structure.children:
            qty = multiplier * child.quantity

            if child.ref_kind == REF_PIN:
                addr = child.ref
                sub_raw = await client.fetch(addr)
                sub_structure = _try_decode_structure(sub_raw)
                if sub_structure is not None:
                    if addr in path:
                        cycles.append(BomCycle(ref=addr, ref_kind="pin", path=list(path_list)))
                        continue
                    await recurse(sub_structure, path | {addr}, path_list + [addr], qty)
                else:
                    if addr in parts:
                        parts[addr].quantity_total += qty
                    else:
                        parts[addr] = BomPart(
                            ref=addr, ref_kind="pin", resolved_announce=None, quantity_total=qty,
                        )
                continue

            # REF_TRACK
            try:
                head_aid = await resolve_track_head(store, child.ref)
            except PubError:
                # Unresolvable track ref: surfaced as an unresolved leaf, not
                # silently dropped and not fatal to the rest of the walk.
                key = child.ref
                if key in parts:
                    parts[key].quantity_total += qty
                else:
                    parts[key] = BomPart(
                        ref=child.ref, ref_kind="track", resolved_announce=None, quantity_total=qty,
                    )
                continue

            if head_aid in path:
                cycles.append(BomCycle(ref=head_aid, ref_kind="track", path=list(path_list)))
                continue

            sub_artifact, sub_structure = await _load_assembly_structure_for_announce(
                store, client, head_aid,
            )
            if sub_structure is not None:
                await recurse(sub_structure, path | {head_aid}, path_list + [head_aid], qty)
            else:
                if head_aid in parts:
                    parts[head_aid].quantity_total += qty
                else:
                    parts[head_aid] = BomPart(
                        ref=child.ref, ref_kind="track", resolved_announce=head_aid, quantity_total=qty,
                    )

    await recurse(root_structure, frozenset({root_announce_id}), [root_announce_id], 1)
    return BomResult(parts=list(parts.values()), cycles=cycles)


# ═══════════════════════════════════════════════════════════════════════════
# UI convenience: candidate children from the node owner's own feed
# ═══════════════════════════════════════════════════════════════════════════

async def list_own_assembly_candidates(store: PubStore, identity: Identity) -> list[dict]:
    """Best-effort list of the node owner's OWN published announces, newest
    first, suitable as assembly children (§23.7 — workshop state is purely
    client-side; this just reads the local node's own feed, no new cross-
    package coupling). Filters to artifact announces only; deprecated
    revisions are excluded since they are not something a publisher would
    reach for as a fresh child reference."""
    client = PubClient(store=store, identity=None, gateways=[])
    entries = await client.resolve(identity.pub)

    out: list[dict] = []
    for entry in reversed(entries):
        raw = await store.get_announce(entry.announce)
        if raw is None:
            continue
        try:
            ann = PubAnnounce.from_cbor(raw)
            ann.verify(expected_id=entry.announce)
        except PubError:
            continue
        artifact = extract_artifact(ann.meta)
        if artifact is None or artifact.deprecated:
            continue
        out.append({
            "announce_id": entry.announce,
            "name": artifact.name,
            "kind": _KIND_INT_TO_NAME.get(artifact.artifact_kind, str(artifact.artifact_kind)),
        })
    return out
