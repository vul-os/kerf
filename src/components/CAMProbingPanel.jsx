/**
 * CAMProbingPanel — On-machine probing cycle planner panel.
 *
 * Lets the user configure a probing cycle (feature type + dialect + geometry),
 * calls the `cam_onmachine_probing` LLM tool, and renders:
 *   - Probe operations list (feature type, dialect, measurement points)
 *   - Measurement points table (label, X, Y, Z, direction, nominal value)
 *   - G-code preview with syntax highlighting
 *   - Download button for the probing program
 *   - WCS update logic description
 *   - Honest caveats notice
 *
 * Dialects:
 *   - renishaw  — G65 P9810/P9811/P9814/P9815/P9823 macro calls
 *                 (Renishaw Inspection Plus for Fanuc Macro B, Rev D)
 *   - fanuc_g31 — Fanuc G31 skip function + G10 L2/L11 WCS/TLO update
 *                 (Fanuc 0i-MD §4.1.13)
 *
 * Props:
 *   projectId  — current project UUID (optional)
 *   fileId     — associated file UUID (optional)
 */

import { useState } from 'react'
import { Target, Download, AlertTriangle, CheckCircle, Loader2, MapPin } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FEATURE_TYPES = [
  { value: 'bore_centre_find', label: 'Bore Centre-Find (4-point ±X/±Y)' },
  { value: 'boss_centre_find', label: 'Boss Centre-Find (4-point ±X/±Y)' },
  { value: 'surface_measure',  label: 'Surface Measure (single axis)' },
  { value: 'web_pocket_width', label: 'Web / Pocket Width (2-point)' },
  { value: 'tool_length_set',  label: 'Tool-Length Set (setter probe)' },
]

const DIALECTS = [
  { value: 'fanuc_g31', label: 'Fanuc G31 skip + G10 L2 (0i-MD)' },
  { value: 'renishaw',  label: 'Renishaw Inspection Plus (G65 P98nn)' },
]

const AXES = ['X', 'Y', 'Z']
const WCS_OPTIONS = [1, 2, 3, 4, 5, 6]
const WCS_LABELS = { 1: 'G54', 2: 'G55', 3: 'G56', 4: 'G57', 5: 'G58', 6: 'G59' }

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function Label({ children }) {
  return (
    <span style={{ fontSize: 11, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
      {children}
    </span>
  )
}

function Field({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Label>{label}</Label>
      {children}
    </div>
  )
}

function NumInput({ value, onChange, step = 0.1, min }) {
  return (
    <input
      type="number"
      value={value}
      step={step}
      min={min}
      onChange={e => onChange(parseFloat(e.target.value) || 0)}
      style={{
        background: '#0d1117', border: '1px solid #1f2937', borderRadius: 4,
        color: '#e5e7eb', padding: '3px 6px', fontSize: 12, width: '100%',
      }}
    />
  )
}

function Select({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      style={{
        background: '#0d1117', border: '1px solid #1f2937', borderRadius: 4,
        color: '#e5e7eb', padding: '3px 6px', fontSize: 12, width: '100%',
      }}
    >
      {options.map(o => (
        <option key={o.value ?? o} value={o.value ?? o}>
          {o.label ?? o}
        </option>
      ))}
    </select>
  )
}

// ---------------------------------------------------------------------------
// Geometry sub-forms per feature type
// ---------------------------------------------------------------------------

function BoreBossForm({ geom, setGeom, label }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      <Field label="Centre X (mm)">
        <NumInput value={geom.cx ?? 0} onChange={v => setGeom({ ...geom, cx: v })} />
      </Field>
      <Field label="Centre Y (mm)">
        <NumInput value={geom.cy ?? 0} onChange={v => setGeom({ ...geom, cy: v })} />
      </Field>
      <Field label="Approach Z (mm)">
        <NumInput value={geom.approach_z ?? 5} onChange={v => setGeom({ ...geom, approach_z: v })} />
      </Field>
      <Field label={label === 'boss' ? 'Probe Z (mm)' : 'Bore Z (mm)'}>
        <NumInput value={geom.bore_z ?? -10} onChange={v => setGeom({ ...geom, bore_z: v })} />
      </Field>
      <Field label="Nominal Diameter (mm)">
        <NumInput value={geom.nominal_diameter ?? 20} step={1} min={1}
          onChange={v => setGeom({ ...geom, nominal_diameter: v })} />
      </Field>
      <Field label="WCS number">
        <Select value={geom.wcs_number ?? 1}
          onChange={v => setGeom({ ...geom, wcs_number: parseInt(v, 10) })}
          options={WCS_OPTIONS.map(n => ({ value: n, label: `${n} (${WCS_LABELS[n]})` }))} />
      </Field>
    </div>
  )
}

function SurfaceMeasureForm({ geom, setGeom }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      <Field label="X (mm)">
        <NumInput value={geom.x ?? 0} onChange={v => setGeom({ ...geom, x: v })} />
      </Field>
      <Field label="Y (mm)">
        <NumInput value={geom.y ?? 0} onChange={v => setGeom({ ...geom, y: v })} />
      </Field>
      <Field label="Z Approach (mm)">
        <NumInput value={geom.z_approach ?? 5} onChange={v => setGeom({ ...geom, z_approach: v })} />
      </Field>
      <Field label="Axis">
        <Select value={geom.axis ?? 'Z'}
          onChange={v => setGeom({ ...geom, axis: v })}
          options={AXES.map(a => ({ value: a, label: a }))} />
      </Field>
      <Field label="Travel (signed mm)">
        <NumInput value={geom.travel ?? -10} step={0.5}
          onChange={v => setGeom({ ...geom, travel: v })} />
      </Field>
      <Field label="Offset (ball radius, mm)">
        <NumInput value={geom.offset_mm ?? 0} step={0.05} min={0}
          onChange={v => setGeom({ ...geom, offset_mm: v })} />
      </Field>
      <Field label="WCS number">
        <Select value={geom.wcs_number ?? 1}
          onChange={v => setGeom({ ...geom, wcs_number: parseInt(v, 10) })}
          options={WCS_OPTIONS.map(n => ({ value: n, label: `${n} (${WCS_LABELS[n]})` }))} />
      </Field>
    </div>
  )
}

function WebPocketForm({ geom, setGeom }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      <Field label="Centre X (mm)">
        <NumInput value={geom.cx ?? 0} onChange={v => setGeom({ ...geom, cx: v })} />
      </Field>
      <Field label="Centre Y (mm)">
        <NumInput value={geom.cy ?? 0} onChange={v => setGeom({ ...geom, cy: v })} />
      </Field>
      <Field label="Probe Z (mm)">
        <NumInput value={geom.probe_z ?? -5} onChange={v => setGeom({ ...geom, probe_z: v })} />
      </Field>
      <Field label="Axis">
        <Select value={geom.axis ?? 'X'}
          onChange={v => setGeom({ ...geom, axis: v })}
          options={['X', 'Y'].map(a => ({ value: a, label: a }))} />
      </Field>
      <Field label="Nominal Width (mm)">
        <NumInput value={geom.nominal_width ?? 20} step={0.5} min={0.1}
          onChange={v => setGeom({ ...geom, nominal_width: v })} />
      </Field>
    </div>
  )
}

function ToolLengthForm({ geom, setGeom }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      <Field label="Tool number">
        <NumInput value={geom.tool_number ?? 1} step={1} min={1}
          onChange={v => setGeom({ ...geom, tool_number: Math.round(v) })} />
      </Field>
      <Field label="Setter Z nominal (mm)">
        <NumInput value={geom.setter_z_nominal ?? 5} step={0.1}
          onChange={v => setGeom({ ...geom, setter_z_nominal: v })} />
      </Field>
      <Field label="Setter X (mm)">
        <NumInput value={geom.setter_x ?? 0} onChange={v => setGeom({ ...geom, setter_x: v })} />
      </Field>
      <Field label="Setter Y (mm)">
        <NumInput value={geom.setter_y ?? 0} onChange={v => setGeom({ ...geom, setter_y: v })} />
      </Field>
      <Field label="Approach Z (mm)">
        <NumInput value={geom.approach_z ?? 30} onChange={v => setGeom({ ...geom, approach_z: v })} />
      </Field>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Measurement points table
// ---------------------------------------------------------------------------

function MeasurementPointsTable({ points }) {
  if (!points || points.length === 0) return null
  return (
    <div>
      <Label>Measurement Points</Label>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, marginTop: 4 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #1f2937' }}>
            {['Label', 'X', 'Y', 'Z', 'Dir', 'Nominal'].map(h => (
              <th key={h} style={{ textAlign: 'left', padding: '3px 6px', color: '#9ca3af' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {points.map((pt, i) => (
            <tr key={i} style={{ borderBottom: '1px solid #111827' }}>
              <td style={{ padding: '3px 6px', color: '#60a5fa' }}>{pt.label}</td>
              <td style={{ padding: '3px 6px', color: '#e5e7eb', fontFamily: 'monospace' }}>{pt.x?.toFixed(3)}</td>
              <td style={{ padding: '3px 6px', color: '#e5e7eb', fontFamily: 'monospace' }}>{pt.y?.toFixed(3)}</td>
              <td style={{ padding: '3px 6px', color: '#e5e7eb', fontFamily: 'monospace' }}>{pt.z?.toFixed(3)}</td>
              <td style={{ padding: '3px 6px', color: '#34d399' }}>{pt.direction}</td>
              <td style={{ padding: '3px 6px', color: '#e5e7eb', fontFamily: 'monospace' }}>{pt.nominal_value?.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// G-code preview with basic keyword colouring
// ---------------------------------------------------------------------------

function GCodePreview({ gcode }) {
  if (!gcode) return null

  const colourLine = (line) => {
    if (line.startsWith('%') || line.startsWith('(')) {
      return <span style={{ color: '#6b7280' }}>{line}</span>
    }
    const parts = line.split(/\b/)
    return parts.map((part, i) => {
      if (/^G\d+/.test(part)) return <span key={i} style={{ color: '#60a5fa' }}>{part}</span>
      if (/^M\d+/.test(part)) return <span key={i} style={{ color: '#f59e0b' }}>{part}</span>
      if (/^[XYZIJKRF][-\d.]+/.test(part)) return <span key={i} style={{ color: '#34d399' }}>{part}</span>
      if (/^[SPTH]\d+/.test(part)) return <span key={i} style={{ color: '#a78bfa' }}>{part}</span>
      if (/^#\d+/.test(part)) return <span key={i} style={{ color: '#fb923c' }}>{part}</span>
      return <span key={i} style={{ color: '#e5e7eb' }}>{part}</span>
    })
  }

  return (
    <div style={{
      background: '#0d1117', border: '1px solid #1f2937', borderRadius: 6,
      padding: 10, maxHeight: 300, overflowY: 'auto',
    }}>
      <pre style={{ margin: 0, fontSize: 11, fontFamily: 'monospace', lineHeight: 1.5 }}>
        {gcode.split('\n').map((line, i) => (
          <div key={i}>{colourLine(line)}{'\n'}</div>
        ))}
      </pre>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function CAMProbingPanel({ projectId, fileId }) {
  const [featureType, setFeatureType] = useState('bore_centre_find')
  const [dialect, setDialect] = useState('fanuc_g31')
  const [geom, setGeom] = useState({})
  const [probeParams, setProbeParams] = useState({
    probe_feed_mm_min: 300,
    retract_mm: 2.0,
    safe_z_mm: 50.0,
  })

  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const featureLabel = FEATURE_TYPES.find(f => f.value === featureType)?.label ?? featureType

  async function generate() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const body = {
        tool: 'cam_onmachine_probing',
        args: {
          feature_type: featureType,
          dialect,
          nominal_geometry: { ...geom },
          probe_params: { ...probeParams },
        },
      }
      const resp = await fetch(`${API_URL}/api/tools/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await resp.json()
      if (data.error) throw new Error(data.error)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function downloadGcode() {
    if (!result?.gcode) return
    const blob = new Blob([result.gcode], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `probing_${featureType}_${dialect}.nc`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div style={{
      background: '#111827', color: '#e5e7eb', fontFamily: 'sans-serif',
      fontSize: 13, padding: 16, borderRadius: 8, display: 'flex', flexDirection: 'column', gap: 16,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Target size={18} color="#60a5fa" />
        <span style={{ fontWeight: 600, fontSize: 15 }}>On-Machine Probing</span>
        <span style={{
          marginLeft: 'auto', fontSize: 10, background: '#1e3a5f', color: '#93c5fd',
          padding: '2px 8px', borderRadius: 12,
        }}>
          Renishaw / Fanuc G31
        </span>
      </div>

      {/* Configuration */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <Field label="Feature Type">
            <Select value={featureType} onChange={v => { setFeatureType(v); setGeom({}) }}
              options={FEATURE_TYPES} />
          </Field>
          <Field label="Dialect">
            <Select value={dialect} onChange={setDialect} options={DIALECTS} />
          </Field>
        </div>

        {/* Geometry sub-form */}
        <div style={{
          background: '#0d1117', border: '1px solid #1f2937', borderRadius: 6, padding: 10,
        }}>
          <div style={{ marginBottom: 8 }}>
            <Label>Nominal Geometry — {featureLabel}</Label>
          </div>
          {(featureType === 'bore_centre_find' || featureType === 'boss_centre_find') && (
            <BoreBossForm geom={geom} setGeom={setGeom}
              label={featureType === 'boss_centre_find' ? 'boss' : 'bore'} />
          )}
          {featureType === 'surface_measure' && (
            <SurfaceMeasureForm geom={geom} setGeom={setGeom} />
          )}
          {featureType === 'web_pocket_width' && (
            <WebPocketForm geom={geom} setGeom={setGeom} />
          )}
          {featureType === 'tool_length_set' && (
            <ToolLengthForm geom={geom} setGeom={setGeom} />
          )}
        </div>

        {/* Probe params */}
        <div style={{
          background: '#0d1117', border: '1px solid #1f2937', borderRadius: 6, padding: 10,
        }}>
          <div style={{ marginBottom: 8 }}><Label>Probe Parameters</Label></div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
            <Field label="Probe Feed (mm/min)">
              <NumInput value={probeParams.probe_feed_mm_min} step={50} min={50}
                onChange={v => setProbeParams({ ...probeParams, probe_feed_mm_min: v })} />
            </Field>
            <Field label="Retract (mm)">
              <NumInput value={probeParams.retract_mm} step={0.5} min={0.5}
                onChange={v => setProbeParams({ ...probeParams, retract_mm: v })} />
            </Field>
            <Field label="Safe Z (mm)">
              <NumInput value={probeParams.safe_z_mm} step={5} min={5}
                onChange={v => setProbeParams({ ...probeParams, safe_z_mm: v })} />
            </Field>
          </div>
        </div>
      </div>

      {/* Generate button */}
      <button
        onClick={generate}
        disabled={loading}
        style={{
          background: loading ? '#1f2937' : '#1d4ed8',
          color: loading ? '#6b7280' : '#fff',
          border: 'none', borderRadius: 6, padding: '8px 16px',
          cursor: loading ? 'not-allowed' : 'pointer',
          fontWeight: 600, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6,
        }}
      >
        {loading ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Target size={14} />}
        {loading ? 'Generating probing program…' : 'Generate Probing Program'}
      </button>

      {/* Error */}
      {error && (
        <div style={{
          background: '#1f0a0a', border: '1px solid #7f1d1d', borderRadius: 6,
          padding: 10, display: 'flex', gap: 8, alignItems: 'flex-start',
        }}>
          <AlertTriangle size={14} color="#f87171" style={{ flexShrink: 0, marginTop: 1 }} />
          <span style={{ color: '#f87171', fontSize: 12 }}>{error}</span>
        </div>
      )}

      {/* Results */}
      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* Summary */}
          <div style={{
            background: '#0a1f0a', border: '1px solid #14532d', borderRadius: 6,
            padding: 10, display: 'flex', gap: 8, alignItems: 'center',
          }}>
            <CheckCircle size={14} color="#4ade80" />
            <span style={{ color: '#4ade80', fontSize: 12, fontWeight: 600 }}>
              Probing program generated — {result.measurement_points?.length ?? 0} measurement point(s)
            </span>
          </div>

          {/* Measurement points table */}
          <MeasurementPointsTable points={result.measurement_points} />

          {/* WCS update logic */}
          {result.wcs_update_logic && (
            <div style={{
              background: '#0d1117', border: '1px solid #1f2937', borderRadius: 6, padding: 10,
            }}>
              <div style={{ marginBottom: 4 }}><Label>WCS Update Logic</Label></div>
              <p style={{ margin: 0, fontSize: 11, color: '#93c5fd', lineHeight: 1.5 }}>
                {result.wcs_update_logic}
              </p>
            </div>
          )}

          {/* G-code preview */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <Label>G-code Preview</Label>
              <button
                onClick={downloadGcode}
                style={{
                  background: '#1f2937', color: '#9ca3af', border: '1px solid #374151',
                  borderRadius: 4, padding: '3px 8px', fontSize: 11, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: 4,
                }}
              >
                <Download size={11} /> Download .nc
              </button>
            </div>
            <GCodePreview gcode={result.gcode} />
          </div>

          {/* Honest caveats */}
          {result.honest_caveat && (
            <div style={{
              background: '#1c1400', border: '1px solid #78350f', borderRadius: 6,
              padding: 10, display: 'flex', gap: 8, alignItems: 'flex-start',
            }}>
              <AlertTriangle size={13} color="#fbbf24" style={{ flexShrink: 0, marginTop: 1 }} />
              <p style={{ margin: 0, fontSize: 11, color: '#fcd34d', lineHeight: 1.5 }}>
                <strong>Caveats:</strong> {result.honest_caveat}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
