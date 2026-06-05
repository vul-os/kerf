/**
 * weldmentFramePanel.test.jsx
 *
 * Source-level assertions + pure-helper unit tests for WeldmentFramePanel.
 * Uses renderToStaticMarkup (no @testing-library/react).
 *
 * Coverage:
 *  1. fmtNum helper
 *  2. parseSkeleton — validates JSON edge arrays
 *  3. buildFrameParams — maps form state to API params
 *  4. Source structure — data-testid markers
 *  5. api.callTool invocations (source scan)
 *  6. renderToStaticMarkup smoke test
 */

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import WeldmentFramePanel, {
  fmtNum,
  parseSkeleton,
  buildFrameParams,
} from '../WeldmentFramePanel.jsx'

const SRC = readFileSync(
  resolve(__dirname, '../WeldmentFramePanel.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// 1. fmtNum
// ---------------------------------------------------------------------------

describe('fmtNum', () => {
  it('returns — for null', () => {
    expect(fmtNum(null)).toBe('—')
  })

  it('returns — for NaN', () => {
    expect(fmtNum(NaN)).toBe('—')
  })

  it('returns — for Infinity', () => {
    expect(fmtNum(Infinity)).toBe('—')
  })

  it('formats to 2dp by default', () => {
    expect(fmtNum(1.2345)).toBe('1.23')
  })

  it('respects custom dp', () => {
    expect(fmtNum(3.14159, 3)).toBe('3.142')
  })

  it('formats zero correctly', () => {
    expect(fmtNum(0)).toBe('0.00')
  })
})

// ---------------------------------------------------------------------------
// 2. parseSkeleton
// ---------------------------------------------------------------------------

describe('parseSkeleton', () => {
  it('returns error for empty string', () => {
    expect(parseSkeleton('').ok).toBe(false)
    expect(parseSkeleton('').error).toBeTruthy()
  })

  it('returns error for non-array JSON', () => {
    const r = parseSkeleton('{"start":[0,0,0]}')
    expect(r.ok).toBe(false)
    expect(r.error).toMatch(/array/)
  })

  it('returns error for invalid JSON', () => {
    const r = parseSkeleton('not json')
    expect(r.ok).toBe(false)
    expect(r.error).toMatch(/JSON/)
  })

  it('accepts a valid edge list', () => {
    const edges = [
      { start: [0, 0, 0], end: [1000, 0, 0] },
      { start: [1000, 0, 0], end: [1000, 0, 1000] },
    ]
    const r = parseSkeleton(JSON.stringify(edges))
    expect(r.ok).toBe(true)
    expect(r.edges).toHaveLength(2)
    expect(r.edges[0].start).toEqual([0, 0, 0])
  })

  it('rejects an edge with missing start', () => {
    const edges = [{ end: [1000, 0, 0] }]
    const r = parseSkeleton(JSON.stringify(edges))
    expect(r.ok).toBe(false)
    expect(r.error).toMatch(/start/)
  })

  it('rejects an edge with start that is not 3-element array', () => {
    const edges = [{ start: [0, 0], end: [1000, 0, 0] }]
    const r = parseSkeleton(JSON.stringify(edges))
    expect(r.ok).toBe(false)
  })

  it('rejects an edge with missing end', () => {
    const edges = [{ start: [0, 0, 0] }]
    const r = parseSkeleton(JSON.stringify(edges))
    expect(r.ok).toBe(false)
    expect(r.error).toMatch(/end/)
  })

  it('returns empty ok=true for empty array', () => {
    const r = parseSkeleton('[]')
    expect(r.ok).toBe(true)
    expect(r.edges).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// 3. buildFrameParams
// ---------------------------------------------------------------------------

describe('buildFrameParams', () => {
  const VALID_EDGES = [
    { start: [0, 0, 0], end: [1000, 0, 0] },
  ]

  it('passes profile through', () => {
    const p = buildFrameParams({
      skeleton: JSON.stringify(VALID_EDGES),
      profile: 'SHS-50x50x3',
    })
    expect(p.profile).toBe('SHS-50x50x3')
  })

  it('includes parsed edges in skeleton', () => {
    const p = buildFrameParams({
      skeleton: JSON.stringify(VALID_EDGES),
      profile: 'SHS-50x50x3',
    })
    expect(Array.isArray(p.skeleton)).toBe(true)
    expect(p.skeleton).toHaveLength(1)
  })

  it('returns empty skeleton for invalid JSON', () => {
    const p = buildFrameParams({ skeleton: 'bad json', profile: 'SHS-50x50x3' })
    expect(p.skeleton).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// 4. Source structure
// ---------------------------------------------------------------------------

describe('WeldmentFramePanel — source structure', () => {
  it('exports a default WeldmentFramePanel function', () => {
    expect(SRC).toMatch(/export default function WeldmentFramePanel/)
  })

  it('has weldment-frame-panel data-testid', () => {
    expect(SRC).toMatch(/data-testid="weldment-frame-panel"/)
  })

  it('has weldment-panel-toggle data-testid', () => {
    expect(SRC).toMatch(/data-testid="weldment-panel-toggle"/)
  })

  it('has weldment-panel-body data-testid', () => {
    expect(SRC).toMatch(/data-testid="weldment-panel-body"/)
  })

  it('has mode tab template for profile/frame', () => {
    expect(SRC).toMatch(/data-testid=\{`weldment-mode-\$\{k\}`\}/)
  })

  it('has profile mode section testid', () => {
    expect(SRC).toMatch(/data-testid="weldment-profile-mode"/)
  })

  it('has frame mode section testid', () => {
    expect(SRC).toMatch(/data-testid="weldment-frame-mode"/)
  })

  it('has weldment-profile-run button', () => {
    expect(SRC).toMatch(/weldment-profile-run/)
  })

  it('has weldment-frame-run button', () => {
    expect(SRC).toMatch(/weldment-frame-run/)
  })

  it('has cut table data-testid', () => {
    expect(SRC).toMatch(/weldment-cut-table/)
  })

  it('has cut row data-testid', () => {
    expect(SRC).toMatch(/weldment-cut-row/)
  })

  it('mentions Structural Framework in header', () => {
    expect(SRC).toMatch(/Structural Framework/)
  })

  it('references skeleton JSON textarea', () => {
    expect(SRC).toMatch(/wf-skeleton/)
  })
})

// ---------------------------------------------------------------------------
// 5. api.callTool
// ---------------------------------------------------------------------------

describe('WeldmentFramePanel — api.callTool', () => {
  it('calls api.callTool', () => {
    expect(SRC).toMatch(/api\.callTool/)
  })

  it('invokes weldment_profile_lookup', () => {
    expect(SRC).toMatch(/['"]weldment_profile_lookup['"]/)
  })

  it('invokes weldment_frame', () => {
    expect(SRC).toMatch(/['"]weldment_frame['"]/)
  })
})

// ---------------------------------------------------------------------------
// 6. Smoke render
// ---------------------------------------------------------------------------

describe('WeldmentFramePanel — renderToStaticMarkup', () => {
  it('renders without crashing (collapsed)', () => {
    vi.mock('../../../lib/api.js', () => ({ api: { callTool: vi.fn() } }))
    const html = renderToStaticMarkup(<WeldmentFramePanel />)
    expect(html).toContain('weldment-frame-panel')
  })
})
