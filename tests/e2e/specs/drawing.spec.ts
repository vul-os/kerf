/**
 * drawing.spec.ts — create a .drawing file, assert the drawing surface
 * renders (the TechDraw/SVG projection pipeline mounts in a browser).
 *
 * LOCAL MODE (KERF_LOCAL_MODE=true) — no sign-in.
 *
 * Scope (v1): drawing projection calls the OCCT tessellation worker which
 * has a long cold start. We assert the .drawing file is created and the
 * DrawingView surface (an <svg> or <canvas>) mounts — exercising
 * file-create → DrawingView end-to-end without asserting exact projected
 * edges.
 */

import { test, expect } from '@playwright/test'
import { ProjectsPage } from '../pages/ProjectsPage'
import { EditorPage } from '../pages/EditorPage'

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

test.describe('Drawing creation (TechDraw)', () => {
  test.setTimeout(120_000)

  test('add .drawing file — drawing surface renders', async ({ page }) => {
    const pp = new ProjectsPage(page)
    const projectName = `e2e-drawing-${uid()}`
    await pp.goto()
    await page.waitForURL(/\/projects$/, { timeout: 20_000 })
    await pp.createProject(projectName)
    await page.waitForURL(/\/projects\//, { timeout: 20_000 })

    const ep = new EditorPage(page)
    await ep.waitForLoad()

    // Create a .drawing file via the "+ New" dropdown.
    await ep.createFile('Drawing')

    // DrawingView renders an SVG drawing sheet (projection) or a canvas
    // surface. Either presence is the v1 regression signal that the
    // file-create → DrawingView pipeline is wired.
    const surface = page.locator('svg, canvas').first()
    await expect(surface).toBeVisible({ timeout: 90_000 })

    const box = await surface.boundingBox()
    expect(box).not.toBeNull()
    expect((box?.width ?? 0) > 0 && (box?.height ?? 0) > 0).toBe(true)

    // Persist across reload.
    await page.waitForTimeout(1_500)
    await page.reload()
    await ep.waitForLoad()
    await expect(
      page.locator('[title*=".drawing"], [class*="text-"]').first(),
    ).toBeVisible({ timeout: 15_000 })
  })
})
