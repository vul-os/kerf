/**
 * MicrofluidicsPanel.test.jsx — Pure-helper unit tests (no DOM, no fetch).
 *
 * Tests the exported helpers:
 *   fmtNum(n, digits?)    → formatted string
 *   classifyRegime(ca)    → 'squeezing' | 'dripping' | null
 *   buildPressureDropArgs(form) → tool args object
 *   buildDropletArgs(form)      → tool args object
 */
import { describe, it, expect } from 'vitest'
import {
  fmtNum,
  classifyRegime,
  buildPressureDropArgs,
  buildDropletArgs,
} from './MicrofluidicsPanel.jsx'

describe('fmtNum', () => {
  it('returns "—" for null', () => {
    expect(fmtNum(null)).toBe('—')
  })

  it('returns "—" for undefined', () => {
    expect(fmtNum(undefined)).toBe('—')
  })

  it('returns "—" for NaN', () => {
    expect(fmtNum(NaN)).toBe('—')
  })

  it('returns "0" for zero', () => {
    expect(fmtNum(0)).toBe('0')
  })

  it('uses exponential for large numbers', () => {
    const s = fmtNum(1.5e7)
    expect(s).toContain('e')
  })

  it('uses exponential for small numbers', () => {
    const s = fmtNum(1.5e-5)
    expect(s).toContain('e')
  })

  it('uses toPrecision for mid-range', () => {
    const s = fmtNum(123.456)
    expect(s).not.toContain('e')
    expect(parseFloat(s)).toBeCloseTo(123.456, 0)
  })

  it('respects custom digits', () => {
    const s = fmtNum(123.456, 3)
    expect(s.length).toBeLessThanOrEqual(8)
  })
})

describe('classifyRegime', () => {
  it('returns null for null Ca', () => {
    expect(classifyRegime(null)).toBeNull()
  })

  it('returns null for NaN Ca', () => {
    expect(classifyRegime(NaN)).toBeNull()
  })

  it('returns squeezing for Ca < 0.01', () => {
    expect(classifyRegime(0.001)).toBe('squeezing')
    expect(classifyRegime(4.2e-5)).toBe('squeezing')
  })

  it('returns dripping for Ca >= 0.01', () => {
    expect(classifyRegime(0.01)).toBe('dripping')
    expect(classifyRegime(0.1)).toBe('dripping')
  })
})

describe('buildPressureDropArgs', () => {
  it('builds rectangular args', () => {
    const form = {
      shape: 'rectangular',
      length_um: '1000',
      flow_rate_ul_min: '2',
      width_um: '100',
      height_um: '50',
    }
    const args = buildPressureDropArgs(form)
    expect(args.shape).toBe('rectangular')
    expect(args.length_um).toBe(1000)
    expect(args.flow_rate_ul_min).toBe(2)
    expect(args.width_um).toBe(100)
    expect(args.height_um).toBe(50)
  })

  it('builds trapezoidal args', () => {
    const form = {
      shape: 'trapezoidal',
      length_um: '500',
      flow_rate_ul_min: '1',
      width_top_um: '120',
      width_bottom_um: '80',
      trap_height_um: '50',
    }
    const args = buildPressureDropArgs(form)
    expect(args.shape).toBe('trapezoidal')
    expect(args.width_top_um).toBe(120)
    expect(args.width_bottom_um).toBe(80)
    expect(args.trap_height_um).toBe(50)
    // rectangular-specific fields should not appear
    expect(args.width_um).toBeUndefined()
  })

  it('builds semicircular args', () => {
    const form = {
      shape: 'semicircular',
      length_um: '500',
      flow_rate_ul_min: '1',
      radius_um: '25',
    }
    const args = buildPressureDropArgs(form)
    expect(args.shape).toBe('semicircular')
    expect(args.radius_um).toBe(25)
    expect(args.width_um).toBeUndefined()
  })
})

describe('buildDropletArgs', () => {
  it('builds T-junction args', () => {
    const form = {
      geometry: 't_junction',
      q_continuous_ul_min: '2',
      q_dispersed_ul_min: '0.5',
      channel_width_um: '100',
      channel_height_um: '100',
      viscosity_pa_s: '0.001',
      surface_tension: '0.04',
    }
    const args = buildDropletArgs(form)
    expect(args.geometry).toBe('t_junction')
    expect(args.q_continuous_ul_min).toBe(2)
    expect(args.q_dispersed_ul_min).toBe(0.5)
    expect(args.channel_width_um).toBe(100)
    expect(args.channel_height_um).toBe(100)
    expect(args.viscosity_continuous_pa_s).toBeCloseTo(0.001)
    expect(args.surface_tension_n_per_m).toBeCloseTo(0.04)
  })

  it('builds flow-focusing args', () => {
    const form = {
      geometry: 'flow_focusing',
      q_continuous_ul_min: '3',
      q_dispersed_ul_min: '1',
      channel_width_um: '150',
      channel_height_um: '80',
      viscosity_pa_s: '',
      surface_tension: '',
    }
    const args = buildDropletArgs(form)
    expect(args.geometry).toBe('flow_focusing')
    expect(args.channel_width_um).toBe(150)
    // empty optional fields should be omitted / NaN (not added as numbers)
  })

  it('omits optional fields when blank', () => {
    const form = {
      geometry: 't_junction',
      q_continuous_ul_min: '2',
      q_dispersed_ul_min: '0.5',
      channel_width_um: '100',
      channel_height_um: '100',
      viscosity_pa_s: '',
      surface_tension: '',
    }
    const args = buildDropletArgs(form)
    // viscosity_pa_s empty → parseFloat('') = NaN → falsy, so not added
    expect(Number.isNaN(args.viscosity_continuous_pa_s) || args.viscosity_continuous_pa_s == null).toBe(true)
  })
})
