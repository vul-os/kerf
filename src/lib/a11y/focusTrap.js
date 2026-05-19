/**
 * focusTrap.js — Lightweight focus trap for modals, dialogs, and drawers.
 *
 * Focus trapping is a WCAG 2.1 requirement (SC 2.1.2 "No Keyboard Trap"
 * combined with the APG modal dialog pattern). When a modal is open, Tab and
 * Shift+Tab must cycle only within the visible modal container; focus must not
 * escape to the dimmed background.
 *
 * Public API
 * ──────────
 *   createFocusTrap(container, options?) → { activate, deactivate, update }
 *     - container: HTMLElement (the element that should trap focus)
 *     - options.initialFocus: HTMLElement | () => HTMLElement | false
 *         Where to focus on activate(). Defaults to the first focusable child.
 *         Pass `false` to suppress the initial focus move.
 *     - options.returnFocus: HTMLElement | () => HTMLElement | true (default)
 *         Where to return focus on deactivate(). Defaults to the element that
 *         was focused immediately before activate() was called.
 *     - options.escapeDeactivates: boolean (default true)
 *         Whether pressing Escape calls deactivate().
 *     - options.onDeactivate: () => void
 *         Called synchronously inside deactivate(); useful for closing the
 *         owning dialog so React state stays in sync.
 *     - options.allowOutsideClick: boolean (default false)
 *         When true, clicks outside the container do NOT deactivate the trap
 *         (caller is responsible for dismissal). When false (default), outside
 *         clicks call deactivate().
 *
 *   activate()   — start trapping; stores current active element as return target
 *   deactivate() — stop trapping; optionally return focus to stored element
 *   update()     — re-read focusable children (call after DOM mutations)
 *
 * Focusable selector
 * ──────────────────
 * Follows the same selector used by popular a11y libs. Filters out:
 *   - elements with tabIndex < 0 (programmatic-only)
 *   - visually hidden / display:none / visibility:hidden
 *   - disabled form controls
 *   - elements inside an inert subtree
 */

// Tabbable elements in document order (doesn't include tabindex < 0).
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
  'details > summary',
  'audio[controls]',
  'video[controls]',
  '[contenteditable]:not([contenteditable="false"])',
].join(',')

/**
 * Return all focusable descendants of `container`, in DOM order, filtering out
 * hidden / inert nodes.
 *
 * @param {HTMLElement} container
 * @returns {HTMLElement[]}
 */
export function getFocusableChildren(container) {
  if (!container) return []
  const candidates = Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR))
  return candidates.filter((el) => {
    if (el.offsetParent === null && el.tagName !== 'BODY') return false // hidden via display:none
    if (typeof window !== 'undefined') {
      const style = window.getComputedStyle(el)
      if (style.visibility === 'hidden') return false
    }
    if (el.closest('[inert]')) return false
    return true
  })
}

/**
 * Create a focus trap bound to `container`.
 *
 * @param {HTMLElement} container
 * @param {object} [options]
 * @returns {{ activate: () => void, deactivate: () => void, update: () => void }}
 */
export function createFocusTrap(container, options = {}) {
  const {
    initialFocus,
    returnFocus = true,
    escapeDeactivates = true,
    onDeactivate,
    allowOutsideClick = false,
  } = options

  let active = false
  let focusableChildren = []
  let savedFocus = null

  function update() {
    focusableChildren = getFocusableChildren(container)
  }

  function isHTMLElement(val) {
    if (typeof HTMLElement !== 'undefined') return val instanceof HTMLElement
    // In environments without HTMLElement (Node/test), duck-type as an object with focus()
    return val !== null && typeof val === 'object' && typeof val.focus === 'function'
  }

  function getInitialFocusEl() {
    if (initialFocus === false) return null
    if (typeof initialFocus === 'function') return initialFocus()
    if (isHTMLElement(initialFocus)) return initialFocus
    return focusableChildren[0] ?? null
  }

  function getReturnFocusEl() {
    if (returnFocus === false) return null
    if (typeof returnFocus === 'function') return returnFocus()
    if (isHTMLElement(returnFocus)) return returnFocus
    return savedFocus
  }

  function onKeyDown(e) {
    if (!active) return

    if (e.key === 'Escape' && escapeDeactivates) {
      e.preventDefault()
      deactivate()
      return
    }

    if (e.key !== 'Tab') return

    const tabbable = getFocusableChildren(container)
    if (tabbable.length === 0) {
      e.preventDefault()
      return
    }

    const first = tabbable[0]
    const last = tabbable[tabbable.length - 1]
    const focused = document.activeElement

    if (e.shiftKey) {
      // Shift+Tab: if at or before first, wrap to last
      if (focused === first || !container.contains(focused)) {
        e.preventDefault()
        last.focus()
      }
    } else {
      // Tab: if at or after last, wrap to first
      if (focused === last || !container.contains(focused)) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  function onPointerDown(e) {
    if (!active || allowOutsideClick) return
    if (!container.contains(e.target)) {
      e.preventDefault()
      deactivate()
    }
  }

  function activate() {
    if (active) return
    active = true
    savedFocus = document.activeElement

    update()

    document.addEventListener('keydown', onKeyDown, true)
    document.addEventListener('pointerdown', onPointerDown, true)

    // Move focus into the container on the next tick so the container is
    // fully painted (important when it's just been appended to the DOM).
    const target = getInitialFocusEl()
    if (target) {
      // Use setTimeout 0 so we don't clash with any React synthetic focus events.
      setTimeout(() => {
        if (active) target.focus()
      }, 0)
    }
  }

  function deactivate() {
    if (!active) return
    active = false

    document.removeEventListener('keydown', onKeyDown, true)
    document.removeEventListener('pointerdown', onPointerDown, true)

    onDeactivate?.()

    const returnEl = getReturnFocusEl()
    if (returnEl && typeof returnEl.focus === 'function') {
      returnEl.focus()
    }
  }

  return { activate, deactivate, update }
}

/**
 * useFocusTrap — React hook that manages a FocusTrap tied to a ref.
 *
 * @example
 *   const { ref, activate, deactivate } = useFocusTrap({ escapeDeactivates: true })
 *   // mount <div ref={ref}> … </div>
 *   // call activate() when modal opens, deactivate() when it closes
 *
 * Note: This hook is intentionally decoupled from React's import so the util
 * file itself has no React dependency and is testable in pure Node/jsdom.
 * Import `useFocusTrap` from a separate React-aware wrapper in practice.
 */
export { createFocusTrap as default }
