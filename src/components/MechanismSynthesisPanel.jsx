// MechanismSynthesisPanel.jsx — Mechanism Synthesis (four-bar, cam-follower, gear-train).
//
// Tabbed panel wiring kerf-mates synthesis LLM tools into the UI:
//
//   Tab 1 — Four-bar Burmester synthesis
//     • Input: three coupler-curve precision points (mm)
//     • Calls: synthesise_four_bar → displays link lengths + Grashof class
//     • Then:  generate_coupler_curve → SVG coupler-curve plot
//
//   Tab 2 — Cam-follower profile generator
//     • Input: motion law (cycloidal / polynomial / harmonic), lift h, segment angle β
//     • Calls: synthesise_cam → SVG displacement/velocity/acceleration chart
//
//   Tab 3 — Gear-train ratio synthesis
//     • Input: target ratio, stages preference, speed range
//     • Calls: synthesise_gear_train → stage configuration table
//
// All dispatches go to POST /api/tools/call { tool, args }.
// No external chart libraries — all plots are plain inline SVG.
//
// Props: none (standalone panel)

import { useState, useCallback } from 'react'
import { Settings, Cog, Circle, Sliders, AlertTriangle, CheckCircle, Loader2, Play } from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Styles (inline, consistent with AcousticsResultPanel palette)
// ---------------------------------------------------------------------------

const s = {
  root:         { background: '#111827', padding: '12px', fontSize: 12, color: '#e5e7eb', minHeight: 200 },
  header:       { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 },
  title:        { fontWeight: 600, fontSize: 13, color: '#f9fafb' },
  tabs:         { display: 'flex', gap: 2, marginBottom: 10, flexWrap: 'wrap' },
  tab:          { padding: '4px 10px', borderRadius: 4, border: '1px solid #374151', background: '#1f2937', color: '#9ca3af', cursor: 'pointer', fontSize: 11 },
  tabActive:    { background: '#1d4ed8', borderColor: '#3b82f6', color: '#fff' },
  section:      { background: '#1f2937', borderRadius: 6, padding: '10px', marginBottom: 8 },
  sectionTitle: { display: 'flex', alignItems: 'center', gap: 5, fontWeight: 600, marginBottom: 8, color: '#d1d5db', fontSize: 11 },
  row:          { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 },
  label:        { color: '#9ca3af', width: 135, flexShrink: 0, fontSize: 11 },
  input:        { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12, minWidth: 0 },
  select:       { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12 },
  button:       { display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 5, border: 'none', color: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 500 },
  buttonDisabled: { opacity: 0.5, cursor: 'not-allowed' },
  errorBox:     { display: 'flex', alignItems: 'flex-start', gap: 6, background: '#450a0a', borderRadius: 5, padding: '8px', color: '#fca5a5', marginTop: 8 },
  resultBox:    { background: '#0f172a', borderRadius: 4, padding: '8px', marginTop: 6, fontFamily: 'monospace', fontSize: 11 },
  table:        { width: '100%', borderCollapse: 'collapse', marginTop: 4 },
  td:           { padding: '3px 6px', borderBottom: '1px solid #1f2937' },
  mono:         { fontFamily: 'monospace' },
  badge:        { padding: '2px 6px', borderRadius: 3, fontSize: 10, fontWeight: 600 },
  note:         { color: '#6b7280', fontSize: 10, marginBottom: 4 },
  svgWrap:      { background: '#0f172a', borderRadius: 4, marginTop: 8, padding: '4px', overflow: 'hidden' },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function callTool(toolName, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`HTTP ${res.status}: ${txt}`)
  }
  return res.json()
}

function fmt(v, d = 3) {
  if (v == null) return '—'
  if (typeof v === 'number') return v.toFixed(d)
  return String(v)
}

function ErrBox({ msg }) {
  if (!msg) return null
  return (
    <div style={s.errorBox}>
      <AlertTriangle size={14} style={{ marginTop: 1, flexShrink: 0 }} />
      <span style={{ fontSize: 11 }}>{msg}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Coupler-curve SVG plot
// ---------------------------------------------------------------------------

/**
 * Render a 2-D coupler curve as inline SVG.
 * points: Array of [x, y] in mm.
 * precision_pts: Array of [x, y] in mm — shown as orange crosses.
 */
export function CouplerCurvePlot({ points, precisionPts = [] }) {
  if (!Array.isArray(points) || points.length < 2) {
    return (
      <div style={{ ...s.svgWrap, padding: '16px', textAlign: 'center', color: '#6b7280', fontSize: 11 }}>
        No coupler curve data yet.
      </div>
    )
  }

  const W = 340, H = 220
  const PAD = 24

  const xs = points.map(p => p[0])
  const ys = points.map(p => p[1])
  const xMin = Math.min(...xs), xMax = Math.max(...xs)
  const yMin = Math.min(...ys), yMax = Math.max(...ys)
  const xRange = xMax - xMin || 1
  const yRange = yMax - yMin || 1

  function toSvg(x, y) {
    const px = PAD + ((x - xMin) / xRange) * (W - 2 * PAD)
    const py = H - PAD - ((y - yMin) / yRange) * (H - 2 * PAD)
    return [px, py]
  }

  const pathD = points.map((p, i) => {
    const [px, py] = toSvg(p[0], p[1])
    return `${i === 0 ? 'M' : 'L'}${px.toFixed(1)},${py.toFixed(1)}`
  }).join(' ') + ' Z'

  return (
    <div style={s.svgWrap} data-testid="coupler-curve-svg">
      <svg width={W} height={H} style={{ display: 'block' }}>
        {/* Axes */}
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#374151" strokeWidth={1} />
        <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="#374151" strokeWidth={1} />
        {/* Axis labels */}
        <text x={W / 2} y={H - 4} textAnchor="middle" fill="#6b7280" fontSize={9}>x (mm)</text>
        <text x={8} y={H / 2} textAnchor="middle" fill="#6b7280" fontSize={9}
              transform={`rotate(-90,8,${H / 2})`}>y (mm)</text>
        {/* Coupler curve */}
        <path d={pathD} fill="none" stroke="#3b82f6" strokeWidth={1.5} strokeLinejoin="round" />
        {/* Precision points */}
        {precisionPts.map((p, i) => {
          const [px, py] = toSvg(p[0], p[1])
          return (
            <g key={i}>
              <line x1={px - 5} y1={py} x2={px + 5} y2={py} stroke="#f97316" strokeWidth={1.5} />
              <line x1={px} y1={py - 5} x2={px} y2={py + 5} stroke="#f97316" strokeWidth={1.5} />
            </g>
          )
        })}
      </svg>
      <div style={{ fontSize: 10, color: '#6b7280', paddingLeft: 4, paddingBottom: 2 }}>
        Coupler curve — {points.length} pts | x∈[{fmt(xMin, 1)},{fmt(xMax, 1)}] y∈[{fmt(yMin, 1)},{fmt(yMax, 1)}] mm
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Cam profile SVG chart
// ---------------------------------------------------------------------------

/**
 * Render displacement vs cam-angle as inline SVG.
 * profile: Array of { theta_deg, displacement, velocity_per_omega, acceleration_per_omega2 }
 */
export function CamProfileChart({ profile, h }) {
  if (!Array.isArray(profile) || profile.length < 2) {
    return (
      <div style={{ ...s.svgWrap, padding: '16px', textAlign: 'center', color: '#6b7280', fontSize: 11 }}>
        No cam profile data yet.
      </div>
    )
  }

  const W = 340, H = 180
  const PAD = 28

  const thetas = profile.map(p => p.theta_deg)
  const disps  = profile.map(p => p.displacement)
  const tMin = thetas[0], tMax = thetas[thetas.length - 1]
  const dMax = Math.max(...disps, h || 0) || 1

  function toX(theta) {
    return PAD + ((theta - tMin) / (tMax - tMin)) * (W - 2 * PAD)
  }
  function toY(d) {
    return H - PAD - (d / dMax) * (H - 2 * PAD)
  }

  const pathD = profile.map((p, i) => {
    const x = toX(p.theta_deg)
    const y = toY(p.displacement)
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')

  return (
    <div style={s.svgWrap} data-testid="cam-profile-svg">
      <svg width={W} height={H} style={{ display: 'block' }}>
        {/* Axes */}
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#374151" strokeWidth={1} />
        <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="#374151" strokeWidth={1} />
        {/* Axis labels */}
        <text x={W / 2} y={H - 4} textAnchor="middle" fill="#6b7280" fontSize={9}>θ (deg)</text>
        <text x={8} y={H / 2} textAnchor="middle" fill="#6b7280" fontSize={9}
              transform={`rotate(-90,8,${H / 2})`}>y (mm)</text>
        {/* Displacement curve */}
        <path d={pathD} fill="none" stroke="#10b981" strokeWidth={1.5} />
        {/* h reference line */}
        {h != null && (
          <line x1={PAD} y1={toY(h)} x2={W - PAD} y2={toY(h)}
                stroke="#6b7280" strokeWidth={1} strokeDasharray="3,3" />
        )}
        {/* Tick labels */}
        <text x={PAD} y={H - PAD + 12} textAnchor="middle" fill="#6b7280" fontSize={8}>{fmt(tMin, 0)}°</text>
        <text x={W - PAD} y={H - PAD + 12} textAnchor="middle" fill="#6b7280" fontSize={8}>{fmt(tMax, 0)}°</text>
        <text x={PAD - 4} y={toY(dMax) + 4} textAnchor="end" fill="#6b7280" fontSize={8}>{fmt(dMax, 1)}</text>
        <text x={PAD - 4} y={H - PAD + 4} textAnchor="end" fill="#6b7280" fontSize={8}>0</text>
      </svg>
      <div style={{ fontSize: 10, color: '#6b7280', paddingLeft: 4, paddingBottom: 2 }}>
        Displacement vs cam angle | lift h={fmt(h, 2)} mm
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 1 — Four-bar synthesis
// ---------------------------------------------------------------------------

const DEFAULT_POINTS = [
  { x: '10', y: '0' },
  { x: '10', y: '10' },
  { x: '0', y: '10' },
]

function FourBarTab() {
  const [points, setPoints] = useState(DEFAULT_POINTS)
  const [tolMm, setTolMm]   = useState('0.5')
  const [loading, setLoading] = useState(false)
  const [result, setResult]   = useState(null)
  const [curve, setCurve]     = useState(null)
  const [error, setError]     = useState('')

  function updatePoint(i, field, val) {
    setPoints(pts => pts.map((p, idx) => idx === i ? { ...p, [field]: val } : p))
  }

  const run = useCallback(async () => {
    setError(''); setResult(null); setCurve(null); setLoading(true)
    try {
      const pts = points.map(p => [parseFloat(p.x), parseFloat(p.y)])
      if (pts.some(p => p.some(v => !isFinite(v)))) {
        setError('All point coordinates must be finite numbers.')
        return
      }
      const r = await callTool('synthesise_four_bar', {
        points: pts,
        tol_mm: parseFloat(tolMm) || 0.5,
        max_iters: 2000,
      })
      if (!r.ok) { setError(r.reason || r.error || 'synthesis failed'); return }
      setResult(r)
      // Generate coupler curve for plot
      const cr = await callTool('generate_coupler_curve', {
        r1: r.r1, r2: r.r2, r3: r.r3, r4: r.r4, px: r.px, py: r.py,
        n_points: 360,
      })
      if (cr.ok) setCurve(cr.points)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [points, tolMm])

  return (
    <div data-testid="fourbar-tab">
      <div style={s.section}>
        <div style={s.sectionTitle}><Settings size={11} /> Precision Points (mm)</div>
        <div style={{ ...s.note }}>
          Three coupler-curve positions the synthesised linkage must pass through.
          Burmester theory (Sandor &amp; Erdman 1984, Ch. 5).
        </div>
        {points.map((p, i) => (
          <div key={i} style={s.row}>
            <span style={{ ...s.label, width: 55 }}>P{i + 1}</span>
            <span style={{ ...s.label, width: 12, color: '#6b7280' }}>x</span>
            <input style={{ ...s.input, width: 70 }}
                   value={p.x} onChange={e => updatePoint(i, 'x', e.target.value)}
                   data-testid={`point-${i}-x`} />
            <span style={{ ...s.label, width: 12, color: '#6b7280' }}>y</span>
            <input style={{ ...s.input, width: 70 }}
                   value={p.y} onChange={e => updatePoint(i, 'y', e.target.value)}
                   data-testid={`point-${i}-y`} />
          </div>
        ))}
        <div style={s.row}>
          <span style={s.label}>Tolerance (mm)</span>
          <input style={s.input} value={tolMm}
                 onChange={e => setTolMm(e.target.value)} data-testid="fourbar-tol" />
        </div>
        <button
          style={{ ...s.button, background: loading ? '#374151' : '#1d4ed8',
                   ...(loading ? s.buttonDisabled : {}) }}
          onClick={run} disabled={loading}
          data-testid="fourbar-run-btn"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {loading ? 'Running…' : 'Synthesise'}
        </button>
      </div>

      <ErrBox msg={error} />

      {result && (
        <div style={s.section} data-testid="fourbar-result">
          <div style={s.sectionTitle}><CheckCircle size={11} color="#10b981" /> Result</div>
          <table style={s.table}>
            <tbody>
              {[['r1 (ground)', result.r1], ['r2 (crank)', result.r2],
                ['r3 (coupler)', result.r3], ['r4 (rocker)', result.r4],
                ['px (coupler offset x)', result.px], ['py (coupler offset y)', result.py],
                ['Max error', `${fmt(result.max_error_mm, 4)} mm`],
                ['Grashof', result.grashof]].map(([k, v]) => (
                <tr key={k}>
                  <td style={{ ...s.td, color: '#9ca3af', width: '55%' }}>{k}</td>
                  <td style={{ ...s.td, ...s.mono, color: '#f9fafb' }}>{fmt(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.warnings?.length > 0 && (
            <div style={{ color: '#fbbf24', fontSize: 10, marginTop: 4 }}>
              {result.warnings.map((w, i) => <div key={i}>{w}</div>)}
            </div>
          )}
          <CouplerCurvePlot points={curve || []} precisionPts={points.map(p => [parseFloat(p.x), parseFloat(p.y)])} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 2 — Cam-follower
// ---------------------------------------------------------------------------

function CamTab() {
  const [law, setLaw]           = useState('cycloidal')
  const [h, setH]               = useState('10')
  const [betaDeg, setBetaDeg]   = useState('120')
  const [polyOrder, setPolyOrder] = useState('5')
  const [rise, setRise]         = useState('true')
  const [loading, setLoading]   = useState(false)
  const [result, setResult]     = useState(null)
  const [error, setError]       = useState('')

  const run = useCallback(async () => {
    setError(''); setResult(null); setLoading(true)
    try {
      const args = {
        law,
        h: parseFloat(h),
        beta_deg: parseFloat(betaDeg),
        n_points: 180,
        rise: rise === 'true',
      }
      if (law === 'polynomial') args.poly_order = parseInt(polyOrder, 10)
      const r = await callTool('synthesise_cam', args)
      if (!r.ok) { setError(r.reason || r.error || 'cam synthesis failed'); return }
      setResult(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [law, h, betaDeg, polyOrder, rise])

  return (
    <div data-testid="cam-tab">
      <div style={s.section}>
        <div style={s.sectionTitle}><Circle size={11} /> Cam-Follower Profile</div>
        <div style={{ ...s.note }}>
          Follower motion law → displacement / velocity / acceleration profiles.
          Norton 2012, Ch. 8; Litvin &amp; Fuentes 2004, Ch. 8.
        </div>
        <div style={s.row}>
          <span style={s.label}>Motion law</span>
          <select style={s.select} value={law} onChange={e => setLaw(e.target.value)}
                  data-testid="cam-law">
            <option value="cycloidal">Cycloidal (C2, best dynamics)</option>
            <option value="polynomial">Polynomial (3-4-5 / 4-5-6-7)</option>
            <option value="harmonic">Harmonic (C1, simple)</option>
          </select>
        </div>
        {law === 'polynomial' && (
          <div style={s.row}>
            <span style={s.label}>Poly order</span>
            <select style={s.select} value={polyOrder}
                    onChange={e => setPolyOrder(e.target.value)} data-testid="cam-poly-order">
              <option value="4">4 (cubic Hermite, C1)</option>
              <option value="5">5 (3-4-5, C2)</option>
              <option value="6">6 (5-6, C2+)</option>
              <option value="7">7 (4-5-6-7, C3)</option>
            </select>
          </div>
        )}
        <div style={s.row}>
          <span style={s.label}>Lift h (mm)</span>
          <input style={s.input} value={h} onChange={e => setH(e.target.value)}
                 data-testid="cam-h" />
        </div>
        <div style={s.row}>
          <span style={s.label}>Segment angle β (°)</span>
          <input style={s.input} value={betaDeg} onChange={e => setBetaDeg(e.target.value)}
                 data-testid="cam-beta" />
        </div>
        <div style={s.row}>
          <span style={s.label}>Segment type</span>
          <select style={s.select} value={rise} onChange={e => setRise(e.target.value)}
                  data-testid="cam-rise">
            <option value="true">Rise</option>
            <option value="false">Fall</option>
          </select>
        </div>
        <button
          style={{ ...s.button, background: loading ? '#374151' : '#1d4ed8',
                   ...(loading ? s.buttonDisabled : {}) }}
          onClick={run} disabled={loading}
          data-testid="cam-run-btn"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {loading ? 'Running…' : 'Generate Profile'}
        </button>
      </div>

      <ErrBox msg={error} />

      {result && (
        <div style={s.section} data-testid="cam-result">
          <div style={s.sectionTitle}>
            <CheckCircle size={11} color="#10b981" /> Profile (
            <span style={{ ...s.mono, color: '#f9fafb' }}>{result.law}</span>
            {result.poly_order != null && `, order=${result.poly_order}`})
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 6 }}>
            {[
              ['Lift', `${fmt(result.h, 2)} mm`],
              ['β', `${fmt(result.beta_deg, 1)}°`],
              ['Points', result.n_points],
              ['C2 ok', result.continuity_ok ? '✓' : '✗'],
              ['Lift ok', result.lift_ok ? '✓' : '✗'],
            ].map(([k, v]) => (
              <span key={k} style={{ fontSize: 11, color: '#9ca3af' }}>
                {k}: <strong style={{ color: '#f9fafb' }}>{v}</strong>
              </span>
            ))}
          </div>
          <CamProfileChart profile={result.profile} h={result.h} />
          {result.warnings?.length > 0 && (
            <div style={{ color: '#fbbf24', fontSize: 10, marginTop: 4 }}>
              {result.warnings.map((w, i) => <div key={i}>{w}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 3 — Gear-train synthesis
// ---------------------------------------------------------------------------

function GearTab() {
  const [targetRatio, setTargetRatio] = useState('4')
  const [preferStages, setPreferStages] = useState('')
  const [maxRpm, setMaxRpm]           = useState('3000')
  const [tolRatio, setTolRatio]       = useState('0.02')
  const [loading, setLoading]         = useState(false)
  const [result, setResult]           = useState(null)
  const [error, setError]             = useState('')

  const run = useCallback(async () => {
    setError(''); setResult(null); setLoading(true)
    try {
      const args = {
        target_ratio: parseFloat(targetRatio),
        speed_range_rpm: [0, parseFloat(maxRpm) || 3000],
        tol_ratio: parseFloat(tolRatio) || 0.02,
      }
      if (preferStages) args.prefer_stages = parseInt(preferStages, 10)
      const r = await callTool('synthesise_gear_train', args)
      if (!r.ok) { setError(r.reason || r.error || 'gear synthesis failed'); return }
      setResult(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [targetRatio, preferStages, maxRpm, tolRatio])

  return (
    <div data-testid="geartrain-tab">
      <div style={s.section}>
        <div style={s.sectionTitle}><Cog size={11} /> Gear-Train Synthesis</div>
        <div style={{ ...s.note }}>
          1- or 2-stage ISO spur-gear train for a target ratio.
          ISO 54, Shigley 10th ed. Ch. 13, Norton 2012 Ch. 11.
        </div>
        <div style={s.row}>
          <span style={s.label}>Target ratio</span>
          <input style={s.input} value={targetRatio} onChange={e => setTargetRatio(e.target.value)}
                 data-testid="gear-ratio" />
        </div>
        <div style={s.row}>
          <span style={s.label}>Max speed (rpm)</span>
          <input style={s.input} value={maxRpm} onChange={e => setMaxRpm(e.target.value)}
                 data-testid="gear-max-rpm" />
        </div>
        <div style={s.row}>
          <span style={s.label}>Ratio tolerance</span>
          <input style={s.input} value={tolRatio} onChange={e => setTolRatio(e.target.value)}
                 data-testid="gear-tol" />
        </div>
        <div style={s.row}>
          <span style={s.label}>Prefer stages</span>
          <select style={s.select} value={preferStages}
                  onChange={e => setPreferStages(e.target.value)} data-testid="gear-stages">
            <option value="">Auto</option>
            <option value="1">1 stage</option>
            <option value="2">2 stages</option>
          </select>
        </div>
        <button
          style={{ ...s.button, background: loading ? '#374151' : '#1d4ed8',
                   ...(loading ? s.buttonDisabled : {}) }}
          onClick={run} disabled={loading}
          data-testid="gear-run-btn"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {loading ? 'Running…' : 'Synthesise'}
        </button>
      </div>

      <ErrBox msg={error} />

      {result && (
        <div style={s.section} data-testid="gear-result">
          <div style={s.sectionTitle}><CheckCircle size={11} color="#10b981" /> Result</div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 8 }}>
            {[
              ['Stages', result.stages],
              ['Actual ratio', fmt(result.total_ratio, 4)],
              ['Error', `${(result.ratio_error * 100).toFixed(2)}%`],
            ].map(([k, v]) => (
              <span key={k} style={{ fontSize: 11, color: '#9ca3af' }}>
                {k}: <strong style={{ color: '#f9fafb' }}>{v}</strong>
              </span>
            ))}
          </div>
          {result.stage_configs?.map((sc, i) => (
            <div key={i} style={{ marginBottom: 8 }}>
              <div style={{ color: '#60a5fa', fontWeight: 600, fontSize: 11, marginBottom: 4 }}>
                Stage {i + 1}
              </div>
              <table style={s.table}>
                <tbody>
                  {[
                    ['Module m', `${sc.module} mm`],
                    ['z₁ (pinion)', sc.z1],
                    ['z₂ (gear)', sc.z2],
                    ['Ratio z₂/z₁', fmt(sc.ratio, 4)],
                    ['Centre distance', `${fmt(sc.centre_distance_mm, 3)} mm`],
                    ['Pitch ∅ pinion', `${fmt(sc.pitch_diameter_1_mm, 3)} mm`],
                    ['Pitch ∅ gear', `${fmt(sc.pitch_diameter_2_mm, 3)} mm`],
                    ['Pressure angle', `${sc.pressure_angle_deg}°`],
                  ].map(([k, v]) => (
                    <tr key={k}>
                      <td style={{ ...s.td, color: '#9ca3af', width: '55%' }}>{k}</td>
                      <td style={{ ...s.td, ...s.mono, color: '#f9fafb' }}>{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {result.warnings?.length > 0 && (
            <div style={{ color: '#fbbf24', fontSize: 10, marginTop: 4 }}>
              {result.warnings.map((w, i) => <div key={i}>{w}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'fourbar', label: 'Four-bar', icon: <Settings size={11} /> },
  { id: 'cam',     label: 'Cam-follower', icon: <Circle size={11} /> },
  { id: 'gear',    label: 'Gear-train', icon: <Cog size={11} /> },
]

export default function MechanismSynthesisPanel() {
  const [activeTab, setActiveTab] = useState('fourbar')

  return (
    <div style={s.root} data-testid="mechanism-synthesis-panel">
      {/* Header */}
      <div style={s.header}>
        <Sliders size={14} style={{ color: '#3b82f6', flexShrink: 0 }} />
        <span style={s.title}>Mechanism Synthesis</span>
      </div>

      {/* Tab bar */}
      <div style={s.tabs} role="tablist">
        {TABS.map(tab => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            style={{ ...s.tab, ...(activeTab === tab.id ? s.tabActive : {}) }}
            onClick={() => setActiveTab(tab.id)}
            data-testid={`tab-${tab.id}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'fourbar' && <FourBarTab />}
      {activeTab === 'cam'     && <CamTab />}
      {activeTab === 'gear'    && <GearTab />}
    </div>
  )
}
