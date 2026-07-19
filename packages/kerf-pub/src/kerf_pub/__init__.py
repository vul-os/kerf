"""kerf_pub — kerf's implementation of the DMTAP-PUB open standard (§22, §23).

The public-object substrate powering kerf's decentralized Workshop:

* signed, plaintext-addressed public blobs (``PubManifest``),
* signed announcements (``PubAnnounce``) and per-author append-only feeds
  (``FeedHead`` / ``FeedEntry``),
* the CAD artifact profile (``ArtifactMetadata`` / ``AssemblyStructure``),
* a four-verb client (publish / fetch / resolve / submit) with a zero-socket
  local-only invariant,
* the §22.5.1 gateway HTTP endpoints, and
* durable pin hydration (``PubClient.hydrate_pin``) — swarm-fetching every
  manifest and chunk an announce names over the followed-gateway swarm, with
  an IPFS gateway (``kerf_pub.ipfs``) as a second, always-untrusted chunk
  fetch-adapter behind the same self-verification gate.

MIT-licensed, part of the OSS node — never gated behind a cloud/billing flag.
"""

from .cid import cid_for_chunk
from .errors import PubError, ProfileError
from .identity import Identity
from .ipfs import IPFSGatewayFetcher, default_ipfs_gateway_url
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
from .client import PubClient, check_fork, check_head_watermark, HydrationResult

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
    "check_head_watermark",
    "HydrationResult",
    "cid_for_chunk",
    "IPFSGatewayFetcher",
    "default_ipfs_gateway_url",
]
