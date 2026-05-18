import { describe, it, expect } from 'vitest'
import {
  parseFEMResult,
  availableFields,
  pickColorConfig,
  fieldLabel,
  fieldUnit,
  extractScalars,
  normaliseScalars,
  FIELD_DISPLACEMENT,
  FIELD_VONMISES,
  FIELD_TEMPERATURE,
  FIELD_MODAL,
} from './femResults.js'

// ── fixture data ──────────────────────────────────────────────────────────────

const MINIMAL_RAW = {
  max_vonmises_stress: 1e6,
  max_displacement: 0.005,
  displacement: {
    node_displacements: [
      { ux: 0.001, uy: 0.002, uz: 0.003 },
      { ux: 0.002, uy: 0.001, uz: 0.000, mag: 0.00224 },
    ],
    stresses: [1e5, 5e5, 1e6],
  },
  fos: 2.5,
  frequencies: [120.5, 250.3, 480.1],
  mode_shapes: [
    [{ ux: 0.01, uy: 0.0, uz: 0.0 }, { ux: 0.02, uy: 0.01, uz: 0.0 }],
  ],
  temperatures: [293, 350, 420],
  warnings: ['mesh coarse'],
  errors: [],
}

// ── parseFEMResult ─────────────────────────────────────────────────────────────

describe('parseFEMResult', () => {
  it('throws for non-object input', () => {
    expect(() => parseFEMResult(null)).toThrow(TypeError)
    expect(() => parseFEMResult(42)).toThrow(TypeError)
    expect(() => parseFEMResult([])).toThrow(TypeError)
    expect(() => parseFEMResult('string')).toThrow(TypeError)
  })

  it('parses a minimal result without throwing', () => {
    expect(() => parseFEMResult(MINIMAL_RAW)).not.toThrow()
  })

  it('returns nodeDisplacements array with ux/uy/uz/mag', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    expect(r.nodeDisplacements).toHaveLength(2)
    expect(r.nodeDisplacements[0]).toMatchObject({ ux: 0.001, uy: 0.002, uz: 0.003 })
    expect(r.nodeDisplacements[0].mag).toBeCloseTo(Math.sqrt(0.001 ** 2 + 0.002 ** 2 + 0.003 ** 2), 5)
  })

  it('preserves explicit mag when provided', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    expect(r.nodeDisplacements[1].mag).toBeCloseTo(0.00224, 5)
  })

  it('returns stresses array', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    expect(r.stresses).toEqual([1e5, 5e5, 1e6])
  })

  it('returns temperatures', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    expect(r.temperatures).toEqual([293, 350, 420])
  })

  it('returns maxDisplacement from backend value', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    expect(r.maxDisplacement).toBe(0.005)
  })

  it('computes maxDisplacement from nodes when backend omits it', () => {
    const raw = { ...MINIMAL_RAW, max_displacement: undefined }
    const r = parseFEMResult(raw)
    // Computed from the two node displacements: both <= 0.00374..., second is 0.00224
    expect(r.maxDisplacement).toBeGreaterThan(0)
  })

  it('returns maxVonmises from backend value', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    expect(r.maxVonmises).toBe(1e6)
  })

  it('computes maxVonmises from stresses when backend omits it', () => {
    const raw = { ...MINIMAL_RAW, max_vonmises_stress: undefined }
    const r = parseFEMResult(raw)
    expect(r.maxVonmises).toBe(1e6)
  })

  it('returns maxTemperature and minTemperature', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    expect(r.maxTemperature).toBe(420)
    expect(r.minTemperature).toBe(293)
  })

  it('returns fos', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    expect(r.fos).toBe(2.5)
  })

  it('returns frequencies and modeShapes', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    expect(r.frequencies).toEqual([120.5, 250.3, 480.1])
    expect(r.modeShapes).toHaveLength(1)
  })

  it('returns warnings and errors arrays', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    expect(r.warnings).toEqual(['mesh coarse'])
    expect(r.errors).toEqual([])
  })

  it('handles fully empty input gracefully', () => {
    const r = parseFEMResult({})
    expect(r.nodeDisplacements).toEqual([])
    expect(r.stresses).toEqual([])
    expect(r.temperatures).toEqual([])
    expect(r.maxDisplacement).toBe(0)
    expect(r.maxVonmises).toBe(0)
    expect(r.fos).toBeNull()
  })

  it('handles missing displacement sub-object', () => {
    const r = parseFEMResult({ max_vonmises_stress: 500 })
    expect(r.nodeDisplacements).toEqual([])
    expect(r.stresses).toEqual([])
  })

  it('normalises malformed node displacement entries to zeros', () => {
    const raw = {
      displacement: {
        node_displacements: [null, undefined, {}, { ux: 'bad', uy: 1, uz: 0 }],
      },
    }
    const r = parseFEMResult(raw)
    expect(r.nodeDisplacements).toHaveLength(4)
    r.nodeDisplacements.forEach(d => {
      expect(typeof d.ux).toBe('number')
      expect(typeof d.mag).toBe('number')
    })
  })
})

// ── availableFields ───────────────────────────────────────────────────────────

describe('availableFields', () => {
  it('returns null-safe empty array for falsy input', () => {
    expect(availableFields(null)).toEqual([])
    expect(availableFields(undefined)).toEqual([])
  })

  it('returns all four fields for a complete result', () => {
    const r = parseFEMResult(MINIMAL_RAW)
    const fields = availableFields(r)
    expect(fields).toContain(FIELD_DISPLACEMENT)
    expect(fields).toContain(FIELD_VONMISES)
    expect(fields).toContain(FIELD_TEMPERATURE)
    expect(fields).toContain(FIELD_MODAL)
  })

  it('omits vonmises when stresses is empty', () => {
    const raw = { ...MINIMAL_RAW, displacement: { node_displacements: MINIMAL_RAW.displacement.node_displacements, stresses: [] } }
    const r = parseFEMResult(raw)
    expect(availableFields(r)).not.toContain(FIELD_VONMISES)
  })

  it('omits temperature when temperatures is empty', () => {
    const raw = { ...MINIMAL_RAW, temperatures: [] }
    const r = parseFEMResult(raw)
    expect(availableFields(r)).not.toContain(FIELD_TEMPERATURE)
  })

  it('omits modal when mode_shapes is empty', () => {
    const raw = { ...MINIMAL_RAW, mode_shapes: [] }
    const r = parseFEMResult(raw)
    expect(availableFields(r)).not.toContain(FIELD_MODAL)
  })
})

// ── pickColorConfig ───────────────────────────────────────────────────────────

describe('pickColorConfig', () => {
  const r = parseFEMResult(MINIMAL_RAW)

  it('returns scaleName, minValue, maxValue, label, unit, colorMode', () => {
    const cfg = pickColorConfig(r, FIELD_DISPLACEMENT)
    expect(cfg).toHaveProperty('scaleName')
    expect(cfg).toHaveProperty('minValue')
    expect(cfg).toHaveProperty('maxValue')
    expect(cfg).toHaveProperty('label')
    expect(cfg).toHaveProperty('unit')
    expect(cfg).toHaveProperty('colorMode')
  })

  it('displacement uses viridis by default', () => {
    expect(pickColorConfig(r, FIELD_DISPLACEMENT).scaleName).toBe('viridis')
  })

  it('vonmises uses plasma by default', () => {
    expect(pickColorConfig(r, FIELD_VONMISES).scaleName).toBe('plasma')
  })

  it('temperature uses coolwarm by default', () => {
    expect(pickColorConfig(r, FIELD_TEMPERATURE).scaleName).toBe('coolwarm')
  })

  it('modal uses jet by default', () => {
    expect(pickColorConfig(r, FIELD_MODAL).scaleName).toBe('jet')
  })

  it('respects explicit scaleName override', () => {
    const cfg = pickColorConfig(r, FIELD_VONMISES, 'viridis')
    expect(cfg.scaleName).toBe('viridis')
  })

  it('displacement colorMode is "displacement"', () => {
    expect(pickColorConfig(r, FIELD_DISPLACEMENT).colorMode).toBe('displacement')
  })

  it('vonmises colorMode is "vonmises"', () => {
    expect(pickColorConfig(r, FIELD_VONMISES).colorMode).toBe('vonmises')
  })

  it('temperature min/max span the temperature range', () => {
    const cfg = pickColorConfig(r, FIELD_TEMPERATURE)
    expect(cfg.minValue).toBe(293)
    expect(cfg.maxValue).toBe(420)
  })

  it('displacement maxValue equals result.maxDisplacement', () => {
    const cfg = pickColorConfig(r, FIELD_DISPLACEMENT)
    expect(cfg.maxValue).toBe(r.maxDisplacement)
  })
})

// ── fieldLabel / fieldUnit ────────────────────────────────────────────────────

describe('fieldLabel', () => {
  it('returns non-empty strings for all known fields', () => {
    for (const f of [FIELD_DISPLACEMENT, FIELD_VONMISES, FIELD_TEMPERATURE, FIELD_MODAL]) {
      expect(fieldLabel(f).length).toBeGreaterThan(0)
    }
  })

  it('falls back to the field name for unknown fields', () => {
    expect(fieldLabel('custom_field')).toBe('custom_field')
  })
})

describe('fieldUnit', () => {
  it('displacement unit is mm', () => {
    expect(fieldUnit(FIELD_DISPLACEMENT)).toBe('mm')
  })

  it('vonmises unit is MPa', () => {
    expect(fieldUnit(FIELD_VONMISES)).toBe('MPa')
  })

  it('temperature unit is K', () => {
    expect(fieldUnit(FIELD_TEMPERATURE)).toBe('K')
  })
})

// ── extractScalars ────────────────────────────────────────────────────────────

describe('extractScalars', () => {
  const r = parseFEMResult(MINIMAL_RAW)

  it('extracts displacement magnitudes', () => {
    const s = extractScalars(r, FIELD_DISPLACEMENT)
    expect(s).toHaveLength(2)
    s.forEach(v => expect(v).toBeGreaterThanOrEqual(0))
  })

  it('extracts stresses for vonmises', () => {
    const s = extractScalars(r, FIELD_VONMISES)
    expect(s).toEqual([1e5, 5e5, 1e6])
  })

  it('extracts temperatures', () => {
    const s = extractScalars(r, FIELD_TEMPERATURE)
    expect(s).toEqual([293, 350, 420])
  })

  it('extracts mode shape magnitudes', () => {
    const s = extractScalars(r, FIELD_MODAL, 0)
    expect(s).toHaveLength(2)
    s.forEach(v => expect(v).toBeGreaterThanOrEqual(0))
  })

  it('returns empty for out-of-range mode index', () => {
    expect(extractScalars(r, FIELD_MODAL, 99)).toEqual([])
  })
})

// ── normaliseScalars ──────────────────────────────────────────────────────────

describe('normaliseScalars', () => {
  it('maps [min, max] to [0, 1]', () => {
    const out = normaliseScalars([0, 50, 100], 0, 100)
    expect(out).toEqual([0, 0.5, 1])
  })

  it('clamps values outside [min, max]', () => {
    const out = normaliseScalars([-10, 110], 0, 100)
    expect(out[0]).toBe(0)
    expect(out[1]).toBe(1)
  })

  it('returns all-zero when range is 0', () => {
    expect(normaliseScalars([5, 5, 5], 5, 5)).toEqual([0, 0, 0])
  })
})
