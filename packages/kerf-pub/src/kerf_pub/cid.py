"""CIDv1 (raw codec) derivation for DMTAP-PUB chunk hashes.

This is pure address translation — no network, no dependencies beyond
:mod:`kerf_pub.hashing` — used by :mod:`kerf_pub.ipfs` to name a kerf-pub
chunk the way an IPFS gateway expects it (the "IPFS as a later fetch-adapter,
never ground truth" ADR posture: IPFS never becomes a source of truth for
kerf-pub bytes, it is just another place the *same*, independently-verified
bytes might be sitting).

**Why a kerf-pub chunk hash is already (almost) a multihash.** A kerf-pub
chunk address ``h_i`` (§22.2.2) is ``HASH_PREFIX ‖ digest`` — for the
shipped SHA2-256 build, ``HASH_PREFIX = 0x12``. The multiformats `multihash
table <https://github.com/multiformats/multicodec>`_ assigns SHA2-256 the
*same* code, ``0x12``. That is not a coincidence kerf relies on by accident —
§23 Appendix A of the DMTAP-PUB spec explicitly sanctions the SHA2-256 prefix
as the interop seam with external content-addressed stores (Git-LFS, and by
the same construction, IPFS). A real multihash is:

    multihash = varint(code) ‖ varint(digest_length) ‖ digest

which is ``h_i`` with exactly one thing missing: the digest-length varint.
For SHA2-256 that length is a constant 32 (``0x20``), so completing the
multihash is a pure, lossless, deterministic insertion — no information is
invented, nothing about the digest is reinterpreted.

**From multihash to CIDv1.** A CIDv1 wraps a multihash with a version varint
and a multicodec (content-type) varint naming *how to interpret the bytes the
multihash addresses*:

    cid_bytes = varint(version=1) ‖ varint(codec) ‖ multihash

kerf-pub chunks are opaque plaintext bytes with no internal DAG structure (a
manifest is what supplies structure, and manifests are NOT IPLD — see
:mod:`kerf_pub.ipfs`), so the correct codec is ``raw`` (``0x55``), the
multicodec for "just bytes, no links".

**Textual form.** The default IPFS gateway path segment is the *multibase*
string form: a one-character base prefix followed by the encoded bytes.
Multibase code ``'b'`` is RFC 4648 base32, lowercase alphabet, **no**
padding — which is why virtually every CIDv1 string you have ever seen in
the wild starts with the letter ``b``. This module implements that base32
variant itself (no ``base64`` module dependency) since it is the one
multibase encoding kerf-pub needs.

Every value produced by :func:`cid_for_chunk` happens to need only
single-byte varints (version 1, codec 0x55, multihash code 0x12, and length
32 are all < 0x80) — but :func:`_varint` is implemented as general unsigned
LEB128 so a future digest choice (e.g. BLAKE3, prefix ``0x1e`` — also < 0x80,
so still single-byte) keeps working without a second look at this file.
"""

from __future__ import annotations

from . import hashing

# ── RFC 4648 base32, lowercase, no padding — the multibase 'b' encoding ───────
_B32_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"


def _b32_encode_nopad(data: bytes) -> str:
    """Base32-encode ``data`` (RFC 4648 §6, lowercase, unpadded)."""
    bits = 0
    value = 0
    out: list[str] = []
    for byte in data:
        value = (value << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append(_B32_ALPHABET[(value >> bits) & 0x1F])
    if bits > 0:
        out.append(_B32_ALPHABET[(value << (5 - bits)) & 0x1F])
    return "".join(out)


def _varint(n: int) -> bytes:
    """Unsigned LEB128 varint (the multiformats varint convention)."""
    if n < 0:
        raise ValueError("varint must be non-negative")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


# multiformats registry values this module produces (multicodec.csv).
CID_VERSION_1 = 0x01
CODEC_RAW = 0x55        # "raw" — opaque bytes, no IPLD links
MULTIBASE_BASE32 = "b"  # RFC 4648 base32, lowercase, no padding


def cid_for_chunk(h: bytes) -> str:
    """CIDv1 (raw codec, base32 multibase) naming the kerf-pub chunk ``h``.

    ``h`` is a kerf-pub chunk hash (``HASH_PREFIX ‖ digest``, §22.2.2,
    33 bytes for the shipped SHA2-256 build) — exactly the value carried in
    ``PubManifest.chunks``. Chunk-bytes addressing ONLY: manifests,
    announces, and feed entries are kerf-object deterministic CBOR, not
    IPLD, and are never given a CID (see :mod:`kerf_pub.ipfs`).
    """
    hashing.check_hash(h)
    code = h[0]
    digest = h[1:]
    multihash = _varint(code) + _varint(len(digest)) + digest
    cid_bytes = _varint(CID_VERSION_1) + _varint(CODEC_RAW) + multihash
    return MULTIBASE_BASE32 + _b32_encode_nopad(cid_bytes)
