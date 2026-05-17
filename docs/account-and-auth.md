# Account and auth

How to sign up, sign in, manage API tokens, and connect OAuth providers.

---

## Sign-up

### Email and password

```
POST /auth/register
```

Body: `{email, password, name?}`

Minimum password length is 8 characters. The email must be unique. A personal workspace is created automatically on sign-up. A welcome email is sent if the hosted tier has a transactional email provider configured.

### Google OAuth

Click **Continue with Google** in the app. This starts the OAuth flow at `GET /auth/google/start` (scope `openid email profile`). After authorisation, you are redirected back and a Kerf account is found-or-created for your Google identity:

1. Match by `google_id` — if found, update name and avatar.
2. Match by email — if found, link the Google identity to the existing account.
3. Otherwise, create a new account and a personal workspace.

### GitHub OAuth (sign-in)

Click **Continue with GitHub** in the app. This starts the OAuth flow at `GET /auth/github/login/start` (scope `read:user user:email`). The same find-or-create logic applies as for Google.

Note: this is distinct from the **GitHub repo connect** flow in [github-sync.md](./github-sync.md), which uses `scope=repo` and links a *project* to a GitHub repository.

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

Tokens carry the `workspace:member-role` scope by default. An optional per-token daily spend cap (`max_spend_per_day_usd`) limits how much a single token can spend on paid LLM calls per day. See [billing-and-credits.md](./billing-and-credits.md#api-token-daily-caps).

---

## BYO API keys

To use your own LLM provider API keys instead of Kerf credits, save a key in **Settings → API keys**. Set `prefer_byo = true` to use your keys by default. When a key is on file and BYO is preferred, that provider's requests bypass billing entirely. See [billing-and-credits.md](./billing-and-credits.md#byo-bring-your-own-keys).

---

## GitHub OAuth (repo connect)

Connecting a GitHub account for git sync is a separate flow from GitHub sign-in:

- Start: `GET /auth/github/start` (scope `repo` — requires an already-authenticated Kerf session)
- Callback: `GET /auth/github/callback` — encrypts the token at rest and upserts `cloud_github_tokens`
- Disconnect: `DELETE /auth/github`

GitHub tokens are stored AES-GCM encrypted. See [github-sync.md](./github-sync.md) for the full git sync model.

---

## Local mode

When Kerf is running in `local_mode = true` (single-user self-hosted install), authentication is bypassed entirely. The endpoint `POST /auth/bootstrap-local` issues a session for the configured local user without a password. The login UI is hidden; all requests resolve to the local user.

See [local-self-host.md](./local-self-host.md) for the full local install model.

---

## Related pages

- [billing-and-credits.md](./billing-and-credits.md) — credits, API token daily caps, BYO keys
- [github-sync.md](./github-sync.md) — linking a GitHub repo to a project
- [local-self-host.md](./local-self-host.md) — local install, auth.optional mode
- [projects.md](./projects.md) — workspace model, share links
