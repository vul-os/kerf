/**
 * airfoilPolarBridge.js
 *
 * Thin fetch wrapper for the airfoil aerodynamics endpoints:
 *   POST /api/aero/airfoil/coords
 *   POST /api/aero/airfoil/polar
 *
 * No auth token is required — these are pure-compute endpoints.
 */

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

/**
 * Fetch (x, y) coordinates for a named airfoil.
 *
 * @param {string} airfoil - e.g. "naca0012", "e387", "clarky"
 * @returns {Promise<{airfoil: string, x: number[], y: number[], n_points: number}>}
 */
export async function fetchAirfoilCoords(airfoil) {
  const res = await fetch(`${API_URL}/api/aero/airfoil/coords`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ airfoil }),
  })
  if (!res.ok) {
    const text = await res.text()
    let msg = text
    try { msg = JSON.parse(text).detail || text } catch { /* ignore */ }
    throw new AirfoilApiError(res.status, msg)
  }
  return res.json()
}

/**
 * Compute a polar sweep for a named airfoil.
 *
 * @param {string} airfoil - e.g. "naca0012"
 * @param {[number, number, number]} alphaRange - [start_deg, end_deg, step_deg]
 * @returns {Promise<{airfoil: string, alpha: number[], CL: number[], CD: number[]}>}
 */
export async function fetchAirfoilPolar(airfoil, alphaRange) {
  if (!Array.isArray(alphaRange) || alphaRange.length !== 3) {
    throw new TypeError('alphaRange must be an array of [start, end, step]')
  }
  const res = await fetch(`${API_URL}/api/aero/airfoil/polar`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ airfoil, alpha_range: alphaRange }),
  })
  if (!res.ok) {
    const text = await res.text()
    let msg = text
    try { msg = JSON.parse(text).detail || text } catch { /* ignore */ }
    throw new AirfoilApiError(res.status, msg)
  }
  return res.json()
}

export class AirfoilApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}
