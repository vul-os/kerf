/**
 * Vitest structural tests for CAMMachineSimPanel.
 *
 * Uses renderToStaticMarkup (react-dom/server) — no @testing-library/react,
 * following the project pattern from CameraLensPicker.test.jsx.
 */

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CAMMachineSimPanel from './CAMMachineSimPanel.jsx'

const defaultPoints = [
  { x: 0, y: 0, z: 50 },
  { x: 5, y: 5, z: 0 },
  { x: 0, y: 0, z: -200 },
]

const defaultProps = {
  toolpathPoints: defaultPoints,
  toolDiameter: 12,
  toolLength: 80,
  holderDiameter: 32,
  holderLength: 50,
  stockBounds: { x_min: -50, x_max: 50, y_min: -50, y_max: 50, z_min: 0, z_max: 50 },
  tablePivotZ: 0,
}

// ---------------------------------------------------------------------------
// 1. Basic rendering
// ---------------------------------------------------------------------------

describe('CAMMachineSimPanel rendering', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)).not.toThrow()
  })

  it('has data-testid="cam-machine-sim-panel"', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toMatch(/data-testid="cam-machine-sim-panel"/)
  })

  it('renders the "Machine Collision Check" title', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toContain('Machine Collision Check')
  })

  it('renders the AABB kinematic sim label', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toContain('AABB kinematic sim')
  })

  it('renders the check button', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toMatch(/<button/)
  })

  it('check button has aria-label', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toMatch(/aria-label="Run machine collision check"/)
  })

  it('shows tool diameter', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} toolDiameter={16} />)
    expect(html).toContain('16mm')
  })

  it('shows holder diameter', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} holderDiameter={40} />)
    expect(html).toContain('40mm')
  })

  it('shows point count', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toContain('3')  // 3 toolpath points
  })
})

// ---------------------------------------------------------------------------
// 2. Machine schematic SVG
// ---------------------------------------------------------------------------

describe('CAMMachineSimPanel schematic', () => {
  it('renders machine schematic SVG element', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toMatch(/<svg/)
  })

  it('schematic has data-testid="machine-schematic"', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toMatch(/data-testid="machine-schematic"/)
  })

  it('schematic has aria-label', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toMatch(/aria-label="Machine schematic XZ view"/)
  })

  it('schematic shows TABLE label', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toContain('TABLE')
  })

  it('schematic shows XZ view label', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toContain('XZ view')
  })
})

// ---------------------------------------------------------------------------
// 3. Prop variants
// ---------------------------------------------------------------------------

describe('CAMMachineSimPanel prop variants', () => {
  it('renders with no toolpath points', () => {
    expect(() => renderToStaticMarkup(
      <CAMMachineSimPanel {...defaultProps} toolpathPoints={[]} />
    )).not.toThrow()
  })

  it('renders with no stockBounds', () => {
    expect(() => renderToStaticMarkup(
      <CAMMachineSimPanel {...defaultProps} stockBounds={undefined} />
    )).not.toThrow()
  })

  it('renders with 5-axis points (a_deg, b_deg)', () => {
    const fiveAxisPoints = [
      { x: 0, y: 0, z: 50, a_deg: 0, b_deg: 0 },
      { x: 5, y: 0, z: 20, a_deg: 30, b_deg: 15 },
    ]
    expect(() => renderToStaticMarkup(
      <CAMMachineSimPanel {...defaultProps} toolpathPoints={fiveAxisPoints} />
    )).not.toThrow()
  })

  it('renders with tablePivotZ set', () => {
    expect(() => renderToStaticMarkup(
      <CAMMachineSimPanel {...defaultProps} tablePivotZ={25} />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 4. Initial state (no result)
// ---------------------------------------------------------------------------

describe('CAMMachineSimPanel initial state', () => {
  it('does not show collision badge initially (no result yet)', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).not.toContain('No collisions')
    expect(html).not.toContain('collision event')
  })

  it('does not show error box initially', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).not.toMatch(/role="alert"/)
  })

  it('button shows "Check Collisions" in initial state', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toContain('Check Collisions')
  })

  it('button is not disabled in initial state', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).not.toMatch(/disabled=""/)
  })
})

// ---------------------------------------------------------------------------
// 5. Accessibility and structure
// ---------------------------------------------------------------------------

describe('CAMMachineSimPanel accessibility', () => {
  it('renders an SVG icon (Cpu icon)', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toMatch(/<svg/)
  })

  it('has a header section', () => {
    const html = renderToStaticMarkup(<CAMMachineSimPanel {...defaultProps} />)
    expect(html).toMatch(/Machine Collision Check/)
  })
})
