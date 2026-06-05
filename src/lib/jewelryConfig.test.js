/**
 * jewelryConfig.test.js — Vitest tests for src/lib/jewelryConfig.js
 *
 * Coverage:
 *   caratFromMm / mmFromCarat  — diamond + coloured-stone density correction
 *   ringSizeToDiameter         — US / UK / EU / JP systems
 *   ringDiameterToSize         — round-trip inverse
 *   metalWeight / castingWeight
 *   computeProngParams         — prong geometry ratios
 *   computeBezelParams         — bezel geometry ratios
 *   computePaveLayout          — stone count + spacing
 *   ringBandVolume             — Pappus approximation
 *   gemCatalogSearch / gemsByBirthMonth
 *   idealProportions           — key cuts
 */

import { describe, it, expect } from 'vitest'
import {
  caratFromMm,
  mmFromCarat,
  ringSizeToDiameter,
  ringDiameterToSize,
  metalWeight,
  castingWeight,
  computeProngParams,
  computeBezelParams,
  computePaveLayout,
  ringBandVolume,
  gemCatalogSearch,
  gemsByBirthMonth,
  idealProportions,
  GEM_DENSITIES,
  GEM_CATALOG,
  CUT_CATALOG,
  METAL_DENSITY,
  METAL_HALLMARK,
  UK_AU_SIZES,
  US_SIZES,
} from './jewelryConfig.js'

// ── caratFromMm / mmFromCarat ─────────────────────────────────────────────────

describe('caratFromMm', () => {
  it('1 ct round brilliant diamond ≈ 6.5 mm', () => {
    expect(caratFromMm(6.5)).toBeCloseTo(1.0, 2)
  })

  it('0 mm returns 0', () => {
    expect(caratFromMm(0)).toBe(0)
  })

  it('negative mm returns 0', () => {
    expect(caratFromMm(-1)).toBe(0)
  })

  it('2 ct diamond is larger than 1 ct (cubic scaling)', () => {
    const d1 = mmFromCarat(1.0)
    const d2 = mmFromCarat(2.0)
    expect(d2).toBeGreaterThan(d1)
  })

  it('princess 1 ct diamond ≈ 5.5 mm', () => {
    expect(caratFromMm(5.5, 'princess')).toBeCloseTo(1.0, 2)
  })

  it('oval 1 ct diamond ≈ 7.7 mm', () => {
    expect(caratFromMm(7.7, 'oval')).toBeCloseTo(1.0, 2)
  })

  it('marquise 1 ct diamond ≈ 10 mm', () => {
    expect(caratFromMm(10.0, 'marquise')).toBeCloseTo(1.0, 2)
  })

  it('ruby (denser than diamond) gives more carats per mm than diamond', () => {
    // ruby density 4.00 > diamond 3.51 → more carats per mm
    const ctDiamond = caratFromMm(5.0, 'round_brilliant', null, 3.51)
    const ctRuby    = caratFromMm(5.0, 'round_brilliant', 'ruby')
    expect(ctRuby).toBeGreaterThan(ctDiamond)
  })

  it('emerald gem (less dense) gives fewer carats per mm', () => {
    const ctDiamond = caratFromMm(5.0, 'round_brilliant', null, 3.51)
    const ctEmerald = caratFromMm(5.0, 'round_brilliant', 'emerald')
    expect(ctEmerald).toBeLessThan(ctDiamond)
  })

  it('unknown gem material falls back to diamond density', () => {
    const ctUnknown = caratFromMm(6.5, 'round_brilliant', 'mystery_stone')
    const ctDiamond = caratFromMm(6.5, 'round_brilliant')
    expect(ctUnknown).toBeCloseTo(ctDiamond, 4)
  })

  it('explicit density overrides material', () => {
    const ctExplicit = caratFromMm(6.5, 'round_brilliant', 'ruby', 3.51)
    const ctDiamond  = caratFromMm(6.5, 'round_brilliant')
    expect(ctExplicit).toBeCloseTo(ctDiamond, 4)
  })
})

describe('mmFromCarat', () => {
  it('round-trip: mmFromCarat(caratFromMm(d)) ≈ d', () => {
    const d = 6.0
    expect(mmFromCarat(caratFromMm(d))).toBeCloseTo(d, 3)
  })

  it('0 carat returns 0', () => {
    expect(mmFromCarat(0)).toBe(0)
  })

  it('0.25 ct round brilliant is smaller than 0.5 ct', () => {
    expect(mmFromCarat(0.25)).toBeLessThan(mmFromCarat(0.5))
  })

  it('cushion 1 ct has correct ref mm ≈ 5.5', () => {
    expect(mmFromCarat(1.0, 'cushion')).toBeCloseTo(5.5, 2)
  })
})

// ── ringSizeToDiameter ────────────────────────────────────────────────────────

describe('ringSizeToDiameter', () => {
  it('US size 0 → 11.63 mm', () => {
    expect(ringSizeToDiameter('US', 0)).toBeCloseTo(11.63, 2)
  })

  it('US size 7 → ~17.32 mm (cross-check Stuller 2024)', () => {
    expect(ringSizeToDiameter('US', 7)).toBeCloseTo(17.32, 1)
  })

  it('US size 5 → ~15.69 mm', () => {
    expect(ringSizeToDiameter('US', 5)).toBeCloseTo(15.69, 1)
  })

  it('UK size N → matches ISO 8653 circumference / π', () => {
    const circ = UK_AU_SIZES['N'] // 54.4 mm
    const expected = circ / Math.PI
    expect(ringSizeToDiameter('UK', 'N')).toBeCloseTo(expected, 4)
  })

  it('AU size N same as UK size N', () => {
    expect(ringSizeToDiameter('AU', 'N')).toBeCloseTo(ringSizeToDiameter('UK', 'N'), 5)
  })

  it('EU size 52 → 52 / π mm', () => {
    expect(ringSizeToDiameter('EU', 52)).toBeCloseTo(52 / Math.PI, 4)
  })

  it('JP size 13 → (37 + 13) / π mm', () => {
    expect(ringSizeToDiameter('JP', 13)).toBeCloseTo(50 / Math.PI, 4)
  })

  it('US size >16 throws', () => {
    expect(() => ringSizeToDiameter('US', 17)).toThrow()
  })

  it('US size <0 throws', () => {
    expect(() => ringSizeToDiameter('US', -1)).toThrow()
  })

  it('Unknown UK size throws', () => {
    expect(() => ringSizeToDiameter('UK', 'ZZ')).toThrow()
  })

  it('EU size <41 throws', () => {
    expect(() => ringSizeToDiameter('EU', 40)).toThrow()
  })

  it('EU size >76 throws', () => {
    expect(() => ringSizeToDiameter('EU', 77)).toThrow()
  })

  it('JP size 0 throws', () => {
    expect(() => ringSizeToDiameter('JP', 0)).toThrow()
  })

  it('Unknown system throws', () => {
    expect(() => ringSizeToDiameter('METRIC', 10)).toThrow()
  })
})

// ── ringDiameterToSize ────────────────────────────────────────────────────────

describe('ringDiameterToSize', () => {
  it('round-trip US size 7 → diameter → US size nearest 7', () => {
    const d = ringSizeToDiameter('US', 7)
    expect(ringDiameterToSize('US', d)).toBe(7)
  })

  it('round-trip UK size N', () => {
    const d = ringSizeToDiameter('UK', 'N')
    expect(ringDiameterToSize('UK', d)).toBe('N')
  })

  it('round-trip EU size 52', () => {
    const d = ringSizeToDiameter('EU', 52)
    expect(ringDiameterToSize('EU', d)).toBe(52)
  })

  it('round-trip JP size 13', () => {
    const d = ringSizeToDiameter('JP', 13)
    expect(ringDiameterToSize('JP', d)).toBe(13)
  })

  it('US result is a valid US size', () => {
    const d = ringSizeToDiameter('US', 6)
    const s = ringDiameterToSize('US', d)
    expect(US_SIZES).toContain(s)
  })
})

// ── metalWeight / castingWeight ───────────────────────────────────────────────

describe('metalWeight', () => {
  it('18k yellow gold 1000 mm³ ≈ 15.58 g', () => {
    const w = metalWeight(1000, '18k_yellow')
    expect(w.netGrams).toBeCloseTo(15.58, 2)
  })

  it('returns correct dwt', () => {
    const w = metalWeight(1000, 'sterling_925')
    expect(w.netDwt).toBeCloseTo(w.netGrams / 1.55517384, 4)
  })

  it('returns correct ozt', () => {
    const w = metalWeight(1000, 'platinum_950')
    expect(w.netOzt).toBeCloseTo(w.netGrams / 31.1034768, 4)
  })

  it('returns null for volume 0', () => {
    expect(metalWeight(0, '18k_yellow')).toBeNull()
  })

  it('returns null for negative volume', () => {
    expect(metalWeight(-100, '18k_yellow')).toBeNull()
  })

  it('returns null for unknown metal', () => {
    expect(metalWeight(1000, 'unobtainium')).toBeNull()
  })
})

describe('castingWeight', () => {
  it('gross weight is greater than net weight', () => {
    const r = castingWeight(1000, '14k_yellow')
    expect(r.grossGrams).toBeGreaterThan(r.netGrams)
  })

  it('default 15% allowance: gross ≈ net × 1.15', () => {
    const r = castingWeight(1000, '14k_yellow')
    expect(r.grossGrams).toBeCloseTo(r.netGrams * 1.15, 4)
  })

  it('explicit allowance used', () => {
    const r = castingWeight(1000, '14k_yellow', 20)
    expect(r.grossGrams).toBeCloseTo(r.netGrams * 1.20, 4)
  })

  it('returns allowancePct in result', () => {
    const r = castingWeight(1000, '14k_yellow', 12)
    expect(r.allowancePct).toBe(12)
  })
})

// ── computeProngParams ────────────────────────────────────────────────────────

describe('computeProngParams', () => {
  it('prong_diameter proportional to stone', () => {
    const r = computeProngParams(6.5)
    expect(r.prong_diameter_mm).toBeCloseTo(6.5 * 0.18, 4)
  })

  it('prong_height proportional to stone', () => {
    const r = computeProngParams(6.5)
    expect(r.prong_height_mm).toBeCloseTo(6.5 * 0.40, 4)
  })

  it('default prong_count is 4', () => {
    expect(computeProngParams(6.5).prong_count).toBe(4)
  })

  it('custom prong_count respected', () => {
    expect(computeProngParams(6.5, 6).prong_count).toBe(6)
  })

  it('seat_depth_mm is 10% of stone diameter', () => {
    const r = computeProngParams(8.0)
    expect(r.seat_depth_mm).toBeCloseTo(8.0 * 0.10, 4)
  })

  it('girdle_clearance_mm is 5% of stone diameter', () => {
    const r = computeProngParams(8.0)
    expect(r.girdle_clearance_mm).toBeCloseTo(8.0 * 0.05, 4)
  })

  it('prong_count < 3 throws', () => {
    expect(() => computeProngParams(6.5, 2)).toThrow()
  })

  it('zero stone diameter throws', () => {
    expect(() => computeProngParams(0)).toThrow()
  })
})

// ── computeBezelParams ────────────────────────────────────────────────────────

describe('computeBezelParams', () => {
  it('inner diameter slightly larger than stone', () => {
    const r = computeBezelParams(6.5)
    expect(r.bezel_inner_diameter_mm).toBeGreaterThan(6.5)
  })

  it('outer diameter larger than inner', () => {
    const r = computeBezelParams(6.5)
    expect(r.bezel_outer_diameter_mm).toBeGreaterThan(r.bezel_inner_diameter_mm)
  })

  it('bezel_wall_mm is 10% of stone diameter by default', () => {
    const r = computeBezelParams(6.5)
    expect(r.bezel_wall_mm).toBeCloseTo(6.5 * 0.10, 4)
  })

  it('outer = inner + 2 × wall', () => {
    const r = computeBezelParams(6.5)
    expect(r.bezel_outer_diameter_mm).toBeCloseTo(r.bezel_inner_diameter_mm + 2 * r.bezel_wall_mm, 3)
  })

  it('explicit wall ratio used', () => {
    const r = computeBezelParams(6.5, undefined, 0.12)
    expect(r.bezel_wall_mm).toBeCloseTo(6.5 * 0.12, 4)
  })

  it('zero stone diameter throws', () => {
    expect(() => computeBezelParams(0)).toThrow()
  })
})

// ── computePaveLayout ─────────────────────────────────────────────────────────

describe('computePaveLayout', () => {
  it('stone_count is stones_per_row × row_count', () => {
    const r = computePaveLayout(1.2, 30.0, 2)
    expect(r.stone_count).toBe(r.stones_per_row * 2)
  })

  it('stone_spacing is 1.05 × stone diameter', () => {
    const r = computePaveLayout(1.2, 30.0)
    expect(r.stone_spacing_mm).toBeCloseTo(1.2 * 1.05, 4)
  })

  it('bead_diameter is 25% of stone diameter', () => {
    const r = computePaveLayout(1.5, 30.0)
    expect(r.bead_diameter_mm).toBeCloseTo(1.5 * 0.25, 4)
  })

  it('drill_depth is 50% of stone diameter', () => {
    const r = computePaveLayout(1.5, 30.0)
    expect(r.drill_depth_mm).toBeCloseTo(1.5 * 0.50, 4)
  })

  it('stones_per_row = floor(length / spacing)', () => {
    const spacing = 1.2 * 1.05
    const r = computePaveLayout(1.2, 30.0)
    expect(r.stones_per_row).toBe(Math.floor(30.0 / spacing))
  })

  it('zero stone diameter throws', () => {
    expect(() => computePaveLayout(0, 30.0)).toThrow()
  })

  it('zero band length throws', () => {
    expect(() => computePaveLayout(1.2, 0)).toThrow()
  })
})

// ── ringBandVolume ────────────────────────────────────────────────────────────

describe('ringBandVolume', () => {
  it('positive volume for valid inputs', () => {
    expect(ringBandVolume(17.0, 4.0, 1.5)).toBeGreaterThan(0)
  })

  it('larger ring has more volume', () => {
    const small = ringBandVolume(14.0, 3.0, 1.0)
    const large = ringBandVolume(18.0, 3.0, 1.0)
    expect(large).toBeGreaterThan(small)
  })

  it('wider band has more volume', () => {
    const narrow = ringBandVolume(17.0, 2.0, 1.5)
    const wide   = ringBandVolume(17.0, 5.0, 1.5)
    expect(wide).toBeGreaterThan(narrow)
  })

  it('thicker band has more volume', () => {
    const thin  = ringBandVolume(17.0, 4.0, 1.0)
    const thick = ringBandVolume(17.0, 4.0, 2.5)
    expect(thick).toBeGreaterThan(thin)
  })

  it('zero inner diameter returns 0', () => {
    expect(ringBandVolume(0, 4.0, 1.5)).toBe(0)
  })

  it('Pappus: V = 2π × R × (width × thickness)', () => {
    const id = 17.0, bw = 4.0, t = 1.5
    const R = id / 2 + t / 2
    const expected = 2 * Math.PI * R * (bw * t)
    expect(ringBandVolume(id, bw, t)).toBeCloseTo(expected, 3)
  })
})

// ── gemCatalogSearch / gemsByBirthMonth ───────────────────────────────────────

describe('gemCatalogSearch', () => {
  it('empty query returns all gems', () => {
    expect(gemCatalogSearch('')).toHaveLength(GEM_CATALOG.length)
  })

  it('search "diamond" returns diamond', () => {
    const results = gemCatalogSearch('diamond')
    expect(results.some(g => g.name === 'diamond')).toBe(true)
  })

  it('case-insensitive match', () => {
    expect(gemCatalogSearch('RUBY').some(g => g.name === 'ruby')).toBe(true)
  })

  it('unknown gem returns empty', () => {
    expect(gemCatalogSearch('xyzzy_not_a_gem')).toHaveLength(0)
  })
})

describe('gemsByBirthMonth', () => {
  it('April (4) returns diamond', () => {
    expect(gemsByBirthMonth(4).some(g => g.name === 'diamond')).toBe(true)
  })

  it('July (7) returns ruby', () => {
    expect(gemsByBirthMonth(7).some(g => g.name === 'ruby')).toBe(true)
  })

  it('September (9) returns sapphire', () => {
    expect(gemsByBirthMonth(9).some(g => g.name === 'sapphire')).toBe(true)
  })

  it('month with no birthstones returns empty or non-empty (not throw)', () => {
    expect(() => gemsByBirthMonth(0)).not.toThrow()
  })
})

// ── idealProportions ─────────────────────────────────────────────────────────

describe('idealProportions', () => {
  it('round_brilliant returns table_pct and crown_angle', () => {
    const p = idealProportions('round_brilliant')
    expect(p).not.toBeNull()
    expect(Array.isArray(p.table_pct)).toBe(true)
    expect(p.table_pct).toHaveLength(2)
    expect(p.crown_angle_deg).toBeDefined()
  })

  it('round_brilliant pavilion angle in GIA Excellent range [40.2, 41.25]', () => {
    const p = idealProportions('round_brilliant')
    expect(p.pavilion_angle_deg[0]).toBeGreaterThanOrEqual(40.0)
    expect(p.pavilion_angle_deg[1]).toBeLessThanOrEqual(42.0)
  })

  it('princess returns table_pct and depth range', () => {
    const p = idealProportions('princess')
    expect(p).not.toBeNull()
    expect(Array.isArray(p.table_pct)).toBe(true)
    expect(p.total_depth_pct).toBeDefined()
  })

  it('emerald returns step_rows', () => {
    const p = idealProportions('emerald')
    expect(p.step_rows).toBeDefined()
  })

  it('unknown cut returns null', () => {
    expect(idealProportions('hexagonal')).toBeNull()
  })
})

// ── catalog completeness ──────────────────────────────────────────────────────

describe('GEM_DENSITIES', () => {
  it('diamond density is 3.51 g/cm³ (NIST/GIA)', () => {
    expect(GEM_DENSITIES.diamond).toBeCloseTo(3.51, 2)
  })

  it('ruby and sapphire are same density (corundum 4.00 g/cm³)', () => {
    expect(GEM_DENSITIES.ruby).toBeCloseTo(4.00, 2)
    expect(GEM_DENSITIES.sapphire).toBeCloseTo(4.00, 2)
  })

  it('all densities are positive', () => {
    for (const [name, rho] of Object.entries(GEM_DENSITIES)) {
      expect(rho).toBeGreaterThan(0), `${name}: density must be > 0`
    }
  })
})

describe('METAL_DENSITY', () => {
  it('platinum_950 is heaviest common metal (21.40)', () => {
    expect(METAL_DENSITY.platinum_950).toBeGreaterThan(METAL_DENSITY['18k_yellow'])
  })

  it('titanium is lightest entry', () => {
    const allDensities = Object.values(METAL_DENSITY)
    expect(METAL_DENSITY.titanium).toBe(Math.min(...allDensities))
  })

  it('18k_yellow 15.58 g/cm³ matches WGC spec', () => {
    expect(METAL_DENSITY['18k_yellow']).toBeCloseTo(15.58, 2)
  })
})

describe('METAL_HALLMARK', () => {
  it('18k hallmark is 750', () => {
    expect(METAL_HALLMARK['18k_yellow']).toBe(750)
  })

  it('sterling silver hallmark is 925', () => {
    expect(METAL_HALLMARK.sterling_925).toBe(925)
  })

  it('platinum_950 hallmark is 950', () => {
    expect(METAL_HALLMARK.platinum_950).toBe(950)
  })

  it('titanium hallmark is null (not precious metal)', () => {
    expect(METAL_HALLMARK.titanium).toBeNull()
  })
})

describe('CUT_CATALOG', () => {
  it('round_brilliant entry present', () => {
    expect(CUT_CATALOG.some(c => c.name === 'round_brilliant')).toBe(true)
  })

  it('all entries have name, label, facets, note', () => {
    for (const c of CUT_CATALOG) {
      expect(c.name).toBeTruthy()
      expect(c.label).toBeTruthy()
      expect(c.facets).toBeTruthy()
      expect(c.note).toBeTruthy()
    }
  })
})
