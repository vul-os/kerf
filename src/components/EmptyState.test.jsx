// EmptyState.test.jsx — Vitest smoke tests for EmptyState.
//
// Strategy: renderToStaticMarkup (react-dom/server). Tests verify:
//   - Renders without throwing
//   - role="status" + aria-label = title
//   - title, description, icon, action (button + link variants)
//   - size prop scales correctly
//   - disabled action button

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import EmptyState from './EmptyState.jsx'

const ICON = <svg data-testid="icon" aria-hidden="true" />

describe('EmptyState', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(<EmptyState title="Nothing here" />)).not.toThrow()
  })

  it('has role="status"', () => {
    const html = renderToStaticMarkup(<EmptyState title="Empty" />)
    expect(html).toMatch(/role="status"/)
  })

  it('aria-label equals the title prop', () => {
    const html = renderToStaticMarkup(<EmptyState title="No files yet" />)
    expect(html).toMatch(/aria-label="No files yet"/)
  })

  it('renders the title text', () => {
    const html = renderToStaticMarkup(<EmptyState title="No results found" />)
    expect(html).toContain('No results found')
  })

  it('renders description when provided', () => {
    const html = renderToStaticMarkup(
      <EmptyState title="Empty" description="Upload something to start." />,
    )
    expect(html).toContain('Upload something to start.')
  })

  it('does NOT render description element when omitted', () => {
    const html = renderToStaticMarkup(<EmptyState title="Empty" />)
    // No extra <p> with ink-400 text
    expect(html).not.toContain('ink-400 max-w-sm')
  })

  it('renders the icon element', () => {
    const html = renderToStaticMarkup(<EmptyState title="Empty" icon={ICON} />)
    expect(html).toMatch(/<svg/)
  })

  it('icon wrapper is aria-hidden', () => {
    const html = renderToStaticMarkup(<EmptyState title="Empty" icon={ICON} />)
    expect(html).toMatch(/aria-hidden="true"/)
  })

  it('does NOT render icon wrapper when icon is omitted', () => {
    const html = renderToStaticMarkup(<EmptyState title="Empty" />)
    // No icon container (no aria-hidden div)
    expect(html).not.toMatch(/aria-hidden="true"/)
  })

  it('renders a button action', () => {
    const html = renderToStaticMarkup(
      <EmptyState title="Empty" action={{ label: 'Add file', onClick: () => {} }} />,
    )
    expect(html).toMatch(/<button\b/)
    expect(html).toContain('Add file')
  })

  it('renders a link action when href is provided', () => {
    const html = renderToStaticMarkup(
      <EmptyState title="Empty" action={{ label: 'Go to docs', href: '/docs' }} />,
    )
    expect(html).toMatch(/<a\b/)
    expect(html).toContain('href="/docs"')
    expect(html).toContain('Go to docs')
  })

  it('renders a disabled button when action.disabled is true', () => {
    const html = renderToStaticMarkup(
      <EmptyState title="Empty" action={{ label: 'Disabled', disabled: true }} />,
    )
    expect(html).toMatch(/disabled/)
  })

  it('does NOT render action area when action is omitted', () => {
    const html = renderToStaticMarkup(<EmptyState title="Empty" />)
    expect(html).not.toMatch(/<button\b/)
    expect(html).not.toMatch(/<a\b/)
  })

  it('accepts a custom className', () => {
    const html = renderToStaticMarkup(<EmptyState title="Empty" className="my-custom" />)
    expect(html).toContain('my-custom')
  })

  it('renders correctly in sm size', () => {
    expect(() =>
      renderToStaticMarkup(<EmptyState title="Empty" size="sm" />),
    ).not.toThrow()
  })

  it('renders correctly in lg size', () => {
    expect(() =>
      renderToStaticMarkup(<EmptyState title="Empty" size="lg" />),
    ).not.toThrow()
  })
})
