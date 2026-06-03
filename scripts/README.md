# scripts/

Helper scripts for local development, seeding, testing, and deployment.

---

## Local development

### `./scripts/dev.sh` — one-command local dev loop

Starts the full Kerf stack locally in **LOCAL_MODE** (no signup needed — auto-login as the local user).

```bash
./scripts/dev.sh
```

What it does, in order:

1. Verifies Postgres is running; starts it via `brew services start postgresql@16` (macOS) or `pg_ctl start` (Linux) if not.
2. Ensures the `kerf` database exists (creates it via `createdb -U pc kerf` if missing). Uses the `pc` role per project convention.
3. Runs pending migrations via `python3 -m kerf_core.db.migrations.runner`.
4. Builds the static config + docs manifest (`init-config.mjs`, `build-docs-manifest.mjs`).
5. Starts the backend on **:8080** in the background (`python3 -m kerf_core --port 8080 --reload`).
6. Starts the Vite frontend on **:5173** in the foreground.
7. On Ctrl-C: kills the backend and exits cleanly.

**Override the database URL:**

```bash
DATABASE_URL=postgres://other@host/mydb ./scripts/dev.sh
```

**Ports:**

| Service | URL |
|---------|-----|
| API     | http://localhost:8080 |
| Web     | http://localhost:5173 |

---

### `./scripts/seed-dev.sh` — seed realistic dev data

Populates the local database with four example projects (idempotent — safe to re-run):

```bash
./scripts/seed-dev.sh
```

| Project name               | Type        | Contents |
|----------------------------|-------------|----------|
| `_seed_BIM Example`        | BIM         | 4 walls + floor slab + flat roof + stair |
| `_seed_Mechanical Part`    | Mechanical  | Mounting bracket: extrude + boss + holes + fillet + chamfer |
| `_seed_PCB Example`        | Electronics | 3 components: R1 (330R) + C1 (100nF) + D1 (LED) |
| `_seed_Component Library`  | Library/BOM | 10 parts with distributor pricing (Digi-Key, Mouser, RS) |

All seed projects use the prefix `_seed_` so they are easy to identify and clean up.

Seeds are **idempotent**: if a project with the same name already exists in the seed workspace, it is skipped.

---

## Running the seed tests

```bash
pytest scripts/test_seed_data.py -v
```

Tests run against an in-memory SQLite database — no real Postgres required. They verify:
- 4 projects are created
- BIM project has ≥ 6 files
- Mechanical part has exactly 5 features
- PCB circuit has 3 components (R1, C1, D1)
- Library has exactly 10 parts
- Re-running the seed is idempotent (no duplicates)

---

## Other scripts

| Script | Purpose |
|--------|---------|
| `dev-cloud.sh` | Like `dev.sh` but in **CLOUD_MODE** (requires account signup at `/signup`) |
| `deploy-fly.sh` | Deploy to Fly.io (production or dev environment) |
| `loop_local.sh` | Drop + recreate schema, migrate, seed, run full test suite |
| `test_all.sh` | Run full test harness |
| `install.sh` | One-line installer for end users |
| `bump-version.sh` | Bump the project version |
