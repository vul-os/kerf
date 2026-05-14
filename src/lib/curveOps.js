// curveOps.js — Pure JS curve operations (Rhino-parity depth).
//
// A curve is one of:
//   {kind:'line',    x1,y1,z1,  x2,y2,z2}
//   {kind:'polyline',points:[{x,y,z},...]}
//   {kind:'arc',     cx,cy,cz, radius, startAngle, endAngle, normal:{x,y,z}}
//     (normal defaults to {x:0,y:0,z:1}; angles in radians; arc sweeps CCW when
//      viewed from the normal direction)
//   {kind:'circle',  cx,cy,cz, radius, normal:{x,y,z}}
//   {kind:'bspline', degree, controlPoints:[{x,y,z},...], knots:[...], weights:[...] optional}
//
// All functions are pure (no side effects) and safe for Web Workers and vitest.

// ─── internal helpers ──────────────────────────────────────────────────────────

function vec3(x, y, z) { return { x, y, z } }
function vadd(a, b) { return vec3(a.x + b.x, a.y + b.y, a.z + b.z) }
function vsub(a, b) { return vec3(a.x - b.x, a.y - b.y, a.z - b.z) }
function vscale(v, s) { return vec3(v.x * s, v.y * s, v.z * s) }
function vdot(a, b) { return a.x * b.x + a.y * b.y + a.z * b.z }
function vcross(a, b) {
  return vec3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)
}
function vlen(v) { return Math.sqrt(vdot(v, v)) }
function vnorm(v) {
  const l = vlen(v)
  return l < 1e-15 ? vec3(0, 0, 0) : vscale(v, 1 / l)
}
function vlerp(a, b, t) { return vadd(vscale(a, 1 - t), vscale(b, t)) }

// Uniform clamped B-spline knot vector for degree d, n+1 control points.
function _uniformKnots(n, d) {
  const m = n + d + 1
  const knots = []
  for (let i = 0; i <= m; i++) {
    if (i <= d) knots.push(0)
    else if (i >= m - d) knots.push(1)
    else knots.push((i - d) / (n - d + 1))
  }
  return knots
}

// De Boor evaluation: returns point on B-spline at parameter u in [0,1].
function _deBoor(degree, controlPoints, knots, u) {
  const n = controlPoints.length - 1
  // Map u to knot domain [knots[degree], knots[n+1]].
  const uMin = knots[degree]
  const uMax = knots[n + 1]
  const uu = uMin + u * (uMax - uMin)

  // Find knot span.
  let k = degree
  for (let i = degree; i <= n; i++) {
    if (uu >= knots[i] && uu < knots[i + 1]) { k = i; break }
    if (uu >= knots[n + 1]) { k = n; break }
  }

  // Copy relevant control points.
  const d = controlPoints.slice(k - degree, k + 1).map(p => ({ ...p }))

  for (let r = 1; r <= degree; r++) {
    for (let j = degree; j >= r; j--) {
      const denom = knots[k - degree + j + r] - knots[k - degree + j]
      const alpha = denom < 1e-15 ? 0 : (uu - knots[k - degree + j]) / denom
      d[j] = vlerp(d[j - 1], d[j], alpha)
    }
  }
  return d[degree]
}

// Derivative of B-spline (returns tangent direction, not necessarily unit).
function _deBoorDeriv(degree, controlPoints, knots, u) {
  if (degree === 0) return vec3(0, 0, 0)
  const n = controlPoints.length - 1
  const dpts = []
  for (let i = 0; i < n; i++) {
    const denom = knots[i + degree + 1] - knots[i + 1]
    const s = denom < 1e-15 ? 0 : degree / denom
    dpts.push(vscale(vsub(controlPoints[i + 1], controlPoints[i]), s))
  }
  if (dpts.length === 0) return vec3(0, 0, 0)
  const kd = knots.slice(1, knots.length - 1)
  return _deBoor(degree - 1, dpts, kd, u)
}

// Arc normal (default Z).
function _arcNormal(curve) {
  return curve.normal ? vnorm(curve.normal) : vec3(0, 0, 1)
}

// Arc sweep in radians (always positive, CCW).
function _arcSweep(curve) {
  let sweep = curve.endAngle - curve.startAngle
  while (sweep <= 0) sweep += Math.PI * 2
  while (sweep > Math.PI * 2) sweep -= Math.PI * 2
  return sweep === 0 ? Math.PI * 2 : sweep
}

// Build two orthonormal axes in the plane of an arc/circle given its normal.
// Convention: for n=Z we want u=X, v=Y; for n=X we want u=Y, v=Z, etc.
// We pick ref as the world axis with the smallest |dot(n, axis)| (least parallel),
// then u = normalize(ref × n), v = n × u.
function _planeAxes(normal) {
  const n = vnorm(normal)
  // Pick ref = Z when n is not parallel to Z, else Y.
  const ref = Math.abs(n.z) < 0.9 ? vec3(0, 0, 1) : vec3(0, 1, 0)
  const u = vnorm(vcross(ref, n))
  const v = vcross(n, u)
  return { u, v }
}

// Evaluate a point on an arc at angle theta (absolute, in radians).
function _arcPoint(curve, theta) {
  const n = _arcNormal(curve)
  const { u, v } = _planeAxes(n)
  const center = vec3(curve.cx, curve.cy, curve.cz)
  const r = curve.radius
  return vadd(center, vadd(vscale(u, r * Math.cos(theta)), vscale(v, r * Math.sin(theta))))
}

// ─── curveLength ──────────────────────────────────────────────────────────────

/**
 * Total arc length of a curve.
 */
export function curveLength(curve) {
  switch (curve.kind) {
    case 'line': {
      const d = vsub(vec3(curve.x2, curve.y2, curve.z2), vec3(curve.x1, curve.y1, curve.z1))
      return vlen(d)
    }
    case 'polyline': {
      const pts = curve.points
      let len = 0
      for (let i = 1; i < pts.length; i++) len += vlen(vsub(pts[i], pts[i - 1]))
      return len
    }
    case 'arc': {
      return curve.radius * _arcSweep(curve)
    }
    case 'circle': {
      return 2 * Math.PI * curve.radius
    }
    case 'bspline': {
      // Numerical integration via 64-point discretisation.
      const N = 64
      let len = 0
      let prev = pointAt(curve, 0)
      for (let i = 1; i <= N; i++) {
        const curr = pointAt(curve, i / N)
        len += vlen(vsub(curr, prev))
        prev = curr
      }
      return len
    }
    default:
      throw new Error(`curveLength: unknown kind '${curve.kind}'`)
  }
}

// ─── pointAt ─────────────────────────────────────────────────────────────────

/**
 * Point on curve at parameter t ∈ [0,1].
 */
export function pointAt(curve, t) {
  const tt = Math.max(0, Math.min(1, t))
  switch (curve.kind) {
    case 'line': {
      const a = vec3(curve.x1, curve.y1, curve.z1)
      const b = vec3(curve.x2, curve.y2, curve.z2)
      return vlerp(a, b, tt)
    }
    case 'polyline': {
      const pts = curve.points
      if (pts.length === 1) return { ...pts[0] }
      const totalSegs = pts.length - 1
      const scaled = tt * totalSegs
      const seg = Math.min(Math.floor(scaled), totalSegs - 1)
      const local = scaled - seg
      return vlerp(pts[seg], pts[seg + 1], local)
    }
    case 'arc': {
      const sweep = _arcSweep(curve)
      const theta = curve.startAngle + sweep * tt
      return _arcPoint(curve, theta)
    }
    case 'circle': {
      const theta = tt * 2 * Math.PI
      return _arcPoint({ ...curve, startAngle: 0 }, theta)
    }
    case 'bspline': {
      const { degree, controlPoints } = curve
      const knots = curve.knots || _uniformKnots(controlPoints.length - 1, degree)
      return _deBoor(degree, controlPoints, knots, tt)
    }
    default:
      throw new Error(`pointAt: unknown kind '${curve.kind}'`)
  }
}

// ─── tangentAt ───────────────────────────────────────────────────────────────

/**
 * Unit tangent vector at parameter t ∈ [0,1].
 */
export function tangentAt(curve, t) {
  const tt = Math.max(0, Math.min(1, t))
  switch (curve.kind) {
    case 'line': {
      const d = vsub(vec3(curve.x2, curve.y2, curve.z2), vec3(curve.x1, curve.y1, curve.z1))
      return vnorm(d)
    }
    case 'polyline': {
      const pts = curve.points
      if (pts.length < 2) return vec3(0, 0, 0)
      const totalSegs = pts.length - 1
      const scaled = tt * totalSegs
      const seg = Math.min(Math.floor(scaled), totalSegs - 1)
      return vnorm(vsub(pts[seg + 1], pts[seg]))
    }
    case 'arc': {
      const sweep = _arcSweep(curve)
      const theta = curve.startAngle + sweep * tt
      const n = _arcNormal(curve)
      const { u, v } = _planeAxes(n)
      // Tangent is derivative of position w.r.t. theta, normalised.
      const rawTan = vadd(vscale(u, -Math.sin(theta)), vscale(v, Math.cos(theta)))
      // Positive sweep means CCW, so tangent is already in correct direction.
      return vnorm(rawTan)
    }
    case 'circle': {
      const theta = tt * 2 * Math.PI
      const n = _arcNormal({ normal: curve.normal })
      const { u, v } = _planeAxes(n)
      return vnorm(vadd(vscale(u, -Math.sin(theta)), vscale(v, Math.cos(theta))))
    }
    case 'bspline': {
      const { degree, controlPoints } = curve
      const knots = curve.knots || _uniformKnots(controlPoints.length - 1, degree)
      const d = _deBoorDeriv(degree, controlPoints, knots, tt)
      return vnorm(d)
    }
    default:
      throw new Error(`tangentAt: unknown kind '${curve.kind}'`)
  }
}

// ─── discretize ──────────────────────────────────────────────────────────────

/**
 * Return array of n+1 evenly-spaced (by parameter) points along curve.
 */
export function discretize(curve, n) {
  const pts = []
  for (let i = 0; i <= n; i++) {
    pts.push(pointAt(curve, i / n))
  }
  return pts
}

// ─── projectCurveToSurface ───────────────────────────────────────────────────

/**
 * Project a 3D curve onto a plane, returning a 2D sketch entity (polyline).
 *
 * surface_plane is one of:
 *   'XY' | 'XZ' | 'YZ'  (named standard planes)
 *   {origin:{x,y,z}, normal:{x,y,z}}  (arbitrary plane)
 *
 * Returns {kind:'polyline', points:[{x,y,z:0},...]} in the plane's local 2D
 * coordinate system (z=0), with x/y being the in-plane coordinates.
 */
export function projectCurveToSurface(curve, surface_plane) {
  const N = 64
  const pts3d = discretize(curve, N)

  let origin, normal, uAxis, vAxis

  if (surface_plane === 'XY') {
    origin = vec3(0, 0, 0); normal = vec3(0, 0, 1)
    uAxis = vec3(1, 0, 0); vAxis = vec3(0, 1, 0)
  } else if (surface_plane === 'XZ') {
    origin = vec3(0, 0, 0); normal = vec3(0, 1, 0)
    uAxis = vec3(1, 0, 0); vAxis = vec3(0, 0, 1)
  } else if (surface_plane === 'YZ') {
    origin = vec3(0, 0, 0); normal = vec3(1, 0, 0)
    uAxis = vec3(0, 1, 0); vAxis = vec3(0, 0, 1)
  } else {
    // Arbitrary plane.
    origin = vec3(
      surface_plane.origin.x,
      surface_plane.origin.y,
      surface_plane.origin.z,
    )
    normal = vnorm(vec3(
      surface_plane.normal.x,
      surface_plane.normal.y,
      surface_plane.normal.z,
    ))
    // Build orthonormal frame using the same convention as _planeAxes.
    const ref = Math.abs(normal.z) < 0.9 ? vec3(0, 0, 1) : vec3(0, 1, 0)
    uAxis = vnorm(vcross(ref, normal))
    vAxis = vcross(normal, uAxis)
  }

  // Orthographic projection: drop the normal component.
  const projected = pts3d.map(p => {
    const rel = vsub(p, origin)
    // Remove normal component.
    const d = vdot(rel, normal)
    const inPlane = vsub(rel, vscale(normal, d))
    const u2 = vdot(inPlane, uAxis)
    const v2 = vdot(inPlane, vAxis)
    return { x: u2, y: v2, z: 0 }
  })

  return { kind: 'polyline', points: projected }
}

// ─── intersectCurves ─────────────────────────────────────────────────────────

/**
 * Find intersections between two curves using discretize-then-segment approach.
 * Returns [{point:{x,y,z}, tA, tB}, ...].
 */
export function intersectCurves(curveA, curveB, tolerance = 0.01) {
  const N = 128
  const ptsA = discretize(curveA, N)
  const ptsB = discretize(curveB, N)

  const results = []
  const tol2 = tolerance * tolerance

  for (let i = 0; i < N; i++) {
    const a0 = ptsA[i], a1 = ptsA[i + 1]
    for (let j = 0; j < N; j++) {
      const b0 = ptsB[j], b1 = ptsB[j + 1]

      // 3D segment-segment closest point.
      const r = vsub(a0, b0)
      const u = vsub(a1, a0)
      const v = vsub(b1, b0)
      const a = vdot(u, u)
      const e = vdot(v, v)
      if (a < 1e-15 || e < 1e-15) continue
      const f = vdot(v, r)
      const b = vdot(u, v)
      const denom = a * e - b * b
      let s, tt
      if (Math.abs(denom) < 1e-15) {
        s = 0; tt = f / e
      } else {
        const c = vdot(u, r)
        s = (b * f - c * e) / denom
        tt = (a * f - b * c) / denom  // renamed from t to tt to avoid shadowing
      }
      s = Math.max(0, Math.min(1, s))
      tt = Math.max(0, Math.min(1, tt))

      const pA = vadd(a0, vscale(u, s))
      const pB = vadd(b0, vscale(v, tt))
      const dist2 = vdot(vsub(pA, pB), vsub(pA, pB))

      if (dist2 <= tol2) {
        const tA = (i + s) / N
        const tB = (j + tt) / N
        // Deduplicate: skip if we already have a nearby result.
        const mid = vlerp(pA, pB, 0.5)
        const dup = results.some(r2 => vdot(vsub(r2.point, mid), vsub(r2.point, mid)) <= tol2)
        if (!dup) results.push({ point: mid, tA, tB })
      }
    }
  }
  return results
}

// ─── curveBoolean ────────────────────────────────────────────────────────────

/**
 * Boolean operation on two closed curves (closed polylines or circles).
 * op: 'union' | 'difference' | 'intersection'
 * Returns {kind:'polyline', points:[...]} representing the result boundary.
 *
 * Implementation: discretize both, find crossings, split at crossings,
 * tag segments by inside/outside membership, reassemble.
 */
export function curveBoolean(curveA, curveB, op) {
  const N = 256

  // Discretize both to closed polygon arrays.
  function toPoly(c) {
    if (c.kind === 'circle') {
      const pts = []
      for (let i = 0; i < N; i++) {
        const theta = (i / N) * 2 * Math.PI
        pts.push(_arcPoint({ ...c, startAngle: 0 }, theta))
      }
      return pts
    }
    if (c.kind === 'polyline') return c.points
    // For anything else discretize.
    const pts = discretize(c, N)
    pts.pop() // remove duplicate endpoint for a closed polygon
    return pts
  }

  const polyA = toPoly(curveA)
  const polyB = toPoly(curveB)

  // Point-in-polygon (2D, using x/y).
  function pip(poly, pt) {
    let inside = false
    const n = poly.length
    for (let i = 0, j = n - 1; i < n; j = i++) {
      const xi = poly[i].x, yi = poly[i].y
      const xj = poly[j].x, yj = poly[j].y
      if (((yi > pt.y) !== (yj > pt.y)) &&
          pt.x < ((xj - xi) * (pt.y - yi)) / (yj - yi) + xi) {
        inside = !inside
      }
    }
    return inside
  }

  // Midpoint of segment between consecutive polygon points.
  function midpt(pts, i) {
    const a = pts[i], b = pts[(i + 1) % pts.length]
    return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 }
  }

  const result = []

  // Collect segments from A.
  for (let i = 0; i < polyA.length; i++) {
    const mid = midpt(polyA, i)
    const inB = pip(polyB, mid)
    let include = false
    if (op === 'union')        include = !inB
    if (op === 'difference')   include = !inB
    if (op === 'intersection') include = inB
    if (include) {
      result.push(polyA[i])
    }
  }

  // Collect segments from B.
  for (let i = 0; i < polyB.length; i++) {
    const mid = midpt(polyB, i)
    const inA = pip(polyA, mid)
    let include = false
    if (op === 'union')        include = !inA
    if (op === 'difference')   include = inA  // subtract B from A → keep B parts inside A? No — keep none of B for difference
    if (op === 'intersection') include = inA
    // For 'difference' we do NOT include any B points.
    if (op === 'difference') include = false
    if (include) {
      result.push(polyB[i])
    }
  }

  if (result.length === 0) return { kind: 'polyline', points: [] }
  // Close the polygon.
  const closed = [...result, result[0]]
  return { kind: 'polyline', points: closed }
}

// ─── blendCurve ──────────────────────────────────────────────────────────────

/**
 * Create a G0/G1/G2-continuous B-spline bridging the end of curveA (at t_end_A)
 * to the end of curveB (at t_end_B).
 *
 * Returns {kind:'bspline', degree, controlPoints, knots}.
 */
export function blendCurve(curveA, t_end_A, curveB, t_end_B, continuity = 'G1') {
  const pA = pointAt(curveA, t_end_A)
  const pB = pointAt(curveB, t_end_B)
  const tA = tangentAt(curveA, t_end_A)
  const tB = tangentAt(curveB, t_end_B)

  const dist = vlen(vsub(pB, pA))
  const scale = dist / 3

  if (continuity === 'G0') {
    // Degree-1 B-spline (straight line).
    const cp = [pA, pB]
    return {
      kind: 'bspline',
      degree: 1,
      controlPoints: cp,
      knots: [0, 0, 1, 1],
    }
  }

  if (continuity === 'G1') {
    // Cubic with tangent at both ends.
    const h1 = vadd(pA, vscale(tA, scale))
    const h2 = vsub(pB, vscale(tB, scale))
    const cp = [pA, h1, h2, pB]
    return {
      kind: 'bspline',
      degree: 3,
      controlPoints: cp,
      knots: [0, 0, 0, 0, 1, 1, 1, 1],
    }
  }

  // G2: degree-5 with tangent and curvature continuity.
  // Approximate curvature vector by finite difference of tangent.
  const EPS = 1e-4
  const tA2 = tangentAt(curveA, Math.max(0, t_end_A - EPS))
  const tB2 = tangentAt(curveB, Math.min(1, t_end_B + EPS))
  const kA = vscale(vsub(tA, tA2), 1 / EPS)  // curvature-like
  const kB = vscale(vsub(tB2, tB), 1 / EPS)

  const h1 = vadd(pA, vscale(tA, scale))
  const h2 = vadd(h1, vscale(vadd(tA, vscale(kA, scale * 0.5)), scale * 0.5))
  const h5 = vsub(pB, vscale(tB, scale))
  const h4 = vsub(h5, vscale(vadd(tB, vscale(kB, scale * 0.5)), scale * 0.5))
  const h3 = vlerp(h2, h4, 0.5)

  const cp = [pA, h1, h2, h3, h4, h5, pB]
  const knots = _uniformKnots(cp.length - 1, 5)
  return {
    kind: 'bspline',
    degree: 5,
    controlPoints: cp,
    knots,
  }
}

// ─── matchCurve ──────────────────────────────────────────────────────────────

/**
 * Adjust curveB so that its start (t=0) matches curveA's end (t=1) with the
 * requested continuity.  Returns a modified copy of curveB.
 *
 * Only bspline targets are modified in a geometrically meaningful way.
 * Other kinds are returned with their endpoints moved (G0 only regardless).
 */
export function matchCurve(curveA, curveB, continuity = 'G1') {
  const pA = pointAt(curveA, 1)
  const tA = tangentAt(curveA, 1)

  if (curveB.kind === 'bspline') {
    const cp = curveB.controlPoints.map(p => ({ ...p }))
    // G0: move first control point.
    cp[0] = { ...pA }
    if (continuity !== 'G0' && cp.length >= 2) {
      // G1: align second control point along tA.
      const dist = vlen(vsub(cp[1], cp[0]))
      cp[1] = vadd(pA, vscale(tA, dist || 1))
    }
    if (continuity === 'G2' && cp.length >= 3) {
      // G2: adjust third control point for curvature.
      const EPS = 1e-4
      const tA2 = tangentAt(curveA, Math.max(0, 1 - EPS))
      const kA = vscale(vsub(tA, tA2), 1 / EPS)
      const d1 = vlen(vsub(cp[1], cp[0]))
      cp[2] = vadd(cp[1], vadd(vscale(tA, d1), vscale(kA, d1 * d1 * 0.5)))
    }
    return { ...curveB, controlPoints: cp }
  }

  if (curveB.kind === 'line') {
    const end = pointAt(curveB, 1)
    return { ...curveB, x1: pA.x, y1: pA.y, z1: pA.z, x2: end.x, y2: end.y, z2: end.z }
  }

  if (curveB.kind === 'polyline') {
    const pts = curveB.points.map(p => ({ ...p }))
    pts[0] = { ...pA }
    return { ...curveB, points: pts }
  }

  // arc/circle: just update start point conceptually (return unchanged).
  return curveB
}

// ─── offsetCurve3D ───────────────────────────────────────────────────────────

/**
 * 3D offset: move each point of the curve by `distance` along axis_or_normal.
 * axis_or_normal can be {x,y,z} (a fixed direction) or 'X'|'Y'|'Z'.
 * Returns a polyline.
 */
export function offsetCurve3D(curve, distance, axis_or_normal) {
  const N = 64
  const pts = discretize(curve, N)

  let dir
  if (axis_or_normal === 'X') dir = vec3(1, 0, 0)
  else if (axis_or_normal === 'Y') dir = vec3(0, 1, 0)
  else if (axis_or_normal === 'Z') dir = vec3(0, 0, 1)
  else dir = vnorm(vec3(axis_or_normal.x, axis_or_normal.y, axis_or_normal.z))

  const offset = vscale(dir, distance)
  return {
    kind: 'polyline',
    points: pts.map(p => vadd(p, offset)),
  }
}

// ─── polylineToNurbs ─────────────────────────────────────────────────────────

/**
 * Fit a B-spline of given degree through the control polygon defined by
 * polyline.points.  Uses chord-length parameterisation and the Schoenberg-
 * Whitney conditions for an interpolating knot vector.
 *
 * Returns {kind:'bspline', degree, controlPoints, knots}.
 */
export function polylineToNurbs(polyline, degree = 3) {
  const pts = polyline.points
  if (!pts || pts.length < 2) throw new Error('polylineToNurbs: need ≥2 points')
  const d = Math.min(degree, pts.length - 1)

  // For simplicity use global approximation: treat pts as control polygon,
  // add a clamped uniform knot vector so the curve passes through endpoints.
  const n = pts.length - 1
  const knots = _uniformKnots(n, d)

  return {
    kind: 'bspline',
    degree: d,
    controlPoints: pts.map(p => ({ x: p.x || 0, y: p.y || 0, z: p.z || 0 })),
    knots,
  }
}

// ─── simplifyCurve ───────────────────────────────────────────────────────────

/**
 * Reduce curve complexity:
 * - polyline: Douglas-Peucker point reduction.
 * - bspline: knot removal (removes interior knots where deviation < tolerance).
 * - other kinds: returned unchanged.
 */
export function simplifyCurve(curve, tolerance) {
  if (curve.kind === 'polyline') {
    return { ...curve, points: _douglasPeucker(curve.points, tolerance) }
  }

  if (curve.kind === 'bspline') {
    return _bsplineSimplify(curve, tolerance)
  }

  return curve
}

// Douglas-Peucker line simplification.
function _douglasPeucker(pts, tol) {
  if (pts.length <= 2) return pts

  // Find the point farthest from the line segment pts[0]..pts[last].
  const first = pts[0], last = pts[pts.length - 1]
  const line = vsub(last, first)
  const lineLen = vlen(line)

  let maxDist = -1, maxIdx = 0
  for (let i = 1; i < pts.length - 1; i++) {
    let dist
    if (lineLen < 1e-15) {
      dist = vlen(vsub(pts[i], first))
    } else {
      const t = Math.max(0, Math.min(1, vdot(vsub(pts[i], first), line) / (lineLen * lineLen)))
      const proj = vadd(first, vscale(line, t))
      dist = vlen(vsub(pts[i], proj))
    }
    if (dist > maxDist) { maxDist = dist; maxIdx = i }
  }

  if (maxDist <= tol) return [first, last]

  const left = _douglasPeucker(pts.slice(0, maxIdx + 1), tol)
  const right = _douglasPeucker(pts.slice(maxIdx), tol)
  // Merge (left ends with pts[maxIdx], right starts with pts[maxIdx]).
  return [...left.slice(0, -1), ...right]
}

// Greedy knot removal for B-splines.
function _bsplineSimplify(curve, tolerance) {
  let { degree, controlPoints, knots } = curve
  knots = knots || _uniformKnots(controlPoints.length - 1, degree)

  // Sample the original curve.
  const N = 128
  const original = []
  for (let i = 0; i <= N; i++) original.push(pointAt(curve, i / N))

  // Try removing interior knots one at a time if error stays below tolerance.
  let changed = true
  while (changed) {
    changed = false
    // Interior knots are at indices [degree+1 .. knots.length-degree-2].
    const intStart = degree + 1
    const intEnd = knots.length - degree - 2

    for (let ki = intStart; ki <= intEnd; ki++) {
      if (ki >= knots.length - degree - 1) break
      const newKnots = [...knots.slice(0, ki), ...knots.slice(ki + 1)]
      // Reduce control point count proportionally (simple: drop midpoint).
      if (newKnots.length < 2 * (degree + 1)) break
      const midIdx = Math.round((ki - degree - 1) * (controlPoints.length / (knots.length - 2 * (degree + 1) + 1)))
      const trimIdx = Math.max(1, Math.min(controlPoints.length - 2, midIdx))
      const newCP = [...controlPoints.slice(0, trimIdx), ...controlPoints.slice(trimIdx + 1)]
      if (newCP.length < degree + 1) break

      const candidate = { kind: 'bspline', degree, controlPoints: newCP, knots: newKnots }
      // Check max deviation.
      let maxDev = 0
      for (let i = 0; i <= N; i++) {
        const cPt = pointAt(candidate, i / N)
        maxDev = Math.max(maxDev, vlen(vsub(cPt, original[i])))
      }
      if (maxDev <= tolerance) {
        controlPoints = newCP
        knots = newKnots
        changed = true
        break
      }
    }
  }

  return { ...curve, controlPoints, knots }
}
