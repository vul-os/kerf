"""DMTAP-PUB object model (§22) and the CAD artifact profile (§23).

Every object here is a deterministic integer-keyed CBOR map (§18.1.2). Content
addresses and signing preimages are computed with :mod:`kerf_pub.cbor` and
:mod:`kerf_pub.hashing`, so they are byte-reproducible across implementations.

Signatures are Ed25519 (suite 0x01); digests ride under the shipped multihash
prefix (BLAKE3-256 / 0x1e — see :mod:`kerf_pub.hashing`). All fail-closed
checks raise :class:`kerf_pub.errors.PubError` with the exact §22.10 code.
Every content address and signing preimage this module produces is held to the
shared cross-implementation vectors by ``tests/test_conformance_vectors.py``.

**Known gap: DeviceCert chains (§22.3.3 step 4).** The spec authorizes a
``signer`` either by ``signer == pub`` OR by a ``DeviceCert`` (§1.2) that
``pub`` signed over ``signer`` and that is not revoked (§1.5). kerf-pub
implements only the first arm and rejects the second. Precisely what is
missing, so a later pass knows its scope:

* no ``DeviceCert`` CBOR decode/encode, and no field on any §22 object to
  carry one (the spec does not place it inside the announce, so it must be
  resolved out of band);
* no Identity-document resolution to find the authorized device set for a
  ``pub``, and no revocation check (§1.5) — an unrevoked-at-signing-time cert
  is worthless without a way to learn it was later revoked, so shipping the
  signature check alone would be a fail-OPEN half-measure;
* no delegated *signing*: :class:`~kerf_pub.identity.Identity` signs with the
  root key, so kerf-pub never emits an object another implementation would
  need a chain to verify. Its output is universally verifiable; only its input
  is narrower than the spec allows.

Consequence, stated plainly: kerf-pub REJECTS a spec-legal announce or feed
head signed by a DeviceCert-delegated key (``0x0904`` / ``0x0906``). This is
strictly conservative — it never accepts anything a conformant verifier would
refuse — but it is a real interop limitation against publishers that keep
``IK`` cold (§1.2a), which §22.9 item 5 RECOMMENDS. §22 makes DeviceCert
support a SHOULD, not a MUST, so this remains conformant v0 behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import cbor
from . import hashing
from .errors import (
    PubError,
    ProfileError,
    ERR_PUB_UNSUPPORTED_VERSION,
    ERR_PUB_MANIFEST_KEY_PRESENT,
    ERR_PUB_MANIFEST_HASH_MISMATCH,
    ERR_PUB_ANNOUNCE_SIG_INVALID,
    ERR_PUB_ANNOUNCE_ID_MISMATCH,
    ERR_PUB_FEED_SIG_INVALID,
    ERR_PUB_FEED_CHAIN_BROKEN,
    ERR_PUB_SUPERSEDE_INVALID,
)
from .identity import ed25519_verify

# ── constants ─────────────────────────────────────────────────────────────────
PUB_VERSION = 0
SUITE_V0 = 0x01  # Ed25519 sign (§18.1.4); digest via hash-agility prefix.
DEFAULT_CHUNK_SZ = 1 << 20  # 1 MiB (§16.4 / §22.2.1)

DS_ANNOUNCE = b"DMTAP-PUB-v0/announce\x00"
DS_FEED = b"DMTAP-PUB-v0/feed\x00"


def _require_hash(h: Any, what: str) -> bytes:
    if not isinstance(h, (bytes, bytearray)):
        raise PubError(ERR_PUB_UNSUPPORTED_VERSION, f"{what} must be bytes")
    hashing.check_hash(bytes(h))
    return bytes(h)


# ════════════════════════════════════════════════════════════════════════════
# §22.2  Public blob profile — PubManifest
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class PubManifest:
    """A plaintext-addressed Merkle-DAG manifest (§22.2.1). Keys: 1 id, 2 size,
    3 chunk_sz, 4 chunks, 6 suite. Key 5 (a per-file key) is FORBIDDEN."""

    id: bytes
    size: int
    chunk_sz: int
    chunks: list[bytes]
    suite: int = SUITE_V0

    # ── construction ──────────────────────────────────────────────────────────
    @staticmethod
    def split_chunks(data: bytes, chunk_sz: int = DEFAULT_CHUNK_SZ) -> list[bytes]:
        """Fixed-size plaintext chunks; the last MAY be short (§22.2.1)."""
        if chunk_sz <= 0:
            raise ValueError("chunk_sz must be positive")
        if not data:
            # A zero-length blob is one empty chunk, so `chunks` stays non-empty.
            return [b""]
        return [data[i:i + chunk_sz] for i in range(0, len(data), chunk_sz)]

    @classmethod
    def build(cls, data: bytes, chunk_sz: int = DEFAULT_CHUNK_SZ) -> "PubManifest":
        """Build a manifest over ``data``'s plaintext chunks (§22.2.2)."""
        plainchunks = cls.split_chunks(data, chunk_sz)
        chunk_hashes = [hashing.mhash(c) for c in plainchunks]
        return cls(
            id=hashing.merkle_root(chunk_hashes),
            size=len(data),
            chunk_sz=chunk_sz,
            chunks=chunk_hashes,
            suite=SUITE_V0,
        )

    # ── wire ──────────────────────────────────────────────────────────────────
    def to_cbor(self) -> bytes:
        return cbor.encode({
            1: self.id,
            2: self.size,
            3: self.chunk_sz,
            4: list(self.chunks),
            6: self.suite,
        })

    @classmethod
    def from_cbor(cls, raw: bytes) -> "PubManifest":
        m = cbor.decode(raw)
        if not isinstance(m, dict):
            raise PubError(ERR_PUB_MANIFEST_HASH_MISMATCH, "manifest is not a map")
        if 5 in m:
            # The key-5 trap (§22.2.1): a public blob has no key by construction.
            raise PubError(ERR_PUB_MANIFEST_KEY_PRESENT, "PubManifest carries key 5")
        for k in (1, 2, 3, 4, 6):
            if k not in m:
                raise PubError(ERR_PUB_MANIFEST_HASH_MISMATCH, f"missing key {k}")
        if m[6] != SUITE_V0:
            raise PubError(ERR_PUB_UNSUPPORTED_VERSION, f"unknown suite {m[6]}")
        chunks = m[4]
        if not isinstance(chunks, list) or not chunks:
            raise PubError(ERR_PUB_MANIFEST_HASH_MISMATCH, "chunks must be non-empty")
        chunks = [_require_hash(h, "chunk hash") for h in chunks]
        return cls(
            id=_require_hash(m[1], "manifest id"),
            size=int(m[2]),
            chunk_sz=int(m[3]),
            chunks=chunks,
            suite=int(m[6]),
        )

    def verify(self) -> None:
        """Recompute the DS-tagged Merkle root and fail closed on mismatch."""
        if self.suite != SUITE_V0:
            raise PubError(ERR_PUB_UNSUPPORTED_VERSION, f"unknown suite {self.suite}")
        recomputed = hashing.merkle_root(self.chunks)
        if recomputed != self.id:
            raise PubError(ERR_PUB_MANIFEST_HASH_MISMATCH, "root != id")


# ════════════════════════════════════════════════════════════════════════════
# §22.3  pub_announce
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class PubAnnounce:
    """A bare, unsealed, signed announcement (§22.3.1). Keys: 1 v, 2 suite,
    3 pub, 4 roots, 5 meta, 6 supersedes(opt), 7 ts, 8 signer, 9 sig."""

    pub: bytes
    roots: list[bytes]
    ts: int
    meta: dict[str, Any] = field(default_factory=dict)
    supersedes: bytes | None = None
    v: int = PUB_VERSION
    suite: int = SUITE_V0
    signer: bytes | None = None
    sig: bytes | None = None

    # ── signing / addressing ───────────────────────────────────────────────────
    def _body_map(self) -> dict[int, Any]:
        body: dict[int, Any] = {
            1: self.v,
            2: self.suite,
            3: self.pub,
            4: list(self.roots),
            5: dict(self.meta),
            7: self.ts,
            8: self.signer,
        }
        if self.supersedes is not None:
            body[6] = self.supersedes
        return body

    def _signing_preimage(self) -> bytes:
        # DMTAP-PUB-v0/announce ‖ 0x00 ‖ det_cbor(PubAnnounce ∖ {9})  (§22.3.1)
        return DS_ANNOUNCE + cbor.encode(self._body_map())

    def sign(self, identity) -> "PubAnnounce":
        """Sign with a local :class:`~kerf_pub.identity.Identity` (signer == pub)."""
        if self.pub is None:
            self.pub = identity.pub
        self.signer = identity.signer
        self.sig = identity.sign(self._signing_preimage())
        return self

    def to_cbor(self) -> bytes:
        if self.sig is None or self.signer is None:
            raise ValueError("announce is unsigned")
        body = self._body_map()
        body[9] = self.sig
        return cbor.encode(body)

    @property
    def id(self) -> bytes:
        # announce_id = HASH_PREFIX ‖ digest(det_cbor(full signed announce)) (§22.3.1)
        return hashing.mhash(self.to_cbor())

    @classmethod
    def from_cbor(cls, raw: bytes) -> "PubAnnounce":
        m = cbor.decode(raw)
        if not isinstance(m, dict):
            raise PubError(ERR_PUB_ANNOUNCE_SIG_INVALID, "announce is not a map")
        for k in (1, 2, 3, 4, 5, 7, 8, 9):
            if k not in m:
                raise PubError(ERR_PUB_ANNOUNCE_SIG_INVALID, f"missing key {k}")
        roots = m[4]
        if not isinstance(roots, list) or not roots:
            raise PubError(ERR_PUB_ANNOUNCE_SIG_INVALID, "roots must be non-empty")
        meta = m[5]
        if not isinstance(meta, dict):
            raise PubError(ERR_PUB_ANNOUNCE_SIG_INVALID, "meta must be a map")
        return cls(
            v=int(m[1]),
            suite=int(m[2]),
            pub=bytes(m[3]),
            roots=[_require_hash(r, "root") for r in roots],
            meta=meta,
            supersedes=_require_hash(m[6], "supersedes") if 6 in m else None,
            ts=int(m[7]),
            signer=bytes(m[8]),
            sig=bytes(m[9]),
        )

    # ── verification (§22.3.3) ──────────────────────────────────────────────────
    def verify(self, expected_id: bytes | None = None) -> None:
        # 1. unknown v/suite → fail closed
        if self.v != PUB_VERSION:
            raise PubError(ERR_PUB_UNSUPPORTED_VERSION, f"v={self.v}")
        if self.suite != SUITE_V0:
            raise PubError(ERR_PUB_UNSUPPORTED_VERSION, f"suite={self.suite}")
        # 2. content-address bind
        if expected_id is not None and self.id != expected_id:
            raise PubError(ERR_PUB_ANNOUNCE_ID_MISMATCH, "announce_id != fetched address")
        if self.sig is None or self.signer is None:
            raise PubError(ERR_PUB_ANNOUNCE_SIG_INVALID, "unsigned announce")
        # 3. signature under signer
        if not ed25519_verify(self.signer, self.sig, self._signing_preimage()):
            raise PubError(ERR_PUB_ANNOUNCE_SIG_INVALID, "sig verify failed")
        # 4. signer authorized by pub (§22.3.3 step 4). That step permits EITHER
        #    signer == pub OR a DeviceCert (§1.2) chain from pub to signer.
        #    kerf-pub implements only the first arm — see the module note on
        #    the DeviceCert gap. Enforcing signer == pub is the STRICTER of the
        #    two readings: it can never accept an announce a fully conformant
        #    verifier would reject, only reject one it would accept. That is a
        #    fail-closed interop limitation, never a security hole.
        if self.signer != self.pub:
            raise PubError(
                ERR_PUB_ANNOUNCE_SIG_INVALID,
                "signer != pub; DeviceCert chains (§22.3.3 step 4, second arm) "
                "are not implemented — see kerf_pub.objects module docstring",
            )

    def verify_supersedes(self, predecessor: "PubAnnounce") -> None:
        """§22.3.3 step 5 / §22.3.4: a publisher may only supersede its own announce."""
        if self.supersedes is None:
            return
        if predecessor.pub != self.pub:
            raise PubError(ERR_PUB_SUPERSEDE_INVALID, "supersedes a different author")


# ════════════════════════════════════════════════════════════════════════════
# §22.4  Author feeds
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class FeedEntry:
    """A position in an author feed (§22.4.1). Keys: 1 seq, 2 announce,
    3 prev(opt, absent iff genesis), 4 ts."""

    seq: int
    announce: bytes
    ts: int
    prev: bytes | None = None

    def to_cbor(self) -> bytes:
        body: dict[int, Any] = {1: self.seq, 2: self.announce, 4: self.ts}
        if self.prev is not None:
            body[3] = self.prev
        return cbor.encode(body)

    @property
    def id(self) -> bytes:
        return hashing.mhash(self.to_cbor())

    @classmethod
    def from_cbor(cls, raw: bytes) -> "FeedEntry":
        m = cbor.decode(raw)
        if not isinstance(m, dict):
            raise PubError(ERR_PUB_FEED_CHAIN_BROKEN, "feed entry is not a map")
        for k in (1, 2, 4):
            if k not in m:
                raise PubError(ERR_PUB_FEED_CHAIN_BROKEN, f"missing key {k}")
        entry = cls(
            seq=int(m[1]),
            announce=_require_hash(m[2], "announce"),
            ts=int(m[4]),
            prev=_require_hash(m[3], "prev") if 3 in m else None,
        )
        entry.check_shape()
        return entry

    def check_shape(self) -> None:
        """Genesis (seq 0) has no prev; every other entry MUST carry one (§22.4.1)."""
        if self.seq == 0 and self.prev is not None:
            raise PubError(ERR_PUB_FEED_CHAIN_BROKEN, "genesis entry carries prev")
        if self.seq != 0 and self.prev is None:
            raise PubError(ERR_PUB_FEED_CHAIN_BROKEN, "non-genesis entry lacks prev")


@dataclass
class FeedHead:
    """The signed tip of an author feed (§22.4.1). Keys: 1 v, 2 suite, 3 pub,
    4 seq, 5 tip, 6 ts, 7 signer, 8 sig."""

    pub: bytes
    seq: int
    tip: bytes
    ts: int
    v: int = PUB_VERSION
    suite: int = SUITE_V0
    signer: bytes | None = None
    sig: bytes | None = None

    def _body_map(self) -> dict[int, Any]:
        return {
            1: self.v,
            2: self.suite,
            3: self.pub,
            4: self.seq,
            5: self.tip,
            6: self.ts,
            7: self.signer,
        }

    def _signing_preimage(self) -> bytes:
        # DMTAP-PUB-v0/feed ‖ 0x00 ‖ det_cbor(FeedHead ∖ {8})  (§22.4.1)
        return DS_FEED + cbor.encode(self._body_map())

    def sign(self, identity) -> "FeedHead":
        if self.pub is None:
            self.pub = identity.pub
        self.signer = identity.signer
        self.sig = identity.sign(self._signing_preimage())
        return self

    def to_cbor(self) -> bytes:
        if self.sig is None or self.signer is None:
            raise ValueError("feed head is unsigned")
        body = self._body_map()
        body[8] = self.sig
        return cbor.encode(body)

    @classmethod
    def from_cbor(cls, raw: bytes) -> "FeedHead":
        m = cbor.decode(raw)
        if not isinstance(m, dict):
            raise PubError(ERR_PUB_FEED_SIG_INVALID, "feed head is not a map")
        for k in (1, 2, 3, 4, 5, 6, 7, 8):
            if k not in m:
                raise PubError(ERR_PUB_FEED_SIG_INVALID, f"missing key {k}")
        return cls(
            v=int(m[1]),
            suite=int(m[2]),
            pub=bytes(m[3]),
            seq=int(m[4]),
            tip=_require_hash(m[5], "tip"),
            ts=int(m[6]),
            signer=bytes(m[7]),
            sig=bytes(m[8]),
        )

    def verify(self) -> None:
        if self.v != PUB_VERSION:
            raise PubError(ERR_PUB_UNSUPPORTED_VERSION, f"v={self.v}")
        if self.suite != SUITE_V0:
            raise PubError(ERR_PUB_UNSUPPORTED_VERSION, f"suite={self.suite}")
        if self.sig is None or self.signer is None:
            raise PubError(ERR_PUB_FEED_SIG_INVALID, "unsigned head")
        if not ed25519_verify(self.signer, self.sig, self._signing_preimage()):
            raise PubError(ERR_PUB_FEED_SIG_INVALID, "sig verify failed")
        # Same §22.3.3 step-4 restriction as PubAnnounce.verify (see there).
        if self.signer != self.pub:
            raise PubError(
                ERR_PUB_FEED_SIG_INVALID,
                "signer != pub; DeviceCert chains (§22.3.3 step 4, second arm) "
                "are not implemented — see kerf_pub.objects module docstring",
            )


# ════════════════════════════════════════════════════════════════════════════
# §23  CAD artifact profile — ArtifactMetadata / AssemblyStructure
# ════════════════════════════════════════════════════════════════════════════

# §23.3.2 registries (profile-local)
KIND_PART = 1
KIND_ASSEMBLY = 2
KIND_PCB = 3
KIND_SCHEMATIC = 4
KIND_DRAWING = 5
KIND_DATASET = 6
KIND_DOC = 7

FMT_STEP = 1
FMT_NATIVE = 2
FMT_GLTF = 3        # tessellated mesh — MUST always be derived-rendition (CAD-4)
FMT_ECAD = 4
FMT_PDF = 5
FMT_ASSEMBLY_STRUCTURE = 6

ROLE_CANONICAL = 1
ROLE_DERIVED = 2
ROLE_STRUCTURE = 3

# §23.6.1 assembly child reference modes
REF_PIN = 1
REF_TRACK = 2

META_ARTIFACT_KEY = "artifact"


@dataclass
class Units:
    """§23.3.3. length_unit is REQUIRED and MUST NOT be defaulted or inferred."""

    length_unit: str
    angle_unit: str | None = None   # defaults to "rad" when absent
    mass_unit: str | None = None

    def to_map(self) -> dict[int, Any]:
        m: dict[int, Any] = {1: self.length_unit}
        if self.angle_unit is not None:
            m[2] = self.angle_unit
        if self.mass_unit is not None:
            m[3] = self.mass_unit
        return m

    @classmethod
    def from_map(cls, m: dict) -> "Units":
        if 1 not in m or not isinstance(m[1], str) or not m[1]:
            # CAD-6 — structurally closed: no implied default (§23.3.3).
            raise ProfileError("CAD-6", "units.length_unit is required and explicit")
        return cls(length_unit=m[1], angle_unit=m.get(2), mass_unit=m.get(3))


@dataclass
class ArtifactFormat:
    """§23.3.4."""

    format_id: int
    manifest_root: bytes
    role: int
    derived_from_format: bytes | None = None
    format_version: str | None = None

    def to_map(self) -> dict[int, Any]:
        m: dict[int, Any] = {1: self.format_id, 2: self.manifest_root, 3: self.role}
        if self.derived_from_format is not None:
            m[4] = self.derived_from_format
        if self.format_version is not None:
            m[5] = self.format_version
        return m

    @classmethod
    def from_map(cls, m: dict) -> "ArtifactFormat":
        for k in (1, 2, 3):
            if k not in m:
                raise ProfileError("CAD-2", f"ArtifactFormat missing key {k}")
        return cls(
            format_id=int(m[1]),
            manifest_root=_require_hash(m[2], "manifest_root"),
            role=int(m[3]),
            derived_from_format=(
                _require_hash(m[4], "derived_from_format") if 4 in m else None
            ),
            format_version=m.get(5),
        )


@dataclass
class ArtifactMetadata:
    """§23.3.1 — embedded as deterministic CBOR bytes under meta["artifact"]."""

    name: str
    description: str
    artifact_kind: int
    formats: list[ArtifactFormat]
    units: Units
    license: str
    tags: list[str] | None = None
    deprecated: bool | None = None
    deprecation_reason: str | None = None
    derived_from: bytes | None = None

    def to_map(self) -> dict[int, Any]:
        m: dict[int, Any] = {
            1: self.name,
            2: self.description,
            3: self.artifact_kind,
            4: [f.to_map() for f in self.formats],
            5: self.units.to_map(),
            7: self.license,
        }
        if self.tags is not None:
            m[6] = list(self.tags)
        if self.deprecated is not None:
            m[8] = self.deprecated
        if self.deprecation_reason is not None:
            m[9] = self.deprecation_reason
        if self.derived_from is not None:
            m[10] = self.derived_from
        return m

    def to_cbor(self) -> bytes:
        return cbor.encode(self.to_map())

    @classmethod
    def from_map(cls, m: dict) -> "ArtifactMetadata":
        for k in (1, 2, 3, 4, 5, 7):
            if k not in m:
                raise ProfileError("CAD-1", f"ArtifactMetadata missing required key {k}")
        formats = m[4]
        if not isinstance(formats, list) or not formats:
            raise ProfileError("CAD-2", "formats must contain at least one entry")
        return cls(
            name=m[1],
            description=m[2],
            artifact_kind=int(m[3]),
            formats=[ArtifactFormat.from_map(f) for f in formats],
            units=Units.from_map(m[5]),
            license=m[7],
            tags=m.get(6),
            deprecated=m.get(8),
            deprecation_reason=m.get(9),
            derived_from=_require_hash(m[10], "derived_from") if 10 in m else None,
        )

    @classmethod
    def from_cbor(cls, raw: bytes) -> "ArtifactMetadata":
        return cls.from_map(cbor.decode(raw))

    def validate(self) -> None:
        validate_artifact_metadata(self)


def embed_artifact(meta: dict[str, Any], am: ArtifactMetadata) -> dict[str, Any]:
    """Return a copy of ``meta`` with ArtifactMetadata under META_ARTIFACT_KEY."""
    out = dict(meta)
    out[META_ARTIFACT_KEY] = am.to_cbor()
    return out


def extract_artifact(meta: dict[str, Any]) -> ArtifactMetadata | None:
    """Decode ArtifactMetadata from a PubAnnounce.meta map, or None if absent."""
    raw = meta.get(META_ARTIFACT_KEY)
    if raw is None:
        return None
    if not isinstance(raw, (bytes, bytearray)):
        raise ProfileError("CAD-1", "meta['artifact'] must be CBOR bytes")
    return ArtifactMetadata.from_cbor(bytes(raw))


def validate_artifact_metadata(am: ArtifactMetadata) -> None:
    """Enforce the §23.10 profile MUSTs (CAD-1 … CAD-7 + canonical-source rule)."""
    # CAD-1 — license present and non-empty.
    if not am.license:
        raise ProfileError("CAD-1", "license (SPDX expression) is required")
    # CAD-2 — at least one format.
    if not am.formats:
        raise ProfileError("CAD-2", "formats must contain at least one entry")
    # CAD-6 — units.length_unit present (Units.from_map already enforces on decode).
    if not am.units.length_unit:
        raise ProfileError("CAD-6", "units.length_unit must be explicit")
    # CAD-7 — deprecated ⇒ deprecation_reason.
    if am.deprecated and not am.deprecation_reason:
        raise ProfileError("CAD-7", "deprecated=true requires deprecation_reason")

    is_assembly = am.artifact_kind == KIND_ASSEMBLY
    canonical = [f for f in am.formats if f.role == ROLE_CANONICAL]
    structure = [f for f in am.formats if f.role == ROLE_STRUCTURE]

    for f in am.formats:
        # CAD-4 — a mesh/tessellation is NEVER canonical-source.
        if f.format_id == FMT_GLTF and f.role == ROLE_CANONICAL:
            raise ProfileError("CAD-4", "glTF/mesh must never be canonical-source")
        # CAD-5 — every derived-rendition carries derived_from_format.
        if f.role == ROLE_DERIVED and f.derived_from_format is None:
            raise ProfileError(
                "CAD-5", "derived-rendition must carry derived_from_format"
            )

    # CAD-3 — exactly one canonical (non-assembly) or exactly one structure (assembly).
    if is_assembly:
        if len(structure) != 1:
            raise ProfileError(
                "CAD-3", "assembly must have exactly one role=structure entry"
            )
        if not any(
            f.format_id == FMT_ASSEMBLY_STRUCTURE and f.role == ROLE_STRUCTURE
            for f in am.formats
        ):
            raise ProfileError(
                "CAD-3", "assembly structure entry must be format_id=6, role=3"
            )
    else:
        if len(canonical) != 1:
            raise ProfileError(
                "CAD-3", "non-assembly must have exactly one role=canonical-source"
            )
        # Canonical-source rule (§23.3.4): a mesh can never be it (already CAD-4);
        # STEP is canonical only when no native source is published.
        c = canonical[0]
        if c.format_id == FMT_STEP and any(
            f.format_id == FMT_NATIVE for f in am.formats
        ):
            raise ProfileError(
                "CAD-3",
                "STEP may be canonical-source only when no native source is published",
            )


@dataclass
class AssemblyChild:
    """§23.6.2."""

    ref_kind: int   # pin(1) / track(2)
    ref: bytes      # manifest_root (pin) or pub_announce id (track)
    quantity: int
    transform: bytes | None = None

    def to_map(self) -> dict[int, Any]:
        m: dict[int, Any] = {1: self.ref_kind, 2: self.ref, 3: self.quantity}
        if self.transform is not None:
            m[4] = self.transform
        return m

    @classmethod
    def from_map(cls, m: dict) -> "AssemblyChild":
        for k in (1, 2, 3):
            if k not in m:
                raise ProfileError("CAD-9", f"AssemblyChild missing key {k}")
        if m[1] not in (REF_PIN, REF_TRACK):
            raise ProfileError("CAD-9", f"invalid ref_kind {m[1]}")
        if int(m[3]) < 1:
            raise ProfileError("CAD-9", "quantity must be >= 1")
        return cls(
            ref_kind=int(m[1]),
            ref=_require_hash(m[2], "ref"),
            quantity=int(m[3]),
            transform=bytes(m[4]) if 4 in m else None,
        )


@dataclass
class AssemblyStructure:
    """§23.6.2 — published as an ordinary §22 public blob (its bytes are the
    content of a role=structure ArtifactFormat's manifest_root)."""

    children: list[AssemblyChild]

    def to_cbor(self) -> bytes:
        return cbor.encode({1: [c.to_map() for c in self.children]})

    @classmethod
    def from_cbor(cls, raw: bytes) -> "AssemblyStructure":
        m = cbor.decode(raw)
        if not isinstance(m, dict) or 1 not in m:
            raise ProfileError("CAD-9", "AssemblyStructure missing children")
        children = m[1]
        if not isinstance(children, list) or not children:
            raise ProfileError("CAD-9", "assembly must have >= 1 child")
        return cls(children=[AssemblyChild.from_map(c) for c in children])
