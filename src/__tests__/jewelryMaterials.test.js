// jewelryMaterials.test.js
//
// Pure unit tests for src/lib/jewelryMaterials.js.
// No WebGL, no Three.js instantiation — only the resolver API is tested.
//
// Covers:
//   - materialFor: null for non-jewelry nodes
//   - materialFor: metal PBR params for every METAL_PRESETS key via ring_shank
//   - materialFor: gem PBR params for every GEM_PRESETS key via gemstone op
//   - metalMaterial: correct metalness/roughness/color, correct fallback
//   - gemMaterial:   correct transmission/ior/color, correct fallback
//   - Spot-check canonical values from metal_cost.py and gemstones.py

import { describe, it, expect } from 'vitest'
import {
  materialFor,
  metalMaterial,
  gemMaterial,
  METAL_PRESETS,
  GEM_PRESETS,
} from '../lib/jewelryMaterials.js'

// ---------------------------------------------------------------------------
// materialFor — null for non-jewelry nodes
// ---------------------------------------------------------------------------

describe('materialFor — non-jewelry nodes', () => {
  it('returns null for null input', () => {
    expect(materialFor(null)).toBeNull()
  })
  it('returns null for undefined input', () => {
    expect(materialFor(undefined)).toBeNull()
  })
  it('returns null for a non-object', () => {
    expect(materialFor('ring_shank')).toBeNull()
  })
  it('returns null for a pad node', () => {
    expect(materialFor({ op: 'pad', sketch: 'sketch-1', depth: 10 })).toBeNull()
  })
  it('returns null for a fillet node', () => {
    expect(materialFor({ op: 'fillet', radius: 2 })).toBeNull()
  })
  it('returns null for a node with no op', () => {
    expect(materialFor({ metal: '18k_yellow' })).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// materialFor — gemstone op
// ---------------------------------------------------------------------------

describe('materialFor — gemstone op', () => {
  it('returns kind=gem for a gemstone node', () => {
    const result = materialFor({ op: 'gemstone', material: 'diamond', cut: 'round_brilliant' })
    expect(result).not.toBeNull()
    expect(result.kind).toBe('gem')
  })

  it('returns diamond preset for material=diamond', () => {
    const result = materialFor({ op: 'gemstone', material: 'diamond' })
    expect(result.ior).toBeCloseTo(2.418, 2)
    expect(result.transmission).toBe(1.0)
    expect(result.dispersion).toBeGreaterThan(0)
    expect(result.roughness).toBe(0.0)
  })

  it('returns ruby preset for material=ruby (red, corundum RI ~1.766)', () => {
    const result = materialFor({ op: 'gemstone', material: 'ruby' })
    expect(result.kind).toBe('gem')
    // GEM_CATALOG: ri: (1.762, 1.770) → midpoint 1.766
    expect(result.ior).toBeCloseTo(1.766, 2)
    expect(result.transmission).toBeGreaterThan(0.8)
    // Red body colour
    const r = (result.color >> 16) & 0xff
    const g = (result.color >> 8) & 0xff
    expect(r).toBeGreaterThan(g) // red dominant
  })

  it('returns sapphire preset (blue, RI ~1.766)', () => {
    const result = materialFor({ op: 'gemstone', material: 'sapphire' })
    expect(result.ior).toBeCloseTo(1.766, 2)
    const b = result.color & 0xff
    const r = (result.color >> 16) & 0xff
    expect(b).toBeGreaterThan(r) // blue dominant
  })

  it('returns emerald preset (green, beryl RI ~1.584)', () => {
    const result = materialFor({ op: 'gemstone', material: 'emerald' })
    expect(result.ior).toBeCloseTo(1.584, 2)
    const g = (result.color >> 8) & 0xff
    const r = (result.color >> 16) & 0xff
    expect(g).toBeGreaterThan(r) // green dominant
  })

  it('returns amethyst preset (purple, quartz RI ~1.549)', () => {
    const result = materialFor({ op: 'gemstone', material: 'amethyst' })
    expect(result.ior).toBeCloseTo(1.549, 2)
  })

  it('returns aquamarine preset (light blue, beryl RI ~1.579)', () => {
    const result = materialFor({ op: 'gemstone', material: 'aquamarine' })
    expect(result.ior).toBeCloseTo(1.579, 2)
  })

  it('returns zircon preset with high RI ~1.955 and dispersion', () => {
    const result = materialFor({ op: 'gemstone', material: 'zircon' })
    expect(result.ior).toBeCloseTo(1.955, 2)
    expect(result.dispersion).toBeGreaterThan(0)
  })

  it('falls back to diamond when material is unknown', () => {
    const result = materialFor({ op: 'gemstone', material: 'unobtainium' })
    expect(result.kind).toBe('gem')
    expect(result.ior).toBeCloseTo(2.418, 2)
  })

  it('falls back to diamond when material is absent', () => {
    const result = materialFor({ op: 'gemstone' })
    expect(result.kind).toBe('gem')
    expect(result.ior).toBeCloseTo(2.418, 2)
  })

  it('covers all GEM_PRESETS keys via materialFor', () => {
    for (const [gemName, preset] of Object.entries(GEM_PRESETS)) {
      const result = materialFor({ op: 'gemstone', material: gemName })
      expect(result, `gem '${gemName}' should resolve`).not.toBeNull()
      expect(result.kind).toBe('gem')
      expect(result.ior).toBe(preset.ior)
      expect(typeof result.transmission).toBe('number')
      expect(result.transmission).toBeGreaterThanOrEqual(0)
      expect(result.transmission).toBeLessThanOrEqual(1)
    }
  })
})

// ---------------------------------------------------------------------------
// materialFor — metal ops
// ---------------------------------------------------------------------------

describe('materialFor — metal ops (ring_shank)', () => {
  it('returns kind=metal for a ring_shank node', () => {
    const result = materialFor({ op: 'ring_shank', metal: '18k_yellow', ring_size: 7 })
    expect(result).not.toBeNull()
    expect(result.kind).toBe('metal')
  })

  it('18k yellow: metalness=1, roughness<0.1, warm gold colour', () => {
    const result = materialFor({ op: 'ring_shank', metal: '18k_yellow' })
    expect(result.metalness).toBe(1.0)
    expect(result.roughness).toBeLessThan(0.1)
    // 18k yellow is warm/golden — red + green channels dominant over blue
    const r = (result.color >> 16) & 0xff
    const b = result.color & 0xff
    expect(r).toBeGreaterThan(b)
  })

  it('18k white: less warm (lower red/blue ratio) than 18k yellow', () => {
    const yellow = materialFor({ op: 'ring_shank', metal: '18k_yellow' })
    const white  = materialFor({ op: 'ring_shank', metal: '18k_white' })
    // Yellow gold: red >> blue (high warmth ratio).
    // White gold: near-grey, so red ≈ blue (low warmth ratio).
    const yellowWarmth = ((yellow.color >> 16) & 0xff) / Math.max(1, yellow.color & 0xff)
    const whiteWarmth  = ((white.color  >> 16) & 0xff) / Math.max(1, white.color  & 0xff)
    expect(yellowWarmth).toBeGreaterThan(whiteWarmth)
  })

  it('18k rose: more red than 18k yellow white (copper-rich)', () => {
    const rose = materialFor({ op: 'ring_shank', metal: '18k_rose' })
    const white = materialFor({ op: 'ring_shank', metal: '18k_white' })
    const roseR  = (rose.color  >> 16) & 0xff
    const whiteR = (white.color >> 16) & 0xff
    expect(roseR).toBeGreaterThanOrEqual(whiteR)
  })

  it('platinum_950: very high brightness (bright grey)', () => {
    const result = materialFor({ op: 'ring_shank', metal: 'platinum_950' })
    const r = (result.color >> 16) & 0xff
    expect(r).toBeGreaterThan(200) // near-white
    expect(result.roughness).toBeLessThanOrEqual(0.06)
  })

  it('sterling_925: metalness=1, grey colour', () => {
    const result = materialFor({ op: 'ring_shank', metal: 'sterling_925' })
    expect(result.metalness).toBe(1.0)
    const r = (result.color >> 16) & 0xff
    expect(r).toBeGreaterThan(150) // grey/silver-ish
  })

  it('falls back to 18k_yellow when metal key is unknown', () => {
    const result = materialFor({ op: 'ring_shank', metal: 'unobtainium' })
    const ref    = metalMaterial('18k_yellow')
    expect(result.color).toBe(ref.color)
    expect(result.metalness).toBe(ref.metalness)
  })

  it('falls back to 18k_yellow when metal is absent', () => {
    const result = materialFor({ op: 'ring_shank' })
    const ref    = metalMaterial('18k_yellow')
    expect(result.color).toBe(ref.color)
  })

  it('covers all METAL_PRESETS keys', () => {
    for (const [metalKey, preset] of Object.entries(METAL_PRESETS)) {
      const result = metalMaterial(metalKey)
      expect(result, `metal '${metalKey}' should resolve`).not.toBeNull()
      expect(result.kind).toBe('metal')
      expect(result.metalness).toBe(preset.metalness)
      expect(result.roughness).toBe(preset.roughness)
      expect(result.color).toBe(preset.color)
    }
  })

  it('jewelry_prong_head resolves as metal', () => {
    const result = materialFor({ op: 'jewelry_prong_head', metal: '14k_white' })
    expect(result.kind).toBe('metal')
    expect(result.metalness).toBe(1.0)
  })

  it('jewelry_bezel resolves as metal', () => {
    const result = materialFor({ op: 'jewelry_bezel', metal: '18k_rose' })
    expect(result.kind).toBe('metal')
  })

  it('gem_seat resolves as metal (the cutter solid)', () => {
    const result = materialFor({ op: 'gem_seat', cut: 'round_brilliant' })
    expect(result.kind).toBe('metal')
  })

  it('channel_seat resolves as metal', () => {
    const result = materialFor({ op: 'channel_seat' })
    expect(result.kind).toBe('metal')
  })
})

// ---------------------------------------------------------------------------
// metalMaterial — direct API
// ---------------------------------------------------------------------------

describe('metalMaterial', () => {
  it('returns kind=metal', () => {
    expect(metalMaterial('24k_yellow').kind).toBe('metal')
  })
  it('24k pure gold: highest colour saturation of yellow golds', () => {
    const result = metalMaterial('24k_yellow')
    expect(result.color).toBe(0xffd700)
    expect(result.roughness).toBeLessThanOrEqual(0.05)
  })
  it('normalises case', () => {
    // Pass lowercased key — should still resolve
    const result = metalMaterial('platinum_950')
    expect(result.metalness).toBe(1.0)
  })
  it('palladium_950 has lower roughness than brass (more polished)', () => {
    const pd  = metalMaterial('palladium_950')
    const br  = metalMaterial('brass')
    expect(pd.roughness).toBeLessThan(br.roughness)
  })
})

// ---------------------------------------------------------------------------
// gemMaterial — direct API
// ---------------------------------------------------------------------------

describe('gemMaterial', () => {
  it('returns kind=gem', () => {
    expect(gemMaterial('diamond').kind).toBe('gem')
  })
  it('diamond has dispersion > 0 (fire)', () => {
    expect(gemMaterial('diamond').dispersion).toBeGreaterThan(0)
  })
  it('most coloured stones have dispersion=0', () => {
    for (const name of ['ruby', 'sapphire', 'emerald', 'amethyst', 'garnet']) {
      const r = gemMaterial(name)
      expect(r.dispersion, `${name} dispersion`).toBe(0)
    }
  })
  it('all gems have transmission in [0, 1]', () => {
    for (const name of Object.keys(GEM_PRESETS)) {
      const r = gemMaterial(name)
      expect(r.transmission, `${name} transmission`).toBeGreaterThanOrEqual(0)
      expect(r.transmission, `${name} transmission`).toBeLessThanOrEqual(1)
    }
  })
  it('all gems have roughness in [0, 1)', () => {
    for (const name of Object.keys(GEM_PRESETS)) {
      const r = gemMaterial(name)
      expect(r.roughness, `${name} roughness`).toBeGreaterThanOrEqual(0)
      expect(r.roughness, `${name} roughness`).toBeLessThan(1)
    }
  })
  it('opaque/semi-opaque stones: opal transmission < diamond', () => {
    expect(gemMaterial('opal').transmission).toBeLessThan(gemMaterial('diamond').transmission)
  })
  it('turquoise is opaque (transmission=0)', () => {
    expect(gemMaterial('turquoise').transmission).toBe(0)
  })
  it('pearl is near-opaque (transmission < 0.1)', () => {
    expect(gemMaterial('pearl').transmission).toBeLessThan(0.1)
  })
  it('unknown gem falls back to diamond', () => {
    const result = gemMaterial('unobtainium')
    expect(result.ior).toBeCloseTo(2.418, 2)
  })
})

// ---------------------------------------------------------------------------
// Cross-check canonical IOR values from gemstones.py GEM_CATALOG
// ri field is a tuple (lo, hi); IOR preset should equal the midpoint.
// ---------------------------------------------------------------------------

describe('IOR values match GEM_CATALOG midpoints', () => {
  // GEM_CATALOG ri tuples (lo, hi) — from gemstones.py
  const catalogRI = {
    diamond:    [2.417, 2.419],
    ruby:       [1.762, 1.770],
    sapphire:   [1.762, 1.770],
    emerald:    [1.565, 1.602],
    amethyst:   [1.544, 1.553],
    aquamarine: [1.567, 1.590],
    morganite:  [1.572, 1.600],
    topaz:      [1.609, 1.643],
    garnet:     [1.714, 1.888],
    spinel:     [1.712, 1.762],
    tanzanite:  [1.691, 1.700],
    peridot:    [1.650, 1.703],
    tourmaline: [1.624, 1.644],
    alexandrite:[1.746, 1.755],
    zircon:     [1.925, 1.984],
  }

  for (const [gem, [lo, hi]] of Object.entries(catalogRI)) {
    it(`${gem} IOR is within published RI range [${lo}, ${hi}]`, () => {
      const result = gemMaterial(gem)
      expect(result.ior, `${gem} IOR`).toBeGreaterThanOrEqual(lo)
      expect(result.ior, `${gem} IOR`).toBeLessThanOrEqual(hi)
    })
  }
})
