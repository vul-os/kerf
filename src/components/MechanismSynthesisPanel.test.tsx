// MechanismSynthesisPanel.test.jsx
//
// Vitest suite for MechanismSynthesisPanel (Burmester four-bar, cam-follower,
// gear-train synthesis).
//
// Rendering strategy: renderToStaticMarkup from react-dom/server
// (no @testing-library/react required — same pattern as AcousticsResultPanel.test.jsx).
//
// Tiers:
//   1. Source-level assertions — tool names + data-testid landmarks
//   2. CouplerCurvePlot pure SVG rendering — input/output contract
//   3. CamProfileChart pure SVG rendering — input/output contract
//   4. renderToStaticMarkup smoke tests of the full panel in each tab
//
// Run: npx vitest run src/components/MechanismSynthesisPanel.test.jsx

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import MechanismSynthesisPanel, {
  CouplerCurvePlot,
  CamProfileChart,
} from './MechanismSynthesisPanel.jsx'

// ---------------------------------------------------------------------------
// Source text for Tier 1 assertions
// ---------------------------------------------------------------------------

const SRC = readFileSync(
  resolve(import.meta.dirname, 'MechanismSynthesisPanel.jsx'),
  'utf8',
)

// ---------------------------------------------------------------------------
// 1. Source-level assertions
// ---------------------------------------------------------------------------

describe('MechanismSynthesisPanel source — tool dispatch', () => {
  it('references synthesise_four_bar tool', () => {
    expect(SRC).toContain("'synthesise_four_bar'")
  })

  it('references generate_coupler_curve tool', () => {
    expect(SRC).toContain("'generate_coupler_curve'")
  })

  it('references synthesise_cam tool', () => {
    expect(SRC).toContain("'synthesise_cam'")
  })

  it('references synthesise_gear_train tool', () => {
    expect(SRC).toContain("'synthesise_gear_train'")
  })

  it('calls /api/tools/call endpoint', () => {
    expect(SRC).toContain('/api/tools/call')
  })
})

describe('MechanismSynthesisPanel source — data-testid landmarks', () => {
  it('has data-testid="mechanism-synthesis-panel"', () => {
    expect(SRC).toContain('data-testid="mechanism-synthesis-panel"')
  })

  it('has tab-fourbar button (via template literal)', () => {
    // Tab IDs are set via template literal: data-testid={`tab-${tab.id}`}
    // Verify the pattern is present (dynamic generation of tab-fourbar, tab-cam, tab-gear)
    expect(SRC).toContain('data-testid={`tab-${tab.id}`}')
  })

  it('has tab buttons with fourbar/cam/gear ids in TABS array', () => {
    expect(SRC).toContain("{ id: 'fourbar'")
    expect(SRC).toContain("{ id: 'cam'")
    expect(SRC).toContain("{ id: 'gear'")
  })

  it('has fourbar run button', () => {
    expect(SRC).toContain('data-testid="fourbar-run-btn"')
  })

  it('has cam run button', () => {
    expect(SRC).toContain('data-testid="cam-run-btn"')
  })

  it('has gear run button', () => {
    expect(SRC).toContain('data-testid="gear-run-btn"')
  })

  it('has fourbar precision-point inputs (via template literal)', () => {
    // Point inputs use template literals: data-testid={`point-${i}-x`}
    expect(SRC).toContain('data-testid={`point-${i}-x`}')
    expect(SRC).toContain('data-testid={`point-${i}-y`}')
  })

  it('has cam SVG testid in CamProfileChart', () => {
    expect(SRC).toContain('data-testid="cam-profile-svg"')
  })

  it('has coupler curve SVG testid in CouplerCurvePlot', () => {
    expect(SRC).toContain('data-testid="coupler-curve-svg"')
  })
})

describe('MechanismSynthesisPanel source — Burmester/Norton citations', () => {
  it('cites Burmester theory', () => {
    // Either the library name or the author should appear
    expect(SRC.toLowerCase()).toMatch(/burmester|sandor.*erdman/)
  })

  it('cites Norton or Litvin for cam', () => {
    expect(SRC.toLowerCase()).toMatch(/norton|litvin/)
  })

  it('cites ISO 54 or Shigley for gear', () => {
    expect(SRC.toLowerCase()).toMatch(/iso 54|shigley/)
  })
})

// ---------------------------------------------------------------------------
// 2. CouplerCurvePlot SVG rendering
// ---------------------------------------------------------------------------

describe('CouplerCurvePlot — SVG rendering', () => {
  it('renders empty-state when no points', () => {
    const html = renderToStaticMarkup(<CouplerCurvePlot points={[]} />)
    expect(html).toContain('No coupler curve data yet')
  })

  it('renders empty-state for null points', () => {
    const html = renderToStaticMarkup(<CouplerCurvePlot points={null} />)
    expect(html).toContain('No coupler curve data yet')
  })

  it('renders SVG when points provided', () => {
    // A simple square as a coupler curve
    const pts = [[0, 0], [10, 0], [10, 10], [0, 10]]
    const html = renderToStaticMarkup(<CouplerCurvePlot points={pts} />)
    expect(html).toContain('<svg')
    expect(html).toContain('data-testid="coupler-curve-svg"')
  })

  it('renders path element in SVG', () => {
    const pts = [[0, 0], [5, 5], [10, 0], [5, -5]]
    const html = renderToStaticMarkup(<CouplerCurvePlot points={pts} />)
    expect(html).toContain('<path')
  })

  it('renders precision points as crosses when provided', () => {
    const pts = [[0, 0], [5, 5], [10, 0]]
    const prec = [[0, 0], [5, 5], [10, 0]]
    const html = renderToStaticMarkup(<CouplerCurvePlot points={pts} precisionPts={prec} />)
    // Precision points render as SVG <line> elements
    expect(html).toContain('<line')
  })

  it('shows coordinate range in footer', () => {
    const pts = [[0, 0], [20, 0], [20, 15], [0, 15]]
    const html = renderToStaticMarkup(<CouplerCurvePlot points={pts} />)
    expect(html).toContain('mm')
    expect(html).toContain('Coupler curve')
  })
})

// ---------------------------------------------------------------------------
// 3. CamProfileChart SVG rendering
// ---------------------------------------------------------------------------

/** Build a minimal cycloidal profile stub for testing. */
function makeCycloidal(n = 10, h = 10.0, betaDeg = 120.0) {
  const profile = []
  for (let i = 0; i <= n; i++) {
    const theta_deg = (betaDeg * i) / n
    const xi = i / n
    const displacement = h * (xi - Math.sin(2 * Math.PI * xi) / (2 * Math.PI))
    profile.push({
      theta_deg,
      displacement: parseFloat(displacement.toFixed(6)),
      velocity_per_omega: 0,
      acceleration_per_omega2: 0,
    })
  }
  return profile
}

describe('CamProfileChart — SVG rendering', () => {
  it('renders empty-state when no profile', () => {
    const html = renderToStaticMarkup(<CamProfileChart profile={[]} h={10} />)
    expect(html).toContain('No cam profile data yet')
  })

  it('renders empty-state for null profile', () => {
    const html = renderToStaticMarkup(<CamProfileChart profile={null} h={10} />)
    expect(html).toContain('No cam profile data yet')
  })

  it('renders SVG when profile provided', () => {
    const profile = makeCycloidal(10, 10, 120)
    const html = renderToStaticMarkup(<CamProfileChart profile={profile} h={10} />)
    expect(html).toContain('<svg')
    expect(html).toContain('data-testid="cam-profile-svg"')
  })

  it('renders path element for displacement curve', () => {
    const profile = makeCycloidal(20, 15, 90)
    const html = renderToStaticMarkup(<CamProfileChart profile={profile} h={15} />)
    expect(html).toContain('<path')
  })

  it('renders h reference dashed line', () => {
    const profile = makeCycloidal(10, 10, 120)
    const html = renderToStaticMarkup(<CamProfileChart profile={profile} h={10} />)
    // Dashed reference line is present as a <line> with stroke-dasharray
    expect(html).toContain('stroke-dasharray')
  })

  it('shows lift h in footer', () => {
    const profile = makeCycloidal(10, 8.5, 120)
    const html = renderToStaticMarkup(<CamProfileChart profile={profile} h={8.5} />)
    expect(html).toContain('8.50')
  })

  it('shows angle axis labels', () => {
    const profile = makeCycloidal(10, 10, 90)
    const html = renderToStaticMarkup(<CamProfileChart profile={profile} h={10} />)
    expect(html).toContain('(deg)')
  })
})

// ---------------------------------------------------------------------------
// 4. MechanismSynthesisPanel full smoke renders
// ---------------------------------------------------------------------------

describe('MechanismSynthesisPanel — full panel render', () => {
  it('renders without crashing', () => {
    const html = renderToStaticMarkup(<MechanismSynthesisPanel />)
    expect(typeof html).toBe('string')
    expect(html.length).toBeGreaterThan(0)
  })

  it('renders the panel root testid', () => {
    const html = renderToStaticMarkup(<MechanismSynthesisPanel />)
    expect(html).toContain('data-testid="mechanism-synthesis-panel"')
  })

  it('renders the Mechanism Synthesis title', () => {
    const html = renderToStaticMarkup(<MechanismSynthesisPanel />)
    expect(html).toContain('Mechanism Synthesis')
  })

  it('renders all three tab buttons', () => {
    const html = renderToStaticMarkup(<MechanismSynthesisPanel />)
    expect(html).toContain('Four-bar')
    expect(html).toContain('Cam-follower')
    expect(html).toContain('Gear-train')
  })

  it('default tab is fourbar (fourbar-tab rendered)', () => {
    const html = renderToStaticMarkup(<MechanismSynthesisPanel />)
    expect(html).toContain('data-testid="fourbar-tab"')
  })

  it('renders three precision-point x inputs in fourbar tab', () => {
    const html = renderToStaticMarkup(<MechanismSynthesisPanel />)
    // Template literal testids render to concrete strings in markup
    expect(html).toContain('point-0-x')
    expect(html).toContain('point-1-x')
    expect(html).toContain('point-2-x')
  })

  it('renders Synthesise run button in fourbar tab', () => {
    const html = renderToStaticMarkup(<MechanismSynthesisPanel />)
    expect(html).toContain('data-testid="fourbar-run-btn"')
    expect(html).toContain('Synthesise')
  })

  it('renders Precision Points section header', () => {
    const html = renderToStaticMarkup(<MechanismSynthesisPanel />)
    expect(html).toContain('Precision Points')
  })
})
