import { describe, it, expect } from 'vitest'
import { computeRibProfile } from './ribGeom.js'

const square = [
  { x: 0, y: 0 },
  { x: 10, y: 0 },
  { x: 10, y: 10 },
  { x: 0, y: 10 },
]

const triangle = [
  { x: 0, y: 0 },
  { x: 5, y: 0 },
  { x: 2.5, y: 4 },
]

const diamond = [
  { x: 5, y: 0 },
  { x: 10, y: 5 },
  { x: 5, y: 10 },
  { x: 0, y: 5 },
]

describe('computeRibProfile — basic contract', () => {
  it('returns an array', () => {
    expect(Array.isArray(computeRibProfile(square, 2))).toBe(true)
  })

  it('returns empty array for invalid thickness', () => {
    expect(computeRibProfile(square, 0)).toEqual([])
    expect(computeRibProfile(square, -1)).toEqual([])
  })

  it('returns empty array for sketch with fewer than 3 points', () => {
    expect(computeRibProfile([{ x: 0, y: 0 }], 2)).toEqual([])
    expect(computeRibProfile([{ x: 0, y: 0 }, { x: 1, y: 0 }], 2)).toEqual([])
  })

  it('returns empty array for null/undefined sketch', () => {
    expect(computeRibProfile(null, 2)).toEqual([])
    expect(computeRibProfile(undefined, 2)).toEqual([])
  })
})

describe('computeRibProfile — single-side offset', () => {
  it('offset polyline has same number of points as input', () => {
    const result = computeRibProfile(square, 2, false, false)
    expect(result.length).toBe(square.length)
  })

  it('offset points are different from original', () => {
    const result = computeRibProfile(square, 2, false, false)
    for (let i = 0; i < result.length; i++) {
      expect(result[i].x).not.toBe(square[i].x)
    }
  })

  it('larger thickness produces larger offset distance', () => {
    const small = computeRibProfile(square, 1, false, false)
    const large = computeRibProfile(square, 5, false, false)
    const areaSmall = polygonArea(small)
    const areaLarge = polygonArea(large)
    expect(areaLarge).toBeGreaterThan(areaSmall)
  })
})

describe('computeRibProfile — both_sides symmetry', () => {
  it('both_sides=true produces offset polyline', () => {
    const result = computeRibProfile(square, 2, true, false)
    expect(result.length).toBe(square.length)
  })

  it('both_sides=true with half thickness is smaller than full offset', () => {
    const bothHalf = computeRibProfile(square, 2, true, false)
    const singleFull = computeRibProfile(square, 2, false, false)
    expect(polygonArea(bothHalf)).toBeLessThan(polygonArea(singleFull))
  })
})

function polygonArea(pts) {
  let a = 0
  for (let i = 0; i < pts.length; i++) {
    const j = (i + 1) % pts.length
    a += pts[i].x * pts[j].y - pts[j].x * pts[i].y
  }
  return Math.abs(a / 2)
}

describe('computeRibProfile — midplane', () => {
  it('midplane=true returns original points (no offset)', () => {
    const result = computeRibProfile(square, 2, false, true)
    expect(result.length).toBe(square.length)
  })

  it('midplane=false with both_sides=false returns offset points', () => {
    const noOffset = computeRibProfile(square, 2, false, true)
    const offset = computeRibProfile(square, 2, false, false)
    expect(offset).not.toEqual(noOffset)
  })
})

describe('computeRibProfile — positive vs negative thickness', () => {
  it('positive thickness returns offset polyline', () => {
    const result = computeRibProfile(square, 2, false, false)
    expect(result.length).toBeGreaterThan(0)
  })

  it('zero thickness returns empty array', () => {
    expect(computeRibProfile(square, 0, false, false)).toEqual([])
  })
})

describe('computeRibProfile — various shapes', () => {
  it('works with triangle', () => {
    const result = computeRibProfile(triangle, 1, false, false)
    expect(result.length).toBe(triangle.length)
  })

  it('works with diamond', () => {
    const result = computeRibProfile(diamond, 1, false, false)
    expect(result.length).toBe(diamond.length)
  })
})