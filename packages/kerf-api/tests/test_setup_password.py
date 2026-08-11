"""First run: claiming a node with a password, and signing in with it.

`local_mode` — the default, and the only mode a desktop install has used —
hands out a full session from /auth/bootstrap-local with no credential at all.
Anything that can reach the port is signed in. These endpoints replace that
with one password per node, set on first load.

Most of the value here is in the refusals, because a first run is a *claim*:
whoever sets the password owns the node. So the tests care about who is allowed
to claim, that claiming twice is impossible, and that neither answer leaks
whether a node is still claimable.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile
from contextlib import asynccontextmanager
from typing import Generator

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

from kerf_core import node_credential  # noqa: E402


@pytest.fixture()
def client(tmp_path) -> Generator[TestClient, None, None]:
    """A fresh, unclaimed node per test."""
    db_url = f"sqlite://{tmp_path}/setup.db"

    async def _migrate():
        from kerf_core.db.migrations.runner import run_sqlite_migrations
        await run_sqlite_migrations(db_url)

    asyncio.run(_migrate())

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        import kerf_core.db.connection as _conn
        from kerf_core.db.sqlite_backend import create_sqlite_pool

        pool = await create_sqlite_pool(db_url, max_size=2)
        _conn._pool = pool
        yield
        _conn._pool = None
        await pool.close()

    from kerf_api.routes_setup import router

    app = FastAPI(lifespan=_lifespan)
    app.include_router(router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── the hash ────────────────────────────────────────────────────────────────

def test_a_password_verifies_against_its_own_hash():
    stored = node_credential.hash_password("correct horse battery staple")
    assert node_credential.verify_password("correct horse battery staple", stored) is True
    assert node_credential.verify_password("something else", stored) is False


def test_an_unconfigured_node_authenticates_nothing():
    """The dummy hash exists so a wrong password and an unset one take the same
    time. It must never be the thing that lets someone in."""
    assert node_credential.verify_password("anything at all", None) is False
    assert node_credential.verify_password("", None) is False


def test_the_hash_is_salted():
    """Two nodes with the same password must not share a hash, or one leak
    tells you about every other node."""
    a = node_credential.hash_password("same password")
    b = node_credential.hash_password("same password")
    assert a != b


# ── first run ───────────────────────────────────────────────────────────────

def test_a_fresh_node_reports_itself_unconfigured(client):
    body = client.get("/api/setup/state").json()
    assert body["configured"] is False
    assert body["can_configure_here"] is True


def test_claiming_sets_the_password(client):
    resp = client.post("/api/setup/password", json={"password": "a-good-long-password"})
    assert resp.status_code == 201

    assert client.get("/api/setup/state").json()["configured"] is True


def test_a_node_can_only_be_claimed_once(client):
    client.post("/api/setup/password", json={"password": "a-good-long-password"})

    second = client.post("/api/setup/password", json={"password": "attacker-chosen"})

    assert second.status_code == 409
    # An attacker with a live session must not be able to lock the owner out,
    # and the owner can always reach the machine.
    assert "set-password" in second.json()["detail"]


def test_the_original_password_survives_a_second_claim_attempt(client):
    client.post("/api/setup/password", json={"password": "a-good-long-password"})
    client.post("/api/setup/password", json={"password": "attacker-chosen"})

    assert client.post("/api/setup/signin", json={"password": "attacker-chosen"}).status_code == 401


@pytest.mark.parametrize("password", ["", "short", "1234567"])
def test_a_too_short_password_is_refused(client, password):
    resp = client.post("/api/setup/password", json={"password": password})
    assert resp.status_code == 422
    assert client.get("/api/setup/state").json()["configured"] is False


def test_claiming_over_a_network_bind_is_refused(client, monkeypatch):
    """An unconfigured node on a network is claimable by whoever arrives first.
    That is a race with a stranger, so the browser refuses and the operator
    uses the CLI, where reaching the machine already proves the point."""
    monkeypatch.setattr(node_credential, "may_configure_over_network",
                        lambda: (False, "bound to 0.0.0.0, not loopback — use kerf admin set-password"))

    resp = client.post("/api/setup/password", json={"password": "a-good-long-password"})

    assert resp.status_code == 403
    assert "set-password" in resp.json()["detail"]
    assert client.get("/api/setup/state").json()["configured"] is False


def test_the_state_endpoint_says_where_setup_is_possible(client, monkeypatch):
    monkeypatch.setattr(node_credential, "may_configure_over_network",
                        lambda: (False, "bound to 0.0.0.0, not loopback"))

    body = client.get("/api/setup/state").json()

    assert body["can_configure_here"] is False
    assert "loopback" in body["reason"]


# ── signing in ──────────────────────────────────────────────────────────────

def test_the_wrong_password_is_refused(client):
    client.post("/api/setup/password", json={"password": "a-good-long-password"})

    resp = client.post("/api/setup/signin", json={"password": "not it"})

    assert resp.status_code == 401


def test_an_unclaimed_node_answers_signin_exactly_like_a_wrong_password(client):
    """Which of the two it is tells an attacker whether the node is still
    claimable, and that is the more useful fact of the pair."""
    unclaimed = client.post("/api/setup/signin", json={"password": "guess"})

    client.post("/api/setup/password", json={"password": "a-good-long-password"})
    wrong = client.post("/api/setup/signin", json={"password": "guess"})

    assert unclaimed.status_code == wrong.status_code == 401
    assert unclaimed.json()["detail"] == wrong.json()["detail"]


# ── the generated password ──────────────────────────────────────────────────

def test_a_suggested_password_is_long_and_unique():
    first = node_credential.suggest_password()
    assert len(first) >= node_credential.MIN_PASSWORD_LENGTH
    assert first != node_credential.suggest_password()


@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1", True), ("localhost", True), ("::1", True),
    ("0.0.0.0", False), ("", False), ("192.168.1.5", False),
])
def test_loopback_detection_matches_the_terminal_gate(host, expected):
    """Both gates key on the same question — who can reach this — so they must
    not disagree about what loopback means."""
    assert node_credential._is_loopback(host) is expected
