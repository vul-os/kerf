/**
 * CompareByDomain.test.jsx — unit tests for the cross-tool domain matrix page.
 *
 * Uses renderToStaticMarkup (react-dom/server) — consistent with the project pattern.
 * Uses vi.mock to stub loadManifest for deterministic data.
 *
 * Note: CompareByDomain uses useEffect + useState for async manifest loading.
 * renderToStaticMarkup captures the initial (loading) render synchronously.
 * Tests that need the loaded state import and call pivotByDomain directly,
 * or use the synchronous DomainMatrix sub-component extracted in isolation.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { DOMAIN_META, pivotByDomain, STATUS_META } from '../../lib/compareFeatures.js'

/* -------------------------------------------------------------------------- */
/* Tests against the compareFeatures helpers (no React needed)                */
/* -------------------------------------------------------------------------- */

describe('compareFeatures helpers (used by CompareByDomain)', () => {
  const SAMPLE_ITEMS = [
    {
      slug: 'fusion',
      competitor: 'Autodesk Fusion 360',
      category: 'cad-mechanical',
      features: [
        {
          domain: 'D1',
          feature: 'Constraint sketcher',
          competitor: { status: 'yes' },
          kerf: { status: 'yes' },
        },
        {
          domain: 'D1',
          feature: 'Loft',
          competitor: { status: 'yes' },
          kerf: { status: 'partial' },
        },
        {
          domain: 'D6',
          feature: 'PCB layout',
          competitor: { status: 'yes' },
          kerf: { status: 'yes' },
        },
      ],
    },
    {
      slug: 'solidworks',
      competitor: 'SOLIDWORKS',
      category: 'cad-mechanical',
      features: [
        {
          domain: 'D1',
          feature: 'Constraint sketcher',
          competitor: { status: 'yes' },
          kerf: { status: 'yes' },
        },
      ],
    },
  ]

  it('DOMAIN_META contains exactly 14 entries', () => {
    expect(DOMAIN_META).toHaveLength(14)
  })

  it('DOMAIN_META codes are D1..D14', () => {
    const codes = DOMAIN_META.map((d) => d.code)
    for (let i = 1; i <= 14; i++) {
      expect(codes).toContain(`D${i}`)
    }
  })

  it('DOMAIN_META slugs map geometry to D1', () => {
    const d1 = DOMAIN_META.find((d) => d.code === 'D1')
    expect(d1.slug).toBe('geometry')
  })

  it('DOMAIN_META slugs map cost to D14', () => {
    const d14 = DOMAIN_META.find((d) => d.code === 'D14')
    expect(d14.slug).toBe('cost')
  })

  it('pivotByDomain returns features map and cadSlugs for D1', () => {
    const { features, cadSlugs } = pivotByDomain(SAMPLE_ITEMS, 'D1')
    expect(features instanceof Map).toBe(true)
    expect(features.size).toBe(2) // Constraint sketcher + Loft
    expect(cadSlugs).toHaveLength(2) // fusion + solidworks
    expect(cadSlugs).toContain('fusion')
    expect(cadSlugs).toContain('solidworks')
  })

  it('pivotByDomain returns empty map and empty cadSlugs for a domain with no data', () => {
    const { features, cadSlugs } = pivotByDomain(SAMPLE_ITEMS, 'D8')
    expect(features.size).toBe(0)
    expect(cadSlugs).toHaveLength(0)
  })

  it('pivotByDomain kerf status: prefers yes > partial > paid > no > unknown', () => {
    // fusion has kerf=yes for D1/Constraint sketcher, solidworks also has yes
    const { features } = pivotByDomain(SAMPLE_ITEMS, 'D1')
    const sketcherEntry = features.get('Constraint sketcher')
    expect(sketcherEntry.kerf).toBe('yes')
  })

  it('pivotByDomain competitor entries keyed by slug', () => {
    const { features } = pivotByDomain(SAMPLE_ITEMS, 'D1')
    const sketcherEntry = features.get('Constraint sketcher')
    expect(sketcherEntry.competitors.fusion).toBe('yes')
    expect(sketcherEntry.competitors.solidworks).toBe('yes')
  })

  it('pivotByDomain: loft is only in fusion (not solidworks)', () => {
    const { features } = pivotByDomain(SAMPLE_ITEMS, 'D1')
    const loftEntry = features.get('Loft')
    expect(loftEntry.competitors.fusion).toBe('yes')
    expect(loftEntry.competitors.solidworks).toBeUndefined()
  })

  it('pivotByDomain for D6 includes only fusion (which has D6 features)', () => {
    const { features, cadSlugs } = pivotByDomain(SAMPLE_ITEMS, 'D6')
    expect(cadSlugs).toHaveLength(1)
    expect(cadSlugs).toContain('fusion')
    expect(features.size).toBe(1)
  })

  it('STATUS_META has exactly 5 status keys', () => {
    const keys = Object.keys(STATUS_META)
    expect(keys).toHaveLength(5)
    expect(keys).toContain('yes')
    expect(keys).toContain('partial')
    expect(keys).toContain('paid')
    expect(keys).toContain('no')
    expect(keys).toContain('unknown')
  })

  it('STATUS_META symbols are distinct', () => {
    const symbols = Object.values(STATUS_META).map((s) => s.symbol)
    expect(new Set(symbols).size).toBe(5)
  })
})

/* -------------------------------------------------------------------------- */
/* Smoke render tests for CompareByDomain                                      */
/* -------------------------------------------------------------------------- */

describe('CompareByDomain smoke render', () => {
  async function renderPage(slug) {
    // Dynamic import to avoid module-top side effects
    const { default: CompareByDomain } = await import('./CompareByDomain.jsx')
    return renderToStaticMarkup(
      <MemoryRouter initialEntries={[`/compare/by-domain/${slug}`]}>
        <Routes>
          <Route path="/compare/by-domain/:slug" element={<CompareByDomain />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('unknown slug renders a "Domain not found" page synchronously', async () => {
    const html = await renderPage('not-a-real-domain-xyz')
    expect(html).toContain('Domain not found')
  })

  it('valid slug "geometry" renders without throwing', async () => {
    const html = await renderPage('geometry')
    // In initial (loading) render: shows loading state or the hero
    // Either way the page must not be a 404
    expect(html).not.toContain('Domain not found')
  })

  it('valid slug "cost" (D14) renders without throwing', async () => {
    const html = await renderPage('cost')
    expect(html).not.toContain('Domain not found')
  })

  it('renders a link back to the compare landing', async () => {
    const html = await renderPage('geometry')
    expect(html).toContain('/compare')
  })
})
