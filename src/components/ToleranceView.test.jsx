/**
 * ToleranceView.test.jsx
 *
 * Tests the parseToleranceFile helper and basic rendering of ToleranceView.
 * Uses renderToStaticMarkup (no @testing-library/react) — same pattern as
 * the rest of the component test suite.
 */
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ToleranceView, { parseToleranceFile } from './ToleranceView.jsx'

// ---------------------------------------------------------------------------
// parseToleranceFile
// ---------------------------------------------------------------------------

describe('parseToleranceFile', () => {
  it('returns empty kind for blank input', () => {
    expect(parseToleranceFile('').kind).toBe('empty')
    expect(parseToleranceFile('   ').kind).toBe('empty')
    expect(parseToleranceFile(null).kind).toBe('empty')
  })

  it('returns invalid kind for bad JSON', () => {
    const r = parseToleranceFile('not json')
    expect(r.kind).toBe('invalid')
    expect(typeof r.error).toBe('string')
  })

  it('returns invalid for non-object JSON', () => {
    const r = parseToleranceFile('[1, 2, 3]')
    expect(r.kind).toBe('invalid')
  })

  it('returns unsupported when kind is unknown', () => {
    const r = parseToleranceFile(JSON.stringify({ kind: 'assembly' }))
    expect(r.kind).toBe('unsupported')
  })

  it('parses valid tolerance file with tolerances array', () => {
    const doc = {
      kind: 'tolerance',
      id: 'tol-001',
      name: 'shaft_assembly',
      tolerances: [
        { id: 'A', nominal: 50.0, plus: 0.1, minus: 0.1, unit: 'mm' },
        { id: 'B', nominal: 25.0, plus: 0.05, minus: 0.05, unit: 'mm' },
      ],
    }
    const r = parseToleranceFile(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.id).toBe('tol-001')
    expect(r.name).toBe('shaft_assembly')
    expect(r.tolerances).toHaveLength(2)
    expect(r.tolerances[0].nominal).toBe(50.0)
  })

  it('accepts file with no kind field (implicit tolerance)', () => {
    const doc = {
      tolerances: [
        { id: 'X', nominal: 10.0, plus: 0.02, minus: 0.02 },
      ],
    }
    const r = parseToleranceFile(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.tolerances).toHaveLength(1)
  })

  it('returns empty tolerances for missing tolerances field', () => {
    const r = parseToleranceFile(JSON.stringify({ kind: 'tolerance', id: 'x' }))
    expect(r.kind).toBe('ok')
    expect(r.tolerances).toEqual([])
  })

  it('handles tolerances in upper/lower form', () => {
    const doc = {
      tolerances: [
        { id: 'Y', nominal: 20.0, upper: 20.1, lower: 19.9 },
      ],
    }
    const r = parseToleranceFile(JSON.stringify(doc))
    expect(r.kind).toBe('ok')
    expect(r.tolerances[0].upper).toBe(20.1)
    expect(r.tolerances[0].lower).toBe(19.9)
  })
})

// ---------------------------------------------------------------------------
// ToleranceView component rendering
// ---------------------------------------------------------------------------

// Mock the api module so we can render without a browser/server
vi.mock('../lib/api.js', () => ({
  api: {
    runTolerance: vi.fn().mockResolvedValue({}),
    chat: vi.fn().mockResolvedValue({}),
  },
}))

// Mock worstCaseStack / rssStack from the tolerance lib
vi.mock('../lib/tolerance.js', () => ({
  worstCaseStack: () => ({ method: 'worst_case', nominal: 75.0, max: 75.17, min: 74.83 }),
  rssStack: () => ({ method: 'rss', nominal: 75.0, band: 0.12 }),
}))

describe('ToleranceView — render', () => {
  it('renders empty state for null content', () => {
    const html = renderToStaticMarkup(
      <ToleranceView content="" fileName="test.tolerance" />
    )
    expect(html).toContain('Empty tolerance file')
    // or the kind:empty branch
  })

  it('renders invalid state for bad JSON', () => {
    const html = renderToStaticMarkup(
      <ToleranceView content="{bad json{{" fileName="test.tolerance" />
    )
    expect(html).toContain('Invalid tolerance file')
  })

  it('renders dimension table for valid tolerance file', () => {
    const doc = JSON.stringify({
      kind: 'tolerance',
      tolerances: [
        { id: 'shaft', nominal: 50.0, plus: 0.05, minus: 0.05, unit: 'mm' },
        { id: 'bore',  nominal: 25.0, plus: 0.025, minus: 0.025, unit: 'mm' },
      ],
    })
    const html = renderToStaticMarkup(
      <ToleranceView content={doc} fileName="shaft.tolerance" />
    )
    expect(html).toContain('shaft')
    expect(html).toContain('bore')
    expect(html).toContain('50.0000')
    expect(html).toContain('Dimension Chain')
    expect(html).toContain('Worst-Case')
  })

  it('renders Monte-Carlo button in header', () => {
    const doc = JSON.stringify({
      tolerances: [{ id: 'A', nominal: 10, plus: 0.1, minus: 0.1 }],
    })
    const html = renderToStaticMarkup(
      <ToleranceView content={doc} fileName="test.tolerance" projectId="p1" fileId="f1" />
    )
    expect(html).toContain('Monte-Carlo')
  })

  it('renders auto-build chain button', () => {
    const doc = JSON.stringify({
      tolerances: [{ id: 'A', nominal: 10, plus: 0.1, minus: 0.1 }],
    })
    const html = renderToStaticMarkup(
      <ToleranceView content={doc} fileName="test.tolerance" projectId="p1" fileId="f1" />
    )
    expect(html).toContain('Auto-build')
  })

  it('shows filename in header', () => {
    const doc = JSON.stringify({ tolerances: [] })
    const html = renderToStaticMarkup(
      <ToleranceView content={doc} fileName="bracket_assy.tolerance" />
    )
    expect(html).toContain('bracket_assy.tolerance')
  })

  it('renders IT grade chips when grade is present', () => {
    const doc = JSON.stringify({
      tolerances: [
        { id: 'D1', nominal: 25.0, grade: 'IT8' },
      ],
    })
    const html = renderToStaticMarkup(
      <ToleranceView content={doc} fileName="test.tolerance" />
    )
    expect(html).toContain('IT8')
  })
})
