/**
 * IrrigationPanel.test.jsx — SSR smoke tests for the irrigation layout panel.
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import IrrigationPanel from './IrrigationPanel.jsx'

// ---------------------------------------------------------------------------
// 1. Empty / default state
// ---------------------------------------------------------------------------

describe('IrrigationPanel — default state', () => {
  it('renders without crashing', () => {
    expect(() => renderToStaticMarkup(<IrrigationPanel />)).not.toThrow()
  })

  it('has data-testid="irrigation-panel"', () => {
    const html = renderToStaticMarkup(<IrrigationPanel />)
    expect(html).toContain('data-testid="irrigation-panel"')
  })

  it('renders an SVG canvas', () => {
    const html = renderToStaticMarkup(<IrrigationPanel />)
    expect(html).toMatch(/<svg\b/)
    expect(html).toContain('data-testid="irrigation-svg"')
  })

  it('has aria-label on SVG', () => {
    const html = renderToStaticMarkup(<IrrigationPanel />)
    expect(html).toContain('aria-label="Irrigation layout plan"')
  })

  it('shows site boundary dimensions', () => {
    const html = renderToStaticMarkup(<IrrigationPanel width_ft={80} length_ft={50} />)
    expect(html).toContain('80 × 50 ft')
  })

  it('shows "Place heads" placeholder text', () => {
    const html = renderToStaticMarkup(<IrrigationPanel />)
    expect(html).toContain('Place')
  })
})

// ---------------------------------------------------------------------------
// 2. Buttons
// ---------------------------------------------------------------------------

describe('IrrigationPanel — toolbar buttons', () => {
  it('renders Place heads button', () => {
    const html = renderToStaticMarkup(<IrrigationPanel />)
    expect(html).toContain('data-testid="irrigation-layout-btn"')
    expect(html).toContain('Place heads')
  })

  it('renders Zone flow demand button', () => {
    const html = renderToStaticMarkup(<IrrigationPanel />)
    expect(html).toContain('data-testid="irrigation-flow-btn"')
    expect(html).toContain('Zone flow demand')
  })

  it('renders with onDispatch prop without crashing', () => {
    expect(() => renderToStaticMarkup(
      <IrrigationPanel onDispatch={() => {}} />
    )).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// 3. Custom dimensions and sprinkler kind
// ---------------------------------------------------------------------------

describe('IrrigationPanel — props', () => {
  it('accepts custom svgWidth/svgHeight', () => {
    const html = renderToStaticMarkup(
      <IrrigationPanel svgWidth={800} svgHeight={500} />
    )
    expect(html).toContain('width="800"')
    expect(html).toContain('height="500"')
  })

  it('renders with RainBird_5000 sprinkler kind', () => {
    expect(() => renderToStaticMarkup(
      <IrrigationPanel sprinklerKind="RainBird_5000" pattern="triangular" zoneCount={3} />
    )).not.toThrow()
  })

  it('renders with triangular pattern', () => {
    expect(() => renderToStaticMarkup(
      <IrrigationPanel pattern="triangular" />
    )).not.toThrow()
  })
})
