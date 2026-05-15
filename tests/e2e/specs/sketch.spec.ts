/**
 * sketch.spec.ts — add a .sketch file, interact with the canvas, reload to
 * verify persistence.
 *
 * LOCAL MODE: no sign-in required (KERF_LOCAL_MODE=true).
 *
 * What this suite covers
 * ----------------------
 * 1. Create a project and open the editor
 * 2. Create a .sketch file via the "+ New" dropdown → "Sketch"
 * 3. The sketch canvas becomes visible
 * 4. Draw a basic shape using pointer events on the canvas
 * 5. Reload the page — the sketch file still exists in the file tree
 *    (persistence check: the file was saved to the backend)
 *
 * Limitations (v1)
 * ----------------
 * The sketch tool uses planegcs under the hood; a full constraint-solving
 * assertion would require knowing the internal JSON schema. We scope this
 * spec to the simpler invariant: "a .sketch file survives a page reload".
 * The visual draw step exercises the pointer-event path so the spec isn't
 * entirely trivial, but we don't assert the exact geometry.
 */

import { test, expect } from '@playwright/test'
import { ProjectsPage } from '../pages/ProjectsPage'
import { EditorPage } from '../pages/EditorPage'

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

test.describe('Sketch editor (local mode)', () => {
  test('add .sketch file — canvas visible + file persists on reload', async ({ page }) => {
    // 1. Create a project
    const pp = new ProjectsPage(page)
    const projectName = `e2e-sketch-${uid()}`
    await pp.goto()
    await page.waitForURL(/\/projects$/, { timeout: 20_000 })
    await pp.createProject(projectName)
    await page.waitForURL(/\/projects\//, { timeout: 20_000 })

    // We are now on the editor page
    const editorUrl = page.url()
    const ep = new EditorPage(page)
    await ep.waitForLoad()

    // 2. Create a .sketch file
    await ep.createFile('Sketch')

    // 3. The sketch canvas should appear. Sketch files open in SketchView.jsx
    //    which renders an HTML5 canvas directly (not Three.js).
    const canvas = page.locator('canvas').first()
    await expect(canvas).toBeVisible({ timeout: 20_000 })

    // 4. Draw something — enough to confirm pointer events reach the canvas.
    //    We don't assert specific geometry.
    await ep.drawRectangleInSketch()

    // Give the auto-save a moment to fire (it debounces on content change)
    await page.waitForTimeout(1_500)

    // 5. Reload and verify the sketch file is still listed in the file tree.
    await page.reload()
    await ep.waitForLoad()

    // The file tree should contain at least one item with ".sketch" in its name.
    // The exact name comes from the backend (e.g. "sketch1.sketch").
    await expect(
      page.locator('[class*="text-amber"], [title*=".sketch"]').first(),
    ).toBeVisible({ timeout: 15_000 })
  })
})
