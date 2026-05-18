/**
 * landing.aerospace.test.js
 *
 * Smoke tests for:
 *   - src/routes/domains/Aerospace.jsx
 *   - src/routes/domains/aerospace.meta.js
 *   - src/routes/Landing.jsx (aerospace sector card)
 *   - src/components/domains/DomainSwitcher.jsx (aerospace tab)
 *   - src/App.jsx route registration
 *
 * Tests are pure source-level (readFileSync) — no jsdom required.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const PAGE_SRC = readFileSync(
  resolve(__dirname, '../domains/Aerospace.jsx'),
  'utf8',
)

const META_SRC = readFileSync(
  resolve(__dirname, '../domains/aerospace.meta.js'),
  'utf8',
)

const LANDING_SRC = readFileSync(
  resolve(__dirname, '../Landing.jsx'),
  'utf8',
)

const SWITCHER_SRC = readFileSync(
  resolve(__dirname, '../../components/domains/DomainSwitcher.jsx'),
  'utf8',
)

const APP_SRC = readFileSync(
  resolve(__dirname, '../../App.jsx'),
  'utf8',
)

/* -------------------------------------------------------------------------- */
/* Aerospace.jsx — module structure                                            */
/* -------------------------------------------------------------------------- */

describe('Aerospace page — module', () => {
  it('exports a default function Aerospace', () => {
    expect(PAGE_SRC).toMatch(/export default function Aerospace/)
  })

  it('imports Header', () => {
    expect(PAGE_SRC).toMatch(/import Header/)
  })

  it('imports Footer', () => {
    expect(PAGE_SRC).toMatch(/import Footer/)
  })

  it('imports Button', () => {
    expect(PAGE_SRC).toMatch(/import Button/)
  })

  it('imports DomainSwitcher', () => {
    expect(PAGE_SRC).toMatch(/import DomainSwitcher/)
  })

  it('imports aerospace.meta.js', () => {
    expect(PAGE_SRC).toMatch(/aerospace\.meta/)
  })

  it('passes active="aerospace" to DomainSwitcher', () => {
    expect(PAGE_SRC).toMatch(/active=["']aerospace["']/)
  })
})

describe('Aerospace page — hero', () => {
  it('contains the sector name "aerospace" or "Aerospace"', () => {
    expect(PAGE_SRC).toMatch(/[Aa]erospace/)
  })

  it('mentions the tagline "From airframe sketch to STEP and Mystran"', () => {
    expect(PAGE_SRC).toMatch(/TAGLINE|From airframe sketch to STEP/)
  })

  it('links to /signup CTA', () => {
    expect(PAGE_SRC).toMatch(/\/signup/)
  })

  it('links to /docs/aerospace', () => {
    expect(PAGE_SRC).toMatch(/\/docs\/aerospace/)
  })

  it('mentions MIT licensed', () => {
    expect(PAGE_SRC).toMatch(/MIT licensed/)
  })

  it('mentions Python SDK or kerf-sdk', () => {
    expect(PAGE_SRC).toMatch(/kerf-sdk|Python SDK/)
  })
})

describe('Aerospace page — capabilities', () => {
  it('mentions FEM or FEniCSx', () => {
    expect(PAGE_SRC).toMatch(/FEniCSx|FEM/)
  })

  it('mentions Mystran', () => {
    expect(PAGE_SRC).toMatch(/Mystran/)
  })

  it('mentions STEP AP242 or STEP', () => {
    expect(PAGE_SRC).toMatch(/STEP/)
  })

  it('mentions composites or CFRP', () => {
    expect(PAGE_SRC).toMatch(/composites|CFRP/)
  })

  it('mentions GD&T per AS9100 or Y14.5', () => {
    expect(PAGE_SRC).toMatch(/AS9100|Y14\.5|GD&T/)
  })

  it('mentions CFD or SU2 or OpenFOAM', () => {
    expect(PAGE_SRC).toMatch(/CFD|SU2|OpenFOAM/)
  })

  it('mentions airframe or wing geometry', () => {
    expect(PAGE_SRC).toMatch(/airframe|wing|fuselage/)
  })

  it('mentions fatigue life or S-N curve', () => {
    expect(PAGE_SRC).toMatch(/fatigue|S-N curve|Al 7075/)
  })
})

describe('Aerospace page — chat transcript', () => {
  it('uses real Kerf tool name: search_kerf_docs', () => {
    expect(PAGE_SRC).toMatch(/search_kerf_docs/)
  })

  it('uses real Kerf tool name: read_file', () => {
    expect(PAGE_SRC).toMatch(/read_file/)
  })

  it('uses real Kerf tool name: run_fem', () => {
    expect(PAGE_SRC).toMatch(/run_fem/)
  })

  it('uses real Kerf tool name: export_mystran', () => {
    expect(PAGE_SRC).toMatch(/export_mystran/)
  })
})

describe('Aerospace page — STEP/Mystran interchange callout', () => {
  it('states that STEP and Mystran are standard interchange formats', () => {
    expect(PAGE_SRC).toMatch(/standard interchange|every aerospace tool/)
  })

  it('mentions Mystran in callout', () => {
    expect(PAGE_SRC).toMatch(/Mystran/)
  })

  it('mentions STEP AP242 in callout', () => {
    expect(PAGE_SRC).toMatch(/STEP AP2/)
  })
})

describe('Aerospace page — open + scriptable section', () => {
  it('mentions MIT', () => {
    expect(PAGE_SRC).toMatch(/MIT/)
  })

  it('mentions PyPI or Python SDK', () => {
    expect(PAGE_SRC).toMatch(/PyPI|Python SDK/)
  })

  it('shows a Python code sample', () => {
    expect(PAGE_SRC).toMatch(/import kerf_sdk|kerf\.Client/)
  })
})

describe('Aerospace page — design constraints', () => {
  it('does not reference raster images', () => {
    expect(PAGE_SRC).not.toMatch(/src=["'][^"']*\.(png|jpg|jpeg|webp)["']/)
  })

  it('does not contain Paystack', () => {
    expect(PAGE_SRC).not.toMatch(/Paystack/)
  })

  it('does not contain bunny.net', () => {
    expect(PAGE_SRC).not.toMatch(/bunny\.net/)
  })

  it('is responsive — uses lg: Tailwind breakpoint', () => {
    expect(PAGE_SRC).toMatch(/lg:/)
  })

  it('is responsive — uses sm: Tailwind breakpoint', () => {
    expect(PAGE_SRC).toMatch(/sm:/)
  })

  it('uses ink-* or kerf-* design tokens', () => {
    expect(PAGE_SRC).toMatch(/ink-|kerf-/)
  })
})

/* -------------------------------------------------------------------------- */
/* aerospace.meta.js                                                           */
/* -------------------------------------------------------------------------- */

describe('aerospace.meta.js — structure', () => {
  it('exports META_TITLE', () => {
    expect(META_SRC).toMatch(/export const META_TITLE/)
  })

  it('exports a TAGLINE', () => {
    expect(META_SRC).toMatch(/export const TAGLINE/)
  })

  it('tagline mentions airframe or STEP or Mystran', () => {
    expect(META_SRC).toMatch(/airframe|STEP|Mystran/)
  })

  it('has canonical URL pointing to kerf.sh/domains/aerospace', () => {
    expect(META_SRC).toMatch(/https:\/\/kerf\.sh\/domains\/aerospace/)
  })

  it('has OG image URL for aerospace.png', () => {
    expect(META_SRC).toMatch(/https:\/\/kerf\.sh\/og\/aerospace\.png/)
  })
})

/* -------------------------------------------------------------------------- */
/* Landing.jsx — aerospace sector card                                         */
/* -------------------------------------------------------------------------- */

describe('Landing.jsx — aerospace capability group', () => {
  it('contains id: "aerospace" in CAPABILITY_GROUPS', () => {
    expect(LANDING_SRC).toMatch(/id:\s*['"]aerospace['"]/)
  })

  it('contains tagline mentioning airframe or Mystran', () => {
    expect(LANDING_SRC).toMatch(/airframe|Mystran/)
  })

  it('contains /domains/aerospace link in DOMAINS', () => {
    expect(LANDING_SRC).toMatch(/\/domains\/aerospace/)
  })

  it('does not remove any existing sector', () => {
    expect(LANDING_SRC).toMatch(/id:\s*['"]mech['"]/)
    expect(LANDING_SRC).toMatch(/id:\s*['"]electronics['"]/)
    expect(LANDING_SRC).toMatch(/id:\s*['"]arch['"]/)
    expect(LANDING_SRC).toMatch(/id:\s*['"]sharing['"]/)
  })
})

/* -------------------------------------------------------------------------- */
/* DomainSwitcher.jsx — aerospace tab                                          */
/* -------------------------------------------------------------------------- */

describe('DomainSwitcher.jsx — aerospace tab', () => {
  it('includes aerospace slug', () => {
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]aerospace['"]/)
  })

  it('includes label Aerospace', () => {
    expect(SWITCHER_SRC).toMatch(/label:\s*['"]Aerospace['"]/)
  })

  it('still contains existing tabs', () => {
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]jewelry['"]/)
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]electronics['"]/)
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]automotive['"]/)
  })
})

/* -------------------------------------------------------------------------- */
/* App.jsx — aerospace route registration                                      */
/* -------------------------------------------------------------------------- */

describe('App.jsx — aerospace route', () => {
  it('imports Aerospace component (lazy-loaded)', () => {
    expect(APP_SRC).toMatch(/import\('\.\/routes\/domains\/Aerospace\.jsx'\)/)
  })

  it('registers /domains/aerospace route', () => {
    expect(APP_SRC).toMatch(/domains\/aerospace/)
  })

  it('does not contain merge conflict markers', () => {
    expect(APP_SRC).not.toMatch(/<<<<<<<|>>>>>>>|=======/)
  })
})
