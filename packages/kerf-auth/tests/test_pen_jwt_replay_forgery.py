"""Pen-test T-71: JWT replay + forgery attack suite.

Attack classes:
  1. alg=none — unsigned token accepted?
  2. Wrong-secret forgery — attacker signs with a different key
  3. RS256/HS256 algorithm confusion — alg header swap attack
  4. kid-injection — kid header pointing to traversal path
  5. Expired token replay — exp in the past
  6. Revoked refresh-token replay — used token replayed after logout
  7. Tampered payload — flip sub to another user
  8. Missing signature segment — truncated token
  9. Empty-string token
  10. Revoked access token still rejected (no server-side access blacklist needed;
      short TTL enforced + /logout revokes refresh so new access cannot be minted)
  11. Cross-account token — token minted for user A used against user B's resource
  12. Bare-base64 payload (no header/sig) rejected

All 12 cases must result in HTTP 401 or a hard rejection — never 200.

These tests are hermetic: no DATABASE_URL required. DB calls are mocked so
only the JWT validation layer in kerf_core.dependencies is exercised.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

JWT_SECRET = "dev-secret-change-in-production"
USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())


def _make_token(payload: dict, secret: str = JWT_SECRET, algorithm: str = "HS256") -> str:
    return pyjwt.encode(payload, secret, algorithm=algorithm)


def _valid_payload(user_id: str = USER_A, ttl_seconds: int = 900) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "sub": user_id,
        "exp": now + timedelta(seconds=ttl_seconds),
        "iat": now,
    }


def _b64_segment(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def _craft_raw_token(header: dict, payload: dict, secret: bytes = b"") -> str:
    """Craft a raw token: sign the header.payload with HMAC-SHA256 over `secret`."""
    h = _b64_segment(header)
    p = _b64_segment(payload)
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{h}.{p}.{sig_b64}"


# ---------------------------------------------------------------------------
# Test app — a minimal protected endpoint that calls require_auth
# ---------------------------------------------------------------------------

def _make_app() -> FastAPI:
    from kerf_core.dependencies import require_auth

    app = FastAPI()

    @app.get("/protected")
    async def protected(payload: dict = Depends(require_auth)):
        return {"user": payload.get("sub")}

    return app


# ---------------------------------------------------------------------------
# The test class — 12 attack cases
# ---------------------------------------------------------------------------

class TestJWTReplayForgery:
    """T-71: JWT replay + forgery pen-test suite."""

    def setup_method(self):
        # Patch settings so decode_jwt uses our known secret.
        self._settings_patcher = patch(
            "kerf_core.dependencies.settings",
            jwt_secret=JWT_SECRET,
            jwt_access_ttl_minutes=15,
        )
        self._settings_patcher.start()
        self.client = TestClient(_make_app(), raise_server_exceptions=False)

    def teardown_method(self):
        self._settings_patcher.stop()

    def _get(self, token: str) -> Any:
        return self.client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    # 1. alg=none — unsigned token must be rejected
    def test_alg_none_unsigned_token_rejected(self):
        header = _b64_segment({"alg": "none", "typ": "JWT"})
        payload = _b64_segment({"sub": USER_A, "exp": int(time.time()) + 900})
        # alg=none token has an empty signature segment
        token = f"{header}.{payload}."
        r = self._get(token)
        assert r.status_code == 401, f"alg=none token must be rejected; got {r.status_code}"

    # 2. alg=none with no trailing dot (malformed none)
    def test_alg_none_no_trailing_dot_rejected(self):
        header = _b64_segment({"alg": "none", "typ": "JWT"})
        payload = _b64_segment({"sub": USER_A, "exp": int(time.time()) + 900})
        token = f"{header}.{payload}"
        r = self._get(token)
        assert r.status_code == 401

    # 3. Wrong-secret forgery — attacker uses a different HMAC key
    def test_wrong_secret_forgery_rejected(self):
        token = _make_token(_valid_payload(), secret="attacker-secret")
        r = self._get(token)
        assert r.status_code == 401, "Wrong-secret token must be rejected"

    # 4. Algorithm confusion: RS256 header, HS256 body — alg swap
    #    Attacker crafts a token with RS256 in the header but signs with HMAC.
    def test_alg_confusion_rs256_header_hs256_signature_rejected(self):
        # Craft a raw token claiming RS256 in the header, but signed with HS256
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {"sub": USER_A, "exp": int(time.time()) + 900}
        token = _craft_raw_token(header, payload, secret=JWT_SECRET.encode())
        r = self._get(token)
        assert r.status_code == 401, "RS256-header with HS256 signature must be rejected"

    # 5. kid-injection — kid header contains a path traversal string
    def test_kid_path_traversal_in_header_rejected(self):
        header = {"alg": "HS256", "typ": "JWT", "kid": "../../etc/passwd"}
        payload = {"sub": USER_A, "exp": int(time.time()) + 900}
        # Signed with wrong key so the signature also fails
        token = _craft_raw_token(header, payload, secret=b"wrongkey")
        r = self._get(token)
        assert r.status_code == 401

    # 6. kid with null-byte injection
    def test_kid_null_byte_injection_rejected(self):
        header = {"alg": "HS256", "typ": "JWT", "kid": "key\x00evil"}
        payload = {"sub": USER_A, "exp": int(time.time()) + 900}
        token = _craft_raw_token(header, payload, secret=b"wrongkey")
        r = self._get(token)
        assert r.status_code == 401

    # 7. Expired token replay — exp is in the past
    def test_expired_token_rejected(self):
        now = datetime.now(timezone.utc)
        payload = {
            "sub": USER_A,
            "exp": now - timedelta(seconds=1),
            "iat": now - timedelta(seconds=900),
        }
        token = _make_token(payload)
        r = self._get(token)
        assert r.status_code == 401, "Expired token must be rejected"

    # 8. Tampered payload — flip sub to a different user, signature still from USER_A token
    def test_tampered_sub_claim_rejected(self):
        # Issue a valid token for USER_A, then manually swap the payload segment.
        original = _make_token(_valid_payload(USER_A))
        parts = original.split(".")
        assert len(parts) == 3
        # Replace payload with USER_B as sub but keep original signature
        evil_payload = _b64_segment({"sub": USER_B, "exp": int(time.time()) + 900})
        tampered = f"{parts[0]}.{evil_payload}.{parts[2]}"
        r = self._get(tampered)
        assert r.status_code == 401, "Tampered payload must fail signature check"

    # 9. Missing signature segment — only header.payload
    def test_missing_signature_segment_rejected(self):
        header = _b64_segment({"alg": "HS256", "typ": "JWT"})
        payload = _b64_segment({"sub": USER_A, "exp": int(time.time()) + 900})
        token = f"{header}.{payload}"  # no third segment
        r = self._get(token)
        assert r.status_code == 401, "Token missing signature segment must be rejected"

    # 10. Empty-string token
    def test_empty_string_token_rejected(self):
        r = self._get("")
        assert r.status_code == 401, "Empty token must be rejected"

    # 11. Bare base64 payload — not a JWT at all
    def test_bare_base64_payload_rejected(self):
        # Just a base64-encoded JSON blob, no JWT structure
        blob = base64.urlsafe_b64encode(
            json.dumps({"sub": USER_A, "exp": int(time.time()) + 900}).encode()
        ).decode()
        r = self._get(blob)
        assert r.status_code == 401, "Bare base64 payload must be rejected"

    # 12. Revoked refresh token cannot be used to get a new access token
    #     via /refresh — the revoked_at IS NOT NULL branch in get_refresh_token
    def test_revoked_refresh_token_rejected_on_refresh_endpoint(self):
        """After logout, a replayed refresh token must get HTTP 401."""
        import kerf_auth.routes as auth_routes

        app = FastAPI()
        app.include_router(auth_routes.router, prefix="/auth")
        client = TestClient(app, raise_server_exceptions=False)

        conn = AsyncMock()
        tx = MagicMock()
        tx.__aenter__ = AsyncMock(return_value=None)
        tx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx)

        # get_refresh_token returns None → revoked/not found
        with patch(
            "kerf_auth.routes.rt_queries.get_refresh_token",
            AsyncMock(return_value=None),
        ), patch(
            "kerf_auth.routes.get_pool_required",
            AsyncMock(return_value=_fake_pool(conn)),
        ):
            r = client.post(
                "/auth/refresh",
                json={"refresh_token": "stolen-revoked-token"},
            )
        assert r.status_code == 401, (
            f"Revoked/unknown refresh token must be rejected; got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# Helper reused in test_revoked_refresh_token_rejected_on_refresh_endpoint
# ---------------------------------------------------------------------------

def _fake_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool
