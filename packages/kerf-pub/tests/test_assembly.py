"""§23.6 assembly support: child-ref validation + the BOM walk (kerf_pub.assembly).

Pure InMemoryPubStore tests — no DB, no network — mirroring test_client.py's
style. The HTTP-layer happy path / unresolvable-ref / BOM-endpoint tests live
in test_router_local.py (they need a real project, so they use the Postgres
fixtures already set up there).
"""

from __future__ import annotations

import time

import pytest

from kerf_pub import (
    ArtifactFormat, ArtifactMetadata, AssemblyChild, AssemblyStructure,
    Identity, InMemoryPubStore, PubClient, PubManifest, ProfileError, PubError,
    Units, embed_artifact,
)
from kerf_pub.objects import (
    FMT_ASSEMBLY_STRUCTURE, FMT_NATIVE, KIND_ASSEMBLY, KIND_PART,
    PubAnnounce, REF_PIN, REF_TRACK, ROLE_CANONICAL, ROLE_STRUCTURE,
)
from kerf_pub.assembly import (
    UnresolvedChildRef,
    build_assembly_children,
    list_own_assembly_candidates,
    resolve_track_head,
    walk_bom,
)


def _root(b: bytes) -> bytes:
    return PubManifest.build(b).id


async def _publish_part(client: PubClient, name: str, body: bytes) -> bytes:
    am = ArtifactMetadata(
        name=name, description="", artifact_kind=KIND_PART,
        formats=[ArtifactFormat(FMT_NATIVE, _root(body), ROLE_CANONICAL)],
        units=Units(length_unit="mm"), license="MIT",
    )
    return await client.publish({"part.native": body}, am)


async def _publish_assembly(client: PubClient, name: str, children: list[AssemblyChild]) -> bytes:
    structure = AssemblyStructure(children=children)
    struct_bytes = structure.to_cbor()
    am = ArtifactMetadata(
        name=name, description="", artifact_kind=KIND_ASSEMBLY,
        formats=[ArtifactFormat(FMT_ASSEMBLY_STRUCTURE, _root(struct_bytes), ROLE_STRUCTURE)],
        units=Units(length_unit="mm"), license="MIT",
    )
    return await client.publish({"structure.cbor": struct_bytes}, am)


async def _publish_with_supersedes(
    client: PubClient, name: str, artifact_kind: int, files: dict[str, bytes],
    formats: list[ArtifactFormat], supersedes: bytes,
) -> bytes:
    """Sign+append a revision that supersedes a prior announce (§22.3.4) — a
    capability `PubClient.publish()` doesn't expose (it always publishes a
    fresh seq-0-or-append entry with no supersedes), so this test helper
    replicates its internals with `supersedes` wired in."""
    roots: list[bytes] = []
    for data in files.values():
        manifest = PubManifest.build(data)
        await client.store.put_manifest(manifest.id, manifest.to_cbor())
        for h, chunk in zip(manifest.chunks, PubManifest.split_chunks(data, manifest.chunk_sz)):
            await client.store.put_chunk(h, chunk)
        roots.append(manifest.id)

    am = ArtifactMetadata(
        name=name, description="", artifact_kind=artifact_kind, formats=formats,
        units=Units(length_unit="mm"), license="MIT",
    )
    am.validate()
    meta = embed_artifact({}, am)

    announce = PubAnnounce(
        pub=client.identity.pub, roots=roots, ts=int(time.time() * 1000),
        meta=meta, supersedes=supersedes,
    ).sign(client.identity)
    aid = announce.id
    await client.store.put_announce(aid, announce.to_cbor())
    await client.store.set_pinned(aid, True)
    await client._append_own_feed(aid)
    return aid


# ---------------------------------------------------------------------------
# build_assembly_children — publish-time child validation
# ---------------------------------------------------------------------------

async def test_build_assembly_children_happy_path():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn, gateways=[])

    part_aid = await _publish_part(client, "Bolt", b"bolt-body")
    bolt_root = _root(b"bolt-body")

    children = await build_assembly_children(store, client, [
        {"ref_kind": "pin", "manifest_root": _b64(bolt_root), "quantity": 4},
        {"ref_kind": "track", "announce_id": _b64(part_aid), "quantity": 1},
    ])
    assert len(children) == 2
    assert children[0].ref_kind == REF_PIN and children[0].ref == bolt_root and children[0].quantity == 4
    assert children[1].ref_kind == REF_TRACK and children[1].ref == part_aid and children[1].quantity == 1


async def test_build_assembly_children_unresolved_ref_raises():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn, gateways=[])

    fake_announce = b"\x12" + b"\x00" * 32
    with pytest.raises(UnresolvedChildRef) as ei:
        await build_assembly_children(store, client, [
            {"ref_kind": "track", "announce_id": _b64(fake_announce), "quantity": 1},
        ])
    assert _b64(fake_announce) in str(ei.value)


async def test_build_assembly_children_empty_rejected():
    store = InMemoryPubStore()
    client = PubClient(store=store, identity=Identity.generate(), gateways=[])
    with pytest.raises(UnresolvedChildRef):
        await build_assembly_children(store, client, [])


async def test_build_assembly_children_bad_ref_kind_rejected():
    store = InMemoryPubStore()
    client = PubClient(store=store, identity=Identity.generate(), gateways=[])
    with pytest.raises(UnresolvedChildRef):
        await build_assembly_children(store, client, [
            {"ref_kind": "bogus", "quantity": 1},
        ])


def _b64(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# walk_bom — nested assemblies, quantity multiplication, dedup
# ---------------------------------------------------------------------------

async def test_bom_walk_nested_quantity_multiplication_and_dedup():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn, gateways=[])

    bolt_body = b"bolt-body"
    bolt_root = _root(bolt_body)
    await _publish_part(client, "Bolt", bolt_body)

    sub_aid = await _publish_assembly(client, "SubAssy", [
        AssemblyChild(ref_kind=REF_PIN, ref=bolt_root, quantity=2),
    ])

    root_aid = await _publish_assembly(client, "RootAssy", [
        AssemblyChild(ref_kind=REF_TRACK, ref=sub_aid, quantity=3),
        AssemblyChild(ref_kind=REF_PIN, ref=bolt_root, quantity=1),
    ])

    result = await walk_bom(store, root_aid, client)
    assert result.cycles == []
    assert len(result.parts) == 1
    part = result.parts[0]
    assert part.ref == bolt_root
    assert part.ref_kind == "pin"
    # 3 (SubAssy instances) * 2 (bolts/SubAssy) + 1 (direct bolt) = 7, deduped
    # to a single BOM line by content address (§23.6.3).
    assert part.quantity_total == 7


async def test_bom_walk_root_must_be_assembly():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn, gateways=[])
    part_aid = await _publish_part(client, "Bolt", b"just a part")
    with pytest.raises(ProfileError):
        await walk_bom(store, part_aid, client)


# ---------------------------------------------------------------------------
# resolve_track_head — forward supersedes resolution (§23.5)
# ---------------------------------------------------------------------------

async def test_resolve_track_head_follows_supersedes_chain():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn, gateways=[])

    body_v1 = b"part v1"
    aid_v1 = await _publish_part(client, "Widget v1", body_v1)

    body_v2 = b"part v2"
    aid_v2 = await _publish_with_supersedes(
        client, "Widget v2", KIND_PART, {"part.native": body_v2},
        [ArtifactFormat(FMT_NATIVE, _root(body_v2), ROLE_CANONICAL)],
        supersedes=aid_v1,
    )

    assert await resolve_track_head(store, aid_v1) == aid_v2
    # the head itself resolves to itself (no further descendant)
    assert await resolve_track_head(store, aid_v2) == aid_v2


async def test_resolve_track_head_no_feed_returns_ref_itself():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn, gateways=[])
    aid = await _publish_part(client, "Solo", b"solo body")
    assert await resolve_track_head(store, aid) == aid


async def test_resolve_track_head_unresolvable_raises_pub_error():
    store = InMemoryPubStore()
    with pytest.raises(PubError):
        await resolve_track_head(store, b"\x12" + b"\xAB" * 32)


# ---------------------------------------------------------------------------
# cycle rejection: track-ref cycle across two assemblies (§23.6.3, CAD-10)
# ---------------------------------------------------------------------------

async def test_bom_walk_rejects_track_cycle_across_two_assemblies():
    store = InMemoryPubStore()
    idn_a = Identity.generate()
    idn_b = Identity.generate()
    client_a = PubClient(store=store, identity=idn_a, gateways=[])
    client_b = PubClient(store=store, identity=idn_b, gateways=[])

    # B publishes an initial (non-assembly) revision.
    b1_body = b"b-as-a-part"
    b1_aid = await _publish_part(client_b, "B-as-part", b1_body)

    # A publishes an assembly tracking B's current (still non-assembly) head.
    a1_aid = await _publish_assembly(client_a, "A", [
        AssemblyChild(ref_kind=REF_TRACK, ref=b1_aid, quantity=1),
    ])

    # B's publisher later republishes B as an assembly that tracks BACK to A
    # — malicious or accidental, but a conformant walker must not recurse
    # forever or silently drop it (CAD-10).
    b2_structure = AssemblyStructure(children=[
        AssemblyChild(ref_kind=REF_TRACK, ref=a1_aid, quantity=1),
    ])
    b2_struct_bytes = b2_structure.to_cbor()
    await _publish_with_supersedes(
        client_b, "B-as-assembly", KIND_ASSEMBLY, {"structure.cbor": b2_struct_bytes},
        [ArtifactFormat(FMT_ASSEMBLY_STRUCTURE, _root(b2_struct_bytes), ROLE_STRUCTURE)],
        supersedes=b1_aid,
    )

    result = await walk_bom(store, a1_aid, client_a)
    assert result.parts == []
    assert len(result.cycles) == 1
    cycle = result.cycles[0]
    assert cycle.ref_kind == "track"
    assert cycle.ref == a1_aid
    assert a1_aid in cycle.path


# ---------------------------------------------------------------------------
# list_own_assembly_candidates
# ---------------------------------------------------------------------------

async def test_list_own_assembly_candidates_filters_non_artifact_and_deprecated():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn, gateways=[])

    await _publish_part(client, "Bracket", b"bracket body")
    # a plain (non-artifact) public blob is not a candidate
    await client.publish({"readme.txt": b"hello"})

    candidates = await list_own_assembly_candidates(store, idn)
    assert len(candidates) == 1
    assert candidates[0]["name"] == "Bracket"
    assert candidates[0]["kind"] == "part"
