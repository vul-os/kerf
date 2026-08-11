/**
 * Typed stand-ins for three.js objects in tests.
 *
 * Most of three constructs fine without a GPU — Scene, PerspectiveCamera,
 * Box3, BufferGeometry are all plain JS until something renders them — so the
 * factories here return *real* objects wherever that is possible. A real object
 * is strictly better than a literal with the two fields the code under test
 * happens to read: it cannot drift out of sync with three's API, and it catches
 * a call the double would have silently accepted.
 *
 * WebGLRenderer is the exception. It needs a canvas and a live GL context, so
 * it stays a double, and the cast that makes it typeable lives here rather than
 * at each call site — one place to look, with the reason attached.
 *
 * `geom3` covers the other half of the problem: Kerf's parts hold either a
 * three BufferGeometry or a JSCAD Geom3, and tests routinely build a Geom3 with
 * only the polygons the assertion needs. Geom3 requires `transforms`, so the
 * literal has to be completed rather than cast away.
 */
import * as THREE from 'three'
import type { Geom3 } from '../types/geometry.js'

/** A real Scene. */
export function scene(): THREE.Scene {
  return new THREE.Scene()
}

/** A real PerspectiveCamera with the fields most tests assert on. */
export function camera(
  { aspect = 1, fov = 45, near = 0.1, far = 1000 } = {},
): THREE.PerspectiveCamera {
  return new THREE.PerspectiveCamera(fov, aspect, near, far)
}

/**
 * A WebGLRenderer double.
 *
 * The one three object that cannot be constructed headless — it acquires a GL
 * context in its constructor. Post-processing code only ever asks it for the
 * drawing-buffer size, so that is what the double provides.
 */
export function renderer(width = 512, height = 512): THREE.WebGLRenderer {
  return {
    getSize(target: THREE.Vector2) {
      target.x = width
      target.y = height
      return target
    },
  } as unknown as THREE.WebGLRenderer
}

/** A real Box3 over the given corners. */
export function box3(
  min: [number, number, number] = [-1, -1, -1],
  max: [number, number, number] = [1, 1, 1],
): THREE.Box3 {
  return new THREE.Box3(new THREE.Vector3(...min), new THREE.Vector3(...max))
}

/** A real BufferGeometry with a position attribute, and optionally an index. */
export function bufferGeometry(
  positions: number[] | Float32Array = [0, 0, 0, 1, 0, 0, 0, 1, 0],
  indices?: number[] | Uint32Array,
): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute(
    'position',
    new THREE.BufferAttribute(
      positions instanceof Float32Array ? positions : new Float32Array(positions),
      3,
    ),
  )
  if (indices) {
    geometry.setIndex(
      new THREE.BufferAttribute(
        indices instanceof Uint32Array ? indices : new Uint32Array(indices),
        1,
      ),
    )
  }
  return geometry
}

/**
 * A JSCAD Geom3 carrying the given polygons.
 *
 * `transforms` is required by the type and read by JSCAD's own operations, so
 * a `{ polygons }` literal is not a Geom3 — it is a Geom3 that will throw the
 * first time anything transforms it. Defaults to the identity matrix.
 */
export function geom3(polygons: unknown[] = [], transforms?: number[]): Geom3 {
  return {
    polygons,
    transforms: transforms ?? [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
  } as Geom3
}

/** A Geom3 built from triangles given as flat vertex triples. */
export function geom3FromTriangles(triangles: number[][][]): Geom3 {
  return geom3(triangles.map((vertices) => ({ vertices })))
}
