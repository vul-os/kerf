/**
 * Pure helpers for FEM deformed-shape overlay math.
 * No Three.js or DOM dependency — importable in vitest.
 */

/**
 * Apply displacement scaling to a flat positions array (Float32Array or Array),
 * returning a new Float32Array of the same length.
 *
 * nodeDisplacements: array of {ux, uy, uz} objects, one per node.
 * positions:        flat [x0,y0,z0, x1,y1,z1, ...] original node coordinates.
 * scale:            visual scale factor (1.0 = true scale; 10–100 for exaggeration).
 *
 * The function intentionally handles fewer nodeDisplacements than nodes by
 * leaving the tail unchanged — FEM results may cover a subset when the mesh
 * includes rigid bodies.
 */
export function applyDisplacementScale(positions, nodeDisplacements, scale) {
  const out = new Float32Array(positions.length)
  const n = Math.min(nodeDisplacements.length, positions.length / 3)
  for (let i = 0; i < positions.length; i++) {
    out[i] = positions[i]
  }
  for (let i = 0; i < n; i++) {
    const d = nodeDisplacements[i]
    out[i * 3 + 0] += (d.ux || 0) * scale
    out[i * 3 + 1] += (d.uy || 0) * scale
    out[i * 3 + 2] += (d.uz || 0) * scale
  }
  return out
}

/**
 * Compute displacement magnitudes from nodeDisplacements array.
 * Returns Float32Array of length nodeDisplacements.length.
 */
export function displacementMagnitudes(nodeDisplacements) {
  const out = new Float32Array(nodeDisplacements.length)
  for (let i = 0; i < nodeDisplacements.length; i++) {
    const d = nodeDisplacements[i]
    if (typeof d.mag === 'number') {
      out[i] = d.mag
    } else {
      const ux = d.ux || 0
      const uy = d.uy || 0
      const uz = d.uz || 0
      out[i] = Math.sqrt(ux * ux + uy * uy + uz * uz)
    }
  }
  return out
}

/**
 * Map a normalised value [0..1] to an RGB array [r,g,b] in [0..1]
 * using a blue→cyan→green→yellow→red colormap (matches ParaView "Rainbow").
 */
export function scalarToRGB(t) {
  const clamped = Math.max(0, Math.min(1, t))
  // 4 segments: blue→cyan, cyan→green, green→yellow, yellow→red
  if (clamped < 0.25) {
    const s = clamped / 0.25
    return [0, s, 1]
  } else if (clamped < 0.5) {
    const s = (clamped - 0.25) / 0.25
    return [0, 1, 1 - s]
  } else if (clamped < 0.75) {
    const s = (clamped - 0.5) / 0.25
    return [s, 1, 0]
  } else {
    const s = (clamped - 0.75) / 0.25
    return [1, 1 - s, 0]
  }
}

/**
 * Build a vertex-color Float32Array (R,G,B per vertex) for a set of nodes,
 * coloured by their displacement magnitude relative to [0, maxMag].
 */
export function buildDisplacementColors(nodeDisplacements, maxMag) {
  const mags = displacementMagnitudes(nodeDisplacements)
  const colors = new Float32Array(mags.length * 3)
  const norm = maxMag > 0 ? 1 / maxMag : 1
  for (let i = 0; i < mags.length; i++) {
    const [r, g, b] = scalarToRGB(mags[i] * norm)
    colors[i * 3 + 0] = r
    colors[i * 3 + 1] = g
    colors[i * 3 + 2] = b
  }
  return colors
}
