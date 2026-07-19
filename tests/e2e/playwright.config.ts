/**
 * Playwright configuration for Kerf end-to-end tests.
 *
 * LOCAL MODE
 * ----------
 * The backend reads KERF_LOCAL_MODE=true and calls /auth/bootstrap-local on
 * startup, auto-minting a singleton user so tests never need a sign-in form.
 * The webServer stanza below wires this up automatically when you run
 * `npm test` from this directory.
 *
 * DEV USAGE (reuse an already-running server):
 *   VITE_API_URL=http://localhost:8080 npm run dev   # terminal 1
 *   npm test                                         # terminal 2 — reuseExistingServer=true skips boot
 *
 * CI (fresh server each run):
 *   DATABASE_URL=postgres://... KERF_LOCAL_MODE=true npm test
 *
 * Port layout (separate from the dev port so dev + test can coexist):
 *   :8081  — kerf-server (FastAPI)
 *   :5174  — Vite dev server (proxies /api + /auth to :8081)
 */

import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './specs',

  // Run tests serially — all share one DB instance; parallel writes would
  // require isolated schemas per worker which is overkill for v1.
  fullyParallel: false,
  workers: 1,

  retries: 0,

  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],

  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5174',
    headless: true,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',

    // Give slow WASM workers (OCCT, JSCAD) time to finish
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
  },

  // Two project profiles against two server stacks:
  //   local — LOCAL_MODE singleton auto-login (:5174 → :8081)
  //   cloud — LOCAL_MODE=false, real signup/login + Workshop/Library (:5175 → :8082)
  // Specs that need the public auth surface run under `cloud`; everything
  // else under `local`. "cloud" here just means "server mode" — Workshop
  // and Library are core MIT node capabilities present in both projects.
  projects: [
    {
      name: 'local',
      testIgnore: [
        '**/signup.spec.ts',
        '**/library.spec.ts',
        '**/workshop.spec.ts',
      ],
      use: { baseURL: 'http://localhost:5174' },
    },
    {
      name: 'cloud',
      testMatch: [
        '**/signup.spec.ts',
        '**/library.spec.ts',
        '**/workshop.spec.ts',
      ],
      use: { baseURL: 'http://localhost:5175' },
    },
  ],

  // webServer boots a throwaway Vite dev server + kerf-server. If you
  // already have servers running on these ports (local dev) Playwright will
  // reuse them instead of starting new ones (reuseExistingServer=true when
  // not in CI).
  //
  // Adjust the python command if your environment uses `python3` or a
  // virtualenv — `python -m kerf_core` is what `pip install -e .[full]`
  // makes available.
  webServer: [
    {
      // Backend: kerf-server on :8081
      // NOTE: kerf_core.config.Settings has no env prefix, so it reads the
      // UNPREFIXED names (LOCAL_MODE / DATABASE_URL / CORS_ORIGIN). The
      // KERF_* duplicates are kept for any deploy path that consumes them —
      // setting only KERF_DATABASE_URL would leave the server on its default
      // DSN.
      // CORS_ORIGIN is belt-and-braces: the browser now reaches the API
      // same-origin through the Vite proxy (see KERF_API_PROXY_TARGET below),
      // so preflight shouldn't arise, but a direct call would otherwise be
      // rejected against the default :5173 origin.
      command:
        'KERF_PORT=8081 KERF_LOCAL_MODE=true LOCAL_MODE=true ' +
        'CORS_ORIGIN=http://localhost:5174 ' +
        (process.env.DATABASE_URL
          ? `KERF_DATABASE_URL=${process.env.DATABASE_URL} ` +
            `DATABASE_URL=${process.env.DATABASE_URL} `
          : '') +
        'python -m kerf_core --port 8081',
      url: 'http://localhost:8081/health',
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // Frontend: Vite on :5174 (proxies /api + /auth to :8081)
      //
      // KERF_API_PROXY_TARGET, not VITE_API_URL: VITE_-prefixed vars are inlined
      // into the client bundle, so the browser would call http://localhost:8081
      // cross-origin and every fetch would be blocked by the index.html CSP
      // (connect-src 'self'), stranding all local specs on /login. Going through
      // the Vite proxy keeps requests same-origin.
      command:
        'KERF_API_PROXY_TARGET=http://localhost:8081 ' +
        'npx vite --port 5174 --host localhost',
      cwd: '../..',
      url: 'http://localhost:5174',
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // Cloud backend on :8082 — LOCAL_MODE=false, no local auto-login, so
      // the real /signup + /login surface exists. Workshop/Library are
      // unconditional node capabilities in every mode.
      command:
        'KERF_PORT=8082 KERF_LOCAL_MODE=false LOCAL_MODE=false ' +
        'CORS_ORIGIN=http://localhost:5175 ' +
        (process.env.DATABASE_URL
          ? `KERF_DATABASE_URL=${process.env.DATABASE_URL} ` +
            `DATABASE_URL=${process.env.DATABASE_URL} `
          : '') +
        'python -m kerf_core --port 8082',
      url: 'http://localhost:8082/health',
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // Cloud frontend: Vite on :5175 (proxies /api + /auth to :8082)
      // Same-origin proxy rather than VITE_API_URL — see the :5174 note above.
      command:
        'KERF_API_PROXY_TARGET=http://localhost:8082 ' +
        'npx vite --port 5175 --host localhost',
      cwd: '../..',
      url: 'http://localhost:5175',
      timeout: 60_000,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
