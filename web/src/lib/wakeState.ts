// Page -> service-worker state handoff for Wake push (public/sw.js,
// docs/distributed-workshop.md's "Wake" section). A service worker woken
// purely to handle a `push` event runs in a fresh worker global scope with
// no access to the page's in-memory state or localStorage, so the page
// mirrors just enough into the Cache Storage API — a same-origin store both
// contexts can read — for the worker's best-effort targeted refresh: the API
// base URL, the current access token, and the list of followed pubs Wake is
// enabled for.
//
// Never load-bearing: kerf_pub.wake is explicitly "fire-and-forget,
// best-effort" (a wake is a latency optimization, never a delivery
// guarantee), and this mirror is one more best-effort layer on top of that
// — if it's stale, missing, or Cache Storage is unavailable, the worker just
// skips the background refresh and still shows the notification.

export const WAKE_CACHE_NAME = 'kerf-wake-state-v1'
export const WAKE_STATE_URL = '/__kerf-wake-state'

export async function writeWakeState({ apiUrl, accessToken, pubs }) {
  if (typeof caches === 'undefined') return
  try {
    const cache = await caches.open(WAKE_CACHE_NAME)
    await cache.put(
      WAKE_STATE_URL,
      new Response(JSON.stringify({ apiUrl: apiUrl || '', accessToken: accessToken || null, pubs: pubs || [] }), {
        headers: { 'content-type': 'application/json' },
      }),
    )
  } catch {
    // Private-browsing storage restrictions, quota pressure, etc. — degrade
    // to "notification only", never fatal.
  }
}
