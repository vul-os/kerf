/**
 * lengthTuning.js — KiCad-style PCB trace length tuning + differential-pair
 * skew compensation.
 *
 * Trace model (CircuitJSON):
 *   {
 *     type: 'pcb_trace',
 *     id: string,
 *     net_id: string,
 *     points: [{ x, y }, ...],      // polyline vertices, mm
 *     target_length_mm?: number,    // annotation for length-tuning
 *   }
 *
 * Differential pair model (board.differential_pairs — added by buses agent):
 *   [{
 *     name: string,
 *     net_p_id: string,
 *     net_n_id: string,
 *     skew_max_mm?: number,
 *   }]
 */

// ── Internal geometry helpers ─────────────────────────────────────────────────

function dist(a, b) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  return Math.sqrt(dx * dx + dy * dy)
}

/**
 * Unit vector from a to b.  Returns {x:1,y:0} if points coincide.
 */
function unit(a, b) {
  const d = dist(a, b)
  if (d < 1e-12) return { x: 1, y: 0 }
  return { x: (b.x - a.x) / d, y: (b.y - a.y) / d }
}

/**
 * Perpendicular (CCW 90°) of a unit vector.
 */
function perp(u) {
  return { x: -u.y, y: u.x }
}

/**
 * Sum an array of numbers.
 */
function sum(arr) {
  return arr.reduce((s, v) => s + v, 0)
}

// ── traceLength ───────────────────────────────────────────────────────────────

/**
 * Compute the total polyline length of a trace (sum of all segment lengths).
 *
 * @param {{ points: Array<{x: number, y: number}> }} trace
 * @returns {number} length in mm
 */
export function traceLength(trace) {
  if (!trace || !Array.isArray(trace.points) || trace.points.length < 2) return 0
  let total = 0
  for (let i = 0; i < trace.points.length - 1; i++) {
    total += dist(trace.points[i], trace.points[i + 1])
  }
  return total
}

// ── differentialSkew ──────────────────────────────────────────────────────────

/**
 * Return the lengths of the P and N traces for a named differential pair, plus
 * the skew delta (|length_p - length_n|).
 *
 * Defensive: returns null with an error string if the pair definition or its
 * traces are missing (buses agent may not have run yet).
 *
 * @param {Array|object} circuit_json
 * @param {string} pair_name
 * @returns {{ length_p: number, length_n: number, delta_mm: number }|{ error: string }}
 */
export function differentialSkew(circuit_json, pair_name) {
  const elements = Array.isArray(circuit_json) ? circuit_json : [circuit_json]

  // Find board element for differential_pairs definition
  const board = elements.find((e) => e?.type === 'pcb_board') ?? null

  const pairs = board?.differential_pairs
  if (!Array.isArray(pairs)) {
    return { error: 'board.differential_pairs not defined' }
  }

  const pairDef = pairs.find((p) => p.name === pair_name)
  if (!pairDef) {
    return { error: `differential pair '${pair_name}' not found` }
  }

  const { net_p_id, net_n_id } = pairDef
  const traces = elements.filter((e) => e?.type === 'pcb_trace')

  // Sum lengths across all trace segments belonging to each net
  const lenOf = (net_id) =>
    sum(traces.filter((t) => t.net_id === net_id).map(traceLength))

  const length_p = lenOf(net_p_id)
  const length_n = lenOf(net_n_id)

  return {
    length_p,
    length_n,
    delta_mm: Math.abs(length_p - length_n),
  }
}

// ── generateMeander ───────────────────────────────────────────────────────────

/**
 * Generate a meander path between start and end whose total polyline length is
 * approximately target_length.
 *
 * Styles:
 *   'serpentine' — symmetric square-wave (perpendicular teeth)
 *   'accordion'  — symmetric triangle-wave (diagonal teeth)
 *   'trombone'   — U-turn out-and-back (single semi-circular path approximated
 *                  as a rectangular detour)
 *
 * Throws if target_length < straight distance.
 *
 * @param {{x:number,y:number}} start
 * @param {{x:number,y:number}} end
 * @param {number} target_length  — desired path length in mm
 * @param {'serpentine'|'accordion'|'trombone'} style
 * @param {number} amplitude_mm   — half-width of teeth
 * @param {number} period_mm      — spacing between teeth centres
 * @returns {Array<{x:number,y:number}>}  ordered point list (includes start)
 */
export function generateMeander(
  start,
  end,
  target_length,
  style = 'serpentine',
  amplitude_mm = 0.5,
  period_mm = 1.0,
) {
  const straight = dist(start, end)

  if (target_length < straight - 1e-9) {
    throw new Error(
      `generateMeander: target_length (${target_length.toFixed(4)}) < straight distance (${straight.toFixed(4)})`,
    )
  }

  const extra = target_length - straight

  // If no extra length needed, return straight line
  if (extra < 1e-9) {
    return [{ x: start.x, y: start.y }, { x: end.x, y: end.y }]
  }

  const fwd = unit(start, end)   // along-axis unit vector
  const side = perp(fwd)         // perpendicular unit vector

  if (style === 'trombone') {
    return _tromboneMeander(start, end, target_length, fwd, side, amplitude_mm)
  }

  if (style === 'accordion') {
    return _accordionMeander(start, end, target_length, fwd, side, amplitude_mm, period_mm)
  }

  // Default: serpentine
  return _serpentineMeander(start, end, target_length, fwd, side, amplitude_mm, period_mm)
}

// ── Meander implementations ───────────────────────────────────────────────────

/**
 * Serpentine: square-wave teeth perpendicular to the trace axis.
 * Each tooth adds  2 * amplitude  of extra length (two vertical strokes) and
 * occupies `period_mm` along the axis.
 */
function _serpentineMeander(start, end, target_length, fwd, side, amplitude, period) {
  const straight = dist(start, end)
  const extra = target_length - straight

  // Each tooth: out amplitude + back amplitude = 2*amplitude extra path
  // plus the two horizontal connectors of length 0 (they stay on axis between teeth)
  // Actually for a square wave tooth of width = period/2:
  //   leg up = amplitude, across = period/2, leg down = amplitude
  //   extra per tooth = 2*amplitude (the two legs; across contributes to axis progress)
  const extraPerTooth = 2 * amplitude
  const nTeeth = Math.max(1, Math.ceil(extra / extraPerTooth))

  // Recompute period to fit exactly nTeeth teeth in straight distance, minimum period
  const effectivePeriod = Math.max(period, straight / nTeeth)

  const points = [{ x: start.x, y: start.y }]
  let side_sign = 1

  for (let i = 0; i < nTeeth; i++) {
    const t0 = (i / nTeeth)
    const t1 = ((i + 0.5) / nTeeth)
    const t2 = ((i + 1) / nTeeth)

    // base point at t0
    const b0 = _lerp(start, end, t0)
    // peak at t1 (offset by amplitude perpendicular)
    const peak_base = _lerp(start, end, t1)
    const peak = {
      x: peak_base.x + side.x * amplitude * side_sign,
      y: peak_base.y + side.y * amplitude * side_sign,
    }
    // base point at t2
    const b2 = _lerp(start, end, t2)

    // Square-wave: rise, across, fall
    const rise = {
      x: b0.x + side.x * amplitude * side_sign,
      y: b0.y + side.y * amplitude * side_sign,
    }
    const fall = {
      x: b2.x + side.x * amplitude * side_sign,
      y: b2.y + side.y * amplitude * side_sign,
    }

    points.push(rise, fall)
    side_sign = -side_sign
  }

  points.push({ x: end.x, y: end.y })
  return points
}

/**
 * Accordion: triangle-wave (diagonal strokes).
 * Each tooth: diagonal to peak then diagonal back = 2 * hypot(period/2, amplitude)
 * vs straight progress of `period`.
 * Extra per period = 2*hypot(p/2, A) - p
 */
function _accordionMeander(start, end, target_length, fwd, side, amplitude, period) {
  const straight = dist(start, end)
  const extra = target_length - straight

  const halfPeriod = period / 2
  const legLen = Math.sqrt(halfPeriod * halfPeriod + amplitude * amplitude)
  const extraPerTooth = 2 * legLen - period

  if (extraPerTooth <= 1e-9) {
    // Degenerate: amplitude too small — fall back to more teeth
    return _serpentineMeander(start, end, target_length, fwd, side, amplitude, period)
  }

  const nTeeth = Math.max(1, Math.ceil(extra / extraPerTooth))

  const points = [{ x: start.x, y: start.y }]
  let side_sign = 1

  for (let i = 0; i < nTeeth; i++) {
    const t_peak = (i + 0.5) / nTeeth
    const base_peak = _lerp(start, end, t_peak)
    const peak = {
      x: base_peak.x + side.x * amplitude * side_sign,
      y: base_peak.y + side.y * amplitude * side_sign,
    }
    points.push(peak)
    side_sign = -side_sign
  }

  points.push({ x: end.x, y: end.y })
  return points
}

/**
 * Trombone: single U-turn out-and-back detour.
 * The path goes out (amplitude) perpendicular, travels forward to a turn
 * point, reverses, comes back, and re-joins the exit direction.
 * Total extra length ≈ 2 * (amplitude * 2 + turn_length)
 *
 * Layout:
 *   start ─── detour_entry ─── [ out side ]
 *                                       |  turn_gap
 *             detour_exit  ─── [ out side ]
 *                                       |
 *   ...                         ─── end
 */
function _tromboneMeander(start, end, target_length, fwd, side, amplitude) {
  const straight = dist(start, end)
  const extra = target_length - straight

  // 4 perpendicular legs of length = amplitude each:
  // entry_out, turn_bottom, exit_out (reversed), entry_in
  // Plus a forward run of length `run` between the two tines.
  // Extra added = 4*amplitude + 2*run - 0 (no change in forward progress
  //   because we go out, forward, back to same x, and in)
  // So: extra = 4*amplitude + 2*run => run = (extra - 4*amplitude) / 2
  // If amplitude is too large we clamp run to 0 and reduce amplitude.

  let amp = amplitude
  let run = (extra - 4 * amp) / 2

  if (run < 0) {
    // reduce amplitude to fit
    amp = extra / 4
    run = 0
  }

  // Entry: 1/4 along the axis
  const entry = _lerp(start, end, 0.25)
  const exit_ = _lerp(start, end, 0.75)

  // Use midpoint between entry and exit for the trombone centre
  const mid_fwd = {
    x: (entry.x + exit_.x) / 2,
    y: (entry.y + exit_.y) / 2,
  }

  // Perpendicular offset
  const off = (x) => ({ x: x.x + side.x * amp, y: x.y + side.y * amp })

  // Run extension (forward direction)
  const half_run = run / 2
  const tip1 = {
    x: off(entry).x + fwd.x * half_run,
    y: off(entry).y + fwd.y * half_run,
  }
  const tip2 = {
    x: off(exit_).x + fwd.x * half_run,
    y: off(exit_).y + fwd.y * half_run,
  }

  return [
    { x: start.x, y: start.y },
    { x: entry.x, y: entry.y },
    off(entry),
    tip1,
    tip2,
    off(exit_),
    { x: exit_.x, y: exit_.y },
    { x: end.x, y: end.y },
  ]
}

// ── applyMeander ──────────────────────────────────────────────────────────────

/**
 * Replace segment at segment_index with a meander so that the updated trace
 * reaches its target_length_mm.
 *
 * The segment's start and end points are preserved exactly.
 *
 * @param {object} trace        — CircuitJSON pcb_trace
 * @param {number} segment_index
 * @param {string} style
 * @param {number} amplitude_mm
 * @returns {object}            — updated trace (deep copy)
 */
export function applyMeander(trace, segment_index, style = 'serpentine', amplitude_mm = 0.5) {
  if (!trace || !Array.isArray(trace.points) || trace.points.length < 2) {
    throw new Error('applyMeander: trace must have at least 2 points')
  }

  const pts = trace.points
  const nSegs = pts.length - 1

  if (segment_index < 0 || segment_index >= nSegs) {
    throw new Error(`applyMeander: segment_index ${segment_index} out of range [0, ${nSegs - 1}]`)
  }

  const target = trace.target_length_mm
  if (typeof target !== 'number' || target <= 0) {
    throw new Error('applyMeander: trace.target_length_mm must be a positive number')
  }

  const currentLen = traceLength(trace)
  const segStart = pts[segment_index]
  const segEnd = pts[segment_index + 1]
  const segLen = dist(segStart, segEnd)

  // Extra length we need to add
  const needed = target - currentLen

  if (needed < -1e-9) {
    throw new Error(
      `applyMeander: target_length_mm (${target}) < current length (${currentLen.toFixed(4)}) — cannot shorten a trace`,
    )
  }

  // The meander replaces this segment, so its target length = segLen + needed
  const meanderTarget = segLen + needed

  const meanderPts = generateMeander(
    segStart,
    segEnd,
    meanderTarget,
    style,
    amplitude_mm,
  )

  // Replace segment: points before + meander interior + points after
  const before = pts.slice(0, segment_index)
  const after = pts.slice(segment_index + 2)

  const newPoints = [...before, ...meanderPts, ...after]

  return { ...trace, points: newPoints }
}

// ── tuneTraceToTarget ─────────────────────────────────────────────────────────

/**
 * Automatically pick the longest straight segment in the trace and apply a
 * meander on it to reach target_length_mm.
 *
 * @param {object} trace
 * @param {string} style
 * @param {number} amplitude_mm
 * @returns {object} updated trace
 */
export function tuneTraceToTarget(trace, style = 'serpentine', amplitude_mm = 0.5) {
  if (!trace || !Array.isArray(trace.points) || trace.points.length < 2) {
    throw new Error('tuneTraceToTarget: invalid trace')
  }

  const pts = trace.points

  // Find the longest segment
  let maxLen = -1
  let maxIdx = 0
  for (let i = 0; i < pts.length - 1; i++) {
    const l = dist(pts[i], pts[i + 1])
    if (l > maxLen) {
      maxLen = l
      maxIdx = i
    }
  }

  return applyMeander(trace, maxIdx, style, amplitude_mm)
}

// ── matchDifferentialPair ─────────────────────────────────────────────────────

/**
 * Find the shorter trace of a diff pair and apply a meander to bring its
 * total net length within skew_max_mm of the longer trace.
 *
 * Uses the first pcb_trace segment for the shorter net that has a sufficient
 * straight segment to absorb the meander.
 *
 * @param {Array|object} circuit_json
 * @param {string} pair_name
 * @param {string} style
 * @param {number} amplitude_mm
 * @param {number} [skew_max_mm]  — overrides pair definition; defaults to 0.05
 * @returns {{ circuit_json: Array, tuned_net: string, delta_mm: number }}
 */
export function matchDifferentialPair(
  circuit_json,
  pair_name,
  style = 'serpentine',
  amplitude_mm = 0.5,
  skew_max_mm,
) {
  const elements = Array.isArray(circuit_json) ? [...circuit_json] : [circuit_json]

  const skewInfo = differentialSkew(elements, pair_name)
  if (skewInfo.error) {
    throw new Error(`matchDifferentialPair: ${skewInfo.error}`)
  }

  const { length_p, length_n, delta_mm } = skewInfo

  // Resolve skew_max_mm from argument or pair definition
  const board = elements.find((e) => e?.type === 'pcb_board') ?? {}
  const pairs = board?.differential_pairs ?? []
  const pairDef = pairs.find((p) => p.name === pair_name) ?? {}
  const maxSkew = skew_max_mm ?? pairDef.skew_max_mm ?? 0.05

  if (delta_mm <= maxSkew) {
    return { circuit_json: elements, tuned_net: null, delta_mm }
  }

  // Which net is shorter?
  const isP_shorter = length_p < length_n
  const shorter_net = isP_shorter ? pairDef.net_p_id : pairDef.net_n_id
  const longer_length = isP_shorter ? length_n : length_p

  // Find all traces for the shorter net (may be multiple segments)
  const shortTraces = elements
    .map((e, idx) => ({ e, idx }))
    .filter(({ e }) => e?.type === 'pcb_trace' && e.net_id === shorter_net)

  if (shortTraces.length === 0) {
    throw new Error(`matchDifferentialPair: no traces found for net '${shorter_net}'`)
  }

  // Pick the trace with the longest individual segment (best candidate for meander)
  let bestTraceEntry = null
  let bestSegLen = -1
  let bestSegIdx = 0

  for (const { e, idx } of shortTraces) {
    const pts = e.points ?? []
    for (let si = 0; si < pts.length - 1; si++) {
      const sl = dist(pts[si], pts[si + 1])
      if (sl > bestSegLen) {
        bestSegLen = sl
        bestSegIdx = si
        bestTraceEntry = { e, idx }
      }
    }
  }

  if (!bestTraceEntry) {
    throw new Error('matchDifferentialPair: no suitable segment found in shorter trace')
  }

  // Annotate with target_length_mm
  const currentShortTotal = sum(
    shortTraces.map(({ e }) => traceLength(e)),
  )
  const targetTotal = longer_length

  const annotated = {
    ...bestTraceEntry.e,
    target_length_mm: bestTraceEntry.e.target_length_mm ?? (currentShortTotal + (targetTotal - currentShortTotal)),
  }
  // Set target so that this trace picks up the entire delta
  annotated.target_length_mm = traceLength(bestTraceEntry.e) + (targetTotal - currentShortTotal)

  const tuned = applyMeander(annotated, bestSegIdx, style, amplitude_mm)

  // Replace in elements
  const newElements = [...elements]
  newElements[bestTraceEntry.idx] = tuned

  const finalSkew = differentialSkew(newElements, pair_name)

  return {
    circuit_json: newElements,
    tuned_net: shorter_net,
    delta_mm: finalSkew.delta_mm ?? 0,
  }
}

// ── Internal utilities ────────────────────────────────────────────────────────

function _lerp(a, b, t) {
  return {
    x: a.x + (b.x - a.x) * t,
    y: a.y + (b.y - a.y) * t,
  }
}
