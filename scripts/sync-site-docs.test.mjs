// Gate for `site/docs/` — the markdown the standalone static site fetches.
//
// site/docs.html curates a hand-ordered subset of the docs corpus by
// `data-slug`, and site/docs/<slug>.md is supposed to be that doc. It was an
// UNGATED partial mirror: 30 of 58 files had drifted from their sources (one
// still pointed readers at `oss-cloud-separation.md`, deleted in bfdbd635) and
// nothing in the suite noticed. scripts/sync-site-docs.mjs makes those files
// derived; this file is what keeps them derived.
//
// FAIL-CLOSED, and deliberately not skippable: every input it needs
// (site/docs.html, the docs sources, the generated manifest) is in this
// checkout, so there is no "not available here" case to skip for. If a source
// doc changes and site/docs is not re-synced, this fails.
//
// COVERAGE ASSERTIONS: a mirror gate is exactly the sort of test that can pass
// by iterating an empty list, so the counts are pinned before anything is
// compared — a nav with no slugs, or a site/docs with no files, fails loudly
// rather than passing vacuously.

import { describe, it, expect, beforeAll } from 'vitest'
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { navSlugs, slugToPath, plan, regenerateManifest } from './sync-site-docs.mjs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SITE_DOCS_HTML = join(ROOT, 'site', 'docs.html')
const SITE_DOCS_DIR = join(ROOT, 'site', 'docs')
const MANIFEST = join(ROOT, 'public', 'docs-manifest.json')

// The size of the curated subset. A count, not just a set comparison: a change
// that both adds and removes a nav entry must still be a deliberate edit here.
const EXPECTED_CURATED_SLUGS = 58

let html
let manifest

beforeAll(() => {
  // Derive the slug map from the docs sources as they are on disk right now,
  // so "did site/docs drift" is a question about the sources and not about a
  // stale build artifact. Same call predev/prebuild:web make.
  regenerateManifest()
  html = readFileSync(SITE_DOCS_HTML, 'utf8')
  manifest = JSON.parse(readFileSync(MANIFEST, 'utf8'))
}, 60_000)

describe('site/docs — the gate has something to check', () => {
  it('finds the curated nav and the mirrored files', () => {
    expect(existsSync(SITE_DOCS_HTML)).toBe(true)
    expect(existsSync(SITE_DOCS_DIR)).toBe(true)

    const slugs = navSlugs(html)
    expect(slugs.length).toBe(EXPECTED_CURATED_SLUGS)

    const files = readdirSync(SITE_DOCS_DIR).filter((f) => f.endsWith('.md'))
    expect(files.length).toBe(EXPECTED_CURATED_SLUGS)

    // The manifest must actually carry a slug->path map, or every comparison
    // below would be skipped as "unresolved" and the gate would check nothing.
    const map = slugToPath(manifest)
    expect(map.size).toBeGreaterThan(EXPECTED_CURATED_SLUGS)
  })
})

describe('site/docs is a synced curated subset, not a stale partial mirror', () => {
  it('every nav slug resolves to a doc that still exists', () => {
    const { unresolved } = plan({ html, manifest })
    expect(
      unresolved,
      `site/docs.html links slugs no doc provides: ${unresolved.join(', ')}. ` +
        'Remove the nav entry (the doc was deleted) or repoint it (the slug changed).',
    ).toEqual([])
  })

  it('every mirrored file is byte-identical to its source', () => {
    const { copies } = plan({ html, manifest })
    expect(copies.length).toBe(EXPECTED_CURATED_SLUGS)

    const drifted = copies
      .filter((c) => c.current !== c.desired)
      .map((c) => `site/docs/${c.slug}.md != ${c.rel}${c.current === null ? ' (missing)' : ''}`)

    expect(
      drifted,
      `${drifted.length} file(s) in site/docs have drifted from the docs corpus. ` +
        'These files are GENERATED — do not edit them. Run: node scripts/sync-site-docs.mjs',
    ).toEqual([])
  })

  it('holds no file the curated nav does not reference', () => {
    const { orphans } = plan({ html, manifest })
    expect(
      orphans,
      `site/docs holds ${orphans.length} file(s) the nav never links, so nothing ` +
        'keeps them current: ' + orphans.join(', ') + '. Run: node scripts/sync-site-docs.mjs',
    ).toEqual([])
  })

  it('lists each slug exactly once in the nav', () => {
    expect(() => navSlugs(html)).not.toThrow()
  })
})
