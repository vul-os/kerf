/**
 * Narrowing helpers for the three.js object graph.
 *
 * three's own types are honest about two things the app was quietly assuming:
 *
 *   `Mesh.material` is `Material | Material[]`. A multi-material mesh — which
 *   any imported STEP or GLB with per-face materials produces — makes
 *   `mesh.material.dispose` undefined. Call sites written as
 *   `mesh.material?.dispose()` then skip the dispose and leak the GPU
 *   allocation; call sites written as `mesh.material.dispose()` throw
 *   "dispose is not a function"; and an assignment like
 *   `mesh.material.vertexColors = true` lands on the array object and does
 *   nothing at all, so the colours never appear.
 *
 *   `Object3D.children` and the `traverse` callback are `Object3D`, which has
 *   no `geometry` or `material`. Reading them off an arbitrary child is
 *   undefined for a Group, a Light or a Bone.
 *
 * These are the fixes for both, in one place, so no call site has to remember.
 */
import * as THREE from 'three'

/** Every material on an object, whether it carries one or an array. */
export function materialsOf(
  material: THREE.Material | THREE.Material[] | null | undefined,
): THREE.Material[] {
  if (!material) return []
  return Array.isArray(material) ? material : [material]
}

/**
 * Dispose every material on an object. Safe on a mesh with none, one, or an
 * array — which is the whole point.
 */
export function disposeMaterial(
  material: THREE.Material | THREE.Material[] | null | undefined,
): void {
  for (const m of materialsOf(material)) m.dispose?.()
}

/**
 * Dispose an object's geometry and all of its materials.
 *
 * Takes any Object3D rather than a Mesh, because the call sites are `remove()`
 * and `traverse()` handlers where the static type is Object3D and only some
 * children carry GPU resources. A Group or a Light simply has nothing to do.
 */
export function disposeObject(object: THREE.Object3D | null | undefined): void {
  if (!object) return
  const carrier = object as Partial<Pick<THREE.Mesh, 'geometry' | 'material'>>
  carrier.geometry?.dispose?.()
  disposeMaterial(carrier.material)
}

/** Dispose every geometry and material under a root, inclusive. */
export function disposeSubtree(root: THREE.Object3D | null | undefined): void {
  root?.traverse(disposeObject)
}

/**
 * Set a property on every material of an object.
 *
 * Assigning through `mesh.material.x = v` is wrong for the array case in a way
 * nothing reports: the write succeeds, on the array.
 */
export function setMaterialProp<K extends keyof THREE.Material>(
  material: THREE.Material | THREE.Material[] | null | undefined,
  key: K,
  value: THREE.Material[K],
): void {
  for (const m of materialsOf(material)) m[key] = value
}

/** True when an Object3D is a Mesh, narrowing it for geometry/material access. */
export function isMesh(object: THREE.Object3D | null | undefined): object is THREE.Mesh {
  return !!object && (object as THREE.Mesh).isMesh === true
}

/** True when an Object3D is an InstancedMesh. */
export function isInstancedMesh(
  object: THREE.Object3D | null | undefined,
): object is THREE.InstancedMesh {
  return !!object && (object as THREE.InstancedMesh).isInstancedMesh === true
}

/** True when an Object3D is a Line, LineSegments or LineLoop. */
export function isLine(object: THREE.Object3D | null | undefined): object is THREE.Line {
  return !!object && (object as THREE.Line).isLine === true
}

/**
 * The position attribute of a geometry, or null.
 *
 * `getAttribute` returns `BufferAttribute | InterleavedBufferAttribute`, and
 * the interleaved variant has no `.array` of its own — reading one as though
 * it did yields the whole interleaved buffer rather than the positions.
 */
export function positionAttribute(
  geometry: THREE.BufferGeometry | null | undefined,
): THREE.BufferAttribute | null {
  const attribute = geometry?.getAttribute('position')
  if (!attribute) return null
  return (attribute as THREE.BufferAttribute).isBufferAttribute
    ? (attribute as THREE.BufferAttribute)
    : null
}
