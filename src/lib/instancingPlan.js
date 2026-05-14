// instancingPlan.js — S2 batched draw-call planner for the Kerf assembly viewport.
//
// `planInstances(components)` groups assembly Components by (file_id, config_id)
// and returns:
//   - One entry per unique part that appears ≥ 2 times:
//       { key, mesh_template_id, componentIds, transforms }
//     where `componentIds` is the parallel array that maps instanceId → Component.id
//     and `transforms` is the parallel Array<THREE.Matrix4>.
//   - Singletons (parts appearing exactly once) are excluded from the plan —
//     they fall through to the normal per-Mesh path.
//
// The planner is pure: no Three.js imports, no side effects, no DOM. Tests can
// import it without a WebGL context.

import * as THREE from 'three'

/**
 * Group Components by identity key and separate instances from singletons.
 *
 * @param {Array<{
 *   id: string,
 *   file_id: string,
 *   config_id?: string,
 *   transform?: number[],
 * }>} components  — the `.assembly` file's components array (after parseAssembly)
 *
 * @returns {{
 *   groups: Array<{
 *     key: string,
 *     mesh_template_id: string,
 *     componentIds: string[],
 *     transforms: THREE.Matrix4[],
 *   }>,
 *   singletonIds: Set<string>,
 * }}
 *
 * `groups` contains only entries with ≥ 2 components (InstancedMesh candidates).
 * `singletonIds` is the set of component.id values that were NOT batched.
 */
export function planInstances(components) {
  if (!components || components.length === 0) {
    return { groups: [], singletonIds: new Set() }
  }

  // Build per-key buckets.
  const buckets = new Map() // key → { mesh_template_id, componentIds, transforms }
  for (const comp of components) {
    const fileId   = comp.file_id   || ''
    const configId = comp.config_id || ''
    const key = `${fileId}::${configId}`

    if (!buckets.has(key)) {
      buckets.set(key, {
        key,
        mesh_template_id: fileId,
        componentIds: [],
        transforms: [],
      })
    }

    const bucket = buckets.get(key)
    bucket.componentIds.push(comp.id)

    // Convert the stored 16-element row-major transform array to a Matrix4.
    // Assembly.js stores transforms row-major (human readable); Three.js stores
    // elements column-major — `matrix.set()` accepts row-major arguments so we
    // can pass the flat array directly using spread.
    const m = new THREE.Matrix4()
    if (comp.transform && comp.transform.length === 16) {
      // matrix.set(n11,n12,...n44) — row by row (Three convention for .set).
      // eslint-disable-next-line prefer-spread
      m.set(...comp.transform)
    }
    bucket.transforms.push(m)
  }

  // Split into groups (≥2 instances) and singletons.
  const groups      = []
  const singletonIds = new Set()

  for (const bucket of buckets.values()) {
    if (bucket.componentIds.length >= 2) {
      groups.push(bucket)
    } else {
      // Only one component for this key — keep as singleton.
      for (const id of bucket.componentIds) singletonIds.add(id)
    }
  }

  return { groups, singletonIds }
}

/**
 * Read the KERF_INSTANCING localStorage flag.
 * Default: ON (returns true if absent).
 *
 * @returns {boolean}
 */
export function instancingEnabled() {
  try {
    const v = window.localStorage.getItem('KERF_INSTANCING')
    if (v === null) return true   // default ON
    return v !== '0'
  } catch {
    return true
  }
}
