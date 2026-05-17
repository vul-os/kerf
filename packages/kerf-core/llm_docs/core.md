# kerf-core — meta-plugin contract + application factory

`kerf-core` is the structural foundation of Kerf. It owns:

- **`create_app()`** — the single FastAPI application factory
- **Plugin contract** — `PluginContext`, `PluginManifest`, `ToolRegistry`, `WorkerRegistry`
- **Storage abstraction** — `StorageBackend` ABC + `local`, `s3`, `git_storer` implementations
- **DB layer** — asyncpg pool, migration runner, per-table query modules
- **Config** — pydantic-settings `Config` (alias: `Settings`) read from env / `.env`
- **Utilities** — topological sort, project context, field encryption

---

## Boot sequence (`kerf_core.app.create_app`)

```
create_app(config?)
  1. Config.load()          — env vars + .env → Config
  2. _configure_logging()   — structlog JSON/console
  3. FastAPI(..., lifespan)
     lifespan:
       4. asyncpg pool open (create_pool_from_config)
       5. StorageBackend wired (storage.factory.create_storage)
       6. ToolRegistry + WorkerRegistry created
       7. importlib.metadata.entry_points("kerf.plugins") → discover all plugins
       8. topo_sort(plugins, depends) → ordered list
       9. for each plugin: await register(app, PluginContext)
      10. WorkerRegistry.start_all()
      11. _mount_frontend()  — SPA catch-all LAST (after all /api/* routes)
  /health           GET  → {status, version}
  /healthz          GET  → {status, version}
  /health/capabilities GET → {plugins, capabilities}
```

The topo-sort ensures a plugin that lists `depends=["kerf-auth"]` always loads after `kerf-auth`. Plugins that fail to load are logged but do not crash the server.

---

## Plugin contract

Every plugin package exposes a single async entry-point registered under the `kerf.plugins` entry-points group (pyproject.toml `[project.entry-points."kerf.plugins"]`).

```python
# kerf_myplugin/plugin.py
PLUGIN_DEPENDS = ["kerf-auth"]          # optional module-level list

async def register(app: FastAPI, ctx: PluginContext) -> PluginManifest:
    app.include_router(my_router, prefix="/api")
    ctx.tools.register("my_tool", my_tool_spec, my_tool_handler)
    ctx.workers.register("my_worker", my_worker_factory)
    return PluginManifest(
        name="my-plugin",
        version="0.1.0",
        provides=["my.capability"],
        depends=["kerf-auth"],
    )
```

### PluginContext fields

| field | type | description |
|---|---|---|
| `pool` | `asyncpg.Pool` | Shared DB pool (may be `None` if DB unavailable) |
| `storage` | `StorageBackend` | Active storage backend |
| `config` | `Config` | Loaded settings |
| `tools` | `ToolRegistry` | Mutable LLM tool registry |
| `workers` | `WorkerRegistry` | Mutable background-worker registry |
| `logger` | `structlog.BoundLogger` | Plugin-scoped logger |
| `cloud_enabled` | `bool` | Whether cloud mode is active |
| `local_mode` | `bool` | Whether running as single-user local install |

### ToolRegistry

```python
ctx.tools.register(name: str, spec: ToolSpec, handler: ToolHandler)
ctx.tools.get(name)         → (spec, handler) | None
ctx.tools.all_specs()       → list[ToolSpec]
ctx.tools.all_names()       → list[str]
```

`ToolSpec` carries `name`, `description`, and `parameters` (JSON Schema dict).
`ToolHandler` is `async (ctx, args) → Any`.

Duplicate tool names raise `ValueError` at registration time — use `logger.debug` to skip duplicates gracefully.

### WorkerRegistry

```python
ctx.workers.register(name: str, factory: async () → worker)
ctx.workers.start_all()     → list[worker handles]
```

Factories are called once at startup. Workers typically subclass `kerf_workers.base.BaseWorker`.

---

## Config (`kerf_core.config.Config`)

All settings are read from environment variables (prefix-free) or a `.env` file at the package root. Key fields:

```
DATABASE_URL          postgres://…
JWT_SECRET            string
STORAGE_BACKEND       "local" | "s3"
LOCAL_STORAGE_PATH    ./kerf-storage (default)
S3_BUCKET / S3_REGION / S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY
S3_ENDPOINT           custom endpoint (Tigris, MinIO, …)
CLOUD_ENABLED         false (OSS) | true (cloud deploy)
LOCAL_MODE            true (single user) | false (cloud)
PYWORKER_URL          http://localhost:8090
DEFAULT_MODEL         claude-opus-4-7
ANTHROPIC_PROMPT_CACHE  true (default)
```

`KERF_STORAGE_S3_*` aliases map Fly/Tigris-provisioned secrets onto the canonical `S3_*` names automatically.

`Config.load(config_path="")` returns a cached `Settings` instance. `get_settings()` is the lru-cached singleton getter used throughout.

---

## Storage abstraction

```
StorageBackend (ABC)
  put(key, body, content_type, size)  → PutResult
  get(key)                            → (IO[bytes], content_type)
  delete(key)
  signed_url(key, ttl_seconds)        → str
  public_url(key, updated_at?)        → str
  put_chunk / list_chunks / concat_chunks_to / delete_upload
```

Implementations:
- `local.LocalStorage` — on-disk directory, used in development / single-user installs
- `s3.S3Storage` — boto3 S3-compatible, used in cloud deploy (Tigris or AWS)
- `git_storer.S3GitStorer` — bulk sync of bare git repos to S3 for the cloud Git backend (see below)

### S3GitStorer

Drives cloud Git: syncs an entire bare git repository between S3 and a local temp directory.

```python
storer = S3GitStorer.from_s3storage(s3storage, repo_prefix="git/<project_id>")
storer.clone_to_local(local_dir)   # S3 → local bare repo
storer.push_from_local(local_dir)  # local bare repo → S3 (objects first, refs last)
```

Optimistic concurrency uses a sentinel object `_marker` whose ETag must match `If-Match` on write. A concurrent pusher that loses the race receives `StorerConcurrencyError` and must retry.

The `push_from_local` flow:
1. `git gc --aggressive` (best-effort repack)
2. Upload pack files → loose objects → ref files (ordered to keep readers consistent)
3. Conditional PUT of the marker
4. Batch-delete orphaned S3 keys

---

## DB migrations

Migrations live in `kerf_core/db/migrations/` as numbered SQL files (`001_init.sql` … `033_*`). The runner applies them in order at startup, tracking applied migrations in a `schema_migrations` table.

Key tables introduced by core migrations:
- `users`, `workspaces`, `workspace_members`, `projects`, `project_members`
- `files`, `file_revisions` (soft-delete + gzip-compressed diffs)
- `api_tokens`, `refresh_tokens`
- `usage_events`, `upload_sessions`, `derived_artifacts`
- `step_tessellation_jobs`, `fem_jobs`, `cam_jobs`, `sim_jobs`
- `cloud_user_balances`, `cloud_github_tokens`
- `model_prices` (pricing), `workshop_likes`

---

## Utilities

- `kerf_core.utils.topo_sort.topo_sort(nodes, edges)` — Kahn's algorithm used for plugin ordering
- `kerf_core.utils.context.ProjectCtx` — per-request context threaded into tool handlers (pool, project_id, user_id, storage, file_revisions_max)
- `kerf_core.utils.encrypt.encrypt_secret / decrypt_secret` — AES-GCM field encryption for stored credentials
- `kerf_core.revisions` — write_revision helper (base vs diff, gzip, cap enforcement)
- `kerf_core.dependencies.require_auth / optional_auth` — FastAPI dependency that validates JWT or opaque API token
