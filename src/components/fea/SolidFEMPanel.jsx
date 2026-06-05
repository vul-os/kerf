// SolidFEMPanel.jsx — FEM results panel for solid tet/hex elements.
//
// Wires the fem_solid_static, fem_modal_beam, and fem_linear_static_beam
// LLM tools via the standard /api/projects/{pid}/files/{fid}/fem endpoint.
//
// Sections:
//   Solid Static    — tet4 / hex8 mesh with nodal displacement + von Mises contour
//   Modal Beam      — consistent-mass Hermite beam modal analysis
//   Beam Static     — 1-D axial bar / Euler-Bernoulli beam / thermal bar
//
// Props: { projectId, fileId }

import { useState, useRef } from 'react'
import {
  Activity, AlertTriangle, CheckCircle, Loader2,
  Play, Grid3x3, BarChart2, Thermometer,
} from 'lucide-react'
import { useAuth } from '../../store/auth.js'
import { submitFemJob, pollFemStatus } from './feaApi.js'
import { s, badgeStyle } from './feaStyles.js'

// ── helpers ────────────────────────────────────────────────────────────────────

function fmtMPa(pa) {
  if (pa == null || !isFinite(pa)) return '—'
  return (pa / 1e6).toFixed(3) + ' MPa'
}
function fmtMm(m) {
  if (m == null || !isFinite(m)) return '—'
  return (m * 1000).toFixed(4) + ' mm'
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

  return { running, status, error, run }
}

// ── Von Mises stress contour bar ───────────────────────────────────────────────

function VonMisesContour({ vmValues, maxVm, yieldStrength }) {
  if (!Array.isArray(vmValues) || vmValues.length === 0) return null
  const max = maxVm || Math.max(...vmValues) || 1
  const N = 20
  const buckets = Array(N).fill(0)
  for (const v of vmValues) {
    const idx = Math.min(N - 1, Math.floor((v / max) * N))
    buckets[idx]++
  }
  const peak = Math.max(...buckets) || 1
  const yieldLine = yieldStrength ? Math.min(N - 1, Math.round((yieldStrength / max) * N)) : null

  return (
    <div aria-label="Von Mises stress distribution contour">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>
        von Mises stress distribution
        {yieldStrength && (
          <span style={{ color: '#fbbf24', fontSize: 10, marginLeft: 8 }}>
            ▲ yield @ {fmtMPa(yieldStrength)}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 48, position: 'relative' }}>
        {buckets.map((count, i) => {
          const t = i / (N - 1)
          const r = Math.round(t * 255)
          const b = Math.round((1 - t) * 255)
          return (
            <div
              key={i}
              title={`Bin ${i}: ${count} elements — σ ≈ ${((i / N) * max / 1e6).toFixed(1)} MPa`}
              style={{
                flex: 1,
                height: `${Math.max(2, (count / peak) * 100)}%`,
                background: `rgb(${r},80,${b})`,
                borderRadius: '2px 2px 0 0',
                border: (yieldLine !== null && i === yieldLine) ? '2px solid #fbbf24' : 'none',
                boxSizing: 'border-box',
              }}
            />
          )
        })}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', marginTop: 2 }}>
        <span>0 MPa</span>
        <span>{(max / 1e6).toFixed(2)} MPa</span>
      </div>
    </div>
  )
}

// ── Displacement profile plot (1-D beam) ──────────────────────────────────────

function DeflectionPlot({ x, w, label }) {
  const W = 240, H = 64
  if (!Array.isArray(x) || x.length < 2 || !Array.isArray(w)) return null
  const maxAbs = Math.max(...w.map(Math.abs)) || 1
  const maxX = x[x.length - 1] || 1
  const step = W / (x.length - 1 || 1)
  const pts = x.map((xi, i) => {
    const px = ((xi / maxX) * W).toFixed(1)
    const py = (H / 2 - (w[i] / maxAbs) * (H * 0.42)).toFixed(1)
    return `${px},${py}`
  }).join(' ')
  return (
    <div aria-label={label || 'Deflection profile'}>
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>{label || 'Deflection profile'}</div>
      <svg width={W} height={H} style={{ display: 'block', background: '#1f2937', borderRadius: 4 }}>
        <line x1={0} y1={H / 2} x2={W} y2={H / 2} stroke="#374151" strokeWidth="1" strokeDasharray="4 2" />
        <polyline points={pts} fill="none" stroke="#22d3ee" strokeWidth="1.5" />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', marginTop: 2 }}>
        <span>x=0</span>
        <span style={{ color: '#22d3ee' }}>δ_max={fmtMm(Math.max(...w.map(Math.abs)))}</span>
        <span>x={maxX.toFixed(2)} m</span>
      </div>
    </div>
  )
}

// ── Modal frequency spectrum ───────────────────────────────────────────────────

function FrequencySpectrum({ freqs }) {
  const W = 240, H = 48
  if (!Array.isArray(freqs) || freqs.length === 0) return null
  const max = Math.max(...freqs) || 1
  const barW = Math.floor(W / freqs.length) - 2
  return (
    <div aria-label="Natural frequency spectrum">
      <div style={{ ...s.sectionTitle, marginBottom: 4 }}>Natural frequency spectrum</div>
      <svg width={W} height={H} style={{ display: 'block', background: '#1f2937', borderRadius: 4 }}>
        {freqs.map((f, i) => {
          const barH = Math.max(2, (f / max) * (H - 8))
          const x = i * (barW + 2) + 1
          return (
            <g key={i}>
              <rect
                x={x} y={H - barH - 4} width={barW} height={barH}
                fill="#a78bfa" rx="1"
                title={`Mode ${i + 1}: ${f.toFixed(1)} Hz`}
              />
              <text x={x + barW / 2} y={H - 1} textAnchor="middle"
                fontSize="8" fill="#6b7280">
                {i + 1}
              </text>
            </g>
          )
        })}
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', marginTop: 2 }}>
        <span>f_1 = {freqs[0]?.toFixed(2)} Hz</span>
        <span>f_{freqs.length} = {freqs[freqs.length - 1]?.toFixed(2)} Hz</span>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// SOLID STATIC  — fem_solid_static
// ══════════════════════════════════════════════════════════════════════════════

const ELEM_TYPES = ['tet4', 'tet10', 'hex8', 'hex20']

// Compact example mesh: 4-node tetrahedron (unit cube corner)
const DEFAULT_NODES = '0,0,0\n1,0,0\n0,1,0\n0,0,1'
const DEFAULT_ELEMS = '[{"kind":"tet4","node_indices":[0,1,2,3]}]'

function SolidStaticCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [E, setE]               = useState('200e9')
  const [nu, setNu]             = useState('0.3')
  const [rho, setRho]           = useState('7850')
  const [ys, setYs]             = useState('275e6')
  const [nodesStr, setNodesStr] = useState(DEFAULT_NODES)
  const [elemsStr, setElemsStr] = useState(DEFAULT_ELEMS)
  const [fixNode, setFixNode]   = useState('0')
  const [loadNode, setLoadNode] = useState('3')
  const [loadFy, setLoadFy]     = useState('1000')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  function handleRun() {
    let nodes, elements
    try {
      nodes    = nodesStr.split('\n').filter(l => l.trim()).map(l => l.split(',').map(Number))
      elements = JSON.parse(elemsStr)
    } catch (e) {
      return
    }
    const fixedNid = parseInt(fixNode, 10) || 0
    const loadNid  = parseInt(loadNode, 10) || nodes.length - 1
    run({
      analysis_type: 'solid_static',
      nodes,
      elements,
      E: parseFloat(E) || 200e9,
      nu: parseFloat(nu) || 0.3,
      density: parseFloat(rho) || 7850,
      yield_strength: parseFloat(ys) || 275e6,
      constraints: [{ node_id: fixedNid, dofs: [0.0, 0.0, 0.0] }],
      loads: [{ node_id: loadNid, force: [0, parseFloat(loadFy) || 1000, 0] }],
      // generic fallback for job queue
      material_props: {
        E: parseFloat(E) || 200e9,
        nu: parseFloat(nu) || 0.3,
        rho: parseFloat(rho) || 7850,
        yield_strength: parseFloat(ys) || 275e6,
      },
      boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
      loads_fallback: [{ type: 'force', face_tags: [2], value: parseFloat(loadFy) || 1000 }],
      mesh_size: 0.1,
      solver: 'fenicsx',
    })
  }

  const vmValues = Array.isArray(result?.element_vonmises_pa) ? result.element_vonmises_pa : []
  const dispNodes = Array.isArray(result?.node_displacements) ? result.node_displacements : []

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }}
      data-testid="solid-static-card">
      <SectionHeader icon={Grid3x3} label="Solid FEM — tet4/tet10/hex8/hex20 linear static" color="#38bdf8" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>E (Pa)</label>
          <input type="text" value={E} onChange={e => setE(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>ν</label>
          <input type="number" value={nu} step="0.01" min="0" max="0.49" onChange={e => setNu(e.target.value)} style={s.input} disabled={running} />
          <label style={{ ...s.label, width: 60 }}>ρ (kg/m³)</label>
          <input type="number" value={rho} onChange={e => setRho(e.target.value)} style={{ ...s.input, flex: '0 0 70px' }} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>σ_yield (Pa)</label>
          <input type="text" value={ys} onChange={e => setYs(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Fix node #</label>
          <input type="number" value={fixNode} min="0" onChange={e => setFixNode(e.target.value)} style={{ ...s.input, flex: '0 0 50px' }} disabled={running} />
          <label style={{ ...s.label, width: 60 }}>Load node #</label>
          <input type="number" value={loadNode} min="0" onChange={e => setLoadNode(e.target.value)} style={{ ...s.input, flex: '0 0 50px' }} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>Fy load (N)</label>
          <input type="number" value={loadFy} onChange={e => setLoadFy(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={{ ...s.sectionTitle }}>Nodes (x,y,z per line)</div>
        <textarea value={nodesStr} onChange={e => setNodesStr(e.target.value)}
          disabled={running} rows={3}
          style={{ ...s.input, flex: 'none', width: '100%', boxSizing: 'border-box', resize: 'vertical', fontFamily: 'inherit' }} />
        <div style={{ ...s.sectionTitle }}>Elements JSON array</div>
        <textarea value={elemsStr} onChange={e => setElemsStr(e.target.value)}
          disabled={running} rows={2}
          style={{ ...s.input, flex: 'none', width: '100%', boxSizing: 'border-box', resize: 'vertical', fontFamily: 'inherit' }} />
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#0369a1', ...(running ? s.buttonDisabled : {}) }}>
        {running
          ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Solving…</>
          : <><Play size={13} /> Run Solid Static</>}
      </button>
      {error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{error}</span></div>
      )}
      {(jobStatus === 'queued' || jobStatus === 'running') && !result && (
        <div style={s.infoBox}><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /><span>Assembling K, solving…</span></div>
      )}
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Solid Static Results</span></div>
          <table style={s.table}><tbody>
            {result.max_displacement_m != null && (
              <ResultRow label="Max displacement" value={fmtMm(result.max_displacement_m)} />
            )}
            {result.max_vonmises_stress_pa != null && (
              <ResultRow label="Max von Mises" value={fmtMPa(result.max_vonmises_stress_pa)} />
            )}
            {result.factor_of_safety != null && (
              <ResultRow label="Factor of Safety" value={Number(result.factor_of_safety).toFixed(3)} />
            )}
            {dispNodes.length > 0 && (
              <ResultRow label="Nodes solved" value={String(dispNodes.length)} />
            )}
            {vmValues.length > 0 && (
              <ResultRow label="Elements" value={String(vmValues.length)} />
            )}
          </tbody></table>
          <VonMisesContour
            vmValues={vmValues}
            maxVm={result.max_vonmises_stress_pa}
            yieldStrength={parseFloat(ys) || undefined}
          />
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// MODAL BEAM  — fem_modal_beam
// ══════════════════════════════════════════════════════════════════════════════

function ModalBeamCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [mode, setMode]       = useState('beam')
  const [E, setE]             = useState('200e9')
  const [I, setI]             = useState('8.33e-9')  // 10×10mm square
  const [A, setA]             = useState('1e-4')
  const [rho, setRho]         = useState('7850')
  const [L, setL]             = useState('1.0')
  const [nModes, setNModes]   = useState('4')
  const [nElem, setNElem]     = useState('12')
  const [bcType, setBcType]   = useState('cantilever')  // clamped-free
  // Plate params
  const [nu, setNu]           = useState('0.3')
  const [h, setH]             = useState('0.01')
  const [a, setA_p]           = useState('1.0')
  const [b, setB]             = useState('1.0')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  const BC_PRESETS = {
    cantilever:   [{ type: 'fixed', x: 0 }],
    'simply-supported': [{ type: 'pinned', x: 0 }, { type: 'pinned', x: parseFloat(L) || 1 }],
    'fixed-fixed': [{ type: 'fixed', x: 0 }, { type: 'fixed', x: parseFloat(L) || 1 }],
  }

  function handleRun() {
    if (mode === 'plate') {
      run({
        analysis_type: 'modal_beam',
        mode: 'plate',
        E: parseFloat(E) || 200e9,
        nu: parseFloat(nu) || 0.3,
        rho: parseFloat(rho) || 7850,
        h: parseFloat(h) || 0.01,
        a: parseFloat(a) || 1.0,
        b: parseFloat(b) || 1.0,
        // generic fallback
        material_props: { E: parseFloat(E) || 200e9, nu: parseFloat(nu) || 0.3, rho: parseFloat(rho) || 7850, yield_strength: 275e6 },
        boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
        loads: [],
        mesh_size: 0.1,
        solver: 'fenicsx',
      })
    } else {
      const supports = BC_PRESETS[bcType] || BC_PRESETS.cantilever
      run({
        analysis_type: 'modal_beam',
        mode: 'beam',
        E: parseFloat(E) || 200e9,
        I: parseFloat(I) || 8.33e-9,
        A: parseFloat(A) || 1e-4,
        rho: parseFloat(rho) || 7850,
        L: parseFloat(L) || 1.0,
        supports,
        n_elem: parseInt(nElem, 10) || 12,
        n_modes: parseInt(nModes, 10) || 4,
        // generic fallback
        material_props: { E: parseFloat(E) || 200e9, nu: 0.3, rho: parseFloat(rho) || 7850, yield_strength: 275e6 },
        boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
        loads: [],
        mesh_size: 0.05,
        solver: 'fenicsx',
      })
    }
  }

  const freqs = Array.isArray(result?.frequencies_hz) ? result.frequencies_hz
    : (result?.f_1_hz != null ? [result.f_1_hz] : [])

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }}
      data-testid="modal-beam-card">
      <SectionHeader icon={BarChart2} label="Modal — Hermite beam (consistent mass) / plate" color="#a78bfa" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Analysis</label>
          <select value={mode} onChange={e => setMode(e.target.value)} style={s.select} disabled={running}>
            <option value="beam">1-D Beam (Hermite FEM)</option>
            <option value="plate">Thin Plate (Blevins closed-form)</option>
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>E (Pa)</label>
          <input type="text" value={E} onChange={e => setE(e.target.value)} style={s.input} disabled={running} />
        </div>
        <div style={s.row}>
          <label style={s.label}>ρ (kg/m³)</label>
          <input type="number" value={rho} onChange={e => setRho(e.target.value)} style={s.input} disabled={running} />
        </div>

        {mode === 'beam' && (<>
          <div style={s.row}>
            <label style={s.label}>I (m⁴)</label>
            <input type="text" value={I} onChange={e => setI(e.target.value)} style={s.input} disabled={running} />
            <label style={{ ...s.label, width: 40 }}>A</label>
            <input type="text" value={A} onChange={e => setA(e.target.value)} style={{ ...s.input, flex: '0 0 80px' }} disabled={running} />
          </div>
          <div style={s.row}>
            <label style={s.label}>L (m)</label>
            <input type="number" value={L} step="0.1" onChange={e => setL(e.target.value)} style={s.input} disabled={running} />
          </div>
          <div style={s.row}>
            <label style={s.label}>BC</label>
            <select value={bcType} onChange={e => setBcType(e.target.value)} style={s.select} disabled={running}>
              <option value="cantilever">Cantilever (clamped-free)</option>
              <option value="simply-supported">Simply supported</option>
              <option value="fixed-fixed">Fixed-fixed</option>
            </select>
          </div>
          <div style={s.row}>
            <label style={s.label}>Modes</label>
            <input type="number" value={nModes} min="1" max="10" onChange={e => setNModes(e.target.value)} style={s.input} disabled={running} />
            <label style={{ ...s.label, width: 55 }}>Elements</label>
            <input type="number" value={nElem} min="4" max="40" onChange={e => setNElem(e.target.value)} style={{ ...s.input, flex: '0 0 50px' }} disabled={running} />
          </div>
        </>)}

        {mode === 'plate' && (<>
          <div style={s.row}>
            <label style={s.label}>ν</label>
            <input type="number" value={nu} step="0.01" min="0" max="0.49" onChange={e => setNu(e.target.value)} style={s.input} disabled={running} />
            <label style={{ ...s.label, width: 50 }}>h (m)</label>
            <input type="number" value={h} step="0.001" onChange={e => setH(e.target.value)} style={{ ...s.input, flex: '0 0 70px' }} disabled={running} />
          </div>
          <div style={s.row}>
            <label style={s.label}>a (m)</label>
            <input type="number" value={a} step="0.1" onChange={e => setA_p(e.target.value)} style={s.input} disabled={running} />
            <label style={{ ...s.label, width: 40 }}>b</label>
            <input type="number" value={b} step="0.1" onChange={e => setB(e.target.value)} style={{ ...s.input, flex: '0 0 70px' }} disabled={running} />
          </div>
        </>)}
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#4c1d95', ...(running ? s.buttonDisabled : {}) }}>
        {running
          ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Eigensolve…</>
          : <><Play size={13} /> Run Modal</>}
      </button>
      {error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{error}</span></div>
      )}
      {(jobStatus === 'queued' || jobStatus === 'running') && !result && (
        <div style={s.infoBox}><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /><span>K φ = ω² M φ…</span></div>
      )}
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Modal Results</span></div>
          {freqs.length > 0 && (
            <table style={s.table}>
              <thead><tr>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>Mode</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>f (Hz)</td>
                <td style={{ ...s.td, color: '#9ca3af', fontSize: 11 }}>ω (rad/s)</td>
              </tr></thead>
              <tbody>
                {freqs.map((f, i) => {
                  const omega = result.omega_rad_s?.[i] ?? (2 * Math.PI * f)
                  return (
                    <tr key={i}>
                      <td style={s.td}>{i + 1}</td>
                      <td style={{ ...s.td, ...s.mono }}>{Number(f).toFixed(3)}</td>
                      <td style={{ ...s.td, ...s.mono }}>{Number(omega).toFixed(2)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
          {result.flexural_rigidity_D != null && (
            <ResultRow label="D (N·m)" value={fmtSci(result.flexural_rigidity_D)} />
          )}
          <FrequencySpectrum freqs={freqs} />
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// BEAM STATIC  — fem_linear_static_beam
// ══════════════════════════════════════════════════════════════════════════════

function BeamStaticCard({ projectId, fileId }) {
  const { running, status, error, run } = useFemJob({ projectId, fileId })
  const [analysis, setAnalysis] = useState('beam')
  const [E, setE]               = useState('200e9')
  const [I, setI]               = useState('8.33e-9')
  const [A, setA]               = useState('1e-4')
  const [L, setL]               = useState('1.0')
  const [q, setQ]               = useState('1000')    // distributed load N/m
  const [Pload, setPload]       = useState('5000')    // point load N
  const [xLoad, setXLoad]       = useState('0.5')
  const [bcPreset, setBcPreset] = useState('cantilever')
  // Thermal
  const [alpha, setAlpha]       = useState('12e-6')
  const [dT, setDT]             = useState('50')
  const [nElem, setNElem]       = useState('20')

  const result    = status?.result && typeof status.result === 'object' ? status.result : null
  const jobStatus = status?.status

  const BC_MAP = {
    cantilever:       [{ type: 'fixed', x: 0 }],
    'simply-supported': (lv) => [{ type: 'pinned', x: 0 }, { type: 'roller', x: lv }],
    'fixed-fixed':    (lv) => [{ type: 'fixed', x: 0 }, { type: 'fixed', x: lv }],
  }

  function getSupports() {
    const lv = parseFloat(L) || 1.0
    const bc = BC_MAP[bcPreset]
    return typeof bc === 'function' ? bc(lv) : bc
  }

  function handleRun() {
    const supports = getSupports()
    const Lv = parseFloat(L) || 1.0
    if (analysis === 'beam') {
      run({
        analysis_type: 'beam_static',
        analysis: 'beam',
        E: parseFloat(E) || 200e9,
        I: parseFloat(I) || 8.33e-9,
        L: Lv,
        supports,
        point_loads: [{ x: parseFloat(xLoad) || Lv / 2, F: parseFloat(Pload) || 5000 }],
        distributed_load: parseFloat(q) || 0,
        n_elem: parseInt(nElem, 10) || 20,
        // generic fallback
        material_props: { E: parseFloat(E) || 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
        boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
        loads: [{ type: 'force', face_tags: [2], value: parseFloat(Pload) || 5000 }],
        mesh_size: 0.05,
        solver: 'fenicsx',
      })
    } else if (analysis === 'axial_bar') {
      run({
        analysis_type: 'beam_static',
        analysis: 'axial_bar',
        E: parseFloat(E) || 200e9,
        A: parseFloat(A) || 1e-4,
        L: Lv,
        supports,
        point_loads: [{ x: Lv, F: parseFloat(Pload) || 5000 }],
        distributed_load: parseFloat(q) || 0,
        n_elem: parseInt(nElem, 10) || 20,
        material_props: { E: parseFloat(E) || 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
        boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
        loads: [{ type: 'force', face_tags: [2], value: parseFloat(Pload) || 5000 }],
        mesh_size: 0.05,
        solver: 'fenicsx',
      })
    } else {  // thermal_bar
      run({
        analysis_type: 'beam_static',
        analysis: 'thermal_bar',
        E: parseFloat(E) || 200e9,
        A: parseFloat(A) || 1e-4,
        L: Lv,
        alpha: parseFloat(alpha) || 12e-6,
        dT: parseFloat(dT) || 50,
        supports: [{ type: 'fixed', x: 0 }, { type: 'fixed', x: Lv }],
        n_elem: 1,
        material_props: { E: parseFloat(E) || 200e9, nu: 0.3, rho: 7850, yield_strength: 275e6 },
        boundary_conditions: [{ type: 'fixed', face_tags: [1] }],
        loads: [],
        mesh_size: 0.1,
        solver: 'fenicsx',
      })
    }
  }

  return (
    <div style={{ ...s.root, background: '#0f172a', borderRadius: 6, padding: 12 }}
      data-testid="beam-static-card">
      <SectionHeader icon={Thermometer} label="1-D Beam/Bar Static (Euler-Bernoulli)" color="#34d399" />
      <div style={s.section}>
        <div style={s.row}>
          <label style={s.label}>Analysis</label>
          <select value={analysis} onChange={e => setAnalysis(e.target.value)} style={s.select} disabled={running}>
            <option value="beam">Euler-Bernoulli beam</option>
            <option value="axial_bar">Axial bar</option>
            <option value="thermal_bar">Thermal stress bar</option>
          </select>
        </div>
        <div style={s.row}>
          <label style={s.label}>E (Pa)</label>
          <input type="text" value={E} onChange={e => setE(e.target.value)} style={s.input} disabled={running} />
        </div>
        {(analysis === 'beam') && (
          <div style={s.row}>
            <label style={s.label}>I (m⁴)</label>
            <input type="text" value={I} onChange={e => setI(e.target.value)} style={s.input} disabled={running} />
          </div>
        )}
        {(analysis === 'axial_bar' || analysis === 'thermal_bar') && (
          <div style={s.row}>
            <label style={s.label}>A (m²)</label>
            <input type="text" value={A} onChange={e => setA(e.target.value)} style={s.input} disabled={running} />
          </div>
        )}
        <div style={s.row}>
          <label style={s.label}>L (m)</label>
          <input type="number" value={L} step="0.1" onChange={e => setL(e.target.value)} style={s.input} disabled={running} />
        </div>
        {analysis !== 'thermal_bar' && (<>
          <div style={s.row}>
            <label style={s.label}>BC type</label>
            <select value={bcPreset} onChange={e => setBcPreset(e.target.value)} style={s.select} disabled={running}>
              <option value="cantilever">Cantilever</option>
              <option value="simply-supported">Simply supported</option>
              <option value="fixed-fixed">Fixed-fixed</option>
            </select>
          </div>
          <div style={s.row}>
            <label style={s.label}>UDL q (N/m)</label>
            <input type="number" value={q} onChange={e => setQ(e.target.value)} style={s.input} disabled={running} />
          </div>
          <div style={s.row}>
            <label style={s.label}>Point load (N)</label>
            <input type="number" value={Pload} onChange={e => setPload(e.target.value)} style={s.input} disabled={running} />
            <label style={{ ...s.label, width: 40 }}>@ x=</label>
            <input type="number" value={xLoad} step="0.1" onChange={e => setXLoad(e.target.value)} style={{ ...s.input, flex: '0 0 60px' }} disabled={running} />
          </div>
          <div style={s.row}>
            <label style={s.label}>Elements</label>
            <input type="number" value={nElem} min="2" max="100" onChange={e => setNElem(e.target.value)} style={s.input} disabled={running} />
          </div>
        </>)}
        {analysis === 'thermal_bar' && (<>
          <div style={s.row}>
            <label style={s.label}>α (1/K)</label>
            <input type="text" value={alpha} onChange={e => setAlpha(e.target.value)} style={s.input} disabled={running} />
          </div>
          <div style={s.row}>
            <label style={s.label}>ΔT (K)</label>
            <input type="number" value={dT} onChange={e => setDT(e.target.value)} style={s.input} disabled={running} />
          </div>
        </>)}
      </div>
      <button onClick={handleRun} disabled={running || !projectId || !fileId}
        style={{ ...s.button, background: '#065f46', ...(running ? s.buttonDisabled : {}) }}>
        {running
          ? <><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> Solving…</>
          : <><Play size={13} /> Run Beam/Bar</>}
      </button>
      {error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{error}</span></div>
      )}
      {(jobStatus === 'queued' || jobStatus === 'running') && !result && (
        <div style={s.infoBox}><Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /><span>Assembling elements…</span></div>
      )}
      {result && jobStatus === 'done' && (
        <div style={s.section}>
          <div style={s.sectionTitle}><CheckCircle size={12} style={{ color: '#34d399' }} /><span>Results</span></div>
          <table style={s.table}><tbody>
            {result.max_deflection_m != null && (
              <ResultRow label="Max deflection" value={fmtMm(result.max_deflection_m)} />
            )}
            {result.max_displacement_m != null && (
              <ResultRow label="Max displacement" value={fmtMm(result.max_displacement_m)} />
            )}
            {result.thermal_stress_pa != null && (
              <ResultRow label="Thermal stress" value={fmtMPa(result.thermal_stress_pa)} />
            )}
            {result.reactions && Object.entries(result.reactions).map(([k, v]) => (
              <ResultRow key={k}
                label={`R @ x=${k}`}
                value={`R=${typeof v === 'object' ? fmtSci(v.R ?? v, 'N') : fmtSci(v, 'N')}`}
              />
            ))}
          </tbody></table>
          {result.deflection_profile && result.x_coords && (
            <DeflectionPlot x={result.x_coords} w={result.deflection_profile} label="Deflection profile" />
          )}
        </div>
      )}
      {jobStatus === 'error' && status?.error && (
        <div style={s.errorBox} role="alert"><AlertTriangle size={13} /><span>{status.error}</span></div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TOP-LEVEL SOLID FEM PANEL
// ══════════════════════════════════════════════════════════════════════════════

const SOLID_SECTIONS = [
  { id: 'solid',  label: 'Solid Static',   color: '#38bdf8' },
  { id: 'modal',  label: 'Modal Beam',     color: '#a78bfa' },
  { id: 'beam',   label: 'Beam/Bar Static', color: '#34d399' },
]

/**
 * SolidFEMPanel — Solid tet/hex FEM + modal beam + 1-D beam/bar static.
 *
 * Closes the manifest gap: "FE — solid (tet/hex) solver" and
 * "FE — 1D beam / 2D truss (native)" and "Modal / buckling" — backend-only.
 *
 * Props: { projectId, fileId }
 */
export default function SolidFEMPanel({ projectId, fileId }) {
  const [active, setActive] = useState('solid')

  return (
    <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 13 }}
      data-testid="solid-fem-panel">
      <div
        style={{ display: 'flex', gap: 0, borderBottom: '1px solid #1f2937', background: '#0f172a', overflowX: 'auto' }}
        role="tablist"
        aria-label="Solid FEM sections"
      >
        {SOLID_SECTIONS.map(sec => {
          const isActive = active === sec.id
          return (
            <button
              key={sec.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={`solid-fem-panel-${sec.id}`}
              id={`solid-fem-tab-${sec.id}`}
              onClick={() => setActive(sec.id)}
              style={{
                padding: '7px 12px',
                background: 'none',
                border: 'none',
                borderBottom: isActive ? `2px solid ${sec.color}` : '2px solid transparent',
                color: isActive ? sec.color : '#6b7280',
                cursor: 'pointer',
                fontSize: 11,
                fontWeight: isActive ? 700 : 400,
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
                whiteSpace: 'nowrap',
                fontFamily: 'inherit',
              }}
            >
              {sec.label}
            </button>
          )
        })}
      </div>

      <div style={{ padding: '12px 0 0 0', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {active === 'solid' && (
          <div role="tabpanel" id="solid-fem-panel-solid" aria-labelledby="solid-fem-tab-solid">
            <SolidStaticCard projectId={projectId} fileId={fileId} />
          </div>
        )}
        {active === 'modal' && (
          <div role="tabpanel" id="solid-fem-panel-modal" aria-labelledby="solid-fem-tab-modal">
            <ModalBeamCard projectId={projectId} fileId={fileId} />
          </div>
        )}
        {active === 'beam' && (
          <div role="tabpanel" id="solid-fem-panel-beam" aria-labelledby="solid-fem-tab-beam">
            <BeamStaticCard projectId={projectId} fileId={fileId} />
          </div>
        )}
      </div>
    </div>
  )
}
