/**
 * SculptStudioPanel.test.jsx
 * ==========================
 * Tests for the DCC Sculpt Studio panel.
 *
 * Strategy
 * --------
 * Tier 1 — source inspection: data-testid landmarks, callTool invocations.
 * Tier 2 — renderToStaticMarkup smoke tests: panel mounts, controls present.
 * Tier 3 — exported helper unit tests: makeBrushArgs, makeRemeshArgs,
 *           makePolypaintArgs (pure functions for building tool call args).
 */

import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'
import { renderToStaticMarkup } from 'react-dom/server'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(path.resolve(__dirname, './SculptStudioPanel.jsx'), 'utf8')

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('lucide-react', () => {
  const Stub = () => null
  return {
    Layers: Stub, Zap: Stub, RotateCcw: Stub, Cpu: Stub, Palette: Stub,
    Activity: Stub, ChevronDown: Stub, ChevronRight: Stub,
  }
})

import SculptStudioPanel, {
  BRUSH_KINDS,
  TAUBIN_ID,
  makeBrushArgs,
  makeRemeshArgs,
  makePolypaintArgs,
} from './SculptStudioPanel.jsx'

// ── Source inspection ─────────────────────────────────────────────────────────

describe('SculptStudioPanel source: required testids and tool calls', () => {
  it('has data-testid="sculpt-studio-panel"', () => {
    expect(src).toContain('data-testid="sculpt-studio-panel"')
  })

  it('has data-testid="sculpt-viewport"', () => {
    expect(src).toContain('data-testid="sculpt-viewport"')
  })

  it('has data-testid="mesh-stats"', () => {
    expect(src).toContain('data-testid="mesh-stats"')
  })

  it('calls sculpt_apply_brush', () => {
    expect(src).toContain('sculpt_apply_brush')
  })

  it('calls sculpt_dynamesh_remesh', () => {
    expect(src).toContain('sculpt_dynamesh_remesh')
  })

  it('calls sculpt_polypaint_stroke', () => {
    expect(src).toContain('sculpt_polypaint_stroke')
  })

  it('has btn-apply-brush', () => {
    expect(src).toContain('data-testid="btn-apply-brush"')
  })

  it('has btn-remesh', () => {
    expect(src).toContain('data-testid="btn-remesh"')
  })

  it('has btn-polypaint-stroke', () => {
    expect(src).toContain('data-testid="btn-polypaint-stroke"')
  })

  it('has brush-palette testid', () => {
    expect(src).toContain('data-testid="brush-palette"')
  })
})

// ── BRUSH_KINDS export ────────────────────────────────────────────────────────

describe('BRUSH_KINDS export', () => {
  it('is an array', () => {
    expect(Array.isArray(BRUSH_KINDS)).toBe(true)
  })

  it('contains grab, smooth, inflate, crease, pinch', () => {
    const ids = BRUSH_KINDS.map((b) => b.id)
    expect(ids).toContain('grab')
    expect(ids).toContain('smooth')
    expect(ids).toContain('inflate')
    expect(ids).toContain('crease')
    expect(ids).toContain('pinch')
  })

  it('every brush has id, label, description', () => {
    for (const b of BRUSH_KINDS) {
      expect(typeof b.id).toBe('string')
      expect(typeof b.label).toBe('string')
      expect(typeof b.description).toBe('string')
    }
  })

  it('TAUBIN_ID is defined', () => {
    expect(typeof TAUBIN_ID).toBe('string')
    expect(TAUBIN_ID).toBeTruthy()
  })
})

// ── SSR smoke tests ───────────────────────────────────────────────────────────

describe('SculptStudioPanel renderToStaticMarkup', () => {
  it('mounts without throwing', () => {
    expect(() => renderToStaticMarkup(<SculptStudioPanel />)).not.toThrow()
  })

  it('renders sculpt-studio-panel root', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('sculpt-studio-panel')
  })

  it('renders brush palette', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('brush-palette')
  })

  it('shows mesh stats container', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('mesh-stats')
  })

  it('renders all 5 BRUSH_KINDS buttons', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    for (const b of BRUSH_KINDS) {
      expect(html).toContain(`brush-${b.id}`)
    }
  })

  it('renders Taubin brush button', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('brush-taubin')
  })

  it('renders strength slider', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('slider-strength')
  })

  it('renders radius slider', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('slider-radius')
  })

  it('renders remesh resolution slider', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('slider-remesh-res')
  })

  it('renders polypaint color input', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('polypaint-color')
  })

  it('accepts content prop with existing mesh', () => {
    const content = JSON.stringify({
      positions: [[0,0,0],[1,0,0],[0,1,0]],
      triangles: [[0,1,2]],
    })
    expect(() => renderToStaticMarkup(<SculptStudioPanel content={content} />)).not.toThrow()
  })

  it('handles bad content gracefully', () => {
    expect(() => renderToStaticMarkup(<SculptStudioPanel content="NOT_JSON" />)).not.toThrow()
  })

  it('renders apply brush button', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('btn-apply-brush')
  })

  it('renders remesh button', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('btn-remesh')
  })

  it('renders polypaint stroke button', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('btn-polypaint-stroke')
  })

  it('renders falloff buttons', () => {
    const html = renderToStaticMarkup(<SculptStudioPanel />)
    expect(html).toContain('falloff-smooth')
    expect(html).toContain('falloff-linear')
    expect(html).toContain('falloff-constant')
  })
})

// ── makeBrushArgs helper unit tests ──────────────────────────────────────────

describe('makeBrushArgs — sculpt_apply_brush arg shape', () => {
  const DEFAULT_MESH = {
    positions: [[0,0,0],[1,0,0],[0,1,0]],
    triangles: [[0,1,2]],
  }

  it('is a function', () => {
    expect(typeof makeBrushArgs).toBe('function')
  })

  it('returns positions and triangles', () => {
    const args = makeBrushArgs({
      mesh: DEFAULT_MESH,
      kind: 'grab',
      center: [0.5, 0.5, 0.5],
      radius: 0.3,
      strength: 0.5,
      falloff: 'smooth',
    })
    expect(args).toHaveProperty('positions')
    expect(args).toHaveProperty('triangles')
    expect(args.positions).toEqual(DEFAULT_MESH.positions)
  })

  it('includes kind, center, radius, strength, falloff', () => {
    const args = makeBrushArgs({
      mesh: DEFAULT_MESH,
      kind: 'smooth',
      center: [0, 0, 0],
      radius: 1.0,
      strength: 0.8,
      falloff: 'linear',
    })
    expect(args.kind).toBe('smooth')
    expect(args.center).toEqual([0, 0, 0])
    expect(args.radius).toBe(1.0)
    expect(args.strength).toBe(0.8)
    expect(args.falloff).toBe('linear')
  })

  it('accepts all BRUSH_KINDS ids', () => {
    for (const b of BRUSH_KINDS) {
      const args = makeBrushArgs({
        mesh: DEFAULT_MESH,
        kind: b.id,
        center: [0, 0, 0],
        radius: 0.5,
        strength: 0.5,
        falloff: 'smooth',
      })
      expect(args.kind).toBe(b.id)
    }
  })
})

describe('makeRemeshArgs — sculpt_dynamesh_remesh arg shape', () => {
  const DEFAULT_MESH = {
    positions: [[0,0,0],[1,0,0],[0,1,0]],
    triangles: [[0,1,2]],
  }

  it('is a function', () => {
    expect(typeof makeRemeshArgs).toBe('function')
  })

  it('returns positions, triangles, target_resolution', () => {
    const args = makeRemeshArgs({ mesh: DEFAULT_MESH, resolution: 128 })
    expect(args).toHaveProperty('positions')
    expect(args).toHaveProperty('triangles')
    expect(args).toHaveProperty('target_resolution')
    expect(args.target_resolution).toBe(128)
  })
})

describe('makePolypaintArgs — sculpt_polypaint_stroke arg shape', () => {
  const DEFAULT_MESH = {
    positions: [[0,0,0],[1,0,0],[0,1,0]],
    triangles: [[0,1,2]],
  }

  it('is a function', () => {
    expect(typeof makePolypaintArgs).toBe('function')
  })

  it('returns positions, vertex_colors, center, radius, color', () => {
    const currentColors = [[0.5,0.5,0.5],[0.5,0.5,0.5],[0.5,0.5,0.5]]
    const args = makePolypaintArgs({
      mesh: DEFAULT_MESH,
      vertexColors: currentColors,
      center: [0.5, 0.5, 0.5],
      radius: 0.3,
      polyColor: '#ff5500',
      polyOpacity: 0.8,
      falloff: 'smooth',
    })
    expect(args).toHaveProperty('positions')
    expect(args).toHaveProperty('vertex_colors')
    expect(args).toHaveProperty('center')
    expect(args).toHaveProperty('radius')
    expect(args).toHaveProperty('color')
    expect(Array.isArray(args.color)).toBe(true)
    expect(args.color).toHaveLength(3)
    // #ff5500 → [1, 0.333..., 0]
    expect(args.color[0]).toBeCloseTo(1.0, 1)
  })

  it('converts hex color to normalized RGB array', () => {
    const args = makePolypaintArgs({
      mesh: { positions: [], triangles: [] },
      vertexColors: [],
      center: [0,0,0],
      radius: 1,
      polyColor: '#ffffff',
      polyOpacity: 1.0,
      falloff: 'smooth',
    })
    expect(args.color[0]).toBeCloseTo(1.0, 4)
    expect(args.color[1]).toBeCloseTo(1.0, 4)
    expect(args.color[2]).toBeCloseTo(1.0, 4)
  })
})
