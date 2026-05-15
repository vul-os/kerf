/**
 * feature.spec.ts — Feature timeline: add a .feature file, add a Pad node,
 * assert OCCT worker produces a mesh.
 *
 * Scaffolded — marked test.skip for future PRs.
 *
 * TODO
 * ----
 * 1. Create a project + a .sketch file with a closed loop.
 * 2. Create a .feature file and link it to the sketch.
 * 3. Click "Pad" in the FeatureView toolbar (FeatureInspector.jsx).
 * 4. Wait for the OCCT worker to post back a mesh message.
 * 5. Assert the Three.js canvas has rendered geometry (same pixel check as
 *    jscad.spec.ts).
 *
 * Blocker: the OCCT worker (opencascade.js, ~15 MB gzipped) takes 20–60 s
 * to load on cold CI. We need to either pre-warm or increase the test
 * timeout to ~90 s before this can run reliably in CI.
 */

import { test } from '@playwright/test'

test.describe('Feature timeline (OCCT)', () => {
  test.skip(true, 'scaffolded — implement in follow-up PR')

  test('add Pad node — OCCT worker produces mesh', async ({ page }) => {
    // TODO: implement
    void page
  })
})
