function _toPts(seg) {
  const pts = seg.points || seg
  if (pts.length === 2 && typeof pts[0].x === 'number') {
    return pts
  }
  return pts.map(p => (Array.isArray(p) ? { x: p[0], y: p[1] } : p))
}

export function segmentMinDistance(seg1, seg2) {
  const pts1 = _toPts(seg1)
  const pts2 = _toPts(seg2)
  return _segSegDist(pts1[0], pts1[1], pts2[0], pts2[1])
}

function _segSegDist(a, b, c, d) {
  const dx1 = b.x - a.x, dy1 = b.y - a.y
  const dx2 = d.x - c.x, dy2 = d.y - c.y
  const cx = c.x - a.x, cy = c.y - a.y
  const len1Sq = dx1 * dx1 + dy1 * dy1
  const len2Sq = dx2 * dx2 + dy2 * dy2

  if (len1Sq === 0 && len2Sq === 0) {
    return Math.hypot(c.x - a.x, c.y - a.y)
  }

  if (len1Sq === 0) {
    return _ptSegDist(a, c, d)
  }
  if (len2Sq === 0) {
    return _ptSegDist(c, a, b)
  }

  const det = dx1 * dy2 - dy1 * dx2
  if (Math.abs(det) < 1e-12) {
    const d1 = _ptSegDist(a, c, d)
    const d2 = _ptSegDist(b, c, d)
    const d3 = _ptSegDist(c, a, b)
    const d4 = _ptSegDist(d, a, b)
    return Math.min(d1, d2, d3, d4)
  }

  const t = ((cx * dy2 - cy * dx2) / det)
  const u = ((dy1 * cx - dx1 * cy) / det)

  if (t > 0 && t < 1 && u > 0 && u < 1) {
    return 0
  }

  const d1 = _ptSegDist(a, c, d)
  const d2 = _ptSegDist(b, c, d)
  const d3 = _ptSegDist(c, a, b)
  const d4 = _ptSegDist(d, a, b)
  return Math.min(d1, d2, d3, d4)
}

function _ptSegDist(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return Math.hypot(p.x - a.x, p.y - a.y)
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq))
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
}

export function shoveSegment(seg, perpendicular_vec, amount_mm) {
  const pts = seg.points || seg
  const [p0, p1] = pts
  const nx = perpendicular_vec.x, ny = perpendicular_vec.y
  const dx = nx * amount_mm
  const dy = ny * amount_mm
  return {
    ...seg,
    points: [
      { x: p0.x + dx, y: p0.y + dy },
      { x: p1.x + dx, y: p1.y + dy }
    ]
  }
}

function _perpVector(seg) {
  const pts = seg.points || seg
  const [a, b] = pts
  const dx = b.x - a.x, dy = b.y - a.y
  const len = Math.hypot(dx, dy)
  if (len === 0) return { x: 0, y: 0 }
  return { x: -dy / len, y: dx / len }
}

function _intersectPoint(a, b, c, d) {
  const dx1 = b.x - a.x, dy1 = b.y - a.y
  const dx2 = d.x - c.x, dy2 = d.y - c.y
  const cx = c.x - a.x, cy = c.y - a.y
  const det = dx1 * dy2 - dy1 * dx2
  if (Math.abs(det) < 1e-12) return null
  const t = (cx * dy2 - cy * dx2) / det
  const u = (dx1 * cy - dy1 * cx) / det
  if (t >= 0 && t <= 1 && u >= 0 && u <= 1) {
    return { x: a.x + t * dx1, y: a.y + t * dy1, t, u }
  }
  return null
}

function _splitTraceAtPoint(trace, point, tol = 0.01) {
  const pts = trace.points
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1]
    const ip = _intersectPoint(a, b, point, point)
    if (!ip) continue
    const newPts = [...pts.slice(0, i + 1), { x: ip.x, y: ip.y }, ...pts.slice(i + 1)]
    return { trace, idx: i, point: { x: ip.x, y: ip.y }, newPts }
  }
  return null
}

function _traceSegments(trace) {
  const pts = trace.points
  const segs = []
  for (let i = 0; i < pts.length - 1; i++) {
    segs.push({ trace, segIdx: i, points: [pts[i], pts[i + 1]] })
  }
  return segs
}

function _isTJunction(newTrace, existingTrace) {
  const newPts = newTrace.points
  const existPts = existingTrace.points
  const tolerance = 0.01

  for (const np of [newPts[0], newPts[newPts.length - 1]]) {
    for (let i = 0; i < existPts.length - 1; i++) {
      const d = _ptSegDist(np, existPts[i], existPts[i + 1])
      if (d < tolerance) {
        return true
      }
    }
  }
  return false
}

function _doShove(circuit_json, layer, newSeg, clearance_mm, depth, maxDepth, shovedTraces, conflicts) {
  if (depth >= maxDepth) {
    return
  }

  const board = circuit_json.pcb_board || circuit_json.board || {}
  const newTrace = newSeg.trace

  for (const trace of board.pcb_trace || []) {
    if (trace.layer !== layer) continue
    if (trace.net_id === newTrace.net_id && _isTJunction(newTrace, trace)) continue
  }

  const existingTraces = (board.pcb_trace || []).filter(t => {
    if (t.layer !== layer) return false
    if (t.net_id === newSeg.trace.net_id && _isTJunction(newSeg.trace, t)) return false
    return true
  })

  const newPts = newSeg.points
  const conflictSegs = []

  for (const trace of existingTraces) {
    const segs = _traceSegments(trace)
    for (const seg of segs) {
      if (_segSegDist(newPts[0], newPts[1], seg.points[0], seg.points[1]) < clearance_mm) {
        conflictSegs.push(seg)
      }
    }
  }

  for (const cs of conflictSegs) {
    const traceId = cs.trace.id || cs.trace.pcb_trace_id
    if (conflicts.has(traceId)) continue

    const perp = _perpVector(cs)
    if (perp.x === 0 && perp.y === 0) continue

    const shoved = shoveSegment(cs, perp, clearance_mm)

    const trace = cs.trace
    const pts = [...trace.points]
    pts[cs.segIdx] = shoved.points[0]
    pts[cs.segIdx + 1] = shoved.points[1]

    const updatedTrace = { ...trace, points: pts }
    const board2 = circuit_json.pcb_board || circuit_json.board || {}
    const traces = board2.pcb_trace || []
    const idx = traces.findIndex(t => (t.id || t.pcb_trace_id) === (trace.id || trace.pcb_trace_id))
    if (idx >= 0) {
      traces[idx] = updatedTrace
    }

    shovedTraces.push(traceId)
    conflicts.add(traceId)

    if (board2.pcb_board) {
      board2.pcb_board.pcb_trace = traces
    } else {
      board2.pcb_trace = traces
    }

    const newSeg2 = { trace: updatedTrace, points: [shoved.points[0], shoved.points[1]] }
    _doShove(circuit_json, layer, newSeg2, clearance_mm, depth + 1, maxDepth, shovedTraces, conflicts)
  }
}

export function routeWithShove(circuit_json, layer, new_trace_points, clearance_mm) {
  const shovedTraces = []
  const conflictsUnresolved = new Set()
  const MAX_DEPTH = 3

  if (!circuit_json) {
    return { circuit_json: null, shoved_traces: [], conflicts_resolved: 0, conflicts_unresolved: 0 }
  }

  const circuit = JSON.parse(JSON.stringify(circuit_json))
  const board = circuit.pcb_board || circuit.board || {}
  const traces = board.pcb_trace || []

  const newTrace = {
    id: `new_${Date.now()}`,
    net_id: 'new',
    layer,
    width_mm: 0.25,
    points: new_trace_points.map(p => (Array.isArray(p) ? { x: p[0], y: p[1] } : p))
  }

  const newSegs = []
  for (let i = 0; i < newTrace.points.length - 1; i++) {
    newSegs.push({ trace: newTrace, points: [newTrace.points[i], newTrace.points[i + 1]] })
  }

  for (const seg of newSegs) {
    const conflicts = new Set()
    _doShove(circuit, layer, seg, clearance_mm, 0, MAX_DEPTH, shovedTraces, conflicts)
  }

  const unresolvedCount = conflictsUnresolved.size

  return {
    circuit_json: circuit,
    shoved_traces: [...new Set(shovedTraces)],
    conflicts_resolved: shovedTraces.length,
    conflicts_unresolved: unresolvedCount
  }
}
