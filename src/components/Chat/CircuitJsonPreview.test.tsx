// CircuitJsonPreview.test.jsx — Vitest smoke tests for CircuitJsonPreview.
//
// We use react-dom/server renderToStaticMarkup (already a project dep) to
// render the component to an HTML string and make structural assertions,
// following the same pattern as Loader.test.jsx and other project component
// tests. This avoids @testing-library/react (not installed) while still
// verifying the component mounts without throwing.
//
// DOMParser / XMLSerializer are not available in the Vitest/jsdom environment
// when running renderToStaticMarkup on the server — circuit-to-svg produces
// SVG strings but parseLibrarySvg gracefully degrades when DOMParser is absent,
// so we still get a rendered shell. The SVG canvas falls back to the "No
// primitives" empty state, which is the expected behaviour in jsdom.

import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CircuitJsonPreview from './CircuitJsonPreview.jsx'
import type { CircuitElement } from '../../types'

// ---------------------------------------------------------------------------
// Minimal Circuit JSON fixture
// ---------------------------------------------------------------------------

// These fixtures are deliberately partial (they only carry the fields the component's
// rendering path reads) and don't structurally satisfy circuit-json's real discriminated
// union — see src/types/circuit.ts's header comment on the same impedance mismatch for
// circuitJsonPatch.js's addFootprint(). Cast rather than fully populate every required
// field of every real element shape.
const MINIMAL_CIRCUIT_JSON = [
  {
    type: 'source_component',
    source_component_id: 'sc1',
    name: 'R1',
    ftype: 'simple_resistor',
    resistance: '10k',
  },
  {
    type: 'source_port',
    source_port_id: 'sp1',
    name: 'plus',
    source_component_id: 'sc1',
  },
  {
    type: 'pcb_component',
    pcb_component_id: 'pbc1',
    source_component_id: 'sc1',
    x: 0,
    y: 0,
    layer: 'top',
  },
  {
    type: 'schematic_component',
    schematic_component_id: 'sch1',
    source_component_id: 'sc1',
    center: { x: 0, y: 0 },
    size: { width: 1, height: 0.5 },
  },
] as unknown as CircuitElement[]

// Stub circuit-to-svg so we don't need the full tscircuit stack in the test
// runner (workers / WASM / browser APIs). The component gracefully handles an
// SVG string that fails to parse.
vi.mock('circuit-to-svg', () => ({
  convertCircuitJsonToSchematicSvg: () => '<svg viewBox="0 0 100 100"><g/></svg>',
  convertCircuitJsonToPcbSvg: () => '<svg viewBox="0 0 100 100"><g/></svg>',
}))

// Stub the api module — Open-in-editor calls api.createFile which needs a
// live server; we just need the import to resolve cleanly.
vi.mock('../../lib/api.js', () => ({
  api: {
    createFile: vi.fn().mockResolvedValue({ id: 'mock-file-id' }),
  },
}))

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CircuitJsonPreview — renders without crashing', () => {
  it('renders a container div for a minimal Circuit JSON array', () => {
    const html = renderToStaticMarkup(
      <CircuitJsonPreview circuitJson={MINIMAL_CIRCUIT_JSON} />,
    )
    // Should produce some HTML rather than throwing
    expect(typeof html).toBe('string')
    expect(html.length).toBeGreaterThan(0)
  })

  it('renders the Schematic tab button', () => {
    const html = renderToStaticMarkup(
      <CircuitJsonPreview circuitJson={MINIMAL_CIRCUIT_JSON} />,
    )
    expect(html).toContain('Schematic')
  })

  it('renders the PCB tab button', () => {
    const html = renderToStaticMarkup(
      <CircuitJsonPreview circuitJson={MINIMAL_CIRCUIT_JSON} />,
    )
    expect(html).toContain('PCB')
  })

  it('does not render "Open in editor" button when projectId is absent', () => {
    const html = renderToStaticMarkup(
      <CircuitJsonPreview circuitJson={MINIMAL_CIRCUIT_JSON} />,
    )
    expect(html).not.toContain('Open in editor')
  })

  it('renders "Open in editor" button when projectId is provided', () => {
    const html = renderToStaticMarkup(
      <CircuitJsonPreview circuitJson={MINIMAL_CIRCUIT_JSON} projectId="proj-123" />,
    )
    expect(html).toContain('Open in editor')
  })

  it('shows empty-state message for an empty array', () => {
    const html = renderToStaticMarkup(
      <CircuitJsonPreview circuitJson={[]} />,
    )
    expect(html).toContain('Empty circuit JSON')
  })

  it('does not crash when circuitJson has only source_ items', () => {
    const sourceOnly = [
      { type: 'source_component', source_component_id: 'sc1', name: 'C1', ftype: 'simple_capacitor' },
    ] as unknown as CircuitElement[]
    const html = renderToStaticMarkup(
      <CircuitJsonPreview circuitJson={sourceOnly} />,
    )
    expect(typeof html).toBe('string')
    expect(html.length).toBeGreaterThan(0)
  })
})
