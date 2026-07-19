// Kerf service worker — Wake push receive-side only (RFC 8291/8292,
// kerf_pub.wake, substrate capability ⑤). See docs/distributed-workshop.md's
// "Wake" section for the full picture; this file is deliberately the ONLY
// thing it does — Kerf has no offline cache / asset precache strategy here.
//
// A wake push payload is content-free by design (kerf_pub.wake's docstring:
// "no announce id, no artifact name, no author identity, nothing beyond a
// fresh random nonce") — this worker never learns WHICH followed feed
// changed. What it does on a `push` event:
//
//   1. Best-effort: POST a targeted re-crawl (`/api/pub/follows/:pub/refresh`)
//      for every followed pub the user has Wake enabled for, using the
//      access token the page last handed off via Cache Storage
//      (src/lib/wake.js's writeWakeState — see readWakeState() below). This
//      is opportunistic, NOT load-bearing: an expired/missing token just
//      means the request 401s and is ignored — pull is always the source of
//      truth (DMTAP: "push is a latency optimization, not delivery"), and
//      the Workshop re-crawls on its own the next time it's opened anyway.
//   2. postMessage any open Workshop tabs so a foreground tab can refresh
//      immediately instead of waiting for the user to click the notification.
//   3. Show one quiet notification (no sound, coalesced via `tag` so a burst
//      of wakes doesn't stack up a pile of banners) — but only if the page
//      previously confirmed Notification permission was granted (the browser
//      would silently no-op showNotification() otherwise, so this is just an
//      early-out, not a security check).
//
// Clicking the notification focuses (or opens) a /workshop tab.

const WAKE_CACHE_NAME = 'kerf-wake-state-v1'
const WAKE_STATE_URL = '/__kerf-wake-state'

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

async function readWakeState() {
  try {
    const cache = await caches.open(WAKE_CACHE_NAME)
    const res = await cache.match(WAKE_STATE_URL)
    if (!res) return null
    return await res.json()
  } catch {
    return null
  }
}

async function refreshFollowedPubs(state) {
  if (!state || !state.accessToken || !Array.isArray(state.pubs) || state.pubs.length === 0) {
    return
  }
  const apiUrl = state.apiUrl || ''
  await Promise.allSettled(
    state.pubs.map((pubKey) =>
      fetch(`${apiUrl}/api/pub/follows/${encodeURIComponent(pubKey)}/refresh`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          authorization: `Bearer ${state.accessToken}`,
        },
      }),
    ),
  )
}

async function notifyOpenClients() {
  const clientsList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
  for (const client of clientsList) {
    client.postMessage({ type: 'kerf-wake' })
  }
}

self.addEventListener('push', (event) => {
  event.waitUntil(
    (async () => {
      const state = await readWakeState()
      await Promise.allSettled([refreshFollowedPubs(state), notifyOpenClients()])

      if (self.Notification && self.Notification.permission === 'granted') {
        await self.registration.showNotification('Kerf Workshop', {
          body: 'New revisions in a followed feed.',
          tag: 'kerf-wake',
          renotify: false,
          silent: true,
          icon: '/icon-192.png',
          badge: '/icon-192.png',
        })
      }
    })(),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(
    (async () => {
      const clientsList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of clientsList) {
        if (client.url.includes('/workshop')) {
          client.postMessage({ type: 'kerf-wake' })
          if ('focus' in client) return client.focus()
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow('/workshop')
      return undefined
    })(),
  )
})
