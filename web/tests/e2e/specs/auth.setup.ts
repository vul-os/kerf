/**
 * auth.setup.ts — claim the node and save a signed-in browser state.
 *
 * Kerf used to sign anyone in who could reach the port: in local mode the app
 * called /auth/bootstrap-local on load and got a full session with no
 * credential. Every spec relied on that, and none of them mentioned auth.
 *
 * There is a password now, set on first load, so the suite has to set one too.
 * Doing it here rather than in each spec keeps the change to one file: this
 * runs first (the other projects declare it as a dependency), claims the node,
 * signs in, and writes the browser state that every other project reuses.
 *
 * Claiming is idempotent from the suite's point of view — a 409 means a
 * previous run already claimed this database, and the password is the same
 * either way, so signing in still works.
 */
import { test as setup, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

/** Not a secret: these nodes are ephemeral, loopback-only and rebuilt per run. */
export const E2E_NODE_PASSWORD = 'e2e-node-passw0rd'

export function storageStatePath(project: string): string {
  // Beside the suite, not the cwd: playwright may be invoked from either the
  // repo root or tests/e2e, and a state file that lands in a different place
  // each time is a state file the projects cannot find.
  return path.join(__dirname, '..', '.auth', `${project}.json`)
}

setup('claim the node and sign in', async ({ page, request, baseURL }) => {
  // Both stacks share this file; the local project is the one that consumes
  // it, and the server-mode project keeps its own per-spec signups.
  const target = storageStatePath('local')
  fs.mkdirSync(path.dirname(target), { recursive: true })

  const claim = await request.post(`${baseURL}/api/setup/password`, {
    data: { password: E2E_NODE_PASSWORD },
  })
  // 201 = we claimed it. 409 = a previous run did, with the same password.
  expect([201, 409]).toContain(claim.status())

  const signin = await request.post(`${baseURL}/api/setup/signin`, {
    data: { password: E2E_NODE_PASSWORD },
  })
  expect(signin.ok()).toBeTruthy()
  const session = await signin.json()
  expect(session.access_token).toBeTruthy()

  // The app reads its session from localStorage under `kerf.auth` (zustand
  // persist). Seed it BEFORE any of the app's own scripts run: writing it
  // after a goto() looks like it works and does not — the store rehydrates
  // from an empty key, and the first state change persists its own nulls back
  // over the value that was just written.
  const persisted = JSON.stringify({
    state: {
      accessToken: session.access_token,
      refreshToken: session.refresh_token,
      user: session.user,
    },
    version: 0,
  })
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    ['kerf.auth', persisted],
  )

  await page.goto(`${baseURL}/projects`)
  // Signed in means the app rendered itself rather than the setup screen. If
  // this ever fails, every other spec would fail one assertion later and much
  // less legibly.
  await expect(page.getByRole('heading', { name: 'Unlock this Kerf' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()

  await page.context().storageState({ path: target })
})
