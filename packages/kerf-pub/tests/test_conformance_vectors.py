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

import hashlib
import json
import os
import warnings
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
    by_name = {v["name"]: v for v in doc["vectors"]}
    # Keying by name silently collapses duplicates, which would under-report the
    # corpus size to every count assertion below. Catch it at load time.
    assert len(by_name) == len(doc["vectors"]), (
        f"duplicate vector name(s) in {VECTORS_PATH}: "
        f"{len(doc['vectors'])} entries collapsed to {len(by_name)}"
    )
    return by_name


VECTORS = _load()

# Every vector in the frozen suite, mapped to the test in THIS module that
# replays it. Written out rather than derived so a vector cannot be added to
# the corpus and quietly go unreplayed, and so a test cannot be deleted while
# the vector it covered still reads as covered. Both directions are checked by
# ``test_all_vectors_are_claimed_by_this_module``.
REPLAYED_BY = {
    "pub_manifest_single_chunk": "test_manifest_root",
    "pub_manifest_three_chunks": "test_manifest_root",
    "pub_manifest_type_incompatibility": "test_manifest_type_incompatibility_vs_sealed_tree",
    "pub_manifest_key5_forbidden": "test_manifest_key5_is_rejected",
    "pub_announce_signing_preimage": "test_announce_signing_preimage_and_signature",
    "pub_announce_id": "test_announce_id_is_content_address_of_signed_object",
    "pub_announce_supersede_same_author_valid": "test_supersede_same_author_accepted",
    "pub_announce_supersede_cross_author_invalid": "test_supersede_cross_author_rejected",
    "pub_feed_entry_chain": "test_feed_entry_ids_and_prev_chain",
    "pub_feed_head_signing_preimage": "test_feed_head_signing_preimage_and_signature",
    "pub_feed_rollback_strict_less_than": "test_feed_rollback_strict_less_than_rejected",
    "pub_feed_equal_seq_identical_tip_idempotent": "test_feed_equal_seq_identical_tip_is_idempotent",
    "pub_feed_equal_seq_different_tip_fork": "test_feed_equal_seq_different_tip_is_a_fork_not_a_rollback",
    "pub_feed_genesis_carries_prev_malformed": "test_malformed_feed_entry_shapes_rejected",
    "pub_feed_nongenesis_missing_prev_malformed": "test_malformed_feed_entry_shapes_rejected",
}

# The corpus size this module is written against. A count, not just a set
# comparison: a resync that both adds and removes a vector keeps the set
# assertion honest only because this number is also pinned.
EXPECTED_VECTOR_COUNT = 15


def vec(name: str) -> dict:
    v = VECTORS.get(name)
    assert v is not None, f"vector {name!r} missing from the frozen suite"
    return v


def test_all_vectors_are_claimed_by_this_module():
    """Fail loudly if the vendored suite grows a vector nobody replays.

    Three assertions, because a growing corpus can under-run three ways: a new
    vector nobody replays, a named replay test that no longer exists, and a
    count that drifts while the set happens to still match.
    """
    missing = set(VECTORS) - set(REPLAYED_BY)
    assert not missing, (
        f"vendored suite grew vector(s) nobody replays: {sorted(missing)}. "
        "Add a replay test and map it in REPLAYED_BY — do not just widen the map."
    )
    stale = set(REPLAYED_BY) - set(VECTORS)
    assert not stale, (
        f"REPLAYED_BY claims vector(s) the corpus no longer has: {sorted(stale)}"
    )

    for name, test_name in sorted(REPLAYED_BY.items()):
        assert test_name in globals(), (
            f"vector {name!r} is mapped to {test_name}(), which does not exist "
            "in this module — the vector is unreplayed."
        )

    assert len(VECTORS) == EXPECTED_VECTOR_COUNT
    assert len(REPLAYED_BY) == EXPECTED_VECTOR_COUNT


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
# the sibling spec checkout does not exist.
#
# The guard that was added after that incident only asserted identity when the
# sibling checkout happened to be reachable, and skipped otherwise — which is to
# say it did nothing in CI, in a release tarball, and on any machine that had not
# also cloned the spec repo. A guard added because of a real incident and then
# made skippable is not a guard.
#
# So it is split in two, by the only question that matters: can this check run
# standalone, from this checkout alone?
#
#   1. ``test_vendored_vectors_are_the_pinned_bytes`` — YES, so it is a HARD
#      ERROR, everywhere, with no skip path. It pins the exact digest and length
#      of the vendored file. Any byte change fails it, including a change to a
#      provenance string that leaves all 15 vectors identical — precisely the
#      drift that actually happened and that nothing caught. Re-syncing from the
#      spec is still a one-line edit here, but it is now a DELIBERATE one that
#      shows up in review, instead of a file quietly becoming something else.
#
#   2. ``test_vendored_vectors_match_the_spec_repo_byte_for_byte`` — NO. It
#      needs a second repository that by design is absent from CI and from every
#      release artifact. Making its absence a hard error would fail kerf's
#      default gate for a reason that is not about kerf, which trains people to
#      ignore it — the same "guard nobody reads" failure by a different route.
#      It is therefore a LOUD skip: it emits a warning that survives into
#      pytest's default warnings summary, names every path it looked at, and
#      states exactly what it did NOT check. It is fail-closed in the one case
#      where intent is unambiguous: if ``KERF_PUB_SPEC_VECTORS`` is set, the
#      path must exist and match, or the test fails.
#
# (1) is what makes (2)'s skip acceptable: the vendored copy is never unchecked,
# only ever cross-checked-against-the-spec or not.

# sha256 + length of tests/vectors/pub_vectors.json as vendored from the DMTAP
# spec repo. UPDATE ONLY when deliberately re-syncing from that repo, in the
# same commit as the re-copied file, and say so in the commit message:
#   shasum -a 256 packages/kerf-pub/tests/vectors/pub_vectors.json
VENDORED_VECTORS_SHA256 = (
    "43a4ab54fee10fea3997f99605e01fb9b7dc9b465da32cd365cd3413c0be81f4"
)
VENDORED_VECTORS_BYTES = 16953

ENV_SPEC_VECTORS = "KERF_PUB_SPEC_VECTORS"

_SPEC_VECTORS_CANDIDATES = (
    Path(__file__).resolve().parents[4] / "vulos" / "dmtap" / "conformance" / "vectors" / "pub_vectors.json",
    Path(__file__).resolve().parents[5] / "vulos" / "dmtap" / "conformance" / "vectors" / "pub_vectors.json",
)


def _spec_vectors_path() -> Path | None:
    for p in _SPEC_VECTORS_CANDIDATES:
        if p.is_file():
            return p
    return None


def test_vendored_vectors_are_the_pinned_bytes():
    """Standalone drift guard: no sibling checkout, no network, no skip path."""
    raw = VECTORS_PATH.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    assert (len(raw), got) == (VENDORED_VECTORS_BYTES, VENDORED_VECTORS_SHA256), (
        f"vendored {VECTORS_PATH} is not the bytes this suite was written against.\n"
        f"  expected {VENDORED_VECTORS_BYTES} bytes, sha256 {VENDORED_VECTORS_SHA256}\n"
        f"  got      {len(raw)} bytes, sha256 {got}\n"
        "This file is INPUT: re-copy it verbatim from the spec repo's "
        "conformance/vectors/pub_vectors.json and update VENDORED_VECTORS_SHA256 / "
        "VENDORED_VECTORS_BYTES in the same commit. Do NOT edit the vendored copy "
        "in place, and do NOT regenerate it here — a corpus a client regenerates "
        "for itself tests nothing but its own arithmetic."
    )


def test_vendored_vectors_match_the_spec_repo_byte_for_byte():
    """The vendored copy MUST equal the spec repo's file exactly, when reachable."""
    override = os.environ.get(ENV_SPEC_VECTORS)
    if override:
        src = Path(override)
        # Explicitly pointed at a spec repo: absence is an error, not a skip.
        assert src.is_file(), (
            f"{ENV_SPEC_VECTORS}={override} does not name a readable file. It was "
            "set deliberately, so this is a hard error rather than a skip."
        )
    else:
        src = _spec_vectors_path()

    if src is None:
        searched = "\n".join(f"    {p}" for p in _SPEC_VECTORS_CANDIDATES)
        reason = (
            "DRIFT CHECK NOT RUN: the DMTAP spec repo was not found alongside this "
            "checkout, so the vendored conformance corpus was NOT compared against "
            "its source.\n"
            f"  not checked: {VECTORS_PATH} == <dmtap>/conformance/vectors/pub_vectors.json\n"
            f"  searched:\n{searched}\n"
            f"  to run it here: {ENV_SPEC_VECTORS}=/path/to/dmtap/conformance/vectors/"
            "pub_vectors.json pytest ...\n"
            "  what DID run: test_vendored_vectors_are_the_pinned_bytes pins the "
            "vendored file's sha256, so the copy cannot change unnoticed — but "
            "whether it still matches the spec repo is unverified here."
        )
        # A pytest skip is invisible without -rs; a warning lands in the default
        # summary. This skip must be seen, because the guard exists on account of
        # a drift that went unseen.
        warnings.warn(reason, UserWarning, stacklevel=2)
        pytest.skip(reason)

    assert VECTORS_PATH.read_bytes() == src.read_bytes(), (
        f"vendored {VECTORS_PATH} has drifted from {src}.\n"
        "Re-copy the spec repo's file verbatim — do NOT edit the vendored copy, "
        "and do NOT regenerate it here: it is INPUT to this suite, and a corpus "
        "that a client regenerates for itself tests nothing but its own arithmetic."
    )
