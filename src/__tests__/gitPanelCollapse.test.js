// gitPanelCollapse.test.js — unit tests for the shared panel collapse/expand
// logic introduced by T-142 (Git panel parity with Chat panel).
//
// Tests are intentionally DOM-free: panelCollapse.js is a plain ES module
// (no JSX, no React, no DOM APIs beyond localStorage) so we can run the full
// suite in vitest's default node-like environment with a localStorage stub.
//
// What we test:
//   1. readCollapsed — correct default, '1'→collapsed, '0'→expanded, absent→default
//   2. writeCollapsed — serialises to '0'/'1', swallows storage errors
//   3. editorGridCols — all four combinations of chat/git collapsed state
//   4. Key constants — CHAT_COLLAPSE_KEY / GIT_COLLAPSE_KEY are stable strings

import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  readCollapsed,
  writeCollapsed,
  editorGridCols,
  CHAT_COLLAPSE_KEY,
  GIT_COLLAPSE_KEY,
} from '../lib/panelCollapse.js'

// ---------------------------------------------------------------------------
// Minimal localStorage stub (vitest runs in a node environment that may not
// provide window.localStorage; we shim it on globalThis for this module only).
// ---------------------------------------------------------------------------
const store = {}
const localStorageStub = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v) },
  removeItem: (k) => { delete store[k] },
  clear: () => { Object.keys(store).forEach((k) => delete store[k]) },
}

beforeEach(() => {
  localStorageStub.clear()
  // Inject the stub into globalThis so panelCollapse.js picks it up.
  globalThis.localStorage = localStorageStub
})

// ---------------------------------------------------------------------------
// Key constants
// ---------------------------------------------------------------------------

describe('panel collapse key constants', () => {
  it('CHAT_COLLAPSE_KEY is the expected localStorage key', () => {
    expect(CHAT_COLLAPSE_KEY).toBe('kerf:chatCollapsed')
  })

  it('GIT_COLLAPSE_KEY is the expected localStorage key', () => {
    expect(GIT_COLLAPSE_KEY).toBe('kerf:gitCollapsed')
  })

  it('CHAT_COLLAPSE_KEY and GIT_COLLAPSE_KEY are distinct', () => {
    expect(CHAT_COLLAPSE_KEY).not.toBe(GIT_COLLAPSE_KEY)
  })
})

// ---------------------------------------------------------------------------
// readCollapsed
// ---------------------------------------------------------------------------

describe('readCollapsed — key absent', () => {
  it('returns defaultCollapsed=false when key is absent', () => {
    expect(readCollapsed('kerf:test', false)).toBe(false)
  })

  it('returns defaultCollapsed=true when key is absent', () => {
    expect(readCollapsed('kerf:test', true)).toBe(true)
  })
})

describe('readCollapsed — value "1"', () => {
  it('returns true (collapsed) when stored value is "1"', () => {
    localStorageStub.setItem('kerf:test', '1')
    expect(readCollapsed('kerf:test', false)).toBe(true)
  })
})

describe('readCollapsed — value "0"', () => {
  it('returns false (expanded) when stored value is "0"', () => {
    localStorageStub.setItem('kerf:test', '0')
    expect(readCollapsed('kerf:test', true)).toBe(false)
  })
})

describe('readCollapsed — unexpected stored value', () => {
  it('treats any value other than "1" as expanded (false)', () => {
    localStorageStub.setItem('kerf:test', 'yes')
    expect(readCollapsed('kerf:test', true)).toBe(false)
  })
})

describe('readCollapsed — localStorage unavailable', () => {
  it('returns the default when localStorage throws', () => {
    const broken = { getItem: () => { throw new Error('quota') } }
    globalThis.localStorage = broken
    expect(readCollapsed('kerf:test', true)).toBe(true)
    expect(readCollapsed('kerf:test', false)).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// writeCollapsed
// ---------------------------------------------------------------------------

describe('writeCollapsed', () => {
  it('writes "1" when collapsed=true', () => {
    writeCollapsed('kerf:test', true)
    expect(localStorageStub.getItem('kerf:test')).toBe('1')
  })

  it('writes "0" when collapsed=false', () => {
    writeCollapsed('kerf:test', false)
    expect(localStorageStub.getItem('kerf:test')).toBe('0')
  })

  it('does not throw when localStorage is unavailable', () => {
    globalThis.localStorage = { setItem: () => { throw new Error('private') } }
    expect(() => writeCollapsed('kerf:test', true)).not.toThrow()
  })
})

describe('writeCollapsed + readCollapsed round-trip', () => {
  it('write true → read true', () => {
    writeCollapsed(GIT_COLLAPSE_KEY, true)
    expect(readCollapsed(GIT_COLLAPSE_KEY, false)).toBe(true)
  })

  it('write false → read false', () => {
    writeCollapsed(CHAT_COLLAPSE_KEY, false)
    expect(readCollapsed(CHAT_COLLAPSE_KEY, true)).toBe(false)
  })

  it('toggling state round-trips correctly', () => {
    writeCollapsed(GIT_COLLAPSE_KEY, false)
    expect(readCollapsed(GIT_COLLAPSE_KEY, true)).toBe(false)
    writeCollapsed(GIT_COLLAPSE_KEY, true)
    expect(readCollapsed(GIT_COLLAPSE_KEY, false)).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// editorGridCols — all four combinations
// ---------------------------------------------------------------------------

describe('editorGridCols — both panels collapsed', () => {
  it('returns the two-column template (no right panels)', () => {
    expect(editorGridCols(true, true)).toBe('240px_1fr')
  })
})

describe('editorGridCols — chat open, git collapsed', () => {
  it('returns the three-column template with Chat column (380px)', () => {
    expect(editorGridCols(false, true)).toBe('240px_1fr_380px')
  })
})

describe('editorGridCols — chat collapsed, git open', () => {
  it('returns the three-column template with Git column (384px)', () => {
    expect(editorGridCols(true, false)).toBe('240px_1fr_384px')
  })
})

describe('editorGridCols — both panels open', () => {
  it('returns the four-column template (Chat then Git)', () => {
    expect(editorGridCols(false, false)).toBe('240px_1fr_380px_384px')
  })
})

describe('editorGridCols — column ordering', () => {
  it('Chat column (380px) always precedes Git column (384px) when both open', () => {
    const cols = editorGridCols(false, false)
    const parts = cols.split('_')
    expect(parts.indexOf('380px')).toBeLessThan(parts.indexOf('384px'))
  })

  it('canvas column (1fr) is always the second column', () => {
    for (const [chat, git] of [[true, true], [false, true], [true, false], [false, false]]) {
      const parts = editorGridCols(chat, git).split('_')
      expect(parts[1]).toBe('1fr')
    }
  })

  it('file-tree column (240px) is always the first column', () => {
    for (const [chat, git] of [[true, true], [false, true], [true, false], [false, false]]) {
      const parts = editorGridCols(chat, git).split('_')
      expect(parts[0]).toBe('240px')
    }
  })
})
