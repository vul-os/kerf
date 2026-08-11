/**
 * workshop.spec.ts — a published Part appears in the Workshop browse list.
 *
 * Runs under the `server-mode` Playwright project (LOCAL_MODE=false).
 *
 * Workshop is no longer a central, project-visibility-driven catalog — that
 * role moved to /library (GET /api/library/parts -> list_public_parts, see
 * library.spec.ts). Per decisions.md's 2026-07-17 "Final form" ADR and
 * docs/distributed-workshop.md, Workshop is now client-side state: the set
 * of author feeds ("follows") a node chooses to follow, crawled and rendered
 * as a derived index (GET /api/pub/workshop, kerf_pub.router_local). There
 * is no central Workshop server, so a merely-public project proves nothing
 * about Workshop — it has to be announced over DMTAP-PUB (POST
 * /api/pub/publish) and the node has to follow a feed that carries it.
 *
 * This test exercises that real flow: publish a Part from a project (signs
 * and appends to THIS node's own DMTAP-PUB feed, kerf_pub.identity — the
 * publishing identity is per-node, not per-user), then follow that same
 * node's own feed (gateway_url left blank — PubClient.resolve() checks the
 * local pub store before ever going over the network, so a self-follow
 * resolves entirely from local state already written by publish, no live
 * gateway required). GET /api/pub/workshop then derives a listing from that
 * follow, and the seeded part must render in the browser.
 */

import { test, expect, type APIRequestContext } from '@playwright/test'
import { E2E_NODE_PASSWORD } from '../node-credential'

const uniq = () => `${Date.now()}-${Math.floor(Math.random() * 1e4)}`

async function seedPublishedPart(req: APIRequestContext) {
  // Seeding used to register a throwaway account. There are no accounts: a
  // node has one password, and the setup project has already claimed this one.
  // That suits this spec — the publishing identity was always per-node rather
  // than per-user, so the author here was never really the account anyway.
  const session = await req.post('/api/setup/signin', {
    data: { password: E2E_NODE_PASSWORD },
  })
  expect(session.ok()).toBeTruthy()
  const { access_token, default_workspace } = await session.json()
  const auth = { Authorization: `Bearer ${access_token}` }

  const projectName = `e2e-ws-proj-${uniq()}`
  const pr = await req.post('/api/projects', {
    headers: auth,
    data: {
      workspace_id: default_workspace.id,
      name: projectName,
      starter: 'blank',
    },
  })
  expect(pr.ok()).toBeTruthy()
  const project = await pr.json()

  const fr = await req.post(`/api/projects/${project.id}/files`, {
    headers: auth,
    data: { name: 'widget.part', kind: 'part', content: '{}' },
  })
  expect(fr.ok()).toBeTruthy()

  // Announce the part over DMTAP-PUB — signs it under this node's own
  // publishing identity and appends it to that identity's feed
  // (kerf_pub.client.PubClient.publish). This is the actual act that makes
  // something show up in Workshop; project visibility is unrelated to it.
  const partName = `e2e-ws-part-${uniq()}`
  const pub = await req.post('/api/pub/publish', {
    headers: auth,
    data: {
      project_id: project.id,
      metadata: {
        name: partName,
        description: 'A widget published for the Workshop e2e test.',
        artifact_kind: 'part',
        license: 'MIT',
        units: { length_unit: 'mm' },
      },
    },
  })
  // Surface the status and body on failure. `expect(pub.ok()).toBeTruthy()`
  // alone reports "Received: false", which says nothing about WHY — this call
  // failed in CI while passing locally and the assertion gave nothing to work
  // from. A 404 means kerf-pub did not mount; a 500 means it mounted and threw.
  if (!pub.ok()) {
    throw new Error(
      `POST /api/pub/publish failed: ${pub.status()} ${pub.statusText()}\n` +
        `${await pub.text()}`,
    )
  }

  // The publishing identity is per-node (packages/kerf-pub/src/kerf_pub/identity.py
  // — one Ed25519 keypair on disk, not scoped to this user), so it already
  // exists after the publish call above.
  const idRes = await req.get('/api/pub/identity', { headers: auth })
  expect(idRes.ok()).toBeTruthy()
  const { pub: nodePub } = await idRes.json()
  expect(typeof nodePub).toBe('string')
  expect(nodePub.length).toBeGreaterThan(0)

  // Follow that same identity's feed. gateway_url is left blank on purpose:
  // PubClient.resolve() reads the local pub store before ever calling out
  // to a gateway (kerf_pub.client.PubClient.resolve), and the feed head +
  // announce this node just published are already in that same local store
  // — so a self-follow resolves fully offline.
  const followRes = await req.post('/api/pub/follows', {
    headers: auth,
    data: { pub: nodePub, label: 'This node', gateway_url: '' },
  })
  expect(followRes.ok()).toBeTruthy()

  return { partName }
}

test.describe('Workshop (server mode)', () => {
  test('published Part appears in Workshop after following the feed', async ({
    page,
  }) => {
    const { partName } = await seedPublishedPart(page.request)

    // Already signed in: the setup project claimed this node and saved the
    // session, so there is no sign-in step to drive here.
    await page.goto('/projects')
    await expect(
      page.getByRole('heading', { name: 'Projects' }),
    ).toBeVisible({ timeout: 20_000 })

    // Navigate to Workshop via the in-app link (client-side route) — a hard
    // page.goto('/workshop') races App.tsx's bootstrap gate: until
    // /api/config resolves, App renders null (see the `bootstrapping` guard),
    // so a fresh navigation can land on a blank frame instead of Workshop.
    await page.getByRole('link', { name: 'Workshop', exact: true }).first().click()

    // With a followed feed carrying a listing, Workshop renders past both
    // empty states (BrowseEmptyState never mounts), so the page heading is
    // once again the only element matching /workshop/i.
    await expect(
      page.getByRole('heading', { name: /workshop/i }),
    ).toBeVisible({ timeout: 15_000 })
    await expect(
      page.getByText(partName, { exact: false }).first(),
    ).toBeVisible({ timeout: 15_000 })
  })
})
