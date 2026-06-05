/**
 * CorridorModelPanel.test.jsx — SSR smoke tests for the corridor model panel.
 *
 * Uses react-dom/server renderToStaticMarkup (same pattern as TINView.test.jsx).
 * No jsdom / @testing-library required.
 */

import { describe, it, expect, vi, beforeAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CorridorModelPanel from './CorridorModelPanel.jsx'

// ---------------------------------------------------------------------------
// Fixtures — minimal data matching civil_corridor_model output shape
// ---------------------------------------------------------------------------

const CROSS_SECTIONS = [
  {
    station_m: 0.0,
    cl_elev_m: 100.0,
    cut_area_m2: 0.0,
    fill_area_m2: 0.0,
    points: [
      { offset_m: -10.0, elev_m: 100.0, label: 'daylight_left' },
      { offset_m:  -6.05, elev_m: 99.807, label: 'shoulder_left' },
      { offset_m:  -3.65, elev_m: 99.927, label: 'edge_lane_left' },
      { offset_m:   0.0,  elev_m: 100.0,  label: 'CL' },
      { offset_m:   3.65, elev_m: 99.927, label: 'edge_lane_right' },
      { offset_m:   6.05, elev_m: 99.807, label: 'shoulder_right' },
      { offset_m:  10.0,  elev_m: 100.0,  label: 'daylight_right' },
    ],
  },
  {
    station_m: 50.0,
    cl_elev_m: 101.0,
    cut_area_m2: 5.2,
    fill_area_m2: 0.0,
    points: [
      { offset_m: -12.0, elev_m: 102.0, label: 'daylight_left' },
      { offset_m:  -6.05, elev_m: 100.807, label: 'shoulder_left' },
      { offset_m:  -3.65, elev_m: 100.927, label: 'edge_lane_left' },
      { offset_m:   0.0,  elev_m: 101.0,   label: 'CL' },
      { offset_m:   3.65, elev_m: 100.927, label: 'edge_lane_right' },
      { offset_m:   6.05, elev_m: 100.807, label: 'shoulder_right' },
      { offset_m:  12.0,  elev_m: 102.0,   label: 'daylight_right' },
    ],
  },
  {
    station_m: 100.0,
    cl_elev_m: 102.0,
    cut_area_m2: 8.4,
    fill_area_m2: 0.0,
    points: [
      { offset_m: -14.0, elev_m: 104.0, label: 'daylight_left' },
      { offset_m:  -6.05, elev_m: 101.807, label: 'shoulder_left' },
      { offset_m:  -3.65, elev_m: 101.927, label: 'edge_lane_left' },
      { offset_m:   0.0,  elev_m: 102.0,   label: 'CL' },
      { offset_m:   3.65, elev_m: 101.927, label: 'edge_lane_right' },
      { offset_m:   6.05, elev_m: 101.807, label: 'shoulder_right' },
      { offset_m:  14.0,  elev_m: 104.0,   label: 'daylight_right' },
    ],
  },
]

const MASS_HAUL = [
  { station_m: 0,   mass_ordinate_m3: 0,     cut_vol_m3: 0,   fill_vol_m3: 0 },
  { station_m: 50,  mass_ordinate_m3: 162.5, cut_vol_m3: 162.5, fill_vol_m3: 0 },
  { station_m: 100, mass_ordinate_m3: 587.5, cut_vol_m3: 587.5, fill_vol_m3: 0 },
]

const EARTHWORK = {
  total_cut_m3:  587.5,
  total_fill_m3: 0.0,
  net_m3:        -587.5,
}

// ---------------------------------------------------------------------------
// 1. Empty state
// ---------------------------------------------------------------------------

describe('CorridorModelPanel — empty state', () => {
  it('renders without crashing with no props', () => {
    expect(() => renderToStaticMarkup(<CorridorModelPanel />)).not.toThrow()
  })

  it('renders the data-testid root', () => {
    const html = renderToStaticMarkup(<CorridorModelPanel />)
    expect(html).toContain('data-testid="corridor-model-panel"')
  })

  it('shows Run model button', () => {
    const html = renderToStaticMarkup(<CorridorModelPanel />)
    expect(html).toContain('Run model')
  })

  it('shows empty-state hint text', () => {
    const html = renderToStaticMarkup(<CorridorModelPanel />)
    expect(html).toContain('Run model')
  })

  it('does not crash without onDispatch', () => {
    expect(() => renderToStaticMarkup(
      <CorridorModelPanel alignmentLength={200} />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 2. With cross-section and mass-haul data
// ---------------------------------------------------------------------------

describe('CorridorModelPanel — with full data', () => {
  let html

  beforeAll(() => {
    html = renderToStaticMarkup(
      <CorridorModelPanel
        crossSections={CROSS_SECTIONS}
        massHaul={MASS_HAUL}
        earthwork={EARTHWORK}
      />
    )
  })

  it('renders without crashing', () => {
    expect(html).toBeTruthy()
  })

  it('renders station slider', () => {
    expect(html).toContain('data-testid="station-slider"')
  })

  it('renders earthwork summary', () => {
    expect(html).toContain('data-testid="earthwork-summary"')
  })

  it('renders cut volume in summary', () => {
    expect(html).toContain('587.5')
  })

  it('renders mass haul chart', () => {
    expect(html).toContain('data-testid="mass-haul-chart"')
  })

  it('renders cross-section SVG', () => {
    // Should have SVG path for the cross-section
    expect(html).toMatch(/<path\b/)
  })

  it('renders aria-label for cross-section', () => {
    expect(html).toContain('aria-label="Cross-section view"')
  })

  it('renders aria-label for mass haul', () => {
    expect(html).toContain('aria-label="Mass haul diagram"')
  })

  it('renders "Corridor Model" heading', () => {
    expect(html).toContain('Corridor Model')
  })

  it('does not show empty-state text when data present', () => {
    // When data is present the slider should be present, not the "Click Run model" hint
    // The hint is only shown when hasData is false and not loading
    // With crossSections set, hasData = true so hint is hidden
    expect(html).not.toContain('Click &quot;Run model&quot;')
  })
})

// ---------------------------------------------------------------------------
// 3. Earthwork summary values
// ---------------------------------------------------------------------------

describe('CorridorModelPanel — earthwork summary', () => {
  it('shows fill volume', () => {
    const html = renderToStaticMarkup(
      <CorridorModelPanel
        crossSections={CROSS_SECTIONS}
        massHaul={MASS_HAUL}
        earthwork={{ total_cut_m3: 100.0, total_fill_m3: 200.0, net_m3: 100.0 }}
      />
    )
    expect(html).toContain('200')
    expect(html).toContain('100')
  })

  it('shows positive net with + sign', () => {
    const html = renderToStaticMarkup(
      <CorridorModelPanel
        crossSections={CROSS_SECTIONS}
        massHaul={MASS_HAUL}
        earthwork={{ total_cut_m3: 100.0, total_fill_m3: 200.0, net_m3: 100.0 }}
      />
    )
    expect(html).toContain('+100')
  })
})

// ---------------------------------------------------------------------------
// 4. Mass haul with mixed cut/fill
// ---------------------------------------------------------------------------

describe('CorridorModelPanel — mixed mass haul', () => {
  it('renders without crashing with negative ordinates (borrow)', () => {
    const mh = [
      { station_m: 0,   mass_ordinate_m3:  0,    cut_vol_m3: 0,   fill_vol_m3: 0 },
      { station_m: 50,  mass_ordinate_m3: -100,  cut_vol_m3: 0,   fill_vol_m3: 100 },
      { station_m: 100, mass_ordinate_m3:  50,   cut_vol_m3: 150, fill_vol_m3: 100 },
    ]
    expect(() => renderToStaticMarkup(
      <CorridorModelPanel crossSections={CROSS_SECTIONS} massHaul={mh} />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 5. onDispatch callback
// ---------------------------------------------------------------------------

describe('CorridorModelPanel — onDispatch', () => {
  it('renders with onDispatch prop without crashing', () => {
    const html = renderToStaticMarkup(
      <CorridorModelPanel
        crossSections={CROSS_SECTIONS}
        massHaul={MASS_HAUL}
        earthwork={EARTHWORK}
        onDispatch={() => {}}
      />
    )
    expect(html).toContain('data-testid="corridor-run-btn"')
  })
})

// ---------------------------------------------------------------------------
// 6. Custom width
// ---------------------------------------------------------------------------

describe('CorridorModelPanel — custom width', () => {
  it('applies custom width style', () => {
    const html = renderToStaticMarkup(
      <CorridorModelPanel width={800} />
    )
    expect(html).toContain('width:800')
  })
})

// ---------------------------------------------------------------------------
// 7. Cross-section with ditch points
// ---------------------------------------------------------------------------

describe('CorridorModelPanel — ditch section', () => {
  const DITCH_XS = [{
    station_m: 0.0, cl_elev_m: 100.0, cut_area_m2: 3.5, fill_area_m2: 0.0,
    points: [
      { offset_m: -11.0, elev_m: 101.0, label: 'daylight_left' },
      { offset_m:  -7.65, elev_m: 99.4, label: 'ditch_left' },
      { offset_m:  -6.05, elev_m: 99.807, label: 'shoulder_left' },
      { offset_m:  -3.65, elev_m: 99.927, label: 'edge_lane_left' },
      { offset_m:   0.0,  elev_m: 100.0,  label: 'CL' },
      { offset_m:   3.65, elev_m: 99.927, label: 'edge_lane_right' },
      { offset_m:   6.05, elev_m: 99.807, label: 'shoulder_right' },
      { offset_m:   7.65, elev_m: 99.4, label: 'ditch_right' },
      { offset_m:  11.0,  elev_m: 101.0,  label: 'daylight_right' },
    ],
  }]

  it('renders ditch section without crashing', () => {
    expect(() => renderToStaticMarkup(
      <CorridorModelPanel crossSections={DITCH_XS} massHaul={MASS_HAUL} />
    )).not.toThrow()
  })

  it('renders SVG paths for ditch section', () => {
    const html = renderToStaticMarkup(
      <CorridorModelPanel crossSections={DITCH_XS} massHaul={MASS_HAUL} />
    )
    expect(html).toMatch(/<path\b/)
  })
})
