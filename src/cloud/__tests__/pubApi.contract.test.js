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
      calls.push({ url, ...opts })
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

  it('pin: POST /api/pub/pin/:announce_id', async () => {
    await pub.pin('ann-1')
    expect(calls[0].url).toBe('/api/pub/pin/ann-1')
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
