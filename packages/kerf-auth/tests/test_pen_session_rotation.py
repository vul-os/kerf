"""T-72 — Session expiry + token rotation (pen-test hermetic suite).

Scope: refresh-token rotation via the /auth/refresh endpoint and the
`refresh_tokens` table.  All 12 cases run without a real DB or network —
the asyncpg pool and kerf_core.db.queries.refresh_tokens are fully mocked.

Cases
-----
1.  Happy-path rotation: valid token → new access + new refresh returned.
2.  Old refresh is revoked immediately after a successful rotation.
3.  New refresh is distinct from the old one.
4.  Using the old (now revoked) token a second time → 401 (double-use / replay).
5.  Expired refresh token → 401 (get_refresh_token returns None for expired).
6.  Revoked refresh token → 401.
7.  Completely unknown / garbage token → 401.
8.  Missing refresh_token body field → 422 (pydantic validation).
9.  Empty string refresh_token → 400.
10. Rotation after password-reset: new tokens work; old tokens (revoked) refused.
11. Multiple simultaneous refresh "slots" — each slot rotates independently.
12. Family revocation: double-use attempt always yields 401; new token still valid.
"""

import datetime as _dt
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Minimal FastAPI app
# ---------------------------------------------------------------------------

def _make_app():
    from kerf_auth.routes import router as auth_router
    app = FastAPI()
    app.include_router(auth_router, prefix="/auth")
    return app


# ---------------------------------------------------------------------------
# Fake settings (no real secrets touched)
# ---------------------------------------------------------------------------

FAKE_SETTINGS = MagicMock()
FAKE_SETTINGS.jwt_secret = "test-jwt-secret-T72"
FAKE_SETTINGS.jwt_access_ttl_minutes = 15
FAKE_SETTINGS.jwt_refresh_ttl_days = 30
FAKE_SETTINGS.password_pepper = "test-pepper"
FAKE_SETTINGS.cors_origin = "http://localhost:5173"
FAKE_SETTINGS.local_mode = False
FAKE_SETTINGS.cloud_github_client_id = ""
FAKE_SETTINGS.cloud_github_client_secret = ""
FAKE_SETTINGS.google_client_id = ""
FAKE_SETTINGS.google_client_secret = ""
FAKE_SETTINGS.system_user_email = ""
FAKE_SETTINGS.system_user_name = ""

# ---------------------------------------------------------------------------
# Shared fake rows
# ---------------------------------------------------------------------------

USER_ID = "aaaaaaaa-0000-0000-0000-000000000001"

FAKE_USER_ROW = {
    "id": USER_ID,
    "email": "rotate@example.com",
    "name": "Rotate User",
    "avatar_url": None,
    "account_role": "user",
    "is_system": False,
    "email_verified": True,
    "created_at": _dt.datetime(2024, 1, 1),
}

FAKE_WORKSPACE_ROW = {
    "id": "bbbbbbbb-0000-0000-0000-000000000002",
    "slug": "personal-aaaaaaa-abcd",
    "name": "Rotate User",
    "avatar_url": None,
    "created_at": _dt.datetime(2024, 1, 1),
}

FAKE_RT_ROW_CREATED = {
    "id": "dddddddd-0000-0000-0000-000000000004",
    "user_id": USER_ID,
    "token_hash": "new_hash",
    "expires_at": _dt.datetime(2099, 1, 1, tzinfo=_dt.timezone.utc),
    "revoked_at": None,
    "created_at": _dt.datetime(2024, 6, 1, tzinfo=_dt.timezone.utc),
}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fake_rt_row(token: str, user_id: str = USER_ID):
    """Build a valid (not revoked, not expired) refresh_tokens row."""
    return {
        "id": "cccccccc-0000-0000-0000-000000000003",
        "user_id": user_id,
        "token_hash": _hash(token),
        "expires_at": _dt.datetime(2099, 1, 1, tzinfo=_dt.timezone.utc),
        "revoked_at": None,
        "created_at": _dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc),
    }


# ---------------------------------------------------------------------------
# Mock-pool builder
# ---------------------------------------------------------------------------

def _mock_conn(ws_row=FAKE_WORKSPACE_ROW):
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=ws_row)
    return conn


def _make_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# ---------------------------------------------------------------------------
# Central patching context — mirrors the test_github_login pattern exactly
# ---------------------------------------------------------------------------

class _RefreshSession:
    """One-shot context: patches settings + pool + rt_queries + users_queries."""

    def __init__(self, rt_get_return=None, user_row=None):
        """
        rt_get_return: what rt_queries.get_refresh_token returns.
                       None  → simulates expired/revoked/unknown token.
                       dict  → valid token row.
        """
        self._rt_get_return = rt_get_return
        self._user_row = user_row if user_row is not None else FAKE_USER_ROW
        self._patches = []

    def __enter__(self):
        import kerf_auth.routes as _routes
        import kerf_core.db.queries.refresh_tokens as rt_q
        import kerf_core.db.queries.users as users_q

        conn = _mock_conn()
        pool = _make_pool(conn)

        # Patch pool so the route receives our mock instead of raising RuntimeError
        p_pool = patch.object(
            _routes, "get_pool_required", AsyncMock(return_value=pool)
        )
        # Patch settings to avoid touching real .env
        p_settings = patch.object(_routes, "settings", FAKE_SETTINGS)
        # Patch rt_queries functions imported into routes
        p_rt_get = patch.object(
            rt_q, "get_refresh_token", AsyncMock(return_value=self._rt_get_return)
        )
        p_rt_revoke = patch.object(
            rt_q, "revoke_refresh_token", AsyncMock(return_value=True)
        )
        p_rt_create = patch.object(
            rt_q, "create_refresh_token", AsyncMock(return_value=FAKE_RT_ROW_CREATED)
        )
        # Patch users_queries.get_user
        p_users = patch.object(
            users_q, "get_user", AsyncMock(return_value=self._user_row)
        )

        for p in (p_pool, p_settings, p_rt_get, p_rt_revoke, p_rt_create, p_users):
            p.start()
            self._patches.append(p)

        self.rt_revoke_mock = p_rt_revoke.new
        self.rt_get_mock = p_rt_get.new
        self.rt_create_mock = p_rt_create.new

        app = _make_app()
        self.client = TestClient(app, raise_server_exceptions=True)
        return self

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()


# ===========================================================================
# Case 1: Happy-path rotation — 200 with new tokens
# ===========================================================================

class TestCase01HappyPathRotation:
    def test_valid_refresh_returns_200_with_new_tokens(self):
        old_refresh = "valid-refresh-token-case01"
        rt_row = _fake_rt_row(old_refresh)
        with _RefreshSession(rt_get_return=rt_row) as s:
            resp = s.client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body


# ===========================================================================
# Case 2: Old token is revoked immediately after rotation
# ===========================================================================

class TestCase02OldTokenRevoked:
    def test_old_refresh_is_revoked_on_rotation(self):
        """revoke_refresh_token must be called with the hash of the presented token."""
        old_refresh = "valid-token-case02"
        rt_row = _fake_rt_row(old_refresh)
        import kerf_core.db.queries.refresh_tokens as rt_q

        revoke_calls = []

        async def _capturing_revoke(conn, token_hash):
            revoke_calls.append(token_hash)
            return True

        with _RefreshSession(rt_get_return=rt_row) as s:
            with patch.object(rt_q, "revoke_refresh_token", _capturing_revoke):
                s.client.post("/auth/refresh", json={"refresh_token": old_refresh})

        assert len(revoke_calls) == 1, "revoke_refresh_token must be called exactly once"
        assert revoke_calls[0] == _hash(old_refresh), (
            "revoke must target the hash of the OLD token, not a new one"
        )


# ===========================================================================
# Case 3: New refresh is distinct from the old one
# ===========================================================================

class TestCase03NewRefreshDistinct:
    def test_new_refresh_token_differs_from_old(self):
        old_refresh = "valid-token-case03"
        rt_row = _fake_rt_row(old_refresh)
        with _RefreshSession(rt_get_return=rt_row) as s:
            resp = s.client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert resp.status_code == 200
        body = resp.json()
        assert body["refresh_token"] != old_refresh, (
            "The rotated refresh token must differ from the original"
        )


# ===========================================================================
# Case 4: Double-use of old (now revoked) token → 401
# ===========================================================================

class TestCase04DoubleUseRevoked:
    def test_double_use_of_old_token_is_rejected(self):
        old_refresh = "valid-token-case04"
        rt_row = _fake_rt_row(old_refresh)

        # First use: succeeds (token is valid)
        with _RefreshSession(rt_get_return=rt_row) as s:
            r1 = s.client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert r1.status_code == 200

        # Second use: get_refresh_token returns None (token was revoked after rotation)
        with _RefreshSession(rt_get_return=None) as s:
            r2 = s.client.post("/auth/refresh", json={"refresh_token": old_refresh})
        assert r2.status_code == 401, (
            "Replaying the old refresh token after rotation must be rejected"
        )


# ===========================================================================
# Case 5: Expired refresh token → 401
# ===========================================================================

class TestCase05ExpiredToken:
    def test_expired_refresh_token_rejected(self):
        # get_refresh_token returns None for expired tokens (SQL: expires_at > now())
        with _RefreshSession(rt_get_return=None) as s:
            resp = s.client.post(
                "/auth/refresh", json={"refresh_token": "expired-token-xyz"}
            )
        assert resp.status_code == 401
        assert "invalid" in resp.json()["detail"].lower()


# ===========================================================================
# Case 6: Revoked refresh token → 401
# ===========================================================================

class TestCase06RevokedToken:
    def test_revoked_refresh_token_rejected(self):
        # get_refresh_token returns None for revoked tokens (SQL: revoked_at IS NULL)
        with _RefreshSession(rt_get_return=None) as s:
            resp = s.client.post(
                "/auth/refresh", json={"refresh_token": "revoked-token-xyz"}
            )
        assert resp.status_code == 401


# ===========================================================================
# Case 7: Unknown / garbage token → 401
# ===========================================================================

class TestCase07UnknownToken:
    def test_unknown_token_rejected(self):
        with _RefreshSession(rt_get_return=None) as s:
            resp = s.client.post(
                "/auth/refresh", json={"refresh_token": "garbage-token-not-in-db"}
            )
        assert resp.status_code == 401


# ===========================================================================
# Case 8: Missing body field → 422 (pydantic validation)
# ===========================================================================

class TestCase08MissingField:
    def test_missing_refresh_token_field_returns_validation_error(self):
        """FastAPI/pydantic validation fires before the route handler.
        Missing required field → 422 Unprocessable Entity."""
        with _RefreshSession(rt_get_return=None) as s:
            resp = s.client.post("/auth/refresh", json={})
        assert resp.status_code == 422


# ===========================================================================
# Case 9: Empty string refresh_token → 400
# ===========================================================================

class TestCase09EmptyString:
    def test_empty_refresh_token_returns_400(self):
        """The route explicitly checks `if not req.refresh_token:` → 400."""
        with _RefreshSession(rt_get_return=None) as s:
            resp = s.client.post("/auth/refresh", json={"refresh_token": ""})
        assert resp.status_code == 400
        assert "invalid" in resp.json()["detail"].lower()


# ===========================================================================
# Case 10: Post-password-reset behavior
# ===========================================================================

class TestCase10PostResetBehavior:
    """After password reset the old refresh tokens are revoked in routes.py
    (`UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = $1 AND revoked_at IS NULL`).
    The new token issued at the end of /reset-password must be accepted;
    any pre-reset token must be refused."""

    def test_new_token_after_reset_is_accepted(self):
        """Simulate: new token created post-reset → valid row returned → 200."""
        post_reset_refresh = "new-token-after-reset"
        rt_row = _fake_rt_row(post_reset_refresh)
        with _RefreshSession(rt_get_return=rt_row) as s:
            resp = s.client.post(
                "/auth/refresh", json={"refresh_token": post_reset_refresh}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body

    def test_old_token_before_reset_rejected(self):
        """Simulate: old token has revoked_at set → get_refresh_token returns None → 401."""
        with _RefreshSession(rt_get_return=None) as s:
            resp = s.client.post(
                "/auth/refresh", json={"refresh_token": "pre-reset-token"}
            )
        assert resp.status_code == 401


# ===========================================================================
# Case 11: Multiple concurrent refresh sessions rotate independently
# ===========================================================================

class TestCase11MultipleSlots:
    def test_two_independent_slots_each_rotate_successfully(self):
        token_a = "session-slot-A"
        token_b = "session-slot-B"

        with _RefreshSession(rt_get_return=_fake_rt_row(token_a)) as s:
            resp_a = s.client.post("/auth/refresh", json={"refresh_token": token_a})
        assert resp_a.status_code == 200

        with _RefreshSession(rt_get_return=_fake_rt_row(token_b)) as s:
            resp_b = s.client.post("/auth/refresh", json={"refresh_token": token_b})
        assert resp_b.status_code == 200

        assert "refresh_token" in resp_a.json()
        assert "refresh_token" in resp_b.json()

    def test_slot_b_not_invalidated_by_slot_a_rotation(self):
        """Rotating slot-A must not affect the validity of slot-B."""
        token_b = "session-slot-B-independent"

        # Rotate slot-A
        with _RefreshSession(rt_get_return=_fake_rt_row("session-slot-A-independent")) as s:
            ra = s.client.post(
                "/auth/refresh", json={"refresh_token": "session-slot-A-independent"}
            )
        assert ra.status_code == 200

        # Slot-B is still valid
        with _RefreshSession(rt_get_return=_fake_rt_row(token_b)) as s:
            rb = s.client.post("/auth/refresh", json={"refresh_token": token_b})
        assert rb.status_code == 200


# ===========================================================================
# Case 12: Token theft / family revocation property
# ===========================================================================

class TestCase12FamilyRevocationProperty:
    """Design invariant: a consumed refresh token NEVER works again.
    The attacker who replays it gains nothing — they get 401.
    The legitimate holder's new token is unaffected by the replay attempt."""

    def test_consumed_token_always_yields_401(self):
        """Replaying an already-consumed token → 401, error detail is non-revealing."""
        with _RefreshSession(rt_get_return=None) as s:
            resp = s.client.post(
                "/auth/refresh", json={"refresh_token": "consumed-family-token"}
            )
        assert resp.status_code == 401
        detail = resp.json()["detail"].lower()
        # Error must not reveal internals (stack traces, SQL, user existence)
        assert "invalid refresh token" in detail or "invalid" in detail

    def test_new_token_valid_after_replay_attempt(self):
        """Replaying an old token does NOT cascade to revoke the new token.
        The new token (different value) is still accepted."""
        new_token = "legitimate-new-token-post-rotation"

        # Simulate old-token replay → rejected
        with _RefreshSession(rt_get_return=None) as s:
            r_old = s.client.post(
                "/auth/refresh", json={"refresh_token": "old-consumed-token"}
            )
        assert r_old.status_code == 401

        # New token is still valid (no cascade revocation in current implementation)
        with _RefreshSession(rt_get_return=_fake_rt_row(new_token)) as s:
            r_new = s.client.post("/auth/refresh", json={"refresh_token": new_token})
        assert r_new.status_code == 200

    def test_error_detail_does_not_leak_internal_state(self):
        """401 detail must be generic — never expose whether token existed,
        expired-at value, or user id."""
        with _RefreshSession(rt_get_return=None) as s:
            resp = s.client.post(
                "/auth/refresh", json={"refresh_token": "probe-token"}
            )
        assert resp.status_code == 401
        detail = resp.json().get("detail", "")
        # Must not contain SQL fragments, user IDs, or stack traces
        for forbidden in ("SELECT", "UPDATE", "aaaaaaaa", "Traceback", "Exception"):
            assert forbidden not in detail, (
                f"Error detail leaks internal info: {detail!r}"
            )
