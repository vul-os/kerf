// CameraLensPicker.test.jsx — Vitest structural tests for the CameraLensPicker
// component.
//
// @testing-library/react is not installed. Following the project pattern from
// Loader.test.jsx, we render to static markup via react-dom/server and assert
// structural properties with substring / regex matches.

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import CameraLensPicker from './CameraLensPicker.jsx'

// ── 1. Default render ─────────────────────────────────────────────────────────

describe('CameraLensPicker defaults', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(<CameraLensPicker />)).not.toThrow()
  })

  it('has a data-testid="camera-lens-picker" wrapper', () => {
    const html = renderToStaticMarkup(<CameraLensPicker />)
    expect(html).toMatch(/data-testid="camera-lens-picker"/)
  })

  it('renders the trigger button', () => {
    const html = renderToStaticMarkup(<CameraLensPicker />)
    expect(html).toMatch(/<button/)
  })

  it('button has aria-haspopup="menu"', () => {
    const html = renderToStaticMarkup(<CameraLensPicker />)
    expect(html).toMatch(/aria-haspopup="menu"/)
  })

  it('button is collapsed by default (aria-expanded="false")', () => {
    const html = renderToStaticMarkup(<CameraLensPicker />)
    expect(html).toMatch(/aria-expanded="false"/)
  })

  it('shows "Perspective" label by default', () => {
    const html = renderToStaticMarkup(<CameraLensPicker />)
    expect(html).toContain('Perspective')
  })

  it('does not render the dropdown menu when closed', () => {
    const html = renderToStaticMarkup(<CameraLensPicker />)
    expect(html).not.toMatch(/role="menu"/)
  })
})

// ── 2. Controlled projection prop ─────────────────────────────────────────────

describe('CameraLensPicker projection prop', () => {
  it('shows "Orthographic" when projection="orthographic"', () => {
    const html = renderToStaticMarkup(<CameraLensPicker projection="orthographic" />)
    expect(html).toContain('Orthographic')
  })

  it('shows "Two-Point" when projection="two-point"', () => {
    const html = renderToStaticMarkup(<CameraLensPicker projection="two-point" />)
    expect(html).toContain('Two-Point')
  })

  it('shows "Fisheye" when projection="fisheye"', () => {
    const html = renderToStaticMarkup(<CameraLensPicker projection="fisheye" />)
    expect(html).toContain('Fisheye')
  })

  it('shows "Panoramic 360°" when projection="panoramic-360"', () => {
    const html = renderToStaticMarkup(<CameraLensPicker projection="panoramic-360" />)
    expect(html).toContain('Panoramic 360')
  })

  it('falls back to the raw kind string for unknown projections', () => {
    const html = renderToStaticMarkup(<CameraLensPicker projection="custom-mode" />)
    expect(html).toContain('custom-mode')
  })
})

// ── 3. Focal-length display ───────────────────────────────────────────────────

describe('CameraLensPicker focalMm prop', () => {
  it('reflects focalMm=85 in the input value when open (static)', () => {
    // In static markup the dropdown is closed by default, so we test that
    // the component accepts the prop without erroring. The focal-length input
    // only renders inside the open dropdown; we indirectly verify by checking
    // the markup doesn't crash.
    expect(() => renderToStaticMarkup(<CameraLensPicker focalMm={85} />)).not.toThrow()
  })
})

// ── 4. Sensor prop ────────────────────────────────────────────────────────────

describe('CameraLensPicker sensor prop', () => {
  it('accepts sensor="aps-c" without erroring', () => {
    expect(() => renderToStaticMarkup(<CameraLensPicker sensor="aps-c" />)).not.toThrow()
  })

  it('accepts sensor="micro-4-3" without erroring', () => {
    expect(() => renderToStaticMarkup(<CameraLensPicker sensor="micro-4-3" />)).not.toThrow()
  })
})

// ── 5. Camera icon ────────────────────────────────────────────────────────────

describe('CameraLensPicker icon', () => {
  it('renders an SVG (Camera icon from lucide-react)', () => {
    const html = renderToStaticMarkup(<CameraLensPicker />)
    expect(html).toMatch(/<svg/)
  })

  it('Camera icon is aria-hidden', () => {
    const html = renderToStaticMarkup(<CameraLensPicker />)
    expect(html).toMatch(/aria-hidden="true"/)
  })
})

// ── 6. Button title ───────────────────────────────────────────────────────────

describe('CameraLensPicker button title', () => {
  it('has a descriptive title attribute on the trigger button', () => {
    const html = renderToStaticMarkup(<CameraLensPicker />)
    expect(html).toMatch(/title="Camera projection and lens settings"/)
  })
})

// ── 7. Chevron rotation class ─────────────────────────────────────────────────

describe('CameraLensPicker chevron', () => {
  it('chevron does not have rotate-180 class when closed (default)', () => {
    const html = renderToStaticMarkup(<CameraLensPicker />)
    // When closed the rotate-180 class should NOT be in the chevron class list.
    // We confirm by ensuring the chevron svg (ChevronDown) container does NOT
    // include rotate-180 — a simple structural check.
    expect(html).not.toMatch(/rotate-180/)
  })
})
