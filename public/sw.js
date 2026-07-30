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
//      already accepted, arriving within the device's §16 wake budget, or the
//      whole event is dropped before any work is done. Steps 1–3 run only for a
//      wake that clears the gate.
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
// ends. This worker is kerf's receiving end, and all three of §8.4's
// device-side gates are enforced here. The budgets are not invented: DMTAP core
// §16 (parameter table, "Push wake rate limit" / "Push wake replay cache")
// fixes them numerically, and marks the rate limit "emitter **and** receiver
// enforce (§4.9.4)".
//
// REPLAY-DEDUP — `ERR_WAKEPING_REPLAY`, 0x0316, DROP_SILENT.
//   "Each wake's sealed plaintext is a fresh ≥16-byte nonce; the device keeps a
//   bounded replay cache and drops a wake whose nonce it has already accepted —
//   closing the relay-replay battery-drain the emitter's limiter cannot see."
//   kerf_pub.wake.send_wake seals exactly `os.urandom(16)` per send, and the
//   user agent hands this worker that plaintext as `event.data`. So the nonce is
//   on the wire and this gate needs nothing the protocol has not already fixed.
//   The cache is bounded (WAKE_REPLAY_MAX, newest-first, 24 h TTL) and persisted
//   in Cache Storage, because a worker woken for a push starts with an empty
//   global scope — an in-memory set would forget every nonce between pushes and
//   dedup nothing, which is the failure mode that makes replay caches
//   decorative.
//
// CONTENT-FREE SHAPE CHECK — `ERR_WAKEPING_CONTENT_PRESENT`, 0x0313.
//   §8.4: "a WakePing bearing any field beyond the opaque token … is rejected".
//   kerf's emitter sends a 16-byte token and nothing else, so a push whose
//   decrypted plaintext is absent, shorter, or longer is not a conformant kerf
//   WakePing and is dropped unread. This also means a push carrying a payload at
//   all beyond the token never reaches the refresh path.
//
// INBOUND RATE-LIMIT BACKSTOP — `ERR_WAKEPING_RATE_LIMITED`, 0x0315.
//   §8.4: "the receiving device enforces the same budget on inbound wakes as a
//   fail-closed backstop, so a misbehaving relay that replays/floods cannot
//   exceed the budget." The budget it mirrors is §16's, not kerf's emitter's:
//   ≤ 1 wake / 60 s per device, ≈ 30 wakes / h. Both are enforced below as a
//   sliding window over the timestamps of ACCEPTED wakes.
//
//   Two things make this safe to enforce here rather than something needing a
//   protocol decision:
//     • The clock is the device's own (`Date.now()`). The adversary this gate
//       exists for is the push relay, which chooses only WHEN it delivers — it
//       cannot move the clock it is being measured against. Nothing here trusts
//       a timestamp that arrived over the network, because none does: the wake's
//       whole plaintext is a nonce.
//     • Dropping an over-budget wake cannot lose data. Kerf's wake is
//       content-free and this worker's reaction to ANY wake is the same
//       idempotent re-crawl of every followed pub, so a wake refused inside the
//       window would have triggered work a wake seconds earlier already did.
//       The cost is bounded latency (up to one window) on the next revision,
//       against which pull remains the source of truth.
//
//   Kerf's EMITTER still has no limiter of its own — kerf_pub.wake.
//   notify_subscribers fans out one unthrottled wake per subscriber per publish,
//   with no coalescing window — so §8.4's emitter half is genuinely missing and
//   is recorded as such in docs/node-architecture.md and kerf_pub/wake.py. This
//   backstop is what bounds the battery cost meanwhile, which is exactly the job
//   §8.4 gives the receiver.
//
// WHAT IS STILL NOT DEFENDED HERE, precisely. The OS/user-agent decides to run
// this worker before a line of it executes, so a flood still costs the wakeups
// the platform performs — a receiver can refuse the work (network, tab wake,
// notification), never the process start. Undecryptable pushes are dropped by
// the user agent before `push` fires (RFC 8291; §8.4's 0x0314), which is why
// there is no auth gate in this file. And a relay can only replay ciphertexts
// the emitter really produced, since it cannot mint new ones under the device's
// push key.
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
// §16, "Push wake replay cache": "≥ recent 512 nonces or 24 h, whichever
// larger". Both halves are honoured, and they do not fight each other: only
// ACCEPTED nonces are recorded (§4.9.4's wording — "a cache of recently-accepted
// nonces"), and acceptance is itself capped at WAKE_HOURLY_BUDGET, so 24 h of
// accepted wakes is at most 30×24 = 720 entries. WAKE_REPLAY_MAX = 1024 is a
// hard ceiling above that — an unbounded nonce cache would be its own
// denial-of-service — which the TTL therefore reaches first in any run where the
// limiter below is doing its job, while still leaving the ceiling comfortably
// over §16's 512 floor. Worst case on disk: 1024 entries × ~60 B of JSON
// (`{"n":"<32 hex>","t":<13 digits>}`) ≈ 60 KB of Cache Storage.
const WAKE_REPLAY_MAX = 1024
const WAKE_REPLAY_TTL_MS = 24 * 60 * 60 * 1000
// §16, "Push wake rate limit": "≤ 1 wake / 60 s per device (burst-coalesced),
// budget ≈ 30 wakes / h", "emitter **and** receiver enforce (§4.9.4)".
const WAKE_MIN_INTERVAL_MS = 60 * 1000
const WAKE_HOURLY_BUDGET = 30
const WAKE_BUDGET_WINDOW_MS = 60 * 60 * 1000
// Bump when the persisted record's shape changes. v1 was a bare array of hex
// nonces (no timestamps, no accept log).
const WAKE_RECORD_VERSION = 2

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

// ── §8.4 gates: shape, replay-dedup, inbound rate limit ──────────────────────

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

// The device's own clock. Deliberately a named seam: the value MUST come from
// the device (see the rate-limit note above), never from anything a push relay
// can influence.
function wakeNow() {
  return Date.now()
}

// A timestamp that is never in the future and never NaN. A clock that jumped
// backwards (or a corrupted record) must make the gate MORE conservative, not
// less: clamping a future stamp to `now` keeps an entry alive for its full TTL
// and keeps a stale accept blocking for its full window, rather than reading as
// "long ago" and opening the gate.
function wakeStamp(t, now) {
  return typeof t === 'number' && isFinite(t) && t <= now ? t : now
}

const emptyWakeRecord = () => ({ v: WAKE_RECORD_VERSION, seen: [], accepts: [] })

// Normalize whatever is on disk into { seen: [{n, t}], accepts: [t] }, both
// newest-first, pruned to their §16 windows and hard caps. v1 records (a bare
// array of hex strings, no timestamps) are migrated by stamping them `now` —
// keeping them, because forgetting an accepted nonce is what lets a replay
// through, and the cost of over-keeping is one TTL.
//
// `skewed` reports that at least one stamp had to be clamped out of the future.
// The caller persists the clamped record so a clock that moved backwards costs
// one window of refusals rather than wedging the limiter until real time catches
// up. A push relay cannot provoke this — nothing here comes off the wire.
function normalizeWakeRecord(parsed, now) {
  const rec = emptyWakeRecord()
  let skewed = false
  const clamp = (t) => {
    const stamped = wakeStamp(t, now)
    if (stamped !== t) skewed = true
    return stamped
  }

  const rawSeen = Array.isArray(parsed) ? parsed : parsed && Array.isArray(parsed.seen) ? parsed.seen : []
  for (const entry of rawSeen) {
    const n = typeof entry === 'string' ? entry : entry && typeof entry.n === 'string' ? entry.n : null
    if (!n) continue
    const t = typeof entry === 'string' ? ((skewed = true), now) : clamp(entry.t)
    if (now - t >= WAKE_REPLAY_TTL_MS) continue
    rec.seen.push({ n, t })
  }
  rec.seen.sort((a, b) => b.t - a.t)
  if (rec.seen.length > WAKE_REPLAY_MAX) {
    rec.seen = rec.seen.slice(0, WAKE_REPLAY_MAX)
    skewed = true // an oversized record on disk is also worth rewriting once
  }

  const rawAccepts = parsed && Array.isArray(parsed.accepts) ? parsed.accepts : []
  for (const t of rawAccepts) {
    const stamped = clamp(t)
    if (now - stamped >= WAKE_BUDGET_WINDOW_MS) continue
    rec.accepts.push(stamped)
  }
  rec.accepts.sort((a, b) => b - a)
  rec.accepts = rec.accepts.slice(0, WAKE_HOURLY_BUDGET)
  rec.skewed = skewed
  return rec
}

async function readWakeRecord(now) {
  const cache = await caches.open(WAKE_REPLAY_CACHE_NAME)
  const res = await cache.match(WAKE_REPLAY_URL)
  if (!res) return emptyWakeRecord()
  return normalizeWakeRecord(await res.json(), now)
}

async function writeWakeRecord(rec) {
  const cache = await caches.open(WAKE_REPLAY_CACHE_NAME)
  // Written field-by-field so nothing internal (e.g. `skewed`) leaks into the
  // persisted shape.
  const body = JSON.stringify({ v: WAKE_RECORD_VERSION, seen: rec.seen, accepts: rec.accepts })
  await cache.put(WAKE_REPLAY_URL, new Response(body, { headers: { 'content-type': 'application/json' } }))
}

// Serialize claims. Service workers are single-threaded, but two `push` events
// can interleave across `await` points — and a read-modify-write that
// interleaves is a replay cache that lets the replay through (and a rate limiter
// that lets a burst through). Chaining every claim onto one promise makes
// check-and-record atomic with respect to other claims in this worker instance;
// across worker restarts the persisted record is the record.
let wakeClaimChain = Promise.resolve()

// claimWake — 'accept' only if `hex` is a nonce this device has not already
// accepted AND the §16 budget has room, in which case it has been durably
// recorded. Everything else is a drop:
//   'replay'       ERR_WAKEPING_REPLAY        0x0316  DROP_SILENT
//   'rate-limited' ERR_WAKEPING_RATE_LIMITED  0x0315  drop beyond cap
//   'unavailable'  gate could not be evaluated — fail closed, drop anyway
// A replay costs one read and no write: a relay re-sending one captured
// ciphertext ten thousand times must not turn into ten thousand cache writes,
// and a nonce that was never accepted is not on the budget's tab either.
function claimWake(hex) {
  const run = wakeClaimChain.then(async () => {
    if (!hex) return 'unavailable'
    if (typeof caches === 'undefined') return 'unavailable'
    const now = wakeNow()
    let rec
    try {
      rec = await readWakeRecord(now)
    } catch {
      // Unreadable/corrupt record: drop THIS wake (fail closed), but leave a
      // valid empty record behind so the gate recovers on the next push instead
      // of refusing every wake forever — a permanently wedged gate is a
      // self-inflicted outage, not a defence.
      try {
        await writeWakeRecord(emptyWakeRecord())
      } catch {
        /* nothing more to do; the wake is dropped either way */
      }
      return 'unavailable'
    }
    if (rec.skewed) {
      // Migration (v1 record), a clamped clock, or an oversized record on disk:
      // persist the normalized form once so the correction is durable. Never
      // reachable from the wire, so this cannot be used to amplify writes; and a
      // failure here is not fatal — normalization already applied in memory.
      try {
        await writeWakeRecord(rec)
      } catch {
        /* keep going: the in-memory normalization still governs this decision */
      }
    }
    try {
      if (rec.seen.some((e) => e.n === hex)) return 'replay'
      // §16: ≤ 1 wake / 60 s, and ≈ 30 wakes / h. `accepts` is newest-first and
      // already pruned to the hour, so both tests are local.
      if (rec.accepts.length > 0 && now - rec.accepts[0] < WAKE_MIN_INTERVAL_MS) return 'rate-limited'
      if (rec.accepts.length >= WAKE_HOURLY_BUDGET) return 'rate-limited'
      // Newest first, oldest evicted: a bounded cache that keeps the most
      // recent nonces is the one that catches the replays worth catching.
      await writeWakeRecord({
        v: WAKE_RECORD_VERSION,
        seen: [{ n: hex, t: now }, ...rec.seen].slice(0, WAKE_REPLAY_MAX),
        accepts: [now, ...rec.accepts].slice(0, WAKE_HOURLY_BUDGET),
      })
      return 'accept'
    } catch {
      // The nonce could not be durably recorded, so accepting it would mean a
      // wake this device cannot dedup next time. Drop.
      return 'unavailable'
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
      // a replayed or over-budget wake would hand the offending relay the
      // user-visible half of the nuisance it was after.
      const nonce = await wakeNonceHex(event)
      if (!nonce) return // 0x0313 ERR_WAKEPING_CONTENT_PRESENT (or an unreadable payload)
      if ((await claimWake(nonce)) !== 'accept') return // 0x0316 / 0x0315 / unevaluable

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
