// Guard: the emitted favicon must be DERIVED FROM `brand/logo.svg`, not a
// hand-redrawn or hardcoded approximation of it. This is the failure mode
// that shipped a retired mark for months (see git history at efb20d2c) —
// build-icons.mjs used to re-declare the mark's coordinates as literals
// instead of reading the brand file, so regenerating never helped.
//
// This test fails closed: if either file is missing or unreadable, it
// throws rather than silently reporting "0 checks passed".
import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const BRAND_LOGO = path.join(ROOT, 'brand', 'logo.svg')
const PUBLIC_FAVICON = path.join(ROOT, 'public', 'favicon.svg')
const GENERATOR = path.join(ROOT, 'scripts', 'build-icons.mjs')

function readOrThrow(p, label) {
  if (!existsSync(p)) throw new Error(`GUARD CANNOT RUN: ${label} is missing at ${p}`)
  return readFileSync(p, 'utf8')
}

describe('brand icon generator stays derived from brand/logo.svg', () => {
  it('public/favicon.svg is byte-identical to brand/logo.svg', () => {
    const brand = readOrThrow(BRAND_LOGO, 'brand/logo.svg')
    const favicon = readOrThrow(PUBLIC_FAVICON, 'public/favicon.svg')
    expect(favicon).toBe(brand)
  })

  it('build-icons.mjs reads brand/logo.svg at run time rather than re-declaring its geometry', () => {
    const src = readOrThrow(GENERATOR, 'scripts/build-icons.mjs')
    // Positive assertion: the generator must actually reference the brand file.
    expect(src).toMatch(/brand.*logo\.svg/)
    // Negative assertion, coverage-counted: none of the mark's known literal
    // coordinates may appear as hardcoded strings in the generator. If the
    // mark's geometry ever changes, this list goes stale on purpose — that's
    // the point: a stale hardcoded coordinate here would mean the generator
    // drifted from the source exactly like the historical bug.
    const brand = readOrThrow(BRAND_LOGO, 'brand/logo.svg')
    const shapeLiterals = [...brand.matchAll(/<(?:rect|polygon|path)\b[^>]*\/>/g)]
      .map((m) => m[0])
      .filter((el) => !/width="32" height="32" rx=/.test(el)) // exclude the background tile
    expect(shapeLiterals.length).toBeGreaterThan(0) // coverage-count: we found something to check
    for (const literal of shapeLiterals) {
      // Extract just the numeric/point payload (e.g. "10.5,16 26,6 26,13")
      // since that's what a hardcoded re-declaration would copy verbatim.
      const payload = (literal.match(/points="([^"]+)"/) || literal.match(/d="([^"]+)"/) || [])[1]
      if (payload) expect(src.includes(payload)).toBe(false)
    }
  })
})
