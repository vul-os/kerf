# Account and auth

How to sign up, sign in, and manage API tokens.

---

## Sign-up

### Email and password

```
POST /auth/register
```

Body: `{email, password, name?}`

Minimum password length is 8 characters. The email must be unique. A personal workspace is created automatically on sign-up. Kerf has no transactional email — there is no welcome email.

### Google OAuth

Click **Continue with Google** in the app. This starts the OAuth flow at `GET /auth/google/start` (scope `openid email profile`). After authorisation, you are redirected back and a Kerf account is found-or-created for your Google identity:

1. Match by `google_id` — if found, update name and avatar.
2. Match by email — if found, link the Google identity to the existing account.
3. Otherwise, create a new account and a personal workspace.

GitHub sign-in is retired: kerf operates no OAuth app for GitHub (see the
"Addendum: local git only; no OAuth" ADR in `decisions.md`, 2026-07-17).
Google OAuth and email/password remain the two sign-in paths.

---

## Sign-in

```
POST /auth/login
```

Body: `{email, password}`

Returns `{access_token, refresh_token, user, default_workspace}`.

---

## Token lifecycle

Kerf uses short-lived JWT access tokens (configurable TTL, default 15 minutes) and long-lived opaque refresh tokens (configurable TTL, default 30 days).

| Token | Where used | How to refresh |
|---|---|---|
| `access_token` | `Authorization: Bearer <token>` header on every API call | `POST /auth/refresh` |
| `refresh_token` | `POST /auth/refresh` body | Rotating — each refresh issues a new pair |

Refresh tokens are single-use (rotating). The old refresh token is revoked atomically when a new pair is issued.

### Sign-out

```
POST /auth/logout
```

Body: `{refresh_token}` — revokes the refresh token. The access token expires on its own (there is no server-side access-token revocation; keep the TTL short).

---

## Password reset

```
POST /auth/password-reset/request
```

Body: `{email}` — sends a password reset email to the address if it exists. The email contains a time-limited link.

```
POST /auth/password-reset/confirm
```

Body: `{token, new_password}` — consumes the reset token and updates the password.

---

## API tokens

API tokens are long-lived credentials tied to a workspace. They are used with the [kerf-sdk](./v1-rpc.md) and for programmatic access.

```
POST   /api/api-tokens     — create a token (name required, workspace context required)
GET    /api/api-tokens     — list your tokens for this workspace
DELETE /api/api-tokens/:id — revoke a token
```

The raw token value is returned **once** at creation time and is not retrievable afterwards. Store it securely.

Tokens carry the `workspace:member-role` scope by default. An optional per-token daily spend cap (`max_spend_per_day_usd`) limits how much a single token can spend on LLM calls per day — a safety limit against runaway automated usage, not a billing mechanism (kerf has no billing anywhere). See [billing-and-credits.md](./billing-and-credits.md).

---

## BYO API keys

To use your own LLM provider API keys, save a key in **Settings → API keys**. Set `prefer_byo = true` to use your keys by default. Kerf has no billing anywhere — bringing your own key simply means requests go straight to your provider account instead of a shared one. See [billing-and-credits.md](./billing-and-credits.md).

---

## GitHub (as a git remote)

There is no GitHub OAuth flow for repo access. GitHub is configured as an
ordinary git remote using your own SSH key or PAT, exactly as with the git
CLI — kerf never brokers OAuth or holds a GitHub token on your behalf. See
[github-sync.md](./github-sync.md) for the full git sync model.

---

## Local mode

When Kerf is running in `local_mode = true` (single-user self-hosted install), authentication is bypassed entirely. The endpoint `POST /auth/bootstrap-local` issues a session for the configured local user without a password. The login UI is hidden; all requests resolve to the local user.

See [local-self-host.md](./local-self-host.md) for the full local install model.

---

## Related pages

- [billing-and-credits.md](./billing-and-credits.md) — API token daily caps, BYO keys (retired: kerf has no billing anywhere)
- [github-sync.md](./github-sync.md) — linking a GitHub repo to a project
- [local-self-host.md](./local-self-host.md) — local install, auth.optional mode
- [projects.md](./projects.md) — workspace model, share links
