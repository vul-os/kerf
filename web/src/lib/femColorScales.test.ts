import { describe, it, expect } from 'vitest'
import { viridis, plasma, jet, rainbow, coolwarm, COLOR_SCALES, COLOR_SCALE_NAMES, scaleToCSS } from './femColorScales.js'

// Helper: compute perceived luminance (BT.709 coefficients)
function luminance([r, g, b]) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

// Check that an array of luminance values is monotonically non-decreasing
// with at least some meaningful overall increase from first to last.
function isMonotonicallyIncreasing(lums, tolerance = 0.005) {
  for (let i = 1; i < lums.length; i++) {
    if (lums[i] < lums[i - 1] - tolerance) return false
  }
  return true
}

// Sample a scale at n evenly-spaced points
function sample(fn, n = 11) {
  return Array.from({ length: n }, (_, i) => fn(i / (n - 1)))
}

// ── output shape ─────────────────────────────────────────────────────────────

describe('colour scale output shape', () => {
  const scales = [viridis, plasma, jet, rainbow, coolwarm]
  const names = ['viridis', 'plasma', 'jet', 'rainbow', 'coolwarm']

  for (let i = 0; i < scales.length; i++) {
    const fn = scales[i]
    const name = names[i]

    it(`${name}(t) returns a 3-element array`, () => {
      const result = fn(0.5)
      expect(result).toHaveLength(3)
    })

    it(`${name}(t) returns values in [0, 1] for t=0`, () => {
      const [r, g, b] = fn(0)
      expect(r).toBeGreaterThanOrEqual(0)
      expect(r).toBeLessThanOrEqual(1)
      expect(g).toBeGreaterThanOrEqual(0)
      expect(g).toBeLessThanOrEqual(1)
      expect(b).toBeGreaterThanOrEqual(0)
      expect(b).toBeLessThanOrEqual(1)
    })

    it(`${name}(t) returns values in [0, 1] for t=1`, () => {
      const [r, g, b] = fn(1)
      expect(r).toBeGreaterThanOrEqual(0)
      expect(r).toBeLessThanOrEqual(1)
      expect(g).toBeGreaterThanOrEqual(0)
      expect(g).toBeLessThanOrEqual(1)
      expect(b).toBeGreaterThanOrEqual(0)
      expect(b).toBeLessThanOrEqual(1)
    })

    it(`${name}(t) clamps t < 0`, () => {
      const neg = fn(-0.5)
      const zero = fn(0)
      expect(neg).toEqual(zero)
    })

    it(`${name}(t) clamps t > 1`, () => {
      const over = fn(1.5)
      const one = fn(1)
      expect(over).toEqual(one)
    })
  }
})

// ── viridis specific ─────────────────────────────────────────────────────────

describe('viridis', () => {
  it('viridis(0) is dark (luminance < 0.15)', () => {
    const lum = luminance(viridis(0))
    expect(lum).toBeLessThan(0.15)
  })

  it('viridis(0) has dominant blue channel', () => {
    const [r, g, b] = viridis(0)
    expect(b).toBeGreaterThan(r)
    expect(b).toBeGreaterThan(g * 0.5)
  })

  it('viridis(1) is bright yellow (high R and G, low B)', () => {
    const [r, g, b] = viridis(1)
    expect(r).toBeGreaterThan(0.7)
    expect(g).toBeGreaterThan(0.7)
    expect(b).toBeLessThan(0.4)
  })

  it('viridis(1) has high luminance (> 0.7)', () => {
    const lum = luminance(viridis(1))
    expect(lum).toBeGreaterThan(0.7)
  })

  it('viridis has monotonically increasing luminance', () => {
    const lums = sample(viridis).map(luminance)
    expect(isMonotonicallyIncreasing(lums)).toBe(true)
  })

  it('viridis overall luminance increases from t=0 to t=1', () => {
    const lum0 = luminance(viridis(0))
    const lum1 = luminance(viridis(1))
    expect(lum1 - lum0).toBeGreaterThan(0.5)
  })
})

// ── plasma specific ──────────────────────────────────────────────────────────

describe('plasma', () => {
  it('plasma(0) is dark blue/purple', () => {
    const [r, g, b] = plasma(0)
    expect(b).toBeGreaterThan(0.3)
    expect(luminance([r, g, b])).toBeLessThan(0.15)
  })

  it('plasma(1) is bright yellow (high R and G)', () => {
    const [r, g, b] = plasma(1)
    expect(r).toBeGreaterThan(0.7)
    expect(g).toBeGreaterThan(0.7)
  })

  it('plasma has monotonically increasing luminance', () => {
    const lums = sample(plasma).map(luminance)
    expect(isMonotonicallyIncreasing(lums)).toBe(true)
  })

  it('plasma overall luminance increases from t=0 to t=1', () => {
    expect(luminance(plasma(1)) - luminance(plasma(0))).toBeGreaterThan(0.4)
  })
})

// ── jet specific ─────────────────────────────────────────────────────────────

describe('jet', () => {
  it('jet(0) is dark blue', () => {
    const [r, g, b] = jet(0)
    expect(b).toBeGreaterThan(0.3)
    expect(r).toBeLessThan(0.2)
    expect(g).toBeLessThan(0.2)
  })

  it('jet(0.5) is near cyan-green', () => {
    const [r, g, b] = jet(0.5)
    expect(g).toBeGreaterThan(0.7)
    expect(r).toBeLessThan(0.8)
  })

  it('jet(1) is dark red', () => {
    const [r, g, b] = jet(1)
    expect(r).toBeGreaterThan(0.4)
    expect(g).toBeLessThan(0.2)
    expect(b).toBeLessThan(0.2)
  })
})

// ── rainbow = jet alias ───────────────────────────────────────────────────────

describe('rainbow', () => {
  it('rainbow is identical to jet at all sample points', () => {
    for (let i = 0; i <= 10; i++) {
      const t = i / 10
      expect(rainbow(t)).toEqual(jet(t))
    }
  })
})

// ── coolwarm specific ─────────────────────────────────────────────────────────

describe('coolwarm', () => {
  it('coolwarm(0) is blue (dominant blue channel)', () => {
    const [r, g, b] = coolwarm(0)
    expect(b).toBeGreaterThan(r)
  })

  it('coolwarm(1) is red (dominant red channel)', () => {
    const [r, g, b] = coolwarm(1)
    expect(r).toBeGreaterThan(b)
    expect(r).toBeGreaterThan(g)
  })

  it('coolwarm(0.5) is near neutral (grey-white, roughly equal RGB)', () => {
    const [r, g, b] = coolwarm(0.5)
    // Mid-point should be relatively neutral: all channels > 0.6
    expect(r).toBeGreaterThan(0.6)
    expect(g).toBeGreaterThan(0.6)
    expect(b).toBeGreaterThan(0.6)
  })
})

// ── registry ─────────────────────────────────────────────────────────────────

describe('COLOR_SCALES registry', () => {
  it('contains all five palettes', () => {
    expect(Object.keys(COLOR_SCALES)).toHaveLength(5)
    expect(COLOR_SCALES.viridis).toBeTypeOf('function')
    expect(COLOR_SCALES.plasma).toBeTypeOf('function')
    expect(COLOR_SCALES.jet).toBeTypeOf('function')
    expect(COLOR_SCALES.rainbow).toBeTypeOf('function')
    expect(COLOR_SCALES.coolwarm).toBeTypeOf('function')
  })

  it('COLOR_SCALE_NAMES lists all 5 scales', () => {
    expect(COLOR_SCALE_NAMES).toHaveLength(5)
    expect(COLOR_SCALE_NAMES).toContain('viridis')
    expect(COLOR_SCALE_NAMES).toContain('coolwarm')
  })
})

// ── scaleToCSS ────────────────────────────────────────────────────────────────

describe('scaleToCSS', () => {
  it('returns a valid rgb() string', () => {
    const css = scaleToCSS('viridis', 0.5)
    expect(css).toMatch(/^rgb\(\d+,\d+,\d+\)$/)
  })

  it('falls back to viridis for unknown scale name', () => {
    const unknown = scaleToCSS('nonexistent', 0.5)
    const expected = scaleToCSS('viridis', 0.5)
    expect(unknown).toBe(expected)
  })

  it('produces different outputs for t=0 and t=1 on viridis', () => {
    expect(scaleToCSS('viridis', 0)).not.toBe(scaleToCSS('viridis', 1))
  })
})
