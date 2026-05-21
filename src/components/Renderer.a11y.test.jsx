// Renderer.a11y.test.jsx — T-C5: keyboard + SR affordance for the 3D canvas.
//
// Strategy: source-file structural checks.  Renderer.jsx has deep WebGL /
// Three.js dependencies that cannot be instantiated in a vitest node
// environment, so we inspect the source text for ARIA attributes and test
// CANVAS_KEY_MAP by extracting it from the source text.
//
// Tests:
//   A. Canvas wrapper carries role="application"
//   B. Canvas wrapper carries a descriptive aria-label
//   C. Canvas wrapper carries tabIndex={0}
//   D. CANVAS_KEY_MAP exported constant covers arrows + zoom + reset
//   E. Key-handler source-level: preventDefault, guard, orbit, zoom, reset
//   F. role="status" live region present with aria-live + sr-only
//   G. Announcer text changes on selectedId / selectedFeatures

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(path.resolve(__dirname, './Renderer.jsx'), 'utf8')

// ── A. Structural: ARIA attributes on the canvas wrapper ──────────────────

describe('Renderer T-C5 — canvas ARIA + focusability', () => {
  it('canvas wrapper has role="application"', () => {
    expect(src).toContain('role="application"')
  })

  it('canvas wrapper has a descriptive aria-label mentioning viewport or canvas', () => {
    const match = src.match(/aria-label="([^"]+)"/)
    expect(match).not.toBeNull()
    const label = match[1].toLowerCase()
    expect(label).toMatch(/viewport|canvas/)
  })

  it('canvas wrapper aria-label mentions a key-binding hint', () => {
    const match = src.match(/aria-label="([^"]+)"/)
    expect(match).not.toBeNull()
    const label = match[1].toLowerCase()
    expect(label).toMatch(/arrow|orbit|zoom|reset/)
  })

  it('canvas wrapper has tabIndex={0}', () => {
    expect(src).toContain('tabIndex={0}')
  })

  it('canvas wrapper has an onKeyDown handler', () => {
    expect(src).toContain('onKeyDown={handleCanvasKeyDown}')
  })
})

// ── B. SR announcer ────────────────────────────────────────────────────────

// Find the last (JSX) occurrence of role="status" — the first may be a comment.
function findStatusDivIdx(source) {
  let idx = source.lastIndexOf('role="status"')
  return idx
}

describe('Renderer T-C5 — role="status" live region', () => {
  it('contains a role="status" element in JSX (not only in comments)', () => {
    // The JSX occurrence must be inside angle brackets, preceded by whitespace.
    expect(src).toMatch(/^\s+role="status"/m)
  })

  it('live region has aria-live="polite"', () => {
    const idx = findStatusDivIdx(src)
    expect(idx).toBeGreaterThan(-1)
    const nearby = src.slice(idx, idx + 200)
    expect(nearby).toContain('aria-live="polite"')
  })

  it('live region has aria-atomic="true"', () => {
    const idx = findStatusDivIdx(src)
    const nearby = src.slice(idx, idx + 200)
    expect(nearby).toContain('aria-atomic="true"')
  })

  it('live region renders the srAnnounce state value', () => {
    const idx = findStatusDivIdx(src)
    const nearby = src.slice(idx, idx + 300)
    expect(nearby).toContain('srAnnounce')
  })

  it('sr-only class is applied to the live region', () => {
    const idx = findStatusDivIdx(src)
    const nearby = src.slice(idx, idx + 200)
    expect(nearby).toContain('sr-only')
  })
})

// ── C. CANVAS_KEY_MAP — parsed from source ────────────────────────────────
//
// Rather than importing the module (which drags in WebGL / THREE), we parse
// the exported constant declaration out of the source text.

function parseCanvasKeyMap(source) {
  // Match the CANVAS_KEY_MAP object literal block.
  const start = source.indexOf('export const CANVAS_KEY_MAP = {')
  if (start === -1) return null
  const openBrace = source.indexOf('{', start)
  // Find matching close brace (simple depth counter — no nested objects in this map)
  let depth = 0
  let i = openBrace
  while (i < source.length) {
    if (source[i] === '{') depth++
    if (source[i] === '}') {
      depth--
      if (depth === 0) break
    }
    i++
  }
  const block = source.slice(openBrace, i + 1)
  // Extract key:value pairs — both single-quoted and unquoted keys
  const pairs = {}
  const re = /['"]?([^'":\s,{}]+)['"]?\s*:\s*['"]([^'"]+)['"]/g
  let m
  while ((m = re.exec(block)) !== null) {
    pairs[m[1]] = m[2]
  }
  return pairs
}

const keyMap = parseCanvasKeyMap(src)

describe('CANVAS_KEY_MAP (source-parsed)', () => {
  it('is present and exported in Renderer.jsx', () => {
    expect(src).toContain('export const CANVAS_KEY_MAP')
    expect(keyMap).not.toBeNull()
  })

  it('maps arrowup → orbitUp', () => {
    expect(keyMap['arrowup']).toBe('orbitUp')
  })

  it('maps arrowdown → orbitDown', () => {
    expect(keyMap['arrowdown']).toBe('orbitDown')
  })

  it('maps arrowleft → orbitLeft', () => {
    expect(keyMap['arrowleft']).toBe('orbitLeft')
  })

  it('maps arrowright → orbitRight', () => {
    expect(keyMap['arrowright']).toBe('orbitRight')
  })

  it('maps + → zoomIn', () => {
    expect(keyMap['+']).toBe('zoomIn')
  })

  it('maps = → zoomIn (no-shift physical + key)', () => {
    expect(keyMap['=']).toBe('zoomIn')
  })

  it('maps - → zoomOut', () => {
    expect(keyMap['-']).toBe('zoomOut')
  })

  it('maps r → resetView', () => {
    expect(keyMap['r']).toBe('resetView')
  })

  it('covers all four orbit directions', () => {
    const orbitActions = Object.values(keyMap).filter((v) => v.startsWith('orbit'))
    expect(orbitActions).toHaveLength(4)
  })

  it('covers zoomIn and zoomOut', () => {
    const vals = Object.values(keyMap)
    expect(vals).toContain('zoomIn')
    expect(vals).toContain('zoomOut')
  })

  it('covers resetView', () => {
    expect(Object.values(keyMap)).toContain('resetView')
  })
})

// ── D. Key-handler source-level checks ───────────────────────────────────

describe('Renderer T-C5 — key handler source checks', () => {
  it('calls e.preventDefault() for handled keys', () => {
    expect(src).toContain('e.preventDefault()')
  })

  it('returns early for unrecognised keys (guard: if (!action) return)', () => {
    expect(src).toContain('if (!action) return')
  })

  it('uses THREE.Spherical for orbit camera nudge', () => {
    expect(src).toContain('THREE.Spherical')
  })

  it('uses multiplyScalar(factor) for zoom dolly', () => {
    expect(src).toContain('multiplyScalar(factor)')
  })

  it('resetView calls controls.reset()', () => {
    expect(src).toContain('controls.reset()')
  })

  it('resetView announces to SR via setSrAnnounce', () => {
    expect(src).toContain("setSrAnnounce('View reset')")
  })
})

// ── E. Selection announcer ────────────────────────────────────────────────

describe('Renderer T-C5 — selection announcer useEffect', () => {
  it('announces "Selected: <id>" when selectedId is truthy', () => {
    expect(src).toContain('Selected: ${id}')
  })

  it('announces "No selection" when nothing is selected', () => {
    expect(src).toContain("setSrAnnounce('No selection')")
  })

  it('announces selected features list when selectedFeatures is non-empty', () => {
    expect(src).toContain('Selected features:')
  })

  it('announcer effect has selectedId in its dependency array', () => {
    // Find the setSrAnnounce call that handles selection, then look forward
    // for the closing effect deps array.
    const effectIdx = src.indexOf('setSrAnnounce(`Selected: ${id}`)')
    expect(effectIdx).toBeGreaterThan(-1)
    const after = src.slice(effectIdx, effectIdx + 400)
    expect(after).toContain('selectedId')
  })

  it('srAnnounce state is declared via useState', () => {
    expect(src).toContain('srAnnounce')
    expect(src).toContain('setSrAnnounce')
    // It should be in a useState call
    expect(src).toMatch(/const \[srAnnounce, setSrAnnounce\] = useState/)
  })
})
