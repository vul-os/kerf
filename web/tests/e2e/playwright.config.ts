/**
 * Playwright configuration for Kerf end-to-end tests.
 *
 * WHAT THIS RUNS AGAINST
 * ----------------------
 * kerf-server, serving the BUILT frontend itself (KERF_FRONTEND_DIST ->
 * web/dist) — the same code path the desktop binary and the Docker image use.
 * There is no Vite dev server and no proxy: the browser talks to one origin,
 * which is what the app does in the field.
 *
 * That replaced two Vite dev servers. Every test opens a fresh browser
 * context, so each page load re-fetched the un-bundled module graph from the
 * dev server; serving the build removes that per-test cost.
 *
 * It also deletes a class of configuration hazard. The dev-server setup needed
 * a hand-maintained proxy list (/compile-ifc, /run-fem, /run-cam, …) because
 * plugin routes mount at the root, and anything missing from that list was
 * silently answered with index.html — which had already broken BIM/FEM/CAM/
 * topo/tess once. Serving from the API means there is no list to keep in sync,
 * and no VITE_API_URL/CSP interaction to get wrong.
 *
 * Because it serves a build, `npm run build` in web/ must have run first. The
 * check below says so plainly rather than letting 28 specs time out on a blank
 * page.
 *
 * DATABASE — embedded SQLite, not Postgres
 * ----------------------------------------
 * Postgres is optional in Kerf; the default install opens an embedded SQLite
 * file. Running E2E on SQLite makes this suite the coverage for the path most
 * users are actually on. That is not theoretical: moving it turned up three
 * Postgres-only defects that 500'd on a default install — the auth rate
 * limiter, the CAM tool DB, and every timestamptz column read back as text.
 * See decisions.md.
 *
 * Each project gets its own database file, so local mode's singleton user and
 * server mode's registered users never share a users table. global-setup.ts
 * creates and migrates them, so `npm test` needs no setup at all: no service
 * container, no DATABASE_URL, no migrate step.
 *
 * Set DATABASE_URL to a postgres:// DSN to run the same suite against Postgres
 * instead (both projects then share it, as they did before).
 *
 * Port layout (separate from dev :5173/:8080 so dev and test coexist):
 *   :8081  — kerf-server, local mode (auto-login singleton) + web/dist
 *   :8082  — kerf-server, server mode (real signup/login) + web/dist
 */

import { existsSync } from 'node:fs'
import path from 'node:path'

import { defineConfig } from '@playwright/test'

import { prepareDatabases } from './global-setup'

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..')
const DIST = path.join(REPO_ROOT, 'web', 'dist')

if (!existsSync(path.join(DIST, 'index.html'))) {
  throw new Error(
    `web/dist/index.html not found at ${DIST}.\n` +
      `The e2e suite serves the BUILT frontend from kerf-server, so build it first:\n` +
      `    cd web && npm run build\n`,
  )
}

/** Where global-setup.ts puts the SQLite files. Gitignored. */
export const DB_DIR = path.join(__dirname, '.tmp')

/**
 * One DSN per project unless DATABASE_URL pins an external database, in which
 * case both share it (the historic Postgres behaviour).
 */
export const LOCAL_DB =
  process.env.DATABASE_URL || `sqlite://${path.join(DB_DIR, 'e2e-local.db')}`
export const SERVER_DB =
  process.env.DATABASE_URL || `sqlite://${path.join(DB_DIR, 'e2e-server.db')}`

// Here, at module scope, NOT in a `globalSetup` hook: Playwright starts the
// webServer processes before globalSetup runs, so a hook would migrate a
// database the servers had already opened. They booted against an empty file
// and logged `no such table: distributor_credentials` while initialising, then
// worked anyway because the query layer opens connections per request — the
// kind of quiet, boot-time-only breakage worth being deliberate about.
//
// Guarded to the main process: Playwright re-evaluates this config in every
// worker, and re-running the prepare there would clear the auth rate-limit
// buckets in the middle of a run — quietly resetting a limit the server-mode
// specs are exercising. TEST_WORKER_INDEX is set only in workers.
if (process.env.TEST_WORKER_INDEX === undefined) {
  prepareDatabases(DB_DIR, [LOCAL_DB, SERVER_DB])
}

/** One kerf-server, serving the API and the built SPA from a single origin. */
function kerfServer(port: number, localMode: boolean, db: string) {
  return {
    // kerf_core.config.Settings has NO env prefix, so it reads the unprefixed
    // names (LOCAL_MODE / DATABASE_URL / PORT). The KERF_* duplicates are kept
    // for deploy paths that consume those instead — setting only
    // KERF_DATABASE_URL would leave the server on its default DSN.
    command:
      `KERF_PORT=${port} ` +
      `KERF_LOCAL_MODE=${localMode} LOCAL_MODE=${localMode} ` +
      // Any plugin that fails to register fails the boot — see the note in app.py.
      `KERF_STRICT_PLUGINS=true ` +
      `KERF_FRONTEND_DIST=${DIST} ` +
      `KERF_DATABASE_URL=${db} DATABASE_URL=${db} ` +
      `python -m kerf_core --port ${port}`,
    url: `http://localhost:${port}/health`,
    // Plugin registration walks every installed kerf-* package; on a cold CI
    // runner that is slower than a warm laptop.
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    stdout: 'pipe' as const,
    stderr: 'pipe' as const,
  }
}

export default defineConfig({
  testDir: './specs',

  // No globalSetup: database preparation happens at module scope above,
  // because that hook runs after the webServers have already started.

  // Spec FILES run in parallel; tests within a file stay serial, because
  // several build on state an earlier test in the same file created. Files are
  // safe to overlap: each names its fixtures with a uid and asserts on exact
  // names, so concurrent files never observe each other's rows.
  fullyParallel: false,
  // Two, not more: the heavy specs render three.js through headless Chromium's
  // software rasteriser, so workers compete for the same CPU rather than
  // overlapping I/O. On a 4-vCPU runner, more workers buys nothing and starts
  // costing timeouts in exactly the WebGL specs this suite is here to protect.
  workers: process.env.CI ? 2 : undefined,

  retries: 0,

  // Per-test budget. Playwright's default is 30s — which was never consistent
  // with this suite's own step budgets: `actionTimeout` below is 30s, and
  // individual assertions ask for 20-30s, so ONE step was permitted to consume
  // the entire test. The heavy specs do several such steps in a row (create a
  // project, load the editor, type into Monaco, wait for autosave, boot a WASM
  // worker, render), and they legitimately total more than 30s.
  //
  // This is what made bim.spec look flaky for weeks: it takes ~29-33s end to
  // end, so it passed or failed on machine noise rather than on anything in the
  // code. Raising the total does not hide slowness — every individual step is
  // still bounded, and a genuine hang still fails, just at 120s instead of 30s.
  timeout: 120_000,

  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],

  use: {
    headless: true,
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',

    // Give slow WASM workers (web-ifc, JSCAD, planegcs) time to finish.
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
  },

  // Two project profiles against two server stacks:
  //   local        — LOCAL_MODE singleton auto-login (:8081)
  //   server-mode  — LOCAL_MODE=false, real signup/login + Workshop/Library (:8082)
  // Specs that need the public auth surface run under `server-mode`; everything
  // else under `local`. Workshop and Library are core MIT node capabilities
  // present in both projects.
  projects: [
    {
      name: 'local',
      testIgnore: [
        '**/signup.spec.ts',
        '**/library.spec.ts',
        '**/workshop.spec.ts',
      ],
      use: { baseURL: process.env.E2E_BASE_URL || 'http://localhost:8081' },
    },
    {
      name: 'server-mode',
      testMatch: [
        '**/signup.spec.ts',
        '**/library.spec.ts',
        '**/workshop.spec.ts',
      ],
      use: { baseURL: process.env.E2E_SERVER_BASE_URL || 'http://localhost:8082' },
    },
  ],

  webServer: [
    kerfServer(8081, true, LOCAL_DB),
    kerfServer(8082, false, SERVER_DB),
  ],
})
