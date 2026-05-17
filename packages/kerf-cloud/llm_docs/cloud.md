# kerf-cloud — cloud plugin: GitHub repo-connect, share links, job traveler, distributor integrations

`kerf-cloud` is a cloud-gated plugin. When `CLOUD_ENABLED=false` (local install or OSS self-host) its `register()` function returns an empty manifest and mounts nothing. All code paths are therefore unreachable in the OSS build.

Depends on `kerf-auth` and `kerf-api`.

---

## Plugin registration

```python
PLUGIN_DEPENDS = ["kerf-auth", "kerf-api"]

async def register(app, ctx) -> PluginManifest:
    if not ctx.cloud_enabled:
        return PluginManifest(name="kerf-cloud", provides=[], ...)

    app.include_router(router, prefix="/api")            # git + share routes
    app.include_router(github_oauth_router, prefix="/auth")
    await _init_distributor_registry(ctx)                # cloud-only
    return PluginManifest(
        name="kerf-cloud",
        provides=["cloud.workshop", "cloud.git", "cloud.distributors"],
        ...
    )
```

---

## GitHub repo-connect / repo-sync

`kerf-cloud` enables projects to be connected to GitHub repositories so that commits in Kerf are pushed upstream and GitHub pushes can be pulled into Kerf.

### Routes (`/api/projects/{id}/git/…`)

| Method | Path | Description |
|---|---|---|
| POST | `/api/projects/{id}/git/init` | Initialise a bare git repo for the project (S3-backed via `S3GitStorer`) |
| POST | `/api/projects/{id}/git/import` | Import from a GitHub URL (clone → store in S3) |
| POST | `/api/projects/{id}/git/connect` | Connect to an existing GitHub repo (owner/repo) |
| POST | `/api/projects/{id}/git/commit` | Commit current project state to the git backend |
| POST | `/api/projects/{id}/git/push` | Push local git state to GitHub (requires installation token) |
| POST | `/api/projects/{id}/git/pull` | Pull from GitHub into the project |
| POST | `/api/projects/{id}/git/branch` | Create a new branch |
| POST | `/api/projects/{id}/git/checkout` | Switch branch |
| POST | `/api/projects/{id}/git/merge` | Merge one branch into another |
| GET | `/api/projects/{id}/git/log` | Commit history |
| GET | `/api/projects/{id}/git/status` | Working tree status |
| GET | `/api/projects/{id}/git/diff` | Diff between two refs |
| GET | `/api/projects/{id}/git/branches` | List branches |

### GitHub App flow (`/auth/github/…`)

The GitHub App integration is the preferred path for repo-sync because it uses installation tokens rather than requiring users to store a personal access token.

| Method | Path | Description |
|---|---|---|
| GET | `/auth/github/app/install` | Redirect to the GitHub App installation page |
| GET | `/auth/github/app/callback` | Handle post-installation callback, store `installation_id` |

The `github_app` module provides:
- `app_jwt(app_id, private_key_pem)` — 9-minute RS256 JWT for authenticating as the App
- `installation_token(installation_id, app_id, pem)` — short-lived token (in-memory cached, refreshed 5 min before expiry)
- `install_url(app_slug, state)` — GitHub App installation redirect URL

Private key is stored as base64 in `CLOUD_GITHUB_PRIVATE_KEY_B64` and never logged.

### Git storage architecture

The git backend uses `S3GitStorer` from `kerf_core.storage.git_storer`:

1. Each project has a bare git repo at `<S3_PREFIX>/git/<project_id>/`
2. To work with the repo: `clone_to_local(tmp_dir)` → modify → `push_from_local(tmp_dir)`
3. Objects upload in order: pack files → loose objects → refs (reader-safe ordering)
4. Optimistic concurrency via a sentinel `_marker` S3 object; concurrent pushers receive `StorerConcurrencyError`

This model was chosen to support large STEP / binary CAD file workflows without per-object overhead.

---

## Share links (`kerf_cloud.share_link`)

Share links let designers share a design revision with a customer for review and approval. They do not require the customer to have a Kerf account.

### API

```python
token = create_share(project_id, revision_id, ttl_days=30,
                     allow_comments=True, allow_approve=True)
info  = resolve_share(token)   # None if invalid/expired/revoked
ok    = add_comment(token, customer_name, body)
ok    = record_approval(token, customer_name, signature)
ok    = revoke_share(token)
```

Tokens are `<16-char-urlsafe>.<8-char-HMAC>` — the HMAC check digit prevents enumeration attacks. Records are stored as JSON files under `data/cloud/share/` (overridable via `KERF_SHARE_DIR`). No DB dependency.

LLM tools registered: `share.create`, `share.resolve`, `share.add_comment`, `share.record_approval`, `share.revoke`.

---

## Job Traveler (`kerf_cloud.job_traveler`)

A production-ops layer for tracking a design from order through manufacture to delivery. Suited to jewelry workshops and small-batch manufacturing. No DB dependency — persisted as JSON files under `data/cloud/jobs/`.

### Data model

- **PurchaseOrder** — customer + line items (part_ref, qty, unit_price, lead_time); status: `draft → issued → received → closed`
- **JobTraveler** — links a PO + project/revision; tracks progress through `STAGE_ORDER = ["design", "cast", "clean", "set", "polish", "qc"]`
- **InventoryItem** — on_hand, allocated, reorder_point per SKU

### Key operations

```python
create_po(customer, items)           → {ok, po}
issue_po(po_id)                      → {ok, po}
receive_po(po_id, received_items)    → {ok, po, inventory_updates}
start_traveler(po, project, revision, due_date) → {ok, traveler}
advance_stage(traveler_id, stage, assignee)     → {ok, traveler, next_stage}
close_traveler(traveler_id, qc_pass=True)       → {ok, traveler}
allocation_check(items)              → {ok, checks, shortfalls}
inventory_pick_list(bom)             → {ok, can_fill, needs_order, summary}
```

LLM tools registered: `job_create_po`, `job_inventory_pick_list`.

---

## Distributor integrations (`kerf_cloud.distributors`)

Cloud-only registry that proxies part searches to electronics/hardware distributors. Credentials are AES-GCM encrypted at rest in the `distributor_credentials` DB table.

Enabled distributors: DigiKey, Mouser, LCSC, McMaster-Carr. The registry loads at startup via `Registry.reload()` and is refreshed on a background sweep.

```python
# kerf_cloud/plugin.py  (_init_distributor_registry)
reg = Registry(pool, cfg, fx=None)
await reg.reload()
ctx.workers.register("distributors.sweep", sweep_factory)
```

The sweep worker periodically calls `reload()` to pick up new credentials without a restart.

---

## Email (`kerf_cloud.email`)

Transactional email via a pluggable provider abstraction. See `packages/kerf-cloud/llm_docs/email_providers.md` for the provider-level docs.

Provider is selected by `EMAIL_PROVIDER` config: `smtp` (default), `resend`, `ses`.

---

## Cloud beta mode

When `CLOUD_BETA=true`, billing routes respond with 503 (payments disabled) while all other features remain active. The frontend greys out payment controls. This is a temporary launch gate; the beta block in `plugin.py` is marked for removal post-launch.

---

## Security notes

- GitHub App private key is never logged; decoded from base64 env var at runtime only
- Installation tokens are cached in-memory only; never written to DB
- Share link records are HMAC-signed; brute-force enumeration requires 2^64 guesses
- Distributor credentials are AES-GCM encrypted at rest
- Public docs for this package deliberately omit vendor-specific service names
