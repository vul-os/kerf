/**
 * usePrefersReducedMotion — React hook that reads the OS/browser
 * `prefers-reduced-motion: reduce` media feature and subscribes to changes.
 *
 * Returns `true` when the user has requested reduced motion, `false` otherwise.
 *
 * Usage
 * ─────
 *   const reduced = usePrefersReducedMotion()
 *   // disabled   → full animation
 *   // true       → no entrance fades / slide-ins / transform tweens
 *
 * The hook intentionally falls back to `false` in environments where
 * `window.matchMedia` is unavailable (SSR, unit tests without jsdom shims).
 */

import { useState, useEffect } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'

/**
 * Read `prefers-reduced-motion` once — useful outside React (e.g. plain JS).
 *
 * @returns {boolean}
 */
export function prefersReducedMotion() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }
  return window.matchMedia(QUERY).matches
}

/**
 * React hook: subscribes to `prefers-reduced-motion` changes and re-renders
 * on toggle.
 *
 * @returns {boolean} `true` when reduced motion is requested.
 */
export default function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => prefersReducedMotion())

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return
    }
    const mql = window.matchMedia(QUERY)
    const handler = (e) => setReduced(e.matches)

    // Modern API — addEventListener is preferred over addListener (deprecated).
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', handler)
      return () => mql.removeEventListener('change', handler)
    }
    // Fallback for older Safari / Firefox.
    mql.addListener(handler)
    return () => mql.removeListener(handler)
  }, [])

  return reduced
}
