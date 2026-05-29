/**
 * PipeNetworkView.test.jsx — SSR smoke tests for the pipe network viewport.
 *
 * Uses react-dom/server renderToStaticMarkup (no jsdom / @testing-library).
 */
import { describe, it, expect, beforeAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import PipeNetworkView from './PipeNetworkView.jsx'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const NODES = [
  { id: 'J1', x: 0,  y: 0,  elevation_m: 10, demand_m3s: 0.005 },
  { id: 'J2', x: 50, y: 0,  elevation_m: 8,  demand_m3s: 0.003 },
  { id: 'J3', x: 50, y: 40, elevation_m: 6,  demand_m3s: 0.004 },
]

const RESERVOIRS = [
  { id: 'R1', x: -30, y: 20, head_m: 40 },
]

const PIPES = [
  { id: 'P1', node_a: 'R1', node_b: 'J1', length_m: 120, diameter_m: 0.25, roughness: 130 },
  { id: 'P2', node_a: 'J1', node_b: 'J2', length_m: 100, diameter_m: 0.20, roughness: 130 },
  { id: 'P3', node_a: 'J2', node_b: 'J3', length_m:  80, diameter_m: 0.15, roughness: 130 },
]

const RESULTS = {
  pipe_flows_m3s: { P1: 0.012, P2: 0.007, P3: 0.004 },
  nodal_heads_m:  { J1: 38.1, J2: 35.4, J3: 32.1 },
  nodal_pressures_m: { J1: 28.1, J2: 27.4, J3: 26.1 },
  converged: true,
  iterations: 8,
  residual: 1e-8,
}

// ---------------------------------------------------------------------------
// 1. Empty / default state
// ---------------------------------------------------------------------------

describe('PipeNetworkView — empty state', () => {
  it('renders without crashing with no props', () => {
    expect(() => renderToStaticMarkup(<PipeNetworkView />)).not.toThrow()
  })

  it('shows fallback text when no nodes', () => {
    const html = renderToStaticMarkup(<PipeNetworkView />)
    expect(html).toContain('No network data')
  })

  it('renders an SVG root', () => {
    const html = renderToStaticMarkup(<PipeNetworkView />)
    expect(html).toMatch(/<svg\b/)
  })

  it('has aria-label on the SVG', () => {
    const html = renderToStaticMarkup(<PipeNetworkView />)
    expect(html).toContain('aria-label="Pipe network plan view"')
  })

  it('has data-testid="pipe-network-view"', () => {
    const html = renderToStaticMarkup(<PipeNetworkView />)
    expect(html).toContain('data-testid="pipe-network-view"')
  })
})

// ---------------------------------------------------------------------------
// 2. With full network data
// ---------------------------------------------------------------------------

describe('PipeNetworkView — with nodes, pipes, reservoirs', () => {
  let html

  beforeAll(() => {
    html = renderToStaticMarkup(
      <PipeNetworkView
        nodes={NODES}
        pipes={PIPES}
        reservoirs={RESERVOIRS}
      />
    )
  })

  it('renders without crashing', () => {
    expect(html).toBeTruthy()
  })

  it('does not show the empty-state message', () => {
    expect(html).not.toContain('No network data')
  })

  it('renders a line element for each pipe', () => {
    const lines = html.match(/<line\b/g) || []
    // At least 3 pipe lines (P1, P2, P3) plus legend lines
    expect(lines.length).toBeGreaterThanOrEqual(3)
  })

  it('renders circles for nodes and reservoirs', () => {
    const circles = html.match(/<circle\b/g) || []
    expect(circles.length).toBeGreaterThanOrEqual(4)   // 3 junctions + 1 reservoir
  })

  it('renders the solve button', () => {
    expect(html).toContain('Run network solve')
    expect(html).toContain('data-testid="pipe-solve-btn"')
  })
})

// ---------------------------------------------------------------------------
// 3. Dispatches civil_water_network_solve
// ---------------------------------------------------------------------------

describe('PipeNetworkView — onDispatch dispatches correct tool', () => {
  it('renders with onDispatch prop without crashing', () => {
    const dispatched = []
    expect(() => renderToStaticMarkup(
      <PipeNetworkView
        nodes={NODES}
        pipes={PIPES}
        reservoirs={RESERVOIRS}
        onDispatch={(d) => dispatched.push(d)}
      />
    )).not.toThrow()
  })

  it('includes pipe data-testid attributes for each pipe', () => {
    const html = renderToStaticMarkup(
      <PipeNetworkView nodes={NODES} pipes={PIPES} reservoirs={RESERVOIRS} />
    )
    expect(html).toContain('data-testid="pipe-P1"')
    expect(html).toContain('data-testid="pipe-P2"')
    expect(html).toContain('data-testid="pipe-P3"')
  })
})

// ---------------------------------------------------------------------------
// 4. Pre-computed results overlay
// ---------------------------------------------------------------------------

describe('PipeNetworkView — with pre-computed results', () => {
  let html

  beforeAll(() => {
    html = renderToStaticMarkup(
      <PipeNetworkView
        nodes={NODES}
        pipes={PIPES}
        reservoirs={RESERVOIRS}
        results={RESULTS}
      />
    )
  })

  it('renders without crashing', () => {
    expect(html).toBeTruthy()
  })

  it('shows convergence status', () => {
    expect(html).toContain('Converged')
  })

  it('shows iteration count', () => {
    expect(html).toContain('8 iter')
  })
})

// ---------------------------------------------------------------------------
// 5. Custom dimensions
// ---------------------------------------------------------------------------

describe('PipeNetworkView — custom dimensions', () => {
  it('respects width/height props', () => {
    const html = renderToStaticMarkup(
      <PipeNetworkView nodes={NODES} pipes={PIPES} width={800} height={500} />
    )
    expect(html).toContain('width="800"')
    expect(html).toContain('height="500"')
  })
})
