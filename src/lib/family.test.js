import { describe, it, expect } from 'vitest'
import {
  defaultFamily,
  validateFamily,
  resolveParams,
  validateInstance,
  addParam,
  removeParam,
  updateParam,
  addType,
  removeType,
} from './family.js'

// ── defaultFamily ─────────────────────────────────────────────────────────────

describe('defaultFamily', () => {
  it('returns a valid family for a known category', () => {
    const f = defaultFamily('Window')
    expect(f.version).toBe(1)
    expect(f.category).toBe('Window')
    expect(Array.isArray(f.params)).toBe(true)
    expect(Array.isArray(f.types)).toBe(true)
  })

  it('defaults to Generic when no category supplied', () => {
    const f = defaultFamily()
    expect(f.category).toBe('Generic')
  })
})

// ── validateFamily ────────────────────────────────────────────────────────────

describe('validateFamily', () => {
  it('accepts a well-formed window family', () => {
    const f = {
      version: 1,
      name: 'Standard Window',
      category: 'Window',
      params: [
        { name: 'width', type: 'number', unit: 'mm', default: 900, min: 300, max: 3000 },
        { name: 'glazing', type: 'enum', options: ['single', 'double', 'triple'], default: 'double' },
      ],
      types: [],
    }
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(true)
    expect(errors).toHaveLength(0)
  })

  it('rejects unknown category', () => {
    const f = { ...defaultFamily('Window'), category: 'Spaceship' }
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('category'))).toBe(true)
  })

  it('rejects wrong version', () => {
    const f = { ...defaultFamily('Door'), version: 2 }
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('version'))).toBe(true)
  })

  it('rejects duplicate param names', () => {
    const f = defaultFamily('Wall')
    f.params = [
      { name: 'width', type: 'number', default: 100 },
      { name: 'width', type: 'number', default: 200 },
    ]
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('duplicate'))).toBe(true)
  })

  it('rejects enum param without options', () => {
    const f = defaultFamily('Door')
    f.params = [{ name: 'swing', type: 'enum', options: [], default: 'left' }]
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('options'))).toBe(true)
  })

  it('rejects enum default not in options', () => {
    const f = defaultFamily('Door')
    f.params = [{ name: 'swing', type: 'enum', options: ['left', 'right'], default: 'both' }]
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('not in options'))).toBe(true)
  })

  it('rejects number param where min > max', () => {
    const f = defaultFamily('Window')
    f.params = [{ name: 'width', type: 'number', min: 1000, max: 500 }]
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('min') && e.includes('max'))).toBe(true)
  })

  it('rejects duplicate type ids', () => {
    const f = defaultFamily('Column')
    f.types = [
      { id: 't1', name: 'Type A', params: {} },
      { id: 't1', name: 'Type B', params: {} },
    ]
    const { ok, errors } = validateFamily(f)
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('duplicate type'))).toBe(true)
  })
})

// ── resolveParams ─────────────────────────────────────────────────────────────

describe('resolveParams', () => {
  const family = {
    version: 1,
    name: 'Window',
    category: 'Window',
    params: [
      { name: 'width', type: 'number', default: 900 },
      { name: 'height', type: 'number', default: 1200 },
      { name: 'glazing', type: 'enum', options: ['single', 'double', 'triple'], default: 'double' },
      { name: 'sill_height', type: 'number', default: 900 },
    ],
    types: [
      { id: 'type-wide', name: 'Wide', params: { width: 1500, glazing: 'triple' } },
    ],
  }

  it('returns defaults when no instance overrides', () => {
    const r = resolveParams(family, {})
    expect(r.width).toBe(900)
    expect(r.height).toBe(1200)
    expect(r.glazing).toBe('double')
  })

  it('instance params override defaults', () => {
    const r = resolveParams(family, { params: { width: 800 } })
    expect(r.width).toBe(800)
    expect(r.height).toBe(1200)
  })

  it('type params override defaults', () => {
    const r = resolveParams(family, { type_id: 'type-wide' })
    expect(r.width).toBe(1500)
    expect(r.glazing).toBe('triple')
    expect(r.height).toBe(1200) // still from default
  })

  it('instance params override type params (full precedence chain)', () => {
    const r = resolveParams(family, { type_id: 'type-wide', params: { width: 600, sill_height: 850 } })
    expect(r.width).toBe(600)       // instance wins over type
    expect(r.glazing).toBe('triple') // type wins over default
    expect(r.height).toBe(1200)     // default
    expect(r.sill_height).toBe(850) // instance
  })

  it('unknown type_id yields only defaults', () => {
    const r = resolveParams(family, { type_id: 'does-not-exist' })
    expect(r.width).toBe(900)
  })
})

// ── validateInstance ──────────────────────────────────────────────────────────

describe('validateInstance', () => {
  const family = {
    version: 1,
    name: 'Door',
    category: 'Door',
    params: [
      { name: 'width', type: 'number', default: 900, min: 600, max: 2400 },
      { name: 'height', type: 'number', default: 2100, min: 1800, max: 3000 },
      { name: 'swing', type: 'enum', options: ['left', 'right', 'double'], default: 'right' },
    ],
    types: [{ id: 'type-a', name: 'Type A', params: { width: 1000 } }],
  }

  it('accepts valid resolved params', () => {
    const { ok } = validateInstance(family, { params: { width: 900, swing: 'left' } })
    expect(ok).toBe(true)
  })

  it('rejects value below min', () => {
    const { ok, errors } = validateInstance(family, { params: { width: 100 } })
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('below min'))).toBe(true)
  })

  it('rejects value above max', () => {
    const { ok, errors } = validateInstance(family, { params: { height: 5000 } })
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('above max'))).toBe(true)
  })

  it('rejects invalid enum value', () => {
    const { ok, errors } = validateInstance(family, { params: { swing: 'up' } })
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('not a valid option'))).toBe(true)
  })

  it('rejects unknown type_id', () => {
    const { ok, errors } = validateInstance(family, { type_id: 'no-such-type' })
    expect(ok).toBe(false)
    expect(errors.some((e) => e.includes('type_id'))).toBe(true)
  })

  it('accepts valid type_id reference', () => {
    const { ok } = validateInstance(family, { type_id: 'type-a' })
    expect(ok).toBe(true)
  })
})

// ── addParam / removeParam / updateParam ──────────────────────────────────────

describe('addParam / removeParam / updateParam', () => {
  it('addParam appends a new param', () => {
    const f = defaultFamily('Beam')
    addParam(f, { name: 'span', type: 'number', default: 6000 })
    expect(f.params).toHaveLength(1)
    expect(f.params[0].name).toBe('span')
  })

  it('addParam throws on duplicate name', () => {
    const f = defaultFamily('Beam')
    addParam(f, { name: 'span', type: 'number' })
    expect(() => addParam(f, { name: 'span', type: 'number' })).toThrow()
  })

  it('removeParam removes by name', () => {
    const f = defaultFamily('Beam')
    addParam(f, { name: 'span', type: 'number' })
    addParam(f, { name: 'depth', type: 'number' })
    removeParam(f, 'span')
    expect(f.params).toHaveLength(1)
    expect(f.params[0].name).toBe('depth')
  })

  it('removeParam throws when name not found', () => {
    const f = defaultFamily('Beam')
    expect(() => removeParam(f, 'nonexistent')).toThrow()
  })

  it('updateParam patches a field', () => {
    const f = defaultFamily('Window')
    addParam(f, { name: 'width', type: 'number', default: 900 })
    updateParam(f, 'width', { default: 1200, max: 3000 })
    expect(f.params[0].default).toBe(1200)
    expect(f.params[0].max).toBe(3000)
  })
})

// ── addType / removeType ──────────────────────────────────────────────────────

describe('addType / removeType', () => {
  it('addType appends a named preset', () => {
    const f = defaultFamily('Column')
    addType(f, { id: 'ipe200', name: 'IPE 200', params: { depth: 200, width: 100 } })
    expect(f.types).toHaveLength(1)
    expect(f.types[0].id).toBe('ipe200')
  })

  it('addType throws on duplicate id', () => {
    const f = defaultFamily('Column')
    addType(f, { id: 'ipe200', name: 'IPE 200', params: {} })
    expect(() => addType(f, { id: 'ipe200', name: 'IPE 200 dup', params: {} })).toThrow()
  })

  it('removeType removes by id', () => {
    const f = defaultFamily('Column')
    addType(f, { id: 'ipe200', name: 'IPE 200', params: {} })
    addType(f, { id: 'ipe300', name: 'IPE 300', params: {} })
    removeType(f, 'ipe200')
    expect(f.types).toHaveLength(1)
    expect(f.types[0].id).toBe('ipe300')
  })

  it('removeType throws when id not found', () => {
    const f = defaultFamily('Column')
    expect(() => removeType(f, 'missing')).toThrow()
  })
})
