// draft.js — Pure JS Draft workbench: 2D orthogonal CAD .draft file format.
const VALID_KINDS = ['line', 'polyline', 'arc', 'circle', 'spline', 'rect', 'text', 'dimension']

let _counter = 0
function uid() { return 'u' + (++_counter).toString(36) }

export function defaultDraft(name = 'Untitled') {
  return { version: 1, name, scale: 1.0, entities: [] }
}

export function validateDraft(d) {
  const errors = []
  if (!d || typeof d !== 'object') return { ok: false, errors: ['draft must be an object'] }
  if (d.version !== 1) errors.push('version must be 1')
  if (typeof d.name !== 'string') errors.push('name must be a string')
  if (typeof d.scale !== 'number') errors.push('scale must be a number')
  else if (d.scale <= 0) errors.push('scale must be positive')
  if (!Array.isArray(d.entities)) errors.push('entities must be an array')
  else {
    const ids = new Set()
    d.entities.forEach((e, i) => {
      if (!e || typeof e !== 'object') { errors.push(`entities[${i}]: must be an object`); return }
      if (!VALID_KINDS.includes(e.kind)) { errors.push(`entities[${i}]: kind must be one of ${VALID_KINDS.join(',')}`); return }
      if (!e.id) { errors.push(`entities[${i}]: id is required`); return }
      if (ids.has(e.id)) errors.push(`entities[${i}]: duplicate id "${e.id}"`)
      ids.add(e.id)
      const v = _validateEntity(e, i); if (v.length) errors.push(...v)
    })
  }
  return { ok: errors.length === 0, errors }
}

function _validateEntity(e, i) {
  const errs = [], p = `entities[${i}]`
  switch (e.kind) {
    case 'line':
      if (typeof e.x1 !== 'number') errs.push(`${p}: x1 must be a number`)
      if (typeof e.y1 !== 'number') errs.push(`${p}: y1 must be a number`)
      if (typeof e.x2 !== 'number') errs.push(`${p}: x2 must be a number`)
      if (typeof e.y2 !== 'number') errs.push(`${p}: y2 must be a number`)
      break
    case 'polyline':
      if (!Array.isArray(e.points)) errs.push(`${p}: points must be an array`)
      else e.points.forEach((pt, j) => {
        if (!Array.isArray(pt) || pt.length < 2 || typeof pt[0] !== 'number' || typeof pt[1] !== 'number')
          errs.push(`${p}.points[${j}]: [x, y] number pair required`)
      })
      break
    case 'arc':
      ;['cx', 'cy', 'rx', 'ry', 'start_angle', 'end_angle'].forEach(f => { if (typeof e[f] !== 'number') errs.push(`${p}.${f} must be a number`) })
      break
    case 'circle':
      ;['cx', 'cy', 'r'].forEach(f => { if (typeof e[f] !== 'number') errs.push(`${p}.${f} must be a number`) })
      break
    case 'spline':
      if (!Array.isArray(e.points)) errs.push(`${p}: points must be an array`)
      break
    case 'rect':
      ;['x', 'y', 'w', 'h'].forEach(f => { if (typeof e[f] !== 'number') errs.push(`${p}.${f} must be a number`) })
      break
    case 'text':
      if (typeof e.x !== 'number') errs.push(`${p}.x must be a number`)
      if (typeof e.y !== 'number') errs.push(`${p}.y must be a number`)
      if (typeof e.value !== 'string') errs.push(`${p}.value must be a string`)
      break
    case 'dimension':
      ;['x1', 'y1', 'x2', 'y2'].forEach(f => { if (typeof e[f] !== 'number') errs.push(`${p}.${f} must be a number`) })
      break
  }
  return errs
}

export function addEntity(d, entity) {
  if (!d || typeof d !== 'object') throw new Error('draft must be an object')
  const e = { ...entity, id: entity.id || uid() }
  const v = validateDraft({ ...d, entities: [...d.entities, e] })
  if (!v.ok) throw new Error(v.errors.join('; '))
  d.entities.push(e)
  return e
}

export function removeEntity(d, id) {
  const idx = d.entities.findIndex(e => e.id === id)
  if (idx === -1) throw new Error(`entity "${id}" not found`)
  d.entities.splice(idx, 1)
}

export function moveEntity(d, id, dx, dy) {
  const e = d.entities.find(e => e.id === id)
  if (!e) throw new Error(`entity "${id}" not found`)
  switch (e.kind) {
    case 'line': case 'dimension':
      e.x1 += dx; e.y1 += dy; e.x2 += dx; e.y2 += dy; break
    case 'polyline':
      e.points = e.points.map(([x, y]) => [x + dx, y + dy]); break
    case 'arc': case 'circle':
      e.cx += dx; e.cy += dy; break
    case 'rect':
      e.x += dx; e.y += dy; break
    case 'text':
      e.x += dx; e.y += dy; break
    case 'spline':
      e.points = e.points.map(([x, y]) => [x + dx, y + dy]); break
  }
}

function _hypot(x, y) { return Math.hypot(x, y) }
function _norm(x, y) { const l = _hypot(x, y); return l === 0 ? [0, 0] : [x / l, y / l] }
function _dot(x1, y1, x2, y2) { return x1 * x2 + y1 * y2 }

export function offsetEntity(d, id, distance) {
  const e = d.entities.find(e => e.id === id)
  if (!e) throw new Error(`entity "${id}" not found`)
  if (e.kind === 'line') {
    const dx = e.x2 - e.x1, dy = e.y2 - e.y1
    const [nx, ny] = _norm(-dy, dx)
    return { ...e, id: uid(), x1: e.x1 + nx * distance, y1: e.y1 + ny * distance, x2: e.x2 + nx * distance, y2: e.y2 + ny * distance }
  }
  if (e.kind === 'polyline') {
    if (e.points.length < 2) return null
    const pts = e.points.map((pt, i) => {
      const prev = e.points[(i - 1 + e.points.length) % e.points.length]
      const next = e.points[(i + 1) % e.points.length]
      const dx1 = pt[0] - prev[0], dy1 = pt[1] - prev[1]
      const dx2 = next[0] - pt[0], dy2 = next[1] - pt[1]
      let [nx1, ny1] = _norm(-dy1, dx1), [nx2, ny2] = _norm(-dy2, dx2)
      if (_dot(dx1, dy1, nx2, ny2) < 0) { nx2 = -nx2; ny2 = -ny2 }
      const nx = (nx1 + nx2) / 2, ny = (ny1 + ny2) / 2
      const [nnx, nny] = _norm(nx, ny)
      return [pt[0] + nnx * distance, pt[1] + nny * distance]
    })
    return { ...e, id: uid(), points: pts }
  }
  return null
}

function _lineIntersect(x1, y1, x2, y2, x3, y3, x4, y4) {
  const dx1 = x2 - x1, dy1 = y2 - y1, dx2 = x4 - x3, dy2 = y4 - y3
  const denom = dx1 * dy2 - dy1 * dx2
  if (Math.abs(denom) < 1e-12) return null
  const t = ((x3 - x1) * dy2 - (y3 - y1) * dx2) / denom
  return [x1 + t * dx1, y1 + t * dy1]
}

export function trimEntity(d, id, boundary_id) {
  const target = d.entities.find(e => e.id === id)
  const boundary = d.entities.find(e => e.id === boundary_id)
  if (!target || !boundary) throw new Error('entity not found')
  if (target.kind !== 'line' || boundary.kind !== 'line') return target
  const ix = _lineIntersect(target.x1, target.y1, target.x2, target.y2, boundary.x1, boundary.y1, boundary.x2, boundary.y2)
  if (!ix) return target
  const [ixx, ixy] = ix
  const d1 = _hypot(target.x1 - ixx, target.y1 - ixy), d2 = _hypot(target.x2 - ixx, target.y2 - ixy)
  if (d1 < d2) return Object.assign(target, { x1: ixx, y1: ixy })
  return Object.assign(target, { x2: ixx, y2: ixy })
}

export function filletCorner(d, line1_id, line2_id, radius) {
  const l1 = d.entities.find(e => e.id === line1_id)
  const l2 = d.entities.find(e => e.id === line2_id)
  if (!l1 || !l2) throw new Error('lines not found')
  if (l1.kind !== 'line' || l2.kind !== 'line') throw new Error('fillet requires line entities')

  const dx1 = l1.x2 - l1.x1, dy1 = l1.y2 - l1.y1
  const dx2 = l2.x2 - l2.x1, dy2 = l2.y2 - l2.y1
  const [n1x, n1y] = _norm(-dy1, dx1), [n2x, n2y] = _norm(-dy2, dx2)

  const dot = Math.min(Math.abs(_dot(n1x, n1y, n2x, n2y)), 0.9999)
  const angle = Math.acos(dot)
  const offsetDist = radius / Math.tan(angle / 2)

  const p1x = l1.x1 + n1x * offsetDist, p1y = l1.y1 + n1y * offsetDist
  const p2x = l2.x1 + n2x * offsetDist, p2y = l2.y1 + n2y * offsetDist

  const ix = _lineIntersect(p1x, p1y, p1x + dx1, p1y + dy1, p2x, p2y, p2x + dx2, p2y + dy2)
  if (!ix) return null

  const [cx, cy] = ix
  const sp = radius / _hypot(p1x - cx, p1y - cy)
  const sx1 = cx + (p1x - cx) * (1 - sp), sy1 = cy + (p1y - cy) * (1 - sp)
  const sx2 = cx + (p2x - cx) * (1 - sp), sy2 = cy + (p2y - cy) * (1 - sp)

  let a1 = Math.atan2(sy1 - cy, sx1 - cx), a2 = Math.atan2(sy2 - cy, sx2 - cx)
  if (a1 < 0) a1 += Math.PI * 2
  if (a2 < 0) a2 += Math.PI * 2

  l1.x2 = sx1; l1.y2 = sy1
  l2.x1 = sx2; l2.y1 = sy2
  const arc = { id: uid(), kind: 'arc', cx, cy, rx: radius, ry: radius, start_angle: a1 * 180 / Math.PI, end_angle: a2 * 180 / Math.PI, clockwise: false }
  d.entities.push(arc)
  return arc
}

export function patternLinear(d, id, count, dx, dy) {
  const src = d.entities.find(e => e.id === id)
  if (!src) throw new Error(`entity "${id}" not found`)
  if (count < 2) return []
  const copies = []
  for (let i = 1; i < count; i++) {
    const c = JSON.parse(JSON.stringify(src))
    c.id = uid()
    const _doc = { entities: [c] }
    moveEntity(_doc, c.id, dx * i, dy * i)
    d.entities.push(c)
    copies.push(c)
  }
  return copies
}

export function patternPolar(d, id, count, center, total_angle_deg) {
  const src = d.entities.find(e => e.id === id)
  if (!src) throw new Error(`entity "${id}" not found`)
  if (count < 2) return []
  const [cx, cy] = Array.isArray(center) ? center : [0, 0]
  const angleStep = total_angle_deg / count * Math.PI / 180
  const copies = []
  for (let i = 1; i < count; i++) {
    const c = JSON.parse(JSON.stringify(src))
    c.id = uid()
    const a = angleStep * i, cos = Math.cos(a), sin = Math.sin(a)
    switch (c.kind) {
      case 'line': case 'dimension': {
        const mx1 = cx + (c.x1 - cx) * cos - (c.y1 - cy) * sin, my1 = cy + (c.x1 - cx) * sin + (c.y1 - cy) * cos
        const mx2 = cx + (c.x2 - cx) * cos - (c.y2 - cy) * sin, my2 = cy + (c.x2 - cx) * sin + (c.y2 - cy) * cos
        c.x1 = mx1; c.y1 = my1; c.x2 = mx2; c.y2 = my2; break
      }
      case 'circle': case 'arc': {
        const ncx = cx + (c.cx - cx) * cos - (c.cy - cy) * sin
        const ncy = cy + (c.cx - cx) * sin + (c.cy - cy) * cos
        c.cx = ncx; c.cy = ncy; break
      }
      case 'rect': {
        const nrx = cx + (c.x - cx) * cos - (c.y - cy) * sin
        const nry = cy + (c.x - cx) * sin + (c.y - cy) * cos
        c.x = nrx; c.y = nry; c.rotation = (c.rotation || 0) + angleStep * i; break
      }
      case 'text': {
        const ntx = cx + (c.x - cx) * cos - (c.y - cy) * sin
        const nty = cy + (c.x - cx) * sin + (c.y - cy) * cos
        c.x = ntx; c.y = nty; c.rotation = (c.rotation || 0) + angleStep * i; break
      }
      case 'polyline': case 'spline':
        c.points = c.points.map(([px, py]) => [cx + (px - cx) * cos - (py - cy) * sin, cy + (px - cx) * sin + (py - cy) * cos]); break
    }
    d.entities.push(c)
    copies.push(c)
  }
  return copies
}

function _dxf(str) { return str.toString().slice(0, 250) }

export function exportDXF(d) {
  const lines = []
  const ln = (...args) => { lines.push(args.join('\n')) }

  ln(0, 'SECTION', 2, 'HEADER')
  ln(9, '$ACADVER', 1, 'AC1009')
  ln(0, 'ENDSEC')

  ln(0, 'SECTION', 2, 'ENTITIES')
  for (const e of d.entities) {
    switch (e.kind) {
      case 'line':
        ln(0, 'LINE', 8, '0', 10, e.x1, 20, e.y1, 30, 0, 11, e.x2, 21, e.y2, 31, 0)
        break
      case 'circle':
        ln(0, 'CIRCLE', 8, '0', 10, e.cx, 20, e.cy, 30, 0, 40, e.r)
        break
      case 'arc':
        ln(0, 'ARC', 8, '0', 10, e.cx, 20, e.cy, 30, 0, 40, e.rx, 50, e.start_angle, 51, e.end_angle)
        break
      case 'polyline': {
        const pts = e.points
        ln(0, 'POLYLINE', 8, '0', 66, 1, 70, e.closed ? 1 : 0)
        for (const [px, py] of pts) ln(0, 'VERTEX', 8, '0', 10, px, 20, py, 30, 0)
        ln(0, 'SEQEND', 8, '0')
        break
      }
      case 'text':
        ln(0, 'TEXT', 8, '0', 10, e.x, 20, e.y, 30, 0, 40, e.size || 12, 1, _dxf(e.value))
        break
    }
  }
  ln(0, 'ENDSEC')
  ln(0, 'EOF')
  return lines.join('\n')
}
