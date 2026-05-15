/**
 * workshop.spec.ts — publish a project, assert it appears in the Workshop.
 *
 * Scaffolded — marked test.skip for future PRs.
 *
 * TODO
 * ----
 * 1. Enable KERF_CLOUD_MODE + KERF_WORKSHOP_ENABLED in the test server.
 * 2. Create a project, set visibility to "public", trigger Workshop publish.
 * 3. Navigate to /workshop and assert the project card is visible.
 * 4. Click the listing, assert the detail page shows the correct title.
 *
 * Blocker: Workshop routes are guarded by `cloudEnabled` in App.jsx.
 * The e2e server needs `KERF_CLOUD_ENABLED=true` and a minimal cloud plugin
 * stack loaded. Wire this in a follow-up once the cloud e2e env is ready.
 */

import { test } from '@playwright/test'

test.describe('Workshop (cloud mode)', () => {
  test.skip(true, 'scaffolded — implement in follow-up PR')

  test('publish project — appears in Workshop listing', async ({ page }) => {
    // TODO: implement
    void page
  })
})
