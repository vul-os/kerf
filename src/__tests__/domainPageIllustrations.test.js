/**
 * domainPageIllustrations.test.js
 *
 * Tests that:
 *   1. DomainPage.jsx exports a default function (the shared template).
 *   2. Every domain page that uses DomainPage exports HERO_ILLUSTRATION and/or
 *      CAPABILITY_ILLUSTRATIONS with the correct shape.
 *   3. The illustration components referenced come from the illustrations index
 *      and are callable React components (functions).
 *   4. DomainPage accepts heroIllustration + capabilityIllustrations as optional
 *      props (source-level check).
 *
 * Strategy: no DOM rendering — pure module import + shape assertions. This
 * matches the pattern used in mechanicalDomainPage.test.jsx and the
 * newSectorDomains.test.js files.
 */
import { describe, it, expect } from 'vitest'

/* -------------------------------------------------------------------------- */
/* DomainPage template module                                                  */
/* -------------------------------------------------------------------------- */

import DomainPage from '../routes/domains/DomainPage.jsx'

describe('DomainPage', () => {
  it('exports a default function (React component)', () => {
    expect(typeof DomainPage).toBe('function')
  })

  it('accepts heroIllustration prop (source-level check)', async () => {
    const mod = await import('../routes/domains/DomainPage.jsx?raw')
    const src = mod.default
    expect(src).toContain('heroIllustration')
  })

  it('accepts capabilityIllustrations prop (source-level check)', async () => {
    const mod = await import('../routes/domains/DomainPage.jsx?raw')
    const src = mod.default
    expect(src).toContain('capabilityIllustrations')
  })

  it('renders hero illustration when provided (source-level check)', async () => {
    const mod = await import('../routes/domains/DomainPage.jsx?raw')
    const src = mod.default
    expect(src).toContain('HeroIllustration')
    // Should be rendered inside the hero grid layout
    expect(src).toContain('lg:grid-cols-')
  })

  it('renders CapabilityIllustrations section when items provided (source-level check)', async () => {
    const mod = await import('../routes/domains/DomainPage.jsx?raw')
    const src = mod.default
    expect(src).toContain('CapabilityIllustrations')
    expect(src).toContain('figcaption')
  })
})

/* -------------------------------------------------------------------------- */
/* Illustration index exports                                                  */
/* -------------------------------------------------------------------------- */

describe('illustrations/index.js', () => {
  it('exports all 25 named illustration components', async () => {
    const mod = await import('../components/illustrations/index.js')
    const expected = [
      'HeroIllustration',
      'JscadIllustration',
      'FeatureTreeIllustration',
      'SketcherIllustration',
      'DrawingIllustration',
      'CircuitIllustration',
      'LibraryIllustration',
      'WorkshopIllustration',
      'ChatLoopIllustration',
      'FemIllustration',
      'TopoIllustration',
      'CamIllustration',
      'BimIllustration',
      'GitIllustration',
      'ScriptingIllustration',
      'PipelineIllustration',
      'SketchShortcutsIllustration',
      'SketchToJscadIllustration',
      'SpiceSimIllustration',
      'RfAnalysisIllustration',
      'RevitParityIllustration',
      'StairsMepIllustration',
      'ViewportScaleIllustration',
      'FineGrainedUndoIllustration',
      'TolerancePlusMatesIllustration',
    ]
    for (const name of expected) {
      expect(typeof mod[name]).toBe('function')
    }
  })
})

/* -------------------------------------------------------------------------- */
/* Per-domain illustration mapping tests                                       */
/* -------------------------------------------------------------------------- */

/**
 * Domain pages using the DomainPage template that export HERO_ILLUSTRATION.
 * Each entry: { name, module, expectCapability }
 */
const TEMPLATE_DOMAINS = [
  { name: 'Civil', module: '../routes/domains/Civil.jsx', expectCapability: true },
  { name: 'Horology', module: '../routes/domains/Horology.jsx', expectCapability: true },
  { name: 'Composites', module: '../routes/domains/Composites.jsx', expectCapability: true },
  { name: 'Dental', module: '../routes/domains/Dental.jsx', expectCapability: false },
  { name: 'Marine', module: '../routes/domains/Marine.jsx', expectCapability: true },
  { name: 'Packaging', module: '../routes/domains/Packaging.jsx', expectCapability: false },
  { name: 'Mold', module: '../routes/domains/Mold.jsx', expectCapability: true },
  { name: 'Optics', module: '../routes/domains/Optics.jsx', expectCapability: false },
  { name: 'Piping', module: '../routes/domains/Piping.jsx', expectCapability: false },
  { name: 'Woodworking', module: '../routes/domains/Woodworking.jsx', expectCapability: false },
]

describe('DomainPage template domains — HERO_ILLUSTRATION exports', () => {
  TEMPLATE_DOMAINS.forEach(({ name, module }) => {
    it(`${name}: exports HERO_ILLUSTRATION as a function`, async () => {
      const mod = await import(/* @vite-ignore */ module)
      expect(typeof mod.HERO_ILLUSTRATION).toBe('function')
    })
  })
})

describe('DomainPage template domains — CAPABILITY_ILLUSTRATIONS exports', () => {
  TEMPLATE_DOMAINS.filter((d) => d.expectCapability).forEach(({ name, module }) => {
    it(`${name}: exports CAPABILITY_ILLUSTRATIONS as a non-empty array`, async () => {
      const mod = await import(/* @vite-ignore */ module)
      expect(Array.isArray(mod.CAPABILITY_ILLUSTRATIONS)).toBe(true)
      expect(mod.CAPABILITY_ILLUSTRATIONS.length).toBeGreaterThan(0)
    })

    it(`${name}: each CAPABILITY_ILLUSTRATIONS entry has Illustration function + caption string`, async () => {
      const mod = await import(/* @vite-ignore */ module)
      for (const entry of mod.CAPABILITY_ILLUSTRATIONS) {
        expect(typeof entry.Illustration).toBe('function')
        expect(typeof entry.caption).toBe('string')
        expect(entry.caption.length).toBeGreaterThan(0)
      }
    })
  })
})

/**
 * Custom domain pages (non-template) that also export HERO_ILLUSTRATION.
 */
const CUSTOM_DOMAINS = [
  { name: 'Mechanical', module: '../routes/domains/Mechanical.jsx' },
  { name: 'Electronics', module: '../routes/domains/Electronics.jsx' },
  { name: 'FemCfd', module: '../routes/domains/FemCfd.jsx' },
  { name: 'Architecture', module: '../routes/domains/Architecture.jsx' },
  { name: 'Aerospace', module: '../routes/domains/Aerospace.jsx' },
  { name: 'Automotive', module: '../routes/domains/Automotive.jsx' },
  { name: 'Jewelry', module: '../routes/domains/Jewelry.jsx' },
  { name: 'MotionSim', module: '../routes/domains/MotionSim.jsx' },
  { name: 'PLC', module: '../routes/domains/PLC.jsx' },
  { name: 'Firmware', module: '../routes/domains/Firmware.jsx' },
  { name: 'Silicon', module: '../routes/domains/Silicon.jsx' },
  { name: 'Textiles', module: '../routes/domains/Textiles.jsx' },
]

describe('Custom domain pages — HERO_ILLUSTRATION exports', () => {
  CUSTOM_DOMAINS.forEach(({ name, module }) => {
    it(`${name}: exports HERO_ILLUSTRATION as a function`, async () => {
      const mod = await import(/* @vite-ignore */ module)
      expect(typeof mod.HERO_ILLUSTRATION).toBe('function')
    })
  })
})

/**
 * Source-level check: DomainPage-template pages pass heroIllustration prop.
 */
describe('DomainPage template domains — heroIllustration prop wired in source', () => {
  TEMPLATE_DOMAINS.forEach(({ name, module }) => {
    it(`${name}: source contains heroIllustration=`, async () => {
      const raw = await import(/* @vite-ignore */ module + '?raw')
      expect(raw.default).toContain('heroIllustration=')
    })
  })
})
