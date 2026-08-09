/**
 * global-setup.ts — clear auth rate-limit buckets before a run.
 *
 * WHY
 * ---
 * /auth/register is rate limited to 5 per hour per IP (kerf_auth/routes.py). That is a real
 * brute-force control and is deliberately NOT made configurable — a "disable rate limiting"
 * env var is exactly the kind of knob that ends up set in production.
 *
 * But the cloud specs register a fresh user per test, so the fourth consecutive local run
 * inside an hour starts getting 429s and the cloud project fails wholesale, with symptoms
 * that look nothing like rate limiting: instant sub-200ms failures on tests that never
 * mention auth. CI never hit this because its database is new every run; a developer
 * re-running the suite locally hits it immediately.
 *
 * Clearing the bucket table here keeps the limiter fully intact in the application and
 * makes the suite repeatable against a long-lived local database.
 *
 * Best-effort by design: if DATABASE_URL is unset (embedded SQLite) or python cannot be
 * reached, the run continues — this must never be the reason a suite fails to start.
 */

import { spawnSync } from 'node:child_process'

const PY = `
import os, sys
url = os.environ.get("DATABASE_URL", "")
if not url.startswith(("postgres://", "postgresql://")):
    sys.exit(0)
try:
    # asyncpg, not psycopg — it is what kerf-core already depends on, so it is present
    # wherever the server can run and this needs no extra install in CI or locally.
    import asyncio, asyncpg

    async def clear() -> None:
        conn = await asyncpg.connect(url.replace("postgres://", "postgresql://"), timeout=5)
        try:
            await conn.execute("DELETE FROM rate_limit_buckets")
        finally:
            await conn.close()

    asyncio.run(clear())
    print("e2e: cleared rate_limit_buckets")
except Exception as exc:
    print(f"e2e: could not clear rate limits ({exc}) - continuing")
`

export default function globalSetup(): void {
  const res = spawnSync('python', ['-c', PY], {
    encoding: 'utf8',
    env: process.env,
    timeout: 20_000,
  })
  const out = (res.stdout || '').trim()
  if (out) console.log(out)
}
