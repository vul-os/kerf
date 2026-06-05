/**
 * OrbitDeterminationPanel.jsx — Orbit determination results panel.
 *
 * Displays results from both batch least-squares (BLS) and Extended Kalman
 * Filter (EKF) orbit determination, including:
 *   - Estimated state vector (position + velocity at epoch)
 *   - Formal covariance diagonal (position/velocity uncertainties)
 *   - Post-fit residual / innovation statistics (sigma_0, RMS)
 *   - Convergence status and iteration count
 *   - EKF innovation time series sparkline
 *
 * Props
 * ─────
 * mode         {'batch'|'ekf'|'both'}  Which estimator results to show.  Default 'both'.
 * batchResult  {object|null}   Result from POST /api/llm-tools/aero_orbit_determination.
 * ekfResult    {object|null}   Result from POST /api/llm-tools/aero_ekf_orbit_determination.
 * onRunBatch   {Function}      Called when user clicks "Run Batch LS" (no args).
 * onRunEkf     {Function}      Called when user clicks "Run EKF" (no args).
 * loading      {boolean}       Show loading overlay while running.
 *
 * Wire-up: parent posts to /api/llm-tools with tool_name = 'aero_orbit_determination'
 * or 'aero_ekf_orbit_determination' and passes the response object as batchResult/ekfResult.
 *
 * Usage
 * ─────
 * <OrbitDeterminationPanel
 *   mode="both"
 *   batchResult={batchRes}
 *   ekfResult={ekfRes}
 *   onRunBatch={handleBatch}
 *   onRunEkf={handleEkf}
 *   loading={isRunning}
 * />
 */

import { useState, useMemo } from 'react'

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Single row in a state-vector table. */
function StateRow({ label, value, unit, sigma }) {
  const sigStr = sigma != null ? ` ± ${sigma.toFixed(4)}` : ''
  return (
    <tr className="od-state-row">
      <td className="od-td-label">{label}</td>
      <td className="od-td-value">
        {typeof value === 'number' ? value.toFixed(6) : '—'}
        <span className="od-unit">{unit}</span>
        {sigma != null && <span className="od-sigma">{sigStr}</span>}
      </td>
    </tr>
  )
}

/** Convergence / health badge. */
function StatusBadge({ ok, label }) {
  const color = ok ? '#22c55e' : '#ef4444'
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 10px',
        borderRadius: 9999,
        background: color,
        color: '#fff',
        fontSize: 11,
        fontWeight: 700,
        marginLeft: 6,
      }}
    >
      {label}
    </span>
  )
}

/** Mini sparkline — SVG polyline of normalised values. */
function Sparkline({ values, width = 200, height = 36, color = '#60a5fa' }) {
  if (!values || values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width
    const y = height - ((v - min) / range) * (height - 4) - 2
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
      {/* zero line if range spans zero */}
      {min < 0 && max > 0 && (() => {
        const y0 = height - ((0 - min) / range) * (height - 4) - 2
        return <line x1={0} y1={y0.toFixed(1)} x2={width} y2={y0.toFixed(1)}
                     stroke="#ffffff30" strokeDasharray="3 2" strokeWidth={0.8} />
      })()}
    </svg>
  )
}

/** State vector table for either batch or EKF result. */
function StateTable({ result, title, color }) {
  if (!result || !result.ok) return null

  const x = result.x_estimated ?? result.state_final
  if (!x || x.length !== 6) return null

  const labels = ['r_x', 'r_y', 'r_z', 'v_x', 'v_y', 'v_z']
  const units  = ['km', 'km', 'km', 'km/s', 'km/s', 'km/s']
  const covDiag = result.covariance_diag ?? null
  const sigmas = covDiag
    ? covDiag.map(v => v >= 0 ? Math.sqrt(v) : null)
    : null

  return (
    <div className="od-state-table-wrap" style={{ borderLeft: `3px solid ${color}`, paddingLeft: 10 }}>
      <div className="od-table-title" style={{ color, fontWeight: 700, marginBottom: 4 }}>
        {title}
      </div>
      <table className="od-state-table">
        <tbody>
          {x.map((v, i) => (
            <StateRow
              key={labels[i]}
              label={labels[i]}
              value={v}
              unit={units[i]}
              sigma={sigmas?.[i]}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Statistics row for one estimator. */
function StatsBlock({ result, title }) {
  if (!result || !result.ok) return null

  const rms = result.rms_residual ?? result.rms_innovation
  const sigma0 = result.sigma_0 ?? null
  const nObs = result.n_observations
  const nIter = result.n_iter ?? null
  const converged = result.converged ?? null

  return (
    <div className="od-stats-block">
      <div className="od-stats-title">{title}</div>
      <div className="od-stats-grid">
        {nObs != null && (
          <div className="od-stat">
            <span className="od-stat-label">Observations</span>
            <span className="od-stat-value">{nObs}</span>
          </div>
        )}
        {rms != null && (
          <div className="od-stat">
            <span className="od-stat-label">RMS residual</span>
            <span className="od-stat-value">{Number(rms).toFixed(4)}</span>
          </div>
        )}
        {sigma0 != null && (
          <div className="od-stat">
            <span className="od-stat-label">σ₀</span>
            <span className="od-stat-value">{Number(sigma0).toFixed(4)}</span>
          </div>
        )}
        {nIter != null && (
          <div className="od-stat">
            <span className="od-stat-label">Iterations</span>
            <span className="od-stat-value">{nIter}</span>
          </div>
        )}
        {converged != null && (
          <div className="od-stat">
            <span className="od-stat-label">Converged</span>
            <StatusBadge ok={converged} label={converged ? 'YES' : 'NO'} />
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Default fixture data (demonstration mode when no results provided)
// ---------------------------------------------------------------------------

const DEMO_BATCH = {
  ok: true,
  converged: true,
  n_iter: 5,
  x_estimated: [5678.123, 2345.456, 1234.789, -1.234, 6.789, 3.012],
  rms_residual: 0.9821,
  sigma_0: 0.9934,
  n_observations: 40,
  covariance_trace: 0.00042,
  warnings: [],
}

const DEMO_EKF = {
  ok: true,
  state_final: [5673.445, 2350.102, 1237.334, -1.229, 6.792, 3.015],
  covariance_diag: [4.1e-5, 3.8e-5, 5.2e-5, 1.2e-9, 1.1e-9, 9.8e-10],
  rms_innovation: 1.043,
  n_observations: 40,
  position_norm_km: 6278.34,
  state_history_sample: [
    [5700, 2300, 1200, -1.20, 6.80, 3.00],
    [5695, 2310, 1210, -1.21, 6.79, 3.01],
    [5690, 2320, 1220, -1.22, 6.79, 3.01],
    [5685, 2330, 1230, -1.23, 6.79, 3.01],
    [5680, 2340, 1235, -1.23, 6.79, 3.01],
  ],
  warnings: [],
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function OrbitDeterminationPanel({
  mode = 'both',
  batchResult = null,
  ekfResult = null,
  onRunBatch = null,
  onRunEkf = null,
  loading = false,
}) {
  const [showDemo, setShowDemo] = useState(false)

  const batch = batchResult ?? (showDemo ? DEMO_BATCH : null)
  const ekf   = ekfResult   ?? (showDemo ? DEMO_EKF   : null)

  // Innovation time series for EKF sparkline
  const innovSeries = useMemo(() => {
    if (!ekf?.state_history_sample) return []
    return ekf.state_history_sample.map(s =>
      Math.sqrt(s[0] ** 2 + s[1] ** 2 + s[2] ** 2)
    )
  }, [ekf])

  const showBatch = mode === 'batch' || mode === 'both'
  const showEkf   = mode === 'ekf'   || mode === 'both'

  return (
    <div className="od-panel">
      <style>{OD_STYLES}</style>

      {/* Header */}
      <div className="od-header">
        <span className="od-title">Orbit Determination</span>
        <span className="od-subtitle">Batch LS + EKF</span>
        {(batch?.ok || ekf?.ok) && (
          <StatusBadge ok={true} label="RESULT" />
        )}
      </div>

      {/* Action buttons */}
      <div className="od-actions">
        {showBatch && onRunBatch && (
          <button
            className="od-btn od-btn-batch"
            onClick={onRunBatch}
            disabled={loading}
          >
            Run Batch LS
          </button>
        )}
        {showEkf && onRunEkf && (
          <button
            className="od-btn od-btn-ekf"
            onClick={onRunEkf}
            disabled={loading}
          >
            Run EKF
          </button>
        )}
        <button
          className="od-btn od-btn-demo"
          onClick={() => setShowDemo(d => !d)}
        >
          {showDemo ? 'Hide Demo' : 'Demo'}
        </button>
      </div>

      {loading && (
        <div className="od-loading">
          <span className="od-spinner" />
          Running estimator…
        </div>
      )}

      {/* Results */}
      {!loading && (batch?.ok || ekf?.ok) && (
        <div className="od-results">
          {/* State vector tables side by side */}
          <div className="od-state-tables">
            {showBatch && batch?.ok && (
              <StateTable
                result={batch}
                title="Batch Least-Squares"
                color="#60a5fa"
              />
            )}
            {showEkf && ekf?.ok && (
              <StateTable
                result={ekf}
                title="Extended Kalman Filter"
                color="#a78bfa"
              />
            )}
          </div>

          {/* Statistics */}
          <div className="od-stats-row">
            {showBatch && batch?.ok && (
              <StatsBlock result={batch} title="Batch LS Statistics" />
            )}
            {showEkf && ekf?.ok && (
              <StatsBlock result={ekf} title="EKF Statistics" />
            )}
          </div>

          {/* EKF position history sparkline */}
          {showEkf && ekf?.ok && innovSeries.length > 1 && (
            <div className="od-sparkline-wrap">
              <div className="od-sparkline-label">
                EKF position norm ‖r‖ over arc [km]
              </div>
              <Sparkline values={innovSeries} color="#a78bfa" />
            </div>
          )}

          {/* Warnings */}
          {[...(batch?.warnings ?? []), ...(ekf?.warnings ?? [])].map((w, i) => (
            <div key={i} className="od-warning">⚠ {w}</div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && !batch?.ok && !ekf?.ok && !showDemo && (
        <div className="od-empty">
          <div className="od-empty-icon">🛰</div>
          <div className="od-empty-text">
            No orbit determination results yet.
          </div>
          <div className="od-empty-sub">
            Provide tracking observations and run Batch LS or EKF.
          </div>
        </div>
      )}

      {/* Method footnote */}
      <div className="od-footnote">
        Batch LS: Tapley, Schutz & Born (2004) §4.3 · EKF: TSB §4.7 · Joseph-form P update (Bierman 1977 §IV.6)
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles (scoped via class prefix od-)
// ---------------------------------------------------------------------------

const OD_STYLES = `
.od-panel {
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 10px;
  padding: 18px 20px 14px;
  font-family: 'Inter', 'SF Pro Display', system-ui, sans-serif;
  color: #e2e8f0;
  min-width: 420px;
  max-width: 800px;
  box-sizing: border-box;
  position: relative;
}
.od-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.od-title {
  font-size: 16px;
  font-weight: 700;
  color: #f1f5f9;
}
.od-subtitle {
  font-size: 11px;
  color: #64748b;
  background: #1e293b;
  padding: 2px 7px;
  border-radius: 4px;
}
.od-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.od-btn {
  border: none;
  border-radius: 6px;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}
.od-btn:disabled { opacity: 0.5; cursor: default; }
.od-btn-batch { background: #1d4ed8; color: #fff; }
.od-btn-ekf   { background: #6d28d9; color: #fff; }
.od-btn-demo  { background: #334155; color: #94a3b8; }
.od-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #94a3b8;
  font-size: 13px;
  padding: 10px 0;
}
.od-spinner {
  width: 14px; height: 14px;
  border: 2px solid #334155;
  border-top-color: #60a5fa;
  border-radius: 50%;
  animation: od-spin 0.8s linear infinite;
  display: inline-block;
}
@keyframes od-spin { to { transform: rotate(360deg); } }
.od-results {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.od-state-tables {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.od-state-table-wrap { min-width: 200px; }
.od-table-title { font-size: 12px; margin-bottom: 4px; }
.od-state-table {
  border-collapse: collapse;
  font-size: 11px;
  width: 100%;
}
.od-state-row:hover { background: #1e293b20; }
.od-td-label {
  color: #94a3b8;
  padding: 2px 8px 2px 0;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  width: 40px;
}
.od-td-value {
  color: #f1f5f9;
  padding: 2px 0;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}
.od-unit {
  color: #64748b;
  font-size: 9px;
  margin-left: 3px;
}
.od-sigma {
  color: #94a3b8;
  font-size: 10px;
  margin-left: 2px;
}
.od-stats-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.od-stats-block {
  background: #1e293b;
  border-radius: 7px;
  padding: 10px 14px;
  min-width: 180px;
}
.od-stats-title {
  font-size: 11px;
  color: #64748b;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.od-stats-grid {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.od-stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
}
.od-stat-label { color: #94a3b8; }
.od-stat-value {
  color: #f1f5f9;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}
.od-sparkline-wrap {
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 6px;
  padding: 8px 10px;
}
.od-sparkline-label {
  font-size: 10px;
  color: #64748b;
  margin-bottom: 4px;
}
.od-warning {
  font-size: 11px;
  color: #fbbf24;
  background: #fbbf2415;
  border: 1px solid #fbbf2440;
  border-radius: 5px;
  padding: 5px 10px;
}
.od-empty {
  text-align: center;
  padding: 28px 10px;
  color: #475569;
}
.od-empty-icon { font-size: 32px; margin-bottom: 8px; }
.od-empty-text { font-size: 14px; color: #64748b; margin-bottom: 4px; }
.od-empty-sub  { font-size: 11px; color: #334155; }
.od-footnote {
  font-size: 9px;
  color: #334155;
  margin-top: 12px;
  border-top: 1px solid #1e293b;
  padding-top: 6px;
}
`
