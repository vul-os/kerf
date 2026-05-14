import { describe, it, expect } from 'vitest'
import {
  setPadMaskOverride,
  setPadPasteOverride,
  getEffectivePadMask,
  getEffectivePadPaste,
  validatePadOverrides,
} from './padOverrides.js'

const BOARD_DEFAULTS = { mask_expansion_mm: 0.05, paste_scale: 1.0 }

function makePad(overrides = {}) {
  return {
    type: 'pcb_smtpad',
    pcb_smtpad_id: 'p1',
    x: 10,
    y: 20,
    width: 2,
    height: 3,
    ...overrides,
  }
}

describe('setPadMaskOverride', () => {
  it('sets expansion_mm on pad', () => {
    const pad = makePad()
    setPadMaskOverride(pad, 0.1)
    expect(pad.mask_override.expansion_mm).toBe(0.1)
  })

  it('overwrites previous mask_override', () => {
    const pad = makePad()
    setPadMaskOverride(pad, 0.1)
    setPadMaskOverride(pad, 0.2)
    expect(pad.mask_override.expansion_mm).toBe(0.2)
  })
})

describe('setPadPasteOverride', () => {
  it('accepts a number as scale', () => {
    const pad = makePad()
    setPadPasteOverride(pad, 0.8)
    expect(pad.paste_override.scale).toBe(0.8)
  })

  it('accepts an object with scale', () => {
    const pad = makePad()
    setPadPasteOverride(pad, { scale: 0.9 })
    expect(pad.paste_override.scale).toBe(0.9)
  })

  it('accepts an object with offset_mm', () => {
    const pad = makePad()
    setPadPasteOverride(pad, { offset_mm: 0.05 })
    expect(pad.paste_override.offset_mm).toBe(0.05)
  })

  it('accepts an object with polygon', () => {
    const pad = makePad()
    const poly = [[0, 0], [1, 0], [1, 1]]
    setPadPasteOverride(pad, { polygon: poly })
    expect(pad.paste_override.polygon).toEqual(poly)
  })
})

describe('getEffectivePadMask', () => {
  it('returns 4-corner polygon', () => {
    const pad = makePad()
    const mask = getEffectivePadMask(pad, BOARD_DEFAULTS)
    expect(mask).toHaveLength(4)
  })

  it('uses board default expansion when no override', () => {
    const pad = makePad()
    const mask = getEffectivePadMask(pad, BOARD_DEFAULTS)
    expect(mask[0][0]).toBeCloseTo(10 - 1 - 0.05)
    expect(mask[0][1]).toBeCloseTo(20 - 1.5 - 0.05)
  })

  it('uses pad override expansion over board default', () => {
    const pad = makePad()
    setPadMaskOverride(pad, 0.2)
    const mask = getEffectivePadMask(pad, BOARD_DEFAULTS)
    expect(mask[0][0]).toBeCloseTo(10 - 1 - 0.2)
    expect(mask[0][1]).toBeCloseTo(20 - 1.5 - 0.2)
  })

  it('uses 0 expansion when board_defaults is empty', () => {
    const pad = makePad()
    const mask = getEffectivePadMask(pad, {})
    expect(mask[0][0]).toBeCloseTo(10 - 1)
    expect(mask[0][1]).toBeCloseTo(20 - 1.5)
  })

  it('handles round pad (pad_diameter)', () => {
    const pad = { pcb_smtpad_id: 'r1', x: 5, y: 5, pad_diameter: 4 }
    const mask = getEffectivePadMask(pad, BOARD_DEFAULTS)
    expect(mask).toHaveLength(4)
    expect(mask[0][0]).toBeCloseTo(5 - 2 - 0.05)
  })
})

describe('getEffectivePadPaste', () => {
  it('returns 4-corner polygon', () => {
    const pad = makePad()
    const paste = getEffectivePadPaste(pad, BOARD_DEFAULTS)
    expect(paste).toHaveLength(4)
  })

  it('uses board default scale when no override', () => {
    const pad = makePad()
    const paste = getEffectivePadPaste(pad, BOARD_DEFAULTS)
    expect(paste[0][0]).toBeCloseTo(10 - 1)
    expect(paste[0][1]).toBeCloseTo(20 - 1.5)
  })

  it('uses pad override scale over board default', () => {
    const pad = makePad()
    setPadPasteOverride(pad, 0.5)
    const paste = getEffectivePadPaste(pad, BOARD_DEFAULTS)
    expect(paste[0][0]).toBeCloseTo(10 - 0.5)
    expect(paste[0][1]).toBeCloseTo(20 - 0.75)
  })

  it('returns custom polygon when provided', () => {
    const pad = makePad()
    const customPoly = [[0, 0], [2, 0], [2, 2], [0, 2]]
    setPadPasteOverride(pad, { polygon: customPoly })
    const paste = getEffectivePadPaste(pad, BOARD_DEFAULTS)
    expect(paste).toEqual(customPoly)
  })

  it('applies offset_mm', () => {
    const pad = makePad()
    setPadPasteOverride(pad, { scale: 1.0, offset_mm: 0.1 })
    const paste = getEffectivePadPaste(pad, BOARD_DEFAULTS)
    expect(paste[0][0]).toBeCloseTo(10 - 1 + 0.1)
    expect(paste[0][1]).toBeCloseTo(20 - 1.5 + 0.1)
  })
})

describe('validatePadOverrides', () => {
  it('returns empty array for valid pad', () => {
    const pad = makePad()
    expect(validatePadOverrides(pad)).toHaveLength(0)
  })

  it('returns error for null pad', () => {
    const errors = validatePadOverrides(null)
    expect(errors).toContain('pad is required')
  })

  it('returns error for negative mask expansion', () => {
    const pad = makePad()
    setPadMaskOverride(pad, -0.1)
    const errors = validatePadOverrides(pad)
    expect(errors.some((e) => e.includes('non-negative'))).toBe(true)
  })

  it('returns error for negative paste scale', () => {
    const pad = makePad()
    setPadPasteOverride(pad, -0.5)
    const errors = validatePadOverrides(pad)
    expect(errors.some((e) => e.includes('non-negative'))).toBe(true)
  })

  it('returns error for invalid polygon', () => {
    const pad = makePad()
    setPadPasteOverride(pad, { polygon: [[0, 0]] })
    const errors = validatePadOverrides(pad)
    expect(errors.some((e) => e.includes('at least 3 points'))).toBe(true)
  })

  it('accepts valid mask_override only', () => {
    const pad = makePad()
    setPadMaskOverride(pad, 0.1)
    const errors = validatePadOverrides(pad)
    expect(errors).toHaveLength(0)
  })

  it('accepts valid paste_override only', () => {
    const pad = makePad()
    setPadPasteOverride(pad, 0.8)
    const errors = validatePadOverrides(pad)
    expect(errors).toHaveLength(0)
  })

  it('accepts both overrides', () => {
    const pad = makePad()
    setPadMaskOverride(pad, 0.1)
    setPadPasteOverride(pad, 0.8)
    const errors = validatePadOverrides(pad)
    expect(errors).toHaveLength(0)
  })
})