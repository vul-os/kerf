import { describe, it, expect } from 'vitest'
import { is3dmFile, splitImported3dmTree } from './rhino3dm.js'

// ── is3dmFile ──────────────────────────────────────────────────────────────

describe('is3dmFile', () => {
  it('returns true for .3dm extension', () => {
    expect(is3dmFile('model.3dm')).toBe(true)
  })

  it('returns true for uppercase .3DM', () => {
    expect(is3dmFile('ARCH.3DM')).toBe(true)
  })

  it('returns true for mixed-case .3Dm', () => {
    expect(is3dmFile('house.3Dm')).toBe(true)
  })

  it('returns false for .step', () => {
    expect(is3dmFile('part.step')).toBe(false)
  })

  it('returns false for empty string', () => {
    expect(is3dmFile('')).toBe(false)
  })

  it('returns false for non-string (null)', () => {
    expect(is3dmFile(null)).toBe(false)
  })

  it('returns false for non-string (number)', () => {
    expect(is3dmFile(42)).toBe(false)
  })

  it('returns false for filename with .3dm in the middle', () => {
    expect(is3dmFile('file.3dm.bak')).toBe(false)
  })
})

// ── splitImported3dmTree ───────────────────────────────────────────────────

describe('splitImported3dmTree', () => {
  it('returns empty folder_layout for empty array', () => {
    const { folder_layout } = splitImported3dmTree([])
    expect(Object.keys(folder_layout)).toHaveLength(0)
  })

  it('returns empty folder_layout for non-array input', () => {
    const { folder_layout } = splitImported3dmTree(null)
    expect(Object.keys(folder_layout)).toHaveLength(0)
  })

  it('groups files by rhino_layer', () => {
    const files = [
      { name: 'wall.feature', kind: 'feature', content: { rhino_layer: 'Walls' } },
      { name: 'floor.feature', kind: 'feature', content: { rhino_layer: 'Floors' } },
      { name: 'slab.feature', kind: 'feature', content: { rhino_layer: 'Floors' } },
    ]
    const { folder_layout } = splitImported3dmTree(files)
    expect(Object.keys(folder_layout).sort()).toEqual(['Floors', 'Walls'])
    expect(folder_layout['Floors']).toHaveLength(2)
    expect(folder_layout['Walls']).toHaveLength(1)
  })

  it('puts files without a rhino_layer in _ungrouped', () => {
    const files = [
      { name: 'mystery.mesh', kind: 'mesh' },
      { name: 'orphan.sketch', kind: 'sketch', content: {} },
    ]
    const { folder_layout } = splitImported3dmTree(files)
    expect(folder_layout['_ungrouped']).toHaveLength(2)
  })

  it('applies the correct Kerf extension for known kinds', () => {
    const files = [
      { name: 'body', kind: 'feature', content: { rhino_layer: 'L1' } },
      { name: 'profile', kind: 'sketch', content: { rhino_layer: 'L1' } },
      { name: 'surface', kind: 'surf', content: { rhino_layer: 'L1' } },
      { name: 'hull', kind: 'mesh', content: { rhino_layer: 'L1' } },
      { name: 'origin', kind: 'point', content: { rhino_layer: 'L1' } },
    ]
    const { folder_layout } = splitImported3dmTree(files)
    const names = folder_layout['L1'].map((f) => f.name)
    expect(names).toContain('body.feature')
    expect(names).toContain('profile.sketch')
    expect(names).toContain('surface.surf')
    expect(names).toContain('hull.mesh')
    expect(names).toContain('origin.point')
  })

  it('path includes the layer folder', () => {
    const files = [{ name: 'beam.feature', kind: 'feature', content: { rhino_layer: 'Structure' } }]
    const { folder_layout } = splitImported3dmTree(files)
    expect(folder_layout['Structure'][0].path).toBe('/Structure/beam.feature')
  })

  it('sanitises layer names with path separators', () => {
    const files = [{ name: 'col.feature', kind: 'feature', content: { rhino_layer: 'A/B/C' } }]
    const { folder_layout } = splitImported3dmTree(files)
    const keys = Object.keys(folder_layout)
    expect(keys[0]).toBe('A_B_C')
  })

  it('skips null or non-object entries gracefully', () => {
    const files = [null, undefined, 42, { name: 'ok.mesh', kind: 'mesh' }]
    const { folder_layout } = splitImported3dmTree(files)
    expect(folder_layout['_ungrouped']).toHaveLength(1)
  })

  it('strips existing extension before appending canonical one', () => {
    // Incoming name already has .feature; should not double-up
    const files = [{ name: 'part.feature', kind: 'feature', content: { rhino_layer: 'X' } }]
    const { folder_layout } = splitImported3dmTree(files)
    expect(folder_layout['X'][0].name).toBe('part.feature')
  })
})
