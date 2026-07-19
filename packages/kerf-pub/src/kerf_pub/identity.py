"""Local publishing identity — an Ed25519 keypair (§1.2, §18.1.4 suite 0x01).

The identity's public key IS the DMTAP ``IK`` carried in the clear in every
``PubAnnounce.pub`` / ``FeedHead.pub`` — authenticity, not anonymity (§22.3).

**Known limitation (TODO).** DMTAP allows an operational ``signer`` key
distinct from the cold root ``pub``, chained by a ``DeviceCert`` (§1.2,
§22.3.1 field 8). kerf-pub signs directly with the root key: ``signer == pub``
always, and no ``DeviceCert`` chains are built or verified — see the
:mod:`kerf_pub.objects` module docstring for exactly what that leaves
unimplemented on the verify side. Keeping ``IK`` cold behind a revocable device
key (§1.2a) is a later addition; until then a key compromise has the full blast
radius of the root identity (§22.9 item 5).

Storage follows kerf's config/data-dir convention: the raw 32-byte Ed25519 seed
is written to ``$KERF_DATA_DIR/pub/identity.key`` (0600), defaulting to
``~/.kerf/pub/identity.key`` when ``KERF_DATA_DIR`` is unset. No network, no DB.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PrivateFormat,
    PublicFormat,
    NoEncryption,
)


# ── raw Ed25519 primitives (suite 0x01) ───────────────────────────────────────

def ed25519_generate() -> bytes:
    """Return a fresh 32-byte Ed25519 private seed."""
    return Ed25519PrivateKey.generate().private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )


def ed25519_pub(seed: bytes) -> bytes:
    """Derive the 32-byte public key from a private seed."""
    return (
        Ed25519PrivateKey.from_private_bytes(seed)
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )


def ed25519_sign(seed: bytes, msg: bytes) -> bytes:
    """Detached Ed25519 signature (64 bytes) over ``msg`` under ``seed``."""
    return Ed25519PrivateKey.from_private_bytes(seed).sign(msg)


def ed25519_verify(pub: bytes, sig: bytes, msg: bytes) -> bool:
    """Verify a detached Ed25519 signature; return False rather than raise."""
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, msg)
        return True
    except (InvalidSignature, ValueError):
        return False


# ── identity storage ──────────────────────────────────────────────────────────

def default_key_path() -> Path:
    base = os.environ.get("KERF_DATA_DIR")
    root = Path(base).expanduser() if base else Path.home() / ".kerf"
    return root / "pub" / "identity.key"


class Identity:
    """A local publishing identity: an Ed25519 seed + its derived public key."""

    def __init__(self, seed: bytes):
        if len(seed) != 32:
            raise ValueError("Ed25519 seed must be 32 bytes")
        self._seed = seed
        self.pub = ed25519_pub(seed)  # 32-byte IK, == signer in v1

    # signer == pub in v1 (no DeviceCert, see module docstring).
    @property
    def signer(self) -> bytes:
        return self.pub

    def sign(self, msg: bytes) -> bytes:
        return ed25519_sign(self._seed, msg)

    @classmethod
    def generate(cls) -> "Identity":
        return cls(ed25519_generate())

    @classmethod
    def load_or_create(cls, path: str | os.PathLike | None = None) -> "Identity":
        """Load the local identity, generating and persisting one if absent."""
        p = Path(path) if path is not None else default_key_path()
        if p.exists():
            seed = p.read_bytes()
            if len(seed) != 32:
                raise ValueError(f"corrupt identity key at {p}: {len(seed)} bytes")
            return cls(seed)
        seed = ed25519_generate()
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write 0600 — private key material.
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, seed)
        finally:
            os.close(fd)
        return cls(seed)
