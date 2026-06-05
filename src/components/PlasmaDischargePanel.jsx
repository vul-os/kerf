/**
 * PlasmaDischargePanel.jsx
 *
 * Visualisation panel for 1-D DC glow-discharge drift-diffusion results
 * (produced by plasma_discharge_simulate LLM tool, kerf-cfd package).
 *
 * Sections
 * --------
 *  1. Summary card  — gas, pressure, gap, voltage, V_bd, sheath thickness, J
 *  2. Density profiles chart  — n_e and n_i vs x (SVG sparkline, log-scale opt.)
 *  3. Electric field + potential chart  — E(x) and φ(x) vs x
 *  4. Ionisation rate profile  — S_ion(x) vs x
 *  5. Paschen curve  — V_bd vs pd with current operating point marked
 *  6. Model notes  — honest limitations banner
 *
 * Props
 * -----
 * x_m                  : number[] | null
 * n_e_m3               : number[] | null
 * n_i_m3               : number[] | null
 * E_field_V_m          : number[] | null
 * phi_V                : number[] | null
 * ionization_rate_m3_s : number[] | null
 * paschen_curve        : { pd_Pa_m: number[], V_bd_V: number[] } | null
 * current_density_A_m2 : number | null
 * sheath_thickness_m   : number | null
 * breakdown_estimate_V : number | null
 * converged            : boolean
 * gas                  : string
 * pressure_Pa          : number | null
 * gap_m                : number | null
 * voltage_V            : number | null
 * model_notes          : string | null
 */

// ── Utilities ─────────────────────────────────────────────────────────────────

function fmt(v, sig = 3) {
  if (v == null || v === '' || isNaN(v)) return '—'
  if (!isFinite(v)) return v > 0 ? '∞' : '-∞'
  const av = Math.abs(v)
  if (av === 0) return '0'
  if (av < 0.001 || av >= 1e5) return v.toExponential(sig - 1)
  return Number(v.toPrecision(sig)).toString()
}

function fmtSI(v, unit) {
  if (v == null || !isFinite(v)) return '—'
  return `${fmt(v)} ${unit}`
}

// ── SVG Sparkline helper ──────────────────────────────────────────────────────

function Sparkline({ xs, ys, color = '#60a5fa', width = 280, height = 80 }) {
  if (!xs || !ys || xs.length < 2) return <text fontSize="11" fill="#9ca3af">No data</text>

  const xMin = Math.min(...xs)
  const xMax = Math.max(...xs)
  const yMin = Math.min(...ys.filter(isFinite))
  const yMax = Math.max(...ys.filter(isFinite))
  const pad = 6

  const scaleX = v => pad + ((v - xMin) / Math.max(xMax - xMin, 1e-30)) * (width - 2 * pad)
  const scaleY = v => (height - pad) - ((v - yMin) / Math.max(yMax - yMin, 1e-30)) * (height - 2 * pad)

  const pts = xs
    .map((x, i) => `${scaleX(x)},${scaleY(ys[i])}`)
    .join(' ')

  return (
    <polyline
      points={pts}
      fill="none"
      stroke={color}
      strokeWidth="1.5"
      strokeLinejoin="round"
    />
  )
}

// ── Dual sparkline chart ──────────────────────────────────────────────────────

function LineChart({ xs, series, labels, yLabel, xLabel, width = 320, height = 120 }) {
  const COLORS = ['#60a5fa', '#f87171', '#34d399', '#fbbf24']
  const pad = { top: 10, right: 10, bottom: 28, left: 48 }
  const W = width - pad.left - pad.right
  const H = height - pad.top - pad.bottom

  if (!xs || xs.length < 2) {
    return (
      <svg width={width} height={height}>
        <text x={width / 2} y={height / 2} textAnchor="middle" fontSize="11" fill="#6b7280">No data</text>
      </svg>
    )
  }

  const xMin = Math.min(...xs)
  const xMax = Math.max(...xs)
  const allY = series.flatMap(s => s.filter(isFinite))
  const yMin = Math.min(...allY)
  const yMax = Math.max(...allY)

  const sx = v => pad.left + ((v - xMin) / Math.max(xMax - xMin, 1e-30)) * W
  const sy = v => pad.top + H - ((v - yMin) / Math.max(yMax - yMin, 1e-30)) * H

  return (
    <svg width={width} height={height} style={{ overflow: 'visible' }}>
      {/* Axes */}
      <line x1={pad.left} y1={pad.top} x2={pad.left} y2={pad.top + H} stroke="#374151" />
      <line x1={pad.left} y1={pad.top + H} x2={pad.left + W} y2={pad.top + H} stroke="#374151" />
      {/* Y label */}
      {yLabel && (
        <text
          x={10} y={pad.top + H / 2}
          fontSize="9" fill="#9ca3af"
          transform={`rotate(-90, 10, ${pad.top + H / 2})`}
          textAnchor="middle"
        >{yLabel}</text>
      )}
      {/* X label */}
      {xLabel && (
        <text x={pad.left + W / 2} y={height - 4} fontSize="9" fill="#9ca3af" textAnchor="middle">{xLabel}</text>
      )}
      {/* Y-axis ticks */}
      {[0, 0.5, 1].map(t => {
        const yv = yMin + t * (yMax - yMin)
        const yy = sy(yv)
        return (
          <g key={t}>
            <line x1={pad.left - 3} y1={yy} x2={pad.left} y2={yy} stroke="#374151" />
            <text x={pad.left - 5} y={yy + 3} fontSize="8" fill="#6b7280" textAnchor="end">{fmt(yv)}</text>
          </g>
        )
      })}
      {/* Series lines */}
      {series.map((ys, si) => {
        const pts = xs.map((x, i) => {
          const y = ys[i]
          if (!isFinite(y)) return null
          return `${sx(x)},${sy(y)}`
        }).filter(Boolean).join(' ')
        return (
          <polyline key={si} points={pts} fill="none" stroke={COLORS[si % COLORS.length]}
            strokeWidth="1.5" strokeLinejoin="round" />
        )
      })}
      {/* Legend */}
      {labels && labels.map((lbl, i) => (
        <g key={i} transform={`translate(${pad.left + W - 80}, ${pad.top + 4 + i * 14})`}>
          <line x1="0" y1="5" x2="12" y2="5" stroke={COLORS[i % COLORS.length]} strokeWidth="1.5" />
          <text x="15" y="9" fontSize="8" fill="#d1d5db">{lbl}</text>
        </g>
      ))}
    </svg>
  )
}

// ── Summary Card ─────────────────────────────────────────────────────────────

function SummaryCard({
  gas, pressure_Pa, gap_m, voltage_V,
  breakdown_estimate_V, sheath_thickness_m, current_density_A_m2, converged,
}) {
  const above = voltage_V != null && breakdown_estimate_V != null && isFinite(breakdown_estimate_V)
    ? voltage_V > breakdown_estimate_V
    : null

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px',
      marginBottom: '12px',
    }}>
      {[
        ['Gas', gas || '—'],
        ['Pressure', fmtSI(pressure_Pa, 'Pa')],
        ['Gap', fmtSI(gap_m, 'm')],
        ['Voltage', fmtSI(voltage_V, 'V')],
        ['Breakdown V (Paschen)', isFinite(breakdown_estimate_V) ? fmtSI(breakdown_estimate_V, 'V') : '∞'],
        ['Above Breakdown?', above == null ? '—' : above ? '✅ Yes' : '❌ No'],
        ['Sheath Thickness', fmtSI(sheath_thickness_m, 'm')],
        ['Current Density', fmtSI(current_density_A_m2, 'A/m²')],
        ['Converged', converged ? '✅' : '⏳ Transient'],
      ].map(([k, v]) => (
        <div key={k} style={{
          background: '#1f2937', borderRadius: '6px', padding: '8px',
          border: '1px solid #374151',
        }}>
          <div style={{ fontSize: '10px', color: '#9ca3af', marginBottom: '2px' }}>{k}</div>
          <div style={{ fontSize: '13px', color: '#f3f4f6', fontWeight: 500 }}>{v}</div>
        </div>
      ))}
    </div>
  )
}

// ── Paschen Curve Chart ───────────────────────────────────────────────────────

function PaschenChart({ paschen_curve, pressure_Pa, gap_m, voltage_V, breakdown_estimate_V }) {
  if (!paschen_curve) return <div style={{ color: '#6b7280', fontSize: '12px' }}>No Paschen data</div>

  const { pd_Pa_m, V_bd_V } = paschen_curve
  if (!pd_Pa_m || !V_bd_V) return null

  const W = 320, H = 140
  const pad = { top: 10, right: 20, bottom: 30, left: 55 }
  const w = W - pad.left - pad.right
  const h = H - pad.top - pad.bottom

  // Filter finite values
  const valid = pd_Pa_m.map((pd, i) => ({ pd, V: V_bd_V[i] }))
    .filter(p => isFinite(p.V) && p.V > 0 && p.V < 1e6)

  if (valid.length < 3) return <div style={{ color: '#6b7280', fontSize: '11px' }}>Paschen curve unavailable</div>

  const xMin = Math.log10(Math.min(...valid.map(p => p.pd)))
  const xMax = Math.log10(Math.max(...valid.map(p => p.pd)))
  const yMin = 0
  const yMax = Math.min(Math.max(...valid.map(p => p.V)) * 1.1, 5000)

  const sx = pd => pad.left + ((Math.log10(pd) - xMin) / Math.max(xMax - xMin, 0.01)) * w
  const sy = V => pad.top + h - ((V - yMin) / Math.max(yMax - yMin, 1)) * h

  const pts = valid.map(p => `${sx(p.pd)},${sy(p.V)}`).join(' ')

  // Current operating point
  const opPd = pressure_Pa != null && gap_m != null ? pressure_Pa * gap_m : null
  const opV = voltage_V

  return (
    <svg width={W} height={H} style={{ overflow: 'visible' }}>
      <line x1={pad.left} y1={pad.top} x2={pad.left} y2={pad.top + h} stroke="#374151" />
      <line x1={pad.left} y1={pad.top + h} x2={pad.left + w} y2={pad.top + h} stroke="#374151" />
      <text x={8} y={pad.top + h / 2} fontSize="9" fill="#9ca3af"
        transform={`rotate(-90, 8, ${pad.top + h / 2})`} textAnchor="middle">V_bd [V]</text>
      <text x={pad.left + w / 2} y={H - 4} fontSize="9" fill="#9ca3af" textAnchor="middle">pd [Pa·m]</text>
      {/* Y ticks */}
      {[0, 0.5, 1].map(t => {
        const yv = yMin + t * (yMax - yMin)
        const yy = sy(yv)
        return (
          <g key={t}>
            <line x1={pad.left - 3} y1={yy} x2={pad.left} y2={yy} stroke="#374151" />
            <text x={pad.left - 5} y={yy + 3} fontSize="8" fill="#6b7280" textAnchor="end">{Math.round(yv)}</text>
          </g>
        )
      })}
      {/* Paschen curve */}
      <polyline points={pts} fill="none" stroke="#a78bfa" strokeWidth="2" strokeLinejoin="round" />
      {/* Operating point */}
      {opPd != null && isFinite(opPd) && opV != null && (
        <circle
          cx={sx(opPd)} cy={sy(Math.min(opV, yMax))}
          r="5" fill="#f59e0b" stroke="#fbbf24" strokeWidth="1.5"
        />
      )}
      {/* Breakdown voltage horizontal line */}
      {breakdown_estimate_V != null && isFinite(breakdown_estimate_V) && breakdown_estimate_V < yMax && (
        <line
          x1={pad.left} y1={sy(breakdown_estimate_V)}
          x2={pad.left + w} y2={sy(breakdown_estimate_V)}
          stroke="#f87171" strokeWidth="1" strokeDasharray="4,3"
        />
      )}
      {/* Legend */}
      <g transform={`translate(${pad.left + w - 100}, ${pad.top + 4})`}>
        <line x1="0" y1="5" x2="12" y2="5" stroke="#a78bfa" strokeWidth="2" />
        <text x="15" y="9" fontSize="8" fill="#d1d5db">Paschen V_bd</text>
      </g>
      <g transform={`translate(${pad.left + w - 100}, ${pad.top + 18})`}>
        <circle cx="6" cy="5" r="4" fill="#f59e0b" />
        <text x="15" y="9" fontSize="8" fill="#d1d5db">Operating pt</text>
      </g>
    </svg>
  )
}

// ── Model Notes Banner ────────────────────────────────────────────────────────

function ModelNotesBanner({ notes }) {
  if (!notes) return null
  return (
    <div style={{
      background: '#1c1917', border: '1px solid #78350f',
      borderRadius: '6px', padding: '8px 10px', marginTop: '12px',
    }}>
      <div style={{ fontSize: '10px', fontWeight: 700, color: '#f59e0b', marginBottom: '4px' }}>
        Model Limitations (Honest)
      </div>
      <div style={{ fontSize: '10px', color: '#d97706', lineHeight: 1.5 }}>{notes}</div>
    </div>
  )
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export default function PlasmaDischargePanel({
  x_m, n_e_m3, n_i_m3, E_field_V_m, phi_V, ionization_rate_m3_s,
  paschen_curve: paschenData, current_density_A_m2, sheath_thickness_m,
  breakdown_estimate_V, converged, gas, pressure_Pa, gap_m, voltage_V,
  model_notes,
}) {
  const hasProfiles = x_m && x_m.length > 1

  return (
    <div style={{
      fontFamily: "'Inter', sans-serif",
      background: '#111827',
      color: '#f3f4f6',
      padding: '16px',
      borderRadius: '8px',
      maxWidth: '720px',
    }}>
      <div style={{ marginBottom: '12px' }}>
        <div style={{ fontSize: '16px', fontWeight: 700, color: '#e5e7eb' }}>
          Plasma / Gas Discharge
        </div>
        <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '2px' }}>
          1-D DC glow-discharge · drift-diffusion fluid model · Townsend ionisation + Poisson field
        </div>
      </div>

      {/* Summary */}
      <SummaryCard
        gas={gas}
        pressure_Pa={pressure_Pa}
        gap_m={gap_m}
        voltage_V={voltage_V}
        breakdown_estimate_V={breakdown_estimate_V}
        sheath_thickness_m={sheath_thickness_m}
        current_density_A_m2={current_density_A_m2}
        converged={converged}
      />

      {/* Density profiles */}
      {hasProfiles && (
        <div style={{ marginBottom: '12px' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: '#9ca3af', marginBottom: '6px' }}>
            Density Profiles (n_e, n_i)
          </div>
          <LineChart
            xs={x_m}
            series={[n_e_m3, n_i_m3]}
            labels={['n_e [m⁻³]', 'n_i [m⁻³]']}
            yLabel="n [m⁻³]"
            xLabel="x [m]"
            width={340}
            height={120}
          />
        </div>
      )}

      {/* Electric field + potential */}
      {hasProfiles && (
        <div style={{ marginBottom: '12px' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: '#9ca3af', marginBottom: '6px' }}>
            Electric Field + Potential
          </div>
          <LineChart
            xs={x_m}
            series={[E_field_V_m, phi_V]}
            labels={['E [V/m]', 'φ [V]']}
            yLabel="E / φ"
            xLabel="x [m]"
            width={340}
            height={120}
          />
        </div>
      )}

      {/* Ionisation rate */}
      {hasProfiles && ionization_rate_m3_s && (
        <div style={{ marginBottom: '12px' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: '#9ca3af', marginBottom: '6px' }}>
            Townsend Ionisation Rate S_ion [m⁻³ s⁻¹]
          </div>
          <LineChart
            xs={x_m}
            series={[ionization_rate_m3_s]}
            labels={['S_ion']}
            yLabel="S_ion"
            xLabel="x [m]"
            width={340}
            height={100}
          />
        </div>
      )}

      {/* Paschen curve */}
      <div style={{ marginBottom: '12px' }}>
        <div style={{ fontSize: '11px', fontWeight: 600, color: '#9ca3af', marginBottom: '6px' }}>
          Paschen Breakdown Curve  (V_bd vs pd)
        </div>
        <PaschenChart
          paschen_curve={paschenData}
          pressure_Pa={pressure_Pa}
          gap_m={gap_m}
          voltage_V={voltage_V}
          breakdown_estimate_V={breakdown_estimate_V}
        />
        <div style={{ fontSize: '9px', color: '#6b7280', marginTop: '4px' }}>
          Yellow dot = operating point. Dashed line = Paschen V_bd for this pd.
          Curve from Townsend criterion: V_bd = B·pd / ln(A·pd / ln(1+1/γ)).
        </div>
      </div>

      {/* Model limitations */}
      <ModelNotesBanner notes={model_notes} />
    </div>
  )
}
