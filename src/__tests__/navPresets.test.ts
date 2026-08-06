import { describe, it, expect } from 'vitest'
import {
  resolveButtons,
  NAV_PRESET_LIST,
  NAV_PRESET_IDS,
  DEFAULT_NAV_PRESET,
} from '../lib/navPresets.js'

const NONE = {}
const ALT = { alt: true }
const SHIFT = { shift: true }
const CTRL = { ctrl: true }

describe('navigation presets', () => {
  it('offers the six styles', () => {
    expect(NAV_PRESET_IDS).toEqual([
      'standard', 'blender', 'maya', 'revit', 'solidworks', 'touchpad',
    ])
    // Every preset documents its own bindings for the UI.
    for (const p of NAV_PRESET_LIST) {
      expect(p.name).toBeTruthy()
      expect(p.rows.length).toBeGreaterThan(2)
    }
  })

  it('standard: left orbits, right pans, unaffected by modifiers', () => {
    expect(resolveButtons('standard', NONE)).toEqual({
      LEFT: 'rotate', MIDDLE: 'dolly', RIGHT: 'pan',
    })
    expect(resolveButtons('standard', ALT)).toEqual(resolveButtons('standard', NONE))
  })

  it('blender: MMB orbits, shift+MMB pans, ctrl+MMB zooms', () => {
    expect(resolveButtons('blender', NONE).MIDDLE).toBe('rotate')
    expect(resolveButtons('blender', SHIFT).MIDDLE).toBe('pan')
    expect(resolveButtons('blender', CTRL).MIDDLE).toBe('dolly')
    // Left stays free so it can select, as in Blender.
    expect(resolveButtons('blender', NONE).LEFT).toBeNull()
  })

  it('maya: nothing navigates unless Alt is held', () => {
    expect(resolveButtons('maya', NONE)).toEqual({ LEFT: null, MIDDLE: null, RIGHT: null })
    expect(resolveButtons('maya', ALT)).toEqual({
      LEFT: 'rotate', MIDDLE: 'pan', RIGHT: 'dolly',
    })
  })

  it('revit: MMB pans, shift+MMB orbits', () => {
    expect(resolveButtons('revit', NONE).MIDDLE).toBe('pan')
    expect(resolveButtons('revit', SHIFT).MIDDLE).toBe('rotate')
  })

  it('solidworks: MMB rotates, ctrl+MMB pans, shift+MMB zooms', () => {
    expect(resolveButtons('solidworks', NONE).MIDDLE).toBe('rotate')
    expect(resolveButtons('solidworks', CTRL).MIDDLE).toBe('pan')
    expect(resolveButtons('solidworks', SHIFT).MIDDLE).toBe('dolly')
  })

  it('touchpad: left orbits, shift+left pans (no middle button needed)', () => {
    expect(resolveButtons('touchpad', NONE).LEFT).toBe('rotate')
    expect(resolveButtons('touchpad', SHIFT).LEFT).toBe('pan')
  })

  it('falls back to the default for an unknown id rather than throwing', () => {
    expect(resolveButtons('bogus-from-old-localstorage', NONE)).toEqual(
      resolveButtons(DEFAULT_NAV_PRESET, NONE),
    )
  })

  it('never leaves the left button navigating in the Alt/MMB-gated styles', () => {
    // These four are the styles where left-click must stay a pure select — if a
    // preset bound LEFT to rotate, click-to-select would still work but every
    // stray drag would spin the model, which is exactly what users switch away
    // from these tools' defaults to avoid.
    for (const id of ['blender', 'maya', 'revit', 'solidworks']) {
      expect(resolveButtons(id, NONE).LEFT).toBeNull()
    }
  })
})
