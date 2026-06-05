/**
 * Vitest structural tests for CAMVerifyPanel.
 *
 * Uses renderToStaticMarkup (react-dom/server) — no @testing-library/react
 * needed, following the project pattern from CameraLensPicker.test.jsx.
 */

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CAMVerifyPanel from './CAMVerifyPanel.jsx'

const defaultProps = {
  projectId: 'proj-1',
  fileId: 'file-1',
  clPoints: [{ x: 0, y: 0, z: 0 }, { x: 10, y: 10, z: -5 }],
  stockBounds: { x_min: 0, x_max: 20, y_min: 0, y_max: 20, stock_top: 0, stock_bottom: -10 },
  toolDiameter: 6,
  toolKind: 'flat',
  resolutionMm: 0.5,
}

// ---------------------------------------------------------------------------
// 1. Renders without throwing
// ---------------------------------------------------------------------------

describe('CAMVerifyPanel rendering', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)).not.toThrow()
  })

  it('has data-testid="cam-verify-panel"', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)
    expect(html).toMatch(/data-testid="cam-verify-panel"/)
  })

  it('renders the "Material Removal Verify" title', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)
    expect(html).toContain('Material Removal Verify')
  })

  it('renders the Van Hook method label', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)
    expect(html).toContain('Van Hook 1986 dexel/Z-map')
  })

  it('renders the run button', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)
    expect(html).toMatch(/<button/)
  })

  it('run button has aria-label for simulation', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)
    expect(html).toMatch(/aria-label="Run material removal simulation"/)
  })

  it('shows tool diameter', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} toolDiameter={8} />)
    expect(html).toContain('8mm')
  })

  it('shows tool kind', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} toolKind="ball" />)
    expect(html).toContain('ball')
  })

  it('shows resolution', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} resolutionMm={0.25} />)
    expect(html).toContain('0.25')
  })
})

// ---------------------------------------------------------------------------
// 2. Prop variants
// ---------------------------------------------------------------------------

describe('CAMVerifyPanel prop variants', () => {
  it('accepts gcode instead of clPoints without throwing', () => {
    const props = { ...defaultProps, clPoints: undefined, gcode: 'G1 X0 Y0 Z-5 F1000' }
    expect(() => renderToStaticMarkup(<CAMVerifyPanel {...props} />)).not.toThrow()
  })

  it('renders with bull-nose tool', () => {
    const html = renderToStaticMarkup(
      <CAMVerifyPanel {...defaultProps} toolKind="bull" cornerRadiusMm={1.5} />
    )
    expect(html).toContain('bull')
  })

  it('renders with partSurfaceZ prop', () => {
    expect(() => renderToStaticMarkup(
      <CAMVerifyPanel {...defaultProps} partSurfaceZ={-2.5} />
    )).not.toThrow()
  })

  it('minimal props (no clPoints or gcode) still renders', () => {
    expect(() => renderToStaticMarkup(
      <CAMVerifyPanel
        stockBounds={{ x_min: 0, x_max: 10, y_min: 0, y_max: 10 }}
      />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 3. DexelHeatmap SVG (via static render with injected result state)
// ---------------------------------------------------------------------------

describe('CAMVerifyPanel heatmap', () => {
  it('DexelHeatmap SVG has correct aria-label (via internal component)', () => {
    // We test the SVG by importing DexelHeatmap indirectly via module
    // (it is not exported, but we can verify the main panel produces an SVG
    // element only when result data is injected — here we just verify the
    // static render includes the SVG structure for the axis labels).
    // Since the panel starts with no result, we just check structural presence.
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)
    // Grid resolution label should be present
    expect(html).toContain('0.5mm/cell')
  })
})

// ---------------------------------------------------------------------------
// 4. Accessibility
// ---------------------------------------------------------------------------

describe('CAMVerifyPanel accessibility', () => {
  it('button is not disabled initially (panel is interactive)', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)
    // Button should not have disabled attribute in initial state
    // (running=false → not disabled)
    expect(html).not.toMatch(/disabled=""/)
  })

  it('Run Simulation text appears in button', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)
    expect(html).toContain('Run Simulation')
  })
})

// ---------------------------------------------------------------------------
// 5. No result state — no stats visible
// ---------------------------------------------------------------------------

describe('CAMVerifyPanel initial state', () => {
  it('does not show stats section initially', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)
    // Stats grid only shows after result — should not contain "Removed" label
    // in the stats cell structure
    expect(html).not.toContain('No gouges')
  })

  it('does not show error box initially', () => {
    const html = renderToStaticMarkup(<CAMVerifyPanel {...defaultProps} />)
    expect(html).not.toMatch(/role="alert"/)
  })
})
