// serviceWorkerWakeGate.test.js — ROLES.md §8.4's device-side wake gates, as
// implemented by public/sw.js's `push` handler.
//
// public/sw.js is a classic (non-module) service worker: it is never imported
// by the app bundle, has no exports, and registers its behaviour by calling
// self.addEventListener at top level. So this file does what a browser does —
// evaluates the real file's source in a scope carrying a fake `self`, `caches`
// and `fetch`, captures the listeners it registers, and drives them. The gate
// under test is therefore the shipped bytes of public/sw.js, not a
// reimplementation of them: if someone deletes the replay cache from sw.js,
// these tests fail.
//
// What is asserted, per §8.4:
//   - a fresh 16-byte nonce is accepted exactly once (the wake does its work);
//   - the SAME nonce replayed does no work at all — no re-crawl POST, no tab
//     postMessage, no notification (0x0316 ERR_WAKEPING_REPLAY, DROP_SILENT);
//   - the replay cache survives a worker restart, which is the whole point of
//     persisting it (a push-woken worker starts with an empty global scope);
//   - a payload that is not exactly the 16-byte token — absent, short, long —
//     is dropped unread (0x0313 ERR_WAKEPING_CONTENT_PRESENT);
//   - the cache stays bounded, newest-first;
//   - concurrent delivery of one nonce is claimed once, not twice;
//   - a broken Cache Storage fails CLOSED (drop), never open.
//
// COVERAGE ASSERTION: this suite is worthless if it silently stops exercising
// the real file, so it first asserts that public/sw.js is readable, registers a
// `push` listener, and contains the replay-cache constants it is written
// against. A stub that no-ops would fail those before any behaviour is checked.

import { describe, it, expect, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import vm from 'node:vm'

const HERE = dirname(fileURLToPath(import.meta.url))
const SW_PATH = resolve(HERE, '../../../public/sw.js')
const SW_SOURCE = readFileSync(SW_PATH, 'utf8')

// ---- a minimal Cache Storage that persists across "worker restarts" --------

function makeCacheStorage(store, { failing = false } = {}) {
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
          bucket.set(url, await res.text())
        },
      }
    },
  }
}

// ---- boot a fresh "service worker instance" over the real sw.js source -----

function bootWorker({ cacheStore, failingCaches = false, wakeState = null, notificationPermission = 'granted' } = {}) {
  const listeners = {}
  const calls = { fetch: [], postMessage: [], notifications: [] }

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

  const caches = makeCacheStorage(cacheStore, { failing: failingCaches })

  // Seed the page-written wake state bucket so the re-crawl path is reachable.
  if (wakeState && !failingCaches) {
    if (!cacheStore.has('kerf-wake-state-v1')) cacheStore.set('kerf-wake-state-v1', new Map())
    cacheStore.get('kerf-wake-state-v1').set('/__kerf-wake-state', JSON.stringify(wakeState))
  }

  const sandbox = {
    self,
    caches,
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
    console,
    encodeURIComponent,
  }
  vm.createContext(sandbox)
  vm.runInContext(SW_SOURCE, sandbox, { filename: SW_PATH })

  return { listeners, calls }
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

const nonce = (seed) => Array.from({ length: 16 }, (_, i) => (seed + i) & 0xff)

async function deliver(worker, bytes) {
  const { event, settle } = pushEvent(bytes)
  worker.listeners.push(event)
  await settle()
}

// ---- coverage assertion: we really are driving the shipped file ------------

describe('public/sw.js is the file under test', () => {
  it('is readable and registers the handlers these tests drive', () => {
    expect(SW_SOURCE.length).toBeGreaterThan(500)
    const store = new Map()
    const worker = bootWorker({ cacheStore: store })
    expect(typeof worker.listeners.push).toBe('function')
    expect(typeof worker.listeners.notificationclick).toBe('function')
  })

  it('contains the §8.4 replay-gate constants this suite is written against', () => {
    // If the gate is ever deleted or renamed, fail here with a clear reason
    // rather than passing vacuously because nothing is left to exercise.
    for (const needle of [
      'kerf-wake-replay-v1',
      '__kerf-wake-seen-nonces',
      'WAKE_NONCE_BYTES = 16',
      'WAKE_REPLAY_MAX',
      'claimWakeNonce',
    ]) {
      expect(SW_SOURCE, `public/sw.js no longer contains ${needle}`).toContain(needle)
    }
  })
})

describe('§8.4 replay-dedup (ERR_WAKEPING_REPLAY 0x0316)', () => {
  let store
  const wakeState = { apiUrl: 'https://kerf.test', accessToken: 'tok', pubs: ['pubA', 'pubB'] }

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

    await deliver(w, nonce(1)) // the relay replays the identical sealed wake

    expect(w.calls.fetch).toHaveLength(after.fetch)
    expect(w.calls.postMessage).toHaveLength(after.post)
    expect(w.calls.notifications).toHaveLength(after.notify)
  })

  it('still drops the replay after the worker is torn down and restarted', async () => {
    // The case an in-memory Set would silently fail: a worker woken purely for
    // a push starts with a fresh global scope.
    const first = bootWorker({ cacheStore: store, wakeState })
    await deliver(first, nonce(7))
    expect(first.calls.fetch.length).toBeGreaterThan(0)

    const second = bootWorker({ cacheStore: store, wakeState }) // new instance, same origin storage
    await deliver(second, nonce(7))

    expect(second.calls.fetch).toHaveLength(0)
    expect(second.calls.notifications).toHaveLength(0)
  })

  it('accepts distinct nonces from distinct wakes', async () => {
    const w = bootWorker({ cacheStore: store, wakeState })
    await deliver(w, nonce(1))
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

  it('bounds the persisted cache, newest first', async () => {
    const w = bootWorker({ cacheStore: store, wakeState })
    for (let i = 0; i < 260; i++) {
      // 260 distinct nonces: 16 bytes each, differing in the first two.
      await deliver(w, [i & 0xff, (i >> 8) & 0xff, ...Array(14).fill(0)])
    }
    const persisted = JSON.parse(store.get('kerf-wake-replay-v1').get('/__kerf-wake-seen-nonces'))
    expect(persisted).toHaveLength(256)
    // Newest first: the last nonce delivered (259 = 0x0103) heads the list.
    expect(persisted[0]).toBe('0301' + '00'.repeat(14))
  })
})

describe('§8.4 content-free shape check (ERR_WAKEPING_CONTENT_PRESENT 0x0313)', () => {
  const wakeState = { apiUrl: 'https://kerf.test', accessToken: 'tok', pubs: ['pubA'] }

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

describe('the gate fails closed', () => {
  it('drops the wake when Cache Storage cannot be used at all', async () => {
    // Private browsing / quota pressure: the device cannot run §8.4's gate, so
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
})
