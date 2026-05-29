/**
 * WaveformViewer.test.jsx — Vitest + renderToStaticMarkup tests
 *
 * Tests:
 *   1. Empty / no-signal state renders correctly
 *   2. Single-signal waveform renders trace elements
 *   3. Multi-signal waveform renders all signals
 *   4. Meta title is shown in header
 *   5. Legend renders signal names and units
 *   6. data-testid="waveform-viewer" is present when signals exist
 */

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import WaveformViewer from './WaveformViewer.jsx'

// ---------------------------------------------------------------------------
// Test fixture helpers
// ---------------------------------------------------------------------------

function makeSignal(name, units, n = 20) {
  const t = Array.from({ length: n }, (_, i) => i * 1e-9)
  const y = Array.from({ length: n }, (_, i) => Math.sin(i * 0.3) * 1.8)
  return { name, units, t, y }
}

function render(props = {}) {
  return renderToStaticMarkup(<WaveformViewer {...props} />)
}

// ---------------------------------------------------------------------------
// 1. Empty state
// ---------------------------------------------------------------------------

describe('WaveformViewer — empty state', () => {
  it('renders an empty-state message when signals is []', () => {
    const html = render({ data: { signals: [], meta: {} } })
    expect(html).toContain('No waveform signals')
  })

  it('renders empty state when content is empty string', () => {
    const html = render({ content: '' })
    expect(html).toContain('No waveform signals')
  })

  it('renders empty state when content is invalid JSON', () => {
    const html = render({ content: 'not-json' })
    expect(html).toContain('No waveform signals')
  })

  it('renders empty state when signals key is missing', () => {
    const html = render({ content: JSON.stringify({ meta: { title: 'no signals here' } }) })
    expect(html).toContain('No waveform signals')
  })
})

// ---------------------------------------------------------------------------
// 2. Single-signal rendering
// ---------------------------------------------------------------------------

describe('WaveformViewer — single signal', () => {
  const sig = makeSignal('V(out)', 'V', 30)

  it('renders data-testid="waveform-viewer"', () => {
    const html = render({ data: { signals: [sig], meta: {} } })
    expect(html).toContain('data-testid="waveform-viewer"')
  })

  it('renders an SVG polyline for the trace', () => {
    const html = render({ data: { signals: [sig], meta: {} } })
    expect(html).toMatch(/<polyline/)
  })

  it('shows the signal name in the legend', () => {
    const html = render({ data: { signals: [sig], meta: {} } })
    expect(html).toContain('V(out)')
  })

  it('shows the signal units in the legend', () => {
    const html = render({ data: { signals: [sig], meta: {} } })
    expect(html).toContain('(V)')
  })

  it('renders a Time axis label', () => {
    const html = render({ data: { signals: [sig], meta: {} } })
    expect(html).toContain('Time (')
  })

  it('has an aria-label on the SVG', () => {
    const html = render({ data: { signals: [sig], meta: {} } })
    expect(html).toMatch(/aria-label="SPICE waveform: V\(out\)"/)
  })
})

// ---------------------------------------------------------------------------
// 3. Multi-signal rendering
// ---------------------------------------------------------------------------

describe('WaveformViewer — multi signal', () => {
  const signals = [
    makeSignal('V(in)', 'V', 25),
    makeSignal('V(out)', 'V', 25),
    makeSignal('I(R1)', 'A', 25),
  ]

  it('renders a polyline for each signal', () => {
    const html = render({ data: { signals, meta: {} } })
    const count = (html.match(/<polyline/g) || []).length
    expect(count).toBeGreaterThanOrEqual(3)
  })

  it('shows all signal names in the legend', () => {
    const html = render({ data: { signals, meta: {} } })
    expect(html).toContain('V(in)')
    expect(html).toContain('V(out)')
    expect(html).toContain('I(R1)')
  })

  it('shows the signal count in the header', () => {
    const html = render({ data: { signals, meta: {} } })
    expect(html).toContain('3 signals')
  })
})

// ---------------------------------------------------------------------------
// 4. Meta title
// ---------------------------------------------------------------------------

describe('WaveformViewer — meta', () => {
  it('shows meta.title in the header', () => {
    const sig = makeSignal('V(out)', 'V')
    const html = render({ data: { signals: [sig], meta: { title: 'Transient sim test' } } })
    expect(html).toContain('Transient sim test')
  })

  it('shows meta.source in the header', () => {
    const sig = makeSignal('V(out)', 'V')
    const html = render({ data: { signals: [sig], meta: { source: 'rc_filter.cir' } } })
    expect(html).toContain('rc_filter.cir')
  })
})

// ---------------------------------------------------------------------------
// 5. content prop (JSON string)
// ---------------------------------------------------------------------------

describe('WaveformViewer — content prop', () => {
  it('parses a JSON string and renders waveform', () => {
    const sig = makeSignal('V(test)', 'V', 10)
    const content = JSON.stringify({ signals: [sig], meta: { title: 'From content' } })
    const html = render({ content })
    expect(html).toContain('data-testid="waveform-viewer"')
    expect(html).toContain('V(test)')
    expect(html).toContain('From content')
  })
})

// ---------------------------------------------------------------------------
// 6. Trace shape validation — t and y arrays
// ---------------------------------------------------------------------------

describe('WaveformViewer — trace geometry', () => {
  it('polyline points attribute is non-empty when signal has data', () => {
    const sig = makeSignal('V(x)', 'V', 10)
    const html = render({ data: { signals: [sig], meta: {} } })
    // points="..." attribute should have numeric coordinate pairs
    const m = html.match(/points="([^"]+)"/)
    expect(m).not.toBeNull()
    expect(m[1].trim()).not.toBe('')
  })

  it('does not render a polyline for a signal with empty t[]', () => {
    const sig = { name: 'V(empty)', units: 'V', t: [], y: [] }
    const html = render({ data: { signals: [sig], meta: {} } })
    // Signal is defined so waveform viewer renders, but no polyline points
    // are produced for an empty t[] array (clampedPolyline returns empty string)
    expect(html).toContain('data-testid="waveform-viewer"')
    // No <polyline> with a non-trivial points attribute should be present
    const polylineMatches = (html.match(/<polyline[^>]+points="[^"]+"/g) || [])
    expect(polylineMatches.length).toBe(0)
  })
})
