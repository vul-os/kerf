"""DMTAP-PUB error registry (§22.10, subsystem byte 0x09) and profile errors.

Every fail-closed check in the object model raises :class:`PubError` carrying
the exact ``ERR_PUB_*`` code and name from §22.10, so a caller (or a test) can
assert on ``.code`` rather than string-matching a message.
"""

from __future__ import annotations

# ── §22.10 ERR_PUB_* codes ────────────────────────────────────────────────────
ERR_PUB_UNSUPPORTED_VERSION = 0x0901
ERR_PUB_MANIFEST_KEY_PRESENT = 0x0902
ERR_PUB_MANIFEST_TYPE_MISMATCH = 0x0903
ERR_PUB_ANNOUNCE_SIG_INVALID = 0x0904
ERR_PUB_ANNOUNCE_ID_MISMATCH = 0x0905
ERR_PUB_FEED_SIG_INVALID = 0x0906
ERR_PUB_FEED_ROLLBACK = 0x0907
ERR_PUB_FEED_CHAIN_BROKEN = 0x0908
ERR_PUB_MANIFEST_HASH_MISMATCH = 0x0909
ERR_PUB_CHUNK_HASH_MISMATCH = 0x090A
ERR_PUB_SUPERSEDE_INVALID = 0x090B
ERR_PUB_NOT_SERVED = 0x090C
ERR_PUB_SERVE_QUOTA = 0x090D

_NAMES = {
    0x0901: "ERR_PUB_UNSUPPORTED_VERSION",
    0x0902: "ERR_PUB_MANIFEST_KEY_PRESENT",
    0x0903: "ERR_PUB_MANIFEST_TYPE_MISMATCH",
    0x0904: "ERR_PUB_ANNOUNCE_SIG_INVALID",
    0x0905: "ERR_PUB_ANNOUNCE_ID_MISMATCH",
    0x0906: "ERR_PUB_FEED_SIG_INVALID",
    0x0907: "ERR_PUB_FEED_ROLLBACK",
    0x0908: "ERR_PUB_FEED_CHAIN_BROKEN",
    0x0909: "ERR_PUB_MANIFEST_HASH_MISMATCH",
    0x090A: "ERR_PUB_CHUNK_HASH_MISMATCH",
    0x090B: "ERR_PUB_SUPERSEDE_INVALID",
    0x090C: "ERR_PUB_NOT_SERVED",
    0x090D: "ERR_PUB_SERVE_QUOTA",
}


class PubError(Exception):
    """A DMTAP-PUB fail-closed violation, carrying its §22.10 code."""

    def __init__(self, code: int, message: str = ""):
        self.code = code
        self.name = _NAMES.get(code, f"ERR_PUB_0x{code:04X}")
        super().__init__(f"{self.name} (0x{code:04X}): {message}")


class ProfileError(ValueError):
    """A §23 CAD-artifact-profile conformance violation (CAD-1 … CAD-10)."""

    def __init__(self, rule: str, message: str = ""):
        self.rule = rule
        super().__init__(f"{rule}: {message}")
