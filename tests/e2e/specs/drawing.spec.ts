/**
 * drawing.spec.ts — add a .drawing file with a view, assert SVG renders.
 *
 * Scaffolded — marked test.skip for future PRs.
 *
 * TODO
 * ----
 * 1. Create a project with a .jscad file that produces a mesh.
 * 2. Create a .drawing file via "+ New" → "Drawing".
 * 3. Add a standard view (front / top / isometric) via the DrawingToolbar.
 * 4. Wait for DrawingView.jsx to render an SVG projection.
 * 5. Assert that an <svg> element is present in the DOM and has non-zero
 *    width/height attributes (proxy for "projection succeeded").
 *
 * Blocker: Drawing projection calls the OCCT tessellation worker to project
 * edges. Same cold-start latency concern as feature.spec.ts. Needs a
 * pre-warmed worker or extended timeout.
 */

import { test } from '@playwright/test'

test.describe('Drawing creation (TechDraw)', () => {
  test.skip(true, 'scaffolded — implement in follow-up PR')

  test('add .drawing file — SVG projection renders', async ({ page }) => {
    // TODO: implement
    void page
  })
})
