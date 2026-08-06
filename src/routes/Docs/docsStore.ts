import { create } from 'zustand'
import { buildIndex, type DocEntry, type SearchIndexData } from './searchIndex.js'
import { isInternalPlanning, type DocsManifest } from './groupTaxonomy.js'

export interface DocGroupBucket {
  group?: string
  items: DocEntry[]
}

export interface DocsState {
  status: 'idle' | 'loading' | 'ready' | 'error'
  error: string | null
  manifest: DocsManifest | null // raw manifest (flat or grouped — taxonomy helpers normalize)
  entries: DocEntry[]           // flat, internal-planning entries already stripped
  bySlug: Map<string, DocEntry>
  byGroup: DocGroupBucket[]     // legacy by-manifest-group buckets (still consumed by search results)
  recent: DocEntry[]            // top 5 by mtime, descending
  index: SearchIndexData | null // search index from buildIndex(entries)
  load: () => Promise<void>
}

// Single in-memory store for the docs corpus. The manifest is a static asset
// emitted by `scripts/build-docs-manifest.mjs` at build time, so we just fetch
// it once on mount, build the search index, and hold both for the rest of the
// session. The store is also the cache layer when the user navigates between
// articles — we don't refetch the manifest on /docs/:slug pages.

export const useDocs = create<DocsState>()((set, get) => ({
  status: 'idle', // idle | loading | ready | error
  error: null,
  manifest: null, // raw manifest (flat or grouped — taxonomy helpers normalize)
  entries: [],    // flat, internal-planning entries already stripped
  bySlug: new Map(),
  byGroup: [],   // legacy by-manifest-group buckets (still consumed by search results)
  recent: [],    // top 5 by mtime, descending
  index: null,   // search index from buildIndex(entries)

  load: async () => {
    if (get().status === 'ready' || get().status === 'loading') return
    set({ status: 'loading', error: null })
    try {
      const res = await fetch('/docs-manifest.json', { cache: 'no-cache' })
      if (!res.ok) throw new Error(`manifest fetch failed: ${res.status}`)
      const manifest: DocsManifest = await res.json()
      // Tolerate either { entries: [...] } (flat) or { groups: [{ items }] }
      // (grouped). We extract a flat entries[] for the legacy consumers
      // (search, recent, articles) and hand the raw manifest to the new
      // sidebar taxonomy code via the store.
      const flat = flattenManifest(manifest)
      const entries = flat.filter((e) => !isInternalPlanning(e))
      const bySlug = new Map(entries.map((e) => [e.slug, e]))
      const byGroup = groupEntries(entries)
      const recent = [...entries].sort((a, b) => (b.mtime ?? 0) - (a.mtime ?? 0)).slice(0, 5)
      const index = buildIndex(entries)
      set({ status: 'ready', manifest, entries, bySlug, byGroup, recent, index })
    } catch (e) {
      console.error('[docs] manifest load failed', e)
      set({ status: 'error', error: e instanceof Error ? e.message : String(e) })
    }
  },
}))

// The v2 manifest emits BOTH shapes: a grouped sidebar projection
// (`groups[].items`, intentionally WITHOUT `body` — and including Domains
// route-links that are not articles) and a flat list (`items`/`entries`, the
// COMPLETE records *with* `body`). Article rendering reads `entry.body`, so the
// flat list is the source of truth here; the sidebar consumes `manifest.groups`
// separately via groupTaxonomy. The previous implementation walked `groups`
// first and marked every slug seen, so the body-bearing flat entries were all
// skipped — every article rendered blank. Prefer the flat list; fall back to
// group items only for a true legacy grouped-only manifest (no flat list).
export function flattenManifest(manifest: DocsManifest | null | undefined): DocEntry[] {
  if (!manifest) return []
  const out: DocEntry[] = []
  const seen = new Set<string>()

  const flat = Array.isArray(manifest.items)
    ? manifest.items
    : Array.isArray(manifest.entries)
      ? manifest.entries
      : null
  if (flat) {
    for (const e of flat) {
      if (!e || !e.slug || seen.has(e.slug)) continue
      seen.add(e.slug)
      out.push(e)
    }
    return out
  }

  if (Array.isArray(manifest.groups)) {
    for (const g of manifest.groups) {
      for (const item of g.items || []) {
        if (!item || !item.slug || seen.has(item.slug)) continue
        seen.add(item.slug)
        out.push({ ...item, group: item.group || g.label })
      }
    }
  }
  return out
}

// Sidebar group order. Anything outside this list falls to the bottom.
const GROUP_ORDER = [
  'Getting Started',
  'Modeling',
  'Electronics',
  'Library & BOM',
  'Workspaces',
  'API & Reference',
  'Roadmap',
  'Legal',
]

function groupEntries(entries: DocEntry[]): DocGroupBucket[] {
  const map = new Map<string | undefined, DocEntry[]>()
  for (const e of entries) {
    let bucket = map.get(e.group)
    if (!bucket) { bucket = []; map.set(e.group, bucket) }
    bucket.push(e)
  }
  for (const items of map.values()) {
    items.sort((a, b) => (a.order ?? 99) - (b.order ?? 99))
  }
  return GROUP_ORDER
    .filter((g) => map.has(g))
    .map((group) => ({ group, items: map.get(group)! }))
    .concat(
      [...map.keys()]
        .filter((g) => !GROUP_ORDER.includes(g as string))
        .map((group) => ({ group, items: map.get(group)! })),
    )
}
