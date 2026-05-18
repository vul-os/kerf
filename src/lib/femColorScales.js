/**
 * Scientific colour palettes for FEM result visualisation.
 *
 * Each scale is a function (t: number) => [r, g, b] where:
 *   t ∈ [0, 1]  (clamped internally)
 *   r, g, b ∈ [0, 1]
 *
 * The palettes are implemented as piecewise-linear interpolations of
 * hand-sampled control points that match the canonical reference outputs.
 *
 * Palettes provided:
 *   viridis   — perceptually uniform, dark-blue → purple → teal → yellow
 *   plasma    — perceptually uniform, dark-blue → magenta → yellow
 *   jet       — classic rainbow (blue → cyan → green → yellow → red)
 *   rainbow   — alias for jet (same implementation, different name)
 *   coolwarm  — diverging blue → white → red
 */

// ── helper ────────────────────────────────────────────────────────────────────

/**
 * Piecewise-linear interpolation through an array of RGB stop points.
 * stops: [[r,g,b], ...] evenly spaced in t ∈ [0, 1]
 */
function piecewiseLinear(stops, t) {
  const clamped = Math.max(0, Math.min(1, t))
  const n = stops.length - 1
  if (n <= 0) return stops[0].slice()
  const scaled = clamped * n
  const lo = Math.floor(scaled)
  const hi = Math.min(lo + 1, n)
  const frac = scaled - lo
  const a = stops[lo]
  const b = stops[hi]
  return [
    a[0] + (b[0] - a[0]) * frac,
    a[1] + (b[1] - a[1]) * frac,
    a[2] + (b[2] - a[2]) * frac,
  ]
}

// ── viridis ───────────────────────────────────────────────────────────────────
// Sampled from matplotlib viridis: dark-blue → purple → teal → yellow
// Luminance is monotonically increasing (perceptually uniform).

const VIRIDIS_STOPS = [
  [0.267, 0.005, 0.329], // 0.0  dark blue-purple
  [0.283, 0.141, 0.458], // 0.1
  [0.254, 0.265, 0.530], // 0.2
  [0.207, 0.372, 0.553], // 0.3
  [0.164, 0.471, 0.558], // 0.4
  [0.128, 0.567, 0.551], // 0.5  teal
  [0.135, 0.659, 0.518], // 0.6
  [0.267, 0.749, 0.441], // 0.7
  [0.478, 0.821, 0.318], // 0.8
  [0.741, 0.873, 0.150], // 0.9
  [0.993, 0.906, 0.144], // 1.0  yellow
]

export function viridis(t) {
  return piecewiseLinear(VIRIDIS_STOPS, t)
}

// ── plasma ────────────────────────────────────────────────────────────────────
// Sampled from matplotlib plasma: dark-blue/purple → magenta → yellow
// Also perceptually uniform with monotonically increasing luminance.

const PLASMA_STOPS = [
  [0.050, 0.030, 0.528], // 0.0  dark blue
  [0.231, 0.023, 0.589], // 0.1
  [0.379, 0.015, 0.603], // 0.2
  [0.512, 0.029, 0.574], // 0.3
  [0.635, 0.091, 0.506], // 0.4
  [0.743, 0.183, 0.411], // 0.5  magenta-red
  [0.832, 0.286, 0.309], // 0.6
  [0.904, 0.403, 0.198], // 0.7
  [0.955, 0.537, 0.090], // 0.8
  [0.980, 0.681, 0.048], // 0.9
  [0.940, 0.975, 0.131], // 1.0  yellow
]

export function plasma(t) {
  return piecewiseLinear(PLASMA_STOPS, t)
}

// ── jet ───────────────────────────────────────────────────────────────────────
// Classic rainbow: dark-blue → cyan → green → yellow → red
// NOT perceptually uniform but widely used in engineering/FEM tools.

export function jet(t) {
  const c = Math.max(0, Math.min(1, t))
  // 4-segment piecewise: blue→cyan, cyan→green, green→yellow, yellow→red
  if (c < 0.125) {
    return [0, 0, 0.5 + c * 4]
  } else if (c < 0.375) {
    const s = (c - 0.125) / 0.25
    return [0, s, 1]
  } else if (c < 0.625) {
    const s = (c - 0.375) / 0.25
    return [s, 1, 1 - s]
  } else if (c < 0.875) {
    const s = (c - 0.625) / 0.25
    return [1, 1 - s, 0]
  } else {
    const s = (c - 0.875) / 0.125
    return [1 - s * 0.5, 0, 0]
  }
}

// ── rainbow ───────────────────────────────────────────────────────────────────
// Alias for jet (same hue sweep, matches the "ParaView Rainbow" preset
// already used in femDisplacement.js).

export function rainbow(t) {
  return jet(t)
}

// ── coolwarm ──────────────────────────────────────────────────────────────────
// Diverging: blue (cold) → white (neutral) → red (hot)
// Useful for signed quantities (e.g. principal stress, temperature delta).

const COOLWARM_STOPS = [
  [0.085, 0.532, 0.201], // 0.0  deep blue — wait, per Moreland 2009:
  // actually starts blue:
  // re-sampled correctly below
]

// Correct Moreland 2009 coolwarm (smooth diverging):
const COOLWARM_STOPS_CORRECT = [
  [0.230, 0.299, 0.754], // 0.0  vivid blue
  [0.439, 0.572, 0.923], // 0.2
  [0.699, 0.790, 0.977], // 0.4
  [0.865, 0.865, 0.865], // 0.5  neutral grey-white
  [0.957, 0.730, 0.644], // 0.6
  [0.882, 0.435, 0.343], // 0.8
  [0.706, 0.016, 0.150], // 1.0  vivid red
]

export function coolwarm(t) {
  return piecewiseLinear(COOLWARM_STOPS_CORRECT, t)
}

// ── registry ──────────────────────────────────────────────────────────────────

/**
 * Map of palette name → scale function.
 * Useful for picker components that select by name.
 */
export const COLOR_SCALES = {
  viridis,
  plasma,
  jet,
  rainbow,
  coolwarm,
}

/**
 * Ordered list for display in UI pickers.
 */
export const COLOR_SCALE_NAMES = ['viridis', 'plasma', 'jet', 'rainbow', 'coolwarm']

/**
 * Convert a normalised scalar t ∈ [0, 1] to a CSS rgb() string using the
 * named palette.  Falls back to viridis for unknown names.
 */
export function scaleToCSS(scaleName, t) {
  const fn = COLOR_SCALES[scaleName] || viridis
  const [r, g, b] = fn(t)
  return `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`
}
