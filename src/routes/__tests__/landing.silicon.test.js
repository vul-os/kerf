/**
 * landing.silicon.test.js
 *
 * Smoke tests for:
 *   - src/routes/domains/Silicon.jsx
 *   - src/routes/domains/silicon.meta.js
 *   - src/routes/Landing.jsx (silicon sector card)
 *   - src/components/domains/DomainSwitcher.jsx (silicon tab)
 *   - src/App.jsx route registration
 *
 * Tests are pure source-level (readFileSync) — no jsdom required.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const PAGE_SRC = readFileSync(
  resolve(__dirname, '../domains/Silicon.jsx'),
  'utf8',
)

const META_SRC = readFileSync(
  resolve(__dirname, '../domains/silicon.meta.js'),
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
/* Silicon.jsx — module structure                                              */
/* -------------------------------------------------------------------------- */

describe('Silicon page — module', () => {
  it('exports a default function Silicon', () => {
    expect(PAGE_SRC).toMatch(/export default function Silicon/)
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

  it('imports silicon.meta.js', () => {
    expect(PAGE_SRC).toMatch(/silicon\.meta/)
  })

  it('passes active="silicon" to DomainSwitcher', () => {
    expect(PAGE_SRC).toMatch(/active=["']silicon["']/)
  })
})

describe('Silicon page — hero', () => {
  it('contains the sector name "silicon" or "Silicon"', () => {
    expect(PAGE_SRC).toMatch(/[Ss]ilicon/)
  })

  it('mentions the tagline "From RTL to GDS-II"', () => {
    expect(PAGE_SRC).toMatch(/TAGLINE|From RTL to GDS-II/)
  })

  it('links to /signup CTA', () => {
    expect(PAGE_SRC).toMatch(/\/signup/)
  })

  it('links to /docs/silicon', () => {
    expect(PAGE_SRC).toMatch(/\/docs\/silicon/)
  })

  it('mentions MIT licensed', () => {
    expect(PAGE_SRC).toMatch(/MIT licensed/)
  })

  it('mentions Python SDK or kerf-sdk', () => {
    expect(PAGE_SRC).toMatch(/kerf-sdk|Python SDK/)
  })
})

describe('Silicon page — capabilities', () => {
  it('mentions RTL synthesis and Yosys', () => {
    expect(PAGE_SRC).toMatch(/Yosys/)
  })

  it('mentions OpenROAD for place and route', () => {
    expect(PAGE_SRC).toMatch(/OpenROAD/)
  })

  it('mentions DRC or LVS', () => {
    expect(PAGE_SRC).toMatch(/DRC|LVS/)
  })

  it('mentions GDS-II', () => {
    expect(PAGE_SRC).toMatch(/GDS-II/)
  })

  it('mentions Sky130 PDK', () => {
    expect(PAGE_SRC).toMatch(/Sky130|sky130/)
  })

  it('mentions static timing or OpenSTA', () => {
    expect(PAGE_SRC).toMatch(/OpenSTA|static timing|STA/)
  })

  it('mentions SPEF (parasitic extraction)', () => {
    expect(PAGE_SRC).toMatch(/SPEF/)
  })
})

describe('Silicon page — chat transcript', () => {
  it('uses real Kerf tool name: search_kerf_docs', () => {
    expect(PAGE_SRC).toMatch(/search_kerf_docs/)
  })

  it('uses real Kerf tool name: run_rtl_synth', () => {
    expect(PAGE_SRC).toMatch(/run_rtl_synth/)
  })

  it('uses real Kerf tool name: run_pnr', () => {
    expect(PAGE_SRC).toMatch(/run_pnr/)
  })

  it('uses real Kerf tool name: export_gds', () => {
    expect(PAGE_SRC).toMatch(/export_gds/)
  })
})

describe('Silicon page — GDS-II interchange callout', () => {
  it('contains interchange callout section mentioning GDS-II', () => {
    expect(PAGE_SRC).toMatch(/GDS-II/)
  })

  it('states that GDS-II is a standard interchange', () => {
    expect(PAGE_SRC).toMatch(/standard interchange|every EDA tool/)
  })
})

describe('Silicon page — open + scriptable section', () => {
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

describe('Silicon page — design constraints', () => {
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
/* silicon.meta.js                                                             */
/* -------------------------------------------------------------------------- */

describe('silicon.meta.js — structure', () => {
  it('exports META_TITLE', () => {
    expect(META_SRC).toMatch(/export const META_TITLE/)
  })

  it('exports a TAGLINE', () => {
    expect(META_SRC).toMatch(/export const TAGLINE/)
  })

  it('tagline mentions RTL to GDS-II', () => {
    expect(META_SRC).toMatch(/RTL to GDS-II/)
  })

  it('has canonical URL pointing to kerf.sh/domains/silicon', () => {
    expect(META_SRC).toMatch(/https:\/\/kerf\.sh\/domains\/silicon/)
  })

  it('has OG image URL for silicon.png', () => {
    expect(META_SRC).toMatch(/https:\/\/kerf\.sh\/og\/silicon\.png/)
  })

  it('meta description is ≤ 160 characters', () => {
    const match = META_SRC.match(/META_DESCRIPTION\s*=\s*\n?\s*['"`]([^'"`]+)['"`]/)
    if (match) {
      expect(match[1].length).toBeLessThanOrEqual(160)
    }
  })
})

/* -------------------------------------------------------------------------- */
/* Landing.jsx — silicon sector card                                           */
/* -------------------------------------------------------------------------- */

describe('Landing.jsx — silicon capability group', () => {
  it('contains id: "silicon" in CAPABILITY_GROUPS', () => {
    expect(LANDING_SRC).toMatch(/id:\s*['"]silicon['"]/)
  })

  it('contains tagline for silicon', () => {
    expect(LANDING_SRC).toMatch(/From RTL to GDS-II/)
  })

  it('contains /domains/silicon link in DOMAINS', () => {
    expect(LANDING_SRC).toMatch(/\/domains\/silicon/)
  })

  it('does not remove any existing sector (mech, cae, electronics, arch, sharing)', () => {
    expect(LANDING_SRC).toMatch(/id:\s*['"]mech['"]/)
    expect(LANDING_SRC).toMatch(/id:\s*['"]cae['"]/)
    expect(LANDING_SRC).toMatch(/id:\s*['"]electronics['"]/)
    expect(LANDING_SRC).toMatch(/id:\s*['"]arch['"]/)
    expect(LANDING_SRC).toMatch(/id:\s*['"]sharing['"]/)
  })
})

/* -------------------------------------------------------------------------- */
/* DomainSwitcher.jsx — silicon tab                                            */
/* -------------------------------------------------------------------------- */

describe('DomainSwitcher.jsx — silicon tab', () => {
  it('includes silicon slug', () => {
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]silicon['"]/)
  })

  it('includes label Silicon', () => {
    expect(SWITCHER_SRC).toMatch(/label:\s*['"]Silicon['"]/)
  })

  it('still contains existing tabs (jewelry, mechanical, electronics)', () => {
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]jewelry['"]/)
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]mechanical['"]/)
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]electronics['"]/)
  })
})

/* -------------------------------------------------------------------------- */
/* App.jsx — silicon route registration                                        */
/* -------------------------------------------------------------------------- */

describe('App.jsx — silicon route', () => {
  it('imports Silicon component (lazy-loaded)', () => {
    expect(APP_SRC).toMatch(/import\('\.\/routes\/domains\/Silicon\.jsx'\)/)
  })

  it('registers /domains/silicon route', () => {
    expect(APP_SRC).toMatch(/domains\/silicon/)
  })

  it('does not contain merge conflict markers', () => {
    expect(APP_SRC).not.toMatch(/<<<<<<<|>>>>>>>|=======/)
  })
})
