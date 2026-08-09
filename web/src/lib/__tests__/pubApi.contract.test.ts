// pubApi.contract.test.js — verifies src/lib/pubApi.js's `pub` client hits
// the exact /api/pub/* contract this frontend wave was coded against
// (backend built in parallel, per the wave-2 task brief). Pure fetch-mock
// tests, no React needed.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { pub, wake } from '../pubApi.js'

// The fetch mock below only needs the {ok, status, json} shape `request()`
// in ../pubApi.ts actually reads, not the full Response interface — cast at
// the assignment rather than fleshing out every Response member for a
// test-only stand-in.
type CallRecord = { url: string; [key: string]: unknown }

describe('pub API client — matches the /api/pub contract', () => {
  let calls: CallRecord[]
  beforeEach(() => {
    calls = []
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL, opts?: RequestInit) => {
      // A developer .env can set VITE_API_URL, which api.js prefixes onto
      // every request; the contract under test is the path, so strip any
      // origin before recording.
      calls.push({ url: String(url).replace(/^https?:\/\/[^/]+/, ''), ...opts })
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
      }
    }) as unknown as typeof fetch
  })
  afterEach(() => {
    delete globalThis.fetch
  })

  it('getIdentity: GET /api/pub/identity', async () => {
    await pub.getIdentity()
    expect(calls[0].url).toBe('/api/pub/identity')
    expect(calls[0].method ?? 'GET').toBe('GET')
  })

  it('createIdentity: POST /api/pub/identity', async () => {
    await pub.createIdentity()
    expect(calls[0].url).toBe('/api/pub/identity')
    expect(calls[0].method).toBe('POST')
  })

  it('listFollows: GET /api/pub/follows', async () => {
    await pub.listFollows()
    expect(calls[0].url).toBe('/api/pub/follows')
  })

  it('addFollow: POST /api/pub/follows {pub,label,gateway_url}', async () => {
    await pub.addFollow({ pub: 'ed25519:abc', label: 'Kerf', gatewayUrl: 'https://vulos.org/projects/kerf' })
    expect(calls[0].url).toBe('/api/pub/follows')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body as string)).toEqual({ pub: 'ed25519:abc', label: 'Kerf', gateway_url: 'https://vulos.org/projects/kerf' })
  })

  it('removeFollow: DELETE /api/pub/follows/:pub', async () => {
    await pub.removeFollow('ed25519:abc')
    expect(calls[0].url).toBe('/api/pub/follows/ed25519%3Aabc')
    expect(calls[0].method).toBe('DELETE')
  })

  it('listWorkshop: GET /api/pub/workshop', async () => {
    await pub.listWorkshop()
    expect(calls[0].url).toBe('/api/pub/workshop')
  })

  it('publish: POST /api/pub/publish {project_id, metadata}', async () => {
    await pub.publish({
      projectId: 'proj-1',
      metadata: { name: 'Bracket', description: '', artifact_kind: 'part', license: 'MIT', units: { length_unit: 'mm' }, tags: [] },
    })
    expect(calls[0].url).toBe('/api/pub/publish')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body as string)).toEqual({
      project_id: 'proj-1',
      metadata: { name: 'Bracket', description: '', artifact_kind: 'part', license: 'MIT', units: { length_unit: 'mm' }, tags: [] },
    })
  })

  it('publish: assembly kind includes a children array {ref_kind, manifest_root|announce_id, quantity}', async () => {
    await pub.publish({
      projectId: 'proj-1',
      metadata: { name: 'Gearbox', description: '', artifact_kind: 'assembly', license: 'MIT', units: { length_unit: 'mm' }, tags: [] },
      children: [
        { ref_kind: 'track', announce_id: 'ann-child-1', quantity: 2 },
        { ref_kind: 'pin', manifest_root: 'manifest-root-1', quantity: 1 },
      ],
    })
    expect(calls[0].url).toBe('/api/pub/publish')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body as string).children).toEqual([
      { ref_kind: 'track', announce_id: 'ann-child-1', quantity: 2 },
      { ref_kind: 'pin', manifest_root: 'manifest-root-1', quantity: 1 },
    ])
  })

  it('publish: omits `children` entirely for non-assembly publishes', async () => {
    await pub.publish({
      projectId: 'proj-1',
      metadata: { name: 'Bracket', description: '', artifact_kind: 'part', license: 'MIT', units: { length_unit: 'mm' }, tags: [] },
    })
    expect(JSON.parse(calls[0].body as string)).not.toHaveProperty('children')
  })

  it('assemblyCandidates: GET /api/pub/assembly-candidates/:project_id', async () => {
    await pub.assemblyCandidates('proj-1')
    expect(calls[0].url).toBe('/api/pub/assembly-candidates/proj-1')
    expect(calls[0].method ?? 'GET').toBe('GET')
  })

  it('bom: GET /api/pub/bom/:announce_id', async () => {
    await pub.bom('ann-1')
    expect(calls[0].url).toBe('/api/pub/bom/ann-1')
    expect(calls[0].method ?? 'GET').toBe('GET')
  })

  it('pin: POST /api/pub/pin/:announce_id', async () => {
    await pub.pin('ann-1')
    expect(calls[0].url).toBe('/api/pub/pin/ann-1')
    expect(calls[0].method).toBe('POST')
  })

  it('hydratePin: POST /api/pub/pin/:announce_id/hydrate', async () => {
    await pub.hydratePin('ann-1')
    expect(calls[0].url).toBe('/api/pub/pin/ann-1/hydrate')
    expect(calls[0].method).toBe('POST')
  })

  it('unpin: DELETE /api/pub/pin/:announce_id', async () => {
    await pub.unpin('ann-1')
    expect(calls[0].url).toBe('/api/pub/pin/ann-1')
    expect(calls[0].method).toBe('DELETE')
  })

  it('has no leftover account-based workshop client (likes/forks/slugs)', async () => {
    // Cast: this test's whole point is asserting these properties are
    // *absent* from the real module namespace, so the un-narrowed cast
    // isn't hiding a real shape — it's what lets us ask the question at all.
    const api = (await import('../pubApi.js')) as unknown as Record<string, unknown>
    expect(api.workshop).toBeUndefined()
    expect(api.githubOAuth).toBeUndefined()
  })
})

describe('wake API client — matches the anonymous .well-known/dmtap-pub/* wake contract', () => {
  let calls: CallRecord[]
  beforeEach(() => {
    calls = []
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL, opts?: RequestInit) => {
      calls.push({ url: String(url).replace(/^https?:\/\/[^/]+/, ''), ...opts })
      return { ok: true, status: 200, json: async () => ({ public_key: 'fake-key' }) }
    }) as unknown as typeof fetch
  })
  afterEach(() => {
    delete globalThis.fetch
  })

  it('getKey: GET /.well-known/dmtap-pub/wake-key', async () => {
    const res = await wake.getKey()
    expect(calls[0].url).toBe('/.well-known/dmtap-pub/wake-key')
    expect(calls[0].method ?? 'GET').toBe('GET')
    expect(res).toEqual({ public_key: 'fake-key' })
  })

  it('subscribe: POST /.well-known/dmtap-pub/feed/:pub/subscribe {endpoint, keys}', async () => {
    await wake.subscribe('ed25519:abc', {
      endpoint: 'https://push.example.net/ep/1',
      keys: { p256dh: 'p256dh-value', auth: 'auth-value' },
    })
    expect(calls[0].url).toBe('/.well-known/dmtap-pub/feed/ed25519%3Aabc/subscribe')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body as string)).toEqual({
      endpoint: 'https://push.example.net/ep/1',
      keys: { p256dh: 'p256dh-value', auth: 'auth-value' },
    })
  })

  it('unsubscribe: DELETE /.well-known/dmtap-pub/feed/:pub/subscribe {endpoint}', async () => {
    await wake.unsubscribe('ed25519:abc', 'https://push.example.net/ep/1')
    expect(calls[0].url).toBe('/.well-known/dmtap-pub/feed/ed25519%3Aabc/subscribe')
    expect(calls[0].method).toBe('DELETE')
    expect(JSON.parse(calls[0].body as string)).toEqual({ endpoint: 'https://push.example.net/ep/1' })
  })
})
