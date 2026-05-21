"""T-79 — Workspace invite hijack: token is random, bound to invitee email, single-use.

10 hermetic cases (no DB required — asyncpg mocked):

  C01  valid invite → 200 + workspace returned (happy path)
  C02  unknown token → 404 (invite not found)
  C03  blank token → 400 (guard: not req.token)
  C04  email mismatch → 403 (invite is not for your account)
  C05  invite consumed (DELETE executed) — single-use enforced
  C06  non-member (role=member) cannot invite (POST /workspaces/{slug}/members) → 403
  C07  non-admin cannot invite (viewer/editor) → 403
  C08  unauthenticated accept → 401 (no bearer token)
  C09  role escalation via tampered invite is impossible — role comes from DB row
  C10  invite cannot escape workspace boundary (accepts into the invite's workspace_id)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import kerf_api.routes as api_routes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WS_ID = str(uuid.uuid4())
_INVITE_ID = str(uuid.uuid4())
_USER_ID = str(uuid.uuid4())
_USER_EMAIL = "invitee@example.com"
_INVITE_TOKEN = "secure-random-token-abc123"


def _app():
    app = FastAPI()
    app.include_router(api_routes.router, prefix="/api")
    return app


def _fake_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _conn_with_tx():
    """asyncpg connection mock whose .transaction() ctx-manager works."""
    conn = AsyncMock()
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    return conn


def _valid_invite_row(email: str = _USER_EMAIL, role: str = "member") -> dict:
    return {
        "id": uuid.UUID(_INVITE_ID),
        "workspace_id": uuid.UUID(_WS_ID),
        "email": email,
        "role": role,
    }


def _user_email_row(email: str = _USER_EMAIL) -> dict:
    return {"email": email}


def _ws_row() -> dict:
    return {
        "id": uuid.UUID(_WS_ID),
        "slug": "test-workspace",
        "name": "Test Workspace",
        "avatar_url": None,
        "created_at": datetime.now(timezone.utc),
        "my_role": None,
        "member_count": None,
        "project_count": None,
    }


def _auth_header(user_id: str = _USER_ID) -> dict:
    """Mint a JWT for the given user_id via the app's auth helper."""
    from kerf_auth.routes import generate_access_token
    token, _ = generate_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# C01  Valid token + matching email → 200 workspace response
# ---------------------------------------------------------------------------

def test_c01_valid_invite_returns_200():
    conn = _conn_with_tx()
    # fetchrow calls: (1) invite row, (2) user email row
    conn.fetchrow = AsyncMock(side_effect=[
        _valid_invite_row(),
        _user_email_row(),
    ])
    conn.execute = AsyncMock()

    ws = _ws_row()
    with patch.object(api_routes, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(api_routes.workspaces_queries, "add_workspace_member", AsyncMock(return_value={})), \
         patch.object(api_routes.workspaces_queries, "get_workspace", AsyncMock(return_value=ws)):
        client = TestClient(_app())
        r = client.post(
            "/api/workspaces/accept",
            json={"token": _INVITE_TOKEN},
            headers=_auth_header(),
        )

    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "test-workspace"


# ---------------------------------------------------------------------------
# C02  Unknown token (fetchrow returns None) → 404
# ---------------------------------------------------------------------------

def test_c02_unknown_token_returns_404():
    conn = _conn_with_tx()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock()

    with patch.object(api_routes, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))):
        client = TestClient(_app())
        r = client.post(
            "/api/workspaces/accept",
            json={"token": "no-such-token"},
            headers=_auth_header(),
        )

    assert r.status_code == 404
    assert "invite" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# C03  Blank token → 400 (route-level guard)
# ---------------------------------------------------------------------------

def test_c03_blank_token_returns_400():
    with patch.object(api_routes, "get_pool_required", AsyncMock()):
        client = TestClient(_app())
        r = client.post(
            "/api/workspaces/accept",
            json={"token": ""},
            headers=_auth_header(),
        )

    assert r.status_code == 400


# ---------------------------------------------------------------------------
# C04  Email mismatch → 403 (invite is not for your account)
# ---------------------------------------------------------------------------

def test_c04_email_mismatch_returns_403():
    conn = _conn_with_tx()
    # Invite is for someone@else.com but the authenticated user has a different email
    conn.fetchrow = AsyncMock(side_effect=[
        _valid_invite_row(email="someone@else.com"),  # invite row
        _user_email_row(email="attacker@evil.com"),   # authenticated user's email
    ])
    conn.execute = AsyncMock()

    with patch.object(api_routes, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))):
        client = TestClient(_app())
        r = client.post(
            "/api/workspaces/accept",
            json={"token": _INVITE_TOKEN},
            headers=_auth_header(),
        )

    assert r.status_code == 403
    assert "not for your account" in r.json()["detail"]


# ---------------------------------------------------------------------------
# C05  Single-use: DELETE is executed on successful accept
# ---------------------------------------------------------------------------

def test_c05_invite_is_deleted_on_accept():
    """After a successful accept the invite row must be deleted (single-use)."""
    conn = _conn_with_tx()
    invite_row = _valid_invite_row()
    conn.fetchrow = AsyncMock(side_effect=[invite_row, _user_email_row()])
    conn.execute = AsyncMock()

    ws = _ws_row()
    with patch.object(api_routes, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(api_routes.workspaces_queries, "add_workspace_member", AsyncMock(return_value={})), \
         patch.object(api_routes.workspaces_queries, "get_workspace", AsyncMock(return_value=ws)):
        client = TestClient(_app())
        r = client.post(
            "/api/workspaces/accept",
            json={"token": _INVITE_TOKEN},
            headers=_auth_header(),
        )

    assert r.status_code == 200
    # Verify DELETE was issued for the invite row
    delete_calls = [
        c for c in conn.execute.await_args_list
        if "DELETE FROM workspace_invites" in str(c.args[0])
    ]
    assert delete_calls, "Single-use violated: DELETE FROM workspace_invites was never called"
    # Ensure the right invite id was deleted
    assert str(invite_row["id"]) in str(delete_calls[0].args), (
        f"DELETE targeted wrong id: {delete_calls[0].args}"
    )


# ---------------------------------------------------------------------------
# C06  Non-member (role=member) cannot send invites via POST /members → 403
# ---------------------------------------------------------------------------

def test_c06_member_cannot_invite_others():
    """Only owner/admin can POST /api/workspaces/{slug}/members."""
    conn = _conn_with_tx()
    ws = {
        "id": uuid.UUID(_WS_ID),
        "slug": "test-ws",
        "name": "Test WS",
    }

    with patch.object(api_routes, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(api_routes.workspaces_queries, "get_workspace_by_slug", AsyncMock(return_value=ws)), \
         patch.object(api_routes, "get_user_workspace_role", AsyncMock(return_value="member")):
        client = TestClient(_app())
        r = client.post(
            "/api/workspaces/test-ws/members",
            json={"email": "new@example.com", "role": "member"},
            headers=_auth_header(),
        )

    assert r.status_code == 403


# ---------------------------------------------------------------------------
# C07  Viewer (no workspace role) cannot invite → 403
# ---------------------------------------------------------------------------

def test_c07_non_member_cannot_invite():
    """A user with no workspace membership cannot send invites."""
    conn = _conn_with_tx()
    ws = {
        "id": uuid.UUID(_WS_ID),
        "slug": "test-ws",
        "name": "Test WS",
    }

    with patch.object(api_routes, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(api_routes.workspaces_queries, "get_workspace_by_slug", AsyncMock(return_value=ws)), \
         patch.object(api_routes, "get_user_workspace_role", AsyncMock(return_value=None)):
        client = TestClient(_app())
        r = client.post(
            "/api/workspaces/test-ws/members",
            json={"email": "hijack@example.com", "role": "owner"},
            headers=_auth_header(),
        )

    assert r.status_code == 403


# ---------------------------------------------------------------------------
# C08  Unauthenticated accept → 401
# ---------------------------------------------------------------------------

def test_c08_unauthenticated_accept_returns_401():
    """POST /api/workspaces/accept without bearer token must be 401."""
    with patch.object(api_routes, "get_pool_required", AsyncMock()):
        client = TestClient(_app())
        r = client.post(
            "/api/workspaces/accept",
            json={"token": _INVITE_TOKEN},
            # no Authorization header
        )

    assert r.status_code == 401


# ---------------------------------------------------------------------------
# C09  Role escalation impossible — role comes from DB row, not request body
# ---------------------------------------------------------------------------

def test_c09_role_comes_from_db_not_request():
    """The assigned role is the one stored in the invite row (member).
    The request body carries no role field; any injected role attempt has no effect.
    """
    conn = _conn_with_tx()
    # DB has role=member
    conn.fetchrow = AsyncMock(side_effect=[
        _valid_invite_row(role="member"),
        _user_email_row(),
    ])
    conn.execute = AsyncMock()

    add_member_mock = AsyncMock(return_value={})
    ws = _ws_row()
    with patch.object(api_routes, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(api_routes.workspaces_queries, "add_workspace_member", add_member_mock), \
         patch.object(api_routes.workspaces_queries, "get_workspace", AsyncMock(return_value=ws)):
        client = TestClient(_app())
        r = client.post(
            "/api/workspaces/accept",
            # No role field — client cannot inject role
            json={"token": _INVITE_TOKEN},
            headers=_auth_header(),
        )

    assert r.status_code == 200
    # Verify add_workspace_member was called with role=member (from DB row)
    call_args = add_member_mock.await_args
    assert call_args is not None, "add_workspace_member was never called"
    # role is the 3rd positional arg (after conn, workspace_id, user_id)
    assigned_role = call_args.args[3]
    assert assigned_role == "member", (
        f"Role escalation: expected 'member' (from DB), got '{assigned_role}'"
    )


# ---------------------------------------------------------------------------
# C10  Invite cannot escape workspace boundary — add_member targets invite's workspace
# ---------------------------------------------------------------------------

def test_c10_invite_cannot_escape_workspace_boundary():
    """The add_workspace_member call must use the workspace_id from the invite row,
    not any value that could be supplied by the client."""
    conn = _conn_with_tx()
    ws_id_from_invite = uuid.UUID(_WS_ID)
    conn.fetchrow = AsyncMock(side_effect=[
        _valid_invite_row(),  # workspace_id = _WS_ID
        _user_email_row(),
    ])
    conn.execute = AsyncMock()

    add_member_mock = AsyncMock(return_value={})
    ws = _ws_row()
    with patch.object(api_routes, "get_pool_required", AsyncMock(return_value=_fake_pool(conn))), \
         patch.object(api_routes.workspaces_queries, "add_workspace_member", add_member_mock), \
         patch.object(api_routes.workspaces_queries, "get_workspace", AsyncMock(return_value=ws)):
        client = TestClient(_app())
        r = client.post(
            "/api/workspaces/accept",
            json={"token": _INVITE_TOKEN},
            headers=_auth_header(),
        )

    assert r.status_code == 200
    call_args = add_member_mock.await_args
    assert call_args is not None, "add_workspace_member was never called"
    # workspace_id is the 1st positional arg after conn
    used_ws_id = call_args.args[1]
    assert used_ws_id == ws_id_from_invite, (
        f"Workspace boundary escape: expected {ws_id_from_invite}, got {used_ws_id}"
    )
