// viewEditor.test.jsx — Pure data-layer tests for ViewEditor helpers.

import { describe, it, expect } from 'vitest'
import {
  VALID_KINDS,
  defaultView,
  validateView,
  addAnnotation,
  removeAnnotation,
  setCropBox,
  clearCropBox,
  applyFilters,
} from '../../lib/view.js'

// ── 1. defaultView ────────────────────────────────────────────────────────────

describe('defaultView', () => {
  it('produces a valid view for every kind', () => {
    for (const kind of VALID_KINDS) {
      const v = defaultView(kind, 'bim-1')
      const { ok } = validateView(v)
      expect(ok, `${kind} should be valid`).toBe(true)
    }
  })

  it('sets the supplied bim_file_id', () => {
    const v = defaultView('plan', 'file-abc')
    expect(v.bim_file_id).toBe('file-abc')
  })

  it('has empty filters and annotations', () => {
    const v = defaultView('3d', 'file-x')
    expect(v.filters).toHaveLength(0)
    expect(v.annotations).toHaveLength(0)
  })
})

// ── 2. validateView ───────────────────────────────────────────────────────────

describe('validateView', () => {
  it('rejects a non-object', () => {
    const { ok } = validateView(null)
    expect(ok).toBe(false)
  })

  it('rejects an invalid kind', () => {
    const v = { ...defaultView('plan', 'x'), kind: 'isometric' }
    const { ok } = validateView(v)
    expect(ok).toBe(false)
  })

  it('rejects missing bim_file_id', () => {
    const v = { ...defaultView('plan', ''), bim_file_id: '' }
    const { ok, errors } = validateView(v)
    expect(ok).toBe(false)
    expect(errors.some((e) => /bim_file_id/.test(e))).toBe(true)
  })
})

// ── 3. addAnnotation / removeAnnotation ───────────────────────────────────────

describe('addAnnotation / removeAnnotation', () => {
  it('adds an annotation and assigns an id', () => {
    const v = defaultView('plan', 'f1')
    const next = addAnnotation(v, { kind: 'tag', label: 'Room 1' })
    expect(next.annotations).toHaveLength(1)
    expect(next.annotations[0].id).toBeTruthy()
    expect(next.annotations[0].label).toBe('Room 1')
  })

  it('removes an annotation by id', () => {
    let v = defaultView('plan', 'f1')
    v = addAnnotation(v, { kind: 'tag', label: 'A' })
    const id = v.annotations[0].id
    const removed = removeAnnotation(v, id)
    expect(removed.annotations).toHaveLength(0)
  })

  it('is immutable — original view unchanged', () => {
    const v = defaultView('plan', 'f1')
    addAnnotation(v, { kind: 'tag' })
    expect(v.annotations).toHaveLength(0)
  })
})

// ── 4. setCropBox / clearCropBox ──────────────────────────────────────────────

describe('setCropBox / clearCropBox', () => {
  it('sets a valid crop box', () => {
    const v = defaultView('plan', 'f1')
    const next = setCropBox(v, [0, 0, 0], [5000, 5000, 3000])
    expect(next.crop_box).toBeTruthy()
    expect(next.crop_box.min).toEqual([0, 0, 0])
    expect(next.crop_box.max).toEqual([5000, 5000, 3000])
  })

  it('clears the crop box', () => {
    let v = defaultView('plan', 'f1')
    v = setCropBox(v, [0, 0, 0], [1, 1, 1])
    v = clearCropBox(v)
    expect(v.crop_box).toBeNull()
  })

  it('throws on a non-vec3 argument', () => {
    const v = defaultView('plan', 'f1')
    expect(() => setCropBox(v, [0, 0], [1, 1, 1])).toThrow()
  })
})

// ── 5. applyFilters ───────────────────────────────────────────────────────────

describe('applyFilters', () => {
  const bim = {
    elements: [
      { id: 'e1', category: 'Wall', level: '1' },
      { id: 'e2', category: 'Door', level: '1' },
    ],
  }

  it('returns all elements when no filters', () => {
    const v = defaultView('plan', 'f1')
    const result = applyFilters(v, bim)
    expect(result).toHaveLength(2)
  })

  it('filters by equality expression', () => {
    const v = { ...defaultView('plan', 'f1'), filters: [{ expr: "category=='Wall'" }] }
    const result = applyFilters(v, bim)
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('e1')
  })
})
