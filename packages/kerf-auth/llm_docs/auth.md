# kerf-auth — authentication flows, routes, token lifecycle

`kerf-auth` provides Kerf's token lifecycle: JWT access tokens, opaque refresh
tokens, and long-lived opaque API tokens.

**Sign-in does not live here any more.** Kerf is one node, one password: it is
set on first load and exchanged for a session through `/api/setup/*` (see
`kerf-api`). Registration, login, password reset, email verification and OAuth
— Google and GitHub alike — are gone, along with the accounts they served.
Recovery is `kerf admin set-password` on the machine, because a self-hosted
node has no mail transport.

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

### `/api/setup/*` — the whole of sign-in (in kerf-api)

| Method | Path | Description |
|---|---|---|
| GET | `/api/setup/state` | Has this node been claimed, and may it be claimed from here? |
| POST | `/api/setup/password` | Claim an unconfigured node. Once only (409 after). 403 on a non-loopback bind — use `kerf admin set-password`. |
| POST | `/api/setup/signin` | Exchange the node password for a session. Returns `AuthResponse`. |

### `/auth/*` — token lifecycle only

| Method | Path | Description |
|---|---|---|
| POST | `/auth/refresh` | Exchange a refresh token for a new access token. |
| POST | `/auth/logout` | Revoke the current refresh token (cookie or body). |

`/auth/register`, `/auth/login`, `/auth/forgot-password`, `/auth/reset-password`,
`/auth/bootstrap-local` and the Google and GitHub OAuth routes have been
removed. They return 404. Do not suggest them.

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
- `max_spend_per_day_usd` / `spend_today_usd` columns remain on `api_tokens` but are no longer enforced — Kerf has no billing anywhere, so every request runs unconditionally

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

The node password is hashed with **bcrypt** plus a server-side pepper
(`PASSWORD_PEPPER`), in `kerf_core.node_credential`. The pepper prevents
rainbow-table attacks if the bcrypt hashes leak without the server config. An
unconfigured node is compared against a dummy hash so that "no password set"
and "wrong password" take the same time — otherwise a stopwatch tells an
attacker whether the node is still claimable.

```python
def hash_password(password: str) -> str:
    peppered = (password + settings.password_pepper).encode("utf-8")
    return bcrypt.hashpw(peppered, bcrypt.gensalt()).decode("utf-8")
```

---

## GitHub is a git remote, not an identity provider

The GitHub OAuth sign-in flow that used to be documented here is removed, along
with Google's. GitHub is used as an ordinary git remote — you authenticate with
a personal access token or an SSH key, exactly as you would with the git CLI.
Kerf brokers no OAuth and holds no GitHub-issued token on your behalf.

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
