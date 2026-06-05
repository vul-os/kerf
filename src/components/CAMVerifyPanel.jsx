/**
 * CAMVerifyPanel — Toolpath material-removal verification panel.
 *
 * Calls the `cam_verify_material_removal` LLM tool via the REST API and
 * renders:
 *   - Removed volume / % stock cleared
 *   - Gouge detection results (count + severity)
 *   - A Z-slice heatmap of the dexel grid (SVG)
 *   - Gouge markers in the slice view
 *
 * Method: Van Hook (1986) dexel/Z-map simulation.
 *
 * Props:
 *   projectId  — current project UUID
 *   fileId     — .cam file UUID (used for result association, not required)
 *   clPoints   — [{x,y,z}, ...] cutter location points (optional)
 *   gcode      — G-code string (optional; used if clPoints not provided)
 *   stockBounds — {x_min, x_max, y_min, y_max, stock_top, stock_bottom}
 *   toolDiameter — mm (default 6)
 *   toolKind   — "flat" | "ball" | "bull" (default "flat")
 *   partSurfaceZ — constant Z level of finished part surface for gouge check
 */

import { useState } from 'react'
import { AlertTriangle, CheckCircle, Loader2, Activity, ZoomIn } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

function depthToColor(depth, maxDepth) {
  if (maxDepth < 1e-9) return '#4ade80'
  const t = Math.min(1.0, depth / maxDepth)
  // Green → yellow → red
  if (t < 0.5) {
    const u = t * 2
    return `rgb(${Math.round(u * 250)},${Math.round(220)},0)`
  }
  const u = (t - 0.5) * 2
  return `rgb(250,${Math.round(220 * (1 - u))},0)`
}

// ---------------------------------------------------------------------------
// Z-slice heatmap
// ---------------------------------------------------------------------------

function DexelHeatmap({ gougePoints, stockBounds, resolution }) {
  if (!stockBounds) return null
  const { x_min = 0, x_max = 100, y_min = 0, y_max = 100 } = stockBounds

  const W = x_max - x_min
  const H = y_max - y_min
  if (W <= 0 || H <= 0) return null

  const maxDepth = gougePoints.length > 0
    ? Math.max(...gougePoints.map(g => g.depth))
    : 0

  const svgW = 220
  const svgH = 220 * (H / W)

  const cellPx = resolution ? (svgW / W) * resolution : 3

  return (
    <svg
      width={svgW}
      height={svgH}
      viewBox={`0 0 ${svgW} ${svgH}`}
      style={{ background: '#0d1117', border: '1px solid #1f2937', borderRadius: 4 }}
      role="img"
      aria-label="Dexel slice view — gouge map"
    >
      {/* Background: cleared region indicator */}
      <rect x={0} y={0} width={svgW} height={svgH} fill="#0d2a1a" />
      <text x={4} y={12} fontSize={8} fill="#374151">Z-map gouge view</text>

      {/* Gouge markers */}
      {gougePoints.map((g, i) => {
        const px = ((g.x - x_min) / W) * svgW
        const py = (1 - (g.y - y_min) / H) * svgH
        const c = depthToColor(g.depth, maxDepth)
        return (
          <rect
            key={i}
            x={px - cellPx / 2}
            y={py - cellPx / 2}
            width={cellPx}
            height={cellPx}
            fill={c}
            opacity={0.85}
          >
            <title>{`Gouge at (${g.x.toFixed(2)}, ${g.y.toFixed(2)}): ${g.depth.toFixed(3)}mm deep`}</title>
          </rect>
        )
      })}

      {/* Axes */}
      <line x1={0} y1={svgH - 10} x2={svgW} y2={svgH - 10} stroke="#1f2937" strokeWidth={0.5} />
      <text x={2} y={svgH - 2} fontSize={6} fill="#4b5563">X: {x_min}</text>
      <text x={svgW - 20} y={svgH - 2} fontSize={6} fill="#4b5563">{x_max}</text>

      {/* Legend */}
      {maxDepth > 0 && (
        <>
          <defs>
            <linearGradient id="gouge-legend" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#4ade80" />
              <stop offset="50%" stopColor="#facc15" />
              <stop offset="100%" stopColor="#ef4444" />
            </linearGradient>
          </defs>
          <rect x={svgW - 40} y={4} width={36} height={5} fill="url(#gouge-legend)" rx={2} />
          <text x={svgW - 40} y={14} fontSize={6} fill="#6b7280">0</text>
          <text x={svgW - 18} y={14} fontSize={6} fill="#6b7280">{maxDepth.toFixed(1)}mm</text>
        </>
      )}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function CAMVerifyPanel({
  projectId,
  fileId,
  clPoints,
  gcode,
  stockBounds,
  toolDiameter = 6,
  toolKind = 'flat',
  partSurfaceZ,
  resolutionMm = 0.5,
}) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function handleRun() {
    if (!clPoints && !gcode) {
      setError('Provide cl_points or gcode to simulate')
      return
    }
    if (!stockBounds) {
      setError('stock_bounds required')
      return
    }
    setError(null)
    setRunning(true)
    setResult(null)

    try {
      const body = {
        stock_bounds: stockBounds,
        tool_diameter_mm: toolDiameter,
        tool_kind: toolKind,
        resolution_mm: resolutionMm,
      }
      if (clPoints) body.cl_points = clPoints
      if (gcode) body.gcode = gcode
      if (partSurfaceZ != null) body.part_surface_z_flat = partSurfaceZ

      // The verify tool runs synchronously in the API worker.
      const res = await fetch(`${API_URL}/api/cam/verify-material-removal`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const txt = await res.text()
        throw new Error(`${res.status}: ${txt}`)
      }
      const data = await res.json()
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const gougeCount = result?.gouge_points?.length ?? 0
  const hasGouges = gougeCount > 0

  return (
    <div data-testid="cam-verify-panel" style={styles.root}>
      <div style={styles.header}>
        <Activity size={14} style={{ color: '#60a5fa' }} />
        <span style={styles.title}>Material Removal Verify</span>
        <span style={styles.methodTag}>Van Hook 1986 dexel/Z-map</span>
      </div>

      <div style={styles.infoRow}>
        <span style={styles.dimLabel}>Tool</span>
        <span style={styles.dimVal}>{toolDiameter}mm {toolKind}</span>
        <span style={styles.dimLabel}>Grid</span>
        <span style={styles.dimVal}>{resolutionMm}mm/cell</span>
      </div>

      <button
        type="button"
        onClick={handleRun}
        disabled={running}
        style={{ ...styles.btn, ...(running ? styles.btnDisabled : {}) }}
        aria-label="Run material removal simulation"
      >
        {running
          ? <><Loader2 size={12} style={styles.spin} /> Simulating…</>
          : <><ZoomIn size={12} /> Run Simulation</>}
      </button>

      {error && (
        <div style={styles.errorBox} role="alert">
          <AlertTriangle size={12} />
          <span style={{ marginLeft: 6 }}>{error}</span>
        </div>
      )}

      {result && (
        <div style={styles.section}>
          {/* Summary stats */}
          <div style={styles.statsGrid}>
            <StatCell label="Removed" value={`${result.removed_volume_mm3?.toFixed(1)} mm³`} />
            <StatCell label="Cleared" value={`${result.percent_cleared?.toFixed(1)}%`} accent="#34d399" />
            <StatCell label="Remaining" value={`${result.remaining_stock_mm3?.toFixed(1)} mm³`} />
            <StatCell label="Moves" value={result.n_moves} />
          </div>

          {/* Gouge summary */}
          <div style={{ ...styles.badge, ...(hasGouges ? styles.badgeWarn : styles.badgeOk) }}>
            {hasGouges
              ? <><AlertTriangle size={11} style={{ marginRight: 5 }} />
                  {gougeCount} gouge{gougeCount !== 1 ? 's' : ''} detected
                  {result.gouge_points[0] ? ` — worst: ${result.gouge_points[0].depth.toFixed(3)}mm` : ''}</>
              : <><CheckCircle size={11} style={{ marginRight: 5 }} /> No gouges</>}
          </div>

          {/* Heatmap */}
          <DexelHeatmap
            gougePoints={result.gouge_points || []}
            stockBounds={stockBounds}
            resolution={resolutionMm}
          />

          {/* Top gouges table */}
          {hasGouges && (
            <div style={styles.gougeTable}>
              <div style={styles.sectionLabel}>Top gouges</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr>
                    {['X', 'Y', 'Z part', 'Z actual', 'Depth'].map(h => (
                      <th key={h} style={styles.th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.gouge_points.slice(0, 8).map((g, i) => (
                    <tr key={i}>
                      <td style={styles.td}>{g.x.toFixed(2)}</td>
                      <td style={styles.td}>{g.y.toFixed(2)}</td>
                      <td style={styles.td}>{g.z_part.toFixed(3)}</td>
                      <td style={styles.td}>{g.z_actual.toFixed(3)}</td>
                      <td style={{ ...styles.td, color: '#f87171', fontWeight: 600 }}>
                        {g.depth.toFixed(3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StatCell({ label, value, accent = '#a78bfa' }) {
  return (
    <div style={styles.statCell}>
      <span style={{ color: '#6b7280', fontSize: 10 }}>{label}</span>
      <span style={{ color: accent, fontWeight: 600, fontFamily: 'ui-monospace,monospace' }}>
        {value}
      </span>
    </div>
  )
}

const styles = {
  root: {
    fontFamily: 'ui-monospace,SFMono-Regular,Menlo,monospace',
    fontSize: 12,
    color: '#e5e7eb',
    background: '#111827',
    borderRadius: 6,
    padding: 14,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  header: { display: 'flex', alignItems: 'center', gap: 8, borderBottom: '1px solid #1f2937', paddingBottom: 8 },
  title: { fontWeight: 700, fontSize: 13, color: '#f3f4f6' },
  methodTag: { marginLeft: 'auto', fontSize: 10, color: '#4b5563', fontStyle: 'italic' },
  infoRow: { display: 'flex', gap: 12, alignItems: 'center' },
  dimLabel: { color: '#6b7280', fontSize: 11 },
  dimVal: { color: '#d1d5db', fontSize: 11, fontWeight: 600 },
  btn: {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '6px 14px', background: '#1e3a5f',
    border: 'none', borderRadius: 5, color: '#93c5fd',
    fontSize: 12, fontWeight: 600, cursor: 'pointer', width: 'fit-content',
  },
  btnDisabled: { opacity: 0.5, cursor: 'not-allowed' },
  section: { display: 'flex', flexDirection: 'column', gap: 8 },
  statsGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 6 },
  statCell: { display: 'flex', flexDirection: 'column', gap: 2, background: '#1f2937', borderRadius: 4, padding: '5px 8px' },
  badge: { display: 'flex', alignItems: 'center', borderRadius: 4, padding: '5px 10px', fontSize: 11, fontWeight: 600 },
  badgeOk: { background: '#052e16', color: '#34d399', border: '1px solid #065f46' },
  badgeWarn: { background: '#2c1006', color: '#f97316', border: '1px solid #7c2d12' },
  gougeTable: { display: 'flex', flexDirection: 'column', gap: 4 },
  sectionLabel: { fontSize: 11, color: '#6b7280', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' },
  th: { textAlign: 'left', padding: '3px 6px', color: '#6b7280', borderBottom: '1px solid #1f2937' },
  td: { padding: '2px 6px', color: '#d1d5db', borderBottom: '1px solid #1f2937' },
  errorBox: { display: 'flex', alignItems: 'center', background: '#1f0707', border: '1px solid #7f1d1d', borderRadius: 4, padding: '6px 10px', color: '#fca5a5', fontSize: 11 },
  spin: { animation: 'spin 1s linear infinite' },
}
