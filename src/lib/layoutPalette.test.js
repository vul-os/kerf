// layoutPalette.test.js — Vitest unit tests for PDK layer palette.

import { describe, it, expect } from 'vitest'
import {
  sky130Palette,
  gf180Palette,
  getPaletteColor,
  defaultLayerColor,
} from './layoutPalette.js'

// ── SKY130 palette coverage ───────────────────────────────────────────────────

describe('sky130Palette', () => {
  it('has at least 30 entries', () => {
    expect(Object.keys(sky130Palette).length).toBeGreaterThanOrEqual(30)
  })

  it('every entry has a fill string', () => {
    for (const [name, entry] of Object.entries(sky130Palette)) {
      expect(typeof entry.fill, `${name}.fill`).toBe('string')
      expect(entry.fill.length, `${name}.fill non-empty`).toBeGreaterThan(0)
    }
  })

  it('every entry has a stroke string', () => {
    for (const [name, entry] of Object.entries(sky130Palette)) {
      expect(typeof entry.stroke, `${name}.stroke`).toBe('string')
      expect(entry.stroke.length, `${name}.stroke non-empty`).toBeGreaterThan(0)
    }
  })

  it('contains expected core layers', () => {
    const required = ['nwell', 'diff', 'poly', 'licon1', 'met1', 'via1', 'met2', 'via2', 'met3', 'via3', 'met4', 'via4', 'met5']
    for (const layer of required) {
      expect(sky130Palette[layer], `missing SKY130 layer: ${layer}`).toBeDefined()
    }
  })

  it('met1 has numeric layerNum and datatype', () => {
    expect(typeof sky130Palette.met1.layerNum).toBe('number')
    expect(typeof sky130Palette.met1.datatype).toBe('number')
  })

  it('li1 is present (local interconnect)', () => {
    expect(sky130Palette.li1).toBeDefined()
  })

  it('pwell is present', () => {
    expect(sky130Palette.pwell).toBeDefined()
  })

  it('pad layer is present', () => {
    expect(sky130Palette.pad).toBeDefined()
  })
})

// ── GF180MCU palette coverage ─────────────────────────────────────────────────

describe('gf180Palette', () => {
  it('has at least 20 entries', () => {
    expect(Object.keys(gf180Palette).length).toBeGreaterThanOrEqual(20)
  })

  it('contains metal layers 1-5', () => {
    for (const l of ['metal1', 'metal2', 'metal3', 'metal4', 'metal5']) {
      expect(gf180Palette[l], `missing GF180MCU layer: ${l}`).toBeDefined()
    }
  })

  it('contains comp (active) layer', () => {
    expect(gf180Palette.comp).toBeDefined()
  })

  it('fill strings look like rgba(...)', () => {
    for (const [name, entry] of Object.entries(gf180Palette)) {
      expect(entry.fill, `${name}.fill should start with rgba`).toMatch(/^rgba\(/)
    }
  })
})

// ── getPaletteColor ───────────────────────────────────────────────────────────

describe('getPaletteColor', () => {
  it('returns fill + stroke by string key', () => {
    const c = getPaletteColor(sky130Palette, 'met1')
    expect(c).not.toBeNull()
    expect(typeof c.fill).toBe('string')
    expect(typeof c.stroke).toBe('string')
  })

  it('returns null for unknown string key', () => {
    expect(getPaletteColor(sky130Palette, 'nonexistent_layer')).toBeNull()
  })

  it('returns correct entry by { layerNum, datatype }', () => {
    // met1 in SKY130: layerNum=68, datatype=20
    const c = getPaletteColor(sky130Palette, { layerNum: 68, datatype: 20 })
    expect(c).not.toBeNull()
    expect(c.fill).toBe(sky130Palette.met1.fill)
  })

  it('returns null for unmatched { layerNum, datatype }', () => {
    const c = getPaletteColor(sky130Palette, { layerNum: 9999, datatype: 9999 })
    expect(c).toBeNull()
  })

  it('works with gf180 palette by string key', () => {
    const c = getPaletteColor(gf180Palette, 'metal2')
    expect(c).not.toBeNull()
    expect(typeof c.fill).toBe('string')
  })
})

// ── defaultLayerColor ─────────────────────────────────────────────────────────

describe('defaultLayerColor', () => {
  it('is defined and has fill + stroke', () => {
    expect(defaultLayerColor).toBeDefined()
    expect(typeof defaultLayerColor.fill).toBe('string')
    expect(typeof defaultLayerColor.stroke).toBe('string')
  })
})
