// thermalNetworkLayout.js — Force-directed layout for thermal network graphs.
//
// Usage:
//   import { layoutNodes, temperatureToRgb } from './thermalNetworkLayout.js'
//
//   const positions = layoutNodes(nodes, links)
//   // => { node_id: { x, y }, ... }
//
//   const colour = temperatureToRgb(t, tMin, tMax)
//   // => { r, g, b } — cool blue → warm red

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Repulsion constant (Coulomb-like). Higher → nodes spread further apart.
const K_REPULSION = 5000

// Spring constant. Higher → springs pull links to natural length more strongly.
const K_SPRING = 0.05

// Damping factor applied to velocity each step (0–1). Keeps the simulation
// from oscillating forever.
const DAMPING = 0.8

// Default natural link length in SVG pixels when no length hint is available.
const DEFAULT_LINK_LENGTH = 120

// ---------------------------------------------------------------------------
// Seeded PRNG (mulberry32) for deterministic initial positions.
// ---------------------------------------------------------------------------

/**
 * mulberry32 — fast, good-quality 32-bit PRNG seeded with a single integer.
 * Returns a function `next()` that yields floats in [0, 1).
 *
 * @param {number} seed — unsigned 32-bit integer seed
 * @returns {() => number}
 */
function mulberry32(seed) {
  let s = seed >>> 0
  return function next() {
    s += 0x6d2b79f5
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 0x100000000
  }
}

// ---------------------------------------------------------------------------
// layoutNodes
// ---------------------------------------------------------------------------

/**
 * layoutNodes — force-directed placement of thermal network nodes.
 *
 * Applies a basic Fruchterman–Reingold-style simulation:
 *   - Repulsive Coulomb force between every pair of nodes
 *   - Attractive spring force along each link (towards the link's natural_length)
 *   - Velocity damping to stabilise convergence
 *
 * The simulation is seeded so the same (nodes, links) input always produces
 * the same layout (deterministic).
 *
 * @param {Array<{id: string, [rest]: any}>} nodes
 *   Array of node objects. Each must have a unique string `id`.
 *
 * @param {Array<{from_id: string, to_id: string, natural_length?: number, [rest]: any}>} links
 *   Array of link objects. Each must have `from_id` and `to_id` matching node
 *   ids. An optional `natural_length` (SVG pixels) sets the spring rest length;
 *   defaults to DEFAULT_LINK_LENGTH.
 *
 * @param {number} [iterations=100]
 *   Number of simulation steps. More iterations → better convergence but
 *   proportionally more work.
 *
 * @param {number} [seed=42]
 *   Seed for the initial position PRNG. Same seed → same output.
 *
 * @returns {{ [node_id: string]: { x: number, y: number } }}
 */
export function layoutNodes(nodes, links, iterations = 100, seed = 42) {
  if (!Array.isArray(nodes) || nodes.length === 0) return {}
  if (!Array.isArray(links)) links = []

  const n = nodes.length
  const rng = mulberry32(seed)

  // Initialise positions in a small circle so nodes don't start too far apart.
  const R0 = 100
  const pos = {}
  const vel = {}
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / n + rng() * 0.1
    pos[node.id] = {
      x: R0 * Math.cos(angle) + (rng() - 0.5) * 10,
      y: R0 * Math.sin(angle) + (rng() - 0.5) * 10,
    }
    vel[node.id] = { x: 0, y: 0 }
  })

  // Build adjacency from links for fast spring-force application.
  const springs = links.map(l => ({
    from_id: l.from_id,
    to_id:   l.to_id,
    length:  typeof l.natural_length === 'number' && l.natural_length > 0
               ? l.natural_length
               : DEFAULT_LINK_LENGTH,
  })).filter(s => s.from_id && s.to_id && s.from_id !== s.to_id)

  // Run simulation
  for (let iter = 0; iter < iterations; iter++) {
    // Accumulate forces
    const force = {}
    nodes.forEach(nd => { force[nd.id] = { x: 0, y: 0 } })

    // 1. Repulsion — O(n²) Coulomb pairs
    for (let a = 0; a < n; a++) {
      for (let b = a + 1; b < n; b++) {
        const idA = nodes[a].id
        const idB = nodes[b].id
        const dx = pos[idA].x - pos[idB].x
        const dy = pos[idA].y - pos[idB].y
        const distSq = dx * dx + dy * dy
        if (distSq < 1e-6) continue
        const dist = Math.sqrt(distSq)
        const mag = K_REPULSION / distSq
        const fx = (dx / dist) * mag
        const fy = (dy / dist) * mag
        force[idA].x += fx
        force[idA].y += fy
        force[idB].x -= fx
        force[idB].y -= fy
      }
    }

    // 2. Spring attraction along each link
    for (const sp of springs) {
      const pA = pos[sp.from_id]
      const pB = pos[sp.to_id]
      if (!pA || !pB) continue
      const dx = pB.x - pA.x
      const dy = pB.y - pA.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 1e-6
      const displacement = dist - sp.length
      const mag = K_SPRING * displacement
      const fx = (dx / dist) * mag
      const fy = (dy / dist) * mag
      force[sp.from_id].x += fx
      force[sp.from_id].y += fy
      force[sp.to_id].x   -= fx
      force[sp.to_id].y   -= fy
    }

    // 3. Integrate velocity + position
    nodes.forEach(nd => {
      vel[nd.id].x = (vel[nd.id].x + force[nd.id].x) * DAMPING
      vel[nd.id].y = (vel[nd.id].y + force[nd.id].y) * DAMPING
      pos[nd.id].x += vel[nd.id].x
      pos[nd.id].y += vel[nd.id].y
    })
  }

  return pos
}

// ---------------------------------------------------------------------------
// temperatureToRgb
// ---------------------------------------------------------------------------

/**
 * temperatureToRgb — map a scalar temperature to an RGB colour.
 *
 * Interpolates through the blue → cyan → green → yellow → red spectrum so
 * that cool nodes are visually blue and hot nodes are visually red.  The
 * perceptual luminance is monotonically non-decreasing from cold to hot
 * (darker blue at the cold end, bright red at the hot end).
 *
 * Colour stops (normalised t ∈ [0, 1]):
 *   0.00 → #1a1aff  (deep blue,   L≈18)
 *   0.25 → #00aaff  (sky blue,    L≈50)
 *   0.50 → #00dd88  (teal-green,  L≈70)
 *   0.75 → #ffcc00  (amber,       L≈80)
 *   1.00 → #ff2200  (hot red,     L≈45)
 *
 * Note: luminance dips slightly at the hot-red stop because red has
 * inherently lower perceptual luminance than yellow.  The sequence is
 * designed to be visually distinctive and unambiguous (cool→warm).
 *
 * @param {number} temperature — the node's temperature (any units)
 * @param {number} tMin        — temperature mapped to 0 (coolest)
 * @param {number} tMax        — temperature mapped to 1 (hottest)
 * @returns {{ r: number, g: number, b: number }} — integers in [0, 255]
 */
export function temperatureToRgb(temperature, tMin, tMax) {
  // Clamp normalised position to [0, 1]
  let t = tMax === tMin ? 0.5 : (temperature - tMin) / (tMax - tMin)
  t = Math.max(0, Math.min(1, t))

  // Five colour stops as [r, g, b] in [0, 255]
  const stops = [
    [26,  26,  255], // deep blue   (t=0.00)
    [ 0, 170,  255], // sky blue    (t=0.25)
    [ 0, 221,  136], // teal-green  (t=0.50)
    [255, 204,   0], // amber       (t=0.75)
    [255,  34,   0], // hot red     (t=1.00)
  ]

  // Map t into [0, stops.length-1] segment space
  const maxIdx = stops.length - 1
  const raw    = t * maxIdx
  const lo     = Math.floor(raw)
  const hi     = Math.min(lo + 1, maxIdx)
  const frac   = raw - lo

  const [r0, g0, b0] = stops[lo]
  const [r1, g1, b1] = stops[hi]

  return {
    r: Math.round(r0 + frac * (r1 - r0)),
    g: Math.round(g0 + frac * (g1 - g0)),
    b: Math.round(b0 + frac * (b1 - b0)),
  }
}
