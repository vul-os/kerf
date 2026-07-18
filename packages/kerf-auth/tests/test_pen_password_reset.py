"""T-73 — Password-reset token: single-use, ≤30 min expiry, account-bound.

12 hermetic cases (no DB required — asyncpg mocked):

  C01  valid token → 200 + new tokens issued
  C02  token consumed (used_at IS NOT NULL) → 400
  C03  token expired (expires_at in the past) → 400
  C04  token kind != 'reset' (e.g. 'verify') → 400
  C05  blank token string → 400
  C06  password too short (< 8 chars) → 400
  C07  missing password field entirely → 422 (Pydantic)
  C08  successful reset marks token used (used_at = now())
  C09  successful reset updates password_hash in users table
  C10  successful reset revokes all existing refresh tokens for that user
  C11  cross-account: token for user_a cannot be used to set user_b password
       (token_hash lookup returns the bound user; reset applies only to that user)
  C12  reset token TTL ≤ 30 min (RESET_TOKEN_TTL constant)
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import kerf_auth.routes as auth


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _app():
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    return app


def _fake_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _conn_with_tx():
    """Return a mock asyncpg connection whose .transaction() ctx-manager works."""
    conn = AsyncMock()
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    return conn


def _valid_token_row(user_id="u-reset-1"):
    """Simulate email_tokens row returned when token is valid."""
    return {"id": "tok-1", "user_id": user_id}


def _valid_user_row(user_id="u-reset-1"):
    """Simulate users row returned after reset."""
    from datetime import datetime, timezone
    return {
        "id": user_id,
        "email": "reset@example.com",
        "name": "Reset User",
        "avatar_url": None,
        "account_role": "user",
        "is_system": False,
        "email_verified": True,
        "created_at": datetime.now(timezone.utc),
        "password_hash": "newbcrypthash",
    }


def _patch_valid_reset(conn, user_id="u-reset-1"):
    """Configure conn for a valid reset path:
    - fetchrow returns a valid token row (first call),
    - then a valid user row (second call after update).
    """
    token_row = _valid_token_row(user_id)
    user_row = _valid_user_row(user_id)
    conn.fetchrow = AsyncMock(side_effect=[token_row, user_row])
    conn.execute = AsyncMock()


# ---------------------------------------------------------------------------
# C01  Valid token → 200 with new tokens issued
# ---------------------------------------------------------------------------

def test_c01_valid_token_returns_200_with_tokens():
    conn = _conn_with_tx()
    _patch_valid_reset(conn)
    with patch.object(auth, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(auth, "issue_tokens", AsyncMock(return_value=("acc-tok", "ref-tok"))), \
         patch.object(auth, "get_default_workspace", AsyncMock(return_value=(None, False))):
        c = TestClient(_app())
        r = c.post("/auth/reset-password", json={"token": "goodtoken", "password": "newpassword1"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] == "acc-tok"
    assert body["refresh_token"] == "ref-tok"


# ---------------------------------------------------------------------------
# C02  Token already consumed (fetchrow returns None → invalid-or-expired path)
# ---------------------------------------------------------------------------

def test_c02_used_token_returns_400():
    """DB returns no row (used_at IS NOT NULL filtered out) → 400."""
    conn = _conn_with_tx()
    conn.fetchrow = AsyncMock(return_value=None)
    with patch.object(auth, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))):
        c = TestClient(_app())
        r = c.post("/auth/reset-password", json={"token": "usedtoken", "password": "newpassword1"})
    assert r.status_code == 400
    assert "invalid" in r.json()["detail"].lower() or "expired" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# C03  Expired token (fetchrow returns None because expires_at filter fails)
# ---------------------------------------------------------------------------

def test_c03_expired_token_returns_400():
    """Token past its TTL: DB WHERE expires_at > now() excludes it → None."""
    conn = _conn_with_tx()
    conn.fetchrow = AsyncMock(return_value=None)
    with patch.object(auth, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))):
        c = TestClient(_app())
        r = c.post("/auth/reset-password", json={"token": "expiredtoken", "password": "newpassword1"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# C04  Token of wrong kind ('verify') → 400 (fetchrow returns None because kind='reset' filter)
# ---------------------------------------------------------------------------

def test_c04_wrong_kind_token_returns_400():
    """A verify-email token cannot be used for password reset (kind mismatch)."""
    conn = _conn_with_tx()
    conn.fetchrow = AsyncMock(return_value=None)
    with patch.object(auth, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))):
        c = TestClient(_app())
        r = c.post("/auth/reset-password", json={"token": "verifytok", "password": "newpassword1"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# C05  Blank token → 400 (route guard: `not req.token`)
# ---------------------------------------------------------------------------

def test_c05_blank_token_returns_400():
    c = TestClient(_app())
    r = c.post("/auth/reset-password", json={"token": "", "password": "newpassword1"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# C06  Password too short (< 8 chars) → 400
# ---------------------------------------------------------------------------

def test_c06_short_password_returns_400():
    c = TestClient(_app())
    r = c.post("/auth/reset-password", json={"token": "sometoken", "password": "short"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# C07  Missing password field → 422 (Pydantic validation)
# ---------------------------------------------------------------------------

def test_c07_missing_password_field_returns_422():
    c = TestClient(_app())
    r = c.post("/auth/reset-password", json={"token": "sometoken"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# C08  Successful reset marks token used (UPDATE email_tokens SET used_at=now())
# ---------------------------------------------------------------------------

def test_c08_successful_reset_marks_token_consumed():
    conn = _conn_with_tx()
    _patch_valid_reset(conn)
    with patch.object(auth, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(auth, "issue_tokens", AsyncMock(return_value=("at", "rt"))), \
         patch.object(auth, "get_default_workspace", AsyncMock(return_value=(None, False))):
        c = TestClient(_app())
        c.post("/auth/reset-password", json={"token": "goodtoken", "password": "newpassword1"})
    sqls = " ".join(str(call.args[0]) for call in conn.execute.await_args_list)
    assert "UPDATE email_tokens SET used_at = now()" in sqls


# ---------------------------------------------------------------------------
# C09  Successful reset updates the user's password_hash
# ---------------------------------------------------------------------------

def test_c09_successful_reset_updates_password_hash():
    conn = _conn_with_tx()
    _patch_valid_reset(conn)
    with patch.object(auth, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(auth, "issue_tokens", AsyncMock(return_value=("at", "rt"))), \
         patch.object(auth, "get_default_workspace", AsyncMock(return_value=(None, False))):
        c = TestClient(_app())
        c.post("/auth/reset-password", json={"token": "goodtoken", "password": "newpassword1"})
    sqls = " ".join(str(call.args[0]) for call in conn.execute.await_args_list)
    assert "UPDATE users SET password_hash" in sqls


# ---------------------------------------------------------------------------
# C10  Successful reset revokes all existing refresh tokens for that user
# ---------------------------------------------------------------------------

def test_c10_successful_reset_revokes_existing_sessions():
    conn = _conn_with_tx()
    _patch_valid_reset(conn)
    with patch.object(auth, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(auth, "issue_tokens", AsyncMock(return_value=("at", "rt"))), \
         patch.object(auth, "get_default_workspace", AsyncMock(return_value=(None, False))):
        c = TestClient(_app())
        c.post("/auth/reset-password", json={"token": "goodtoken", "password": "newpassword1"})
    sqls = " ".join(str(call.args[0]) for call in conn.execute.await_args_list)
    assert "UPDATE refresh_tokens SET revoked_at = now()" in sqls


# ---------------------------------------------------------------------------
# C11  Cross-account: token for user_a applies only to user_a (account-bound)
#
#  The token row carries user_id from DB; the route updates that specific user.
#  We verify the UPDATE users WHERE id = <user_a_id> does NOT target user_b.
# ---------------------------------------------------------------------------

def test_c11_reset_is_bound_to_tokens_user_id():
    user_a_id = "u-aaaaaa"
    user_b_id = "u-bbbbbb"

    conn = _conn_with_tx()
    # Token row is bound to user_a
    token_row = {"id": "tok-a", "user_id": user_a_id}
    user_a_row = _valid_user_row(user_a_id)
    conn.fetchrow = AsyncMock(side_effect=[token_row, user_a_row])
    conn.execute = AsyncMock()

    with patch.object(auth, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(auth, "issue_tokens", AsyncMock(return_value=("at", "rt"))), \
         patch.object(auth, "get_default_workspace", AsyncMock(return_value=(None, False))):
        c = TestClient(_app())
        r = c.post("/auth/reset-password", json={"token": "user_a_token", "password": "newpassword1"})

    assert r.status_code == 200
    # All UPDATE calls must use user_a's id, never user_b's id.
    for call in conn.execute.await_args_list:
        args = call.args
        # If the SQL targets users or refresh_tokens by user_id, it must be user_a
        if len(args) >= 2 and isinstance(args[0], str):
            if "UPDATE users SET password_hash" in args[0] or \
               "UPDATE refresh_tokens SET revoked_at" in args[0]:
                assert user_b_id not in str(args), \
                    f"cross-account: SQL targeted user_b: {args}"
                assert user_a_id in str(args), \
                    f"cross-account: SQL should target user_a: {args}"


# ---------------------------------------------------------------------------
# C12  Reset token TTL ≤ 30 minutes (spec: ≤ 30 min expiry)
# ---------------------------------------------------------------------------

def test_c12_reset_token_ttl_is_at_most_30_minutes():
    """RESET_TOKEN_TTL constant must be ≤ 30 minutes per the T-73 spec."""
    ttl: timedelta = auth.RESET_TOKEN_TTL
    assert ttl <= timedelta(minutes=30), (
        f"RESET_TOKEN_TTL is {ttl}, must be ≤ 30 min per T-73 spec "
        f"(currently {int(ttl.total_seconds() // 60)} min)"
    )
