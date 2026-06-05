// DaylightingPanel.jsx — CIE daylighting simulation panel.
//
// Computes illuminance (lux) and daylight factor (DF %) on a grid of
// measurement points using CIE S 011/E:2003 standard sky models.
//
// Backend tool: optics_daylighting_simulation
//   - CIE clear sky, overcast sky, intermediate sky
//   - Sun position via Spencer (1971) from lat/lon/date/time
//   - Two-pass simplified radiosity (Cohen & Wallace 1993)
//   - Outputs: lux per point, avg/min/max, uniformity, mean DF %
//
// Props: { projectId: string }

import { useState, useCallback } from 'react'
import { Sun, Play, AlertTriangle, Grid, MapPin, Clock } from 'lucide-react'
import { api } from '../../lib/api.js'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SKY_MODELS = [
  { value: 'cie_clear',        label: 'CIE Clear Sky (sunny)' },
  { value: 'cie_overcast',     label: 'CIE Standard Overcast (Moon-Spencer)' },
  { value: 'cie_intermediate', label: 'CIE Intermediate Sky' },
]

// CIBSE / BS 8206-2 DF targets
const DF_TARGETS = [
  { label: 'Residential living room', min_pct: 1.5 },
  { label: 'Bedroom',                 min_pct: 1.0 },
  { label: 'Kitchen',                 min_pct: 2.0 },
  { label: 'Office / classroom',      min_pct: 2.0 },
  { label: 'Studio / workshop',       min_pct: 4.0 },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt1(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(1)
}

function fmt2(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

function dfClass(pct) {
  if (pct >= 4.0) return 'text-green-600 dark:text-green-400'
  if (pct >= 2.0) return 'text-yellow-600 dark:text-yellow-400'
  return 'text-red-500 dark:text-red-400'
}

function lux2Color(lux, maxLux) {
  if (!maxLux) return '#1e3a5f'
  const t = Math.min(1, lux / maxLux)
  // Blue → yellow → white gradient (false-colour illuminance)
  const r = Math.round(30 + t * 225)
  const g = Math.round(58 + t * 197)
  const b = Math.round(95 + (1 - t) * 160)
  return `rgb(${r},${g},${b})`
}

/**
 * Build a uniform rectangular grid of measurement points.
 * @param {number} xMin @param {number} xMax @param {number} yMin @param {number} yMax
 * @param {number} z @param {number} nx @param {number} ny
 */
function buildGrid(xMin, xMax, yMin, yMax, z, nx, ny) {
  const pts = []
  const dx = nx > 1 ? (xMax - xMin) / (nx - 1) : 0
  const dy = ny > 1 ? (yMax - yMin) / (ny - 1) : 0
  for (let i = 0; i < ny; i++) {
    for (let j = 0; j < nx; j++) {
      pts.push([xMin + j * dx, yMin + i * dy, z])
    }
  }
  return pts
}

// ---------------------------------------------------------------------------
// Illuminance Grid Visualisation
// ---------------------------------------------------------------------------

function IlluminanceGrid({ points, maxLux }) {
  if (!points || !points.length) return null

  // Infer grid dimensions from unique x/y
  const xs = [...new Set(points.map(p => p.point[0]))].sort((a, b) => a - b)
  const ys = [...new Set(points.map(p => p.point[1]))].sort((a, b) => a - b)
  const nx = xs.length
  const ny = ys.length

  if (nx < 2 || ny < 2) return null

  const cellW = Math.min(600 / nx, 48)
  const cellH = Math.min(300 / ny, 48)
  const svgW = cellW * nx
  const svgH = cellH * ny

  // Map point to grid index
  const xIdx = Object.fromEntries(xs.map((x, i) => [x, i]))
  const yIdx = Object.fromEntries(ys.map((y, i) => [y, i]))

  return (
    <div className="mt-4 overflow-auto">
      <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">
        Illuminance grid (lux) — false colour
      </div>
      <svg width={svgW} height={svgH} className="block rounded border border-gray-200 dark:border-gray-700">
        {points.map((p, idx) => {
          const xi = xIdx[p.point[0]]
          const yi = yIdx[p.point[1]]
          const color = lux2Color(p.illuminance_lux, maxLux)
          return (
            <g key={idx}>
              <rect
                x={xi * cellW}
                y={yi * cellH}
                width={cellW - 1}
                height={cellH - 1}
                fill={color}
              />
              {cellW > 24 && (
                <text
                  x={xi * cellW + cellW / 2}
                  y={yi * cellH + cellH / 2 + 4}
                  textAnchor="middle"
                  fontSize={Math.min(9, cellH * 0.4)}
                  fill="white"
                  style={{ userSelect: 'none' }}
                >
                  {Math.round(p.illuminance_lux)}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      <div className="flex items-center gap-2 mt-1 text-xs text-gray-500 dark:text-gray-400">
        <div className="w-4 h-3 rounded" style={{ background: lux2Color(0, maxLux) }} />
        <span>0 lux</span>
        <div className="w-4 h-3 rounded ml-2" style={{ background: lux2Color(maxLux / 2, maxLux) }} />
        <span>{Math.round(maxLux / 2)} lux</span>
        <div className="w-4 h-3 rounded ml-2" style={{ background: lux2Color(maxLux, maxLux) }} />
        <span>{Math.round(maxLux)} lux (max)</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Panel
// ---------------------------------------------------------------------------

export default function DaylightingPanel({ projectId }) {
  const [lat, setLat] = useState(51.5)
  const [lon, setLon] = useState(-0.1)
  const [date, setDate] = useState('2026-06-21')
  const [time, setTime] = useState('12:00')
  const [tz, setTz] = useState(1)
  const [skyModel, setSkyModel] = useState('cie_clear')
  // Grid definition
  const [xMin, setXMin] = useState(0)
  const [xMax, setXMax] = useState(10)
  const [yMin, setYMin] = useState(0)
  const [yMax, setYMax] = useState(8)
  const [workplaneZ, setWorkplaneZ] = useState(0.85)
  const [gridNx, setGridNx] = useState(8)
  const [gridNy, setGridNy] = useState(6)
  // State
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const pts = buildGrid(xMin, xMax, yMin, yMax, workplaneZ, gridNx, gridNy)
      if (pts.length > 1000) {
        setError('Grid too large — reduce Nx × Ny to ≤ 1000 points.')
        return
      }

      const res = await api.post(`/projects/${projectId}/tools/run`, {
        tool: 'optics_daylighting_simulation',
        args: {
          latitude_deg: lat,
          longitude_deg: lon,
          date_iso: date,
          time_local: time,
          timezone_offset_h: tz,
          sky_model: skyModel,
          measurement_points: pts,
        },
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.message || body.reason || `Request failed (${res.status})`)
        return
      }

      const body = await res.json()
      if (body.ok === false) {
        setError(body.reason || body.message || 'Simulation failed')
        return
      }
      setResult(body)
    } catch (err) {
      setError(err.message || 'Network error')
    } finally {
      setLoading(false)
    }
  }, [projectId, lat, lon, date, time, tz, skyModel, xMin, xMax, yMin, yMax, workplaneZ, gridNx, gridNy])

  const dfPct = result?.mean_daylight_factor_pct

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm p-5 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-yellow-100 dark:bg-yellow-900/40">
          <Sun size={18} className="text-yellow-600 dark:text-yellow-400" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Daylighting Simulation</h2>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            CIE S 011 sky models · illuminance grid · daylight factor
          </p>
        </div>
      </div>

      {/* Location + Sky */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
            <MapPin size={10} className="inline mr-1" />Latitude °N
          </label>
          <input
            type="number" step="0.1" value={lat}
            onChange={e => setLat(parseFloat(e.target.value))}
            className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm dark:text-white"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
            Longitude °E
          </label>
          <input
            type="number" step="0.1" value={lon}
            onChange={e => setLon(parseFloat(e.target.value))}
            className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm dark:text-white"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
            <Clock size={10} className="inline mr-1" />Date
          </label>
          <input
            type="date" value={date}
            onChange={e => setDate(e.target.value)}
            className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm dark:text-white"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
            Local Time
          </label>
          <input
            type="time" value={time}
            onChange={e => setTime(e.target.value)}
            className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm dark:text-white"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
            UTC Offset (h)
          </label>
          <input
            type="number" step="0.5" value={tz}
            onChange={e => setTz(parseFloat(e.target.value))}
            className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm dark:text-white"
          />
        </div>
        <div className="col-span-2 sm:col-span-3">
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
            Sky Model (CIE S 011/E:2003)
          </label>
          <select
            value={skyModel}
            onChange={e => setSkyModel(e.target.value)}
            className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2 py-1 text-sm dark:text-white"
          >
            {SKY_MODELS.map(m => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Grid definition */}
      <div className="rounded-lg bg-gray-50 dark:bg-gray-800 p-3">
        <div className="flex items-center gap-2 mb-2 text-xs font-semibold text-gray-600 dark:text-gray-300">
          <Grid size={12} />Measurement Grid (work-plane)
        </div>
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
          {[
            ['X min (m)', xMin, setXMin],
            ['X max (m)', xMax, setXMax],
            ['Y min (m)', yMin, setYMin],
            ['Y max (m)', yMax, setYMax],
            ['Z (m)', workplaneZ, setWorkplaneZ],
          ].map(([label, val, setter]) => (
            <div key={label}>
              <label className="block text-xs text-gray-500 dark:text-gray-400 mb-0.5">{label}</label>
              <input
                type="number" step="0.1" value={val}
                onChange={e => setter(parseFloat(e.target.value))}
                className="w-full rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-2 py-1 text-xs dark:text-white"
              />
            </div>
          ))}
          <div>
            <label className="block text-xs text-gray-500 dark:text-gray-400 mb-0.5">Nx × Ny</label>
            <div className="flex gap-1">
              <input
                type="number" min="2" max="40" value={gridNx}
                onChange={e => setGridNx(parseInt(e.target.value, 10))}
                className="w-1/2 rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-1 py-1 text-xs dark:text-white"
              />
              <input
                type="number" min="2" max="40" value={gridNy}
                onChange={e => setGridNy(parseInt(e.target.value, 10))}
                className="w-1/2 rounded border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 px-1 py-1 text-xs dark:text-white"
              />
            </div>
          </div>
        </div>
        <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
          {gridNx * gridNy} points · max 1000
        </p>
      </div>

      {/* Run */}
      <button
        onClick={run}
        disabled={loading || gridNx * gridNy > 1000}
        className="flex items-center gap-2 rounded-lg bg-yellow-500 hover:bg-yellow-600 disabled:opacity-50 px-4 py-2 text-sm font-semibold text-white transition-colors"
      >
        <Play size={14} />
        {loading ? 'Simulating…' : 'Run Daylighting Simulation'}
      </button>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-3 py-2">
          <AlertTriangle size={14} className="text-red-500 shrink-0" />
          <span className="text-xs text-red-600 dark:text-red-400">{error}</span>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {/* Summary stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'Average Illuminance', value: `${fmt1(result.average_lux)} lux` },
              { label: 'Min Illuminance',     value: `${fmt1(result.min_lux)} lux` },
              { label: 'Max Illuminance',     value: `${fmt1(result.max_lux)} lux` },
              { label: 'Uniformity (Emin/Eavg)', value: fmt2(result.uniformity_ratio) },
            ].map(({ label, value }) => (
              <div key={label} className="rounded-lg bg-gray-50 dark:bg-gray-800 p-3">
                <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
                <div className="text-base font-semibold text-gray-900 dark:text-white mt-0.5">{value}</div>
              </div>
            ))}
          </div>

          {/* Daylight Factor */}
          <div className="rounded-lg bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-700 p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs text-yellow-700 dark:text-yellow-300 font-semibold">
                  Mean Daylight Factor (DF)
                  <span className="ml-1 font-normal text-gray-500 dark:text-gray-400">
                    — ref: 10,000 lux (CIBSE Guide A / BS 8206-2)
                  </span>
                </div>
                <div className={`text-2xl font-bold mt-1 ${dfClass(dfPct)}`}>
                  {fmt2(dfPct)} %
                </div>
              </div>
              <div className="text-right text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
                <div className="font-medium text-gray-600 dark:text-gray-300">BS 8206-2 targets:</div>
                {DF_TARGETS.map(t => (
                  <div key={t.label} className={dfPct >= t.min_pct ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}>
                    {dfPct >= t.min_pct ? '✓' : '✗'} {t.label} (≥ {t.min_pct}%)
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Illuminance grid visualisation */}
          <IlluminanceGrid points={result.points} maxLux={result.max_lux} />

          {/* Reference */}
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-2">
            {result.reference}
          </p>
        </div>
      )}
    </div>
  )
}
