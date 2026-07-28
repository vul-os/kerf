"""PubAnnounce: sign/verify, id bind, bad sig, supersedes same-author (§22.3)."""

import pytest

from kerf_pub import Identity, PubAnnounce, PubManifest, PubError
from kerf_pub import cbor, hashing
from kerf_pub.errors import (
    ERR_PUB_ANNOUNCE_SIG_INVALID,
    ERR_PUB_ANNOUNCE_ID_MISMATCH,
    ERR_PUB_SUPERSEDE_INVALID,
    ERR_PUB_UNSUPPORTED_VERSION,
)


def _announce(idn, roots=None):
    roots = roots or [PubManifest.build(b"blob").id]
    return PubAnnounce(pub=idn.pub, roots=roots, ts=1_700_000_000_000,
                       meta={}).sign(idn)


def test_sign_verify_roundtrip():
    idn = Identity.generate()
    a = _announce(idn)
    a.verify(expected_id=a.id)
    b = PubAnnounce.from_cbor(a.to_cbor())
    b.verify(expected_id=a.id)
    assert b.id == a.id
    assert b.signer == idn.pub == b.pub


def test_announce_id_is_derived_from_the_signature_excluded_body():
    """§22.3.1: announce_id = 0x1e ‖ BLAKE3-256(det_cbor(PubAnnounce ∖ {9})).

    Key 9 (``sig``) is EXCLUDED. This asserted the opposite until 2026-07-28,
    matching kerf-pub's then-implementation of the formula the spec has since
    withdrawn (§1.3: no identifier may be derived from a malleable signature).
    """
    idn = Identity.generate()
    a = _announce(idn)
    body = cbor.encode(a._body_map())
    assert 9 not in cbor.decode(body)
    assert a.id == hashing.mhash(body)
    assert a.id != hashing.mhash(a.to_cbor())  # NOT the complete signed object


def test_announce_id_is_stable_across_a_different_signature():
    """The §1.3 property the exclusion exists for: a second valid-shaped sig over
    the same body must not mint a second announce_id."""
    idn = Identity.generate()
    a = _announce(idn)
    before = a.id
    a.sig = bytes(64)  # a different 64-byte sig value, same body
    assert a.id == before


def test_bad_signature_rejected():
    idn = Identity.generate()
    a = _announce(idn)
    a.sig = bytes(64)  # zeroed signature
    with pytest.raises(PubError) as ei:
        a.verify()
    assert ei.value.code == ERR_PUB_ANNOUNCE_SIG_INVALID


def test_wrong_signer_rejected():
    idn = Identity.generate()
    other = Identity.generate()
    a = _announce(idn)
    a.signer = other.pub  # v1: signer must equal pub (no DeviceCert chains)
    with pytest.raises(PubError) as ei:
        a.verify()
    assert ei.value.code == ERR_PUB_ANNOUNCE_SIG_INVALID


def test_id_mismatch_rejected():
    idn = Identity.generate()
    a = _announce(idn)
    wrong = bytes([hashing.HASH_PREFIX]) + bytes(32)
    with pytest.raises(PubError) as ei:
        a.verify(expected_id=wrong)
    assert ei.value.code == ERR_PUB_ANNOUNCE_ID_MISMATCH


def test_tampered_body_breaks_sig():
    idn = Identity.generate()
    a = _announce(idn)
    raw = cbor.decode(a.to_cbor())
    raw[7] = raw[7] + 1  # bump ts after signing
    tampered = PubAnnounce.from_cbor(cbor.encode(raw))
    with pytest.raises(PubError) as ei:
        tampered.verify()
    assert ei.value.code == ERR_PUB_ANNOUNCE_SIG_INVALID


def test_supersedes_same_author_ok():
    idn = Identity.generate()
    orig = _announce(idn)
    rev = PubAnnounce(pub=idn.pub, roots=orig.roots, ts=1_700_000_100_000,
                      meta={}, supersedes=orig.id).sign(idn)
    rev.verify(expected_id=rev.id)
    rev.verify_supersedes(orig)  # same pub → ok


def test_supersedes_other_author_rejected():
    a_id = Identity.generate()
    b_id = Identity.generate()
    orig = _announce(a_id)
    rev = PubAnnounce(pub=b_id.pub, roots=orig.roots, ts=1_700_000_100_000,
                      meta={}, supersedes=orig.id).sign(b_id)
    with pytest.raises(PubError) as ei:
        rev.verify_supersedes(orig)  # b supersedes a's announce → invalid
    assert ei.value.code == ERR_PUB_SUPERSEDE_INVALID


def test_unsupported_version_rejected():
    idn = Identity.generate()
    a = _announce(idn)
    a.v = 1
    a.sign(idn)  # re-sign so only the version is "wrong"
    with pytest.raises(PubError) as ei:
        a.verify()
    assert ei.value.code == ERR_PUB_UNSUPPORTED_VERSION
