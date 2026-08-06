/**
 * ControlsPanel.jsx
 *
 * Control-systems analysis panel — Bode plot, Nyquist diagram, and step-response
 * chart, rendered from pre-fetched tool output.
 *
 * Props
 * -----
 *   bode      — output of controls_bode_sweep  (omega, mag_db, phase_deg, + margins)
 *   nyquist   — output of controls_nyquist_sweep (omega, real_g, imag_g)
 *   step      — output of controls_tf_step_response (t, y, steady_state)
 *   width     — SVG width  (default 560)
 *   height    — SVG height per sub-chart (default 200)
 *   className — extra CSS class
 *
 * The component is purely presentational — it receives data as props and does
 * not fetch anything itself.
 *
 * Layout:
 *   ┌─────────────────────────────────────────┐
 *   │  Bode — Magnitude (dB)                  │
 *   ├─────────────────────────────────────────┤
 *   │  Bode — Phase (deg)                     │
 *   ├─────────────────────────────────────────┤
 *   │  Nyquist diagram                        │
 *   ├─────────────────────────────────────────┤
 *   │  Step response                          │
 *   └─────────────────────────────────────────┘
 *
 * References
 * ----------
 * Ogata, K. "Modern Control Engineering", 5th ed. (Pearson)
 * Nyquist, H. (1932). "Regeneration Theory." Bell System Tech. J. 11.
 */

import { useState } from 'react'

// ---------------------------------------------------------------------------
// Layout constants
// ---------------------------------------------------------------------------

const MAR = { top: 28, right: 20, bottom: 44, left: 60 }

// ---------------------------------------------------------------------------
// Generic helpers (pure functions — no hooks)
// ---------------------------------------------------------------------------

function scaleLinear(domMin, domMax, rangeMin, rangeMax) {
  const den = domMax - domMin
  return (v) => den === 0 ? rangeMin : rangeMin + ((v - domMin) / den) * (rangeMax - rangeMin)
}

function scaleLog10(domMin, domMax, rangeMin, rangeMax) {
  const lmin = Math.log10(domMin)
  const lmax = Math.log10(domMax)
  const den = lmax - lmin
  return (v) => den === 0 ? rangeMin : rangeMin + ((Math.log10(v) - lmin) / den) * (rangeMax - rangeMin)
}

function finiteRange(arr) {
  const finite = arr.filter(Number.isFinite)
  if (!finite.length) return [0, 1]
  return [Math.min(...finite), Math.max(...finite)]
}

function niceTicks(min, max, count = 6) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min]
  const step = (max - min) / (count - 1)
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(step) || 1)))
  const niceStep = Math.ceil(step / mag) * mag
  const start = Math.ceil(min / niceStep) * niceStep
  const ticks = []
  for (let v = start; v <= max + niceStep * 0.01; v += niceStep) {
    ticks.push(+v.toPrecision(5))
    if (ticks.length > 10) break
  }
  return ticks.length ? ticks : [min, max]
}

function logTicks(min, max) {
  const ticks = []
  for (let e = Math.floor(Math.log10(min)); e <= Math.ceil(Math.log10(max)); e++) {
    const v = Math.pow(10, e)
    if (v >= min * 0.99 && v <= max * 1.01) ticks.push(v)
  }
  return ticks.length ? ticks : [min, max]
}

function polyline(xs, ys, xScale, yScale) {
  const pts = []
  for (let i = 0; i < xs.length; i++) {
    const x = xScale(xs[i])
    const y = yScale(ys[i])
    if (Number.isFinite(x) && Number.isFinite(y)) pts.push(`${x.toFixed(1)},${y.toFixed(1)}`)
  }
  return pts.join(' ')
}

// ---------------------------------------------------------------------------
// Axis helpers
// ---------------------------------------------------------------------------

function YAxis({ scale, ticks, unit, width: w, height: h, x0 }) {
  return (
    <g>
      {ticks.map((t) => {
        const y = scale(t)
        if (!Number.isFinite(y)) return null
        return (
          <g key={t}>
            <line x1={x0} x2={x0 + w} y1={y} y2={y} stroke="#3a3a5a" strokeWidth={0.5} />
            <text x={x0 - 6} y={y + 4} textAnchor="end" fill="#888" fontSize={10} fontFamily="monospace">
              {t}
            </text>
          </g>
        )
      })}
      <text
        transform={`rotate(-90) translate(${-h / 2 - MAR.top},${x0 - 42})`}
        textAnchor="middle"
        fill="#aaa"
        fontSize={11}
        fontFamily="sans-serif"
      >
        {unit}
      </text>
    </g>
  )
}

function XAxisLog({ scale, ticks, unit, y0, width: w }) {
  return (
    <g>
      {ticks.map((t) => {
        const x = scale(t)
        if (!Number.isFinite(x)) return null
        const label = t >= 1000 ? `${t / 1000}k` : t >= 1 ? String(t) : String(t)
        return (
          <g key={t}>
            <line x1={x} x2={x} y1={MAR.top} y2={y0} stroke="#3a3a5a" strokeWidth={0.5} />
            <text x={x} y={y0 + 16} textAnchor="middle" fill="#888" fontSize={10} fontFamily="monospace">
              {label}
            </text>
          </g>
        )
      })}
      <text x={w / 2} y={y0 + 32} textAnchor="middle" fill="#aaa" fontSize={11} fontFamily="sans-serif">
        {unit}
      </text>
    </g>
  )
}

// ---------------------------------------------------------------------------
// Sub-chart: Bode Magnitude
// ---------------------------------------------------------------------------

function BodeMagChart({ bode, width, height }) {
  const innerW = width - MAR.left - MAR.right
  const innerH = height - MAR.top - MAR.bottom

  if (!bode || !bode.omega || !bode.mag_db) {
    return <EmptyState width={width} height={height} label="No Bode data" />
  }

  const { omega, mag_db, gain_margin_db, omega_gc } = bode
  const [magMin, magMax] = finiteRange(mag_db)
  const pad = Math.max((magMax - magMin) * 0.1, 5)
  const [omMin, omMax] = [omega[0], omega[omega.length - 1]]

  const xS = scaleLog10(omMin, omMax, MAR.left, MAR.left + innerW)
  const yS = scaleLinear(magMin - pad, magMax + pad, MAR.top + innerH, MAR.top)

  const xTicks = logTicks(omMin, omMax)
  const yTicks = niceTicks(magMin - pad, magMax + pad)

  const pts = polyline(omega, mag_db, xS, yS)

  return (
    <svg
      width={width}
      height={height}
      role="img"
      aria-label={`Bode magnitude plot${gain_margin_db != null ? `, GM=${gain_margin_db.toFixed(1)} dB` : ''}`}
    >
      <rect width={width} height={height} fill="#0d0d1a" rx={4} />
      {/* 0 dB reference line */}
      <line
        x1={MAR.left} x2={MAR.left + innerW}
        y1={yS(0)} y2={yS(0)}
        stroke="#445" strokeWidth={1} strokeDasharray="4 2"
      />
      <YAxis scale={yS} ticks={yTicks} unit="Magnitude (dB)" width={innerW} height={innerH} x0={MAR.left} />
      <XAxisLog scale={xS} ticks={xTicks} unit="ω (rad/s)" y0={MAR.top + innerH} width={width} />
      <polyline points={pts} fill="none" stroke="#4fc3f7" strokeWidth={2} />
      {/* Gain crossover marker */}
      {omega_gc != null && Number.isFinite(xS(omega_gc)) && (
        <line
          x1={xS(omega_gc)} x2={xS(omega_gc)}
          y1={MAR.top} y2={MAR.top + innerH}
          stroke="#ff9800" strokeWidth={1} strokeDasharray="3 2" opacity={0.8}
        />
      )}
      <text x={MAR.left + 6} y={MAR.top + 14} fill="#4fc3f7" fontSize={11} fontFamily="sans-serif" fontWeight="bold">
        Bode — Magnitude
      </text>
      {gain_margin_db != null && (
        <text x={MAR.left + innerW} y={MAR.top + 14} textAnchor="end" fill="#ffd54f" fontSize={10} fontFamily="monospace">
          GM = {gain_margin_db.toFixed(1)} dB
        </text>
      )}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Sub-chart: Bode Phase
// ---------------------------------------------------------------------------

function BodePhaseChart({ bode, width, height }) {
  const innerW = width - MAR.left - MAR.right
  const innerH = height - MAR.top - MAR.bottom

  if (!bode || !bode.omega || !bode.phase_deg) {
    return <EmptyState width={width} height={height} label="No Bode data" />
  }

  const { omega, phase_deg, phase_margin_deg, omega_pc } = bode
  const [phMin, phMax] = finiteRange(phase_deg)
  const pad = Math.max((phMax - phMin) * 0.1, 10)
  const [omMin, omMax] = [omega[0], omega[omega.length - 1]]

  const xS = scaleLog10(omMin, omMax, MAR.left, MAR.left + innerW)
  const yS = scaleLinear(phMin - pad, phMax + pad, MAR.top + innerH, MAR.top)

  const xTicks = logTicks(omMin, omMax)
  const yTicks = niceTicks(phMin - pad, phMax + pad)
  const pts = polyline(omega, phase_deg, xS, yS)

  return (
    <svg
      width={width}
      height={height}
      role="img"
      aria-label={`Bode phase plot${phase_margin_deg != null ? `, PM=${phase_margin_deg.toFixed(1)} deg` : ''}`}
    >
      <rect width={width} height={height} fill="#0d0d1a" rx={4} />
      {/* -180° reference */}
      {Number.isFinite(yS(-180)) && (
        <line
          x1={MAR.left} x2={MAR.left + innerW}
          y1={yS(-180)} y2={yS(-180)}
          stroke="#445" strokeWidth={1} strokeDasharray="4 2"
        />
      )}
      <YAxis scale={yS} ticks={yTicks} unit="Phase (deg)" width={innerW} height={innerH} x0={MAR.left} />
      <XAxisLog scale={xS} ticks={xTicks} unit="ω (rad/s)" y0={MAR.top + innerH} width={width} />
      <polyline points={pts} fill="none" stroke="#ce93d8" strokeWidth={2} />
      {omega_pc != null && Number.isFinite(xS(omega_pc)) && (
        <line
          x1={xS(omega_pc)} x2={xS(omega_pc)}
          y1={MAR.top} y2={MAR.top + innerH}
          stroke="#ff9800" strokeWidth={1} strokeDasharray="3 2" opacity={0.8}
        />
      )}
      <text x={MAR.left + 6} y={MAR.top + 14} fill="#ce93d8" fontSize={11} fontFamily="sans-serif" fontWeight="bold">
        Bode — Phase
      </text>
      {phase_margin_deg != null && (
        <text x={MAR.left + innerW} y={MAR.top + 14} textAnchor="end" fill="#ffd54f" fontSize={10} fontFamily="monospace">
          PM = {phase_margin_deg.toFixed(1)}°
        </text>
      )}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Sub-chart: Nyquist diagram
// ---------------------------------------------------------------------------

function NyquistChart({ nyquist, width, height }) {
  const innerW = width - MAR.left - MAR.right
  const innerH = height - MAR.top - MAR.bottom

  if (!nyquist || !nyquist.real_g || !nyquist.imag_g) {
    return <EmptyState width={width} height={height} label="No Nyquist data" />
  }

  const { real_g, imag_g, encirclements_approx } = nyquist

  const [reMin, reMax] = finiteRange(real_g)
  const [imMin, imMax] = finiteRange(imag_g)
  const rePad = Math.max((reMax - reMin) * 0.15, 0.5)
  const imPad = Math.max((imMax - imMin) * 0.15, 0.5)

  // Ensure -1+0j is visible
  const reMinV = Math.min(reMin - rePad, -1.5)
  const reMaxV = Math.max(reMax + rePad, 0.5)
  const imMinV = imMin - imPad
  const imMaxV = imMax + imPad

  const xS = scaleLinear(reMinV, reMaxV, MAR.left, MAR.left + innerW)
  const yS = scaleLinear(imMinV, imMaxV, MAR.top + innerH, MAR.top)

  const xTicks = niceTicks(reMinV, reMaxV, 5)
  const yTicks = niceTicks(imMinV, imMaxV, 5)

  const pts = polyline(real_g, imag_g, xS, yS)

  // Axis lines
  const y0line = yS(0)
  const x0line = xS(0)

  return (
    <svg width={width} height={height} role="img" aria-label="Nyquist diagram">
      <rect width={width} height={height} fill="#0d0d1a" rx={4} />
      {/* Real axis */}
      <line x1={MAR.left} x2={MAR.left + innerW} y1={y0line} y2={y0line} stroke="#3a3a5a" strokeWidth={1} />
      {/* Imaginary axis */}
      <line x1={x0line} x2={x0line} y1={MAR.top} y2={MAR.top + innerH} stroke="#3a3a5a" strokeWidth={1} />
      {/* Grid */}
      {xTicks.map((t) => {
        const x = xS(t)
        return Number.isFinite(x) ? (
          <line key={t} x1={x} x2={x} y1={MAR.top} y2={MAR.top + innerH} stroke="#2a2a3a" strokeWidth={0.5} />
        ) : null
      })}
      {yTicks.map((t) => {
        const y = yS(t)
        return Number.isFinite(y) ? (
          <line key={t} x1={MAR.left} x2={MAR.left + innerW} y1={y} y2={y} stroke="#2a2a3a" strokeWidth={0.5} />
        ) : null
      })}
      {/* Tick labels */}
      {xTicks.map((t) => {
        const x = xS(t)
        return Number.isFinite(x) ? (
          <text key={t} x={x} y={MAR.top + innerH + 16} textAnchor="middle" fill="#888" fontSize={9} fontFamily="monospace">{t}</text>
        ) : null
      })}
      {yTicks.map((t) => {
        const y = yS(t)
        return Number.isFinite(y) ? (
          <text key={t} x={MAR.left - 6} y={y + 3} textAnchor="end" fill="#888" fontSize={9} fontFamily="monospace">{t}</text>
        ) : null
      })}
      {/* Curve */}
      <polyline points={pts} fill="none" stroke="#80cbc4" strokeWidth={2} />
      {/* -1+0j critical point */}
      <circle cx={xS(-1)} cy={yS(0)} r={5} fill="#f44336" opacity={0.9} />
      <text x={xS(-1) + 8} y={yS(0) - 6} fill="#f44336" fontSize={10} fontFamily="monospace">−1</text>
      <text x={MAR.left + 6} y={MAR.top + 14} fill="#80cbc4" fontSize={11} fontFamily="sans-serif" fontWeight="bold">
        Nyquist Diagram
      </text>
      {encirclements_approx != null && (
        <text x={MAR.left + innerW} y={MAR.top + 14} textAnchor="end" fill={encirclements_approx === 0 ? '#66bb6a' : '#ef5350'} fontSize={10} fontFamily="monospace">
          N = {encirclements_approx}
        </text>
      )}
      <text x={width / 2} y={MAR.top + innerH + 32} textAnchor="middle" fill="#aaa" fontSize={11} fontFamily="sans-serif">Re(G)</text>
      <text transform={`rotate(-90) translate(${-(MAR.top + innerH / 2)},${MAR.left - 44})`} textAnchor="middle" fill="#aaa" fontSize={11} fontFamily="sans-serif">Im(G)</text>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Sub-chart: Step response
// ---------------------------------------------------------------------------

function StepResponseChart({ step, width, height }) {
  const innerW = width - MAR.left - MAR.right
  const innerH = height - MAR.top - MAR.bottom

  if (!step || !step.t || !step.y) {
    return <EmptyState width={width} height={height} label="No step-response data" />
  }

  const { t, y, steady_state, response_type } = step
  const [yMin, yMax] = finiteRange(y)
  const yPad = Math.max((yMax - yMin) * 0.1, 0.05)
  const xS = scaleLinear(t[0], t[t.length - 1], MAR.left, MAR.left + innerW)
  const yS = scaleLinear(yMin - yPad, yMax + yPad, MAR.top + innerH, MAR.top)

  const xTicks = niceTicks(t[0], t[t.length - 1])
  const yTicks = niceTicks(yMin - yPad, yMax + yPad)
  const pts = polyline(t, y, xS, yS)

  const label = response_type === 'impulse' ? 'Impulse Response' : 'Step Response'

  return (
    <svg width={width} height={height} role="img" aria-label={label}>
      <rect width={width} height={height} fill="#0d0d1a" rx={4} />
      {steady_state != null && Number.isFinite(yS(steady_state)) && (
        <line
          x1={MAR.left} x2={MAR.left + innerW}
          y1={yS(steady_state)} y2={yS(steady_state)}
          stroke="#444" strokeWidth={1} strokeDasharray="4 2"
        />
      )}
      <YAxis scale={yS} ticks={yTicks} unit="y(t)" width={innerW} height={innerH} x0={MAR.left} />
      {/* X axis ticks */}
      {xTicks.map((t_) => {
        const x = xS(t_)
        return Number.isFinite(x) ? (
          <g key={t_}>
            <line x1={x} x2={x} y1={MAR.top} y2={MAR.top + innerH} stroke="#2a2a3a" strokeWidth={0.5} />
            <text x={x} y={MAR.top + innerH + 16} textAnchor="middle" fill="#888" fontSize={10} fontFamily="monospace">{t_}</text>
          </g>
        ) : null
      })}
      <text x={width / 2} y={MAR.top + innerH + 32} textAnchor="middle" fill="#aaa" fontSize={11} fontFamily="sans-serif">
        t (s)
      </text>
      <polyline points={pts} fill="none" stroke="#a5d6a7" strokeWidth={2} />
      <text x={MAR.left + 6} y={MAR.top + 14} fill="#a5d6a7" fontSize={11} fontFamily="sans-serif" fontWeight="bold">
        {label}
      </text>
      {steady_state != null && (
        <text x={MAR.left + innerW} y={MAR.top + 14} textAnchor="end" fill="#ffd54f" fontSize={10} fontFamily="monospace">
          y∞ = {steady_state.toFixed(4)}
        </text>
      )}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Empty state helper
// ---------------------------------------------------------------------------

function EmptyState({ width, height, label }) {
  return (
    <div
      style={{
        width,
        height,
        background: '#0d0d1a',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: 4,
        color: '#555',
        fontFamily: 'sans-serif',
        fontSize: 13,
      }}
    >
      {label}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function ControlsPanel({
  bode = null,
  nyquist = null,
  step = null,
  width = 560,
  height = 200,
  className = '',
}) {
  const [activeTab, setActiveTab] = useState('bode')

  const tabs = [
    { id: 'bode',    label: 'Bode' },
    { id: 'nyquist', label: 'Nyquist' },
    { id: 'step',    label: 'Step Response' },
  ]

  const tabStyle = (id) => ({
    padding: '6px 14px',
    background: activeTab === id ? '#1e2040' : 'transparent',
    border: 'none',
    borderBottom: activeTab === id ? '2px solid #4fc3f7' : '2px solid transparent',
    color: activeTab === id ? '#4fc3f7' : '#888',
    cursor: 'pointer',
    fontFamily: 'sans-serif',
    fontSize: 13,
  })

  return (
    <div className={`controls-panel ${className}`} style={{ display: 'inline-block' }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: '1px solid #2a2a3a', marginBottom: 8 }}>
        {tabs.map((tab) => (
          <button key={tab.id} style={tabStyle(tab.id)} onClick={() => setActiveTab(tab.id)}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Charts */}
      {activeTab === 'bode' && (
        <div>
          <BodeMagChart bode={bode} width={width} height={height} />
          <div style={{ height: 4 }} />
          <BodePhaseChart bode={bode} width={width} height={height} />
        </div>
      )}
      {activeTab === 'nyquist' && (
        <NyquistChart nyquist={nyquist} width={width} height={height * 1.5} />
      )}
      {activeTab === 'step' && (
        <StepResponseChart step={step} width={width} height={height * 1.5} />
      )}

      {/* Margins summary */}
      {activeTab === 'bode' && bode && (
        <div style={{
          marginTop: 6,
          padding: '6px 10px',
          background: '#0d0d1a',
          borderRadius: 4,
          fontFamily: 'monospace',
          fontSize: 12,
          color: '#aaa',
          display: 'flex',
          gap: 20,
        }}>
          <span>GM: <strong style={{ color: bode.gain_margin_db != null && bode.gain_margin_db >= 6 ? '#66bb6a' : '#ef5350' }}>
            {bode.gain_margin_db != null ? `${bode.gain_margin_db.toFixed(1)} dB` : '—'}
          </strong></span>
          <span>PM: <strong style={{ color: bode.phase_margin_deg != null && bode.phase_margin_deg >= 30 ? '#66bb6a' : '#ef5350' }}>
            {bode.phase_margin_deg != null ? `${bode.phase_margin_deg.toFixed(1)}°` : '—'}
          </strong></span>
          <span>ωgc: <strong style={{ color: '#ffd54f' }}>
            {bode.omega_gc != null ? `${bode.omega_gc.toFixed(3)} rad/s` : '—'}
          </strong></span>
        </div>
      )}
    </div>
  )
}
