/**
 * orbitBridge.ts — Fetch wrapper for POST /aero/orbit/propagate.
 *
 * Sends classical orbital elements + propagation parameters to the backend
 * and returns the trajectory point array (IJK frame, km).
 *
 * Usage
 * -----
 *   import { propagateOrbit } from './orbitBridge.js'
 *
 *   const result = await propagateOrbit({
 *     a: 6778.137,       // km  semi-major axis
 *     e: 0.0,            // eccentricity
 *     i: 0.8976,         // rad inclination
 *     Omega: 0.0,        // rad RAAN
 *     omega: 0.0,        // rad argument of perigee
 *     nu0: 0.0,          // rad initial true anomaly
 *     duration_s: 5544,  // seconds
 *     n_steps: 200,      // sample count
 *   })
 *
 *   // result.ok === true
 *   // result.trajectory === [{x, y, z}, ...]  (km, IJK/ECI)
 *
 * Error handling
 * --------------
 * On HTTP error the function throws an Error with the status code and body.
 * On network failure the underlying fetch rejection propagates.
 */

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

/** Orbital elements + propagation settings for {@link propagateOrbit}. */
export interface OrbitPropagateParams {
  /** Semi-major axis (km), > 0. */
  a: number
  /** Eccentricity, [0, 1). */
  e: number
  /** Inclination (rad). */
  i: number
  /** RAAN Ω (rad). */
  Omega: number
  /** Argument of perigee ω (rad). */
  omega: number
  /** Initial true anomaly ν₀ (rad). */
  nu0: number
  /** Propagation duration (s), > 0. */
  duration_s: number
  /** Number of trajectory points (2–10000). Defaults to 200. */
  n_steps?: number
}

/** A single trajectory sample (km, IJK/ECI frame). */
export interface OrbitTrajectoryPoint {
  x: number
  y: number
  z: number
}

/** Response body for POST /aero/orbit/propagate. */
export interface OrbitPropagateResult {
  ok: boolean
  n_steps: number
  duration_s: number
  a_km: number
  e: number
  trajectory: OrbitTrajectoryPoint[]
}

/**
 * Propagate a Keplerian orbit.
 *
 * @param params - Orbital elements + propagation settings.
 * @param accessToken - Optional Bearer token for authenticated requests.
 * @throws {Error} On HTTP error (4xx / 5xx) or network failure.
 */
export async function propagateOrbit(
  params: OrbitPropagateParams,
  accessToken: string | null = null,
): Promise<OrbitPropagateResult> {
  const {
    a,
    e,
    i,
    Omega,
    omega,
    nu0,
    duration_s,
    n_steps = 200,
  } = params

  const headers: Record<string, string> = { 'content-type': 'application/json' }
  if (accessToken) {
    headers.authorization = `Bearer ${accessToken}`
  }

  const body = JSON.stringify({ a, e, i, Omega, omega, nu0, duration_s, n_steps })

  const resp = await fetch(`${API_URL}/api/aero/orbit/propagate`, {
    method: 'POST',
    headers,
    body,
  })

  if (!resp.ok) {
    let detail: string = resp.statusText
    try {
      const errJson = await resp.json()
      detail = errJson.detail ?? JSON.stringify(errJson)
    } catch {
      // keep statusText
    }
    throw new Error(`propagateOrbit: HTTP ${resp.status} — ${detail}`)
  }

  return resp.json()
}

/**
 * Compute the Keplerian orbital period (seconds) for a given semi-major axis.
 *
 * T = 2π √(a³ / μ)
 *
 * @param a_km - Semi-major axis (km).
 * @param mu - Gravitational parameter (km³/s²). Defaults to Earth's.
 * @returns Orbital period in seconds.
 */
export function orbitalPeriod(a_km: number, mu = 398_600.4418): number {
  return 2 * Math.PI * Math.sqrt(a_km ** 3 / mu)
}
