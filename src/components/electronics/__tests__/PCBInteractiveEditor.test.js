// PCBInteractiveEditor.test.js — Vitest smoke tests for the PCB editor UI.
//
// Strategy: source-contract tests (no React rendering overhead needed for
// these checks) + a dynamic import sanity test to verify the module loads.
// fetch is mocked to return empty / ok responses so no real backend is needed.
//
// Verifies:
//   1. Toolbar source has all four tool buttons (select / route / push-shove / delete)
//   2. Toolbar source has all four layer buttons (top / bottom / inner1 / inner2)
//   3. Toolbar source has undo/redo buttons
//   4. Toolbar source has DRC indicator element
//   5. Canvas source has SVG viewBox
//   6. PCBInteractiveEditor module imports without throwing (dynamic import)
//   7. Canvas source renders pads and traces groups
//   8. PCBInteractiveEditor source references the route/push-shove API endpoints

import { describe, it, expect, vi, beforeAll } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// ── Global fetch mock (returns empty arrays / ok) ─────────────────────────────

beforeAll(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ ok: true, violations: [], pads: [], traces: [], keepouts: [] }),
    text: async () => '{}',
  })
})

// ── Helpers ───────────────────────────────────────────────────────────────────

const root = resolve(__dirname, '../../..')

function src(relPath) {
  return readFileSync(resolve(root, relPath), 'utf8')
}

// ─────────────────────────────────────────────────────────────────────────────

describe('Toolbar — source contracts', () => {
  const toolbarSrc = src('components/electronics/pcb-editor/Toolbar.jsx')

  it('has tool buttons rendered from TOOLS array', () => {
    // Buttons use data-testid={`tool-${id}`} via map over TOOLS
    expect(toolbarSrc).toMatch(/data-testid=\{`tool-\$\{id\}`\}/)
  })

  it('declares select tool in TOOLS array', () => {
    expect(toolbarSrc).toMatch(/id:\s*['"]select['"]/)
  })

  it('declares route tool in TOOLS array', () => {
    expect(toolbarSrc).toMatch(/id:\s*['"]route['"]/)
  })

  it('declares push-shove tool in TOOLS array', () => {
    expect(toolbarSrc).toMatch(/id:\s*['"]push-shove['"]/)
  })

  it('declares delete tool in TOOLS array', () => {
    expect(toolbarSrc).toMatch(/id:\s*['"]delete['"]/)
  })

  it('has layer buttons rendered from LAYERS array', () => {
    // Buttons use data-testid={`layer-${id}`} via map over LAYERS
    expect(toolbarSrc).toMatch(/data-testid=\{`layer-\$\{id\}`\}/)
  })

  it('declares top layer in LAYERS array', () => {
    expect(toolbarSrc).toMatch(/id:\s*['"]top['"]/)
  })

  it('declares bottom layer in LAYERS array', () => {
    expect(toolbarSrc).toMatch(/id:\s*['"]bottom['"]/)
  })

  it('declares inner1 layer in LAYERS array', () => {
    expect(toolbarSrc).toMatch(/id:\s*['"]inner1['"]/)
  })

  it('declares inner2 layer in LAYERS array', () => {
    expect(toolbarSrc).toMatch(/id:\s*['"]inner2['"]/)
  })

  it('has an undo button', () => {
    expect(toolbarSrc).toMatch(/data-testid="btn-undo"/)
  })

  it('has a redo button', () => {
    expect(toolbarSrc).toMatch(/data-testid="btn-redo"/)
  })

  it('has a DRC indicator', () => {
    expect(toolbarSrc).toMatch(/data-testid="drc-indicator"/)
  })
})

describe('Canvas — source contracts', () => {
  const canvasSrc = src('components/electronics/pcb-editor/Canvas.jsx')

  it('uses SVG viewBox', () => {
    expect(canvasSrc).toMatch(/viewBox/)
  })

  it('renders a pads layer', () => {
    expect(canvasSrc).toMatch(/data-layer="pads"/)
  })

  it('renders a traces layer', () => {
    expect(canvasSrc).toMatch(/data-layer="traces"/)
  })

  it('renders a grid', () => {
    expect(canvasSrc).toMatch(/data-layer="grid"/)
  })

  it('renders keepout zones', () => {
    expect(canvasSrc).toMatch(/data-layer="keepout"/)
  })

  it('snaps coordinates to the grid', () => {
    expect(canvasSrc).toMatch(/snapToGrid/)
  })
})

describe('PCBInteractiveEditor — source contracts', () => {
  const editorSrc = src('components/electronics/PCBInteractiveEditor.jsx')

  it('calls electronics_route_trace endpoint', () => {
    expect(editorSrc).toMatch(/electronics_route_trace/)
  })

  it('calls electronics_delete_object endpoint', () => {
    expect(editorSrc).toMatch(/electronics_delete_object/)
  })

  it('calls pcb_drc endpoint for DRC polling', () => {
    expect(editorSrc).toMatch(/pcb_drc/)
  })

  it('calls pcb_shove_trace endpoint for push-shove', () => {
    expect(editorSrc).toMatch(/pcb_shove_trace/)
  })

  it('has mock fixture pads', () => {
    expect(editorSrc).toMatch(/MOCK_PADS/)
  })

  it('has mock fixture traces', () => {
    expect(editorSrc).toMatch(/MOCK_TRACES/)
  })

  it('supports undo/redo via dispatch', () => {
    expect(editorSrc).toMatch(/UNDO/)
    expect(editorSrc).toMatch(/REDO/)
  })

  it('loads board from /api/projects/:id/pcb when project_id present', () => {
    expect(editorSrc).toMatch(/\/api\/projects\/.+\/pcb/)
  })
})

describe('PCBEditor route — source contracts', () => {
  const routeSrc = src('routes/PCBEditor.jsx')

  it('imports PCBInteractiveEditor', () => {
    expect(routeSrc).toMatch(/PCBInteractiveEditor/)
  })

  it('exports a default component', () => {
    expect(routeSrc).toMatch(/export default function PCBEditor/)
  })
})

describe('App.jsx — route registration', () => {
  const appSrc = src('App.jsx')

  it('lazy-imports PCBEditor', () => {
    expect(appSrc).toMatch(/lazy.*PCBEditor/)
  })

  it('registers /pcb-editor route', () => {
    expect(appSrc).toMatch(/\/pcb-editor/)
  })
})

describe('PCBInteractiveEditor — module loads', () => {
  it('module can be dynamically imported without throwing', async () => {
    // Mock router dep before import
    vi.mock('react-router-dom', () => ({
      useSearchParams: () => [new URLSearchParams()],
    }))
    const mod = await import('../PCBInteractiveEditor.jsx')
    expect(mod.default).toBeTruthy()
  })
})
