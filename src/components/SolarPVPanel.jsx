/**
 * SolarPVPanel.jsx
 *
 * Solar PV analysis panel — renders I-V and P-V curves from pre-fetched
 * tool output (pv_cell_iv, pv_module_shaded_iv, pv_mppt_mismatch_loss).
 *
 * Props
 * -----
 *   ivData      — output of pv_cell_iv or pv_module_shaded_iv
 *                 { iv_curve: [{v, i, p}], isc_a?, voc_v?, mpp?: {p_w, v_v, i_a} }
 *   title       — chart title (default "PV I-V / P-V Curve")
 *   showPV      — show P-V overlay (default true)
 *   width       — SVG width  (default 560)
 *   height      — SVG height (default 340)
 *   className   — extra CSS class
 *
 * Two y-axes:
 *   Left  → Current I (A)   — blue line
 *   Right → Power  P (W)    — amber line (when showPV)
 *
 * The component is purely presentational — no fetch logic.
 *
 * References
 * ----------
 * Villalva, M.G. et al. (2009) "Comprehensive approach to the electrical
 *   modelling of photovoltaic modules." IEEE Trans. Power Electron. 24(5).
 * De Soto, W. et al. (2006) "Improvement and validation of a model for
 *   photovoltaic array performance." Solar Energy 80(1).
 */

import { useState } from 'react'

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

const MAR = { top: 36, right: 60, bottom: 52, left: 60 }

// ---------------------------------------------------------------------------
// Scale helpers
// ---------------------------------------------------------------------------

function scaleLinear(domMin, domMax, rangeMin, rangeMax) {
  const den = domMax - domMin
  return (v) => den === 0 ? rangeMin : rangeMin + ((v - domMin) / den) * (rangeMax - rangeMin)
}

function niceTicks(min, max, count = 6) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [min]
  const step = (max - min) / Math.max(count - 1, 1)
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(step) || 1)))
  const niceStep = Math.ceil(step / mag) * mag
  const start = Math.ceil(min / niceStep) * niceStep
  const ticks = []
  for (let v = start; v <= max + niceStep * 0.01; v += niceStep) {
    ticks.push(+v.toPrecision(5))
    if (ticks.length > 12) break
  }
  return ticks.length ? ticks : [min, max]
}

function polylinePts(data, xFn, yFn) {
  return data
    .map((d) => {
      const x = xFn(d)
      const y = yFn(d)
      return Number.isFinite(x) && Number.isFinite(y) ? `${x.toFixed(1)},${y.toFixed(1)}` : null
    })
    .filter(Boolean)
    .join(' ')
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

function Tooltip({ x, y, v, i, p, show }) {
  if (!show) return null
  return (
    <g transform={`translate(${x + 10},${y - 10})`} style={{ pointerEvents: 'none' }}>
      <rect x={0} y={-20} width={130} height={60} rx={4} fill="#1a1a2e" stroke="#3f3f5a" strokeWidth={1} opacity={0.97} />
      <text fill="#e0e0f0" fontSize={11} fontFamily="monospace">
        <tspan x={6} dy={0}>V = {v?.toFixed(3)} V</tspan>
        <tspan x={6} dy={15}>I = {i?.toFixed(4)} A</tspan>
        <tspan x={6} dy={15}>P = {p?.toFixed(3)} W</tspan>
      </text>
    </g>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function SolarPVPanel({
  ivData = null,
  title = 'PV I-V / P-V Curve',
  showPV = true,
  width = 560,
  height = 340,
  className = '',
}) {
  const [tooltip, setTooltip] = useState(null)

  const innerW = width - MAR.left - MAR.right
  const innerH = height - MAR.top - MAR.bottom

  if (!ivData || !ivData.iv_curve || ivData.iv_curve.length === 0) {
    return (
      <div
        className={className}
        style={{
          width, height,
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
        No PV data
      </div>
    )
  }

  const { iv_curve, isc_a, voc_v, mpp, power_loss_vs_uniform_pct } = ivData

  // Compute domains
  const vs = iv_curve.map((d) => d.v)
  const is_ = iv_curve.map((d) => d.i)
  const ps = iv_curve.map((d) => d.p || d.v * d.i)

  const vMin = Math.min(...vs)
  const vMax = Math.max(...vs)
  const iMin = 0
  const iMax = Math.max(...is_) * 1.05
  const pMin = 0
  const pMax = Math.max(...ps) * 1.1

  const xS = scaleLinear(vMin, vMax, MAR.left, MAR.left + innerW)
  const yI = scaleLinear(iMin, iMax, MAR.top + innerH, MAR.top)
  const yP = scaleLinear(pMin, pMax, MAR.top + innerH, MAR.top)

  const vTicks = niceTicks(vMin, vMax)
  const iTicks = niceTicks(iMin, iMax)
  const pTicks = niceTicks(pMin, pMax)

  const ivPts = polylinePts(iv_curve, (d) => xS(d.v), (d) => yI(d.i))
  const pvPts = showPV ? polylinePts(iv_curve, (d) => xS(d.v), (d) => yP(d.p ?? d.v * d.i)) : ''

  const mppX = mpp ? xS(mpp.v_v) : null
  const mppYi = mpp ? yI(mpp.i_a) : null
  const mppYp = mpp ? yP(mpp.p_w) : null

  return (
    <div className={`solar-pv-panel ${className}`} style={{ display: 'inline-block' }}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`${title}${mpp ? `, MPP ${mpp.p_w.toFixed(1)} W @ ${mpp.v_v.toFixed(2)} V` : ''}`}
        onMouseLeave={() => setTooltip(null)}
      >
        <rect width={width} height={height} fill="#0d0d1a" rx={4} />

        {/* Title */}
        <text x={width / 2} y={20} textAnchor="middle" fill="#e0e0f0" fontSize={13} fontFamily="sans-serif" fontWeight="bold">
          {title}
        </text>

        {/* Grid */}
        {vTicks.map((t) => {
          const x = xS(t)
          return Number.isFinite(x) ? (
            <line key={t} x1={x} x2={x} y1={MAR.top} y2={MAR.top + innerH} stroke="#1e1e2e" strokeWidth={1} />
          ) : null
        })}
        {iTicks.map((t) => {
          const y = yI(t)
          return Number.isFinite(y) ? (
            <line key={t} x1={MAR.left} x2={MAR.left + innerW} y1={y} y2={y} stroke="#1e1e2e" strokeWidth={1} />
          ) : null
        })}

        {/* Left Y axis ticks (current) */}
        {iTicks.map((t) => {
          const y = yI(t)
          return Number.isFinite(y) ? (
            <g key={t}>
              <line x1={MAR.left - 4} x2={MAR.left} y1={y} y2={y} stroke="#555" strokeWidth={1} />
              <text x={MAR.left - 8} y={y + 4} textAnchor="end" fill="#4fc3f7" fontSize={10} fontFamily="monospace">
                {t.toPrecision(3)}
              </text>
            </g>
          ) : null
        })}

        {/* Right Y axis ticks (power) */}
        {showPV && pTicks.map((t) => {
          const y = yP(t)
          return Number.isFinite(y) ? (
            <g key={t}>
              <line x1={MAR.left + innerW} x2={MAR.left + innerW + 4} y1={y} y2={y} stroke="#555" strokeWidth={1} />
              <text x={MAR.left + innerW + 8} y={y + 4} textAnchor="start" fill="#ffd54f" fontSize={10} fontFamily="monospace">
                {t.toPrecision(3)}
              </text>
            </g>
          ) : null
        })}

        {/* X axis ticks */}
        {vTicks.map((t) => {
          const x = xS(t)
          return Number.isFinite(x) ? (
            <text key={t} x={x} y={MAR.top + innerH + 18} textAnchor="middle" fill="#888" fontSize={10} fontFamily="monospace">
              {t.toPrecision(3)}
            </text>
          ) : null
        })}

        {/* Axis labels */}
        <text x={MAR.left + innerW / 2} y={height - 8} textAnchor="middle" fill="#aaa" fontSize={11} fontFamily="sans-serif">
          Voltage (V)
        </text>
        <text
          transform={`rotate(-90) translate(${-(MAR.top + innerH / 2)},${MAR.left - 46})`}
          textAnchor="middle"
          fill="#4fc3f7"
          fontSize={11}
          fontFamily="sans-serif"
        >
          Current (A)
        </text>
        {showPV && (
          <text
            transform={`rotate(90) translate(${MAR.top + innerH / 2},${-(width - MAR.right + 46)})`}
            textAnchor="middle"
            fill="#ffd54f"
            fontSize={11}
            fontFamily="sans-serif"
          >
            Power (W)
          </text>
        )}

        {/* P-V curve */}
        {showPV && <polyline points={pvPts} fill="none" stroke="#ffd54f" strokeWidth={1.5} opacity={0.85} />}

        {/* I-V curve */}
        <polyline points={ivPts} fill="none" stroke="#4fc3f7" strokeWidth={2.5} />

        {/* MPP marker */}
        {mpp && Number.isFinite(mppX) && Number.isFinite(mppYi) && (
          <g>
            {/* Vertical dashed line through MPP */}
            <line x1={mppX} x2={mppX} y1={MAR.top} y2={MAR.top + innerH} stroke="#a5d6a7" strokeWidth={1} strokeDasharray="4 2" opacity={0.7} />
            {/* MPP circle on I-V */}
            <circle cx={mppX} cy={mppYi} r={6} fill="#a5d6a7" stroke="#fff" strokeWidth={1.5} opacity={0.95} />
            {/* MPP circle on P-V */}
            {showPV && Number.isFinite(mppYp) && (
              <circle cx={mppX} cy={mppYp} r={6} fill="#ffd54f" stroke="#fff" strokeWidth={1.5} opacity={0.95} />
            )}
          </g>
        )}

        {/* Interactive hover overlay */}
        <rect
          x={MAR.left}
          y={MAR.top}
          width={innerW}
          height={innerH}
          fill="transparent"
          onMouseMove={(e) => {
            const svgEl = e.currentTarget.closest('svg')
            if (!svgEl) return
            const rect = svgEl.getBoundingClientRect()
            const px = e.clientX - rect.left
            // Find nearest point
            const vHover = vMin + ((px - MAR.left) / innerW) * (vMax - vMin)
            let nearest = iv_curve[0]
            let minDist = Infinity
            for (const d of iv_curve) {
              const dist = Math.abs(d.v - vHover)
              if (dist < minDist) { minDist = dist; nearest = d }
            }
            setTooltip({
              svgX: xS(nearest.v),
              svgY: yI(nearest.i),
              v: nearest.v,
              i: nearest.i,
              p: nearest.p ?? nearest.v * nearest.i,
            })
          }}
        />

        {/* Tooltip */}
        {tooltip && (
          <Tooltip x={tooltip.svgX} y={tooltip.svgY} v={tooltip.v} i={tooltip.i} p={tooltip.p} show />
        )}

        {/* Isc, Voc labels */}
        {isc_a != null && Number.isFinite(yI(isc_a)) && (
          <text x={MAR.left + 6} y={yI(isc_a) - 4} fill="#4fc3f7" fontSize={10} fontFamily="monospace" opacity={0.8}>
            Isc={isc_a.toFixed(2)} A
          </text>
        )}
        {voc_v != null && Number.isFinite(xS(voc_v)) && (
          <text x={xS(voc_v) - 4} y={MAR.top + innerH - 6} textAnchor="end" fill="#4fc3f7" fontSize={10} fontFamily="monospace" opacity={0.8}>
            Voc={voc_v.toFixed(2)} V
          </text>
        )}
      </svg>

      {/* Summary bar */}
      <div style={{
        marginTop: 4,
        padding: '6px 10px',
        background: '#0d0d1a',
        borderRadius: 4,
        fontFamily: 'monospace',
        fontSize: 12,
        color: '#aaa',
        display: 'flex',
        gap: 20,
        flexWrap: 'wrap',
      }}>
        {mpp && (
          <>
            <span>Pmpp: <strong style={{ color: '#ffd54f' }}>{mpp.p_w.toFixed(2)} W</strong></span>
            <span>Vmpp: <strong style={{ color: '#4fc3f7' }}>{mpp.v_v.toFixed(3)} V</strong></span>
            <span>Impp: <strong style={{ color: '#4fc3f7' }}>{mpp.i_a.toFixed(3)} A</strong></span>
          </>
        )}
        {isc_a != null && <span>Isc: <strong style={{ color: '#4fc3f7' }}>{isc_a.toFixed(3)} A</strong></span>}
        {voc_v != null && <span>Voc: <strong style={{ color: '#4fc3f7' }}>{voc_v.toFixed(3)} V</strong></span>}
        {power_loss_vs_uniform_pct != null && (
          <span>
            Shading loss: <strong style={{ color: '#ef5350' }}>
              {power_loss_vs_uniform_pct.toFixed(1)} %
            </strong>
          </span>
        )}
      </div>
    </div>
  )
}
