"""Minimal deterministic CBOR (RFC 8949 Core Deterministic Encoding).

kerf ships no ``cbor2`` dependency, and every DMTAP-PUB object is a fixed
integer-keyed (or, for ``meta``, text-keyed) map of unsigned ints, byte
strings, text strings, arrays, and booleans (§18.1.1). This module implements
exactly that subset, deterministically, so signing preimages and content
addresses are byte-for-byte reproducible without pulling in a general CBOR
library.

Determinism rules enforced on BOTH encode and decode (§18.1.1):

1. Integers / lengths / counts use the shortest possible encoding
   ("preferred serialization"); no indefinite-length items.
2. Map keys are sorted by their encoded bytes, ascending, and are unique.
3. No floats, no CBOR tags, no ``undefined``.
4. ``null`` (0xf6) is rejected on decode — an absent optional field is
   omitted from the map on the wire, never carried as null (§18.1.1).

The decoder is strict: any violation raises :class:`CBORError` so a verifier
of a signed object re-checks canonical form rather than trusting the bytes.
"""

from __future__ import annotations

from typing import Any


class CBORError(ValueError):
    """A byte string was not valid deterministic CBOR for the PUB subset."""


# ── encode ────────────────────────────────────────────────────────────────────

def _head(major: int, n: int) -> bytes:
    mt = major << 5
    if n < 0:
        raise CBORError("negative argument")
    if n < 24:
        return bytes([mt | n])
    if n < 0x100:
        return bytes([mt | 24, n])
    if n < 0x10000:
        return bytes([mt | 25]) + n.to_bytes(2, "big")
    if n < 0x100000000:
        return bytes([mt | 26]) + n.to_bytes(4, "big")
    if n < 0x10000000000000000:
        return bytes([mt | 27]) + n.to_bytes(8, "big")
    raise CBORError("integer too large for CBOR (>u64)")


def encode(obj: Any) -> bytes:
    """Deterministically encode ``obj`` (the PUB subset) to CBOR bytes."""
    # bool MUST be checked before int (bool is an int subclass in Python).
    if isinstance(obj, bool):
        return b"\xf5" if obj else b"\xf4"
    if isinstance(obj, int):
        if obj < 0:
            return _head(1, -1 - obj)
        return _head(0, obj)
    if isinstance(obj, (bytes, bytearray)):
        b = bytes(obj)
        return _head(2, len(b)) + b
    if isinstance(obj, str):
        b = obj.encode("utf-8")
        return _head(3, len(b)) + b
    if isinstance(obj, (list, tuple)):
        return _head(4, len(obj)) + b"".join(encode(x) for x in obj)
    if isinstance(obj, dict):
        items = []
        seen: set[bytes] = set()
        for k, v in obj.items():
            ek = encode(k)
            if ek in seen:
                raise CBORError("duplicate map key")
            seen.add(ek)
            items.append((ek, encode(v)))
        items.sort(key=lambda kv: kv[0])
        return _head(5, len(items)) + b"".join(k + v for k, v in items)
    if obj is None:
        # Only ever appears inside a signing preimage; the PUB objects never
        # emit null on the wire, so refuse to encode it here too.
        raise CBORError("null is not encodable in the PUB CBOR subset")
    raise CBORError(f"unencodable type: {type(obj).__name__}")


# ── decode ────────────────────────────────────────────────────────────────────

class _Decoder:
    __slots__ = ("buf", "pos")

    def __init__(self, buf: bytes):
        self.buf = buf
        self.pos = 0

    def _byte(self) -> int:
        if self.pos >= len(self.buf):
            raise CBORError("truncated CBOR")
        b = self.buf[self.pos]
        self.pos += 1
        return b

    def _take(self, n: int) -> bytes:
        if self.pos + n > len(self.buf):
            raise CBORError("truncated CBOR")
        out = self.buf[self.pos:self.pos + n]
        self.pos += n
        return out

    def _arg(self, ai: int) -> int:
        if ai < 24:
            return ai
        if ai == 24:
            n = self._byte()
            if n < 24:
                raise CBORError("non-minimal integer encoding")
            return n
        if ai == 25:
            n = int.from_bytes(self._take(2), "big")
            if n < 0x100:
                raise CBORError("non-minimal integer encoding")
            return n
        if ai == 26:
            n = int.from_bytes(self._take(4), "big")
            if n < 0x10000:
                raise CBORError("non-minimal integer encoding")
            return n
        if ai == 27:
            n = int.from_bytes(self._take(8), "big")
            if n < 0x100000000:
                raise CBORError("non-minimal integer encoding")
            return n
        # 28,29,30 reserved; 31 indefinite.
        raise CBORError("reserved / indefinite length not permitted")

    def read(self) -> Any:
        b = self._byte()
        major = b >> 5
        ai = b & 0x1F
        if major == 0:
            return self._arg(ai)
        if major == 1:
            return -1 - self._arg(ai)
        if major == 2:
            n = self._arg(ai)
            return self._take(n)
        if major == 3:
            n = self._arg(ai)
            raw = self._take(n)
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CBORError("invalid UTF-8 text string") from exc
        if major == 4:
            n = self._arg(ai)
            return [self.read() for _ in range(n)]
        if major == 5:
            n = self._arg(ai)
            out: dict[Any, Any] = {}
            prev_key: bytes | None = None
            for _ in range(n):
                kstart = self.pos
                key = self.read()
                kbytes = self.buf[kstart:self.pos]
                if prev_key is not None and kbytes <= prev_key:
                    raise CBORError("map keys not sorted / duplicate key")
                prev_key = kbytes
                out[key] = self.read()
            return out
        if major == 7:
            if ai == 20:
                return False
            if ai == 21:
                return True
            if ai == 22:
                raise CBORError("null not permitted on the wire")
            if ai == 23:
                raise CBORError("undefined not permitted")
            raise CBORError("floats / simple values not permitted")
        raise CBORError(f"unexpected major type {major}")


def decode(data: bytes) -> Any:
    """Strictly decode deterministic CBOR bytes, rejecting non-canonical form."""
    dec = _Decoder(bytes(data))
    val = dec.read()
    if dec.pos != len(dec.buf):
        raise CBORError("trailing bytes after CBOR item")
    return val
