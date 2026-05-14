// instancingPlan.test.js — vitest coverage for the S2 instancing planner.
//
// The planner is pure (no WebGL, no DOM) so all five cases can be tested
// without any mocking or environment shims.
//
// Cases:
//   1. No duplicates (all singletons)
//   2. Two components with the same (file_id, config_id) → one instance group
//   3. Three distinct groups (≥2 each) with singletons mixed in
//   4. Single component → singleton, no groups
//   5. Empty assembly → empty result

import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { planInstances } from '../lib/instancingPlan.js'

// Identity transform (row-major 4×4 as flat array, same format as assembly.js)
const I = [
  1, 0, 0, 0,
  0, 1, 0, 0,
  0, 0, 1, 0,
  0, 0, 0, 1,
]

// A simple translation: T(5,0,0)
const T5 = [
  1, 0, 0, 5,
  0, 1, 0, 0,
  0, 0, 1, 0,
  0, 0, 0, 1,
]

// ---------------------------------------------------------------------------

describe('planInstances', () => {

  // 1. All components have distinct (file_id, config_id) → all singletons.
  it('returns no groups and all singletons when every component is unique', () => {
    const components = [
      { id: 'c1', file_id: 'fa', config_id: 'def', transform: I },
      { id: 'c2', file_id: 'fb', config_id: 'def', transform: I },
      { id: 'c3', file_id: 'fc', config_id: 'def', transform: I },
    ]
    const { groups, singletonIds } = planInstances(components)
    expect(groups).toHaveLength(0)
    expect(singletonIds.size).toBe(3)
    expect(singletonIds.has('c1')).toBe(true)
    expect(singletonIds.has('c2')).toBe(true)
    expect(singletonIds.has('c3')).toBe(true)
  })

  // 2. Two components share (file_id, config_id) → one instance group.
  it('produces one instance group for two components sharing the same file+config', () => {
    const components = [
      { id: 'screw-a', file_id: 'screw', config_id: 'm3', transform: I   },
      { id: 'screw-b', file_id: 'screw', config_id: 'm3', transform: T5  },
    ]
    const { groups, singletonIds } = planInstances(components)
    expect(groups).toHaveLength(1)
    expect(singletonIds.size).toBe(0)

    const g = groups[0]
    expect(g.key).toBe('screw::m3')
    expect(g.mesh_template_id).toBe('screw')
    expect(g.componentIds).toHaveLength(2)
    expect(g.componentIds).toContain('screw-a')
    expect(g.componentIds).toContain('screw-b')
    expect(g.transforms).toHaveLength(2)
    // Each transform should be a THREE.Matrix4.
    for (const t of g.transforms) {
      expect(t).toBeInstanceOf(THREE.Matrix4)
    }
  })

  // 3. Three distinct groups plus singletons.
  it('correctly separates three groups from two singletons', () => {
    const components = [
      // Group A (file=bolt, config=m4) — 3 instances
      { id: 'bolt-1', file_id: 'bolt', config_id: 'm4', transform: I },
      { id: 'bolt-2', file_id: 'bolt', config_id: 'm4', transform: T5 },
      { id: 'bolt-3', file_id: 'bolt', config_id: 'm4', transform: I },
      // Group B (file=nut, config=m4) — 2 instances
      { id: 'nut-1',  file_id: 'nut',  config_id: 'm4', transform: I },
      { id: 'nut-2',  file_id: 'nut',  config_id: 'm4', transform: T5 },
      // Group C (file=washer, config=flat) — 2 instances
      { id: 'w-1',    file_id: 'washer', config_id: 'flat', transform: I },
      { id: 'w-2',    file_id: 'washer', config_id: 'flat', transform: T5 },
      // Singletons
      { id: 'plate',  file_id: 'plate',  config_id: '',     transform: I },
      { id: 'bracket',file_id: 'bracket',config_id: '',     transform: I },
    ]
    const { groups, singletonIds } = planInstances(components)

    expect(groups).toHaveLength(3)
    expect(singletonIds.size).toBe(2)
    expect(singletonIds.has('plate')).toBe(true)
    expect(singletonIds.has('bracket')).toBe(true)

    const keys = groups.map((g) => g.key).sort()
    expect(keys).toContain('bolt::m4')
    expect(keys).toContain('nut::m4')
    expect(keys).toContain('washer::flat')

    const boltGroup = groups.find((g) => g.key === 'bolt::m4')
    expect(boltGroup.componentIds).toHaveLength(3)
  })

  // 4. Single component → singleton, no instance groups.
  it('treats a single component as a singleton (no groups)', () => {
    const components = [
      { id: 'only', file_id: 'part-x', config_id: 'v1', transform: I },
    ]
    const { groups, singletonIds } = planInstances(components)
    expect(groups).toHaveLength(0)
    expect(singletonIds.size).toBe(1)
    expect(singletonIds.has('only')).toBe(true)
  })

  // 5. Empty assembly → empty result.
  it('returns empty groups and empty singletonIds for an empty assembly', () => {
    const { groups, singletonIds } = planInstances([])
    expect(groups).toHaveLength(0)
    expect(singletonIds.size).toBe(0)
  })

  // Bonus: null / undefined components → empty result, no throw.
  it('handles null components gracefully', () => {
    const { groups, singletonIds } = planInstances(null)
    expect(groups).toHaveLength(0)
    expect(singletonIds.size).toBe(0)
  })

  // Bonus: components without a transform default to identity matrix.
  it('defaults to identity Matrix4 when transform is absent', () => {
    const components = [
      { id: 'a', file_id: 'f', config_id: 'c' },
      { id: 'b', file_id: 'f', config_id: 'c' },
    ]
    const { groups } = planInstances(components)
    expect(groups).toHaveLength(1)
    const identity = new THREE.Matrix4()
    for (const t of groups[0].transforms) {
      expect(t.elements).toEqual(identity.elements)
    }
  })
})
