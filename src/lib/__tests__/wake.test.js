// wake.test.js — unit tests for src/lib/wake.js, the browser-side
// orchestration behind the Workshop's "Notify me" toggle
// (docs/distributed-workshop.md's "Wake" section, public/sw.js's receive
// side, packages/kerf-pub/src/kerf_pub/wake.py's server side).
//
// This repo has no jsdom (see src/lib/detectWebGL.test.js's header comment)
// — browser globals (navigator, window, Notification, caches) are patched
// directly on globalThis per test and restored in a finally block, and the
// cloud API client + zustand stores are vi.mock'd so this file exercises
// wake.js's own logic in isolation.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ApiError } from '../api.js'

// ---- mocks ------------------------------------------------------------

const wakeApiMock = { getKey: vi.fn(), subscribe: vi.fn(), unsubscribe: vi.fn() }
vi.mock('../../cloud/api.js', () => ({ wake: wakeApiMock }))

const writeWakeStateMock = vi.fn()
vi.mock('../wakeState.js', () => ({ writeWakeState: (...args) => writeWakeStateMock(...args) }))

// A minimal fake of the zustand `useWake` store — enough for wake.js's
// getState()/setEnabled() calls, with real mutation so "does disabling the
// last enabled pub tear down the push subscription" can be exercised.
let wakeStoreState
vi.mock('../../store/wake.js', () => ({
  useWake: { getState: () => wakeStoreState },
}))

let authStoreState
vi.mock('../../store/auth.js', () => ({
  useAuth: { getState: () => authStoreState },
}))

const {
  isWakeBrowserSupported, isWakeUsableForFollow, urlBase64ToUint8Array,
  getWakeKeyInfo, enableWakeNotifications, disableWakeNotifications,
  onWakeMessage, syncWakeStateOnChange,
} = await import('../wake.js')

// wake.js resolves its own API_URL the same way (import.meta.env.VITE_API_URL
// || ''); mirror that here instead of hardcoding '' so this file doesn't
// depend on whether a developer .env sets VITE_API_URL (see
// src/cloud/__tests__/pubApi.contract.test.js's identical note).
const API_URL = import.meta.env.VITE_API_URL || ''

// ---- helpers ------------------------------------------------------------

// withGlobals patches the given browser globals for the duration of `fn`.
// `fn` may be sync or async (most of wake.js's exports are async, resuming
// after an `await` on a later microtask) — if it returns a thenable, restore
// only happens once that settles, via `.finally()`, so the patched globals
// are still in place for every await inside `fn`, not just its synchronous
// prologue. Sync callers keep their exact prior behaviour: assertion errors
// thrown inside `fn` propagate synchronously, restoring first.
function withGlobals(overrides, fn) {
  const keys = ['navigator', 'window', 'Notification', 'caches']
  const saved = {}
  for (const k of keys) saved[k] = globalThis[k]
  for (const k of keys) {
    if (k in overrides) globalThis[k] = overrides[k]
    else delete globalThis[k]
  }
  const restore = () => {
    for (const k of keys) {
      if (saved[k] === undefined) delete globalThis[k]
      else globalThis[k] = saved[k]
    }
  }
  let result
  try {
    result = fn()
  } catch (err) {
    restore()
    throw err
  }
  if (result && typeof result.then === 'function') {
    return result.finally(restore)
  }
  restore()
  return result
}

function makeSupportedGlobals({ permission = 'default', registration } = {}) {
  const reg = registration || {
    pushManager: {
      getSubscription: vi.fn().mockResolvedValue(null),
      subscribe: vi.fn().mockResolvedValue({
        endpoint: 'https://push.example.net/ep/1',
        keys: { p256dh: 'p256dh-value', auth: 'auth-value' },
        toJSON() {
          return { endpoint: this.endpoint, keys: this.keys }
        },
      }),
    },
  }
  return {
    navigator: {
      serviceWorker: {
        register: vi.fn().mockResolvedValue(reg),
        ready: Promise.resolve(reg),
        getRegistration: vi.fn().mockResolvedValue(reg),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    },
    window: { PushManager: function PushManager() {}, location: { origin: 'https://kerf.sh' } },
    Notification: { permission, requestPermission: vi.fn().mockResolvedValue('granted') },
    caches: { open: vi.fn() },
    __registration: reg,
  }
}

beforeEach(() => {
  wakeStoreState = {
    enabledPubs: [],
    setEnabled: vi.fn((pubKey, on) => {
      wakeStoreState.enabledPubs = on
        ? (wakeStoreState.enabledPubs.includes(pubKey) ? wakeStoreState.enabledPubs : [...wakeStoreState.enabledPubs, pubKey])
        : wakeStoreState.enabledPubs.filter((p) => p !== pubKey)
    }),
  }
  authStoreState = { accessToken: 'tok-abc' }
  wakeApiMock.getKey.mockReset()
  wakeApiMock.subscribe.mockReset()
  wakeApiMock.unsubscribe.mockReset()
  writeWakeStateMock.mockReset()
})

// ---------------------------------------------------------------------------
// isWakeBrowserSupported
// ---------------------------------------------------------------------------

describe('isWakeBrowserSupported', () => {
  it('is false with no browser globals at all (SSR / Node)', () => {
    withGlobals({}, () => {
      expect(isWakeBrowserSupported()).toBe(false)
    })
  })

  it('is false when serviceWorker is missing from navigator', () => {
    withGlobals({ navigator: {}, window: { PushManager: function () {} }, Notification: {} }, () => {
      expect(isWakeBrowserSupported()).toBe(false)
    })
  })

  it('is false when PushManager is missing from window', () => {
    withGlobals({ navigator: { serviceWorker: {} }, window: {}, Notification: {} }, () => {
      expect(isWakeBrowserSupported()).toBe(false)
    })
  })

  it('is false when Notification is undefined', () => {
    withGlobals({ navigator: { serviceWorker: {} }, window: { PushManager: function () {} } }, () => {
      expect(isWakeBrowserSupported()).toBe(false)
    })
  })

  it('is true when all three are present', () => {
    withGlobals(
      { navigator: { serviceWorker: {} }, window: { PushManager: function () {} }, Notification: {} },
      () => {
        expect(isWakeBrowserSupported()).toBe(true)
      },
    )
  })
})

// ---------------------------------------------------------------------------
// isWakeUsableForFollow
// ---------------------------------------------------------------------------

describe('isWakeUsableForFollow', () => {
  it('is usable when gateway_url is empty/missing (this node, no explicit gateway)', () => {
    expect(isWakeUsableForFollow({ pub: 'ed25519:aaaa' }, 'https://kerf.sh')).toBe(true)
    expect(isWakeUsableForFollow({ pub: 'ed25519:aaaa', gateway_url: '' }, 'https://kerf.sh')).toBe(true)
    expect(isWakeUsableForFollow({ pub: 'ed25519:aaaa', gateway_url: '   ' }, 'https://kerf.sh')).toBe(true)
  })

  it('is usable when gateway_url resolves to the same origin', () => {
    expect(isWakeUsableForFollow({ gateway_url: 'https://kerf.sh' }, 'https://kerf.sh')).toBe(true)
    expect(isWakeUsableForFollow({ gateway_url: 'https://kerf.sh/some/path' }, 'https://kerf.sh')).toBe(true)
  })

  it('is NOT usable when gateway_url names a different node', () => {
    expect(isWakeUsableForFollow({ gateway_url: 'https://other-node.example' }, 'https://kerf.sh')).toBe(false)
  })

  it('is NOT usable when gateway_url is malformed and origin is available', () => {
    expect(isWakeUsableForFollow({ gateway_url: 'http://[invalid' }, 'https://kerf.sh')).toBe(false)
  })

  it('is NOT usable when there is no origin to compare against', () => {
    expect(isWakeUsableForFollow({ gateway_url: 'https://other-node.example' }, null)).toBe(false)
  })

  it('falls back to window.location.origin when currentOrigin is not passed', () => {
    withGlobals({ window: { location: { origin: 'https://kerf.sh' } } }, () => {
      expect(isWakeUsableForFollow({ gateway_url: 'https://kerf.sh' })).toBe(true)
      expect(isWakeUsableForFollow({ gateway_url: 'https://elsewhere.example' })).toBe(false)
    })
  })
})

// ---------------------------------------------------------------------------
// urlBase64ToUint8Array
// ---------------------------------------------------------------------------

describe('urlBase64ToUint8Array', () => {
  it('decodes a base64url string (with -/_ substitution) to the right bytes', () => {
    // "hello" -> base64 "aGVsbG8=" -> base64url "aGVsbG8" (no padding, no -/_ here)
    const out = urlBase64ToUint8Array('aGVsbG8')
    expect(Array.from(out)).toEqual(Array.from(new TextEncoder().encode('hello')))
  })

  it('handles base64url characters (- and _) not valid in standard base64', () => {
    // bytes [0xfb, 0xff] -> standard base64 "+/8=" -> base64url "-_8"
    const out = urlBase64ToUint8Array('-_8')
    expect(Array.from(out)).toEqual([0xfb, 0xff])
  })
})

// ---------------------------------------------------------------------------
// getWakeKeyInfo
// ---------------------------------------------------------------------------

describe('getWakeKeyInfo', () => {
  it('returns available:true + the public key on success', async () => {
    wakeApiMock.getKey.mockResolvedValue({ public_key: 'fake-vapid-key' })
    const info = await getWakeKeyInfo({ fresh: true })
    expect(info).toEqual({ available: true, publicKey: 'fake-vapid-key' })
  })

  it('never throws — a 503 (wake not configured) resolves to available:false', async () => {
    wakeApiMock.getKey.mockRejectedValue(new ApiError(503, 'wake is not configured on this node'))
    const info = await getWakeKeyInfo({ fresh: true })
    expect(info).toEqual({ available: false, publicKey: null })
  })

  it('caches the result — a second call does not re-hit the API unless fresh:true', async () => {
    wakeApiMock.getKey.mockResolvedValue({ public_key: 'k1' })
    await getWakeKeyInfo({ fresh: true })
    wakeApiMock.getKey.mockResolvedValue({ public_key: 'k2' })
    const second = await getWakeKeyInfo()
    expect(second.publicKey).toBe('k1')
    expect(wakeApiMock.getKey).toHaveBeenCalledTimes(1)

    const fresh = await getWakeKeyInfo({ fresh: true })
    expect(fresh.publicKey).toBe('k2')
    expect(wakeApiMock.getKey).toHaveBeenCalledTimes(2)
  })
})

// ---------------------------------------------------------------------------
// enableWakeNotifications
// ---------------------------------------------------------------------------

describe('enableWakeNotifications', () => {
  it('fails fast when the browser does not support Push', async () => {
    const res = await withGlobals({}, () => enableWakeNotifications('ed25519:aaaa'))
    expect(res).toEqual({ ok: false, error: "Push notifications aren't supported in this browser." })
    expect(wakeApiMock.getKey).not.toHaveBeenCalled()
  })

  it('fails when Notification permission was previously denied', async () => {
    const g = makeSupportedGlobals({ permission: 'denied' })
    const res = await withGlobals(g, () => enableWakeNotifications('ed25519:aaaa'))
    expect(res).toEqual({ ok: false, error: 'Notifications are blocked for this site.' })
  })

  it('fails when this node has no VAPID key configured', async () => {
    wakeApiMock.getKey.mockRejectedValue(new ApiError(503, 'not configured'))
    await getWakeKeyInfo({ fresh: true }) // prime the module-level cache with this test's mock
    const g = makeSupportedGlobals()
    const res = await withGlobals(g, () => enableWakeNotifications('ed25519:aaaa'))
    expect(res).toEqual({ ok: false, error: 'Wake is not configured on this node.' })
  })

  it('fails when the user declines the permission prompt', async () => {
    wakeApiMock.getKey.mockResolvedValue({ public_key: 'fake-key' })
    await getWakeKeyInfo({ fresh: true })
    const g = makeSupportedGlobals({ permission: 'default' })
    g.Notification.requestPermission = vi.fn().mockResolvedValue('denied')
    const res = await withGlobals(g, () => enableWakeNotifications('ed25519:aaaa'))
    expect(res).toEqual({ ok: false, error: 'Notification permission was not granted.' })
    expect(wakeApiMock.subscribe).not.toHaveBeenCalled()
  })

  it('full success path: permission -> SW register -> subscribe -> register endpoint -> local store + SW state mirror', async () => {
    wakeApiMock.getKey.mockResolvedValue({ public_key: 'fake-key' })
    await getWakeKeyInfo({ fresh: true })
    wakeApiMock.subscribe.mockResolvedValue({ pub: 'ed25519:aaaa', subscribed: true })
    const g = makeSupportedGlobals({ permission: 'granted' })

    const res = await withGlobals(g, () => enableWakeNotifications('ed25519:aaaa'))

    expect(res).toEqual({ ok: true, error: null })
    expect(g.navigator.serviceWorker.register).toHaveBeenCalledWith('/sw.js')
    expect(g.__registration.pushManager.subscribe).toHaveBeenCalledWith(
      expect.objectContaining({ userVisibleOnly: true }),
    )
    expect(wakeApiMock.subscribe).toHaveBeenCalledWith('ed25519:aaaa', {
      endpoint: 'https://push.example.net/ep/1',
      keys: { p256dh: 'p256dh-value', auth: 'auth-value' },
    })
    expect(wakeStoreState.enabledPubs).toEqual(['ed25519:aaaa'])
    expect(writeWakeStateMock).toHaveBeenCalledWith({
      apiUrl: API_URL,
      accessToken: 'tok-abc',
      pubs: ['ed25519:aaaa'],
    })
  })

  it('reuses an existing push subscription instead of subscribing again', async () => {
    wakeApiMock.getKey.mockResolvedValue({ public_key: 'fake-key' })
    await getWakeKeyInfo({ fresh: true })
    wakeApiMock.subscribe.mockResolvedValue({ subscribed: true })
    const existing = {
      endpoint: 'https://push.example.net/ep/existing',
      keys: { p256dh: 'p', auth: 'a' },
      toJSON() { return { endpoint: this.endpoint, keys: this.keys } },
    }
    const g = makeSupportedGlobals({ permission: 'granted' })
    g.__registration.pushManager.getSubscription = vi.fn().mockResolvedValue(existing)

    const res = await withGlobals(g, () => enableWakeNotifications('ed25519:bbbb'))

    expect(res.ok).toBe(true)
    expect(g.__registration.pushManager.subscribe).not.toHaveBeenCalled()
    expect(wakeApiMock.subscribe).toHaveBeenCalledWith('ed25519:bbbb', {
      endpoint: 'https://push.example.net/ep/existing',
      keys: { p256dh: 'p', auth: 'a' },
    })
  })

  it('surfaces the server error message when the subscribe endpoint rejects', async () => {
    wakeApiMock.getKey.mockResolvedValue({ public_key: 'fake-key' })
    await getWakeKeyInfo({ fresh: true })
    wakeApiMock.subscribe.mockRejectedValue(new ApiError(429, 'this feed has reached its wake-subscriber cap'))
    const g = makeSupportedGlobals({ permission: 'granted' })

    const res = await withGlobals(g, () => enableWakeNotifications('ed25519:aaaa'))

    expect(res).toEqual({ ok: false, error: 'this feed has reached its wake-subscriber cap' })
    expect(wakeStoreState.enabledPubs).toEqual([])
  })

  it('gives a generic error for a non-ApiError failure (e.g. subscribe() rejected by the browser)', async () => {
    wakeApiMock.getKey.mockResolvedValue({ public_key: 'fake-key' })
    await getWakeKeyInfo({ fresh: true })
    const g = makeSupportedGlobals({ permission: 'granted' })
    g.__registration.pushManager.getSubscription = vi.fn().mockResolvedValue(null)
    g.__registration.pushManager.subscribe = vi.fn().mockRejectedValue(new Error('boom'))

    const res = await withGlobals(g, () => enableWakeNotifications('ed25519:aaaa'))

    expect(res).toEqual({ ok: false, error: 'Could not enable notifications.' })
  })
})

// ---------------------------------------------------------------------------
// disableWakeNotifications
// ---------------------------------------------------------------------------

describe('disableWakeNotifications', () => {
  it('turns the local toggle off immediately, even before the network call resolves', async () => {
    wakeStoreState.enabledPubs = ['ed25519:aaaa']
    wakeApiMock.unsubscribe.mockResolvedValue({ subscribed: false })
    const g = makeSupportedGlobals()
    g.__registration.pushManager.getSubscription = vi.fn().mockResolvedValue({
      endpoint: 'https://push.example.net/ep/1',
      unsubscribe: vi.fn().mockResolvedValue(true),
    })

    await withGlobals(g, () => disableWakeNotifications('ed25519:aaaa'))

    expect(wakeStoreState.setEnabled).toHaveBeenCalledWith('ed25519:aaaa', false)
  })

  it('unregisters the browser push subscription once no follow has Wake enabled anymore', async () => {
    wakeStoreState.enabledPubs = ['ed25519:aaaa']
    wakeApiMock.unsubscribe.mockResolvedValue({ subscribed: false })
    const g = makeSupportedGlobals()
    const existing = {
      endpoint: 'https://push.example.net/ep/1',
      unsubscribe: vi.fn().mockResolvedValue(true),
    }
    g.__registration.pushManager.getSubscription = vi.fn().mockResolvedValue(existing)

    const res = await withGlobals(g, () => disableWakeNotifications('ed25519:aaaa'))

    expect(res).toEqual({ ok: true, error: null })
    expect(existing.unsubscribe).toHaveBeenCalled()
  })

  it('keeps the shared browser push subscription alive if another follow still has Wake on', async () => {
    wakeStoreState.enabledPubs = ['ed25519:aaaa', 'ed25519:bbbb']
    wakeApiMock.unsubscribe.mockResolvedValue({ subscribed: false })
    const g = makeSupportedGlobals()
    const existing = {
      endpoint: 'https://push.example.net/ep/1',
      unsubscribe: vi.fn().mockResolvedValue(true),
    }
    g.__registration.pushManager.getSubscription = vi.fn().mockResolvedValue(existing)

    await withGlobals(g, () => disableWakeNotifications('ed25519:aaaa'))

    expect(existing.unsubscribe).not.toHaveBeenCalled()
  })

  it('is best-effort: a failed server unsubscribe still turns the toggle off, but reports the error', async () => {
    wakeStoreState.enabledPubs = ['ed25519:aaaa']
    wakeApiMock.unsubscribe.mockRejectedValue(new ApiError(500, 'gateway unreachable'))
    const g = makeSupportedGlobals()
    g.__registration.pushManager.getSubscription = vi.fn().mockResolvedValue({
      endpoint: 'https://push.example.net/ep/1',
      unsubscribe: vi.fn().mockResolvedValue(true),
    })

    const res = await withGlobals(g, () => disableWakeNotifications('ed25519:aaaa'))

    expect(res).toEqual({ ok: false, error: 'gateway unreachable' })
    expect(wakeStoreState.setEnabled).toHaveBeenCalledWith('ed25519:aaaa', false)
  })

  it('degrades gracefully with no browser Push support at all — just forgets the local toggle', async () => {
    wakeStoreState.enabledPubs = ['ed25519:aaaa']
    const res = await withGlobals({}, () => disableWakeNotifications('ed25519:aaaa'))
    expect(res).toEqual({ ok: true, error: null })
    expect(wakeStoreState.setEnabled).toHaveBeenCalledWith('ed25519:aaaa', false)
  })
})

// ---------------------------------------------------------------------------
// onWakeMessage / syncWakeStateOnChange
// ---------------------------------------------------------------------------

describe('onWakeMessage', () => {
  it('invokes the callback only for {type: "kerf-wake"} service worker messages', () => {
    let handler
    const nav = {
      serviceWorker: {
        addEventListener: vi.fn((event, cb) => { handler = cb }),
        removeEventListener: vi.fn(),
      },
    }
    withGlobals({ navigator: nav }, () => {
      const cb = vi.fn()
      const unsubscribe = onWakeMessage(cb)

      handler({ data: { type: 'kerf-wake' } })
      expect(cb).toHaveBeenCalledTimes(1)

      handler({ data: { type: 'something-else' } })
      expect(cb).toHaveBeenCalledTimes(1)

      handler({ data: null })
      expect(cb).toHaveBeenCalledTimes(1)

      unsubscribe()
      expect(nav.serviceWorker.removeEventListener).toHaveBeenCalledWith('message', handler)
    })
  })

  it('is a no-op (returns a callable unsubscribe) when there is no serviceWorker support', () => {
    const unsubscribe = withGlobals({}, () => onWakeMessage(vi.fn()))
    expect(() => unsubscribe()).not.toThrow()
  })
})

describe('syncWakeStateOnChange', () => {
  it('mirrors the current access token + enabled-pubs set via writeWakeState', async () => {
    authStoreState = { accessToken: 'tok-xyz' }
    wakeStoreState.enabledPubs = ['ed25519:aaaa', 'ed25519:bbbb']

    await syncWakeStateOnChange()

    expect(writeWakeStateMock).toHaveBeenCalledWith({
      apiUrl: API_URL,
      accessToken: 'tok-xyz',
      pubs: ['ed25519:aaaa', 'ed25519:bbbb'],
    })
  })
})
