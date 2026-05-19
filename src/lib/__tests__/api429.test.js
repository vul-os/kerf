// api429.test.js — 429 rate-limit handling in src/lib/api.js request().
//
// Strategy:
//   - Mock useAuth, ToastBus.toast, and global.fetch.
//   - Verify that a 429 response:
//       1. Triggers toast.error with the retry_after seconds.
//       2. Throws ApiError(429, "rate limit exceeded").
//       3. Does NOT retry (unlike 401).
//   - Verify 429 without retry_after in body shows a generic message.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Shared auth mock state
const authState = {
  accessToken: 'tok-A',
  refreshToken: 'r-A',
  setSession: vi.fn(),
  logout: vi.fn(),
}

vi.mock('../../store/auth.js', () => ({
  useAuth: { getState: () => authState },
}))

// Mock the ToastBus so we can capture toast.error calls.
const mockToastError = vi.fn()
vi.mock('../../components/ToastBus.jsx', () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: mockToastError,
    warning: vi.fn(),
  }),
}))

let api
let ApiError

beforeEach(async () => {
  vi.resetModules()
  authState.accessToken = 'tok-A'
  authState.refreshToken = 'r-A'
  authState.setSession = vi.fn()
  authState.logout = vi.fn()
  mockToastError.mockReset()
  globalThis.fetch = vi.fn()

  const mod = await import('../../lib/api.js')
  api = mod.api
  ApiError = mod.ApiError
})

afterEach(() => {
  vi.restoreAllMocks()
  delete globalThis.fetch
})

// Helper: build a 429 response stub
function make429Response({ retry_after = null } = {}) {
  const body = retry_after != null
    ? JSON.stringify({ detail: 'rate limit exceeded', retry_after })
    : JSON.stringify({ detail: 'rate limit exceeded' })
  return {
    ok: false,
    status: 429,
    statusText: 'Too Many Requests',
    text: async () => body,
    json: async () => JSON.parse(body),
  }
}

describe('request() — 429 handling', () => {
  it('throws ApiError(429) when server returns 429', async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce(make429Response({ retry_after: 42 }))

    await expect(api.me()).rejects.toMatchObject({
      status: 429,
      message: 'rate limit exceeded',
    })
  })

  it('fires toast.error with retry_after seconds', async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce(make429Response({ retry_after: 42 }))

    try { await api.me() } catch { /* expected */ }

    expect(mockToastError).toHaveBeenCalledOnce()
    const msg = mockToastError.mock.calls[0][0]
    expect(msg).toContain('42')
    expect(msg).toMatch(/too many requests/i)
  })

  it('fires toast.error with generic message when retry_after absent', async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce(make429Response())

    try { await api.me() } catch { /* expected */ }

    expect(mockToastError).toHaveBeenCalledOnce()
    const msg = mockToastError.mock.calls[0][0]
    expect(msg).toMatch(/too many requests/i)
  })

  it('does NOT retry on 429 (unlike 401)', async () => {
    const fetch429 = vi.fn().mockResolvedValue(make429Response({ retry_after: 10 }))
    globalThis.fetch = fetch429

    try { await api.me() } catch { /* expected */ }

    // fetch should only be called once — no automatic retry for 429
    expect(fetch429).toHaveBeenCalledTimes(1)
  })

  it('ApiError from 429 has status 429', async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce(make429Response({ retry_after: 5 }))

    let caught = null
    try { await api.me() } catch (e) { caught = e }

    expect(caught).not.toBeNull()
    expect(caught.status).toBe(429)
  })
})
