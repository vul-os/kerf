/**
 * library.spec.ts — browse a Library Part, fork it into a project.
 *
 * Scaffolded — marked test.skip for future PRs.
 *
 * TODO
 * ----
 * 1. Seed a Library Part via the API (publisher token required).
 * 2. Navigate to /library/:slug.
 * 3. Click "Fork" and assert the project appears in /projects.
 *
 * Blocker: Library routes require cloudEnabled + a seeded publisher + part
 * record. Needs a cloud-mode e2e environment.
 */

import { test } from '@playwright/test'

test.describe('Library browse + fork (cloud mode)', () => {
  test.skip(true, 'scaffolded — implement in follow-up PR')

  test('open Library Part and fork into project', async ({ page }) => {
    // TODO: implement
    void page
  })
})
