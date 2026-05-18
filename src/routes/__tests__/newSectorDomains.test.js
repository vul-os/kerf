/**
 * newSectorDomains.test.js — pure-module smoke tests for the T-182 new sector
 * domain meta files.
 *
 * Strategy: each domain exports META_TITLE, META_DESCRIPTION, META_OG_IMAGE,
 * META_URL, FEATURES, and JSON_LD. We verify the SEO contract on every module
 * without mounting any React component (no DOM environment required).
 */
import { describe, it, expect } from 'vitest'
import * as compositesMeta from '../domains/composites.meta.js'
import * as dentalMeta from '../domains/dental.meta.js'
import * as opticsMeta from '../domains/optics.meta.js'
import * as horologyMeta from '../domains/horology.meta.js'
import * as pipingMeta from '../domains/piping.meta.js'
import * as packagingMeta from '../domains/packaging.meta.js'
import * as moldMeta from '../domains/mold.meta.js'
import * as woodworkingMeta from '../domains/woodworking.meta.js'
import * as marineMeta from '../domains/marine.meta.js'
import * as civilMeta from '../domains/civil.meta.js'

const ALL_METAS = [
  { name: 'composites', mod: compositesMeta, slug: 'composites' },
  { name: 'dental', mod: dentalMeta, slug: 'dental' },
  { name: 'optics', mod: opticsMeta, slug: 'optics' },
  { name: 'horology', mod: horologyMeta, slug: 'horology' },
  { name: 'piping', mod: pipingMeta, slug: 'piping' },
  { name: 'packaging', mod: packagingMeta, slug: 'packaging' },
  { name: 'mold', mod: moldMeta, slug: 'mold' },
  { name: 'woodworking', mod: woodworkingMeta, slug: 'woodworking' },
  { name: 'marine', mod: marineMeta, slug: 'marine' },
  { name: 'civil', mod: civilMeta, slug: 'civil' },
]

/* -------------------------------------------------------------------------- */
/* Shared contract tests applied to every new meta module                     */
/* -------------------------------------------------------------------------- */

for (const { name, mod, slug } of ALL_METAS) {
  describe(`${name}.meta — META_TITLE`, () => {
    it('is a non-empty string', () => {
      expect(typeof mod.META_TITLE).toBe('string')
      expect(mod.META_TITLE.length).toBeGreaterThan(0)
    })

    it('is ≤ 60 characters', () => {
      expect(mod.META_TITLE.length).toBeLessThanOrEqual(60)
    })

    it('contains "Kerf"', () => {
      expect(mod.META_TITLE).toMatch(/Kerf/i)
    })
  })

  describe(`${name}.meta — META_DESCRIPTION`, () => {
    it('is a non-empty string', () => {
      expect(typeof mod.META_DESCRIPTION).toBe('string')
      expect(mod.META_DESCRIPTION.length).toBeGreaterThan(0)
    })

    it('is ≤ 155 characters', () => {
      expect(mod.META_DESCRIPTION.length).toBeLessThanOrEqual(155)
    })
  })

  describe(`${name}.meta — META_OG_IMAGE`, () => {
    it('points to the correct kerf.sh OG image', () => {
      expect(mod.META_OG_IMAGE).toBe(`https://kerf.sh/og/${slug}.png`)
    })
  })

  describe(`${name}.meta — META_URL`, () => {
    it('is the canonical page URL', () => {
      expect(mod.META_URL).toBe(`https://kerf.sh/domains/${slug}`)
    })
  })

  describe(`${name}.meta — FEATURES`, () => {
    it('is a non-empty array', () => {
      expect(Array.isArray(mod.FEATURES)).toBe(true)
      expect(mod.FEATURES.length).toBeGreaterThan(0)
    })

    it('every feature has id, name, description', () => {
      for (const f of mod.FEATURES) {
        expect(typeof f.id).toBe('string')
        expect(f.id.length).toBeGreaterThan(0)
        expect(typeof f.name).toBe('string')
        expect(f.name.length).toBeGreaterThan(0)
        expect(typeof f.description).toBe('string')
        expect(f.description.length).toBeGreaterThan(0)
      }
    })

    it('feature ids are unique', () => {
      const ids = mod.FEATURES.map((f) => f.id)
      expect(new Set(ids).size).toBe(ids.length)
    })

    it('has at least 3 features', () => {
      expect(mod.FEATURES.length).toBeGreaterThanOrEqual(3)
    })
  })

  describe(`${name}.meta — JSON_LD`, () => {
    it('is a non-null object', () => {
      expect(typeof mod.JSON_LD).toBe('object')
      expect(mod.JSON_LD).not.toBeNull()
    })

    it('has schema.org context', () => {
      expect(mod.JSON_LD['@context']).toBe('https://schema.org')
    })

    it('has a @graph array with WebPage and ItemList', () => {
      const graph = mod.JSON_LD['@graph']
      expect(Array.isArray(graph)).toBe(true)
      const webPage = graph.find((n) => n['@type'] === 'WebPage')
      expect(webPage).toBeTruthy()
      expect(webPage.url).toBe(mod.META_URL)
      const list = graph.find((n) => n['@type'] === 'ItemList')
      expect(list).toBeTruthy()
      expect(list.numberOfItems).toBe(mod.FEATURES.length)
    })

    it('is JSON-serialisable', () => {
      expect(() => JSON.stringify(mod.JSON_LD)).not.toThrow()
    })
  })
}

/* -------------------------------------------------------------------------- */
/* Domain-specific content spot-checks                                        */
/* -------------------------------------------------------------------------- */

describe('composites.meta — domain-specific', () => {
  it('mentions CLT or laminate', () => {
    const text = compositesMeta.FEATURES.map((f) => f.description).join(' ')
    expect(text).toMatch(/CLT|laminate/i)
  })
})

describe('dental.meta — domain-specific', () => {
  it('mentions crown or bridge', () => {
    const text = dentalMeta.FEATURES.map((f) => f.name + f.description).join(' ')
    expect(text).toMatch(/crown|bridge/i)
  })
})

describe('optics.meta — domain-specific', () => {
  it('mentions ray tracing', () => {
    const text = opticsMeta.FEATURES.map((f) => f.name + f.description).join(' ')
    expect(text).toMatch(/ray/i)
  })
})

describe('horology.meta — domain-specific', () => {
  it('mentions escapement or gear', () => {
    const text = horologyMeta.FEATURES.map((f) => f.name + f.description).join(' ')
    expect(text).toMatch(/escapement|gear/i)
  })
})

describe('piping.meta — domain-specific', () => {
  it('mentions ASME or ISO 10628', () => {
    const text = pipingMeta.FEATURES.map((f) => f.description).join(' ')
    expect(text).toMatch(/ASME|ISO 10628/i)
  })
})

describe('packaging.meta — domain-specific', () => {
  it('mentions ECMA or dieline', () => {
    const text = packagingMeta.FEATURES.map((f) => f.description).join(' ')
    expect(text).toMatch(/ECMA|dieline/i)
  })
})

describe('mold.meta — domain-specific', () => {
  it('mentions core or cavity', () => {
    const text = moldMeta.FEATURES.map((f) => f.description).join(' ')
    expect(text).toMatch(/core|cavity/i)
  })
})

describe('woodworking.meta — domain-specific', () => {
  it('mentions joinery or CNC', () => {
    const text = woodworkingMeta.FEATURES.map((f) => f.description).join(' ')
    expect(text).toMatch(/joinery|CNC/i)
  })
})

describe('marine.meta — domain-specific', () => {
  it('mentions hull or hydrostatic', () => {
    const text = marineMeta.FEATURES.map((f) => f.description).join(' ')
    expect(text).toMatch(/hull|hydrostatic/i)
  })
})

describe('civil.meta — domain-specific', () => {
  it('mentions hydrology or geotech', () => {
    const text = civilMeta.FEATURES.map((f) => f.description).join(' ')
    expect(text).toMatch(/hydrology|geotech|Coulomb/i)
  })
})
