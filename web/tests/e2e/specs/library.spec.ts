/**
 * library.spec.ts — browse the Library catalog and open a Library Part.
 *
 * Runs under the `server-mode` Playwright project (LOCAL_MODE=false). The Library
 * catalog (GET /api/library/parts → list_public_parts) lists files of
 * kind='part' from projects with visibility='public' — no verified-publisher
 * requirement for the default (non-verified-only) listing. We seed that
 * state via the API, then browse + open the part in the browser.
 *
 * "server mode" now means only LOCAL_MODE=false — the way in is the node
 * password either way.
 */

import { test, expect, type APIRequestContext } from '@playwright/test'
import { E2E_NODE_PASSWORD } from '../node-credential'

const uniq = () => `${Date.now()}-${Math.floor(Math.random() * 1e4)}`

async function seedLibraryPart(req: APIRequestContext) {
  // Seeding used to register a throwaway account. There are no accounts: a
  // node has one password, and the setup project has already claimed this one,
  // so signing in with it is how anything gets a token here.
  const session = await req.post('/api/setup/signin', {
    data: { password: E2E_NODE_PASSWORD },
  })
  expect(session.ok()).toBeTruthy()
  const { access_token, default_workspace } = await session.json()
  const auth = { Authorization: `Bearer ${access_token}` }

  const pr = await req.post('/api/projects', {
    headers: auth,
    data: {
      workspace_id: default_workspace.id,
      name: `e2e-lib-proj-${uniq()}`,
      starter: 'blank',
    },
  })
  expect(pr.ok()).toBeTruthy()
  const project = await pr.json()

  const partName = `e2e-libpart-${uniq()}`
  const fr = await req.post(`/api/projects/${project.id}/files`, {
    headers: auth,
    data: { name: partName, kind: 'part', content: '{}' },
  })
  expect(fr.ok()).toBeTruthy()

  const up = await req.patch(`/api/projects/${project.id}`, {
    headers: auth,
    data: { visibility: 'public' },
  })
  expect(up.ok()).toBeTruthy()

  return { partName }
}

test.describe('Library browse + open (server mode)', () => {
  test('open Library Part from the catalog', async ({ page }) => {
    const { partName } = await seedLibraryPart(page.request)

    // Already signed in: the setup project claimed this node and saved the
    // session, so there is no sign-in step to drive here.
    await page.goto('/projects')
    await expect(
      page.getByRole('heading', { name: 'Projects' }),
    ).toBeVisible({ timeout: 20_000 })

    // Navigate to Library via the in-app link (client-side route — a hard
    // page.goto races useNodeConfig and the catch-all bounces it away).
    await page.getByRole('link', { name: 'Library', exact: true }).first().click()
    await expect(
      page.getByRole('heading', { name: 'Library', exact: true }).first(),
    ).toBeVisible({ timeout: 15_000 })

    // The seeded part appears in the catalog.
    const card = page.getByText(partName, { exact: false }).first()
    await expect(card).toBeVisible({ timeout: 15_000 })

    // Opening it navigates to the part detail (/library/:slug or
    // /workshop/:slug) and shows the part name as the page heading.
    await card.click()
    await expect(
      page.getByRole('heading', { name: new RegExp(partName) }).first(),
    ).toBeVisible({ timeout: 15_000 })
  })
})
