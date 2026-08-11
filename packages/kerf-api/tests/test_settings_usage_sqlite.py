"""The Settings read surface — saved provider keys and usage — on SQLite.

These two routes are what make Kerf's settings usable without editing a config
file: one says which LLM providers this user has a key for, the other reports
what those keys have been spending. Both are new; neither had any coverage,
and ``usage_events`` in particular had been written at six call sites for a
long time with nothing ever reading it back.

The sweep in ``test_route_sweep_sqlite.py`` already asserts these routes don't
5xx, but it runs against empty tables, so every aggregate there is trivially
zero. This seeds real rows and checks the arithmetic — including the day
bucketing, which is the one piece of SQL here that is not identical on both
backends.

Hermetic: SQLite is stdlib, so this runs in the default tier.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = pathlib.Path(__file__).parent
_PACKAGES_ROOT = _HERE.parent.parent
for _entry in _PACKAGES_ROOT.iterdir():
    if not _entry.name.startswith("kerf-"):
        continue
    _src = _entry / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

_JWT_SECRET = "dev-secret-change-in-production"
_DB_PATH = pathlib.Path(tempfile.mkdtemp(prefix="kerf-settings-")) / "settings.db"
_DB_URL = f"sqlite://{_DB_PATH}"

# Long enough that _mask_api_key shows a tail rather than collapsing to "••••".
_REAL_KEY = "sk-ant-test-0000000000000000a91f"

_IDS: dict[str, str] = {}


async def _migrate_and_seed() -> dict[str, str]:
    from kerf_core.db.migrations.runner import run_sqlite_migrations
    from kerf_core.db.sqlite_backend import create_sqlite_pool
    from kerf_core.utils.encrypt import encrypt_secret

    await run_sqlite_migrations(_DB_URL)
    pool = await create_sqlite_pool(_DB_URL, max_size=2)
    try:
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "INSERT INTO users (email, name, account_role, is_system) "
                "VALUES ($1, 'Settings', 'user', false) RETURNING *",
                f"settings-{uuid.uuid4().hex[:8]}@test.invalid",
            )
            other = await conn.fetchrow(
                "INSERT INTO users (email, name, account_role, is_system) "
                "VALUES ($1, 'Other', 'user', false) RETURNING *",
                f"other-{uuid.uuid4().hex[:8]}@test.invalid",
            )
            ws = await conn.fetchrow(
                "INSERT INTO workspaces (slug, name, created_by) VALUES ($1, 'WS', $2) RETURNING *",
                f"settings-{uuid.uuid4().hex[:8]}", user["id"],
            )
            proj = await conn.fetchrow(
                "INSERT INTO projects (workspace_id, name, description, visibility, tags) "
                "VALUES ($1, 'P', '', 'private', '[]') RETURNING *",
                ws["id"],
            )
            other_proj = await conn.fetchrow(
                "INSERT INTO projects (workspace_id, name, description, visibility, tags) "
                "VALUES ($1, 'P2', '', 'private', '[]') RETURNING *",
                ws["id"],
            )

            # One decryptable key with a gateway base_url, one whose ciphertext
            # is garbage — the second stands in for a key saved under a server
            # secret that has since been rotated.
            await conn.execute(
                "INSERT INTO user_provider_keys (user_id, provider, encrypted_key, base_url) "
                "VALUES ($1, 'anthropic', $2, $3)",
                user["id"],
                encrypt_secret(_REAL_KEY.encode(), "byo-provider-key"),
                "https://gateway.internal/v1",
            )
            await conn.execute(
                "INSERT INTO user_provider_keys (user_id, provider, encrypted_key) "
                "VALUES ($1, 'openai', $2)",
                user["id"], b"not-a-valid-ciphertext",
            )
            # Another user's key must never appear in our listing.
            await conn.execute(
                "INSERT INTO user_provider_keys (user_id, provider, encrypted_key) "
                "VALUES ($1, 'gemini', $2)",
                other["id"], encrypt_secret(b"someone-elses-key", "byo-provider-key"),
            )

            now = datetime.now(timezone.utc)
            rows = [
                # (kind, model, in, out, bytes, usd, project, created_at)
                ("token", "claude-opus-4-7", 1000, 200, 0, 0.05, proj["id"], now),
                ("token", "claude-opus-4-7", 500, 100, 0, 0.02, proj["id"], now),
                ("token", "gpt-4o", 300, 50, 0, 0.01, other_proj["id"], now - timedelta(days=1)),
                ("storage", None, 0, 0, 4096, 0.0, proj["id"], now - timedelta(days=1)),
                # Outside a 7-day window; inside the 30-day default.
                ("token", "gpt-4o", 900, 90, 0, 0.09, proj["id"], now - timedelta(days=10)),
            ]
            for kind, model, tin, tout, bd, usd, pid, ts in rows:
                await conn.execute(
                    "INSERT INTO usage_events "
                    "(user_id, project_id, kind, model, input_tokens, output_tokens, "
                    " bytes_delta, usd_cost, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                    user["id"], pid, kind, model, tin, tout, bd, usd, ts,
                )
            # Another user's spend must not land in our totals.
            await conn.execute(
                "INSERT INTO usage_events "
                "(user_id, project_id, kind, model, input_tokens, output_tokens, usd_cost) "
                "VALUES ($1, $2, 'token', 'gpt-4o', 99999, 99999, 99.99)",
                other["id"], proj["id"],
            )
        return {
            "user_id": str(user["id"]),
            "project_id": str(proj["id"]),
            "other_project_id": str(other_proj["id"]),
        }
    finally:
        await pool.close()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import kerf_core.db.connection as _conn
    from kerf_core.db.sqlite_backend import create_sqlite_pool

    pool = await create_sqlite_pool(_DB_URL, max_size=4)
    _conn._pool = pool
    yield
    _conn._pool = None
    await pool.close()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    global _IDS
    _IDS = asyncio.run(_migrate_and_seed())

    from kerf_api.routes import router as api_router

    app = FastAPI(lifespan=_lifespan)
    app.include_router(api_router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _headers() -> dict[str, str]:
    now = datetime.now(tz=timezone.utc)
    token = jwt.encode(
        {"sub": _IDS["user_id"], "exp": now + timedelta(hours=1), "iat": now},
        _JWT_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


# ── provider keys ────────────────────────────────────────────────────────────

def test_provider_keys_are_masked_and_never_returned_in_full(client: TestClient):
    body = client.get("/api/provider-keys", headers=_headers()).json()
    anthropic = next(k for k in body["keys"] if k["provider"] == "anthropic")

    assert anthropic["masked_key"] == "••••a91f"
    assert anthropic["readable"] is True
    assert anthropic["base_url"] == "https://gateway.internal/v1"
    # The whole point: the plaintext must not appear anywhere in the response.
    assert _REAL_KEY not in client.get("/api/provider-keys", headers=_headers()).text


def test_undecryptable_key_is_reported_not_hidden(client: TestClient):
    """A rotated jwt_secret orphans saved keys — say so instead of 500ing."""
    body = client.get("/api/provider-keys", headers=_headers()).json()
    openai = next(k for k in body["keys"] if k["provider"] == "openai")

    assert openai["readable"] is False
    assert openai["masked_key"] == ""


def test_provider_keys_are_scoped_to_the_caller(client: TestClient):
    body = client.get("/api/provider-keys", headers=_headers()).json()
    assert {k["provider"] for k in body["keys"]} == {"anthropic", "openai"}


# ── usage ────────────────────────────────────────────────────────────────────

def test_usage_totals_sum_only_the_callers_events(client: TestClient):
    body = client.get("/api/usage", headers=_headers()).json()

    assert body["totals"]["events"] == 5
    assert body["totals"]["input_tokens"] == 1000 + 500 + 300 + 900
    assert body["totals"]["output_tokens"] == 200 + 100 + 50 + 90
    assert body["totals"]["bytes_delta"] == 4096
    assert body["totals"]["usd_cost"] == pytest.approx(0.17)


def test_usage_groups_by_model_and_excludes_non_token_kinds(client: TestClient):
    body = client.get("/api/usage", headers=_headers()).json()
    by_model = {m["model"]: m for m in body["by_model"]}

    assert set(by_model) == {"claude-opus-4-7", "gpt-4o"}
    assert by_model["claude-opus-4-7"]["input_tokens"] == 1500
    assert by_model["claude-opus-4-7"]["usd_cost"] == pytest.approx(0.07)
    assert by_model["gpt-4o"]["events"] == 2


def test_usage_groups_by_kind(client: TestClient):
    body = client.get("/api/usage", headers=_headers()).json()
    by_kind = {k["kind"]: k for k in body["by_kind"]}

    assert set(by_kind) == {"token", "storage"}
    assert by_kind["storage"]["bytes_delta"] == 4096
    assert by_kind["token"]["events"] == 4


def test_usage_buckets_by_day(client: TestClient):
    """substr(created_at, 1, 10) has to yield a YYYY-MM-DD on both backends."""
    body = client.get("/api/usage", headers=_headers()).json()
    days = [d["day"] for d in body["daily"]]

    assert len(days) == 3, f"expected 3 distinct days, got {days}"
    assert days == sorted(days)
    for day in days:
        datetime.strptime(day, "%Y-%m-%d")  # raises if the bucketing broke

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert next(d for d in body["daily"] if d["day"] == today)["input_tokens"] == 1500


def test_usage_window_excludes_older_events(client: TestClient):
    body = client.get("/api/usage?days=7", headers=_headers()).json()

    assert body["totals"]["events"] == 4  # the 10-day-old row drops out
    assert body["totals"]["input_tokens"] == 1000 + 500 + 300


def test_usage_project_filter_narrows(client: TestClient):
    body = client.get(
        f"/api/usage?project_id={_IDS['other_project_id']}", headers=_headers()
    ).json()

    assert body["totals"]["events"] == 1
    assert [m["model"] for m in body["by_model"]] == ["gpt-4o"]


def test_usage_recent_returns_events_newest_first(client: TestClient):
    body = client.get("/api/usage", headers=_headers()).json()
    recent = body["recent"]

    assert len(recent) == 5
    assert [r["created_at"] for r in recent] == sorted(
        (r["created_at"] for r in recent), reverse=True
    )
    assert all(r["payer"] == "kerf_paid" for r in recent)


def test_usage_requires_auth(client: TestClient):
    assert client.get("/api/usage").status_code in (401, 403)
    assert client.get("/api/provider-keys").status_code in (401, 403)
