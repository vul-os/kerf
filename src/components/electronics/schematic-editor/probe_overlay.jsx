// probe_overlay.jsx — Voltage/current waveform plotter in pure SVG.
//
// Renders simulation waveform results returned by the /run-spice endpoint.
// Each waveform is a {name, kind, x:[...], y:[...]} object from routes_spice.py.
//
// Props:
//   waveforms  — [{name, kind, x, y, xUnit, yUnit}] from backend
//   height     — panel height in px (default 200)
//   probes     — [string] — probe labels to highlight
//   onClose    — () => void

// Palette for up to 8 traces
const TRACE_COLORS = [
  '#38bdf8', // sky-400
  '#fb923c', // orange-400
  '#34d399', // emerald-400
  '#f472b6', // pink-400
  '#a78bfa', // violet-400
  '#facc15', // yellow-400
  '#f87171', // red-400
  '#4ade80', // green-400
]

function formatNum(v) {
  if (Math.abs(v) >= 1e3)  return (v / 1e3).toPrecision(4) + ' k'
  if (Math.abs(v) >= 1)    return v.toPrecision(4)
  if (Math.abs(v) >= 1e-3) return (v * 1e3).toPrecision(3) + ' m'
  if (Math.abs(v) >= 1e-6) return (v * 1e6).toPrecision(3) + ' µ'
  return v.toExponential(2)
}

function WaveformPlot({ waveform, color, svgW, svgH, xMin, xMax, yMin, yMax }) {
  if (!waveform.x?.length || !waveform.y?.length) return null

  const pad = { top: 14, bottom: 18, left: 50, right: 10 }
  const plotW = svgW - pad.left - pad.right
  const plotH = svgH - pad.top - pad.bottom

  const xRange = xMax - xMin || 1
  const yRange = yMax - yMin || 1

  const toSvgX = (v) => pad.left + ((v - xMin) / xRange) * plotW
  const toSvgY = (v) => pad.top + (1 - (v - yMin) / yRange) * plotH

  const pts = waveform.x.map((xv, i) => `${toSvgX(xv).toFixed(1)},${toSvgY(waveform.y[i]).toFixed(1)}`).join(' ')

  return (
    <polyline
      points={pts}
      fill="none"
      stroke={color}
      strokeWidth={1.5}
      strokeLinejoin="round"
    />
  )
}

function Axes({ svgW, svgH, xMin, xMax, yMin, yMax, xLabel, yLabel }) {
  const pad = { top: 14, bottom: 18, left: 50, right: 10 }
  const plotW = svgW - pad.left - pad.right
  const plotH = svgH - pad.top - pad.bottom

  // 4 horizontal grid lines
  const yTicks = 4
  const xTicks = 5

  return (
    <g>
      {/* Axes */}
      <line x1={pad.left} y1={pad.top} x2={pad.left} y2={pad.top + plotH} stroke="#334155" strokeWidth={1} />
      <line x1={pad.left} y1={pad.top + plotH} x2={pad.left + plotW} y2={pad.top + plotH} stroke="#334155" strokeWidth={1} />

      {/* Y grid + labels */}
      {Array.from({ length: yTicks + 1 }).map((_, i) => {
        const t = i / yTicks
        const y = pad.top + (1 - t) * plotH
        const val = yMin + t * (yMax - yMin)
        return (
          <g key={`y${i}`}>
            <line x1={pad.left} y1={y} x2={pad.left + plotW} y2={y} stroke="#1e293b" strokeWidth={1} />
            <text x={pad.left - 4} y={y + 3} textAnchor="end" fontSize={8} fill="#64748b">
              {formatNum(val)}
            </text>
          </g>
        )
      })}

      {/* X grid + labels */}
      {Array.from({ length: xTicks + 1 }).map((_, i) => {
        const t = i / xTicks
        const x = pad.left + t * plotW
        const val = xMin + t * (xMax - xMin)
        return (
          <g key={`x${i}`}>
            <line x1={x} y1={pad.top} x2={x} y2={pad.top + plotH} stroke="#1e293b" strokeWidth={1} />
            <text x={x} y={pad.top + plotH + 10} textAnchor="middle" fontSize={8} fill="#64748b">
              {formatNum(val)}
            </text>
          </g>
        )
      })}
    </g>
  )
}

export default function ProbeOverlay({ waveforms = [], height = 200, onClose }) {
  if (!waveforms.length) return null

  // Compute global x extent
  let xMin = Infinity, xMax = -Infinity
  for (const w of waveforms) {
    for (const v of (w.x ?? [])) {
      if (v < xMin) xMin = v
      if (v > xMax) xMax = v
    }
  }
  if (!isFinite(xMin)) xMin = 0
  if (!isFinite(xMax)) xMax = 1

  // Per-waveform y extents
  const extents = waveforms.map((w) => {
    const ys = w.y ?? []
    return {
      yMin: ys.length ? Math.min(...ys) : 0,
      yMax: ys.length ? Math.max(...ys) : 1,
    }
  })

  // Global y extent for shared scale
  const yMin = Math.min(...extents.map((e) => e.yMin))
  const yMax = Math.max(...extents.map((e) => e.yMax))

  const svgW = 900
  const svgH = height - 28  // subtract legend

  return (
    <div
      className="bg-[#0a1020] border-t border-white/10 flex flex-col"
      style={{ height }}
      data-testid="probe-overlay"
    >
      {/* Header */}
      <div className="flex items-center px-3 py-1 border-b border-white/5 gap-2 flex-shrink-0">
        <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Simulation Results</span>
        <div className="flex gap-3 ml-3 overflow-x-auto">
          {waveforms.map((w, i) => (
            <span key={w.name} className="flex items-center gap-1 text-[10px] whitespace-nowrap">
              <span
                style={{ backgroundColor: TRACE_COLORS[i % TRACE_COLORS.length] }}
                className="inline-block w-4 h-0.5 rounded"
              />
              <span style={{ color: TRACE_COLORS[i % TRACE_COLORS.length] }}>{w.name}</span>
            </span>
          ))}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="ml-auto text-gray-600 hover:text-gray-300 text-xs transition-colors"
            aria-label="Close simulation results"
          >
            ✕
          </button>
        )}
      </div>

      {/* SVG plot */}
      <div className="flex-1 overflow-hidden">
        <svg
          width="100%"
          height="100%"
          viewBox={`0 0 ${svgW} ${svgH}`}
          preserveAspectRatio="none"
          className="block"
        >
          <Axes svgW={svgW} svgH={svgH} xMin={xMin} xMax={xMax} yMin={yMin} yMax={yMax} />
          {waveforms.map((w, i) => (
            <WaveformPlot
              key={w.name}
              waveform={w}
              color={TRACE_COLORS[i % TRACE_COLORS.length]}
              svgW={svgW}
              svgH={svgH}
              xMin={xMin}
              xMax={xMax}
              yMin={yMin}
              yMax={yMax}
            />
          ))}
        </svg>
      </div>
    </div>
  )
}
