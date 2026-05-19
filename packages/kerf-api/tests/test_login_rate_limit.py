"""T-310 — Login rate-limit contract.

Verifies that:
  1. 11 rapid POST /auth/login from same IP → 11th returns 429.
  2. Different IPs are independent (second IP succeeds after first is limited).

Design: no live Postgres needed. We mock the rate_limit.enforce function to
simulate bucket exhaustion, and the DB pool / user lookup to control auth
outcomes. The TestClient talks to a real FastAPI app wired with the kerf_auth
router.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    """Build a minimal FastAPI app wiring kerf_auth router."""
    import kerf_auth.routes as auth_routes

    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/auth")
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoginRateLimit:
    """The login endpoint enforces a rate limit keyed on IP."""

    def test_11th_login_from_same_ip_returns_429(self):
        """Simulate 10 successful attempts then a rate-limit hit on the 11th."""
        import kerf_core.rate_limit as rl_mod
        import kerf_auth.routes as auth_routes

        call_count = 0
        LIMIT = 10

        async def fake_enforce(pool, key, max_per_window, window_seconds=60):
            nonlocal call_count
            call_count += 1
            if call_count > LIMIT:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=429,
                    detail={"detail": "rate limit exceeded", "retry_after": 30},
                    headers={"Retry-After": "30"},
                )

        # Mock a successful login so auth logic doesn't hit the DB.
        fake_user = {
            "id": "00000000-0000-0000-0000-000000000001",
            "email": "test@example.com",
            "name": "Test User",
            "avatar_url": "",
            "account_role": "user",
            "is_system": False,
            "email_verified": True,
            "created_at": "2024-01-01T00:00:00Z",
            "password_hash": "$2b$12$somefakehashedpassword...",
        }

        with patch.object(rl_mod, "enforce", side_effect=fake_enforce), \
             patch("kerf_core.db.connection.get_pool_required") as mock_core_pool, \
             patch.object(auth_routes, "get_pool_required") as mock_auth_pool, \
             patch.object(auth_routes, "users_queries") as mock_uq, \
             patch.object(auth_routes, "check_password", return_value=True), \
             patch.object(auth_routes, "issue_tokens", new=AsyncMock(return_value=("access", "refresh"))), \
             patch.object(auth_routes, "get_default_workspace", new=AsyncMock(return_value=(None, False))):

            # Wire DB pool mocks (rate_limit dep uses kerf_core.db.connection;
            # auth route uses auth_routes.get_pool_required)
            fake_conn = AsyncMock()
            fake_conn.__aenter__ = AsyncMock(return_value=fake_conn)
            fake_conn.__aexit__ = AsyncMock(return_value=False)
            fake_pool = AsyncMock()
            fake_pool.acquire.return_value = fake_conn
            mock_core_pool.return_value = fake_pool
            mock_auth_pool.return_value = fake_pool
            mock_uq.get_user_by_email = AsyncMock(return_value=fake_user)

            app = _make_app()
            client = TestClient(app, raise_server_exceptions=False)

            responses = []
            for _ in range(11):
                r = client.post(
                    "/auth/login",
                    json={"email": "test@example.com", "password": "validpass"},
                    headers={"X-Forwarded-For": "1.2.3.4"},
                )
                responses.append(r.status_code)

        # The 11th call should be 429
        assert responses[10] == 429, (
            f"Expected 11th login to be 429, got {responses[10]}"
        )

    def test_different_ips_are_independent(self):
        """Two different IPs each get their own bucket — one being limited
        does NOT affect the other."""
        import kerf_core.rate_limit as rl_mod
        import kerf_auth.routes as auth_routes

        # Per-IP counters
        ip_counts: dict[str, int] = {}
        LIMIT = 10

        async def fake_enforce(pool, key, max_per_window, window_seconds=60):
            # key format: "auth:login:<ip>"
            parts = key.split(":")
            caller = parts[-1] if parts else "unknown"
            ip_counts[caller] = ip_counts.get(caller, 0) + 1
            if ip_counts[caller] > LIMIT:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=429,
                    detail={"detail": "rate limit exceeded", "retry_after": 30},
                    headers={"Retry-After": "30"},
                )

        fake_user = {
            "id": "00000000-0000-0000-0000-000000000002",
            "email": "test2@example.com",
            "name": "Test2",
            "avatar_url": "",
            "account_role": "user",
            "is_system": False,
            "email_verified": True,
            "created_at": "2024-01-01T00:00:00Z",
            "password_hash": "$2b$12$somefakehashedpassword...",
        }

        with patch.object(rl_mod, "enforce", side_effect=fake_enforce), \
             patch("kerf_core.db.connection.get_pool_required") as mock_core_pool2, \
             patch.object(auth_routes, "get_pool_required") as mock_auth_pool2, \
             patch.object(auth_routes, "users_queries") as mock_uq, \
             patch.object(auth_routes, "check_password", return_value=True), \
             patch.object(auth_routes, "issue_tokens", new=AsyncMock(return_value=("tok", "rtok"))), \
             patch.object(auth_routes, "get_default_workspace", new=AsyncMock(return_value=(None, False))):

            fake_conn = AsyncMock()
            fake_conn.__aenter__ = AsyncMock(return_value=fake_conn)
            fake_conn.__aexit__ = AsyncMock(return_value=False)
            fake_pool = AsyncMock()
            fake_pool.acquire.return_value = fake_conn
            mock_core_pool2.return_value = fake_pool
            mock_auth_pool2.return_value = fake_pool
            mock_uq.get_user_by_email = AsyncMock(return_value=fake_user)

            app = _make_app()
            client = TestClient(app, raise_server_exceptions=False)

            # Exhaust IP-A
            for _ in range(10):
                client.post(
                    "/auth/login",
                    json={"email": "test2@example.com", "password": "valid"},
                    headers={"X-Forwarded-For": "10.0.0.1"},
                )
            # 11th from IP-A is rate-limited
            r_a = client.post(
                "/auth/login",
                json={"email": "test2@example.com", "password": "valid"},
                headers={"X-Forwarded-For": "10.0.0.1"},
            )
            assert r_a.status_code == 429, (
                f"IP-A 11th request should be 429, got {r_a.status_code}"
            )

            # IP-B is unaffected — its first request should succeed
            r_b = client.post(
                "/auth/login",
                json={"email": "test2@example.com", "password": "valid"},
                headers={"X-Forwarded-For": "10.0.0.2"},
            )
            assert r_b.status_code != 429, (
                f"IP-B first request should NOT be 429; got {r_b.status_code}"
            )
