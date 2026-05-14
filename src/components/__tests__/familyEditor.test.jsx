// familyEditor.test.jsx — Pure data-layer tests for FamilyEditor helpers.
//
// Tests operate directly on family.js exported functions — same pattern as
// graphEditor.test.jsx. No React rendering needed.

import { describe, it, expect } from 'vitest'
import {
  defaultFamily,
  validateFamily,
  addParam,
  removeParam,
  updateParam,
  addType,
  removeType,
  resolveParams,
} from '../../lib/family.js'

// ── 1. defaultFamily ──────────────────────────────────────────────────────────

describe('defaultFamily', () => {
  it('returns an object with the given category', () => {
    const f = defaultFamily('Door')
    expect(f.category).toBe('Door')
  })

  it('defaults to Generic when no category supplied', () => {
    const f = defaultFamily()
    expect(f.category).toBe('Generic')
  })

  it('has an empty params array', () => {
    const f = defaultFamily()
    expect(Array.isArray(f.params)).toBe(true)
    expect(f.params).toHaveLength(0)
  })

  it('has an empty types array', () => {
    const f = defaultFamily()
    expect(Array.isArray(f.types)).toBe(true)
    expect(f.types).toHaveLength(0)
  })

  it('passes validateFamily with no errors', () => {
    const { ok } = validateFamily(defaultFamily('Window'))
    expect(ok).toBe(true)
  })
})

// ── 2. validateFamily ─────────────────────────────────────────────────────────

describe('validateFamily', () => {
  it('rejects a non-object', () => {
    const { ok, errors } = validateFamily(null)
    expect(ok).toBe(false)
    expect(errors.length).toBeGreaterThan(0)
  })

  it('rejects an invalid category', () => {
    const f = { ...defaultFamily(), category: 'Spaceship' }
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(false)
    expect(errors.some((e) => /category/.test(e))).toBe(true)
  })

  it('rejects duplicate param names', () => {
    const f = defaultFamily()
    f.params = [
      { name: 'width', type: 'number' },
      { name: 'width', type: 'number' },
    ]
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(false)
    expect(errors.some((e) => /duplicate/.test(e))).toBe(true)
  })

  it('rejects a number param where min > max', () => {
    const f = defaultFamily()
    f.params = [{ name: 'h', type: 'number', min: 100, max: 50 }]
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(false)
    expect(errors.some((e) => /min.*max/.test(e))).toBe(true)
  })
})

// ── 3. addParam / removeParam / updateParam ───────────────────────────────────

describe('addParam', () => {
  it('appends the param', () => {
    const f = defaultFamily()
    addParam(f, { name: 'width', type: 'number', default: 600 })
    expect(f.params).toHaveLength(1)
    expect(f.params[0].name).toBe('width')
  })

  it('throws on duplicate name', () => {
    const f = defaultFamily()
    addParam(f, { name: 'width', type: 'number' })
    expect(() => addParam(f, { name: 'width', type: 'number' })).toThrow()
  })
})

describe('removeParam', () => {
  it('removes the named param', () => {
    const f = defaultFamily()
    addParam(f, { name: 'height', type: 'number' })
    removeParam(f, 'height')
    expect(f.params).toHaveLength(0)
  })

  it('throws when the param does not exist', () => {
    const f = defaultFamily()
    expect(() => removeParam(f, 'ghost')).toThrow()
  })
})

describe('updateParam', () => {
  it('patches the param in place', () => {
    const f = defaultFamily()
    addParam(f, { name: 'depth', type: 'number', default: 200 })
    updateParam(f, 'depth', { default: 300 })
    expect(f.params[0].default).toBe(300)
  })
})

// ── 4. addType / removeType ───────────────────────────────────────────────────

describe('addType / removeType', () => {
  it('adds a named type preset', () => {
    const f = defaultFamily()
    addType(f, { id: 'single', name: 'Single', params: { width: 800 } })
    expect(f.types).toHaveLength(1)
    expect(f.types[0].id).toBe('single')
  })

  it('throws on duplicate type id', () => {
    const f = defaultFamily()
    addType(f, { id: 'double', name: 'Double', params: {} })
    expect(() => addType(f, { id: 'double', name: 'Double2', params: {} })).toThrow()
  })

  it('removes a type by id', () => {
    const f = defaultFamily()
    addType(f, { id: 'slim', name: 'Slim', params: {} })
    removeType(f, 'slim')
    expect(f.types).toHaveLength(0)
  })
})

// ── 5. resolveParams ──────────────────────────────────────────────────────────

describe('resolveParams', () => {
  it('resolves defaults', () => {
    const f = defaultFamily()
    addParam(f, { name: 'width', type: 'number', default: 900 })
    const resolved = resolveParams(f, {})
    expect(resolved.width).toBe(900)
  })

  it('instance overrides type which overrides default', () => {
    const f = defaultFamily()
    addParam(f, { name: 'height', type: 'number', default: 2100 })
    addType(f, { id: 'tall', name: 'Tall', params: { height: 2400 } })
    const resolved = resolveParams(f, { type_id: 'tall', params: { height: 2600 } })
    expect(resolved.height).toBe(2600)
  })

  it('type override wins over default when no instance override', () => {
    const f = defaultFamily()
    addParam(f, { name: 'width', type: 'number', default: 800 })
    addType(f, { id: 'narrow', name: 'Narrow', params: { width: 700 } })
    const resolved = resolveParams(f, { type_id: 'narrow' })
    expect(resolved.width).toBe(700)
  })
})
