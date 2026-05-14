import { describe, it, expect } from 'vitest'
import { composeTransforms, validateTransformList } from './multiTransform.js'

const IDENTITY_PLACEMENT = {
  origin: { x: 0, y: 0, z: 0 },
  rotation: { x: 0, y: 0, z: 0 },
}

const X_OFFSET_PLACEMENT = {
  origin: { x: 10, y: 0, z: 0 },
  rotation: { x: 0, y: 0, z: 0 },
}

describe('composeTransforms', () => {
  it('returns identity for empty transforms array', () => {
    const result = composeTransforms(IDENTITY_PLACEMENT, [])
    expect(result).toHaveLength(1)
    expect(result[0]).toEqual(IDENTITY_PLACEMENT)
  })

  it('single linear transform produces correct count', () => {
    const result = composeTransforms(IDENTITY_PLACEMENT, [
      { kind: 'linear', direction: 'x', count: 4, spacing: 5 },
    ])
    expect(result).toHaveLength(4)
    expect(result[0].origin.x).toBe(0)
    expect(result[1].origin.x).toBe(5)
    expect(result[2].origin.x).toBe(10)
    expect(result[3].origin.x).toBe(15)
  })

  it('linear transform along y direction', () => {
    const result = composeTransforms(IDENTITY_PLACEMENT, [
      { kind: 'linear', direction: 'y', count: 3, spacing: 2 },
    ])
    expect(result).toHaveLength(3)
    expect(result[0].origin.y).toBe(0)
    expect(result[1].origin.y).toBe(2)
    expect(result[2].origin.y).toBe(4)
  })

  it('single polar transform produces correct count', () => {
    const result = composeTransforms(IDENTITY_PLACEMENT, [
      { kind: 'polar', axis: 'z', count: 6, total_angle_deg: 360 },
    ])
    expect(result).toHaveLength(6)
  })

  it('polar transform with partial angle', () => {
    const result = composeTransforms(IDENTITY_PLACEMENT, [
      { kind: 'polar', axis: 'z', count: 3, total_angle_deg: 180 },
    ])
    expect(result).toHaveLength(3)
  })

  it('mirror transform returns two placements', () => {
    const result = composeTransforms(IDENTITY_PLACEMENT, [
      { kind: 'mirror', plane_or_face: 'XY' },
    ])
    expect(result).toHaveLength(2)
    expect(result[0].origin.z).toBe(0)
    expect(result[1].origin.z).toBe(-0)
  })

  it('linear then polar produces cartesian product', () => {
    const transforms = [
      { kind: 'linear', direction: 'x', count: 4, spacing: 1 },
      { kind: 'polar', axis: 'z', count: 3, total_angle_deg: 360 },
    ]
    const result = composeTransforms(IDENTITY_PLACEMENT, transforms)
    expect(result).toHaveLength(12)
  })

  it('polar then linear produces cartesian product', () => {
    const transforms = [
      { kind: 'polar', axis: 'z', count: 3, total_angle_deg: 360 },
      { kind: 'linear', direction: 'x', count: 4, spacing: 1 },
    ]
    const result = composeTransforms(IDENTITY_PLACEMENT, transforms)
    expect(result).toHaveLength(12)
  })

  it('three transforms produce correct cartesian product', () => {
    const transforms = [
      { kind: 'linear', direction: 'x', count: 2, spacing: 1 },
      { kind: 'polar', axis: 'z', count: 3, total_angle_deg: 360 },
      { kind: 'linear', direction: 'y', count: 2, spacing: 1 },
    ]
    const result = composeTransforms(IDENTITY_PLACEMENT, transforms)
    expect(result).toHaveLength(12)
  })

  it('preserves non-zero source placement origin', () => {
    const result = composeTransforms(X_OFFSET_PLACEMENT, [
      { kind: 'linear', direction: 'x', count: 2, spacing: 5 },
    ])
    expect(result[0].origin.x).toBe(10)
    expect(result[1].origin.x).toBe(15)
  })

  it('handles case-insensitive kind', () => {
    const result = composeTransforms(IDENTITY_PLACEMENT, [
      { kind: 'LINEAR', direction: 'X', count: 2, spacing: 1 },
    ])
    expect(result).toHaveLength(2)
  })

  it('mirror with XY plane negates z', () => {
    const result = composeTransforms(IDENTITY_PLACEMENT, [
      { kind: 'mirror', plane_or_face: 'XY' },
    ])
    expect(result[0].origin.z).toBe(0)
    expect(result[1].origin.z).toBe(-0)
  })

  it('mirror with XZ plane negates y', () => {
    const result = composeTransforms(IDENTITY_PLACEMENT, [
      { kind: 'mirror', plane_or_face: 'XZ' },
    ])
    expect(result[0].origin.y).toBe(0)
    expect(result[1].origin.y).toBe(-0)
  })

  it('mirror with YZ plane negates x', () => {
    const result = composeTransforms(IDENTITY_PLACEMENT, [
      { kind: 'mirror', plane_or_face: 'YZ' },
    ])
    expect(result[0].origin.x).toBe(0)
    expect(result[1].origin.x).toBe(-0)
  })
})

describe('validateTransformList', () => {
  it('returns ok true for valid single linear transform', () => {
    const result = validateTransformList([
      { kind: 'linear', direction: 'x', count: 4, spacing: 5 },
    ])
    expect(result.ok).toBe(true)
    expect(result.errors).toHaveLength(0)
  })

  it('returns ok true for valid single polar transform', () => {
    const result = validateTransformList([
      { kind: 'polar', axis: 'z', count: 6, total_angle_deg: 360 },
    ])
    expect(result.ok).toBe(true)
  })

  it('returns ok true for valid single mirror transform', () => {
    const result = validateTransformList([
      { kind: 'mirror', plane_or_face: 'XY' },
    ])
    expect(result.ok).toBe(true)
  })

  it('returns ok false for empty array', () => {
    const result = validateTransformList([])
    expect(result.ok).toBe(false)
    expect(result.errors).toContain("transforms must be non-empty")
  })

  it('returns ok false for non-array', () => {
    const result = validateTransformList("not an array")
    expect(result.ok).toBe(false)
    expect(result.errors).toContain("transforms must be an array")
  })

  it('returns ok false for invalid kind', () => {
    const result = validateTransformList([
      { kind: 'invalid', direction: 'x', count: 2, spacing: 1 },
    ])
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes("kind"))).toBe(true)
  })

  it('returns ok false for linear missing direction', () => {
    const result = validateTransformList([
      { kind: 'linear', count: 4, spacing: 5 },
    ])
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes("direction"))).toBe(true)
  })

  it('returns ok false for linear count < 2', () => {
    const result = validateTransformList([
      { kind: 'linear', direction: 'x', count: 1, spacing: 5 },
    ])
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes("count"))).toBe(true)
  })

  it('returns ok false for polar missing axis', () => {
    const result = validateTransformList([
      { kind: 'polar', count: 6, total_angle_deg: 360 },
    ])
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes("axis"))).toBe(true)
  })

  it('returns ok false for polar total_angle_deg > 360', () => {
    const result = validateTransformList([
      { kind: 'polar', axis: 'z', count: 6, total_angle_deg: 361 },
    ])
    expect(result.ok).toBe(false)
  })

  it('returns multiple errors for multiple issues', () => {
    const result = validateTransformList([
      { kind: 'linear', direction: 'invalid', count: 1, spacing: -1 },
    ])
    expect(result.ok).toBe(false)
    expect(result.errors.length).toBeGreaterThan(1)
  })

  it('returns ok false when transforms exceeds 4', () => {
    const manyTransforms = [
      { kind: 'linear', direction: 'x', count: 2, spacing: 1 },
      { kind: 'linear', direction: 'y', count: 2, spacing: 1 },
      { kind: 'linear', direction: 'z', count: 2, spacing: 1 },
      { kind: 'polar', axis: 'z', count: 2, total_angle_deg: 180 },
      { kind: 'polar', axis: 'x', count: 2, total_angle_deg: 180 },
    ]
    const result = validateTransformList(manyTransforms)
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes("maximum of 4"))).toBe(true)
  })
})