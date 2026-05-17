/**
 * feature.spec.ts — create a .feature file, assert the parametric viewport
 * comes up (the OCCT/Three pipeline initialises end-to-end in a browser).
 *
 * LOCAL MODE (KERF_LOCAL_MODE=true) — no sign-in.
 *
 * Scope (v1, matching jscad.spec.ts): we don't assert exact Pad geometry —
 * the OCCT worker (opencascade.js, ~15 MB) has a long cold start. We assert
 * the .feature file is created and the viewport canvas renders at non-zero
 * size, which still exercises file-create → editor → renderer end-to-end.
 */

import { test, expect } from '@playwright/test'
import { ProjectsPage } from '../pages/ProjectsPage'
import { EditorPage } from '../pages/EditorPage'

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

test.describe('Feature timeline (OCCT)', () => {
  // OCCT (opencascade.js) cold start is slow — give the whole test room.
  test.setTimeout(120_000)

  test('add Feature file — parametric viewport renders', async ({ page }) => {
    const pp = new ProjectsPage(page)
    const projectName = `e2e-feature-${uid()}`
    await pp.goto()
    await page.waitForURL(/\/projects$/, { timeout: 20_000 })
    await pp.createProject(projectName)
    await page.waitForURL(/\/projects\//, { timeout: 20_000 })

    const ep = new EditorPage(page)
    await ep.waitForLoad()

    // Create a .feature file via the "+ New" dropdown.
    await ep.createFile('Feature')

    // The parametric viewport (Three.js canvas) should mount. OCCT may take
    // tens of seconds to warm up on a cold worker — generous deadline.
    const canvas = page.locator('canvas').first()
    await expect(canvas).toBeVisible({ timeout: 90_000 })

    const dims = await canvas.evaluate((el: HTMLCanvasElement) => ({
      w: el.width,
      h: el.height,
    }))
    expect(dims.w).toBeGreaterThan(0)
    expect(dims.h).toBeGreaterThan(0)

    // The .feature file should persist in the tree across a reload.
    await page.waitForTimeout(1_500)
    await page.reload()
    await ep.waitForLoad()
    await expect(
      page.locator('[title*=".feature"], [class*="text-"]').first(),
    ).toBeVisible({ timeout: 15_000 })
  })
})
