// MonthlyLoadChart.jsx — SVG bar chart for monthly building energy loads.
//
// Props:
//   data: Array of 12 month objects:
//     { month: string, heating_kWh: number, cooling_kWh: number,
//       lighting_kWh: number, equipment_kWh: number }
//   title: optional string
//   height: optional number (default 220)
//   width: optional number (default 560)
//
// Renders a grouped stacked bar chart per month with a legend.

import { useMemo } from 'react'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const SERIES = [
  { key: 'heating_kWh',   label: 'Heating',   color: '#ef4444' },
  { key: 'cooling_kWh',   label: 'Cooling',   color: '#3b82f6' },
  { key: 'lighting_kWh',  label: 'Lighting',  color: '#f59e0b' },
  { key: 'equipment_kWh', label: 'Equipment', color: '#8b5cf6' },
]

function fmt(n) {
  if (n == null || !Number.isFinite(n)) return '0'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return n.toFixed(0)
}

export default function MonthlyLoadChart({
  data,
  title = 'Monthly Energy Loads',
  width = 560,
  height = 220,
}) {
  const MARGIN = { top: 20, right: 16, bottom: 44, left: 52 }
  const chartW = width - MARGIN.left - MARGIN.right
  const chartH = height - MARGIN.top - MARGIN.bottom

  const months = useMemo(() => {
    if (!Array.isArray(data) || data.length === 0) return MONTHS.map((m) => ({ month: m }))
    // Accept either 12-element or fewer; pad with zeros
    const out = MONTHS.map((m, i) => ({
      month: m,
      heating_kWh:   (data[i]?.heating_kWh   ?? 0),
      cooling_kWh:   (data[i]?.cooling_kWh   ?? 0),
      lighting_kWh:  (data[i]?.lighting_kWh  ?? 0),
      equipment_kWh: (data[i]?.equipment_kWh ?? 0),
    }))
    return out
  }, [data])

  const maxTotal = useMemo(() => {
    const totals = months.map((m) =>
      SERIES.reduce((s, ser) => s + (m[ser.key] ?? 0), 0)
    )
    return Math.max(...totals, 1)
  }, [months])

  const barW = chartW / 12 * 0.7
  const barStep = chartW / 12

  // Y-axis tick count
  const N_TICKS = 5
  const tickInterval = maxTotal / N_TICKS

  const yTicks = Array.from({ length: N_TICKS + 1 }, (_, i) => ({
    value: i * tickInterval,
    y: chartH - (i * tickInterval / maxTotal) * chartH,
  }))

  return (
    <div className="flex flex-col items-start gap-2">
      {title && (
        <div className="text-[11px] uppercase tracking-wider text-ink-500">{title}</div>
      )}
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={title}
        className="overflow-visible"
        style={{ maxWidth: '100%' }}
      >
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          {/* Y-axis grid + ticks */}
          {yTicks.map((t) => (
            <g key={t.value}>
              <line
                x1={0} y1={t.y} x2={chartW} y2={t.y}
                stroke="#334155" strokeWidth={0.5}
              />
              <text
                x={-6} y={t.y}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={9}
                fill="#64748b"
              >
                {fmt(t.value)}
              </text>
            </g>
          ))}
          {/* Y-axis label */}
          <text
            x={-40}
            y={chartH / 2}
            textAnchor="middle"
            fontSize={9}
            fill="#64748b"
            transform={`rotate(-90, -40, ${chartH / 2})`}
          >
            kWh
          </text>

          {/* Bars */}
          {months.map((m, i) => {
            const cx = i * barStep + barStep / 2
            const x0 = cx - barW / 2
            let stackY = chartH
            return (
              <g key={m.month}>
                {SERIES.map((ser) => {
                  const val = m[ser.key] ?? 0
                  const h = (val / maxTotal) * chartH
                  const y = stackY - h
                  stackY -= h
                  return (
                    <rect
                      key={ser.key}
                      x={x0}
                      y={y}
                      width={barW}
                      height={h}
                      fill={ser.color}
                      opacity={0.85}
                    >
                      <title>{`${m.month} ${ser.label}: ${val.toFixed(0)} kWh`}</title>
                    </rect>
                  )
                })}
                {/* Month label */}
                <text
                  x={cx}
                  y={chartH + 12}
                  textAnchor="middle"
                  fontSize={9}
                  fill="#94a3b8"
                >
                  {m.month}
                </text>
              </g>
            )
          })}

          {/* X-axis baseline */}
          <line x1={0} y1={chartH} x2={chartW} y2={chartH} stroke="#334155" strokeWidth={1} />
        </g>

        {/* Legend */}
        <g transform={`translate(${MARGIN.left}, ${height - 10})`}>
          {SERIES.map((ser, i) => (
            <g key={ser.key} transform={`translate(${i * 110}, 0)`}>
              <rect x={0} y={-6} width={8} height={8} fill={ser.color} opacity={0.85} rx={1} />
              <text x={12} y={0} fontSize={9} fill="#94a3b8">{ser.label}</text>
            </g>
          ))}
        </g>
      </svg>
    </div>
  )
}
