/**
 * dcc.test.jsx — Registry wiring + fragment shape tests for DCC panels.
 *
 * Tests
 * -----
 * 1.  dcc.js default export is an array of 3 entries.
 * 2.  Every entry has id, kinds, exts, load (function), label.
 * 3.  sculpt_studio entry: kind 'sculpt_studio', ext '.sculpt'.
 * 4.  animation_clip entry: kind 'animation_clip', ext '.anim'.
 * 5.  geometry_nodes entry: kind 'geometry_nodes', ext '.geonodes'.
 * 6.  Every entry load() returns a Promise (lazy import).
 * 7.  No duplicate ids in the fragment.
 * 8.  resolvePanelEntry resolves each kind from the live registry.
 * 9.  resolvePanelEntry resolves each extension.
 * 10. resolvePanelEntry returns null for an unknown kind.
 */

import { describe, it, expect } from 'vitest'
import DCC_ENTRIES from '../dcc.js'
import { resolvePanelEntry } from '../../panelRegistry.js'

// ---------------------------------------------------------------------------
// 1–7: Fragment shape
// ---------------------------------------------------------------------------

describe('dcc.js fragment — shape', () => {
  it('exports an array of 3 entries', () => {
    expect(Array.isArray(DCC_ENTRIES)).toBe(true)
    expect(DCC_ENTRIES).toHaveLength(3)
  })

  it('every entry has id, kinds, exts, load (function), label', () => {
    for (const e of DCC_ENTRIES) {
      expect(typeof e.id).toBe('string')
      expect(e.id).toBeTruthy()
      expect(Array.isArray(e.kinds)).toBe(true)
      expect(e.kinds.length).toBeGreaterThan(0)
      expect(Array.isArray(e.exts)).toBe(true)
      expect(e.exts.length).toBeGreaterThan(0)
      expect(typeof e.load).toBe('function')
      expect(typeof e.label).toBe('string')
      expect(e.label).toBeTruthy()
    }
  })

  it('sculpt_studio entry has kind sculpt_studio and ext .sculpt', () => {
    const e = DCC_ENTRIES.find((x) => x.id === 'sculpt_studio')
    expect(e).toBeTruthy()
    expect(e.kinds).toContain('sculpt_studio')
    expect(e.exts).toContain('.sculpt')
  })

  it('animation_clip entry has kind animation_clip and ext .anim', () => {
    const e = DCC_ENTRIES.find((x) => x.id === 'animation_clip')
    expect(e).toBeTruthy()
    expect(e.kinds).toContain('animation_clip')
    expect(e.exts).toContain('.anim')
  })

  it('geometry_nodes entry has kind geometry_nodes and ext .geonodes', () => {
    const e = DCC_ENTRIES.find((x) => x.id === 'geometry_nodes')
    expect(e).toBeTruthy()
    expect(e.kinds).toContain('geometry_nodes')
    expect(e.exts).toContain('.geonodes')
  })

  it('every entry load() returns a Promise-like (thenable)', () => {
    for (const e of DCC_ENTRIES) {
      const result = e.load()
      expect(typeof result.then).toBe('function')
    }
  })

  it('no duplicate ids in the fragment', () => {
    const ids = DCC_ENTRIES.map((e) => e.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

// ---------------------------------------------------------------------------
// 8–10: Registry resolution via panelRegistry.js
// ---------------------------------------------------------------------------

describe('resolvePanelEntry — DCC kinds', () => {
  const KIND_CASES = [
    { kind: 'sculpt_studio',  expectedId: 'sculpt_studio' },
    { kind: 'animation_clip', expectedId: 'animation_clip' },
    { kind: 'geometry_nodes', expectedId: 'geometry_nodes' },
  ]

  for (const { kind, expectedId } of KIND_CASES) {
    it(`kind '${kind}' resolves to id '${expectedId}'`, () => {
      const entry = resolvePanelEntry({ kind })
      expect(entry).not.toBeNull()
      expect(entry.id).toBe(expectedId)
    })

    it(`kind '${kind}' entry has a lazy Panel component`, () => {
      const entry = resolvePanelEntry({ kind })
      expect(entry).not.toBeNull()
      // lazy() returns an object with _payload and $$typeof
      expect(entry.Panel).toBeTruthy()
    })
  }

  const EXT_CASES = [
    { name: 'my_sculpt.sculpt',     expectedId: 'sculpt_studio' },
    { name: 'take001.anim',         expectedId: 'animation_clip' },
    { name: 'tree_gen.geonodes',    expectedId: 'geometry_nodes' },
  ]

  for (const { name, expectedId } of EXT_CASES) {
    it(`extension match for '${name}' → id '${expectedId}'`, () => {
      const entry = resolvePanelEntry({ kind: '', name })
      expect(entry).not.toBeNull()
      expect(entry.id).toBe(expectedId)
    })
  }

  it('returns null for unknown kind', () => {
    expect(resolvePanelEntry({ kind: 'totally_unknown_dcc_xyz' })).toBeNull()
  })

  it('returns null when file is null', () => {
    expect(resolvePanelEntry(null)).toBeNull()
  })
})
