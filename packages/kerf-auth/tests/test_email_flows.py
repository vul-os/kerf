"""Slice 8 (revised): no transactional email; local-account recovery.

Kerf sends no email anywhere (decisions.md 2026-07-17 "accounts shrink to
the box"). ``_send_email`` and the email-token verification flow it fed
(``/verify-email``, ``/request-verification``) are gone. This pins the
replacement contract:

- register() never touches email; new accounts are auto-verified since
  there is no inbox to click a link from.
- /verify-email and /request-verification no longer exist (404).
- /forgot-password always 501s with a message pointing at
  `kerf admin reset-password` — same response regardless of whether the
  email is registered (no enumeration surface, because there's nothing to
  differentiate on any more).
- /reset-password itself (token consumption) is unchanged — see
  test_pen_password_reset.py — except it no longer sends a confirmation
  email on success.
- admin_generate_password_reset_link() is the local-account-recovery
  primitive `kerf admin reset-password <email>` (kerf-cli) calls: same
  single-use/expiring token machinery, delivered out of band instead of
  by email.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import kerf_auth.routes as auth


@pytest.fixture(autouse=True)
def _stub_rate_limit(monkeypatch):
    """Prevent rate_limit from hitting the DB pool in all tests here.

    The /forgot-password route now has a rate_limit dependency (R17).
    Stub enforce so tests remain hermetic.
    """
    import kerf_core.rate_limit as _rl_module
    monkeypatch.setattr(_rl_module, "enforce", AsyncMock(return_value=None))
    import kerf_core.db.connection as _conn_module
    monkeypatch.setattr(_conn_module, "get_pool_required", AsyncMock(return_value=MagicMock()))


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


def _conn():
    conn = AsyncMock()
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    return conn


# ---- _send_email is gone -------------------------------------------------

def test_send_email_no_longer_exists():
    """The lazily-importing kerf_cloud.email shim is fully removed, not a
    soft-failing stub."""
    assert not hasattr(auth, "_send_email")


# ---- register(): no email calls, auto-verified ---------------------------

def test_register_auto_verifies_no_email_calls():
    """New accounts are marked email_verified immediately — there is no
    verification email to wait on."""
    conn = _conn()
    created_user = {
        "id": "u-new-1",
        "email": "new@example.com",
        "name": "",
        "avatar_url": "",
        "account_role": "user",
        "is_system": False,
        "email_verified": False,
        "created_at": datetime.now(timezone.utc),
    }
    conn.fetchrow = AsyncMock(return_value=created_user)
    conn.execute = AsyncMock()

    with patch.object(auth, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(auth.users_queries, "create_user", AsyncMock(return_value=created_user)), \
         patch.object(auth, "create_personal_workspace", AsyncMock(return_value=None)), \
         patch.object(auth, "issue_tokens", AsyncMock(return_value=("at", "rt"))), \
         patch.object(auth, "get_default_workspace", AsyncMock(return_value=(None, False))):
        c = TestClient(_app())
        r = c.post("/auth/register", json={"email": "new@example.com", "password": "longenough1"})

    assert r.status_code == 201
    assert r.json()["user"]["email_verified"] is True
    # The account is verified via a direct UPDATE, never an emailed token.
    sqls = " ".join(str(call.args[0]) for call in conn.execute.await_args_list)
    assert "UPDATE users SET email_verified = true" in sqls
    assert "email_tokens" not in sqls


def test_register_source_has_no_send_email_call():
    """Source contract: register() no longer references _send_email or a
    verify-kind email token."""
    import pathlib
    src = pathlib.Path(auth.__file__).read_text()
    i = src.index("async def register(")
    body = src[i:i + 3000]
    assert "_send_email(" not in body
    assert '"verify"' not in body


# ---- /verify-email and /request-verification are gone --------------------

def test_verify_email_route_removed():
    c = TestClient(_app())
    r = c.get("/auth/verify-email?token=whatever")
    assert r.status_code == 404


def test_request_verification_route_removed():
    c = TestClient(_app())
    r = c.post("/auth/request-verification")
    assert r.status_code == 404


# ---- /forgot-password : always 501, no enumeration ------------------------

def test_forgot_password_unknown_email_returns_501():
    c = TestClient(_app())
    r = c.post("/auth/forgot-password", json={"email": "nobody@x.com"})
    assert r.status_code == 501
    assert "kerf admin reset-password" in r.json()["detail"]


def test_forgot_password_known_email_returns_identical_501():
    """Same 501 regardless of whether the email is registered — the route
    does no DB lookup at all any more, so there is nothing to enumerate."""
    c = TestClient(_app())
    r_unknown = c.post("/auth/forgot-password", json={"email": "nobody@x.com"})
    r_known = c.post("/auth/forgot-password", json={"email": "pat@x.com"})
    assert r_unknown.status_code == r_known.status_code == 501
    assert r_unknown.json() == r_known.json()


# ---- admin_generate_password_reset_link(): local recovery primitive ------

def test_admin_reset_link_none_for_unknown_email():
    conn = _conn()

    import asyncio

    async def _call():
        with patch.object(auth.users_queries, "get_user_by_email", AsyncMock(return_value=None)):
            return await auth.admin_generate_password_reset_link(conn, "nobody@x.com")

    result = asyncio.run(_call())
    assert result is None


def test_admin_reset_link_none_for_oauth_only_account():
    conn = _conn()
    user = {"id": "u-oauth-1", "password_hash": None}

    import asyncio

    async def _call():
        with patch.object(auth.users_queries, "get_user_by_email", AsyncMock(return_value=user)):
            return await auth.admin_generate_password_reset_link(conn, "oauth@x.com")

    result = asyncio.run(_call())
    assert result is None


def test_admin_reset_link_returns_url_for_password_account():
    conn = _conn()
    user = {"id": "u-pw-1", "password_hash": "bcrypt$x"}

    import asyncio

    async def _call():
        with patch.object(auth.users_queries, "get_user_by_email", AsyncMock(return_value=user)), \
             patch.object(auth, "_create_email_token", AsyncMock(return_value="tok-abc")), \
             patch.object(auth, "_app_url", return_value="https://app.test"):
            return await auth.admin_generate_password_reset_link(conn, "pat@x.com")

    link = asyncio.run(_call())
    assert link == "https://app.test/reset-password?token=tok-abc"


# ---- /reset-password : input validation still holds -----------------------

def test_reset_password_short_password_400():
    c = TestClient(_app())
    r = c.post("/auth/reset-password", json={"token": "t", "password": "short"})
    assert r.status_code == 400


def test_reset_password_invalid_token_400():
    conn = _conn()
    conn.fetchrow = AsyncMock(return_value=None)
    with patch.object(auth, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))):
        c = TestClient(_app())
        r = c.post("/auth/reset-password",
                   json={"token": "bad", "password": "longenough1"})
    assert r.status_code == 400
