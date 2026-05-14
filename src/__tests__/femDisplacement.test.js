import { describe, it, expect } from 'vitest'
import {
  applyDisplacementScale,
  displacementMagnitudes,
  scalarToRGB,
  buildDisplacementColors,
} from '../lib/femDisplacement.js'

describe('applyDisplacementScale', () => {
  it('returns original positions when scale is 0', () => {
    const pos = new Float32Array([1, 2, 3, 4, 5, 6])
    const disp = [{ ux: 10, uy: 20, uz: 30 }, { ux: 5, uy: 5, uz: 5 }]
    const out = applyDisplacementScale(pos, disp, 0)
    expect(out[0]).toBeCloseTo(1)
    expect(out[1]).toBeCloseTo(2)
    expect(out[2]).toBeCloseTo(3)
  })

  it('applies true-scale displacement at scale=1', () => {
    const pos = new Float32Array([0, 0, 0])
    const disp = [{ ux: 0.001, uy: -0.002, uz: 0.0 }]
    const out = applyDisplacementScale(pos, disp, 1)
    expect(out[0]).toBeCloseTo(0.001)
    expect(out[1]).toBeCloseTo(-0.002)
    expect(out[2]).toBeCloseTo(0)
  })

  it('exaggerates displacement at scale=100', () => {
    const pos = new Float32Array([1, 0, 0])
    const disp = [{ ux: 0.001, uy: 0, uz: 0 }]
    const out = applyDisplacementScale(pos, disp, 100)
    expect(out[0]).toBeCloseTo(1.1)
  })

  it('handles more nodes than displacement entries', () => {
    const pos = new Float32Array([0, 0, 0, 5, 5, 5])
    const disp = [{ ux: 1, uy: 1, uz: 1 }]
    const out = applyDisplacementScale(pos, disp, 1)
    // first node displaced
    expect(out[0]).toBeCloseTo(1)
    // second node unchanged
    expect(out[3]).toBeCloseTo(5)
  })

  it('does not mutate the original positions array', () => {
    const pos = new Float32Array([0, 0, 0])
    const disp = [{ ux: 99, uy: 99, uz: 99 }]
    applyDisplacementScale(pos, disp, 1)
    expect(pos[0]).toBe(0)
  })
})

describe('displacementMagnitudes', () => {
  it('computes magnitude from components when mag not present', () => {
    const disp = [{ ux: 3, uy: 4, uz: 0 }]
    const out = displacementMagnitudes(disp)
    expect(out[0]).toBeCloseTo(5)
  })

  it('uses pre-computed mag field when present', () => {
    const disp = [{ ux: 0, uy: 0, uz: 0, mag: 7 }]
    const out = displacementMagnitudes(disp)
    expect(out[0]).toBeCloseTo(7)
  })
})

describe('scalarToRGB', () => {
  it('returns blue at t=0', () => {
    const [r, g, b] = scalarToRGB(0)
    expect(r).toBeCloseTo(0)
    expect(b).toBeCloseTo(1)
  })

  it('returns red at t=1', () => {
    const [r, g, b] = scalarToRGB(1)
    expect(r).toBeCloseTo(1)
    expect(g).toBeCloseTo(0)
    expect(b).toBeCloseTo(0)
  })

  it('clamps values outside [0,1]', () => {
    const [r1] = scalarToRGB(-1)
    const [r2] = scalarToRGB(2)
    expect(r1).toBeCloseTo(0)
    expect(r2).toBeCloseTo(1)
  })
})

describe('buildDisplacementColors', () => {
  it('returns Float32Array of length 3 * n', () => {
    const disp = [
      { ux: 0, uy: 0, uz: 0, mag: 0 },
      { ux: 1, uy: 0, uz: 0, mag: 1 },
    ]
    const colors = buildDisplacementColors(disp, 1)
    expect(colors).toBeInstanceOf(Float32Array)
    expect(colors.length).toBe(6)
  })

  it('zero magnitude maps to blue (r≈0, b≈1)', () => {
    const disp = [{ mag: 0 }]
    const colors = buildDisplacementColors(disp, 1)
    expect(colors[0]).toBeCloseTo(0)  // r
    expect(colors[2]).toBeCloseTo(1)  // b
  })

  it('max magnitude maps to red (r≈1, b≈0)', () => {
    const disp = [{ mag: 1 }]
    const colors = buildDisplacementColors(disp, 1)
    expect(colors[0]).toBeCloseTo(1)  // r
    expect(colors[2]).toBeCloseTo(0)  // b
  })

  it('handles maxMag=0 without division by zero', () => {
    const disp = [{ mag: 0 }]
    expect(() => buildDisplacementColors(disp, 0)).not.toThrow()
  })
})
