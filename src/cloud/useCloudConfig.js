// Lightweight bootstrap config hook. Hits /api/config exactly once per page
// load and caches the result in a tiny zustand store. Safe to call from
// either the OSS frontend (will just see cloudEnabled=false defaults) or
// the cloud bundle.
//
// Shape returned by /api/config (per docs/architecture.md):
//   {
//     cloud_enabled: bool,
//     cloud_beta?: bool,        // billing disabled during beta (everyone Free)
//     google_client_id?: string,
//     paystack_public_key?: string,
//   }
//
// cloudBeta is true when VITE_CLOUD_BETA is set at build time OR when the
// backend reports cloud_beta: true. Either signal is sufficient. When
// cloudBeta is true and cloudEnabled is true, billing/tier-change controls
// are visibly disabled — all product features remain accessible.

import { useEffect } from 'react'
import { create } from 'zustand'

const API_URL = import.meta.env.VITE_API_URL || ''

// Read the build-time env flag once. Truthy string values ("1", "true",
// "yes") activate beta mode even before /api/config responds.
const VITE_CLOUD_BETA = (() => {
  const v = import.meta.env.VITE_CLOUD_BETA
  if (!v) return false
  return ['1', 'true', 'yes'].includes(String(v).toLowerCase())
})()

const DEFAULTS = {
  ready: false,
  cloudEnabled: false,
  // localMode default is true so an OSS build that fails to fetch
  // /api/config (e.g. CORS misconfigured) still skips /login, matching
  // server-side defaults. The cloud build always overrides via the
  // /api/config response.
  localMode: true,
  // cloudBeta: billing-disabled mode. Defaults to the build-time flag so
  // the UI reflects it immediately (before the first /api/config response).
  cloudBeta: VITE_CLOUD_BETA,
  googleClientId: '',
  paystackPublicKey: '',
}

const useStore = create((set, get) => ({
  ...DEFAULTS,
  _inflight: null,

  fetch: () => {
    const s = get()
    if (s.ready || s._inflight) return s._inflight
    const p = fetch(`${API_URL}/api/config`, { credentials: 'omit' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`config ${r.status}`)
        return r.json()
      })
      .then((data) => {
        set({
          ready: true,
          cloudEnabled: !!data.cloud_enabled,
          // local_mode is the single source of truth for "skip the
          // login screen". Fall back to !cloud_enabled when the
          // backend hasn't surfaced the flag yet (older binary).
          localMode: data.local_mode != null ? !!data.local_mode : !data.cloud_enabled,
          // cloudBeta: either the build-time env flag OR the backend flag
          // (whichever is truthy wins — beta can't be disabled by the backend
          // once the build-time flag is set).
          cloudBeta: VITE_CLOUD_BETA || !!data.cloud_beta,
          googleClientId: data.google_client_id || '',
          paystackPublicKey: data.paystack_public_key || '',
          _inflight: null,
        })
      })
      .catch((err) => {
        // Treat network/unreachable as "OSS defaults". Surface in console
        // so devs notice misconfigured proxies.
        console.warn('[useCloudConfig] /api/config failed:', err)
        set({ ...DEFAULTS, ready: true, _inflight: null })
      })
    set({ _inflight: p })
    return p
  },
}))

export function useCloudConfig() {
  const state = useStore()
  useEffect(() => {
    if (!state.ready && !state._inflight) state.fetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return {
    ready: state.ready,
    cloudEnabled: state.cloudEnabled,
    localMode: state.localMode,
    cloudBeta: state.cloudBeta,
    googleClientId: state.googleClientId,
    paystackPublicKey: state.paystackPublicKey,
  }
}

// Imperative accessor for code that can't use hooks (e.g. router loaders).
export function getCloudConfig() {
  return useStore.getState()
}
