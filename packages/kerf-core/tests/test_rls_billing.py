"""
T-86 — RLS: usage_events + cloud_user_balances + billing_buckets
================================================================
Hermetic tests for multi-tenant access control on the three billing tables.

Access-control is enforced at the application layer via explicit WHERE
``user_id = $<caller>`` predicates in every query that reads or mutates
billing rows.  The tests verify that no code path can:
  - read usage_events belonging to a different user
  - read or mutate cloud_user_balances belonging to a different user
  - insert a usage_events row on behalf of another user
  - manipulate another user's credit balance

All 12 cases are hermetic: no real Postgres, no external I/O.
The fake pool/connection asserts which WHERE parameters are passed so
that cross-tenant leaks are caught at the query-construction level.

Invariants under test
---------------------
usage_events (SELECT):
  1. list_usage_events always binds caller's user_id — B's rows not returned.
  2. Handler /billing/usage scopes SELECT to caller's uid.
  3. Handler /billing/me._load_recent_usage scopes SELECT to caller's uid.
  4. Direct fetch without user_id filter (admin path) is not exposed via API.

usage_events (INSERT):
  5. commit_spend(KerfFree) inserts with caller's user_id — cannot forge B's.
  6. commit_spend(KerfPaid) inserts with caller's user_id — cannot forge B's.
  7. commit_spend(Byo) inserts with caller's user_id — cannot forge B's.

cloud_user_balances (SELECT):
  8. /billing/me scopes credit read to caller's uid.
  9. load_user_billing (bucket selector input) scopes to caller's uid.
 10. is_paid_user scopes to caller's uid.

cloud_user_balances (UPDATE/INSERT):
 11. commit_spend(KerfFree) quota-decrement is always WHERE user_id = caller.
 12. commit_spend(KerfPaid) balance-debit is always INSERT/ON CONFLICT for caller.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import pytest

from kerf_billing.buckets import (
    Byo,
    KerfFree,
    KerfPaid,
    ModelInfo,
    UserBilling,
    is_paid_user,
    load_user_billing,
    pick_bucket,
)
from kerf_billing.spend import commit_spend
from kerf_core.db.queries.usage_events import list_usage_events


# ---------------------------------------------------------------------------
# Fixtures — two isolated tenant UUIDs
# ---------------------------------------------------------------------------

USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())
PROJ_A = str(uuid.uuid4())
PROJ_B = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fake asyncpg-like records and connections
# ---------------------------------------------------------------------------

class _Record(dict):
    """Minimal asyncpg-Record-alike that supports dict-style access."""

    def __getitem__(self, key: str):
        return super().__getitem__(key)

    def get(self, key: str, default=None):
        return super().get(key, default)


class _RecordingConn:
    """Records every SQL call + args; returns configured per-call rows."""

    def __init__(self, fetchrow_seq=(), fetch_seq=()):
        self.executed: list[tuple[str, tuple]] = []
        self._fetchrow_seq = list(fetchrow_seq)
        self._fetch_seq = list(fetch_seq)

    async def execute(self, sql: str, *args) -> str:
        self.executed.append((sql, args))
        return "OK"

    async def fetchrow(self, sql: str, *args) -> Optional[_Record]:
        self.executed.append((sql, args))
        if self._fetchrow_seq:
            return self._fetchrow_seq.pop(0)
        return None

    async def fetch(self, sql: str, *args) -> list[_Record]:
        self.executed.append((sql, args))
        if self._fetch_seq:
            return self._fetch_seq.pop(0)
        return []

    def transaction(self):
        outer = self

        class _Tx:
            async def __aenter__(self_inner):
                return outer

            async def __aexit__(self_inner, *_):
                return False

        return _Tx()


class _RecordingPool:
    """Pool that yields a shared _RecordingConn."""

    def __init__(self, fetchrow_seq=(), fetch_seq=()):
        self.conn = _RecordingConn(fetchrow_seq, fetch_seq)

    def acquire(self):
        conn = self.conn

        class _Acq:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *_):
                return False

        return _Acq()

    # Pool-level helpers used by list_usage_events (asyncpg Pool.fetch)
    async def fetch(self, sql: str, *args) -> list[_Record]:
        return await self.conn.fetch(sql, *args)

    async def fetchrow(self, sql: str, *args) -> Optional[_Record]:
        return await self.conn.fetchrow(sql, *args)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_billing(
    user_id: str,
    credits: float = 5.0,
    free_in: int = 100_000,
    free_out: int = 20_000,
    prefer_byo: bool = False,
    byo: tuple = (),
) -> UserBilling:
    return UserBilling(
        user_id=user_id,
        prefer_byo=prefer_byo,
        credits_usd=credits,
        free_tokens_in_remaining=free_in,
        free_tokens_out_remaining=free_out,
        byo_providers=frozenset(byo),
    )


def _cheap_model(provider: str = "anthropic") -> ModelInfo:
    return ModelInfo(provider=provider, model_id="claude-haiku-3", cheap_tier_eligible=True)


def _first_user_id_arg(executed: list[tuple[str, tuple]]) -> Any:
    """Return the first argument of the first SQL call — must be the caller's uid."""
    assert executed, "no SQL calls recorded"
    _, args = executed[0]
    assert args, "SQL call had no arguments"
    return args[0]


# ============================================================================
# Case 1 — list_usage_events always binds caller uid; B's rows never returned
# ============================================================================

@pytest.mark.asyncio
async def test_list_usage_events_scoped_to_caller():
    """The SELECT user_id = $1 must be bound to USER_A — B's events excluded."""
    # Fake pool: returns one event for USER_A, none for USER_B
    event_a = _Record({
        "id": uuid.uuid4(), "user_id": uuid.UUID(USER_A),
        "kind": "token", "model": "claude-haiku-3",
        "input_tokens": 100, "output_tokens": 50,
        "bytes_delta": 0, "usd_cost": 0.001, "payer": "kerf_free",
        "project_id": None, "created_at": None,
    })
    pool = _RecordingPool(fetch_seq=[[event_a]])
    rows = await list_usage_events(pool.conn, user_id=uuid.UUID(USER_A))
    assert len(rows) == 1
    assert str(rows[0]["user_id"]) == USER_A

    # Confirm the WHERE clause bound USER_A, not USER_B
    _, args = pool.conn.executed[0]
    assert str(args[0]) == USER_A


# ============================================================================
# Case 2 — billing/usage route scopes SELECT to caller uid
# ============================================================================

@pytest.mark.asyncio
async def test_billing_usage_route_binds_caller_uid():
    """routes.py /billing/usage: first $1 bound to caller's uid."""
    from datetime import datetime
    from kerf_billing.billing.handlers import Handlers

    pool = _RecordingPool(fetch_seq=[[]])

    class _FakeFx:
        async def rate_with_spread(self, *args):
            return 18.0, None, True

    class _FakeCfg:
        cloud_fx_base_currency = "USD"
        cloud_fx_settlement_currency = "ZAR"
        cloud_fx_spread_pct = 0.2
        cloud_paystack_secret_key = None
        cloud_paystack_public_key = None
        cloud_paystack_webhook_secret = None
        cloud_beta = False

    h = Handlers(pool=pool, cfg=_FakeCfg(), fx_fetcher=_FakeFx(), paystack_client=None)

    from fastapi.testclient import TestClient  # noqa — only for starlette Request mock
    from starlette.datastructures import Headers
    from starlette.requests import Request as StarletteRequest

    # Build a minimal Starlette Request with the correct state
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/billing/usage",
        "query_string": b"",
        "headers": [],
    }
    req = StarletteRequest(scope)
    req.state.user_id = USER_A

    response = await h.usage(req)
    # Confirm the DB fetch was scoped to USER_A
    sql_calls = pool.conn.executed
    assert sql_calls, "no SQL emitted"
    usage_call = next((c for c in sql_calls if "usage_events" in c[0]), None)
    assert usage_call is not None, "no usage_events query found"
    _, args = usage_call
    assert str(args[0]) == USER_A, f"expected USER_A={USER_A!r}, got {args[0]!r}"


# ============================================================================
# Case 3 — /billing/me._load_recent_usage scopes to caller uid
# ============================================================================

@pytest.mark.asyncio
async def test_load_recent_usage_scoped_to_caller():
    """_load_recent_usage: WHERE user_id = $1 must be USER_A, not USER_B."""
    from kerf_billing.billing.handlers import Handlers

    pool = _RecordingPool(
        # me() calls: fetchrow(cloud_user_balances), fetch(invoices), fetch(usage)
        fetch_seq=[[], []],
        fetchrow_seq=[_Record({"credits_usd": 5.0})],
    )

    class _FakeCfg:
        cloud_paystack_secret_key = None
        cloud_paystack_public_key = None
        cloud_paystack_webhook_secret = None
        cloud_beta = False

    h = Handlers(pool=pool, cfg=_FakeCfg(), fx_fetcher=None, paystack_client=None)

    from starlette.requests import Request as StarletteRequest

    scope = {"type": "http", "method": "GET", "path": "/billing/me",
             "query_string": b"", "headers": []}
    req = StarletteRequest(scope)
    req.state.user_id = USER_A

    await h.me(req)

    # Find the usage_events fetch
    usage_call = next(
        (c for c in pool.conn.executed if "usage_events" in c[0]),
        None,
    )
    assert usage_call is not None
    _, args = usage_call
    assert str(args[0]) == USER_A


# ============================================================================
# Case 4 — list_usage_events without user_id filter has no API exposure
# ============================================================================

def test_no_unscoped_usage_events_route_exists():
    """No public API route exposes unfiltered usage_events (cross-tenant leak).

    Verified by confirming that every API-reachable read of usage_events in
    routes.py and handlers.py always includes WHERE user_id = $1 bound to the
    authenticated caller.  Static source inspection.
    """
    import inspect
    from kerf_billing import routes as billing_routes
    from kerf_billing.billing import handlers as billing_handlers

    for mod in (billing_routes, billing_handlers):
        src = inspect.getsource(mod)
        # Every usage_events SELECT in the source should be scoped
        # by a user_id predicate (WHERE user_id = $1).
        selects = [line for line in src.splitlines()
                   if "FROM usage_events" in line or "usage_events" in line]
        # The module contains usage_events references — if zero found the
        # module changed and this test needs updating.
        assert selects, f"{mod.__name__} no longer references usage_events"

    # Confirm WHERE user_id scoping in every SELECT block
    for mod in (billing_routes, billing_handlers):
        src = inspect.getsource(mod)
        # Look for any SELECT … FROM usage_events block without user_id filter
        # (simple heuristic: find each usage_events block and check its context)
        lines = src.splitlines()
        for i, line in enumerate(lines):
            if "FROM usage_events" in line:
                # Check a window of ±5 lines for user_id filter
                window = "\n".join(lines[max(0, i - 5):i + 6])
                assert "user_id" in window, (
                    f"{mod.__name__} line {i+1}: usage_events SELECT appears "
                    f"to lack a user_id WHERE clause:\n{window}"
                )


# ============================================================================
# Case 5 — commit_spend(KerfFree) inserts caller's user_id — cannot forge B
# ============================================================================

@pytest.mark.asyncio
async def test_commit_spend_free_inserts_caller_user_id():
    """KerfFree INSERT: first bound arg is USER_A's id, not USER_B."""
    pool = _RecordingPool()
    await commit_spend(
        pool, bucket=KerfFree(),
        user_id=USER_A, project_id=PROJ_A, model="claude-haiku-3",
        input_tokens=500, output_tokens=100,
        cogs_usd=0.001, billed_usd=0.001,
    )
    insert_call = next(c for c in pool.conn.executed if "INSERT INTO usage_events" in c[0])
    _, args = insert_call
    assert str(args[0]) == USER_A
    # Cannot forge USER_B's row — USER_B must not appear in any argument
    all_args_str = " ".join(str(a) for a in args)
    assert USER_B not in all_args_str


# ============================================================================
# Case 6 — commit_spend(KerfPaid) inserts caller's user_id — cannot forge B
# ============================================================================

@pytest.mark.asyncio
async def test_commit_spend_paid_inserts_caller_user_id():
    """KerfPaid INSERT: first bound arg is USER_A, balance debit scoped to USER_A."""
    pool = _RecordingPool()
    await commit_spend(
        pool, bucket=KerfPaid(),
        user_id=USER_A, project_id=None, model="claude-opus-4-7",
        input_tokens=200, output_tokens=80,
        cogs_usd=0.05, billed_usd=0.06,
    )
    insert_call = next(c for c in pool.conn.executed if "INSERT INTO usage_events" in c[0])
    _, args = insert_call
    assert str(args[0]) == USER_A
    # Balance debit also scoped to USER_A
    balance_call = next(
        c for c in pool.conn.executed if "cloud_user_balances" in c[0]
    )
    _, bargs = balance_call
    assert str(bargs[0]) == USER_A
    all_args_str = " ".join(str(a) for a in bargs)
    assert USER_B not in all_args_str


# ============================================================================
# Case 7 — commit_spend(Byo) inserts caller's user_id — cannot forge B
# ============================================================================

@pytest.mark.asyncio
async def test_commit_spend_byo_inserts_caller_user_id():
    """Byo INSERT: first bound arg must be USER_A, no USER_B leak."""
    pool = _RecordingPool()
    await commit_spend(
        pool, bucket=Byo("anthropic"),
        user_id=USER_A, project_id=PROJ_A, model="claude-sonnet-4-6",
        input_tokens=300, output_tokens=60,
        cogs_usd=0.01, billed_usd=0.0,
    )
    insert_call = next(c for c in pool.conn.executed if "INSERT INTO usage_events" in c[0])
    _, args = insert_call
    assert str(args[0]) == USER_A
    all_args_str = " ".join(str(a) for a in args)
    assert USER_B not in all_args_str


# ============================================================================
# Case 8 — /billing/me scopes credit read to caller uid
# ============================================================================

@pytest.mark.asyncio
async def test_billing_me_scopes_balance_read_to_caller():
    """cloud_user_balances SELECT must be WHERE user_id = USER_A."""
    from kerf_billing.billing.handlers import Handlers
    from starlette.requests import Request as StarletteRequest

    # fetchrow for balance, then two empty fetch() for invoices + usage
    pool = _RecordingPool(
        fetchrow_seq=[_Record({"credits_usd": 7.5})],
        fetch_seq=[[], []],
    )

    class _FakeCfg:
        cloud_paystack_secret_key = None
        cloud_paystack_public_key = None
        cloud_paystack_webhook_secret = None
        cloud_beta = False

    h = Handlers(pool=pool, cfg=_FakeCfg(), fx_fetcher=None, paystack_client=None)

    scope = {"type": "http", "method": "GET", "path": "/billing/me",
             "query_string": b"", "headers": []}
    req = StarletteRequest(scope)
    req.state.user_id = USER_A

    await h.me(req)

    balance_call = next(
        c for c in pool.conn.executed if "cloud_user_balances" in c[0]
    )
    _, args = balance_call
    assert str(args[0]) == USER_A, (
        f"cloud_user_balances read must be scoped to caller USER_A; got {args[0]!r}"
    )
    assert USER_B not in str(args[0])


# ============================================================================
# Case 9 — load_user_billing scopes every sub-query to caller uid
# ============================================================================

@pytest.mark.asyncio
async def test_load_user_billing_all_queries_scoped_to_caller():
    """load_user_billing: all three sub-queries must bind USER_A, not USER_B."""
    pool = _RecordingPool(
        fetchrow_seq=[
            _Record({"credits_usd": 3.0, "free_tokens_in_remaining": 90_000,
                     "free_tokens_out_remaining": 18_000}),
            _Record({"prefer_byo": False}),
        ],
        fetch_seq=[[
            _Record({"provider": "openai"}),
        ]],
    )

    ub = await load_user_billing(pool, USER_A)

    assert ub.user_id == USER_A
    # Verify each executed query used USER_A as the scoping argument
    for sql, args in pool.conn.executed:
        assert args, f"SQL call had no bound args: {sql!r}"
        assert str(args[0]) == USER_A, (
            f"Expected USER_A as first arg in: {sql!r}  got: {args[0]!r}"
        )


# ============================================================================
# Case 10 — is_paid_user scopes SELECT to caller uid
# ============================================================================

@pytest.mark.asyncio
async def test_is_paid_user_scoped_to_caller():
    """is_paid_user must look up USER_A's balance, not any other user's."""
    conn = _RecordingConn(fetchrow_seq=[_Record({"credits_usd": 5.0})])
    result = await is_paid_user(conn, USER_A)

    assert result is True  # credits_usd = 5.0 > 0
    _, args = conn.executed[0]
    assert str(args[0]) == USER_A
    assert USER_B not in str(args[0])


@pytest.mark.asyncio
async def test_is_paid_user_no_row_returns_false():
    """is_paid_user returns False when no balance row exists (new user)."""
    conn = _RecordingConn(fetchrow_seq=[None])
    result = await is_paid_user(conn, USER_A)
    assert result is False


# ============================================================================
# Case 11 — commit_spend(KerfFree) quota-decrement WHERE user_id = caller
# ============================================================================

@pytest.mark.asyncio
async def test_commit_spend_free_quota_decrement_scoped_to_caller():
    """free_tokens quota UPDATE must have WHERE user_id = USER_A — not USER_B."""
    pool = _RecordingPool()
    await commit_spend(
        pool, bucket=KerfFree(),
        user_id=USER_A, project_id=None, model="claude-haiku-3",
        input_tokens=1_000, output_tokens=200,
        cogs_usd=0.002, billed_usd=0.002,
    )
    quota_call = next(
        c for c in pool.conn.executed if "free_tokens" in c[0]
    )
    sql, args = quota_call
    assert "WHERE user_id = $1" in sql, "quota UPDATE must scope with WHERE user_id = $1"
    assert str(args[0]) == USER_A
    assert USER_B not in " ".join(str(a) for a in args)


# ============================================================================
# Case 12 — commit_spend(KerfPaid) balance-debit scoped to caller uid
# ============================================================================

@pytest.mark.asyncio
async def test_commit_spend_paid_balance_debit_scoped_to_caller():
    """cloud_user_balances INSERT/ON CONFLICT must bind USER_A as first arg."""
    pool = _RecordingPool()
    await commit_spend(
        pool, bucket=KerfPaid(),
        user_id=USER_A, project_id=PROJ_A, model="claude-opus-4-7",
        input_tokens=100, output_tokens=50,
        cogs_usd=0.01, billed_usd=0.012,
    )
    balance_call = next(
        c for c in pool.conn.executed if "cloud_user_balances" in c[0]
    )
    sql, args = balance_call
    # Must be an upsert on (user_id, credits_usd) — not a full-table mutation
    assert "ON CONFLICT" in sql or "INSERT INTO cloud_user_balances" in sql, (
        "Expected INSERT … ON CONFLICT upsert for balance debit"
    )
    assert str(args[0]) == USER_A, (
        f"Balance debit must be for USER_A; got {args[0]!r}"
    )
    assert USER_B not in " ".join(str(a) for a in args)
