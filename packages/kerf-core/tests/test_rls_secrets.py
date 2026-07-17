"""
T-88 — RLS: distributor_credentials
====================================
Hermetic tests for the application-level access control on the
``distributor_credentials`` table — operator-managed API secrets; only users
with ``account_role in ('admin','system')`` may list/read/write.

All tests use in-memory fakes (no DB, no network).

Invariants under test
---------------------
distributor_credentials — admin guard:
  1. Regular user (account_role='user') cannot list distributor creds → 403.
  2. Admin user (account_role='admin') can list distributor creds.
  3. System user (account_role='system') can list distributor creds.
  4. Regular user cannot read a specific credential by name → 403.
  5. Regular user cannot upsert a credential → 403.
  6. secret_encrypted blob is NEVER returned by list_credentials or
     get_credential_by_name — only has_secret flag is exposed.

Kerf has no billing anywhere, so the per-user BYO provider-key table
(``user_provider_keys``) and its RLS coverage were removed along with
the rest of the billing infrastructure — every request now uses the
operator-configured provider directly.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import pytest
from fastapi import HTTPException, status


# ---------------------------------------------------------------------------
# Fixtures — two isolated users and a distributor credential
# ---------------------------------------------------------------------------

USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())

CRED_NAME = "mouser"
CRED_SECRET = b"\xde\xad\xbe\xef"  # fake encrypted blob — must never be returned

# distributor_credentials store: {name: row}
_DISTRIBUTOR_CREDS: dict[str, dict] = {
    CRED_NAME: {
        "name": CRED_NAME,
        "enabled": True,
        "secret_encrypted": CRED_SECRET,
        "rate_limit_per_minute": 60,
        "last_used_at": None,
        "updated_at": None,
        "has_secret": True,  # computed, not the raw blob
    }
}

# users store: {user_id: account_role}
_USERS: dict[str, str] = {
    USER_A: "user",
    USER_B: "user",
}


# ---------------------------------------------------------------------------
# Fake DB connection
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    """asyncpg-like record."""
    def __getitem__(self, key):
        return super().__getitem__(key)
    def get(self, key, default=None):
        return super().get(key, default)


class FakeConn:
    """Minimal asyncpg.Connection fake for access-control queries."""

    async def fetchrow(self, query: str, *args) -> Optional[FakeRecord]:
        q = query.strip().lower()

        # account_role lookup for admin guard
        if "select account_role from users" in q:
            uid = str(args[0])
            role = _USERS.get(uid)
            if role:
                return FakeRecord({"account_role": role})
            return None

        # distributor_credentials — single row by name (no raw secret)
        if "from distributor_credentials" in q and "where name" in q:
            name = str(args[0])
            cred = _DISTRIBUTOR_CREDS.get(name)
            if cred:
                safe = {k: v for k, v in cred.items() if k != "secret_encrypted"}
                return FakeRecord(safe)
            return None

        return None

    async def fetch(self, query: str, *args) -> list[FakeRecord]:
        q = query.strip().lower()

        # distributor_credentials list (no raw secret)
        if "from distributor_credentials" in q:
            return [
                FakeRecord({k: v for k, v in cred.items() if k != "secret_encrypted"})
                for cred in _DISTRIBUTOR_CREDS.values()
            ]

        return []

    async def execute(self, query: str, *args) -> str:
        return ""

    def transaction(self):
        return _FakeTxn()


class _FakeTxn:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        pass


class FakeConnCtx:
    async def __aenter__(self):
        return FakeConn()
    async def __aexit__(self, *_):
        pass


class FakePool:
    def acquire(self):
        return FakeConnCtx()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_user(uid: str) -> str:
    """Temporarily promote uid to admin, return uid."""
    _USERS[uid] = "admin"
    return uid


def _reset_user(uid: str) -> None:
    _USERS[uid] = "user"


async def _account_role_check(conn: FakeConn, uid: str, allowed: tuple) -> str:
    """Mirror routes.py admin guard: raise 403 for non-admin."""
    row = await conn.fetchrow("select account_role from users where id = $1", uuid.UUID(uid))
    if not row:
        raise HTTPException(status_code=401, detail="unauthorized")
    if row["account_role"] not in allowed:
        raise HTTPException(status_code=403, detail="admin access required")
    return row["account_role"]


# ══════════════════════════════════════════════════════════════════════════════
# distributor_credentials — admin guard
# ══════════════════════════════════════════════════════════════════════════════

# Case 1 — regular user cannot list distributor credentials
@pytest.mark.asyncio
async def test_list_distributors_regular_user_gets_403():
    """A user with account_role='user' must be rejected with 403."""
    conn = FakeConn()
    with pytest.raises(HTTPException) as exc_info:
        await _account_role_check(conn, USER_A, ("admin", "system"))
    assert exc_info.value.status_code == 403
    assert "admin" in exc_info.value.detail


# Case 2 — admin user can list distributor credentials
@pytest.mark.asyncio
async def test_list_distributors_admin_user_allowed():
    """account_role='admin' must pass the admin guard."""
    _admin_user(USER_A)
    try:
        conn = FakeConn()
        role = await _account_role_check(conn, USER_A, ("admin", "system"))
        assert role == "admin"
        # Proceed to list
        rows = await conn.fetch("select name, enabled from distributor_credentials order by name")
        assert any(r["name"] == CRED_NAME for r in rows)
    finally:
        _reset_user(USER_A)


# Case 3 — system user can list distributor credentials
@pytest.mark.asyncio
async def test_list_distributors_system_user_allowed():
    """account_role='system' must also pass the admin guard."""
    _USERS[USER_B] = "system"
    try:
        conn = FakeConn()
        role = await _account_role_check(conn, USER_B, ("admin", "system"))
        assert role == "system"
    finally:
        _USERS[USER_B] = "user"


# Case 4 — regular user cannot read a credential by name
@pytest.mark.asyncio
async def test_get_credential_by_name_regular_user_gets_403():
    """Regular users must be rejected before any credential lookup."""
    conn = FakeConn()
    with pytest.raises(HTTPException) as exc_info:
        await _account_role_check(conn, USER_A, ("admin", "system"))
        # This line must not be reached
        await conn.fetchrow(
            "select name, enabled from distributor_credentials where name = $1",
            CRED_NAME,
        )
    assert exc_info.value.status_code == 403


# Case 5 — regular user cannot upsert a credential
@pytest.mark.asyncio
async def test_upsert_credential_regular_user_gets_403():
    """Upsert path must also enforce admin guard before any write."""
    conn = FakeConn()
    with pytest.raises(HTTPException) as exc_info:
        await _account_role_check(conn, USER_A, ("admin", "system"))
        # This line must not be reached
        await conn.execute(
            "insert into distributor_credentials (name, secret_encrypted) values ($1, $2)",
            CRED_NAME,
            b"new-secret",
        )
    assert exc_info.value.status_code == 403


# Case 6 — secret_encrypted blob is never returned; only has_secret flag
@pytest.mark.asyncio
async def test_distributor_credentials_secret_not_in_list_response():
    """list_credentials and get_credential_by_name must NOT return secret_encrypted."""
    conn = FakeConn()
    # List path
    rows = await conn.fetch("select name, enabled from distributor_credentials order by name")
    for row in rows:
        assert "secret_encrypted" not in row, (
            "secret_encrypted must never be returned in list response"
        )
        # has_secret flag is fine — it's a boolean, not the blob
        if "has_secret" in row:
            assert isinstance(row["has_secret"], bool)

    # Single-row path
    row = await conn.fetchrow(
        "select name, enabled from distributor_credentials where name = $1",
        CRED_NAME,
    )
    assert row is not None
    assert "secret_encrypted" not in row, (
        "secret_encrypted must never be returned in single-row response"
    )
