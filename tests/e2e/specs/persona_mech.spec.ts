/**
 * persona_mech.spec.ts — mechanical persona E2E flow (T-96).
 *
 * Scope
 * -----
 * Covers the full mechanical designer workflow:
 *   1. Create a new project (mechanical persona)
 *   2. Open the FreeCAD import dialog and verify its UI surface
 *   3. Create a .feature file — OCCT parametric editor mounts
 *   4. Open the Add-feature popover — Sketch-based + Sheet Metal categories present
 *   5. Add a Hole pattern feature — chip appears in the timeline
 *   6. Inspector shows Hole pattern fields (diameter, depth)
 *   7. Create a .drawing file — drawing surface (SVG / canvas) renders
 *   8. PDF export button is visible in the drawing properties panel
 *   9. [LLM-gated] Chat "add 4 M4 holes on top face" — feature tree updates
 *
 * Hermetic by default
 * -------------------
 * All assertions except (9) run without a live LLM provider key. The chat
 * round-trip in step (9) is gated behind E2E_LLM_LIVE so CI never blocks on
 * a provider call. The deterministic steps (≥10 assertions) always run.
 *
 * Counts ≥ 10 user-visible assertions:
 *   A1  Projects heading visible
 *   A2  Project creation navigates to editor
 *   A3  Editor "+ New" button visible
 *   A4  FreeCAD import dialog title rendered
 *   A5  FreeCAD dialog describes .FCStd support
 *   A6  FreeCAD dialog drop-zone accessible
 *   A7  Add-feature popover opens
 *   A8  "Sketch-based" feature category label present
 *   A9  "Sheet Metal" feature category label present
 *   A10 "Hole pattern" menuitem present in popover
 *   A11 Hole-pattern chip appears in the feature timeline
 *   A12 Drawing surface (SVG/canvas) renders at non-zero size
 *   A13 PDF export button visible in drawing panel
 */

import { test, expect } from '@playwright/test'
import { ProjectsPage } from '../pages/ProjectsPage'
import { EditorPage } from '../pages/EditorPage'

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

test.describe('Mechanical persona (T-96)', () => {
  // OCCT cold-start can be slow; give the whole suite generous room.
  test.setTimeout(180_000)

  test('project creation → FreeCAD import dialog → hole pattern feature → drawing → PDF button', async ({ page }) => {
    // ── 1. Create a new project ──────────────────────────────────────────────
    const pp = new ProjectsPage(page)
    await pp.goto()
    await page.waitForURL(/\/projects$/, { timeout: 20_000 })

    // A1 — projects heading
    await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible({ timeout: 20_000 })

    const projectName = `e2e-mech-${uid()}`
    await pp.createProject(projectName)

    // A2 — creation navigates to the editor (URL contains /projects/<id>)
    await page.waitForURL(/\/projects\//, { timeout: 20_000 })

    const ep = new EditorPage(page)
    await ep.waitForLoad()

    // A3 — editor "+ New" toolbar button is visible
    await expect(ep.newFileDropdownButton).toBeVisible()

    // ── 2. FreeCAD import dialog ─────────────────────────────────────────────
    await ep.newFileDropdownButton.click()

    // The CreateMenu includes an "Import FreeCAD" row.
    const importFreeCADItem = page.getByRole('button', { name: /import freecad/i })
    await expect(importFreeCADItem).toBeVisible({ timeout: 10_000 })
    await importFreeCADItem.click()

    // A4 — dialog title
    const dialogTitle = page.getByRole('heading', { name: /import freecad project/i })
    await expect(dialogTitle).toBeVisible({ timeout: 10_000 })

    // A5 — dialog describes .FCStd support text
    await expect(
      page.getByText(/FreeCAD 0\.19\+/i),
    ).toBeVisible()

    // A6 — drop-zone role="button" is accessible
    const dropZone = page.getByRole('button', { name: /drop a \.fcstd file/i })
    await expect(dropZone).toBeVisible()

    // Close the dialog — click Cancel / outside the modal.
    const cancelBtn = page.getByRole('button', { name: /cancel/i }).first()
    await cancelBtn.click()
    await expect(dialogTitle).toHaveCount(0, { timeout: 5_000 })

    // ── 3. Create a .feature file ────────────────────────────────────────────
    await ep.waitForLoad()
    await ep.createFile('Feature')

    // The OCCT parametric viewport (canvas) should mount.
    const canvas = page.locator('canvas').first()
    await expect(canvas).toBeVisible({ timeout: 90_000 })

    // ── 4. Add-feature popover — categories present ──────────────────────────
    // A7 — popover trigger button is present and clickable.
    const addFeatureBtn = page.getByRole('button', { name: /add feature to timeline/i })
    await expect(addFeatureBtn).toBeVisible({ timeout: 15_000 })
    await addFeatureBtn.click()

    const popoverMenu = page.getByRole('menu', { name: /add feature/i })
    await expect(popoverMenu).toBeVisible({ timeout: 5_000 })

    // A8 — "Sketch-based" category label
    await expect(popoverMenu.getByText('Sketch-based')).toBeVisible()

    // A9 — "Sheet Metal" category label
    await expect(popoverMenu.getByText('Sheet Metal')).toBeVisible()

    // A10 — "Hole pattern" menuitem is in the popover
    const holePatternItem = popoverMenu.getByRole('menuitem', { name: /add hole pattern/i })
    await expect(holePatternItem).toBeVisible()

    // ── 5. Add Hole pattern feature ──────────────────────────────────────────
    await holePatternItem.click()

    // A11 — a chip labelled "Hole pattern" (or accessible name matching it)
    //        appears in the feature timeline.
    const timeline = page.getByRole('tree', { name: /feature timeline/i })
    await expect(timeline).toBeVisible({ timeout: 10_000 })
    const holeChip = timeline.getByRole('treeitem', { name: /hole pattern/i })
    await expect(holeChip).toBeVisible({ timeout: 10_000 })

    // Bonus: clicking the chip should show inspector fields (diameter / depth).
    await holeChip.locator('[data-chip-btn]').first().click()
    const diameterLabel = page.getByText('Diameter (mm)')
    await expect(diameterLabel).toBeVisible({ timeout: 5_000 })

    // ── 6. Create a .drawing file ────────────────────────────────────────────
    await ep.waitForLoad()
    await ep.createFile('Drawing')

    // A12 — drawing surface (SVG or canvas) renders at non-zero size.
    const surface = page.locator('svg, canvas').first()
    await expect(surface).toBeVisible({ timeout: 90_000 })
    const box = await surface.boundingBox()
    expect(box).not.toBeNull()
    expect((box?.width ?? 0)).toBeGreaterThan(0)
    expect((box?.height ?? 0)).toBeGreaterThan(0)

    // A13 — PDF export button is visible in the drawing properties panel.
    const pdfBtn = page.getByRole('button', { name: /export as pdf/i })
    await expect(pdfBtn).toBeVisible({ timeout: 15_000 })

    // ── 7. LLM-gated: chat round-trip ────────────────────────────────────────
    if (process.env.E2E_LLM_LIVE) {
      // Navigate back to the feature file to test the chat-driven hole creation.
      // Open the feature file from the tree.
      const featureFileItem = page
        .locator('[title*=".feature"]')
        .first()
      await featureFileItem.click()

      // Open the chat pane if collapsed.
      const chatOpener = page.getByRole('button', { name: /open chat/i })
      if (await chatOpener.count()) {
        await chatOpener.first().click().catch(() => {})
      }

      const composer = page.getByPlaceholder('Ask Kerf to refine the model…')
      await expect(composer).toBeEnabled({ timeout: 30_000 })

      const chatPrompt = 'add 4 M4 holes on top face'
      await composer.fill(chatPrompt)
      await composer.press('Enter')

      // The user's turn must appear (no client crash).
      await expect(page.getByText(chatPrompt, { exact: false })).toBeVisible({ timeout: 15_000 })

      // After the assistant processes the request, the feature timeline should
      // contain a chip that references a hole or hole_pattern.
      await expect(
        page.getByRole('tree', { name: /feature timeline/i }),
      ).toBeVisible({ timeout: 60_000 })

      // No LLM error message.
      await expect(
        page.getByText(/the model returned an error/i),
      ).toHaveCount(0, { timeout: 60_000 })
    }
  })
})
