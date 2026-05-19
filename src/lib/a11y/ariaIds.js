/**
 * ariaIds.js — Unique, stable ID generator for ARIA relationships.
 *
 * ARIA attributes like `aria-labelledby`, `aria-describedby`, `aria-controls`,
 * and `aria-owns` require element IDs that:
 *   1. Are unique in the document at any given time.
 *   2. Are stable during a component's lifetime (not regenerated on re-render).
 *   3. Don't collide across multiple mounted instances of the same component.
 *   4. Are human-readable for debugging.
 *
 * This module provides:
 *   - `generateAriaId(prefix?)` — a monotonically-incrementing ID string.
 *   - `createAriaIdGroup(namespace)` — returns a bound factory that namespaces
 *     IDs under a fixed prefix (convenient for multi-part widgets).
 *   - `resetAriaIdCounter()` — test-only; resets the global counter so
 *     snapshot tests are deterministic.
 *
 * IDs have the shape:  kerf-<prefix>-<n>
 *   e.g.  kerf-dialog-1 / kerf-dialog-2 / kerf-tooltip-3
 *
 * Usage
 * ─────
 *   import { generateAriaId } from '@/lib/a11y/ariaIds'
 *
 *   // In a React component (call at module/class level, or in useMemo/useRef):
 *   const labelId = useMemo(() => generateAriaId('label'), [])
 *   return <div aria-labelledby={labelId}><span id={labelId}>…</span></div>
 *
 *   // Group (all IDs share the 'dialog' prefix):
 *   const ids = createAriaIdGroup('dialog')
 *   const titleId = ids('title')   // 'kerf-dialog-title-4'
 *   const bodyId  = ids('body')    // 'kerf-dialog-body-5'
 */

let _counter = 0

/**
 * Generate a unique ARIA-safe ID string.
 *
 * @param {string} [prefix='aria'] — human-readable label segment
 * @returns {string}   e.g. 'kerf-dialog-1'
 */
export function generateAriaId(prefix = 'aria') {
  _counter += 1
  return `kerf-${prefix}-${_counter}`
}

/**
 * Create a bound factory that prefixes all IDs with `namespace`.
 *
 * @param {string} namespace
 * @returns {(suffix: string) => string}
 *
 * @example
 *   const ids = createAriaIdGroup('combo')
 *   ids('input')   // 'kerf-combo-input-7'
 *   ids('listbox') // 'kerf-combo-listbox-8'
 */
export function createAriaIdGroup(namespace) {
  return function (suffix = '') {
    const key = suffix ? `${namespace}-${suffix}` : namespace
    return generateAriaId(key)
  }
}

/**
 * Reset the internal counter.
 * FOR TESTS ONLY — calling this in production will cause ID collisions.
 */
export function resetAriaIdCounter() {
  _counter = 0
}

/**
 * Return the current counter value without incrementing it.
 * FOR TESTS ONLY — useful for asserting that IDs are sequential.
 */
export function peekAriaIdCounter() {
  return _counter
}
