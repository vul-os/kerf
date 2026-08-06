/**
 * PathTracer.test.js — Smoke tests for path-tracer scene graph and BVH.
 *
 * These tests run in Node (jsdom) via Vitest and do NOT require a WebGPU
 * device.  The GPU-render test is skipped if WebGPU is not available
 * (which is true for all CI environments).
 */

import { describe, it, expect } from 'vitest'
import { Material, Scene, buildBVH } from '../PathTracerScene.js'

// ─── Material ────────────────────────────────────────────────────────────────

describe('Material', () => {
  it('encodes diffuse as kind=0', () => {
    const m = new Material({ kind: 'diffuse', albedo: [0.8, 0.2, 0.1] })
    const gpu = m.toGPU()
    // floats: albedo.r, albedo.g, albedo.b, kind(f32), ior, roughness, emission, pad
    expect(gpu[0]).toBeCloseTo(0.8)
    expect(gpu[1]).toBeCloseTo(0.2)
    expect(gpu[2]).toBeCloseTo(0.1)
    // kind=0 interpreted as float is 0.0
    expect(gpu[3]).toBe(0)
  })

  it('encodes glass as kind=1', () => {
    const m = new Material({ kind: 'glass', albedo: [1, 1, 1], ior: 1.51 })
    const gpu = m.toGPU()
    expect(gpu[4]).toBeCloseTo(1.51)
    // kind field should encode 1
    expect(gpu[3]).toBe(1)
  })

  it('encodes emissive as kind=2', () => {
    const m = new Material({ kind: 'emissive', albedo: [1, 1, 1], emission: 5.0 })
    const gpu = m.toGPU()
    expect(gpu[3]).toBe(2)
    expect(gpu[6]).toBeCloseTo(5.0)
  })

  it('returns Float32Array of length 8', () => {
    const m = new Material()
    expect(m.toGPU()).toBeInstanceOf(Float32Array)
    expect(m.toGPU()).toHaveLength(8)
  })
})

// ─── Scene ───────────────────────────────────────────────────────────────────

describe('Scene', () => {
  it('addSphere registers material and stores sphere', () => {
    const scene = new Scene()
    const mat = new Material({ kind: 'diffuse', albedo: [0.5, 0.5, 0.5] })
    scene.addSphere({ center: [0, 0, -5], radius: 1.0, material: mat })
    expect(scene.spheres).toHaveLength(1)
    expect(scene.materials).toHaveLength(1)
    expect(scene.spheres[0].radius).toBe(1.0)
    expect(scene.spheres[0].matIndex).toBe(0)
  })

  it('addPlane normalises the normal vector', () => {
    const scene = new Scene()
    const mat = new Material()
    scene.addPlane({ point: [0, 0, 0], normal: [0, 2, 0], material: mat })
    const [nx, ny, nz] = scene.planes[0].normal
    expect(Math.sqrt(nx*nx + ny*ny + nz*nz)).toBeCloseTo(1.0)
    expect(ny).toBeCloseTo(1.0)
  })

  it('addLight accepts scalar intensity', () => {
    const scene = new Scene()
    scene.addLight({ position: [0, 5, 0], intensity: 10 })
    expect(scene.sceneLights[0].intensity).toEqual([10, 10, 10])
  })

  it('spheresGPU encodes correct byte length', () => {
    const scene = new Scene()
    const mat = new Material()
    scene.addSphere({ center: [1, 2, 3], radius: 0.5, material: mat })
    scene.addSphere({ center: [4, 5, 6], radius: 1.0, material: mat })
    // each sphere = 8 floats × 2
    const gpu = scene.spheresGPU()
    expect(gpu).toBeInstanceOf(Float32Array)
    expect(gpu.length).toBe(16)
    expect(gpu[0]).toBeCloseTo(1)
    expect(gpu[1]).toBeCloseTo(2)
    expect(gpu[2]).toBeCloseTo(3)
    expect(gpu[3]).toBeCloseTo(0.5)
  })

  it('planesGPU encodes point and normal', () => {
    const scene = new Scene()
    const mat = new Material()
    scene.addPlane({ point: [0, -1, 0], normal: [0, 1, 0], material: mat })
    const gpu = scene.planesGPU()
    expect(gpu.length).toBe(8)
    expect(gpu[1]).toBeCloseTo(-1)  // point.y
    expect(gpu[5]).toBeCloseTo(1.0) // normal.y
  })

  it('materialsGPU packs all materials', () => {
    const scene = new Scene()
    scene.addMaterial(new Material({ kind: 'diffuse', albedo: [1, 0, 0] }))
    scene.addMaterial(new Material({ kind: 'glass',   albedo: [1, 1, 1], ior: 1.5 }))
    const gpu = scene.materialsGPU()
    expect(gpu.length).toBe(16) // 2 × 8 floats
  })
})

// ─── BVH ─────────────────────────────────────────────────────────────────────

describe('buildBVH', () => {
  it('returns Float32Array of 8 floats for single node', () => {
    const scene = new Scene()
    const mat = new Material()
    scene.addSphere({ center: [0, 0, 0], radius: 1.0, material: mat })
    const bvh = buildBVH(scene)
    expect(bvh).toBeInstanceOf(Float32Array)
    expect(bvh.length).toBe(8)
  })

  it('AABB encompasses all spheres', () => {
    const scene = new Scene()
    const mat = new Material()
    scene.addSphere({ center: [-3, 0, 0], radius: 0.5, material: mat })
    scene.addSphere({ center: [ 3, 0, 0], radius: 0.5, material: mat })
    const bvh = buildBVH(scene)
    // aabbMin.x = -3.5, aabbMax.x = 3.5
    expect(bvh[0]).toBeCloseTo(-3.5)
    expect(bvh[4]).toBeCloseTo(3.5)
  })

  it('returns degenerate node for empty scene', () => {
    const scene = new Scene()
    const bvh = buildBVH(scene)
    expect(bvh).toBeInstanceOf(Float32Array)
    expect(bvh.length).toBe(8)
  })

  it('leaf node has LEAF_BIT set in rightIdx', () => {
    const scene = new Scene()
    const mat = new Material()
    scene.addSphere({ center: [0, 0, 0], radius: 1.0, material: mat })
    const bvh = buildBVH(scene)
    const u32 = new Uint32Array(bvh.buffer)
    const LEAF_BIT = 0x80000000
    // rightIdx is index 7
    expect(u32[7] & LEAF_BIT).toBeTruthy()
  })
})

// ─── GPU render smoke test (skipped in non-WebGPU environments) ──────────────

describe('WebGPU render (skipped without GPU)', () => {
  it('skips gracefully when WebGPU is unavailable', async () => {
    const hasWebGPU = typeof navigator !== 'undefined' && !!navigator.gpu
    if (!hasWebGPU) {
      // Explicitly skip — this is expected in CI/Node
      console.log('  [skip] WebGPU not available in this environment.')
      return
    }

    // If WebGPU IS available (e.g. Chrome headless with --enable-features=WebGPU):
    // request an adapter and verify we get one.
    const adapter = await navigator.gpu.requestAdapter()
    expect(adapter).not.toBeNull()
  })
})
