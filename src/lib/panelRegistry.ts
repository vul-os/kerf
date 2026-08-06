// Panel registry — the seam that lets feature panels wire into the Editor without
// every one of them editing the (huge) Editor.jsx dispatch switch.
//
// Registration is split into per-domain FRAGMENT files under ./panels/*.js so that
// many contributors (or agents) can wire panels in parallel with ZERO shared-file
// conflicts — each drops its own fragment; this file auto-collects them via Vite's
// import.meta.glob.
//
// A fragment default-exports an array of entries:
//   // src/lib/panels/aero.ts
//   export default [
//     { id: 'flutter', kinds: ['aero_flutter'], exts: ['.flutter'],
//       load: () => import('../../components/FlutterPanel.jsx'), label: 'Flutter' },
//   ]
//
// Each entry maps a file `kind` and/or filename extension(s) to a lazily-loaded
// React panel. Editor.jsx resolves the current file against the registry AFTER its
// dedicated dispatches and BEFORE the plain-text/code fallback. The lazy component
// renders inside <Suspense> with props: { file, content, projectId, fileId }.
import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

/**
 * A panel-registry fragment entry. `load` returns an arbitrary lazily-loaded
 * React component module — the component's own prop shape is intentionally
 * `any` here: this registry is a generic dispatch seam over ~100 unrelated
 * panels (each typed at its own definition), not a place to model every prop
 * union.
 */
export interface PanelEntry {
  id: string
  kinds?: string[]
  exts?: string[]
  load: () => Promise<{ default: ComponentType<any> }>
  label?: string
}

export interface ResolvedPanelEntry extends PanelEntry {
  Panel: LazyExoticComponent<ComponentType<any>>
}

export interface RegistryFile {
  kind?: string | null
  name?: string | null
}

// Eagerly import the (tiny) fragment modules; the panels they reference stay lazy.
const _fragments = import.meta.glob('./panels/*.ts', { eager: true }) as Record<
  string,
  { default?: PanelEntry[] }
>

const ENTRIES: PanelEntry[] = []
for (const mod of Object.values(_fragments)) {
  const arr = mod?.default
  if (Array.isArray(arr)) ENTRIES.push(...arr)
}

const _cache = new Map<string, LazyExoticComponent<ComponentType<any>>>()

/**
 * Resolve the registry entry for a file, returning the entry plus a memoised lazy
 * `Panel` component, or null if nothing matches.
 */
export function resolvePanelEntry(file: RegistryFile | null | undefined): ResolvedPanelEntry | null {
  if (!file) return null
  const kind = String(file.kind || '').toLowerCase()
  const name = String(file.name || '').toLowerCase()
  for (const e of ENTRIES) {
    const kindHit = Boolean(kind) && (e.kinds || []).some((k) => String(k).toLowerCase() === kind)
    const extHit = (e.exts || []).some((x) => name.endsWith(String(x).toLowerCase()))
    if (kindHit || extHit) {
      if (!_cache.has(e.id)) _cache.set(e.id, lazy(e.load))
      return { ...e, Panel: _cache.get(e.id)! }
    }
  }
  return null
}

/** All registered entries (for a launcher / "new file" menu and for tests). */
export const PANEL_ENTRIES = ENTRIES
