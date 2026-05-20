"""Hermetic tests for POST /v1/ota/release and GET /v1/ota/manifest/{device_id}.

T-261 Definition-of-Done oracles:
  1. POST /v1/ota/release with a valid signed manifest → HTTP 201.
  2. POST /v1/ota/release with an unsigned (tampered) payload → HTTP 401.
  3. GET  /v1/ota/manifest/{device_id} returns the most recent compatible release.
  4. GET  /v1/ota/manifest/{device_id} with current_version >= latest → HTTP 404.
  5. GET  /v1/ota/manifest/{device_id} with no releases → HTTP 404.
  6. POST with missing required fields → HTTP 422 (Pydantic validation).
  7. POST with wrong public_key length → HTTP 400.
  8. Multiple releases → manifest returns the highest version.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kerf_api.routes_ota import router, _clear_store


# ---------------------------------------------------------------------------
# Fixture: TestClient + auto-clear store between tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture
def client(app):
    _clear_store()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_release(version="1.2.3", device_type="esp32"):
    """Return a dict suitable for POST /v1/ota/release that has a valid signature."""
    from kerf_firmware.ota.sign import OTASigner

    payload = os.urandom(256)
    signer = OTASigner.from_new_keypair()
    manifest = signer.sign_bytes(
        payload,
        version=version,
        device_type=device_type,
        download_url=f"https://cdn.example.com/fw-{version}.bin",
        timestamp=1700000000,
    )
    return json.loads(manifest.to_json())


def _make_tampered_release(version="1.2.3", device_type="esp32"):
    """Valid manifest but with the signature corrupted."""
    d = _make_valid_release(version=version, device_type=device_type)
    # Flip the last byte of the hex signature.
    sig_bytes = bytearray(bytes.fromhex(d["ed25519_signature"]))
    sig_bytes[-1] ^= 0xFF
    d["ed25519_signature"] = sig_bytes.hex()
    return d


# ---------------------------------------------------------------------------
# Oracle 1: valid signed release → 201
# ---------------------------------------------------------------------------

class TestReleaseEndpoint:

    def test_valid_release_accepted(self, client):
        payload = _make_valid_release()
        r = client.post("/v1/ota/release", json=payload)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["version"] == "1.2.3"
        assert body["device_type"] == "esp32"

    # Oracle 2: tampered signature → 401
    def test_unsigned_payload_rejected_401(self, client):
        payload = _make_tampered_release()
        r = client.post("/v1/ota/release", json=payload)
        assert r.status_code == 401, r.text

    # Oracle 6: missing required fields → 422
    def test_missing_fields_rejected_422(self, client):
        r = client.post("/v1/ota/release", json={"version": "1.0.0"})
        assert r.status_code == 422

    # Oracle 7: wrong public_key length → 400
    def test_wrong_public_key_length_rejected_400(self, client):
        d = _make_valid_release()
        d["public_key"] = "deadbeef"  # 4 bytes, not 32
        r = client.post("/v1/ota/release", json=d)
        assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# Oracle 3: GET /v1/ota/manifest returns the most recent release
# ---------------------------------------------------------------------------

class TestManifestEndpoint:

    def test_manifest_returns_registered_release(self, client):
        # Register a release first.
        d = _make_valid_release(version="1.0.0", device_type="esp32")
        r = client.post("/v1/ota/release", json=d)
        assert r.status_code == 201

        r = client.get("/v1/ota/manifest/device-abc?device_type=esp32")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["version"] == "1.0.0"
        assert body["device_type"] == "esp32"
        assert body["sha256"] == d["sha256"]
        assert body["download_url"] == d["download_url"]

    # Oracle 5: no releases → 404
    def test_no_releases_returns_404(self, client):
        r = client.get("/v1/ota/manifest/device-xyz?device_type=esp32")
        assert r.status_code == 404

    # Oracle 4: current_version >= latest → 404
    def test_already_latest_returns_404(self, client):
        d = _make_valid_release(version="2.0.0", device_type="stm32")
        client.post("/v1/ota/release", json=d)

        r = client.get(
            "/v1/ota/manifest/device-abc",
            params={"device_type": "stm32", "current_version": "2.0.0"},
        )
        assert r.status_code == 404, "Same version should return 404"

    def test_older_current_version_gets_update(self, client):
        d = _make_valid_release(version="3.0.0", device_type="samd")
        client.post("/v1/ota/release", json=d)

        r = client.get(
            "/v1/ota/manifest/dev-1",
            params={"device_type": "samd", "current_version": "2.9.9"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["version"] == "3.0.0"

    # Oracle 8: multiple releases → highest version returned
    def test_multiple_releases_returns_highest(self, client):
        for ver in ["1.0.0", "1.1.0", "1.2.0"]:
            d = _make_valid_release(version=ver, device_type="esp32")
            r = client.post("/v1/ota/release", json=d)
            assert r.status_code == 201

        r = client.get("/v1/ota/manifest/dev-multi?device_type=esp32")
        assert r.status_code == 200
        assert r.json()["version"] == "1.2.0"

    def test_device_type_filter_applied(self, client):
        d_esp = _make_valid_release(version="5.0.0", device_type="esp32")
        d_stm = _make_valid_release(version="9.9.9", device_type="stm32")
        client.post("/v1/ota/release", json=d_esp)
        client.post("/v1/ota/release", json=d_stm)

        r = client.get("/v1/ota/manifest/dev-x?device_type=esp32")
        assert r.status_code == 200
        assert r.json()["version"] == "5.0.0"

        r2 = client.get("/v1/ota/manifest/dev-x?device_type=stm32")
        assert r2.status_code == 200
        assert r2.json()["version"] == "9.9.9"
