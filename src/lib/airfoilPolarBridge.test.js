/**
 * airfoilPolarBridge.test.js
 *
 * Vitest unit tests for the airfoil polar bridge.  Uses vi.stubGlobal to
 * replace fetch so no real network calls are made.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { fetchAirfoilCoords, fetchAirfoilPolar, AirfoilApiError } from './airfoilPolarBridge.js'

// ---------------------------------------------------------------------------
// fetch mock helpers
// ---------------------------------------------------------------------------

function mockFetch(body, status = 200) {
  const response = {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------
// fetchAirfoilCoords
// ---------------------------------------------------------------------------

describe('fetchAirfoilCoords', () => {
  it('calls POST /api/aero/airfoil/coords with the airfoil name', async () => {
    const mockBody = { airfoil: 'naca0012', x: [1, 0], y: [0, 0], n_points: 2 }
    mockFetch(mockBody)

    const result = await fetchAirfoilCoords('naca0012')

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/aero/airfoil/coords'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ airfoil: 'naca0012' }),
      }),
    )
    expect(result.airfoil).toBe('naca0012')
    expect(result.x).toEqual([1, 0])
    expect(result.y).toEqual([0, 0])
    expect(result.n_points).toBe(2)
  })

  it('throws AirfoilApiError on non-OK response', async () => {
    mockFetch({ detail: 'Unknown airfoil' }, 422)

    await expect(fetchAirfoilCoords('xfoil99')).rejects.toBeInstanceOf(AirfoilApiError)
  })

  it('AirfoilApiError carries the HTTP status code', async () => {
    mockFetch({ detail: 'not found' }, 422)

    try {
      await fetchAirfoilCoords('bad')
      throw new Error('should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(AirfoilApiError)
      expect(err.status).toBe(422)
    }
  })
})

// ---------------------------------------------------------------------------
// fetchAirfoilPolar
// ---------------------------------------------------------------------------

describe('fetchAirfoilPolar', () => {
  const mockPolar = {
    airfoil: 'naca0012',
    alpha: [-10, -5, 0, 5, 10],
    CL: [-1.1, -0.55, 0.0, 0.55, 1.1],
    CD: [0.02, 0.01, 0.005, 0.01, 0.02],
  }

  it('calls POST /api/aero/airfoil/polar with correct body', async () => {
    mockFetch(mockPolar)

    await fetchAirfoilPolar('naca0012', [-10, 10, 5])

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/aero/airfoil/polar'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ airfoil: 'naca0012', alpha_range: [-10, 10, 5] }),
      }),
    )
  })

  it('returns alpha, CL, CD arrays', async () => {
    mockFetch(mockPolar)
    const result = await fetchAirfoilPolar('naca0012', [-10, 10, 5])
    expect(Array.isArray(result.alpha)).toBe(true)
    expect(Array.isArray(result.CL)).toBe(true)
    expect(Array.isArray(result.CD)).toBe(true)
    expect(result.CL.length).toBe(result.alpha.length)
  })

  it('throws TypeError if alphaRange is not an array of 3', async () => {
    mockFetch(mockPolar)
    await expect(fetchAirfoilPolar('naca0012', [-10, 10])).rejects.toBeInstanceOf(TypeError)
    await expect(fetchAirfoilPolar('naca0012', 'invalid')).rejects.toBeInstanceOf(TypeError)
  })

  it('throws AirfoilApiError on non-OK response', async () => {
    mockFetch({ detail: 'alpha_range step is zero' }, 422)
    await expect(fetchAirfoilPolar('naca0012', [0, 10, 0])).rejects.toBeInstanceOf(AirfoilApiError)
  })

  it('AirfoilApiError carries status code from server', async () => {
    mockFetch({ detail: 'server error' }, 500)

    try {
      await fetchAirfoilPolar('naca0012', [-5, 5, 1])
    } catch (err) {
      expect(err).toBeInstanceOf(AirfoilApiError)
      expect(err.status).toBe(500)
    }
  })
})
