/**
 * MotorSelectPanel.jsx — Rocket motor database browser and selector.
 *
 * Allows users to:
 *   1. Browse the built-in motor catalogue (Estes, Aerotech, Cesaroni).
 *   2. Filter by impulse class (A–M), manufacturer, or diameter.
 *   3. Select a motor to view full performance data + thrust-curve chart.
 *   4. Paste / upload a raw RASP .eng file for custom motor parsing.
 *   5. See the NAR/TRA impulse classification for any total impulse value.
 *
 * Props
 * ─────
 * motors        {Array|null}   Pre-loaded motor list from API response.
 * selectedMotor {object|null}  Currently selected motor detail (from 'get' op).
 * onFilter      {Function}     Called with {impulse_class, manufacturer, diameter_mm}
 *                              to trigger the 'list' operation.
 * onSelect      {Function}     Called with motor name string to trigger 'get'.
 * onParseEng    {Function}     Called with eng_text string to trigger 'parse_eng'.
 * loading       {boolean}      Show loading indicator.
 *
 * Wire-up: parent posts to /api/llm-tools with tool_name='aero_motor_database'
 * and passes response into motors / selectedMotor props.
 *
 * Usage
 * ─────
 * <MotorSelectPanel
 *   motors={motorList}
 *   selectedMotor={detail}
 *   onFilter={handleFilter}
 *   onSelect={handleSelect}
 *   onParseEng={handleParse}
 *   loading={isLoading}
 * />
 */

import { useState, useMemo } from 'react'

// ---------------------------------------------------------------------------
// Impulse class colour palette (A=teal, B=blue, …, M=red)
// ---------------------------------------------------------------------------

const CLASS_COLORS = {
  '1/4A': '#94a3b8',
  '1/2A': '#94a3b8',
  'A': '#22d3ee',
  'B': '#38bdf8',
  'C': '#60a5fa',
  'D': '#818cf8',
  'E': '#a78bfa',
  'F': '#c084fc',
  'G': '#e879f9',
  'H': '#f472b6',
  'I': '#fb7185',
  'J': '#f87171',
  'K': '#fbbf24',
  'L': '#fb923c',
  'M': '#ef4444',
  'N': '#dc2626',
  'O': '#b91c1c',
}

const classColor = (cls) => CLASS_COLORS[cls] ?? '#94a3b8'

// ---------------------------------------------------------------------------
// Built-in demo catalogue (shown when no API data available)
// ---------------------------------------------------------------------------

const DEMO_MOTORS = [
  { name: 'A8',  manufacturer: 'Estes',    impulse_class: 'A', total_impulse_ns: 2.40,  average_thrust_n: 5.0,   burn_time_s: 0.49, isp_s: 80,  diameter_mm: 18, propellant_mass_g: 3.1  },
  { name: 'C6',  manufacturer: 'Estes',    impulse_class: 'D', total_impulse_ns: 11.2,  average_thrust_n: 6.6,   burn_time_s: 1.70, isp_s: 104, diameter_mm: 18, propellant_mass_g: 11.0 },
  { name: 'D12', manufacturer: 'Estes',    impulse_class: 'D', total_impulse_ns: 19.7,  average_thrust_n: 11.2,  burn_time_s: 1.75, isp_s: 96,  diameter_mm: 24, propellant_mass_g: 20.8 },
  { name: 'G79', manufacturer: 'Aerotech', impulse_class: 'G', total_impulse_ns: 87.5,  average_thrust_n: 83.3,  burn_time_s: 1.05, isp_s: 223, diameter_mm: 29, propellant_mass_g: 40.0 },
  { name: 'H128',manufacturer: 'Aerotech', impulse_class: 'H', total_impulse_ns: 184.4, average_thrust_n: 130.7, burn_time_s: 1.38, isp_s: 221, diameter_mm: 38, propellant_mass_g: 85.0 },
  { name: 'J285', manufacturer: 'Cesaroni', impulse_class: 'I', total_impulse_ns: 581.0, average_thrust_n: 276.7, burn_time_s: 2.10, isp_s: 182, diameter_mm: 54, propellant_mass_g: 326.0 },
  { name: 'K711', manufacturer: 'Cesaroni', impulse_class: 'K', total_impulse_ns: 1298.0, average_thrust_n: 763.5, burn_time_s: 1.70, isp_s: 201, diameter_mm: 75, propellant_mass_g: 660.0 },
]

const DEMO_DETAIL = {
  ...DEMO_MOTORS[3],
  length_mm: 124,
  total_mass_g: 72,
  delays_s: [10],
  n_thrust_points: 9,
  thrust_curve: [
    { time_s: 0.00, thrust_n:   0 },
    { time_s: 0.06, thrust_n: 110 },
    { time_s: 0.15, thrust_n: 100 },
    { time_s: 0.40, thrust_n:  90 },
    { time_s: 0.70, thrust_n:  82 },
    { time_s: 0.90, thrust_n:  75 },
    { time_s: 1.00, thrust_n:  60 },
    { time_s: 1.05, thrust_n:  30 },
    { time_s: 1.08, thrust_n:   0 },
  ],
}

// ---------------------------------------------------------------------------
// Thrust curve SVG chart
// ---------------------------------------------------------------------------

function ThrustCurveChart({ curve, width = 300, height = 100 }) {
  if (!curve || curve.length < 2) return null

  const pad = { top: 8, right: 8, bottom: 20, left: 36 }
  const W = width  - pad.left - pad.right
  const H = height - pad.top  - pad.bottom

  const tMax = Math.max(...curve.map(p => p.time_s))
  const fMax = Math.max(...curve.map(p => p.thrust_n))

  const sx = t => (t / (tMax || 1)) * W
  const sy = f => H - (f / (fMax || 1)) * H

  const pathD = curve.map((p, i) =>
    `${i === 0 ? 'M' : 'L'}${sx(p.time_s).toFixed(1)},${sy(p.thrust_n).toFixed(1)}`
  ).join(' ')

  // Fill area
  const fillD = `${pathD} L${sx(tMax)},${H.toFixed(1)} L0,${H.toFixed(1)} Z`

  // Grid lines (2 horizontal ticks)
  const gridF = [fMax * 0.5, fMax].map(f => ({
    f,
    y: (sy(f) + pad.top).toFixed(1),
    label: f >= 1000 ? `${(f / 1000).toFixed(1)}kN` : `${f.toFixed(0)}N`,
  }))

  return (
    <svg width={width} height={height} style={{ display: 'block', overflow: 'visible' }}>
      <g transform={`translate(${pad.left},${pad.top})`}>
        {/* Grid */}
        {gridF.map((g, i) => (
          <g key={i}>
            <line x1={0} y1={sy(g.f).toFixed(1)} x2={W} y2={sy(g.f).toFixed(1)}
                  stroke="#1e293b" strokeWidth={1} />
            <text x={-4} y={(parseFloat(sy(g.f)) + 3).toFixed(1)}
                  fill="#475569" fontSize={8} textAnchor="end">{g.label}</text>
          </g>
        ))}

        {/* Baseline */}
        <line x1={0} y1={H} x2={W} y2={H} stroke="#334155" strokeWidth={1} />

        {/* Fill */}
        <path d={fillD} fill="#e879f920" />

        {/* Curve */}
        <path d={pathD} fill="none" stroke="#e879f9" strokeWidth={1.5}
              strokeLinejoin="round" strokeLinecap="round" />

        {/* Axes labels */}
        <text x={W / 2} y={H + 14} fill="#475569" fontSize={8} textAnchor="middle">
          time [s]
        </text>
        <text x={sx(0)} y={H + 14} fill="#475569" fontSize={8} textAnchor="start">
          0
        </text>
        <text x={sx(tMax)} y={H + 14} fill="#475569" fontSize={8} textAnchor="end">
          {tMax.toFixed(2)}
        </text>
      </g>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Motor list row
// ---------------------------------------------------------------------------

function MotorRow({ motor, selected, onSelect }) {
  const cls = motor.impulse_class ?? '?'
  return (
    <tr
      className={`msp-motor-row ${selected ? 'msp-motor-row-sel' : ''}`}
      onClick={() => onSelect?.(motor.name)}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && onSelect?.(motor.name)}
    >
      <td>
        <span className="msp-class-badge" style={{ background: classColor(cls) + '30', color: classColor(cls) }}>
          {cls}
        </span>
      </td>
      <td className="msp-name">{motor.name}</td>
      <td className="msp-mfr">{motor.manufacturer}</td>
      <td className="msp-num">{motor.total_impulse_ns?.toFixed(1)} <span className="msp-unit">N·s</span></td>
      <td className="msp-num">{motor.average_thrust_n?.toFixed(0)} <span className="msp-unit">N</span></td>
      <td className="msp-num">{motor.isp_s?.toFixed(0)} <span className="msp-unit">s</span></td>
      <td className="msp-num">{motor.burn_time_s?.toFixed(2)} <span className="msp-unit">s</span></td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Motor detail sidebar
// ---------------------------------------------------------------------------

function MotorDetail({ motor }) {
  if (!motor) return null
  const cls = motor.impulse_class ?? '?'
  const clrBase = classColor(cls)
  return (
    <div className="msp-detail">
      <div className="msp-detail-header" style={{ borderBottom: `2px solid ${clrBase}` }}>
        <span className="msp-detail-name">{motor.name}</span>
        <span className="msp-class-badge" style={{ background: clrBase + '30', color: clrBase }}>
          Class {cls}
        </span>
      </div>

      <div className="msp-detail-grid">
        <DetailRow label="Manufacturer"   value={motor.manufacturer} />
        <DetailRow label="Diameter"       value={motor.diameter_mm}  unit="mm" />
        <DetailRow label="Length"         value={motor.length_mm}    unit="mm" />
        <DetailRow label="Total impulse"  value={motor.total_impulse_ns?.toFixed(2)} unit="N·s" />
        <DetailRow label="Average thrust" value={motor.average_thrust_n?.toFixed(1)} unit="N" />
        <DetailRow label="Peak thrust"    value={motor.peak_thrust_n?.toFixed(1)} unit="N" />
        <DetailRow label="Burn time"      value={motor.burn_time_s?.toFixed(3)} unit="s" />
        <DetailRow label="Isp"            value={motor.isp_s?.toFixed(1)} unit="s" />
        <DetailRow label="Propellant"     value={motor.propellant_mass_g?.toFixed(1)} unit="g" />
        <DetailRow label="Total mass"     value={motor.total_mass_g?.toFixed(1)} unit="g" />
        {motor.delays_s?.length > 0 && (
          <DetailRow label="Delays" value={motor.delays_s?.join(', ')} unit="s" />
        )}
      </div>

      {motor.thrust_curve && (
        <div className="msp-chart-wrap">
          <div className="msp-chart-label">Thrust curve</div>
          <ThrustCurveChart curve={motor.thrust_curve} />
        </div>
      )}
    </div>
  )
}

function DetailRow({ label, value, unit }) {
  return (
    <div className="msp-detail-row">
      <span className="msp-detail-label">{label}</span>
      <span className="msp-detail-value">
        {value ?? '—'}
        {unit && <span className="msp-unit"> {unit}</span>}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Eng file paste input
// ---------------------------------------------------------------------------

function EngPasteInput({ onParse }) {
  const [text, setText] = useState('')
  return (
    <div className="msp-eng-input">
      <div className="msp-eng-label">Paste RASP .eng file:</div>
      <textarea
        className="msp-eng-textarea"
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={'; MotorName 29mm 120mm 0 30g 60g Manufacturer\n0.000 0.00\n0.500 100.00\n1.000 0.00'}
        rows={5}
      />
      <button
        className="od-btn od-btn-batch"
        onClick={() => text.trim() && onParse?.(text)}
        disabled={!text.trim()}
      >
        Parse .eng
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

const CLASSES = ['', '1/2A', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N']

function FilterBar({ onFilter }) {
  const [cls, setCls]    = useState('')
  const [mfr, setMfr]    = useState('')
  const [diam, setDiam]  = useState('')

  const apply = () => onFilter?.({
    impulse_class: cls || undefined,
    manufacturer: mfr || undefined,
    diameter_mm: diam ? parseFloat(diam) : undefined,
  })

  return (
    <div className="msp-filter-bar">
      <select className="msp-select" value={cls} onChange={e => setCls(e.target.value)}>
        {CLASSES.map(c => (
          <option key={c} value={c}>{c || 'All classes'}</option>
        ))}
      </select>
      <input
        className="msp-input"
        value={mfr}
        onChange={e => setMfr(e.target.value)}
        placeholder="Manufacturer…"
      />
      <input
        className="msp-input msp-input-sm"
        value={diam}
        onChange={e => setDiam(e.target.value)}
        placeholder="Ø mm"
        type="number"
        min={0}
      />
      <button className="od-btn od-btn-batch" onClick={apply}>Filter</button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function MotorSelectPanel({
  motors: motorsProp = null,
  selectedMotor: selectedMotorProp = null,
  onFilter = null,
  onSelect = null,
  onParseEng = null,
  loading: loadingProp = false,
  content,
}) {
  // Backward-compatible content string: JSON.parse it and merge over prop defaults.
  let _parsed = null
  if (content != null) {
    try { _parsed = JSON.parse(content) } catch { /* ignore */ }
  }
  const motors = (_parsed && _parsed.motors !== undefined) ? _parsed.motors : motorsProp
  const selectedMotor = (_parsed && _parsed.selectedMotor !== undefined) ? _parsed.selectedMotor : selectedMotorProp
  const loading = (_parsed && _parsed.loading !== undefined) ? _parsed.loading : loadingProp
  const [showEng, setShowEng]     = useState(false)
  const [localSel, setLocalSel]   = useState(null)
  const [showDemo, setShowDemo]   = useState(false)

  const motorList = motors ?? (showDemo ? DEMO_MOTORS : null)
  const detail    = selectedMotor ?? (showDemo && localSel === 'G79' ? DEMO_DETAIL : null)

  const handleSelect = (name) => {
    setLocalSel(name)
    onSelect?.(name)
  }

  return (
    <div className="msp-panel">
      <style>{MSP_STYLES}</style>

      {/* Header */}
      <div className="od-header">
        <span className="od-title">Motor Database</span>
        <span className="od-subtitle">Thrustcurve / RASP .eng</span>
        <button
          className="od-btn od-btn-demo"
          style={{ marginLeft: 'auto', fontSize: 10 }}
          onClick={() => setShowDemo(d => !d)}
        >
          {showDemo ? 'Hide Demo' : 'Demo Data'}
        </button>
      </div>

      {/* Filter bar */}
      <FilterBar onFilter={onFilter} />

      {/* Eng paste toggle */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <button
          className="od-btn od-btn-demo"
          onClick={() => setShowEng(e => !e)}
        >
          {showEng ? 'Hide .eng input' : 'Parse .eng file'}
        </button>
      </div>
      {showEng && <EngPasteInput onParse={onParseEng} />}

      {loading && (
        <div className="od-loading">
          <span className="od-spinner" />
          Loading motors…
        </div>
      )}

      {/* Main content: list + detail side-by-side */}
      {!loading && (
        <div className="msp-content">
          {/* Motor list (shown when available) */}
          {motorList && (
            <div className="msp-list-wrap">
              <table className="msp-table">
                <thead>
                  <tr>
                    <th>Class</th>
                    <th>Name</th>
                    <th>Mfr</th>
                    <th>Impulse</th>
                    <th>Avg F</th>
                    <th>Isp</th>
                    <th>Burn</th>
                  </tr>
                </thead>
                <tbody>
                  {motorList.map(m => (
                    <MotorRow
                      key={m.name}
                      motor={m}
                      selected={localSel === m.name}
                      onSelect={handleSelect}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Motor detail — shown whenever selectedMotor is available */}
          {detail && <MotorDetail motor={detail} />}
        </div>
      )}

      {/* Empty state */}
      {!loading && !motorList && !detail && !showDemo && (
        <div className="od-empty">
          <div className="od-empty-icon">🚀</div>
          <div className="od-empty-text">No motors loaded.</div>
          <div className="od-empty-sub">
            Apply a filter to load motors from the catalogue,
            or paste a RASP .eng file.
          </div>
        </div>
      )}

      {/* Footnote */}
      <div className="od-footnote">
        NAR/TRA impulse classification · Thrustcurve.org RASP .eng format ·
        Sutton &amp; Biblarz RPE 9th ed. §11
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const MSP_STYLES = `
.msp-panel {
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 10px;
  padding: 18px 20px 14px;
  font-family: 'Inter', 'SF Pro Display', system-ui, sans-serif;
  color: #e2e8f0;
  min-width: 500px;
  max-width: 900px;
  box-sizing: border-box;
}
.msp-filter-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  align-items: center;
}
.msp-select, .msp-input {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 5px;
  color: #e2e8f0;
  padding: 4px 8px;
  font-size: 12px;
}
.msp-input-sm { width: 64px; }
.msp-eng-input {
  background: #1e293b;
  border-radius: 7px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.msp-eng-label {
  font-size: 11px;
  color: #64748b;
  margin-bottom: 4px;
}
.msp-eng-textarea {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 4px;
  color: #e2e8f0;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 11px;
  width: 100%;
  box-sizing: border-box;
  padding: 6px;
  margin-bottom: 6px;
  resize: vertical;
}
.msp-content {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.msp-list-wrap {
  flex: 1;
  overflow-x: auto;
}
.msp-table {
  border-collapse: collapse;
  width: 100%;
  font-size: 11px;
}
.msp-table th {
  background: #1e293b;
  color: #94a3b8;
  font-size: 10px;
  font-weight: 600;
  padding: 5px 8px;
  text-align: left;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  white-space: nowrap;
}
.msp-motor-row {
  cursor: pointer;
  transition: background 0.1s;
}
.msp-motor-row:hover { background: #1e293b; }
.msp-motor-row-sel  { background: #1e293b; outline: 1px solid #6d28d9; }
.msp-motor-row td   { padding: 5px 8px; border-bottom: 1px solid #1e293b10; }
.msp-class-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 9999px;
  font-size: 10px;
  font-weight: 700;
}
.msp-name { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: #f1f5f9; }
.msp-mfr  { color: #94a3b8; }
.msp-num  { font-family: 'JetBrains Mono', monospace; color: #cbd5e1; text-align: right; }
.msp-unit { font-size: 9px; color: #475569; }
.msp-detail {
  width: 280px;
  min-width: 240px;
  background: #1e293b;
  border-radius: 8px;
  padding: 12px 14px;
}
.msp-detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding-bottom: 6px;
}
.msp-detail-name {
  font-size: 15px;
  font-weight: 700;
  color: #f1f5f9;
  font-family: 'JetBrains Mono', monospace;
}
.msp-detail-grid {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-bottom: 10px;
}
.msp-detail-row {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  padding: 2px 0;
  border-bottom: 1px solid #0f172a40;
}
.msp-detail-label { color: #94a3b8; }
.msp-detail-value { color: #f1f5f9; font-family: 'JetBrains Mono', monospace; }
.msp-chart-wrap {
  background: #0f172a;
  border-radius: 6px;
  padding: 8px;
}
.msp-chart-label {
  font-size: 10px;
  color: #64748b;
  margin-bottom: 4px;
}
`
