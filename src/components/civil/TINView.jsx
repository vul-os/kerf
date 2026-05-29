/**
 * TINView.jsx — 3-D triangulated irregular network (TIN) viewer.
 *
 * Renders a TIN surface in an SVG pseudo-3D isometric projection.  No external
 * 3D lib is required: faces are projected to screen coordinates using a simple
 * isometric transform, then painter-sorted (back-to-front) and drawn as filled
 * polygons with a contour-line overlay.
 *
 * Props
 * ─────
 *   points   {Array<[x,y,z]>}    Survey/terrain point cloud (metres).
 *   edges    {Array<[i,j]>}      Edge indices into points (optional — derived
 *                                from triangles when absent).
 *   triangles {Array<[i,j,k]>}  Triangle face indices (optional — if absent a
 *                                simple radial fan from centroid is used for demo).
 *   contourInterval {number}    Contour line interval in z units (default 1).
 *   width    {number}           SVG canvas width  (default 600).
 *   height   {number}           SVG canvas height (default 420).
 *   wireframe {boolean}         Show wireframe overlay (default true).
 *   showContours {boolean}      Show contour lines (default true).
 *   className {string}          Extra CSS classes on the root element.
 *   onDispatch {function}       Called with { tool, params } when user clicks
 *                                "Run terrain analysis" (optional).
 *
 * The dispatch button calls `civil_tin_terrain` via POST /api/tools/call.
 */

import { useMemo, useState } from 'react'

// ---------------------------------------------------------------------------
// Projection helpers
// ---------------------------------------------------------------------------

/**
 * Isometric projection:
 *   screen_x = (x - y) * cos(30°) * scale
 *   screen_y = (x + y) * sin(30°) * scale - z * zScale
 */
function project(x, y, z, scale, zScale) {
  const cos30 = Math.sqrt(3) / 2
  const sin30 = 0.5
  return {
    sx: (x - y) * cos30 * scale,
    sy: (x + y) * sin30 * scale - z * zScale,
  }
}

function fitToViewport(points, width, height, padding) {
  if (!points || points.length === 0) return { scale: 1, zScale: 1, cx: 0, cy: 0 }
  const cos30 = Math.sqrt(3) / 2
  const sin30 = 0.5

  // Compute bounding box of projected points (z=0) to find scale
  let minSX = Infinity, maxSX = -Infinity, minSY = Infinity, maxSY = -Infinity
  for (const [x, y] of points) {
    const sx = (x - y) * cos30
    const sy = (x + y) * sin30
    if (sx < minSX) minSX = sx
    if (sx > maxSX) maxSX = sx
    if (sy < minSY) minSY = sy
    if (sy > maxSY) maxSY = sy
  }

  const rangeX = maxSX - minSX || 1
  const rangeY = maxSY - minSY || 1
  const usableW = width - padding * 2
  const usableH = height - padding * 2 * 0.6
  const scale = Math.min(usableW / rangeX, usableH / rangeY)

  return { scale, cx: (minSX + maxSX) / 2, cy: (minSY + maxSY) / 2 }
}

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

function elevToRgb(z, zMin, zMax) {
  const t = zMax === zMin ? 0.5 : Math.max(0, Math.min(1, (z - zMin) / (zMax - zMin)))
  // Low: dark teal → mid: olive green → high: sand/brown
  const r = Math.round(t < 0.5 ? 40 + t * 2 * 120 : 160 + (t - 0.5) * 2 * 60)
  const g = Math.round(t < 0.5 ? 80 + t * 2 * 80 : 160 - (t - 0.5) * 2 * 60)
  const b = Math.round(t < 0.5 ? 80 - t * 2 * 60 : 20)
  return `rgb(${r},${g},${b})`
}

function shadedFaceColour(pts3, zMin, zMax) {
  // Average z for base colour, then apply simple Lambert shading
  const avgZ = pts3.reduce((s, p) => s + p[2], 0) / pts3.length

  // Face normal (simplified — use cross product of two edges)
  const [p0, p1, p2] = pts3
  const u = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]]
  const v = [p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]]
  const nx = u[1] * v[2] - u[2] * v[1]
  const ny = u[2] * v[0] - u[0] * v[2]
  const nz = u[0] * v[1] - u[1] * v[0]
  const nLen = Math.sqrt(nx * nx + ny * ny + nz * nz) || 1

  // Sun direction (normalised)
  const lx = 0.577, ly = 0.577, lz = 0.577
  const lambert = Math.max(0.2, (nx / nLen) * lx + (ny / nLen) * ly + (nz / nLen) * lz)

  const base = elevToRgb(avgZ, zMin, zMax)
  const m = base.match(/\d+/g).map(Number)
  const r = Math.min(255, Math.round(m[0] * lambert))
  const g = Math.min(255, Math.round(m[1] * lambert))
  const b = Math.min(255, Math.round(m[2] * lambert))
  return `rgb(${r},${g},${b})`
}

// ---------------------------------------------------------------------------
// Contour extraction
// ---------------------------------------------------------------------------

function extractContourSegments(points, triangles, zLevel) {
  const segments = []
  for (const [i, j, k] of triangles) {
    const pts = [points[i], points[j], points[k]]
    const crossed = []
    const edges = [[0, 1], [1, 2], [2, 0]]
    for (const [a, b] of edges) {
      const za = pts[a][2], zb = pts[b][2]
      if ((za <= zLevel && zb > zLevel) || (za > zLevel && zb <= zLevel)) {
        const t = (zLevel - za) / (zb - za)
        crossed.push([
          pts[a][0] + t * (pts[b][0] - pts[a][0]),
          pts[a][1] + t * (pts[b][1] - pts[a][1]),
          zLevel,
        ])
      }
    }
    if (crossed.length === 2) segments.push(crossed)
  }
  return segments
}

// ---------------------------------------------------------------------------
// Simple Delaunay-like triangulation (ear-clipping convex hull fallback)
// Build a triangulation from a point cloud when none is supplied.
// For small point sets this is adequate for visualization.
// ---------------------------------------------------------------------------

function buildFanTriangles(points) {
  if (points.length < 3) return []
  // Use centroid as anchor and fan-triangulate the sorted perimeter
  const cx = points.reduce((s, p) => s + p[0], 0) / points.length
  const cy = points.reduce((s, p) => s + p[1], 0) / points.length
  const cz = points.reduce((s, p) => s + p[2], 0) / points.length

  const sorted = points
    .map((p, i) => ({ i, angle: Math.atan2(p[1] - cy, p[0] - cx) }))
    .sort((a, b) => a.angle - b.angle)

  const triangles = []
  for (let k = 0; k < sorted.length; k++) {
    const a = sorted[k].i
    const b = sorted[(k + 1) % sorted.length].i
    triangles.push([a, b, points.length]) // centroid appended at end
  }

  // Return augmented points + triangles
  return { augPoints: [...points, [cx, cy, cz]], triangles }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

export default function TINView({
  points: rawPoints,
  triangles: rawTriangles,
  contourInterval = 1,
  width = 600,
  height = 420,
  wireframe = true,
  showContours = true,
  className = '',
  onDispatch,
}) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  // ── Geometry setup ─────────────────────────────────────────────────────────
  const { points, triangles, zMin, zMax } = useMemo(() => {
    if (!rawPoints || rawPoints.length < 3) {
      return { points: [], triangles: [], zMin: 0, zMax: 1 }
    }

    let pts = rawPoints
    let tris = rawTriangles

    if (!tris || tris.length === 0) {
      const fan = buildFanTriangles(pts)
      pts = fan.augPoints
      tris = fan.triangles
    }

    const zVals = pts.map(p => p[2])
    return {
      points: pts,
      triangles: tris,
      zMin: Math.min(...zVals),
      zMax: Math.max(...zVals),
    }
  }, [rawPoints, rawTriangles])

  // ── Projection ─────────────────────────────────────────────────────────────
  const PADDING = 40
  const { scale, cx, cy } = useMemo(
    () => fitToViewport(points, width, height, PADDING),
    [points, width, height],
  )
  const zScale = scale * 0.6

  function toScreen(p) {
    const cos30 = Math.sqrt(3) / 2
    const sin30 = 0.5
    const sx = (p[0] - p[1]) * cos30 * scale - cx * scale
    const sy = (p[0] + p[1]) * sin30 * scale - p[2] * zScale - cy * scale
    return [sx + width / 2, sy + height * 0.6]
  }

  // ── Faces (painter-sorted back-to-front) ───────────────────────────────────
  const sortedFaces = useMemo(() => {
    if (points.length === 0) return []
    return triangles
      .map((tri) => {
        const [i, j, k] = tri
        const pts3 = [points[i], points[j], points[k]]
        const avgZ = pts3.reduce((s, p) => s + p[2], 0) / 3
        // Use average of iso-projected y for painter sort
        const avgSY = pts3.reduce((s, p) => s + toScreen(p)[1], 0) / 3
        return { pts3, avgSY, avgZ }
      })
      .sort((a, b) => b.avgSY - a.avgSY)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, triangles, scale, zScale, width, height])

  // ── Contour segments ───────────────────────────────────────────────────────
  const contourSegs = useMemo(() => {
    if (!showContours || points.length === 0 || triangles.length === 0) return []
    const segs = []
    for (let z = Math.ceil(zMin / contourInterval) * contourInterval; z <= zMax; z += contourInterval) {
      for (const seg of extractContourSegments(points, triangles, z)) {
        segs.push(seg)
      }
    }
    return segs
  }, [points, triangles, zMin, zMax, contourInterval, showContours])

  // ── Dispatch ───────────────────────────────────────────────────────────────
  async function handleRunAnalysis() {
    if (!rawPoints || rawPoints.length < 3) return
    setLoading(true)
    setError(null)
    const params = { points: rawPoints, op: 'stats' }
    try {
      if (onDispatch) {
        onDispatch({ tool: 'civil_tin_terrain', params })
      } else {
        const res = await fetch(`${API_URL}/api/tools/call`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ tool_name: 'civil_tin_terrain', params }),
        })
        const data = await res.json()
        setResult(data)
      }
    } catch (e) {
      setError(e.message || 'Dispatch failed')
    } finally {
      setLoading(false)
    }
  }

  const isEmpty = points.length === 0

  return (
    <div
      className={`flex flex-col gap-2 ${className}`}
      data-testid="tin-view"
    >
      {/* Toolbar */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-slate-500 font-medium tracking-wide uppercase">
          TIN Surface
        </span>
        <button
          className="text-xs px-3 py-1 rounded bg-kerf-700 hover:bg-kerf-600 text-white disabled:opacity-50 transition-colors"
          onClick={handleRunAnalysis}
          disabled={loading || isEmpty}
          data-testid="tin-run-btn"
        >
          {loading ? 'Running…' : 'Run terrain analysis'}
        </button>
      </div>

      {/* SVG canvas */}
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="rounded border border-slate-800"
        style={{ background: '#0f172a' }}
        aria-label="TIN surface view"
        role="img"
      >
        {isEmpty ? (
          <text
            x={width / 2}
            y={height / 2}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize="14"
            fill="#475569"
            fontFamily="system-ui, sans-serif"
          >
            No TIN data — pass points prop
          </text>
        ) : (
          <>
            {/* Shaded faces */}
            <g aria-label="TIN faces">
              {sortedFaces.map(({ pts3, avgZ }, fi) => {
                const screenPts = pts3.map(p => toScreen(p))
                const d = `M${screenPts.map(([sx, sy]) => `${sx.toFixed(1)},${sy.toFixed(1)}`).join('L')}Z`
                const fill = shadedFaceColour(pts3, zMin, zMax)
                return (
                  <path key={fi} d={d} fill={fill} stroke="none" />
                )
              })}
            </g>

            {/* Wireframe overlay */}
            {wireframe && (
              <g aria-label="Wireframe" opacity="0.4">
                {sortedFaces.map(({ pts3 }, fi) => {
                  const screenPts = pts3.map(p => toScreen(p))
                  const d = `M${screenPts.map(([sx, sy]) => `${sx.toFixed(1)},${sy.toFixed(1)}`).join('L')}Z`
                  return (
                    <path key={fi} d={d} fill="none" stroke="#94a3b8" strokeWidth="0.5" />
                  )
                })}
              </g>
            )}

            {/* Contour lines */}
            {showContours && (
              <g aria-label="Contours">
                {contourSegs.map(([a, b], ci) => {
                  const [ax, ay] = toScreen(a)
                  const [bx, by] = toScreen(b)
                  return (
                    <line
                      key={ci}
                      x1={ax.toFixed(1)}
                      y1={ay.toFixed(1)}
                      x2={bx.toFixed(1)}
                      y2={by.toFixed(1)}
                      stroke="#fbbf24"
                      strokeWidth="1"
                      opacity="0.75"
                    />
                  )
                })}
              </g>
            )}

            {/* Elevation legend */}
            <g transform={`translate(${width - 80}, ${height - 100})`} aria-label="Elevation legend">
              <rect x="0" y="0" width="18" height="80" rx="2"
                fill="url(#tinGrad)" stroke="#475569" strokeWidth="0.5" />
              <text x="22" y="8" fontSize="9" fill="#94a3b8" fontFamily="monospace">
                {zMax.toFixed(1)} m
              </text>
              <text x="22" y="76" fontSize="9" fill="#94a3b8" fontFamily="monospace">
                {zMin.toFixed(1)} m
              </text>
              <defs>
                <linearGradient id="tinGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={elevToRgb(zMax, zMin, zMax)} />
                  <stop offset="50%" stopColor={elevToRgb((zMin + zMax) / 2, zMin, zMax)} />
                  <stop offset="100%" stopColor={elevToRgb(zMin, zMin, zMax)} />
                </linearGradient>
              </defs>
            </g>
          </>
        )}
      </svg>

      {/* Status */}
      {result && (
        <div className="text-xs text-slate-400 font-mono px-1">
          {result.ok
            ? `${result.n_triangles} triangles · area ${result.area_2d_m2?.toFixed(1)} m²`
            : result.error || 'Analysis complete'}
        </div>
      )}
      {error && (
        <div className="text-xs text-red-400 px-1">{error}</div>
      )}
    </div>
  )
}
