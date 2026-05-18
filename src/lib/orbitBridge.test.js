/**
 * orbitBridge.test.js — Vitest tests for orbitBridge.js
 *
 * All tests are pure data-layer / mock-fetch; no real HTTP calls are made.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { propagateOrbit, orbitalPeriod } from './orbitBridge.js'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const R_EARTH = 6_378.137  // km
const MU = 398_600.4418    // km³/s²

/** Build a valid LEO request body (400 km circular orbit). */
function leoParams(overrides = {}) {
  const a = R_EARTH + 400
  return {
    a,
    e: 0.0,
    i: Math.PI / 3,
    Omega: 0.0,
    omega: 0.0,
    nu0: 0.0,
    duration_s: 5544,
    n_steps: 50,
    ...overrides,
  }
}

/** Build a minimal valid API response. */
function mockResponse(n_steps = 50, duration_s = 5544) {
  const trajectory = Array.from({ length: n_steps }, (_, k) => ({
    x: (R_EARTH + 400) * Math.cos((2 * Math.PI * k) / n_steps),
    y: (R_EARTH + 400) * Math.sin((2 * Math.PI * k) / n_steps),
    z: 0,
  }))
  return {
    ok: true,
    n_steps,
    duration_s,
    a_km: R_EARTH + 400,
    e: 0.0,
    trajectory,
  }
}

// ---------------------------------------------------------------------------
// Mock fetch
// ---------------------------------------------------------------------------

let fetchMock

beforeEach(() => {
  fetchMock = vi.fn()
  global.fetch = fetchMock
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// orbitalPeriod (pure math, no fetch)
// ---------------------------------------------------------------------------

describe('orbitalPeriod', () => {
  it('returns ~5544 s for 400 km LEO', () => {
    const T = orbitalPeriod(R_EARTH + 400)
    // 92.4 min = 5544 s ± 60 s
    expect(T).toBeGreaterThan(5480)
    expect(T).toBeLessThan(5610)
  })

  it('is close to 92 minutes for 400 km LEO', () => {
    const T = orbitalPeriod(R_EARTH + 400)
    const minutes = T / 60
    expect(minutes).toBeGreaterThan(91)
    expect(minutes).toBeLessThan(93)
  })

  it('increases monotonically with altitude', () => {
    const T400 = orbitalPeriod(R_EARTH + 400)
    const T800 = orbitalPeriod(R_EARTH + 800)
    expect(T800).toBeGreaterThan(T400)
  })

  it('GEO (42 164 km) period is ~86 164 s (sidereal day)', () => {
    const T = orbitalPeriod(42_164)
    expect(Math.abs(T - 86_164)).toBeLessThan(60)
  })
})

// ---------------------------------------------------------------------------
// propagateOrbit — success path
// ---------------------------------------------------------------------------

describe('propagateOrbit success', () => {
  it('calls POST /api/aero/orbit/propagate', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse()),
    })

    await propagateOrbit(leoParams())

    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toMatch(/\/api\/aero\/orbit\/propagate$/)
    expect(opts.method).toBe('POST')
  })

  it('sends the correct orbital elements in the request body', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse()),
    })

    const params = leoParams({ nu0: 1.2, e: 0.05 })
    await propagateOrbit(params)

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.a).toBeCloseTo(R_EARTH + 400)
    expect(body.e).toBeCloseTo(0.05)
    expect(body.nu0).toBeCloseTo(1.2)
    expect(body.n_steps).toBe(50)
  })

  it('returns the parsed response JSON', async () => {
    const resp = mockResponse(100, 6000)
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(resp),
    })

    const result = await propagateOrbit(leoParams({ n_steps: 100, duration_s: 6000 }))
    expect(result.ok).toBe(true)
    expect(result.n_steps).toBe(100)
    expect(result.trajectory).toHaveLength(100)
  })

  it('attaches Authorization header when accessToken is provided', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse()),
    })

    await propagateOrbit(leoParams(), 'tok_test123')

    const headers = fetchMock.mock.calls[0][1].headers
    expect(headers.authorization).toBe('Bearer tok_test123')
  })

  it('omits Authorization header when no token provided', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse()),
    })

    await propagateOrbit(leoParams())

    const headers = fetchMock.mock.calls[0][1].headers
    expect(headers.authorization).toBeUndefined()
  })

  it('defaults n_steps to 200 when omitted', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse(200)),
    })

    const params = leoParams()
    delete params.n_steps
    await propagateOrbit(params)

    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.n_steps).toBe(200)
  })
})

// ---------------------------------------------------------------------------
// propagateOrbit — error handling
// ---------------------------------------------------------------------------

describe('propagateOrbit errors', () => {
  it('throws on HTTP 422 with detail in message', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 422,
      statusText: 'Unprocessable Entity',
      json: () => Promise.resolve({ detail: 'eccentricity must be in [0, 1)' }),
    })

    await expect(propagateOrbit(leoParams())).rejects.toThrow('422')
  })

  it('throws on HTTP 500', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: () => Promise.reject(new Error('no body')),
    })

    await expect(propagateOrbit(leoParams())).rejects.toThrow('500')
  })

  it('propagates network failure', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))

    await expect(propagateOrbit(leoParams())).rejects.toThrow('Failed to fetch')
  })
})

// ---------------------------------------------------------------------------
// Trajectory shape sanity check (using mocked data)
// ---------------------------------------------------------------------------

describe('trajectory shape', () => {
  it('each trajectory point has numeric x, y, z', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse(20)),
    })

    const result = await propagateOrbit(leoParams({ n_steps: 20 }))
    for (const pt of result.trajectory) {
      expect(typeof pt.x).toBe('number')
      expect(typeof pt.y).toBe('number')
      expect(typeof pt.z).toBe('number')
    }
  })

  it('mocked 400 km LEO points have radius ~6778 km', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse(20)),
    })

    const result = await propagateOrbit(leoParams({ n_steps: 20 }))
    const expected_r = R_EARTH + 400
    for (const pt of result.trajectory) {
      const r = Math.sqrt(pt.x ** 2 + pt.y ** 2 + pt.z ** 2)
      expect(Math.abs(r - expected_r)).toBeLessThan(1)
    }
  })
})
