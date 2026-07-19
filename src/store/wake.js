// Which followed pubs the user has toggled "Notify me" (Wake push) on for —
// see docs/distributed-workshop.md's "Wake" section and src/lib/wake.js for
// the actual PushManager.subscribe()/subscribe-endpoint orchestration.
//
// Purely local UI state: the real subscription registration lives
// server-side (kerf_pub.wake's pub_wake_subscriptions table, one row per
// {pub, endpoint}). This store just remembers which toggles should render
// as "on" across reloads, and feeds the service worker's Cache Storage
// handoff (src/lib/wakeState.js) so a push event knows which follows to
// targeted-refresh.

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const useWake = create(
  persist(
    (set, get) => ({
      enabledPubs: [],

      isEnabled: (pubKey) => get().enabledPubs.includes(pubKey),

      setEnabled: (pubKey, on) =>
        set((s) => ({
          enabledPubs: on
            ? (s.enabledPubs.includes(pubKey) ? s.enabledPubs : [...s.enabledPubs, pubKey])
            : s.enabledPubs.filter((p) => p !== pubKey),
        })),
    }),
    { name: 'kerf.wake' },
  ),
)
