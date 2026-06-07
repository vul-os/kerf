/**
 * PointCloudPanel.jsx — Laser-scan / point-cloud viewport for plant and
 * infrastructure brownfield work.
 *
 * Renders a scanned point cloud in an isometric Canvas 2D projection.
 * When deviation data is supplied (from pointcloud_deviation_check), points
 * are coloured by a signed-deviation heatmap (blue = below / gap,
 * green = within tolerance, red = above / protrusion).
 *
 * When pipe detection results are supplied (from pointcloud_detect_pipes),
 * each detected cylinder is overlaid as a coloured tube (two semicircular
 * arcs at start/end + axis line in the pipe's unique colour).
 *
 * When as-built overlay results are supplied (from pointcloud_asbuilt_overlay),
 * a deviation table is rendered below the viewport listing each matched pipe
 * with position/diameter deviation and pass/fail status.
 *
 * Props
 * ─────
 * points           {Array<[x,y,z]>}       Point positions (metres).
 * deviations       {Array<number>|null}   Per-point signed deviation (m).
 *                                          If null, points are coloured by Z.
 * heatmapColors    {Array<[R,G,B]>|null}  Pre-computed RGB triples from the
 *                                          backend (overrides local compute).
 * stats            {object|null}          pointcloud_import stats dict.
 * aabb             {object|null}          pointcloud_import aabb dict.
 * planeResult      {object|null}          pointcloud_fit_plane result dict.
 * pipeSegments     {Array<object>|null}   Detected pipe segments from
 *                                          pointcloud_detect_pipes.segments.
 * pipeRuns         {Array<object>|null}   Pipe runs from
 *                                          pointcloud_detect_pipes.runs.
 * asbuiltOverlay   {object|null}          Result from pointcloud_asbuilt_overlay.
 * tolerance_m      {number}               Deviation tolerance (m) — default 0.01.
 * width            {number}               Canvas pixel width  (default 640).
 * height           {number}               Canvas pixel height (default 440).
 * className        {string}               Extra CSS class on root element.
 * onDispatch       {function}             Called with { tool, params } for AI
 *                                          tool calls (optional).
 *
 * Layout
 * ──────
 *   ┌─────────────────────────────────┬──────────────┐
 *   │  Isometric point cloud canvas   │  Stats panel │
 *   │  (rotatable via pointer-drag)   │  + controls  │
 *   └─────────────────────────────────┴──────────────┘
 *   └─────────────── Colour bar ────────────────────┘
 *   └─────── As-built / design deviation table ─────┘
 *
 * Isometric projection:
 *   sx = (x - y) * cos30 * scale + cx
 *   sy = (x + y) * sin30 * scale - z * zScale + cy
 *
 * Point size is adaptive: max(1.5, 6 / sqrt(N)) pixels.
 */

import { useEffect, useRef, useState, useMemo, useCallback } from 'react'

// ── Projection helpers ────────────────────────────────────────────────────────

const COS30 = Math.sqrt(3) / 2
const SIN30 = 0.5

function project(x, y, z, scale, zScale, cx, cy, rotY = 0) {
  // Rotate around Z-axis by rotY
  const cr = Math.cos(rotY)
  const sr = Math.sin(rotY)
  const rx = x * cr - y * sr
  const ry = x * sr + y * cr
  return {
    sx: (rx - ry) * COS30 * scale + cx,
    sy: (rx + ry) * SIN30 * scale - z * zScale + cy,
  }
}

function fitViewport(points, width, height, padding) {
  if (!points || points.length === 0) return { scale: 1, zScale: 1, cx: width / 2, cy: height / 2 }
  let minSX = Infinity, maxSX = -Infinity, minSY = Infinity, maxSY = -Infinity
  for (const [x, y, z] of points) {
    const sx = (x - y) * COS30
    const sy = (x + y) * SIN30 - z * 0.8
    if (sx < minSX) minSX = sx
    if (sx > maxSX) maxSX = sx
    if (sy < minSY) minSY = sy
    if (sy > maxSY) maxSY = sy
  }
  const rangeX = (maxSX - minSX) || 1
  const rangeY = (maxSY - minSY) || 1
  const scale = Math.min((width - padding * 2) / rangeX, (height - padding * 2) / rangeY)
  const cx = width / 2 - ((minSX + maxSX) / 2) * scale
  const cy = height / 2 - ((minSY + maxSY) / 2) * scale
  return { scale, zScale: scale * 0.8, cx, cy }
}

// ── Colour helpers ─────────────────────────────────────────────────────────────

function deviationToColor(d, devRange) {
  if (devRange < 1e-9) return 'rgb(100,180,100)'
  const t = Math.max(-1, Math.min(1, d / devRange))
  if (t < 0) {
    const abs_t = -t
    return `rgb(0,${Math.round(255 * (1 - abs_t))},${Math.round(255 * abs_t)})`
  }
  return `rgb(${Math.round(255 * t)},${Math.round(255 * (1 - t))},0)`
}

function elevToColor(z, zMin, zMax) {
  const t = zMax === zMin ? 0.5 : Math.max(0, Math.min(1, (z - zMin) / (zMax - zMin)))
  const r = Math.round(t < 0.5 ? 30 + t * 2 * 140 : 170 + (t - 0.5) * 2 * 60)
  const g = Math.round(t < 0.5 ? 100 + t * 2 * 80 : 180 - (t - 0.5) * 2 * 80)
  const b = Math.round(t < 0.5 ? 180 - t * 2 * 100 : 40)
  return `rgb(${r},${g},${b})`
}

// ── Stats panel ───────────────────────────────────────────────────────────────

function StatRow({ label, value }) {
  return (
    <tr>
      <td style={{ color: '#8a9aa8', fontSize: 11, paddingRight: 8, paddingBottom: 2, whiteSpace: 'nowrap' }}>
        {label}
      </td>
      <td style={{ color: '#e2ecf5', fontSize: 11, fontFamily: 'monospace', paddingBottom: 2 }}>
        {value}
      </td>
    </tr>
  )
}

// Colour palette for pipe segments (distinct per DN or segment_id)
const PIPE_COLORS = [
  '#e05b5b', '#5bc8e0', '#5be075', '#e0b45b',
  '#b45be0', '#e0e05b', '#5b8be0', '#e07b5b',
  '#5be0b4', '#c05be0', '#7be060', '#e05ba0',
]

function pipeColor(idx) {
  return PIPE_COLORS[idx % PIPE_COLORS.length]
}

function StatsPanel({ stats, aabb, planeResult, deviations, tolerance_m, pipeSegments, pipeRuns }) {
  const nPts = stats?.n_points ?? (deviations?.length ?? 0)
  const hasDevs = deviations && deviations.length > 0
  const devMin = hasDevs ? Math.min(...deviations) : null
  const devMax = hasDevs ? Math.max(...deviations) : null
  const devRms = hasDevs
    ? Math.sqrt(deviations.reduce((s, d) => s + d * d, 0) / deviations.length)
    : null
  const nWithin = hasDevs ? deviations.filter(d => Math.abs(d) <= tolerance_m).length : null

  const hasPipes = pipeSegments && pipeSegments.length > 0
  const hasRuns = pipeRuns && pipeRuns.length > 0
  const nElbows = hasRuns ? pipeRuns.reduce((acc, r) => acc + (r.elbows?.length ?? 0), 0) : 0

  return (
    <div style={{
      minWidth: 170, maxWidth: 200,
      background: '#1a2530',
      borderLeft: '1px solid #2a3b4c',
      padding: '10px 12px',
      display: 'flex', flexDirection: 'column', gap: 8,
      fontSize: 12,
      overflowY: 'auto',
    }}>
      <div style={{ color: '#5ba0c8', fontWeight: 600, fontSize: 12, marginBottom: 2 }}>
        Point Cloud
      </div>

      <table style={{ borderCollapse: 'collapse' }}>
        <tbody>
          {nPts > 0 && <StatRow label="N points" value={nPts.toLocaleString()} />}
          {aabb && <>
            <StatRow label="X range" value={`${aabb.size_x?.toFixed(2)} m`} />
            <StatRow label="Y range" value={`${aabb.size_y?.toFixed(2)} m`} />
            <StatRow label="Z range" value={`${aabb.size_z?.toFixed(2)} m`} />
            <StatRow label="Diagonal" value={`${aabb.diagonal_m?.toFixed(2)} m`} />
          </>}
          {stats?.density_per_m2 != null && (
            <StatRow label="Density" value={`${stats.density_per_m2.toFixed(2)} pt/m²`} />
          )}
        </tbody>
      </table>

      {hasDevs && (
        <>
          <div style={{ color: '#5ba0c8', fontWeight: 600, fontSize: 12, marginTop: 4 }}>
            Deviation
          </div>
          <table style={{ borderCollapse: 'collapse' }}>
            <tbody>
              <StatRow label="Min" value={`${devMin.toFixed(4)} m`} />
              <StatRow label="Max" value={`${devMax.toFixed(4)} m`} />
              <StatRow label="RMS" value={`${devRms.toFixed(4)} m`} />
              <StatRow label="Tolerance" value={`±${tolerance_m} m`} />
              <StatRow
                label="Within tol."
                value={`${nWithin} / ${deviations.length} (${(nWithin / deviations.length * 100).toFixed(1)}%)`}
              />
            </tbody>
          </table>
        </>
      )}

      {planeResult?.success && (
        <>
          <div style={{ color: '#5ba0c8', fontWeight: 600, fontSize: 12, marginTop: 4 }}>
            Fit Plane
          </div>
          <table style={{ borderCollapse: 'collapse' }}>
            <tbody>
              <StatRow label="Normal" value={`[${planeResult.normal.map(v => v.toFixed(3)).join(', ')}]`} />
              <StatRow label="Inliers" value={`${planeResult.inlier_count} (${(planeResult.inlier_fraction * 100).toFixed(1)}%)`} />
              <StatRow label="RMSE" value={`${planeResult.rmse_m?.toFixed(4)} m`} />
              <StatRow label="Dip" value={`${planeResult.dip_deg?.toFixed(1)}°`} />
              <StatRow label="Level" value={<span style={{ color: planeResult.level_check === 'PASS' ? '#4ec94e' : '#e55' }}>{planeResult.level_check}</span>} />
              <StatRow label="Plumb" value={<span style={{ color: planeResult.plumb_check === 'PASS' ? '#4ec94e' : '#e55' }}>{planeResult.plumb_check}</span>} />
            </tbody>
          </table>
        </>
      )}

      {hasPipes && (
        <>
          <div style={{ color: '#5ba0c8', fontWeight: 600, fontSize: 12, marginTop: 4 }}>
            Detected Pipes
          </div>
          <table style={{ borderCollapse: 'collapse' }}>
            <tbody>
              <StatRow label="Segments" value={pipeSegments.length} />
              {hasRuns && <StatRow label="Runs" value={pipeRuns.length} />}
              {hasRuns && nElbows > 0 && <StatRow label="Elbows" value={nElbows} />}
            </tbody>
          </table>
          {/* Per-pipe DN summary */}
          {pipeSegments.slice(0, 6).map((seg, idx) => (
            <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 1 }}>
              <div style={{
                width: 8, height: 8, borderRadius: '50%',
                background: pipeColor(idx), flexShrink: 0,
              }} />
              <span style={{ color: '#c8dce8', fontSize: 10 }}>
                DN{seg.nominal_dn_mm} · {seg.length_m?.toFixed(2)} m
              </span>
            </div>
          ))}
          {pipeSegments.length > 6 && (
            <span style={{ color: '#5a7a8a', fontSize: 10 }}>
              +{pipeSegments.length - 6} more
            </span>
          )}
        </>
      )}
    </div>
  )
}

// ── Colour bar ─────────────────────────────────────────────────────────────────

function DeviationColorBar({ devRange, tolerance_m }) {
  const stops = 7
  const swatches = []
  for (let i = 0; i <= stops; i++) {
    const t = i / stops
    const d = (t - 0.5) * 2 * devRange
    swatches.push({ d, color: deviationToColor(d, devRange) })
  }
  const gradient = `linear-gradient(to right, ${swatches.map(s => s.color).join(', ')})`

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px 6px', background: '#131f2b' }}>
      <span style={{ color: '#6a8aa0', fontSize: 10, minWidth: 60, textAlign: 'right' }}>
        {`−${devRange.toFixed(3)} m`}
      </span>
      <div style={{ flex: 1, height: 10, borderRadius: 5, background: gradient }} />
      <span style={{ color: '#6a8aa0', fontSize: 10, minWidth: 60 }}>
        {`+${devRange.toFixed(3)} m`}
      </span>
      <span style={{ color: '#6a8aa0', fontSize: 10 }}>
        tol: ±{tolerance_m}m
      </span>
    </div>
  )
}

function ElevColorBar({ zMin, zMax }) {
  const stops = 5
  const swatches = []
  for (let i = 0; i <= stops; i++) {
    const t = i / stops
    const z = zMin + (zMax - zMin) * t
    swatches.push({ z, color: elevToColor(z, zMin, zMax) })
  }
  const gradient = `linear-gradient(to right, ${swatches.map(s => s.color).join(', ')})`

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px 6px', background: '#131f2b' }}>
      <span style={{ color: '#6a8aa0', fontSize: 10, minWidth: 60, textAlign: 'right' }}>
        z={zMin.toFixed(2)} m
      </span>
      <div style={{ flex: 1, height: 10, borderRadius: 5, background: gradient }} />
      <span style={{ color: '#6a8aa0', fontSize: 10, minWidth: 60 }}>
        z={zMax.toFixed(2)} m
      </span>
    </div>
  )
}

// ── As-built / design deviation table ─────────────────────────────────────────

const STATUS_COLOR = {
  ok: '#4ec94e',
  pos_mismatch: '#e0a040',
  dia_mismatch: '#e06040',
  both_mismatch: '#e04040',
}

function AsbuiltDeviationTable({ overlay }) {
  if (!overlay || !overlay.matches || overlay.matches.length === 0) return null
  const { matches, summary, n_asbuilt, n_design, n_matched, n_unmatched } = overlay

  return (
    <div style={{
      background: '#111d28',
      borderTop: '1px solid #1e3040',
      padding: '8px 14px',
      fontFamily: 'sans-serif',
      fontSize: 11,
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
        <span style={{ color: '#5ba0c8', fontWeight: 700, fontSize: 12 }}>
          As-Built vs Design
        </span>
        <span style={{ color: '#8aacb8', fontSize: 10 }}>
          {n_matched}/{n_asbuilt} matched · {n_unmatched} orphan
        </span>
        {summary && (
          <span style={{ marginLeft: 'auto', color: '#7a9ab0', fontSize: 10 }}>
            Max pos dev: {(summary.max_pos_dev_m * 1000).toFixed(1)} mm ·
            RMS: {(summary.rms_pos_dev_m * 1000).toFixed(1)} mm
          </span>
        )}
      </div>

      {/* Summary badges */}
      {summary && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
          {summary.n_ok > 0 && (
            <span style={{ background: '#1a3a1a', color: '#4ec94e', padding: '1px 8px', borderRadius: 10, fontSize: 10 }}>
              {summary.n_ok} OK
            </span>
          )}
          {summary.n_pos_mismatch > 0 && (
            <span style={{ background: '#2a2510', color: '#e0a040', padding: '1px 8px', borderRadius: 10, fontSize: 10 }}>
              {summary.n_pos_mismatch} pos mismatch
            </span>
          )}
          {summary.n_dia_mismatch > 0 && (
            <span style={{ background: '#2a1510', color: '#e06040', padding: '1px 8px', borderRadius: 10, fontSize: 10 }}>
              {summary.n_dia_mismatch} dia mismatch
            </span>
          )}
          {summary.n_both_mismatch > 0 && (
            <span style={{ background: '#2a1010', color: '#e04040', padding: '1px 8px', borderRadius: 10, fontSize: 10 }}>
              {summary.n_both_mismatch} both mismatch
            </span>
          )}
        </div>
      )}

      {/* Deviation table */}
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #1e3040' }}>
            {['As-built', 'Design', 'Pos dev', 'Dia dev', 'Status'].map(h => (
              <th key={h} style={{
                color: '#5a8aa0', fontSize: 10, fontWeight: 600,
                padding: '2px 6px', textAlign: 'left',
              }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matches.map((m, i) => (
            <tr key={i} style={{ borderBottom: '1px solid #182530' }}>
              <td style={{ color: '#c8dce8', fontSize: 10, padding: '2px 6px' }}>{m.asbuilt_id}</td>
              <td style={{ color: '#c8dce8', fontSize: 10, padding: '2px 6px' }}>{m.design_id}</td>
              <td style={{ color: m.pos_ok ? '#4ec94e' : '#e06040', fontSize: 10, padding: '2px 6px', fontFamily: 'monospace' }}>
                {(m.pos_deviation_m * 1000).toFixed(1)} mm
              </td>
              <td style={{ color: m.dia_ok ? '#4ec94e' : '#e06040', fontSize: 10, padding: '2px 6px', fontFamily: 'monospace' }}>
                {(m.dia_deviation_m * 1000).toFixed(1)} mm ({(m.dia_deviation_frac * 100).toFixed(1)}%)
              </td>
              <td style={{ padding: '2px 6px' }}>
                <span style={{
                  color: STATUS_COLOR[m.status] ?? '#8aacb8',
                  fontSize: 9,
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.03em',
                }}>
                  {m.status.replace('_', ' ')}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}


// ── Main panel ────────────────────────────────────────────────────────────────

export default function PointCloudPanel({
  points = null,
  deviations = null,
  heatmapColors = null,
  stats = null,
  aabb = null,
  planeResult = null,
  pipeSegments = null,
  pipeRuns = null,
  asbuiltOverlay = null,
  tolerance_m = 0.01,
  width = 640,
  height = 440,
  className = '',
  onDispatch = null,
}) {
  const canvasRef = useRef(null)
  const [rotY, setRotY] = useState(Math.PI / 6)
  const [dragging, setDragging] = useState(false)
  const [lastX, setLastX] = useState(0)

  const pts = useMemo(() => {
    if (!points || points.length === 0) return []
    return points
  }, [points])

  const hasPipes = pipeSegments && pipeSegments.length > 0
  const hasDevs = deviations && deviations.length === pts.length
  const hasHeatmap = heatmapColors && heatmapColors.length === pts.length

  const devRange = useMemo(() => {
    if (!hasDevs) return 0
    const abs = deviations.map(Math.abs)
    return Math.max(...abs, 1e-9)
  }, [deviations, hasDevs])

  const { zMin, zMax } = useMemo(() => {
    if (pts.length === 0) return { zMin: 0, zMax: 1 }
    let mn = Infinity, mx = -Infinity
    for (const p of pts) {
      if (p[2] < mn) mn = p[2]
      if (p[2] > mx) mx = p[2]
    }
    return { zMin: mn, zMax: mx === mn ? mn + 1 : mx }
  }, [pts])

  // Canvas width is total width minus stats sidebar
  const canvasW = Math.max(width - 200, 300)

  const viewport = useMemo(
    () => fitViewport(pts, canvasW, height - 20, 30),
    [pts, canvasW, height]
  )

  const ptSize = useMemo(() => Math.max(1.5, 6 / Math.sqrt(Math.max(pts.length, 1))), [pts])

  // Render loop
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvasW, height - 20)
    ctx.fillStyle = '#0d1822'
    ctx.fillRect(0, 0, canvasW, height - 20)

    if (pts.length === 0) {
      ctx.fillStyle = '#3a5570'
      ctx.font = '14px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('No point cloud data', canvasW / 2, (height - 20) / 2)
      ctx.fillStyle = '#2a4560'
      ctx.font = '11px sans-serif'
      ctx.fillText('Provide points[] to render the scan', canvasW / 2, (height - 20) / 2 + 22)
      return
    }

    const { scale, zScale, cx, cy } = viewport

    // Sort back-to-front for painter's algorithm (by screen Y)
    const projected = pts.map((p, i) => {
      const { sx, sy } = project(p[0], p[1], p[2], scale, zScale, cx, cy, rotY)
      return { sx, sy, z: p[2], idx: i }
    })
    projected.sort((a, b) => a.sy - b.sy)

    // Draw points
    for (const { sx, sy, z, idx } of projected) {
      let color
      if (hasHeatmap) {
        const [r, g, b] = heatmapColors[idx]
        color = `rgb(${r},${g},${b})`
      } else if (hasDevs) {
        color = deviationToColor(deviations[idx], devRange)
      } else {
        color = elevToColor(z, zMin, zMax)
      }
      ctx.beginPath()
      ctx.arc(sx, sy, ptSize, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
    }

    // Draw AABB wireframe if aabb provided
    if (aabb && aabb.min_x != null) {
      const corners = [
        [aabb.min_x, aabb.min_y, aabb.min_z],
        [aabb.max_x, aabb.min_y, aabb.min_z],
        [aabb.max_x, aabb.max_y, aabb.min_z],
        [aabb.min_x, aabb.max_y, aabb.min_z],
        [aabb.min_x, aabb.min_y, aabb.max_z],
        [aabb.max_x, aabb.min_y, aabb.max_z],
        [aabb.max_x, aabb.max_y, aabb.max_z],
        [aabb.min_x, aabb.max_y, aabb.max_z],
      ]
      const edges = [
        [0, 1], [1, 2], [2, 3], [3, 0],
        [4, 5], [5, 6], [6, 7], [7, 4],
        [0, 4], [1, 5], [2, 6], [3, 7],
      ]
      ctx.strokeStyle = 'rgba(90,160,220,0.35)'
      ctx.lineWidth = 0.8
      for (const [a, b] of edges) {
        const pa = project(corners[a][0], corners[a][1], corners[a][2], scale, zScale, cx, cy, rotY)
        const pb = project(corners[b][0], corners[b][1], corners[b][2], scale, zScale, cx, cy, rotY)
        ctx.beginPath()
        ctx.moveTo(pa.sx, pa.sy)
        ctx.lineTo(pb.sx, pb.sy)
        ctx.stroke()
      }
    }

    // Draw fitted plane indicator if available
    if (planeResult?.success && planeResult.centroid) {
      const [cx3, cy3, cz3] = planeResult.centroid
      const [nx, ny, nz] = planeResult.normal
      const { sx: pcx, sy: pcy } = project(cx3, cy3, cz3, scale, zScale, cx, cy, rotY)
      const scale_n = 2.0  // metres
      const { sx: pnx, sy: pny } = project(
        cx3 + nx * scale_n, cy3 + ny * scale_n, cz3 + nz * scale_n,
        scale, zScale, cx, cy, rotY
      )
      ctx.strokeStyle = 'rgba(255,200,60,0.9)'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(pcx, pcy)
      ctx.lineTo(pnx, pny)
      ctx.stroke()
      ctx.beginPath()
      ctx.arc(pcx, pcy, 5, 0, Math.PI * 2)
      ctx.fillStyle = 'rgba(255,200,60,0.9)'
      ctx.fill()
    }

    // Draw detected pipe segments as coloured cylinder overlays.
    // Each cylinder is rendered as:
    //   • A thick axis line from centerline_start to centerline_end
    //   • A small filled circle at each endpoint (to indicate pipe termination)
    //   • DN label at the midpoint
    if (hasPipes && pipeSegments) {
      for (let pi = 0; pi < pipeSegments.length; pi++) {
        const seg = pipeSegments[pi]
        if (!seg.centerline_start || !seg.centerline_end) continue

        const color = pipeColor(pi)
        const [sx1, sy1, sz1] = seg.centerline_start
        const [sx2, sy2, sz2] = seg.centerline_end

        const pa = project(sx1, sy1, sz1, scale, zScale, cx, cy, rotY)
        const pb = project(sx2, sy2, sz2, scale, zScale, cx, cy, rotY)

        // Pipe radius in screen pixels (proportional, clamped for readability)
        const screenRadius = Math.max(2, Math.min(10, (seg.radius_m ?? 0.05) * scale * 2))

        // Draw thick axis line
        ctx.strokeStyle = color
        ctx.globalAlpha = 0.85
        ctx.lineWidth = screenRadius * 2
        ctx.lineCap = 'round'
        ctx.beginPath()
        ctx.moveTo(pa.sx, pa.sy)
        ctx.lineTo(pb.sx, pb.sy)
        ctx.stroke()
        ctx.globalAlpha = 1.0

        // Endpoint caps
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.arc(pa.sx, pa.sy, screenRadius, 0, Math.PI * 2)
        ctx.fill()
        ctx.beginPath()
        ctx.arc(pb.sx, pb.sy, screenRadius, 0, Math.PI * 2)
        ctx.fill()

        // DN label at midpoint
        const mx = (pa.sx + pb.sx) / 2
        const my = (pa.sy + pb.sy) / 2
        ctx.fillStyle = 'rgba(0,0,0,0.6)'
        ctx.fillRect(mx - 14, my - 9, 28, 11)
        ctx.fillStyle = color
        ctx.font = 'bold 9px monospace'
        ctx.textAlign = 'center'
        ctx.fillText(`DN${seg.nominal_dn_mm}`, mx, my)
      }
      ctx.lineCap = 'butt'

      // Draw elbow markers from pipe runs
      if (pipeRuns) {
        for (const run of pipeRuns) {
          for (const elbow of (run.elbows ?? [])) {
            if (!elbow.position) continue
            const [ex, ey, ez] = elbow.position
            const pe = project(ex, ey, ez, scale, zScale, cx, cy, rotY)
            ctx.beginPath()
            ctx.arc(pe.sx, pe.sy, 5, 0, Math.PI * 2)
            ctx.fillStyle = 'rgba(255,220,80,0.9)'
            ctx.fill()
            ctx.strokeStyle = '#c08000'
            ctx.lineWidth = 1.5
            ctx.stroke()
            // Angle label
            ctx.fillStyle = '#ffe080'
            ctx.font = '8px sans-serif'
            ctx.textAlign = 'center'
            ctx.fillText(`${elbow.angle_deg?.toFixed(0)}°`, pe.sx, pe.sy - 8)
          }
        }
      }
    }

    // Point count overlay
    ctx.fillStyle = 'rgba(0,0,0,0.45)'
    ctx.fillRect(6, 6, 140, 18)
    ctx.fillStyle = '#7ab0d0'
    ctx.font = '10px monospace'
    ctx.textAlign = 'left'
    ctx.fillText(`${pts.length.toLocaleString()} points | drag to rotate`, 10, 19)
  }, [pts, rotY, viewport, deviations, heatmapColors, hasDevs, hasHeatmap, devRange, zMin, zMax, ptSize, aabb, planeResult, pipeSegments, pipeRuns, hasPipes, canvasW, height])

  // Mouse handlers for rotation
  const onPointerDown = useCallback((e) => {
    setDragging(true)
    setLastX(e.clientX)
    e.currentTarget.setPointerCapture(e.pointerId)
  }, [])

  const onPointerMove = useCallback((e) => {
    if (!dragging) return
    const dx = e.clientX - lastX
    setRotY(r => r + dx * 0.01)
    setLastX(e.clientX)
  }, [dragging, lastX])

  const onPointerUp = useCallback(() => setDragging(false), [])

  return (
    <div
      className={className}
      style={{
        display: 'flex',
        flexDirection: 'column',
        background: '#0d1822',
        borderRadius: 8,
        overflow: 'hidden',
        fontFamily: 'sans-serif',
        width: width,
        userSelect: 'none',
      }}
    >
      {/* Header */}
      <div style={{
        padding: '6px 14px',
        background: '#131f2b',
        borderBottom: '1px solid #1e3040',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        flexWrap: 'wrap',
      }}>
        <span style={{ color: '#5ba0c8', fontWeight: 700, fontSize: 13 }}>
          Point Cloud Viewer
        </span>
        {hasDevs && (
          <span style={{
            background: '#1e3a50', color: '#7ec8e8',
            padding: '1px 7px', borderRadius: 10, fontSize: 10,
          }}>
            Deviation Heatmap
          </span>
        )}
        {planeResult?.success && (
          <span style={{
            background: '#2e2a10', color: '#f0c040',
            padding: '1px 7px', borderRadius: 10, fontSize: 10,
          }}>
            Plane Fit
          </span>
        )}
        {hasPipes && (
          <span style={{
            background: '#1a3820', color: '#60e090',
            padding: '1px 7px', borderRadius: 10, fontSize: 10,
          }}>
            {pipeSegments.length} Pipe{pipeSegments.length !== 1 ? 's' : ''} Detected
          </span>
        )}
        {asbuiltOverlay?.n_matched > 0 && (
          <span style={{
            background: '#2a1a30', color: '#c080e0',
            padding: '1px 7px', borderRadius: 10, fontSize: 10,
          }}>
            As-Built Overlay
          </span>
        )}
      </div>

      {/* Body */}
      <div style={{ display: 'flex', flex: 1 }}>
        {/* Canvas viewport */}
        <canvas
          ref={canvasRef}
          width={canvasW}
          height={height - 20}
          style={{ cursor: dragging ? 'grabbing' : 'grab', display: 'block' }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerUp}
        />

        {/* Stats sidebar */}
        <StatsPanel
          stats={stats}
          aabb={aabb}
          planeResult={planeResult}
          deviations={deviations}
          tolerance_m={tolerance_m}
          pipeSegments={pipeSegments}
          pipeRuns={pipeRuns}
        />
      </div>

      {/* Colour bar */}
      {hasDevs
        ? <DeviationColorBar devRange={devRange} tolerance_m={tolerance_m} />
        : pts.length > 0
          ? <ElevColorBar zMin={zMin} zMax={zMax} />
          : null
      }

      {/* As-built / design deviation table */}
      <AsbuiltDeviationTable overlay={asbuiltOverlay} />

      {/* AI dispatch button */}
      {onDispatch && (
        <div style={{ padding: '6px 12px', background: '#131f2b', borderTop: '1px solid #1e3040', display: 'flex', gap: 8 }}>
          <button
            onClick={() => onDispatch({
              tool: 'pointcloud_import',
              params: { format: 'xyz', data: '', voxel_cell_size: 0.1, max_return_pts: 5000 }
            })}
            style={{
              background: '#1a4060', color: '#8ecde8', border: '1px solid #2a6080',
              padding: '3px 10px', borderRadius: 4, cursor: 'pointer', fontSize: 11,
            }}
          >
            Import scan…
          </button>
          <button
            onClick={() => onDispatch({
              tool: 'pointcloud_detect_pipes',
              params: { points: points ?? [], threshold_m: 0.02, min_inliers: 20, max_pipes: 20 }
            })}
            style={{
              background: '#1a3820', color: '#60e090', border: '1px solid #2a5830',
              padding: '3px 10px', borderRadius: 4, cursor: 'pointer', fontSize: 11,
            }}
          >
            Detect pipes…
          </button>
        </div>
      )}
    </div>
  )
}
