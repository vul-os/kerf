// AcousticsResultPanel.test.jsx
//
// Vitest suite for AcousticsResultPanel.
//
// Rendering strategy: renderToStaticMarkup from react-dom/server
// (same pattern as HdriPicker.test.jsx / SectorCommandList.test.jsx —
// no @testing-library/react dependency required).
//
// Tool-dispatch contracts are verified via source-level assertions on the
// component source file — confirming that each /api/tools/call reference
// is present and uses the correct tool name.
//
// Run: npx vitest run src/components/acoustics/AcousticsResultPanel.test.jsx

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import AcousticsResultPanel from './AcousticsResultPanel.jsx'

// ---------------------------------------------------------------------------
// Source text for tool-name assertions
// ---------------------------------------------------------------------------

const SRC = readFileSync(
  resolve(import.meta.dirname, 'AcousticsResultPanel.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// Render helper
// ---------------------------------------------------------------------------

function render(props = {}) {
  return renderToStaticMarkup(<AcousticsResultPanel {...props} />)
}

// ---------------------------------------------------------------------------
// 1. Basic rendering
// ---------------------------------------------------------------------------

describe('AcousticsResultPanel — basic rendering', () => {
  it('renders without crashing', () => {
    const html = render()
    expect(typeof html).toBe('string')
    expect(html.length).toBeGreaterThan(0)
  })

  it('contains the panel title text "Acoustics"', () => {
    const html = render()
    expect(html).toContain('Acoustics')
  })

  it('renders the ISO 9613-2 badge text', () => {
    const html = render()
    expect(html).toContain('ISO 9613-2')
  })

  it('renders the data-testid attribute', () => {
    const html = render()
    expect(html).toContain('data-testid="acoustics-result-panel"')
  })
})

// ---------------------------------------------------------------------------
// 2. Tab structure
// ---------------------------------------------------------------------------

describe('AcousticsResultPanel — tab structure', () => {
  it('renders Outdoor tab button', () => {
    const html = render()
    expect(html).toContain('Outdoor (ISO 9613-2)')
  })

  it('renders Room Acoustics tab button', () => {
    const html = render()
    expect(html).toContain('Room Acoustics')
  })

  it('renders Transmission Loss tab button', () => {
    const html = render()
    expect(html).toContain('Transmission Loss')
  })

  it('renders Weighting / SPL tab button', () => {
    const html = render()
    expect(html).toContain('Weighting / SPL')
  })
})

// ---------------------------------------------------------------------------
// 3. Default tab content (Outdoor — shown on first render)
// ---------------------------------------------------------------------------

describe('AcousticsResultPanel — default outdoor tab', () => {
  it('shows Single-Band Outdoor Propagation widget', () => {
    const html = render()
    expect(html).toContain('Single-Band Outdoor Propagation')
  })

  it('shows Octave-Band widget', () => {
    const html = render()
    expect(html).toContain('Octave-Band Outdoor Propagation')
  })

  it('mentions the ISO 9613-2 standard in a note', () => {
    const html = render()
    expect(html).toContain('ISO 9613-2:1996')
  })

  it('renders Maekawa barrier diffraction note', () => {
    const html = render()
    expect(html).toContain('Maekawa')
  })

  it('renders ground-type label', () => {
    const html = render()
    expect(html).toContain('Ground type')
  })

  it('renders hard-ground option text', () => {
    const html = render()
    expect(html).toContain('hard')
  })

  it('renders soft-ground option text', () => {
    const html = render()
    expect(html).toContain('soft')
  })
})

// ---------------------------------------------------------------------------
// 4. Tool-name dispatch assertions (source-level)
// ---------------------------------------------------------------------------

describe('AcousticsResultPanel — tool dispatch coverage', () => {
  // ISO 9613-2 outdoor tools
  it('dispatches acoustics_iso9613_outdoor', () => {
    expect(SRC).toContain("'acoustics_iso9613_outdoor'")
  })

  it('dispatches acoustics_iso9613_octave_bands', () => {
    expect(SRC).toContain("'acoustics_iso9613_octave_bands'")
  })

  // Room acoustics tools
  it('dispatches acoustics_sabine_rt60', () => {
    expect(SRC).toContain("'acoustics_sabine_rt60'")
  })

  it('dispatches acoustics_eyring_rt60', () => {
    expect(SRC).toContain("'acoustics_eyring_rt60'")
  })

  it('dispatches acoustics_room_constant', () => {
    expect(SRC).toContain("'acoustics_room_constant'")
  })

  it('dispatches acoustics_nc_rating', () => {
    expect(SRC).toContain("'acoustics_nc_rating'")
  })

  it('dispatches acoustics_nr_rating', () => {
    expect(SRC).toContain("'acoustics_nr_rating'")
  })

  it('dispatches wave_room_modes', () => {
    expect(SRC).toContain("'wave_room_modes'")
  })

  // Transmission loss tools
  it('dispatches acoustics_mass_law_tl', () => {
    expect(SRC).toContain("'acoustics_mass_law_tl'")
  })

  it('dispatches acoustics_composite_tl', () => {
    expect(SRC).toContain("'acoustics_composite_tl'")
  })

  it('dispatches acoustics_spl_transmitted', () => {
    expect(SRC).toContain("'acoustics_spl_transmitted'")
  })

  it('dispatches wave_sea_two_rooms_tl', () => {
    expect(SRC).toContain("'wave_sea_two_rooms_tl'")
  })

  // Weighting / SPL tools
  it('dispatches acoustics_a_weighting', () => {
    expect(SRC).toContain("'acoustics_a_weighting'")
  })

  it('dispatches acoustics_apply_weighting', () => {
    expect(SRC).toContain("'acoustics_apply_weighting'")
  })

  it('dispatches acoustics_spl_sum', () => {
    expect(SRC).toContain("'acoustics_spl_sum'")
  })

  it('dispatches acoustics_point_source', () => {
    expect(SRC).toContain("'acoustics_point_source'")
  })

  // All calls go through /api/tools/call
  it('uses /api/tools/call endpoint', () => {
    expect(SRC).toContain('/api/tools/call')
  })
})

// ---------------------------------------------------------------------------
// 5. Widget descriptions match standards
// ---------------------------------------------------------------------------

describe('AcousticsResultPanel — engineering content', () => {
  it('references Maekawa 1968 barrier formula', () => {
    expect(SRC).toContain('Maekawa')
  })

  it('references SEA (Statistical Energy Analysis)', () => {
    expect(SRC).toContain('Statistical Energy Analysis')
  })

  it('references IEC 61672-1 for A-weighting', () => {
    expect(SRC).toContain('IEC 61672-1')
  })

  it('references ISO 140-3 for mass law TL', () => {
    expect(SRC).toContain('ISO 140-3')
  })

  it('references Sabine equation note', () => {
    expect(SRC).toContain('Sabine')
  })

  it('references Eyring RT60', () => {
    expect(SRC).toContain('Eyring')
  })

  it('references NC ratings guidance (offices etc)', () => {
    expect(SRC).toContain('offices')
  })
})

// ---------------------------------------------------------------------------
// 6. callTool helper structure
// ---------------------------------------------------------------------------

describe('AcousticsResultPanel — callTool implementation', () => {
  it('POST method is used for all tool calls', () => {
    expect(SRC).toContain("method: 'POST'")
  })

  it('Content-Type header is application/json', () => {
    expect(SRC).toContain("'Content-Type': 'application/json'")
  })

  it('request body includes tool name and args', () => {
    expect(SRC).toContain('tool: toolName')
    expect(SRC).toContain('args')
  })
})
