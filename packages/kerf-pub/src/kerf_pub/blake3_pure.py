"""Pure-Python BLAKE3-256, used only when the optional ``blake3`` wheel is absent.

DMTAP-PUB v0 REQUIRES BLAKE3-256 as the content-addressing digest (§18.1.5,
multihash prefix ``0x1e``). kerf's house style is to hand-roll the small,
fully-specified primitives it needs rather than take a dependency (see
:mod:`kerf_pub.cbor`, which implements deterministic CBOR for the same reason),
and a missing binary wheel must never be able to make a node fail to verify
content it is otherwise able to verify. So this module ships a complete,
dependency-free BLAKE3 whose *only* job is to be byte-identical to the
reference implementation.

:mod:`kerf_pub.hashing` prefers the ``blake3`` extension module when it is
importable (roughly two orders of magnitude faster, which matters for a gateway
hashing 1 MiB chunks) and silently falls back here otherwise. Both paths are
covered by the shared DMTAP conformance vectors, so a divergence between them
is a test failure, not a silent interop break.

Scope: unkeyed hashing with a 32-byte output (``blake3_256``). The keyed-hash
and derive-key modes, and extendable output beyond 32 bytes, are not needed by
§22 and are deliberately not implemented.

Reference: BLAKE3 specification (Aumasson, Neves, Wilcox-O'Hearn, Winnerlein),
§2.1-§2.5 — the same construction as the reference ``blake3`` crate.
"""

from __future__ import annotations

OUT_LEN = 32
KEY_LEN = 32
BLOCK_LEN = 64
CHUNK_LEN = 1024

# Domain-separation flags (BLAKE3 spec §2.1).
CHUNK_START = 1 << 0
CHUNK_END = 1 << 1
PARENT = 1 << 2
ROOT = 1 << 3

IV = (
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
)

MSG_PERMUTATION = (2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8)

_M32 = 0xFFFFFFFF


def _rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & _M32


def _g(s: list[int], a: int, b: int, c: int, d: int, mx: int, my: int) -> None:
    s[a] = (s[a] + s[b] + mx) & _M32
    s[d] = _rotr(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & _M32
    s[b] = _rotr(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b] + my) & _M32
    s[d] = _rotr(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & _M32
    s[b] = _rotr(s[b] ^ s[c], 7)


def _round(s: list[int], m: list[int]) -> None:
    # Columns.
    _g(s, 0, 4, 8, 12, m[0], m[1])
    _g(s, 1, 5, 9, 13, m[2], m[3])
    _g(s, 2, 6, 10, 14, m[4], m[5])
    _g(s, 3, 7, 11, 15, m[6], m[7])
    # Diagonals.
    _g(s, 0, 5, 10, 15, m[8], m[9])
    _g(s, 1, 6, 11, 12, m[10], m[11])
    _g(s, 2, 7, 8, 13, m[12], m[13])
    _g(s, 3, 4, 9, 14, m[14], m[15])


def _compress(cv: tuple[int, ...] | list[int], block_words: list[int],
              counter: int, block_len: int, flags: int) -> list[int]:
    """The BLAKE3 compression function; returns all 16 output words."""
    state = [
        cv[0], cv[1], cv[2], cv[3], cv[4], cv[5], cv[6], cv[7],
        IV[0], IV[1], IV[2], IV[3],
        counter & _M32, (counter >> 32) & _M32, block_len, flags,
    ]
    m = list(block_words)
    for i in range(7):
        _round(state, m)
        if i < 6:
            m = [m[p] for p in MSG_PERMUTATION]
    for i in range(8):
        state[i] ^= state[i + 8]
        state[i + 8] ^= cv[i]
    return state


def _words(block: bytes) -> list[int]:
    """64 bytes -> 16 little-endian u32 words (short blocks are zero-padded)."""
    if len(block) < BLOCK_LEN:
        block = block + b"\x00" * (BLOCK_LEN - len(block))
    return [int.from_bytes(block[i:i + 4], "little") for i in range(0, BLOCK_LEN, 4)]


def _chunk_cv(chunk: bytes, counter: int, root: bool) -> list[int]:
    """Chaining value of one chunk. If ``root``, the final compression is the
    root node and its first 8 words ARE the 32-byte output (BLAKE3 §2.4)."""
    cv: list[int] = list(IV)
    n = len(chunk)
    # A zero-length input is still one chunk of one empty block.
    nblocks = max(1, (n + BLOCK_LEN - 1) // BLOCK_LEN)
    for i in range(nblocks):
        block = chunk[i * BLOCK_LEN:(i + 1) * BLOCK_LEN]
        flags = 0
        if i == 0:
            flags |= CHUNK_START
        if i == nblocks - 1:
            flags |= CHUNK_END
            if root:
                flags |= ROOT
        cv = _compress(cv, _words(block), counter, len(block), flags)[:8]
    return cv


def _parent_cv(left: list[int], right: list[int], root: bool) -> list[int]:
    block_words = left + right
    flags = PARENT | (ROOT if root else 0)
    return _compress(IV, block_words, 0, BLOCK_LEN, flags)[:8]


def blake3_256(data: bytes) -> bytes:
    """Unkeyed BLAKE3 of ``data``, truncated to the default 32-byte output."""
    data = bytes(data)
    nchunks = max(1, (len(data) + CHUNK_LEN - 1) // CHUNK_LEN)

    if nchunks == 1:
        cv = _chunk_cv(data, 0, root=True)
        return b"".join(w.to_bytes(4, "little") for w in cv)

    level = [
        _chunk_cv(data[i * CHUNK_LEN:(i + 1) * CHUNK_LEN], i, root=False)
        for i in range(nchunks)
    ]
    # BLAKE3's tree puts the largest power of two chunks in the left subtree,
    # which is exactly greedy pairwise merging with an odd tail promoted intact.
    # Merge down to two nodes; the LAST merge is the root node and is the only
    # one that carries the ROOT flag (BLAKE3 §2.4).
    while len(level) > 2:
        nxt: list[list[int]] = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_parent_cv(level[i], level[i + 1], root=False))
        if len(level) % 2:
            nxt.append(level[-1])
        level = nxt

    cv = _parent_cv(level[0], level[1], root=True)
    return b"".join(w.to_bytes(4, "little") for w in cv)
