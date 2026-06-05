// Panel registry — the seam that lets feature panels wire into the Editor without
// every one of them editing the (huge) Editor.jsx dispatch switch.
//
// Each entry maps a file kind and/or filename extension(s) to a lazily-loaded
// React panel. Editor.jsx resolves the current file against this registry AFTER
// its dedicated dispatches and BEFORE the plain-text/code fallback, so a file
// whose `kind`/extension matches an entry opens its panel.
//
// To wire a new panel, append ONE entry to ENTRIES below:
//   { id: 'corridor', kinds: ['civil_corridor'], exts: ['.corridor'],
//     load: () => import('../components/civil/CorridorModelPanel.jsx'), label: 'Corridor' }
//
// The lazy component is rendered by Editor.jsx inside <Suspense>, and receives
// props: { file, content, projectId, fileId }.
import { lazy } from 'react'

/** @type {Array<{id:string,kinds?:string[],exts?:string[],load:()=>Promise<any>,label?:string}>} */
const ENTRIES = [
  // ── wired by the frontend-wiring fan-out; keep alphabetical by id ──────────
]

const _cache = new Map()

/**
 * Resolve the registry entry for a file, returning the entry plus a memoised
 * lazy `Panel` component, or null if nothing matches.
 */
export function resolvePanelEntry(file) {
  if (!file) return null
  const kind = String(file.kind || '').toLowerCase()
  const name = String(file.name || '').toLowerCase()
  for (const e of ENTRIES) {
    const kindHit = kind && (e.kinds || []).some((k) => k.toLowerCase() === kind)
    const extHit = (e.exts || []).some((x) => name.endsWith(x.toLowerCase()))
    if (kindHit || extHit) {
      if (!_cache.has(e.id)) _cache.set(e.id, lazy(e.load))
      return { ...e, Panel: _cache.get(e.id) }
    }
  }
  return null
}

/** All registered entries (for a launcher / "new file" menu and for tests). */
export const PANEL_ENTRIES = ENTRIES
