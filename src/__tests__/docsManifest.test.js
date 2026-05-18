// docsManifest.test.js — regression guard for "docs not showing on local/dev".
//
// Strategy (matches the project's no-DOM convention — see
// mechanicalDomainPage.test.jsx): the docs UI is React, but the load-bearing
// surface is the pure data layer in docsStore.js. The bug was in
// `flattenManifest`: the v2 manifest carries a grouped sidebar projection
// (`groups[].items`, NO `body`) AND a flat list (`items`/`entries`, the full
// records WITH `body`). The old code walked `groups` first and marked every
// slug seen, so the body-bearing flat entries were all dropped — every article
// rendered blank (Article.jsx reads `entry.body`).
//
// We assert (1) flattenManifest prefers the body-bearing flat list, (2) the
// real shipped manifest is healthy, and (3) the store hydrates bySlug WITH
// body (article render) plus entries/recent/index (index render).

import { readFileSync } from 'node:fs'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flattenManifest, useDocs } from '../routes/Docs/docsStore.js'

const REAL_MANIFEST = JSON.parse(
  readFileSync(new URL('../../public/docs-manifest.json', import.meta.url), 'utf8'),
)

describe('flattenManifest — prefers the body-bearing flat list', () => {
  it('returns flat `items` records (with body), not the bodyless group projection', () => {
    const manifest = {
      version: 2,
      groups: [
        // sidebar projection — deliberately NO body, plus a non-article route link
        { id: 'get-started', label: 'Get started', items: [
          { slug: 'getting-started', title: 'Getting started', path: 'docs/getting-started.md' },
        ] },
        { id: 'domains', label: 'Domains', items: [
          { id: 'jewelry', title: 'Jewelry', route: '/domains/jewelry' },
        ] },
      ],
      items: [
        { slug: 'getting-started', title: 'Getting started', group: 'get-started',
          body: '# Getting started\n\nReal article body.', source: 'docs/getting-started.md' },
      ],
      entries: [
        { slug: 'getting-started', title: 'Getting started', group: 'get-started',
          body: '# Getting started\n\nReal article body.', source: 'docs/getting-started.md' },
      ],
    }
    const flat = flattenManifest(manifest)
    expect(flat).toHaveLength(1)
    expect(flat[0].slug).toBe('getting-started')
    expect(flat[0].body).toContain('Real article body.')
    // The Domains route-link is NOT an article and must not leak in as a
    // bodyless entry.
    expect(flat.find((e) => e.slug === 'jewelry')).toBeUndefined()
  })

  it('falls back to group items for a true legacy grouped-only manifest', () => {
    const legacy = {
      groups: [{ id: 'g', label: 'G', items: [{ slug: 'x', title: 'X', body: 'legacy body' }] }],
    }
    const flat = flattenManifest(legacy)
    expect(flat.map((e) => e.slug)).toEqual(['x'])
    expect(flat[0].body).toBe('legacy body')
  })

  it('is null/empty safe', () => {
    expect(flattenManifest(null)).toEqual([])
    expect(flattenManifest({})).toEqual([])
  })
})

describe('shipped docs-manifest.json is healthy', () => {
  it('is v2 with grouped + flat shapes', () => {
    expect(REAL_MANIFEST.version).toBe(2)
    expect(Array.isArray(REAL_MANIFEST.groups)).toBe(true)
    expect(Array.isArray(REAL_MANIFEST.items)).toBe(true)
    expect(REAL_MANIFEST.items.length).toBeGreaterThan(10)
  })

  it('every flat item carries a non-empty body (else articles render blank)', () => {
    const bodyless = REAL_MANIFEST.items.filter((e) => !e.body || !String(e.body).trim())
    expect(bodyless.map((e) => e.slug)).toEqual([])
  })

  it('flattenManifest yields one body-bearing entry per shipped item', () => {
    const flat = flattenManifest(REAL_MANIFEST)
    expect(flat.length).toBe(REAL_MANIFEST.items.length)
    for (const e of flat) {
      expect(e.slug, `slug missing on ${JSON.stringify(e).slice(0, 80)}`).toBeTruthy()
      expect(typeof e.body).toBe('string')
      expect(e.body.trim().length).toBeGreaterThan(0)
    }
  })
})

describe('useDocs store hydrates the docs index + an article', () => {
  beforeEach(() => {
    useDocs.setState({
      status: 'idle', error: null, manifest: null, entries: [],
      bySlug: new Map(), byGroup: [], recent: [], index: null,
    })
    vi.restoreAllMocks()
  })

  it('load() → ready, with bySlug bodies (article) and entries/recent/index (index)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => REAL_MANIFEST,
    })))

    await useDocs.getState().load()
    const s = useDocs.getState()

    expect(s.status).toBe('ready')
    expect(s.error).toBeNull()
    // Index render path: a populated, searchable, recency-sorted corpus.
    expect(s.entries.length).toBeGreaterThan(10)
    expect(s.recent.length).toBeGreaterThan(0)
    expect(s.index).toBeTruthy()
    // Article render path: a known article resolves WITH body (the regression).
    const known = REAL_MANIFEST.items[0].slug
    const entry = s.bySlug.get(known)
    expect(entry).toBeTruthy()
    expect(typeof entry.body).toBe('string')
    expect(entry.body.trim().length).toBeGreaterThan(0)
  })

  it('surfaces a fetch failure as status=error (not a silent blank page)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404 })))
    await useDocs.getState().load()
    expect(useDocs.getState().status).toBe('error')
  })
})
