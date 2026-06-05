/**
 * CAMMachineSimPanel — Machine simulation / collision-detection panel.
 *
 * Calls the `cam_machine_collision_check` LLM tool via the REST API and
 * renders:
 *   - Collision count / max overlap
 *   - Component-pair breakdown (which bodies collide)
 *   - A 2-D schematic showing tool-holder + table footprint + collision marker
 *   - Timeline of collision events
 *
 * Machine model: AABB kinematic simulation (spindle/holder/tool vs table/stock).
 * Kinematics: head-table A-around-X + B-around-Y (same convention as
 * kerf_cam.five_axis.gcode_constant_tilt).
 *
 * Props:
 *   toolpathPoints  — [{x, y, z, a_deg?, b_deg?}, ...] joint-space points
 *   toolDiameter    — mm (default 12)
 *   toolLength      — mm (default 80)
 *   holderDiameter  — mm (default 32)
 *   holderLength    — mm (default 50)
 *   stockBounds     — {x_min, x_max, y_min, y_max, z_min, z_max}
 *   tablePivotZ     — mm (default 0)
 */

import { useState } from 'react'
import { AlertTriangle, CheckCircle, Loader2, Cpu } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Side-view schematic (XZ plane projection)
// ---------------------------------------------------------------------------

function MachineSchematic({ points, holderLength = 50, toolLength = 80, holderDia = 32, toolDia = 12, collisions }) {
  const W = 220
  const H = 180
  const originX = W / 2
  const originZ = H * 0.6   // Z=0 is at 60% from top

  const scale = 0.6   // px per mm

  function px(x) { return originX + x * scale }
  function pz(z) { return originZ - z * scale }

  // Sample a few toolpath points to show tool travel
  const samplePts = points && points.length > 0
    ? points.filter((_, i) => i % Math.max(1, Math.floor(points.length / 20)) === 0).slice(0, 20)
    : []

  // Find collision point indices
  const collisionIndices = new Set((collisions || []).map(c => c.point_index))

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      style={{ background: '#0d1117', border: '1px solid #1f2937', borderRadius: 4 }}
      role="img"
      aria-label="Machine schematic XZ view"
      data-testid="machine-schematic"
    >
      {/* Table */}
      <rect
        x={px(-150)} y={pz(0)}
        width={Math.abs(px(150) - px(-150))} height={20 * scale}
        fill="#1e3a5f" stroke="#2563eb" strokeWidth={0.5}
      />
      <text x={px(0)} y={pz(-5)} textAnchor="middle" fontSize={7} fill="#3b82f6">TABLE</text>

      {/* Toolpath trace */}
      {samplePts.length > 1 && samplePts.map((pt, i) => {
        if (i === 0) return null
        const prev = samplePts[i - 1]
        return (
          <line
            key={i}
            x1={px(prev.x || 0)} y1={pz(prev.z || 0)}
            x2={px(pt.x || 0)} y2={pz(pt.z || 0)}
            stroke="#4b5563" strokeWidth={0.5}
          />
        )
      })}

      {/* Tool at first collision (or at last point) */}
      {samplePts.map((pt, i) => {
        const isCollision = collisionIndices.has(i)
        const cx = px(pt.x || 0)
        const cz = pz(pt.z || 0)
        const color = isCollision ? '#ef4444' : '#6b7280'
        return (
          <circle key={i} cx={cx} cy={cz} r={2} fill={color} opacity={0.7}>
            {isCollision && <title>Collision at point {i}</title>}
          </circle>
        )
      })}

      {/* Tool body (at first sampled point) */}
      {samplePts.length > 0 && (() => {
        const pt = samplePts[Math.floor(samplePts.length / 2)]
        const cx = px(pt.x || 0)
        const cz = pz(pt.z || 0)
        const toolR = (toolDia / 2) * scale
        const holR = (holderDia / 2) * scale
        const toolH = toolLength * scale
        const holH = holderLength * scale
        return (
          <>
            {/* Tool holder */}
            <rect x={cx - holR} y={cz - holH} width={holR * 2} height={holH}
              fill="#374151" stroke="#4b5563" strokeWidth={0.5} opacity={0.9} />
            {/* Tool */}
            <rect x={cx - toolR} y={cz} width={toolR * 2} height={toolH}
              fill="#1d4ed8" stroke="#3b82f6" strokeWidth={0.5} opacity={0.9} />
          </>
        )
      })()}

      {/* Axis labels */}
      <text x={W - 12} y={pz(0) - 2} fontSize={7} fill="#4b5563">Z=0</text>
      <text x={4} y={12} fontSize={7} fill="#4b5563">XZ view</text>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function CAMMachineSimPanel({
  toolpathPoints,
  toolDiameter = 12,
  toolLength = 80,
  holderDiameter = 32,
  holderLength = 50,
  stockBounds,
  tablePivotZ = 0,
}) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function handleRun() {
    if (!toolpathPoints || toolpathPoints.length === 0) {
      setError('Provide toolpath_points to check')
      return
    }
    setError(null)
    setRunning(true)
    setResult(null)

    try {
      const body = {
        toolpath_points: toolpathPoints,
        tool_diameter_mm: toolDiameter,
        tool_length_mm: toolLength,
        holder_diameter_mm: holderDiameter,
        holder_length_mm: holderLength,
        table_pivot_z: tablePivotZ,
      }
      if (stockBounds) body.stock_bounds = stockBounds

      const res = await fetch(`${API_URL}/api/cam/machine-collision-check`, {
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

  const nCollisions = result?.n_collisions ?? 0
  const hasCollisions = nCollisions > 0

  // Collision pair breakdown: count per (componentA, componentB) pair
  const pairCounts = {}
  if (result?.collisions) {
    for (const c of result.collisions) {
      const key = `${c.component_a} ↔ ${c.component_b}`
      pairCounts[key] = (pairCounts[key] || 0) + 1
    }
  }

  return (
    <div data-testid="cam-machine-sim-panel" style={styles.root}>
      <div style={styles.header}>
        <Cpu size={14} style={{ color: '#a78bfa' }} />
        <span style={styles.title}>Machine Collision Check</span>
        <span style={styles.methodTag}>AABB kinematic sim</span>
      </div>

      <div style={styles.infoRow}>
        <span style={styles.dimLabel}>Tool ⌀</span>
        <span style={styles.dimVal}>{toolDiameter}mm</span>
        <span style={styles.dimLabel}>Holder ⌀</span>
        <span style={styles.dimVal}>{holderDiameter}mm</span>
        <span style={styles.dimLabel}>Points</span>
        <span style={styles.dimVal}>{toolpathPoints?.length ?? 0}</span>
      </div>

      <button
        type="button"
        onClick={handleRun}
        disabled={running}
        style={{ ...styles.btn, ...(running ? styles.btnDisabled : {}) }}
        aria-label="Run machine collision check"
      >
        {running
          ? <><Loader2 size={12} style={styles.spin} /> Checking…</>
          : <><Cpu size={12} /> Check Collisions</>}
      </button>

      {error && (
        <div style={styles.errorBox} role="alert">
          <AlertTriangle size={12} />
          <span style={{ marginLeft: 6 }}>{error}</span>
        </div>
      )}

      {/* Schematic always shown (shows current toolpath geometry) */}
      <MachineSchematic
        points={toolpathPoints}
        holderLength={holderLength}
        toolLength={toolLength}
        holderDia={holderDiameter}
        toolDia={toolDiameter}
        collisions={result?.collisions}
      />

      {result && (
        <div style={styles.section}>
          {/* Summary badge */}
          <div style={{ ...styles.badge, ...(hasCollisions ? styles.badgeWarn : styles.badgeOk) }}>
            {hasCollisions
              ? <>
                  <AlertTriangle size={11} style={{ marginRight: 5 }} />
                  {nCollisions} collision event{nCollisions !== 1 ? 's' : ''}
                  {result.max_overlap_mm > 0 ? ` — max overlap ${result.max_overlap_mm.toFixed(2)}mm` : ''}
                </>
              : <><CheckCircle size={11} style={{ marginRight: 5 }} /> No collisions</>}
          </div>

          {/* Stats row */}
          <div style={styles.statsGrid}>
            <StatCell label="Checked" value={result.n_points_checked} />
            <StatCell label="Collisions" value={nCollisions} accent={hasCollisions ? '#f87171' : '#34d399'} />
            <StatCell label="Max overlap" value={`${result.max_overlap_mm.toFixed(2)}mm`} accent={hasCollisions ? '#f97316' : '#a78bfa'} />
          </div>

          {/* Pair breakdown */}
          {hasCollisions && Object.keys(pairCounts).length > 0 && (
            <div style={styles.pairTable}>
              <div style={styles.sectionLabel}>Collision pairs</div>
              {Object.entries(pairCounts).map(([pair, count]) => (
                <div key={pair} style={styles.pairRow}>
                  <span style={{ color: '#f97316' }}>{pair}</span>
                  <span style={{ color: '#9ca3af', marginLeft: 'auto' }}>{count}×</span>
                </div>
              ))}
            </div>
          )}

          {/* First collision detail */}
          {result.first_collision && (
            <div style={styles.firstCollision}>
              <span style={{ color: '#6b7280', fontSize: 10 }}>FIRST COLLISION</span>
              <div style={styles.collisionDetail}>
                <span>Point #{result.first_collision.point_index}</span>
                <span>X={result.first_collision.x.toFixed(2)}</span>
                <span>Y={result.first_collision.y.toFixed(2)}</span>
                <span>Z={result.first_collision.z.toFixed(2)}</span>
                {result.first_collision.a_deg !== 0 && (
                  <span>A={result.first_collision.a_deg.toFixed(1)}°</span>
                )}
                {result.first_collision.b_deg !== 0 && (
                  <span>B={result.first_collision.b_deg.toFixed(1)}°</span>
                )}
              </div>
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
  infoRow: { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' },
  dimLabel: { color: '#6b7280', fontSize: 11 },
  dimVal: { color: '#d1d5db', fontSize: 11, fontWeight: 600 },
  btn: {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '6px 14px', background: '#3b0764',
    border: 'none', borderRadius: 5, color: '#c4b5fd',
    fontSize: 12, fontWeight: 600, cursor: 'pointer', width: 'fit-content',
  },
  btnDisabled: { opacity: 0.5, cursor: 'not-allowed' },
  section: { display: 'flex', flexDirection: 'column', gap: 8 },
  statsGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 },
  statCell: { display: 'flex', flexDirection: 'column', gap: 2, background: '#1f2937', borderRadius: 4, padding: '5px 8px' },
  badge: { display: 'flex', alignItems: 'center', borderRadius: 4, padding: '5px 10px', fontSize: 11, fontWeight: 600 },
  badgeOk: { background: '#052e16', color: '#34d399', border: '1px solid #065f46' },
  badgeWarn: { background: '#2c0606', color: '#ef4444', border: '1px solid #7f1d1d' },
  pairTable: { display: 'flex', flexDirection: 'column', gap: 3 },
  pairRow: { display: 'flex', alignItems: 'center', padding: '3px 6px', background: '#1f2937', borderRadius: 3 },
  sectionLabel: { fontSize: 10, color: '#6b7280', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' },
  firstCollision: { display: 'flex', flexDirection: 'column', gap: 4, background: '#1a0a0a', border: '1px solid #7f1d1d', borderRadius: 4, padding: '6px 10px' },
  collisionDetail: { display: 'flex', gap: 12, flexWrap: 'wrap', color: '#fca5a5', fontSize: 11 },
  errorBox: { display: 'flex', alignItems: 'center', background: '#1f0707', border: '1px solid #7f1d1d', borderRadius: 4, padding: '6px 10px', color: '#fca5a5', fontSize: 11 },
  spin: { animation: 'spin 1s linear infinite' },
}
