// electronicsDomainPage.test.jsx — coverage for the Electronics domain page
// and its SEO metadata module.
//
// We test the pure-data contracts only (meta strings, JSON-LD shape, capability
// list contents, comparison table shape). React render is not exercised here —
// the component tree pulls in Header/Footer and the full router which require
// a browser-like environment outside the scope of the unit harness.

import { describe, it, expect } from 'vitest'
import { meta, jsonLd } from '../routes/domains/electronics.meta.js'

/* -------------------------------------------------------------------------- */
/* meta object                                                                  */
/* -------------------------------------------------------------------------- */

describe('electronics.meta — meta object', () => {
  it('has a title ≤60 characters', () => {
    expect(typeof meta.title).toBe('string')
    expect(meta.title.length).toBeLessThanOrEqual(60)
  })

  it('has a description ≤155 characters', () => {
    expect(typeof meta.description).toBe('string')
    expect(meta.description.length).toBeLessThanOrEqual(155)
  })

  it('includes the og object with required fields', () => {
    expect(meta.og).toBeDefined()
    expect(typeof meta.og.title).toBe('string')
    expect(typeof meta.og.description).toBe('string')
    expect(meta.og.image).toMatch(/^https:\/\/kerf\.sh\/og\//)
    expect(meta.og.url).toMatch(/^https:\/\/kerf\.sh\//)
    expect(meta.og.type).toBe('website')
  })

  it('og image points to the electronics asset', () => {
    expect(meta.og.image).toContain('electronics')
  })

  it('og url is on the /electronics path', () => {
    expect(meta.og.url).toContain('/electronics')
  })
})

/* -------------------------------------------------------------------------- */
/* JSON-LD                                                                      */
/* -------------------------------------------------------------------------- */

describe('electronics.meta — jsonLd', () => {
  it('is a WebPage type', () => {
    expect(jsonLd['@context']).toBe('https://schema.org')
    expect(jsonLd['@type']).toBe('WebPage')
  })

  it('has a name matching the meta title', () => {
    expect(jsonLd.name).toBe(meta.title)
  })

  it('has a mainEntity of type ItemList', () => {
    expect(jsonLd.mainEntity).toBeDefined()
    expect(jsonLd.mainEntity['@type']).toBe('ItemList')
  })

  it('itemListElement has at least 15 capabilities', () => {
    const items = jsonLd.mainEntity.itemListElement
    expect(Array.isArray(items)).toBe(true)
    expect(items.length).toBeGreaterThanOrEqual(15)
  })

  it('every item has position, @type ListItem, and a name string', () => {
    for (const item of jsonLd.mainEntity.itemListElement) {
      expect(item['@type']).toBe('ListItem')
      expect(typeof item.position).toBe('number')
      expect(typeof item.name).toBe('string')
      expect(item.name.length).toBeGreaterThan(0)
    }
  })

  it('positions are sequential starting from 1', () => {
    const positions = jsonLd.mainEntity.itemListElement.map((i) => i.position)
    for (let i = 0; i < positions.length; i++) {
      expect(positions[i]).toBe(i + 1)
    }
  })

  it('covers key real module names in item names', () => {
    const names = jsonLd.mainEntity.itemListElement.map((i) => i.name.toLowerCase())
    const joined = names.join(' ')
    // real kerf-electronics modules
    expect(joined).toContain('erc')
    expect(joined).toContain('gerber')
    expect(joined).toContain('spice')
    expect(joined).toContain('differential pair')
    expect(joined).toContain('panelize')
    expect(joined).toContain('testpoint')
    expect(joined).toContain('variant')
  })
})

/* -------------------------------------------------------------------------- */
/* Sanity: no invented module names in description                             */
/* -------------------------------------------------------------------------- */

describe('electronics.meta — copy integrity', () => {
  it('description does not contain cloud-internal tech (Paystack, bunny.net)', () => {
    const combined = [meta.description, meta.og.description].join(' ').toLowerCase()
    expect(combined).not.toContain('paystack')
    expect(combined).not.toContain('bunny.net')
  })

  it('meta title does not contain Claude or co-author markers', () => {
    expect(meta.title.toLowerCase()).not.toContain('claude')
    expect(meta.title.toLowerCase()).not.toContain('co-authored')
  })
})
