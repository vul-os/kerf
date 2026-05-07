import { create } from 'zustand'
import { buildIndex } from './searchIndex.js'

// Single in-memory store for the docs corpus. The manifest is a static asset
// emitted by `scripts/build-docs-manifest.mjs` at build time, so we just fetch
// it once on mount, build the search index, and hold both for the rest of the
// session. The store is also the cache layer when the user navigates between
// articles — we don't refetch the manifest on /docs/:slug pages.

export const useDocs = create((set, get) => ({
  status: 'idle', // idle | loading | ready | error
  error: null,
  entries: [],
  bySlug: new Map(),
  byGroup: [],   // [{ group, items: [entry, ...] }] in declared order
  recent: [],    // top 5 by mtime, descending
  index: null,   // search index from buildIndex(entries)

  load: async () => {
    if (get().status === 'ready' || get().status === 'loading') return
    set({ status: 'loading', error: null })
    try {
      const res = await fetch('/docs-manifest.json', { cache: 'no-cache' })
      if (!res.ok) throw new Error(`manifest fetch failed: ${res.status}`)
      const manifest = await res.json()
      const entries = manifest.entries || []
      const bySlug = new Map(entries.map((e) => [e.slug, e]))
      const byGroup = groupEntries(entries)
      const recent = [...entries].sort((a, b) => b.mtime - a.mtime).slice(0, 5)
      const index = buildIndex(entries)
      set({ status: 'ready', entries, bySlug, byGroup, recent, index })
    } catch (e) {
      console.error('[docs] manifest load failed', e)
      set({ status: 'error', error: e.message })
    }
  },
}))

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

function groupEntries(entries) {
  const map = new Map()
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
    .map((group) => ({ group, items: map.get(group) }))
    .concat(
      [...map.keys()]
        .filter((g) => !GROUP_ORDER.includes(g))
        .map((group) => ({ group, items: map.get(group) })),
    )
}
