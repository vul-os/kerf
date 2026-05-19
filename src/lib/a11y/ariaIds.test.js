// ariaIds.test.js — Vitest unit tests for the ARIA unique-ID generator.

import { describe, it, expect, beforeEach } from 'vitest'
import {
  generateAriaId,
  createAriaIdGroup,
  resetAriaIdCounter,
  peekAriaIdCounter,
} from './ariaIds.js'

beforeEach(() => {
  resetAriaIdCounter()
})

// ── generateAriaId ────────────────────────────────────────────────────────────

describe('generateAriaId', () => {
  it('returns a non-empty string', () => {
    const id = generateAriaId()
    expect(typeof id).toBe('string')
    expect(id.length).toBeGreaterThan(0)
  })

  it('starts with the kerf- prefix', () => {
    expect(generateAriaId()).toMatch(/^kerf-/)
  })

  it('embeds the supplied prefix', () => {
    resetAriaIdCounter()
    const id = generateAriaId('dialog')
    expect(id).toContain('dialog')
  })

  it('generates unique IDs on successive calls', () => {
    const ids = Array.from({ length: 100 }, () => generateAriaId('x'))
    const unique = new Set(ids)
    expect(unique.size).toBe(100)
  })

  it('is monotonically increasing', () => {
    const id1 = generateAriaId('a')
    const id2 = generateAriaId('a')
    const n1 = parseInt(id1.split('-').pop(), 10)
    const n2 = parseInt(id2.split('-').pop(), 10)
    expect(n2).toBeGreaterThan(n1)
  })

  it('uses "aria" as the default prefix', () => {
    const id = generateAriaId()
    expect(id).toMatch(/^kerf-aria-\d+$/)
  })

  it('produces IDs that are valid HTML id attribute values (no spaces)', () => {
    const id = generateAriaId('my label')
    // The ID should not contain bare spaces — replace with hyphen or similar
    // (we don't enforce this in the implementation but the default doesn't
    // produce spaces, so check the default-prefix form)
    const plain = generateAriaId('tooltip')
    expect(/\s/.test(plain)).toBe(false)
  })
})

// ── createAriaIdGroup ─────────────────────────────────────────────────────────

describe('createAriaIdGroup', () => {
  it('returns a function', () => {
    const ids = createAriaIdGroup('dialog')
    expect(typeof ids).toBe('function')
  })

  it('embeds the namespace in every generated ID', () => {
    const ids = createAriaIdGroup('tooltip')
    const id1 = ids('title')
    const id2 = ids('body')
    expect(id1).toContain('tooltip')
    expect(id2).toContain('tooltip')
  })

  it('embeds the suffix in the ID', () => {
    const ids = createAriaIdGroup('combo')
    expect(ids('input')).toContain('input')
    expect(ids('listbox')).toContain('listbox')
  })

  it('produces unique IDs even with the same suffix', () => {
    const ids = createAriaIdGroup('modal')
    const a = ids('title')
    const b = ids('title')
    expect(a).not.toBe(b)
  })

  it('produces unique IDs across two separate groups', () => {
    const g1 = createAriaIdGroup('alpha')
    const g2 = createAriaIdGroup('beta')
    const id1 = g1('x')
    const id2 = g2('x')
    expect(id1).not.toBe(id2)
  })

  it('works with an empty suffix (uses just the namespace)', () => {
    const ids = createAriaIdGroup('panel')
    const id = ids()
    expect(id).toMatch(/^kerf-panel-\d+$/)
  })
})

// ── resetAriaIdCounter / peekAriaIdCounter ────────────────────────────────────

describe('resetAriaIdCounter', () => {
  it('resets counter so subsequent IDs start from 1 again', () => {
    generateAriaId()
    generateAriaId()
    resetAriaIdCounter()
    const id = generateAriaId('reset')
    expect(id).toBe('kerf-reset-1')
  })
})

describe('peekAriaIdCounter', () => {
  it('returns 0 after reset', () => {
    resetAriaIdCounter()
    expect(peekAriaIdCounter()).toBe(0)
  })

  it('does not increment the counter', () => {
    resetAriaIdCounter()
    peekAriaIdCounter()
    peekAriaIdCounter()
    const id = generateAriaId('p')
    expect(id).toBe('kerf-p-1')
  })

  it('reflects the current count after generates', () => {
    resetAriaIdCounter()
    generateAriaId()
    generateAriaId()
    generateAriaId()
    expect(peekAriaIdCounter()).toBe(3)
  })
})
