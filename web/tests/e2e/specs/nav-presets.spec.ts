/**
 * nav-presets.spec.ts — the viewport navigation-style tab (bottom right).
 *
 * The presets follow FreeCAD's navigation styles, which are the de-facto
 * reference implementations of each vendor's scheme.
 *
 * What this suite covers
 * ----------------------
 * 1. The tab shows the active preset and lists all six styles.
 * 2. Switching preset actually changes what the mouse does — asserted by
 *    driving the mouse and diffing the rendered frame, not by reading state.
 *    Maya is the sharpest test: nothing navigates unless Alt is held, so a plain
 *    left-drag must leave the frame untouched while Alt+left-drag must orbit.
 * 3. The choice survives a reload (localStorage).
 *
 * Why a frame DIFF and not a centroid: orbiting rotates the camera around the
 * model's centre, so the object stays put on screen and its centroid barely
 * moves. The silhouette changes a lot though, so counting changed pixels is the
 * metric that actually distinguishes "the view moved" from "nothing happened".
 */

import { test, expect, Page } from '@playwright/test'
import { ProjectsPage } from '../pages/ProjectsPage'
import { EditorPage } from '../pages/EditorPage'
import { deleteProject, projectIdFromUrl } from '../utils/cleanup'

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

// Tracked at module scope so the setup helper below can record it and afterEach
// can delete it.
let createdProjectId: string | null = null
const registerProject = (id: string | null) => { createdProjectId = id }

const CUBE = `export default function ({ primitives }) {
  return [{ id: 'block', geom: primitives.cuboid({ size: [20, 20, 20] }) }]
}`

/** Grab the current frame as a plain array so we can diff two of them. */
async function frame(page: Page): Promise<number[]> {
  return await page.locator('canvas').first().evaluate(
    (el: HTMLCanvasElement) =>
      new Promise<number[]>((resolve) => {
        requestAnimationFrame(() => {
          const gl = (el.getContext('webgl2') ||
            el.getContext('webgl')) as WebGLRenderingContext | null
          if (!gl) return resolve([])
          const px = new Uint8Array(el.width * el.height * 4)
          gl.readPixels(0, 0, el.width, el.height, gl.RGBA, gl.UNSIGNED_BYTE, px)
          // Subsample: every 16th pixel is plenty to tell "moved" from "didn't",
          // and keeps the array small enough to cross the bridge quickly.
          const out: number[] = []
          for (let i = 0; i < px.length; i += 64) out.push(px[i], px[i + 1], px[i + 2])
          resolve(out)
        })
      }),
  )
}

/**
 * How much the view moved, as a percentage of the OBJECT — not of the frame.
 *
 * The renderer auto-frames the model, so a cube only ever covers ~3 % of the
 * canvas however big it is. Measured against the whole frame, even a full orbit
 * shifts under 1 % of pixels and the signal drowns. Normalising by the lit pixel
 * count makes "the view moved" unmistakable (tens of percent) and "nothing
 * happened" a clean zero.
 */
function movedPct(a: number[], b: number[]): number {
  if (!a.length || a.length !== b.length) return -1
  let changed = 0
  let lit = 0
  for (let i = 0; i < a.length; i++) {
    if (a[i] > 60) lit++
    if (Math.abs(a[i] - b[i]) > 20) changed++
  }
  return (100 * changed) / Math.max(1, lit)
}

async function leftDrag(page: Page, mods: string[] = []) {
  const box = (await page.locator('canvas').first().boundingBox())!
  const cx = box.x + box.width / 2
  const cy = box.y + box.height / 2
  for (const m of mods) await page.keyboard.down(m)
  await page.mouse.move(cx, cy)
  await page.mouse.down()
  await page.mouse.move(cx + 180, cy + 60, { steps: 14 })
  await page.mouse.up()
  for (const m of mods) await page.keyboard.up(m)
  await page.waitForTimeout(900) // let OrbitControls damping settle
}

async function projectWithCube(page: Page) {
  const pp = new ProjectsPage(page)
  await pp.goto()
  await page.waitForURL(/\/projects$/, { timeout: 20_000 })
  await pp.createProject(`e2e-nav-${uid()}`)
  await page.waitForURL(/\/projects\//, { timeout: 20_000 })
  registerProject(projectIdFromUrl(page))

  const ep = new EditorPage(page)
  await ep.waitForLoad()
  await ep.createFile('File')
  await expect(page.locator('.monaco-editor').first()).toBeVisible({ timeout: 20_000 })
  await ep.typeInMonaco(CUBE)

  await expect
    .poll(async () => (await frame(page)).filter((v) => v > 60).length, {
      timeout: 30_000,
      intervals: [500, 1_000, 2_000],
      message: 'cube never rendered',
    })
    .toBeGreaterThan(0)
}

test.describe('Viewport navigation presets (local mode)', () => {
  // Clean up after ourselves: leftover projects accumulate in the shared DB and
  // eventually break projects.spec's grid assertions (issue #5).
  test.afterEach(async ({ page }) => {
    await deleteProject(page, createdProjectId)
    createdProjectId = null
  })

  test.setTimeout(120_000)

  test('the tab lists all six styles and shows the active one', async ({ page }) => {
    await projectWithCube(page)

    const tab = page.getByTestId('nav-prefs-tab')
    await expect(tab).toBeVisible()
    await expect(tab).toContainText('Standard CAD')

    await tab.getByRole('button', { name: /Standard CAD/ }).click()
    const menu = page.getByRole('menu', { name: 'Navigation style' })
    for (const name of [
      'Standard CAD', 'Blender', 'Autodesk Maya', 'AutoCAD & Revit', 'SolidWorks', 'Touchpad',
    ]) {
      await expect(menu.getByRole('menuitemradio', { name: new RegExp(name, 'i') })).toBeVisible()
    }
  })

  test('switching to Maya gates navigation behind Alt, and persists', async ({ page }) => {
    await projectWithCube(page)
    const tab = page.getByTestId('nav-prefs-tab')

    // Standard: a plain left-drag orbits.
    const a1 = await frame(page)
    await leftDrag(page)
    const a2 = await frame(page)
    expect(movedPct(a1, a2), 'standard: plain left-drag should orbit').toBeGreaterThan(15)

    // Switch to Maya.
    await tab.getByRole('button', { name: /Standard CAD/ }).click()
    await page.getByRole('menuitemradio', { name: /Autodesk Maya/i }).click()
    await expect(tab).toContainText('Autodesk Maya')

    // Maya: a plain left-drag must do NOTHING (it is a pure select).
    const b1 = await frame(page)
    await leftDrag(page)
    const b2 = await frame(page)
    expect(movedPct(b1, b2), 'maya: plain left-drag must not navigate').toBeLessThan(2)

    // Maya: Alt + left-drag orbits.
    const c1 = await frame(page)
    await leftDrag(page, ['Alt'])
    const c2 = await frame(page)
    expect(movedPct(c1, c2), 'maya: alt+left-drag should orbit').toBeGreaterThan(15)

    // The choice survives a reload.
    await page.reload()
    await expect(page.getByTestId('nav-prefs-tab')).toContainText('Autodesk Maya', {
      timeout: 20_000,
    })
  })
})
