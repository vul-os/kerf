# kerf-auth — authentication flows, routes, token lifecycle

`kerf-auth` provides all authentication surfaces for Kerf: email/password registration and login, Google OAuth, GitHub OAuth (cloud-only), JWT access tokens, opaque refresh tokens, and long-lived opaque API tokens.

It registers as the first plugin in the dependency chain (`depends=[]`). All other API-bearing plugins declare `depends=["kerf-auth"]` and therefore load after it.

---

## Plugin registration

```python
# kerf_auth/plugin.py
async def register(app, ctx) -> PluginManifest:
    app.include_router(router, prefix="/auth")
    app.include_router(api_tokens_router, prefix="/api")
    return PluginManifest(
        name="kerf-auth",
        provides=["auth.jwt", "auth.api-token", "auth.session"],
        depends=[],
    )
```

---

## Routes

### `/auth/*` — session management

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create account (email + password). Returns `AuthResponse`. Also fires a welcome email via `kerf_cloud.email` (silent fail). |
| POST | `/auth/login` | Verify password (bcrypt + pepper). Returns `AuthResponse`. |
| POST | `/auth/refresh` | Exchange a refresh token for a new access token. |
| POST | `/auth/logout` | Revoke the current refresh token (cookie or body). |
| GET | `/auth/me` | Return the authenticated user + default workspace. |
| GET | `/auth/google` | Redirect to Google OAuth consent screen. |
| GET | `/auth/google/callback` | Exchange Google code for user. Auto-creates account on first sign-in. |
| GET | `/auth/github/login` | Redirect to GitHub OAuth (cloud-only, requires `cloud_enabled`). |
| GET | `/auth/github/callback` | Exchange GitHub code. Saves encrypted GitHub token to DB. |

### `/api/api-tokens` — long-lived API tokens

| Method | Path | Description |
|---|---|---|
| GET | `/api/api-tokens` | List the authenticated user's API tokens. |
| POST | `/api/api-tokens` | Create a new token. The raw token is returned once and never shown again. |
| DELETE | `/api/api-tokens/{id}` | Revoke a token. |

---

## Token types

### JWT access token
- Short-lived (default 15 minutes, `JWT_ACCESS_TTL_MINUTES`)
- HS256-signed with `JWT_SECRET`
- Payload: `{sub: user_id, exp, iat}`
- Sent as `Authorization: Bearer <token>` or `access_token` cookie

### Refresh token
- Long-lived (default 30 days, `JWT_REFRESH_TTL_DAYS`)
- Opaque 64-byte URL-safe random string
- Stored in DB as SHA-256 hash
- Sent as `refresh_token` httpOnly cookie or JSON body field
- One-time use: the old token is revoked and a new one issued on each refresh

### Opaque API token
- For the kerf-sdk and scripting clients
- Never expire unless explicitly revoked
- Stored as SHA-256 hash in `api_tokens` table
- Format: `kerf_<random_urlsafe_bytes>` (easily recognisable for scanning)
- Optional per-token daily spend cap (`max_spend_per_day_usd`) enforced by `kerf-billing`

---

## Auth dependency (`kerf_core.dependencies`)

All protected routes use FastAPI dependencies:

```python
from kerf_core.dependencies import require_auth, optional_auth

@router.get("/my-route")
async def my_route(user_id: str = Depends(require_auth)):
    ...
```

`require_auth` accepts either a valid JWT Bearer token or a valid opaque API token. Returns the `user_id` string. Raises `HTTP 401` on failure.

`optional_auth` returns `user_id | None` — used for public endpoints that have optional personalisation.

---

## Password hashing

Passwords are hashed with **bcrypt** plus a server-side pepper (`PASSWORD_PEPPER`). The pepper prevents rainbow-table attacks if the bcrypt hashes leak without the server config.

```python
def hash_password(password: str) -> str:
    peppered = (password + settings.password_pepper).encode("utf-8")
    return bcrypt.hashpw(peppered, bcrypt.gensalt()).decode("utf-8")
```

---

## GitHub OAuth flow (cloud)

GitHub OAuth is only mounted when `cloud_enabled=True`. The flow:

1. `GET /auth/github/login` — redirect to `github.com/login/oauth/authorize`
2. User authorises → GitHub redirects to `/auth/github/callback?code=…`
3. Exchange code for a GitHub access token (POST to `github.com/login/oauth/access_token`)
4. Fetch the user's GitHub email via the GitHub API
5. Upsert Kerf user, store encrypted GitHub token in `cloud_github_tokens`
6. Issue Kerf JWT + refresh token, redirect to frontend

The encrypted token enables the GitHub App repo-connect flow (handled by `kerf-cloud`).

---

## AuthResponse shape

```json
{
  "access_token": "eyJ…",
  "refresh_token": "…",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "Alice",
    "avatar_url": "",
    "account_role": "user",
    "is_system": false,
    "created_at": "2026-01-01T00:00:00"
  },
  "default_workspace": {
    "id": "uuid",
    "slug": "personal-abc-1234",
    "name": "Alice",
    "created_at": "…"
  }
}
```

Every new user automatically gets a personal workspace created during registration.
