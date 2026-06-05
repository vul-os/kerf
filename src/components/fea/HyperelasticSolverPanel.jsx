// HyperelasticSolverPanel.jsx — Nonlinear hyperelastic FEM panel.
//
// Wires the `fem_hyperelastic_solve` LLM tool (Total-Lagrangian Newton-Raphson)
// via the standard /api/projects/{pid}/files/{fid}/fem endpoint.
//
// Features:
//   - Material model selector: Neo-Hookean / Mooney-Rivlin / Ogden (N=1)
//   - Displacement-controlled uniaxial test OR free-form JSON model input
//   - Stress-stretch curve (λ vs P, FEM points + analytic overlay, SVG sparkline)
//   - Results table: max stretch, max P, J_min, converged, NR iterations
//   - Deformed mesh summary (node count, element count, max displacement)
//
// Props: { projectId, fileId }

import { useState, useRef } from 'react'
import {
  Activity, AlertTriangle, CheckCircle, Loader2, Play,
  TrendingUp,
} from 'lucide-react'
import { useAuth } from '../../store/auth.js'
import { submitFemJob, pollFemStatus } from './feaApi.js'
import { s, badgeStyle } from './feaStyles.js'

// ── helpers ────────────────────────────────────────────────────────────────────

function fmtNum(v, digits = 4) {
  if (v == null || !isFinite(Number(v))) return '—'
  return Number(v).toFixed(digits)
}
function fmtSci(v, unit = '') {
  if (v == null || !isFinite(Number(v))) return '—'
  return Number(v).toExponential(3) + (unit ? ' ' + unit : '')
}

function ResultRow({ label, value }) {
  return (
    <tr>
      <td style={s.td}>{label}</td>
      <td style={{ ...s.td, ...s.mono }}>{value}</td>
    </tr>
  )
}

function SectionHeader({ icon: Icon, label, color }) {
  return (
    <div style={{ ...s.header, marginBottom: 4 }}>
      <Icon size={15} style={{ color }} />
      <span style={{ ...s.title, color }}>{label}</span>
    </div>
  )
}

// Generic run/poll hook
function useFemJob({ projectId, fileId }) {
  const [running, setRunning] = useState(false)
  const [status, setStatus]   = useState(null)
  const [error, setError]     = useState(null)
  const pollRef = useRef(null)

  function stopPoll() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  async function run(body) {
    if (!projectId || !fileId) return
    setError(null)
    setRunning(true)
    setStatus(null)
    stopPoll()
    try {
      const token = useAuth.getState().accessToken
      const ctx = { pid: projectId, fid: fileId, token }
      const queued = await submitFemJob(ctx, body)
      setStatus({ status: 'queued', job_id: queued.job_id })
      pollRef.current = setInterval(async () => {
        const st = await pollFemStatus(ctx)
        setStatus(st)
        if (st.status === 'done' || st.status === 'error') {
          stopPoll()
          setRunning(false)
        }
      }, 3000)
    } catch (e) {
      setError(e.message)
      setRunning(false)
    }
  }

  return { running, status, error, run, stopPoll }
}

// ── Stress-stretch SVG sparkline ───────────────────────────────────────────────
// Renders FEM path points (circles) + analytic curve (dashed) on a simple SVG.

function StressStretchChart({ path, materialType, matParams }) {
  if (!path || path.length < 2) return null

  // Extract λ and nominal stress P from path steps
  // path items: { lambda: ..., reaction: ..., analytic: ... }
  const width = 260
  const height = 140
  const pad = { top: 10, right: 12, bottom: 28, left: 44 }

  const lambdas  = path.map(p => Number(p.lambda  ?? p.stretch ?? 1))
  const reacts   = path.map(p => Number(p.reaction ?? p.P_fem   ?? 0))
  const analytics = path.map(p => p.analytic != null ? Number(p.analytic) : null)

  const lMin = Math.min(...lambdas, 1.0)
  const lMax = Math.max(...lambdas, 1.02)
  const pMin = Math.min(0, ...reacts)
  const pMax = Math.max(...reacts, 1e-9)

  function xScale(l)  { return pad.left + (l - lMin) / (lMax - lMin) * (width - pad.left - pad.right) }
  function yScale(p)  { return pad.top + (1 - (p - pMin) / (pMax - pMin)) * (height - pad.top - pad.bottom) }

  // FEM points polyline
  const femLine = reacts.map((p, i) => `${xScale(lambdas[i])},${yScale(p)}`).join(' ')

  // Analytic overlay (dashed)
  const analPts = analytics.filter(Boolean)
  let analLine = null
  if (analPts.length >= 2) {
    analLine = analytics
      .map((p, i) => p != null ? `${xScale(lambdas[i])},${yScale(p)}` : null)
      .filter(Boolean)
      .join(' ')
  }

  // Axis labels
  const yTicks = [pMin, pMin + (pMax - pMin) * 0.5, pMax]
  const xTicks = [lMin, lMin + (lMax - lMin) * 0.5, lMax]

  return (
    <div style={{ background: '#0f172a', borderRadius: 6, padding: 8, marginTop: 4 }}>
      <div style={{ color: '#9ca3af', fontSize: 11, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
        <TrendingUp size={11} />
        Stress-stretch curve (λ vs nominal P)
        {analLine && (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginLeft: 8 }}>
            <svg width="18" height="4"><line x1="0" y1="2" x2="18" y2="2" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="3,2" /></svg>
            <span style={{ fontSize: 10 }}>analytic</span>
          </span>
        )}
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <svg width="10" height="10"><circle cx="5" cy="5" r="3.5" fill="#22d3ee" /></svg>
          <span style={{ fontSize: 10 }}>FEM</span>
        </span>
      </div>
      <svg width={width} height={height} style={{ display: 'block', overflow: 'visible' }}>
        {/* Axes */}
        <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} stroke="#374151" strokeWidth="1" />
        <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} stroke="#374151" strokeWidth="1" />

        {/* Y-axis ticks + labels */}
        {yTicks.map((p, i) => (
          <g key={i}>
            <line x1={pad.left - 4} y1={yScale(p)} x2={pad.left} y2={yScale(p)} stroke="#374151" strokeWidth="1" />
            <text x={pad.left - 6} y={yScale(p) + 4} textAnchor="end" fontSize="9" fill="#6b7280">
              {fmtSci(p)}
            </text>
          </g>
        ))}

        {/* X-axis ticks + labels */}
        {xTicks.map((l, i) => (
          <g key={i}>
            <line x1={xScale(l)} y1={height - pad.bottom} x2={xScale(l)} y2={height - pad.bottom + 4} stroke="#374151" strokeWidth="1" />
            <text x={xScale(l)} y={height - pad.bottom + 14} textAnchor="middle" fontSize="9" fill="#6b7280">
              {l.toFixed(3)}
            </text>
          </g>
        ))}

        {/* Axis labels */}
        <text x={pad.left + (width - pad.left - pad.right) / 2} y={height - 1}
          textAnchor="middle" fontSize="10" fill="#9ca3af">λ (stretch)</text>
        <text x={10} y={pad.top + (height - pad.top - pad.bottom) / 2}
          textAnchor="middle" fontSize="10" fill="#9ca3af"
          transform={`rotate(-90, 10, ${pad.top + (height - pad.top - pad.bottom) / 2})`}>P (Pa)</text>

        {/* Analytic overlay (dashed amber) */}
        {analLine && (
          <polyline points={analLine} fill="none" stroke="#f59e0b" strokeWidth="1.5"
            strokeDasharray="4,3" opacity="0.85" />
        )}

        {/* FEM polyline (cyan) */}
        <polyline points={femLine} fill="none" stroke="#22d3ee" strokeWidth="1.5" />

        {/* FEM data points */}
        {reacts.map((p, i) => (
          <circle key={i} cx={xScale(lambdas[i])} cy={yScale(p)} r="3"
            fill="#22d3ee" stroke="#0f172a" strokeWidth="1" />
        ))}
      </svg>
    </div>
  )
}

// ── Material model defaults ────────────────────────────────────────────────────

const MODEL_DEFAULTS = {
  neo_hookean: {
    label: 'Neo-Hookean',
    color: '#10b981',
    params: { type: 'neo_hookean', mu: 1e5, bulk: 3e7 },
    paramFields: [
      { key: 'mu',   label: 'μ (shear mod, Pa)', default: 1e5 },
      { key: 'bulk', label: 'K (bulk mod, Pa)',   default: 3e7 },
    ],
    hint: 'Simple rubber: W = μ/2(I₁-3) + bulk/2(J-1)²',
  },
  mooney_rivlin: {
    label: 'Mooney-Rivlin',
    color: '#8b5cf6',
    params: { type: 'mooney_rivlin', C10: 4e4, C01: 1e4, d: 0 },
    paramFields: [
      { key: 'C10', label: 'C10 (Pa)',        default: 4e4 },
      { key: 'C01', label: 'C01 (Pa)',        default: 1e4 },
      { key: 'd',   label: 'd (compressibility, Pa⁻¹)', default: 0 },
    ],
    hint: 'Rubber/elastomer: W = C10(I₁-3) + C01(I₂-3) + (J-1)²/d',
  },
  ogden: {
    label: 'Ogden N=1',
    color: '#f59e0b',
    params: { type: 'ogden', mu_p: [1e5], alpha_p: [2.0], kappa: 3e7 },
    paramFields: [
      { key: 'mu_p_0',   label: 'μ₁ (Pa)',   default: 1e5 },
      { key: 'alpha_p_0', label: 'α₁',       default: 2.0 },
      { key: 'kappa',    label: 'κ (bulk, Pa)', default: 3e7 },
    ],
    hint: 'Ogden N=1 (α=2 → same as Neo-Hookean when κ>>μ)',
  },
}

// ── Main panel ─────────────────────────────────────────────────────────────────

export default function HyperelasticSolverPanel({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })

  const [modelType, setModelType]   = useState('neo_hookean')
  const [params, setParams]         = useState({
    neo_hookean:   { mu: '1e5', bulk: '3e7' },
    mooney_rivlin: { C10: '4e4', C01: '1e4', d: '0' },
    ogden:         { mu_p_0: '1e5', alpha_p_0: '2.0', kappa: '3e7' },
  })
  const [lambdaTarget, setLambdaTarget] = useState('1.3')
  const [nSteps, setNSteps]             = useState('10')
  const [advancedMode, setAdvancedMode] = useState(false)
  const [jsonModel, setJsonModel]       = useState('')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status
  const mdl       = MODEL_DEFAULTS[modelType]

  function updateParam(k, v) {
    setParams(prev => ({ ...prev, [modelType]: { ...prev[modelType], [k]: v } }))
  }

  function buildMaterialDict() {
    const p = params[modelType]
    if (modelType === 'neo_hookean') {
      return { type: 'neo_hookean', mu: parseFloat(p.mu) || 1e5, bulk: parseFloat(p.bulk) || 3e7 }
    }
    if (modelType === 'mooney_rivlin') {
      return { type: 'mooney_rivlin', C10: parseFloat(p.C10) || 4e4, C01: parseFloat(p.C01) || 0, d: parseFloat(p.d) || 0 }
    }
    if (modelType === 'ogden') {
      return {
        type: 'ogden',
        mu_p:    [parseFloat(p.mu_p_0) || 1e5],
        alpha_p: [parseFloat(p.alpha_p_0) || 2.0],
        kappa:   parseFloat(p.kappa) || 3e7,
      }
    }
    return {}
  }

  function handleRun() {
    if (advancedMode) {
      try {
        const model = JSON.parse(jsonModel)
        run({ analysis_type: 'hyperelastic', model })
      } catch {
        // parse error shown inline
      }
      return
    }

    const lam = parseFloat(lambdaTarget) || 1.3
    const mat = buildMaterialDict()
    // Unit cube, displacement-controlled uniaxial test
    run({
      analysis_type: 'hyperelastic',
      model: {
        mesh: { type: 'unit_cube', n_div: 1 },
        material: mat,
        prescribed_displacements: {
          'top_z': lam - 1.0,   // δ = (λ-1)×L, L=1
        },
        n_load_steps: parseInt(nSteps, 10) || 10,
        solver: 'newton_raphson',
        b_bar: true,
        arc_length: false,
        report_path: true,
      },
    })
  }

  // Extract path array from result for chart
  const chartPath = result?.path ?? null
  const pathValid = Array.isArray(chartPath) && chartPath.length >= 2

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }}
      data-testid="hyperelastic-solver-card">
      <SectionHeader icon={Activity} label="Hyperelastic FEM (Total-Lagrangian NR)" color={mdl.color} />

      {/* Model type */}
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Model</label>
          <select value={modelType} onChange={e => setModelType(e.target.value)} style={s.select} disabled={running}>
            {Object.entries(MODEL_DEFAULTS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </div>
        <div style={{ color: '#6b7280', fontSize: 11, paddingLeft: 4, marginTop: -4 }}>{mdl.hint}</div>
      </div>

      {/* Parameter fields */}
      {!advancedMode && (
        <div style={s.section}>
          {mdl.paramFields.map(f => (
            <div style={s.row} key={f.key}>
              <label style={s.label}>{f.label}</label>
              <input
                type="text"
                value={params[modelType][f.key] ?? String(f.default)}
                onChange={e => updateParam(f.key, e.target.value)}
                style={s.input}
                disabled={running}
              />
            </div>
          ))}

          {/* Loading */}
          <div style={s.row}>
            <label style={s.label}>Target λ (stretch)</label>
            <input type="text" value={lambdaTarget} onChange={e => setLambdaTarget(e.target.value)}
              style={s.input} disabled={running} />
          </div>
          <div style={s.row}>
            <label style={s.label}>Load steps</label>
            <input type="number" value={nSteps} min="2" max="50"
              onChange={e => setNSteps(e.target.value)} style={s.input} disabled={running} />
          </div>
        </div>
      )}

      {/* Advanced JSON mode */}
      <div style={{ ...s.row, marginTop: -4 }}>
        <input type="checkbox" checked={advancedMode} onChange={e => setAdvancedMode(e.target.checked)} disabled={running} id="hyp-adv" />
        <label htmlFor="hyp-adv" style={{ color: '#9ca3af', fontSize: 11, cursor: 'pointer' }}>
          Advanced (raw JSON model)
        </label>
      </div>
      {advancedMode && (
        <textarea
          value={jsonModel}
          onChange={e => setJsonModel(e.target.value)}
          placeholder={'{\n  "mesh": {...},\n  "material": {...},\n  "prescribed_displacements": {...},\n  ...\n}'}
          rows={8}
          style={{ ...s.input, flex: 'unset', width: '100%', fontFamily: 'ui-monospace, monospace', fontSize: 11, resize: 'vertical' }}
          disabled={running}
        />
      )}

      {/* Run button */}
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#065f46', ...(running ? s.buttonDisabled : {}) }}>
        {running
          ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Solving NR…</>
          : <><Play size={13} /> Run Hyperelastic FEM</>}
      </button>

      {/* Status */}
      {error && (
        <div style={s.errorBox} role="alert">
          <AlertTriangle size={13} />
          <span>{error}</span>
        </div>
      )}
      {(jobStatus === 'queued' || jobStatus === 'running') && (
        <div style={s.infoBox}>
          <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
          <span>{jobStatus === 'queued' ? 'Queued…' : 'Newton-Raphson iterations…'}</span>
          {status?.job_id && (
            <span style={{ ...s.mono, fontSize: 10, marginLeft: 'auto' }}>#{String(status.job_id).slice(0, 8)}</span>
          )}
        </div>
      )}

      {/* Results */}
      {result && jobStatus === 'done' && (
        <>
          <div style={s.section}>
            <div style={s.sectionTitle}>
              <CheckCircle size={12} style={{ color: '#34d399' }} />
              <span>Results</span>
              {result.converged && (
                <span style={{ ...badgeStyle('done'), fontSize: 10, marginLeft: 8 }}>converged</span>
              )}
              {result.converged === false && (
                <span style={{ ...badgeStyle('error'), fontSize: 10, marginLeft: 8 }}>not converged</span>
              )}
            </div>
            <table style={s.table}><tbody>
              {result.max_stretch    != null && <ResultRow label="Max stretch λ"       value={fmtNum(result.max_stretch, 5)} />}
              {result.max_nominal_P  != null && <ResultRow label="Max nominal stress P" value={fmtSci(result.max_nominal_P, 'Pa')} />}
              {result.J_min         != null && <ResultRow label="J_min (incompress.)"  value={fmtNum(result.J_min, 5)} />}
              {result.J_max         != null && <ResultRow label="J_max"                value={fmtNum(result.J_max, 5)} />}
              {result.max_displacement != null && <ResultRow label="Max displacement"  value={fmtSci(result.max_displacement, 'm')} />}
              {result.n_nodes        != null && <ResultRow label="Nodes"               value={String(result.n_nodes)} />}
              {result.n_elements     != null && <ResultRow label="Elements (H8)"       value={String(result.n_elements)} />}
              {result.nr_iters_last  != null && <ResultRow label="NR iters (last step)" value={String(result.nr_iters_last)} />}
              {result.steps_done     != null && <ResultRow label="Steps done"          value={String(result.steps_done)} />}
              {result.analytic_error_pct != null && (
                <ResultRow label="Analytic error"
                  value={fmtNum(result.analytic_error_pct, 2) + ' %'} />
              )}
            </tbody></table>
          </div>

          {/* Stress-stretch chart */}
          {pathValid && (
            <StressStretchChart path={chartPath} materialType={modelType} matParams={params[modelType]} />
          )}

          {/* Deformed mesh note */}
          {result.deformed_nodes && (
            <div style={{ color: '#6b7280', fontSize: 11, marginTop: 4 }}>
              Deformed mesh: {result.deformed_nodes} nodes · max disp {fmtSci(result.max_displacement, 'm')}
            </div>
          )}

          {/* Gaps / caveats */}
          <div style={{ color: '#6b7280', fontSize: 11, borderTop: '1px solid #1f2937', paddingTop: 6 }}>
            Caveats: no viscoelastic relaxation, no Mullins stress-softening, no Yeoh / Arruda-Boyce models.
          </div>
        </>
      )}

      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert">
          <AlertTriangle size={13} />
          <span>{status.error}</span>
        </div>
      )}
    </div>
  )
}
