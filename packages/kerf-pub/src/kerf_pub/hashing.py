"""Content addressing: multihash-prefixed digests and the DMTAP-PUB Merkle tree.

Digest choice (shipped): **SHA2-256 under multihash prefix 0x12**.

The v0-REQUIRED default is BLAKE3-256 under prefix ``0x1e`` (§18.1.5), but kerf
ships no ``blake3`` dependency today, and §23 Appendix A explicitly sanctions
kerf addressing its public chunks under the reserved SHA2-256 prefix ``0x12``
using the same digests its Git-LFS objects already carry — accepting the
narrower near-term interop surface and migrating to native BLAKE3 later via the
same hash-agility prefix, with no flag day.

The prefix byte is therefore carried in EVERY ``hash`` value (prefix ‖ digest,
33 bytes) so that swapping in BLAKE3 is a one-line change here — set
``HASH_PREFIX`` / ``_digest`` — and every stored/served address already declares
its algorithm. Nothing downstream assumes a particular digest.
"""

from __future__ import annotations

import hashlib

# Multihash prefix bytes (§18.1.5 truncated to one byte for v0).
PREFIX_BLAKE3_256 = 0x1E  # v0 REQUIRED default — not yet shipped (no blake3 dep)
PREFIX_SHA2_256 = 0x12    # RESERVED (compliance migration) — SHIPPED here
PREFIX_SHA3_256 = 0x16    # RESERVED

# The digest kerf currently ships behind the agility prefix.
HASH_PREFIX = PREFIX_SHA2_256
DIGEST_LEN = 32
HASH_LEN = 1 + DIGEST_LEN  # prefix ‖ digest

# §22.2.2 manifest-tree domain-separation tag.
DS_MANIFEST = b"DMTAP-PUB-v0/manifest\x00"


def _digest(data: bytes) -> bytes:
    """Raw 32-byte digest under the shipped algorithm (SHA2-256 for prefix 0x12)."""
    if HASH_PREFIX == PREFIX_SHA2_256:
        return hashlib.sha256(data).digest()
    if HASH_PREFIX == PREFIX_SHA3_256:
        return hashlib.sha3_256(data).digest()
    # PREFIX_BLAKE3_256 slots in here the day `blake3` becomes a dependency:
    #   import blake3; return blake3.blake3(data).digest()
    raise NotImplementedError(f"digest for prefix 0x{HASH_PREFIX:02x} not available")


def mhash(data: bytes) -> bytes:
    """Content address of ``data``: HASH_PREFIX ‖ digest(data) (33 bytes)."""
    return bytes([HASH_PREFIX]) + _digest(data)


def check_hash(h: bytes) -> None:
    """Validate a ``hash`` value's prefix and length (§18.1.5). Raises ValueError."""
    if len(h) != HASH_LEN:
        raise ValueError(f"hash must be {HASH_LEN} bytes, got {len(h)}")
    if h[0] != HASH_PREFIX:
        raise ValueError(
            f"unsupported hash prefix 0x{h[0]:02x} "
            f"(this build serves 0x{HASH_PREFIX:02x})"
        )


def verify_chunk(h: bytes, plaintext: bytes) -> bool:
    """True iff ``plaintext`` hashes to the listed chunk address ``h`` (§22.2.2)."""
    return mhash(plaintext) == h


# ── RFC 6962 binary Merkle tree, DS-tagged per §22.2.2 ────────────────────────

def _leaf(h_i: bytes) -> bytes:
    # leaf(h_i) = digest( DS ‖ 0x00 ‖ h_i ) ; h_i is the full 33-byte chunk hash.
    return _digest(DS_MANIFEST + b"\x00" + h_i)


def _node(left: bytes, right: bytes) -> bytes:
    # node(l, r) = digest( DS ‖ 0x01 ‖ l ‖ r ) ; l, r are 32-byte subtree digests.
    return _digest(DS_MANIFEST + b"\x01" + left + right)


def _mth(hashes: list[bytes]) -> bytes:
    """RFC 6962 Merkle Tree Hash over the ordered chunk hashes (32-byte digest)."""
    n = len(hashes)
    if n == 0:
        raise ValueError("Merkle tree over zero leaves is undefined")
    if n == 1:
        return _leaf(hashes[0])
    # k = largest power of two strictly less than n (RFC 6962 split rule).
    k = 1
    while k << 1 < n:
        k <<= 1
    return _node(_mth(hashes[:k]), _mth(hashes[k:]))


def merkle_root(chunk_hashes: list[bytes]) -> bytes:
    """PubManifest.id = HASH_PREFIX ‖ MTH(h_0 … h_{n-1}) (§22.2.2)."""
    return bytes([HASH_PREFIX]) + _mth(chunk_hashes)
