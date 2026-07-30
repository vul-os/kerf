// serviceWorkerWakeGate.test.js — ROLES.md §8.4's device-side wake gates, as
// implemented by public/sw.js's `push` handler.
//
// public/sw.js is a classic (non-module) service worker: it is never imported
// by the app bundle, has no exports, and registers its behaviour by calling
// self.addEventListener at top level. So this file does what a browser does —
// evaluates the real file's source in a scope carrying a fake `self`, `caches`,
// `fetch` and `Date`, captures the listeners it registers, and drives them. The
// gate under test is therefore the shipped bytes of public/sw.js, not a
// reimplementation of them: if someone deletes the replay cache or the rate
// limiter from sw.js, these tests fail.
//
// What is asserted, per §8.4 (budgets from DMTAP core §16):
//   - a fresh 16-byte nonce is accepted exactly once (the wake does its work);
//   - the SAME nonce replayed does no work at all — no re-crawl POST, no tab
//     postMessage, no notification (0x0316 ERR_WAKEPING_REPLAY, DROP_SILENT);
//   - a replay flood does not even write to Cache Storage;
//   - the replay cache survives a worker restart, which is the whole point of
//     persisting it (a push-woken worker starts with an empty global scope);
//   - a v1 record (bare hex array, no timestamps) still dedups after upgrade;
//   - entries older than the 24 h TTL are evicted, and the cache is bounded
//     newest-first at WAKE_REPLAY_MAX;
//   - a payload that is not exactly the 16-byte token — absent, short, long —
//     is dropped unread (0x0313 ERR_WAKEPING_CONTENT_PRESENT);
//   - a FLOOD of distinct fresh nonces is refused past §16's budget
//     (≤ 1 wake / 60 s, ≈ 30 wakes / h) and resumes when the window frees up
//     (0x0315 ERR_WAKEPING_RATE_LIMITED), across worker restarts too;
//   - concurrent delivery of one nonce is claimed once, not twice;
//   - a broken Cache Storage fails CLOSED (drop), never open.
//
// The clock is injected because the gate measures against the DEVICE's clock:
// these tests drive it directly rather than sleeping, and the fact that a fake
// `Date.now` is enough to steer the limiter is the same reason a push relay
// cannot — it never gets to supply one.
//
// COVERAGE ASSERTION: this suite is worthless if it silently stops exercising
// the real file, so it first asserts that public/sw.js is readable, registers a
// `push` listener, and contains the gate constants it is written against. A stub
// that no-opped would fail those before any behaviour is checked.

import { describe, it, expect, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const HERE = dirname(fileURLToPath(import.meta.url))
const SW_PATH = resolve(HERE, '../../../public/sw.js')
const SW_SOURCE = readFileSync(SW_PATH, 'utf8')

const REPLAY_BUCKET = 'kerf-wake-replay-v1'
const REPLAY_URL = '/__kerf-wake-seen-nonces'
const MINUTE = 60 * 1000
const HOUR = 60 * MINUTE

// ---- a device clock the test drives (sw.js reads Date.now()) ----------------

function makeClock(start = 1_770_000_000_000) {
  return {
    now: start,
    advance(ms) {
      this.now += ms
    },
  }
}

// ---- a minimal Cache Storage that persists across "worker restarts" --------

function makeCacheStorage(store, { failing = false, counters } = {}) {
  return {
    open: async (name) => {
      if (failing) throw new Error('Cache Storage unavailable (private browsing)')
      if (!store.has(name)) store.set(name, new Map())
      const bucket = store.get(name)
      return {
        match: async (url) => {
          const body = bucket.get(url)
          return body === undefined ? undefined : { json: async () => JSON.parse(body) }
        },
        put: async (url, res) => {
          if (counters) counters.puts++
          bucket.set(url, await res.text())
        },
      }
    },
  }
}

// ---- boot a fresh "service worker instance" over the real sw.js source -----

function bootWorker({
  cacheStore,
  failingCaches = false,
  wakeState = null,
  notificationPermission = 'granted',
  clock = makeClock(),
} = {}) {
  const listeners = {}
  const calls = { fetch: [], postMessage: [], notifications: [], puts: 0 }

  const clientsList = [{ url: 'https://kerf.test/workshop', postMessage: (m) => calls.postMessage.push(m), focus: () => {} }]

  const self = {
    addEventListener: (type, fn) => {
      listeners[type] = fn
    },
    skipWaiting: () => {},
    clients: { claim: async () => {}, matchAll: async () => clientsList, openWindow: async () => {} },
    registration: {
      showNotification: async (title, opts) => {
        calls.notifications.push({ title, opts })
      },
    },
    Notification: { permission: notificationPermission },
  }

  const caches = makeCacheStorage(cacheStore, { failing: failingCaches, counters: calls })

  // Seed the page-written wake state bucket so the re-crawl path is reachable.
  if (wakeState && !failingCaches) {
    if (!cacheStore.has('kerf-wake-state-v1')) cacheStore.set('kerf-wake-state-v1', new Map())
    cacheStore.get('kerf-wake-state-v1').set('/__kerf-wake-state', JSON.stringify(wakeState))
  }

  const sandbox = {
    self,
    caches,
    // Only Date.now() is used by sw.js; the fake keeps the gate's window
    // arithmetic under the test's control.
    Date: { now: () => clock.now },
    Response: class {
      constructor(body) {
        this._body = body
      }
      async text() {
        return this._body
      }
      async json() {
        return JSON.parse(this._body)
      }
    },
    fetch: async (url, init) => {
      calls.fetch.push({ url, init })
      return { ok: true }
    },
    Promise,
    Uint8Array,
    JSON,
    Array,
    Error,
    isFinite,
    console,
    encodeURIComponent,
  }
  vm.createContext(sandbox)
  vm.runInContext(SW_SOURCE, sandbox, { filename: SW_PATH })

  return { listeners, calls, clock }
}

// A push event whose decrypted plaintext is `bytes`; `null` means "no payload".
function pushEvent(bytes) {
  const waits = []
  return {
    event: {
      data: bytes === null ? null : { arrayBuffer: async () => Uint8Array.from(bytes).buffer },
      waitUntil: (p) => waits.push(p),
    },
    settle: async () => {
      await Promise.all(waits)
    },
  }
}

const nonce = (seed) => [seed & 0xff, (seed >> 8) & 0xff, ...Array(14).fill(0)]
const nonceHex = (seed) =>
  nonce(seed)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')

async function deliver(worker, bytes) {
  const { event, settle } = pushEvent(bytes)
  worker.listeners.push(event)
  await settle()
}

const persisted = (store) => JSON.parse(store.get(REPLAY_BUCKET).get(REPLAY_URL))

function seedReplayRecord(store, record) {
  if (!store.has(REPLAY_BUCKET)) store.set(REPLAY_BUCKET, new Map())
  store.get(REPLAY_BUCKET).set(REPLAY_URL, JSON.stringify(record))
}

const wakeState = { apiUrl: 'https://kerf.test', accessToken: 'tok', pubs: ['pubA', 'pubB'] }

// ---- coverage assertion: we really are driving the shipped file ------------

describe('public/sw.js is the file under test', () => {
  it('is readable and registers the handlers these tests drive', () => {
    expect(SW_SOURCE.length).toBeGreaterThan(500)
    const store = new Map()
    const worker = bootWorker({ cacheStore: store })
    expect(typeof worker.listeners.push).toBe('function')
    expect(typeof worker.listeners.notificationclick).toBe('function')
  })

  it('contains the §8.4 gate constants this suite is written against', () => {
    // If a gate is ever deleted or renamed, fail here with a clear reason
    // rather than passing vacuously because nothing is left to exercise.
    for (const needle of [
      'kerf-wake-replay-v1',
      '__kerf-wake-seen-nonces',
      'WAKE_NONCE_BYTES = 16',
      'WAKE_REPLAY_MAX',
      'WAKE_REPLAY_TTL_MS',
      'WAKE_MIN_INTERVAL_MS',
      'WAKE_HOURLY_BUDGET',
      'claimWake',
    ]) {
      expect(SW_SOURCE, `public/sw.js no longer contains ${needle}`).toContain(needle)
    }
  })

  it('pins the §16 budgets the gate claims to enforce', () => {
    // DMTAP core §16: "≤ 1 wake / 60 s per device …, budget ≈ 30 wakes / h" and
    // "≥ recent 512 nonces or 24 h, whichever larger". A silent loosening of any
    // of these should be a failing test, not a diff nobody reads.
    expect(SW_SOURCE).toContain('const WAKE_MIN_INTERVAL_MS = 60 * 1000')
    expect(SW_SOURCE).toContain('const WAKE_HOURLY_BUDGET = 30')
    expect(SW_SOURCE).toContain('const WAKE_BUDGET_WINDOW_MS = 60 * 60 * 1000')
    expect(SW_SOURCE).toContain('const WAKE_REPLAY_TTL_MS = 24 * 60 * 60 * 1000')
    const max = /const WAKE_REPLAY_MAX = (\d+)/.exec(SW_SOURCE)
    expect(max, 'WAKE_REPLAY_MAX is gone').not.toBeNull()
    // §16's floor is 512 nonces; the ceiling must also cover 24 h of wakes at
    // the hourly budget (30 × 24 = 720) or the two §16 rows would contradict.
    expect(Number(max[1])).toBeGreaterThanOrEqual(720)
  })
})

describe('§8.4 replay-dedup (ERR_WAKEPING_REPLAY 0x0316)', () => {
  let store

  beforeEach(() => {
    store = new Map()
  })

  it('accepts a fresh nonce and does the wake work', async () => {
    const w = bootWorker({ cacheStore: store, wakeState })
    await deliver(w, nonce(1))

    expect(w.calls.fetch).toHaveLength(2) // one targeted re-crawl per followed pub
    expect(w.calls.postMessage).toEqual([{ type: 'kerf-wake' }])
    expect(w.calls.notifications).toHaveLength(1)
  })

  it('drops a replayed nonce completely — no fetch, no postMessage, no notification', async () => {
    const w = bootWorker({ cacheStore: store, wakeState })
    await deliver(w, nonce(1))
    const after = {
      fetch: w.calls.fetch.length,
      post: w.calls.postMessage.length,
      notify: w.calls.notifications.length,
    }

    w.clock.advance(2 * MINUTE) // past the rate-limit window: this is the replay gate's test
    await deliver(w, nonce(1)) // the relay replays the identical sealed wake

    expect(w.calls.fetch).toHaveLength(after.fetch)
    expect(w.calls.postMessage).toHaveLength(after.post)
    expect(w.calls.notifications).toHaveLength(after.notify)
  })

  it('costs no Cache Storage write when a relay floods one captured wake', async () => {
    // A replay is refused on the read alone. Turning a replay flood into a write
    // flood would hand the relay a second way to spend the device.
    const w = bootWorker({ cacheStore: store, wakeState })
    await deliver(w, nonce(1))
    const putsAfterAccept = w.calls.puts
    expect(putsAfterAccept).toBeGreaterThan(0)

    for (let i = 0; i < 50; i++) {
      w.clock.advance(2 * MINUTE)
      await deliver(w, nonce(1))
    }
    expect(w.calls.puts).toBe(putsAfterAccept)
  })

  it('still drops the replay after the worker is torn down and restarted', async () => {
    // The case an in-memory Set would silently fail: a worker woken purely for
    // a push starts with a fresh global scope.
    const clock = makeClock()
    const first = bootWorker({ cacheStore: store, wakeState, clock })
    await deliver(first, nonce(7))
    expect(first.calls.fetch.length).toBeGreaterThan(0)

    clock.advance(2 * MINUTE)
    const second = bootWorker({ cacheStore: store, wakeState, clock }) // new instance, same origin storage
    await deliver(second, nonce(7))

    expect(second.calls.fetch).toHaveLength(0)
    expect(second.calls.notifications).toHaveLength(0)
  })

  it('dedups against a v1 record (bare hex array, no timestamps)', async () => {
    // Upgrade path: a device that already has the pre-timestamp cache must not
    // forget its accepted nonces — forgetting one is what lets a replay through.
    seedReplayRecord(store, [nonceHex(11), nonceHex(12)])
    const w = bootWorker({ cacheStore: store, wakeState })
    await deliver(w, nonce(11))
    expect(w.calls.notifications).toHaveLength(0)
  })

  it('accepts distinct nonces from distinct wakes, one per window', async () => {
    const w = bootWorker({ cacheStore: store, wakeState })
    await deliver(w, nonce(1))
    w.clock.advance(2 * MINUTE)
    await deliver(w, nonce(2))
    expect(w.calls.notifications).toHaveLength(2)
  })

  it('claims a nonce once even when two deliveries interleave', async () => {
    const w = bootWorker({ cacheStore: store, wakeState })
    const a = pushEvent(nonce(3))
    const b = pushEvent(nonce(3))
    w.listeners.push(a.event)
    w.listeners.push(b.event)
    await Promise.all([a.settle(), b.settle()])

    expect(w.calls.notifications).toHaveLength(1)
  })

  it('evicts entries past the 24 h TTL', async () => {
    const clock = makeClock()
    seedReplayRecord(store, {
      v: 2,
      seen: [{ n: nonceHex(21), t: clock.now - 25 * HOUR }],
      accepts: [],
    })
    const w = bootWorker({ cacheStore: store, wakeState, clock })
    await deliver(w, nonce(21)) // older than the TTL: no longer a remembered accept
    expect(w.calls.notifications).toHaveLength(1)
    expect(persisted(store).seen.map((e) => e.n)).toEqual([nonceHex(21)])
  })

  it('bounds the persisted cache, newest first', async () => {
    // An unbounded nonce cache is its own denial of service, so the ceiling is
    // enforced even when the record on disk arrives oversized.
    const clock = makeClock()
    const oversized = Array.from({ length: 1500 }, (_, i) => ({ n: nonceHex(1000 + i), t: clock.now - i }))
    seedReplayRecord(store, { v: 2, seen: oversized, accepts: [] })

    const w = bootWorker({ cacheStore: store, wakeState, clock })
    await deliver(w, nonce(5))

    const rec = persisted(store)
    const max = Number(/const WAKE_REPLAY_MAX = (\d+)/.exec(SW_SOURCE)[1])
    expect(rec.seen).toHaveLength(max)
    expect(rec.seen[0].n).toBe(nonceHex(5)) // newest first
  })
})

describe('§8.4 content-free shape check (ERR_WAKEPING_CONTENT_PRESENT 0x0313)', () => {
  it.each([
    ['no payload at all', null],
    ['a truncated token', [1, 2, 3]],
    ['an over-long payload', Array.from({ length: 64 }, (_, i) => i)],
    ['an empty payload', []],
  ])('drops %s', async (_label, bytes) => {
    const w = bootWorker({ cacheStore: new Map(), wakeState })
    await deliver(w, bytes)
    expect(w.calls.fetch).toHaveLength(0)
    expect(w.calls.postMessage).toHaveLength(0)
    expect(w.calls.notifications).toHaveLength(0)
  })
})

describe('§8.4 inbound rate-limit backstop (ERR_WAKEPING_RATE_LIMITED 0x0315)', () => {
  let store

  beforeEach(() => {
    store = new Map()
  })

  it('refuses a flood of distinct fresh nonces inside the 60 s window', async () => {
    // §16: ≤ 1 wake / 60 s per device. Each of these is a well-formed, never-seen
    // nonce — only the budget stops them, which is the whole point of the
    // backstop: a relay that can replay can also withhold-and-burst.
    const w = bootWorker({ cacheStore: store, wakeState })
    await deliver(w, nonce(100))
    expect(w.calls.notifications).toHaveLength(1)

    for (let i = 1; i <= 20; i++) {
      w.clock.advance(1000)
      await deliver(w, nonce(100 + i))
    }

    expect(w.calls.notifications).toHaveLength(1)
    expect(w.calls.fetch).toHaveLength(2) // only the first wake's two re-crawls
    expect(w.calls.postMessage).toHaveLength(1)
  })

  it('accepts again once the 60 s window has passed', async () => {
    const w = bootWorker({ cacheStore: store, wakeState })
    await deliver(w, nonce(200))
    w.clock.advance(30 * 1000)
    await deliver(w, nonce(201))
    expect(w.calls.notifications).toHaveLength(1)

    w.clock.advance(31 * 1000) // now > 60 s since the last ACCEPTED wake
    await deliver(w, nonce(202))
    expect(w.calls.notifications).toHaveLength(2)
  })

  it('refuses past the ≈30 wakes/h budget even when each is spaced over 60 s', async () => {
    const w = bootWorker({ cacheStore: store, wakeState })
    for (let i = 0; i < 30; i++) {
      await deliver(w, nonce(300 + i))
      w.clock.advance(61 * 1000)
    }
    expect(w.calls.notifications).toHaveLength(30) // the hour's whole budget

    await deliver(w, nonce(400)) // 31st inside the same hour
    expect(w.calls.notifications).toHaveLength(30)

    // Once the oldest accept ages out of the rolling hour there is room again.
    w.clock.advance(HOUR)
    await deliver(w, nonce(401))
    expect(w.calls.notifications).toHaveLength(31)
  })

  it('enforces the budget across a worker restart', async () => {
    // The limiter is only a backstop if it survives the process lifetime a push
    // wake actually has: one event.
    const clock = makeClock()
    const first = bootWorker({ cacheStore: store, wakeState, clock })
    await deliver(first, nonce(500))
    expect(first.calls.notifications).toHaveLength(1)

    clock.advance(5 * 1000)
    const second = bootWorker({ cacheStore: store, wakeState, clock })
    await deliver(second, nonce(501)) // fresh nonce, new worker, same device
    expect(second.calls.notifications).toHaveLength(0)
    expect(second.calls.fetch).toHaveLength(0)
  })

  it('does not bank a refused wake as accepted', async () => {
    // §4.9.4 dedups "recently-accepted" nonces, so a wake refused for budget was
    // never accepted and may land later — bounded by the budget, which is
    // exactly the guarantee §8.4 asks the receiver for.
    const w = bootWorker({ cacheStore: store, wakeState })
    await deliver(w, nonce(600))
    w.clock.advance(1000)
    await deliver(w, nonce(601)) // refused: inside the window
    expect(w.calls.notifications).toHaveLength(1)
    expect(persisted(store).seen.map((e) => e.n)).toEqual([nonceHex(600)])

    w.clock.advance(2 * MINUTE)
    await deliver(w, nonce(601))
    expect(w.calls.notifications).toHaveLength(2)
  })

  it('treats a backwards clock jump conservatively, and self-heals', async () => {
    // A stored accept stamped in the future (user moved the clock back) must not
    // read as "long ago" — it is clamped to now, so the limiter stays closed for
    // one window and then recovers rather than wedging.
    const clock = makeClock()
    seedReplayRecord(store, { v: 2, seen: [], accepts: [clock.now + 10 * HOUR] })
    const w = bootWorker({ cacheStore: store, wakeState, clock })

    await deliver(w, nonce(700))
    expect(w.calls.notifications).toHaveLength(0)

    clock.advance(2 * MINUTE)
    await deliver(w, nonce(701))
    expect(w.calls.notifications).toHaveLength(1)
  })
})

describe('the gate fails closed', () => {
  it('drops the wake when Cache Storage cannot be used at all', async () => {
    // Private browsing / quota pressure: the device cannot run §8.4's gates, so
    // it must not do the work either. Dropping costs only latency — pull is the
    // source of truth — so failing open here would buy nothing.
    const w = bootWorker({ cacheStore: new Map(), failingCaches: true })
    await deliver(w, nonce(9))
    expect(w.calls.fetch).toHaveLength(0)
    expect(w.calls.postMessage).toHaveLength(0)
    expect(w.calls.notifications).toHaveLength(0)
  })

  it('drops the wake when reading the payload throws', async () => {
    const w = bootWorker({ cacheStore: new Map() })
    const waits = []
    w.listeners.push({
      data: {
        arrayBuffer: async () => {
          throw new Error('decrypt failed')
        },
      },
      waitUntil: (p) => waits.push(p),
    })
    await Promise.all(waits)
    expect(w.calls.fetch).toHaveLength(0)
    expect(w.calls.notifications).toHaveLength(0)
  })

  it('drops the wake when the persisted record is corrupt, then recovers', async () => {
    const store = new Map()
    store.set(REPLAY_BUCKET, new Map([[REPLAY_URL, 'not json{']]))
    const w = bootWorker({ cacheStore: store, wakeState })

    await deliver(w, nonce(800))
    expect(w.calls.notifications).toHaveLength(0) // fail closed on the unreadable record

    w.clock.advance(2 * MINUTE)
    await deliver(w, nonce(801)) // record was reset to a valid empty one
    expect(w.calls.notifications).toHaveLength(1)
  })
})
