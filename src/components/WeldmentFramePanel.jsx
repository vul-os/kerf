/**
 * WeldmentFramePanel — Structural weldment framework generator.
 *
 * Three modes:
 *   "profile"  — weldment_profile_lookup: look up a profile designation and
 *                return its area, mass-per-metre, and section properties.
 *   "frame"    — weldment_frame: take a skeleton (list of 3-D edges) + profile
 *                designation → generate member list with joint trimming
 *                (miter/butt rules) and a cut list.
 *   "cutlist"  — weldment_cutlist: from a raw member list → rolled-up cut list
 *                with total mass.
 *
 * The skeleton editor is a simple textarea accepting JSON; the user pastes a
 * list of {"start":[x,y,z],"end":[x,y,z]} line-segment objects (mm).
 *
 * References
 * ----------
 * kerf_cad_core.weldment — miter/butt joint geometry (deterministic)
 * kerf_cad_core.weldment_profiles — cross-section property tables
 *
 * Props
 * -----
 * onToast  (msg) => void  — optional
 */

import { useState } from 'react'
import { Frame, ChevronDown, ChevronRight, Loader2, AlertTriangle } from 'lucide-react'
import { api } from '../lib/api.js'

// ---------------------------------------------------------------------------
// Pure helpers — export for tests
// ---------------------------------------------------------------------------

/**
 * Format a number to `dp` decimal places; returns '—' for null/NaN/Infinity.
 * @param {number|null|undefined} v
 * @param {number} dp
 */
export function fmtNum(v, dp = 2) {
  if (v == null || !isFinite(v)) return '—'
  return v.toFixed(dp)
}

/**
 * Parse a skeleton JSON string.
 * Returns { ok: true, edges } or { ok: false, error }.
 * @param {string} raw
 */
export function parseSkeleton(raw) {
  if (!raw || !raw.trim()) return { ok: false, error: 'Empty skeleton' }
  let parsed
  try {
    parsed = JSON.parse(raw)
  } catch (e) {
    return { ok: false, error: `JSON parse error: ${e.message}` }
  }
  if (!Array.isArray(parsed)) return { ok: false, error: 'Skeleton must be a JSON array' }
  for (let i = 0; i < parsed.length; i++) {
    const e = parsed[i]
    if (!e || typeof e !== 'object') return { ok: false, error: `Edge ${i}: must be an object` }
    if (!Array.isArray(e.start) || e.start.length !== 3)
      return { ok: false, error: `Edge ${i}: start must be [x,y,z]` }
    if (!Array.isArray(e.end) || e.end.length !== 3)
      return { ok: false, error: `Edge ${i}: end must be [x,y,z]` }
  }
  return { ok: true, edges: parsed }
}

/**
 * Build weldment_frame params from form state.
 * @param {object} s
 */
export function buildFrameParams(s) {
  const sk = parseSkeleton(s.skeleton)
  return {
    skeleton: sk.ok ? sk.edges : [],
    profile: s.profile || 'SHS-50x50x3',
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function FieldRow({ label, children, hint }) {
  return (
    <div className="flex items-start gap-2 py-0.5">
      <label className="text-[11px] text-ink-400 w-32 flex-shrink-0 pt-1">{label}</label>
      <div className="flex-1">{children}</div>
      {hint && <span className="text-[10px] text-ink-600 flex-shrink-0 pt-1">{hint}</span>}
    </div>
  )
}

function TextInput({ value, onChange, placeholder, 'data-testid': testid }) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      data-testid={testid}
      className="w-full bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 focus:outline-none focus:ring-1 focus:ring-kerf-300/60"
    />
  )
}

function TextArea({ value, onChange, placeholder, rows, 'data-testid': testid }) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows || 5}
      data-testid={testid}
      className="w-full bg-ink-900 border border-ink-700 rounded px-2 py-1 text-[11px] text-ink-100 font-mono focus:outline-none focus:ring-1 focus:ring-kerf-300/60 resize-y"
    />
  )
}

function ResultKV({ label, value, unit }) {
  return (
    <div className="flex items-center justify-between py-0.5 border-b border-ink-900">
      <span className="text-[11px] text-ink-400">{label}</span>
      <span className="text-[11px] text-ink-100 font-mono">
        {value}{unit ? <span className="text-ink-500 ml-1">{unit}</span> : null}
      </span>
    </div>
  )
}

function WarningList({ warnings }) {
  if (!warnings?.length) return null
  return (
    <div className="mt-2 space-y-0.5">
      {warnings.map((w, i) => (
        <div key={i} className="flex items-start gap-1 text-[10px] text-amber-400/80">
          <AlertTriangle size={10} className="mt-0.5 flex-shrink-0" />
          {w}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode: weldment_profile_lookup
// ---------------------------------------------------------------------------

function ProfileLookupMode({ onToast }) {
  const [profile, setProfile] = useState('SHS-50x50x3')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  async function run() {
    setLoading(true)
    setResult(null)
    try {
      const data = await api.callTool('weldment_profile_lookup', { profile })
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.(e?.message || 'weldment_profile_lookup failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-1" data-testid="weldment-profile-mode">
      <p className="text-[10px] text-ink-500 mb-1">
        Look up cross-section properties for a profile designation
        (SHS, RHS, CHS, IPE, HEA, L, Channel, Flat, etc.)
      </p>
      <FieldRow label="Profile">
        <TextInput value={profile} onChange={setProfile} placeholder="SHS-50x50x3" data-testid="wp-profile" />
      </FieldRow>

      <button type="button" onClick={run} disabled={loading}
        data-testid="weldment-profile-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Frame size={12} />}
        Look Up Profile
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="weldment-profile-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="Designation" value={result.designation ?? '—'} />
              <ResultKV label="Area A" value={fmtNum(result.area_mm2)} unit="mm²" />
              <ResultKV label="Mass/m" value={fmtNum(result.mass_per_m_kg, 3)} unit="kg/m" />
              <ResultKV label="Ix" value={result.Ix_mm4 != null ? fmtNum(result.Ix_mm4, 0) : '—'} unit="mm⁴" />
              <ResultKV label="Iy" value={result.Iy_mm4 != null ? fmtNum(result.Iy_mm4, 0) : '—'} unit="mm⁴" />
              <WarningList warnings={result.warnings} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode: weldment_frame
// ---------------------------------------------------------------------------

const SKELETON_EXAMPLE = JSON.stringify([
  { start: [0, 0, 0],    end: [1000, 0, 0] },
  { start: [1000, 0, 0], end: [1000, 0, 1000] },
  { start: [1000, 0, 1000], end: [0, 0, 1000] },
  { start: [0, 0, 1000], end: [0, 0, 0] },
], null, 2)

function FrameMode({ onToast }) {
  const [form, setForm] = useState({
    skeleton: SKELETON_EXAMPLE,
    profile: 'SHS-50x50x3',
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  function set(k) {
    return (v) => setForm((f) => ({ ...f, [k]: v }))
  }

  const skeletonStatus = parseSkeleton(form.skeleton)

  async function run() {
    if (!skeletonStatus.ok) {
      onToast?.(`Skeleton error: ${skeletonStatus.error}`)
      return
    }
    setLoading(true)
    setResult(null)
    try {
      const data = await api.callTool('weldment_frame', buildFrameParams(form))
      setResult(data?.result ?? data)
    } catch (e) {
      onToast?.(e?.message || 'weldment_frame failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-1" data-testid="weldment-frame-mode">
      <p className="text-[10px] text-ink-500 mb-1">
        Skeleton edges (JSON array of {'{start:[x,y,z],end:[x,y,z]}'} in mm)
        → members with miter/butt trimming + cut list
      </p>
      <FieldRow label="Profile">
        <TextInput value={form.profile} onChange={set('profile')} placeholder="SHS-50x50x3" data-testid="wf-profile" />
      </FieldRow>
      <FieldRow label="Skeleton">
        <TextArea value={form.skeleton} onChange={set('skeleton')} rows={6}
          placeholder={SKELETON_EXAMPLE} data-testid="wf-skeleton" />
      </FieldRow>

      {!skeletonStatus.ok && form.skeleton.trim() && (
        <div className="flex items-center gap-1 text-[10px] text-amber-400">
          <AlertTriangle size={10} />
          {skeletonStatus.error}
        </div>
      )}

      <button type="button" onClick={run} disabled={loading || !skeletonStatus.ok}
        data-testid="weldment-frame-run"
        className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded bg-kerf-300/10 hover:bg-kerf-300/20 text-[11px] text-kerf-300 disabled:opacity-40">
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Frame size={12} />}
        Generate Frame
      </button>

      {result && (
        <div className="mt-2 rounded border border-ink-800 p-2 bg-ink-900/60" data-testid="weldment-frame-result">
          {result.ok === false ? (
            <p className="text-[11px] text-red-400">{result.reason || 'Unknown error'}</p>
          ) : (
            <>
              <ResultKV label="Members" value={result.member_count ?? result.members?.length ?? '—'} />
              <ResultKV label="Profile" value={result.profile ?? form.profile} />
              {/* Cut list summary */}
              {result.cutlist?.length > 0 && (
                <div className="mt-2">
                  <p className="text-[10px] text-ink-500 mb-1 uppercase tracking-wider">Cut list</p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[11px]" data-testid="weldment-cut-table">
                      <thead>
                        <tr className="text-ink-500 text-[10px] uppercase tracking-wider border-b border-ink-800">
                          <th className="text-left pb-1 pr-2 font-medium">Profile</th>
                          <th className="text-right pb-1 pr-2 font-medium">Pieces</th>
                          <th className="text-right pb-1 pr-2 font-medium">Length</th>
                          <th className="text-right pb-1 font-medium">Mass</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.cutlist.map((row, i) => (
                          <tr key={i} className="border-b border-ink-900" data-testid="weldment-cut-row">
                            <td className="py-1 pr-2 font-mono text-ink-200">{row.designation}</td>
                            <td className="py-1 pr-2 text-right text-ink-300">{row.pieces?.length ?? '—'}</td>
                            <td className="py-1 pr-2 text-right font-mono text-ink-200">
                              {fmtNum(row.total_length_mm, 0)} <span className="text-ink-500">mm</span>
                            </td>
                            <td className="py-1 text-right font-mono text-ink-200">
                              {fmtNum(row.total_mass_kg, 2)} <span className="text-ink-500">kg</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              <WarningList warnings={result.warnings} />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const MODES = [
  ['profile', 'Profile Lookup'],
  ['frame', 'Generate Frame'],
]

export default function WeldmentFramePanel({ onToast }) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState('profile')

  return (
    <div className="border-t border-ink-800 flex-shrink-0" data-testid="weldment-frame-panel">
      <div className="flex items-center px-3 py-1.5 gap-2">
        <button type="button" onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1.5 text-[11px] text-ink-400 hover:text-kerf-300 flex-1 min-w-0"
          aria-expanded={open}
          aria-controls="weldment-panel-body"
          data-testid="weldment-panel-toggle">
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          <Frame size={12} className="text-ink-500" />
          <span className="font-medium">Weldments — Structural Framework</span>
        </button>
      </div>

      {open && (
        <div id="weldment-panel-body" className="px-3 pb-3" data-testid="weldment-panel-body">
          <div className="flex gap-1 mb-2">
            {MODES.map(([k, label]) => (
              <button key={k} type="button"
                onClick={() => setMode(k)}
                data-testid={`weldment-mode-${k}`}
                className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                  mode === k
                    ? 'bg-kerf-300/20 text-kerf-300'
                    : 'bg-ink-800 text-ink-400 hover:bg-ink-700'
                }`}>
                {label}
              </button>
            ))}
          </div>

          {mode === 'profile' && <ProfileLookupMode onToast={onToast} />}
          {mode === 'frame'   && <FrameMode onToast={onToast} />}
        </div>
      )}
    </div>
  )
}
