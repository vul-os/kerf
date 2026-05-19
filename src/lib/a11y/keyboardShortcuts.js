/**
 * keyboardShortcuts.js — Global keyboard shortcut registry.
 *
 * Provides a single keydown listener on `document` that dispatches to
 * registered handlers. Key design decisions:
 *
 *   1. RESPECTS INPUT FOCUS — shortcuts do NOT fire when the user is typing
 *      in an <input>, <textarea>, <select>, or a [contenteditable] element.
 *      This prevents Cmd+K from triggering the command palette when the user
 *      is typing "ok" in a text field.
 *
 *   2. MODIFIER-AWARE — supports `meta` (Cmd on Mac, Win key on Windows),
 *      `ctrl`, `alt`/`option`, and `shift` modifiers. The special modifier
 *      `mod` maps to `meta` on macOS and `ctrl` on all other platforms
 *      (mirrors the CodeMirror/Tiptap convention).
 *
 *   3. PRIORITY ORDERING — handlers registered with higher `priority` (number,
 *      default 0) fire first. Within the same priority, LIFO (last registered
 *      fires first) so components can override parent shortcuts.
 *
 *   4. PROPAGATION CONTROL — a handler returning `true` (or the string `'stop'`)
 *      stops further handlers in the chain (but does NOT call
 *      e.preventDefault() unless the handler calls it explicitly).
 *
 *   5. SINGLE LISTENER — all shortcuts share one listener, avoiding the
 *      O(N²) addEventListener cost of per-shortcut subscriptions.
 *
 * Public API
 * ──────────
 *   registerShortcut(descriptor, handler, options?) → unregister: () => void
 *     - descriptor: string  e.g. 'mod+k', 'shift+?', 'ctrl+alt+t'
 *     - handler: (event: KeyboardEvent) => boolean | void
 *         Return `true` to stop subsequent handlers (like stopPropagation for
 *         the shortcut chain). Don't return anything (or return void/false/null)
 *         to let the chain continue.
 *     - options.priority: number (default 0) — higher fires first
 *     - options.allowInInput: boolean (default false) — fire even when an
 *         input/textarea/contenteditable has focus
 *     - options.preventDefault: boolean (default false) — auto-call
 *         e.preventDefault() before invoking the handler
 *
 *   unregisterAll() — remove every registered shortcut (useful in tests)
 *
 *   parseShortcut(descriptor) → ShortcutDescriptor — parse a shortcut string
 *     into a normalised object; exported for testing.
 *
 * Descriptor format
 * ─────────────────
 *   Parts separated by '+'. Order is normalised internally.
 *   Modifiers: mod, ctrl, alt, shift, meta
 *   Key: any single character OR a KeyboardEvent.key name (case-insensitive)
 *
 *   Examples:
 *     'mod+k'           → Cmd/Ctrl + K
 *     'mod+shift+p'     → Cmd/Ctrl + Shift + P
 *     'shift+?'         → Shift + ?
 *     'escape'          → Escape (no modifiers)
 *     'ctrl+alt+delete' → Ctrl + Alt + Delete
 */

const IS_MAC =
  typeof navigator !== 'undefined' &&
  /mac|iphone|ipad|ipod/i.test(navigator.platform || navigator.userAgent)

/**
 * Parse a shortcut descriptor string into a normalised object.
 *
 * @param {string} descriptor
 * @returns {{ mod: boolean, ctrl: boolean, alt: boolean, shift: boolean, meta: boolean, key: string }}
 */
export function parseShortcut(descriptor) {
  const parts = descriptor
    .toLowerCase()
    .split('+')
    .map((p) => p.trim())
    .filter(Boolean)

  const result = { mod: false, ctrl: false, alt: false, shift: false, meta: false, key: '' }
  const modifiers = new Set(['mod', 'ctrl', 'alt', 'shift', 'meta'])

  for (const part of parts) {
    if (modifiers.has(part)) {
      result[part] = true
    } else {
      // Last non-modifier part becomes the key
      result.key = part
    }
  }

  // Resolve 'mod' to the platform-appropriate modifier
  if (result.mod) {
    if (IS_MAC) {
      result.meta = true
    } else {
      result.ctrl = true
    }
    result.mod = false
  }

  return result
}

/**
 * Test whether a KeyboardEvent matches a parsed shortcut descriptor.
 *
 * @param {KeyboardEvent} event
 * @param {{ ctrl: boolean, alt: boolean, shift: boolean, meta: boolean, key: string }} parsed
 * @returns {boolean}
 */
export function matchesShortcut(event, parsed) {
  if (event.ctrlKey !== parsed.ctrl) return false
  if (event.altKey !== parsed.alt) return false
  if (event.shiftKey !== parsed.shift) return false
  if (event.metaKey !== parsed.meta) return false

  // Normalise the key: single characters are compared lowercase; named keys
  // (Tab, Escape, ArrowUp…) are compared case-insensitively.
  const eventKey = event.key.toLowerCase()
  const parsedKey = parsed.key.toLowerCase()
  return eventKey === parsedKey
}

/**
 * Return true if the currently-focused element is an interactive input
 * (typing target). Used to suppress shortcuts when the user is composing text.
 *
 * @returns {boolean}
 */
export function isFocusInInput() {
  if (typeof document === 'undefined') return false
  const el = document.activeElement
  if (!el) return false
  const tag = el.tagName.toUpperCase()
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (el.isContentEditable) return true
  // Monaco editor wraps everything in a div with role=textbox
  if (el.getAttribute('role') === 'textbox') return true
  return false
}

// ── Registry ──────────────────────────────────────────────────────────────────

let _handlers = []
let _listenerAttached = false

function ensureListener() {
  if (_listenerAttached) return
  if (typeof document === 'undefined') return
  _listenerAttached = true
  document.addEventListener('keydown', _dispatch, true)
}

function _dispatch(event) {
  // Sort by priority (descending) each time so insertions are reflected.
  const sorted = [..._handlers].sort((a, b) => (b.options.priority ?? 0) - (a.options.priority ?? 0))

  for (const entry of sorted) {
    const { parsed, handler, options } = entry

    if (!options.allowInInput && isFocusInInput()) continue

    if (!matchesShortcut(event, parsed)) continue

    if (options.preventDefault) event.preventDefault()

    const result = handler(event)
    if (result === true || result === 'stop') break
  }
}

/**
 * Register a global keyboard shortcut.
 *
 * @param {string} descriptor   e.g. 'mod+k'
 * @param {(e: KeyboardEvent) => boolean | void} handler
 * @param {{ priority?: number, allowInInput?: boolean, preventDefault?: boolean }} [options]
 * @returns {() => void}  call to unregister
 */
export function registerShortcut(descriptor, handler, options = {}) {
  const parsed = parseShortcut(descriptor)
  const entry = {
    descriptor,
    parsed,
    handler,
    options: {
      priority: options.priority ?? 0,
      allowInInput: options.allowInInput ?? false,
      preventDefault: options.preventDefault ?? false,
    },
  }

  _handlers.push(entry)
  ensureListener()

  return function unregister() {
    _handlers = _handlers.filter((h) => h !== entry)
  }
}

/**
 * Remove all registered shortcuts and detach the document listener.
 * Useful in test teardown to prevent cross-test contamination.
 */
export function unregisterAll() {
  _handlers = []
  if (_listenerAttached && typeof document !== 'undefined') {
    document.removeEventListener('keydown', _dispatch, true)
    _listenerAttached = false
  } else {
    _listenerAttached = false
  }
}

/**
 * Return a snapshot of currently registered shortcut descriptors (for debugging).
 *
 * @returns {string[]}
 */
export function listShortcuts() {
  return _handlers.map((h) => h.descriptor)
}
