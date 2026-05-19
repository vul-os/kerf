// keyboardShortcuts.test.js — Vitest unit tests for the keyboard shortcut registry.
//
// Strategy: the project runs vitest in Node (no jsdom). We test the pure-logic
// exports (parseShortcut, matchesShortcut) directly, and test the
// registerShortcut machinery by stubbing document on globalThis before import.
//
// Tests verify the SPEC requirements:
//   1. parseShortcut correctly normalises modifiers and keys.
//   2. matchesShortcut correctly gates on modifier+key combinations.
//   3. isFocusInInput detects input/textarea/contenteditable elements.
//   4. registerShortcut calls handler on match and skips it when input focused.
//   5. Priority ordering: higher priority fires first.
//   6. Return true from handler stops the chain.
//   7. unregister() prevents further invocations.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  parseShortcut,
  matchesShortcut,
  isFocusInInput,
  registerShortcut,
  unregisterAll,
  listShortcuts,
} from './keyboardShortcuts.js'

// ── parseShortcut ─────────────────────────────────────────────────────────────

describe('parseShortcut', () => {
  it('parses a single key with no modifiers', () => {
    const p = parseShortcut('escape')
    expect(p.key).toBe('escape')
    expect(p.ctrl).toBe(false)
    expect(p.shift).toBe(false)
    expect(p.meta).toBe(false)
    expect(p.alt).toBe(false)
  })

  it('parses ctrl modifier', () => {
    const p = parseShortcut('ctrl+k')
    expect(p.ctrl).toBe(true)
    expect(p.key).toBe('k')
  })

  it('parses shift modifier', () => {
    const p = parseShortcut('shift+?')
    expect(p.shift).toBe(true)
    expect(p.key).toBe('?')
  })

  it('parses multiple modifiers', () => {
    const p = parseShortcut('ctrl+shift+z')
    expect(p.ctrl).toBe(true)
    expect(p.shift).toBe(true)
    expect(p.key).toBe('z')
  })

  it('resolves "mod" into either ctrl or meta (never both mod=true)', () => {
    const p = parseShortcut('mod+k')
    expect(p.mod).toBe(false) // mod is always resolved
    expect(p.ctrl || p.meta).toBe(true) // one of the two is set
    expect(p.key).toBe('k')
  })

  it('lowercases the key', () => {
    const p = parseShortcut('ctrl+K')
    expect(p.key).toBe('k')
  })

  it('handles named keys like "arrowup"', () => {
    const p = parseShortcut('arrowup')
    expect(p.key).toBe('arrowup')
  })

  it('parses alt modifier', () => {
    const p = parseShortcut('alt+t')
    expect(p.alt).toBe(true)
    expect(p.key).toBe('t')
  })

  it('parses meta modifier', () => {
    const p = parseShortcut('meta+s')
    expect(p.meta).toBe(true)
    expect(p.key).toBe('s')
  })
})

// ── matchesShortcut ───────────────────────────────────────────────────────────

describe('matchesShortcut', () => {
  function fakeEvent(overrides) {
    return {
      key: 'k',
      ctrlKey: false,
      altKey: false,
      shiftKey: false,
      metaKey: false,
      ...overrides,
    }
  }

  it('matches a plain key press', () => {
    const parsed = parseShortcut('escape')
    expect(matchesShortcut(fakeEvent({ key: 'Escape' }), parsed)).toBe(true)
    expect(matchesShortcut(fakeEvent({ key: 'Enter' }), parsed)).toBe(false)
  })

  it('requires modifiers to match', () => {
    const parsed = parseShortcut('ctrl+k')
    expect(matchesShortcut(fakeEvent({ key: 'k', ctrlKey: true }), parsed)).toBe(true)
    expect(matchesShortcut(fakeEvent({ key: 'k', ctrlKey: false }), parsed)).toBe(false)
  })

  it('rejects extra modifier keys not in descriptor', () => {
    const parsed = parseShortcut('ctrl+k')
    expect(
      matchesShortcut(fakeEvent({ key: 'k', ctrlKey: true, shiftKey: true }), parsed),
    ).toBe(false)
  })

  it('is case-insensitive for key', () => {
    const parsed = parseShortcut('ctrl+k')
    expect(matchesShortcut(fakeEvent({ key: 'K', ctrlKey: true }), parsed)).toBe(true)
  })

  it('matches shift+? correctly', () => {
    const parsed = parseShortcut('shift+?')
    expect(matchesShortcut(fakeEvent({ key: '?', shiftKey: true }), parsed)).toBe(true)
    expect(matchesShortcut(fakeEvent({ key: '?', shiftKey: false }), parsed)).toBe(false)
  })

  it('returns false for different key with matching modifiers', () => {
    const parsed = parseShortcut('ctrl+k')
    expect(matchesShortcut(fakeEvent({ key: 'j', ctrlKey: true }), parsed)).toBe(false)
  })
})

// ── isFocusInInput ────────────────────────────────────────────────────────────

describe('isFocusInInput', () => {
  let savedDocument

  beforeEach(() => {
    savedDocument = global.document
  })
  afterEach(() => {
    global.document = savedDocument
  })

  it('returns false when document is undefined', () => {
    global.document = undefined
    expect(isFocusInInput()).toBe(false)
  })

  it('returns false when activeElement is null', () => {
    global.document = { activeElement: null }
    expect(isFocusInInput()).toBe(false)
  })

  it('returns true for INPUT element', () => {
    global.document = {
      activeElement: {
        tagName: 'INPUT',
        isContentEditable: false,
        getAttribute: () => null,
      },
    }
    expect(isFocusInInput()).toBe(true)
  })

  it('returns true for TEXTAREA element', () => {
    global.document = {
      activeElement: {
        tagName: 'TEXTAREA',
        isContentEditable: false,
        getAttribute: () => null,
      },
    }
    expect(isFocusInInput()).toBe(true)
  })

  it('returns true for SELECT element', () => {
    global.document = {
      activeElement: {
        tagName: 'SELECT',
        isContentEditable: false,
        getAttribute: () => null,
      },
    }
    expect(isFocusInInput()).toBe(true)
  })

  it('returns true for contenteditable element', () => {
    global.document = {
      activeElement: {
        tagName: 'DIV',
        isContentEditable: true,
        getAttribute: () => null,
      },
    }
    expect(isFocusInInput()).toBe(true)
  })

  it('returns true for role=textbox element (Monaco)', () => {
    global.document = {
      activeElement: {
        tagName: 'DIV',
        isContentEditable: false,
        getAttribute: (attr) => (attr === 'role' ? 'textbox' : null),
      },
    }
    expect(isFocusInInput()).toBe(true)
  })

  it('returns false for a plain BUTTON', () => {
    global.document = {
      activeElement: {
        tagName: 'BUTTON',
        isContentEditable: false,
        getAttribute: () => null,
      },
    }
    expect(isFocusInInput()).toBe(false)
  })
})

// ── registerShortcut — dispatch logic ────────────────────────────────────────
//
// We stub global.document with a minimal event-listener implementation so we
// can capture the dispatch function and fire it directly.

describe('registerShortcut — dispatch logic', () => {
  let capturedListener = null
  let fakeActiveElement = null

  beforeEach(() => {
    // Install a document stub that captures the keydown listener
    global.document = {
      addEventListener: vi.fn((type, fn) => {
        if (type === 'keydown') capturedListener = fn
      }),
      removeEventListener: vi.fn(),
      get activeElement() { return fakeActiveElement },
    }
    fakeActiveElement = { tagName: 'BODY', isContentEditable: false, getAttribute: () => null }
    capturedListener = null
    unregisterAll()
  })

  afterEach(() => {
    unregisterAll()
  })

  function fireKey(key, mods = {}) {
    const e = {
      key,
      ctrlKey: mods.ctrl ?? false,
      shiftKey: mods.shift ?? false,
      altKey: mods.alt ?? false,
      metaKey: mods.meta ?? false,
      preventDefault: vi.fn(),
    }
    if (capturedListener) capturedListener(e)
    return e
  }

  it('registers a listener on document', () => {
    const handler = vi.fn()
    registerShortcut('ctrl+k', handler)
    expect(global.document.addEventListener).toHaveBeenCalledWith('keydown', expect.any(Function), true)
  })

  it('handler is called when shortcut matches', () => {
    const handler = vi.fn()
    registerShortcut('ctrl+k', handler)
    fireKey('k', { ctrl: true })
    expect(handler).toHaveBeenCalledOnce()
  })

  it('handler is NOT called when key does not match', () => {
    const handler = vi.fn()
    registerShortcut('ctrl+k', handler)
    fireKey('j', { ctrl: true })
    expect(handler).not.toHaveBeenCalled()
  })

  it('handler is NOT called when modifier differs', () => {
    const handler = vi.fn()
    registerShortcut('ctrl+k', handler)
    fireKey('k') // no ctrl
    expect(handler).not.toHaveBeenCalled()
  })

  it('handler is NOT called when input is focused (default allowInInput=false)', () => {
    const handler = vi.fn()
    registerShortcut('ctrl+k', handler)

    // Simulate focused input
    fakeActiveElement = {
      tagName: 'INPUT',
      isContentEditable: false,
      getAttribute: () => null,
    }

    fireKey('k', { ctrl: true })
    expect(handler).not.toHaveBeenCalled()
  })

  it('handler IS called when input is focused and allowInInput=true', () => {
    const handler = vi.fn()
    registerShortcut('ctrl+k', handler, { allowInInput: true })

    fakeActiveElement = {
      tagName: 'INPUT',
      isContentEditable: false,
      getAttribute: () => null,
    }

    fireKey('k', { ctrl: true })
    expect(handler).toHaveBeenCalledOnce()
  })

  it('handler IS called when textarea is focused and allowInInput=true', () => {
    const handler = vi.fn()
    registerShortcut('ctrl+s', handler, { allowInInput: true })

    fakeActiveElement = {
      tagName: 'TEXTAREA',
      isContentEditable: false,
      getAttribute: () => null,
    }

    fireKey('s', { ctrl: true })
    expect(handler).toHaveBeenCalledOnce()
  })

  it('returns an unregister function that stops the handler from firing', () => {
    const handler = vi.fn()
    const unregister = registerShortcut('ctrl+k', handler)
    unregister()
    fireKey('k', { ctrl: true })
    expect(handler).not.toHaveBeenCalled()
  })

  it('higher priority handler fires first', () => {
    const order = []
    registerShortcut('ctrl+k', () => { order.push('low') }, { priority: 0 })
    registerShortcut('ctrl+k', () => { order.push('high') }, { priority: 10 })
    fireKey('k', { ctrl: true })
    expect(order[0]).toBe('high')
  })

  it('returning true from a handler stops subsequent handlers', () => {
    const second = vi.fn()
    registerShortcut('ctrl+k', () => true, { priority: 10 })
    registerShortcut('ctrl+k', second, { priority: 0 })
    fireKey('k', { ctrl: true })
    expect(second).not.toHaveBeenCalled()
  })

  it('returning "stop" from a handler stops subsequent handlers', () => {
    const second = vi.fn()
    registerShortcut('ctrl+k', () => 'stop', { priority: 10 })
    registerShortcut('ctrl+k', second, { priority: 0 })
    fireKey('k', { ctrl: true })
    expect(second).not.toHaveBeenCalled()
  })

  it('listShortcuts returns all registered descriptor strings', () => {
    registerShortcut('ctrl+k', vi.fn())
    registerShortcut('mod+p', vi.fn())
    const list = listShortcuts()
    expect(list).toContain('ctrl+k')
    expect(list).toContain('mod+p')
  })

  it('unregisterAll clears all handlers', () => {
    const handler = vi.fn()
    registerShortcut('ctrl+k', handler)
    unregisterAll()
    fireKey('k', { ctrl: true })
    expect(handler).not.toHaveBeenCalled()
  })

  it('preventDefault option auto-calls e.preventDefault()', () => {
    registerShortcut('ctrl+k', vi.fn(), { preventDefault: true })
    const e = fireKey('k', { ctrl: true })
    expect(e.preventDefault).toHaveBeenCalled()
  })
})
