// Wake push (RFC 8291/8292) — browser-side orchestration for the Workshop's
// "Notify me" toggle. See docs/distributed-workshop.md's "Wake" section for
// the full picture and public/sw.js for the receive side (the service
// worker's `push` handler).
//
// v1 scope: Wake only works for a follow whose subscribe target is THIS
// node's own gateway (an empty `gateway_url`, or one that resolves to this
// same origin) — a browser's Push API supports only ONE active subscription
// per (origin, service worker registration) at a time, keyed to a single
// `applicationServerKey` (RFC 8292's VAPID public key). Every feed hosted on
// THIS node shares this node's one VAPID identity (kerf_pub.wake's
// notify_subscribers signs with `default_wake_config()`, not a per-author
// key), so one shared subscription can register against any number of this
// node's followed feeds. A follow whose `gateway_url` names a genuinely
// different node has its own, different VAPID key — subscribing to it would
// need a SEPARATE Push subscription this origin's service worker cannot hold
// at the same time as the first, so v1 disables the toggle for those follows
// (isWakeUsableForFollow) rather than silently breaking whichever one was
// registered second.

import { wake as wakeApi } from '../cloud/api.js'
import { useWake } from '../store/wake.js'
import { useAuth } from '../store/auth.js'
import { writeWakeState } from './wakeState.js'
import { ApiError } from './api.js'

const API_URL = import.meta.env.VITE_API_URL || ''

export function isWakeBrowserSupported() {
  return (
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    typeof window !== 'undefined' &&
    'PushManager' in window &&
    typeof Notification !== 'undefined'
  )
}

// isWakeUsableForFollow — true when `follow.gateway_url` is empty (resolved
// purely from the local store, kerf_pub.router_local._resolve_follow_listings)
// or names this same origin; false for a genuinely different node's gateway
// (see module docstring for why). `currentOrigin` is injectable for tests —
// defaults to the real page origin in the browser.
export function isWakeUsableForFollow(follow, currentOrigin) {
  const origin = currentOrigin !== undefined
    ? currentOrigin
    : (typeof window !== 'undefined' ? window.location.origin : null)
  const gw = (follow && follow.gateway_url || '').trim()
  if (!gw) return true
  if (!origin) return false
  try {
    return new URL(gw, origin).origin === origin
  } catch {
    return false
  }
}

// urlBase64ToUint8Array — the standard Web Push conversion from a
// base64url-encoded VAPID public key to the Uint8Array PushManager.subscribe
// wants for `applicationServerKey`.
export function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const out = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

let cachedKeyInfo = null // { available, publicKey } | null — the node's own wake config

// getWakeKeyInfo() -> { available, publicKey } — never throws. Cached for the
// session (a node's wake config doesn't change without a restart); pass
// `{ fresh: true }` to bypass the cache.
export async function getWakeKeyInfo({ fresh = false } = {}) {
  if (cachedKeyInfo && !fresh) return cachedKeyInfo
  try {
    const res = await wakeApi.getKey()
    cachedKeyInfo = { available: true, publicKey: res.public_key }
  } catch {
    cachedKeyInfo = { available: false, publicKey: null }
  }
  return cachedKeyInfo
}

async function ensurePushSubscription(publicKeyB64) {
  const registration = await navigator.serviceWorker.register('/sw.js')
  await navigator.serviceWorker.ready

  const existing = await registration.pushManager.getSubscription()
  if (existing) return existing

  const applicationServerKey = urlBase64ToUint8Array(publicKeyB64)
  try {
    return await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey })
  } catch (err) {
    // A stale subscription registered under a since-rotated VAPID key (a
    // dev key regenerated, say) — browsers refuse subscribe() with a
    // mismatched key while one is already active. Self-heal once.
    const stale = await registration.pushManager.getSubscription()
    if (stale) {
      await stale.unsubscribe()
      return registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey })
    }
    throw err
  }
}

function syncWakeState() {
  const { accessToken } = useAuth.getState()
  const { enabledPubs } = useWake.getState()
  return writeWakeState({ apiUrl: API_URL, accessToken, pubs: enabledPubs })
}

// enableWakeNotifications(pubKey) — the full "Notify me" ON flow: permission
// -> service worker -> push subscription -> register with this feed's
// subscribe endpoint -> remember it locally. Returns {ok, error}; never
// throws — the toggle just surfaces `error`.
export async function enableWakeNotifications(pubKey) {
  if (!isWakeBrowserSupported()) {
    return { ok: false, error: "Push notifications aren't supported in this browser." }
  }
  if (Notification.permission === 'denied') {
    return { ok: false, error: 'Notifications are blocked for this site.' }
  }
  const keyInfo = await getWakeKeyInfo()
  if (!keyInfo.available || !keyInfo.publicKey) {
    return { ok: false, error: 'Wake is not configured on this node.' }
  }
  try {
    if (Notification.permission === 'default') {
      const perm = await Notification.requestPermission()
      if (perm !== 'granted') {
        return { ok: false, error: 'Notification permission was not granted.' }
      }
    }
    const subscription = await ensurePushSubscription(keyInfo.publicKey)
    await wakeApi.subscribe(pubKey, subscription.toJSON())
    useWake.getState().setEnabled(pubKey, true)
    await syncWakeState()
    return { ok: true, error: null }
  } catch (err) {
    return { ok: false, error: err instanceof ApiError ? err.message : 'Could not enable notifications.' }
  }
}

// disableWakeNotifications(pubKey) — unregisters this feed's server-side
// subscription (best-effort — a failure still turns the toggle off locally,
// matching kerf_pub.wake's "best-effort, never blocks" posture) and forgets
// the local toggle. If no other follow still has Wake enabled, also tears
// down the browser-level push subscription so there's no dangling
// registration with the push service.
export async function disableWakeNotifications(pubKey) {
  useWake.getState().setEnabled(pubKey, false)
  let error = null
  try {
    if (isWakeBrowserSupported()) {
      const registration = await navigator.serviceWorker.getRegistration()
      const existing = registration ? await registration.pushManager.getSubscription() : null
      if (existing) {
        try {
          await wakeApi.unsubscribe(pubKey, existing.endpoint)
        } catch (err) {
          error = err instanceof ApiError ? err.message : 'Could not reach this feed to unsubscribe.'
        }
        if (useWake.getState().enabledPubs.length === 0) {
          await existing.unsubscribe()
        }
      }
    }
  } finally {
    await syncWakeState()
  }
  return { ok: !error, error }
}

// onWakeMessage(callback) — the service worker postMessages every open
// window client on each `push` event (public/sw.js's notifyOpenClients).
// Returns an unsubscribe function.
export function onWakeMessage(callback) {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return () => {}
  const handler = (event) => {
    if (event.data && event.data.type === 'kerf-wake') callback()
  }
  navigator.serviceWorker.addEventListener('message', handler)
  return () => navigator.serviceWorker.removeEventListener('message', handler)
}

// syncWakeStateOnChange() — refreshes the service worker's Cache Storage
// mirror (src/lib/wakeState.js). Call whenever the access token or the
// enabled-pubs set changes, so a stale session/toggle set never lingers.
export function syncWakeStateOnChange() {
  return syncWakeState()
}
