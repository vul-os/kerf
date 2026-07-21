"""Replay the SHARED DMTAP-PUB §22 conformance vectors against kerf-pub.

``tests/vectors/pub_vectors.json`` is a byte-for-byte copy of the frozen
``conformance/vectors/pub_vectors.json`` in the DMTAP spec repo — the same file
the Rust implementation is held to. That claim is ENFORCED, not asserted: see
``test_vendored_vectors_match_the_spec_repo_byte_for_byte`` at the end of this
file. It was unenforced until 2026-07-21 and had already drifted. It is vendored (not read from a sibling
checkout) so this suite is self-contained in CI; it is INPUT, never regenerated
here. Its expectations were produced by the spec repo's generator and
independently cross-checked there by a second from-scratch implementation.

This is the two-implementations rule made mechanical: kerf-pub is a conformant
§22 implementation only insofar as it reproduces these exact bytes. Every
vector is asserted through kerf-pub's ORDINARY public API — ``hashing``,
``objects``, ``identity``, ``client`` — never through a parallel path written
to satisfy the test.

Applicability: all 15 vectors apply to kerf-pub and all 15 are replayed here.
There is no PUB-server/client-UX vector in this suite to skip (contrast the
Rust implementation's client-UX attestation skip, which lives in a different
suite).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kerf_pub import cbor, hashing
from kerf_pub.client import check_head_watermark
from kerf_pub.errors import (
    PubError,
    ERR_PUB_MANIFEST_KEY_PRESENT,
    ERR_PUB_FEED_ROLLBACK,
    ERR_PUB_FEED_CHAIN_BROKEN,
    ERR_PUB_SUPERSEDE_INVALID,
)
from kerf_pub.identity import ed25519_pub, ed25519_sign, ed25519_verify
from kerf_pub.objects import (
    DS_ANNOUNCE,
    DS_FEED,
    FeedEntry,
    FeedHead,
    PubAnnounce,
    PubManifest,
)

VECTORS_PATH = Path(__file__).parent / "vectors" / "pub_vectors.json"


def _load() -> dict[str, dict]:
    doc = json.loads(VECTORS_PATH.read_text())
    assert doc["format"] == "dmtap-conformance-vectors/1"
    return {v["name"]: v for v in doc["vectors"]}


VECTORS = _load()


def vec(name: str) -> dict:
    v = VECTORS.get(name)
    assert v is not None, f"vector {name!r} missing from the frozen suite"
    return v


def test_all_vectors_are_claimed_by_this_module():
    """Fail loudly if the vendored suite grows a vector nobody replays."""
    replayed = {
        "pub_manifest_single_chunk",
        "pub_manifest_three_chunks",
        "pub_manifest_type_incompatibility",
        "pub_manifest_key5_forbidden",
        "pub_announce_signing_preimage",
        "pub_announce_id",
        "pub_announce_supersede_same_author_valid",
        "pub_announce_supersede_cross_author_invalid",
        "pub_feed_entry_chain",
        "pub_feed_head_signing_preimage",
        "pub_feed_rollback_strict_less_than",
        "pub_feed_equal_seq_identical_tip_idempotent",
        "pub_feed_equal_seq_different_tip_fork",
        "pub_feed_genesis_carries_prev_malformed",
        "pub_feed_nongenesis_missing_prev_malformed",
    }
    assert set(VECTORS) == replayed, "vendored vector suite changed — update this module"
    assert len(VECTORS) == 15


# ── §18.1.5 content addressing ────────────────────────────────────────────────

def test_write_digest_is_blake3_256_under_prefix_0x1e():
    """The v0-REQUIRED digest. If this flips, every vector below flips with it."""
    assert hashing.HASH_PREFIX == hashing.PREFIX_BLAKE3_256 == 0x1E
    assert hashing.mhash(b"")[0] == 0x1E


# ── §22.2.2 PubManifest Merkle root ───────────────────────────────────────────

@pytest.mark.parametrize(
    "name", ["pub_manifest_single_chunk", "pub_manifest_three_chunks"]
)
def test_manifest_root(name):
    v = vec(name)
    chunks = [bytes.fromhex(h) for h in v["input"]["plaintext_chunks_hex"]]

    got_hashes = [hashing.mhash(c) for c in chunks]
    assert [h.hex() for h in got_hashes] == v["expected"]["chunk_hashes_hex"]

    assert hashing.merkle_root(got_hashes).hex() == v["expected"]["id_hex"]

    # And the same root through the object model's own builder.
    m = PubManifest.build(b"".join(chunks), chunk_sz=max(len(c) for c in chunks))
    if len(chunks) == 1:
        assert m.id.hex() == v["expected"]["id_hex"]
    m2 = PubManifest(
        id=hashing.merkle_root(got_hashes), size=sum(len(c) for c in chunks),
        chunk_sz=max(len(c) for c in chunks), chunks=got_hashes,
    )
    m2.verify()  # recomputes the DS-tagged root and must agree with `id`


def test_manifest_type_incompatibility_vs_sealed_tree():
    """§22.2.3: the DS tag alone must keep a public root off a sealed root."""
    v = vec("pub_manifest_type_incompatibility")
    hs = [bytes.fromhex(h) for h in v["input"]["chunk_hashes_hex"]]

    public_root = hashing.merkle_root(hs)
    assert public_root.hex() == v["expected"]["public_root_hex"]

    # The §18.9.5 BARE tree (no DS fold) over the identical h_i list, computed
    # here — kerf-pub has no reason to expose it; it exists only to show the
    # divergence is caused by the DS tag, not by different inputs.
    def bare(hashes: list[bytes]) -> bytes:
        d = hashing._digest_with  # same BLAKE3-256 as the public tree
        if len(hashes) == 1:
            return d(0x1E, b"\x00" + hashes[0])
        k = 1
        while k << 1 < len(hashes):
            k <<= 1
        return d(0x1E, b"\x01" + bare(hashes[:k]) + bare(hashes[k:]))

    sealed_root = bytes([0x1E]) + bare(hs)
    assert sealed_root.hex() == v["expected"]["sealed_style_root_hex"]
    assert (public_root != sealed_root) is v["expected"]["roots_differ"] is True


def test_manifest_key5_is_rejected():
    v = vec("pub_manifest_key5_forbidden")
    with pytest.raises(PubError) as ei:
        PubManifest.from_cbor(bytes.fromhex(v["input"]["cbor_hex"]))
    assert ei.value.code == ERR_PUB_MANIFEST_KEY_PRESENT == int(
        v["expected"]["error_code"], 16
    )
    # The same manifest WITHOUT key 5 must decode and self-verify — proving the
    # rejection is about key 5 and not about the encoding generally.
    ok = PubManifest.from_cbor(
        bytes.fromhex(v["input"]["valid_cbor_hex_for_reference"])
    )
    ok.verify()
    assert ok.id.hex() == vec("pub_manifest_single_chunk")["expected"]["id_hex"]


# ── §22.3 pub_announce ────────────────────────────────────────────────────────

def _announce_from_body(body: dict) -> PubAnnounce:
    return PubAnnounce(
        v=body[1], suite=body[2], pub=body[3], roots=list(body[4]), meta=body[5],
        supersedes=body.get(6), ts=body[7], signer=body[8], sig=body.get(9),
    )


def test_announce_signing_preimage_and_signature():
    v = vec("pub_announce_signing_preimage")
    seed = bytes.fromhex(v["input"]["seed_hex"])
    msg = bytes.fromhex(v["input"]["msg_hex"])

    assert DS_ANNOUNCE == bytes.fromhex(v["input"]["domain_hex"])
    assert ed25519_pub(seed).hex() == v["expected"]["pubkey_hex"]

    # kerf-pub's own deterministic CBOR must reproduce the preimage byte-for-byte.
    ann = _announce_from_body(cbor.decode(msg))
    assert ann._signing_preimage() == DS_ANNOUNCE + msg

    sig = ed25519_sign(seed, ann._signing_preimage())
    assert sig.hex() == v["expected"]["sig_hex"]
    assert ed25519_verify(ann.signer, sig, ann._signing_preimage())


def test_announce_id_is_content_address_of_signed_object():
    v = vec("pub_announce_id")
    raw = bytes.fromhex(v["input"]["bytes_hex"])
    ann = PubAnnounce.from_cbor(raw)
    assert ann.to_cbor() == raw  # round-trips to the identical canonical bytes
    assert ann.id.hex() == v["expected"]["id_hex"]
    ann.verify(expected_id=ann.id)  # full §22.3.3 chain incl. sig under signer


def test_supersede_same_author_accepted():
    v = vec("pub_announce_supersede_same_author_valid")
    succ = PubAnnounce.from_cbor(bytes.fromhex(v["input"]["successor_cbor_hex"]))
    succ.verify()
    assert succ.pub.hex() == v["input"]["successor_pub_hex"]
    assert succ.supersedes.hex() == v["input"]["successor_supersedes_hex"]

    pred = PubAnnounce.from_cbor(bytes.fromhex(vec("pub_announce_id")["input"]["bytes_hex"]))
    assert pred.id.hex() == v["input"]["predecessor_announce_id_hex"]
    succ.verify_supersedes(pred)  # accept


def test_supersede_cross_author_rejected():
    v = vec("pub_announce_supersede_cross_author_invalid")
    succ = PubAnnounce.from_cbor(bytes.fromhex(v["input"]["successor_cbor_hex"]))
    succ.verify()  # B's announce is itself well-formed and correctly signed
    pred = PubAnnounce.from_cbor(bytes.fromhex(vec("pub_announce_id")["input"]["bytes_hex"]))
    assert pred.pub != succ.pub

    with pytest.raises(PubError) as ei:
        succ.verify_supersedes(pred)
    assert ei.value.code == ERR_PUB_SUPERSEDE_INVALID == int(
        v["expected"]["error_code"], 16
    )


# ── §22.4 author feeds ────────────────────────────────────────────────────────

def test_feed_entry_ids_and_prev_chain():
    v = vec("pub_feed_entry_chain")
    entries = [FeedEntry.from_cbor(bytes.fromhex(h))
               for h in v["input"]["entries_cbor_hex"]]

    assert [e.id.hex() for e in entries] == v["expected"]["entry_ids_hex"]
    assert entries[0].prev is None and entries[0].seq == 0
    for prev, cur in zip(entries, entries[1:]):
        assert cur.seq == prev.seq + 1
        assert cur.prev == prev.id
    assert v["expected"]["prev_chain_valid"] is True


def test_feed_head_signing_preimage_and_signature():
    v = vec("pub_feed_head_signing_preimage")
    seed = bytes.fromhex(v["input"]["seed_hex"])
    msg = bytes.fromhex(v["input"]["msg_hex"])

    assert DS_FEED == bytes.fromhex(v["input"]["domain_hex"])
    assert ed25519_pub(seed).hex() == v["expected"]["pubkey_hex"]

    body = cbor.decode(msg)
    head = FeedHead(v=body[1], suite=body[2], pub=body[3], seq=body[4],
                    tip=body[5], ts=body[6], signer=body[7])
    assert head._signing_preimage() == DS_FEED + msg

    sig = ed25519_sign(seed, head._signing_preimage())
    assert sig.hex() == v["expected"]["sig_hex"]

    head.sig = sig
    head.verify()  # full §22.4.1 head verification over kerf-pub's own encoding
    # The signed tip is entry1, which commits transitively to entry0 via `prev`.
    assert head.tip.hex() == vec("pub_feed_entry_chain")["expected"]["entry_ids_hex"][1]


def test_feed_rollback_strict_less_than_rejected():
    v = vec("pub_feed_rollback_strict_less_than")
    with pytest.raises(PubError) as ei:
        check_head_watermark(
            accepted_seq=v["input"]["last_accepted_seq"], accepted_tip=None,
            presented_seq=v["input"]["presented_seq"],
            presented_tip=bytes.fromhex(v["input"]["presented_tip_hex"]),
        )
    assert ei.value.code == ERR_PUB_FEED_ROLLBACK == int(
        v["expected"]["error_code"], 16
    )


def test_feed_equal_seq_identical_tip_is_idempotent():
    v = vec("pub_feed_equal_seq_identical_tip_idempotent")
    # Must NOT raise: equal seq is not a rollback.
    check_head_watermark(
        accepted_seq=v["input"]["last_accepted_seq"],
        accepted_tip=bytes.fromhex(v["input"]["last_accepted_tip_hex"]),
        presented_seq=v["input"]["presented_seq"],
        presented_tip=bytes.fromhex(v["input"]["presented_tip_hex"]),
    )


def test_feed_equal_seq_different_tip_is_a_fork_not_a_rollback():
    v = vec("pub_feed_equal_seq_different_tip_fork")
    # The alternate entry really does address to the presented tip.
    alt = FeedEntry.from_cbor(bytes.fromhex(v["input"]["presented_tip_cbor_hex"]))
    assert alt.id.hex() == v["input"]["presented_tip_hex"]

    with pytest.raises(PubError) as ei:
        check_head_watermark(
            accepted_seq=v["input"]["last_accepted_seq"],
            accepted_tip=bytes.fromhex(v["input"]["last_accepted_tip_hex"]),
            presented_seq=v["input"]["presented_seq"],
            presented_tip=alt.id,
        )
    assert ei.value.code == ERR_PUB_FEED_CHAIN_BROKEN == int(
        v["expected"]["error_code"], 16
    )
    assert ei.value.code != ERR_PUB_FEED_ROLLBACK  # equivocation is never 0x0907


@pytest.mark.parametrize("name", [
    "pub_feed_genesis_carries_prev_malformed",
    "pub_feed_nongenesis_missing_prev_malformed",
])
def test_malformed_feed_entry_shapes_rejected(name):
    v = vec(name)
    with pytest.raises(PubError) as ei:
        FeedEntry.from_cbor(bytes.fromhex(v["input"]["cbor_hex"]))
    assert ei.value.code == ERR_PUB_FEED_CHAIN_BROKEN == int(
        v["expected"]["error_code"], 16
    )


# ── vendored-copy drift guard ────────────────────────────────────────────────
# The docstring above asserts this file is a byte-for-byte copy of the spec
# repo's. Nothing enforced that, and it had already drifted: the spec corrected
# the corpus's `generated_by` provenance string and the vendored copy kept the
# old text. The 15 vectors themselves were identical, so no test failed and no
# one noticed — which is exactly how a vendored artifact goes stale in a way that
# eventually DOES matter, silently, one resync at a time.
#
# Vendoring is still right: the copy keeps this suite self-contained in CI, where
# the sibling spec checkout does not exist. So the guard is conditional — it
# asserts identity when the source is reachable and skips loudly when it is not,
# rather than pretending a check ran.

_SPEC_VECTORS_CANDIDATES = (
    Path(__file__).resolve().parents[4] / "vulos" / "dmtap" / "conformance" / "vectors" / "pub_vectors.json",
    Path(__file__).resolve().parents[5] / "vulos" / "dmtap" / "conformance" / "vectors" / "pub_vectors.json",
)


def _spec_vectors_path() -> Path | None:
    for p in _SPEC_VECTORS_CANDIDATES:
        if p.is_file():
            return p
    return None


def test_vendored_vectors_match_the_spec_repo_byte_for_byte():
    """The vendored copy MUST equal the spec repo's file exactly, when reachable."""
    src = _spec_vectors_path()
    if src is None:
        pytest.skip(
            "dmtap spec repo not found alongside this checkout — drift cannot be "
            "checked here. This is a SKIP, not a pass: the vendored copy is "
            "unverified in this environment."
        )
    assert VECTORS_PATH.read_bytes() == src.read_bytes(), (
        f"vendored {VECTORS_PATH} has drifted from {src}.\n"
        "Re-copy the spec repo's file verbatim — do NOT edit the vendored copy, "
        "and do NOT regenerate it here: it is INPUT to this suite, and a corpus "
        "that a client regenerates for itself tests nothing but its own arithmetic."
    )
