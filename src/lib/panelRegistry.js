// Panel registry — the seam that lets feature panels wire into the Editor without
// every one of them editing the (huge) Editor.jsx dispatch switch.
//
// Registration is split into per-domain FRAGMENT files under ./panels/*.js so that
// many contributors (or agents) can wire panels in parallel with ZERO shared-file
// conflicts — each drops its own fragment; this file auto-collects them via Vite's
// import.meta.glob.
//
// A fragment default-exports an array of entries:
//   // src/lib/panels/aero.js
//   export default [
//     { id: 'flutter', kinds: ['aero_flutter'], exts: ['.flutter'],
//       load: () => import('../../components/FlutterPanel.jsx'), label: 'Flutter' },
//   ]
//
// Each entry maps a file `kind` and/or filename extension(s) to a lazily-loaded
// React panel. Editor.jsx resolves the current file against the registry AFTER its
// dedicated dispatches and BEFORE the plain-text/code fallback. The lazy component
// renders inside <Suspense> with props: { file, content, projectId, fileId }.
import { lazy } from 'react'

// Eagerly import the (tiny) fragment modules; the panels they reference stay lazy.
const _fragments = import.meta.glob('./panels/*.js', { eager: true })

/** @type {Array<{id:string,kinds?:string[],exts?:string[],load:()=>Promise<any>,label?:string}>} */
const ENTRIES = []
for (const mod of Object.values(_fragments)) {
  const arr = mod?.default
  if (Array.isArray(arr)) ENTRIES.push(...arr)
}

const _cache = new Map()

/**
 * Resolve the registry entry for a file, returning the entry plus a memoised lazy
 * `Panel` component, or null if nothing matches.
 */
export function resolvePanelEntry(file) {
  if (!file) return null
  const kind = String(file.kind || '').toLowerCase()
  const name = String(file.name || '').toLowerCase()
  for (const e of ENTRIES) {
    const kindHit = kind && (e.kinds || []).some((k) => String(k).toLowerCase() === kind)
    const extHit = (e.exts || []).some((x) => name.endsWith(String(x).toLowerCase()))
    if (kindHit || extHit) {
      if (!_cache.has(e.id)) _cache.set(e.id, lazy(e.load))
      return { ...e, Panel: _cache.get(e.id) }
    }
  }
  return null
}

/** All registered entries (for a launcher / "new file" menu and for tests). */
export const PANEL_ENTRIES = ENTRIES
