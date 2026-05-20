"""routes_ota.py — OTA firmware release + manifest endpoints.

Endpoints:
  POST /v1/ota/release
      Register a new OTA firmware release.  The request body must include
      a signed manifest (ed25519).  The signature is verified server-side
      against the public key embedded in the manifest.  Returns HTTP 401 if
      the signature does not verify.  Returns HTTP 400 on bad input.

  GET  /v1/ota/manifest/{device_id}
      Return the most recent compatible release for the given device.
      The device_type query param filters by device family (optional).
      Returns JSON matching the OTAManifest shape so the device can poll it.

Storage:
  In-process dict (suitable for tests / single-process dev).  Production would
  use a DB table; the interface is intentionally thin so the backing store can
  be swapped without touching route logic.

Security notes:
  - The signing private key NEVER passes through this server.
  - The server only stores the public key + manifest metadata for look-up.
  - Signature verification on POST ensures tampered manifests are rejected.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory release store  (replace with DB table in production)
# ---------------------------------------------------------------------------

# Keyed by (device_type, version) → manifest dict
_releases: Dict[tuple, dict] = {}


def _get_store() -> Dict[tuple, dict]:
    """Return the active release store (mockable in tests)."""
    return _releases


def _clear_store() -> None:
    """Clear the release store — test helper only."""
    _releases.clear()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ReleaseRequest(BaseModel):
    version: str = Field(..., description="Semver string, e.g. '1.2.3'")
    device_type: str = Field(..., description="Target device family, e.g. 'esp32'")
    sha256: str = Field(..., description="Hex-encoded SHA-256 of the firmware binary")
    ed25519_signature: str = Field(
        ...,
        description="Hex-encoded ed25519 signature covering the protected header region",
    )
    public_key: str = Field(..., description="Hex-encoded 32-byte raw ed25519 public key")
    image_size: int = Field(..., description="Firmware binary size in bytes", gt=0)
    timestamp: int = Field(..., description="Unix epoch of the release")
    download_url: str = Field(..., description="URL from which the device downloads the binary")


class ManifestResponse(BaseModel):
    version: str
    device_type: str
    sha256: str
    ed25519_signature: str
    public_key: str
    image_size: int
    timestamp: int
    download_url: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_release(req: ReleaseRequest) -> None:
    """Verify the ed25519 signature of the release manifest.

    Raises HTTPException(401) on bad signature.
    Raises HTTPException(400) on malformed hex / wrong key length.
    """
    try:
        from kerf_firmware.ota.sign import OTAManifest, OTAVerifier

        manifest = OTAManifest(
            version=req.version,
            device_type=req.device_type,
            sha256=req.sha256,
            ed25519_signature=req.ed25519_signature,
            public_key=req.public_key,
            image_size=req.image_size,
            timestamp=req.timestamp,
            download_url=req.download_url,
        )
        pub_bytes = bytes.fromhex(req.public_key)
        if len(pub_bytes) != 32:
            raise HTTPException(status_code=400, detail="public_key must be 32 bytes (64 hex chars)")

        verifier = OTAVerifier(pub_bytes)

        # We can't re-download the firmware here; instead we verify the
        # signature of the protected header region only (the image integrity
        # is guaranteed by sha256 which the device re-verifies after download).
        import hashlib, struct

        # Reconstruct the protected region (44 bytes) as in sign.py.
        HEADER_MAGIC = 0x4B455246
        sha256_digest = bytes.fromhex(req.sha256)

        parts = req.version.lstrip("v").split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        version_int = (major << 16) | (minor << 8) | patch

        protected = struct.pack(
            "<II I 32s",
            HEADER_MAGIC,
            version_int,
            req.image_size,
            sha256_digest,
        )
        signature = bytes.fromhex(req.ed25519_signature)

        # Use the backend's verify function directly.
        ops = verifier._verify_fn  # internal reference
        pub_key_obj = verifier._public_key
        try:
            ops(pub_key_obj, signature, protected)
        except Exception as exc:
            logger.warning("OTA release signature verification failed: %s", exc)
            raise HTTPException(
                status_code=401,
                detail=f"Signature verification failed: {exc}",
            )

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Bad hex encoding: {exc}") from exc
    except ImportError as exc:
        logger.error("kerf_firmware.ota not importable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="OTA signing library unavailable on this server",
        ) from exc


def _version_tuple(v: str) -> tuple:
    parts = v.lstrip("v").split(".")
    try:
        return tuple(int(x) for x in parts[:3])
    except ValueError:
        return (0, 0, 0)


# ---------------------------------------------------------------------------
# POST /v1/ota/release
# ---------------------------------------------------------------------------

@router.post("/v1/ota/release", status_code=201)
async def post_ota_release(req: ReleaseRequest) -> dict:
    """Register a new OTA firmware release.

    The ed25519 signature in the body must verify against the embedded
    public_key; rejects with HTTP 401 if not.
    """
    _verify_release(req)

    store = _get_store()
    key = (req.device_type.lower(), req.version)
    store[key] = req.model_dump()
    logger.info("OTA release registered: device_type=%s version=%s",
                req.device_type, req.version)
    return {"ok": True, "version": req.version, "device_type": req.device_type}


# ---------------------------------------------------------------------------
# GET /v1/ota/manifest/{device_id}
# ---------------------------------------------------------------------------

@router.get("/v1/ota/manifest/{device_id}")
async def get_ota_manifest(
    device_id: str,
    device_type: Optional[str] = None,
    current_version: Optional[str] = None,
) -> ManifestResponse:
    """Return the most recent compatible OTA release for this device.

    Query params:
      device_type      — filter releases to this device family (e.g. "esp32")
      current_version  — if provided, only return releases strictly newer

    Returns HTTP 404 if no matching release exists.
    """
    store = _get_store()
    if not store:
        raise HTTPException(status_code=404, detail="No OTA releases registered")

    # Collect candidates filtered by device_type.
    dt_filter = (device_type or "").lower()
    candidates = [
        v for (dt, ver), v in store.items()
        if (not dt_filter or dt == dt_filter)
    ]

    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=f"No OTA releases for device_type={device_type!r}",
        )

    # Sort descending by version and pick the latest.
    candidates.sort(key=lambda r: _version_tuple(r["version"]), reverse=True)
    latest = candidates[0]

    # If the device already has this version (or newer), return 404.
    if current_version:
        if _version_tuple(latest["version"]) <= _version_tuple(current_version):
            raise HTTPException(
                status_code=404,
                detail="Device is already on the latest version",
            )

    return ManifestResponse(**latest)
