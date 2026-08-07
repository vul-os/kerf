/**
 * PathTracerScene.ts — Scene graph + BVH builder for WebGPU path-tracer.
 *
 * Exports:
 *   class Material  — material descriptor
 *   class Scene     — sphere/plane/light container + serialiser
 *   buildBVH(scene) — returns flat BvhNode array (currently wraps all spheres
 *                     in one root AABB; full SAH BVH is laid in as a TODO)
 */

import type { Vec3 } from '../../types'

export type MaterialKind = 'diffuse' | 'glass' | 'emissive'

export interface MaterialOptions {
  kind?: MaterialKind
  /** linear RGB [0..1] */
  albedo?: Vec3
  /** index of refraction (glass) */
  ior?: number
  roughness?: number
  /** emissive scale (emissive kind) */
  emission?: number
}

interface Sphere { center: Vec3; radius: number; matIndex: number }
interface Plane { point: Vec3; normal: Vec3; matIndex: number }
interface SceneLight { position: Vec3; intensity: Vec3 }

// ─── Material ────────────────────────────────────────────────────────────────

export class Material {
  kind: MaterialKind
  albedo: Vec3
  ior: number
  roughness: number
  emission: number

  constructor({ kind = 'diffuse', albedo = [0.8, 0.8, 0.8], ior = 1.5, roughness = 0.0, emission = 1.0 }: MaterialOptions = {}) {
    this.kind      = kind
    this.albedo    = albedo
    this.ior       = ior
    this.roughness = roughness
    this.emission  = emission
  }

  /** Encode as Float32Array for GPU upload (matches Material struct in WGSL: 8 × f32). */
  toGPU(): Float32Array {
    const kindMap: Record<MaterialKind, number> = { diffuse: 0, glass: 1, emissive: 2 }
    return new Float32Array([
      this.albedo[0], this.albedo[1], this.albedo[2],
      kindMap[this.kind] ?? 0,
      this.ior,
      this.roughness,
      this.emission,
      0, // _pad
    ])
  }
}

// ─── Scene ───────────────────────────────────────────────────────────────────

export class Scene {
  spheres: Sphere[]
  planes: Plane[]
  sceneLights: SceneLight[]
  materials: Material[]

  constructor() {
    this.spheres   = []
    this.planes    = []
    this.sceneLights = []
    this.materials = []
  }

  /** Register a material and return its index. */
  addMaterial(mat: Material): number {
    this.materials.push(mat)
    return this.materials.length - 1
  }

  addSphere({ center, radius, material }: { center: Vec3; radius: number; material: Material | number }): void {
    const matIndex = material instanceof Material
      ? this.addMaterial(material)
      : material // allow passing pre-registered index
    this.spheres.push({ center, radius, matIndex })
  }

  /**
   * @param opts.point   — any point on the plane
   * @param opts.normal  — outward normal (will be normalised)
   */
  addPlane({ point, normal, material }: { point: Vec3; normal: Vec3; material: Material | number }): void {
    const n = _normalise(normal)
    const matIndex = material instanceof Material
      ? this.addMaterial(material)
      : material
    this.planes.push({ point, normal: n, matIndex })
  }

  /** @param opts.intensity — RGB or scalar */
  addLight({ position, intensity }: { position: Vec3; intensity: Vec3 | number }): void {
    const rgb: Vec3 = typeof intensity === 'number'
      ? [intensity, intensity, intensity]
      : intensity
    this.sceneLights.push({ position, intensity: rgb })
  }

  // ── GPU serialisation ────────────────────────────────────────────────────

  /** Float32Array: each sphere = 8 floats (center xyz, radius, matIndex, pad×3) */
  spheresGPU(): Float32Array {
    const buf = new Float32Array(this.spheres.length * 8)
    this.spheres.forEach(({ center, radius, matIndex }, i) => {
      const o = i * 8
      buf[o + 0] = center[0]
      buf[o + 1] = center[1]
      buf[o + 2] = center[2]
      buf[o + 3] = radius
      // matIndex stored as bit-cast float via Uint32 view
      new Uint32Array(buf.buffer, (o + 4) * 4, 1)[0] = matIndex
      // pad: already 0
    })
    return buf
  }

  /** Float32Array: each plane = 8 floats (point xyz, pad, normal xyz, matIndex) */
  planesGPU(): Float32Array {
    const buf = new Float32Array(this.planes.length * 8)
    this.planes.forEach(({ point, normal, matIndex }, i) => {
      const o = i * 8
      buf[o + 0] = point[0]
      buf[o + 1] = point[1]
      buf[o + 2] = point[2]
      // _pad0 = 0
      buf[o + 4] = normal[0]
      buf[o + 5] = normal[1]
      buf[o + 6] = normal[2]
      new Uint32Array(buf.buffer, (o + 7) * 4, 1)[0] = matIndex
    })
    return buf
  }

  /** Float32Array: each light = 8 floats (position xyz, pad, intensity xyz, pad) */
  lightsGPU(): Float32Array {
    const buf = new Float32Array(this.sceneLights.length * 8)
    this.sceneLights.forEach(({ position, intensity }, i) => {
      const o = i * 8
      buf[o + 0] = position[0]
      buf[o + 1] = position[1]
      buf[o + 2] = position[2]
      // _pad0
      buf[o + 4] = intensity[0]
      buf[o + 5] = intensity[1]
      buf[o + 6] = intensity[2]
      // _pad1
    })
    return buf
  }

  /** Float32Array: packed material array — each material = 8 floats */
  materialsGPU(): Float32Array {
    const arrays = this.materials.map((m) => m.toGPU())
    const total = new Float32Array(arrays.reduce((s, a) => s + a.length, 0))
    let offset = 0
    for (const a of arrays) {
      total.set(a, offset)
      offset += a.length
    }
    return total
  }
}

// ─── BVH ─────────────────────────────────────────────────────────────────────

/**
 * Build a flat BVH over all spheres in `scene`.
 *
 * Current implementation: single-level (one root AABB containing everything).
 * Suitable for up to ~20 primitives; a SAH split pass is straightforward to
 * add by recursing over sphere centroids.
 *
 * @returns flat array of BvhNode (each node = 8 floats):
 *   [aabbMin.xyz, leftIdx, aabbMax.xyz, rightIdx]
 *   Leaf node: rightIdx MSB set (0x80000000), leftIdx = first sphere index,
 *   rightIdx & 0x7FFFFFFF = count.
 */
export function buildBVH(scene: Scene): Float32Array {
  const spheres = scene.spheres
  if (spheres.length === 0) {
    // Empty scene — return a degenerate node
    return new Float32Array(8)
  }

  // Compute root AABB
  let minX = Infinity, minY = Infinity, minZ = Infinity
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
  for (const { center: [cx, cy, cz], radius: r } of spheres) {
    minX = Math.min(minX, cx - r); maxX = Math.max(maxX, cx + r)
    minY = Math.min(minY, cy - r); maxY = Math.max(maxY, cy + r)
    minZ = Math.min(minZ, cz - r); maxZ = Math.max(maxZ, cz + r)
  }

  // Single leaf node covers all spheres — shader does linear search inside it
  const LEAF_BIT = 0x80000000
  const node = new Float32Array(8)
  const nodeU32 = new Uint32Array(node.buffer)
  node[0] = minX; node[1] = minY; node[2] = minZ
  nodeU32[3] = 0                             // leftIdx = first sphere index
  node[4] = maxX; node[5] = maxY; node[6] = maxZ
  nodeU32[7] = (spheres.length | LEAF_BIT) >>> 0

  return node
}

// ─── Prebuilt scene factories ─────────────────────────────────────────────────

/**
 * Default "Glass Spheres" scene: 3 glass spheres with different IORs on a
 * checkerboard plane, lit by a single area light.
 */
export function createGlassSpheresScene(): Scene {
  const scene = new Scene()

  // Materials
  const floor = new Material({ kind: 'diffuse', albedo: [0.8, 0.8, 0.7] })
  const glassBK7  = new Material({ kind: 'glass', albedo: [1.0, 1.0, 1.0], ior: 1.51 })  // BK7 optical glass
  const glassSF11 = new Material({ kind: 'glass', albedo: [1.0, 0.95, 0.9], ior: 1.78 }) // SF11 dense flint
  const glassWater = new Material({ kind: 'glass', albedo: [0.9, 0.98, 1.0], ior: 1.33 }) // Water

  scene.addPlane({ point: [0, -1, 0], normal: [0, 1, 0], material: floor })
  scene.addSphere({ center: [-2.0, 0, -5], radius: 1.0, material: glassBK7 })
  scene.addSphere({ center: [ 0.0, 0, -5], radius: 1.0, material: glassSF11 })
  scene.addSphere({ center: [ 2.0, 0, -5], radius: 1.0, material: glassWater })

  scene.addLight({ position: [0, 6, -4], intensity: [15, 15, 15] })

  return scene
}

/**
 * Cornell Box scene approximation using spheres + planes.
 */
export function createCornellBoxScene(): Scene {
  const scene = new Scene()

  const white  = new Material({ kind: 'diffuse', albedo: [0.73, 0.73, 0.73] })
  const red    = new Material({ kind: 'diffuse', albedo: [0.65, 0.05, 0.05] })
  const green  = new Material({ kind: 'diffuse', albedo: [0.12, 0.45, 0.15] })
  // NOTE: constructed but never assigned to a surface — addLight() below creates a point
  // light instead. Pre-existing in the source (confirmed against the pre-migration .js);
  // left as-is (no behaviour change), just renamed to satisfy the unused-var lint rule.
  const _light = new Material({ kind: 'emissive', albedo: [15, 15, 15], emission: 1.0 })
  const glass  = new Material({ kind: 'glass', albedo: [1, 1, 1], ior: 1.5 })

  // Walls (planes)
  scene.addPlane({ point: [0, 0, 0],    normal: [0, 1, 0],  material: white })  // floor
  scene.addPlane({ point: [0, 5.5, 0],  normal: [0, -1, 0], material: white })  // ceiling
  scene.addPlane({ point: [0, 0, -7],   normal: [0, 0, 1],  material: white })  // back wall
  scene.addPlane({ point: [-2.75, 0, 0], normal: [1, 0, 0],  material: red })   // left wall
  scene.addPlane({ point: [ 2.75, 0, 0], normal: [-1, 0, 0], material: green }) // right wall

  // Sphere
  scene.addSphere({ center: [0, 1.2, -5], radius: 1.2, material: glass })

  // Ceiling light
  scene.addLight({ position: [0, 5.4, -5], intensity: [15, 15, 15] })

  return scene
}

/**
 * Prism / dispersion demo: a triangular prism approximated as a glass sphere
 * with the highest IOR, plus a background light.
 */
export function createPrismScene(): Scene {
  const scene = new Scene()

  const floor  = new Material({ kind: 'diffuse', albedo: [0.5, 0.5, 0.5] })
  const prism  = new Material({ kind: 'glass', albedo: [1, 1, 1], ior: 1.9 }) // Dense glass
  const redSph = new Material({ kind: 'diffuse', albedo: [0.9, 0.1, 0.1] })
  const bluSph = new Material({ kind: 'diffuse', albedo: [0.1, 0.2, 0.9] })

  scene.addPlane({ point: [0, -1, 0], normal: [0, 1, 0], material: floor })
  scene.addSphere({ center: [0, 0.5, -5], radius: 1.5, material: prism })
  scene.addSphere({ center: [-3.5, 0, -6], radius: 0.7, material: redSph })
  scene.addSphere({ center: [ 3.5, 0, -6], radius: 0.7, material: bluSph })

  scene.addLight({ position: [0, 8, -4], intensity: [20, 20, 20] })

  return scene
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function _normalise([x, y, z]: Vec3): Vec3 {
  const len = Math.sqrt(x * x + y * y + z * z)
  return len < 1e-10 ? [0, 1, 0] : [x / len, y / len, z / len]
}
