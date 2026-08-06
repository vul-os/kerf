// ScantlingCheckPanel.jsx — Hull structural scantling rule checks (class-society).
//
// Wires the marine_scantling_check LLM tool:
//   marine_scantling_check — ISO 12215-5 / ABS / DNV local scantling PASS/FAIL
//
// Renders:
//   - Panel/stiffener geometry inputs + material + rule set selection
//   - Required vs actual plate thickness and stiffener SM
//   - PASS/FAIL badges with utilisation progress bars
//   - Cited rule clause per result
//   - Notes / advisory messages
//
// Rule sets (published open-formula skeleton):
//   ISO 12215-5:2008 — small craft any material
//   ABS Rules for Steel Vessels 2024 Pt.3 Ch.2 §3 — local shell scantlings
//   DNV Rules for Classification of Ships 2023 Pt.3 Ch.1 Sec.7 — local scantlings
//
// Honest scope note: these are the published engineering formulae (design
// pressures, plate bending, stiffener SM). Full proprietary rule suites
// (Lloyd's, BV NR 467, ABS DLA) require class-society licensing.

import { useState, useCallback } from 'react'
import {
  Shield,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  Play,
  ChevronDown,
  ChevronRight,
  Ruler,
  Info,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const API_URL =
  typeof import.meta !== 'undefined' && import.meta.env
    ? import.meta.env.VITE_API_URL || ''
    : ''

async function callTool(toolName, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`HTTP ${res.status}: ${txt}`)
  }
  const data = await res.json()
  if (typeof data.result === 'string') {
    try { return JSON.parse(data.result) } catch { return data.result }
  }
  return data.result ?? data
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MATERIALS = [
  { value: 'frp_eglass', label: 'E-glass/polyester FRP' },
  { value: 'frp_epoxy',  label: 'E-glass/epoxy FRP' },
  { value: 'al5083',     label: 'Al 5083-H116' },
  { value: 'al6061',     label: 'Al 6061-T6' },
  { value: 'steel_s235', label: 'Steel S235' },
  { value: 'steel_s355', label: 'Steel S355' },
]

const ZONES = [
  { value: 'bottom',    label: 'Bottom' },
  { value: 'side',      label: 'Side shell' },
  { value: 'deck',      label: 'Weather deck' },
  { value: 'bulkhead',  label: 'Bulkhead' },
]

const CATEGORIES = [
  { value: 'A', label: 'A — Ocean' },
  { value: 'B', label: 'B — Offshore' },
  { value: 'C', label: 'C — Inshore' },
  { value: 'D', label: 'D — Sheltered water' },
]

const RULE_SETS = [
  {
    id: 'iso',
    label: 'ISO 12215-5:2008',
    description: 'Small craft (< 24 m), any material. Categories A–D, motor + sailing.',
  },
  {
    id: 'abs',
    label: 'ABS Steel Vessels 2024',
    description: 'ABS Rules Pt.3 Ch.2 §3 — local shell plating & stiffeners.',
  },
  {
    id: 'dnv',
    label: 'DNV Ships 2023',
    description: 'DNV-RU-SHIP Pt.3 Ch.1 Sec.7 — local scantlings (slamming pressure).',
  },
]

// ---------------------------------------------------------------------------
// Styling helpers
// ---------------------------------------------------------------------------

const cls = (...parts) => parts.filter(Boolean).join(' ')

function UtilBar({ util, passes }) {
  const pct = Math.min(util * 100, 150)
  const color = passes
    ? util < 0.8  ? '#34d399'   // green: good margin
    : util < 1.0  ? '#facc15'   // yellow: tight
    :               '#f97316'   // orange: at limit (shouldn't happen if passes)
    : '#ef4444'                 // red: fail

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{
        height: 8, background: '#1f2937', borderRadius: 4, overflow: 'hidden',
        position: 'relative',
      }}>
        <div style={{
          height: '100%',
          width: `${Math.min(pct, 100)}%`,
          background: color,
          borderRadius: 4,
          transition: 'width 0.4s ease',
        }} />
        {/* 100% marker */}
        <div style={{
          position: 'absolute', top: 0, left: '66.67%', width: 1, height: '100%',
          background: '#6b7280',
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
        <span style={{ fontSize: 11, color: '#9ca3af' }}>0%</span>
        <span style={{ fontSize: 11, color, fontWeight: 600 }}>
          {(util * 100).toFixed(1)}% utilisation
        </span>
        <span style={{ fontSize: 11, color: '#9ca3af' }}>100%</span>
      </div>
    </div>
  )
}

function PassBadge({ passes }) {
  return passes ? (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 12,
      background: '#064e3b', color: '#34d399',
      fontSize: 12, fontWeight: 700,
    }}>
      <CheckCircle2 size={12} /> PASS
    </span>
  ) : (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 8px', borderRadius: 12,
      background: '#450a0a', color: '#ef4444',
      fontSize: 12, fontWeight: 700,
    }}>
      <XCircle size={12} /> FAIL
    </span>
  )
}

function CompareRow({ label, required, actual, unit, util, passes }) {
  const hasActual = actual !== null && actual !== undefined
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ color: '#d1d5db', fontSize: 13 }}>{label}</span>
        {hasActual && <PassBadge passes={passes} />}
      </div>
      <div style={{ display: 'flex', gap: 16, fontSize: 13 }}>
        <div style={{ flex: 1 }}>
          <div style={{ color: '#6b7280', fontSize: 11, marginBottom: 2 }}>Required</div>
          <div style={{ color: '#f9fafb', fontWeight: 600, fontFamily: 'monospace' }}>
            {required != null ? `${required.toFixed(3)} ${unit}` : '—'}
          </div>
        </div>
        {hasActual && (
          <div style={{ flex: 1 }}>
            <div style={{ color: '#6b7280', fontSize: 11, marginBottom: 2 }}>Provided</div>
            <div style={{ color: '#f9fafb', fontWeight: 600, fontFamily: 'monospace' }}>
              {`${actual.toFixed(3)} ${unit}`}
            </div>
          </div>
        )}
      </div>
      {hasActual && <UtilBar util={util} passes={passes} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Check result card
// ---------------------------------------------------------------------------

function CheckCard({ result }) {
  const [open, setOpen] = useState(true)

  const { rule_set, zone, P_design_kPa, plate, stiffener, passes, clause, notes } = result

  return (
    <div style={{
      background: '#111827',
      border: `1px solid ${passes ? '#065f46' : '#7f1d1d'}`,
      borderRadius: 8, marginBottom: 12, overflow: 'hidden',
    }}>
      {/* Header */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', padding: '10px 14px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: '#f9fafb',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {passes
            ? <CheckCircle2 size={16} style={{ color: '#34d399' }} />
            : <XCircle size={16} style={{ color: '#ef4444' }} />
          }
          <span style={{ fontWeight: 600, fontSize: 14 }}>{rule_set}</span>
          <span style={{ color: '#6b7280', fontSize: 12 }}>— {zone}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: '#9ca3af' }}>
            P = {P_design_kPa.toFixed(1)} kPa
          </span>
          {open ? <ChevronDown size={14} color="#6b7280" /> : <ChevronRight size={14} color="#6b7280" />}
        </div>
      </button>

      {open && (
        <div style={{ padding: '0 14px 14px' }}>
          {/* Plate check */}
          <CompareRow
            label="Plate thickness"
            required={plate.t_required_mm}
            actual={plate.t_actual_mm}
            unit="mm"
            util={plate.utilisation}
            passes={plate.passes}
          />

          {/* Stiffener check */}
          <CompareRow
            label="Stiffener section modulus"
            required={stiffener.SM_required_cm3}
            actual={stiffener.SM_actual_cm3}
            unit="cm³"
            util={stiffener.utilisation}
            passes={stiffener.passes}
          />

          {/* Clause */}
          <div style={{
            marginTop: 10, padding: '8px 10px',
            background: '#0f172a', borderRadius: 6,
            borderLeft: '3px solid #374151',
          }}>
            <div style={{ color: '#6b7280', fontSize: 11, marginBottom: 3 }}>
              Rule clause
            </div>
            <div style={{ color: '#94a3b8', fontSize: 11, lineHeight: 1.5 }}>
              {clause}
            </div>
          </div>

          {/* Notes */}
          {notes && notes.length > 0 && (
            <div style={{ marginTop: 8 }}>
              {notes.map((n, i) => (
                <div key={i} style={{
                  display: 'flex', gap: 6, alignItems: 'flex-start',
                  color: '#9ca3af', fontSize: 11, marginTop: 4,
                }}>
                  <Info size={11} style={{ marginTop: 2, flexShrink: 0, color: '#6b7280' }} />
                  <span>{n}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Input row helper
// ---------------------------------------------------------------------------

function InputRow({ label, value, onChange, type = 'number', unit, min, step }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <label style={{ color: '#9ca3af', fontSize: 12, width: 150, flexShrink: 0 }}>
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(type === 'number' ? parseFloat(e.target.value) || 0 : e.target.value)}
        min={min}
        step={step}
        style={{
          flex: 1, background: '#1f2937', border: '1px solid #374151',
          borderRadius: 4, padding: '4px 8px', color: '#f9fafb', fontSize: 13,
        }}
      />
      {unit && <span style={{ color: '#6b7280', fontSize: 12, width: 32 }}>{unit}</span>}
    </div>
  )
}

function SelectRow({ label, value, onChange, options }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
      <label style={{ color: '#9ca3af', fontSize: 12, width: 150, flexShrink: 0 }}>
        {label}
      </label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          flex: 1, background: '#1f2937', border: '1px solid #374151',
          borderRadius: 4, padding: '4px 8px', color: '#f9fafb', fontSize: 13,
        }}
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function ScantlingCheckPanel({ result: propResult, loading: propLoading, error: propError }) {
  // ── State ──────────────────────────────────────────────────────────────────
  const [material,    setMaterial]    = useState('al5083')
  const [zone,        setZone]        = useState('bottom')
  const [category,    setCategory]    = useState('A')
  const [ruleSets,    setRuleSets]    = useState(['iso'])

  // Panel geometry
  const [bMm,  setBMm]  = useState(300)
  const [lMm,  setLMm]  = useState(600)
  const [luMm, setLuMm] = useState(1200)
  const [sMm,  setSMm]  = useState(300)
  const [zMm,  setZMm]  = useState(0)

  // ISO 12215-5 hull inputs
  const [LWL,    setLWL]    = useState(10)
  const [BWL,    setBWL]    = useState(3)
  const [mLDC,   setMLDC]   = useState(5000)
  const [V,      setV]      = useState(20)
  const [beta,   setBeta]   = useState(18)
  const [sailing, setSailing] = useState(false)

  // ABS / DNV inputs
  const [hPanel, setHPanel] = useState(1.5)
  const [vKn,    setVKn]    = useState(0)
  const [Cw,     setCw]     = useState(0)
  const [draft,  setDraft]  = useState(2.5)

  // Actual scantlings (for PASS/FAIL)
  const [tActual,   setTActual]   = useState('')
  const [smActual,  setSmActual]  = useState('')
  const [fixedEnds, setFixedEnds] = useState(true)

  // UI state
  const [isoOpen,    setIsoOpen]    = useState(true)
  const [absOpen,    setAbsOpen]    = useState(false)
  const [result,     setResult]     = useState(propResult || null)
  const [loading,    setLoading]    = useState(propLoading || false)
  const [error,      setError]      = useState(propError || null)

  const toggleRuleSet = useCallback(id => {
    setRuleSets(prev =>
      prev.includes(id) ? prev.filter(r => r !== id) : [...prev, id]
    )
  }, [])

  const handleRun = useCallback(async () => {
    if (ruleSets.length === 0) {
      setError('Select at least one rule set.')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const args = {
        b_mm: bMm, l_mm: lMm, lu_mm: luMm, s_mm: sMm,
        material,
        rule_sets: ruleSets,
        zone,
        // ISO
        LWL, BWL, mLDC, V, beta_04: beta,
        category,
        z_mm: zMm,
        is_sailing: sailing,
        // ABS / DNV
        h_panel_m: hPanel,
        V_kn: vKn,
        Cw,
        draft_m: draft,
        both_ends_fixed: fixedEnds,
      }
      // Optional actuals
      if (tActual !== '') args.t_actual_mm = parseFloat(tActual)
      if (smActual !== '') args.SM_actual_cm3 = parseFloat(smActual)

      const data = await callTool('marine_scantling_check', args)
      if (data.error) throw new Error(data.error)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [
    ruleSets, bMm, lMm, luMm, sMm, material, zone, category,
    LWL, BWL, mLDC, V, beta, zMm, sailing,
    hPanel, vKn, Cw, draft, tActual, smActual, fixedEnds,
  ])

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div style={{
      fontFamily: 'system-ui, -apple-system, sans-serif',
      background: '#0d1117',
      color: '#f9fafb',
      minHeight: '100%',
      padding: 20,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
        <Shield size={20} style={{ color: '#60a5fa' }} />
        <div>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            Hull Scantling Rule Checks
          </h2>
          <p style={{ margin: 0, fontSize: 12, color: '#6b7280' }}>
            ISO 12215-5 · ABS Steel Vessels · DNV Ships — PASS/FAIL + utilisation
          </p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 20, alignItems: 'start' }}>

        {/* ── Left: Inputs ── */}
        <div>
          {/* Rule sets */}
          <div style={{
            background: '#111827', border: '1px solid #1f2937',
            borderRadius: 8, padding: 14, marginBottom: 14,
          }}>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10, color: '#e5e7eb' }}>
              Rule Sets
            </div>
            {RULE_SETS.map(rs => (
              <label key={rs.id} style={{
                display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 10,
                cursor: 'pointer',
              }}>
                <input
                  type="checkbox"
                  checked={ruleSets.includes(rs.id)}
                  onChange={() => toggleRuleSet(rs.id)}
                  style={{ marginTop: 2 }}
                />
                <div>
                  <div style={{ fontSize: 13, color: '#f9fafb', fontWeight: 500 }}>{rs.label}</div>
                  <div style={{ fontSize: 11, color: '#6b7280' }}>{rs.description}</div>
                </div>
              </label>
            ))}
            <div style={{
              marginTop: 8, padding: '6px 8px', background: '#0f172a',
              borderRadius: 4, borderLeft: '3px solid #1d4ed8',
              fontSize: 11, color: '#6b7280',
            }}>
              These implement the published engineering formulae (open). Full proprietary
              rule suites (Lloyd's, BV NR 467) require class-society licensing.
            </div>
          </div>

          {/* Panel geometry */}
          <div style={{
            background: '#111827', border: '1px solid #1f2937',
            borderRadius: 8, padding: 14, marginBottom: 14,
          }}>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10, color: '#e5e7eb' }}>
              Panel &amp; Stiffener Geometry
            </div>
            <InputRow label="Panel short side b" value={bMm} onChange={setBMm} unit="mm" min={10} step={10} />
            <InputRow label="Panel long side l"  value={lMm} onChange={setLMm} unit="mm" min={10} step={10} />
            <InputRow label="Stiffener span lu"  value={luMm} onChange={setLuMm} unit="mm" min={10} step={10} />
            <InputRow label="Stiffener spacing s" value={sMm} onChange={setSMm} unit="mm" min={10} step={10} />
            <InputRow label="Crown/camber z"     value={zMm} onChange={setZMm} unit="mm" min={0}  step={5} />
            <SelectRow label="Material" value={material} onChange={setMaterial} options={MATERIALS} />
            <SelectRow label="Hull zone" value={zone} onChange={setZone} options={ZONES} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <label style={{ color: '#9ca3af', fontSize: 12, width: 150 }}>Stiffener ends</label>
              <select
                value={fixedEnds ? 'fixed' : 'pin'}
                onChange={e => setFixedEnds(e.target.value === 'fixed')}
                style={{
                  flex: 1, background: '#1f2937', border: '1px solid #374151',
                  borderRadius: 4, padding: '4px 8px', color: '#f9fafb', fontSize: 13,
                }}
              >
                <option value="fixed">Fixed (C=1/12)</option>
                <option value="pin">Pin-pin (C=1/8)</option>
              </select>
            </div>
          </div>

          {/* Actual scantlings */}
          <div style={{
            background: '#111827', border: '1px solid #1f2937',
            borderRadius: 8, padding: 14, marginBottom: 14,
          }}>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4, color: '#e5e7eb' }}>
              Actual Scantlings (optional)
            </div>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 10 }}>
              Leave blank to get required values only.
            </div>
            <InputRow label="Plate thickness t" value={tActual} onChange={setTActual} unit="mm" min={0} step={0.5} />
            <InputRow label="Stiffener SM"       value={smActual} onChange={setSmActual} unit="cm³" min={0} step={1} />
          </div>

          {/* ISO 12215-5 hull inputs */}
          <div style={{
            background: '#111827', border: '1px solid #1f2937',
            borderRadius: 8, marginBottom: 14, overflow: 'hidden',
          }}>
            <button
              onClick={() => setIsoOpen(o => !o)}
              style={{
                width: '100%', padding: '10px 14px',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                background: 'transparent', border: 'none', cursor: 'pointer', color: '#e5e7eb',
                fontWeight: 600, fontSize: 13,
              }}
            >
              ISO 12215-5 Hull Parameters
              {isoOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            {isoOpen && (
              <div style={{ padding: '0 14px 14px' }}>
                <SelectRow label="Design category" value={category} onChange={setCategory} options={CATEGORIES} />
                <InputRow label="Waterline length" value={LWL}  onChange={setLWL}  unit="m"  min={1} step={0.5} />
                <InputRow label="Waterline beam"   value={BWL}  onChange={setBWL}  unit="m"  min={0.5} step={0.1} />
                <InputRow label="Displacement"     value={mLDC} onChange={setMLDC} unit="kg" min={100} step={100} />
                <InputRow label="Max speed"        value={V}    onChange={setV}    unit="kn" min={0} step={1} />
                <InputRow label="Deadrise β₀.₄"    value={beta} onChange={setBeta} unit="°"  min={0} step={1} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <label style={{ color: '#9ca3af', fontSize: 12, width: 150 }}>Sailing craft</label>
                  <input
                    type="checkbox"
                    checked={sailing}
                    onChange={e => setSailing(e.target.checked)}
                  />
                </div>
              </div>
            )}
          </div>

          {/* ABS / DNV inputs */}
          <div style={{
            background: '#111827', border: '1px solid #1f2937',
            borderRadius: 8, marginBottom: 16, overflow: 'hidden',
          }}>
            <button
              onClick={() => setAbsOpen(o => !o)}
              style={{
                width: '100%', padding: '10px 14px',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                background: 'transparent', border: 'none', cursor: 'pointer', color: '#e5e7eb',
                fontWeight: 600, fontSize: 13,
              }}
            >
              ABS / DNV Pressure Inputs
              {absOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            {absOpen && (
              <div style={{ padding: '0 14px 14px' }}>
                <InputRow label="Panel depth h" value={hPanel} onChange={setHPanel} unit="m"   min={0} step={0.1} />
                <InputRow label="Vessel draft"  value={draft}  onChange={setDraft}  unit="m"   min={0} step={0.1} />
                <InputRow label="Speed (DNV)"   value={vKn}    onChange={setVKn}    unit="kn"  min={0} step={1} />
                <InputRow label="Wave Cw (ABS)" value={Cw}     onChange={setCw}     unit="kPa" min={0} step={0.5} />
              </div>
            )}
          </div>

          {/* Run button */}
          <button
            onClick={handleRun}
            disabled={loading}
            style={{
              width: '100%',
              padding: '10px 0',
              background: loading ? '#1f2937' : '#1d4ed8',
              border: 'none', borderRadius: 6,
              color: loading ? '#6b7280' : '#fff',
              fontSize: 14, fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            }}
          >
            {loading
              ? <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Checking…</>
              : <><Play size={14} /> Run Scantling Checks</>
            }
          </button>
        </div>

        {/* ── Right: Results ── */}
        <div>
          {error && (
            <div style={{
              background: '#450a0a', border: '1px solid #7f1d1d',
              borderRadius: 8, padding: 14, marginBottom: 14,
              display: 'flex', gap: 8, alignItems: 'flex-start',
            }}>
              <AlertTriangle size={16} style={{ color: '#ef4444', flexShrink: 0, marginTop: 1 }} />
              <span style={{ color: '#fca5a5', fontSize: 13 }}>{error}</span>
            </div>
          )}

          {!result && !loading && !error && (
            <div style={{
              background: '#111827', border: '1px solid #1f2937',
              borderRadius: 8, padding: 40, textAlign: 'center',
              color: '#4b5563',
            }}>
              <Ruler size={32} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
              <p style={{ margin: 0, fontSize: 14 }}>
                Configure inputs and click Run to check scantlings against selected rule sets.
              </p>
            </div>
          )}

          {result && (
            <>
              {/* Summary banner */}
              <div style={{
                background: result.all_pass ? '#064e3b' : '#450a0a',
                border: `1px solid ${result.all_pass ? '#065f46' : '#7f1d1d'}`,
                borderRadius: 8, padding: '12px 16px', marginBottom: 16,
                display: 'flex', alignItems: 'center', gap: 10,
              }}>
                {result.all_pass
                  ? <CheckCircle2 size={20} style={{ color: '#34d399', flexShrink: 0 }} />
                  : <XCircle size={20} style={{ color: '#ef4444', flexShrink: 0 }} />
                }
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: '#f9fafb' }}>
                    {result.all_pass ? 'All checks PASS' : 'One or more checks FAIL'}
                  </div>
                  <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 2 }}>
                    {result.summary}
                  </div>
                </div>
              </div>

              {/* Per-rule-set cards */}
              {(result.checks || []).map((r, i) => (
                <CheckCard key={i} result={r} />
              ))}

              {/* Honest scope note */}
              <div style={{
                marginTop: 12, padding: '8px 10px', background: '#0f172a',
                borderRadius: 6, borderLeft: '3px solid #1d4ed8',
              }}>
                <div style={{ fontSize: 11, color: '#6b7280', lineHeight: 1.5 }}>
                  <strong style={{ color: '#94a3b8' }}>Scope:</strong> ISO 12215-5 (full, all materials),
                  ABS Pt.3 Ch.2 §3 local shell (steel), DNV Pt.3 Ch.1 Sec.7 local scantlings.
                  Not covered: Lloyd's full rule, BV NR 467, ABS DLA (Part 5A), DNV fatigue module —
                  these require licensed class-society rule-tree software.
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  )
}
