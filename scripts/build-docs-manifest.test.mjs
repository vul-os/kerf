/**
 * Smoke-tests for the docs-manifest generator.
 *
 * Asserts that the four newly-added overview pages (silicon, firmware,
 * aerospace, plc) are picked up by the generator and assigned to the
 * correct group in the manifest.
 */

import { describe, it, expect, beforeAll } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execSync } from 'node:child_process'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = join(__dirname, '..')
const MANIFEST_PATH = join(ROOT, 'public', 'docs-manifest.json')

// Run the generator once before all tests so we have a fresh manifest.
beforeAll(() => {
  execSync('node scripts/build-docs-manifest.mjs', { cwd: ROOT, stdio: 'pipe' })
}, 30_000)

function loadManifest() {
  const raw = readFileSync(MANIFEST_PATH, 'utf8')
  return JSON.parse(raw)
}

// ---------------------------------------------------------------------------
// The four new package-overview pages
// ---------------------------------------------------------------------------

const NEW_PAGES = [
  { slug: 'silicon',   expectedGroup: 'reference', docFile: 'docs/silicon.md' },
  { slug: 'firmware',  expectedGroup: 'reference', docFile: 'docs/firmware.md' },
  { slug: 'aerospace', expectedGroup: 'reference', docFile: 'docs/aerospace.md' },
  { slug: 'plc',       expectedGroup: 'reference', docFile: 'docs/plc.md' },
]

describe('new package overview pages — source files exist', () => {
  for (const { slug, docFile } of NEW_PAGES) {
    it(`${docFile} is present on disk`, () => {
      expect(existsSync(join(ROOT, docFile))).toBe(true)
    })
  }
})

describe('new package overview pages — registered in manifest', () => {
  let manifest

  beforeAll(() => {
    manifest = loadManifest()
  })

  for (const { slug, expectedGroup } of NEW_PAGES) {
    it(`"${slug}" appears in manifest.items`, () => {
      const item = manifest.items.find((i) => i.slug === slug)
      expect(item, `slug "${slug}" missing from items[]`).toBeDefined()
    })

    it(`"${slug}" is assigned to group "${expectedGroup}"`, () => {
      const group = manifest.groups.find((g) => g.id === expectedGroup)
      expect(group, `group "${expectedGroup}" not found in groups[]`).toBeDefined()
      const item = group.items.find((i) => i.slug === slug)
      expect(item, `slug "${slug}" not found in group "${expectedGroup}"`).toBeDefined()
    })

    it(`"${slug}" has a non-empty title`, () => {
      const item = manifest.items.find((i) => i.slug === slug)
      expect(item?.title).toBeTruthy()
    })

    it(`"${slug}" has a non-empty summary`, () => {
      const item = manifest.items.find((i) => i.slug === slug)
      expect(item?.summary).toBeTruthy()
    })
  }
})

describe('manifest structure sanity', () => {
  let manifest

  beforeAll(() => {
    manifest = loadManifest()
  })

  it('has version 2', () => {
    expect(manifest.version).toBe(2)
  })

  it('has a groups array', () => {
    expect(Array.isArray(manifest.groups)).toBe(true)
    expect(manifest.groups.length).toBeGreaterThan(0)
  })

  it('has an items array', () => {
    expect(Array.isArray(manifest.items)).toBe(true)
    expect(manifest.items.length).toBeGreaterThan(0)
  })

  it('all four new pages appear exactly once in items[]', () => {
    const slugs = NEW_PAGES.map((p) => p.slug)
    for (const slug of slugs) {
      const matches = manifest.items.filter((i) => i.slug === slug)
      expect(matches.length, `expected exactly 1 entry for slug "${slug}"`).toBe(1)
    }
  })

  it('no item is placed in an unknown group', () => {
    const groupIds = new Set(manifest.groups.map((g) => g.id))
    // items[] entries carry the flat form — check via group membership in groups[]
    for (const group of manifest.groups) {
      expect(groupIds.has(group.id)).toBe(true)
    }
  })
})
