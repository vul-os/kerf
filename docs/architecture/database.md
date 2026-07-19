# Database architecture: embedded SQLite by default, Postgres for scale

kerf runs on one of two database backends, chosen purely by the `DATABASE_URL`
scheme:

| `DATABASE_URL`            | Backend                | When                                            |
|---------------------------|------------------------|-------------------------------------------------|
| *(unset)*                 | Embedded **SQLite** at `~/.kerf/kerf.db` | The default — a local, single-user install. Zero dependencies. |
| `sqlite:///path/to.db`    | Embedded **SQLite** at that path         | Explicit local file / tests.                    |
| `postgres://…`            | **PostgreSQL** (asyncpg)                  | Teams / always-on / multi-node — the scale backend. |

The switch is a single config line. Everything above the pool — the API, the
frontend, every plugin, every `db/queries/*` module — is backend-agnostic and
unchanged.

## Why this design

The prior default required a running Postgres before kerf would boot. For a
local-first CAD tool that is the single biggest install-friction point. Making
SQLite the default removes it: `curl`-install the binary, run it, and it creates
its own database file.

The honest question was *how much parity* is achievable. kerf's query layer is
written against asyncpg: **282 Postgres-ism callsites** across `db/queries/`
(`$N` placeholders, `RETURNING`, `ON CONFLICT`, `jsonb`, `= ANY(array)`,
`now()`, `::casts`, `FOR UPDATE SKIP LOCKED`). Rewriting all of it to a
lowest-common-denominator SQL, or introducing an ORM, would be a large, risky
change touching every feature.

The chosen architecture is a **thin dialect adapter at the connection/pool
layer** plus a **checked-in SQLite migration set** — not a rewrite:

* **`db/dialect.py`** — a runtime *query* translator (Postgres SQL → SQLite SQL)
  and parameter/row adapter.
* **`db/sqlite_backend.py`** — `SqlitePool` / `SqliteConnection` classes that
  mirror the asyncpg pool/connection surface (`fetch` / `fetchrow` / `fetchval`
  / `execute` / `executemany` / `transaction()` / `acquire()`) on top of
  [`aiosqlite`](https://pypi.org/project/aiosqlite/). Every query module keeps
  calling exactly the methods it always did.
* **`db/connection.py`** — branches on the URL scheme to build the right pool.
  The asyncpg path is byte-for-byte the historical behaviour.
* **`db/migrations_sqlite/`** — a SQLite variant of the baseline migrations,
  generated once (offline) by `scripts/gen_sqlite_migrations.py` and checked in.
  DDL is **not** translated at runtime.

SQLite ≥ 3.35 (2021) supports `RETURNING` and upsert (`ON CONFLICT … DO
UPDATE`) natively, which is what makes this adapter approach viable without
touching the queries.

## Dialect translation

### Query-level (runtime, `db/dialect.py`)

Applied on every query as it passes through the adapter:

| Postgres                              | SQLite                                                        | Notes |
|---------------------------------------|--------------------------------------------------------------|-------|
| `$1`, `$2`, … placeholders            | `?` (re-bound in order of appearance)                        | Handles reuse and out-of-order `$N` by duplicating params. |
| `expr::jsonb->>'k'` / `expr->>'k'`    | `json_extract(expr, '$.k')`                                   | SQLite JSON1. |
| `$1 = ANY(col)`                       | `EXISTS (SELECT 1 FROM json_each(col) WHERE value = ?)`       | Arrays are stored as JSON text. |
| `::type` casts (`::uuid`, `::jsonb`…) | removed                                                       | SQLite is dynamically typed; `'{}'::jsonb` → `'{}'`. |
| `gen_random_uuid()`                   | pure-SQLite UUIDv4 expression (`randomblob`-based)           | Rare in queries; mainly a column default (see DDL). |
| `now()` / `current_timestamp`         | `CURRENT_TIMESTAMP`                                           | |
| `FOR UPDATE SKIP LOCKED` / `FOR UPDATE` | removed                                                    | Single-writer embedded mode; the enclosing transaction suffices. |
| `ILIKE`                               | `LIKE`                                                        | SQLite `LIKE` is ASCII-case-insensitive. |

**Parameter adaptation:** `uuid.UUID` → `str`; `list`/`dict` (arrays, jsonb) →
JSON `str`; `datetime` → `'YYYY-MM-DD HH:MM:SS.ffffff'` in UTC (matching
`CURRENT_TIMESTAMP` ordering); `bytes` → BLOB.

**Row adaptation:** rows are returned as a `dict` subclass (`Record`) so
`dict(row)`, `row["col"]`, and `.keys()` all work like asyncpg's `Record`. The
known Postgres `ARRAY` columns (`tags`, `tooth_ids`, `received_chunks`) are
parsed from JSON text back into Python lists on read — asyncpg returns those as
lists, so this preserves parity. (`jsonb` columns are **not** parsed: asyncpg
returns *those* as JSON strings too, and the query layer `json.loads()` them
itself, so leaving them as text keeps both backends identical.)

**`execute()` command tags:** asyncpg returns `"UPDATE 1"` / `"DELETE 1"` /
`"INSERT 0 1"` and several callsites compare against those exact strings, so the
adapter synthesises them from the SQL verb and `cursor.rowcount`.

### Schema-level (offline, `scripts/gen_sqlite_migrations.py`)

Run once whenever a Postgres migration changes; output is checked in:

| Postgres DDL                    | SQLite DDL                                             |
|---------------------------------|-------------------------------------------------------|
| `create extension …`            | dropped                                               |
| `gen_random_uuid()` default     | pure-SQLite UUIDv4 expression                         |
| `uuid`                          | `text`                                                |
| `citext`                        | `text collate nocase`                                 |
| `jsonb`                         | `text`                                                |
| `timestamptz` / `timestamp`     | `text` (ISO-8601 / `CURRENT_TIMESTAMP`)               |
| `bytea`                         | `blob`                                                |
| `<type>[]` (arrays)             | `text` (JSON); array default `'{}'` → `'[]'`          |
| `serial` / `bigserial`         | `integer`                                             |
| `now()`                         | `CURRENT_TIMESTAMP`                                   |
| `now() + interval 'N unit'`     | `(datetime('now','+N unit'))`                         |
| `… using gin/gist (…)` indexes  | dropped (no JSON/array index in SQLite)               |
| checks, inline FKs, partial `where` indexes, composite PKs | passed through unchanged (already valid SQLite) |

## What runs on SQLite vs what is Postgres-only

**Runs on SQLite (the core serving path):** project CRUD, files + revisions,
auth (users, refresh tokens, email tokens), workspaces + members, share links,
Workshop public listing / likes / follows / pins, library + BOM, blob ledger,
usage telemetry, cloud-git-local metadata, the kerf-pub store (chunks /
manifests / feed / watermark / availability), and the async job tables
(FEM / CAM / SPICE / tessellation / render / firmware) — the last running in a
**single-writer** mode.

**Degrades gracefully on SQLite (Postgres-only for full behaviour):**

* **Multi-worker job-queue fan-out** — `FOR UPDATE SKIP LOCKED` is stripped, so
  concurrent workers can't atomically claim distinct queued rows. Fine for one
  local worker; a busy multi-worker pool needs Postgres.
* **`LISTEN` / `NOTIFY` instant wakeups** (kerf-tess) — `add_listener` is a
  no-op on SQLite; workers fall back to their existing polling loop.
* **Horizontal multi-node scale** — a single SQLite file is one machine.

On startup with the SQLite backend, kerf logs a one-line `db_backend_sqlite`
notice naming exactly these degradations and pointing at
`DATABASE_URL=postgres://…` for the scale backend.

## Files

* `packages/kerf-core/src/kerf_core/db/dialect.py` — query/param/row translation
* `packages/kerf-core/src/kerf_core/db/sqlite_backend.py` — `SqlitePool` / `SqliteConnection`
* `packages/kerf-core/src/kerf_core/db/connection.py` — scheme-based pool selection
* `packages/kerf-core/src/kerf_core/db/config.py` — `default_database_url()` (the SQLite default)
* `packages/kerf-core/src/kerf_core/db/migrations/runner.py` — SQLite + Postgres appliers
* `packages/kerf-core/src/kerf_core/db/migrations_sqlite/` — checked-in SQLite DDL
* `scripts/gen_sqlite_migrations.py` — the offline DDL generator

## Tests

* `packages/kerf-core/tests/test_sqlite_backend.py` — dialect unit tests + core-path integration on a real SQLite DB (project CRUD, files/revisions, auth, public-listing joins, transactions, status strings, `ON CONFLICT`).
* `packages/kerf-pub/tests/test_sqlite_pub_store.py` — the kerf-pub store over `SqlitePool`.

The existing Postgres suites are unchanged and still run against Postgres.
