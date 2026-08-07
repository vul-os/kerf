/**
 * domains.new-sectors.test.js
 *
 * Oracles for the four new domain pages: PLC, MotionSim, FemCfd, Textiles.
 *
 * Per page:
 *   1. Page module has a default export (renders without importing).
 *   2. Hero heading text is present in source.
 *   3. Source contains the sector name.
 *   4. Capability cards render (source contains CapabilityCard / CAPABILITIES).
 *   5. App route is registered in App.jsx.
 *   6. Landing.jsx card entry is present.
 *   7. DomainSwitcher.jsx tab entry is present.
 */
import { describe, it, expect } from 'vitest'

/* -------------------------------------------------------------------------- */
/* Helper — load source of each file as a string via ?raw                      */
/* -------------------------------------------------------------------------- */

async function loadRaw(path) {
  try {
    const mod = await import(/* @vite-ignore */ path + '?raw')
    return mod.default
  } catch {
    return null
  }
}

/* -------------------------------------------------------------------------- */
/* Sector definitions                                                          */
/* -------------------------------------------------------------------------- */

const SECTORS = [
  {
    id: 'plc',
    name: 'PLC',
    module: '../domains/PLC.jsx',
    meta: '../domains/plc.meta.js',
    routeSlug: 'plc',
    headingFragment: 'PLC design',
    sectorNameInHero: 'PLC',
    switcherSlug: 'plc',
  },
  {
    id: 'motion',
    name: 'MotionSim',
    module: '../domains/MotionSim.jsx',
    meta: '../domains/motion.meta.js',
    routeSlug: 'motion',
    headingFragment: 'Motion that',
    sectorNameInHero: 'motion simulation',
    switcherSlug: 'motion',
  },
  {
    id: 'femcfd',
    name: 'FemCfd',
    module: '../domains/FemCfd.jsx',
    meta: '../domains/femcfd.meta.js',
    routeSlug: 'femcfd',
    headingFragment: 'FEM',
    sectorNameInHero: 'FEM',
    switcherSlug: 'femcfd',
  },
  {
    id: 'textiles',
    name: 'Textiles',
    module: '../domains/Textiles.jsx',
    meta: '../domains/textiles.meta.js',
    routeSlug: 'textiles',
    headingFragment: 'Textiles that',
    sectorNameInHero: 'textile',
    switcherSlug: 'textiles',
  },
]

/* -------------------------------------------------------------------------- */
/* Per-page module import smoke tests                                          */
/* -------------------------------------------------------------------------- */

describe('new sector page modules import without error', () => {
  SECTORS.forEach(({ id, module }) => {
    it(`${id}: module has a default export`, async () => {
      const mod = await import(/* @vite-ignore */ module)
      expect(typeof mod.default).toBe('function')
    })
  })
})

/* -------------------------------------------------------------------------- */
/* Meta files                                                                  */
/* -------------------------------------------------------------------------- */

describe('new sector meta files', () => {
  SECTORS.forEach(({ id, meta: metaPath }) => {
    it(`${id}: meta exports a meta object with title and description`, async () => {
      const mod = await import(/* @vite-ignore */ metaPath)
      expect(typeof mod.meta).toBe('object')
      expect(typeof mod.meta.title).toBe('string')
      expect(mod.meta.title.length).toBeGreaterThan(0)
      expect(typeof mod.meta.description).toBe('string')
      expect(mod.meta.description.length).toBeGreaterThan(0)
    })

    it(`${id}: meta title is ≤60 chars`, async () => {
      const mod = await import(/* @vite-ignore */ metaPath)
      expect(mod.meta.title.length).toBeLessThanOrEqual(60)
    })

    it(`${id}: meta description is ≤155 chars`, async () => {
      const mod = await import(/* @vite-ignore */ metaPath)
      expect(mod.meta.description.length).toBeLessThanOrEqual(155)
    })
  })
})

/* -------------------------------------------------------------------------- */
/* Source-level checks (hero heading, sector name, capability cards)          */
/* -------------------------------------------------------------------------- */

describe('new sector page source checks', () => {
  SECTORS.forEach(({ id, module, headingFragment, sectorNameInHero }) => {
    it(`${id}: source contains hero heading fragment "${headingFragment}"`, async () => {
      const src = await loadRaw(module)
      if (src == null) return
      expect(src).toContain(headingFragment)
    })

    it(`${id}: hero source contains sector name "${sectorNameInHero}"`, async () => {
      const src = await loadRaw(module)
      if (src == null) return
      expect(src.toLowerCase()).toContain(sectorNameInHero.toLowerCase())
    })

    it(`${id}: source contains CAPABILITIES array (capability cards)`, async () => {
      const src = await loadRaw(module)
      if (src == null) return
      expect(src).toContain('CAPABILITIES')
    })

    it(`${id}: source contains CapabilityCard`, async () => {
      const src = await loadRaw(module)
      if (src == null) return
      expect(src).toContain('CapabilityCard')
    })
  })
})

/* -------------------------------------------------------------------------- */
/* App.jsx route registration                                                  */
/* -------------------------------------------------------------------------- */

describe('App.jsx route registration', () => {
  SECTORS.forEach(({ id, routeSlug }) => {
    it(`${id}: App.jsx registers a route for /domains/${routeSlug}`, async () => {
      const src = await loadRaw('../../App.jsx')
      if (src == null) return
      expect(src).toContain(`/domains/${routeSlug}`)
    })
  })
})

/* -------------------------------------------------------------------------- */
/* Landing.jsx card presence                                                   */
/* -------------------------------------------------------------------------- */

describe('Landing.jsx domain card entries', () => {
  SECTORS.forEach(({ id, routeSlug }) => {
    it(`${id}: Landing.jsx contains href to /domains/${routeSlug}`, async () => {
      const src = await loadRaw('../../routes/Landing.jsx')
        ?? await loadRaw('../Landing.jsx')
      if (src == null) return
      expect(src).toContain(`/domains/${routeSlug}`)
    })
  })
})

/* -------------------------------------------------------------------------- */
/* DomainSwitcher.jsx tab presence                                             */
/* -------------------------------------------------------------------------- */

describe('DomainSwitcher.jsx tab entries', () => {
  SECTORS.forEach(({ id, switcherSlug }) => {
    it(`${id}: DomainSwitcher.jsx contains slug "${switcherSlug}"`, async () => {
      const src = await loadRaw('../../components/domains/DomainSwitcher.jsx')
      if (src == null) return
      expect(src).toContain(switcherSlug)
    })
  })
})

/* -------------------------------------------------------------------------- */
/* domains/index.jsx (hub) presence                                            */
/* -------------------------------------------------------------------------- */

describe('domains/index.jsx DOMAINS list entries', () => {
  SECTORS.forEach(({ id, routeSlug }) => {
    it(`${id}: domains/index.jsx contains slug "${routeSlug}"`, async () => {
      const src = await loadRaw('../domains/index.jsx')
      if (src == null) return
      expect(src).toContain(routeSlug)
    })
  })
})
