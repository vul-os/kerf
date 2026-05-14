# Cloud

Kerf's hosted tier — managed Postgres + storage + LLM keys with surfaces the
OSS build doesn't ship.

> **Licensing.** Cloud-tier code is **proprietary** under `cloud/`,
> `backend/cloud/`, and `src/cloud/`. See [LICENSE-CLOUD](../LICENSE-CLOUD).
> OSS core (everything else) is MIT and runs standalone.

Hands-on build/deploy guide: [docs/cloud-operator.md](./cloud-operator.md).

## Cloud-only vs OSS

| Feature | Cloud-only | Notes |
|---------|------------|-------|
| Workshop sharing | ✅ | Publish + fork + like + library submissions |
| Paystack billing | ✅ | USD UI, ZAR settlement via `backend/cloud/billing/` |
| GitHub OAuth | ✅ | `/auth/github/{start,callback}`, tokens encrypted |
| S3 Git Storer | ✅ | Stateless bare-repo deploys via `backend/storage/git_storer.py` |
| Cloud git routes | ✅ | Pull/push/branch/merge in `backend/routes/cloud.py` |
| STEP pre-tessellation | ✅ | Server-side triangulation; workers boot via `TESS_WORKERS` |
| Distributor live pricing | ✅ | 6h sweep in `distributors/sync.py`; DigiKey/Mouser/LCSC |
| Email (Mailer) | ✅ | `backend/cloud/email/mailer.py`; Resend/SES/SMTP |
| Everything else | OSS | Storage abstraction, file-revisions, tool registry, agent loop |

## Enabling cloud

Set `cloud_enabled=true` in `.env`. This flips two things:

**Routes** — `backend/main.py:190–193` conditionally mounts:
```python
if settings.cloud_enabled:
    app.include_router(cloud.router, prefix="/api", tags=["cloud"])
    app.include_router(cloud.github_oauth_router, prefix="/auth", tags=["github-oauth"])
    app.include_router(billing.router, prefix="/api", tags=["billing"])
```

**Startup services** — same block starts the Mailer, DistributorRegistry, and
pricing sweep goroutine.

**`local_mode` guard** — `backend/config.py:77–81`:
```python
@model_validator(mode="after")
def _enforce_cloud_disables_local_mode(self):
    if self.cloud_enabled and self.local_mode:
        self.local_mode = False
    return self
```
`cloud_enabled=true` forces `local_mode=false` regardless of the `.env` setting.

## AES-GCM encryption

`backend/utils/encrypt.py` — domain-scoped key derivation:
```
key = SHA-256(b"kerf:enc:<domain>:<jwt_secret>")
```
Used for:
- Distributor credentials (`distributor_credentials` table)
- GitHub OAuth tokens (`cloud_github_tokens` table, migration 031)

## S3 Git Storer

`backend/storage/git_storer.py` — `S3GitStorer` wraps pygit2 bare repos on S3:

- `clone_to_local`: downloads every S3 key under the prefix into a local bare repo. Empty prefix → `pygit2.init_repository(bare=True)`.
- `push_from_local`: repacks with `git gc --aggressive --prune=now`, uploads pack files → loose objects → refs (in that order), then writes a sentinel `_marker` object under conditional-put for optimistic concurrency. Orphan keys are batch-deleted via `delete_objects` (up to 1000/call).

Consistency: objects uploaded **before** refs so a concurrent reader never sees a ref pointing at a missing object. Two simultaneous writers are detected via the `_marker` ETag — the loser raises `StorerConcurrencyError` and the caller retries with fresh state. For coarser-grained "one push per project" semantics, hold a DB advisory lock at the route layer.

OSS / local-install: not used. Filesystem-backed git lives directly on disk and is handled by `pygit2` against the local repo path. The Storer is only constructed when `STORAGE_BACKEND=s3`.

Tests (`backend/tests/test_git_storer.py`, hermetic via `moto`):
- single-commit push → re-clone round-trip
- empty-prefix bootstrap
- multi-commit history + repack + orphan cleanup
- stale-ETag concurrent-push detection
- batch delete of large orphan sets
- force-replace history drops old loose objects

## Large-file handling (STEP ≥ 5 MB)

Files ≥ 5 MB (`LARGE_STEP_THRESHOLD = 5 * 1024 * 1024`) uploaded as
`kind='step-ref'` (migration 033):

- Binary stored as `blobs/step/<sha256>` in object storage
- DB row holds JSON pointer: `{"hash": "...", "size": N, "original_name": "...", "mime": "model/step"}`
- Download path (`api.py:1389–1402`) resolves pointer and streams from blob store

Upload chunk size: `upload_chunk_size` config (default 5 242 880 bytes).

## Paystack billing

`backend/cloud/billing/`:

- **webhooks** — `paystack.py` handles `charge.success`, credits prepaid balance
- **topup** — user-initiated ZAR → prepaid credit
- **balance** — real-time deduction on each tool call; USD→ZAR daily FX rate + spread

Settlement currency: ZAR. FX rates stored in `cloud_fx_rates`, refreshed daily.

## GitHub OAuth

`/auth/github/start` → redirect to GitHub  
`/auth/github/callback` → encrypts token via AES-GCM, upserts `cloud_github_tokens`  
`DELETE /auth/github` → revokes token (cloud routes only)

Migration 031: `backend/db/migrations/031_cloud_github_tokens.sql` creates
`cloud_github_tokens(user_id, access_token_encrypted, scope, github_user_id, github_login, updated_at)`.

## Workshop publishing

`POST /api/workshop/publish` (owner-only, idempotent) sets `visibility='public'`.
Triggers `cloud_email_log` entry for `workshop_published` email.

Unlike + fork + library submissions also flow through this surface.

## Build

```sh
npm run build          # OSS only
npm run build:cloud    # + Paystack + Workshop + git + billing UI
```

Frontend reads cloud flag from `/api/config` at runtime; backend reads
`KERF_CLOUD=1` / `cloud_enabled=true` from `.env`.

Full deploy / migrations / pricing: [docs/cloud-operator.md](./cloud-operator.md).
