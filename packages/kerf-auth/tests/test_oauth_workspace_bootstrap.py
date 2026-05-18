"""Regression: OAuth sign-in must guarantee a default workspace.

Bug: google_callback / github_login_callback only created a personal
workspace on the *new-user INSERT* path. If that first create failed or
was interrupted (e.g. instance rolled mid-redeploy) the user existed but
owned no workspace, and every later login took an "existing user" path
that never repaired it — surfacing as
``{"detail":"workspace_id or workspace_slug required"}`` on the first
create-project.

Fix: both callbacks now self-heal — after the user is resolved on ANY
path (new INSERT, matched by provider id, matched by email) they call
get_default_workspace and create one if absent (mirrors email login).

These tests pin that invariant deterministically: get_default_workspace
and create_personal_workspace are patched so behaviour is independent of
conn.fetchrow ordering; we assert create_personal_workspace is called
iff no workspace exists, on every resolution path.
"""
import datetime as _dt
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app():
    from kerf_auth.routes import router as auth_router

    app = FastAPI()
    app.include_router(auth_router, prefix="/auth")
    return app


FAKE_SETTINGS = MagicMock()
FAKE_SETTINGS.google_client_id = "goog-client.apps.googleusercontent.com"
FAKE_SETTINGS.google_client_secret = "goog-secret"
FAKE_SETTINGS.google_redirect_url = "https://dev.kerf.sh/auth/google/callback"
FAKE_SETTINGS.cloud_github_client_id = "Iv1.test_client_id"
FAKE_SETTINGS.cloud_github_client_secret = "gh-secret"
FAKE_SETTINGS.cloud_github_redirect_url = "https://dev.kerf.sh/auth/github/callback"
FAKE_SETTINGS.cors_origin = "https://dev.kerf.sh"
FAKE_SETTINGS.jwt_secret = "test-jwt-secret"
FAKE_SETTINGS.jwt_refresh_ttl_days = 30
FAKE_SETTINGS.local_mode = False

USER_ROW = {
    "id": "00000000-0000-0000-0000-0000000000aa",
    "email": "person@example.com",
    "name": "Person Example",
    "avatar_url": "",
    "account_role": "user",
    "is_system": False,
    "created_at": _dt.datetime(2024, 1, 1),
}
WS_ROW = {
    "id": "00000000-0000-0000-0000-0000000000bb",
    "slug": "personal-aa-deadbeef",
    "name": "Person Example",
    "created_by": USER_ROW["id"],
    "created_at": _dt.datetime(2024, 1, 1),
    "avatar_storage_key": None,
}


def _resp(status_code, data):
    r = MagicMock()
    r.status_code = status_code
    r.json = MagicMock(return_value=data)
    return r


def _google_httpx_factory():
    """First `async with` -> token POST; second -> userinfo GET."""
    post_client = AsyncMock()
    post_client.post = AsyncMock(return_value=_resp(200, {"access_token": "ya29.tok"}))
    get_client = AsyncMock()
    get_client.get = AsyncMock(return_value=_resp(200, {
        "sub": "google-sub-123",
        "email": USER_ROW["email"],
        "name": USER_ROW["name"],
        "picture": "",
    }))
    n = {"i": 0}

    class _CM:
        async def __aenter__(self_):
            i = n["i"]; n["i"] += 1
            return post_client if i == 0 else get_client

        async def __aexit__(self_, *a):
            return False

    return lambda **kw: _CM()


def _github_httpx_factory():
    """First `async with` -> token POST; second -> user + emails GETs."""
    post_client = AsyncMock()
    post_client.post = AsyncMock(return_value=_resp(200, {
        "access_token": "ghu_tok", "scope": "read:user,user:email",
    }))
    get_client = AsyncMock()
    get_client.get = AsyncMock(side_effect=[
        _resp(200, {"id": 999, "login": "person", "name": USER_ROW["name"],
                    "avatar_url": ""}),
        _resp(200, [{"email": USER_ROW["email"], "primary": True,
                     "verified": True}]),
    ])
    n = {"i": 0}

    class _CM:
        async def __aenter__(self_):
            i = n["i"]; n["i"] += 1
            return post_client if i == 0 else get_client

        async def __aexit__(self_, *a):
            return False

    return lambda **kw: _CM()


def _pool(fetchrow_side_effect):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# fetchrow sequences per resolution path (only the user-resolution
# fetchrows matter; get_default_workspace + issue_tokens are patched).
PATH_EXISTING_BY_PROVIDER_ID = [USER_ROW]
PATH_EXISTING_BY_EMAIL = [None, USER_ROW]
PATH_NEW_USER = [None, None, USER_ROW]


class _Base:
    provider = ""  # "google" | "github"

    def setup_method(self):
        self._sp = patch("kerf_auth.routes.settings", FAKE_SETTINGS)
        self._sp.start()
        self._it = patch("kerf_auth.routes.issue_tokens",
                         AsyncMock(return_value=("acc.jwt", "refresh.jwt")))
        self._it.start()
        self.app = _make_app()
        self.client = TestClient(self.app, follow_redirects=False)

    def teardown_method(self):
        self._it.stop()
        self._sp.stop()

    # -- per-provider plumbing -------------------------------------------
    def _start_state(self):
        if self.provider == "google":
            r = self.client.get("/auth/google/start")
            cookie = "kerf_oauth_state"
            cb = "/auth/google/callback"
        else:
            r = self.client.get("/auth/github/login/start")
            cookie = "kerf_github_login_state"
            cb = "/auth/github/login/callback"
        assert r.status_code == 302
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        return state, cookie, cb

    def _factory(self):
        return (_google_httpx_factory() if self.provider == "google"
                else _github_httpx_factory())

    def _invoke(self, fetchrow_seq, gdw_return):
        state, cookie, cb = self._start_state()
        cpw = AsyncMock(return_value=WS_ROW)
        with patch("kerf_auth.routes.get_pool_required",
                   AsyncMock(return_value=_pool(list(fetchrow_seq)))), \
             patch("kerf_auth.routes.get_default_workspace",
                   AsyncMock(return_value=gdw_return)), \
             patch("kerf_auth.routes.create_personal_workspace", cpw), \
             patch("kerf_auth.routes.httpx.AsyncClient", self._factory()):
            resp = self.client.get(
                cb, params={"code": "c0de", "state": state},
                cookies={cookie: state},
            )
        return resp, cpw

    # -- shared assertions across all 3 resolution paths -----------------
    @pytest.mark.parametrize("seq", [
        PATH_EXISTING_BY_PROVIDER_ID, PATH_EXISTING_BY_EMAIL, PATH_NEW_USER,
    ])
    def test_creates_workspace_when_absent_on_every_path(self, seq):
        resp, cpw = self._invoke(seq, gdw_return=(None, False))
        assert resp.status_code == 302
        assert "/auth/callback" in resp.headers["location"]
        assert cpw.await_count == 1, (
            "missing default workspace must be self-healed on this path "
            "(regression: 'workspace_id or workspace_slug required')"
        )

    @pytest.mark.parametrize("seq", [
        PATH_EXISTING_BY_PROVIDER_ID, PATH_EXISTING_BY_EMAIL, PATH_NEW_USER,
    ])
    def test_skips_creation_when_workspace_exists(self, seq):
        resp, cpw = self._invoke(seq, gdw_return=(WS_ROW, True))
        assert resp.status_code == 302
        assert cpw.await_count == 0, (
            "must not create a second workspace when one already exists"
        )


class TestGoogleWorkspaceSelfHeal(_Base):
    provider = "google"


class TestGithubWorkspaceSelfHeal(_Base):
    provider = "github"
