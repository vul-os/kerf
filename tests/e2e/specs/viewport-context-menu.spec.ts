/**
 * viewport-context-menu.spec.ts — right-click an object in the 3D viewport.
 *
 * LOCAL MODE: no sign-in required (KERF_LOCAL_MODE=true).
 *
 * What this suite covers
 * ----------------------
 * 1. Right-clicking a solid opens the object menu, targeting the object under
 *    the cursor.
 * 2. Colour: picking a swatch actually repaints that object (read back off the
 *    live WebGL buffer, not just asserted on the DOM) and persists as a
 *    `// kerf:appearance=` marker in the file source.
 * 3. Hide: the object disappears from the canvas.
 * 4. Right-DRAG still pans the camera and must NOT open the menu — OrbitControls
 *    binds RIGHT to PAN, and the menu only fires when the press didn't move.
 *    This is the regression that would most annoy a CAD user, so it is asserted
 *    explicitly.
 *
 * Pixel checks read gl.readPixels inside a requestAnimationFrame callback, so we
 * sample the frame BIMView/Renderer just drew (the drawing buffer is cleared once
 * the frame composites). We classify by brightness: the scene background is
 * near-black, lit geometry is far above it.
 */

import { test, expect, Page } from '@playwright/test'
import { ProjectsPage } from '../pages/ProjectsPage'
import { EditorPage } from '../pages/EditorPage'

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

// One cube, id 'block' — a single object keeps "what is under the cursor"
// unambiguous (the default camera sits on the +X+Y+Z diagonal, so objects
// separated along X project on top of each other).
const CUBE = `export default function ({ primitives }) {
  return [{ id: 'block', geom: primitives.cuboid({ size: [20, 20, 20] }) }]
}`

/** Average colour of the lit (non-background) pixels, plus how much is lit. */
async function litStats(page: Page) {
  return await page.locator('canvas').first().evaluate(
    (el: HTMLCanvasElement) =>
      new Promise<{ rgb: number[] | null; litPct: number }>((resolve) => {
        requestAnimationFrame(() => {
          const gl = (el.getContext('webgl2') ||
            el.getContext('webgl')) as WebGLRenderingContext | null
          if (!gl || !el.width || !el.height) return resolve({ rgb: null, litPct: 0 })
          const { width: w, height: h } = el
          const px = new Uint8Array(w * h * 4)
          gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px)
          let n = 0, r = 0, g = 0, b = 0
          for (let i = 0; i < px.length; i += 4) {
            if (px[i] + px[i + 1] + px[i + 2] > 150) {
              n++; r += px[i]; g += px[i + 1]; b += px[i + 2]
            }
          }
          resolve({
            rgb: n ? [Math.round(r / n), Math.round(g / n), Math.round(b / n)] : null,
            litPct: (100 * n) / (w * h),
          })
        })
      }),
  )
}

async function openMenuOnObject(page: Page) {
  const canvas = page.locator('canvas').first()
  const box = await canvas.boundingBox()
  if (!box) throw new Error('canvas has no bounding box')
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2, { button: 'right' })
  const menu = page.getByTestId('viewport-context-menu')
  await expect(menu).toBeVisible({ timeout: 10_000 })
  return menu
}

/** Create a project + a .jscad file holding a single cube, and wait for the render. */
async function projectWithCube(page: Page) {
  const pp = new ProjectsPage(page)
  await pp.goto()
  await page.waitForURL(/\/projects$/, { timeout: 20_000 })
  await pp.createProject(`e2e-ctxmenu-${uid()}`)
  await page.waitForURL(/\/projects\//, { timeout: 20_000 })

  const ep = new EditorPage(page)
  await ep.waitForLoad()
  await ep.createFile('File')
  await expect(page.locator('.monaco-editor').first()).toBeVisible({ timeout: 20_000 })
  await ep.typeInMonaco(CUBE)

  // Poll until the cube is actually on screen — the JSCAD worker boot dominates.
  await expect
    .poll(async () => (await litStats(page)).litPct, {
      timeout: 30_000,
      intervals: [500, 1_000, 2_000],
      message: 'cube never rendered',
    })
    .toBeGreaterThan(0.5)
}

test.describe('Viewport object context menu (local mode)', () => {
  // Each test creates a project, boots the JSCAD worker, and then polls the
  // WebGL buffer through several appearance changes — comfortably past the 30 s
  // default on a cold CI runner.
  test.setTimeout(90_000)

  test('right-click a solid — recolour, persist to source, and hide', async ({ page }) => {
    await projectWithCube(page)

    const before = await litStats(page)
    // The default palette colour for the first part is 0xc9a96b — warm/tan, so
    // red > blue. Guards against the assertion below passing on a grey cube.
    expect(before.rgb![0]).toBeGreaterThan(before.rgb![2])

    const menu = await openMenuOnObject(page)
    await expect(menu).toContainText('block')

    // --- Colour ---
    await menu.getByRole('menuitem', { name: /Colour/i }).hover()
    await page.getByRole('button', { name: 'Colour #d94f4f' }).click()

    await expect
      .poll(async () => {
        const s = await litStats(page)
        // #d94f4f is strongly red-dominant; the tan default is not.
        return s.rgb ? s.rgb[0] - s.rgb[1] : 0
      }, { timeout: 15_000, intervals: [500, 1_000], message: 'cube never turned red' })
      .toBeGreaterThan(60)

    // --- Persisted into the source, not just the scene ---
    await expect(page.locator('.monaco-editor .view-lines').first()).toContainText(
      'kerf:appearance',
      { timeout: 10_000 },
    )
    await expect(page.locator('.monaco-editor .view-lines').first()).toContainText('#d94f4f')

    // --- Hide ---
    const menu2 = await openMenuOnObject(page)
    // exact: "Hide" is also a substring of Isolate's accessible name
    // ("Isolate hide others"), which is a strict-mode violation without it.
    await menu2.getByRole('menuitem', { name: 'Hide', exact: true }).click()
    await expect
      .poll(async () => (await litStats(page)).litPct, {
        timeout: 15_000,
        intervals: [500, 1_000],
        message: 'object did not disappear after Hide',
      })
      .toBeLessThan(0.1)
  })

  // Platform-ordering guard. `contextmenu` fires on mouse DOWN on Linux/GTK but
  // on mouse UP on Windows — i.e. AFTER the pointerup we open the menu on. A
  // dismiss-on-contextmenu listener therefore closed the menu in the very
  // gesture that opened it on Windows, while looking fine on Linux (it read as
  // "the viewport flickers and no menu ever appears"). Headless Linux can't
  // reproduce the native ordering, so we assert the invariant directly: a
  // contextmenu event arriving after the menu is open must not dismiss it.
  test('menu survives a contextmenu event delivered after it opens (Windows ordering)', async ({
    page,
  }) => {
    await projectWithCube(page)
    const menu = await openMenuOnObject(page)

    await page.locator('canvas').first().dispatchEvent('contextmenu')
    await page.waitForTimeout(300)

    await expect(menu).toBeVisible()
  })

  test('right-DRAG still pans the camera and opens no menu', async ({ page }) => {
    await projectWithCube(page)

    const canvas = page.locator('canvas').first()
    const box = (await canvas.boundingBox())!
    const cx = box.x + box.width / 2
    const cy = box.y + box.height / 2

    // Where is the object before the drag? Track the centroid of the lit pixels.
    const centroid = async () =>
      await canvas.evaluate((el: HTMLCanvasElement) =>
        new Promise<number | null>((resolve) => {
          requestAnimationFrame(() => {
            const gl = (el.getContext('webgl2') ||
              el.getContext('webgl')) as WebGLRenderingContext | null
            if (!gl) return resolve(null)
            const { width: w, height: h } = el
            const px = new Uint8Array(w * h * 4)
            gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px)
            let sx = 0, n = 0
            for (let y = 0; y < h; y++) {
              for (let x = 0; x < w; x++) {
                const i = (y * w + x) * 4
                if (px[i] + px[i + 1] + px[i + 2] > 150) { sx += x; n++ }
              }
            }
            resolve(n ? sx / n : null)
          })
        }),
      )

    const xBefore = await centroid()
    expect(xBefore).not.toBeNull()

    // Right-press, move well past the 6px tap threshold, release.
    await page.mouse.move(cx, cy)
    await page.mouse.down({ button: 'right' })
    await page.mouse.move(cx - 160, cy, { steps: 12 })
    await page.mouse.up({ button: 'right' })
    await page.waitForTimeout(500)

    // The menu must NOT have opened — a right-drag is a pan, not a click.
    await expect(page.getByTestId('viewport-context-menu')).toBeHidden()

    // And the pan must have actually moved the model on screen.
    const xAfter = await centroid()
    expect(xAfter).not.toBeNull()
    expect(Math.abs(xAfter! - xBefore!)).toBeGreaterThan(20)
  })
})
