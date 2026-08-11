// Lightweight bootstrap config hook. Hits /api/config exactly once per page
// load and caches the result in a tiny zustand store. Every kerf node runs the
// same software (there is no "cloud edition" to detect) — this hook surfaces
// the one thing that legitimately varies per node: whether it is running in
// local_mode (one node, one password) or server mode.
//
// It used to also carry OAuth availability, so the login screen could decide
// whether to draw Google and GitHub buttons. There is no federated sign-in any
// more: a node has a single password set on first load, and an account exists
// only to publish parts. See docs/auth.md.
//
// Shape returned by /api/config:
//   { local_mode: bool }

import { useEffect } from 'react'
import { create } from 'zustand'

const API_URL = import.meta.env.VITE_API_URL || ''

interface NodeConfigResponse {
  local_mode?: boolean
}

interface NodeConfigValues {
  ready: boolean
  localMode: boolean
}

const DEFAULTS: NodeConfigValues = {
  ready: false,
  // localMode default is true so a build that fails to fetch /api/config
  // (e.g. CORS misconfigured) still behaves like a self-hosted node, matching
  // the server-side default.
  localMode: true,
}

interface NodeConfigStore extends NodeConfigValues {
  _inflight: Promise<void> | null
  fetch: () => Promise<void> | null
}

const useStore = create<NodeConfigStore>((set, get) => ({
  ...DEFAULTS,
  _inflight: null,

  fetch: () => {
    const s = get()
    if (s.ready || s._inflight) return s._inflight
    const p = fetch(`${API_URL}/api/config`, { credentials: 'omit' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`config ${r.status}`)
        return r.json() as Promise<NodeConfigResponse>
      })
      .then((data) => {
        set({
          ready: true,
          // Fall back to the self-hosted default when an older binary has not
          // surfaced the field yet.
          localMode: data.local_mode != null ? !!data.local_mode : true,
          _inflight: null,
        })
      })
      .catch((err: unknown) => {
        // Treat network/unreachable as defaults. Surface in console so devs
        // notice misconfigured proxies.
        console.warn('[useNodeConfig] /api/config failed:', err)
        set({ ...DEFAULTS, ready: true, _inflight: null })
      })
    set({ _inflight: p })
    return p
  },
}))

export function useNodeConfig(): NodeConfigValues {
  const state = useStore()
  useEffect(() => {
    if (!state.ready && !state._inflight) state.fetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return { ready: state.ready, localMode: state.localMode }
}

// Imperative accessor for code that can't use hooks (e.g. router loaders).
export function getCloudConfig(): NodeConfigStore {
  return useStore.getState()
}
