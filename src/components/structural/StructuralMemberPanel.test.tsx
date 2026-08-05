/**
 * StructuralMemberPanel.test.jsx — Vitest suite for the AISC 360-22 / ACI 318-19 panel.
 *
 * Tests the static render structure (tabs, form rows, labels) using
 * react-dom/server renderToStaticMarkup — no DOM or browser required.
 * Interaction tests (click, fetch) are omitted (no jsdom in this project).
 */

import { describe, it, expect, vi, beforeAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// ── Stub lucide-react icons ───────────────────────────────────────────────────
vi.mock('lucide-react', () => {
  const icon = () => '<svg />'
  return {
    Cpu: icon, Layers: icon, Ruler: icon,
    AlertTriangle: icon, CheckCircle: icon,
    Loader2: icon, Play: icon, ChevronDown: icon, ChevronUp: icon,
    TrendingDown: icon,
  }
})

import StructuralMemberPanel from './StructuralMemberPanel.jsx'

// ── 1. Root render ────────────────────────────────────────────────────────────

describe('StructuralMemberPanel root', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(<StructuralMemberPanel />)).not.toThrow()
  })

  it('contains the panel title text', () => {
    const html = renderToStaticMarkup(<StructuralMemberPanel />)
    expect(html).toContain('Structural Member Design')
  })

  it('mentions AISC 360-22 in the subtitle', () => {
    const html = renderToStaticMarkup(<StructuralMemberPanel />)
    expect(html).toContain('AISC 360-22')
  })

  it('mentions ACI 318-19 in the subtitle', () => {
    const html = renderToStaticMarkup(<StructuralMemberPanel />)
    expect(html).toContain('ACI 318-19')
  })
})

// ── 2. Tab navigation items ───────────────────────────────────────────────────

describe('StructuralMemberPanel tabs', () => {
  it('renders Steel Member tab label', () => {
    const html = renderToStaticMarkup(<StructuralMemberPanel />)
    expect(html).toContain('Steel Member')
  })

  it('renders RC Beam tab label', () => {
    const html = renderToStaticMarkup(<StructuralMemberPanel />)
    expect(html).toContain('RC Beam')
  })

  it('renders Rebar Detailing tab label', () => {
    const html = renderToStaticMarkup(<StructuralMemberPanel />)
    expect(html).toContain('Rebar Detailing')
  })
})

// ── 3. Default tab (Steel Member) content ────────────────────────────────────

describe('StructuralMemberPanel steel tab (default)', () => {
  let html

  beforeAll(() => {
    html = renderToStaticMarkup(<StructuralMemberPanel />)
  })

  it('shows Full Member Check section title', () => {
    expect(html).toContain('Full Member Check')
  })

  it('shows Chapter E section title', () => {
    expect(html).toContain('Chapter E')
  })

  it('shows Chapter F section title', () => {
    expect(html).toContain('Chapter F')
  })

  it('mentions H1-1a/b in the Ch H title', () => {
    expect(html).toContain('H1-1')
  })

  it('shows W-shape designations in select', () => {
    expect(html).toContain('W14X90')
  })

  it('shows HSS_rect as section type option', () => {
    expect(html).toContain('HSS_rect')
  })

  it('shows Fy label', () => {
    expect(html).toContain('Fy')
  })

  it('shows Lb label', () => {
    expect(html).toContain('Lb')
  })

  it('shows Cb label', () => {
    expect(html).toContain('Cb')
  })

  it('shows Pu label', () => {
    expect(html).toContain('Pu')
  })

  it('shows Mux label', () => {
    expect(html).toContain('Mux')
  })

  it('includes LRFD reference text', () => {
    expect(html).toContain('LRFD')
  })

  it('includes ASD reference text', () => {
    expect(html).toContain('ASD')
  })

  it('shows at least one Run button', () => {
    expect(html).toContain('Run')
  })

  it('cites AISC 360-22 §E3 in the reference note', () => {
    expect(html).toContain('AISC 360-22')
  })
})

// ── 4. Section type options present ──────────────────────────────────────────

describe('StructuralMemberPanel section types', () => {
  const html = renderToStaticMarkup(<StructuralMemberPanel />)

  ;['W', 'C', 'HSS_rect', 'HSS_round', 'Pipe', 'Angle'].forEach(type => {
    it(`renders section type option "${type}"`, () => {
      expect(html).toContain(type)
    })
  })
})

// ── 5. W-shape catalogue present ─────────────────────────────────────────────

describe('StructuralMemberPanel W-shape catalogue', () => {
  const html = renderToStaticMarkup(<StructuralMemberPanel />)
  const shapes = ['W14X90', 'W18X50', 'W21X68', 'W24X76', 'W36X135']

  shapes.forEach(s => {
    it(`contains shape "${s}" in the UI`, () => {
      expect(html).toContain(s)
    })
  })
})
