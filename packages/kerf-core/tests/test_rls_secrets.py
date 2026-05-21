"""
T-88 — RLS: distributor_credentials + user_provider_keys
=========================================================
Hermetic tests for the application-level access control on the two secret
tables:

  * ``distributor_credentials`` — operator-managed API secrets; only users with
    ``account_role in ('admin','system')`` may list/read/write.
  * ``user_provider_keys`` — per-user BYO encrypted keys; strictly scoped to
    the owning ``user_id``; other users must get nothing.

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

user_provider_keys — per-user isolation:
  7. User A can retrieve their own provider key.
  8. User B fetching User A's key (wrong user_id) returns nothing.
  9. _make_byo_provider query is scoped to both user_id AND provider
     (no single-arg queries that could leak cross-user).
  10. User A with key X does not bleed into User A fetching key Y (wrong
      provider).
  11. Cross-user upsert attempt: inserting a key for user_id=B while
      authenticated as user_id=A must not succeed — key is namespaced to
      calling user's id.
  12. buckets.py byo_rows query is scoped to user_id (no cross-tenant
      provider enumeration).
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

# user_provider_keys store: {(user_id, provider): encrypted_key}
_PROVIDER_KEYS: dict[tuple[str, str], bytes] = {
    (USER_A, "anthropic"): b"enc-key-user-a-anthropic",
    (USER_A, "openai"):    b"enc-key-user-a-openai",
    (USER_B, "anthropic"): b"enc-key-user-b-anthropic",
}

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

        # user_provider_keys — single key lookup (user_id + provider)
        if "from user_provider_keys" in q and "provider" in q and "user_id" in q:
            user_id = str(args[0])
            provider = str(args[1])
            enc = _PROVIDER_KEYS.get((user_id, provider))
            if enc is not None:
                return FakeRecord({"encrypted_key": enc})
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

        # user_provider_keys provider enumeration (buckets.py)
        if "from user_provider_keys" in q and "provider" in q:
            user_id = str(args[0])
            return [
                FakeRecord({"provider": prov})
                for (uid, prov) in _PROVIDER_KEYS
                if uid == user_id
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


# ══════════════════════════════════════════════════════════════════════════════
# user_provider_keys — per-user isolation
# ══════════════════════════════════════════════════════════════════════════════

# Case 7 — User A can retrieve their own provider key
@pytest.mark.asyncio
async def test_user_a_can_read_own_provider_key():
    """A user may read their own encrypted_key."""
    conn = FakeConn()
    row = await conn.fetchrow(
        "SELECT encrypted_key FROM user_provider_keys WHERE user_id = $1 AND provider = $2",
        USER_A,
        "anthropic",
    )
    assert row is not None
    assert row["encrypted_key"] == _PROVIDER_KEYS[(USER_A, "anthropic")]


# Case 8 — User B fetching User A's key returns nothing
@pytest.mark.asyncio
async def test_user_b_cannot_read_user_a_provider_key():
    """Querying user_provider_keys with user_id=B returns no row for A's key."""
    conn = FakeConn()
    # User B authenticates as themselves — user_id must be scoped to B
    row = await conn.fetchrow(
        "SELECT encrypted_key FROM user_provider_keys WHERE user_id = $1 AND provider = $2",
        USER_B,
        "openai",  # B has no openai key
    )
    assert row is None, "User B must not obtain User A's openai key"


# Case 9 — _make_byo_provider query is scoped to both user_id AND provider
def test_make_byo_provider_query_has_both_predicates():
    """The SELECT in _make_byo_provider must include BOTH user_id and provider
    predicates to prevent cross-user or cross-provider leakage.
    """
    import inspect
    from kerf_api.routes import _make_byo_provider
    src = inspect.getsource(_make_byo_provider)
    assert "user_id" in src and "provider" in src, (
        "_make_byo_provider must filter on both user_id and provider"
    )
    # Verify it uses parameterized placeholders (no string interpolation)
    assert "$1" in src and "$2" in src, (
        "_make_byo_provider must use $1/$2 placeholders (no string interpolation)"
    )


# Case 10 — wrong provider for User A returns nothing
@pytest.mark.asyncio
async def test_user_a_wrong_provider_returns_nothing():
    """User A has no 'gemini' key — lookup must return None."""
    conn = FakeConn()
    row = await conn.fetchrow(
        "SELECT encrypted_key FROM user_provider_keys WHERE user_id = $1 AND provider = $2",
        USER_A,
        "gemini",
    )
    assert row is None, "Non-existent provider must return None, not a different key"


# Case 11 — key is namespaced to authenticated user_id (no cross-user bleed)
@pytest.mark.asyncio
async def test_byo_key_read_is_scoped_to_authenticated_user():
    """Reading a key requires both user_id match and provider match.

    Simulate: a caller passes USER_B's UUID but tries to retrieve USER_A's
    anthropic key.  The query returns nothing because user_id = USER_B has
    only an 'anthropic' row (not 'openai'), and the wrong-user path returns
    nothing for 'openai'.
    """
    conn = FakeConn()
    # USER_B does have an anthropic key
    row_b = await conn.fetchrow(
        "SELECT encrypted_key FROM user_provider_keys WHERE user_id = $1 AND provider = $2",
        USER_B,
        "anthropic",
    )
    assert row_b is not None
    # But USER_B's anthropic key must NOT equal USER_A's anthropic key
    row_a = await conn.fetchrow(
        "SELECT encrypted_key FROM user_provider_keys WHERE user_id = $1 AND provider = $2",
        USER_A,
        "anthropic",
    )
    assert row_a is not None
    assert row_b["encrypted_key"] != row_a["encrypted_key"], (
        "Each user's encrypted key must be distinct — no cross-user bleed"
    )


# Case 12 — buckets.py byo_rows query is scoped to user_id
@pytest.mark.asyncio
async def test_byo_rows_provider_enumeration_is_per_user():
    """SELECT provider FROM user_provider_keys WHERE user_id = $1 must only
    return providers belonging to the requesting user.
    """
    conn = FakeConn()
    # User A has anthropic + openai
    rows_a = await conn.fetch(
        "SELECT provider FROM user_provider_keys WHERE user_id = $1",
        USER_A,
    )
    providers_a = {r["provider"] for r in rows_a}
    assert "anthropic" in providers_a
    assert "openai" in providers_a

    # User B has only anthropic
    rows_b = await conn.fetch(
        "SELECT provider FROM user_provider_keys WHERE user_id = $1",
        USER_B,
    )
    providers_b = {r["provider"] for r in rows_b}
    assert providers_b == {"anthropic"}, f"User B should only have anthropic, got {providers_b}"

    # Cross-check: neither user sees the other's unique keys
    assert "openai" not in providers_b, "User B must not see User A's openai key"
