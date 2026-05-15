/**
 * Page-object model for /projects/:projectId (the Editor view).
 *
 * The editor has three main panels:
 *   - File tree (left sidebar)  — FileTree.jsx
 *   - Editor/viewer (center)    — varies by file kind
 *   - Inspector (right sidebar) — FeatureInspector, chat, etc.
 *
 * Selectors are intentionally coarse (text / title) to survive minor
 * class-name refactors. Data-testid attributes are added where needed; for
 * now we use accessible names and visible text.
 */

import { Page, Locator, expect } from '@playwright/test'

export class EditorPage {
  readonly page: Page

  // File tree
  readonly fileTreePanel: Locator
  readonly newFileDropdownButton: Locator

  constructor(page: Page) {
    this.page = page

    this.fileTreePanel = page.locator('.bg-ink-900').first()
    // The "+ New" dropdown button in the FileTree header
    this.newFileDropdownButton = page.getByTitle(
      'Create a new file or folder, or import a STEP file',
    )
  }

  /** Wait for the editor page to be fully loaded (file tree visible). */
  async waitForLoad() {
    await expect(this.newFileDropdownButton).toBeVisible({ timeout: 20_000 })
  }

  /**
   * Open the "+ New" dropdown and click a specific kind label.
   * @param kind  The label shown in the dropdown, e.g. 'Sketch', 'File', 'Drawing'
   */
  async createFile(kind: 'File' | 'Sketch' | 'Drawing' | 'Feature' | 'Assembly' | 'Part') {
    await this.newFileDropdownButton.click()
    // The dropdown renders CreateRow elements with the kind label as visible text
    await this.page
      .locator('span')
      .filter({ hasText: kind })
      .first()
      .click()
  }

  /**
   * Click a file in the file tree by its displayed name.
   */
  async openFile(name: string) {
    await this.page.getByText(name, { exact: true }).first().click()
  }

  /**
   * Wait for the Monaco editor to appear and type code into it.
   * Replaces all existing content.
   */
  async typeInMonaco(code: string) {
    const editor = this.page.locator('.monaco-editor textarea').first()
    await editor.waitFor({ state: 'visible', timeout: 15_000 })
    // Select all + replace
    await editor.press('ControlOrMeta+a')
    await editor.type(code)
  }

  /**
   * Wait for the Three.js canvas (used by the JSCAD renderer) to appear
   * and contain non-trivial pixel data.
   *
   * The canvas is injected by Renderer.jsx into a container div. We check
   * that at least one pixel in the canvas is non-black as a proxy for
   * "the render produced something".
   */
  async expectCanvasRendered(timeout = 30_000) {
    const canvas = this.page.locator('canvas').first()
    await expect(canvas).toBeVisible({ timeout })

    // Poll until a non-trivial render appears (canvas has at least one
    // non-black pixel). Playwright's evaluateHandle lets us inspect pixel data.
    await expect
      .poll(
        async () => {
          return await canvas.evaluate((el: HTMLCanvasElement) => {
            const ctx = el.getContext('2d')
            if (!ctx) return false
            const { data } = ctx.getImageData(0, 0, el.width, el.height)
            // Check if any pixel's RGB channels are non-zero
            for (let i = 0; i < data.length; i += 4) {
              if (data[i] !== 0 || data[i + 1] !== 0 || data[i + 2] !== 0) {
                return true
              }
            }
            return false
          })
        },
        { timeout, intervals: [1_000] },
      )
      .toBe(true)
  }

  /**
   * In the sketch canvas, draw a rectangle using pointer events.
   * Assumes the sketch view is already showing (after opening a .sketch file).
   * This is a simplified interaction — real constrained drawing would need
   * the correct tool to be active first.
   *
   * For v1 tests we verify persistence of a sketch file, not pixel-perfect
   * geometry. The sketch save happens automatically on every edit.
   */
  async drawRectangleInSketch() {
    const canvas = this.page.locator('canvas').first()
    await expect(canvas).toBeVisible({ timeout: 15_000 })

    const box = await canvas.boundingBox()
    if (!box) throw new Error('canvas has no bounding box')

    const cx = box.x + box.width / 2
    const cy = box.y + box.height / 2
    const half = Math.min(box.width, box.height) * 0.15

    // Simulate a rectangle by clicking 4 corners + double-click to close.
    // The sketch tool accepts clicks as polygon points; a second click near
    // the start closes the loop.
    await this.page.mouse.click(cx - half, cy - half)
    await this.page.mouse.click(cx + half, cy - half)
    await this.page.mouse.click(cx + half, cy + half)
    await this.page.mouse.click(cx - half, cy + half)
    await this.page.mouse.dblclick(cx - half, cy - half)
  }
}
