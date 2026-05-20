// FeatureView.a11y.test.jsx — T-D2: verify no role="button" divs remain in
// FeatureView.jsx and that the mobile inspector handle is a real <button>.
//
// Strategy: source-file structural checks via readFileSync.  FeatureView has
// many WebGL / OCCT dependencies that cannot be instantiated in a vitest node
// environment, so we inspect the source text rather than render the component.
//
// Tests:
//   1. No element uses role="button" (axe "interactive role on non-interactive
//      element" violation eliminated).
//   2. The mobile handle that closes the inspector is a <button> element.
//   3. The mobile handle carries type="button" (prevents accidental form submit).
//   4. The mobile handle retains aria-label="Close inspector".
//   5. FeatureView has a default export (module shape sanity-check).

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(path.resolve(__dirname, './FeatureView.jsx'), 'utf8')

describe('FeatureView T-D2 a11y — no role=button divs', () => {
  it('contains no role="button" on a non-button element', () => {
    // Allow role="button" only if it appears on a <button> tag — but after
    // T-D2 there should be zero occurrences of the antipattern at all.
    // A div/span/a carrying role="button" is the violation we are fixing.
    const matches = [...src.matchAll(/role="button"/g)]
    // Verify every match is absent (we removed them all)
    expect(matches.length).toBe(0)
  })

  it('mobile inspector handle is a <button> element', () => {
    // The Close inspector control must be a <button>.  Attributes may span
    // multiple lines, so we check that </button> follows the aria-label rather
    // than </div> or </span>.
    const closeIdx = src.indexOf('aria-label="Close inspector"')
    expect(closeIdx).toBeGreaterThan(-1)
    // Walk backward from the aria-label to find the opening tag
    const before = src.slice(0, closeIdx)
    const lastOpenTag = before.lastIndexOf('<')
    const openTag = src.slice(lastOpenTag, lastOpenTag + 8)
    expect(openTag).toMatch(/^<button\b/)
  })

  it('mobile inspector handle has type="button"', () => {
    // Find the block from <button opening to the matching > and confirm type="button"
    const closeIdx = src.indexOf('aria-label="Close inspector"')
    const before = src.slice(0, closeIdx)
    const openPos = before.lastIndexOf('<button')
    const closeTagEnd = src.indexOf('>', closeIdx)
    const tagText = src.slice(openPos, closeTagEnd + 1)
    expect(tagText).toContain('type="button"')
  })

  it('mobile inspector handle retains aria-label="Close inspector"', () => {
    expect(src).toContain('aria-label="Close inspector"')
  })

  it('FeatureView has a default export', () => {
    expect(src).toContain('export default function FeatureView')
  })
})
