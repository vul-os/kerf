// useNodeConfig.test.ts — the /api/config consumer.
//
// This file used to be almost entirely about OAuth availability: whether the
// login screen should draw a Google button, a GitHub button, and whether a
// client secret could ever leak into the payload. There is no federated
// sign-in any more — a node has one password, set on first load — so all that
// is gone and what remains is the one field that still varies per node.
//
// Strategy:
//   - Mock global.fetch to return a controlled JSON payload.
//   - Import the store module fresh per test via vi.resetModules() so the
//     singleton state doesn't bleed between cases.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

async function freshStore() {
  vi.resetModules()
  return await import('../lib/useNodeConfig.js')
}

function mockConfigFetch(payload: unknown, { status = 200 } = {}) {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  })
}

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  vi.restoreAllMocks()
  delete (globalThis as { fetch?: unknown }).fetch
})

describe('/api/config', () => {
  it('reads local_mode from the response', async () => {
    mockConfigFetch({ local_mode: false })
    const { getCloudConfig } = await freshStore()
    await getCloudConfig().fetch()
    expect(getCloudConfig().localMode).toBe(false)
    expect(getCloudConfig().ready).toBe(true)
  })

  it('assumes a self-hosted node when an older binary omits the field', async () => {
    // Defaulting the other way would send a self-hoster to a sign-in screen
    // for accounts their node does not have.
    mockConfigFetch({})
    const { getCloudConfig } = await freshStore()
    await getCloudConfig().fetch()
    expect(getCloudConfig().localMode).toBe(true)
  })

  it('falls back to defaults when the request fails', async () => {
    // A misconfigured proxy should leave the app usable, not stuck.
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('network'))
    const { getCloudConfig } = await freshStore()
    await getCloudConfig().fetch()
    expect(getCloudConfig().localMode).toBe(true)
    expect(getCloudConfig().ready).toBe(true)
  })

  it('falls back to defaults on a non-2xx response', async () => {
    mockConfigFetch({ local_mode: false }, { status: 503 })
    const { getCloudConfig } = await freshStore()
    await getCloudConfig().fetch()
    expect(getCloudConfig().localMode).toBe(true)
    expect(getCloudConfig().ready).toBe(true)
  })

  it('fetches once, however many callers ask', async () => {
    mockConfigFetch({ local_mode: true })
    const { getCloudConfig } = await freshStore()
    await Promise.all([
      getCloudConfig().fetch(),
      getCloudConfig().fetch(),
      getCloudConfig().fetch(),
    ])
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
  })
})
