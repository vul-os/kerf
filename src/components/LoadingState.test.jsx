// LoadingState.test.jsx — Vitest smoke tests for LoadingState + skeleton primitives.
//
// Strategy: renderToStaticMarkup (react-dom/server). Tests verify:
//   - role="status" / aria-busy / aria-live on the wrapper
//   - sr-only label text
//   - Correct number of skeleton rows
//   - showAvatar renders SkeletonCircle
//   - SkeletonLine, SkeletonBlock, SkeletonCircle render correctly
//   - animate-pulse class applied to all skeleton primitives

import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import LoadingState, { SkeletonLine, SkeletonBlock, SkeletonCircle } from './LoadingState.jsx'

// ── LoadingState (default export) ────────────────────────────────────────────

describe('LoadingState', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(<LoadingState />)).not.toThrow()
  })

  it('has role="status"', () => {
    const html = renderToStaticMarkup(<LoadingState />)
    expect(html).toMatch(/role="status"/)
  })

  it('has aria-busy="true"', () => {
    const html = renderToStaticMarkup(<LoadingState />)
    expect(html).toMatch(/aria-busy="true"/)
  })

  it('has aria-live="polite"', () => {
    const html = renderToStaticMarkup(<LoadingState />)
    expect(html).toMatch(/aria-live="polite"/)
  })

  it('renders sr-only label with default text', () => {
    const html = renderToStaticMarkup(<LoadingState />)
    expect(html).toMatch(/class="sr-only"[^>]*>Loading/)
  })

  it('renders custom label in sr-only span', () => {
    const html = renderToStaticMarkup(<LoadingState label="Fetching files…" />)
    expect(html).toContain('Fetching files…')
  })

  it('renders the default 3 skeleton rows', () => {
    const html = renderToStaticMarkup(<LoadingState />)
    // Each SkeletonLine renders a div with animate-pulse; count occurrences
    const matches = html.match(/animate-pulse/g) || []
    expect(matches.length).toBeGreaterThanOrEqual(3)
  })

  it('renders the specified number of rows', () => {
    const html5 = renderToStaticMarkup(<LoadingState rows={5} />)
    const html1 = renderToStaticMarkup(<LoadingState rows={1} />)
    // More rows = more animate-pulse divs
    const count5 = (html5.match(/animate-pulse/g) || []).length
    const count1 = (html1.match(/animate-pulse/g) || []).length
    expect(count5).toBeGreaterThan(count1)
  })

  it('does NOT render a circle skeleton when showAvatar=false (default)', () => {
    const html = renderToStaticMarkup(<LoadingState showAvatar={false} />)
    expect(html).not.toMatch(/rounded-full/)
  })

  it('renders a circle skeleton when showAvatar=true', () => {
    const html = renderToStaticMarkup(<LoadingState showAvatar={true} />)
    expect(html).toMatch(/rounded-full/)
  })

  it('accepts a custom className on the wrapper', () => {
    const html = renderToStaticMarkup(<LoadingState className="test-class-xyz" />)
    expect(html).toContain('test-class-xyz')
  })
})

// ── SkeletonLine ──────────────────────────────────────────────────────────────

describe('SkeletonLine', () => {
  it('renders a div', () => {
    const html = renderToStaticMarkup(<SkeletonLine />)
    expect(html).toMatch(/<div\b/)
  })

  it('has animate-pulse class', () => {
    const html = renderToStaticMarkup(<SkeletonLine />)
    expect(html).toContain('animate-pulse')
  })

  it('is aria-hidden', () => {
    const html = renderToStaticMarkup(<SkeletonLine />)
    expect(html).toMatch(/aria-hidden="true"/)
  })

  it('accepts custom width and height', () => {
    const html = renderToStaticMarkup(<SkeletonLine width="w-1/2" height="h-6" />)
    expect(html).toContain('w-1/2')
    expect(html).toContain('h-6')
  })
})

// ── SkeletonBlock ─────────────────────────────────────────────────────────────

describe('SkeletonBlock', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(<SkeletonBlock />)).not.toThrow()
  })

  it('has animate-pulse class', () => {
    const html = renderToStaticMarkup(<SkeletonBlock />)
    expect(html).toContain('animate-pulse')
  })

  it('is aria-hidden', () => {
    const html = renderToStaticMarkup(<SkeletonBlock />)
    expect(html).toMatch(/aria-hidden="true"/)
  })

  it('applies aspect-video by default', () => {
    const html = renderToStaticMarkup(<SkeletonBlock />)
    expect(html).toContain('aspect-video')
  })

  it('accepts a custom aspect ratio', () => {
    const html = renderToStaticMarkup(<SkeletonBlock aspect="aspect-square" />)
    expect(html).toContain('aspect-square')
  })
})

// ── SkeletonCircle ────────────────────────────────────────────────────────────

describe('SkeletonCircle', () => {
  it('renders without throwing', () => {
    expect(() => renderToStaticMarkup(<SkeletonCircle />)).not.toThrow()
  })

  it('has animate-pulse class', () => {
    const html = renderToStaticMarkup(<SkeletonCircle />)
    expect(html).toContain('animate-pulse')
  })

  it('is aria-hidden', () => {
    const html = renderToStaticMarkup(<SkeletonCircle />)
    expect(html).toMatch(/aria-hidden="true"/)
  })

  it('is rounded-full (circular)', () => {
    const html = renderToStaticMarkup(<SkeletonCircle />)
    expect(html).toContain('rounded-full')
  })

  it('accepts a custom size', () => {
    const html = renderToStaticMarkup(<SkeletonCircle size="size-16" />)
    expect(html).toContain('size-16')
  })
})
