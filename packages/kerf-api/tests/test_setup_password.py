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

from kerf_core import bind, node_credential  # noqa: E402


@pytest.fixture(autouse=True)
def loopback_bind(monkeypatch):
    """A node is only claimable through the browser when it is bound to
    loopback, and a TestClient binds nothing at all, so the address has to be
    stated. The tests about refusing a network claim override it."""
    monkeypatch.setattr(bind, "_bind_host", "127.0.0.1")


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


def test_the_right_password_returns_a_usable_session(client, monkeypatch):
    """Every test here checked a refusal, so a 500 on the *correct* password
    went unnoticed until the browser suite hit it: this route was annotated
    `-> dict` while the session machinery returns a model, and FastAPI
    rejected its own response. The success path is the one the product runs on.
    """
    monkeypatch.setenv("LOCAL_MODE", "true")
    client.post("/api/setup/password", json={"password": "a-good-long-password"})

    resp = client.post("/api/setup/signin", json={"password": "a-good-long-password"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]


def test_an_unclaimed_node_answers_signin_exactly_like_a_wrong_password(client):
    """Which of the two it is tells an attacker whether the node is still
    claimable, and that is the more useful fact of the pair."""
    unclaimed = client.post("/api/setup/signin", json={"password": "guess"})

    client.post("/api/setup/password", json={"password": "a-good-long-password"})
    wrong = client.post("/api/setup/signin", json={"password": "guess"})

    assert unclaimed.status_code == wrong.status_code == 401
    assert unclaimed.json()["detail"] == wrong.json()["detail"]


# ── brute force ─────────────────────────────────────────────────────────────
#
# One password guarding a whole node makes brute force the obvious attack, and
# this is the only password endpoint left — /auth/login and its lockout tests
# went with the accounts. What those tests asserted has to hold here instead.

def test_signin_is_rate_limited():
    """A limiter is declared on sign-in, per-IP, in minutes rather than hours.

    Asserted on the route's dependencies rather than by making 11 requests: the
    limiter is backed by the database, and a test that exercises it end to end
    is really a test of the limiter, which kerf-core already covers.
    """
    import kerf_api.routes_setup as setup_routes

    dep = _rate_limit_args(setup_routes.router, "/setup/signin")
    assert dep is not None, "sign-in must be rate limited"
    max_per_window, window_seconds, key_prefix = dep
    assert key_prefix == "setup:signin"
    # A slow limit: the owner types their password a handful of times, an
    # attacker needs thousands of guesses.
    assert max_per_window <= 20
    assert window_seconds <= 300


def test_claiming_is_rate_limited_separately():
    """Distinct buckets, so a burst of claim attempts cannot lock the owner out
    of signing in, or vice versa."""
    import kerf_api.routes_setup as setup_routes

    claim = _rate_limit_args(setup_routes.router, "/setup/password")
    signin = _rate_limit_args(setup_routes.router, "/setup/signin")
    assert claim is not None and signin is not None
    assert claim[2] != signin[2]


def _rate_limit_args(router, path):
    """The (max_per_window, window_seconds, key_prefix) of the rate limiter on
    *path*, or None if it has none.

    rate_limit() returns a closure, so the numbers live in its cell contents
    rather than anywhere nameable.
    """
    for route in router.routes:
        if getattr(route, "path", None) != path:
            continue
        for dependency in getattr(route, "dependencies", []) or []:
            call = getattr(dependency, "dependency", None)
            closure = getattr(call, "__closure__", None) or ()
            values = [c.cell_contents for c in closure]
            ints = [v for v in values if isinstance(v, int) and not isinstance(v, bool)]
            strs = [v for v in values if isinstance(v, str)]
            if len(ints) >= 2 and strs:
                return ints[0], ints[1], strs[0]
        # Dependencies declared as parameter defaults rather than in the
        # decorator live on the dependant tree instead.
        for dep in getattr(getattr(route, "dependant", None), "dependencies", []) or []:
            call = getattr(dep, "call", None)
            closure = getattr(call, "__closure__", None) or ()
            values = [c.cell_contents for c in closure]
            ints = [v for v in values if isinstance(v, int) and not isinstance(v, bool)]
            strs = [v for v in values if isinstance(v, str)]
            if len(ints) >= 2 and strs:
                return ints[0], ints[1], strs[0]
    return None


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
    """Both gates key on the same question — who can reach this — so they read
    it from the same place, and this is that place."""
    assert bind.is_loopback(host) is expected


def test_claiming_over_a_wildcard_bind_is_refused(monkeypatch):
    """The bug this module's gate exists to prevent, in the configuration that
    actually ships: `kerf serve` defaults to --host 0.0.0.0, and for a while
    the gate read a Settings field that does not exist and then fell back to
    "127.0.0.1" — so the default install told the browser it was safe to claim
    a node the whole network could reach."""
    monkeypatch.setattr(bind, "_bind_host", "0.0.0.0")

    allowed, reason = node_credential.may_configure_over_network()

    assert allowed is False
    assert "0.0.0.0" in reason
    assert "kerf admin set-password" in reason


def test_an_unrecorded_bind_is_treated_as_public(monkeypatch):
    """Embedded and third-party hosts never call set_bind_host. Assuming
    loopback there would restore the same hole by a different route, so the
    unknown case fails closed."""
    monkeypatch.setattr(bind, "_bind_host", None)
    monkeypatch.delenv("KERF_HOST", raising=False)

    assert bind.is_loopback_bind() is False
    assert node_credential.may_configure_over_network()[0] is False


def test_a_recorded_loopback_bind_allows_the_claim(monkeypatch):
    monkeypatch.setattr(bind, "_bind_host", "127.0.0.1")
    assert node_credential.may_configure_over_network()[0] is True
