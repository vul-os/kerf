// AssemblyClashPanel.jsx — assembly-level interference / clash workflow.
//
// Four tabs wired to backend LLM tools:
//   • Component Pairs     — brep_assembly_interference (2-body, exact)
//   • Whole-Assembly Sweep— brep_assembly_interference (all pairs, BVH sweep)
//   • Clearance Check     — brep_check_clearance (min-distance vector)
//   • Motion Clash        — brep_assembly_interference stepped through motion frames
//
// Additional tools available from context:
//   assembly_solve, assembly_bom, brep_check_clash_aware_routing
//
// All tools dispatch via POST /api/tools/call (routes_tools.py).
// Props: { projectId?: string }

import { useState, useCallback, useRef } from 'react'
import {
  AlertTriangle, CheckCircle, ChevronDown, ChevronRight,
  Play, Loader2, X, RotateCcw, Layers, Activity,
  Ruler, Move3d, ZoomIn, ToggleLeft, ToggleRight,
  ShieldAlert, ShieldCheck, Shield, Info,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Palette — dark mono matching GeometryInspector
// ---------------------------------------------------------------------------

const p = {
  root: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: 13,
    color: '#e5e7eb',
    background: '#0d1117',
    minHeight: '100vh',
    padding: '24px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
  },
  pageHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    paddingBottom: 16,
    borderBottom: '1px solid #1f2937',
  },
  pageTitle: { fontSize: 18, fontWeight: 700, color: '#f3f4f6' },
  pageSub: { fontSize: 11, color: '#6b7280', marginTop: 2 },
  tabBar: {
    display: 'flex',
    gap: 2,
    borderBottom: '1px solid #1f2937',
    marginBottom: 16,
  },
  tab: (active) => ({
    padding: '7px 14px',
    fontSize: 12,
    fontWeight: 600,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    background: active ? '#161b26' : 'transparent',
    color: active ? '#22d3ee' : '#6b7280',
    border: 'none',
    borderBottom: active ? '2px solid #22d3ee' : '2px solid transparent',
    cursor: 'pointer',
    letterSpacing: '0.04em',
    transition: 'color 0.15s',
  }),
  panel: {
    background: '#111827',
    borderRadius: 8,
    border: '1px solid #1f2937',
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
  },
  fieldRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  label: {
    fontSize: 11,
    color: '#9ca3af',
    width: 130,
    flexShrink: 0,
  },
  input: {
    flex: 1,
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#e5e7eb',
    padding: '4px 7px',
    fontSize: 11,
    outline: 'none',
    fontFamily: 'inherit',
  },
  select: {
    flex: 1,
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#e5e7eb',
    padding: '4px 7px',
    fontSize: 11,
    outline: 'none',
    fontFamily: 'inherit',
  },
  textarea: {
    flex: 1,
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#e5e7eb',
    padding: '4px 7px',
    fontSize: 11,
    outline: 'none',
    fontFamily: 'inherit',
    height: 52,
    resize: 'vertical',
  },
  runBtn: (disabled) => ({
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    padding: '5px 12px',
    background: disabled ? '#1f2937' : '#0e7490',
    border: 'none',
    borderRadius: 4,
    color: disabled ? '#6b7280' : '#fff',
    fontSize: 11,
    fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'inherit',
    alignSelf: 'flex-start',
    opacity: disabled ? 0.6 : 1,
  }),
  clearBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '5px 10px',
    background: 'transparent',
    border: '1px solid #374151',
    borderRadius: 4,
    color: '#9ca3af',
    fontSize: 11,
    cursor: 'pointer',
    fontFamily: 'inherit',
  },
  btnRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
  },
  errorBox: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 6,
    background: '#1f0707',
    border: '1px solid #7f1d1d',
    borderRadius: 4,
    padding: '6px 10px',
    color: '#fca5a5',
    fontSize: 11,
  },
  infoBox: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 6,
    background: '#0a1628',
    border: '1px solid #1e3a5f',
    borderRadius: 4,
    padding: '6px 10px',
    color: '#93c5fd',
    fontSize: 11,
  },
  divider: {
    borderTop: '1px solid #1f2937',
    margin: '4px 0',
  },
  sectionLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: '#6b7280',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    marginBottom: 4,
  },
  toggle: (on) => ({
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    padding: '3px 8px',
    background: on ? '#14532d22' : '#1f2937',
    border: `1px solid ${on ? '#16a34a55' : '#374151'}`,
    borderRadius: 9999,
    color: on ? '#4ade80' : '#9ca3af',
    fontSize: 11,
    cursor: 'pointer',
    fontFamily: 'inherit',
    userSelect: 'none',
  }),
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const API_URL = typeof import.meta !== 'undefined' && import.meta.env
  ? (import.meta.env.VITE_API_URL || '')
  : ''

async function callTool(toolName, args, projectId) {
  const body = { tool: toolName, args }
  if (projectId) body.project_id = projectId
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const txt = await res.text()
    throw new Error(`${res.status}: ${txt}`)
  }
  const data = await res.json()
  if (typeof data.result === 'string') {
    try { return JSON.parse(data.result) } catch { return data.result }
  }
  return data.result ?? data
}

function tryParseJson(str) {
  try { return JSON.parse(str) } catch { return str }
}

function fmtMm(val) {
  if (val == null) return '—'
  const n = parseFloat(val)
  return isNaN(n) ? String(val) : `${n.toFixed(4)} mm`
}

function fmtVol(val) {
  if (val == null) return '—'
  const n = parseFloat(val)
  return isNaN(n) ? String(val) : `${n.toFixed(6)} mm³`
}

// ---------------------------------------------------------------------------
// Severity badge
// ---------------------------------------------------------------------------

function SeverityBadge({ volume }) {
  const v = parseFloat(volume)
  if (isNaN(v) || v <= 0) {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 3,
        background: '#14532d22', border: '1px solid #16a34a55',
        color: '#4ade80', borderRadius: 9999, padding: '1px 7px', fontSize: 10, fontWeight: 700,
      }}>
        <ShieldCheck size={9} /> OK
      </span>
    )
  }
  let color, bg, border, label
  if (v < 1) { color = '#fbbf24'; bg = '#451a0322'; border = '#92400e55'; label = 'MINOR' }
  else if (v < 100) { color = '#f97316'; bg = '#431a0322'; border = '#9a3412aa'; label = 'MODERATE' }
  else { color = '#ef4444'; bg = '#450a0a22'; border = '#991b1baa'; label = 'SEVERE' }
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 3,
      background: bg, border: `1px solid ${border}`,
      color, borderRadius: 9999, padding: '1px 7px', fontSize: 10, fontWeight: 700,
    }}>
      <ShieldAlert size={9} /> {label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Clash SVG pair icon
// ---------------------------------------------------------------------------

function ClashIcon({ size = 32 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      {/* Left body */}
      <rect x="2" y="8" width="14" height="16" rx="2" fill="#1e3a5f" stroke="#3b82f6" strokeWidth="1.5" />
      {/* Right body */}
      <rect x="16" y="8" width="14" height="16" rx="2" fill="#3b0a0a" stroke="#ef4444" strokeWidth="1.5" />
      {/* Overlap zone */}
      <rect x="16" y="9" width="7" height="14" fill="#7f1d1d" opacity="0.7" />
      {/* Clash marker */}
      <line x1="19.5" y1="13" x2="19.5" y2="19" stroke="#fbbf24" strokeWidth="2" strokeLinecap="round" />
      <line x1="16.5" y1="16" x2="22.5" y2="16" stroke="#fbbf24" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

function ClearanceIcon({ size = 32 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      {/* Left body */}
      <rect x="2" y="8" width="11" height="16" rx="2" fill="#1e3a5f" stroke="#3b82f6" strokeWidth="1.5" />
      {/* Right body */}
      <rect x="19" y="8" width="11" height="16" rx="2" fill="#1e3a5f" stroke="#3b82f6" strokeWidth="1.5" />
      {/* Gap arrow */}
      <line x1="13" y1="16" x2="19" y2="16" stroke="#22d3ee" strokeWidth="1.5" />
      <polyline points="15,13 13,16 15,19" stroke="#22d3ee" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <polyline points="17,13 19,16 17,19" stroke="#22d3ee" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Result table for interference list
// ---------------------------------------------------------------------------

function InterferenceTable({ rows }) {
  if (!rows || rows.length === 0) {
    return (
      <div style={{ ...p.infoBox, marginTop: 8 }}>
        <CheckCircle size={12} style={{ flexShrink: 0, marginTop: 1, color: '#4ade80' }} />
        <span style={{ color: '#4ade80' }}>No interferences found — assembly is clean.</span>
      </div>
    )
  }
  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table style={{
        width: '100%', borderCollapse: 'collapse', fontSize: 11,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      }}>
        <thead>
          <tr style={{ background: '#161b26', color: '#9ca3af' }}>
            <th style={{ padding: '5px 8px', textAlign: 'left', borderBottom: '1px solid #1f2937', whiteSpace: 'nowrap' }}>#</th>
            <th style={{ padding: '5px 8px', textAlign: 'left', borderBottom: '1px solid #1f2937' }}>Body A</th>
            <th style={{ padding: '5px 8px', textAlign: 'left', borderBottom: '1px solid #1f2937' }}>Body B</th>
            <th style={{ padding: '5px 8px', textAlign: 'right', borderBottom: '1px solid #1f2937', whiteSpace: 'nowrap' }}>Overlap Vol</th>
            <th style={{ padding: '5px 8px', textAlign: 'right', borderBottom: '1px solid #1f2937', whiteSpace: 'nowrap' }}>Faces</th>
            <th style={{ padding: '5px 8px', textAlign: 'center', borderBottom: '1px solid #1f2937' }}>Severity</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ background: i % 2 === 0 ? '#0d1117' : '#111827' }}>
              <td style={{ padding: '4px 8px', color: '#6b7280' }}>{i + 1}</td>
              <td style={{ padding: '4px 8px', color: '#93c5fd', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.body_a ?? r.component_a ?? '—'}
              </td>
              <td style={{ padding: '4px 8px', color: '#93c5fd', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.body_b ?? r.component_b ?? '—'}
              </td>
              <td style={{ padding: '4px 8px', textAlign: 'right', color: '#e5e7eb' }}>
                {fmtVol(r.overlap_volume ?? r.penetration_volume ?? r.volume)}
              </td>
              <td style={{ padding: '4px 8px', textAlign: 'right', color: '#e5e7eb' }}>
                {r.face_count ?? r.faces ?? '—'}
              </td>
              <td style={{ padding: '4px 8px', textAlign: 'center' }}>
                <SeverityBadge volume={r.overlap_volume ?? r.penetration_volume ?? r.volume ?? 0} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// RawResult — fallback JSON viewer
// ---------------------------------------------------------------------------

function RawResult({ data }) {
  if (!data) return null
  const text = typeof data === 'object' ? JSON.stringify(data, null, 2) : String(data)
  return (
    <pre style={{
      background: '#0a0f1a', border: '1px solid #1f2937', borderRadius: 4,
      padding: '8px 10px', fontSize: 11, color: '#a3e635',
      whiteSpace: 'pre-wrap', wordBreak: 'break-all',
      maxHeight: 220, overflowY: 'auto', margin: 0,
    }}>
      {text}
    </pre>
  )
}

// ---------------------------------------------------------------------------
// Tab: Component Pairs
// ---------------------------------------------------------------------------

function ComponentPairsTab({ projectId }) {
  const [bodyAJson, setBodyAJson] = useState('')
  const [bodyBJson, setBodyBJson] = useState('')
  const [method, setMethod] = useState('boolean')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function run() {
    setRunning(true); setResult(null); setError(null)
    try {
      const args = {
        body_a: tryParseJson(bodyAJson),
        body_b: tryParseJson(bodyBJson),
        method,
      }
      const res = await callTool('brep_assembly_interference', args, projectId)
      setResult(res)
    } catch (e) { setError(e.message) }
    finally { setRunning(false) }
  }

  // Normalize result into row list
  const rows = result
    ? (Array.isArray(result.interferences) ? result.interferences
      : Array.isArray(result) ? result
      : result.overlap_volume != null ? [{ body_a: 'A', body_b: 'B', ...result }]
      : null)
    : null

  return (
    <div style={p.panel}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <ClashIcon size={36} />
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#f3f4f6' }}>Component Pair Check</div>
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
            Möller–Trumbore triangle-triangle + AABB BVH solver. Returns overlap volume and
            interfering face count for two selected bodies.
          </div>
        </div>
      </div>

      <div style={p.divider} />

      <div style={p.fieldRow}>
        <label style={p.label}>Body A JSON</label>
        <textarea
          value={bodyAJson}
          onChange={(e) => setBodyAJson(e.target.value)}
          style={p.textarea}
          placeholder='{"type":"Body","faces":[...]}  or  file_id / component_ref'
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Body B JSON</label>
        <textarea
          value={bodyBJson}
          onChange={(e) => setBodyBJson(e.target.value)}
          style={p.textarea}
          placeholder='{"type":"Body","faces":[...]}  or  file_id / component_ref'
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Detection method</label>
        <select value={method} onChange={(e) => setMethod(e.target.value)} style={p.select} disabled={running}>
          <option value="boolean">Boolean (exact — OBB-SAT)</option>
          <option value="monte_carlo">Monte Carlo (sampling)</option>
          <option value="voxel">Voxel (fast approximate)</option>
        </select>
      </div>

      <div style={p.btnRow}>
        <button
          onClick={run}
          disabled={running || (!bodyAJson && !bodyBJson)}
          style={p.runBtn(running || (!bodyAJson && !bodyBJson))}
        >
          {running
            ? <><Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} /> Checking…</>
            : <><Play size={11} /> Check Interference</>}
        </button>
        {(result || error) && (
          <button onClick={() => { setResult(null); setError(null) }} style={p.clearBtn}>
            <RotateCcw size={10} /> Reset
          </button>
        )}
      </div>

      {error && (
        <div style={p.errorBox} role="alert">
          <AlertTriangle size={12} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      )}

      {result && !error && (
        <>
          {rows ? <InterferenceTable rows={rows} /> : <RawResult data={result} />}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Whole-Assembly Sweep
// ---------------------------------------------------------------------------

function WholeSweepTab({ projectId }) {
  const [fileId, setFileId] = useState('')
  const [method, setMethod] = useState('boolean')
  const [topN, setTopN] = useState('10')
  const [excludeFasteners, setExcludeFasteners] = useState(false)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function run() {
    setRunning(true); setResult(null); setError(null)
    try {
      const args = {
        file_id: fileId || undefined,
        method,
        top_n: parseInt(topN, 10) || 10,
        exclude_fasteners: excludeFasteners,
      }
      const res = await callTool('brep_assembly_interference', args, projectId)
      setResult(res)
    } catch (e) { setError(e.message) }
    finally { setRunning(false) }
  }

  const rows = result
    ? (Array.isArray(result.interferences) ? result.interferences
      : Array.isArray(result) ? result : null)
    : null

  const totalCount = result?.total_pair_count ?? result?.pairs_checked
  const summary = result?.summary

  return (
    <div style={p.panel}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <Layers size={32} style={{ color: '#a78bfa', flexShrink: 0, marginTop: 2 }} />
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#f3f4f6' }}>Whole-Assembly Sweep</div>
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
            Iterate all body pairs in the assembly using BVH broad-phase + exact narrow-phase.
            Reports top-N worst interferences by overlap volume.
          </div>
        </div>
      </div>

      <div style={p.divider} />

      <div style={p.fieldRow}>
        <label style={p.label}>Assembly file ID</label>
        <input
          type="text"
          value={fileId}
          onChange={(e) => setFileId(e.target.value)}
          style={p.input}
          placeholder="uuid (leave blank for active project assembly)"
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Detection method</label>
        <select value={method} onChange={(e) => setMethod(e.target.value)} style={p.select} disabled={running}>
          <option value="boolean">Boolean (exact — OBB-SAT)</option>
          <option value="monte_carlo">Monte Carlo (sampling)</option>
          <option value="voxel">Voxel (fast approximate)</option>
        </select>
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Report top N</label>
        <input
          type="number"
          value={topN}
          onChange={(e) => setTopN(e.target.value)}
          style={{ ...p.input, maxWidth: 80 }}
          min={1} max={200}
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Exclude fasteners</label>
        <button
          type="button"
          onClick={() => setExcludeFasteners((v) => !v)}
          style={p.toggle(excludeFasteners)}
          disabled={running}
          aria-pressed={excludeFasteners}
        >
          {excludeFasteners
            ? <><ToggleRight size={11} /> Fasteners excluded</>
            : <><ToggleLeft size={11} /> Include fasteners</>}
        </button>
      </div>

      <div style={p.btnRow}>
        <button
          onClick={run}
          disabled={running}
          style={p.runBtn(running)}
        >
          {running
            ? <><Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} /> Sweeping…</>
            : <><Play size={11} /> Run Assembly Sweep</>}
        </button>
        {(result || error) && (
          <button onClick={() => { setResult(null); setError(null) }} style={p.clearBtn}>
            <RotateCcw size={10} /> Reset
          </button>
        )}
      </div>

      {error && (
        <div style={p.errorBox} role="alert">
          <AlertTriangle size={12} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      )}

      {result && !error && (
        <>
          {(totalCount != null || summary) && (
            <div style={p.infoBox}>
              <Info size={12} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                {totalCount != null && <>Checked {totalCount} pairs. </>}
                {summary && <>{summary}</>}
                {rows && rows.length > 0 && <> Showing top {rows.length} interferences by volume.</>}
              </span>
            </div>
          )}
          {rows ? <InterferenceTable rows={rows} /> : <RawResult data={result} />}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Clearance Check
// ---------------------------------------------------------------------------

function ClearanceTab({ projectId }) {
  const [bodyAJson, setBodyAJson] = useState('')
  const [bodyBJson, setBodyBJson] = useState('')
  const [minClearance, setMinClearance] = useState('0.5')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function run() {
    setRunning(true); setResult(null); setError(null)
    try {
      const args = {
        body_a: tryParseJson(bodyAJson),
        body_b: tryParseJson(bodyBJson),
        min_clearance: parseFloat(minClearance) || 0.5,
      }
      const res = await callTool('brep_check_clearance', args, projectId)
      setResult(res)
    } catch (e) { setError(e.message) }
    finally { setRunning(false) }
  }

  const dist = result?.min_distance ?? result?.distance ?? result?.clearance
  const vec = result?.closest_vector ?? result?.vector
  const pass = result?.pass ?? result?.ok

  return (
    <div style={p.panel}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <ClearanceIcon size={36} />
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#f3f4f6' }}>Clearance Check</div>
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
            Minimum signed distance between two bodies — closest approach vector and magnitude.
            Negative distance means interpenetration.
          </div>
        </div>
      </div>

      <div style={p.divider} />

      <div style={p.fieldRow}>
        <label style={p.label}>Body A JSON</label>
        <textarea
          value={bodyAJson}
          onChange={(e) => setBodyAJson(e.target.value)}
          style={p.textarea}
          placeholder='{"type":"Body","faces":[...]}  or  file_id / component_ref'
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Body B JSON</label>
        <textarea
          value={bodyBJson}
          onChange={(e) => setBodyBJson(e.target.value)}
          style={p.textarea}
          placeholder='{"type":"Body","faces":[...]}  or  file_id / component_ref'
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Min clearance (mm)</label>
        <input
          type="number"
          value={minClearance}
          onChange={(e) => setMinClearance(e.target.value)}
          style={{ ...p.input, maxWidth: 100 }}
          step="0.1"
          disabled={running}
        />
      </div>

      <div style={p.btnRow}>
        <button
          onClick={run}
          disabled={running || (!bodyAJson && !bodyBJson)}
          style={p.runBtn(running || (!bodyAJson && !bodyBJson))}
        >
          {running
            ? <><Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} /> Measuring…</>
            : <><Ruler size={11} /> Measure Clearance</>}
        </button>
        {(result || error) && (
          <button onClick={() => { setResult(null); setError(null) }} style={p.clearBtn}>
            <RotateCcw size={10} /> Reset
          </button>
        )}
      </div>

      {error && (
        <div style={p.errorBox} role="alert">
          <AlertTriangle size={12} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      )}

      {result && !error && (
        <div style={{
          background: '#0a0f1a', border: '1px solid #1f2937', borderRadius: 6,
          padding: 12, display: 'flex', flexDirection: 'column', gap: 8,
        }}>
          {/* Pass/fail banner */}
          {pass != null && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '5px 10px', borderRadius: 4,
              background: pass ? '#14532d22' : '#450a0a22',
              border: `1px solid ${pass ? '#16a34a55' : '#991b1baa'}`,
            }}>
              {pass
                ? <ShieldCheck size={13} style={{ color: '#4ade80' }} />
                : <ShieldAlert size={13} style={{ color: '#ef4444' }} />}
              <span style={{ fontWeight: 600, fontSize: 12, color: pass ? '#4ade80' : '#ef4444' }}>
                {pass ? 'CLEARANCE OK' : 'CLEARANCE VIOLATION'}
              </span>
            </div>
          )}

          {/* Distance metric */}
          {dist != null && (
            <div style={p.fieldRow}>
              <span style={p.label}>Min distance</span>
              <span style={{
                fontSize: 15, fontWeight: 700,
                color: parseFloat(dist) < 0 ? '#ef4444' : parseFloat(dist) < parseFloat(minClearance) ? '#f59e0b' : '#4ade80',
              }}>
                {fmtMm(dist)}
              </span>
            </div>
          )}

          {/* Closest vector */}
          {vec != null && (
            <div style={p.fieldRow}>
              <span style={p.label}>Closest vector</span>
              <span style={{ color: '#22d3ee', fontSize: 12 }}>
                [{Array.isArray(vec)
                  ? vec.map((c) => parseFloat(c).toFixed(4)).join(', ')
                  : String(vec)}]
              </span>
            </div>
          )}

          {/* Any remaining fields */}
          {typeof result === 'object' && Object.keys(result).some((k) =>
            !['min_distance', 'distance', 'clearance', 'closest_vector', 'vector', 'pass', 'ok'].includes(k)
          ) && (
            <details style={{ marginTop: 4 }}>
              <summary style={{ fontSize: 11, color: '#6b7280', cursor: 'pointer' }}>Full response</summary>
              <RawResult data={result} />
            </details>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab: Motion Clash
// ---------------------------------------------------------------------------

function MotionClashTab({ projectId }) {
  const [bodyAJson, setBodyAJson] = useState('')
  const [bodyBJson, setBodyBJson] = useState('')
  const [axis, setAxis] = useState('[1,0,0]')
  const [rangeFrom, setRangeFrom] = useState('0')
  const [rangeTo, setRangeTo] = useState('90')
  const [steps, setSteps] = useState('12')
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(null)   // {current, total}
  const [frames, setFrames] = useState([])          // per-frame results
  const [error, setError] = useState(null)
  const cancelRef = useRef(false)

  async function run() {
    setRunning(true); setFrames([]); setError(null); setProgress(null)
    cancelRef.current = false
    try {
      const nSteps = Math.max(2, parseInt(steps, 10) || 12)
      const from = parseFloat(rangeFrom) || 0
      const to = parseFloat(rangeTo) || 90
      const axisVec = tryParseJson(axis)
      const frameResults = []

      for (let i = 0; i < nSteps; i++) {
        if (cancelRef.current) break
        const angle = from + (i / (nSteps - 1)) * (to - from)
        setProgress({ current: i + 1, total: nSteps })
        try {
          const args = {
            body_a: tryParseJson(bodyAJson),
            body_b: tryParseJson(bodyBJson),
            method: 'boolean',
            motion_angle_deg: angle,
            motion_axis: axisVec,
          }
          const res = await callTool('brep_assembly_interference', args, projectId)
          const vol = res?.overlap_volume ?? res?.penetration_volume ?? res?.volume ?? 0
          frameResults.push({ angle: angle.toFixed(2), result: res, vol: parseFloat(vol) || 0 })
        } catch (frameErr) {
          frameResults.push({ angle: angle.toFixed(2), error: frameErr.message, vol: 0 })
        }
        setFrames([...frameResults])
      }
    } catch (e) { setError(e.message) }
    finally { setRunning(false); setProgress(null) }
  }

  function cancel() { cancelRef.current = true }

  const clashFrames = frames.filter((f) => f.vol > 0 || f.error)
  const maxVol = frames.length > 0 ? Math.max(...frames.map((f) => f.vol)) : 0

  return (
    <div style={p.panel}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
        <Move3d size={32} style={{ color: '#f59e0b', flexShrink: 0, marginTop: 2 }} />
        <div>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#f3f4f6' }}>Motion Clash Detection</div>
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>
            Steps through a rotation sweep and detects clashes at each frame.
            Identifies the angular range where interference first occurs and its worst frame.
          </div>
        </div>
      </div>

      <div style={p.divider} />

      <div style={p.fieldRow}>
        <label style={p.label}>Body A JSON</label>
        <textarea
          value={bodyAJson}
          onChange={(e) => setBodyAJson(e.target.value)}
          style={p.textarea}
          placeholder='{"type":"Body","faces":[...]}  or  component_ref'
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Body B JSON</label>
        <textarea
          value={bodyBJson}
          onChange={(e) => setBodyBJson(e.target.value)}
          style={p.textarea}
          placeholder='{"type":"Body","faces":[...]}  or  component_ref'
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Rotation axis</label>
        <input
          type="text"
          value={axis}
          onChange={(e) => setAxis(e.target.value)}
          style={p.input}
          placeholder="[1,0,0]"
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Range from (°)</label>
        <input
          type="number"
          value={rangeFrom}
          onChange={(e) => setRangeFrom(e.target.value)}
          style={{ ...p.input, maxWidth: 90 }}
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Range to (°)</label>
        <input
          type="number"
          value={rangeTo}
          onChange={(e) => setRangeTo(e.target.value)}
          style={{ ...p.input, maxWidth: 90 }}
          disabled={running}
        />
      </div>
      <div style={p.fieldRow}>
        <label style={p.label}>Steps</label>
        <input
          type="number"
          value={steps}
          onChange={(e) => setSteps(e.target.value)}
          style={{ ...p.input, maxWidth: 80 }}
          min={2} max={72}
          disabled={running}
        />
      </div>

      <div style={p.btnRow}>
        <button
          onClick={run}
          disabled={running || (!bodyAJson && !bodyBJson)}
          style={p.runBtn(running || (!bodyAJson && !bodyBJson))}
        >
          {running
            ? <><Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} />
                Frame {progress?.current}/{progress?.total}…</>
            : <><Play size={11} /> Sweep Motion</>}
        </button>
        {running && (
          <button onClick={cancel} style={{ ...p.clearBtn, color: '#ef4444', borderColor: '#7f1d1d' }}>
            <X size={10} /> Cancel
          </button>
        )}
        {!running && frames.length > 0 && (
          <button onClick={() => setFrames([])} style={p.clearBtn}>
            <RotateCcw size={10} /> Reset
          </button>
        )}
      </div>

      {error && (
        <div style={p.errorBox} role="alert">
          <AlertTriangle size={12} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      )}

      {/* Progress bar */}
      {running && progress && (
        <div style={{ height: 4, background: '#1f2937', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{
            height: '100%',
            background: '#0e7490',
            width: `${(progress.current / progress.total) * 100}%`,
            transition: 'width 0.2s',
          }} />
        </div>
      )}

      {/* Frame sweep chart — mini bar chart */}
      {frames.length > 0 && (
        <div>
          <div style={p.sectionLabel}>Clash volume per frame</div>
          <div style={{
            display: 'flex', alignItems: 'flex-end', gap: 2,
            height: 52, padding: '0 2px',
          }}>
            {frames.map((f, i) => {
              const pct = maxVol > 0 ? (f.vol / maxVol) * 100 : 0
              const hasClash = f.vol > 0
              const hasError = !!f.error
              return (
                <div
                  key={i}
                  title={`${f.angle}°: ${hasError ? f.error : fmtVol(f.vol)}`}
                  style={{
                    flex: 1, minWidth: 2,
                    height: `${Math.max(pct, hasClash || hasError ? 8 : 2)}%`,
                    background: hasError ? '#7f1d1d' : hasClash ? '#ef4444' : '#1f2937',
                    borderRadius: '2px 2px 0 0',
                    cursor: 'default',
                    transition: 'height 0.15s',
                    minHeight: hasClash || hasError ? 4 : 2,
                  }}
                />
              )
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', marginTop: 3 }}>
            <span>{frames[0]?.angle}°</span>
            <span>{frames[Math.floor(frames.length / 2)]?.angle}°</span>
            <span>{frames[frames.length - 1]?.angle}°</span>
          </div>
        </div>
      )}

      {/* Summary table for clash frames */}
      {frames.length > 0 && (
        <>
          <div style={p.sectionLabel}>
            {clashFrames.length === 0
              ? 'No clashes detected across sweep'
              : `${clashFrames.length} frame${clashFrames.length > 1 ? 's' : ''} with clash`}
          </div>
          {clashFrames.length === 0 ? (
            <div style={{ ...p.infoBox }}>
              <CheckCircle size={12} style={{ flexShrink: 0, marginTop: 1, color: '#4ade80' }} />
              <span style={{ color: '#4ade80' }}>Assembly moves cleanly through the full range — no clashes detected.</span>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{
                width: '100%', borderCollapse: 'collapse', fontSize: 11,
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
              }}>
                <thead>
                  <tr style={{ background: '#161b26', color: '#9ca3af' }}>
                    <th style={{ padding: '5px 8px', textAlign: 'right', borderBottom: '1px solid #1f2937' }}>Angle (°)</th>
                    <th style={{ padding: '5px 8px', textAlign: 'right', borderBottom: '1px solid #1f2937' }}>Overlap Vol</th>
                    <th style={{ padding: '5px 8px', textAlign: 'center', borderBottom: '1px solid #1f2937' }}>Severity</th>
                    <th style={{ padding: '5px 8px', textAlign: 'left', borderBottom: '1px solid #1f2937' }}>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {clashFrames.map((f, i) => (
                    <tr key={i} style={{ background: i % 2 === 0 ? '#0d1117' : '#111827' }}>
                      <td style={{ padding: '4px 8px', textAlign: 'right', color: '#e5e7eb' }}>{f.angle}</td>
                      <td style={{ padding: '4px 8px', textAlign: 'right', color: '#e5e7eb' }}>
                        {f.error ? '—' : fmtVol(f.vol)}
                      </td>
                      <td style={{ padding: '4px 8px', textAlign: 'center' }}>
                        {f.error
                          ? <span style={{ color: '#6b7280', fontSize: 10 }}>ERROR</span>
                          : <SeverityBadge volume={f.vol} />}
                      </td>
                      <td style={{ padding: '4px 8px', color: '#6b7280', fontSize: 10 }}>
                        {f.error || ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// AssemblyClashPanel — main export
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'pairs',    label: 'Component Pairs' },
  { id: 'sweep',    label: 'Whole-Assembly Sweep' },
  { id: 'clearance', label: 'Clearance Check' },
  { id: 'motion',   label: 'Motion Clash' },
]

export default function AssemblyClashPanel({ projectId }) {
  const [activeTab, setActiveTab] = useState('pairs')

  return (
    <div style={p.root} data-testid="assembly-clash-panel">
      {/* Page header */}
      <div style={p.pageHeader}>
        <ShieldAlert size={20} style={{ color: '#ef4444', flexShrink: 0 }} />
        <div>
          <div style={p.pageTitle}>Assembly Clash</div>
          <div style={p.pageSub}>
            Möller–Trumbore + BVH interference · clearance · motion sweep — 4 tools wired
            {projectId && (
              <> · project <code style={{ color: '#6b7280' }}>{projectId.slice(0, 8)}…</code></>
            )}
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div style={p.tabBar}>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            style={p.tab(activeTab === t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'pairs'    && <ComponentPairsTab projectId={projectId} />}
      {activeTab === 'sweep'    && <WholeSweepTab projectId={projectId} />}
      {activeTab === 'clearance' && <ClearanceTab projectId={projectId} />}
      {activeTab === 'motion'   && <MotionClashTab projectId={projectId} />}
    </div>
  )
}
