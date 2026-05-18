/**
 * landing.firmware.test.js
 *
 * Smoke tests for:
 *   - src/routes/domains/Firmware.jsx
 *   - src/routes/domains/firmware.meta.js
 *   - src/routes/Landing.jsx (firmware sector card)
 *   - src/components/domains/DomainSwitcher.jsx (firmware tab)
 *   - src/App.jsx route registration
 *
 * Tests are pure source-level (readFileSync) — no jsdom required.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const PAGE_SRC = readFileSync(
  resolve(__dirname, '../domains/Firmware.jsx'),
  'utf8',
)

const META_SRC = readFileSync(
  resolve(__dirname, '../domains/firmware.meta.js'),
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
/* Firmware.jsx — module structure                                             */
/* -------------------------------------------------------------------------- */

describe('Firmware page — module', () => {
  it('exports a default function Firmware', () => {
    expect(PAGE_SRC).toMatch(/export default function Firmware/)
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

  it('imports firmware.meta.js', () => {
    expect(PAGE_SRC).toMatch(/firmware\.meta/)
  })

  it('passes active="firmware" to DomainSwitcher', () => {
    expect(PAGE_SRC).toMatch(/active=["']firmware["']/)
  })
})

describe('Firmware page — hero', () => {
  it('contains the sector name "firmware" or "Firmware"', () => {
    expect(PAGE_SRC).toMatch(/[Ff]irmware/)
  })

  it('mentions the tagline "From bare metal to .hex"', () => {
    expect(PAGE_SRC).toMatch(/TAGLINE|From bare metal to \.hex/)
  })

  it('links to /signup CTA', () => {
    expect(PAGE_SRC).toMatch(/\/signup/)
  })

  it('links to /docs/firmware', () => {
    expect(PAGE_SRC).toMatch(/\/docs\/firmware/)
  })

  it('mentions MIT licensed', () => {
    expect(PAGE_SRC).toMatch(/MIT licensed/)
  })

  it('mentions Python SDK or kerf-sdk', () => {
    expect(PAGE_SRC).toMatch(/kerf-sdk|Python SDK/)
  })
})

describe('Firmware page — capabilities', () => {
  it('mentions C / C++ or Rust toolchain', () => {
    expect(PAGE_SRC).toMatch(/C \/ C\+\+|Rust/)
  })

  it('mentions ARM or Cortex-M target', () => {
    expect(PAGE_SRC).toMatch(/ARM|Cortex-M|arm-none-eabi/)
  })

  it('mentions RISC-V target', () => {
    expect(PAGE_SRC).toMatch(/RISC-V/)
  })

  it('mentions FreeRTOS', () => {
    expect(PAGE_SRC).toMatch(/FreeRTOS/)
  })

  it('mentions Zephyr', () => {
    expect(PAGE_SRC).toMatch(/Zephyr/)
  })

  it('mentions static analysis (cppcheck or clang-tidy)', () => {
    expect(PAGE_SRC).toMatch(/cppcheck|clang-tidy/)
  })

  it('mentions .hex output', () => {
    expect(PAGE_SRC).toMatch(/\.hex/)
  })

  it('mentions .elf output', () => {
    expect(PAGE_SRC).toMatch(/\.elf/)
  })

  it('mentions OpenOCD or pyOCD for flash/debug', () => {
    expect(PAGE_SRC).toMatch(/OpenOCD|pyOCD/)
  })
})

describe('Firmware page — chat transcript', () => {
  it('uses real Kerf tool name: search_kerf_docs', () => {
    expect(PAGE_SRC).toMatch(/search_kerf_docs/)
  })

  it('uses real Kerf tool name: read_file', () => {
    expect(PAGE_SRC).toMatch(/read_file/)
  })

  it('uses real Kerf tool name: write_file', () => {
    expect(PAGE_SRC).toMatch(/write_file/)
  })

  it('uses real Kerf tool name: run_build', () => {
    expect(PAGE_SRC).toMatch(/run_build/)
  })
})

describe('Firmware page — hex/elf interchange callout', () => {
  it('states that .hex and .elf are universal interchange formats', () => {
    expect(PAGE_SRC).toMatch(/universal|standard interchange/)
  })

  it('mentions .hex in the interchange callout', () => {
    expect(PAGE_SRC).toMatch(/\.hex/)
  })
})

describe('Firmware page — open + scriptable section', () => {
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

describe('Firmware page — design constraints', () => {
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
/* firmware.meta.js                                                            */
/* -------------------------------------------------------------------------- */

describe('firmware.meta.js — structure', () => {
  it('exports META_TITLE', () => {
    expect(META_SRC).toMatch(/export const META_TITLE/)
  })

  it('exports a TAGLINE', () => {
    expect(META_SRC).toMatch(/export const TAGLINE/)
  })

  it('tagline mentions bare metal to .hex', () => {
    expect(META_SRC).toMatch(/bare metal|\.hex/)
  })

  it('has canonical URL pointing to kerf.sh/domains/firmware', () => {
    expect(META_SRC).toMatch(/https:\/\/kerf\.sh\/domains\/firmware/)
  })

  it('has OG image URL for firmware.png', () => {
    expect(META_SRC).toMatch(/https:\/\/kerf\.sh\/og\/firmware\.png/)
  })
})

/* -------------------------------------------------------------------------- */
/* Landing.jsx — firmware sector card                                          */
/* -------------------------------------------------------------------------- */

describe('Landing.jsx — firmware capability group', () => {
  it('contains id: "firmware" in CAPABILITY_GROUPS', () => {
    expect(LANDING_SRC).toMatch(/id:\s*['"]firmware['"]/)
  })

  it('contains tagline for firmware', () => {
    expect(LANDING_SRC).toMatch(/bare metal|\.hex/)
  })

  it('contains /domains/firmware link in DOMAINS', () => {
    expect(LANDING_SRC).toMatch(/\/domains\/firmware/)
  })

  it('does not remove any existing sector', () => {
    expect(LANDING_SRC).toMatch(/id:\s*['"]mech['"]/)
    expect(LANDING_SRC).toMatch(/id:\s*['"]electronics['"]/)
    expect(LANDING_SRC).toMatch(/id:\s*['"]sharing['"]/)
  })
})

/* -------------------------------------------------------------------------- */
/* DomainSwitcher.jsx — firmware tab                                           */
/* -------------------------------------------------------------------------- */

describe('DomainSwitcher.jsx — firmware tab', () => {
  it('includes firmware slug', () => {
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]firmware['"]/)
  })

  it('includes label Firmware', () => {
    expect(SWITCHER_SRC).toMatch(/label:\s*['"]Firmware['"]/)
  })

  it('still contains existing tabs', () => {
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]automotive['"]/)
    expect(SWITCHER_SRC).toMatch(/slug:\s*['"]architecture['"]/)
  })
})

/* -------------------------------------------------------------------------- */
/* App.jsx — firmware route registration                                       */
/* -------------------------------------------------------------------------- */

describe('App.jsx — firmware route', () => {
  it('imports Firmware component (lazy-loaded)', () => {
    expect(APP_SRC).toMatch(/import\('\.\/routes\/domains\/Firmware\.jsx'\)/)
  })

  it('registers /domains/firmware route', () => {
    expect(APP_SRC).toMatch(/domains\/firmware/)
  })

  it('does not contain merge conflict markers', () => {
    expect(APP_SRC).not.toMatch(/<<<<<<<|>>>>>>>|=======/)
  })
})
