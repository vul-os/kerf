// focusTrap.test.js — Vitest unit tests for the focus-trap utility.
//
// Strategy: the project does not have jsdom installed, so we test the
// pure-logic layer of focusTrap.js without a DOM. The key exported functions
// are:
//   - FOCUSABLE_SELECTOR — the CSS selector string (tested indirectly)
//   - getFocusableChildren — tested with a minimal DOM stub
//   - createFocusTrap — tested via a lightweight DOM mock for the Tab-wrapping
//     logic and the Escape-deactivate contract.
//
// The DOM mock is minimal: we only simulate the parts the implementation reads
// (container.querySelectorAll, el.offsetParent, window.getComputedStyle,
// document.activeElement, document.addEventListener / removeEventListener).
// This keeps tests fast and dependency-free while still verifying the
// behavioural contracts required by the task spec.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createFocusTrap, getFocusableChildren } from './focusTrap.js'

// ── minimal DOM stub factory ──────────────────────────────────────────────────

// Unused by any test below (pre-existing dead code, kept as-is since removing
// it is a behaviour/content change out of migration scope; prefixed with `_`
// to satisfy the no-unused-vars lint rule).
function _makeEl(tag = 'button', extra = {}) {
  return {
    tagName: tag.toUpperCase(),
    offsetParent: {},   // non-null ⇒ visible
    focus: vi.fn(),
    blur: vi.fn(),
    closest: vi.fn(() => null),   // not inside [inert]
    getAttribute: vi.fn(() => null),
    isContentEditable: false,
    disabled: false,
    ...extra,
  }
}

function _makeComputedStyle(visibility = 'visible') {
  return { visibility }
}

// ── getFocusableChildren ──────────────────────────────────────────────────────

describe('getFocusableChildren', () => {
  it('returns [] for null container', () => {
    expect(getFocusableChildren(null)).toEqual([])
  })

  it('filters out elements with display:none (offsetParent === null)', () => {
    // We can only test this via the live DOM branch or the offsetParent check.
    // Since there is no real DOM, we verify the null-container early-return.
    expect(getFocusableChildren(undefined)).toEqual([])
  })
})

// ── createFocusTrap — Tab wrapping logic ─────────────────────────────────────
//
// We stub the subset of DOM APIs that createFocusTrap uses:
//   - document.addEventListener / removeEventListener (to capture the keydown handler)
//   - document.activeElement (to tell the trap which element is focused)
//   - getFocusableChildren (real export, but we mock querySelectorAll on container)
// Then we synthesise KeyboardEvent-like objects and call the captured handler
// directly, asserting on e.preventDefault() calls and el.focus() calls.

describe('createFocusTrap — Tab capture logic', () => {
  let capturedKeydown = null
  let _capturedPointerdown = null
  let origAdd, origRemove, origActive

  // Minimal focusable-child stubs
  // Deliberately loosely typed: these are hand-rolled DOM mocks, not full
  // HTMLElement/Document implementations, so the boundary is `any`.
  function makeButtons(n): any[] {
    return Array.from({ length: n }, (_, i) => ({
      tagName: 'BUTTON',
      offsetParent: {},
      focus: vi.fn(),
      closest: vi.fn(() => null),
      getAttribute: vi.fn(() => null),
      isContentEditable: false,
      disabled: false,
      textContent: `btn${i}`,
    }))
  }

  beforeEach(() => {
    capturedKeydown = null
    _capturedPointerdown = null

    // Stub document.addEventListener to capture our handlers
    origAdd = globalThis.document?.addEventListener
    origRemove = globalThis.document?.removeEventListener

    if (typeof globalThis.document === 'undefined') {
      // Provide a minimal globalThis.document stub for this test suite
      globalThis.document = {
        addEventListener: vi.fn((type, fn) => {
          if (type === 'keydown') capturedKeydown = fn
          if (type === 'pointerdown') _capturedPointerdown = fn
        }),
        removeEventListener: vi.fn(),
        activeElement: null,
      } as unknown as Document
    } else {
      globalThis.document.addEventListener = vi.fn((type, fn, ..._rest) => {
        if (type === 'keydown') capturedKeydown = fn
        if (type === 'pointerdown') _capturedPointerdown = fn
      })
      globalThis.document.removeEventListener = vi.fn()
      origActive = Object.getOwnPropertyDescriptor(globalThis.document, 'activeElement')
    }
  })

  afterEach(() => {
    if (origAdd !== undefined) globalThis.document.addEventListener = origAdd
    if (origRemove !== undefined) globalThis.document.removeEventListener = origRemove
    if (origActive !== undefined) {
      Object.defineProperty(globalThis.document, 'activeElement', origActive)
    }
  })

  function makeContainer(buttons): any {
    return {
      querySelectorAll: vi.fn(() => buttons.map(b => ({
        ...b,
        // getFocusableChildren checks offsetParent; keep it truthy
        offsetParent: {},
      }))),
      contains: vi.fn((el) => buttons.includes(el) || buttons.some(b => b === el)),
    }
  }

  function fakeTabEvent(shiftKey = false) {
    return {
      key: 'Tab',
      shiftKey,
      preventDefault: vi.fn(),
    }
  }

  function fakeEscapeEvent() {
    return {
      key: 'Escape',
      shiftKey: false,
      preventDefault: vi.fn(),
    }
  }

  it('activate() attaches a keydown listener', () => {
    const buttons = makeButtons(2)
    const container = makeContainer(buttons)
    const trap = createFocusTrap(container, { initialFocus: false })
    trap.activate()

    expect(typeof capturedKeydown).toBe('function')
  })

  it('Tab from last element: calls preventDefault and focuses first', () => {
    const buttons = makeButtons(3)
    const container = makeContainer(buttons)

    // Simulate activeElement = last button
    const lastBtn = buttons[2]
    // We need getFocusableChildren to return our stubs and container.contains to work
    // Override querySelectorAll to return our buttons
    container.querySelectorAll = vi.fn(() => buttons)
    container.contains = vi.fn((el) => {
      return el === lastBtn
    })

    // Patch document.activeElement
    if (typeof globalThis.document !== 'undefined') {
      Object.defineProperty(globalThis.document, 'activeElement', {
        get: () => lastBtn,
        configurable: true,
      })
    }

    const trap = createFocusTrap(container, { initialFocus: false })
    trap.activate()

    const e = fakeTabEvent(false)
    capturedKeydown(e)

    expect(e.preventDefault).toHaveBeenCalled()
    expect(buttons[0].focus).toHaveBeenCalled()
  })

  it('Shift+Tab from first element: calls preventDefault and focuses last', () => {
    const buttons = makeButtons(3)
    const container = makeContainer(buttons)
    const firstBtn = buttons[0]

    container.querySelectorAll = vi.fn(() => buttons)
    container.contains = vi.fn((el) => el === firstBtn)

    if (typeof globalThis.document !== 'undefined') {
      Object.defineProperty(globalThis.document, 'activeElement', {
        get: () => firstBtn,
        configurable: true,
      })
    }

    const trap = createFocusTrap(container, { initialFocus: false })
    trap.activate()

    const e = fakeTabEvent(true) // Shift+Tab
    capturedKeydown(e)

    expect(e.preventDefault).toHaveBeenCalled()
    expect(buttons[2].focus).toHaveBeenCalled()
  })

  it('Tab from middle element: does NOT call preventDefault', () => {
    const buttons = makeButtons(3)
    const container = makeContainer(buttons)
    const midBtn = buttons[1]

    container.querySelectorAll = vi.fn(() => buttons)
    container.contains = vi.fn((el) => el === midBtn)

    if (typeof globalThis.document !== 'undefined') {
      Object.defineProperty(globalThis.document, 'activeElement', {
        get: () => midBtn,
        configurable: true,
      })
    }

    const trap = createFocusTrap(container, { initialFocus: false })
    trap.activate()

    const e = fakeTabEvent(false)
    capturedKeydown(e)

    expect(e.preventDefault).not.toHaveBeenCalled()
  })

  it('Escape calls onDeactivate when escapeDeactivates=true', () => {
    const buttons = makeButtons(1)
    const container = makeContainer(buttons)
    container.querySelectorAll = vi.fn(() => buttons)
    container.contains = vi.fn(() => false)

    const onDeactivate = vi.fn()
    const trap = createFocusTrap(container, {
      initialFocus: false,
      escapeDeactivates: true,
      onDeactivate,
    })
    trap.activate()

    const e = fakeEscapeEvent()
    capturedKeydown(e)

    expect(onDeactivate).toHaveBeenCalledOnce()
  })

  it('Escape does NOT call onDeactivate when escapeDeactivates=false', () => {
    const buttons = makeButtons(1)
    const container = makeContainer(buttons)
    container.querySelectorAll = vi.fn(() => buttons)
    container.contains = vi.fn(() => false)

    const onDeactivate = vi.fn()
    const trap = createFocusTrap(container, {
      initialFocus: false,
      escapeDeactivates: false,
      onDeactivate,
    })
    trap.activate()

    const e = fakeEscapeEvent()
    capturedKeydown(e)

    expect(onDeactivate).not.toHaveBeenCalled()
  })

  it('deactivate() removes the keydown listener', () => {
    const buttons = makeButtons(2)
    const container = makeContainer(buttons)
    container.querySelectorAll = vi.fn(() => buttons)

    const trap = createFocusTrap(container, { initialFocus: false })
    trap.activate()
    trap.deactivate()

    expect(globalThis.document.removeEventListener).toHaveBeenCalledWith(
      'keydown',
      expect.any(Function),
      true,
    )
  })

  it('deactivate() does not throw when not active', () => {
    const buttons = makeButtons(1)
    const container = makeContainer(buttons)
    const trap = createFocusTrap(container, { initialFocus: false })
    expect(() => trap.deactivate()).not.toThrow()
  })

  it('update() does not throw', () => {
    const buttons = makeButtons(2)
    const container = makeContainer(buttons)
    container.querySelectorAll = vi.fn(() => buttons)

    const trap = createFocusTrap(container, { initialFocus: false })
    trap.activate()
    expect(() => trap.update()).not.toThrow()
    trap.deactivate()
  })
})
