/**
 * GradingPlanView.jsx — plan-view cut/fill grading comparison.
 *
 * Shows two TIN surfaces side by side in 2-D contour plan view:
 *   • Existing surface contours (grey/blue)
 *   • Proposed surface contours (orange)
 *   • Cut / fill colour bands (red = cut, green = fill) from the diff
 *
 * A "Compute volumes" button dispatches `civil_tin_terrain` (op='volume') for
 * the proposed surface via POST /api/tools/call and shows the result.
 *
 * Props
 * ─────
 *   existing  {Array<[x,y,z]>}   Existing-ground survey points.
 *   proposed  {Array<[x,y,z]>}   Proposed finished-grade points.
 *   existingTriangles {Array}     Triangle indices for existing (optional).
 *   proposedTriangles {Array}     Triangle indices for proposed (optional).
 *   contourInterval {number}      Contour interval in metres (default 0.5).
 *   datumZ    {number}            Datum elevation for volume calc (default 0).
 *   width     {number}            SVG canvas width  (default 600).
 *   height    {number}            SVG canvas height (default 420).
 *   className {string}
 *   onDispatch {function}         Called with { tool, params } instead of fetch.
 */

import { useMemo, useState } from 'react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''
const PADDING = 50

// ---------------------------------------------------------------------------
// Project 3-D points to 2-D plan (drop z)
// ---------------------------------------------------------------------------

function fitPlan(points, width, height) {
  if (!points?.length) return { scale: 1, offX: 0, offY: 0 }
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const [x, y] of points) {
    if (x < minX) minX = x; if (x > maxX) maxX = x
    if (y < minY) minY = y; if (y > maxY) maxY = y
  }
  const rangeX = maxX - minX || 1
  const rangeY = maxY - minY || 1
  const usableW = width - PADDING * 2
  const usableH = height - PADDING * 2
  const scale = Math.min(usableW / rangeX, usableH / rangeY)
  const scaledW = rangeX * scale
  const scaledH = rangeY * scale
  return {
    scale,
    offX: PADDING + (usableW - scaledW) / 2 - minX * scale,
    offY: PADDING + (usableH - scaledH) / 2 - minY * scale,
  }
}

// ---------------------------------------------------------------------------
// Extract contour polylines in 2-D plan
// ---------------------------------------------------------------------------

function planContourSegs(points, triangles, zLevel, transform) {
  const { scale, offX, offY } = transform
  const segs = []
  for (const [i, j, k] of triangles) {
    const pts = [points[i], points[j], points[k]]
    const edges = [[0, 1], [1, 2], [2, 0]]
    const crossed = []
    for (const [a, b] of edges) {
      const za = pts[a][2], zb = pts[b][2]
      if ((za <= zLevel && zb > zLevel) || (za > zLevel && zb <= zLevel)) {
        const t = (zLevel - za) / (zb - za)
        const x = pts[a][0] + t * (pts[b][0] - pts[a][0])
        const y = pts[a][1] + t * (pts[b][1] - pts[a][1])
        crossed.push([x * scale + offX, y * scale + offY])
      }
    }
    if (crossed.length === 2) segs.push(crossed)
  }
  return segs
}

// ---------------------------------------------------------------------------
// Approximate per-point elevation difference (cut/fill indicator)
// Interpolates proposed surface at each existing point using nearest centroid
// ---------------------------------------------------------------------------

function buildCutFillFaces(existingPts, proposedPts, proposedTris, transform) {
  // For each proposed triangle face, compute avg z diff relative to existing
  // (simplified: use proposed centroid z vs existing z at nearest point)
  const { scale, offX, offY } = transform
  const faces = []

  for (const [i, j, k] of proposedTris) {
    const pp = [proposedPts[i], proposedPts[j], proposedPts[k]]
    const cx = (pp[0][0] + pp[1][0] + pp[2][0]) / 3
    const cy = (pp[0][1] + pp[1][1] + pp[2][1]) / 3
    const cz = (pp[0][2] + pp[1][2] + pp[2][2]) / 3

    // Find nearest existing point
    let minDist = Infinity, nearZ = cz
    for (const ep of existingPts) {
      const d2 = (ep[0] - cx) ** 2 + (ep[1] - cy) ** 2
      if (d2 < minDist) { minDist = d2; nearZ = ep[2] }
    }

    const diff = cz - nearZ // positive = fill, negative = cut
    const screenPts = pp.map(p => [p[0] * scale + offX, p[1] * scale + offY])
    const d = `M${screenPts.map(([sx, sy]) => `${sx.toFixed(1)},${sy.toFixed(1)}`).join('L')}Z`

    faces.push({ d, diff })
  }
  return faces
}

// ---------------------------------------------------------------------------
// Trivial fan triangulation when none provided
// ---------------------------------------------------------------------------

function buildFanTriangles(points) {
  if (!points || points.length < 3) return { augPoints: points || [], triangles: [] }
  const cx = points.reduce((s, p) => s + p[0], 0) / points.length
  const cy = points.reduce((s, p) => s + p[1], 0) / points.length
  const cz = points.reduce((s, p) => s + p[2], 0) / points.length
  const sorted = points
    .map((p, idx) => ({ idx, angle: Math.atan2(p[1] - cy, p[0] - cx) }))
    .sort((a, b) => a.angle - b.angle)
  const augPoints = [...points, [cx, cy, cz]]
  const triangles = sorted.map(({ idx }, k) => [
    idx,
    sorted[(k + 1) % sorted.length].idx,
    points.length,
  ])
  return { augPoints, triangles }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function GradingPlanView({
  existing: rawExisting = [],
  proposed: rawProposed = [],
  existingTriangles: rawExTris,
  proposedTriangles: rawPropTris,
  contourInterval = 0.5,
  datumZ = 0,
  width = 600,
  height = 420,
  className = '',
  onDispatch,
}) {
  const [loading, setLoading] = useState(false)
  const [volResult, setVolResult] = useState(null)
  const [error, setError] = useState(null)

  // Triangulate if needed
  const { existingPts, existingTris, proposedPts, proposedTris } = useMemo(() => {
    let ePts = rawExisting, eTris = rawExTris
    let pPts = rawProposed, pTris = rawPropTris

    if (!eTris || !eTris.length) {
      const f = buildFanTriangles(ePts)
      ePts = f.augPoints; eTris = f.triangles
    }
    if (!pTris || !pTris.length) {
      const f = buildFanTriangles(pPts)
      pPts = f.augPoints; pTris = f.triangles
    }
    return { existingPts: ePts, existingTris: eTris, proposedPts: pPts, proposedTris: pTris }
  }, [rawExisting, rawProposed, rawExTris, rawPropTris])

  // Fit to viewport using both point sets
  const transform = useMemo(() => {
    const all = [...existingPts, ...proposedPts].filter(p => p)
    return fitPlan(all, width, height)
  }, [existingPts, proposedPts, width, height])

  // z ranges
  const { eZMin, eZMax, pZMin, pZMax } = useMemo(() => {
    const ez = existingPts.map(p => p[2])
    const pz = proposedPts.map(p => p[2])
    return {
      eZMin: Math.min(...ez, 0),
      eZMax: Math.max(...ez, 1),
      pZMin: Math.min(...pz, 0),
      pZMax: Math.max(...pz, 1),
    }
  }, [existingPts, proposedPts])

  // Existing contours
  const existingContours = useMemo(() => {
    if (!existingPts.length || !existingTris.length) return []
    const segs = []
    for (let z = Math.ceil(eZMin / contourInterval) * contourInterval; z <= eZMax; z += contourInterval) {
      segs.push(...planContourSegs(existingPts, existingTris, z, transform))
    }
    return segs
  }, [existingPts, existingTris, eZMin, eZMax, contourInterval, transform])

  // Proposed contours
  const proposedContours = useMemo(() => {
    if (!proposedPts.length || !proposedTris.length) return []
    const segs = []
    for (let z = Math.ceil(pZMin / contourInterval) * contourInterval; z <= pZMax; z += contourInterval) {
      segs.push(...planContourSegs(proposedPts, proposedTris, z, transform))
    }
    return segs
  }, [proposedPts, proposedTris, pZMin, pZMax, contourInterval, transform])

  // Cut/fill faces
  const cutFillFaces = useMemo(() => {
    if (!existingPts.length || !proposedPts.length || !proposedTris.length) return []
    return buildCutFillFaces(existingPts, proposedPts, proposedTris, transform)
  }, [existingPts, proposedPts, proposedTris, transform])

  // ── Dispatch ───────────────────────────────────────────────────────────────
  async function handleVolumes() {
    if (!rawProposed?.length) return
    setLoading(true)
    setError(null)
    const params = { points: rawProposed, op: 'volume', datum_z: datumZ }
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
        setVolResult(data)
      }
    } catch (e) {
      setError(e.message || 'Dispatch failed')
    } finally {
      setLoading(false)
    }
  }

  const isEmpty = existingPts.length === 0 && proposedPts.length === 0

  return (
    <div
      className={`flex flex-col gap-2 ${className}`}
      data-testid="grading-plan-view"
    >
      {/* Toolbar */}
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-slate-500 font-medium tracking-wide uppercase">
          Grading Plan
        </span>
        <button
          className="text-xs px-3 py-1 rounded bg-kerf-700 hover:bg-kerf-600 text-white disabled:opacity-50 transition-colors"
          onClick={handleVolumes}
          disabled={loading || isEmpty}
          data-testid="grading-volume-btn"
        >
          {loading ? 'Computing…' : 'Compute volumes'}
        </button>
      </div>

      {/* SVG canvas */}
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="rounded border border-slate-800"
        style={{ background: '#0f172a' }}
        aria-label="Grading plan view"
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
            No grading data — pass existing + proposed props
          </text>
        ) : (
          <>
            {/* Cut/fill colour wash */}
            <g aria-label="Cut/fill" opacity="0.35">
              {cutFillFaces.map(({ d, diff }, fi) => (
                <path
                  key={fi}
                  d={d}
                  fill={diff < 0 ? '#ef4444' : '#22c55e'}
                  stroke="none"
                />
              ))}
            </g>

            {/* Existing contours */}
            <g aria-label="Existing contours" opacity="0.7">
              {existingContours.map(([a, b], ci) => (
                <line
                  key={ci}
                  x1={a[0].toFixed(1)} y1={a[1].toFixed(1)}
                  x2={b[0].toFixed(1)} y2={b[1].toFixed(1)}
                  stroke="#64748b"
                  strokeWidth="1"
                />
              ))}
            </g>

            {/* Proposed contours */}
            <g aria-label="Proposed contours" opacity="0.85">
              {proposedContours.map(([a, b], ci) => (
                <line
                  key={ci}
                  x1={a[0].toFixed(1)} y1={a[1].toFixed(1)}
                  x2={b[0].toFixed(1)} y2={b[1].toFixed(1)}
                  stroke="#f97316"
                  strokeWidth="1.5"
                />
              ))}
            </g>

            {/* Legend */}
            <g transform={`translate(12, 12)`} aria-label="Legend">
              <rect x="0" y="0" width="148" height="64" rx="4" fill="#1e293b" opacity="0.9" />
              <line x1="8" y1="14" x2="28" y2="14" stroke="#64748b" strokeWidth="1.5" />
              <text x="33" y="18" fontSize="9" fill="#94a3b8" fontFamily="monospace">Existing contour</text>
              <line x1="8" y1="30" x2="28" y2="30" stroke="#f97316" strokeWidth="2" />
              <text x="33" y="34" fontSize="9" fill="#94a3b8" fontFamily="monospace">Proposed contour</text>
              <rect x="8" y="42" width="14" height="12" fill="#22c55e" opacity="0.6" />
              <text x="27" y="52" fontSize="9" fill="#94a3b8" fontFamily="monospace">Fill</text>
              <rect x="68" y="42" width="14" height="12" fill="#ef4444" opacity="0.6" />
              <text x="87" y="52" fontSize="9" fill="#94a3b8" fontFamily="monospace">Cut</text>
            </g>
          </>
        )}
      </svg>

      {/* Volume result */}
      {volResult && (
        <div className="text-xs text-slate-400 font-mono px-1">
          {volResult.ok
            ? `Volume above datum (${datumZ} m): ${volResult.volume_m3?.toFixed(1)} m³`
            : volResult.error || 'Calculation complete'}
        </div>
      )}
      {error && (
        <div className="text-xs text-red-400 px-1">{error}</div>
      )}
    </div>
  )
}
