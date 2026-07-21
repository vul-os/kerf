"""Content addressing: multihash-prefixed digests and the DMTAP-PUB Merkle tree.

Digest choice (shipped): **BLAKE3-256 under multihash prefix 0x1e** — the
v0-REQUIRED default of §18.1.5, and what every other §22 implementation
(notably the Rust one) writes. kerf-pub produces byte-identical content
addresses to them; this is proven, not asserted, by
``tests/test_conformance_vectors.py``, which replays the frozen shared
``pub_vectors.json`` known-answer vectors.

**Migration from the previous SHA2-256 build.** kerf-pub v1 shipped SHA2-256
(prefix ``0x12``) under the §23 Appendix A interop dispensation. That is now the
LEGACY READ path, not a write path:

* Everything kerf-pub **writes** — chunk hashes, manifest roots, announce ids,
  feed-entry ids — is BLAKE3-256 under ``0x1e``. There is no way to ask this
  module to mint a ``0x12`` address.
* Everything kerf-pub **reads** still verifies under either prefix, chosen by
  the prefix byte carried in the address itself. This is real hash agility, and
  it is what makes the cut-over safe: a node that pinned objects under the old
  build keeps verifying and serving them (its stored bytes are unchanged and
  still self-verify), and — critically — an **already-signed** ``PubAnnounce``
  or ``FeedHead`` whose ``roots``/``tip`` commit to ``0x12`` addresses stays
  verifiable. Those signatures cannot be re-derived without the publisher's
  key, so hard-rejecting ``0x12`` on read would have silently orphaned any
  existing feed. Nothing is rewritten, no flag day, no re-signing.
* There is no downgrade risk in accepting both: an address is compared
  byte-for-byte *including* its prefix byte, so a ``0x12`` digest can never
  satisfy a ``0x1e`` reference (or vice versa). Accepting the legacy prefix
  widens only *which already-named* objects verify, never *what a name means*.
* Re-publishing under the new prefix is a plain ``publish`` call: chunks are
  stored as plaintext, so every address is re-derivable from content the node
  already holds.

Set :data:`LEGACY_READ_PREFIXES` to ``()`` to run BLAKE3-only (a fresh
deployment with no pre-cut-over pins should; it costs nothing and narrows the
accepted surface).

**BLAKE3 without a wheel.** The ``blake3`` extension module is used when
importable; otherwise :mod:`kerf_pub.blake3_pure` — a dependency-free BLAKE3 in
the same house style as :mod:`kerf_pub.cbor` — takes over. The two are
byte-identical, so a missing binary wheel degrades speed, never correctness or
interop. Be clear about the size of that degradation, though: measured on the
1 MiB default chunk, the extension runs ~0.8 ms/MiB and the pure-Python path
~1.4 s/MiB — about 1700x. The fallback exists so a node can still *verify* what
it holds on a platform with no prebuilt wheel; it is not a serving posture. A
node hashing real artifacts wants ``blake3`` installed (it is declared as a
dependency, so it normally is), and ``BLAKE3_BACKEND`` reports which path is
live.
"""

from __future__ import annotations

import hashlib

try:  # fast path: the `blake3` wheel (~1700x the pure-Python speed, see above)
    from blake3 import blake3 as _blake3_ext

    def _blake3_256(data: bytes) -> bytes:
        return _blake3_ext(data).digest()

    BLAKE3_BACKEND = "extension"
except ImportError:  # pragma: no cover - exercised by whichever env lacks it
    from .blake3_pure import blake3_256 as _blake3_256

    BLAKE3_BACKEND = "pure-python"

# Multihash prefix bytes (§18.1.5 truncated to one byte for v0).
PREFIX_BLAKE3_256 = 0x1E  # v0 REQUIRED default — SHIPPED here
PREFIX_SHA2_256 = 0x12    # legacy read-only (pre-cut-over kerf-pub v1 pins)
PREFIX_SHA3_256 = 0x16    # RESERVED, not implemented

# The digest kerf writes. Every address kerf-pub mints carries this prefix.
HASH_PREFIX = PREFIX_BLAKE3_256
# Prefixes accepted on READ only. See the migration note above; safe to empty.
LEGACY_READ_PREFIXES: tuple[int, ...] = (PREFIX_SHA2_256,)

DIGEST_LEN = 32
HASH_LEN = 1 + DIGEST_LEN  # prefix ‖ digest

# §22.2.2 manifest-tree domain-separation tag.
DS_MANIFEST = b"DMTAP-PUB-v0/manifest\x00"


def accepted_prefixes() -> tuple[int, ...]:
    """Prefixes this build will verify against (write prefix first)."""
    return (HASH_PREFIX, *LEGACY_READ_PREFIXES)


def _digest_with(prefix: int, data: bytes) -> bytes:
    """Raw 32-byte digest under the algorithm named by ``prefix``."""
    if prefix == PREFIX_BLAKE3_256:
        return _blake3_256(data)
    if prefix == PREFIX_SHA2_256:
        return hashlib.sha256(data).digest()
    if prefix == PREFIX_SHA3_256:
        return hashlib.sha3_256(data).digest()
    raise ValueError(f"digest for prefix 0x{prefix:02x} not available")


def _digest(data: bytes) -> bytes:
    """Raw 32-byte digest under the shipped write algorithm (BLAKE3-256)."""
    return _digest_with(HASH_PREFIX, data)


def mhash(data: bytes) -> bytes:
    """Content address of ``data``: HASH_PREFIX ‖ BLAKE3-256(data) (33 bytes)."""
    return bytes([HASH_PREFIX]) + _digest(data)


def mhash_under(prefix: int, data: bytes) -> bytes:
    """Content address of ``data`` under an explicit prefix (read/verify path)."""
    if prefix not in accepted_prefixes():
        raise ValueError(f"unsupported hash prefix 0x{prefix:02x}")
    return bytes([prefix]) + _digest_with(prefix, data)


def check_hash(h: bytes) -> None:
    """Validate a ``hash`` value's prefix and length (§18.1.5). Raises ValueError."""
    if len(h) != HASH_LEN:
        raise ValueError(f"hash must be {HASH_LEN} bytes, got {len(h)}")
    if h[0] not in accepted_prefixes():
        raise ValueError(
            f"unsupported hash prefix 0x{h[0]:02x} "
            f"(this build accepts {', '.join(f'0x{p:02x}' for p in accepted_prefixes())})"
        )


def verify_chunk(h: bytes, plaintext: bytes) -> bool:
    """True iff ``plaintext`` hashes to the listed chunk address ``h`` (§22.2.2).

    The digest is chosen by ``h``'s own prefix byte, so a legacy 0x12 chunk
    still self-verifies while every newly minted address is 0x1e.
    """
    if len(h) != HASH_LEN or h[0] not in accepted_prefixes():
        return False
    return mhash_under(h[0], plaintext) == h


# ── RFC 6962 binary Merkle tree, DS-tagged per §22.2.2 ────────────────────────

def _leaf(prefix: int, h_i: bytes) -> bytes:
    # leaf(h_i) = digest( DS ‖ 0x00 ‖ h_i ) ; h_i is the full 33-byte chunk hash.
    return _digest_with(prefix, DS_MANIFEST + b"\x00" + h_i)


def _node(prefix: int, left: bytes, right: bytes) -> bytes:
    # node(l, r) = digest( DS ‖ 0x01 ‖ l ‖ r ) ; l, r are 32-byte subtree digests.
    return _digest_with(prefix, DS_MANIFEST + b"\x01" + left + right)


def _mth(prefix: int, hashes: list[bytes]) -> bytes:
    """RFC 6962 Merkle Tree Hash over the ordered chunk hashes (32-byte digest)."""
    n = len(hashes)
    if n == 0:
        raise ValueError("Merkle tree over zero leaves is undefined")
    if n == 1:
        return _leaf(prefix, hashes[0])
    # k = largest power of two strictly less than n (RFC 6962 split rule).
    k = 1
    while k << 1 < n:
        k <<= 1
    return _node(prefix, _mth(prefix, hashes[:k]), _mth(prefix, hashes[k:]))


def merkle_root(chunk_hashes: list[bytes]) -> bytes:
    """PubManifest.id = prefix ‖ MTH(h_0 … h_{n-1}) (§22.2.2).

    The tree's digest follows the chunk hashes' own prefix — a manifest is a
    single-algorithm object, so a mixed-prefix chunk list is malformed and is
    rejected rather than rooted under a guess.
    """
    if not chunk_hashes:
        raise ValueError("Merkle tree over zero leaves is undefined")
    prefixes = {h[0] for h in chunk_hashes}
    if len(prefixes) != 1:
        raise ValueError("manifest mixes hash algorithms across chunks")
    prefix = prefixes.pop()
    if prefix not in accepted_prefixes():
        raise ValueError(f"unsupported hash prefix 0x{prefix:02x}")
    return bytes([prefix]) + _mth(prefix, chunk_hashes)
