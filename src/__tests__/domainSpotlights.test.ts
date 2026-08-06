/**
 * domainSpotlights.test.jsx
 *
 * Smoke tests for DomainSpotlights.jsx:
 *   - Module exports a default function component.
 *   - Key headings and chip labels are present in the JSX output.
 *   - CTA href values are correct.
 *   - SVG aria-labels are non-empty.
 *   - No raster asset references (no src=".png/.jpg/.webp").
 *
 * Intentionally no DOM rendering — this file has no jsdom environment and
 * we test the declarative shape of the component at source level.
 */

import { describe, it, expect } from 'vitest'
// @ts-expect-error - no @types/node in this toolchain
import { readFileSync, existsSync } from 'fs'
// @ts-expect-error - no @types/node in this toolchain
import { resolve, dirname } from 'path'
// @ts-expect-error - no @types/node in this toolchain
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Source-text inspection reads the module off disk by literal path, so a
// .jsx -> .tsx migration silently breaks it (typecheck cannot catch this;
// only running the suite does). Rather than re-pinning to .tsx and breaking
// again on the next slice, resolve whichever extension is present.
function readFirstExisting(dir, base, exts) {
  for (const ext of exts) {
    const path = resolve(dir, `${base}.${ext}`)
    if (existsSync(path)) return readFileSync(path, 'utf8')
  }
  throw new Error(`No source found for ${base} in ${dir}`)
}

const SRC = readFirstExisting(__dirname, '../components/landing/DomainSpotlights', ['tsx', 'jsx'])

describe('DomainSpotlights module', () => {
  it('exports a default function', () => {
    expect(SRC).toMatch(/export default function DomainSpotlights/)
  })

  it('contains the "Domain spotlights" section eyebrow', () => {
    expect(SRC).toMatch(/Domain spotlights/)
  })

  it('contains the "Purpose-built for your craft" heading', () => {
    expect(SRC).toMatch(/Purpose-built for your craft/)
  })
})

describe('DomainSpotlights — Jewelry spotlight', () => {
  it('names the Jewelry spotlight', () => {
    expect(SRC).toMatch(/Jewelry/)
  })

  it('references gem-seat v2 capability', () => {
    expect(SRC).toMatch(/gem-seat v2/)
  })

  it('references ring v4 capability', () => {
    expect(SRC).toMatch(/ring v4/)
  })

  it('references gemstones v2', () => {
    expect(SRC).toMatch(/gemstones v2/)
  })

  it('references 31-template library', () => {
    expect(SRC).toMatch(/31-template library/)
  })

  it('references casting export', () => {
    expect(SRC).toMatch(/casting export/)
  })

  it('references PBR materials', () => {
    expect(SRC).toMatch(/PBR materials/)
  })

  it('references settings v3/v4', () => {
    expect(SRC).toMatch(/settings v3\/v4/)
  })

  it('references chain v2', () => {
    expect(SRC).toMatch(/chain v2/)
  })

  it('has CTA linking to /domains/jewelry', () => {
    expect(SRC).toMatch(/\/domains\/jewelry/)
  })

  it('has a JewelryIllustration inline SVG', () => {
    expect(SRC).toMatch(/function JewelryIllustration/)
  })

  it('JewelryIllustration has a non-empty aria-label', () => {
    const match = SRC.match(/aria-label="([^"]+)"/)
    expect(match).not.toBeNull()
    expect(match[1].length).toBeGreaterThan(0)
  })
})

describe('DomainSpotlights — Automotive spotlight', () => {
  it('names the Automotive spotlight', () => {
    expect(SRC).toMatch(/Automotive/)
  })

  it('references NURBS surfacing Phase 4', () => {
    expect(SRC).toMatch(/NURBS surfacing Phase 4/)
  })

  it('references sheet metal capability', () => {
    expect(SRC).toMatch(/sheet metal/)
  })

  it('references GD&T', () => {
    expect(SRC).toMatch(/GD&T/)
  })

  it('references 5-axis CAM', () => {
    expect(SRC).toMatch(/5-axis CAM/)
  })

  it('references STEP\/IGES interop', () => {
    expect(SRC).toMatch(/STEP\/IGES interop/)
  })

  it('references assemblies', () => {
    expect(SRC).toMatch(/assemblies/)
  })

  it('has CTA to /docs/automotive', () => {
    expect(SRC).toMatch(/\/docs\/automotive/)
  })

  it('has an AutomotiveIllustration inline SVG', () => {
    expect(SRC).toMatch(/function AutomotiveIllustration/)
  })
})

describe('DomainSpotlights — design constraints', () => {
  it('does not reference any raster image src (.png/.jpg/.webp)', () => {
    expect(SRC).not.toMatch(/src=["'][^"']*\.(png|jpg|jpeg|webp)["']/)
  })

  it('does not contain cloud-internal terms (Paystack)', () => {
    expect(SRC).not.toMatch(/Paystack/)
  })

  it('does not expose pricing-margin language', () => {
    expect(SRC).not.toMatch(/20% markup/)
    expect(SRC).not.toMatch(/bunny\.net/)
    expect(SRC).not.toMatch(/go-git/)
  })

  it('uses Tailwind ink-* or kerf-* tokens — no raw hex in className', () => {
    // classNames should not contain raw # colours
    const classMatches = SRC.match(/className="[^"]*#[0-9a-fA-F]{3,6}[^"]*"/g) || []
    expect(classMatches).toHaveLength(0)
  })

  it('is responsive — uses lg: breakpoint prefix', () => {
    expect(SRC).toMatch(/lg:/)
  })
})
