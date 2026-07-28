// Kerf service worker — Wake push receive-side only (RFC 8291/8292,
// kerf_pub.wake; kerf-local, adapted from substrate capability ⑥'s Wake).
// See docs/distributed-workshop.md's "Wake" section for the full picture;
// this file is deliberately the ONLY thing it does — Kerf has no offline
// cache / asset precache strategy here.
//
// A wake push payload is content-free by design (kerf_pub.wake's docstring:
// "no announce id, no artifact name, no author identity, nothing beyond a
// fresh random nonce") — this worker never learns WHICH followed feed
// changed. What it does on a `push` event:
//
//   0. GATE (ROLES.md §8.4, see "Device-side wake gates" below): the wake's
//      plaintext must be a well-formed 16-byte token this device has not
//      already accepted, or the whole event is dropped before any work is
//      done. Steps 1–3 run only for a wake that clears the gate.
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
//
// ── Device-side wake gates (ROLES.md §8.4) ───────────────────────────────────
//
// A wake spends the target's battery, so §8.4 gates wakes fail-closed at BOTH
// ends. This worker is kerf's receiving end. Two of §8.4's device-side gates
// are implemented here; one is not, and the reason is recorded rather than
// papered over.
//
// IMPLEMENTED — replay-dedup (`ERR_WAKEPING_REPLAY`, 0x0316, DROP_SILENT).
//   "Each wake's sealed plaintext is a fresh ≥16-byte nonce; the device keeps a
//   bounded replay cache and drops a wake whose nonce it has already accepted —
//   closing the relay-replay battery-drain the emitter's limiter cannot see."
//   kerf_pub.wake.send_wake seals exactly `os.urandom(16)` per send, and the
//   user agent hands this worker that plaintext as `event.data`. So the nonce is
//   on the wire and this gate needs nothing the protocol has not already fixed.
//   The cache is bounded (WAKE_REPLAY_MAX, newest-first) and persisted in Cache
//   Storage, because a worker woken for a push starts with an empty global scope
//   — an in-memory set would forget every nonce between pushes and dedup
//   nothing, which is the failure mode that makes replay caches decorative.
//
// IMPLEMENTED — content-free shape check (`ERR_WAKEPING_CONTENT_PRESENT`,
//   0x0313). §8.4: "a WakePing bearing any field beyond the opaque token … is
//   rejected". kerf's emitter sends a 16-byte token and nothing else, so a push
//   whose decrypted plaintext is absent, shorter, or longer is not a conformant
//   kerf WakePing and is dropped unread. This also means a push carrying a
//   payload at all beyond the token never reaches the refresh path.
//
// NOT IMPLEMENTED — inbound rate-limit backstop (`ERR_WAKEPING_RATE_LIMITED`,
//   0x0315). This one cannot be built here without a protocol decision, and a
//   limiter with an invented budget would be worse than none: §8.4 defines the
//   device-side limiter as enforcing "the SAME budget" as the emitting node
//   ("the emitting node rate-limits per device (coalescing bursts); the
//   receiving device enforces the same budget on inbound wakes as a fail-closed
//   backstop"). kerf's emitter has no such budget — kerf_pub.wake.notify_
//   subscribers fans out one unthrottled wake per subscriber per publish, with
//   no per-device limiter and no coalescing window — so "the same budget" has no
//   referent to mirror. Picking a number at the receiver alone would silently
//   drop legitimate wakes from a prolific publisher (a correctness regression
//   wearing a security control's clothes) while still not being the §8.4 gate,
//   which is a two-ended agreement. What has to be decided first is written up
//   in docs/node-architecture.md ("Wake" → the §8.4 row).
//
//   What this costs, precisely: the replay cache is bounded, so an adversary
//   holding more than WAKE_REPLAY_MAX distinct captured ciphertexts can cycle
//   them to evict entries and re-land old wakes. The rate limiter is §8.4's
//   backstop for exactly that residue. Everything else a relay can do — replay
//   one wake, replay a handful, inject undecryptable or wrong-shaped payloads —
//   is stopped above.
//
// Fail-closed, and cheap to be: every gate below drops the wake when it cannot
// be evaluated (no Cache Storage, unreadable payload, storage error). Dropping
// a wake costs only latency and never correctness — pull is the source of truth
// and the Workshop re-crawls when opened — so there is no reason to fail open.

const WAKE_CACHE_NAME = 'kerf-wake-state-v1'
const WAKE_STATE_URL = '/__kerf-wake-state'

// Replay cache lives in its OWN Cache Storage bucket, not alongside the
// page-written wake state: src/lib/wakeState.js's writeWakeState owns
// WAKE_CACHE_NAME and rewrites it on every token refresh, and a security gate
// must not share a bucket with something that overwrites it.
const WAKE_REPLAY_CACHE_NAME = 'kerf-wake-replay-v1'
const WAKE_REPLAY_URL = '/__kerf-wake-seen-nonces'
// kerf_pub.wake.send_wake: `token = os.urandom(16)`. Exactly, not at least —
// this worker only ever talks to kerf emitters, so an off-size plaintext is a
// malformed WakePing, not a future one.
const WAKE_NONCE_BYTES = 16
// Bounded (§8.4: "a bounded replay cache"). 256 nonces is ~8 KB of hex and
// covers far more wakes than a device can legitimately receive between the
// foreground re-crawls that make wake redundant anyway.
const WAKE_REPLAY_MAX = 256

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

// ── §8.4 replay gate ─────────────────────────────────────────────────────────

// wakeNonceHex — the wake's plaintext token as lowercase hex, or null if this
// push is not a well-formed kerf WakePing (no payload, or a payload that is not
// exactly WAKE_NONCE_BYTES). Never throws: an unreadable body is `null`, which
// the caller treats as "drop".
async function wakeNonceHex(event) {
  try {
    if (!event || !event.data) return null
    const buf = await event.data.arrayBuffer()
    const bytes = new Uint8Array(buf)
    // ERR_WAKEPING_CONTENT_PRESENT (0x0313): anything beyond the opaque token
    // — or a truncated one — is not a conformant content-free wake.
    if (bytes.length !== WAKE_NONCE_BYTES) return null
    let hex = ''
    for (let i = 0; i < bytes.length; i++) hex += bytes[i].toString(16).padStart(2, '0')
    return hex
  } catch {
    return null
  }
}

async function readSeenNonces() {
  const cache = await caches.open(WAKE_REPLAY_CACHE_NAME)
  const res = await cache.match(WAKE_REPLAY_URL)
  if (!res) return []
  const parsed = await res.json()
  return Array.isArray(parsed) ? parsed.filter((n) => typeof n === 'string') : []
}

async function writeSeenNonces(nonces) {
  const cache = await caches.open(WAKE_REPLAY_CACHE_NAME)
  await cache.put(
    WAKE_REPLAY_URL,
    new Response(JSON.stringify(nonces), { headers: { 'content-type': 'application/json' } }),
  )
}

// Serialize claims. Service workers are single-threaded, but two `push` events
// can interleave across `await` points — and a read-modify-write that
// interleaves is a replay cache that lets the replay through. Chaining every
// claim onto one promise makes the check-and-record atomic with respect to
// other claims in this worker instance; across worker restarts the persisted
// list is the record.
let wakeClaimChain = Promise.resolve()

// claimWakeNonce — true if `hex` is fresh AND was durably recorded; false for a
// replay, and false whenever the cache cannot be read or written. Fail-closed:
// an unverifiable wake is dropped (ERR_WAKEPING_REPLAY, 0x0316, DROP_SILENT).
function claimWakeNonce(hex) {
  const run = wakeClaimChain.then(async () => {
    if (!hex) return false
    if (typeof caches === 'undefined') return false
    try {
      const seen = await readSeenNonces()
      if (seen.includes(hex)) return false // replay — drop, do no work
      // Newest first, oldest evicted: a bounded cache that keeps the most
      // recent nonces is the one that catches the replays worth catching.
      await writeSeenNonces([hex, ...seen].slice(0, WAKE_REPLAY_MAX))
      return true
    } catch {
      return false
    }
  })
  // Keep the chain alive (and un-rejected) regardless of this claim's outcome.
  wakeClaimChain = run.then(
    () => undefined,
    () => undefined,
  )
  return run
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
      // §8.4 gate first, before any network, any tab wake, any notification.
      // A dropped wake is silent by design (DROP_SILENT): showing a banner for
      // a replayed wake would hand the replaying relay the user-visible half of
      // the nuisance it was after.
      const nonce = await wakeNonceHex(event)
      const fresh = await claimWakeNonce(nonce)
      if (!fresh) return

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
