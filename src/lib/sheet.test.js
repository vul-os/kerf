import { describe, it, expect } from 'vitest'
import {
  defaultSheet,
  validateSheet,
  addViewport,
  removeViewport,
  moveViewport,
  addRevisionCloud,
  SHEET_SIZES_MM,
  VALID_SIZES,
} from './sheet.js'

// ── defaultSheet ──────────────────────────────────────────────────────────────

describe('defaultSheet', () => {
  it('returns a valid sheet document', () => {
    const s = defaultSheet('A-101 Floor Plans', 'A-101', 'A1')
    expect(s.version).toBe(1)
    expect(s.name).toBe('A-101 Floor Plans')
    expect(s.sheet_number).toBe('A-101')
    expect(s.size).toBe('A1')
    expect(s.orientation).toBe('landscape')
    expect(s.viewports).toEqual([])
    expect(s.revision_clouds).toEqual([])
  })

  it('assigns unique ids', () => {
    const a = defaultSheet('S1', 'S-001', 'A3')
    const b = defaultSheet('S2', 'S-002', 'A3')
    expect(a.id).not.toBe(b.id)
  })
})

// ── SHEET_SIZES_MM ────────────────────────────────────────────────────────────

describe('SHEET_SIZES_MM', () => {
  it('has expected ISO sizes', () => {
    expect(SHEET_SIZES_MM.A0).toEqual([841, 1189])
    expect(SHEET_SIZES_MM.A4).toEqual([210, 297])
  })

  it('has expected ANSI sizes', () => {
    expect(SHEET_SIZES_MM.ANSI_A).toEqual([216, 279])
    expect(SHEET_SIZES_MM.ANSI_E).toEqual([864, 1118])
  })

  it('covers all VALID_SIZES', () => {
    for (const sz of VALID_SIZES) {
      expect(SHEET_SIZES_MM[sz]).toBeDefined()
    }
  })
})

// ── validateSheet ─────────────────────────────────────────────────────────────

describe('validateSheet', () => {
  it('passes a minimal valid sheet', () => {
    const s = defaultSheet('Plans', 'A-100', 'A1')
    expect(validateSheet(s).ok).toBe(true)
  })

  it('rejects missing name', () => {
    const s = { ...defaultSheet('Plans', 'A-100', 'A1'), name: '' }
    const { ok, errors } = validateSheet(s)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('name'))).toBe(true)
  })

  it('rejects unknown size', () => {
    const s = { ...defaultSheet('Plans', 'A-100', 'A1'), size: 'B5' }
    const { ok, errors } = validateSheet(s)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('size'))).toBe(true)
  })

  it('rejects unknown orientation', () => {
    const s = { ...defaultSheet('Plans', 'A-100', 'A1'), orientation: 'diagonal' }
    const { ok, errors } = validateSheet(s)
    expect(ok).toBe(false)
    expect(errors.some(e => e.includes('orientation'))).toBe(true)
  })

  it('rejects null input', () => {
    expect(validateSheet(null).ok).toBe(false)
  })
})

// ── addViewport / removeViewport / moveViewport ───────────────────────────────

describe('addViewport', () => {
  it('appends a viewport with auto id', () => {
    let s = defaultSheet('Plans', 'A-100', 'A1')
    s = addViewport(s, 'view-uuid-1', [50, 50], 0.02, 'Level 1')
    expect(s.viewports).toHaveLength(1)
    expect(s.viewports[0].view_file_id).toBe('view-uuid-1')
    expect(s.viewports[0].scale).toBe(0.02)
    expect(s.viewports[0].id).toBeTruthy()
  })

  it('throws on missing view_file_id', () => {
    const s = defaultSheet('Plans', 'A-100', 'A1')
    expect(() => addViewport(s, '', [50, 50], 0.02)).toThrow()
  })

  it('throws on invalid scale', () => {
    const s = defaultSheet('Plans', 'A-100', 'A1')
    expect(() => addViewport(s, 'view-1', [0, 0], -1)).toThrow()
  })

  it('is immutable — original unchanged', () => {
    const s = defaultSheet('Plans', 'A-100', 'A1')
    addViewport(s, 'v1', [0, 0], 0.01)
    expect(s.viewports).toHaveLength(0)
  })
})

describe('removeViewport', () => {
  it('removes by id', () => {
    let s = defaultSheet('Plans', 'A-100', 'A1')
    s = addViewport(s, 'v1', [0, 0], 0.02, 'V1')
    s = addViewport(s, 'v2', [200, 0], 0.02, 'V2')
    const idToRemove = s.viewports[0].id
    s = removeViewport(s, idToRemove)
    expect(s.viewports).toHaveLength(1)
    expect(s.viewports[0].title).toBe('V2')
  })
})

describe('moveViewport', () => {
  it('updates position', () => {
    let s = defaultSheet('Plans', 'A-100', 'A1')
    s = addViewport(s, 'v1', [0, 0], 0.02)
    const id = s.viewports[0].id
    s = moveViewport(s, id, [100, 200])
    expect(s.viewports[0].position).toEqual([100, 200])
  })

  it('throws on bad position', () => {
    const s = defaultSheet('Plans', 'A-100', 'A1')
    expect(() => moveViewport(s, 'x', [100])).toThrow()
  })
})

// ── addRevisionCloud ──────────────────────────────────────────────────────────

describe('addRevisionCloud', () => {
  it('adds a cloud with auto id', () => {
    let s = defaultSheet('Plans', 'A-100', 'A1')
    s = addRevisionCloud(s, [[0,0],[100,0],[100,100],[0,100]], 'A', 'wall updated')
    expect(s.revision_clouds).toHaveLength(1)
    expect(s.revision_clouds[0].revision).toBe('A')
    expect(s.revision_clouds[0].id).toBeTruthy()
  })

  it('throws when polygon has fewer than 3 points', () => {
    const s = defaultSheet('Plans', 'A-100', 'A1')
    expect(() => addRevisionCloud(s, [[0,0],[1,1]], 'B')).toThrow()
  })
})
