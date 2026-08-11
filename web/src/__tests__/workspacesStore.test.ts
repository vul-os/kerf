// workspacesStore.test.js — regression for the "workspace_id or
// workspace_slug required" root cause.
//
// Bug: loadAll() set `loaded:true` even when listWorkspaces() failed, and
// the loader effect only runs `if (!loaded && !loading)`. A single
// transient failure of the FIRST fetch (cold autoscaled machine / token
// race right after OAuth) permanently stranded the session with no
// workspace, so create-project sent no workspace_id and the API 400'd.
//
// Fix: retry with backoff; only mark `loaded` once we actually have
// data; never latch `loaded:true` on a bare failure.

import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../lib/api.js', () => ({
  api: { listWorkspaces: vi.fn() },
}))

import { api } from '../lib/api.js'
import { useWorkspaces } from '../store/workspaces.js'

const WS = { id: 'ws-1', slug: 'personal-abc', name: 'Personal' }

// vi.mock() above replaces api.listWorkspaces with a vi.fn() at runtime, but
// its static type is still the real api.js signature (owned by another
// slice) — cast to the mock surface for .mockReset()/.mockResolvedValueOnce().
const listWorkspaces = api.listWorkspaces as unknown as ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.useRealTimers()
  listWorkspaces.mockReset()
  try { localStorage.clear() } catch { /* no storage in this environment */ }
  useWorkspaces.setState({
    workspaces: [], currentSlug: null, loading: false, loaded: false, error: null,
  })
})

describe('useWorkspaces.loadAll resilience', () => {
  it('success: populates workspaces, marks loaded, picks current slug', async () => {
    listWorkspaces.mockResolvedValueOnce([WS])
    const arr = await useWorkspaces.getState().loadAll()
    expect(arr).toEqual([WS])
    const s = useWorkspaces.getState()
    expect(s.workspaces).toEqual([WS])
    expect(s.loaded).toBe(true)
    expect(s.loading).toBe(false)
    expect(s.currentSlug).toBe('personal-abc')
  })

  it('all retries fail: does NOT latch loaded:true (stays retryable)', async () => {
    vi.useFakeTimers()
    listWorkspaces.mockRejectedValue(new Error('cold start / 502'))
    const p = useWorkspaces.getState().loadAll()
    await vi.runAllTimersAsync()
    const arr = await p
    expect(arr).toEqual([])
    const s = useWorkspaces.getState()
    expect(s.loaded).toBe(false) // <-- the regression guard
    expect(s.loading).toBe(false)
    expect(s.error).toBeTruthy()
    expect(s.workspaces).toEqual([])
    // 1 initial + 4 backoff retries
    expect(listWorkspaces).toHaveBeenCalledTimes(5)
  })

  it('transient failure then success: eventually populates', async () => {
    vi.useFakeTimers()
    listWorkspaces
      .mockRejectedValueOnce(new Error('cold'))
      .mockRejectedValueOnce(new Error('cold'))
      .mockResolvedValueOnce([WS])
    const p = useWorkspaces.getState().loadAll()
    await vi.runAllTimersAsync()
    const arr = await p
    expect(arr).toEqual([WS])
    const s = useWorkspaces.getState()
    expect(s.loaded).toBe(true)
    expect(s.workspaces).toEqual([WS])
    expect(s.currentSlug).toBe('personal-abc')
  })
})
