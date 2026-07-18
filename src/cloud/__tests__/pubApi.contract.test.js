// pubApi.contract.test.js — verifies src/cloud/api.js's `pub` client hits
// the exact /api/pub/* contract this frontend wave was coded against
// (backend built in parallel, per the wave-2 task brief). Pure fetch-mock
// tests, no React needed.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { pub } from '../api.js'

describe('pub API client — matches the /api/pub contract', () => {
  let calls
  beforeEach(() => {
    calls = []
    global.fetch = vi.fn(async (url, opts) => {
      // A developer .env can set VITE_API_URL, which api.js prefixes onto
      // every request; the contract under test is the path, so strip any
      // origin before recording.
      calls.push({ url: String(url).replace(/^https?:\/\/[^/]+/, ''), ...opts })
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
      }
    })
  })
  afterEach(() => {
    delete global.fetch
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
    await pub.addFollow({ pub: 'ed25519:abc', label: 'Kerf', gatewayUrl: 'https://kerf.sh' })
    expect(calls[0].url).toBe('/api/pub/follows')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body)).toEqual({ pub: 'ed25519:abc', label: 'Kerf', gateway_url: 'https://kerf.sh' })
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
      metadata: { name: 'Bracket', description: '', artifact_kind: 'part', license: 'MIT', units: 'mm', tags: [] },
    })
    expect(calls[0].url).toBe('/api/pub/publish')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body)).toEqual({
      project_id: 'proj-1',
      metadata: { name: 'Bracket', description: '', artifact_kind: 'part', license: 'MIT', units: 'mm', tags: [] },
    })
  })

  it('publish: assembly kind includes a children array {ref_kind, manifest_root|announce_id, quantity}', async () => {
    await pub.publish({
      projectId: 'proj-1',
      metadata: { name: 'Gearbox', description: '', artifact_kind: 'assembly', license: 'MIT', units: 'mm', tags: [] },
      children: [
        { ref_kind: 'track', announce_id: 'ann-child-1', quantity: 2 },
        { ref_kind: 'pin', manifest_root: 'manifest-root-1', quantity: 1 },
      ],
    })
    expect(calls[0].url).toBe('/api/pub/publish')
    expect(calls[0].method).toBe('POST')
    expect(JSON.parse(calls[0].body).children).toEqual([
      { ref_kind: 'track', announce_id: 'ann-child-1', quantity: 2 },
      { ref_kind: 'pin', manifest_root: 'manifest-root-1', quantity: 1 },
    ])
  })

  it('publish: omits `children` entirely for non-assembly publishes', async () => {
    await pub.publish({
      projectId: 'proj-1',
      metadata: { name: 'Bracket', description: '', artifact_kind: 'part', license: 'MIT', units: 'mm', tags: [] },
    })
    expect(JSON.parse(calls[0].body)).not.toHaveProperty('children')
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
    const api = await import('../api.js')
    expect(api.workshop).toBeUndefined()
    expect(api.githubOAuth).toBeUndefined()
  })
})
