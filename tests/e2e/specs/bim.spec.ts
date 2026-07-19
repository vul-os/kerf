/**
 * bim.spec.ts — author a .bim file, compile it to IFC4, assert the 3D viewer
 * actually draws the resulting geometry.
 *
 * LOCAL MODE: no sign-in required (KERF_LOCAL_MODE=true).
 *
 * What this suite covers
 * ----------------------
 * 1. Create a project and open the editor
 * 2. Create a generic file and rename it to `.bim` (BIM has no "+ New" entry —
 *    Editor.jsx routes on the extension, see isBIMFile())
 * 3. Type a minimal JSON .bim doc: one storey, four walls, one slab
 * 4. The backend compiles it to IFC4 via POST /compile-ifc (IfcOpenShell)
 * 5. BIMView loads web-ifc's WASM, streams the meshes, and Three.js draws them
 *
 * Why this test exists
 * --------------------
 * The whole chain is load-bearing and every link has silently broken before:
 * the `web-ifc` package was missing from package.json entirely (the editor
 * route 500'd), its WASM was fetched from a CDN (so the viewer died offline),
 * and the IFC unit assignment used a non-existent MILLIMETRE enum (so every
 * compile failed). A green canvas here means all three are wired.
 *
 * Backend requirement
 * -------------------
 * /compile-ifc needs IfcOpenShell, which is an OPTIONAL extra:
 *
 *     pip install 'kerf-bim[ifc]'      # or: pip install ifcopenshell
 *
 * Without it the route returns {errors: ["ifcopenshell not available: ..."]},
 * BIMFileView surfaces "IFC compile failed", and this spec fails at step 4
 * with that message rather than a bare timeout.
 *
 * Pixel check (stronger than the one in jscad.spec.ts)
 * ---------------------------------------------------
 * Three.js renders through WebGL, so a 2D getImageData() returns all zeros and
 * proves nothing — jscad.spec.ts settles for "canvas exists and has non-zero
 * dimensions", which stays green even if the renderer draws an empty scene.
 * Here we instead call gl.readPixels() on the LIVE WebGL context (getContext()
 * returns the same context Three.js created) from inside a requestAnimationFrame
 * callback. Our callback is queued after BIMView's animate() for that frame, so
 * the drawing buffer still holds the freshly rendered image — it is only cleared
 * once the frame composites. We then count pixels that differ from the scene's
 * clear colour (0x0a0a0f). Walls/slabs are drawn in 0x7799bb, so real geometry
 * lights up a healthy fraction of the canvas; an empty scene reads as 0%.
 */

import { test, expect } from '@playwright/test'
import { ProjectsPage } from '../pages/ProjectsPage'
import { EditorPage } from '../pages/EditorPage'

const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

// Minimal JSON .bim doc — a 6m × 4m room: four walls on one storey plus a
// floor slab. Matches the schema _compile() reads in kerf_bim/routes.py
// (levels[] / walls[from,to,height,thickness] / slabs[boundary,thickness]).
// All lengths are millimetres.
const ROOM_BIM = JSON.stringify(
  {
    version: 1,
    name: 'E2E Test Building',
    levels: [{ name: 'L1', elevation: 0 }],
    walls: [
      { level: 'L1', from: [0, 0], to: [6000, 0], height: 3000, thickness: 200 },
      { level: 'L1', from: [6000, 0], to: [6000, 4000], height: 3000, thickness: 200 },
      { level: 'L1', from: [6000, 4000], to: [0, 4000], height: 3000, thickness: 200 },
      { level: 'L1', from: [0, 4000], to: [0, 0], height: 3000, thickness: 200 },
    ],
    slabs: [
      {
        level: 'L1',
        boundary: [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
        thickness: 200,
      },
    ],
  },
  null,
  2,
)

/**
 * Read back the live WebGL drawing buffer and classify every pixel.
 *
 * We key on BRIGHTNESS rather than "differs from the clear colour". The scene
 * clears to 0x0a0a0f (sum 35) and an unrendered/cleared buffer reads as pure
 * black (sum 0) — those are only ~10/255 apart per channel, so a
 * difference-from-background test scores a black canvas as 100% "rendered" and
 * would pass on a completely broken viewer. Lit geometry is unmistakable: the
 * walls' material is 0x7799bb (sum 561) and even in full shade the ambient term
 * keeps it near sum 230, far above both. So: sum > 120 ⇒ geometry.
 *
 * Returns null when WebGL is unavailable (we skip rather than fail).
 */
async function readCanvasPixels(page: import('@playwright/test').Page) {
  return await page.getByTestId('bim-canvas').evaluate((el: HTMLCanvasElement) => {
    return new Promise<{ geometry: number; background: number; black: number } | null>(
      (resolve) => {
        // Our rAF callback is queued after BIMView's animate() for this frame,
        // so the drawing buffer still holds the freshly rendered image — it is
        // only cleared once the frame composites.
        requestAnimationFrame(() => {
          // getContext() hands back the SAME context Three.js created, so this
          // reads the real scene rather than allocating a fresh one.
          const gl = (el.getContext('webgl2') ||
            el.getContext('webgl')) as WebGLRenderingContext | null
          if (!gl) return resolve(null)

          const { width: w, height: h } = el
          if (!w || !h) return resolve({ geometry: 0, background: 0, black: 0 })

          const px = new Uint8Array(w * h * 4)
          gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px)

          const total = w * h
          let geometry = 0
          let black = 0
          for (let i = 0; i < px.length; i += 4) {
            const sum = px[i] + px[i + 1] + px[i + 2]
            if (sum > 120) geometry++
            else if (sum === 0) black++
          }
          resolve({
            geometry: geometry / total,
            background: (total - geometry - black) / total,
            black: black / total,
          })
        })
      },
    )
  })
}

test.describe('BIM editor (local mode)', () => {
  test('author a .bim file — IFC compiles and the 3D viewer draws it', async ({
    page,
  }) => {
    // Surface a missing-IfcOpenShell backend as a clear failure instead of a
    // 30 s timeout on an empty canvas.
    const compileFailures: string[] = []
    page.on('response', async (res) => {
      if (!res.url().includes('/compile-ifc')) return
      try {
        const body = await res.json()
        if (body?.errors?.length) compileFailures.push(body.errors.join('; '))
      } catch {
        compileFailures.push(`/compile-ifc returned HTTP ${res.status()}`)
      }
    })

    // 1. Create a project — lands us in the editor.
    const pp = new ProjectsPage(page)
    await pp.goto()
    await page.waitForURL(/\/projects$/, { timeout: 20_000 })
    await pp.createProject(`e2e-bim-${uid()}`)
    await page.waitForURL(/\/projects\//, { timeout: 20_000 })

    const ep = new EditorPage(page)
    await ep.waitForLoad()

    // 2. Create a generic file (seeds as untitled.jscad) and author the room in
    //    Monaco. Content first, rename second: once the file is `.bim`,
    //    Editor.jsx swaps the centre pane to BIMFileView and there is no code
    //    editor left to type into.
    await ep.createFile('File')
    await expect(page.locator('.monaco-editor').first()).toBeVisible({
      timeout: 20_000,
    })

    // Wait for the debounced autosave to actually land, and assert on the PATCH
    // itself rather than the "Saved" chip — that chip is the idle state, so it
    // is already showing before we type and would make this wait vacuous.
    const saved = page.waitForResponse(
      (res) =>
        res.request().method() === 'PATCH' &&
        /\/files\//.test(res.url()) &&
        (res.request().postData() || '').includes('"content"') &&
        res.ok(),
      { timeout: 20_000 },
    )
    await ep.typeInMonaco(ROOM_BIM)
    await saved

    // 3. Rename to .bim — the extension is what routes to BIMFileView
    //    (isBIMFile()), which POSTs the content to /compile-ifc.
    await ep.renameFile('untitled.jscad', 'room.bim')

    // 4. The compile round-trips through IfcOpenShell on the backend; on a
    //    cold server this can take a few seconds.
    const canvas = page.getByTestId('bim-canvas')
    await expect(canvas).toBeVisible({ timeout: 30_000 })
    expect(compileFailures, 'POST /compile-ifc returned errors').toEqual([])

    // 5. The canvas must actually contain geometry, not just exist. Poll —
    //    web-ifc's WASM boot plus mesh streaming takes a moment.
    let px: Awaited<ReturnType<typeof readCanvasPixels>> = null
    await expect
      .poll(
        async () => {
          px = await readCanvasPixels(page)
          if (px === null) return -1 // no WebGL — short-circuit, skipped below
          return px.geometry
        },
        {
          timeout: 30_000,
          intervals: [500, 1_000, 2_000],
          message: 'BIM canvas never rendered any geometry',
        },
      )
      .not.toBe(0)

    test.skip(px === null, 'WebGL unavailable — cannot verify pixels')

    const { geometry, background, black } = px!
    console.log(
      `BIM canvas: ${(geometry * 100).toFixed(1)}% geometry, ` +
        `${(background * 100).toFixed(1)}% background, ${(black * 100).toFixed(1)}% black`,
    )

    // A real render of a 6m × 4m room: geometry covers a meaningful slice of the
    // viewport, and the scene's dark background covers most of the rest. The
    // upper bound and the background floor together rule out the degenerate
    // "buffer is a solid fill" reads that a naive diff-from-background test
    // would happily score as 100% rendered.
    expect(geometry, 'walls/slab should cover a real fraction of the canvas')
      .toBeGreaterThan(0.02)
    expect(geometry, 'canvas is a solid fill, not a rendered scene').toBeLessThan(0.9)
    expect(background, 'scene background missing — buffer likely never rendered')
      .toBeGreaterThan(0.05)

    // No IFC parse/render error surfaced over the canvas.
    await expect(page.getByText('Render error')).toBeHidden()
    await expect(page.getByText('IFC compile failed')).toBeHidden()
  })
})
