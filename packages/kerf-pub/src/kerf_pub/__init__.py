"""kerf_pub — kerf's implementation of the DMTAP-PUB open standard (§22, §23).

The public-object substrate powering kerf's decentralized Workshop:

* signed, plaintext-addressed public blobs (``PubManifest``),
* signed announcements (``PubAnnounce``) and per-author append-only feeds
  (``FeedHead`` / ``FeedEntry``),
* the CAD artifact profile (``ArtifactMetadata`` / ``AssemblyStructure``),
* a four-verb client (publish / fetch / resolve / submit) with a zero-socket
  local-only invariant, and
* the §22.5.1 gateway HTTP endpoints.

MIT-licensed, part of the OSS node — never gated behind a cloud/billing flag.
"""

from .errors import PubError, ProfileError
from .identity import Identity
from .objects import (
    PubManifest,
    PubAnnounce,
    FeedEntry,
    FeedHead,
    ArtifactMetadata,
    ArtifactFormat,
    Units,
    AssemblyStructure,
    AssemblyChild,
    embed_artifact,
    extract_artifact,
    validate_artifact_metadata,
)
from .store import InMemoryPubStore, PostgresPubStore, PubStore, Availability
from .client import PubClient, check_fork

__all__ = [
    "PubError",
    "ProfileError",
    "Identity",
    "PubManifest",
    "PubAnnounce",
    "FeedEntry",
    "FeedHead",
    "ArtifactMetadata",
    "ArtifactFormat",
    "Units",
    "AssemblyStructure",
    "AssemblyChild",
    "embed_artifact",
    "extract_artifact",
    "validate_artifact_metadata",
    "InMemoryPubStore",
    "PostgresPubStore",
    "PubStore",
    "Availability",
    "PubClient",
    "check_fork",
]
