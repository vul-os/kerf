// ThermalNetworkViewer.test.jsx — vitest smoke tests for the SVG thermal
// network visualisation component.
//
// We use react-dom/server renderToStaticMarkup (a project dep, already in
// use by Loader.test.jsx) rather than @testing-library/react so we don't need
// any new npm dependencies.

import { describe, it, expect, beforeAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ThermalNetworkViewer from './ThermalNetworkViewer.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const THREE_NODE_NETWORK = {
  nodes: [
    { id: 'hot',  label: 'Heat source', temperature_K: 500 },
    { id: 'mid',  label: 'Junction',    temperature_K: 350 },
    { id: 'cold', label: 'Heat sink',   temperature_K: 280 },
  ],
  links: [
    { from_id: 'hot',  to_id: 'mid',  type: 'conductive', flux_W: 120 },
    { from_id: 'mid',  to_id: 'cold', type: 'radiative',  flux_W:  80 },
  ],
}

const EMPTY_NETWORK = { nodes: [], links: [] }

const NO_TEMP_NETWORK = {
  nodes: [
    { id: 'A', label: 'Node A' },
    { id: 'B', label: 'Node B' },
  ],
  links: [
    { from_id: 'A', to_id: 'B' },
  ],
}

// ---------------------------------------------------------------------------
// 1. Basic render
// ---------------------------------------------------------------------------

describe('ThermalNetworkViewer — 3-node network', () => {
  let html

  // Render once and reuse for all assertions
  beforeAll(() => {
    html = renderToStaticMarkup(<ThermalNetworkViewer network={THREE_NODE_NETWORK} />)
  })

  it('renders without throwing', () => {
    expect(html).toBeTruthy()
  })

  it('outputs an SVG root element', () => {
    expect(html).toMatch(/<svg\b/)
  })

  it('carries aria-label="Thermal network graph"', () => {
    expect(html).toMatch(/aria-label="Thermal network graph"/)
  })

  it('carries role="img"', () => {
    expect(html).toMatch(/role="img"/)
  })

  it('uses the default 600×400 viewport', () => {
    expect(html).toMatch(/width="600"/)
    expect(html).toMatch(/height="400"/)
  })

  it('renders circles for all three nodes', () => {
    // Each node gets at least one <circle> (the bubble itself)
    const circles = html.match(/<circle\b/g) || []
    // 3 nodes × 2 circles each (shadow + bubble) = 6
    expect(circles.length).toBeGreaterThanOrEqual(3)
  })

  it('renders a <line> for each link', () => {
    const lines = html.match(/<line\b/g) || []
    expect(lines.length).toBe(2)
  })

  it('includes a markerEnd attribute on links (arrow heads)', () => {
    // React serialises markerEnd as marker-end in static markup
    expect(html).toMatch(/marker-end="url\(#/)
  })

  it('renders flux labels for links with flux_W', () => {
    // Both links have flux_W so both labels should appear
    expect(html).toMatch(/120\.0 W/)
    expect(html).toMatch(/80\.0 W/)
  })

  it('uses a dashed stroke for the radiative link', () => {
    expect(html).toMatch(/strokeDasharray|stroke-dasharray/)
  })

  it('renders node labels', () => {
    // truncated at 6 chars: "Heat s" (Heat source), "Juncti" (Junction), "Heat s"
    expect(html).toMatch(/Heat s/)
    expect(html).toMatch(/Juncti/)
  })

  it('renders temperature labels in °C', () => {
    // 500 K → 226.8 °C, 350 K → 76.8 °C, 280 K → 6.8 °C
    expect(html).toMatch(/226\./)
    expect(html).toMatch(/76\./)
    expect(html).toMatch(/6\./)
  })
})

// ---------------------------------------------------------------------------
// 2. Custom dimensions
// ---------------------------------------------------------------------------

describe('ThermalNetworkViewer — custom dimensions', () => {
  it('respects width/height props', () => {
    const html = renderToStaticMarkup(
      <ThermalNetworkViewer network={THREE_NODE_NETWORK} width={800} height={500} />
    )
    expect(html).toMatch(/width="800"/)
    expect(html).toMatch(/height="500"/)
  })

  it('includes the custom className on the SVG root', () => {
    const html = renderToStaticMarkup(
      <ThermalNetworkViewer network={THREE_NODE_NETWORK} className="my-viewer" />
    )
    expect(html).toMatch(/class="my-viewer"/)
  })
})

// ---------------------------------------------------------------------------
// 3. Empty network
// ---------------------------------------------------------------------------

describe('ThermalNetworkViewer — empty network', () => {
  it('renders without crashing', () => {
    expect(() => renderToStaticMarkup(
      <ThermalNetworkViewer network={EMPTY_NETWORK} />
    )).not.toThrow()
  })

  it('renders an SVG with "No nodes" fallback text', () => {
    const html = renderToStaticMarkup(<ThermalNetworkViewer network={EMPTY_NETWORK} />)
    expect(html).toMatch(/<svg\b/)
    expect(html).toContain('No nodes')
  })
})

// ---------------------------------------------------------------------------
// 4. Network without temperature data
// ---------------------------------------------------------------------------

describe('ThermalNetworkViewer — nodes without temperature_K', () => {
  it('renders without crashing', () => {
    expect(() => renderToStaticMarkup(
      <ThermalNetworkViewer network={NO_TEMP_NETWORK} />
    )).not.toThrow()
  })

  it('still renders node circles', () => {
    const html = renderToStaticMarkup(
      <ThermalNetworkViewer network={NO_TEMP_NETWORK} />
    )
    const circles = html.match(/<circle\b/g) || []
    expect(circles.length).toBeGreaterThanOrEqual(2)
  })

  it('omits temperature sub-labels when temperature_K is absent', () => {
    const html = renderToStaticMarkup(
      <ThermalNetworkViewer network={NO_TEMP_NETWORK} />
    )
    // Neither node has temperature_K so no °C text should appear
    expect(html).not.toMatch(/°C/)
  })
})

// ---------------------------------------------------------------------------
// 5. Null / missing network prop
// ---------------------------------------------------------------------------

describe('ThermalNetworkViewer — null network prop', () => {
  it('renders without crashing when network is null', () => {
    expect(() => renderToStaticMarkup(
      <ThermalNetworkViewer network={null} />
    )).not.toThrow()
  })

  it('renders without crashing when network is undefined', () => {
    expect(() => renderToStaticMarkup(
      <ThermalNetworkViewer network={undefined} />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 6. SVG structure integrity
// ---------------------------------------------------------------------------

describe('ThermalNetworkViewer — SVG structural integrity', () => {
  const html = renderToStaticMarkup(
    <ThermalNetworkViewer network={THREE_NODE_NETWORK} />
  )

  it('includes an arrowhead marker definition', () => {
    expect(html).toMatch(/<marker\b/)
    expect(html).toMatch(/orient="auto"/)
  })

  it('includes a background rect', () => {
    expect(html).toMatch(/<rect\b/)
  })

  it('closes the SVG element', () => {
    expect(html).toMatch(/<\/svg>/)
  })
})
