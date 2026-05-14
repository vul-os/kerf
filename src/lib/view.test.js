import { describe, it, expect } from 'vitest'
import {
  defaultView,
  validateView,
  applyFilters,
  addAnnotation,
  removeAnnotation,
  setCropBox,
  clearCropBox,
  VALID_KINDS,
} from './view.js'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const BIM = {
  elements: [
    { id: 'w1', category: 'wall', fire_rating: '2hr',  thickness: 200 },
    { id: 'w2', category: 'wall', fire_rating: '1hr',  thickness: 150 },
    { id: 'd1', category: 'door', fire_rating: '1hr',  width: 900 },
    { id: 'c1', category: 'column', height: 3000 },
  ],
}

// ── defaultView ───────────────────────────────────────────────────────────────

describe('defaultView', () => {
  it('returns a valid plan view', () => {
    const v = defaultView('plan', 'bim-1')
    expect(v.version).toBe(1)
    expect(v.kind).toBe('plan')
    expect(v.bim_file_id).toBe('bim-1')
    expect(v.filters).toEqual([])
    expect(v.annotations).toEqual([])
    expect(v.crop_box).toBeNull()
  })

  it('assigns a unique id each call', () => {
    const a = defaultView('3d', 'bim-x')
    const b = defaultView('3d', 'bim-x')
    expect(a.id).toBeTruthy()
    expect(a.id).not.toBe(b.id)
  })
})

// ── validateView ──────────────────────────────────────────────────────────────

describe('validateView', () => {
  it('passes a minimal valid plan view', () => {
    const v = defaultView('plan', 'bim-1')
    expect(validateView(v).ok).toBe(true)
  })

  it('rejects missing bim_file_id', () => {
    const v = { ...defaultView('plan', 'bim-1'), bim_file_id: '' }
    const { ok, errors } = validateView(v)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('bim_file_id'))).toBe(true)
  })

  it('rejects unknown kind', () => {
    const v = { ...defaultView('plan', 'bim-1'), kind: 'ortho' }
    const { ok, errors } = validateView(v)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('kind'))).toBe(true)
  })

  it('rejects wrong version', () => {
    const v = { ...defaultView('section', 'bim-1'), version: 2 }
    const { ok, errors } = validateView(v)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('version'))).toBe(true)
  })

  it('accepts all valid kinds', () => {
    for (const kind of VALID_KINDS) {
      expect(validateView(defaultView(kind, 'bim-1')).ok).toBe(true)
    }
  })

  it('rejects non-object input', () => {
    expect(validateView(null).ok).toBe(false)
    expect(validateView('string').ok).toBe(false)
  })
})

// ── applyFilters ──────────────────────────────────────────────────────────────

describe('applyFilters', () => {
  it('returns all elements when no filters', () => {
    const v = defaultView('plan', 'bim-1')
    expect(applyFilters(v, BIM)).toHaveLength(4)
  })

  it('filters by category equality', () => {
    const v = { ...defaultView('plan', 'bim-1'), filters: [{ expr: "category=='wall'" }] }
    const result = applyFilters(v, BIM)
    expect(result).toHaveLength(2)
    expect(result.every(e => e.category === 'wall')).toBe(true)
  })

  it('filters with AND', () => {
    const v = { ...defaultView('plan', 'bim-1'), filters: [{ expr: "category=='wall' AND fire_rating=='2hr'" }] }
    const result = applyFilters(v, BIM)
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('w1')
  })

  it('filters with numeric gt', () => {
    const v = { ...defaultView('plan', 'bim-1'), filters: [{ expr: 'thickness>150' }] }
    const result = applyFilters(v, BIM)
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('w1')
  })

  it('returns empty array for null bim_doc', () => {
    const v = defaultView('plan', 'bim-1')
    expect(applyFilters(v, null)).toEqual([])
  })
})

// ── addAnnotation / removeAnnotation ─────────────────────────────────────────

describe('addAnnotation', () => {
  it('appends an annotation with auto id', () => {
    let v = defaultView('plan', 'bim-1')
    v = addAnnotation(v, { kind: 'door_tag', element_id: 'd1', position: [0, 0, 0] })
    expect(v.annotations).toHaveLength(1)
    expect(v.annotations[0].id).toBeTruthy()
    expect(v.annotations[0].kind).toBe('door_tag')
  })

  it('preserves provided id', () => {
    let v = defaultView('plan', 'bim-1')
    v = addAnnotation(v, { id: 'ann-fixed', kind: 'linear_dim', from: [0, 0, 0], to: [1000, 0, 0] })
    expect(v.annotations[0].id).toBe('ann-fixed')
  })

  it('is immutable — original view unchanged', () => {
    const v = defaultView('plan', 'bim-1')
    addAnnotation(v, { kind: 'door_tag' })
    expect(v.annotations).toHaveLength(0)
  })
})

describe('removeAnnotation', () => {
  it('removes by id', () => {
    let v = defaultView('plan', 'bim-1')
    v = addAnnotation(v, { id: 'ann-1', kind: 'door_tag' })
    v = addAnnotation(v, { id: 'ann-2', kind: 'linear_dim' })
    v = removeAnnotation(v, 'ann-1')
    expect(v.annotations).toHaveLength(1)
    expect(v.annotations[0].id).toBe('ann-2')
  })

  it('no-ops when id not found', () => {
    const v = defaultView('plan', 'bim-1')
    const v2 = removeAnnotation(v, 'nonexistent')
    expect(v2.annotations).toHaveLength(0)
  })
})

// ── setCropBox / clearCropBox ─────────────────────────────────────────────────

describe('setCropBox', () => {
  it('sets a valid crop box', () => {
    const v = defaultView('plan', 'bim-1')
    const v2 = setCropBox(v, [0, 0, 0], [5000, 5000, 3000])
    expect(v2.crop_box).toEqual({ min: [0, 0, 0], max: [5000, 5000, 3000] })
  })

  it('throws on invalid min', () => {
    const v = defaultView('plan', 'bim-1')
    expect(() => setCropBox(v, [0, 0], [1, 1, 1])).toThrow()
  })
})

describe('clearCropBox', () => {
  it('removes the crop box', () => {
    let v = defaultView('plan', 'bim-1')
    v = setCropBox(v, [0, 0, 0], [1, 1, 1])
    v = clearCropBox(v)
    expect(v.crop_box).toBeNull()
  })
})
