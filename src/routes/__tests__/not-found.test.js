/**
 * not-found.test.js — T-A3: Real 404 / catch-all page
 *
 * Verifies structural contracts for the NotFound route and the App.jsx
 * catch-all wiring via source-level checks, following the established
 * pattern in this codebase (readFileSync, no jsdom needed for ARIA
 * contract assertions).
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const NOT_FOUND_SRC = readFileSync(resolve(__dirname, '../NotFound.jsx'), 'utf8')
const APP_SRC = readFileSync(resolve(__dirname, '../../App.jsx'), 'utf8')

// ---------------------------------------------------------------------------
// NotFound.jsx — structural contracts
// ---------------------------------------------------------------------------

describe('NotFound.jsx — page structure', () => {
  it('renders a <main> landmark element', () => {
    expect(NOT_FOUND_SRC).toMatch(/<main/)
  })

  it('<main> is labelled with aria-labelledby pointing at the heading', () => {
    expect(NOT_FOUND_SRC).toContain('aria-labelledby="not-found-heading"')
  })

  it('heading id matches aria-labelledby value', () => {
    expect(NOT_FOUND_SRC).toContain('id="not-found-heading"')
  })

  it('heading text conveys "Page not found"', () => {
    expect(NOT_FOUND_SRC).toContain('Page not found')
  })

  it('decorative 404 numeral is hidden from screen readers (aria-hidden)', () => {
    // The large "404" text is purely visual; SR users get the heading instead.
    const lines = NOT_FOUND_SRC.split('\n')
    const numLine = lines.findIndex((l) => l.includes('404') && !l.includes('T-A3'))
    expect(numLine).toBeGreaterThanOrEqual(0)
    // Within a small window the aria-hidden attribute must appear
    const window = lines.slice(Math.max(0, numLine - 2), numLine + 2).join('\n')
    expect(window).toContain('aria-hidden')
  })

  it('includes a home link', () => {
    // A Link (or <a>) that navigates to "/"
    expect(NOT_FOUND_SRC).toMatch(/to=["']\/["']/)
  })

  it('home link has descriptive text (not just an icon)', () => {
    expect(NOT_FOUND_SRC).toContain('Go to home')
  })

  it('logo link has an aria-label for screen readers', () => {
    expect(NOT_FOUND_SRC).toContain('aria-label="Kerf home"')
  })
})

// ---------------------------------------------------------------------------
// App.jsx — routing wiring
// ---------------------------------------------------------------------------

describe('App.jsx — catch-all route wiring', () => {
  it('lazy-imports NotFound', () => {
    expect(APP_SRC).toContain("import('./routes/NotFound.jsx')")
  })

  it('catch-all route path="*" renders NotFound, not a Navigate redirect', () => {
    // Must have path="*" with NotFound, must NOT have the old Navigate redirect on the same line
    expect(APP_SRC).toMatch(/path="\*"[^>]*NotFound/)
  })

  it('silent redirect to "/" on catch-all is removed', () => {
    // The old pattern was: <Route path="*" element={<Navigate to="/" replace />} />
    expect(APP_SRC).not.toMatch(/path="\*".*Navigate.*to=["']\/["']/)
  })
})
