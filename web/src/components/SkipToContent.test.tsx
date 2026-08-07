// SkipToContent.test.jsx — Vitest smoke tests for the SkipToContent component.
//
// Strategy: render to static HTML with react-dom/server (already a project dep)
// and assert the accessibility contract:
//   - Renders an <a> element
//   - href points to the configured target
//   - Link text is the supplied label
//   - Default target is '#main-content'
//   - Default label is 'Skip to main content'

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SkipToContent from './SkipToContent.jsx'

describe('SkipToContent', () => {
  it('renders an anchor element', () => {
    const html = renderToStaticMarkup(<SkipToContent />)
    expect(html).toMatch(/<a\b/)
  })

  it('defaults href to "#main-content"', () => {
    const html = renderToStaticMarkup(<SkipToContent />)
    expect(html).toContain('href="#main-content"')
  })

  it('defaults label to "Skip to main content"', () => {
    const html = renderToStaticMarkup(<SkipToContent />)
    expect(html).toContain('Skip to main content')
  })

  it('accepts a custom target', () => {
    const html = renderToStaticMarkup(<SkipToContent target="#workspace-canvas" />)
    expect(html).toContain('href="#workspace-canvas"')
  })

  it('accepts a custom label', () => {
    const html = renderToStaticMarkup(<SkipToContent label="Skip to editor" />)
    expect(html).toContain('Skip to editor')
  })

  it('is keyboard-visible on focus (has focus: class)', () => {
    const html = renderToStaticMarkup(<SkipToContent />)
    expect(html).toMatch(/focus:translate-y-0/)
  })

  it('has a high z-index to layer above other UI', () => {
    const html = renderToStaticMarkup(<SkipToContent />)
    expect(html).toMatch(/z-\[9999\]/)
  })

  it('renders without throwing when both props are custom', () => {
    expect(() =>
      renderToStaticMarkup(
        <SkipToContent target="#canvas" label="Jump to canvas" />,
      ),
    ).not.toThrow()
  })
})
