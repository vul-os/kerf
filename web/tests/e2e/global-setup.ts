/**
 * global-setup.ts — prepare the databases the suite runs against.
 *
 * NOT registered as Playwright's `globalSetup`, deliberately. Playwright starts
 * the `webServer` processes BEFORE the globalSetup hook runs, so a hook here
 * migrates a database the servers have already opened: they booted against an
 * empty file and logged `no such table: distributor_credentials` while
 * initialising, then worked anyway because the query layer opens connections
 * per request. Only boot-time initialisation was the casualty, which is exactly
 * the kind of thing that fails quietly.
 *
 * So playwright.config.ts calls `prepareDatabases()` at module scope instead,
 * which runs before Playwright starts anything at all.
 *
 * Two jobs:
 *
 * 1. CREATE AND MIGRATE. On the embedded SQLite backend (the default — see
 *    playwright.config.ts) the database is a file this suite owns, so it makes
 *    one here. That is what lets `npm test` work from a clean checkout with no
 *    service container, no DATABASE_URL and no separate migrate step. When
 *    DATABASE_URL names Postgres, migrating is the caller's job and only the
 *    bucket clear below runs.
 *
 * 2. CLEAR AUTH RATE-LIMIT BUCKETS. /auth/register is limited to 5 per hour per
 *    IP (kerf_auth/routes.py). That is a real brute-force control and is
 *    deliberately NOT made configurable — a "disable rate limiting" env var is
 *    exactly the kind of knob that ends up set in production. But the
 *    server-mode specs register a fresh user per test, so re-running the suite
 *    inside an hour starts getting 429s, with symptoms that look nothing like
 *    rate limiting: instant sub-200ms failures on tests that never mention
 *    auth. Clearing the bucket table here leaves the limiter fully intact in
 *    the application and makes the suite repeatable.
 *
 *    This used to run for Postgres only, so it quietly did nothing once the
 *    suite moved to SQLite — which is exactly when it began to matter, because
 *    a SQLite file survives between runs while a CI Postgres container does not.
 */

import { spawnSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'

const PY = `
import asyncio, sys

urls = [u for u in sys.argv[1:] if u]

async def prepare(url: str) -> None:
    from kerf_core.db.dialect import is_sqlite_url
    if is_sqlite_url(url):
        from kerf_core.db.migrations.runner import run_sqlite_migrations
        from kerf_core.db.sqlite_backend import create_sqlite_pool
        await run_sqlite_migrations(url)
        pool = await create_sqlite_pool(url, max_size=1)
        try:
            await pool.execute("DELETE FROM rate_limit_buckets")
        finally:
            await pool.close()
    else:
        # asyncpg, not psycopg — it is what kerf-core already depends on, so it
        # is present wherever the server can run and needs no extra install.
        import asyncpg
        conn = await asyncpg.connect(url.replace("postgres://", "postgresql://"), timeout=5)
        try:
            await conn.execute("DELETE FROM rate_limit_buckets")
        finally:
            await conn.close()

async def main() -> None:
    for url in dict.fromkeys(urls):   # de-dupe: one shared DSN is one prepare
        await prepare(url)

asyncio.run(main())
print("e2e: databases ready, rate-limit buckets cleared")
`

/**
 * Migrate the suite's databases and clear rate-limit buckets. Synchronous on
 * purpose: it is called from config module scope, where nothing can await.
 */
export function prepareDatabases(dbDir: string, urls: string[]): void {
  mkdirSync(dbDir, { recursive: true })

  const res = spawnSync('python', ['-c', PY, ...urls], {
    encoding: 'utf8',
    env: process.env,
    timeout: 120_000,
  })

  const out = [res.stdout, res.stderr].filter(Boolean).join('').trim()
  if (res.status !== 0) {
    // Do not limp on: the servers would boot against an empty database, every
    // spec would fail on a missing table, and the real cause would be buried 28
    // failures deep.
    throw new Error(
      `e2e setup could not prepare the database (exit ${res.status}).\n` +
        `Is kerf-core importable by the \`python\` on PATH? (./scripts/dev-install.sh full)\n\n` +
        out,
    )
  }
  if (out) console.log(out)
}
